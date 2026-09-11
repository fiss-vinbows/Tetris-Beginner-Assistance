"""キャリブレーションの矢印キー微調整ロジック(adjust_calibration_rect)の単体テスト。

盤面の2点クリックだけでは、マウスでピクセル単位に正確に角をクリックするのは
人間には難しく数pxのズレが生じやすい。このズレがマス境界の色誤判定の一因と
疑われたため、クリック後に10x20グリッド線を実際のゲーム画面に重ねて表示し、
矢印キーで見た目に合わせて微調整できるようにした。その調整計算部分を
Qtのイベントループなしで検証する。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt6 import QtCore

from src.capture.calibrate import adjust_calibration_rect

Key = QtCore.Qt.Key


class AdjustCalibrationRectTest(unittest.TestCase):
    def test_left_arrow_moves_rect_without_resize(self) -> None:
        rect = (100, 200, 300, 400)
        result = adjust_calibration_rect(rect, Key.Key_Left, resize=False)
        self.assertEqual(result, (99, 200, 300, 400))

    def test_right_down_arrows_move_rect_without_resize(self) -> None:
        rect = (100, 200, 300, 400)
        result = adjust_calibration_rect(rect, Key.Key_Right, resize=False)
        self.assertEqual(result, (101, 200, 300, 400))
        result = adjust_calibration_rect(rect, Key.Key_Down, resize=False)
        self.assertEqual(result, (100, 201, 300, 400))

    def test_shift_right_arrow_grows_width_only(self) -> None:
        rect = (100, 200, 300, 400)
        result = adjust_calibration_rect(rect, Key.Key_Right, resize=True)
        # 位置(x, y)は変わらず、右下の角だけが動く(=幅が増える)。
        self.assertEqual(result, (100, 200, 301, 400))

    def test_shift_left_arrow_shrinks_width_only(self) -> None:
        rect = (100, 200, 300, 400)
        result = adjust_calibration_rect(rect, Key.Key_Left, resize=True)
        self.assertEqual(result, (100, 200, 299, 400))

    def test_shift_resize_does_not_shrink_below_one_pixel(self) -> None:
        # 幅・高さが1pxを下回ると盤面として意味をなさなくなるため、
        # 際限なく縮小できないようにする。
        rect = (100, 200, 1, 1)
        result = adjust_calibration_rect(rect, Key.Key_Left, resize=True)
        self.assertEqual(result, (100, 200, 1, 1))

    def test_non_arrow_key_returns_none(self) -> None:
        rect = (100, 200, 300, 400)
        self.assertIsNone(adjust_calibration_rect(rect, Key.Key_Return, resize=False))
        self.assertIsNone(adjust_calibration_rect(rect, Key.Key_A, resize=True))


if __name__ == "__main__":
    unittest.main()
