"""画像認識の別プロセス化(src/recognize_process.py)のテスト。

【2026-10-31・利用者の指摘(ローカル対戦で双方とも遅すぎる)】1P と 2P の認識が同じプロセスで取り合いになり、
1回 75ms → 約125ms に遅くなった。1P と 2P を同時に動かす時は、側ごとの子プロセスで撮影と認識をする。
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

from src import app  # noqa: E402
from src.capture.window_detect import GameWindow, layout_calibration  # noqa: E402
from tests.test_assist_worker import _make_calibration, _recognition  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


@unittest.skipUnless(sys.platform == "win32", "Windows だけ")
class TestRecognizerProcess(unittest.TestCase):
    def test_child_process_recognizes_and_closes(self) -> None:
        from src.recognize_process import RecognizerProcess

        recognizer = RecognizerProcess()
        try:
            # 実際の画面を撮って認識する(ゲームが映っていなければ None)。子プロセスとのやり取りが通ればよい
            cal = layout_calibration(GameWindow(1, "", 0, 0, 800, 450))
            result = recognizer.recognize(cal, previous_piece_hint=None)
            self.assertTrue(result is None or isinstance(result, app.RecognitionResult))
        finally:
            recognizer.close()
        self.assertFalse(recognizer._process.is_alive(), "子プロセスが残った")


class TestWorkerUsesChildProcess(unittest.TestCase):
    def _worker(self):
        worker = app.AssistWorker(_make_calibration(), MagicMock(), None, separate_recognition=True)
        worker.cold_clear.poll_suggestion.return_value = None
        return worker

    def test_recognition_comes_from_the_child(self) -> None:
        worker = self._worker()
        worker._recognizer = MagicMock()
        worker._recognizer.recognize.return_value = _recognition(current_piece="T")
        with patch("src.app.recognize", side_effect=AssertionError("このスレッドで認識した")):
            worker._tick_once(capture=MagicMock())
        worker._recognizer.recognize.assert_called_once()
        self.assertEqual(worker._last_current_piece, "T")

    def test_falls_back_when_the_child_fails(self) -> None:
        worker = self._worker()
        broken = MagicMock()
        broken.recognize.side_effect = TimeoutError("応答なし")
        worker._recognizer = broken
        with patch("src.app.recognize", return_value=_recognition(current_piece="L")) as local:
            worker._tick_once(capture=MagicMock())
            worker._tick_once(capture=MagicMock())
        broken.close.assert_called_once()
        self.assertIsNone(worker._recognizer, "動かない子プロセスを使い続けている")
        self.assertEqual(local.call_count, 2, "子プロセスが動かない時に、このスレッドで認識していない")


if __name__ == "__main__":
    unittest.main()
