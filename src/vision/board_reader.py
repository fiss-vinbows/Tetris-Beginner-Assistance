"""盤面画像 → 論理盤面(ミノ種類の2次元配列) への変換"""

from __future__ import annotations

import numpy as np

from .piece_colors import RGB
from .template_matcher import get_templates, match_cell_template

# セル境界の枠線を避けるため、セル画像から内側だけを切り出す際のマージン比率。
_CELL_MARGIN_RATIO = 0.15

# セル内最大chroma(色の鮮やかさ)がこの値未満なら「彩度のある通常ミノではない」とみなす。
# 空セルの背景（透かし模様のノイズ含む）はchroma～20程度、通常ミノは100以上あるため
# 十分な安全マージンを取っている。GARBAGEのフォールバック判定に使う
# (テンプレートマッチングでGARBAGEを扱わない理由はtemplate_matcher.pyのdocstring参照)。
_MIN_PIECE_CHROMA = 60.0

# chromaが低くても、明度がこの値以上なら「ガベージブロック(白灰色)」とみなす。
# 空セル背景の明度は～55程度、ガベージブロックは～200以上あるため十分なマージンがある。
_MIN_GARBAGE_BRIGHTNESS = 150.0

# セル全体の代表色(中央値)がこの明度以上かつ彩度が十分なら、テンプレートに
# 一致しなくても「ブロックが存在する(種類は不明)」とみなす
# (_classify_as_garbage_or_empty参照)。背景の暗い透かし模様を誤って
# ブロックにしないため、明度に下限を設ける。実測では、実ブロックの
# 明度中央値は120以上、背景は80未満だった。
_MIN_UNKNOWN_BLOCK_BRIGHTNESS = 120.0

# 「ブロックは存在するが種類を特定できない」セルを表す値。
# GARBAGEと区別する理由: GARBAGEには「まばらな行は演出ノイズとして打ち消す」
# という専用処理(_discard_sparse_garbage_rows)があり、そこへ混ぜると
# 種類不明のブロックまで一緒に消されてしまう。実際、最初はGARBAGEを
# 流用したところ、この処理に消されて誤判定が50件残った。
# 1つの値に2つの意味を持たせない。
UNKNOWN_BLOCK = "UNKNOWN"

def read_board_grid(
    board_image: np.ndarray,
    cols: int,
    rows: int,
    previous_grid_hint: list[list[str | None]] | None = None,
) -> list[list[str | None]]:
    """盤面領域のRGB画像から、各セルのミノ種類を判定して2次元配列で返す。

    board_image: (height, width, 3) のRGB配列。盤面全体（枠を含まない内側）を想定。
    previous_grid_hint: read_board_grid_with_samples参照。
    戻り値: grid[row][col] = ピース名 ("I","O","T","S","Z","J","L","GARBAGE") または None(空)
    """
    grid, _samples = read_board_grid_with_samples(board_image, cols, rows, previous_grid_hint)
    return grid


def read_board_grid_with_samples(
    board_image: np.ndarray,
    cols: int,
    rows: int,
    previous_grid_hint: list[list[str | None]] | None = None,
) -> tuple[list[list[str | None]], list[list[RGB]]]:
    """read_board_gridと同じ結果に加えて、各セルの生RGBサンプルも返す。

    生サンプルは、I/Jのように色相が非常に近いミノを、盤面上の1マスだけでなく
    複数マス(連結成分全体)から再判定する際に使う（呼び出し側でHue/明度を集計するため）。

    7色のミノは、あらかじめ用意したテンプレート画像とのピクセル一致率で
    判定する(詳細はtemplate_matcher.pyのモジュールdocstring参照)。GARBAGE
    (お邪魔ブロック)はテンプレートマッチングの対象に含めず、彩度・明度の
    閾値による従来通りの判定にフォールバックする(彩度がほぼゼロの灰色は
    「特定の色相」を持たず明るさそのものが特徴のため、ライン消去等の光
    エフェクトで画面全体が明るくなる瞬間、1枚の色見本との色差が大きく
    なりすぎて誤って「不一致」と判定され、盤面全体が一瞬空に見えてしまう
    重大な誤読みが実機ログで確認された)。

    previous_grid_hint: _classify_as_garbage_or_empty参照。直前tickで確定
    していたgrid(呼び出し側のRecognitionResult.board.grid)。彩度は高い
    ものの7色のどのテンプレートにも一致しなかった曖昧なセルで、直前に
    実際にミノが確定していた場合、空扱いにせず直前の判定を維持するために使う。
    """
    templates = get_templates()
    img_h, img_w = board_image.shape[0], board_image.shape[1]
    cell_w = img_w / cols
    cell_h = img_h / rows

    grid: list[list[str | None]] = []
    samples: list[list[RGB]] = []
    for row in range(rows):
        row_cells: list[str | None] = []
        row_samples: list[RGB] = []
        for col in range(cols):
            patch = _extract_cell_patch(board_image, row, col, cell_w, cell_h)
            label = match_cell_template(patch, templates)
            if label is None:
                previous_label = previous_grid_hint[row][col] if previous_grid_hint is not None else None
                label = _classify_as_garbage_or_empty(patch, previous_label=previous_label)
            row_cells.append(label)
            row_samples.append(_representative_color(patch))
        grid.append(row_cells)
        samples.append(row_samples)

    _discard_sparse_garbage_rows(grid, cols)
    return grid, samples


