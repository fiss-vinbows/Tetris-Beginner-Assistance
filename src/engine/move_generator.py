"""現在の盤面に対して、あるミノを置けるすべての候補手（回転×列）を列挙する"""

from __future__ import annotations

from dataclasses import dataclass

from .board_state import BoardState
from .piece_defs import PIECE_ROTATION_STATES

# 4x4グリッド基準の形状なので、はみ出しを考慮してこの範囲を走査すれば全候補を網羅できる
_ORIGIN_COL_SCAN_RANGE = range(-3, 13)


@dataclass
class Move:
    piece: str
    rotation: int
    origin_col: int
    origin_row: int
    landing_cells: list[tuple[int, int]]
    resulting_board: BoardState
    lines_cleared: int
    eroded_cells: int


def enumerate_moves(board: BoardState, piece: str) -> list[Move]:
    """ハードドロップで到達可能な全ての(回転, 列)候補を返す。

    Oミノのように回転しても実質同じ置き方になるケースは、
    最終的な着地マス集合の重複で自動的に除外される。
    """
    moves: list[Move] = []
    seen: set[frozenset[tuple[int, int]]] = set()

    for rotation in range(4):
        shape = PIECE_ROTATION_STATES[piece][rotation]
        for origin_col in _ORIGIN_COL_SCAN_RANGE:
            origin_row = board.hard_drop_row(piece, rotation, origin_col)
            if origin_row is None:
                continue
            landing_cells = [(origin_row + dr, origin_col + dc) for dr, dc in shape]
            key = frozenset(landing_cells)
            if key in seen:
                continue
            seen.add(key)

            placed = board.place_piece(piece, rotation, origin_row, origin_col)

            # eroded cells（Dellacherieの特徴量）: 消去された行に含まれていた
            # このミノ自身のマス数 × 消去行数。「置いてすぐ消える」手ほど高評価にする。
            full_rows = {r for r in range(placed.height) if all(cell is not None for cell in placed.grid[r])}
            cells_in_cleared_rows = sum(1 for r, _ in landing_cells if r in full_rows)
            eroded_cells = cells_in_cleared_rows * len(full_rows)

            cleared_board, lines = placed.clear_lines()
            moves.append(
                Move(
                    piece=piece,
                    rotation=rotation,
                    origin_col=origin_col,
                    origin_row=origin_row,
                    landing_cells=landing_cells,
                    resulting_board=cleared_board,
                    lines_cleared=lines,
                    eroded_cells=eroded_cells,
                )
            )

    return moves
