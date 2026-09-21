"""開幕テンプレ(src/engine/openers.py)のテスト。"""

from __future__ import annotations

import itertools
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine.openers import (
    BOARD_ROWS,
    OPENER_TEMPLATES,
    OpenerStep,
    _can_hard_drop,
    apply_step,
    choose_form,
    choose_opener,
    full_rows_after,
    known_sequence,
    mirror_form_text,
    parse_form,
    plan_form,
    shift_cells_for_clears,
)
from src.vision.shape_matcher import match_piece_shape


def _template(name_ja: str):
    return next(t for t in OPENER_TEMPLATES if t.name_ja == name_ja)


def _choose_with(name_ja: str, sequence: str):
    """指定テンプレの1巡目の図を空の盤面に対して選ぶ(テンプレの優先順に依らない)。"""
    template = _template(name_ja)
    chosen = choose_form(template, set(), list(sequence), None)
    assert chosen is not None, f"{name_ja}が{sequence}で組めない"
    form, steps = chosen
    return template, form, steps


def _run_steps(steps, sequence, hold, board):
    """手順を実際のミノ順に対して実行し、(盤面, ホールド, 残りのミノ順)を返す。

    ラインが消えた手の後は、残りの手順の座標を消えた行数ぶん下へずらす
    (アプリの_check_opener_progressと同じ扱い)。
    """
    seq = list(sequence)
    steps = list(steps)
    for n, step in enumerate(steps):
        if step.use_hold:
            if hold is None:
                hold = seq.pop(0)
                assert seq.pop(0) == step.piece, f"ホールド後に置くミノが違う: {step}"
            else:
                assert hold == step.piece, f"ホールドのミノが違う: {step} hold={hold}"
                hold = seq.pop(0)
        else:
            assert seq.pop(0) == step.piece, f"置くミノが違う: {step}"
        cleared = full_rows_after(board, step.cells)
        board = apply_step(board, step.cells)
        if cleared:
            steps[n + 1 :] = [
                OpenerStep(st.piece, shift_cells_for_clears(st.cells, cleared), st.use_hold, st.spin)
                for st in steps[n + 1 :]
            ]
    return board, hold, seq


def _cells_of(text: str) -> set[tuple[int, int]]:
    """図の'c'のマスを盤面座標の集合にする(ミノを含まない図はparse_formがNoneを返すため)。"""
    lines = text.split("\n")
    return {
        (BOARD_ROWS - len(lines) + i, col)
        for i, line in enumerate(lines)
        for col, ch in enumerate(line)
        if ch == "c"
    }


