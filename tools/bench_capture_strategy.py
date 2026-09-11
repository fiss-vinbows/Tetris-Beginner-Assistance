"""画面キャプチャの分割戦略を比較するベンチマーク。

bench_recognize.pyで、現在の「盤面+HOLD+NEXT全体を含む最小矩形を1回で
キャプチャする」方式が18ms程度かかっており、内訳の中で最大のボトルネックと
判明した。calibration.jsonの実際の座標を見ると、HOLD欄と盤面、盤面とNEXT欄の
間に大きな無駄な余白（キャプチャ対象外だが矩形に含まれてしまう領域）がある
ことが分かったため、「意味のある3つの塊（盤面・HOLD・NEXT全体）」に分けて
個別にgrab()する方式と比較する。

過去の計測で「7回完全に個別にgrab()」=約72ms、「1回にまとめる」=約20msという
結果があったが、これは無駄な余白を含めても呼び出し回数を減らす方が支配的
だったことを示す。今回は「呼び出し回数はやや増えるが、無駄なピクセル数は
大幅に減る」中間案が有利かどうかを検証する。
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.capture.calibrate import load_calibration
from src.capture.screen_capture import CaptureRegion, ScreenCapture

N_TRIALS = 30


def _bounds(rects: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    min_x = min(x for x, _y, _w, _h in rects)
    min_y = min(y for _x, y, _w, _h in rects)
    max_x = max(x + w for x, _y, w, _h in rects)
    max_y = max(y + h for _x, y, _w, h in rects)
    return min_x, min_y, max_x - min_x, max_y - min_y


def main() -> None:
    calibration = load_calibration()
    capture = ScreenCapture()

    board_rect = (
        calibration.board_origin_x, calibration.board_origin_y,
        calibration.board_width, calibration.board_height,
    )
    hold_rect = tuple(calibration.hold_rect)
    next_rects = [tuple(r) for r in calibration.next_rects]

    all_rects = [board_rect, hold_rect, *next_rects]
    whole_region = CaptureRegion(*_bounds(all_rects))
    whole_pixels = whole_region.width * whole_region.height

    board_region = CaptureRegion(*board_rect)
    hold_region = CaptureRegion(*hold_rect)
    next_region = CaptureRegion(*_bounds(next_rects))
    split_pixels = (
        board_region.width * board_region.height
        + hold_region.width * hold_region.height
        + next_region.width * next_region.height
    )

    print(f"全体矩形: {whole_region.width}x{whole_region.height} = {whole_pixels}px")
    print(
        f"3分割合計: 盤面{board_region.width}x{board_region.height} + "
        f"HOLD{hold_region.width}x{hold_region.height} + "
        f"NEXT全体{next_region.width}x{next_region.height} = {split_pixels}px "
        f"(削減率 {(1 - split_pixels / whole_pixels) * 100:.1f}%)"
    )

    whole_times = []
    for _ in range(N_TRIALS):
        t0 = time.perf_counter()
        capture.grab(whole_region)
        t1 = time.perf_counter()
        whole_times.append((t1 - t0) * 1000)

    split_times = []
    for _ in range(N_TRIALS):
        t0 = time.perf_counter()
        capture.grab(board_region)
        capture.grab(hold_region)
        capture.grab(next_region)
        t1 = time.perf_counter()
        split_times.append((t1 - t0) * 1000)

    capture.close()

    def report(name: str, values: list[float]) -> None:
        print(
            f"{name}: mean={statistics.mean(values):.2f}ms "
            f"median={statistics.median(values):.2f}ms "
            f"max={max(values):.2f}ms min={min(values):.2f}ms"
        )

    print()
    report("方式A: 全体を1回でgrab", whole_times)
    report("方式B: 盤面/HOLD/NEXT全体の3回に分けてgrab", split_times)


if __name__ == "__main__":
    main()
