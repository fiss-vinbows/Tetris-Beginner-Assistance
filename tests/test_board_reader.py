"""おじゃまブロック(GARBAGE)行の判定ロジックの単体テスト。

実機で「2段のおじゃまブロックが追加された直後に最善手がおかしくなる」
不具合が報告されたため、その原因だった閾値ロジックを検証する。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.vision.board_reader import _classify_as_garbage_or_empty, _discard_sparse_garbage_rows, UNKNOWN_BLOCK


def make_row(cols: int, garbage_cols: list[int]) -> list[str | None]:
    return ["GARBAGE" if c in garbage_cols else None for c in range(cols)]


class TestGarbageRowThreshold(unittest.TestCase):
    def test_almost_full_garbage_row_is_kept(self):
        # 10列中9列GARBAGE、1列だけ穴(典型的なガベージ行)
        grid = [make_row(10, list(range(9)))]
        _discard_sparse_garbage_rows(grid, 10)
        self.assertEqual(sum(1 for c in grid[0] if c == "GARBAGE"), 9)

    def test_half_garbage_row_is_kept(self):
        # 10列中6列だけGARBAGEと判定できたケース（背景ノイズで4マス誤判定）。
        # 以前の実装(閾値9)ではこれを丸ごと消してしまっていた。
        grid = [make_row(10, list(range(6)))]
        _discard_sparse_garbage_rows(grid, 10)
        self.assertEqual(
            sum(1 for c in grid[0] if c == "GARBAGE"), 6,
            "半分以上GARBAGE判定できているのに行ごと消してしまっている",
        )

    def test_sparse_garbage_is_treated_as_noise(self):
        # 10列中2列だけGARBAGE（ライン消去エフェクト等のノイズを想定）
        grid = [make_row(10, [3, 7])]
        _discard_sparse_garbage_rows(grid, 10)
        self.assertEqual(sum(1 for c in grid[0] if c == "GARBAGE"), 0, "ノイズを本物のガベージ行と誤認識している")

    def test_no_garbage_row_is_untouched(self):
        grid = [[None] * 10]
        _discard_sparse_garbage_rows(grid, 10)
        self.assertEqual(grid[0], [None] * 10)


class TestClassifyAsGarbageOrEmpty(unittest.TestCase):
    """GARBAGE(お邪魔ブロック)のフォールバック判定(テンプレートマッチング非対象)の回帰テスト。

    GARBAGEは彩度がほぼゼロの灰色で「特定の色相」を持たないため、7色の
    ミノのようにテンプレート画像との厳密な一致では判定しない。光エフェクトで
    明るさが変わっても、彩度が低く明度が一定以上であれば安定してGARBAGEと
    判定できることを確認する。
    """

    def _solid_patch(self, color: tuple[int, int, int], size: int = 40) -> np.ndarray:
        patch = np.zeros((size, size, 3), dtype=np.uint8)
        patch[:, :] = color
        return patch

    def test_bright_gray_is_classified_as_garbage(self) -> None:
        patch = self._solid_patch((180, 180, 180))
        self.assertEqual(_classify_as_garbage_or_empty(patch), "GARBAGE")

    def test_even_brighter_gray_from_light_effect_is_still_garbage(self) -> None:
        # ライン消去等の光エフェクトで通常より明るくなっても、彩度が低く
        # 明度が閾値以上である限り、安定してGARBAGEと判定できるべき
        # (これがテンプレートマッチングでは崩れていた不具合の回帰確認)。
        patch = self._solid_patch((230, 230, 230))
        self.assertEqual(_classify_as_garbage_or_empty(patch), "GARBAGE")

    def test_dark_gray_below_brightness_threshold_is_empty(self) -> None:
        patch = self._solid_patch((60, 60, 60))
        self.assertIsNone(_classify_as_garbage_or_empty(patch))

    def test_bright_unmatched_color_is_treated_as_an_occupied_cell(self) -> None:
        # 【2026-09-10・干渉の根本対策】セル全体を代表する色が鮮やかで明るい
        # なら、そこにはブロックが存在する。テンプレートに一致しないのは、
        # 光エフェクトで色が変わって種類を特定できないだけである。
        # ここを「空マス」にすると、実在するブロックの上へAIが配置を提案し、
        # 既存ブロックと重なる「干渉」になる。実機で支援が成立しないほど
        # 頻発した(保存済み生画像40枚で、実ブロックの15.3%が空に落ちていた)。
        # 種類が分からなくても、着地済み盤面は占有情報だけあれば足りる。
        patch = self._solid_patch((0, 200, 255))
        self.assertEqual(_classify_as_garbage_or_empty(patch), UNKNOWN_BLOCK)

    def test_dark_saturated_noise_is_still_empty(self) -> None:
        # 背景の透かし模様のように「彩度はあるが暗い」ものは、ブロックとは
        # みなさない(明度の下限で弾く)。ここを緩めると背景がブロックに化ける。
        patch = self._solid_patch((0, 70, 90))
        self.assertIsNone(_classify_as_garbage_or_empty(patch))

    def test_dark_background_is_empty(self) -> None:
        patch = self._solid_patch((30, 45, 37))
        self.assertIsNone(_classify_as_garbage_or_empty(patch))

    def test_bright_unmatched_color_without_previous_label_is_occupied(self) -> None:
        # 直前の判定による救済は「一度ミノとして確定していたセル」にしか
        # 効かない。置いた瞬間から光っているブロックは一度も確定できないため、
        # previous_label=Noneのまま空に落ちていた。実機の
        # 「Iミノを置いた瞬間にJミノが干渉した」はこの経路。
        patch = self._solid_patch((0, 200, 255))
        self.assertEqual(
            _classify_as_garbage_or_empty(patch, previous_label=None), UNKNOWN_BLOCK
        )

    def test_saturated_color_with_previous_label_keeps_previous_label(self) -> None:
        # 【2026-09-07】ライン消去等の光エフェクトでテンプレート不一致になっても、
        # 直前tickで実際にミノが確定していたセルなら、空扱いにせず直前の
        # 判定を維持する(実機動画でLミノの一致率が0.76→0.07へ1フレームで
        # 崩壊する誤読みを確認して追加した対策の回帰テスト)。
        patch = self._solid_patch((0, 200, 255))
        self.assertEqual(_classify_as_garbage_or_empty(patch, previous_label="L"), "L")

    def test_dark_ghost_piece_does_not_keep_the_previous_label(self) -> None:
        # 【2026-09-15実機・録画 debug_capture_20260915_193825.mp4 フレーム246〜262】
        # TSD直後、消去前の行に残った/閃光で誤読されたラベルが、消去後に同じ
        # 位置へ来た落下中Iのゴースト(着地位置の表示)の下で12フレーム
        # 「置いたブロック」として生き残り、幻の4マス(行17列3〜6)が
        # AIとテンプレに渡った。ゴーストは内部が暗く縁だけ彩度が高い。
        # 直前判定の維持は、閃光中の本物のブロックのように明るいセルに限ること。
        import numpy as np
        from pathlib import Path

        data = np.load(Path(__file__).with_name("fixtures") / "cell_patches_20260915_tsd.npz")
        for name, previous in (("ghost_17_3", "O"), ("ghost_17_4", "I"), ("ghost_17_5", UNKNOWN_BLOCK), ("ghost_17_6", "L")):
            self.assertIsNone(
                _classify_as_garbage_or_empty(data[name], previous_label=previous),
                f"{name}: ゴーストなのに直前の判定{previous}を維持している",
            )
        # 閃光に覆われた本物のブロックは、従来どおり直前の判定を維持する
        for name, previous in (("flash_real_17_3", "O"), ("flash_real_17_6", "L"), ("flash_real_16_3", "O"), ("flash_real_17_9", "I")):
            self.assertEqual(
                _classify_as_garbage_or_empty(data[name], previous_label=previous),
                previous,
                f"{name}: 閃光中の本物のブロックの判定が維持されていない",
            )

    def test_previous_garbage_label_does_not_block_the_occupied_decision(self) -> None:
        # previous_labelがGARBAGEの場合、直前値による救済の対象外である
        # (救済は7色のミノに限定)。それでも、今見えている色が鮮やかで明るい
        # なら「何かある」ことは確かなので、空マスにはしない。
        # ここを空にすると、光っているお邪魔行に穴が空いて干渉の原因になる。
        patch = self._solid_patch((0, 200, 255))
        self.assertEqual(
            _classify_as_garbage_or_empty(patch, previous_label="GARBAGE"), UNKNOWN_BLOCK
        )


if __name__ == "__main__":
    unittest.main()
