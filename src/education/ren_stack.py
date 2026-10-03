"""教育モード: 中あけREN(中央4列を空け、左右3列ずつを積む)の積み増しの推奨手。

【2026-10-03・利用者の要望】種3(中央4列の底に置く3マスのタネ)の中あけRENを積む練習をシミュレーターでする。
テトリス堂の積み増しの図(レベル1)はミノ順が合わないと組めず、1巡目の後で案内が途切れた。ページでも
積み増しは「左はJLOで3x4、右はIを立ててSZT」という考え方として説明されているため、図ではなく評価で
積み増しの手を選ぶ(6-3積みと同じく2手先まで読む。src/education/six_three.py)。

- 中央4列(REN_WELL)は空ける。タネの3マスより多くブロックがあると大きく減点。
- 穴・左右それぞれの凸凹と溝(1列だけ低い列)・左右の高さの差を減点し、行を消す置き方(積んでいる途中)も減点する。
  左右6列がすべて埋まった行(RENで消せる行)は加点する。
- 高く積むほどRENが長く続くので高さそのものは減点しない。【2026-10-03・利用者の指示】20段目(可視の一番上)
  まで積み込むことを想定する(上端の近くも減点しない。出現位置は中央4列の上なので左右を積んでもふさがない)。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.education.rules import COLS, HIDDEN_ROWS, ROWS
from src.education.six_three import _lock, _options
from src.engine.srs_reach import lock_positions

WELL = range(3, 7)  # 中央4列(src/education/ren.py の WELL と同じ)
SIDES = ((0, 1, 2), (7, 8, 9))
SEED_CELLS = 3  # タネのマス数(種3)

# 評価の重み(大きいほど強く避ける/好む)
WELL_BLOCKED = 1000  # 中央4列にタネより多くブロックがある(1マスごと)
HOLE = 300  # 穴(上が埋まった空きマス)。穴の行でRENが途切れるため強く避ける(80では1巡目の図の空きをふさいだ)
BUMP = 12  # 左右それぞれの3列の凸凹
SLOT = 40  # 左右それぞれの3列の中で、両隣より2段以上低い列(溝)。RENでは行が揃わない
READY = 10  # 左右6列がすべて埋まった行(RENで消せる行)
BALANCE = 4  # 左右の高さの差
BURN = 150  # 積んでいる途中で行を消す(1列ごと)


@dataclass(frozen=True)
class RenStackMove:
    piece: str
    cells: tuple[tuple[int, int], ...]  # 22行座標
    use_hold: bool
    score: float


def side_heights(board) -> tuple[int, int]:
    """左右3列それぞれの低い方の列の高さ。"""
    heights = [0] * COLS
    for r, c in board:
        heights[c] = max(heights[c], ROWS - r)
    return tuple(min(heights[c] for c in cols) for cols in SIDES)  # type: ignore[return-value]


def evaluate(board) -> float:
    """盤面の良さ(大きいほど良い)。消去の減点は含まない。"""
    heights = [0] * COLS
    for r, c in board:
        heights[c] = max(heights[c], ROWS - r)
    score = 0.0
    well = sum(1 for _r, c in board if c in WELL)
    score -= WELL_BLOCKED * max(0, well - SEED_CELLS)
    holes = sum(1 for c in range(COLS) for r in range(ROWS - heights[c], ROWS) if (r, c) not in board)
    score -= HOLE * holes
    for cols in SIDES:
        score -= BUMP * sum(abs(heights[a] - heights[b]) for a, b in zip(cols, cols[1:]))
        for i, c in enumerate(cols):
            neighbors = [heights[cols[j]] for j in (i - 1, i + 1) if 0 <= j < len(cols)]
            if neighbors and min(neighbors) - heights[c] >= 2:
                score -= SLOT * (min(neighbors) - heights[c])
    side_cols = [c for cols in SIDES for c in cols]
    score += READY * sum(1 for r in range(ROWS) if all((r, c) in board for c in side_cols))
    left, right = (max(heights[c] for c in cols) for cols in SIDES)
    score -= BALANCE * abs(left - right)
    return score


BEAM_WIDTH = 4  # 先読みで残す局面の数(4・8・16でRENの続き方は同じだった。軽い4にする)


def best_move(board, current: str, hold: str | None, nexts: list[str], can_hold: bool = True) -> RenStackMove | None:
    """見えているミノ(操作ミノ・HOLD・NEXT)を使い切るまで先を読み、最も評価の高い1手目。

    【2026-10-03】2手先までの読みでは、3列ずつの狭い場所でS・Z等の置き方を誤って穴を作り、その行で
    RENが途切れた。手ごとに評価の高い局面だけ(BEAM_WIDTH個)残して先へ進める(ビーム探索)。
    置けるところが無ければNone。
    """
    board = frozenset(board)
    # タネがそろった後は、中央4列に掛かる置き方を試さない(大きく減点される手。探索を軽くする)
    seeded = sum(1 for _r, c in board if c in WELL) >= SEED_CELLS

    def moves(b, piece):
        for cells in lock_positions(b, piece)[0]:
            if any(r < HIDDEN_ROWS for r, _c in cells) or seeded and any(c in WELL for _r, c in cells):
                continue
            yield cells

    # 局面: (評価, 盤面, HOLD, 残りのNEXT, 1手目, 消去の減点の合計)
    beam = []
    for piece, use_hold, hold2, rest in _options(current, hold, nexts, can_hold):
        for cells in moves(board, piece):
            b1, cleared = _lock(board, cells)
            burn = -BURN * cleared
            beam.append((burn + evaluate(b1), b1, hold2, rest, (piece, tuple(cells), use_hold), burn))
    if not beam:
        return None
    best_first = max(beam, key=lambda x: x[0])
    beam = _prune(beam)
    while True:
        nxt = []
        for _score, b, held, rest, first, burn in beam:
            if not rest:
                continue
            for piece, _use_hold, held2, rest2 in _options(rest[0], held, rest[1:], True):
                for cells in moves(b, piece):
                    b2, cleared = _lock(b, cells)
                    total = burn - BURN * cleared
                    nxt.append((total + evaluate(b2), b2, held2, rest2, first, total))
        if not nxt:
            break
        beam = _prune(nxt)
        best_first = max(beam, key=lambda x: x[0])
    piece, cells, use_hold = best_first[4]
    return RenStackMove(piece, cells, use_hold, best_first[0])


def _prune(states: list) -> list:
    """評価の高い順にBEAM_WIDTH個(同じ盤面・HOLDは1つ)。"""
    states.sort(key=lambda x: -x[0])
    seen = set()
    out = []
    for state in states:
        key = (state[1], state[2])
        if key in seen:
            continue
        seen.add(key)
        out.append(state)
        if len(out) >= BEAM_WIDTH:
            break
    return out
