"""シミュレーターの「表示する候補」の設定欄と、推奨手の計算の軽量化のテスト。

【2026-10-02・利用者の要望】候補が多すぎるので、横の設定欄で DPC・開幕TD(テンプレごと)・TDTD・
6-3積み・開幕パフェ積み・継続パフェの表示を切り替える。隠した候補は計算もしない。動作が重い。
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets  # noqa: E402

import tests.config_isolation  # noqa: E402,F401  本番の設定ファイルを使わない
from src.education import keybindings  # noqa: E402
from src.education.advisor import PC_ODDS_ID, SIX_THREE_ID, TDTD_ID, Advisor, _form_soft_sections  # noqa: E402
from src.education.rules import GameState  # noqa: E402
from src.education.window import PracticeWindow  # noqa: E402
from tests.test_education_advisor import FakeEngine  # noqa: E402
from tests.test_education_round2 import _follow  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _ids(advisor: Advisor) -> list[str]:
    return [c.source_id for c in advisor.candidates()]


class TestHiddenCandidates(unittest.TestCase):
    def test_hidden_template_and_six_three_are_not_listed(self) -> None:
        state = GameState.new(0)
        advisor = Advisor(engine_factory=FakeEngine)
        advisor.update(state, now=0.0)
        shown = _ids(advisor)
        template = next(i for i in shown if i not in (SIX_THREE_ID, "cc2"))
        advisor.set_hidden({template, SIX_THREE_ID})
        advisor.update(state, now=0.0)
        self.assertNotIn(template, _ids(advisor))
        self.assertNotIn(SIX_THREE_ID, _ids(advisor))
        self.assertNotIn(template, advisor._template_recs, "隠したテンプレを計算している")

    def test_hidden_pc_odds_is_not_computed(self) -> None:
        calls = []
        advisor = Advisor(engine_factory=FakeEngine, odds_search=lambda *a, **k: calls.append(a))
        advisor.set_hidden({PC_ODDS_ID})
        # パフェ直後(空の盤面・HOLDあり)でも計算しない
        state = GameState.new(1, None, None, ("T", "O", 9))
        advisor.update(state, now=0.0)
        self.assertEqual(calls, [])

    def test_hidden_tdtd_is_not_offered(self) -> None:
        state = GameState.new(1, ("IJLOSTZ", "IJLOSTZ", "TSJLZOI"), None, ("T", "Z", 15))
        advisor = Advisor(engine_factory=FakeEngine, odds_search=lambda *a, **k: None)
        advisor.update(state, now=0.0)
        self.assertTrue(any(c.label.endswith("(TDTD)") for c in advisor.candidates()))
        advisor.set_hidden({TDTD_ID})
        advisor.update(state, now=0.0)
        self.assertFalse(any(c.label.endswith("(TDTD)") for c in advisor.candidates()))
        self.assertIn("DPC", _ids(advisor))


class TestSoftSectionCache(unittest.TestCase):
    def test_cached_difficulty_equals_recomputed(self) -> None:
        # 【2026-10-02】毎手番、全テンプレの残りの手を全部探し直していた。各手の区間数を覚えて使い回す
        state = GameState.new(3)
        advisor = Advisor(engine_factory=FakeEngine, odds_search=lambda *a, **k: None)
        for _ in range(5):
            rec = advisor.update(state, now=0.0)
            name = advisor.active_id
            track = advisor._tracks[name][len(state.history)]
            fresh = type(track)(track.template, track.form, track.steps, track.index)
            self.assertEqual(_form_soft_sections(state, track), _form_soft_sections(state, fresh))
            self.assertTrue(track.soft_steps, "区間数を覚えていない")
            _follow(state, rec)


class TestFilterPanel(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "view.json"
        self._orig = keybindings.VIEW_PATH
        keybindings.VIEW_PATH = self.path
        self.addCleanup(lambda: setattr(keybindings, "VIEW_PATH", self._orig))

    def _window(self) -> PracticeWindow:
        window = PracticeWindow(seed=0, advisor=Advisor(engine_factory=FakeEngine))
        self.addCleanup(window.close)
        return window

    def test_unchecking_hides_and_is_saved(self) -> None:
        window = self._window()
        self.assertIn(SIX_THREE_ID, _ids(window.advisor))
        window.filter_checks[SIX_THREE_ID].setChecked(False)
        self.assertNotIn(SIX_THREE_ID, _ids(window.advisor))
        self.assertFalse(keybindings.load_view(self.path)[keybindings.SHOW_PREFIX + SIX_THREE_ID])
        # 次に開いたときも隠したまま
        again = self._window()
        self.assertFalse(again.filter_checks[SIX_THREE_ID].isChecked())
        self.assertIn(SIX_THREE_ID, again.advisor.hidden)

    def test_panel_lists_all_requested_kinds(self) -> None:
        window = self._window()
        for source_id in ("DPC", TDTD_ID, SIX_THREE_ID, "開幕パフェ積み", PC_ODDS_ID, "迷走砲", "はちみつ砲"):
            self.assertIn(source_id, window.filter_checks)
        self.assertNotIn("オリーブ積み", window.filter_checks, "通常は出さないテンプレ")


class TestPanelRules(unittest.TestCase):
    """【2026-10-03・利用者の指示】候補はトグルスイッチ。優先がAIなら候補の設定を操作できない。
    提示を非表示にしたら優先も隠す。左右移動とソフトドロップのリピート設定を別にする。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for name, file in (("VIEW_PATH", "view.json"), ("REPEAT_PATH", "repeat.json")):
            original = getattr(keybindings, name)
            setattr(keybindings, name, Path(self.tmp.name) / file)
            self.addCleanup(lambda n=name, o=original: setattr(keybindings, n, o))
        self.window = PracticeWindow(seed=0, advisor=Advisor(engine_factory=FakeEngine))
        self.addCleanup(self.window.close)

    def test_candidates_are_toggle_switches(self) -> None:
        # 【2026-10-03・利用者の指示】文字の無い小さなスイッチを、テンプレ名の右に置く
        from src.education.window import MiniSwitch

        self.assertTrue(all(isinstance(w, MiniSwitch) for w in self.window.filter_checks.values()))

    def test_ai_priority_locks_the_candidate_settings(self) -> None:
        window = self.window
        self.assertTrue(all(w.isEnabled() for w in window.filter_checks.values()))
        window.perform("toggle_priority")  # AI優先
        self.assertFalse(any(w.isEnabled() for w in window.filter_checks.values()))
        self.assertFalse(any(b.isEnabled() for b in window.filter_buttons))
        window.perform("toggle_priority")  # テンプレ優先に戻す
        self.assertTrue(all(w.isEnabled() for w in window.filter_checks.values()))

    def test_hiding_hints_hides_the_priority_switch(self) -> None:
        window = self.window
        window.show()
        self.assertTrue(window.priority_btn.isVisible())
        window.perform("toggle_hints")
        self.assertFalse(window.priority_btn.isVisible())
        window.perform("toggle_hints")
        self.assertTrue(window.priority_btn.isVisible())

    def test_soft_drop_has_its_own_repeat_delay(self) -> None:
        from src.education.window import RepeatTracker

        window = self.window
        window.soft_delay_spin.setValue(300)
        self.assertEqual(keybindings.load_repeat()["soft_delay_ms"], 300)
        moves = []
        tracker = RepeatTracker()
        repeat = dict(window.repeat)
        for now in (0, 100, 200, 310, 340):
            tracker.update({"soft_drop"}, now, lambda a: moves.append((now, a)) or True, **repeat)
        # 押した瞬間に1回、300ms後から自分の間隔(18ms)で降り続ける(左右移動のリピート開始とは別)。
        # 340msの判定では318ms・336msの2回分をまとめて行う
        self.assertEqual([t for t, _a in moves], [0, 310, 340, 340])

    def test_repeat_keeps_the_set_speed_even_when_ticks_are_late(self) -> None:
        # 【2026-10-03・利用者の指摘】ソフトドロップが速い時と遅い時がある。16msごとの判定では18msの設定が
        # 約31msに丸められ、裏の計算で判定が遅れる(約40ms)とさらに遅くなっていた
        from src.education.window import RepeatTracker

        repeat = {"delay_ms": 170, "interval_ms": 50, "soft_delay_ms": 20, "soft_interval_ms": 18}
        for tick_ms in (16, 40):
            tracker = RepeatTracker()
            drops = []
            for now in range(0, 1001, tick_ms):
                tracker.update({"soft_drop"}, now, lambda a: drops.append(a) or True, **repeat)
            # 押した瞬間の1回 + 20msから18msごと(1000msまでに55回)
            self.assertAlmostEqual(len(drops), 1 + (1000 - 20) // 18 + 1, delta=3, msg=f"判定が{tick_ms}msごと")

    def test_blocked_move_does_not_build_up(self) -> None:
        # 壁で止まっている間に遅れをためて、離れた瞬間に一気に動かない
        from src.education.window import RepeatTracker

        tracker = RepeatTracker()
        moves = []
        repeat = {"delay_ms": 100, "interval_ms": 50, "soft_delay_ms": 20, "soft_interval_ms": 18}
        for now in range(0, 1001, 16):
            tracker.update({"move_left"}, now, lambda a: moves.append(now) or False, **repeat)
        self.assertLessEqual(max(moves.count(t) for t in set(moves)), 1, "1回の判定で何度も動こうとした")


if __name__ == "__main__":
    unittest.main()
