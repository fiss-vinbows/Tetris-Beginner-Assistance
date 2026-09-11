"""動画ファイルからフレームを読み込むキャプチャソース

実機の画面キャプチャ(screen_capture.ScreenCapture)と同じ「1フレーム=RGB numpy配列」という
インターフェースに揃えており、録画済みのプレイ動画を使った動作検証や、
実機なしでのオフライン解析に使える。
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


class VideoFileSource:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._cap = cv2.VideoCapture(str(self._path))
        if not self._cap.isOpened():
            raise FileNotFoundError(f"動画ファイルを開けませんでした: {path}")

    @property
    def fps(self) -> float:
        return self._cap.get(cv2.CAP_PROP_FPS)

    @property
    def frame_count(self) -> int:
        return int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))

    def read_frame(self) -> np.ndarray | None:
        """次のフレームをRGB配列 (height, width, 3) で返す。動画終端に達したらNone。"""
        ok, frame_bgr = self._cap.read()
        if not ok:
            return None
        return frame_bgr[:, :, ::-1]  # OpenCVはBGR順で返すためRGBに変換

    def seek_frame(self, frame_index: int) -> None:
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)

    def close(self) -> None:
        self._cap.release()

    def __enter__(self) -> "VideoFileSource":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def crop_region(frame: np.ndarray, left: int, top: int, width: int, height: int) -> np.ndarray:
    """フレームからキャリブレーション済みの矩形領域（盤面/HOLD/NEXT欄など）を切り出す"""
    return frame[top : top + height, left : left + width]