def _extract_cell_patch(
    image: np.ndarray,
    row: int,
    col: int,
    cell_w: float,
    cell_h: float,
) -> np.ndarray:
    """指定セルの画像を、境界の枠線を避けて内側だけ切り出す。"""
    x0 = int(col * cell_w)
    x1 = int((col + 1) * cell_w)
    y0 = int(row * cell_h)
    y1 = int((row + 1) * cell_h)

    margin_x = max(1, int(cell_w * _CELL_MARGIN_RATIO))
    margin_y = max(1, int(cell_h * _CELL_MARGIN_RATIO))
    patch = image[y0 + margin_y : y1 - margin_y, x0 + margin_x : x1 - margin_x]
    if patch.size == 0:
        patch = image[y0:y1, x0:x1]
    return patch


def _classify_as_garbage_or_empty(patch: np.ndarray, previous_label: str | None = None) -> str | None:
    """テンプレートに一致しなかったセルを、彩度・明度の閾値でGARBAGEか空マスか判定する。

    GARBAGE(お邪魔ブロック)は彩度がほぼゼロの灰色で「特定の色相」を持たない
    ため、7色のミノのようにテンプレートとの厳密な色一致では判定しない
    (詳細はtemplate_matcher.pyのモジュールdocstring参照)。彩度が低く、かつ
    明度が一定以上あれば、多少の明るさのブレを許容してGARBAGEとみなす。

    previous_label: 直前tickでこのセルに確定していたミノ種類(read_board_grid_
    with_samples参照)。

    【2026-09-07・実機動画解析で判明した重大な誤読み】ライン消去("TETRIS")等の
    光エフェクトが盤面を覆う瞬間、実際には設置済みのミノがあるセルでも、その
    彩度の高いピクセル色がどの7色テンプレートとも十分近くなくなり(エフェクトの
    色が混ざるため)、この関数に「彩度は高いが未知の色」として渡ってくることが
    実測で確認された(Lミノの一致率が0.76→0.07へ1フレームで崩壊)。このエフェクトは
    複数tickにまたがって持続するため、単発ノイズ用の2tickデバウンス(呼び出し側の
    _stabilize_settled_grid)では「2tick連続で同じ間違った値(空)」が観測されて
    しまい素通りしてしまう。彩度が高い=本物の未知の色ノイズという前提自体は
    正しいが、直前tickで実際にミノが確定していたセルに限っては、エフェクトによる
    一時的な色のブレである可能性の方が高いため、空扱いにせず直前の判定を維持する。
    """
    patch_f = patch.astype(np.float32)
    max_c = patch_f.max(axis=2)
    min_c = patch_f.min(axis=2)
    chroma = max_c - min_c

    # 彩度の高いピクセルがあれば、7色のどれにも一致しなかっただけで
    # GARBAGEでもない(未知の色・ノイズ)ので、空マス扱いにする。ただし
    # 直前に実際にミノが確定していたセルは、光エフェクトによる一時的な
    # 誤読の可能性が高いため、空扱いにせず直前の判定を維持する。
    if float(chroma.max()) >= _MIN_PIECE_CHROMA:
        if previous_label is not None and previous_label != "GARBAGE":
            return previous_label
        # 【種類は分からないが「何かある」ことは分かる場合】
        # セル全体を代表する色(中央値)が鮮やかで明るいなら、そこには
        # ブロックが存在する。テンプレートに一致しないのは、光エフェクトで
        # 色が変わって種類を特定できないだけである。
        #
        # ここを「空マス」にすると、実在するブロックの上へAIが配置を提案し、
        # 既存ブロックと重なる「干渉」になる。実機で支援が成立しないほど
        # 頻発した。直前の判定による救済(上の分岐)は、置いた瞬間から光って
        # いて一度も確定できなかったブロックには効かない。
        #
        # 種類が分からないままAIへ渡せるのは、着地済み盤面については
        # 占有情報だけあれば足りるため(GARBAGEはTBPでも「何かある」を
        # 表す)。分からないものを「空」と決めつけない、という方針に沿う。
        median = np.median(patch_f.reshape(-1, 3), axis=0)
        if float(median.max() - median.min()) >= _MIN_PIECE_CHROMA and float(
            median.max()
        ) >= _MIN_UNKNOWN_BLOCK_BRIGHTNESS:
            return UNKNOWN_BLOCK
        return None

    idx_bright = np.unravel_index(np.argmax(max_c), max_c.shape)
    if max_c[idx_bright] >= _MIN_GARBAGE_BRIGHTNESS:
        return "GARBAGE"
    return None


