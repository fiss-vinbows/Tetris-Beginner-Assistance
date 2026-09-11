"""7種テトリミノの回転形状定義（SRS: Super Rotation System準拠）

各ミノは4x4グリッド内の座標リスト（0=状態spawn, 1=右回転, 2=180度, 3=左回転）として定義する。
座標は (row, col)。row=0が上、col=0が左。
"""

from __future__ import annotations

PieceShape = list[tuple[int, int]]

# spawn状態の形状のみを保持し、回転はSRSの回転テーブルに基づき動的に導出する
PIECE_SPAWN_SHAPES: dict[str, PieceShape] = {
    "I": [(1, 0), (1, 1), (1, 2), (1, 3)],
    "O": [(0, 1), (0, 2), (1, 1), (1, 2)],
    "T": [(0, 1), (1, 0), (1, 1), (1, 2)],
    "S": [(0, 1), (0, 2), (1, 0), (1, 1)],
    "Z": [(0, 0), (0, 1), (1, 1), (1, 2)],
    "J": [(0, 0), (1, 0), (1, 1), (1, 2)],
    "L": [(0, 2), (1, 0), (1, 1), (1, 2)],
}

ALL_PIECES: list[str] = list(PIECE_SPAWN_SHAPES.keys())


def _rotate_cw(shape: PieceShape, size: int) -> PieceShape:
    """4x4（Iは実質4x4、その他も4x4基準）グリッド内で時計回りに90度回転"""
    return [(c, size - 1 - r) for r, c in shape]


def build_rotation_states(piece: str) -> list[PieceShape]:
    """spawn状態から時計回りに4状態（0,1,2,3）を生成する"""
    size = 4
    shapes = [PIECE_SPAWN_SHAPES[piece]]
    for _ in range(3):
        shapes.append(_rotate_cw(shapes[-1], size))
    return shapes


PIECE_ROTATION_STATES: dict[str, list[PieceShape]] = {
    piece: build_rotation_states(piece) for piece in ALL_PIECES
}

# Oミノは回転しても見た目が変わらないため回転状態を1つに制限してよいが、
# 探索の統一性のため4状態は保持し、solver側で重複探索を避ける
