"""無限中あけREN(シミュレーターとは別のモード)。

【2026-09-25・利用者の要望】左右6列(左3列・右3列)が常に敷き詰められた盤面で、中央4列だけを
使って4列RENを練習する。左右のブロックは灰色。参考: テトリス堂「無限4列RENゲーム」
(https://shiwehi.com/tetris/game/i4lr.php)。
- 開始時は中央4列の最下段に「タネ」(3マス、空きが1マス)がある(利用者の指示で1段目だけ。4通り)。
  1手目・2手目のミノで初手から消せるタネだけを選ぶ。
- 置いた手でラインが消えなければRENが途切れて終了。どこまでRENを伸ばせるかに挑戦する。
  (【2026-09-25・利用者の指示】参考ページのTAモードは不要)
- 開始前(1手目を置く前)だけ「シャッフル」でミノ順とタネを変えられる。
- AI解析: 見えているミノ(操作ミノ・HOLD・NEXT5)でRENを続けられる手を探して示す(ren_search)。
  操作ミノが袋の先頭の手番は、7種1巡から確定する7個目も使う。
- 操作・回転(通常SRS)・キー割り当て・コントローラーはシミュレーターと共通。
"""

from __future__ import annotations

import random

from PyQt6 import QtCore, QtGui, QtWidgets

from src.education import gamepad, keybindings
from src.education.ren_search import RenPlan, find_ren_plan
from src.education.rules import COLS, GARBAGE, NEXT_VISIBLE, ROWS, GameState, PieceSequence
from src.engine.openers import known_sequence
from src.engine.srs_reach import find_path_min_soft, lock_positions

WELL = range(3, 7)  # 中央4列(左から4〜7列目)
SIDES = tuple(c for c in range(COLS) if c not in WELL)

# タネ(中央4列の3マス)。【2026-09-25・利用者の指示】初期配列の中央のブロックはすべて1段目(最下段)。
# 中央4列を左から見て'#'がブロック(参考ページのタネのうち最下段に3マス並ぶ4通り)。
_TANE_ROWS = (".###", "#.##", "##.#", "###.")
TANES: tuple[frozenset[tuple[int, int]], ...] = tuple(
    frozenset((ROWS - 1, WELL.start + j) for j, ch in enumerate(line) if ch == "#") for line in _TANE_ROWS
)


def _can_clear(board: frozenset, piece: str) -> bool:
    """pieceをSRSで届く位置に置いてラインを消せるか。"""
    for cells in lock_positions(board, piece)[0]:
        if any(all((r, c) in board or (r, c) in cells for c in range(COLS)) for r in {r for r, _c in cells}):
            return True
    return False


def playable_tanes(first: str, second: str) -> list[int]:
    """1手目・2手目のミノで初手からラインを消せる(ホールドも使って)タネの番号。

    【2026-09-25・利用者の指摘】初手から1回も置けないケースがあった。最下段のタネでも、空きが端の
    ときはOとS(またはZ)が続くと消せない(例: .### で O→S)。このタネは選ばない。
    """
    result = []
    for i, tane in enumerate(TANES):
        board = frozenset(tane) | frozenset((r, c) for r in range(ROWS) for c in SIDES)
        if _can_clear(board, first) or _can_clear(board, second):
            result.append(i)
    return result


