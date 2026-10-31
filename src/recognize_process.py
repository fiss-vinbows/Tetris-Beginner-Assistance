"""画面の撮影と画像認識(recognize)を別のプロセスで行う。

【2026-10-31・利用者の指摘(ローカル対戦で双方とも遅すぎる)】1P と 2P の支援(全自動)を同じプロセスで動かすと、
Python は同時に1つのスレッドしか計算を進められない(GIL)ため、2人分の画像認識が取り合いになり、1回の読み取りが
75ms から約125ms に遅くなった(debug_log_20261031_094304)。全自動は1手ごとに読み取りを何回も待つので、それが
そのまま1手の遅さになった。

側ごとに、撮影と認識だけをする子プロセスを1つ持つ。ワーカー(QThread)は依頼を送って結果を待つだけなので、
待つ間は GIL を手放し、2人分の読み取りが同時に進む。recognize は前回の結果をヒントとして受け取るだけの関数
なので、ヒントも一緒に送る。子プロセスが動かない時は、呼び出し側が今までどおり自分のスレッドで認識する。
"""

from __future__ import annotations

import multiprocessing
from typing import Any

# 子プロセスの起動(src.app の読み込みに1〜2秒)を待つ上限と、1回の認識を待つ上限(秒)
START_TIMEOUT_SEC = 15.0
RECOGNIZE_TIMEOUT_SEC = 5.0


def _serve(conn) -> None:  # noqa: ANN001
    """子プロセス: 依頼(キャリブレーション, 引数)を受けて、撮影と認識をして結果を返す。None で終わる。"""
    from src.app import recognize
    from src.capture.screen_capture import ScreenCapture

    conn.send(("ready", None))
    with ScreenCapture() as capture:
        while True:
            message = conn.recv()
            if message is None:
                break
            calibration, kwargs = message
            try:
                conn.send(("ok", recognize(calibration, capture, **kwargs)))
            except Exception as exc:  # noqa: BLE001 - 認識失敗の1回で子プロセスを止めない
                conn.send(("error", repr(exc)))


class RecognizerProcess:
    """撮影と認識をする子プロセス1つ。recognize() は src.app.recognize と同じ引数(capture を除く)。"""

    def __init__(self) -> None:
        context = multiprocessing.get_context("spawn")
        self._conn, child = context.Pipe()
        self._process = context.Process(target=_serve, args=(child,), daemon=True)
        self._process.start()
        child.close()
        if not self._conn.poll(START_TIMEOUT_SEC):
            self.close()
            raise TimeoutError("画像認識の子プロセスが起動しません")
        self._conn.recv()  # ("ready", None)

    def recognize(self, calibration, **kwargs: Any):  # noqa: ANN001, ANN201
        self._conn.send((calibration, kwargs))
        if not self._conn.poll(RECOGNIZE_TIMEOUT_SEC):
            raise TimeoutError("画像認識の子プロセスから応答がありません")
        status, result = self._conn.recv()
        if status != "ok":
            raise RuntimeError(f"子プロセスでの認識エラー: {result}")
        return result

    def close(self) -> None:
        try:
            self._conn.send(None)
        except (OSError, ValueError):
            pass
        self._process.join(2.0)
        if self._process.is_alive():
            self._process.terminate()
        self._conn.close()
