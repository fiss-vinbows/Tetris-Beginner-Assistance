"""overlay/renderer.pyの座標計算ロジックのテスト。

_cell_rectは「盤面上のどこに着地マスの提案ドットを描くか」を決める
唯一の計算箇所で、ここがずれると「提示がおかしい」「提示がずれる」
という症状に直結する。QPainter描画そのものはピクセル比較が必要で
テストしにくいが、座標計算自体は純粋関数として検証できる。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.overlay.renderer import BoardLayout, _cell_rect


class TestCellRect(unittest.TestCase):
    def setUp(self) -> None:
        self.layout = BoardLayout(
            board_origin_x=100,
            board_origin_y=50,
            cell_size=30,
            hold_rect=(10, 10, 80, 60),
        )

    def test_top_left_cell_starts_at_board_origin(self) -> None:
        x, y, w, h = _cell_rect(self.layout, row=0, col=0)
        self.assertEqual((x, y, w, h), (100, 50, 30, 30))

    def test_cell_offset_scales_with_cell_size(self) -> None:
        x, y, w, h = _cell_rect(self.layout, row=2, col=3)
        self.assertEqual((x, y), (100 + 3 * 30, 50 + 2 * 30))
        self.assertEqual((w, h), (30, 30))

    def test_different_row_and_col_do_not_get_swapped(self) -> None:
        # rowとcolを取り違えると、盤面上で提案が90度回転したようにずれる
        # (実機で報告された「ずれ問題」の典型的な原因になりうる)ため、
        # x軸=col、y軸=rowの対応を固定テストで保護する。
        x, y, _w, _h = _cell_rect(self.layout, row=1, col=5)
        self.assertEqual(x, self.layout.board_origin_x + 5 * self.layout.cell_size)
        self.assertEqual(y, self.layout.board_origin_y + 1 * self.layout.cell_size)


class TestCellRectFractionalCellSize(unittest.TestCase):
    """【2026-09-07・実機で発見】DPIスケール環境での丸め誤差蓄積の回帰テスト。

    以前はOverlayWindow.paintEvent側でcell_sizeを整数に丸めてからBoardLayoutへ
    渡していたため、_cell_rectがその丸め済みの値を列・行数分掛け算する際に
    誤差が蓄積し、盤面の下・右のセルほど実機オーバーレイの表示位置が本来の
    座標から大きくズレていた(録画への合成は丸めを介さないためズレなかった)。
    cell_sizeが割り切れない値(DPR=1.25相当)でも、_cell_rectが受け取った
    floatをそのまま使い、丸めていないことを確認する。
    """

    def setUp(self) -> None:
        # 物理cell_size=47をDPR=1.25で割った37.6を想定(丸めると38になり、
        # 19行分で(38-37.6)*19=7.6論理px、DPRを掛け戻すと約9.5物理pxもの
        # ズレになる不具合があった)。
        self.layout = BoardLayout(
            board_origin_x=118.4,
            board_origin_y=0.0,
            cell_size=37.6,
            hold_rect=(10, 10, 80, 60),
        )

    def test_cell_size_is_not_rounded_before_multiplication(self) -> None:
        x, y, w, h = _cell_rect(self.layout, row=19, col=0)
        # 丸めた場合(38*19=722)ではなく、真の値(37.6*19=714.4)で
        # 計算されていることを確認する。
        self.assertAlmostEqual(y, 0.0 + 19 * 37.6)
        self.assertNotAlmostEqual(y, 19 * 38, delta=0.01)
        self.assertAlmostEqual(w, 37.6)
        self.assertAlmostEqual(h, 37.6)


if __name__ == "__main__":
    unittest.main()
