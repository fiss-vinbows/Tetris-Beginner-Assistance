"""教育モード: 見えているミノで取れるパーフェクトクリア(パフェ)の探索。

【2026-09-24・利用者の要望】途中で5手以内にパフェが見えるときは、ソフトドロップが
多くてもその手順を提示する(候補欄に「パフェ」の分岐として出す)。

- 使うのは操作ミノ・HOLD・NEXT5(と袋の位置から確定する7個目)だけ。
- 置き方は通常SRSで出現位置から実際に届く位置だけ(左右移動・回転・1マスずつの落下)。
- パフェの高さ(何段で消し切るか)を決め、その高さより上にはみ出す置き方は打ち切る。
  【2026-09-24・実画面 practice_20260924_201639〜201701】以前は「4の倍数でない空きマスの
  塊ができる置き方」も打ち切っていたが、途中で行が消えると上下の塊がつながるため誤りで、
  取れるパフェ(TST後にL→HOLDしてI→O→J→Z→T)を見逃していた。今はこの打ち切りを速く探す
  1回目だけに使い(見つかった手順は正しい)、見つからなければ打ち切りなしで探し直す。
- 時間の上限を超えたら「見つからなかった」ではなく「未判定」(TIMEOUT)を返す。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from src.education.rules import COLS, HIDDEN_ROWS, ROWS
from src.engine.srs_reach import lock_positions

TIME_LIMIT_SEC = 0.8  # 同期で探すとき(テスト等)の上限。画面では別スレッドで長めに探す
TIMEOUT = "timeout"
UNKNOWN = "?"  # 見えている範囲の次に来るミノ(種類は分からない)

Board = frozenset  # 22行座標の占有マス


@dataclass(frozen=True)
class PCStep:
    piece: str
    cells: tuple[tuple[int, int], ...]  # 22行座標
    use_hold: bool


class _Timeout(Exception):
    pass


def placements(board: Board, piece: str) -> tuple[tuple[tuple[int, int], ...], ...]:
    """出現位置からSRSで届く、固定できる位置(4マス)の一覧(srs_reach.lock_positionsを共用)。"""
    return tuple(sorted(lock_positions(board, piece)[0]))


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
    """パフェの高さ以下の空きマスが、どれも4の倍数の大きさの塊か(1回目の探索の打ち切り用)。

    途中で行が消えると塊がつながるので、これを満たさなくてもパフェになる場合がある。
    """
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

    【2026-09-24・利用者の指示】テトリス(4列消し)を含むパフェが取れるなら、ソフトドロップが
    要ってもそちらを優先する。探す順: テトリスあり(打ち切りあり)→テトリスなし(打ち切りあり)
    →テトリスあり(打ち切りなし)→テトリスなし(打ち切りなし)。時間切れになったら、それまでに
    見つかったパフェを返す。
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
    pruned = True  # 空きマスの塊で打ち切って速く探す(見つかった手順は正しい)
    need_tetris = True  # テトリス(4列消し)を含むパフェだけを探す

    def dfs(b: Board, index: int, held: str | None, height: int, left: int, tetris: bool = False):
        # 高さ以下の空きマスは常に4×残り手数(はみ出しを禁じているため)、
        # 置き終えて盤面が空になったときだけ成功
        if left == 0:
            return [] if not b and (tetris or not need_tetris) else None
        if time.monotonic() > deadline or (cancel is not None and cancel.is_set()):
            raise _Timeout
        if need_tetris and not tetris and (height < 4 or ("I" not in sequence[index:] and held != "I")):
            return None  # もうテトリス(4列消し)はできない: 高さが4段未満か、Iが残っていない
        key = (pruned, need_tetris, b, index, held, height, left, tetris)
        if key in failed:
            return None
        options = []
        if index < len(sequence):
            options.append((sequence[index], False, index + 1, held))
        if index == 0 and not can_hold:
            pass
        elif held is not None and held != UNKNOWN and index <= len(sequence):
            # 見えている範囲の最後でも、次のミノ(種類は見えないが必ず来る)と入れ替えてHOLDの
            # ミノを置ける。入れ替えでHOLDに入った見えないミノは置けない(UNKNOWN)。
            options.append((held, True, index + 1, sequence[index] if index < len(sequence) else UNKNOWN))
        elif held is None and index + 1 < len(sequence):
            options.append((sequence[index + 1], True, index + 2, sequence[index]))
        top = ROWS - height
        for piece, use_hold, next_index, next_held in options:
            if use_hold and held is not None and index < len(sequence) and piece == sequence[index]:
                continue  # 同じ種類のミノを入れ替えても結果は同じ
            for cells in moves(b, piece):
                if any(r < top for r, _c in cells):
                    continue  # パフェの高さより上にはみ出す
                nb, cleared = _lock(b, cells)
                nh = height - cleared
                if pruned and nb and not _regions_ok(nb, nh):
                    continue
                rest = dfs(nb, next_index, next_held, nh, left - 1, tetris or cleared == 4)
                if rest is not None:
                    return [PCStep(piece, cells, use_hold), *rest]
        failed.add(key)
        return None

    def run():
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
        return None

    # テトリスにはIが要る
    tetris_possible = "I" in sequence or hold == "I"
    passes = [(True, True), (True, False), (False, True), (False, False)]
    fallback = None  # 見つかったテトリスなしのパフェ(テトリスありを探し切る前に時間切れなら使う)
    try:
        for pruned, need_tetris in passes:
            if need_tetris and not tetris_possible:
                continue
            if not need_tetris and fallback is not None:
                continue
            found = run()
            if found is not None:
                if need_tetris:
                    return found
                fallback = found
    except _Timeout:
        return fallback if fallback is not None else TIMEOUT
    return fallback


def has_tetris(board: Board, steps: list[PCStep]) -> bool:
    """パフェの手順にテトリス(4列消し)が含まれるか。"""
    board = frozenset(board)
    for step in steps:
        board, cleared = _lock(board, step.cells)
        if cleared == 4:
            return True
    return False
