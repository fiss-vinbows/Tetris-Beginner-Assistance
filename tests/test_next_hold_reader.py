"""next_hold_reader.pyのテスト。

実機動画を解析した結果、HOLD欄を縁取る常時表示のオレンジ色の枠
（ホールド可能状態を示すUI要素）の色を拾うと"L"と誤判定されることが
判明した。パッチの外周にマージンを取って枠を除外することで対処したため、
その効果を回帰テストとして固定化する。

【2026-09-07・テンプレートマッチング方式へ移行】判定方式を色相ベースから
盤面と同じテンプレート画像とのピクセル一致率に変更した。合成パッチの色は
各テンプレート画像自身の代表色(_template_representative_color)から生成する
(PIECE_COLORS定数はHOLD/NEXT欄の実機色を手動サンプリングした別の値であり、
テンプレート画像(盤面セルから採取)とは光沢・明度の違いで必ずしも一致しない
ため。実際にPIECE_COLORS["J"]をそのまま使うと、Jテンプレートより
Iテンプレートに近くなってしまうことが判明した)。

【2026-09-09・上記の懸念は実機で現実化していた】「Jの色見本がIに近い」と
いう当時の観察は正しく、実機ログではNEXT/HOLD欄のJ認識回数が0回、Iが
他ミノの約2倍という状態だった。原因は代表色を「最も彩度が高い1点」で
求めていたことで、テンプレート側ではJ.pngに写り込んだオレンジの縁を、
サンプル側ではミノ表面の光沢を拾っていた。両方をミノ本体の代表色
(中央値)に変更して解決した(dominant_body_color参照)。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.vision.next_hold_reader import read_piece_from_patch
from src.vision.template_matcher import get_template_representative_colors

PATCH_SIZE = 100  # 高さ・幅とも100pxのダミーパッチ
FRAME_THICKNESS = 15  # 縁取り枠の太さ(px)


def _template_representative_color(piece: str) -> tuple[int, int, int]:
    """テンプレート画像の代表色(最も彩度が高い点の色)を返す(テストの合成
    パッチ用)。read_piece_from_patchが実際に比較に使う基準と一致させる
    (単純な平均色を使うと、光沢によるムラで実際の判定基準とズレるため)。
    """
    r, g, b = get_template_representative_colors()[piece]
    return int(r), int(g), int(b)


def _make_patch_with_frame(
    inner_color: tuple[int, int, int] | None,
    frame_color: tuple[int, int, int] = (234, 138, 11),  # 実機で確認したオレンジ枠の色
) -> np.ndarray:
    """外周に枠、内側にミノ色(またはEMPTY相当の暗色)を持つダミーパッチを作る。"""
    patch = np.zeros((PATCH_SIZE, PATCH_SIZE, 3), dtype=np.uint8)
    patch[:, :] = frame_color
    inner = patch[FRAME_THICKNESS:-FRAME_THICKNESS, FRAME_THICKNESS:-FRAME_THICKNESS]
    inner[:, :] = inner_color if inner_color is not None else (5, 5, 5)
    return patch


class TestReadPieceFromPatchWithFrame(unittest.TestCase):
    def test_empty_hold_slot_with_orange_frame_is_not_misread_as_l(self) -> None:
        # 実機で確認された不具合の回帰テスト: ホールド欄が空でも、常時
        # 表示されるオレンジ枠を拾って"L"と誤判定してはいけない。
        patch = _make_patch_with_frame(inner_color=None)
        self.assertIsNone(read_piece_from_patch(patch))

    def test_low_chroma_piece_inside_orange_frame_is_read_correctly(self) -> None:
        # T/S/Z/Jはオレンジ枠よりchromaが低いため、枠を除外できていないと
        # ミノ本体ではなく枠の方が「最も彩度が高い点」として選ばれてしまう。
        for piece in ("T", "S", "Z", "J"):
            with self.subTest(piece=piece):
                r, g, b = _template_representative_color(piece)
                patch = _make_patch_with_frame(inner_color=(r, g, b))
                self.assertEqual(read_piece_from_patch(patch), piece)

    def test_high_chroma_piece_inside_orange_frame_is_read_correctly(self) -> None:
        # O/Lはオレンジ枠よりchromaが高いため、修正前でも一応正しく読めて
        # いたはずだが、マージン適用後も引き続き正しく読めることを確認する。
        for piece in ("O", "L"):
            with self.subTest(piece=piece):
                r, g, b = _template_representative_color(piece)
                patch = _make_patch_with_frame(inner_color=(r, g, b))
                self.assertEqual(read_piece_from_patch(patch), piece)

    def test_frameless_patch_still_works(self) -> None:
        # NEXT欄には枠自体がない(白い外枠のみで、ホールドのような色付き
        # 縁取りはない)。マージンを取っても、中央に十分な大きさで表示
        # されるミノ本体までは削らないことを確認する。
        r, g, b = _template_representative_color("I")
        patch = np.zeros((PATCH_SIZE, PATCH_SIZE, 3), dtype=np.uint8)
        patch[:, :] = (5, 5, 5)
        patch[30:70, 20:80] = (r, g, b)
        self.assertEqual(read_piece_from_patch(patch), "I")


class TestHighlightDoesNotFlipJToI(unittest.TestCase):
    """ミノ表面の光沢を拾って青いJが水色のIになる誤認の回帰テスト。

    実機のHOLD欄に表示された青いJは、本体色が(0,83,181)であるのに対し、
    最も彩度が高い1点は光沢部分の(0,145,206)だった。この1点はIの代表色
    との距離がわずか14しかなく、テンプレート側の代表色を正しく直しても、
    サンプル側が1点抽出のままではIと誤判定され続ける。本体の代表色
    (中央値)同士で比較することで、正しくJと判定できるようにした。
    """

    def test_blue_j_with_cyan_highlight_is_still_j(self) -> None:
        colors = get_template_representative_colors()
        body = colors["J"]
        # 実機で観測された光沢の色(Iの代表色に極めて近い水色)。
        highlight = np.array([0, 145, 206], dtype=np.float32)

        patch = np.zeros((50, 50, 3), dtype=np.uint8)
        patch[:, :] = body.astype(np.uint8)
        # 内側(マージン適用後)に収まる位置へ、少数派として光沢を置く。
        patch[20:24, 20:24] = highlight.astype(np.uint8)

        self.assertEqual(read_piece_from_patch(patch), "J")

    def test_all_seven_pieces_round_trip_through_their_body_color(self) -> None:
        # 7種すべてについて、本体色で塗ったパッチが自分自身と判定されること
        # (どれか1種が別の種類に吸い込まれていないことの確認)。
        for piece, color in get_template_representative_colors().items():
            with self.subTest(piece=piece):
                patch = np.zeros((50, 50, 3), dtype=np.uint8)
                patch[:, :] = color.astype(np.uint8)
                self.assertEqual(read_piece_from_patch(patch), piece)


if __name__ == "__main__":
    unittest.main()
