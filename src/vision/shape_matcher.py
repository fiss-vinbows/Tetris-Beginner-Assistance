"""盤面上で検出した4マスの連結形状から、色を使わずにミノ種類を判定する。

色ベースの判定（ミノ描画のグロス効果による明度ムラ、I/Jの色相が非常に近い等）は
盤面認識のノイズに弱く、実機で誤判定が頻発した（IとJの混同、Sミノの検出失敗など）。
テトリミノは7種・全回転状態を通じて形状が完全に一意（重複なし、事前検証済み）なため、
盤面上の4マス連結パターンを正規化して形状マッチングする方がずっと頑健。
"""

from __future__ import annotations

from src.engine.piece_defs import ALL_PIECES, PIECE_ROTATION_STATES


def _normalize(cells: frozenset[tuple[int, int]]) -> frozenset[tuple[int, int]]:
    """セル集合を、最小の(row,col)が(0,0)になるよう平行移動する"""
    min_r = min(r for r, _c in cells)
    min_c = min(c for _r, c in cells)
    return frozenset((r - min_r, c - min_c) for r, c in cells)


def _build_shape_table() -> dict[frozenset[tuple[int, int]], str]:
    table: dict[frozenset[tuple[int, int]], str] = {}
    for piece in ALL_PIECES:
        for shape in PIECE_ROTATION_STATES[piece]:
            table[_normalize(frozenset(shape))] = piece
    return table


# 各ミノの全回転状態の正規化済み形状(19パターン、重複なし) → ミノ名
_SHAPE_TO_PIECE: dict[frozenset[tuple[int, int]], str] = _build_shape_table()


def match_piece_shape(cells: set[tuple[int, int]] | frozenset[tuple[int, int]]) -> str | None:
    """4マスの絶対座標集合から、一致するミノ種類名を返す。一致しなければNone。"""
    if len(cells) != 4:
        return None
    normalized = _normalize(frozenset(cells))
    return _SHAPE_TO_PIECE.get(normalized)
