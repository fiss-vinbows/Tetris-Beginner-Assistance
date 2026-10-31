"""Steam 版ぷよぷよテトリス2のウィンドウ検出(src/capture/window_detect.py)のテスト。

【2026-10-30・利用者の要望】Steam 版でウィンドウから盤面・HOLD・NEXT の位置を求める機能を標準にする。
位置は利用者のスクリーンショット(描画領域 2560×1440)で測った。tests/fixtures/steam_1440p_tetris_1p.png は
その描画領域の x 240〜1080・y 170〜1180(1P の盤面・HOLD・NEXT だけ)を切り出したもの。
"""

from __future__ import annotations

import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tests.config_isolation  # noqa: E402,F401  本番の設定・プラグインを使わない
import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PyQt6 import QtWidgets  # noqa: E402

from src import plugin_loader  # noqa: E402
from src.capture import window_detect  # noqa: E402
from src.capture.window_detect import (  # noqa: E402
    GameWindow,
    SavedWindow,
    WindowEntry,
    find_game_window,
    layout_calibration,
    save_saved_window,
)

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "steam_1440p_tetris_1p.png"
CROP_ORIGIN = (240, 170)  # 切り出した範囲の左上(描画領域の座標)
REPO_PLUGINS = Path(__file__).resolve().parent.parent / "plugins"


def _entry(title: str, exe: str, width: int = 1920, height: int = 1080, hwnd: int = 1) -> WindowEntry:
    return WindowEntry(GameWindow(hwnd, title, 100, 50, width, height), exe)


class TestLayout(unittest.TestCase):
    def test_reference_size_is_the_measured_layout(self) -> None:
        cal = layout_calibration(GameWindow(1, "PuyoPuyoTetris2", 214, 237, 2560, 1440))
        self.assertEqual((cal.board_origin_x, cal.board_origin_y), (214 + 409, 237 + 211))
        self.assertEqual((cal.board_width, cal.board_height, cal.cell_size), (480, 960, 48))
        self.assertEqual(cal.hold_rect, (214 + 263, 237 + 263, 124, 77))
        self.assertEqual(len(cal.next_rects), 5)

    def test_scaled_to_1080p(self) -> None:
        cal = layout_calibration(GameWindow(1, "", 0, 0, 1920, 1080))
        self.assertEqual((cal.board_width, cal.board_height, cal.cell_size), (360, 720, 36))
        self.assertAlmostEqual(cal.board_origin_x, 409 * 0.75, delta=1)

    def test_letterbox_when_not_16_9(self) -> None:
        # 横に広いウィンドウ: 高さに合わせて縮め、左右に黒帯(中央に描かれる)
        cal = layout_calibration(GameWindow(1, "", 0, 0, 2000, 900))
        scale = 900 / 1440
        self.assertAlmostEqual(cal.board_origin_x, (2000 - 2560 * scale) / 2 + 409 * scale, delta=1)
        self.assertAlmostEqual(cal.board_origin_y, 211 * scale, delta=1)


class TestRecognitionOnScreenshot(unittest.TestCase):
    def test_reads_the_screenshot_with_the_layout(self) -> None:
        from src.app import recognize

        crop = cv2.imdecode(np.fromfile(FIXTURE, dtype=np.uint8), cv2.IMREAD_COLOR)[:, :, ::-1]  # RGB
        client = np.zeros((1440, 2560, 3), dtype=np.uint8)
        x0, y0 = CROP_ORIGIN
        client[y0:y0 + crop.shape[0], x0:x0 + crop.shape[1]] = crop

        class ImageCapture:
            def grab(self, region):
                return client[region.top:region.top + region.height, region.left:region.left + region.width].copy()

        rec = recognize(layout_calibration(GameWindow(1, "PuyoPuyoTetris2", 0, 0, 2560, 1440)), ImageCapture())
        self.assertIsNotNone(rec)
        self.assertEqual(rec.current_piece, "S")
        self.assertTrue(rec.hold_known)
        self.assertIsNone(rec.hold_piece)
        self.assertEqual(tuple(rec.next_queue), ("L", "O", "I", "J", "T"))
        self.assertFalse(any(cell for row in rec.board.grid for cell in row), "着地予想の影をブロックと読んだ")


class TestRecognition2P(unittest.TestCase):
    """【2026-10-31】2P の位置のずれ(10px)で、おじゃまの穴が埋まった行と読まれ、2P の全自動が止まった。

    tests/fixtures/steam_1440p_tetris_2p_garbage.png は実機の録画(debug_capture_20261031_095936_2p、2560×1440 の原寸)の
    1コマ。直す前の 2P の位置で切り出した範囲なので、描画領域の (263 + 1269, 209) に貼る。
    """

    def test_garbage_holes_are_read(self) -> None:
        from src.app import recognize

        frame = cv2.imdecode(np.fromfile(FIXTURE.with_name("steam_1440p_tetris_2p_garbage.png"), dtype=np.uint8), cv2.IMREAD_COLOR)
        client = np.zeros((1440, 2560, 3), dtype=np.uint8)
        x0, y0 = 263 + 1269, 209
        client[y0:y0 + frame.shape[0], x0:x0 + frame.shape[1]] = frame[:, :, ::-1]  # RGB

        class ImageCapture:
            def grab(self, region):
                return client[region.top:region.top + region.height, region.left:region.left + region.width].copy()

        rec = recognize(layout_calibration(GameWindow(1, "PuyoPuyoTetris2", 0, 0, 2560, 1440), "2p"), ImageCapture())
        holes = {r: [c for c in range(10) if rec.board.grid[r][c] is None] for r in range(11, 20)}
        # 画像のおじゃまの穴: 11段目は2列目、12・13段目は6列目、14段目は5列目、15〜19段目は10列目
        self.assertEqual(holes, {11: [1], 12: [5], 13: [5], 14: [4], 15: [9], 16: [9], 17: [9], 18: [9], 19: [9]})
        self.assertFalse(
            any(all(cell is not None for cell in row) for row in rec.board.grid), "おじゃまの行を揃った行と読んだ"
        )


