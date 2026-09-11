"""debug_frames_historyの提案マスを、生画像(board.png)の再読み取り結果と突き合わせる。

残課題_2026-09-10.txt 3-2の手順の自動化。各提案について
  ・生画像で占有と読めるマスに提案が重なっていないか(干渉)
  ・提案の直下が生画像で空いていないか(空中)
を数える。使い方: ./venv/Scripts/python.exe tools/audit_frame_history.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.vision.board_reader import read_board_grid  # noqa: E402

COLS, ROWS = 10, 20


def main() -> None:
    interference = floating = total = 0
    for d in sorted((ROOT / "debug_frames_history").iterdir()):
        info = (d / "info.txt").read_text(encoding="utf-8").splitlines()
        if len(info) < 4 or "best:" not in info[3]:
            continue
        dump = [line for line in info[4:] if line and len(line) == COLS and set(line) <= set(".#ILOZSTJGU")]
        top = ROWS - len(dump)
        cells = [(top + i, c) for i, line in enumerate(dump) for c, ch in enumerate(line) if ch == "#"]
        if not cells:
            continue
        total += 1
        raw = read_board_grid(np.array(Image.open(d / "board.png").convert("RGB")), COLS, ROWS)
        overlap = [(r, c) for r, c in cells if raw[r][c] is not None]
        supported = any(
            r + 1 >= ROWS or (r + 1, c) in cells or raw[r + 1][c] is not None for r, c in cells
        )
        tag = []
        if overlap:
            interference += 1
            tag.append(f"干渉{overlap}")
        if not supported:
            floating += 1
            tag.append("空中")
        print(f"{d.name} {info[0][11:23]} {info[3][:60]} {' '.join(tag)}")
    print(f"\n提案{total}件: 干渉{interference}件 空中{floating}件")


if __name__ == "__main__":
    main()