class RenGame:
    """無限中あけRENの状態。ミノの操作はGameState(通常SRS・HOLD・NEXT5)をそのまま使う。"""

    def __init__(self, seed: int | None = None, tane: int | None = None) -> None:
        rng = random.SystemRandom()
        self.seed = rng.randrange(1 << 31) if seed is None else seed
        sequence = PieceSequence(self.seed)
        if tane is None:
            # 初手から置けるタネだけから選ぶ(同じシードなら同じタネ)
            tane = random.Random(self.seed).choice(playable_tanes(sequence.peek(0), sequence.peek(1)))
        self.tane = tane
        self.state = GameState(sequence=sequence)
        self.state.board = [[None] * COLS for _ in range(ROWS)]
        for r, c in TANES[self.tane]:
            self.state.board[r][c] = GARBAGE
        self._fill_sides()
        self.state._begin_turn(self.state._take_next())
        self.best = 0
        self.ended = False  # RENが途切れた(または積み上がった)

    @property
    def ren(self) -> int:
        """今のREN数(1回目の消去は0REN、2回続けて1REN)。"""
        return max(self.state.combo, 0)

    @property
    def started(self) -> bool:
        return bool(self.state.history)

    def _fill_sides(self) -> None:
        """左右6列はどの行も常に埋める(消去で上から入ってきた行も埋め直す)。"""
        for row in self.state.board:
            for c in SIDES:
                row[c] = GARBAGE
        if self.state.turn_start is not None:
            self.state.turn_start = self.state._snapshot()

    def hard_drop(self) -> None:
        if self.ended:
            return
        self.state.hard_drop()
        self._fill_sides()
        if self.state.combo < 0 or self.state.game_over:
            self.ended = True  # 消せなかった: RENが途切れた
            return
        self.best = max(self.best, self.ren)

    def undo(self) -> bool:
        """一手戻す(練習用)。途切れた手も取り消せる。"""
        if not self.state.undo():
            return False
        self._fill_sides()
        self.ended = False
        return True

    def analyze(self) -> RenPlan | None:
        """見えているミノでRENが最も長く続く手順(AI解析)。続けられる手が無ければNone。"""
        if self.ended:
            return None
        state = self.state
        board = frozenset((r, c) for r in range(ROWS) for c in range(COLS) if state.board[r][c] is not None)
        return find_ren_plan(board, self.known_pieces(), state.hold, not state.hold_used, WELL)

    def known_pieces(self) -> list[str]:
        """今の操作ミノから、分かっているミノ順(操作ミノ+NEXT5、袋の区切りから確定する7個目)。

        【2026-09-25・利用者の指摘】7種1巡を踏まえると見えない部分が分かる場合がある。手番の開始時点
        (HOLD前)で操作ミノが袋の先頭なら、操作ミノとNEXT5で袋の6個が見えているので、残りの1種類が
        7個目に確定する(シミュレーターと同じ known_sequence)。この手番でHOLD済みなら、今の操作ミノ
        から数え直す(HOLDが空だった場合は1個先まで配られている)。
        """
        state = self.state
        sequence = self._turn_sequence()
        if state.hold_used:
            rest = sequence[2:] if state.turn_start.hold is None else sequence[1:]
            sequence = [state.current, *rest]
        return sequence

    def _turn_sequence(self) -> list[str]:
        """手番の開始時点(HOLD前)の操作ミノ+NEXT5(+確定した7個目)。"""
        snap = self.state.turn_start
        nexts = tuple(self.state.sequence.peek(snap.sequence_index + i) for i in range(NEXT_VISIBLE))
        return known_sequence(snap.current, nexts, None, snap.sequence_index - 1) or [snap.current, *nexts]

    def bag_inferred(self) -> bool:
        """この手番で、7種1巡から見えない7個目が確定しているか。"""
        return len(self._turn_sequence()) > 1 + NEXT_VISIBLE