class TestFindGameWindow(unittest.TestCase):
    def setUp(self) -> None:
        window_detect.SAVED_WINDOW_PATH.unlink(missing_ok=True)

    def test_by_title_or_exe_and_the_largest(self) -> None:
        entries = [
            _entry("TBA (Tetris Beginner Assistance)", "pythonw.exe", hwnd=1),
            _entry("PuyoPuyoTetris2", "puyopuyotetris2.exe", 1280, 720, hwnd=2),
            _entry("ぷよぷよテトリス2", "", 2560, 1440, hwnd=3),
        ]
        self.assertEqual(find_game_window(windows=entries).hwnd, 3)
        self.assertIsNone(find_game_window(windows=entries[:1]))

    def test_saved_window_is_found(self) -> None:
        entries = [_entry("別の名前", "mygame.exe", hwnd=7)]
        self.assertIsNone(find_game_window(windows=entries))
        save_saved_window(SavedWindow(exe="mygame.exe"))
        self.assertEqual(find_game_window(windows=entries).hwnd, 7, "一覧から選んだウィンドウを次から探せない")


class TestMainWindow(unittest.TestCase):
    def setUp(self) -> None:
        shutil.rmtree(plugin_loader.PLUGIN_DIR, ignore_errors=True)
        plugin_loader.CONFIG_PATH.unlink(missing_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(plugin_loader.PLUGIN_DIR, ignore_errors=True)

    def _window(self, found: GameWindow | None):
        from src import app

        with patch.object(app, "find_game_window", return_value=found):
            window = app.MainWindow()
        window.show()
        return window

    def test_window_is_used_and_manual_calibration_is_a_plugin(self) -> None:
        from src import app

        game = GameWindow(5, "PuyoPuyoTetris2", 10, 20, 2560, 1440)
        window = self._window(game)
        try:
            self.assertFalse(window.calibrate_btn.isVisible(), "プラグインが無いのに手動キャリブレーションが出ている")
            self.assertIn("PuyoPuyoTetris2", window.status_label.text())
            with patch.object(app, "find_game_window", return_value=game):
                cal = window._resolve_calibration()
            self.assertEqual(cal, layout_calibration(game), "見つかったウィンドウの位置を使っていない")
            with patch.object(app, "find_game_window", return_value=None):
                self.assertIsNone(window._resolve_calibration(), "プラグインが無いのに手動キャリブレーションを使った")
        finally:
            window.close()
        shutil.copytree(REPO_PLUGINS / "switch_capture", plugin_loader.PLUGIN_DIR / "switch_capture")
        window = self._window(None)
        try:
            self.assertTrue(window.calibrate_btn.isVisible())
        finally:
            window.close()

    def test_moving_the_window_stops_assist_mode(self) -> None:
        from src import app

        window = self._window(None)
        try:
            window._game_window = GameWindow(5, "PuyoPuyoTetris2", 10, 20, 2560, 1440)
            window.assist_mode = True
            stopped = []
            window._stop_assist_mode = lambda: stopped.append(True)
            with patch.object(app, "client_rect", return_value=(10, 20, 2560, 1440)):
                window._check_game_window()
            self.assertFalse(stopped, "動いていないのに止めた")
            with patch.object(app, "client_rect", return_value=(60, 20, 2560, 1440)), \
                    patch.object(QtWidgets.QMessageBox, "information"):
                window._check_game_window()
            self.assertTrue(stopped, "ウィンドウが動いたのに止めていない")
        finally:
            window.assist_mode = False
            window.close()


class TestBadgePlacement(unittest.TestCase):
    """【2026-10-30・利用者の要望】止めるボタンはゲームのタイトルバーの中央、状態の表示(情報パネル)は左下。"""

    def test_stop_button_on_title_bar_and_info_at_bottom_left(self) -> None:
        from src import app

        game = GameWindow(5, "PuyoPuyoTetris2", 214, 237, 2560, 1440)
        badge = app.ControlBadge(on_stop=lambda: None)
        try:
            with patch.object(app, "title_bar_rect", return_value=(212, 192, 2564, 45)):
                badge.place(game)
            # Win32 の位置(物理ピクセル)を Qt の位置(論理ピクセル)に直して比べる
            dpr = QtWidgets.QApplication.primaryScreen().devicePixelRatio()
            self.assertEqual(badge.y(), round(192 / dpr), "タイトルバーに重なっていない")
            self.assertEqual(badge.height(), round(45 / dpr))
            self.assertAlmostEqual(badge.x() + badge.width() / 2, (212 + 2564 / 2) / dpr, delta=1, msg="タイトルバーの中央でない")
            self.assertEqual(badge.info.x(), round(214 / dpr) + 12, "情報パネルが左下にない")
            self.assertEqual(badge.info.y() + badge.info.height(), round((237 + 1440) / dpr) - 12)
        finally:
            badge.close()

    def test_without_game_window_top_right(self) -> None:
        from src import app

        badge = app.ControlBadge(on_stop=lambda: None)
        try:
            badge.place(None)  # Switch のキャプチャ等: 従来どおり画面の右上
            screen = QtWidgets.QApplication.primaryScreen().geometry()
            self.assertEqual(badge.x() + badge.width(), screen.width() - 20)
            self.assertGreater(badge.info.y(), badge.y())
        finally:
            badge.close()


if __name__ == "__main__":
    unittest.main()
