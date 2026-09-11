"""shape_matcher.pyの形状一意性テスト。

_infer_current_piece(app.py)は「テトリミノは7種・全回転状態を通じて形状が
完全に一意」という前提の上で、色に頼らず形状だけでミノ種類を判定している。
この前提が崩れる(piece_defs.pyの回転定義が変更された等で、異なるミノが
同じ正規化形状を持つようになる)と、色ベースの判定より頑健なはずの
形状マッチングが特定のミノを別のミノと誤認識し続けるという、気付きにくい
形で盤面認識全体が壊れる。そのため前提そのものを固定テストで保護する。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine.piece_defs import ALL_PIECES, PIECE_ROTATION_STATES
from src.vision.shape_matcher import _normalize, match_piece_shape


class TestShapeUniqueness(unittest.TestCase):
    def test_every_rotation_state_maps_back_to_its_own_piece(self) -> None:
        # 全ミノ・全回転状態について、その形状で照会すると必ず元のミノ名が
        # 返ってくることを確認する(=異なるミノ同士で形状が衝突していない)。
        for piece in ALL_PIECES:
            for shape in PIECE_ROTATION_STATES[piece]:
                with self.subTest(piece=piece, shape=shape):
                    self.assertEqual(match_piece_shape(set(shape)), piece)

    def test_expected_number_of_distinct_normalized_shapes(self) -> None:
        # I/S/Zは180度回転で同じ形になるため2パターン、Oは4回転すべて同じで
        # 1パターン、非対称なJ/L/Tは4回転すべて異なり4パターンずつ
        # (2*3 + 1 + 4*3 = 19)。この内訳が崩れたら回転定義に意図しない
        # 変更が入ったサインとして検知する。
        normalized_shapes = {
            _normalize(frozenset(shape))
            for piece in ALL_PIECES
            for shape in PIECE_ROTATION_STATES[piece]
        }
        self.assertEqual(len(normalized_shapes), 19)

    def test_unrecognized_shape_returns_none(self) -> None:
        # 4マスでもテトリミノのどれとも一致しない形(2x2の正方形から1マスずれた
        # ようなL字もどき等ではなく、単純な一直線でも田の字でもない歪な塊)は
        # Noneを返す(=呼び出し側が色ベースのフォールバックに回せる)ことを確認する。
        not_a_tetromino = {(0, 0), (0, 2), (1, 0), (1, 2)}
        self.assertIsNone(match_piece_shape(not_a_tetromino))

    def test_wrong_cell_count_returns_none(self) -> None:
        self.assertIsNone(match_piece_shape({(0, 0), (0, 1), (0, 2)}))


if __name__ == "__main__":
    unittest.main()
