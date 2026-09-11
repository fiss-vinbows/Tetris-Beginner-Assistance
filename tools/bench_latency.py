"""Cold Clear 2との通信レイテンシを計測するベンチマーク。

「提示速度がまだ遅い」という指摘を受け、AssistWorkerの実際のtick処理の
どこに時間がかかっているかを切り分けるために作成した。

計測対象:
1. start_thinking() 呼び出し自体(送信のみ)の所要時間
2. start_thinking直後、有効なmoves(空でない)が返るまでの
   poll_suggestion()リトライ回数と所要時間(_tick_onceのリトライループを再現)
3. 同一ミノ操作中のpoll_suggestion() 1回あたりの所要時間(通信往復コスト)
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine.board_state import BoardState
from src.engine.cold_clear_client import ColdClearClient

N_TRIALS = 20


def main() -> None:
    client = ColdClearClient()

    start_times = []
    first_suggestion_times = []
    first_suggestion_retries = []
    poll_only_times = []

    board = BoardState()
    pieces = ["I", "O", "T", "S", "Z", "J", "L"]

    for i in range(N_TRIALS):
        current = pieces[i % 7]
        next_queue = [pieces[(i + k) % 7] for k in range(1, 6)]

        t0 = time.perf_counter()
        client.start_thinking(board, current, None, next_queue)
        t1 = time.perf_counter()
        start_times.append((t1 - t0) * 1000)

        retries = 0
        best = client.poll_suggestion(current)
        while best is None and retries < 20:
            time.sleep(0.001)
            best = client.poll_suggestion(current)
            retries += 1
        t2 = time.perf_counter()
        first_suggestion_times.append((t2 - t1) * 1000)
        first_suggestion_retries.append(retries)

        # 同一ミノ操作中のpollを模した追加計測(通信往復コストのみ)
        t3 = time.perf_counter()
        client.poll_suggestion(current)
        t4 = time.perf_counter()
        poll_only_times.append((t4 - t3) * 1000)

    client.close()

    def report(name: str, values: list[float]) -> None:
        print(
            f"{name}: mean={statistics.mean(values):.2f}ms "
            f"median={statistics.median(values):.2f}ms "
            f"max={max(values):.2f}ms min={min(values):.2f}ms"
        )

    print(f"=== {N_TRIALS}回試行 ===")
    report("start_thinking()送信のみ", start_times)
    report("start直後、初回有効moves取得まで", first_suggestion_times)
    print(
        f"初回有効moves取得までのリトライ回数: "
        f"mean={statistics.mean(first_suggestion_retries):.1f} "
        f"max={max(first_suggestion_retries)}"
    )
    report("同一局面へのpoll_suggestion()1回", poll_only_times)


if __name__ == "__main__":
    main()
