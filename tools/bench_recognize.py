"""recognize()の内部処理時間の内訳を計測するベンチマーク。

「提示速度がまだ遅い」という指摘を受け、通信レイテンシ(bench_latency.py、
1-3ms程度でボトルネックでないと判明済み)ではなく、recognize()
(画面キャプチャ+盤面認識)側にどれだけ時間がかかっているかを切り分けるために
作成した。ゲームが起動していなくても、キャリブレーション座標そのものへの
キャプチャ・画像処理コストは計測できる(認識結果自体は無効になるが、
処理時間の内訳を見るのが目的なので問題ない)。
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.capture.calibrate import load_calibration
from src.capture.screen_capture import CaptureRegion, ScreenCapture
from src.vision.board_reader import read_board_grid_with_samples
from src.vision.next_hold_reader import read_piece_from_patch

N_TRIALS = 30


def main() -> None:
    calibration = load_calibration()
    capture = ScreenCapture()

    board_region = CaptureRegion(
        calibration.board_origin_x, calibration.board_origin_y,
        calibration.board_width, calibration.board_height,
    )
    hold_region = CaptureRegion(*calibration.hold_rect)

    rects = [
        (calibration.board_origin_x, calibration.board_origin_y, calibration.board_width, calibration.board_height),
        calibration.hold_rect,
        *calibration.next_rects,
    ]
    min_x = min(x for x, _y, _w, _h in rects)
    min_y = min(y for _x, y, _w, _h in rects)
    max_x = max(x + w for x, _y, w, _h in rects)
    max_y = max(y + h for _x, y, _w, h in rects)

    capture_times = []
    board_read_times = []
    next_hold_read_times = []
    total_times = []

    for _ in range(N_TRIALS):
        t0 = time.perf_counter()
        full_img = capture.grab(CaptureRegion(min_x, min_y, max_x - min_x, max_y - min_y))
        t1 = time.perf_counter()

        def _crop(region: CaptureRegion):
            x0 = region.left - min_x
            y0 = region.top - min_y
            return full_img[y0 : y0 + region.height, x0 : x0 + region.width]

        board_img = _crop(board_region)
        hold_img = _crop(hold_region)
        next_imgs = [_crop(CaptureRegion(*rect)) for rect in calibration.next_rects]

        t2 = time.perf_counter()
        read_board_grid_with_samples(board_img, cols=calibration.board_cols, rows=calibration.board_rows)
        t3 = time.perf_counter()

        read_piece_from_patch(hold_img)
        for img in next_imgs:
            read_piece_from_patch(img)
        t4 = time.perf_counter()

        capture_times.append((t1 - t0) * 1000)
        board_read_times.append((t3 - t2) * 1000)
        next_hold_read_times.append((t4 - t3) * 1000)
        total_times.append((t4 - t0) * 1000)

    capture.close()

    def report(name: str, values: list[float]) -> None:
        print(
            f"{name}: mean={statistics.mean(values):.2f}ms "
            f"median={statistics.median(values):.2f}ms "
            f"max={max(values):.2f}ms min={min(values):.2f}ms"
        )

    print(f"=== recognize()内部処理の内訳 (n={N_TRIALS}) ===")
    report("画面キャプチャ(grab)", capture_times)
    report("盤面読み取り(read_board_grid_with_samples)", board_read_times)
    report("HOLD+NEXT5枠読み取り(read_piece_from_patch x6)", next_hold_read_times)
    report("合計", total_times)


if __name__ == "__main__":
    main()
