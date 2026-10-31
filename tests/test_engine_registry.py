"""思考エンジンの登録と選択(src/engine/registry.py・src/engine_dialog.py)のテスト。

【2026-10-31・利用者の要望】PBA のようにエンジン登録と思考エンジン選択を標準機能にする。
選んだエンジンは支援モード・全自動・シミュレーターで使う。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tests.config_isolation  # noqa: E402,F401  本番の設定ファイル・プラグインを使わない
from PyQt6 import QtWidgets  # noqa: E402

from src.engine import registry  # noqa: E402
from src.engine.registry import DEFAULT_ENGINE, NO_ENGINE, EngineEntry, Registry, available_engines, selected_engine  # noqa: E402
from src.engine_dialog import EngineRegistryDialog  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


class TestRegistry(unittest.TestCase):
    def setUp(self) -> None:
        registry.REGISTRY_PATH.unlink(missing_ok=True)
        self.exe = Path(tempfile.mkdtemp()) / "my_ai.exe"
        self.exe.write_bytes(b"")

    def test_default_is_cold_clear(self) -> None:
        self.assertEqual(selected_engine(), (DEFAULT_ENGINE, None))

    def test_registered_engine_is_selected_and_remembered(self) -> None:
        Registry([EngineEntry("自作AI", str(self.exe))], "自作AI").save()
        name, engine = selected_engine()
        self.assertEqual(name, "自作AI")
        self.assertEqual(engine, (self.exe, None))
        self.assertEqual(list(available_engines()), [DEFAULT_ENGINE, "自作AI"])

    def test_2p_not_used_by_default(self) -> None:
        self.assertEqual(selected_engine(side="2p"), (NO_ENGINE, None))

    def test_missing_selection_falls_back_to_cold_clear(self) -> None:
        Registry([], "消したAI").save()
        self.assertEqual(selected_engine()[0], DEFAULT_ENGINE)

    def test_dialog_rejects_reserved_and_missing(self) -> None:
        dialog = EngineRegistryDialog(Registry(), reserved={"プラグインAI"})
        self.assertIsNotNone(dialog.add_engine(DEFAULT_ENGINE, str(self.exe)))
        self.assertIsNotNone(dialog.add_engine("プラグインAI", str(self.exe)))
        self.assertIsNotNone(dialog.add_engine("無いAI", str(self.exe) + ".none"))
        self.assertIsNone(dialog.add_engine("自作AI", str(self.exe)))
        self.assertIsNotNone(dialog.add_engine("自作AI", str(self.exe)), "同じ名前を2回登録できた")
        self.assertEqual([e.name for e in dialog.engines], ["自作AI"])


class TestMainWindowEngineCombo(unittest.TestCase):
    def setUp(self) -> None:
        registry.REGISTRY_PATH.unlink(missing_ok=True)

    def test_combo_lists_and_saves_selection(self) -> None:
        from unittest.mock import patch

        from src import app

        exe = Path(tempfile.mkdtemp()) / "my_ai.exe"
        exe.write_bytes(b"")
        Registry([EngineEntry("自作AI", str(exe))]).save()
        with patch.object(app, "find_game_window", return_value=None):
            window = app.MainWindow()
        try:
            one, two, solo = (window.side_boxes[k].engine_combo for k in ("1p", "2p", "solo"))
            self.assertEqual([one.itemText(i) for i in range(one.count())], [DEFAULT_ENGINE, "自作AI"])
            self.assertEqual(two.itemText(0), NO_ENGINE, "2P に「使わない」が無い")
            self.assertEqual(two.currentText(), NO_ENGINE, "2P の初めは「使わない」")
            self.assertEqual(one.currentText(), DEFAULT_ENGINE)
            one.setCurrentText("自作AI")
            two.setCurrentText(DEFAULT_ENGINE)
            solo.setCurrentText("自作AI")
            loaded = Registry.load()
            self.assertEqual(loaded.selected, "自作AI", "1P で選んだエンジンを覚えていない")
            self.assertEqual(selected_engine(loaded, "2p")[0], DEFAULT_ENGINE)
            self.assertEqual(selected_engine(loaded, "solo")[0], "自作AI")
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
