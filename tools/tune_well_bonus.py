"""well_bonus（Iミノ用の井戸を保持することへのボーナス）を変えながら、
ライン消去の内訳・生存手数・ゲームオーバー率を比較するチューニングスクリプト。

実機で「1列ずつしか消さない」という指摘を受け、evaluator.pyの
lines_clearedを非線形化(2乗)しただけでは改善しなかったため
（5手先読みでは「テトリスを待つ」という長期戦略を評価しきれないため）、
「井戸を保持していること自体」に1手ごとの評価で価値を持たせる
well_bonusの強化を検証する。
"""

from __future__ import annotations

import random
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine.board_state import BoardState
from src.engine.evaluator import DEFAULT_WEIGHTS
from src.engine.solver import find_best_move

PIECES = ["I", "O", "T", "S", "Z", "J", "L"]


def seven_bag_generator(seed: int):
    rng = random.Random(seed)
    while True:
        bag = PIECES[:]
        rng.shuffle(bag)
        yield from bag


def run(seed: int, weights, max_moves: int) -> dict:
    gen = seven_bag_generator(seed)
    board = BoardState()
    hold_piece: str | None = None
    current_piece = next(gen)
    next_queue = [next(gen) for _ in range(5)]
    just_held = False
    clear_counts = {1: 0, 2: 0, 3: 0, 4: 0}
    total_lines = 0
    move_count = 0
    game_over = False

    for move_count in range(1, max_moves + 1):
        best = find_best_move(board, current_piece, hold_piece, next_queue, allow_hold=not just_held, weights=weights)
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
            just_held = True
        else:
            just_held = False
        placed = board.place_piece(best.piece, best.rotation, best.origin_row, best.origin_col)
        board, lines = placed.clear_lines()
        total_lines += lines
        if lines:
            clear_counts[lines] += 1
        current_piece = next_queue.pop(0)
        next_queue.append(next(gen))

    return {
        "moves": move_count,
        "game_over": game_over,
        "total_lines": total_lines,
        "clear_counts": clear_counts,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=8)
    parser.add_argument("--max-moves", type=int, default=150)
    parser.add_argument("--values", type=str, default="0.22,1.0,1.5,2.0,2.5,3.0")
    args = parser.parse_args()

    for well_bonus in [float(v) for v in args.values.split(",")]:
        weights = replace(DEFAULT_WEIGHTS, well_bonus=well_bonus)
        total_clear_counts = {1: 0, 2: 0, 3: 0, 4: 0}
        total_lines = 0
        game_overs = 0
        total_moves = 0
        for seed in range(args.seeds):
            r = run(seed, weights, args.max_moves)
            total_lines += r["total_lines"]
            total_moves += r["moves"]
            if r["game_over"]:
                game_overs += 1
            for k, v in r["clear_counts"].items():
                total_clear_counts[k] += v

        total_clears = sum(total_clear_counts.values())
        parts = ", ".join(
            f"{k}L={v}({v/total_clears*100:.0f}%)" for k, v in total_clear_counts.items() if total_clears
        )
        print(
            f"well_bonus={well_bonus:.2f}: game_over={game_overs}/{args.seeds} "
            f"avg_moves={total_moves/args.seeds:.1f} avg_lines={total_lines/args.seeds:.1f} [{parts}]"
        )
