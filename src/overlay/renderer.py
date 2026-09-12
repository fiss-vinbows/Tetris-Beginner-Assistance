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

# 読み筋(2手目以降)のドット。1手目より小さく・薄くして区別し、手番の番号を添える。
PLAN_DOT_RADIUS_RATIO = 0.15
PLAN_DOT_ALPHA = 150


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
class PlanStep:
    """読み筋の1手(2手目以降)。cellsは現在の画面座標での着地マス。"""

    piece: str
    cells: list[tuple[int, int]]


@dataclass
class OverlayDrawData:
    """1フレーム分の描画内容（solver.BestMoveから変換して渡す）"""

    piece: str
    landing_cells: list[tuple[int, int]]  # (row, col) 消去前の着地マス
    use_hold: bool
    # 読み筋(2手目以降)。先頭が2手目。ライン消去で画面座標がずれる手より
    # 先は含めない(app._plan_steps_on_screen参照)。
    plan_steps: list[PlanStep] | None = None
    # 盤面の横(HOLD欄の下)に出す短い文字。開幕テンプレの名前など。
    label: str | None = None


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
    _render_plan_steps(painter, layout, data)
    _render_label(painter, layout, data)


def _render_label(painter: QtGui.QPainter, layout: BoardLayout, data: OverlayDrawData) -> None:
    """HOLD欄の下の空きに、目指す積み方の名前などを表示する。"""
    if not data.label:
        return
    x, y, w, h = layout.hold_rect
    font = painter.font()
    font.setPixelSize(max(10, int(layout.cell_size * 0.5)))
    font.setBold(True)
    painter.setFont(font)
    rect = QtCore.QRectF(x - layout.cell_size, y + h + layout.cell_size * 0.5, w + layout.cell_size * 2, layout.cell_size * 4)
    # 背景の上でも読めるよう、黒い縁取りの上に白文字を重ねる。
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 220)))
        painter.drawText(
            rect.translated(dx, dy),
            QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.TextFlag.TextWordWrap,
            data.label,
        )
    painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 255)))
    painter.drawText(
        rect,
        QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.TextFlag.TextWordWrap,
        data.label,
    )


def _render_plan_steps(
    painter: QtGui.QPainter,
    layout: BoardLayout,
    data: OverlayDrawData,
) -> None:
    """読み筋(2手目以降)を、小さく薄いドットと手番の番号で示す。"""
    if not data.plan_steps:
        return
    radius = layout.cell_size * PLAN_DOT_RADIUS_RATIO
    font = painter.font()
    font.setPixelSize(max(8, int(layout.cell_size * 0.45)))
    font.setBold(True)
    painter.setFont(font)
    for index, step in enumerate(data.plan_steps, start=2):
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, PLAN_DOT_ALPHA), 2))
        painter.setBrush(QtGui.QBrush(_piece_qcolor(step.piece, PLAN_DOT_ALPHA)))
        for row, col in step.cells:
            x, y, w, h = _cell_rect(layout, row, col)
            painter.drawEllipse(QtCore.QPointF(x + w / 2, y + h / 2), radius, radius)
        # 番号はミノの一番上・左のマスに添える。
        if step.cells:
            row, col = min(step.cells)
            x, y, w, h = _cell_rect(layout, row, col)
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 230)))
            # ドットと重ならないよう、マスの左上に寄せる。
            painter.drawText(
                QtCore.QRectF(x + 1, y, w, h),
                QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop,
                str(index),
            )


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
