"""はちみつ砲の「2巡目+TST(Tスピン)後」の開始状態を集める(試作)。

配列(7-bag)を実際に最後まで進めて、テンプレの手順どおりに置いた結果の
(盤面, HOLD, 次に出るミノの通し番号) を集計する。オフライン解析なので配列は
全部見えている前提で進めるが、手順の選び方(known_sequence・choose_form)は
アプリと同じくNEXT5までの情報で行う。
"""

from __future__ import annotations

import random
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import src.engine.openers as openers  # noqa: E402
from src.engine.openers import apply_step, choose_form, full_rows_after, known_sequence, shift_cells_for_clears  # noqa: E402

PIECES = "IOTSZJL"


@dataclass(frozen=True)
class StartState:
    board: frozenset[tuple[int, int]]  # 20行座標の占有
    hold: str | None
    next_index: int  # 次に出るミノ(操作ミノになる)の通し番号
    drawn_in_bag: frozenset[str]  # 今の袋から既に出たミノ(HOLDに入ったもの・置いたもの)
    reduced: bool  # どこかで砲のみに縮小したか


def random_sequence(rng: random.Random, bags: int = 5) -> list[str]:
    seq: list[str] = []
    for _ in range(bags):
        bag = list(PIECES)
        rng.shuffle(bag)
        seq += bag
    return seq


def play_honey(seq: list[str], template) -> StartState | None:
    """テンプレの図を順に組む。2巡目の図(TST込み)を置き終えた時点の状態を返す。"""
    board: set[tuple[int, int]] = set()
    hold: str | None = None
    i = 0  # 今の操作ミノの通し番号
    reduced = False
    for form_no in range(2):
        known = known_sequence(seq[i], tuple(seq[i + 1 : i + 6]), hold, i)
        chosen = choose_form(template, board, known, hold)
        if chosen is None:
            return None
        form, steps = chosen
        if len(steps) < len(form.items):
            reduced = True
        steps = list(steps)
        for k, step in enumerate(steps):
            current = seq[i]
            if step.use_hold:
                if hold is None:
                    hold, piece, i = current, seq[i + 1], i + 2
                else:
                    piece, hold, i = hold, current, i + 1
            else:
                piece, i = current, i + 1
            if piece != step.piece:
                return None
            cleared = full_rows_after(board, step.cells)
            board = apply_step(board, step.cells)
            if cleared:
                steps[k + 1 :] = [
                    type(st)(st.piece, shift_cells_for_clears(st.cells, cleared), st.use_hold, st.spin) for st in steps[k + 1 :]
                ]
    bag_start = i - i % 7
    return StartState(frozenset(board), hold, i, frozenset(seq[bag_start:i]), reduced)


def collect(samples: int, seed: int = 0) -> Counter:
    template = next(t for t in openers.OPENER_TEMPLATES if t.name_ja == "はちみつ砲")
    rng = random.Random(seed)
    found: Counter = Counter()
    for _ in range(samples):
        state = play_honey(random_sequence(rng), template)
        found[state] += 1
    return found


def board_text(board: frozenset[tuple[int, int]]) -> str:
    top = min((r for r, _c in board), default=20)
    return "\n".join("".join("X" if (r, c) in board else "_" for c in range(10)) for r in range(top, 20))


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    found = collect(n)
    print(f"試行 {n} 配列: テンプレ完走 {n - found[None]} / 途中で組めず {found[None]}")
    states = [s for s in found if s is not None]
    print(f"異なる開始状態: {len(states)}")
    for s in sorted(states, key=lambda s: -found[s])[:8]:
        print(f"--- 出現{found[s]} HOLD={s.hold} 次={s.next_index} 縮小={s.reduced} 残り{len(s.board)}マス")
        print(board_text(s.board))
