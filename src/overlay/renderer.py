"""最善手オーバーレイの描画ロジック

QPainterに対する純粋な描画処理のみを担当し、
実ウィンドウへの描画・オフスクリーン画像への描画のどちらからも共用できる。
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6 import QtCore, QtGui

from src.vision.piece_colors import PIECE_COLORS

# 着地マスは「枠で囲む」方式だと、ゲーム側の操作ガイド（ドロップ先を示す
# ゴーストピースの枠線）と重なって見づらいというフィードバックを受け、
# 各マスの中心に点を打つだけの控えめな表示に変更した。
LANDING_DOT_RADIUS_RATIO = 0.22  # セルサイズに対するドット半径の比率
LANDING_DOT_OUTLINE_WIDTH = 3  # ドットの白い縁取りの太さ（どんな背景色でも視認できるように）


@dataclass
class BoardLayout:
    """盤面・ホールド欄の画面上の位置とサイズ（オーバーレイウィンドウ内のローカル座標系）

    board_origin_x/y, cell_sizeはfloatで保持する。【2026-09-07・実機で発見】
    DPIスケール環境向けに呼び出し側(OverlayWindow.paintEvent)がこれらを
    物理ピクセル座標からdevicePixelRatioで割って求めているが、以前はここで
    整数に丸めてから渡していたため、_cell_rectがその丸め済みのcell_sizeを
    列・行数分だけ掛け算する際に丸め誤差が毎マスごとに積み重なり、盤面の
    下・右のセルほど実機オーバーレイの表示位置が本来の座標から大きく
    ズレる(録画への合成は物理ピクセル座標のまま丸めを介さないため
    ズレない)不具合が実機動画で確認された。丸めを最終的な描画座標
    (_cell_rectの戻り値をQPointFに渡す一点)まで遅らせることで、
    どのセルも「物理座標をそのままDPRで割った値」からの丸め誤差(最大でも
    0.5論理px)だけに抑えられ、行・列数に比例して蓄積することがなくなる。
    """

    board_origin_x: float
    board_origin_y: float
    cell_size: float
    hold_rect: tuple[int, int, int, int]  # (x, y, w, h)


@dataclass
class OverlayDrawData:
    """1フレーム分の描画内容（solver.BestMoveから変換して渡す）"""

    piece: str
    landing_cells: list[tuple[int, int]]  # (row, col) 消去前の着地マス
    use_hold: bool


def _piece_qcolor(piece: str, alpha: int) -> QtGui.QColor:
    rgb = PIECE_COLORS[piece]
    return QtGui.QColor(rgb.r, rgb.g, rgb.b, alpha)


def render_overlay(
    painter: QtGui.QPainter,
    layout: BoardLayout,
    data: OverlayDrawData,
) -> None:
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

    # 以前はuse_hold=Trueの場合、盤面の着地マスを表示せず「ホールド欄を
    # 枠で囲むだけ」だった。しかしこれだと「ホールドした後、結局どこに
    # 置けばいいのか」が別途分からず、ホールド自体の提案が不安定に見える
    # 一因にもなっていた（実機で「ホールドを提示する枠問題」として指摘）。
    # data.landing_cellsは「ホールド後に実際に使うミノ」の着地位置として
    # 計算済みのため、use_holdの真偽にかかわらず常に盤面上へ表示する。
    #
    # ホールド欄を縁取る追加ヒント(_render_hold_hint)は、ユーザーからの
    # 指示により廃止した。着地マス表示だけで「次に置くべき場所」は伝わる
    # ため、ホールド欄側の追加表示は不要と判断された。
    _render_landing_cells(painter, layout, data)


def _cell_rect(layout: BoardLayout, row: int, col: int) -> tuple[float, float, float, float]:
    x = layout.board_origin_x + col * layout.cell_size
    y = layout.board_origin_y + row * layout.cell_size
    return x, y, layout.cell_size, layout.cell_size


def _render_landing_cells(
    painter: QtGui.QPainter,
    layout: BoardLayout,
    data: OverlayDrawData,
) -> None:
    # 各着地マスの中心に、白縁付きのミノ色ドットを1つずつ打つ。
    # 枠で囲む方式と違い盤面のマス目自体は覆わないため、ゲーム側の
    # ドロップ先ガイド（ゴーストピースの枠線）と重なりにくい。
    radius = layout.cell_size * LANDING_DOT_RADIUS_RATIO

    outline_pen = QtGui.QPen(QtGui.QColor(255, 255, 255, 255), LANDING_DOT_OUTLINE_WIDTH)
    painter.setPen(outline_pen)
    painter.setBrush(QtGui.QBrush(_piece_qcolor(data.piece, 255)))

    for row, col in data.landing_cells:
        x, y, w, h = _cell_rect(layout, row, col)
        center = QtCore.QPointF(x + w / 2, y + h / 2)
        painter.drawEllipse(center, radius, radius)
