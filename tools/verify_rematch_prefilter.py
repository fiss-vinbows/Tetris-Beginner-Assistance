"""再照合の事前判定(2-1)の検証: 保存画像40枚で旧方式と新方式をセル単位・時間で比較する。

使い方: ./venv/Scripts/python.exe tools/verify_rematch_prefilter.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.vision import template_matcher as tm  # noqa: E402
from src.vision.board_reader import read_board_grid  # noqa: E402

COLS, ROWS = 10, 20
HISTORY = ROOT / "debug_frames_history"


def _read_all(images: list[np.ndarray]) -> tuple[list, list[float]]:
    grids = []
    times = []
    for img in images:
        t0 = time.perf_counter()
        grids.append(read_board_grid(img, COLS, ROWS))
        times.append((time.perf_counter() - t0) * 1000)
    return grids, times


def main() -> None:
    images = [
        np.array(Image.open(d / "board.png").convert("RGB"))
        for d in sorted(HISTORY.iterdir())
        if (d / "board.png").exists()
    ]
    print(f"画像枚数: {len(images)}")

    # 旧方式: 事前判定を無効化(彩度しきい値を0にすると常に再照合する)
    original = tm._REMATCH_MIN_CHROMA
    tm._REMATCH_MIN_CHROMA = 0.0
    _read_all(images)  # ウォームアップ(キャッシュ生成)
    old_grids, old_times = _read_all(images)
    tm._REMATCH_MIN_CHROMA = original
    _read_all(images)
    new_grids, new_times = _read_all(images)

    empty_to_block = block_to_empty = label_changed = 0
    total_cells = 0
    for og, ng in zip(old_grids, new_grids):
        for r in range(ROWS):
            for c in range(COLS):
                total_cells += 1
                o, n = og[r][c], ng[r][c]
                if o == n:
                    continue
                if o is None:
                    empty_to_block += 1
                elif n is None:
                    block_to_empty += 1
                else:
                    label_changed += 1
    print(f"総セル数: {total_cells}")
    print(f"  空→占有: {empty_to_block}  占有→空: {block_to_empty}  種類変化: {label_changed}")

    def stats(xs: list[float]) -> str:
        a = np.array(xs)
        return f"中央値={np.median(a):.1f}ms 95%={np.percentile(a, 95):.1f}ms 最大={a.max():.1f}ms"

    print(f"旧方式(常に再照合): {stats(old_times)}")
    print(f"新方式(彩度で限定): {stats(new_times)}")


if __name__ == "__main__":
    main()
