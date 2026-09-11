"""HOLD欄・NEXT欄の画像 → ミノ種類 への変換

【2026-09-07・テンプレートマッチング方式へ移行】以前は「枠内で最も彩度が
高い1点」の色を拾い、色相(Hue)ベースで判定していた(classify_color)。
色相ベースの判定は光エフェクト(ライン消去・コンボ・警告演出等)による
明るさのブレに弱く、実機ログで振動・干渉の一因になっていた。

盤面(board_reader.py)は「枠(セル)全体をテンプレート画像とピクセル単位で
比較する」方式に移行したが、HOLD/NEXT欄はミノがミニチュアアイコンとして
表示され、枠の大部分が背景(暗い透かし模様)で占められる(盤面セルのように
枠全体がミノ色でほぼ埋まるわけではない)。この方式をそのまま適用すると、
一致率が背景ピクセルに薄められてしまい実機映像で0.4程度にしか届かない
ことが確認された。

そこで、枠内の「ミノ本体の代表色」を求め、それを色相(Hue)ではなく
「各テンプレート画像のミノ本体の代表色」とのRGB距離(色空間上の距離)で
比較する方式にした。ハードコードされた基準色(旧piece_colors.PIECE_COLORS)
ではなくテンプレート画像由来の色を基準にすることで、盤面の判定と一貫した
「実機から採取した色見本」を基準にできる。

代表色は当初「枠内で最も彩度が高い1点」としていたが、外れ値1画素に判定
全体を委ねる方式であり、テンプレート側の縁の写り込みとサンプル側の光沢の
両方でI/Jの誤認を起こしていた(詳細はdominant_body_color参照)。
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np

from .template_matcher import dominant_body_color, get_template_representative_colors

# HOLD欄には、ホールド可能な状態を示すオレンジ色の縁取り枠が常時表示されて
# いる（ホールド不可の時は表示されない）。実機動画で、このオレンジ枠の色を
# 拾ってしまい、ミノ本体ではなく枠の方を誤って判定してしまう重大なバグが
# 実機ログで確認された（同じミノを操作中にhold_pieceの認識がブレる不具合の
# 主因）。calibrateでユーザーが指定するHOLD欄の矩形は、白い外枠を基準に
# クリックすることが多く、この縁取り枠を含んでしまいやすい。パッチの外周に
# マージンを取って枠を除外し、内側のミノ本体だけを比較対象にすることで対処する。
_FRAME_MARGIN_RATIO = 0.20

# 枠内最大chromaがこの値未満なら「何も表示されていない(空)」とみなす。
_MIN_PIECE_CHROMA = 60.0

# サンプル点とテンプレート代表色とのRGB距離(ユークリッド距離)がこの値未満
# なら「一致」とみなす。実測に基づく暫定値で、実機での再調整が必要。
_MAX_COLOR_DISTANCE = 80.0


class PatchReading(NamedTuple):
    """1枠分の読み取り結果。

    「空欄」と「読めなかった」を区別する。どちらもpieceはNoneになるが、
    意味は正反対である。HOLD欄では、読めなかっただけの状態を「空欄」と
    解釈すると、ホールド操作の有無を誤って判定してしまう
    (空HOLDへの初回格納は固定なしでNEXTを消費するため、固定の検出を誤る)。
    """

    piece: str | None
    is_empty: bool  # 「確かに何も表示されていない」と判断できたか


def read_patch(patch_image: np.ndarray) -> PatchReading:
    """HOLD欄/NEXT欄1枠分のRGB画像を読み、種類・空欄・不明を区別して返す。"""
    h, w = patch_image.shape[0], patch_image.shape[1]
    margin_y = int(h * _FRAME_MARGIN_RATIO)
    margin_x = int(w * _FRAME_MARGIN_RATIO)
    inner = patch_image[margin_y : h - margin_y, margin_x : w - margin_x]
    if inner.size == 0:
        inner = patch_image

    patch_f = inner.astype(np.float32)
    chroma = patch_f.max(axis=2) - patch_f.min(axis=2)
    if chroma.max() < _MIN_PIECE_CHROMA:
        # 彩度のある画素が全く無い＝確かに空欄。
        return PatchReading(None, is_empty=True)

    # 最も彩度が高い1点ではなく、ミノ本体の代表色(中央値)を使う。
    # 1点では表面の光沢(ハイライト)を拾ってしまい、青いJが水色のIとして
    # 判定される誤認が実機で発生していた(dominant_body_color参照)。
    sample = dominant_body_color(inner)
    if sample is None:
        return PatchReading(None, is_empty=False)

    best_name: str | None = None
    best_dist = float("inf")
    for name, ref_color in get_template_representative_colors().items():
        dist = float(np.sqrt(((sample - ref_color) ** 2).sum()))
        if dist < best_dist:
            best_dist = dist
            best_name = name

    if best_dist >= _MAX_COLOR_DISTANCE:
        # 何かが表示されているが、どのミノにも十分近くない＝読めなかった。
        return PatchReading(None, is_empty=False)
    return PatchReading(best_name, is_empty=False)


def read_piece_from_patch(patch_image: np.ndarray) -> str | None:
    """read_patchの薄いラッパー。種類だけが必要な呼び出し側のために残す。"""
    return read_patch(patch_image).piece
