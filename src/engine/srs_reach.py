"""通常SRSでの到達判定(配置に実際に入れられるか・操作手順)。

【2026-09-23】開幕テンプレの手順生成(openers.plan_form)が、Tスピンの手を
「マスが空いていて支えがある」だけで置けると判定していたため、屋根が早すぎて
入らない・屋根が無くてTスピンにならない順番の手を推奨していた(教育モードで
操作手順が見つからず、利用者が従えずにAIへ切り替わった)。出現位置から左右移動・
左右回転・1マスずつの落下で実際に届くかを幅優先探索で確かめる。

盤面は可視20行の座標(openersと同じ)で受け取り、教育モードのルール
(src.education.rules: 非表示2行を含む22行)に載せて探索する。
"""

from __future__ import annotations

import copy
import heapq
import itertools
from collections import deque
from functools import lru_cache

from src.education.rules import _KICKS_I, _KICKS_JLSTZ, _SHAPES, COLS, HIDDEN_ROWS, ROWS, SPAWN_COL, SPAWN_ROW, GameState

Cell = tuple[int, int]

_OPS = (("←", "move_left"), ("→", "move_right"), ("左回転", "rotate_ccw"), ("右回転", "rotate_cw"), ("↓", "soft_drop"))


def find_path(
    state: GameState, piece: str, target: tuple[Cell, ...], *, spin_entry: bool = False
) -> tuple[str, ...] | None:
    """出現位置からtarget(22行座標)へ置く最短の操作手順。無ければNone。

    spin_entry=True(Tスピンの手)のときは、最後の操作が回転でtargetに収まる
    手順だけを認める(回転せずに落として入れてもTスピンにならないため)。
    """
    sim = copy.copy(state)
    sim.game_over = False
    goal = frozenset(target)
    sim.current = piece
    if not sim._fits(piece, 0, SPAWN_ROW, SPAWN_COL):
        return None
    start = (0, SPAWN_ROW, SPAWN_COL, False)  # 向き・行・列・直前の操作が回転か
    prev: dict[tuple, tuple[tuple, str] | None] = {start: None}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        orient, row, col, rotated = node
        sim.orient, sim.row, sim.col = orient, row, col
        if spin_entry:
            done = rotated and frozenset(sim.current_cells()) == goal and sim.is_grounded()
        else:
            done = frozenset(_ghost_cells(sim)) == goal
        if done:
            path: list[str] = []
            while prev[node] is not None:
                node, label = prev[node]
                path.append(label)
            return _compress(list(reversed(path)) + ["ハードドロップ"])
        for label, method in _OPS:
            sim.orient, sim.row, sim.col = orient, row, col
            if getattr(sim, method)():
                nxt = (sim.orient, sim.row, sim.col, "回転" in label)
                if nxt not in prev:
                    prev[nxt] = (node, label)
                    queue.append(nxt)
    return None


def find_path_min_soft(
    state: GameState, piece: str, target: tuple[Cell, ...], *, spin_entry: bool = False
) -> tuple[tuple[str, ...], int] | None:
    """ソフトドロップの区間数が最も少ない操作手順と、その区間数。無ければNone。

    【2026-09-24・利用者の要望】推奨手の難度(◎○△)をソフトドロップの回数で示す。
    1回=連続したソフトドロップの1区間(「↓×16」は1回、「↓→回転→↓」は2回)。
    Tスピンに必要な下降も数える。find_path(操作数が最短)ではソフトドロップが
    最少とは限らないため、(区間数, 操作数)の小さい順に探す。
    """
    sim = copy.copy(state)
    sim.game_over = False
    goal = frozenset(target)
    sim.current = piece
    if not sim._fits(piece, 0, SPAWN_ROW, SPAWN_COL):
        return None
    # 向き・行・列・直前の操作が回転か・直前の操作がソフトドロップか
    start = (0, SPAWN_ROW, SPAWN_COL, False, False)
    best: dict[tuple, tuple[int, int]] = {start: (0, 0)}
    prev: dict[tuple, tuple[tuple, str] | None] = {start: None}
    order = itertools.count()
    heap = [(0, 0, next(order), start)]
    while heap:
        sections, ops, _n, node = heapq.heappop(heap)
        if best.get(node) != (sections, ops):
            continue  # もっと良い経路で到達済み
        orient, row, col, rotated, _soft = node
        sim.orient, sim.row, sim.col = orient, row, col
        if spin_entry:
            done = rotated and frozenset(sim.current_cells()) == goal and sim.is_grounded()
        else:
            done = frozenset(_ghost_cells(sim)) == goal
        if done:
            path: list[str] = []
            while prev[node] is not None:
                node, label = prev[node]
                path.append(label)
            return _compress(list(reversed(path)) + ["ハードドロップ"]), sections
        for label, method in _OPS:
            sim.orient, sim.row, sim.col = orient, row, col
            if getattr(sim, method)():
                is_soft = label == "↓"
                nxt = (sim.orient, sim.row, sim.col, "回転" in label, is_soft)
                cost = (sections + (1 if is_soft and not node[4] else 0), ops + 1)
                if nxt not in best or cost < best[nxt]:
                    best[nxt] = cost
                    prev[nxt] = (node, label)
                    heapq.heappush(heap, (cost[0], cost[1], next(order), nxt))
    return None


