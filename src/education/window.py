"""教育モードの練習ウィンドウ(PyQt6)。

画面構成は仕様書14-1の案に沿う(確定ではない):
- 中央に盤面、左にHOLD、右にNEXT5
- 下部に「一手戻す」「同一配列でリセット」「別配列でリセット」
- 上部に現在の状態(操作ミノ・消去行数・キー割り当て)

ゲームの規則と状態はrules.GameStateが持ち、ここは描画と入力だけを担当する。
推奨手の表示(第2段階)はこのウィンドウに重ねる想定で、描画の関数を分けている。
"""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from src.education import gamepad, keybindings
from src.education.advisor import Advisor, Recommendation
from src.education.rules import COLS, HIDDEN_ROWS, ROWS, GameState, piece_cells
from src.vision.piece_colors import PIECE_COLORS

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
        next_box.addSpacing(8)
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
        tools.addWidget(self.pad_btn)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.status)
        layout.addLayout(center)
        layout.addLayout(tools)
        layout.addLayout(repeat_row)
        layout.addLayout(buttons)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

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
        self.advisor = advisor if advisor is not None else Advisor()
        self._last_advisor_status = ""
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
        self.refresh()
        return moved

    def _replace_state(self, state: GameState) -> None:
        self.state = state
        self.board_view.state = state

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
        if rec != self.board_view.recommendation or self.advisor.status != self._last_advisor_status:
            self._last_advisor_status = self.advisor.status
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
        self._pad_tracker.update(actions, now_ms, self.perform, **self.repeat)

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
        self.board_view.recommendation = rec if self.show_rec_check.isChecked() else None
        lines = []
        if rec is not None:
            lines.append(f"<b>推奨: {'ホールドして ' if rec.use_hold else ''}{rec.piece}</b>")
            lines.append(f"<span style='color:gray'>{rec.source}</span>")
            if self.show_steps_check.isChecked():
                if rec.steps is None:
                    lines.append("操作手順: 出現位置から届く手順が見つかりません")
                else:
                    lines.append("操作手順:<br>" + " → ".join(rec.steps))
        elif hasattr(self, "advisor") and self.advisor.status:
            lines.append(self.advisor.status)
        self.rec_label.setText("<br>".join(lines))
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
            f"配列: #{state.sequence.seed}   コントローラー: {'接続中' if self.pad.connected() else 'なし'}\n{keys}\n"
            "(キーボードの割り当ては config/education_keys.json で変更できます)"
        )
        self.undo_btn.setEnabled(bool(state.history))


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
