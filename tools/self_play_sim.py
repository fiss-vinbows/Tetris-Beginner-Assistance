"""思考ルーチン(evaluator+solver)だけで何十手も連続プレイさせ、
盤面の質がどう推移するかを検証する自己対戦シミュレーター。

画像認識を一切介さず、7-bag方式のランダムなミノ供給に対して
find_best_moveを繰り返し呼び出し、実際の連続プレイで積み方が
悪化していく傾向がないかを確認する。個別の局面テスト(tests/)では
「1手だけ見れば正しい」ことしか確認できないため、実プレイで
指摘された「継続的にいびつな積み方になる」問題の原因を
探るために作成した。
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine.board_state import BoardState
from src.engine.solver import find_best_move

PIECES = ["I", "O", "T", "S", "Z", "J", "L"]


def seven_bag_generator(seed: int):
    rng = random.Random(seed)
    while True:
        bag = PIECES[:]
        rng.shuffle(bag)
        yield from bag


def print_board(board: BoardState) -> None:
    top = 0
    for r in range(board.height):
        if any(cell is not None for cell in board.grid[r]):
            top = r
            break
    else:
        top = board.height
    for r in range(top, board.height):
        print("".join(c if c else "." for c in board.grid[r]))


def run_simulation(seed: int, max_moves: int = 200, verbose_every: int = 0) -> dict:
    gen = seven_bag_generator(seed)
    board = BoardState()
    hold_piece: str | None = None
    current_piece = next(gen)
    queue_lookahead = 5
    next_queue = [next(gen) for _ in range(queue_lookahead)]

    total_lines = 0
    move_count = 0
    max_height_seen = 0
    total_holes_seen = 0
    just_held = False
    clear_counts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}

    for move_count in range(1, max_moves + 1):
        best = find_best_move(
            board, current_piece, hold_piece, next_queue, allow_hold=not just_held
        )
        if best is None:
            break  # 置き場所がない = ゲームオーバー

        if best.use_hold:
            if hold_piece is None:
                # 現在ピースをホールドし、next_queue先頭を代わりに使う
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
        clear_counts[lines] = clear_counts.get(lines, 0) + 1

        heights = board.column_heights()
        max_height_seen = max(max_height_seen, max(heights))
        total_holes_seen += board.count_holes()

        current_piece = next_queue.pop(0)
        next_queue.append(next(gen))

        if verbose_every and move_count % verbose_every == 0:
            print(f"--- move {move_count} (lines={total_lines}, holes={board.count_holes()}, "
                  f"max_height={max(heights)}) ---")
            print_board(board)
            print()

    return {
        "moves_survived": move_count,
        "total_lines": total_lines,
        "final_holes": board.count_holes(),
        "max_height_seen": max_height_seen,
        "avg_holes_per_move": total_holes_seen / move_count if move_count else 0,
        "game_over": best is None if move_count < max_moves else False,
        "clear_counts": clear_counts,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=10, help="試行するシード数")
    parser.add_argument("--max-moves", type=int, default=200)
    parser.add_argument("--verbose-seed", type=int, default=None, help="このシードだけ盤面を逐次表示する")
    args = parser.parse_args()

    if args.verbose_seed is not None:
        result = run_simulation(args.verbose_seed, args.max_moves, verbose_every=10)
        print(result)
    else:
        results = []
        for seed in range(args.seeds):
            r = run_simulation(seed, args.max_moves)
            results.append(r)
            print(f"seed={seed}: moves={r['moves_survived']} lines={r['total_lines']} "
                  f"game_over={r['game_over']} max_h={r['max_height_seen']} "
                  f"avg_holes={r['avg_holes_per_move']:.2f}")

        game_overs = sum(1 for r in results if r["game_over"])
        avg_moves = sum(r["moves_survived"] for r in results) / len(results)
        avg_lines = sum(r["total_lines"] for r in results) / len(results)

        total_clear_counts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
        for r in results:
            for k, v in r["clear_counts"].items():
                total_clear_counts[k] = total_clear_counts.get(k, 0) + v
        clears_only = {k: v for k, v in total_clear_counts.items() if k > 0}
        total_clear_events = sum(clears_only.values())

        print()
        print(f"=== 集計 (n={len(results)}) ===")
        print(f"ゲームオーバー率: {game_overs}/{len(results)}")
        print(f"平均生存手数: {avg_moves:.1f} / {args.max_moves}")
        print(f"平均消去ライン数: {avg_lines:.1f}")
        print(f"ライン消去の内訳 (全{total_clear_events}回):")
        for k in [1, 2, 3, 4]:
            n = clears_only.get(k, 0)
            pct = n / total_clear_events * 100 if total_clear_events else 0
            print(f"  {k}ライン消去: {n}回 ({pct:.1f}%)")
