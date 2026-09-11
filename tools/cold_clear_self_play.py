"""Cold Clear 2 を使った自己対戦シミュレーター。

自前のsolver.py(evaluator.py)向けのself_play_sim.pyとは別に、実際に
アプリが使っているCold Clear 2エンジンで、ライン消去の質・パーフェクト
クリアの発生・ゲームオーバー率を検証するために作成した。

各手について think_seconds 秒だけ思考させてから着手する（AssistWorkerの
段階的思考とは異なりシミュレーションなので単純化しているが、
「一定時間操作している間に思考が進む」効果を模した検証ができる）。
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine.board_state import BoardState
from src.engine.cold_clear_client import ColdClearClient

PIECES = ["I", "O", "T", "S", "Z", "J", "L"]


def seven_bag_generator(seed: int):
    rng = random.Random(seed)
    while True:
        bag = PIECES[:]
        rng.shuffle(bag)
        yield from bag


def _add_garbage_row(board: BoardState, rng: random.Random) -> BoardState:
    """盤面の下に、1列だけ空いたGARBAGE行を1段追加する（対戦相手からの攻撃を模す）。"""
    new_board = board.clone()
    new_board.grid.pop(0)
    hole_col = rng.randrange(board.width)
    new_board.grid.append(["GARBAGE" if c != hole_col else None for c in range(board.width)])
    return new_board


def run_simulation(
    client: ColdClearClient,
    seed: int,
    max_moves: int,
    think_seconds: float,
    garbage_chance: float = 0.0,
) -> dict:
    """garbage_chance: 1手ごとにGARBAGE行が1段せり上がる確率(0.0〜1.0)。

    対戦中のおじゃまブロック攻撃を受けながらのプレイ品質・安定性を検証するために
    導入した。以前この状況に近い「完全に埋まった行を含む異常な盤面」で
    Cold Clear 2がクラッシュするバグを発見しており、その回帰確認も兼ねる。
    """
    gen = seven_bag_generator(seed)
    garbage_rng = random.Random(seed * 7919 + 1)  # ミノ生成用と独立させる
    board = BoardState()
    hold_piece: str | None = None
    current_piece = next(gen)
    next_queue = [next(gen) for _ in range(5)]

    total_lines = 0
    move_count = 0
    max_height_seen = 0
    total_holes_seen = 0
    clear_counts = {1: 0, 2: 0, 3: 0, 4: 0}
    perfect_clears = 0
    game_over = False
    garbage_rows_added = 0

    for move_count in range(1, max_moves + 1):
        if garbage_chance > 0 and garbage_rng.random() < garbage_chance:
            board = _add_garbage_row(board, garbage_rng)
            garbage_rows_added += 1

        best = client.suggest_move(board, current_piece, hold_piece, next_queue, think_seconds=think_seconds)
        if best is None:
            game_over = True
            break

        if best.use_hold:
            if hold_piece is None:
                hold_piece = current_piece
                current_piece = next_queue.pop(0)
                next_queue.append(next(gen))
            else:
                hold_piece, current_piece = current_piece, hold_piece
        # best.pieceの実際の着地マスをplace_pieceで反映する
        rows = sorted({r for r, _c in best.landing_cells})
        cols_by_row: dict[int, list[int]] = {}
        for r, c in best.landing_cells:
            cols_by_row.setdefault(r, []).append(c)

        # BoardState.place_pieceはrotation/origin_row/origin_colベースのAPIのため、
        # ここではlanding_cellsを直接gridに書き込む簡易実装で代用する。
        new_board = board.clone()
        for r, c in best.landing_cells:
            new_board.grid[r][c] = best.piece
        board, lines = new_board.clear_lines()
        total_lines += lines
        if lines:
            clear_counts[lines] += 1
        if lines and all(cell is None for row in board.grid for cell in row):
            perfect_clears += 1

        heights = board.column_heights()
        max_height_seen = max(max_height_seen, max(heights))
        total_holes_seen += board.count_holes()

        current_piece = next_queue.pop(0)
        next_queue.append(next(gen))

    return {
        "moves_survived": move_count,
        "total_lines": total_lines,
        "final_holes": board.count_holes(),
        "max_height_seen": max_height_seen,
        "avg_holes_per_move": total_holes_seen / move_count if move_count else 0,
        "game_over": game_over,
        "clear_counts": clear_counts,
        "perfect_clears": perfect_clears,
        "garbage_rows_added": garbage_rows_added,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--max-moves", type=int, default=100)
    parser.add_argument("--think-seconds", type=float, default=0.1)
    parser.add_argument(
        "--garbage-chance", type=float, default=0.0,
        help="1手ごとにGARBAGE行が1段せり上がる確率(0.0〜1.0)。対戦中の攻撃を模す。",
    )
    args = parser.parse_args()

    client = ColdClearClient()
    results = []
    start = time.perf_counter()
    for seed in range(args.seeds):
        r = run_simulation(client, seed, args.max_moves, args.think_seconds, args.garbage_chance)
        results.append(r)
        print(
            f"seed={seed}: moves={r['moves_survived']} lines={r['total_lines']} "
            f"game_over={r['game_over']} max_h={r['max_height_seen']} "
            f"avg_holes={r['avg_holes_per_move']:.3f} pc={r['perfect_clears']} "
            f"garbage={r['garbage_rows_added']} clears={r['clear_counts']}"
        )
    client.close()
    elapsed = time.perf_counter() - start

    game_overs = sum(1 for r in results if r["game_over"])
    avg_moves = sum(r["moves_survived"] for r in results) / len(results)
    avg_lines = sum(r["total_lines"] for r in results) / len(results)
    total_pc = sum(r["perfect_clears"] for r in results)
    total_clear_counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for r in results:
        for k, v in r["clear_counts"].items():
            total_clear_counts[k] += v
    total_clears = sum(total_clear_counts.values())

    print()
    print(f"=== 集計 (n={len(results)}, think_seconds={args.think_seconds}, elapsed={elapsed:.1f}s) ===")
    print(f"ゲームオーバー率: {game_overs}/{len(results)}")
    print(f"平均生存手数: {avg_moves:.1f} / {args.max_moves}")
    print(f"平均消去ライン数: {avg_lines:.1f}")
    print(f"パーフェクトクリア合計: {total_pc}")
    for k in [1, 2, 3, 4]:
        n = total_clear_counts.get(k, 0)
        pct = n / total_clears * 100 if total_clears else 0
        print(f"  {k}ライン消去: {n}回 ({pct:.1f}%)")
