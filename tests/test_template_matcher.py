"""テンプレートマッチングによるミノ色判定(template_matcher.py)の単体テスト。

Tetris99のAI「ジェフ」の「あらかじめ用意した色見本とのピクセル一致度が
閾値以上の場合だけ確定する」設計を参考にした判定ロジック。色相ベースの
判定(旧classify_color)がI/Jの取り違えやゴースト・光エフェクトの誤検出に
弱かったことへの対策として導入した。空マス(EMPTY)とGARBAGE(お邪魔
ブロック)は、どちらも背景・明るさの影響を受けやすく決まった1つの見た目を
持たないため意図的にテンプレート化しない(GARBAGEは彩度の低い灰色で、
光エフェクトで明るさが変わると1枚の色見本との色差が大きくなりすぎて
誤って「不一致」と判定される不具合が実機ログで確認されたため、
board_reader.py側で彩度・明度の閾値によるフォールバック判定を行う)。
7色のミノのいずれにも十分近くない場合にNoneを返す。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.vision.template_matcher import (
    MATCH_THRESHOLD,
    TEMPLATE_NAMES,
    _match_score,
    _match_score_ignoring_brightness,
    dominant_body_color,
    get_template_representative_colors,
    load_templates,
    match_cell_template,
)


def _solid_patch(color: tuple[int, int, int], size: int = 40) -> np.ndarray:
    patch = np.zeros((size, size, 3), dtype=np.uint8)
    patch[:, :] = color
    return patch


class LoadTemplatesTest(unittest.TestCase):
    def test_loads_exactly_the_seven_mino_templates(self) -> None:
        # 空マス(EMPTY)とGARBAGE(お邪魔ブロック)はテンプレート化しない
        # (モジュールdocstring参照)。
        templates = load_templates()
        self.assertEqual(set(templates.keys()), set(TEMPLATE_NAMES))
        self.assertNotIn("EMPTY", templates)
        self.assertNotIn("GARBAGE", templates)


class MatchCellTemplateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.templates = load_templates()

    def test_patch_matching_a_real_template_is_classified_correctly(self) -> None:
        # 実際のテンプレート画像そのものを入力すれば、当然そのテンプレートに
        # 一致すべき(自己一致率は100%になるはず)。
        for name in TEMPLATE_NAMES:
            with self.subTest(name=name):
                result = match_cell_template(self.templates[name], self.templates)
                self.assertEqual(result, name)

    def test_slightly_resized_patch_still_matches(self) -> None:
        # キャリブレーションのセルサイズ誤差により、実際のセル画像は
        # テンプレートと数pxサイズが異なりうる。リサイズ後も正しく
        # 一致すべき。
        template = self.templates["I"]
        resized = template[:-2, :-1]  # わずかに小さいパッチをシミュレート
        result = match_cell_template(resized, self.templates)
        self.assertEqual(result, "I")

    def test_background_like_patch_is_rejected_as_none(self) -> None:
        # どのテンプレートにも似ていない(暗い背景相当の)パッチは、
        # 空マスとしてNoneを返すべき。
        background = _solid_patch((30, 45, 37))
        result = match_cell_template(background, self.templates)
        self.assertIsNone(result)

    def test_ghost_like_patch_is_rejected_as_none(self) -> None:
        # ドロップ先ゴースト(暗い半透明表示)は、どの本物のミノ色
        # テンプレートとも十分には一致しないため、Noneとして棄却され
        # 空マス扱いになるべき(個別のゴースト判定ロジックなしで
        # 自然に排除できることの確認)。
        dark_ghost = _solid_patch((20, 4, 4))  # 彩度はあるが暗い
        result = match_cell_template(dark_ghost, self.templates)
        self.assertIsNone(result)


class TestTemplateRepresentativeColors(unittest.TestCase):
    """代表色が「テンプレート画像に写り込んだ縁」ではなくミノ本体から採られること。

    実機の回帰テスト: J.pngの左端にHOLD欄のオレンジ色の縁取りが写り込んで
    おり、「最も彩度が高い1点」を代表色にする旧方式では、そのオレンジ
    (213,115,3)がJの代表色として採取されていた。結果、実物の青いJは
    Iの代表色に最も近くなり、実機ログ全体でNEXT/HOLD欄のJ認識回数が0回
    (Iは他ミノの約2倍)という状態だった。
    """

    def test_j_representative_color_is_blue_not_orange(self) -> None:
        r, g, b = get_template_representative_colors()["J"]
        self.assertGreater(b, r, f"Jの代表色が青くない: RGB=({r:.0f},{g:.0f},{b:.0f})")
        self.assertGreater(b, 120)

    def test_i_and_j_representative_colors_are_separated(self) -> None:
        # I(水色)とJ(青)が代表色として十分離れていること。近すぎると
        # わずかな明度差で取り違える。
        colors = get_template_representative_colors()
        distance = float(np.sqrt(((colors["I"] - colors["J"]) ** 2).sum()))
        self.assertGreater(distance, 50.0)

    def test_edge_artifact_does_not_become_the_representative_color(self) -> None:
        # 本体が青一色で、左端1列だけ彩度の高いオレンジが写り込んだ画像。
        # 少数派である縁の色に引きずられないこと。
        patch = np.zeros((20, 20, 3), dtype=np.uint8)
        patch[:, :] = (0, 82, 181)
        patch[:, 0] = (213, 115, 3)

        color = dominant_body_color(patch)

        self.assertIsNotNone(color)
        r, g, b = color
        self.assertGreater(b, r)


class TestGlowingBlockIsStillMatched(unittest.TestCase):
    """光エフェクトで明るくなったブロックを「空」に落とさないことの回帰テスト。

    実機で、水色のIブロックはRGB(1,153,212)なら一致率0.81だが、光って
    RGB(33,197,250)になると0.30まで落ちて空マスに化けていた(画素ごとの
    距離が約63で、許容距離60をわずかに超えるため全画素が不一致になる)。
    保存済みの生画像40枚では実ブロックの15.3%がこれで空に落ちており、
    空いたマスへAIが配置を提案する「干渉」の直接原因だった。

    以下の色は、すべて実機の生画像から実測したセルの代表色である。
    """

    def setUp(self) -> None:
        self.templates = load_templates()

    def _glow(self, template: np.ndarray, amount: int) -> np.ndarray:
        """加算的に明るくする(実機の光り方に近い)。"""
        return np.clip(template.astype(np.int16) + amount, 0, 255).astype(np.uint8)

    def test_glowing_piece_is_never_treated_as_empty(self) -> None:
        # 干渉を防ぐうえで本質的なのは「そこにブロックがある」と分かること。
        # 明るさ+35で通常の一致率は0.07〜0.26まで落ちる(しきい値0.6)ため、
        # 再挑戦がないと7種すべてが「空マス」に化ける。
        for name in TEMPLATE_NAMES:
            with self.subTest(piece=name):
                glowing = self._glow(self.templates[name], 35)
                self.assertIsNotNone(match_cell_template(glowing, self.templates))

    def test_glowing_piece_keeps_its_identity_except_the_known_j_ambiguity(self) -> None:
        # 種類まで正しく取れることも確認する。ただしJだけは、明るくすると
        # 通常のIの色と近くなるため通常判定の段階でIと決まってしまう。
        # これは明るさを無視する再挑戦を入れる前からある性質で、着地済み
        # 盤面については占有情報だけあれば足りるため実害は限定的。
        # (NEXT/HOLD欄のI/J判定は別経路で、そちらは対策済み)
        for name in TEMPLATE_NAMES:
            if name == "J":
                continue
            with self.subTest(piece=name):
                glowing = self._glow(self.templates[name], 35)
                self.assertEqual(match_cell_template(glowing, self.templates), name)

    def test_brightness_shift_collapses_the_normal_score(self) -> None:
        # 前提の確認: 明るさが変わるだけで通常の一致率が崩れること。
        # ここが崩れないなら、そもそも再挑戦は不要ということになる。
        glowing = self._glow(self.templates["I"], 35)
        self.assertLess(_match_score(glowing, self.templates["I"]), MATCH_THRESHOLD)
        self.assertGreaterEqual(
            _match_score_ignoring_brightness(glowing, self.templates["I"]),
            MATCH_THRESHOLD,
        )

    def test_resized_template_cache_is_not_confused_between_templates(self) -> None:
        # リサイズ結果のキャッシュはidをキーにしている。元の配列への参照を
        # 保持しないと、解放後にidが再利用され、別のミノの色見本が返る。
        # 実際にこの取り違えでテストが誤った結果を出した。
        for _ in range(3):
            fresh = load_templates()
            for name in TEMPLATE_NAMES:
                self.assertEqual(match_cell_template(fresh[name], fresh), name)

    def test_normal_pieces_are_unaffected(self) -> None:
        # 明るさを無視する比較は通常判定に失敗したときだけ使う。既に判定
        # できているセルの結果を変えてはいけない(この正規化は明るさの情報を
        # 捨てるため、色相が近いIとJが互いに近づく。無条件に置き換えると
        # 実機の画像で19セルがI→Jへ変わった)。
        for name in TEMPLATE_NAMES:
            with self.subTest(piece=name):
                self.assertEqual(
                    match_cell_template(self.templates[name], self.templates), name
                )

    def test_dark_background_is_not_matched_by_the_fallback(self) -> None:
        # 明るさを無視する比較を足したことで、暗い背景がミノに化けないこと。
        background = _solid_patch((30, 45, 37))
        self.assertIsNone(match_cell_template(background, self.templates))


class TestRematchIsSkippedForLowChromaCells(unittest.TestCase):
    """彩度の低いセルでは明るさ無視の再照合を計算しないことの回帰テスト(残課題2-1)。

    実機で、空マス・背景は必ず通常照合に失敗するため、無条件に再照合すると
    盤面200セル中190セルで二重の照合が走り、盤面の読み取りが34ms→152msに
    悪化していた。彩度60未満のセルは再照合しても一致し得ない
    (_REMATCH_MIN_CHROMA参照)ので、計算そのものを省略する。
    """

    def setUp(self) -> None:
        self.templates = load_templates()

    def _count_rematch_calls(self, patch: np.ndarray) -> tuple[str | None, int]:
        from src.vision import template_matcher

        calls = 0
        original = template_matcher._match_score_ignoring_brightness

        def counting(patch_arg: np.ndarray, template: np.ndarray) -> float:
            nonlocal calls
            calls += 1
            return original(patch_arg, template)

        template_matcher._match_score_ignoring_brightness = counting
        try:
            return match_cell_template(patch, self.templates), calls
        finally:
            template_matcher._match_score_ignoring_brightness = original

    def test_empty_background_skips_the_rematch_entirely(self) -> None:
        # 空セルの背景(彩度20程度)は再照合を1回も呼ばずにNoneになる。
        label, calls = self._count_rematch_calls(_solid_patch((30, 45, 37)))
        self.assertIsNone(label)
        self.assertEqual(calls, 0)

    def test_gray_garbage_like_cell_skips_the_rematch(self) -> None:
        # 白灰色のガベージ(彩度ほぼ0)も同様。GARBAGE判定は呼び出し側が行う。
        label, calls = self._count_rematch_calls(_solid_patch((200, 200, 205)))
        self.assertIsNone(label)
        self.assertEqual(calls, 0)

    def test_glowing_piece_still_goes_through_the_rematch(self) -> None:
        # 光ったブロックは彩度が残るので、従来どおり再照合で救われる。
        glowing = np.clip(self.templates["I"].astype(np.int16) + 35, 0, 255).astype(np.uint8)
        label, calls = self._count_rematch_calls(glowing)
        self.assertIsNotNone(label)
        self.assertGreater(calls, 0)


if __name__ == "__main__":
    unittest.main()
