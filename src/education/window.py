"""教育モードの練習ウィンドウ(PyQt6)。

画面構成は仕様書14-1の案に沿う(確定ではない):
- 中央に盤面、左にHOLD、右にNEXT5
- 下部に「一手戻す」「同一配列でリセット」「別配列でリセット」
- 上部に現在の状態(操作ミノ・消去行数・キー割り当て)

ゲームの規則と状態はrules.GameStateが持ち、ここは描画と入力だけを担当する。
推奨手の表示(第2段階)はこのウィンドウに重ねる想定で、描画の関数を分けている。

【2026-09-24・利用者の要望】盤面エディタ、1〜3巡目のツモ順設定(ドラッグで並べ替え)、
HOLD下の候補欄(ボタン・F2・コントローラーで循環切替、難度◎○△)、スクリーンショット。
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime
from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets

from src.education import gamepad, keybindings
from src.education.advisor import Advisor, Recommendation
from src.education.rules import (
    COLS,
    GARBAGE,
    HIDDEN_ROWS,
    PIECES,
    ROWS,
    GameState,
    piece_cells,
    validate_bags,
)
from src.engine.srs_reach import difficulty_mark
from src.paths import app_root
from src.vision.piece_colors import PIECE_COLORS

SCREENSHOT_DIR = app_root() / "screenshots"
CANDIDATE_WIDTH = 170  # 候補欄の幅(テンプレ名と難度が1行に収まるように)

CELL = 28  # 1マスの描画サイズ(px)
GHOST_ALPHA = 70
# 押しっぱなしで連続入力する操作(方向キー・十字キー)。
REPEATABLE_ACTIONS = frozenset({"move_left", "move_right", "soft_drop"})
PAD_POLL_MS = 16  # コントローラーの読み取りと、押しっぱなしの連続入力の判定の間隔


class RepeatTracker:
    """押しっぱなしの連続入力(独自のキーリピート)。

    押された瞬間に1回、REPEATABLE_ACTIONSだけは delay_ms 後から interval_ms
    間隔で繰り返す(interval_ms=0なら止まるまで一気に動かす)。
    【2026-09-23・利用者の指示】OSのキーリピートは使わない(単押しで2マス動いた)。
    """

    def __init__(self) -> None:
        self.pressed: set[str] = set()
        self.repeat_at: dict[str, float] = {}

    def update(
        self, actions: set[str], now_ms: float, perform, delay_ms: int, interval_ms: int, soft_interval_ms: int = 20
    ) -> None:
        for action in actions - self.pressed:
            perform(action)
            # ソフトドロップは待ち時間なしで、すぐ自分の間隔で降り続ける
            self.repeat_at[action] = now_ms + (soft_interval_ms if action == "soft_drop" else delay_ms)
        for action in actions & self.pressed:
            if action in REPEATABLE_ACTIONS and now_ms >= self.repeat_at.get(action, now_ms):
                if action == "soft_drop":
                    interval_ms = soft_interval_ms
                if interval_ms <= 0:
                    for _ in range(ROWS):
                        if not perform(action):
                            break
                else:
                    perform(action)
                self.repeat_at[action] = now_ms + interval_ms
        self.pressed = set(actions)

    def clear(self) -> None:
        self.pressed.clear()


def _color(piece: str | None, alpha: int = 255) -> QtGui.QColor:
    if piece is None or piece not in PIECE_COLORS:
        return QtGui.QColor(110, 110, 110, alpha)
    rgb = PIECE_COLORS[piece]
    return QtGui.QColor(rgb.r, rgb.g, rgb.b, alpha)


class BoardView(QtWidgets.QWidget):
    """盤面(非表示2行を薄く含む)・操作ミノ・落下位置のゴーストを描く。"""

    def __init__(self, state: GameState, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self.recommendation: Recommendation | None = None
        self.setFixedSize(COLS * CELL + 2, ROWS * CELL + 2)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor(20, 20, 24))
        state = self.state

        def cell_rect(r: int, c: int) -> QtCore.QRect:
            return QtCore.QRect(1 + c * CELL, 1 + r * CELL, CELL - 1, CELL - 1)

        # 固定ブロックと格子
        for r in range(ROWS):
            for c in range(COLS):
                piece = state.board[r][c]
                if piece is not None:
                    painter.fillRect(cell_rect(r, c), _color(piece))
                else:
                    painter.fillRect(cell_rect(r, c), QtGui.QColor(34, 34, 40) if r >= HIDDEN_ROWS else QtGui.QColor(26, 26, 30))
        # 非表示行との境界線
        painter.setPen(QtGui.QPen(QtGui.QColor(200, 200, 200, 120), 1, QtCore.Qt.PenStyle.DashLine))
        y = 1 + HIDDEN_ROWS * CELL
        painter.drawLine(0, y, self.width(), y)
        if state.game_over:
            painter.setPen(QtGui.QColor(255, 80, 80))
            painter.setFont(QtGui.QFont("", 16, QtGui.QFont.Weight.Bold))
            painter.drawText(self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, "積み上がりました\n(一手戻す / リセット)")
            return
        # 落下位置のゴースト(輪郭だけ。推奨配置と区別できるよう塗りつぶさない)
        ghost_row = state.ghost_row()
        painter.setPen(QtGui.QPen(_color(state.current, 200), 2))
        for r, c in piece_cells(state.current, state.orient, ghost_row, state.col):
            painter.fillRect(cell_rect(r, c), _color(state.current, GHOST_ALPHA))
            painter.drawRect(cell_rect(r, c).adjusted(1, 1, -1, -1))
        # 推奨配置: 斜線の模様と白い破線の枠(塗りつぶしのゴーストと色以外でも区別できるように)
        rec = self.recommendation
        if rec is not None:
            painter.setBrush(QtGui.QBrush(_color(rec.piece, 230), QtCore.Qt.BrushStyle.BDiagPattern))
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 230), 2, QtCore.Qt.PenStyle.DashLine))
            for r, c in rec.cells:
                painter.drawRect(cell_rect(r, c).adjusted(2, 2, -2, -2))
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        # 操作ミノ
        for r, c in state.current_cells():
            painter.fillRect(cell_rect(r, c), _color(state.current))
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 200), 1))
            painter.drawRect(cell_rect(r, c))


class PieceView(QtWidgets.QWidget):
    """HOLD・NEXTの1枠にミノを描く。"""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.piece: str | None = None
        self.highlighted = False
        self.setFixedSize(4 * CELL, 3 * CELL)

    def set_piece(self, piece: str | None, highlighted: bool = False) -> None:
        self.piece = piece
        self.highlighted = highlighted
        self.update()

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor(30, 30, 36))
        if self.highlighted:
            # 【2026-09-23・利用者の指示】この手番でホールドした(もう使えない)ことを黄色の枠で示す
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 220, 0), 4))
            painter.drawRect(self.rect().adjusted(2, 2, -2, -2))
        if self.piece is None:
            return
        cells = piece_cells(self.piece, 0, 0, 0)
        min_c = min(c for _r, c in cells)
        max_c = max(c for _r, c in cells)
        min_r = min(r for r, _c in cells)
        max_r = max(r for r, _c in cells)
        offset_x = (4 - (max_c - min_c + 1)) * CELL // 2
        offset_y = (3 - (max_r - min_r + 1)) * CELL // 2
        for r, c in cells:
            rect = QtCore.QRect(offset_x + (c - min_c) * CELL, offset_y + (r - min_r) * CELL, CELL - 1, CELL - 1)
            painter.fillRect(rect, _color(self.piece))


class PracticeWindow(QtWidgets.QWidget):
    """教育モードの練習画面。キー入力をrules.GameStateの操作へ変換する。"""

    def __init__(
        self, seed: int | None = None, parent: QtWidgets.QWidget | None = None, advisor: Advisor | None = None
    ) -> None:
        super().__init__(parent, QtCore.Qt.WindowType.Window)
        self.setWindowTitle("教育モード(練習)")
        self.bindings = keybindings.load_bindings()
        self.state = GameState.new(seed) if seed is not None else GameState.new(0).reset_new_sequence()

        self.board_view = BoardView(self.state)
        self.hold_view = PieceView()
        self.next_views = [PieceView() for _ in range(5)]
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)

        hold_box = QtWidgets.QVBoxLayout()
        hold_box.addWidget(QtWidgets.QLabel("HOLD"))
        hold_box.addWidget(self.hold_view)
        # 【2026-09-24・利用者の要望】HOLDの下に候補欄(成立するテンプレとAI)。
        # 行をクリックで直接選択、「次の候補」ボタン・ホットキー・コントローラーで循環。
        self.candidate_title = QtWidgets.QLabel()
        self.candidate_box = QtWidgets.QVBoxLayout()
        self.candidate_box.setSpacing(2)
        self.candidate_buttons: list[QtWidgets.QPushButton] = []
        self._candidate_sig: tuple | None = None
        self.cycle_btn = QtWidgets.QPushButton("次の候補")
        self.cycle_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.cycle_btn.clicked.connect(lambda _c=False: self.perform("cycle_candidate"))
        self.candidate_scope = QtWidgets.QLabel()
        self.candidate_scope.setWordWrap(True)
        self.candidate_scope.setStyleSheet("color: gray; font-size: 11px;")
        for widget in (self.candidate_title, self.cycle_btn, self.candidate_scope):
            widget.setFixedWidth(CANDIDATE_WIDTH)
        hold_box.addSpacing(6)
        hold_box.addWidget(self.candidate_title)
        hold_box.addLayout(self.candidate_box)
        hold_box.addWidget(self.cycle_btn)
        hold_box.addWidget(self.candidate_scope)
        # 【2026-09-23・利用者の指示】HOLDの下にBtoB・REN・直前に消した役を表示
        self.clear_label = QtWidgets.QLabel()
        self.clear_label.setWordWrap(True)
        self.clear_label.setFixedWidth(4 * CELL)
        self.clear_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignHCenter)
        self.clear_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        hold_box.addWidget(self.clear_label)
        hold_box.addStretch(1)
        next_box = QtWidgets.QVBoxLayout()
        next_box.addWidget(QtWidgets.QLabel("NEXT"))
        for view in self.next_views:
            next_box.addWidget(view)
        # 推奨手の説明(提案元・操作手順)
        self.show_rec_check = QtWidgets.QCheckBox("推奨配置を表示")
        self.show_rec_check.setChecked(True)
        self.show_steps_check = QtWidgets.QCheckBox("操作手順を表示")
        self.show_steps_check.setChecked(True)
        for check in (self.show_rec_check, self.show_steps_check):
            check.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
            check.toggled.connect(lambda _v: self.refresh())
        self.rec_label = QtWidgets.QLabel()
        self.rec_label.setWordWrap(True)
        self.rec_label.setFixedWidth(4 * CELL + 40)
        self.rec_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft)
        # 【2026-09-24・利用者の要望】トグル: 提示(推奨配置・手順・候補欄)の表示/非表示、
        # テンプレ優先/AI優先。ホットキー・コントローラーにも割り当てられる。
        self.hints_btn = QtWidgets.QPushButton()
        self.priority_btn = QtWidgets.QPushButton()
        self.hints_btn.clicked.connect(lambda _c=False: self.perform("toggle_hints"))
        self.priority_btn.clicked.connect(lambda _c=False: self.perform("toggle_priority"))
        for btn in (self.hints_btn, self.priority_btn):
            btn.setCheckable(True)
            btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
            btn.setFixedWidth(4 * CELL + 40)
        next_box.addSpacing(8)
        next_box.addWidget(self.hints_btn)
        next_box.addWidget(self.priority_btn)
        next_box.addWidget(self.show_rec_check)
        next_box.addWidget(self.show_steps_check)
        next_box.addWidget(self.rec_label)
        next_box.addStretch(1)

        center = QtWidgets.QHBoxLayout()
        center.addLayout(hold_box)
        center.addWidget(self.board_view)
        center.addLayout(next_box)

        buttons = QtWidgets.QHBoxLayout()
        self.undo_btn = QtWidgets.QPushButton("一手戻す")
        self.reset_same_btn = QtWidgets.QPushButton("同一配列でリセット")
        self.reset_new_btn = QtWidgets.QPushButton("別配列でリセット")
        for btn, action in (
            (self.undo_btn, "undo"),
            (self.reset_same_btn, "reset_same"),
            (self.reset_new_btn, "reset_new"),
        ):
            btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)  # ボタンにフォーカスが移ってキー操作が効かなくならないように
            btn.clicked.connect(lambda _checked=False, a=action: self.perform(a))
            buttons.addWidget(btn)
        # 同一配列と別配列のリセットは誤操作しにくいよう間を空ける(仕様書14-2)
        buttons.insertStretch(2, 1)

        # おじゃまブロックのせり上げ(1〜5段、穴の位置・直列/バラはランダム)
        tools = QtWidgets.QHBoxLayout()
        self.garbage_spin = QtWidgets.QSpinBox()
        self.garbage_spin.setRange(1, 5)
        self.garbage_spin.setSuffix(" 段")
        self.garbage_spin.setFocusPolicy(QtCore.Qt.FocusPolicy.ClickFocus)
        self.garbage_btn = QtWidgets.QPushButton("おじゃまをせり上げる")
        self.garbage_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.garbage_btn.clicked.connect(self._add_garbage)
        self.pad_btn = QtWidgets.QPushButton("コントローラーの割り当て")
        self.pad_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.pad_btn.clicked.connect(self._open_pad_dialog)
        tools.addWidget(self.garbage_spin)
        tools.addWidget(self.garbage_btn)
        # 盤面エディタ・ツモ順設定・スクリーンショット
        self.edit_board_btn = QtWidgets.QPushButton("盤面編集")
        self.edit_bags_btn = QtWidgets.QPushButton("ツモ順設定")
        self.screenshot_btn = QtWidgets.QPushButton("画像を保存")
        self.edit_board_btn.clicked.connect(self._open_board_editor)
        self.edit_bags_btn.clicked.connect(self._open_bag_editor)
        self.screenshot_btn.clicked.connect(lambda _c=False: self.perform("screenshot"))
        for btn in (self.edit_board_btn, self.edit_bags_btn, self.screenshot_btn):
            btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
            tools.addWidget(btn)
        tools.addStretch(1)
        # 押しっぱなしの連続入力の設定(キーボード・コントローラー共通、保存される)
        repeat = keybindings.load_repeat()
        self.delay_spin = QtWidgets.QSpinBox()
        self.delay_spin.setRange(*keybindings.REPEAT_LIMITS["delay_ms"])
        self.delay_spin.setValue(repeat["delay_ms"])
        self.interval_spin = QtWidgets.QSpinBox()
        self.interval_spin.setRange(*keybindings.REPEAT_LIMITS["interval_ms"])
        self.interval_spin.setValue(repeat["interval_ms"])
        self.soft_spin = QtWidgets.QSpinBox()
        self.soft_spin.setRange(*keybindings.REPEAT_LIMITS["soft_interval_ms"])
        self.soft_spin.setValue(repeat["soft_interval_ms"])
        for spin, tip in (
            (self.delay_spin, "左右移動: 押しっぱなしで連続入力が始まるまでの時間"),
            (self.interval_spin, "左右移動: 連続入力の間隔(0にすると壁まで一気に動く)"),
            (self.soft_spin, "ソフトドロップ: 押しっぱなしで降りる間隔(0にすると床まで一気に落ちる。固定はしない)"),
        ):
            spin.setSuffix(" ms")
            spin.setToolTip(tip)
            spin.setFocusPolicy(QtCore.Qt.FocusPolicy.ClickFocus)
            spin.valueChanged.connect(self._on_repeat_changed)
        repeat_row = QtWidgets.QHBoxLayout()
        repeat_row.addWidget(QtWidgets.QLabel("リピート開始"))
        repeat_row.addWidget(self.delay_spin)
        repeat_row.addWidget(QtWidgets.QLabel("間隔"))
        repeat_row.addWidget(self.interval_spin)
        repeat_row.addWidget(QtWidgets.QLabel("ソフトドロップ"))
        repeat_row.addWidget(self.soft_spin)
        repeat_row.addStretch(1)
        # 【2026-09-24・利用者の要望】キーボードの割り当ても画面で変更できるようにする
        self.keys_btn = QtWidgets.QPushButton("キーボードの割り当て")
        self.keys_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.keys_btn.clicked.connect(self._open_key_dialog)
        tools.addWidget(self.keys_btn)
        tools.addWidget(self.pad_btn)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.status)
        layout.addLayout(center)
        layout.addLayout(tools)
        layout.addLayout(repeat_row)
        layout.addLayout(buttons)
        self.notice = QtWidgets.QLabel()  # 画像の保存結果・編集の適用結果などの通知
        self.notice.setWordWrap(True)
        self.notice.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.notice)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.screenshot_dir = SCREENSHOT_DIR
        # 編集画面などを閉じた時点で押されていたコントローラーの操作。離すまで無視する
        # (押しっぱなしの入力が閉じた直後の盤面へ持ち越されないように)。
        self._pad_blocked: set[str] = set()

        # USBコントローラー: 認識している場合だけ割り当てボタンを出す
        self.pad = gamepad.Gamepad()
        self.pad_bindings = gamepad.load_pad_bindings()
        self.pad_dialog: PadMappingDialog | None = None
        self.repeat = keybindings.load_repeat()
        self._pad_tracker = RepeatTracker()
        self._key_tracker = RepeatTracker()
        self._held_key_actions: set[str] = set()
        self._pad_find_countdown = 0
        self._clock = QtCore.QElapsedTimer()
        self._clock.start()
        # 画面ではパフェ探索を別スレッドで行い、ホールド等の操作で画面を止めない
        self.advisor = advisor if advisor is not None else Advisor(pc_async=True)
        self.view_path = keybindings.VIEW_PATH
        self.view = keybindings.load_view(self.view_path)
        self.advisor.prefer_ai = self.view["prefer_ai"]
        self._last_advisor_status = ""
        self._last_pc_pending = False
        self.pad_timer = QtCore.QTimer(self)
        self.pad_timer.timeout.connect(self._on_tick)
        self.pad_timer.start(PAD_POLL_MS)
        self.refresh()

    # ---- 操作 ----
    def perform(self, action: str) -> bool:
        """操作を1回行う。動けた(状態が変わった)ならTrue。"""
        state = self.state
        moved = True
        if action == "undo":
            moved = state.undo()
        elif action == "reset_same":
            self._replace_state(state.reset_same_sequence())
        elif action == "reset_new":
            self._replace_state(state.reset_new_sequence())
        elif action == "move_left":
            moved = state.move_left()
        elif action == "move_right":
            moved = state.move_right()
        elif action == "rotate_ccw":
            moved = state.rotate_ccw()
        elif action == "rotate_cw":
            moved = state.rotate_cw()
        elif action == "soft_drop":
            moved = state.soft_drop()
        elif action == "hard_drop":
            state.hard_drop()
        elif action == "hold":
            moved = state.use_hold()
        elif action == "cycle_candidate":
            # 推奨表示だけを切り替える(盤面・操作ミノ・HOLD・履歴は進めない)
            moved = self.advisor.cycle()
        elif action == "toggle_hints":
            self.view["show_hints"] = not self.view["show_hints"]
            keybindings.save_view(self.view, self.view_path)
        elif action == "toggle_priority":
            self.view["prefer_ai"] = not self.view["prefer_ai"]
            self.advisor.set_prefer_ai(self.view["prefer_ai"])
            keybindings.save_view(self.view, self.view_path)
        elif action == "screenshot":
            # 押した処理が終わり、描画が更新された後に撮る
            QtCore.QTimer.singleShot(0, self.save_screenshot)
        self.refresh()
        return moved

    def _replace_state(self, state: GameState) -> None:
        self.state = state
        self.board_view.state = state

    # ---- トグル ----
    def _refresh_toggles(self, show: bool) -> None:
        keys = self.bindings
        self.hints_btn.setChecked(show)
        self.hints_btn.setText(f"提示: {'表示' if show else '非表示'} ({keys.get('toggle_hints', '')})")
        prefer_ai = self.view["prefer_ai"]
        self.priority_btn.setChecked(prefer_ai)
        self.priority_btn.setText(f"優先: {'AI' if prefer_ai else 'テンプレ'} ({keys.get('toggle_priority', '')})")
        # 非表示のときは推奨配置・操作手順・候補欄をまとめて隠す(自力で練習する用)
        widgets = [self.show_rec_check, self.show_steps_check, self.rec_label, self.candidate_title,
                   self.cycle_btn, self.candidate_scope, *self.candidate_buttons]
        for widget in widgets:
            widget.setVisible(show)

    # ---- 候補欄 ----
    def _choose_candidate(self, source_id: str) -> None:
        self.advisor.choose(source_id)
        self.refresh()

    def _refresh_candidates(self) -> None:
        candidates = self.advisor.candidates()
        active = self.advisor.active_id
        sig = tuple((c.source_id, c.mark) for c in candidates) + (active, self.advisor.pc_pending)
        if sig != self._candidate_sig:
            self._candidate_sig = sig
            for btn in self.candidate_buttons:
                self.candidate_box.removeWidget(btn)
                btn.deleteLater()
            self.candidate_buttons = []
            for number, cand in enumerate(candidates, 1):
                mark = f"  {cand.mark}" if cand.mark else ""
                btn = QtWidgets.QPushButton(f"{'▶' if cand.source_id == active else '  '} {number} {cand.label}{mark}")
                btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
                btn.setFixedWidth(CANDIDATE_WIDTH)
                btn.setStyleSheet("text-align: left;" + (" font-weight: bold;" if cand.source_id == active else ""))
                btn.clicked.connect(lambda _c=False, s=cand.source_id: self._choose_candidate(s))
                self.candidate_box.addWidget(btn)
                self.candidate_buttons.append(btn)
        key = self.bindings.get("cycle_candidate", "")
        self.candidate_title.setText(f"候補 ({key}で切替)" if key else "候補")
        # 成立候補がAIだけなら切り替える先が無い
        self.cycle_btn.setEnabled(len(candidates) >= 2)
        preferred = self.advisor.preferred_id
        scope = next((c.scope for c in candidates if c.source_id == active), "")
        lines = []
        if scope:
            lines.append(f"難度の範囲: {scope}")
        lines.append("◎=ソフトドロップなし ○=1回 △=2回以上")
        if self.advisor.pc_pending:
            lines.append("パフェ探索中…")
        if preferred is not None and preferred != active:
            lines.append(f"({preferred}が組めない間はAIで提示)")
        self.candidate_scope.setText("<br>".join(lines))

    # ---- スクリーンショット ----
    def save_screenshot(self) -> Path | None:
        """教育モードのウィンドウ全体をPNGで保存する。失敗は画面に通知する。"""
        target = self.screenshot_dir / (
            f"practice_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.png"
        )
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            pixmap = self.grab()
            if pixmap.isNull():
                raise OSError("画面の画像を取得できませんでした")
            if not pixmap.save(str(target), "PNG"):
                raise OSError("画像ファイルを書き込めませんでした")
        except OSError as exc:
            self.notice.setText(f"画像の保存に失敗しました: {exc}")
            return None
        self.notice.setText(f"画像を保存しました: {target}")
        return target

    # ---- 盤面エディタ・ツモ順設定 ----
    def _open_board_editor(self) -> None:
        dialog = BoardEditDialog(self.state.board, self._start_practice_with_board, self)
        dialog.exec()
        self._after_dialog()

    def _open_bag_editor(self) -> None:
        sequence = self.state.sequence
        dialog = BagEditDialog(sequence.bags or sequence.seed_bags(), sequence.seed_bags(), self._start_practice_with_bags, self)
        dialog.exec()
        self._after_dialog()

    def _start_practice_with_board(self, board, keep_queue: bool = False) -> str | None:
        """編集した盤面を開始盤面として新しい練習を始める。不正なら理由を返す(状態は変えない)。

        【2026-09-24・利用者の指示】通常はツモを今の配列(指定したツモ順を含む)の先頭から、
        HOLDは空で始める。keep_queue=Trueなら今の操作ミノ・HOLD・ツモ位置を保ったまま
        盤面だけ変える(同一配列リセットではこの途中局面に戻る)。
        """
        state = self.state
        position = (state.current, state.hold, state.sequence_index) if keep_queue else None
        what = "盤面(ツモ・HOLDはそのまま)" if keep_queue else "盤面"
        return self._start_practice(lambda: GameState.new(state.sequence.seed, state.sequence.bags, board, position), what)

    def _start_practice_with_bags(self, bags) -> str | None:
        """1〜3巡目のツモ順を指定して新しい練習を始める(開始盤面はそのまま)。"""
        if tuple(map(tuple, bags)) == self.state.sequence.seed_bags():
            bags = None  # シードどおりの並びなら指定なしと同じ
        return self._start_practice(lambda: GameState.new(self.state.sequence.seed, bags, self.state.start_board), "ツモ順")

    def _start_practice(self, build, what: str) -> str | None:
        try:
            state = build()
        except ValueError as exc:
            return str(exc)
        self._replace_state(state)
        self.notice.setText(f"編集した{what}で練習を始めました(同一配列リセットでこの開始状態に戻ります)")
        self.refresh()
        return None

    def _after_dialog(self) -> None:
        """ダイアログを閉じた後: 押しっぱなしの入力を持ち越さず、盤面へ操作を戻す。"""
        self._held_key_actions.clear()
        self._key_tracker.clear()
        self._pad_tracker.clear()
        if self.pad.connected():
            self._pad_blocked = gamepad.actions_for_inputs(self.pad_bindings, self.pad.poll())
        self.setFocus()

    def _add_garbage(self) -> None:
        self.state.add_garbage(self.garbage_spin.value())
        self.refresh()
        self.setFocus()

    def _on_repeat_changed(self) -> None:
        self.repeat = {
            "delay_ms": self.delay_spin.value(),
            "interval_ms": self.interval_spin.value(),
            "soft_interval_ms": self.soft_spin.value(),
        }
        keybindings.save_repeat(self.repeat)

    def _key_action(self, event: QtGui.QKeyEvent) -> str | None:
        name = keybindings.key_event_name(event)
        return keybindings.action_for(self.bindings, name) if name else None

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        action = self._key_action(event)
        if action is None:
            super().keyPressEvent(event)
            return
        if event.isAutoRepeat():
            return  # OSのキーリピートは使わない(連続入力は_on_tickで独自に行う)
        self._held_key_actions.add(action)
        self._key_tracker.update(self._held_key_actions, self._clock.elapsed(), self.perform, **self.repeat)

    def keyReleaseEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.isAutoRepeat():
            return
        action = self._key_action(event)
        if action is None:
            super().keyReleaseEvent(event)
            return
        self._held_key_actions.discard(action)
        self._key_tracker.update(self._held_key_actions, self._clock.elapsed(), self.perform, **self.repeat)

    def focusOutEvent(self, event: QtGui.QFocusEvent) -> None:
        self._held_key_actions.clear()  # フォーカスを失ったら押しっぱなしを残さない
        self._key_tracker.clear()
        super().focusOutEvent(event)

    def _update_recommendation(self) -> None:
        rec = self.advisor.update(self.state)
        pending = self.advisor.pc_pending
        if (
            rec != self.board_view.recommendation
            or self.advisor.status != self._last_advisor_status
            or pending != self._last_pc_pending  # パフェ探索が終わった(候補欄に分岐が出る)
        ):
            self._last_advisor_status = self.advisor.status
            self._last_pc_pending = pending
            self.refresh()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.pad_timer.stop()
        self.advisor.close()  # CC2のプロセスを残さない
        super().closeEvent(event)

    def _on_tick(self) -> None:
        self._update_recommendation()
        if self._held_key_actions:
            if not self.isActiveWindow():
                self._held_key_actions.clear()
            self._key_tracker.update(self._held_key_actions, self._clock.elapsed(), self.perform, **self.repeat)
        self._poll_pad()

    # ---- コントローラー ----
    def _poll_pad(self) -> None:
        if not self.pad.connected():
            self._pad_tracker.clear()
            self._pad_find_countdown -= 1
            if self._pad_find_countdown <= 0:  # 抜き差しに備えて約2秒ごとに探し直す
                self._pad_find_countdown = 2000 // PAD_POLL_MS
                if self.pad.find():
                    self.refresh()
            return
        inputs = self.pad.poll()
        if not self.pad.connected():
            self.refresh()  # 切断された: ボタン表示を更新(押下状態は次回クリア)
            return
        if self.pad_dialog is not None and self.pad_dialog.isVisible():
            self.pad_dialog.feed(inputs)
            self._pad_tracker.clear()
            return
        if not self.isActiveWindow():
            self._pad_tracker.clear()  # フォーカスを失ったら押下状態を残さない
            return
        self._handle_pad_actions(gamepad.actions_for_inputs(self.pad_bindings, inputs), self._clock.elapsed())

    def _handle_pad_actions(self, actions: set[str], now_ms: float) -> None:
        """押された瞬間に1回。方向の操作は押しっぱなしで連続入力する。"""
        self._pad_blocked &= actions  # 離したら通常どおり受け付ける
        self._pad_tracker.update(actions - self._pad_blocked, now_ms, self.perform, **self.repeat)

    def _open_key_dialog(self) -> None:
        dialog = KeyMappingDialog(self.bindings, self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.bindings = dialog.bindings
            keybindings.save_bindings(self.bindings)
            self.refresh()
        self._after_dialog()

    def _open_pad_dialog(self) -> None:
        self.pad_dialog = PadMappingDialog(self.pad_bindings, self)
        if self.pad_dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.pad_bindings = self.pad_dialog.bindings
            gamepad.save_pad_bindings(self.pad_bindings)
        self.pad_dialog = None
        self._pad_tracker.clear()
        self.setFocus()

    # ---- 表示 ----
    def refresh(self) -> None:
        state = self.state
        rec = self.advisor.update(state) if hasattr(self, "advisor") else None
        show = not hasattr(self, "view") or self.view["show_hints"]
        self.board_view.recommendation = rec if show and self.show_rec_check.isChecked() else None
        if hasattr(self, "view"):
            self._refresh_toggles(show)
        lines = []
        if rec is not None:
            lines.append(f"<b>推奨: {'ホールドして ' if rec.use_hold else ''}{rec.piece}</b>")
            lines.append(f"<span style='color:gray'>{rec.source}</span>")
            if rec.scope:
                lines.append(f"難度: {difficulty_mark(rec.soft_sections)}({rec.scope})")
            if self.show_steps_check.isChecked():
                if rec.steps is None:
                    lines.append("操作手順: 出現位置から届く手順が見つかりません")
                else:
                    lines.append("操作手順:<br>" + " → ".join(rec.steps))
        elif hasattr(self, "advisor") and self.advisor.status:
            lines.append(self.advisor.status)
        self.rec_label.setText("<br>".join(lines))
        if hasattr(self, "advisor") and show:
            self._refresh_candidates()
        self.hold_view.set_piece(state.hold, highlighted=state.hold_used)
        lines = []
        if state.back_to_back >= 1:
            lines.append(f'<span style="color:#e0a000">BtoB ×{state.back_to_back}</span>')
        if state.last_clear:
            lines.append(state.last_clear)
        if state.combo >= 1:
            lines.append(f"{state.combo} REN")
        self.clear_label.setText("<br>".join(lines))
        self.pad_btn.setVisible(self.pad.connected())
        for view, piece in zip(self.next_views, state.visible_next()):
            view.set_piece(piece)
        self.board_view.update()
        keys = "  ".join(f"{keybindings.ACTIONS[a].split('(')[0]}:{self.bindings[a]}" for a in keybindings.ACTIONS)
        self.status.setText(
            f"操作ミノ: {state.current}   消去: {state.lines_cleared}行   手数: {len(state.history)}   "
            f"配列: #{state.sequence.seed}{'(ツモ順指定)' if state.sequence.bags else ''}"
            f"{'  開始盤面: 編集あり' if state.start_board else ''}   コントローラー: {'接続中' if self.pad.connected() else 'なし'}\n{keys}\n"
            "(割り当ては「キーボードの割り当て」ボタンで変更できます)"
        )
        self.undo_btn.setEnabled(bool(state.history))


class KeyMappingDialog(QtWidgets.QDialog):
    """キーボードの割り当て画面。「設定」を押してからキーを押すと、その操作に割り当てる。

    1つのキーは1つの操作にだけ割り当てる。別の操作で使っているキーを押したら、
    2つの操作の割り当てを入れ替えて通知する(どちらの操作も空にならないように)。
    この画面を開いている間は盤面は動かない。Escで待機を取り消す。
    """

    def __init__(self, bindings: dict[str, str], parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("キーボードの割り当て")
        self.bindings = dict(bindings)
        self.waiting_for: str | None = None
        self.labels: dict[str, QtWidgets.QLabel] = {}
        grid = QtWidgets.QGridLayout()
        for row, (action, text) in enumerate(keybindings.ACTIONS.items()):
            grid.addWidget(QtWidgets.QLabel(text), row, 0)
            label = QtWidgets.QLabel()
            self.labels[action] = label
            grid.addWidget(label, row, 1)
            set_btn = QtWidgets.QPushButton("設定")
            set_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)  # キー入力をこの画面で受け取る
            set_btn.clicked.connect(lambda _c=False, a=action: self.start_waiting(a))
            grid.addWidget(set_btn, row, 2)
        self.message = QtWidgets.QLabel("「設定」を押してから、割り当てたいキーを押してください。")
        defaults_btn = QtWidgets.QPushButton("初期値に戻す")
        defaults_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        defaults_btn.clicked.connect(self._reset_defaults)
        box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        for button in box.buttons():
            button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(grid)
        layout.addWidget(self.message)
        bottom = QtWidgets.QHBoxLayout()
        bottom.addWidget(defaults_btn)
        bottom.addStretch(1)
        bottom.addWidget(box)
        layout.addLayout(bottom)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self._refresh()

    def _refresh(self) -> None:
        for action, label in self.labels.items():
            text = self.bindings.get(action, "") or "(なし)"
            if action == self.waiting_for:
                text = "▶ キーを押してください…"
            label.setText(text)

    def start_waiting(self, action: str) -> None:
        self.waiting_for = action
        self.setFocus()
        self._refresh()

    def _reset_defaults(self) -> None:
        self.bindings = dict(keybindings.DEFAULT_BINDINGS)
        self.waiting_for = None
        self._refresh()

    def assign(self, name: str) -> None:
        """待機中の操作にキー名を割り当てる(重複したら入れ替える)。"""
        action = self.waiting_for
        if action is None:
            return
        note = ""
        other = keybindings.action_for(self.bindings, name)
        if other is not None and other != action:
            self.bindings[other] = self.bindings.get(action, "")
            note = f"(「{keybindings.ACTIONS[other]}」は {self.bindings[other] or 'なし'} に入れ替えました)"
        self.bindings[action] = name
        self.message.setText(f"{name} を「{keybindings.ACTIONS[action]}」に割り当てました{note}")
        self.waiting_for = None
        self._refresh()

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if self.waiting_for is None:
            super().keyPressEvent(event)
            return
        if event.key() == QtCore.Qt.Key.Key_Escape:
            self.waiting_for = None
            self.message.setText("割り当てを取り消しました。")
            self._refresh()
            return
        name = keybindings.key_event_name(event)
        if name is not None:  # 修飾キー単独は待ち続ける
            self.assign(name)


class PadMappingDialog(QtWidgets.QDialog):
    """コントローラーのボタン割り当て画面。

    「設定」を押してからコントローラーのボタン(十字キー・スティックも可)を押すと、
    その操作に割り当てる。1つの入力は1つの操作にだけ割り当てる(重複したら
    前の操作から外して通知する)。この画面を開いている間は盤面は動かない。
    """

    def __init__(self, bindings: dict[str, list[str]], parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("コントローラーの割り当て")
        self.bindings = {action: list(inputs) for action, inputs in bindings.items()}
        self.waiting_for: str | None = None
        self._previous: set[str] = set()
        self.labels: dict[str, QtWidgets.QLabel] = {}
        grid = QtWidgets.QGridLayout()
        for row, (action, text) in enumerate(keybindings.ACTIONS.items()):
            grid.addWidget(QtWidgets.QLabel(text), row, 0)
            label = QtWidgets.QLabel()
            self.labels[action] = label
            grid.addWidget(label, row, 1)
            set_btn = QtWidgets.QPushButton("設定")
            set_btn.clicked.connect(lambda _c=False, a=action: self.start_waiting(a))
            clear_btn = QtWidgets.QPushButton("クリア")
            clear_btn.clicked.connect(lambda _c=False, a=action: self._clear(a))
            grid.addWidget(set_btn, row, 2)
            grid.addWidget(clear_btn, row, 3)
        self.message = QtWidgets.QLabel("「設定」を押してから、割り当てたいボタンを押してください。")
        defaults_btn = QtWidgets.QPushButton("初期値に戻す")
        defaults_btn.clicked.connect(self._reset_defaults)
        box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(grid)
        layout.addWidget(self.message)
        bottom = QtWidgets.QHBoxLayout()
        bottom.addWidget(defaults_btn)
        bottom.addStretch(1)
        bottom.addWidget(box)
        layout.addLayout(bottom)
        self._refresh()

    def _refresh(self) -> None:
        for action, label in self.labels.items():
            names = self.bindings.get(action, [])
            text = ", ".join(names) if names else "(なし)"
            if action == self.waiting_for:
                text = "▶ ボタンを押してください…"
            label.setText(text)

    def start_waiting(self, action: str) -> None:
        self.waiting_for = action
        self._refresh()

    def _clear(self, action: str) -> None:
        self.bindings[action] = []
        self._refresh()

    def _reset_defaults(self) -> None:
        self.bindings = {action: list(inputs) for action, inputs in gamepad.DEFAULT_PAD_BINDINGS.items()}
        self.waiting_for = None
        self._refresh()

    def feed(self, inputs: set[str]) -> None:
        """コントローラーの今の入力。待機中なら新しく押された入力を割り当てる。"""
        pressed = inputs - self._previous
        self._previous = set(inputs)
        if self.waiting_for is None or not pressed:
            return
        name = sorted(pressed)[0]
        note = ""
        for action, names in self.bindings.items():
            if name in names and action != self.waiting_for:
                names.remove(name)
                note = f"(「{keybindings.ACTIONS[action]}」から外しました)"
        self.bindings[self.waiting_for] = [name]
        self.message.setText(f"{name} を「{keybindings.ACTIONS[self.waiting_for]}」に割り当てました{note}")
        self.waiting_for = None
        self._refresh()


# ---- 盤面エディタ ----
def stroke_cells(first: tuple[int, int], last: tuple[int, int]):
    """マウスの前回位置から今回位置までに通ったセル(速く動かしても塗り飛ばさない)。"""
    r0, c0 = first
    r1, c1 = last
    dc, dr = abs(c1 - c0), -abs(r1 - r0)
    sc, sr = (1 if c0 < c1 else -1), (1 if r0 < r1 else -1)
    error = dc + dr
    while True:
        yield r0, c0
        if (r0, c0) == (r1, c1):
            return
        twice = 2 * error
        if twice >= dr:
            error += dr
            c0 += sc
        if twice <= dc:
            error += dc
            r0 += sr


class BoardDraft:
    """編集中の盤面の下書き(練習中の盤面とは別)。1回のドラッグを1回の取り消し単位にする。"""

    def __init__(self, board) -> None:
        self.cells = [list(row) for row in board]
        self.history: list[tuple] = []
        self._before: tuple | None = None

    def frozen(self) -> tuple:
        return tuple(tuple(row) for row in self.cells)

    def begin_stroke(self) -> None:
        self.finish_stroke()
        self._before = self.frozen()

    def paint(self, row: int, col: int, value: str | None) -> None:
        # 押したままなぞったセルは同じ値に塗る(反転方式だと往復で消えるため)
        if 0 <= row < ROWS and 0 <= col < COLS:
            self.cells[row][col] = value

    def finish_stroke(self) -> None:
        if self._before is not None and self._before != self.frozen():
            self.history.append(self._before)
        self._before = None

    def undo(self) -> bool:
        self.finish_stroke()
        if not self.history:
            return False
        self.cells = [list(row) for row in self.history.pop()]
        return True

    def clear(self) -> None:
        self.begin_stroke()
        self.cells = [[None] * COLS for _ in range(ROWS)]
        self.finish_stroke()


class BoardEditor(QtWidgets.QWidget):
    """下書きの盤面を描き、左ドラッグで塗る・右ドラッグで消す。"""

    def __init__(self, draft: BoardDraft, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.draft = draft
        self.brush: str | None = GARBAGE
        self._stroke_value: str | None = None
        self._previous: tuple[int, int] | None = None
        self.setFixedSize(COLS * CELL + 2, ROWS * CELL + 2)

    def _cell_at(self, event: QtGui.QMouseEvent) -> tuple[int, int]:
        pos = event.position()
        return int((pos.y() - 1) // CELL), int((pos.x() - 1) // CELL)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        button = event.button()
        if button not in (QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.MouseButton.RightButton):
            return
        self.draft.begin_stroke()
        self._stroke_value = None if button == QtCore.Qt.MouseButton.RightButton else self.brush
        self._previous = self._cell_at(event)
        self.draft.paint(*self._previous, self._stroke_value)
        self.update()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._previous is None:
            return
        current = self._cell_at(event)
        for row, col in stroke_cells(self._previous, current):
            self.draft.paint(row, col, self._stroke_value)
        self._previous = current
        self.update()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._previous is None:
            return
        self.mouseMoveEvent(event)
        self.draft.finish_stroke()
        self._previous = None

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor(20, 20, 24))
        for r, line in enumerate(self.draft.cells):
            for c, value in enumerate(line):
                rect = QtCore.QRect(1 + c * CELL, 1 + r * CELL, CELL - 1, CELL - 1)
                if value is not None:
                    painter.fillRect(rect, _color(value))
                else:
                    # 上端の非表示2行はブロックを置けない(練習開始時に拒否する)ので色を変える
                    painter.fillRect(rect, QtGui.QColor(60, 34, 34) if r < HIDDEN_ROWS else QtGui.QColor(34, 34, 40))
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 200, 60), 2))
        y = 1 + HIDDEN_ROWS * CELL
        painter.drawLine(0, y, self.width(), y)


class BoardEditDialog(QtWidgets.QDialog):
    """盤面エディタ。「この盤面から練習」で新しい練習を始める(キャンセルなら何も変えない)。

    apply(board, keep_queue)は開始に失敗したら理由の文字列を返す。その場合は画面を閉じずに理由を出す。
    """

    def __init__(self, board, apply, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("盤面編集")
        self.apply = apply
        self.draft = BoardDraft(board)
        self.editor = BoardEditor(self.draft)
        palette = QtWidgets.QVBoxLayout()
        palette.addWidget(QtWidgets.QLabel("塗る色(右ドラッグで消す)"))
        self.brush_group = QtWidgets.QButtonGroup(self)
        for value, text in [(GARBAGE, "おじゃま"), *[(p, p) for p in PIECES], (None, "消しゴム")]:
            radio = QtWidgets.QRadioButton(text)
            if value is not None and value != GARBAGE:
                radio.setStyleSheet(f"color: {_color(value).name()}; font-weight: bold;")
            radio.toggled.connect(lambda on, v=value: on and setattr(self.editor, "brush", v))
            self.brush_group.addButton(radio)
            palette.addWidget(radio)
            if value == GARBAGE:
                radio.setChecked(True)
        undo_btn = QtWidgets.QPushButton("1つ戻す")
        undo_btn.clicked.connect(self._undo)
        clear_btn = QtWidgets.QPushButton("全消去")
        clear_btn.clicked.connect(self._clear)
        palette.addSpacing(8)
        palette.addWidget(undo_btn)
        palette.addWidget(clear_btn)
        palette.addStretch(1)
        self.message = QtWidgets.QLabel(
            "左ドラッグで塗る・右ドラッグで消す。赤い上端2行には置けません。\n"
            "「この盤面から練習」はツモの先頭(HOLD空)から、\n"
            "「盤面だけ変更」は今の操作ミノ・HOLD・NEXTのまま続けます。"
        )
        self.message.setWordWrap(True)
        box = QtWidgets.QDialogButtonBox()
        start_btn = box.addButton("この盤面から練習", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        # 【2026-09-24・利用者の要望】ツモ状況を保ったまま盤面だけ編集する
        keep_btn = box.addButton("盤面だけ変更(ツモ・HOLDはそのまま)", QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
        keep_btn.clicked.connect(lambda: self._apply(keep_queue=True))
        box.addButton("キャンセル", QtWidgets.QDialogButtonBox.ButtonRole.RejectRole)
        start_btn.setDefault(True)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(self.editor)
        top.addLayout(palette)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.message)
        layout.addWidget(box)

    def _undo(self) -> None:
        self.draft.undo()
        self.editor.update()

    def _clear(self) -> None:
        self.draft.clear()
        self.editor.update()

    def accept(self) -> None:
        self._apply(keep_queue=False)

    def _apply(self, keep_queue: bool) -> None:
        self.draft.finish_stroke()
        error = self.apply(self.draft.frozen(), keep_queue)
        if error:
            self.message.setText(f"<span style='color:#ff6060'>開始できません: {error}</span>")
            return
        super().accept()


# ---- 1〜3巡目のツモ順設定 ----
def move_in_bag(bag, source: int, destination: int) -> tuple[str, ...]:
    """巡の中の挿入移動(交換ではない): source番目をdestination番目へ移し、間を詰める。"""
    if not (0 <= source < len(bag) and 0 <= destination < len(bag)):
        raise ValueError("巡の外へは移動できません")
    result = list(bag)
    result.insert(destination, result.pop(source))
    return tuple(result)


class BagRow(QtWidgets.QListWidget):
    """1巡分(7枚)のカード。同じ行の中だけドラッグで並べ替える(別の巡へは移せない)。"""

    def __init__(self, pieces, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFlow(QtWidgets.QListView.Flow.LeftToRight)
        self.setWrapping(False)
        self.setSpacing(3)
        self.setFixedHeight(66)
        self.setMinimumWidth(7 * 58 + 12)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(QtCore.Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(True)
        self.set_pieces(pieces)

    def set_pieces(self, pieces) -> None:
        self.clear()
        font = QtGui.QFont()
        font.setBold(True)
        font.setPointSize(14)
        for piece in pieces:
            item = QtWidgets.QListWidgetItem(piece)
            item.setSizeHint(QtCore.QSize(52, 52))
            item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            item.setBackground(_color(piece))
            item.setForeground(QtGui.QColor(20, 20, 20))
            item.setFont(font)
            self.addItem(item)

    def pieces(self) -> tuple[str, ...]:
        return tuple(self.item(i).text() for i in range(self.count()))

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        if event.source() is not self:
            event.ignore()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent) -> None:
        if event.source() is not self:
            event.ignore()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        if event.source() is not self:
            event.ignore()
            return
        super().dropEvent(event)


class BagEditDialog(QtWidgets.QDialog):
    """1〜3巡目のツモ順(横7枚×3段)。各巡は7種類を1個ずつ、行の中でドラッグして並べ替える。

    4巡目以降は同じシードの配列のまま。apply(bags)は失敗したら理由の文字列を返す。
    """

    def __init__(self, bags, seed_bags, apply, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ツモ順設定(1〜3巡目)")
        self.apply = apply
        self.seed_bags = seed_bags
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("カードをドラッグして、各巡の中で順番を入れ替えます(左が先に出ます)。"))
        self.rows: list[BagRow] = []
        for number, bag in enumerate(bags, 1):
            layout.addWidget(QtWidgets.QLabel(f"{number}巡目({number * 7 - 6}〜{number * 7}個目)"))
            row = BagRow(bag)
            self.rows.append(row)
            layout.addWidget(row)
        tools = QtWidgets.QHBoxLayout()
        seed_btn = QtWidgets.QPushButton("元の並びに戻す")
        seed_btn.clicked.connect(lambda: self._set(self.seed_bags))
        shuffle_btn = QtWidgets.QPushButton("ランダムに並べる")
        shuffle_btn.clicked.connect(lambda: self._set([random.sample(PIECES, len(PIECES)) for _ in self.rows]))
        tools.addWidget(seed_btn)
        tools.addWidget(shuffle_btn)
        tools.addStretch(1)
        layout.addLayout(tools)
        self.message = QtWidgets.QLabel("適用すると、このツモ順で最初から練習を始めます(開始盤面はそのまま)。")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        box = QtWidgets.QDialogButtonBox()
        box.addButton("このツモ順で練習", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        box.addButton("キャンセル", QtWidgets.QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def _set(self, bags) -> None:
        for row, bag in zip(self.rows, bags):
            row.set_pieces(bag)

    def value(self) -> tuple[tuple[str, ...], ...]:
        return validate_bags(row.pieces() for row in self.rows)

    def accept(self) -> None:
        try:
            error = self.apply(self.value())
        except ValueError as exc:
            error = str(exc)
        if error:
            self.message.setText(f"<span style='color:#ff6060'>開始できません: {error}</span>")
            return
        super().accept()
