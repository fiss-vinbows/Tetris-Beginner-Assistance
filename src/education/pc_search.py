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

from functools import lru_cache

from src.education.rules import _KICKS_I, _KICKS_JLSTZ, _SHAPES, COLS, HIDDEN_ROWS, ROWS, SPAWN_COL, SPAWN_ROW

TIME_LIMIT_SEC = 0.8  # 同期で探すとき(テスト等)の上限。画面では別スレッドで長めに探す
TIMEOUT = "timeout"

Board = frozenset  # 22行座標の占有マス


@dataclass(frozen=True)
class PCStep:
    piece: str
    cells: tuple[tuple[int, int], ...]  # 22行座標
    use_hold: bool


class _Timeout(Exception):
    pass


@lru_cache(maxsize=200_000)
def placements(board: Board, piece: str) -> tuple[tuple[tuple[int, int], ...], ...]:
    """出現位置からSRSで届く、固定できる位置(4マス)の一覧。

    【2026-09-24・利用者の指摘】ホールドを切り替えたときに動作が重かった。以前は
    rules.GameStateの移動・回転を1手ずつ呼んで調べていたため遅かった(空の盤面で
    パフェを探すと時間の上限0.8秒まで画面が止まった)。同じ通常SRS(rules の形と
    補正表)を、占有マスの集合で直接調べる。結果は盤面とミノごとに覚えて使い回す。
    """
    shapes = _SHAPES[piece]
    kicks = _KICKS_I if piece == "I" else _KICKS_JLSTZ

    def fits(orient: int, row: int, col: int) -> bool:
        for dr, dc in shapes[orient]:
            r, c = row + dr, col + dc
            if not (0 <= r < ROWS and 0 <= c < COLS) or (r, c) in board:
                return False
        return True

    if not fits(0, SPAWN_ROW, SPAWN_COL):
        return ()
    start = (0, SPAWN_ROW, SPAWN_COL)
    seen = {start}
    queue = deque([start])
    result: set[tuple[tuple[int, int], ...]] = set()
    while queue:
        orient, row, col = queue.popleft()
        nexts = [(orient, row, col - 1), (orient, row, col + 1), (orient, row + 1, col)]
        if not fits(orient, row + 1, col):
            result.add(tuple(sorted((row + dr, col + dc) for dr, dc in shapes[orient])))
        if piece != "O":
            for direction in (-1, 1):
                new = (orient + direction) % 4
                for dx, dy in kicks[(orient, new)]:
                    if fits(new, row - dy, col + dx):
                        nexts.append((new, row - dy, col + dx))
                        break
        for node in nexts:
            if node not in seen and fits(*node):
                seen.add(node)
                queue.append(node)
    return tuple(sorted(result))


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
    max_pieces: int | None = None,
    time_limit: float = TIME_LIMIT_SEC,
    can_hold: bool = True,
    cancel=None,
):
    """パフェの手順(PCStepのリスト)。無ければNone、時間切れならTIMEOUT。

    max_pieces: 使うミノ数の上限。Noneなら見えているミノ(操作ミノ・NEXT・HOLD)をすべて使える。
    【2026-09-24・実画面 practice_20260924_195905】以前は5手・6段までに限っていたため、
    見えている7個でちょうど埋まる迷走砲の8段パフェを探さなかった。

    sequence: 先頭が操作ミノの、分かっているミノ順。hold: 今のHOLD。
    can_hold: この手番でまだHOLDできるか(HOLD済みなら最初の1手はHOLDしない)。
    cancel: 別スレッドで探すときの打ち切りの合図(threading.Event)。立ったらTIMEOUTを返す。
    盤面が空でも探す(パフェ直後の2段パフェ等)。
    【2026-09-24・実画面 practice_20260924_193201】以前は空の盤面を「パフェ済み」として
    探さず、O・HOLD I・NEXT J L O J S で取れる2段パフェが1手置くまで出なかった。
    """
    board = frozenset(board)
    if any(r < HIDDEN_ROWS for r, _c in board):
        return None
    filled = len(board)
    stack_height = ROWS - min(r for r, _c in board) if board else 0
    available = len(sequence) + (1 if hold is not None else 0)
    if max_pieces is not None:
        available = min(available, max_pieces)
    deadline = time.monotonic() + time_limit
    failed: set[tuple] = set()
    moves = placements

    def dfs(b: Board, index: int, held: str | None, height: int, left: int):
        # 高さ以下の空きマスは常に4×残り手数(はみ出しを禁じているため)、
        # 置き終えて盤面が空になったときだけ成功
        if left == 0:
            return [] if not b else None
        if time.monotonic() > deadline or (cancel is not None and cancel.is_set()):
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
        for height in range(max(stack_height, 1), ROWS - HIDDEN_ROWS + 1):
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