def soft_drop_sections(steps: tuple[str, ...]) -> int:
    """操作手順(「↓×3」のように圧縮済み)の中の、連続したソフトドロップの区間数。"""
    return sum(1 for i, step in enumerate(steps) if step.startswith("↓") and (i == 0 or not steps[i - 1].startswith("↓")))


def difficulty_mark(sections: int | None) -> str:
    """ソフトドロップの区間数を難度の記号にする(0回=◎、1回=○、2回以上=△)。"""
    if sections is None:
        return "評価待ち"
    return "◎" if sections == 0 else "○" if sections == 1 else "△"


def _ghost_cells(sim: GameState) -> tuple[Cell, ...]:
    saved = sim.row
    sim.row = sim.ghost_row()
    cells = sim.current_cells()
    sim.row = saved
    return cells


def _compress(path: list[str]) -> tuple[str, ...]:
    """同じ操作の連続を「→×2」のようにまとめる。"""
    out: list[str] = []
    count = 0
    for i, op in enumerate(path):
        count += 1
        if i + 1 == len(path) or path[i + 1] != op:
            out.append(f"{op}×{count}" if count > 1 else op)
            count = 0
    return tuple(out)


@lru_cache(maxsize=200_000)
def lock_positions(board: frozenset[Cell], piece: str) -> tuple[frozenset, frozenset]:
    """22行座標の盤面boardで、出現位置からSRSで届き固定できる位置(4マスの組)の集合。

    戻り値は(すべての固定位置, 最後の操作が回転で収まる固定位置=Tスピンの入れ方)。
    find_path(操作手順の探索)と同じ動き(左右移動・左右回転・1マスずつの落下)を、
    GameStateを使わず占有マスの集合で直接調べる(【2026-09-24】パフェ直後にDPCの図の
    到達判定で画面が約0.23秒止まっていたため)。結果は盤面とミノごとに覚えて使い回す。
    """
    shapes = _SHAPES[piece]
    kicks = _KICKS_I if piece == "I" else _KICKS_JLSTZ

    def fits(orient: int, row: int, col: int) -> bool:
        for dr, dc in shapes[orient]:
            r, c = row + dr, col + dc
            if not (0 <= r < ROWS and 0 <= c < COLS) or (r, c) in board:
                return False
        return True

    def cells_of(orient: int, row: int, col: int) -> tuple[Cell, ...]:
        return tuple(sorted((row + dr, col + dc) for dr, dc in shapes[orient]))

    if not fits(0, SPAWN_ROW, SPAWN_COL):
        return frozenset(), frozenset()
    start = (0, SPAWN_ROW, SPAWN_COL)
    seen = {start}
    queue = deque([start])
    plain: set[tuple[Cell, ...]] = set()
    spin: set[tuple[Cell, ...]] = set()
    while queue:
        orient, row, col = queue.popleft()
        if not fits(orient, row + 1, col):
            plain.add(cells_of(orient, row, col))
        nexts = [(orient, row, col - 1), (orient, row, col + 1), (orient, row + 1, col)]
        for node in nexts:
            if node not in seen and fits(*node):
                seen.add(node)
                queue.append(node)
        if piece == "O":
            continue
        for direction in (-1, 1):
            new = (orient + direction) % 4
            for dx, dy in kicks[(orient, new)]:
                node = (new, row - dy, col + dx)
                if fits(*node):
                    if not fits(new, node[1] + 1, node[2]):
                        spin.add(cells_of(*node))  # 回転して接地した(最後の操作が回転)
                    if node not in seen:
                        seen.add(node)
                        queue.append(node)
                    break
    return frozenset(plain), frozenset(spin)


def reachable20(placed: frozenset[Cell], piece: str, cells: tuple[Cell, ...], spin_entry: bool) -> bool:
    """20行座標の盤面placedに対し、pieceをcellsへSRSで置けるか(openers用)。"""
    board = frozenset((r + HIDDEN_ROWS, c) for r, c in placed if 0 <= r + HIDDEN_ROWS < ROWS)
    target = tuple(sorted((r + HIDDEN_ROWS, c) for r, c in cells))
    plain, spin = lock_positions(board, piece)
    return target in (spin if spin_entry else plain)
