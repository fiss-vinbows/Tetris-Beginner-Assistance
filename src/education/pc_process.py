"""パフェ探索(pc_search.find_perfect_clear)を別のプロセスで動かす。

【2026-10-04・利用者の指摘(シミュレーターが重い)】パフェ探索(最大3秒)を裏のスレッドで動かしていたが、
Pythonは同時に1つのスレッドしか計算を進められない(GIL)ため、探索の間はキー入力・リピート・画面の更新が
待たされ、最大で約1秒止まっていた。継続パフェ(pc-odds)・AI(Cold Clear 2)と同じく別のプロセスで探す。

打ち切り: 共有メモリの番号(世代)を親が進め、子は探索中に自分の依頼の番号と違えば打ち切る(threading.Eventと
同じ is_set() を持つ _GenerationCancel を find_perfect_clear の cancel に渡す)。
"""

from __future__ import annotations

import multiprocessing
from concurrent.futures import Future, ProcessPoolExecutor

from src.education.pc_search import find_perfect_clear

_shared = None  # 子プロセス側: 親と共有する世代の番号(_init で受け取る)


class _GenerationCancel:
    """依頼した後に世代が進んだら(新しい依頼・打ち切り)立つ合図。"""

    def __init__(self, shared, generation: int) -> None:
        self.shared = shared
        self.generation = generation

    def is_set(self) -> bool:
        return self.shared.value != self.generation


def _init(shared) -> None:
    global _shared
    _shared = shared


def _search(generation: int, board, sequence, hold, can_hold: bool, time_limit: float):
    return find_perfect_clear(
        board, sequence, hold, can_hold=can_hold, time_limit=time_limit, cancel=_GenerationCancel(_shared, generation)
    )


class PcSearchProcess:
    """パフェ探索を1つの子プロセスで順に行う。新しい依頼を出すと前の探索は打ち切る。"""

    def __init__(self) -> None:
        self._context = multiprocessing.get_context("spawn")
        self._shared = self._context.Value("i", 0, lock=False)
        self._pool: ProcessPoolExecutor | None = None

    def submit(self, board, sequence, hold, can_hold: bool, time_limit: float) -> Future:
        self.cancel()  # 前の探索を打ち切る(子プロセスはすぐ次の依頼に移る)
        if self._pool is None:
            # 子プロセスは初めての依頼のときに起動し、以後は使い回す
            self._pool = ProcessPoolExecutor(
                max_workers=1, mp_context=self._context, initializer=_init, initargs=(self._shared,)
            )
        return self._pool.submit(
            _search, self._shared.value, frozenset(board), list(sequence), hold, can_hold, time_limit
        )

    def cancel(self) -> None:
        self._shared.value += 1

    def close(self) -> None:
        self.cancel()
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None
