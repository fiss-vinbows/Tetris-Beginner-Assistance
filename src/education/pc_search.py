"""教育モード: 見えているミノで取れるパーフェクトクリア(パフェ)の探索。

【2026-09-24・利用者の要望】途中で5手以内にパフェが見えるときは、ソフトドロップが
多くてもその手順を提示する(候補欄に「パフェ」の分岐として出す)。

- 使うのは操作ミノ・HOLD・NEXT5(と袋の位置から確定する7個目)だけ。
- 置き方は通常SRSで出現位置から実際に届く位置だけ(左右移動・回転・1マスずつの落下)。
- パフェの高さ(何段で消し切るか)を決め、その高さより上にはみ出す置き方や、
  4の倍数でない空き領域ができる置き方は打ち切る。
- 時間の上限を超えたら「見つからなかった」ではなく「未判定」(TIMEOUT)を返す。
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

from src.education.rules import COLS, HIDDEN_ROWS, ROWS, SPAWN_COL, SPAWN_ROW, GameState, PieceSequence

MAX_PIECES = 5
TIME_LIMIT_SEC = 0.8  # 1手ごとに探すので画面を止めない長さにする
TIMEOUT = "timeout"

Board = frozenset  # 22行座標の占有マス


@dataclass(frozen=True)
class PCStep:
    piece: str
    cells: tuple[tuple[int, int], ...]  # 22行座標
    use_hold: bool


class _Timeout(Exception):
    pass


def _sim(board: Board) -> GameState:
    sim = GameState(sequence=PieceSequence(0))
    sim.board = [[None] * COLS for _ in range(ROWS)]
    for r, c in board:
        sim.board[r][c] = "X"
    return sim


def placements(board: Board, piece: str) -> list[tuple[tuple[int, int], ...]]:
    """出現位置からSRSで届く、固定できる位置(4マス)の一覧。"""
    sim = _sim(board)
    if not sim._fits(piece, 0, SPAWN_ROW, SPAWN_COL):
        return []
    sim.current = piece
    start = (0, SPAWN_ROW, SPAWN_COL)
    seen = {start}
    queue = deque([start])
    result: set[tuple[tuple[int, int], ...]] = set()
    while queue:
        orient, row, col = queue.popleft()
        sim.orient, sim.row, sim.col = orient, row, col
        if sim.is_grounded():
            result.add(tuple(sorted(sim.current_cells())))
        for method in ("move_left", "move_right", "rotate_ccw", "rotate_cw", "soft_drop"):
            sim.orient, sim.row, sim.col = orient, row, col
            if getattr(sim, method)():
                node = (sim.orient, sim.row, sim.col)
                if node not in seen:
                    seen.add(node)
                    queue.append(node)
    return sorted(result)


def _lock(board: Board, cells) -> tuple[Board, int]:
    """置いて揃った行を消した盤面と、消えた行数。"""
    placed = set(board) | set(cells)
    full = [r for r in range(ROWS) if all((r, c) in placed for c in range(COLS))]
    if not full:
        return frozenset(placed), 0
    result = set()
    for r, c in placed:
        if r in full:
            continue
        result.add((r + sum(1 for f in full if f > r), c))
    return frozenset(result), len(full)


def _regions_ok(board: Board, height: int) -> bool:
    """パフェの高さ以下の空きマスが、どれも4の倍数の大きさの塊になっているか。"""
    top = ROWS - height
    empty = {(r, c) for r in range(top, ROWS) for c in range(COLS) if (r, c) not in board}
    while empty:
        stack = [empty.pop()]
        size = 1
        while stack:
            r, c = stack.pop()
            for nb in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
                if nb in empty:
                    empty.remove(nb)
                    stack.append(nb)
                    size += 1
        if size % 4:
            return False
    return True


def find_perfect_clear(
    board: Board,
    sequence: list[str],
    hold: str | None,
    *,
    max_pieces: int = MAX_PIECES,
    time_limit: float = TIME_LIMIT_SEC,
    can_hold: bool = True,
):
    """パフェの手順(PCStepのリスト)。無ければNone、時間切れならTIMEOUT。

    sequence: 先頭が操作ミノの、分かっているミノ順。hold: 今のHOLD。
    can_hold: この手番でまだHOLDできるか(HOLD済みなら最初の1手はHOLDしない)。
    盤面が空でも探す(パフェ直後の2段パフェ等)。
    【2026-09-24・実画面 practice_20260924_193201】以前は空の盤面を「パフェ済み」として
    探さず、O・HOLD I・NEXT J L O J S で取れる2段パフェが1手置くまで出なかった。
    """
    board = frozenset(board)
    if any(r < HIDDEN_ROWS for r, _c in board):
        return None
    filled = len(board)
    stack_height = ROWS - min(r for r, _c in board) if board else 0
    available = min(max_pieces, len(sequence) + (1 if hold is not None else 0))
    deadline = time.monotonic() + time_limit
    cache: dict[tuple, list] = {}
    failed: set[tuple] = set()

    def moves(b: Board, piece: str):
        key = (b, piece)
        if key not in cache:
            cache[key] = placements(b, piece)
        return cache[key]

    def dfs(b: Board, index: int, held: str | None, height: int, left: int):
        # 高さ以下の空きマスは常に4×残り手数(はみ出しを禁じているため)、
        # 置き終えて盤面が空になったときだけ成功
        if left == 0:
            return [] if not b else None
        if time.monotonic() > deadline:
            raise _Timeout
        key = (b, index, held, height, left)
        if key in failed:
            return None
        options = []
        if index < len(sequence):
            options.append((sequence[index], False, index + 1, held))
        if index == 0 and not can_hold:
            pass
        elif held is not None and index < len(sequence):
            options.append((held, True, index + 1, sequence[index]))
        elif held is None and index + 1 < len(sequence):
            options.append((sequence[index + 1], True, index + 2, sequence[index]))
        top = ROWS - height
        for piece, use_hold, next_index, next_held in options:
            if use_hold and held is not None and piece == sequence[index]:
                continue  # 同じ種類のミノを入れ替えても結果は同じ
            for cells in moves(b, piece):
                if any(r < top for r, _c in cells):
                    continue  # パフェの高さより上にはみ出す
                nb, cleared = _lock(b, cells)
                nh = height - cleared
                if nb and not _regions_ok(nb, nh):
                    continue
                rest = dfs(nb, next_index, next_held, nh, left - 1)
                if rest is not None:
                    return [PCStep(piece, cells, use_hold), *rest]
        failed.add(key)
        return None

    try:
        for height in range(max(stack_height, 1), 7):
            empty = height * COLS - filled
            if empty <= 0 or empty % 4:
                continue
            pieces = empty // 4
            if pieces > available:
                break
            found = dfs(board, 0, hold, height, pieces)
            if found is not None:
                return found
    except _Timeout:
        return TIMEOUT
    return None
