"""教育モード: 6-3積み(左6列+右3列を積み、左から7列目をテトリス専用の井戸にする)の推奨手。

【2026-09-24・利用者の要望】6-3積みを候補欄の1つとして選べるようにする。
- 井戸は左から7列目(列番号6)で固定(左右反転はしない)。TSD等は使わず、テトリスで消す。
- 見えているミノ(操作ミノ・HOLD・NEXTの先頭)で2手先まで読み、置き終えた盤面を評価する。
- 置き方は通常SRSで出現位置から届く位置だけ(srs_reach.lock_positions)。
- ColdClear2は使わない(Python内の評価。読みの強さはCC2より弱い)。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.education.rules import COLS, HIDDEN_ROWS, ROWS
from src.engine.srs_reach import lock_positions

WELL_COL = 6  # 左から7列目

Board = frozenset  # 22行座標の占有マス

# 評価の重み(大きいほど強く避ける/好む)
WELL_BLOCKED = 1000  # 井戸にブロックが残る
HOLE = 60  # 穴(上が埋まった空きマス)
BUMP = 5  # 井戸以外の隣り合う列の高さの差
HEIGHT = 3  # 一番高い列の高さ
TETRIS = 300  # テトリス(4列消し)
BURN = 40  # テトリス以外の消去(1列ごと)。6-3積みでは火力を損なう
READY = 8  # 井戸以外がすべて埋まった行(テトリスの準備)。4行まで


@dataclass(frozen=True)
class SixThreeMove:
    piece: str
    cells: tuple[tuple[int, int], ...]  # 22行座標
    use_hold: bool
    score: float


def _lock(board: Board, cells) -> tuple[Board, int]:
    placed = set(board) | set(cells)
    full = [r for r in range(ROWS) if all((r, c) in placed for c in range(COLS))]
    if not full:
        return frozenset(placed), 0
    return frozenset((r + sum(1 for f in full if f > r), c) for r, c in placed if r not in full), len(full)


def _heights(board: Board) -> list[int]:
    heights = [0] * COLS
    for r, c in board:
        heights[c] = max(heights[c], ROWS - r)
    return heights


def evaluate(board: Board) -> float:
    """盤面の良さ(大きいほど良い)。消去の加点・減点は含まない。"""
    heights = _heights(board)
    score = 0.0
    if heights[WELL_COL]:
        score -= WELL_BLOCKED
    # 穴: 各列で一番上のブロックより下にある空きマス
    holes = sum(1 for c in range(COLS) for r in range(ROWS - heights[c], ROWS) if (r, c) not in board)
    score -= HOLE * holes
    stack = [heights[c] for c in range(COLS) if c != WELL_COL]
    score -= BUMP * sum(abs(a - b) for a, b in zip(stack, stack[1:]))
    score -= HEIGHT * max(stack)
    ready = sum(1 for r in range(ROWS) if all((r, c) in board for c in range(COLS) if c != WELL_COL) and (r, WELL_COL) not in board)
    score += READY * min(ready, 4)
    return score


def _clear_score(cleared: int) -> float:
    return TETRIS if cleared == 4 else -BURN * cleared


def _options(current: str, hold: str | None, nexts: list[str], can_hold: bool):
    """(置くミノ, HOLDしたか, 次のHOLD, 残りのNEXT)の選択肢。"""
    yield current, False, hold, nexts
    if can_hold:
        if hold is not None and hold != current:
            yield hold, True, current, nexts
        elif hold is None and nexts:
            yield nexts[0], True, current, nexts[1:]


def best_move(board: Board, current: str, hold: str | None, nexts: list[str], can_hold: bool = True) -> SixThreeMove | None:
    """2手先まで読んで最も評価の高い1手目。置けるところが無ければNone。"""
    board = frozenset(board)
    best: SixThreeMove | None = None
    for piece, use_hold, hold2, rest in _options(current, hold, nexts, can_hold):
        for cells in sorted(lock_positions(board, piece)[0]):
            if any(r < HIDDEN_ROWS for r, _c in cells):
                continue
            b1, cleared = _lock(board, cells)
            first = _clear_score(cleared)
            second = None
            if rest:
                for piece2, _h, _hold3, _rest in _options(rest[0], hold2, rest[1:], True):
                    for cells2 in lock_positions(b1, piece2)[0]:
                        if any(r < HIDDEN_ROWS for r, _c in cells2):
                            continue
                        b2, cleared2 = _lock(b1, cells2)
                        value = _clear_score(cleared2) + evaluate(b2)
                        if second is None or value > second:
                            second = value
            total = first + (second if second is not None else evaluate(b1))
            if best is None or total > best.score:
                best = SixThreeMove(piece, cells, use_hold, total)
    return best
