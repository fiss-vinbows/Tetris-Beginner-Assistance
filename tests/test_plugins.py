"""プラグイン方式(src/plugin_api.py・src/plugin_loader.py)のテスト。

【2026-10-30・利用者の要望】PBA(../Puyopuyo)と同じ形のプラグイン方式にする。全自動モード・ログ出力・
思考エンジンはプラグインが足し、配布してよいプラグインだけを配布物に入れる。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tests.config_isolation  # noqa: E402,F401  本番の設定ファイル・プラグインを使わない
from PyQt6 import QtWidgets  # noqa: E402

from src import plugin_loader  # noqa: E402
from src.plugin_loader import PluginManager, discover, save_disabled  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
REPO_PLUGINS = Path(__file__).resolve().parent.parent / "plugins"


def _write(folder: Path, body: str) -> None:
    folder.mkdir(parents=True)
    (folder / "plugin.py").write_text("from src.plugin_api import Plugin\n" + body, encoding="utf-8")


class TestLoader(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="tba_plugins_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_discover_and_errors(self) -> None:
        _write(self.dir / "a", 'PLUGIN = Plugin(id="a", name="A", full_auto=True)\n')
        _write(self.dir / "broken", "PLUGIN = 1 / 0\n")
        _write(self.dir / "wrong", "PLUGIN = 3\n")
        plugins, errors = discover(self.dir)
        self.assertEqual([p.id for p in plugins], ["a"])
        self.assertIn("ZeroDivisionError", errors["broken"], "1つのプラグインの不具合で止めない")
        self.assertIn("wrong", errors)

    def test_disabled_plugins_do_not_count(self) -> None:
        _write(self.dir / "auto", 'PLUGIN = Plugin(id="auto", name="全自動", full_auto=True)\n')
        _write(self.dir / "log", 'PLUGIN = Plugin(id="log", name="ログ", debug_log=True)\n')
        config = self.dir / "plugins.json"
        manager = PluginManager.load(self.dir, config)
        self.assertTrue(manager.full_auto() and manager.debug_log(), "新しく置いたプラグインは有効で始まる")
        save_disabled({"auto"}, config)
        manager = PluginManager.load(self.dir, config)
        self.assertFalse(manager.full_auto())
        self.assertTrue(manager.debug_log())

    def test_bundled_plugins(self) -> None:
        plugins, errors = discover(REPO_PLUGINS)
        self.assertFalse(errors)
        by_id = {p.id: p for p in plugins}
        self.assertTrue(by_id["full_auto"].full_auto)
        self.assertFalse(by_id["full_auto"].distributable, "全自動モードは配布しない")
        self.assertTrue(by_id["debug_log"].debug_log)
        self.assertFalse(by_id["debug_log"].distributable, "ログ・録画は画面の画像を含むので配布しない")


class TestMainWindow(unittest.TestCase):
    def setUp(self) -> None:
        shutil.rmtree(plugin_loader.PLUGIN_DIR, ignore_errors=True)
        plugin_loader.CONFIG_PATH.unlink(missing_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(plugin_loader.PLUGIN_DIR, ignore_errors=True)

    def _window(self):
        from src.app import MainWindow

        window = MainWindow()
        window.show()
        return window

    def test_items_appear_only_with_their_plugins(self) -> None:
        window = self._window()
        try:
            self.assertFalse(window.side_boxes["1p"].autoplay_box.isVisible(), "プラグインが無いのに全自動モードが出ている")
            self.assertFalse(window.debug_log_checkbox.isVisible())
        finally:
            window.close()
        shutil.copytree(REPO_PLUGINS / "full_auto", plugin_loader.PLUGIN_DIR / "full_auto")
        shutil.copytree(REPO_PLUGINS / "debug_log", plugin_loader.PLUGIN_DIR / "debug_log")
        window = self._window()
        try:
            self.assertTrue(window.side_boxes["1p"].autoplay_box.isVisible())
            self.assertTrue(window.side_boxes["solo"].autoplay_box.isVisibleTo(window.side_boxes["solo"]))
            self.assertFalse(window.side_boxes["2p"].autoplay_box.isVisible(), "ローカル対戦プラグインが無いのに 2P の全自動が出ている")
            self.assertTrue(window.auto_settings_btn.isVisible())
            self.assertTrue(window.debug_log_checkbox.isVisible())
            self.assertTrue(window.record_video_checkbox.isVisible())
            window.debug_log_checkbox.setChecked(True)
            window.plugins.disabled = {"debug_log"}
            window._apply_plugins()
            self.assertFalse(window.debug_log_checkbox.isVisible())
            self.assertFalse(window.debug_log_checkbox.isChecked(), "隠した項目がオンのまま残る")
        finally:
            window.close()


class TestBuild(unittest.TestCase):
    def test_only_distributable_plugins_are_copied(self) -> None:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
        import build_exe

        source = Path(tempfile.mkdtemp(prefix="tba_plugins_src_"))
        target = Path(tempfile.mkdtemp(prefix="tba_plugins_dst_")) / "plugins"
        try:
            _write(source / "public", 'PLUGIN = Plugin(id="public", name="公開")\n')
            _write(source / "_private", 'PLUGIN = Plugin(id="private", name="非公開", distributable=False)\n')
            copied = build_exe.copy_distributable_plugins(source, target)
            self.assertEqual(copied, ["public"])
            self.assertTrue((target / "public" / "plugin.py").exists())
            self.assertFalse((target / "_private").exists(), "配布しないプラグインが配布物に入った")
        finally:
            shutil.rmtree(source, ignore_errors=True)
            shutil.rmtree(target.parent, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
