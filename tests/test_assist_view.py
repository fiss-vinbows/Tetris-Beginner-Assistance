"""支援モードの設定画面(src.assist_view)のテスト。

【2026-10-04・利用者の要望】シミュレーターと同じく、支援モードでも開幕TD・パフェ後・パフェ・
テンプレ全体の有無をトグルスイッチで切り替える。
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tests.config_isolation  # noqa: E402,F401
from PyQt6 import QtWidgets  # noqa: E402

from src import assist_view  # noqa: E402
from src.app import AssistWorker  # noqa: E402
from src.engine.openers import choose_opener, choose_tdtd, known_sequence  # noqa: E402
from tests.test_assist_worker import _make_calibration, _move, _recognition  # noqa: E402
from tests.test_tdtd import AFTER_PC_NEXT  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


class TestAssistViewSettings(unittest.TestCase):
    def setUp(self) -> None:
        self.path = assist_view.ASSIST_VIEW_PATH
        self.path.unlink(missing_ok=True)

    def test_defaults_match_previous_launcher(self) -> None:
        # 以前の起動画面の既定(テンプレあり・継続パフェあり・DPC優先でTDTD)と同じ
        options = assist_view.worker_options(assist_view.load_assist_view())
        self.assertEqual(options, {
            "opener_enabled": True, "pc_odds_enabled": True, "pc_odds_first": False,
            "tdtd_mode": "fallback", "dpc_enabled": True, "excluded_templates": frozenset(),
            "plan_depth": 3, "template_full_plan": False,
        })

    def test_plan_depth_is_remembered(self) -> None:
        panel = assist_view.AssistSettingsPanel()
        panel.plan_depth_spin.setValue(5)
        self.assertEqual(assist_view.load_assist_view()["plan_depth"], 5)
        self.assertEqual(assist_view.AssistSettingsPanel().plan_depth_spin.value(), 5, "次回も同じ手数で開く")

    def test_invalid_plan_depth_falls_back(self) -> None:
        self.path.write_text('{"plan_depth": 9}', encoding="utf-8")
        self.assertEqual(assist_view.load_assist_view()["plan_depth"], 3)

    def test_full_plan_switch(self) -> None:
        panel = assist_view.AssistSettingsPanel()
        panel.full_plan_switch.setChecked(True)
        self.assertTrue(assist_view.worker_options(assist_view.load_assist_view())["template_full_plan"])
        panel.templates_switch.setChecked(False)
        self.assertFalse(panel.full_plan_switch.isEnabled(), "テンプレを使わないなら選べない")

    def test_switches_map_to_worker_options(self) -> None:
        settings = assist_view.load_assist_view()
        settings.update({"show:はちみつ砲": False, "show:TDTD": False, "show:DPC": False, "show:継続パフェ": False})
        assist_view.save_assist_view(settings)
        options = assist_view.worker_options(assist_view.load_assist_view())
        self.assertEqual(options["excluded_templates"], frozenset({"はちみつ砲"}))
        self.assertEqual(options["tdtd_mode"], "off")
        self.assertFalse(options["dpc_enabled"])
        self.assertFalse(options["pc_odds_enabled"])

    def test_dialog_saves_on_toggle_and_disables_without_templates(self) -> None:
        dialog = assist_view.AssistSettingsPanel()
        self.assertIn("迷走砲", dialog.switches)
        self.assertIn("ベーカリーTD", dialog.switches, "TDTD向けのTD系テンプレも並べる")
        dialog.switches["迷走砲"].setChecked(False)
        self.assertFalse(assist_view.load_assist_view()["show:迷走砲"])
        dialog.templates_switch.setChecked(False)
        self.assertFalse(assist_view.load_assist_view()["templates"])
        self.assertFalse(dialog.switches["DPC"].isEnabled())
        self.assertFalse(dialog.switches["迷走砲"].isEnabled())
        self.assertTrue(dialog.switches["継続パフェ"].isEnabled(), "継続パフェはテンプレと別に切り替えられる")
        self.assertFalse(dialog.pc_odds_first_switch.isEnabled(), "テンプレが無ければ優先を選ぶ意味が無い")

    def test_pc_odds_first_switch_saves(self) -> None:
        panel = assist_view.AssistSettingsPanel()
        panel.pc_odds_first_switch.setChecked(True)
        self.assertTrue(assist_view.worker_options(assist_view.load_assist_view())["pc_odds_first"])


class TestExcludedTemplates(unittest.TestCase):
    def test_choose_opener_skips_excluded(self) -> None:
        name = choose_opener(list("ILSTZOJ"))[0].name_ja
        chosen = choose_opener(list("ILSTZOJ"), excluded=frozenset({name}))
        self.assertTrue(chosen is None or chosen[0].name_ja != name)

    def test_choose_tdtd_skips_excluded(self) -> None:
        sequence = known_sequence("T", AFTER_PC_NEXT, None, 21)
        name = choose_tdtd(sequence, "Z")[0].name_ja
        chosen = choose_tdtd(sequence, "Z", excluded=frozenset({name}))
        self.assertTrue(chosen is None or chosen[0].name_ja != name)


class TestAssistWorkerDpcSwitch(unittest.TestCase):
    def _run(self, **kwargs):
        cold_clear = MagicMock()
        cold_clear.poll_suggestion.return_value = _move("A")
        worker = AssistWorker(_make_calibration(), cold_clear, debug_log_path=None, opener_enabled=True, **kwargs)
        worker._opener_locks = 20  # 8段パフェ(20個)の後
        rec = _recognition(current_piece="T", hold_piece="Z", next_queue=AFTER_PC_NEXT)
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch("src.app.recognize", return_value=rec):
                worker._tick_once(capture=MagicMock())
        return worker._opener

    def test_dpc_off_uses_tdtd(self) -> None:
        run = self._run(tdtd_mode="fallback", dpc_enabled=False)
        self.assertIsNotNone(run)
        self.assertNotEqual(run.template.name_ja, "DPC")

    def test_dpc_and_tdtd_off_shows_ai(self) -> None:
        self.assertIsNone(self._run(tdtd_mode="off", dpc_enabled=False))


if __name__ == "__main__":
    unittest.main()


class TestTemplateFullPlan(unittest.TestCase):
    """テンプレに限り、表示手数に関係なく図の残りの手をすべて表示する。"""

    def _count(self, full: bool, template=None) -> int | None:
        worker = AssistWorker(_make_calibration(), MagicMock(), debug_log_path=None, plan_depth=2, template_full_plan=full)
        if template is not None:
            worker._opener = MagicMock(template=template)
        return worker._shown_plan_count()

    def test_counts(self) -> None:
        from src import app

        name = choose_opener(list("ILSTZOJ"))[0]
        self.assertEqual(self._count(False, name), 1, "オフなら表示手数どおり")
        self.assertIsNone(self._count(True, name), "テンプレの間は制限なし")
        self.assertEqual(self._count(True), 1, "AIの提案は表示手数どおり")
        self.assertIsNone(self._count(True, app._PC_ODDS_TEMPLATE), "途中で見えたパフェもすべて表示する")
        self.assertIsNone(self._count(True, app._PC_TEMPLATE))


class TestRejoinAfterLeaving(unittest.TestCase):
    """【2026-10-04・利用者の要望】手順を外れてやめたテンプレへ、盤面が合流したら戻す(シミュレーターと同じ)。"""

    def _worker(self):
        worker = AssistWorker(_make_calibration(), MagicMock(), debug_log_path=None, opener_enabled=True)
        return worker

    def _midway(self):
        from src.engine.openers import apply_step

        template, form, steps = choose_opener(list("ILSTZOJ"))
        board = set(form.existing)
        for st in steps[:2]:
            board = apply_step(board, st.cells)
        return template, steps, board

    def test_rejoins_midway_shape(self) -> None:
        template, steps, board = self._midway()
        worker = self._worker()
        worker._opener_rejoin = template
        got = worker._rejoin_run(board, [s.piece for s in steps[2:]], None)
        self.assertIsNotNone(got)
        _tpl, form, rest = got
        self.assertEqual(form.existing, frozenset(board), "置き済みのミノを既存ブロックに含める")
        self.assertEqual(len(rest), len(form.items), "砲のみ(縮小)と誤表示しない")
        self.assertEqual([s.cells for s in rest], [s.cells for s in steps[2:]])

    def test_no_rejoin_without_left_template_or_on_other_board(self) -> None:
        template, steps, board = self._midway()
        worker = self._worker()
        self.assertIsNone(worker._rejoin_run(board, [s.piece for s in steps[2:]], None), "やめたテンプレが無い")
        worker._opener_rejoin = template
        stray = {(0, 0), (0, 1), (1, 0), (1, 1)} - board  # 図に無い上の方のブロック
        self.assertTrue(stray)
        self.assertIsNone(worker._rejoin_run(board | stray, [s.piece for s in steps[2:]], None), "盤面が図と違えば戻さない")

    def test_excluded_template_is_not_rejoined(self) -> None:
        template, steps, board = self._midway()
        worker = AssistWorker(_make_calibration(), MagicMock(), debug_log_path=None, opener_enabled=True,
                              excluded_templates=frozenset({template.name_ja}))
        worker._opener_rejoin = template
        self.assertIsNone(worker._rejoin_run(board, [s.piece for s in steps[2:]], None))


class TestSettingsAndMissLog(unittest.TestCase):
    """【2026-10-04・利用者の要望】ログに設定と、次の図が見つからない理由を書く。"""

    def test_settings_text(self) -> None:
        worker = AssistWorker(_make_calibration(), MagicMock(), debug_log_path=None, opener_enabled=True,
                              dpc_enabled=False, tdtd_mode="first", excluded_templates=frozenset({"迷走砲"}), plan_depth=4)
        text = worker._settings_text()
        for part in ("テンプレ=あり", "外したテンプレ=迷走砲", "DPC=なし", "TDTD=first", "表示手数=4"):
            self.assertIn(part, text)

    def test_continue_miss_is_logged_once(self) -> None:
        import io

        template, _form, _steps = choose_opener(list("ILSTZOJ"))
        worker = AssistWorker(_make_calibration(), MagicMock(), debug_log_path=None, opener_enabled=True)
        worker._debug_log_file = io.StringIO()
        worker._opener_continuing = template
        worker._opener_locks = 5
        worker._last_current_piece = "S"
        rec = _recognition(current_piece="S", hold_piece="L", next_queue=tuple("LTIZJ"))
        worker._log_continue_miss("図が一致しない・組めない", rec, list("SLTIZJ"))
        worker._log_continue_miss("図が一致しない・組めない", rec, list("SLTIZJ"))
        log = worker._debug_log_file.getvalue()
        self.assertEqual(log.count("次の図を探索中"), 1, "同じ内容は1回だけ")
        self.assertIn("置いた数=5", log)
        self.assertIn("ミノ順=SLTIZJ", log)
        worker._opener_continuing = None
        worker._log_continue_miss("盤面が未確定", rec, None)
        self.assertEqual(worker._debug_log_file.getvalue(), log, "次の図を探していないときは書かない")


class TestGarbageStopsTemplate(unittest.TestCase):
    """【2026-10-04・利用者の指示(案A)/実機ログ debug_log_20261004_101920】おじゃまがあるとパフェは取れない。
    Tスピン(TSD等)まで打ったらAIにし、テンプレの続行・パフェ後のテンプレはおじゃまが無いときだけ。"""

    def _worker(self):
        return AssistWorker(_make_calibration(), MagicMock(), debug_log_path=None, opener_enabled=True, tdtd_mode="first")

    def _run(self, spins, shift_on_clear=True, index=0):
        from src.app import _OpenerRun
        from src.engine.openers import OpenerStep

        steps = [OpenerStep("T" if sp else "O", ((19, i),), False, sp) for i, sp in enumerate(spins)]
        template, form, _ = choose_opener(list("ILSTZOJ"))
        return _OpenerRun(template=template, form=form, steps=steps, board=set(), index=index, shift_on_clear=shift_on_clear)

    def test_cut_after_t_spin(self) -> None:
        worker = self._worker()
        run = self._run([False, True, False, False])  # 積み→TSD→パフェ狙い
        worker._opener = run
        self.assertTrue(worker._limit_steps_for_garbage(run, placed_current=False))
        self.assertEqual([st.spin for st in run.steps], [False, True], "Tスピンの後(パフェ狙い)は出さない")

    def test_stacking_before_t_spin_continues(self) -> None:
        worker = self._worker()
        run = self._run([False, False, False])  # 1巡目の積み(Tスピンは次の図)
        worker._opener = run
        self.assertTrue(worker._limit_steps_for_garbage(run, placed_current=False))
        self.assertEqual(len(run.steps), 3)

    def test_after_t_spin_without_spin_left_goes_to_ai(self) -> None:
        worker = self._worker()
        run = self._run([True, False, False], index=1)  # TSDを打った後のパフェ狙い
        worker._opener = run
        self.assertFalse(worker._limit_steps_for_garbage(run, placed_current=False))
        self.assertIsNone(worker._opener)

    def test_pc_search_steps_stop(self) -> None:
        worker = self._worker()
        run = self._run([False, False], shift_on_clear=False)  # テンプレの続きで探したパフェの手順
        worker._opener = run
        self.assertFalse(worker._limit_steps_for_garbage(run, placed_current=False))

    def test_no_tdtd_on_garbage_only_board(self) -> None:
        from dataclasses import replace

        cold_clear = MagicMock()
        cold_clear.poll_suggestion.return_value = _move("A")
        worker = AssistWorker(_make_calibration(), cold_clear, debug_log_path=None, opener_enabled=True, tdtd_mode="first")
        worker._opener_locks = 20
        rec = _recognition(current_piece="T", hold_piece="Z", next_queue=AFTER_PC_NEXT)
        for r in (18, 19):
            for c in range(10):
                if c != 4:
                    rec.board.grid[r][c] = "GARBAGE"
        rec = replace(rec, board_key=tuple(tuple(row) for row in rec.board.grid))
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch("src.app.recognize", return_value=rec):
                worker._tick_once(capture=MagicMock())
                worker._tick_once(capture=MagicMock())
        self.assertIsNone(worker._opener, "おじゃまだけの盤面をパフェ後と取り違えない")


class TestStaleOpenerAtGameStart(unittest.TestCase):
    """【2026-10-04・実機ログ debug_log_20261004_102916】対局開始の直前に実在しない操作ミノ(I)で開幕テンプレを
    選び、本当の1手目(S)が出てきても1.5秒間ガイドが消えていた。すぐ選び直す。"""

    def test_reselects_without_waiting_for_timeout(self) -> None:
        cold_clear = MagicMock()
        cold_clear.poll_suggestion.return_value = _move("I")
        worker = AssistWorker(_make_calibration(), cold_clear, debug_log_path=None, opener_enabled=True)
        before = _recognition(current_piece="I", next_queue=tuple("SJTLO"))
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch("src.app.recognize", return_value=before):
                worker._tick_once(capture=MagicMock())
                worker._tick_once(capture=MagicMock())
        self.assertIsNotNone(worker._opener)
        self.assertEqual(worker._opener.steps[0].piece, "I", "前提: Iを1手目として選んでいる")
        # ゲームが始まりNEXTが進む。Iは置かれず(盤面は空のまま)、操作ミノはS
        after = _recognition(current_piece="S", next_queue=tuple("JTLOZ"))
        with patch("src.app.recognize", return_value=after):
            for t in (1000.5, 1000.6, 1000.7, 1000.9):
                with patch("src.app.time.monotonic", return_value=t):
                    worker._tick_once(capture=MagicMock())
        self.assertIsNotNone(worker._opener, "選び直したテンプレがある")
        self.assertIn(worker._opener.steps[0].piece, {"S", "J"}, "今のミノ順(S始まり)で選び直す")


class TestMidwayFormRightAfterFigure(unittest.TestCase):
    """【2026-10-04・実機ログ debug_log_20261004_103551 124〜137行目】迷走砲の1巡目の最後に先置きしたSが、
    2巡目の妥協形では置き済みの1手に当たる。図を置き終えた直後から途中形として拾い、3秒待たない。"""

    BOARD = ((16, 0), (16, 7), (16, 8), (17, 0), (17, 1), (17, 2), (17, 4), (17, 7), (17, 8), (17, 9), (18, 0), (18, 1),
             (18, 2), (18, 3), (18, 4), (18, 5), (18, 7), (18, 8), (18, 9), (19, 0), (19, 1), (19, 2), (19, 3), (19, 4),
             (19, 6), (19, 7), (19, 8), (19, 9))

    def test_compromise_form_is_shown_immediately(self) -> None:
        from src.engine.openers import OPENER_TEMPLATES, _assist_template

        cold_clear = MagicMock()
        cold_clear.poll_suggestion.return_value = _move("S")
        worker = AssistWorker(_make_calibration(), cold_clear, debug_log_path=None, opener_enabled=True)
        worker._opener_continuing = _assist_template(next(t for t in OPENER_TEMPLATES if t.name_ja == "迷走砲"))
        worker._opener_locks = 7
        rec = _recognition(current_piece="S", hold_piece="T", next_queue=tuple("OLZIJ"), filled_cells=self.BOARD)
        worker._last_current_piece = "S"
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch("src.app.recognize", return_value=rec):
                worker._tick_once(capture=MagicMock())
                worker._tick_once(capture=MagicMock())
        self.assertIsNotNone(worker._opener, "時間切れを待たずに続きの図を出す")
        self.assertIn("%S>%O", worker._opener.form.section)
        self.assertEqual(worker._opener.form.existing, frozenset(self.BOARD), "先置きしたSを既存ブロックに含める")


class TestSwitchToOtherTemplate(unittest.TestCase):
    """【2026-10-04・利用者の要望】はちみつ砲と迷走砲のどちらでも組めるとき、提示と違う方を組み始めたら、
    その別のテンプレの途中形に合流して提示を切り替える。"""

    SEQUENCE = list("IOTSJZL")  # 1手目がIで、はちみつ砲・迷走砲ともに組め、Iの置き場所が違う

    def test_switches_after_placing_the_other_templates_first_piece(self) -> None:
        from src.engine.openers import OPENER_TEMPLATES, _assist_template, choose_form

        cold_clear = MagicMock()
        cold_clear.poll_suggestion.return_value = _move("I")
        worker = AssistWorker(_make_calibration(), cold_clear, debug_log_path=None, opener_enabled=True)
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch("src.app.recognize", return_value=_recognition(current_piece="I", next_queue=tuple("OTSJZ"))):
                worker._tick_once(capture=MagicMock())
                worker._tick_once(capture=MagicMock())
        shown = worker._opener.template.name_ja
        other = "迷走砲" if shown == "はちみつ砲" else "はちみつ砲"
        templates = {t.name_ja: _assist_template(t) for t in OPENER_TEMPLATES}
        _form, other_steps = choose_form(templates[other], set(), self.SEQUENCE, None)
        self.assertNotEqual(set(other_steps[0].cells), set(worker._opener.steps[0].cells), "前提: Iの置き場所が違う")
        # 提示と違う方(別のテンプレ)の置き場所にIを置いた
        placed = _recognition(current_piece="O", next_queue=tuple("TSJZL"), filled_cells=tuple(other_steps[0].cells))
        with patch("src.app.recognize", return_value=placed):
            for t in (1000.5, 1000.6, 1000.7):
                with patch("src.app.time.monotonic", return_value=t):
                    worker._tick_once(capture=MagicMock())
        self.assertIsNotNone(worker._opener, "別のテンプレに合流していない")
        self.assertEqual(worker._opener.template.name_ja, other)

    def test_excluded_template_is_not_switched_to(self) -> None:
        from src.engine.openers import OPENER_TEMPLATES, _assist_template, choose_form

        templates = {t.name_ja: _assist_template(t) for t in OPENER_TEMPLATES}
        _form, steps = choose_form(templates["迷走砲"], set(), self.SEQUENCE, None)
        worker = AssistWorker(_make_calibration(), MagicMock(), debug_log_path=None, opener_enabled=True,
                              excluded_templates=frozenset({"迷走砲"}))
        worker._opener_rejoin = templates["はちみつ砲"]
        got = worker._rejoin_run(set(steps[0].cells), self.SEQUENCE[1:], None)
        self.assertTrue(got is None or got[0].name_ja != "迷走砲")


class TestHoneyCupSecondBagSeventhPiece(unittest.TestCase):
    """【2026-10-04・実機ログ debug_log_20261004_105351 117〜128行目】HOLDのL(前の袋の繰り越し)も袋の先頭の
    候補にしていたため7個目を補えず、HOLD+次の袋7個を使うはちみつ砲の2巡目が組めなかった。"""

    BOARD = tuple([(16, 7), (16, 8), (17, 2), (17, 7), (17, 8), (17, 9), (18, 0), (18, 1), (18, 2), (18, 3), (18, 4), (18, 5), (18, 7), (18, 8), (18, 9), (19, 0), (19, 1), (19, 2), (19, 3), (19, 4), (19, 6), (19, 7), (19, 8), (19, 9)])

    def _tick(self, held_this_turn: bool):
        from src.engine.openers import OPENER_TEMPLATES, _assist_template

        cold_clear = MagicMock()
        cold_clear.poll_suggestion.return_value = _move("J")
        worker = AssistWorker(_make_calibration(), cold_clear, debug_log_path=None, opener_enabled=True)
        worker._opener_continuing = _assist_template(next(t for t in OPENER_TEMPLATES if t.name_ja == "はちみつ砲"))
        worker._opener_locks = 6
        worker._last_current_piece = "J"
        worker._disallow_hold_active = held_this_turn
        rec = _recognition(current_piece="J", hold_piece="L", next_queue=tuple("SOITZ"), filled_cells=self.BOARD)
        worker._maybe_start_template(rec)
        return worker

    def test_second_bag_starts(self) -> None:
        worker = self._tick(held_this_turn=False)
        self.assertEqual(worker._known_sequence(_recognition(current_piece="J", hold_piece="L", next_queue=tuple("SOITZ")), "L", 7),
                         list("JSOITZL"), "操作ミノを袋の先頭として7個目(L)を補う")
        self.assertIsNotNone(worker._opener, "2巡目が始まらない")
        self.assertIn("2巡目", worker._opener.form.section)

    def test_after_hold_keeps_both_heads(self) -> None:
        # この手番でHOLDした後は、新しく出たミノがHOLD欄にあるかもしれないので先頭を決めつけない
        worker = self._tick(held_this_turn=True)
        self.assertEqual(worker._known_sequence(_recognition(current_piece="J", hold_piece="L", next_queue=tuple("SOITZ")), "L", 7),
                         list("JSOITZ"))


class TestTdtdLabel(unittest.TestCase):
    """【2026-10-04・利用者の指示】開幕テンプレは最初だけ。2回目以降のTD系テンプレは「TDTD」と表記する。"""

    def test_label(self) -> None:
        worker = AssistWorker(_make_calibration(), MagicMock(), debug_log_path=None, opener_enabled=True, tdtd_mode="first")
        self.assertEqual(worker._opener_kind(), "開幕テンプレ")

    def test_tdtd_run_is_labelled_tdtd(self) -> None:
        cold_clear = MagicMock()
        cold_clear.poll_suggestion.return_value = _move("A")
        worker = AssistWorker(_make_calibration(), cold_clear, debug_log_path=None, opener_enabled=True, tdtd_mode="first")
        worker._opener_locks = 20  # 8段パフェ(20個)の後
        rec = _recognition(current_piece="T", hold_piece="Z", next_queue=AFTER_PC_NEXT)
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch("src.app.recognize", return_value=rec):
                worker._tick_once(capture=MagicMock())
        self.assertIsNotNone(worker._opener)
        self.assertEqual(worker._opener_kind(), "TDTD")