def _representative_color(patch: np.ndarray) -> RGB:
    """セル内で最も彩度が高いピクセルの色を、I/J再判定用の生サンプルとして返す。

    ぷよぷよテトリスのミノ描画はグロス（光沢）効果でセル中心が暗く落ち込むため、
    中心付近の平均色を使うと暗い色に引っ張られて誤判定しやすい。
    ミノの縁は彩度が高く、盤面の暗い背景（低彩度）とは明確に区別できるため、
    彩度最大点を採用することでグロス効果の影響を避ける。
    """
    patch_f = patch.astype(np.float32)
    max_c = patch_f.max(axis=2)
    min_c = patch_f.min(axis=2)
    chroma = max_c - min_c
    idx = np.unravel_index(np.argmax(chroma), chroma.shape)
    r, g, b = patch[idx]
    return RGB(int(r), int(g), int(b))


def _discard_sparse_garbage_rows(grid: list[list[str | None]], cols: int) -> None:
    """GARBAGE判定が疎らな行は演出エフェクト等のノイズとみなし、その行のGARBAGE判定を取り消す。

    ライン消去演出などの明るい閃光エフェクトは、色空間上でガベージブロック(白灰色)と
    ほぼ区別がつかず、色ベースの判定だけでは避けられない。しかし本物のガベージラインは
    （穴を除いて）ほぼ全列が埋まっているという構造上の性質があるため、
    GARBAGE判定されたセル数が極端に少ない行は信頼しない（Noneに戻す）ことで、
    エフェクトによる散発的な誤検出を弾く。

    以前は閾値を「cols-1（10列中9列）」としていたが、これでは背景の透かし模様の
    ノイズ等でたった1マスGARBAGE判定に失敗しただけで、本物のガベージ行（実際には
    9〜10マス埋まっている）が丸ごと「空」に化けてしまい、盤面の高さ・穴の計算が
    根本から狂うという重大な問題があった（実機で、2段のガベージ行が追加された
    直後に最善手が明らかにおかしくなる不具合として確認された）。ガベージ行は
    「ほぼ全列が埋まっている」という構造的な特徴があれば十分本物と判断できるため、
    半分以上のマスがGARBAGEと判定できていれば行を保持するよう閾値を緩和する。
    エフェクトの誤検出は通常1〜2マス程度にしか出ないため、これでも弾ける。
    """
    min_garbage_count = max(1, cols // 2)
    for row in grid:
        garbage_count = sum(1 for cell in row if cell == "GARBAGE")
        if 0 < garbage_count < min_garbage_count:
            for i, cell in enumerate(row):
                if cell == "GARBAGE":
                    row[i] = None