class RenWindow(QtWidgets.QWidget):
    """無限中あけRENの画面。盤面の描画・キー/コントローラー入力はシミュレーターと共通の部品を使う。"""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent, QtCore.Qt.WindowType.Window)
        from src.education.window import CELL, PAD_POLL_MS, BoardView, PieceView, RepeatTracker, ToggleSwitch

        self.setWindowTitle("無限中あけREN")
        self.game = RenGame()
        self.bindings = keybindings.load_bindings()
        self.repeat = keybindings.load_repeat()

        self.board_view = BoardView(self.game.state)
        self.hold_view = PieceView()
        self.next_views = [PieceView() for _ in range(5)]
        self.ren_label = QtWidgets.QLabel()
        self.ren_label.setStyleSheet("font-size: 22px; font-weight: bold;")
        self.ren_label.setFixedWidth(4 * CELL + 20)
        self.info_label = QtWidgets.QLabel()
        self.info_label.setWordWrap(True)
        self.info_label.setFixedWidth(4 * CELL + 20)
        # AI解析(見えているミノでRENを続けられる手)。表示/非表示は次回も保持する
        self.view_path = keybindings.VIEW_PATH
        self.view = keybindings.load_view(self.view_path)
        self.analysis_switch = ToggleSwitch("AI解析", "非表示", "表示")
        self.analysis_switch.setChecked(self.view["ren_analysis"])
        self.analysis_switch.toggled.connect(self._on_analysis_toggled)
        self.analysis_label = QtWidgets.QLabel()
        self.analysis_label.setWordWrap(True)
        self.analysis_label.setFixedWidth(4 * CELL + 40)
        self.analysis_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft)
        self._plan_key: tuple | None = None
        self._plan: RenPlan | None = None

        left = QtWidgets.QVBoxLayout()
        left.addWidget(QtWidgets.QLabel("HOLD"))
        left.addWidget(self.hold_view)
        left.addSpacing(10)
        left.addWidget(self.ren_label)
        left.addWidget(self.info_label)
        left.addStretch(1)
        right = QtWidgets.QVBoxLayout()
        right.addWidget(QtWidgets.QLabel("NEXT"))
        for view in self.next_views:
            right.addWidget(view)
        right.addSpacing(8)
        right.addWidget(self.analysis_switch)
        right.addWidget(self.analysis_label)
        right.addStretch(1)
        center = QtWidgets.QHBoxLayout()
        center.addLayout(left)
        center.addWidget(self.board_view)
        center.addLayout(right)

        buttons = QtWidgets.QHBoxLayout()
        self.shuffle_btn = QtWidgets.QPushButton("シャッフル(ミノ順・タネを変える)")
        self.retry_btn = QtWidgets.QPushButton("同じ配列でやり直す")
        self.new_btn = QtWidgets.QPushButton("新しい配列で始める")
        self.undo_btn = QtWidgets.QPushButton("一手戻す")
        self.shuffle_btn.clicked.connect(lambda: self._restart(same=False))
        self.retry_btn.clicked.connect(lambda: self._restart(same=True))
        self.new_btn.clicked.connect(lambda: self._restart(same=False))
        self.undo_btn.clicked.connect(lambda: self.perform("undo"))
        for btn in (self.shuffle_btn, self.undo_btn, self.retry_btn, self.new_btn):
            btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)  # 盤面のキー操作を奪わない
            buttons.addWidget(btn)
        buttons.insertStretch(2, 1)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(center)
        layout.addLayout(buttons)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

        # キー・コントローラー(押しっぱなしの連続入力はシミュレーターと同じ)
        self.pad = gamepad.Gamepad()
        self.pad_bindings = gamepad.load_pad_bindings()
        self._key_tracker = RepeatTracker()
        self._pad_tracker = RepeatTracker()
        self._held_key_actions: set[str] = set()
        self._clock = QtCore.QElapsedTimer()
        self._clock.start()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._on_tick)
        self.timer.start(PAD_POLL_MS)
        self.refresh()

    # ---- 操作 ----
    def perform(self, action: str) -> bool:
        game = self.game
        state = game.state
        moved = True
        if action == "undo":
            moved = game.undo()
        elif action == "reset_same":
            self._restart(same=True)
        elif action == "reset_new":
            self._restart(same=False)
        elif game.ended:
            moved = False  # 終了後はやり直し・一手戻すだけ
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
        elif action == "hold":
            moved = state.use_hold()
        elif action == "hard_drop":
            game.hard_drop()
        else:
            moved = False
        self.refresh()
        return moved

    def _restart(self, same: bool) -> None:
        self.game = RenGame(self.game.seed, self.game.tane) if same else RenGame()
        self.board_view.state = self.game.state
        self._plan_key = None
        self._key_tracker.clear()
        self._pad_tracker.clear()
        self.refresh()
        self.setFocus()

    # ---- 入力 ----
    def _key_action(self, event: QtGui.QKeyEvent) -> str | None:
        name = keybindings.key_event_name(event)
        return keybindings.action_for(self.bindings, name) if name else None

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        action = self._key_action(event)
        if action is None:
            super().keyPressEvent(event)
            return
        if event.isAutoRepeat():
            return
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
        self._held_key_actions.clear()
        self._key_tracker.clear()
        super().focusOutEvent(event)

    def _on_tick(self) -> None:
        now = self._clock.elapsed()
        if self._held_key_actions:
            if not self.isActiveWindow():
                self._held_key_actions.clear()
            self._key_tracker.update(self._held_key_actions, now, self.perform, **self.repeat)
        if self.pad.connected() and self.isActiveWindow():
            actions = gamepad.actions_for_inputs(self.pad_bindings, self.pad.poll())
            self._pad_tracker.update(actions, now, self.perform, **self.repeat)
        else:
            self._pad_tracker.clear()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.timer.stop()
        super().closeEvent(event)

    # ---- AI解析 ----
    def _on_analysis_toggled(self, on: bool) -> None:
        self.view["ren_analysis"] = on
        keybindings.save_view(self.view, self.view_path)
        self.refresh()
        self.setFocus()

    def plan(self) -> RenPlan | None:
        """今の手番の解析結果(手番が変わったときだけ計算し直す)。"""
        state = self.game.state
        key = (id(self.game), len(state.history), state.hold_used, state.current, self.game.ended)
        if key != self._plan_key:
            self._plan_key = key
            self._plan = self.game.analyze()
        return self._plan

    def _refresh_analysis(self) -> None:
        on = self.analysis_switch.isChecked()
        self.analysis_label.setVisible(on)
        plan = self.plan() if on and not self.game.ended else None
        self.board_view.recommendation = plan.steps[0] if plan else None
        if not on or self.game.ended:
            self.analysis_label.setText("")
            return
        if plan is None:
            self.analysis_label.setText(
                "<span style='color:#ff6060'>見えているミノでは、RENを続けられる置き方がありません</span>"
            )
            return
        first = plan.steps[0]
        state = self.game.state
        use_hold = first.use_hold and not state.hold_used
        path = find_path_min_soft(state, first.piece, first.cells)
        order = " → ".join(("(H)" if s.use_hold else "") + s.piece for s in plan.steps)
        lines = [f"<b>推奨: {'ホールドして ' if use_hold else ''}{first.piece}</b>"]
        # 7種1巡から7個目が確定している手番は、そのことも示す
        known = f"分かっている{plan.visible}個(7種1巡から1個確定)" if self.game.bag_inferred() else f"見えている{plan.visible}個"
        if plan.complete:
            lines.append(f"<span style='color:#4caf50'>{known}すべてでRENが続きます</span>")
        else:
            lines.append(f"{known}のうち {len(plan.steps)}手先までRENが続きます")
        lines.append(f"<span style='color:gray'>順番: {order}</span>")
        if path is not None:
            lines.append("操作手順:<br>" + " → ".join((("ホールド",) if use_hold else ()) + path[0]))
        self.analysis_label.setText("<br>".join(lines))

    # ---- 表示 ----
    def _refresh_info(self) -> None:
        game = self.game
        self.ren_label.setText(f"{game.ren} REN")
        lines = [f"最高: {game.best} REN"]
        if game.ended:
            lines.append("<b style='color:#ff6060'>RENが途切れました</b><br>(一手戻す / やり直す)")
        elif not game.started:
            lines.append("中央4列の底のタネから、毎手ラインを消してRENを続けます。")
        self.info_label.setText("<br>".join(lines))

    def refresh(self) -> None:
        state = self.game.state
        self.hold_view.set_piece(state.hold, highlighted=state.hold_used)
        for view, piece in zip(self.next_views, state.visible_next()):
            view.set_piece(piece)
        self.shuffle_btn.setEnabled(not self.game.started)  # 開始前だけ
        self.undo_btn.setEnabled(bool(state.history))
        self._refresh_info()
        self._refresh_analysis()
        self.board_view.update()
