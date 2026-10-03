"""テンプレの図・パフェの手順のガイド表示のテスト。

【2026-09-29・利用者の指示】ブラウザー版のように、テンプレ・パフェで置く予定のミノ(7種)を
盤面に薄く示す。推奨手(Recommendation.guide)に、今の盤面の座標で並べる。
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.education.advisor import PC_ID, Advisor, _pc_guide  # noqa: E402
from src.education.pc_search import PCStep  # noqa: E402
from src.education.rules import GameState  # noqa: E402
from tests.test_education_advisor import FakeEngine  # noqa: E402


class TestPcGuide(unittest.TestCase):
    def test_steps_after_a_line_clear_are_put_back_above_the_cleared_row(self) -> None:
        # 一番下の行(21行目)を2手で消し、3手目は消去後の座標(21行目)で表される
        steps = [
            PCStep("I", ((21, 0), (21, 1), (21, 2), (21, 3)), False),
            PCStep("I", ((21, 4), (21, 5), (21, 6), (21, 7)), False),
            PCStep("O", ((20, 8), (20, 9), (21, 8), (21, 9)), False),  # ここで21行目が揃って消える
            PCStep("I", ((21, 0), (21, 1), (21, 2), (21, 3)), False),  # 消去後の21行目=元の20行目
        ]
        guide = _pc_guide(frozenset(), steps)
        self.assertEqual(guide[2], ("O", ((20, 8), (20, 9), (21, 8), (21, 9))))
        self.assertEqual(guide[3], ("I", ((20, 0), (20, 1), (20, 2), (20, 3))))

    def test_no_clear_keeps_coordinates(self) -> None:
        steps = [PCStep("O", ((20, 0), (20, 1), (21, 0), (21, 1)), False)]
        self.assertEqual(_pc_guide(frozenset(), steps), (("O", steps[0].cells),))


class TestAdvisorGuide(unittest.TestCase):
    def test_template_shows_the_remaining_pieces_of_the_form(self) -> None:
        state = GameState.new(1)
        advisor = Advisor(engine_factory=FakeEngine)
        rec = advisor.update(state, now=0.0)
        self.assertNotEqual(advisor.active_id, PC_ID)
        self.assertGreaterEqual(len(rec.guide), 6, "1巡目の図の残りのミノを示す")
        self.assertEqual(rec.guide[0], (rec.piece, tuple(rec.cells)))

    def test_perfect_clear_shows_the_whole_plan(self) -> None:
        # パフェ直後の空の盤面で2段パフェが見える局面(test_education_round2と同じ)
        state = GameState.new(1, None, None, ("O", "I", 15))
        state.sequence._prefix = tuple("IJLOSTZIJLOSTZ") + tuple("OJLOJSZ")
        advisor = Advisor(engine_factory=FakeEngine, odds_search=lambda *a, **k: None)
        rec = advisor.update(state, now=0.0)
        self.assertEqual(advisor.active_id, PC_ID)
        self.assertEqual(len(rec.guide), 5)
        cells = [cell for _piece, piece_cells in rec.guide for cell in piece_cells]
        self.assertEqual(len(set(cells)), 20, "2段×10列をちょうど埋める")
        self.assertTrue(all(r in (20, 21) for r, _c in cells))


if __name__ == "__main__":
    unittest.main()
