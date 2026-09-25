"""教育モードの6-3積み(2026-09-24・利用者の要望)のテスト。

左6列+右3列を積み、左から7列目(列番号6)をテトリス専用の井戸にする。候補欄の1つとして選ぶ。
"""

from __future__ import annotations

import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets  # noqa: E402

from src.education.advisor import SIX_THREE_ID, Advisor  # noqa: E402
from src.education.rules import COLS, ROWS, GameState  # noqa: E402
from src.education.six_three import WELL_COL, best_move, evaluate  # noqa: E402
from src.education.window import PracticeWindow  # noqa: E402
from src.engine.srs_reach import lock_positions  # noqa: E402
from tests.test_education_advisor import FakeEngine  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _ready_board(rows: int = 4) -> frozenset:
    """井戸(列6)以外が下からrows段埋まった盤面(22行座標)。"""
    return frozenset((r, c) for r in range(ROWS - rows, ROWS) for c in range(COLS) if c != WELL_COL)


class TestSixThreeMove(unittest.TestCase):
    def test_i_goes_into_the_well_for_a_tetris(self) -> None:
        move = best_move(_ready_board(), "I", None, list("OTSZJ"))
        self.assertEqual(move.piece, "I")
        self.assertEqual({c for _r, c in move.cells}, {WELL_COL}, "テトリスの準備ができているのに井戸へ入れない")

    def test_other_pieces_keep_the_well_open(self) -> None:
        for piece in "OTSZJL":
            move = best_move(frozenset(), piece, None, list("IOTSZ"), can_hold=False)
            self.assertNotIn(WELL_COL, {c for _r, c in move.cells}, f"{piece}で井戸を塞いだ")

    def test_moves_are_reachable_by_srs(self) -> None:
        board = _ready_board(2)
        move = best_move(board, "T", "L", list("SZIOJ"))
        self.assertIn(tuple(sorted(move.cells)), lock_positions(board, move.piece)[0])

    def test_evaluation_prefers_open_well_and_no_holes(self) -> None:
        open_well = _ready_board(2)
        blocked = open_well | {(ROWS - 3, WELL_COL)}
        holey = open_well - {(ROWS - 1, 0)} | {(ROWS - 3, 0)}
        self.assertGreater(evaluate(open_well), evaluate(blocked))
        self.assertGreater(evaluate(open_well), evaluate(holey))

    def test_plays_many_pieces_with_tetrises(self) -> None:
        state = GameState.new(1)
        tetrises = 0
        for _ in range(40):
            board = frozenset((r, c) for r in range(ROWS) for c in range(COLS) if state.board[r][c])
            move = best_move(board, state.current, state.hold, list(state.visible_next()), not state.hold_used)
            if move.use_hold:
                state.use_hold()
            for r, c in move.cells:
                state.board[r][c] = move.piece
            full = [r for r in range(ROWS) if all(state.board[r])]
            for r in full:
                del state.board[r]
                state.board.insert(0, [None] * COLS)
            tetrises += len(full) == 4
            state.hold_used = False
            state._begin_turn(state._take_next())
            self.assertFalse(state.game_over)
        self.assertGreaterEqual(tetrises, 2, "40手でテトリスが取れていない")


class TestSixThreeCandidate(unittest.TestCase):
    def test_candidate_is_listed_and_selectable(self) -> None:
        state = GameState.new(3)
        advisor = Advisor(engine_factory=FakeEngine)
        advisor.update(state, now=0.0)
        self.assertIn(SIX_THREE_ID, [c.source_id for c in advisor.candidates()])
        self.assertTrue(advisor.choose(SIX_THREE_ID))
        rec = advisor.update(state, now=0.0)
        self.assertIn("6-3積み", rec.source)
        self.assertIsNotNone(rec.steps)
        # 選んでいる間は次の手番も6-3積みのまま(テンプレ・パフェに切り替えない)
        state.hard_drop()
        advisor.update(state, now=0.0)
        self.assertEqual(advisor.active_id, SIX_THREE_ID)

    def test_async_calculation(self) -> None:
        state = GameState.new(3)
        advisor = Advisor(engine_factory=FakeEngine, pc_async=True)
        self.addCleanup(advisor.close)
        advisor.update(state, now=0.0)
        advisor.choose(SIX_THREE_ID)
        self.assertIsNone(advisor.update(state, now=0.0), "計算前に手を出した")
        self.assertTrue(advisor.s63_pending)
        deadline = time.monotonic() + 5
        rec = None
        while rec is None and time.monotonic() < deadline:
            time.sleep(0.01)
            rec = advisor.update(state, now=0.0)
        self.assertIsNotNone(rec)
        self.assertFalse(advisor.s63_pending)

    def test_well_is_shown_on_the_board(self) -> None:
        window = PracticeWindow(seed=3, advisor=Advisor(engine_factory=FakeEngine))
        self.addCleanup(window.close)
        self.assertIsNone(window.board_view.well_col)
        window.advisor.choose(SIX_THREE_ID)
        window.refresh()
        self.assertEqual(window.board_view.well_col, WELL_COL)
        window.board_view.grab()


if __name__ == "__main__":
    unittest.main()
