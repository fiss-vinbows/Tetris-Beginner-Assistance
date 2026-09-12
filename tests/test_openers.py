"""開幕テンプレ(src/engine/openers.py)のテスト。"""

from __future__ import annotations

import itertools
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine.openers import (
    OPENER_TEMPLATES,
    _can_hard_drop,
    choose_opener,
    parse_form,
    plan_opener,
)
from src.vision.shape_matcher import match_piece_shape


class TestTemplateForms(unittest.TestCase):
    def test_every_form_has_valid_tetromino_shapes(self) -> None:
        # 図の写し間違い(4マスでない、形が違う)を検出する。
        for template in OPENER_TEMPLATES:
            for form in template.forms:
                cells = parse_form(form)
                for piece, cs in cells.items():
                    self.assertEqual(
                        match_piece_shape(frozenset(cs)), piece, f"{template.name_ja}: {piece}の形が違う {cs}"
                    )

    def test_forms_have_no_completed_rows(self) -> None:
        # 1巡目の形でラインが消えると読み筋の座標がずれる。消える行が無いこと。
        for template in OPENER_TEMPLATES:
            for form in template.forms:
                for line in form.splitlines():
                    self.assertIn("-", line, f"{template.name_ja}に揃った行がある")


class TestPlanOpener(unittest.TestCase):
    def test_hard_drop_requires_support_and_clear_column_above(self) -> None:
        placed = {(19, 0)}
        self.assertTrue(_can_hard_drop(placed, ((18, 0), (18, 1), (17, 0), (17, 1))))  # 上に載る
        self.assertFalse(_can_hard_drop(placed, ((18, 5), (18, 6), (17, 5), (17, 6))))  # 宙に浮く
        self.assertFalse(_can_hard_drop({(10, 3)}, ((19, 3), (19, 4), (18, 3), (18, 4))))  # 上にブロック

    def test_honey_cup_with_i_first_is_buildable(self) -> None:
        # テトリス堂の条件「%I>%L>%S」を満たすミノ順で組めること。
        template = OPENER_TEMPLATES[0]
        self.assertEqual(template.name_ja, "はちみつ砲")
        form = parse_form(template.forms[0])
        steps = plan_opener(form, list("ILSTZOJ"))
        self.assertIsNotNone(steps)
        # 形の6ミノをすべて置き、Jは置かない(1巡目はホールドに残す)。
        self.assertEqual(sorted(s.piece for s in steps), sorted(form))
        # TはZの上に載るので、TがZより先に来たらホールドで順を入れ替える。
        pieces = [s.piece for s in steps]
        self.assertLess(pieces.index("Z"), pieces.index("T"))

    def test_piece_not_in_the_form_is_held(self) -> None:
        # はちみつ砲(左)ではJを置かない。Jが先に来たらホールドして次を置く。
        template = OPENER_TEMPLATES[0]
        steps = plan_opener(parse_form(template.forms[0]), list("JILSZTO"))
        self.assertIsNotNone(steps)
        self.assertEqual(steps[0].piece, "I")
        self.assertTrue(steps[0].use_hold)
        self.assertNotIn("J", [s.piece for s in steps])

    def test_infeasible_order_returns_none(self) -> None:
        # Sが先に2つ来る(=IもLもまだ)ような順では、Sを置く場所の支えがない。
        template = OPENER_TEMPLATES[0]
        self.assertIsNone(plan_opener(parse_form(template.forms[0]), list("SZTOJLI")))

    def test_choose_opener_covers_most_bag_orders(self) -> None:
        # 4テンプレ(左右反転含む)のどれかが組めるミノ順が大半であること。
        ok = sum(1 for seq in itertools.permutations("IOTSZJL") if choose_opener(list(seq)) is not None)
        self.assertGreater(ok / 5040, 0.8)


if __name__ == "__main__":
    unittest.main()
