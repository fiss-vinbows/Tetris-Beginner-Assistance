"""配布物(TBA.exe)用のアイコンをテトリミノ風に生成する。

使い方: ./venv/Scripts/python.exe tools/generate_icon.py
出力: assets/icon.ico (16/32/48/256pxを含むマルチサイズico)
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "assets" / "icon.ico"

# テトリスの公式配色に準拠したミノの色
COLOR_T = (168, 44, 214)  # 紫
COLOR_I = (49, 199, 239)  # シアン
COLOR_L = (239, 160, 46)  # オレンジ
BG = (20, 24, 38)  # ダークネイビー


def _draw_block(draw: ImageDraw.ImageDraw, x: int, y: int, size: int, color: tuple[int, int, int]) -> None:
    """立体感を出すため、本体+左上ハイライト+右下シャドウの3層でブロックを描く。"""
    draw.rectangle([x, y, x + size, y + size], fill=color)
    highlight = tuple(min(255, c + 55) for c in color)
    shadow = tuple(max(0, c - 55) for c in color)
    edge = max(2, size // 8)
    draw.rectangle([x, y, x + size, y + edge], fill=highlight)
    draw.rectangle([x, y, x + edge, y + size], fill=highlight)
    draw.rectangle([x + size - edge, y, x + size, y + size], fill=shadow)
    draw.rectangle([x, y + size - edge, x + size, y + size], fill=shadow)


def render(canvas_size: int) -> Image.Image:
    img = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 角丸の背景パネル
    margin = canvas_size * 0.04
    radius = canvas_size * 0.18
    draw.rounded_rectangle(
        [margin, margin, canvas_size - margin, canvas_size - margin],
        radius=radius,
        fill=BG,
    )

    # 中央にTミノ(横1列+中央上1個)、右上にIミノの断片を添えた構図
    grid = canvas_size * 0.155
    pad = max(1, round(canvas_size * 0.012))
    block = grid - pad
    origin_x = canvas_size * 0.20
    origin_y = canvas_size * 0.40

    def cell(col: int, row: int) -> tuple[float, float]:
        return origin_x + col * grid, origin_y + row * grid

    # Tミノ: 下段3マス + 中央上1マス
    for col in (0, 1, 2):
        x, y = cell(col, 1)
        _draw_block(draw, round(x), round(y), round(block), COLOR_T)
    x, y = cell(1, 0)
    _draw_block(draw, round(x), round(y), round(block), COLOR_T)

    # Iミノの断片(右上、縦2マス)を添えて「複数のミノを操る」印象を出す
    for row in (-2, -1):
        x, y = cell(3, row + 2)
        _draw_block(draw, round(x + grid * 0.6), round(y), round(block), COLOR_I)

    # 左下にLミノの1マスをアクセントとして配置
    x, y = cell(-1, 1)
    _draw_block(draw, round(x + grid * 0.15), round(y + grid * 1.05), round(block), COLOR_L)

    return img


def main() -> None:
    OUT_PATH.parent.mkdir(exist_ok=True)
    base = render(256)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    base.save(OUT_PATH, format="ICO", sizes=[(s, s) for s in sizes])
    print(f"生成完了: {OUT_PATH}")


if __name__ == "__main__":
    main()
