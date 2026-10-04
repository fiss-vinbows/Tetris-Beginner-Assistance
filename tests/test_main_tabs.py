"""起動画面のタブ(支援モード・シミュレーター・無限中あけREN)のテスト。

【2026-10-04・利用者の要望】別画面にせずタブで切り替える。タブで表示していないものは思考しない。
支援モード中は他のタブへ切り替えられない。
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tests.config_isolation  # noqa: E402,F401  本番の設定ファイルを使わない
from PyQt6 import QtWidgets  # noqa: E402

from src.app import MainWindow  # noqa: E402
from tests.test_education_advisor import FakeEngine  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


class TestMainTabs(unittest.TestCase):
    def setUp(self) -> None:
        self.window = MainWindow()
        self.window.show()

    def tearDown(self) -> None:
        self.window.close()

    def test_tabs_and_lazy_creation(self) -> None:
        tabs = self.window.tabs
        self.assertEqual([tabs.tabText(i) for i in range(tabs.count())], ["支援モード", "シミュレーター", "無限中あけREN"])
        self.assertIsNone(self.window.practice_window, "開くまで作らない")
        tabs.setCurrentIndex(MainWindow.TAB_PRACTICE)
        practice = self.window.practice_window
        self.assertIsNotNone(practice)
        self.assertFalse(practice.isWindow(), "別画面ではなくタブの中に入れる")
        tabs.setCurrentIndex(MainWindow.TAB_REN)
        self.assertIsNotNone(self.window.ren_window)
        self.assertFalse(self.window.ren_window.isWindow())

    def test_hidden_simulator_does_not_think(self) -> None:
        tabs = self.window.tabs
        tabs.setCurrentIndex(MainWindow.TAB_PRACTICE)
        practice = self.window.practice_window
        practice.advisor.engine_factory = FakeEngine
        practice.advisor.preferred_id = "cc2"
        practice.advisor.update(practice.state)
        self.assertTrue(practice.pad_timer.isActive())
        tabs.setCurrentIndex(MainWindow.TAB_ASSIST)
        self.assertFalse(practice.pad_timer.isActive(), "表示していないのに定期処理が動いている")
        self.assertIsNone(practice.advisor._engine, "表示していないのにAIが動いている")
        tabs.setCurrentIndex(MainWindow.TAB_PRACTICE)
        self.assertTrue(practice.pad_timer.isActive(), "表示したら再開する")
        tabs.setCurrentIndex(MainWindow.TAB_REN)
        ren = self.window.ren_window
        self.assertTrue(ren.timer.isActive())
        tabs.setCurrentIndex(MainWindow.TAB_ASSIST)
        self.assertFalse(ren.timer.isActive())

    def test_other_tabs_are_locked_during_assist(self) -> None:
        self.window._set_other_tabs_enabled(False)
        self.assertFalse(self.window.tabs.isTabEnabled(MainWindow.TAB_PRACTICE))
        self.assertFalse(self.window.tabs.isTabEnabled(MainWindow.TAB_REN))
        self.window._set_other_tabs_enabled(True)
        self.assertTrue(self.window.tabs.isTabEnabled(MainWindow.TAB_PRACTICE))


if __name__ == "__main__":
    unittest.main()
