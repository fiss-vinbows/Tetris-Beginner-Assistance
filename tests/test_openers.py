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
    apply_step,
    choose_form,
    choose_opener,
    known_sequence,
    mirror_form_text,
    parse_form,
    plan_form,
)
from src.vision.shape_matcher import match_piece_shape


def _template(name_ja: str):
    return next(t for t in OPENER_TEMPLATES if t.name_ja == name_ja)


def _run_steps(steps, sequence, hold, board):
    """手順を実際のミノ順に対して実行し、(盤面, ホールド, 残りのミノ順)を返す。"""
    seq = list(sequence)
    for step in steps:
        if step.use_hold:
            if hold is None:
                hold = seq.pop(0)
                assert seq.pop(0) == step.piece, f"ホールド後に置くミノが違う: {step}"
            else:
                assert hold == step.piece, f"ホールドのミノが違う: {step} hold={hold}"
                hold = seq.pop(0)
        else:
            assert seq.pop(0) == step.piece, f"置くミノが違う: {step}"
        board = apply_step(board, step.cells)
    return board, hold, seq


class TestTemplateForms(unittest.TestCase):
    def test_every_form_has_valid_tetromino_shapes(self) -> None:
        # 図の写し間違い(4マスでない、形が違う)を検出する。
        for template in OPENER_TEMPLATES:
            self.assertTrue(template.forms, f"{template.name_ja}に図が無い")
            for form in template.forms:
                for item in form.items:
                    self.assertEqual(
                        match_piece_shape(frozenset(item.cells)),
                        item.piece,
                        f"{template.name_ja} [{form.section}]: {item.piece}の形が違う {item.cells}",
                    )

    def test_first_bag_forms_exist_for_every_template(self) -> None:
        for template in OPENER_TEMPLATES:
            self.assertTrue(
                any(not form.existing for form in template.forms), f"{template.name_ja}に1巡目の図が無い"
            )

    def test_mirror_swaps_pieces_and_columns(self) -> None:
        # 左端のjは右端に移り、鏡像なのでlになる。
        self.assertEqual(mirror_form_text("jl--------\nsz-------U"), "--------jl\nU-------sz")

    def test_composite_figures_after_line_clears_are_skipped(self) -> None:
        # ライン消去後の合成図(同じ記号が2マスずつに分かれている)は解釈しない。
        self.assertIsNone(parse_form("iiiijsszzl\nccccjjjlll\nccccsscczz\nccctttcccc\ncccctccccc"))


class TestPlanForm(unittest.TestCase):
    def test_hard_drop_requires_support_and_clear_column_above(self) -> None:
        placed = {(19, 0)}
        self.assertTrue(_can_hard_drop(placed, ((18, 0), (18, 1), (17, 0), (17, 1))))
        self.assertFalse(_can_hard_drop(placed, ((18, 5), (18, 6), (17, 5), (17, 6))))
        self.assertFalse(_can_hard_drop({(10, 3)}, ((19, 3), (19, 4), (18, 3), (18, 4))))

    def test_honey_cup_first_bag_then_second_bag_then_tst(self) -> None:
        # 1巡目 → 2巡目の図 → TSTの図、と既存ブロックの一致でつながること。
        template = _template("はちみつ砲")
        chosen = choose_opener(list("ILSTZOJ"))
        self.assertIsNotNone(chosen)
        tpl, form, steps = chosen
        self.assertEqual(tpl.name_ja, "はちみつ砲")
        board, hold, _rest = _run_steps(steps, "ILSTZOJ", None, set())
        self.assertEqual(hold, "J", "1巡目はJをホールドに残す")

        second = choose_form(template, board, list("TOSZIJL"), hold)
        self.assertIsNotNone(second, "2巡目の図が見つからない")
        form2, steps2 = second
        self.assertIn("2巡目", form2.section)
        self.assertFalse(any(s.spin for s in steps2))
        board, hold, rest = _run_steps(steps2, "TOSZIJL", hold, board)
        self.assertEqual(hold, "T", "2巡目はTをホールドに残す")

        third = choose_form(template, board, rest + list("OSZIJL")[: 6 - len(rest)], hold)
        self.assertIsNotNone(third, "TSTの図が見つからない")
        form3, steps3 = third
        self.assertEqual(len(steps3), 1)
        self.assertTrue(steps3[0].spin)
        self.assertEqual(steps3[0].piece, "T")
        board_after = apply_step(board, steps3[0].cells)
        # TSTで3行消える。
        self.assertEqual(len(board) + 4 - len(board_after), 30)

    def test_spin_item_is_placed_last(self) -> None:
        form = parse_form("--z-------\n-zz----o--\n-zU----oU-\nccUU--ccUc\nccUcccccc-")
        # 図の解釈: Uは1つのT(4マス)でなければならないので、この図は解釈不能
        self.assertIsNone(form)

    def test_infeasible_order_returns_none(self) -> None:
        template = _template("はちみつ砲")
        first = next(f for f in template.forms if not f.existing)
        self.assertIsNone(plan_form(first, list("SZTOJLI"), None))

    def test_known_sequence_deduces_the_seventh_piece_only_within_one_bag(self) -> None:
        self.assertEqual(known_sequence("I", ("O", "T", "S", "Z", "J")), ["I", "O", "T", "S", "Z", "J", "L"])
        self.assertEqual(known_sequence("I", ("O", "T", "S", "Z", "I")), ["I", "O", "T", "S", "Z", "I"])
        self.assertIsNone(known_sequence(None, ("O", "T", "S", "Z", "J")))

    def test_apply_step_clears_full_rows(self) -> None:
        board = {(19, c) for c in range(6)}
        after = apply_step(board, ((19, 6), (19, 7), (19, 8), (19, 9)))
        self.assertEqual(after, set())
        board = {(19, c) for c in range(6)} | {(18, 0)}
        after = apply_step(board, ((19, 6), (19, 7), (19, 8), (19, 9)))
        self.assertEqual(after, {(19, 0)})

    def test_choose_opener_covers_most_bag_orders(self) -> None:
        ok = sum(1 for seq in itertools.permutations("IOTSZJL") if choose_opener(list(seq)) is not None)
        self.assertGreater(ok / 5040, 0.8)


if __name__ == "__main__":
    unittest.main()