# はちみつ砲の2巡目+TST(3行消去)の後に残る形(opener_data.pyの図をそのまま写す)。
_AFTER_HONEY_TST = _cells_of("cccc------\ncccc--cc--\nccc---cccc\ncccc-ccccc")


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

    def test_honey_cup_first_bag_then_second_bag_with_tst(self) -> None:
        # 1巡目 → 2巡目の図(TSTのTを含む)、と既存ブロックの一致でつながること。
        # 【2026-09-14実機】TSTは別図だが、2巡目の図に「途中でも置けるスピン手」
        # として合流している(_mark_required_items参照)。
        template = _template("はちみつ砲")
        chosen = _choose_with("はちみつ砲", "ILSTZOJ")
        self.assertIsNotNone(chosen)
        tpl, form, steps = chosen
        self.assertEqual(tpl.name_ja, "はちみつ砲")
        board, hold, _rest = _run_steps(steps, "ILSTZOJ", None, set())
        self.assertEqual(hold, "J", "1巡目はJをホールドに残す")

        second = choose_form(template, board, list("TOSZIJL"), hold)
        self.assertIsNotNone(second, "2巡目の図が見つからない")
        form2, steps2 = second
        self.assertIn("2巡目", form2.section)
        self.assertEqual(len(steps2), 8, "2巡目の7ミノ+TSTのTで8手")
        self.assertEqual([s.piece for s in steps2 if s.spin], ["T"], "TSTのTがスピン手として含まれる")
        # 最後のHOLD交換で次の袋の先頭(O)が出てくる
        board, hold, rest = _run_steps(steps2, "TOSZIJL" + "O", hold, board)
        self.assertEqual(board, _AFTER_HONEY_TST, "2巡目+TSTの後に図どおりの残り形になる")

    def test_honey_cup_tst_can_be_taken_mid_sequence(self) -> None:
        # 【2026-09-14実機 debug_log_20260914_192846】1巡目 O Z I(H) L S(H) T の
        # 後、2巡目のミノ順 O L S J T Z I・HOLD=J で「次の図が見つからず終了」に
        # なった。Tは2巡目の図に無く、HOLDのJもZの後でないと置けないので、
        # Tを消費する手が無かった。実機ではTが来た時点でTSTを打ち、消えた後に
        # Z・I・Jを置いてパフェまで達成していた。
        template = _template("はちみつ砲")
        board = {
            (16, 1), (16, 2), (17, 0), (17, 1), (17, 2), (17, 7), (18, 0), (18, 1), (18, 2), (18, 4),
            (18, 5), (18, 6), (18, 7), (18, 8), (18, 9), (19, 0), (19, 1), (19, 2), (19, 3), (19, 5),
            (19, 6), (19, 7), (19, 8), (19, 9),
        }
        for sequence, hold in (("OLSJTZI", "J"), ("JLSJTZI", "O")):  # HOLD交換の前後
            second = choose_form(template, set(board), list(sequence), hold)
            self.assertIsNotNone(second, f"2巡目の図が見つからない: {sequence} hold={hold}")
            form2, steps2 = second
            pieces = [s.piece for s in steps2]
            self.assertIn("T", pieces)
            self.assertTrue(steps2[pieces.index("T")].spin, "TはTSTとして置く")
            self.assertLess(pieces.index("T"), pieces.index("Z"), "TSTはZより前に打つ(Zの後はTを消費できない)")
            board2, _hold, _rest = _run_steps(steps2, sequence + "O", hold, set(board))  # +次の袋の先頭
            self.assertEqual(board2, _AFTER_HONEY_TST, "2巡目+TSTの後に図どおりの残り形になる")

    def test_stray_cannon_connects_first_bag_to_second_bag(self) -> None:
        # 【2026-09-12実機】迷走砲で「次の図が見つからず終了」になった。
        # 原因は(1)Zをホールドに残す6ミノの1巡目形を選んでいたが、2巡目の
        # 図はZも置く形を前提にしていた (2)2巡目の最後の手(Tスピン)は
        # ホールドしたTを未知の次ミノと入れ替えて打つため、既知の7ミノだけ
        # では手順が組めなかった (3)LはZの下へ回転入れする形だった。
        template = _template("迷走砲")
        chosen = _choose_with("迷走砲", "LOJZITS")
        self.assertIsNotNone(chosen)
        tpl, form, steps = chosen
        self.assertEqual(tpl.name_ja, "迷走砲")
        self.assertEqual(len(steps), 7, "Zも置く7ミノの形を選ぶ")
        board, hold, _rest = _run_steps(steps, "LOJZITS", None, set())
        self.assertIsNone(hold)
        second = choose_form(template, board, list("JTSIOZL"), hold)
        self.assertIsNotNone(second, "2巡目の図が見つからない")
        form2, steps2 = second
        self.assertIn("2巡目", form2.section)
        self.assertTrue(steps2[-1].spin, "最後の手がTスピン")
        self.assertTrue(steps2[-1].use_hold, "TはホールドからTスピンに使う")

    def test_next_form_tolerates_a_few_extra_cells(self) -> None:
        # 【2026-09-12実機】置いたばかりのミノが光って余分なマスとして読まれ、
        # 厳密一致では2巡目の図が見つからなかった(はちみつ砲)。数マスの
        # 余分は許し、その場所には置けないものとして手順を探すこと。
        template = _template("はちみつ砲")
        tpl, form, steps = _choose_with("はちみつ砲", "SLIOJZT")
        board, hold, _rest = _run_steps(steps, "SLIOJZT", None, set())
        with_noise = board | {(10, 5)}
        second = choose_form(template, with_noise, list("IOTSZJL"), hold)
        self.assertIsNotNone(second, "余分なマス1つで2巡目の図が見つからない")
        self.assertIsNone(choose_form(template, board | {(10, 0), (10, 1), (10, 2), (10, 3)}, list("IOTSZJL"), hold))

    def test_pieces_are_not_tucked_under_other_pieces_of_the_same_form(self) -> None:
        # 【2026-09-12実機(録画19秒)】はちみつ砲の2巡目で、先に置くJの下へSを
        # 入れる手順を出していた(Sを入れる方法が無い)。ページに回転入れの
        # 明記が無いミノは、ハードドロップで入る置き順だけを認めること。
        template = _template("はちみつ砲")
        tpl, form, steps = _choose_with("はちみつ砲", "TZLISOJ")
        board, hold, _rest = _run_steps(steps, "TZLISOJ", None, set())
        self.assertEqual(hold, "J")
        # T O L Z S J I の順で、Jの下に入るSをJより後に置く手順を出さないこと
        # (TはTSTの位置に先に置けるので図自体は組める)。
        second = choose_form(template, board, list("TOLZSJI"), hold)
        self.assertIsNotNone(second)
        form2, steps2 = second
        under_j = next(i for i, st in enumerate(steps2) if st.piece == "S" and (15, 1) in st.cells)
        over_s = next(i for i, st in enumerate(steps2) if st.piece == "J" and (14, 1) in st.cells)
        self.assertLess(under_j, over_s, "Jの下に入るSをJより後に置いている")

    def test_noted_tuck_is_still_allowed_for_stray_cannon(self) -> None:
        # 迷走砲2巡目の「Lは左回転で後入れ」はページに明記があるので許す。
        template = _template("迷走砲")
        form = next(f for f in template.forms if f.section == "理想形 > 2巡目" and "L" in f.tuck_pieces)
        self.assertIn("L", form.tuck_pieces)

    def test_cannon_is_built_even_when_the_top_pieces_cannot_follow_the_figure(self) -> None:
        # 【2026-09-12・利用者の方針】2巡目の図どおりに全部置けないミノ順でも、
        # Tスピンで消える行に掛かるミノだけ置いてTST/TSDの形までは組む
        # (上に積むパフェ用のミノは省略してよい)。
        template = _template("はちみつ砲")
        tpl, form, steps = _choose_with("はちみつ砲", "TIJSLZO")
        board, hold, _rest = _run_steps(steps, "TIJSLZO", None, set())
        # (以前は I O T S L J Z を使っていたが、TSTのTを図に合流させてからは
        # この順でも全部置けるようになったので、組めない順に変更)
        second = choose_form(template, board, list("IOTSJZL"), hold)
        self.assertIsNotNone(second, "砲だけの手順も見つからない")
        form2, steps2 = second
        self.assertLess(len(steps2), len(form2.items), "全部置く手順は組めないはず")
        placed = {cell for st in steps2 for cell in st.cells}
        required_cells = {cell for i in form2.required for cell in form2.items[i].cells}
        self.assertTrue(required_cells <= placed, "砲に必要なミノが省略されている")
        # 縮小した手順にもTST(スピン手)が含まれる(TSTのTは必須ミノ)
        self.assertEqual([st.piece for st in steps2 if st.spin], ["T"])
        _run_steps(steps2, "IOTSJZL", hold, board)

    def test_spin_item_is_placed_last(self) -> None:
        form = parse_form("--z-------\n-zz----o--\n-zU----oU-\nccUU--ccUc\nccUcccccc-")
        # 図の解釈: Uは1つのT(4マス)でなければならないので、この図は解釈不能
        self.assertIsNone(form)

    def test_infeasible_order_returns_none(self) -> None:
        template = _template("はちみつ砲")
        first = next(f for f in template.forms if not f.existing)
        self.assertIsNone(plan_form(first, list("SZTOJLI"), None))

    def test_known_sequence_deduces_the_seventh_piece_only_at_a_known_bag_head(self) -> None:
        # 袋の先頭(通し番号が7の倍数)だと分かっているときだけ7個目を確定する
        self.assertEqual(known_sequence("I", ("O", "T", "S", "Z", "J"), None, 0), list("IOTSZJL"))
        self.assertEqual(known_sequence("I", ("O", "T", "S", "Z", "J"), None, 7), list("IOTSZJL"))
        # 種類が重なっていれば袋の先頭でも確定できない(認識ミス等)
        self.assertEqual(known_sequence("I", ("O", "T", "S", "Z", "I"), None, 0), list("IOTSZI"))
        self.assertIsNone(known_sequence(None, ("O", "T", "S", "Z", "J")))
        self.assertIsNone(known_sequence("I", ("O", "?", "S", "Z", "J")))
        self.assertIsNone(known_sequence("I", ("O", "T", "S", "Z")))

    def test_known_sequence_never_guesses_across_a_bag_boundary(self) -> None:
        # 【有識者レビュー2026-09-14】前袋 T S Z J L I O / 次袋 T S Z J I L O で、
        # 前袋末尾のI(通し番号6)を操作中・NEXTが次袋先頭のO T S Z Jだと6種類は
        # すべて異なるが、7個目は「不足しているL」ではなく次袋のI。
        # 「6種類が異なれば同じ袋」を根拠に補完してはならない。
        self.assertEqual(known_sequence("I", ("O", "T", "S", "Z", "J"), None, 6), list("IOTSZJ"))
        # 袋の位置が不明なら確定しない
        self.assertEqual(known_sequence("I", ("O", "T", "S", "Z", "J"), None, None), list("IOTSZJ"))
        self.assertEqual(known_sequence("I", ("O", "T", "S", "Z", "J")), list("IOTSZJ"))

    def test_known_sequence_uses_the_hold_piece_right_after_a_hold(self) -> None:
        # 袋の先頭(通し番号7)のTをHOLDした直後: 操作ミノは前袋のJ、HOLD=T。
        # 袋の先頭はHOLD欄のTなので、T+NEXTから7個目Lを確定できる。
        self.assertEqual(known_sequence("J", ("O", "S", "Z", "I", "J"), "T", 7), list("JOSZIJL"))
        # 操作ミノもHOLDもNEXTに含まれない(どちらが袋の先頭か絞れない)なら確定しない
        self.assertEqual(known_sequence("L", ("O", "S", "Z", "I", "J"), "T", 7), list("LOSZIJ"))

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
