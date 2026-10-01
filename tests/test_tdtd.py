"""TDTDのテスト。

【2026-09-30・利用者の要望】TD系テンプレ(迷走砲・はちみつ砲・山岳積み2号・ガムシロ積み)で8段パフェを
取った後(HOLDに前の袋のミノを1個繰り越し、袋の区切りがずれた状態)で、ずれたままTD系テンプレを
1巡目から組み直す。シミュレーターは候補に並べ(自動ではDPCを優先)、支援モードは設定で選ぶ。
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets  # noqa: E402

from src.app import AssistWorker  # noqa: E402
from src.education.advisor import Advisor  # noqa: E402
from src.education.rules import GameState  # noqa: E402
from src.engine.openers import TD_TEMPLATE_NAMES, choose_tdtd, known_sequence  # noqa: E402
from tests.test_assist_worker import _make_calibration, _move, _recognition  # noqa: E402
from tests.test_education_advisor import FakeEngine  # noqa: E402
from tests.test_education_round2 import _follow  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

# パフェ後: 操作ミノTが袋の先頭(通し番号21)、HOLDに前の袋のZを繰り越し
AFTER_PC_NEXT = ("S", "J", "L", "Z", "O")


class TestChooseTdtd(unittest.TestCase):
    def test_first_bag_form_of_a_td_template(self) -> None:
        sequence = known_sequence("T", AFTER_PC_NEXT, None, 21)
        chosen = choose_tdtd(sequence, "Z")
        self.assertIsNotNone(chosen)
        template, form, steps = chosen
        self.assertIn(template.name_ja, TD_TEMPLATE_NAMES)
        self.assertFalse(form.existing, "1巡目の図(既存ブロックなし)から組み直す")
        self.assertTrue(any(f.existing for f in template.forms), "続きの図(2巡目以降)も探せる")
        self.assertEqual(len(steps), len(form.items))

    def test_needs_the_carried_piece(self) -> None:
        self.assertIsNone(choose_tdtd(known_sequence("T", AFTER_PC_NEXT, None, 21), None))


class TestSimulatorTdtd(unittest.TestCase):
    def _state(self) -> GameState:
        return GameState.new(1, ("IJLOSTZ", "IJLOSTZ", "TSJLZOI"), None, ("T", "Z", 15))

    def test_listed_as_a_candidate_and_dpc_is_chosen_automatically(self) -> None:
        advisor = Advisor(engine_factory=FakeEngine, odds_search=lambda *a, **k: None)
        advisor.update(self._state(), now=0.0)
        labels = {c.source_id: c.label for c in advisor.candidates()}
        tdtd = [name for name, label in labels.items() if label.endswith("(TDTD)")]
        self.assertTrue(tdtd, f"TDTDの候補が無い: {labels}")
        self.assertTrue(all(name in TD_TEMPLATE_NAMES for name in tdtd))
        self.assertEqual(advisor.active_id, "DPC", "自動ではDPCを優先する")

    def test_chosen_tdtd_continues_as_tdtd(self) -> None:
        state = self._state()
        advisor = Advisor(engine_factory=FakeEngine, odds_search=lambda *a, **k: None)
        advisor.update(state, now=0.0)
        name = next(c.source_id for c in advisor.candidates() if c.label.endswith("(TDTD)"))
        advisor.choose(name)
        rec = advisor.update(state, now=0.0)
        self.assertIn("TDTD", rec.source)
        _follow(state, rec)
        rec = advisor.update(state, now=0.0)
        self.assertEqual(advisor.active_id, name)
        self.assertIn("TDTD", rec.source, "2手目以降もTDTDとして続ける")


class TestAssistTdtd(unittest.TestCase):
    def _run(self, mode: str):
        cold_clear = MagicMock()
        cold_clear.poll_suggestion.return_value = _move("A")
        worker = AssistWorker(_make_calibration(), cold_clear, debug_log_path=None, opener_enabled=True, tdtd_mode=mode)
        worker._opener_locks = 20  # 8段パフェ(20個)の後
        rec = _recognition(current_piece="T", hold_piece="Z", next_queue=AFTER_PC_NEXT)
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch("src.app.recognize", return_value=rec):
                worker._tick_once(capture=MagicMock())
        return worker._opener

    def test_tdtd_first(self) -> None:
        run = self._run("first")
        self.assertIsNotNone(run)
        self.assertIn(run.template.name_ja, TD_TEMPLATE_NAMES)
        self.assertFalse(run.form.existing)

    def test_dpc_first_and_dpc_only(self) -> None:
        for mode in ("fallback", "off"):
            run = self._run(mode)
            self.assertIsNotNone(run, mode)
            self.assertEqual(run.template.name_ja, "DPC", mode)


class TestTdExtraTemplates(unittest.TestCase):
    """【2026-09-30・利用者の要望】TDTD向けにTD系テンプレを集める(tools/import_td_templates.py)。"""

    def test_collected_templates_have_first_bag_forms(self) -> None:
        from src.engine import openers

        names = [t.name_ja for t in openers.TD_EXTRA_TEMPLATES]
        self.assertEqual(names, ["ホットケーキ積み", "くろみつ砲", "PC-Spin", "皐月積み", "ベーカリーTD", "タンドリーチキン積み"])
        for template in openers.TD_EXTRA_TEMPLATES:
            self.assertTrue(any(not f.existing for f in template.forms), template.name_ja)
            self.assertTrue(any(f.existing for f in template.forms), f"{template.name_ja}: 2巡目以降の図が無い")
        self.assertTrue(set(names) <= TD_TEMPLATE_NAMES)
        # 支援モードの対局開始時のテンプレ選び(choose_opener)は変えない
        self.assertFalse(set(names) & {t.name_ja for t in openers.OPENER_TEMPLATES})

    def test_carried_o_can_use_bakery_td(self) -> None:
        # Oを繰り越し、次の袋が T O S Z L J I: 既存のTD系では組めず、ベーカリーTDなら組める
        chosen = choose_tdtd(known_sequence("T", tuple("OSZLJ"), None, 21), "O")
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen[0].name_ja, "ベーカリーTD")

    def test_olive_is_offered_only_as_tdtd(self) -> None:
        # オリーブ積みは(利用者の指示で)通常の候補には出さない
        for seed in range(5):
            advisor = Advisor(engine_factory=FakeEngine, odds_search=lambda *a, **k: None)
            advisor.update(GameState.new(seed), now=0.0)
            self.assertNotIn("オリーブ積み", [c.source_id for c in advisor.candidates()])


class TestDiscards(unittest.TestCase):
    """【2026-10-01・利用者の指示】TDTDの2巡目もガイドを出し、TSDまでは打ち切れる形にする。

    TDTDでは袋ごとにミノが1つ余り、HOLDも繰り越しのミノでふさがっているため、図に無いミノを
    逃がす先がなく2巡目・TSDの図を組めなかった。余りのミノを図の外へ置く手を許す(discards)。
    """

    def _after_first_bag(self):
        from tests.test_education_round2 import _follow

        state = GameState.new(1, ("IJLOSTZ", "IJLOSTZ", "TSJLZOI"), None, ("T", "Z", 15))
        advisor = Advisor(engine_factory=FakeEngine, odds_search=lambda *a, **k: None)
        advisor.update(state, now=0.0)
        advisor.choose("山岳積み2号")
        for _ in range(7):  # 1巡目の図(7個)を置く
            _follow(state, advisor.update(state, now=0.0))
        return state, advisor

    def test_second_bag_needs_one_discard(self) -> None:
        from src.education.advisor import _board20
        from src.engine import openers
        from src.engine.openers import plan_form

        state, advisor = self._after_first_bag()
        board = _board20(state.board)
        sequence, hold, _ = advisor._turn_sequence(state)
        mountain = next(t for t in openers.OPENER_TEMPLATES if t.name_ja == "山岳積み2号")
        forms = [f for f in mountain.forms if f.existing and f.existing <= board and len(board - f.existing) < 4]
        self.assertTrue(forms)
        # 余りを置かなければ組めない(HOLDが繰り越しのZでふさがっている)
        self.assertTrue(all(plan_form(f, sequence, hold, placed=set(board)) is None for f in forms))
        steps = next(s for f in forms if (s := plan_form(f, sequence, hold, placed=set(board), discards=1)))
        form = next(f for f in forms if plan_form(f, sequence, hold, placed=set(board), discards=1))
        figure = {cell for item in form.items for cell in item.cells}
        outside = [st for st in steps if not set(st.cells) <= figure]
        self.assertEqual(len(outside), 1, "余りのミノを図の外へ置くのは1手")

    def test_simulator_guides_the_second_bag(self) -> None:
        state, advisor = self._after_first_bag()
        rec = advisor.update(state, now=0.0)
        self.assertEqual(advisor.active_id, "山岳積み2号", "1巡目の後でAIに戻った")
        self.assertIn("2巡目", rec.source)
        self.assertIn("TDTD", rec.source)

    def test_discard_spots_keep_away_from_the_figure(self) -> None:
        from src.engine.openers import _DISCARD_TOP_ROW, _discard_spots

        placed = {(19, c) for c in range(9)}  # 一番下の行は右端だけ空き
        todo = {(18, 4), (18, 5), (19, 9), (17, 4)}
        for cells in _discard_spots(placed, "O", todo):
            self.assertFalse(set(cells) & todo)
            self.assertFalse(any(c == tc and r < tr for r, c in cells for tr, tc in todo), "図のマスの真上")
            self.assertGreaterEqual(min(r for r, _c in cells), _DISCARD_TOP_ROW)
            after = placed | set(cells)
            self.assertFalse(any(all((r, c) in after for c in range(10)) for r in {r for r, _c in cells}), "行が揃う")

    def test_choose_form_accepts_discarded_blocks(self) -> None:
        from src.engine import openers
        from src.engine.openers import choose_form, plan_form

        for template, form in ((t, f) for t in openers.OPENER_TEMPLATES + openers.TD_EXTRA_TEMPLATES for f in t.forms):
            if not form.existing or form.is_spin_only():
                continue
            figure = {cell for item in form.items for cell in item.cells}
            # 下の段のミノから順に置くミノ順(Tスピンの手は最後)
            items = sorted(form.items, key=lambda it: (it.last, -max(r for r, _c in it.cells)))
            sequence = [it.piece for it in items]
            if plan_form(form, sequence, None) is None:
                continue
            free = [c for c in range(10) if not any(fc == c for _r, fc in figure)]
            if not free:
                continue
            # 図の外に置いた余りのミノ(縦のI)が残っている盤面
            c = free[0]
            top = min([r for r, cc in form.existing if cc == c] + [20])
            board = set(form.existing) | {(top - k, c) for k in range(1, 5)}
            single = openers.replace(template, forms=(form,))
            self.assertIsNone(choose_form(single, board, sequence, None), "余分な4マスで一致しない(従来どおり)")
            self.assertIsNotNone(choose_form(single, board, sequence, None, discards=2), "TDTDでは一致とみなす")
            return
        self.fail("図のミノを置かない列がある図が見つからない")

class TestSplitPieces(unittest.TestCase):
    """【2026-10-01・利用者の指示】行をまたいで描かれた図(消える前の座標で描かれたミノ)も読む。"""

    # ホットケーキ積みの3巡目の図: Jで17行目が揃って消えた後に、TとZを置く
    PANCAKE = "\n".join(["----------", "ooiiiizlll", "ootttzzlcc", "ccccjjcccc", "ccctjzcccc", "ccccjccccc"])

    def test_split_piece_is_read_with_its_gap_row(self) -> None:
        from src.engine.openers import parse_form

        form = parse_form(self.PANCAKE)
        self.assertIsNotNone(form)
        by_piece = {it.piece: it for it in form.items}
        self.assertEqual(by_piece["T"].cells, ((16, 2), (16, 3), (16, 4), (18, 3)))
        self.assertEqual(by_piece["T"].gap_rows, frozenset({17}))
        self.assertEqual(by_piece["Z"].gap_rows, frozenset({17}))
        self.assertEqual(by_piece["J"].gap_rows, frozenset())

    def test_gap_row_must_be_cleared_in_the_figure(self) -> None:
        from src.engine.openers import parse_form

        broken = self.PANCAKE.replace("ccccjjcccc", "ccc-jjcccc")  # 17行目が揃わない
        self.assertIsNone(parse_form(broken))

    def test_split_piece_is_placed_after_the_line_clears(self) -> None:
        from src.engine.openers import full_rows_after, parse_form, plan_form, shift_cells_for_clears

        form = parse_form(self.PANCAKE)
        steps = plan_form(form, ["O", "I", "J", "T", "Z", "L"], None)
        self.assertIsNotNone(steps)
        order = [st.piece for st in steps]
        self.assertLess(order.index("J"), order.index("T"), "間の行を消すJより先にTを置いた")
        self.assertLess(order.index("J"), order.index("Z"))
        # 実際に行を消しながら置くと、TとZは消えた後の座標でつながり、空いた位置に支えられて置ける
        board = set(form.existing)
        rest = [tuple(st.cells) for st in steps]
        for k, cells in enumerate(rest):
            self.assertFalse(set(cells) & board, steps[k].piece)
            self.assertTrue(any(r + 1 >= 20 or (r + 1, c) in board for r, c in cells), f"{steps[k].piece}が宙に浮く")
            cleared = full_rows_after(board, cells)
            board |= set(cells)
            if cleared:
                board = {(r + sum(1 for g in cleared if g > r), c) for r, c in board if r not in cleared}
                rest[k + 1 :] = [shift_cells_for_clears(c, cleared) for c in rest[k + 1 :]]

    def test_most_figures_of_the_collected_templates_are_read(self) -> None:
        from src.engine.opener_data_td import TD_EXTRA_SOURCE_FORMS

        total = sum(len(forms) for _ja, _en, _url, forms in TD_EXTRA_SOURCE_FORMS)
        self.assertGreaterEqual(total, 250, "行をまたいだ図が収録されていない")


if __name__ == "__main__":
    unittest.main()
