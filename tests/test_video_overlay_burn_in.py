"""録画用フレームへの最善手ドット合成(_draw_suggestion_on_bgr_frame)の単体テスト。

オーバーレイウィンドウは自己汚染防止(_exclude_window_from_screen_capture)のため
画面キャプチャ全般から除外されており、debug_capture.mp4にも最善手の色ドットが
一切映らなかった。録画専用フレームにだけソフトウェア側で提案を焼き込む処理を
追加したため、その座標変換・描画結果を検証する。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.app import _draw_suggestion_on_bgr_frame
from src.capture.calibrate import CalibrationResult
from src.overlay.renderer import OverlayDrawData
from src.vision.piece_colors import PIECE_COLORS


def _make_calibration(cell_size: int = 30) -> CalibrationResult:
    return CalibrationResult(
        board_origin_x=100,
        board_origin_y=200,
        board_width=cell_size * 10,
        board_height=cell_size * 20,
        cell_size=cell_size,
        board_cols=10,
        board_rows=20,
        hold_rect=(0, 0, 1, 1),
        next_rects=[(0, 0, 1, 1)] * 5,
    )


class DrawSuggestionOnBgrFrameTest(unittest.TestCase):
    def test_draws_piece_color_at_landing_cell_center(self) -> None:
        calibration = _make_calibration(cell_size=30)
        frame = np.zeros((400, 400, 3), dtype=np.uint8)
        draw_data = OverlayDrawData(piece="T", landing_cells=[(2, 3)], use_hold=False)

        # region_origin(0, 0)は、_region_boundsが盤面の左上より外側(HOLD/NEXT欄含む)
        # を返すケースを想定し、あえて盤面原点とずらして座標変換の検証を兼ねる。
        _draw_suggestion_on_bgr_frame(frame, calibration, region_origin_x=50, region_origin_y=100, draw_data=draw_data)

        center_x = calibration.board_origin_x - 50 + 3 * calibration.cell_size + calibration.cell_size // 2
        center_y = calibration.board_origin_y - 100 + 2 * calibration.cell_size + calibration.cell_size // 2

        rgb = PIECE_COLORS["T"]
        expected_bgr = np.array([rgb.b, rgb.g, rgb.r])
        actual_bgr = frame[center_y, center_x]
        self.assertTrue(np.array_equal(actual_bgr, expected_bgr))

    def test_no_landing_cells_leaves_frame_untouched(self) -> None:
        calibration = _make_calibration()
        frame = np.zeros((400, 400, 3), dtype=np.uint8)
        draw_data = OverlayDrawData(piece="I", landing_cells=[], use_hold=False)

        _draw_suggestion_on_bgr_frame(frame, calibration, region_origin_x=0, region_origin_y=0, draw_data=draw_data)

        self.assertTrue(np.array_equal(frame, np.zeros((400, 400, 3), dtype=np.uint8)))

    def test_draws_white_outline_around_fill(self) -> None:
        calibration = _make_calibration(cell_size=30)
        frame = np.zeros((400, 400, 3), dtype=np.uint8)
        draw_data = OverlayDrawData(piece="O", landing_cells=[(0, 0)], use_hold=False)

        _draw_suggestion_on_bgr_frame(frame, calibration, region_origin_x=0, region_origin_y=0, draw_data=draw_data)

        center_x = calibration.board_origin_x + calibration.cell_size // 2
        center_y = calibration.board_origin_y + calibration.cell_size // 2
        radius = round(calibration.cell_size * 0.22)
        # ドット半径ぴったりの位置は白い縁取り(255,255,255)であるはず。
        outline_pixel = frame[center_y, center_x + radius]
        self.assertTrue(np.array_equal(outline_pixel, np.array([255, 255, 255])))


if __name__ == "__main__":
    unittest.main()
