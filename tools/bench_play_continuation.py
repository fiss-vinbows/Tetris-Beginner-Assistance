"""探索木の引き継ぎ(play)の効果を測る。

「提示どおりに置いた直後(10ms)の結果」が「1.5秒考えた後の結果」と一致する
割合を、play(引き継ぎ)とstart(渡し直し)で比較する。
使い方: ./venv/Scripts/python.exe tools/bench_play_continuation.py
"""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.app import _board_after_placement  # noqa: E402
from src.engine.board_state import BoardState  # noqa: E402
from src.engine.cold_clear_client import ColdClearClient  # noqa: E402


def _bag():
    while True:
        b = list("IOTSZJL")
        random.shuffle(b)
        yield from b


def _apply(board, hold, up, mv):
    board = _board_after_placement(board, mv.piece, tuple(mv.landing_cells))
    if mv.piece == up[0]:
        up.pop(0)
    elif hold is not None and mv.piece == hold:
        hold = up.pop(0)
    elif hold is None and mv.piece == up[1]:
        hold = up.pop(0)
        up.pop(0)
    else:
        raise RuntimeError("提案のミノが局面と合わない")
    return board, hold


def main(turns: int = 15, think_sec: float = 1.5) -> None:
    random.seed(3)
    g = _bag()
    up = [next(g) for _ in range(turns * 2 + 20)]
    cc = ColdClearClient()
    board, hold = BoardState(), None
    cc.start_thinking(board, up[0], hold, up[1:6])
    same_play = same_start = 0
    for _ in range(turns):
        time.sleep(think_sec)
        deep = cc.poll_suggestion(up[0])
        board, hold = _apply(board, hold, up, deep)
        cc.advance_thinking(deep.placement, [up[5]] if hold is None else [up[4]])
        time.sleep(0.01)
        quick = cc.poll_suggestion(up[0])
        time.sleep(think_sec)
        ref = cc.poll_suggestion(up[0])
        same_play += quick is not None and (quick.piece, quick.landing_cells) == (ref.piece, ref.landing_cells)
        cc.start_thinking(board, up[0], hold, up[1:6])
        time.sleep(0.01)
        quick2 = cc.poll_suggestion(up[0])
        time.sleep(think_sec)
        ref2 = cc.poll_suggestion(up[0])
        same_start += quick2 is not None and (quick2.piece, quick2.landing_cells) == (ref2.piece, ref2.landing_cells)
    cc.close()
    print(f"手番{turns}: play直後の即時結果が{think_sec}秒後と一致={same_play}/{turns}")
    print(f"        start直後の即時結果が{think_sec}秒後と一致={same_start}/{turns}")


if __name__ == "__main__":
    main()
