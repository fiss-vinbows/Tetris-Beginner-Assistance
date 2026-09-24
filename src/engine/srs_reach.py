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

from src.education.rules import COLS, HIDDEN_ROWS, ROWS, SPAWN_COL, SPAWN_ROW, GameState

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
def reachable20(placed: frozenset[Cell], piece: str, cells: tuple[Cell, ...], spin_entry: bool) -> bool:
    """20行座標の盤面placedに対し、pieceをcellsへSRSで置けるか(openers用)。"""
    state = GameState.new(0)
    state.board = [[None] * COLS for _ in range(ROWS)]
    for r, c in placed:
        if 0 <= r + HIDDEN_ROWS < ROWS:
            state.board[r + HIDDEN_ROWS][c] = "X"
    target = tuple((r + HIDDEN_ROWS, c) for r, c in cells)
    return find_path(state, piece, target, spin_entry=spin_entry) is not None
