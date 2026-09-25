"""無限中あけREN(2026-09-25・利用者の要望)のテスト。画面は表示せずoffscreenで動かす。"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

from src.education.ren import SIDES, TANES, WELL, RenGame, RenWindow, playable_tanes  # noqa: E402
from src.education.rules import COLS, GARBAGE, ROWS  # noqa: E402
from src.engine.srs_reach import find_path, lock_positions  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _board(game: RenGame) -> frozenset:
    return frozenset((r, c) for r in range(ROWS) for c in range(COLS) if game.state.board[r][c] is not None)


def _clearing_move(game: RenGame):
    """ラインが消える置き方(SRSで届くもの)を1つ探す。HOLDも試す。"""
    state = game.state
    for piece, use_hold in ((state.current, False), (state.hold or state.visible_next()[0], True)):
        if use_hold and state.hold_used:
            continue
        board = _board(game)
        for cells in sorted(lock_positions(board, piece)[0]):
            rows = {r for r, _c in cells}
            if any(all((r, c) in board or (r, c) in cells for c in range(COLS)) for r in rows):
                return piece, cells, use_hold
    return None


def _place(game: RenGame, piece: str, cells, use_hold: bool) -> None:
    state = game.state
    if use_hold:
        state.use_hold()
    ops = {"←": state.move_left, "→": state.move_right, "左回転": state.rotate_ccw, "右回転": state.rotate_cw, "↓": state.soft_drop}
    for step in find_path(state, piece, tuple(cells)):
        if step == "ハードドロップ":
            continue
        name, _, times = step.partition("×")
        for _ in range(int(times or 1)):
            assert ops[name]()
    game.hard_drop()


class TestTanes(unittest.TestCase):
    def test_seeds_are_three_cells_in_the_bottom_row(self) -> None:
        # 【2026-09-25・利用者の指示】初期配列の中央のブロックはすべて1段目
        self.assertEqual(len(TANES), 4)
        self.assertEqual(len(set(TANES)), 4, "同じ形のタネがある")
        for tane in TANES:
            self.assertEqual(len(tane), 3)
            self.assertTrue(all(c in WELL and r == ROWS - 1 for r, c in tane))

    def test_first_move_is_always_possible(self) -> None:
        # 【2026-09-25・利用者の指摘】初手から1回も置けないケースがあった(例: .### で O→S)
        edge_left = TANES.index(frozenset((ROWS - 1, c) for c in (4, 5, 6)))
        self.assertNotIn(edge_left, playable_tanes("O", "S"))
        self.assertIn(edge_left, playable_tanes("I", "O"))
        for seed in range(300):
            game = RenGame(seed=seed)
            self.assertIn(game.tane, playable_tanes(game.state.current, game.state.visible_next()[0]))
            self.assertIsNotNone(_clearing_move(game), f"配列{seed}: 初手でラインを消せない")


class TestRenGame(unittest.TestCase):
    def test_sides_are_always_filled_and_ren_counts(self) -> None:
        game = RenGame(seed=5, tane=3)  # 底に3マス(###.)
        for row in game.state.board:
            self.assertTrue(all(row[c] == GARBAGE for c in SIDES), "左右6列が埋まっていない")
        rens = []
        for _ in range(6):
            move = _clearing_move(game)
            if move is None:
                break
            _place(game, *move)
            if game.ended:
                break
            rens.append(game.ren)
            for row in game.state.board:
                self.assertTrue(all(row[c] == GARBAGE for c in SIDES), "消去後に左右6列が埋め直されていない")
        self.assertGreaterEqual(len(rens), 2)
        self.assertEqual(rens, list(range(len(rens))), "1手ごとにRENが増えていない")
        self.assertEqual(game.best, rens[-1])

    def test_ren_breaks_when_nothing_is_cleared_and_undo_restores(self) -> None:
        game = RenGame(seed=5, tane=0)  # 底に3マス(.###)
        board = _board(game)
        piece = game.state.current
        # 消えない置き方(一番高い位置に置く)
        high = min(lock_positions(board, piece)[0], key=lambda cells: min(r for r, _c in cells))
        rows = {r for r, _c in high}
        self.assertFalse(any(all((r, c) in board or (r, c) in high for c in range(COLS)) for r in rows))
        _place(game, piece, high, False)
        self.assertTrue(game.ended, "消せなかったのにRENが続いている")
        game.hard_drop()  # 終了後は置けない
        self.assertEqual(len(game.state.history), 1)
        self.assertTrue(game.undo())
        self.assertFalse(game.ended)
        self.assertEqual(_board(game), board)

    def test_same_seed_and_tane_reproduce(self) -> None:
        a = RenGame(seed=9)
        b = RenGame(seed=9, tane=a.tane)
        self.assertEqual(a.state.board, b.state.board)
        self.assertEqual(a.state.visible_next(), b.state.visible_next())


class TestRenWindow(unittest.TestCase):
    def test_keys_play_and_shuffle_only_before_start(self) -> None:
        window = RenWindow()
        self.addCleanup(window.close)
        window.game = RenGame(seed=5, tane=3)
        window.board_view.state = window.game.state
        window.refresh()
        self.assertTrue(window.shuffle_btn.isEnabled())
        piece, cells, use_hold = _clearing_move(window.game)
        if use_hold:
            window.perform("hold")
        for step in find_path(window.game.state, piece, tuple(cells)):
            name, _, times = step.partition("×")
            action = {"←": "move_left", "→": "move_right", "左回転": "rotate_ccw", "右回転": "rotate_cw", "↓": "soft_drop", "ハードドロップ": "hard_drop"}[name]
            for _ in range(int(times or 1)):
                window.perform(action)
        self.assertFalse(window.game.ended)
        self.assertFalse(window.shuffle_btn.isEnabled(), "開始後にシャッフルできる")
        self.assertIn("REN", window.ren_label.text())
        event = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_R, QtCore.Qt.KeyboardModifier.NoModifier)
        window.keyPressEvent(event)  # 同じ配列でやり直す
        self.assertFalse(window.game.started)
        window.board_view.grab()

    def test_simulator_is_renamed(self) -> None:
        from src.education.advisor import Advisor
        from src.education.window import PracticeWindow
        from tests.test_education_advisor import FakeEngine

        window = PracticeWindow(seed=0, advisor=Advisor(engine_factory=FakeEngine))
        self.addCleanup(window.close)
        self.assertEqual(window.windowTitle(), "シミュレーター")


class TestRenAnalysis(unittest.TestCase):
    def test_following_the_plan_keeps_the_ren(self) -> None:
        for seed in range(12):
            game = RenGame(seed=seed)
            plan = game.analyze()
            if plan is None:
                continue
            for step in plan.steps:
                _place(game, step.piece, step.cells, step.use_hold and not game.state.hold_used)
                self.assertFalse(game.ended, f"配列{seed}: 解析どおりに置いたのにRENが途切れた")
            self.assertEqual(game.ren, len(plan.steps) - 1)

    def test_plan_uses_only_visible_pieces(self) -> None:
        game = RenGame(seed=3)
        plan = game.analyze()
        visible = game.known_pieces() + ([game.state.hold] if game.state.hold else [])
        self.assertLessEqual(len(plan.steps), plan.visible)
        self.assertEqual(plan.visible, len(visible))
        pieces = sorted(s.piece for s in plan.steps)
        remaining = list(visible)
        for piece in pieces:
            self.assertIn(piece, remaining, "見えていないミノを使った")
            remaining.remove(piece)

    def test_no_plan_after_the_ren_ended(self) -> None:
        game = RenGame(seed=5, tane=0)
        board = _board(game)
        high = min(lock_positions(board, game.state.current)[0], key=lambda cells: min(r for r, _c in cells))
        _place(game, game.state.current, high, False)
        self.assertTrue(game.ended)
        self.assertIsNone(game.analyze())


class TestSeventhPieceFromBag(unittest.TestCase):
    """【2026-09-25・利用者の指摘】7種1巡を踏まえると見えない部分が分かる場合がある。"""

    def test_seventh_piece_is_known_at_the_head_of_a_bag(self) -> None:
        game = next(g for g in map(RenGame, range(50)) if g.analyze())  # 1手目の操作ミノは袋の先頭
        known = game.known_pieces()
        self.assertTrue(game.bag_inferred())
        self.assertEqual(len(known), 7)
        self.assertEqual(known, [game.state.sequence.peek(i) for i in range(7)], "確定した7個目が実際の配列と違う")
        plan = game.analyze()
        self.assertEqual(plan.visible, 7, "確定した7個目を解析に使っていない")

    def test_not_inferred_in_the_middle_of_a_bag(self) -> None:
        for seed in range(20):
            game = RenGame(seed=seed)
            move = _clearing_move(game)
            if move is None:
                continue
            _place(game, *move)
            if game.ended or game.state.sequence_index - 1 == 7:
                continue  # 次の操作ミノがちょうど袋の先頭なら確定してよい
            self.assertFalse(game.bag_inferred())
            self.assertEqual(len(game.known_pieces()), 6)
            return
        self.fail("確かめる局面が作れなかった")

    def test_hold_on_an_empty_hold_shifts_the_known_pieces(self) -> None:
        game = RenGame(seed=7)
        known = game.known_pieces()
        game.state.use_hold()  # 空のHOLDへ: NEXTの先頭が操作ミノになる
        self.assertEqual(game.known_pieces(), known[1:2] + known[2:])


class TestRenAnalysisView(unittest.TestCase):
    def test_switch_shows_and_hides_the_recommendation(self) -> None:
        import tempfile
        from pathlib import Path

        from src.education import keybindings

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        window = RenWindow()
        self.addCleanup(window.close)
        window.view_path = Path(tmp.name) / "view.json"
        window.game = RenGame(seed=0)
        window.board_view.state = window.game.state
        window.analysis_switch.setChecked(True)
        window.refresh()
        self.assertIsNotNone(window.board_view.recommendation)
        self.assertIn("推奨", window.analysis_label.text())
        window.analysis_switch.setChecked(False)
        self.assertIsNone(window.board_view.recommendation)
        self.assertFalse(keybindings.load_view(window.view_path)["ren_analysis"])


if __name__ == "__main__":
    unittest.main()
