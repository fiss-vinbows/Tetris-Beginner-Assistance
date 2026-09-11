"""mssによる画面領域の高速キャプチャ"""

from __future__ import annotations

from dataclasses import dataclass

import mss
import numpy as np


@dataclass(frozen=True)
class CaptureRegion:
    left: int
    top: int
    width: int
    height: int

    def to_mss_dict(self) -> dict[str, int]:
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}


class ScreenCapture:
    """1つの画面領域を継続的にキャプチャするためのラッパー。

    mss.mss()はスレッドごとに1インスタンスが必要なため、
    このクラスのインスタンスは呼び出し元スレッド内でのみ使い回すこと。
    """

    def __init__(self) -> None:
        self._sct = mss.mss()

    def grab(self, region: CaptureRegion) -> np.ndarray:
        """指定領域をキャプチャし、RGB順のnumpy配列 (height, width, 3) で返す"""
        shot = self._sct.grab(region.to_mss_dict())
        # mssはBGRA順で返すため、RGBに変換する
        frame = np.array(shot)[:, :, :3][:, :, ::-1]
        return frame

    def close(self) -> None:
        self._sct.close()

    def __enter__(self) -> "ScreenCapture":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
