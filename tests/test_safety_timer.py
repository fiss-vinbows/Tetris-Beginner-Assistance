"""支援モードの自動解除の保険(2026-09-26)のテスト。

以前は開始から10分で必ず支援モードが解除された。提示が届くたびに数え直し、
提示が届かない(操作が無い)ときだけ解除する。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.app import SAFETY_TIMEOUT_MS, MainWindow  # noqa: E402


class TestSafetyTimerRestartsOnSuggestion(unittest.TestCase):
    def _window(self, active: bool) -> SimpleNamespace:
        timer = MagicMock()
        timer.isActive.return_value = active
        return SimpleNamespace(last_valid_draw_data=None, overlay=None, safety_timer=timer)

    def test_suggestion_restarts_the_timer(self) -> None:
        window = self._window(active=True)
        MainWindow._on_draw_data_ready(window, MagicMock())
        window.safety_timer.start.assert_called_once_with(SAFETY_TIMEOUT_MS)

    def test_cleared_suggestion_does_not_restart_the_timer(self) -> None:
        window = self._window(active=True)
        MainWindow._on_draw_data_ready(window, None)
        window.safety_timer.start.assert_not_called()

    def test_timer_is_not_started_after_the_assist_mode_stopped(self) -> None:
        window = self._window(active=False)
        MainWindow._on_draw_data_ready(window, MagicMock())
        window.safety_timer.start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
