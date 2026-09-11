"""キャリブレーションツール

対象ゲーム画面上で、盤面/ホールド欄/NEXT欄の位置を順にクリックしてもらい、
その座標から各領域の矩形を算出して config/calibration.json に保存する。

NEXT欄はぷよぷよテトリスのレイアウト（同サイズの枠が縦に等間隔で並ぶ）を前提に、
1番目の枠の矩形と2番目の枠の左上だけから残り4個分の位置を算出する。

一度キャリブレーションすれば、同じウィンドウ配置・解像度である限り再利用できる。
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "calibration.json"

BOARD_COLS = 10
BOARD_ROWS = 20
NEXT_SLOT_COUNT = 5

_STEPS: list[tuple[str, str]] = [
    ("board_top_left", "盤面の左上マスの角をクリックしてください"),
    ("board_bottom_right", "盤面の右下マスの角をクリックしてください"),
    ("hold_top_left", "ホールド欄の左上をクリックしてください"),
    ("hold_bottom_right", "ホールド欄の右下をクリックしてください"),
    ("next1_top_left", "NEXT欄の1番上の枠の左上をクリックしてください"),
    ("next1_bottom_right", "NEXT欄の1番上の枠の右下をクリックしてください"),
    ("next2_top_left", "NEXT欄の2番目の枠の左上をクリックしてください（間隔算出用）"),
]

# 矢印キー1つにつき、キャリブレーション矩形を動かす/伸縮させるピクセル数。
_ARROW_KEY_DELTAS: dict[QtCore.Qt.Key, tuple[int, int]] = {
    QtCore.Qt.Key.Key_Left: (-1, 0),
    QtCore.Qt.Key.Key_Right: (1, 0),
    QtCore.Qt.Key.Key_Up: (0, -1),
    QtCore.Qt.Key.Key_Down: (0, 1),
}


def adjust_calibration_rect(
    rect: tuple[int, int, int, int], key: QtCore.Qt.Key, resize: bool
) -> tuple[int, int, int, int] | None:
    """矢印キー入力に応じてキャリブレーション矩形(x, y, w, h)を1px調整する。

    2点クリックだけによる位置決めは、マウスでピクセル単位に正確に角を
    クリックすることが人間には難しく、数px単位のズレが生じやすい。この
    ズレが原因で盤面のマス境界の色判定が不安定になり、隣接するマスの
    色を取り違える不具合が疑われたため、クリック後に実際の10x20グリッド線を
    ゲーム画面に重ねて表示し、矢印キーで見た目に合わせて微調整できる
    ようにする(Qtに依存しない純粋関数にして単体テスト可能にしている)。

    resize=Falseなら矩形全体を平行移動(左上の位置合わせ)、resize=Trueなら
    右下の角だけを動かす(大きさの微調整)。矢印キー以外が渡された場合はNoneを返す。
    """
    delta = _ARROW_KEY_DELTAS.get(key)
    if delta is None:
        return None
    dx, dy = delta
    x, y, w, h = rect
    if resize:
        return (x, y, max(1, w + dx), max(1, h + dy))
    return (x + dx, y + dy, w, h)


@dataclass
class CalibrationResult:
    board_origin_x: int
    board_origin_y: int
    # board_width/board_heightを実測値として直接保持する(cell_size*board_colsで
    # 計算すると、丸め誤差が列数・行数ぶん蓄積して右端/下端が数px～10pxずれ、
    # 盤面外の要素を誤読み込みする原因になったため)。cell_sizeはセル分割用に残す。
    board_width: int
    board_height: int
    cell_size: int
    board_cols: int
    board_rows: int
    hold_rect: tuple[int, int, int, int]  # (x, y, w, h)
    next_rects: list[tuple[int, int, int, int]]  # 上から順にNEXT_SLOT_COUNT個

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "CalibrationResult":
        return CalibrationResult(
            board_origin_x=data["board_origin_x"],
            board_origin_y=data["board_origin_y"],
            board_width=data["board_width"],
            board_height=data["board_height"],
            cell_size=data["cell_size"],
            board_cols=data["board_cols"],
            board_rows=data["board_rows"],
            hold_rect=tuple(data["hold_rect"]),
            next_rects=[tuple(r) for r in data["next_rects"]],
        )


def load_calibration(path: Path = CONFIG_PATH) -> CalibrationResult:
    data = json.loads(path.read_text(encoding="utf-8"))
    return CalibrationResult.from_dict(data)


class CalibrationOverlay(QtWidgets.QWidget):
    """全画面を覆う半透明ウィンドウ上で、指示に従ってクリックしてもらうためのUI"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint | QtCore.Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        # close()時に実際にオブジェクトを破棄してdestroyedシグナルを発火させる
        # (run_calibration()がネストしたQEventLoopで完了待ちするために必要)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)

        screen = QtWidgets.QApplication.primaryScreen()
        self.setGeometry(screen.geometry())

        self._step_index = 0
        self._points: dict[str, tuple[int, int]] = {}
        # 盤面の2点クリック直後、10x20グリッド線を実際にゲーム画面へ重ねて
        # 表示し、矢印キーで見た目に合わせて微調整するフェーズ用の状態。
        # 物理ピクセル座標の(x, y, w, h)。Noneの間は微調整フェーズではない。
        self._fine_tune_rect: tuple[int, int, int, int] | None = None

        self._label = QtWidgets.QLabel(self)
        self._label.setStyleSheet(
            "background-color: rgba(0,0,0,190); color: white; font-size: 20px; padding: 14px;"
        )
        self._label.move(40, 40)
        self._update_label()

    def _update_label(self) -> None:
        if self._fine_tune_rect is not None:
            self._label.setText(
                "緑の格子がゲーム画面の10x20マスとぴったり重なるよう、矢印キーで"
                "位置を微調整してください。\n"
                "矢印キー: 全体を1pxずつ移動 / Shift+矢印キー: 右下の大きさを1pxずつ調整\n"
                "Enterで確定 (Escでキャンセル)"
            )
            self._label.adjustSize()
            return
        if self._step_index >= len(_STEPS):
            return
        _, message = _STEPS[self._step_index]
        self._label.setText(f"[{self._step_index + 1}/{len(_STEPS)}] {message}\n(Escでキャンセル)")
        self._label.adjustSize()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if self._fine_tune_rect is not None or self._step_index >= len(_STEPS):
            return
        key, _ = _STEPS[self._step_index]
        pos = event.globalPosition().toPoint()
        # Qtが返すクリック座標は論理ピクセル(DPIスケール適用後)だが、
        # 画面キャプチャ(mss)は物理ピクセル座標を使うため、ここで物理座標に変換して保存する。
        # これをしないと、DPIスケールが100%でない環境(マルチモニタでスケールが
        # 異なる場合など)でキャプチャ位置が実際のUIとずれる。
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        dpr = screen.devicePixelRatio()
        self._points[key] = (round(pos.x() * dpr), round(pos.y() * dpr))
        self._step_index += 1
        if key == "board_bottom_right":
            # 盤面の2点クリックだけでは、マウスでピクセル単位に正確に角を
            # クリックすることが人間には難しく数pxのズレが生じやすい
            # (このズレがマス境界の色誤判定の一因と疑われた)。すぐ次の
            # ステップへ進めず、実際のグリッド線を重ねて目視で微調整する
            # フェーズを挟む。
            bx1, by1 = self._points["board_top_left"]
            bx2, by2 = self._points["board_bottom_right"]
            self._fine_tune_rect = (bx1, by1, bx2 - bx1, by2 - by1)
            self._update_label()
        elif self._step_index >= len(_STEPS):
            self._finish()
        else:
            self._update_label()
        self.update()

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:  # noqa: N802
        if event.key() == QtCore.Qt.Key.Key_Escape:
            self.close()
            return
        if self._fine_tune_rect is None:
            return
        if event.key() in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            # 微調整結果を、後続ステップ(hold/next)が参照する
            # board_top_left/board_bottom_rightへ書き戻して確定する。
            x, y, w, h = self._fine_tune_rect
            self._points["board_top_left"] = (x, y)
            self._points["board_bottom_right"] = (x + w, y + h)
            self._fine_tune_rect = None
            if self._step_index >= len(_STEPS):
                self._finish()
            else:
                self._update_label()
            self.update()
            return
        resize = bool(event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier)
        adjusted = adjust_calibration_rect(self._fine_tune_rect, event.key(), resize)
        if adjusted is not None:
            self._fine_tune_rect = adjusted
            self.update()

    def paintEvent(self, event: QtCore.QEvent) -> None:  # noqa: N802
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        # Windows環境では完全に透明(alpha=0)なままの領域はクリックイベントを
        # 拾えないことがあるため、ごく薄い色で画面全体を塗ってクリック判定を確保する
        painter.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 1))
        if self._fine_tune_rect is not None:
            self._draw_fine_tune_grid(painter)
            painter.end()
            return
        pen = QtGui.QPen(QtGui.QColor(0, 255, 120, 255), 3)
        painter.setPen(pen)
        # self._pointsは物理ピクセル座標で保存されているが、mapFromGlobalはQtの
        # 論理座標系を期待するため、表示用にdprで割って論理座標へ戻してから変換する
        # (これを忘れると、クリック位置を示す円がDPI倍だけずれた場所に描画される)
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        dpr = screen.devicePixelRatio()
        for x, y in self._points.values():
            local = self.mapFromGlobal(QtCore.QPoint(round(x / dpr), round(y / dpr)))
            painter.drawEllipse(local, 6, 6)
        painter.end()

    def _draw_fine_tune_grid(self, painter: QtGui.QPainter) -> None:
        """微調整フェーズ用の10x20グリッド線を、ゲーム画面に重ねて描画する。"""
        assert self._fine_tune_rect is not None
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        dpr = screen.devicePixelRatio()
        x, y, w, h = self._fine_tune_rect
        top_left = self.mapFromGlobal(QtCore.QPoint(round(x / dpr), round(y / dpr)))
        logical_w = w / dpr
        logical_h = h / dpr

        pen = QtGui.QPen(QtGui.QColor(0, 255, 120, 220), 1)
        painter.setPen(pen)
        painter.drawRect(QtCore.QRectF(top_left.x(), top_left.y(), logical_w, logical_h))
        for c in range(1, BOARD_COLS):
            lx = top_left.x() + logical_w * c / BOARD_COLS
            painter.drawLine(QtCore.QPointF(lx, top_left.y()), QtCore.QPointF(lx, top_left.y() + logical_h))
        for r in range(1, BOARD_ROWS):
            ly = top_left.y() + logical_h * r / BOARD_ROWS
            painter.drawLine(QtCore.QPointF(top_left.x(), ly), QtCore.QPointF(top_left.x() + logical_w, ly))

    def _finish(self) -> None:
        bx1, by1 = self._points["board_top_left"]
        bx2, by2 = self._points["board_bottom_right"]
        hx1, hy1 = self._points["hold_top_left"]
        hx2, hy2 = self._points["hold_bottom_right"]
        n1x1, n1y1 = self._points["next1_top_left"]
        n1x2, n1y2 = self._points["next1_bottom_right"]
        n2x1, n2y1 = self._points["next2_top_left"]

        board_w = bx2 - bx1
        board_h = by2 - by1
        cell_size = round(((board_w / BOARD_COLS) + (board_h / BOARD_ROWS)) / 2)

        next_w = n1x2 - n1x1
        next_h = n1y2 - n1y1
        slot_pitch_y = n2y1 - n1y1  # 1番目の枠の左上から2番目の枠の左上までの縦間隔
        next_rects = [
            (n1x1, n1y1 + i * slot_pitch_y, next_w, next_h) for i in range(NEXT_SLOT_COUNT)
        ]

        result = CalibrationResult(
            board_origin_x=bx1,
            board_origin_y=by1,
            board_width=board_w,
            board_height=board_h,
            cell_size=cell_size,
            board_cols=BOARD_COLS,
            board_rows=BOARD_ROWS,
            hold_rect=(hx1, hy1, hx2 - hx1, hy2 - hy1),
            next_rects=next_rects,
        )

        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"キャリブレーション結果を保存しました: {CONFIG_PATH}")
        self.close()


def run_calibration() -> None:
    """キャリブレーションを実行する。

    既にQApplicationが動いている状態（app.pyのメインウィンドウから呼ばれる場合）でも
    安全に使えるよう、その場合はネストしたQEventLoopで待機し、
    トップレベルのapp.exec()を二重に呼ばないようにする。
    """
    existing_app = QtWidgets.QApplication.instance()
    app = existing_app if existing_app is not None else QtWidgets.QApplication(sys.argv)

    overlay = CalibrationOverlay()
    overlay.showFullScreen()

    if existing_app is None:
        app.exec()
    else:
        loop = QtCore.QEventLoop()
        overlay.destroyed.connect(loop.quit)
        loop.exec()


if __name__ == "__main__":
    run_calibration()
