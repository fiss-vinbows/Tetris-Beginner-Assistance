"""app.py内の認識ロジック(_infer_current_piece等)の単体テスト。

これらはAssistWorkerの認識→思考ループの核心部分だが、これまで
単体テストが一切存在せず、実機でしか検証できていなかった。
「提示がおかしい」という指摘の原因を切り分けるため、画像処理から
切り離した純粋なロジックとして検証する。
"""

from __future__ import annotations

import inspect
import sys

import numpy as np
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import app
from src.app import (
    _bridge_looks_like_falling_piece,
    _build_settled_board,
    _connected_component,
    _infer_current_piece,
    _is_next_queue_impossible,
    _is_plausible_board_transition,
    _detect_garbage_rise,
    _detect_lock,
    _estimate_next_shift,
    _falling_piece_search_limit,
    _exclude_window_from_screen_capture,
    _resolve_i_j,
    _settled_top_row,
    _stabilize_settled_grid,
    recognize,
)
from src.engine.piece_defs import PIECE_ROTATION_STATES
from src.vision.piece_colors import PIECE_COLORS, RGB

BOARD_COLS = 10
BOARD_ROWS = 20


def _empty_grid(rows: int = BOARD_ROWS, cols: int = BOARD_COLS) -> list[list[str | None]]:
    return [[None] * cols for _ in range(rows)]


def _empty_samples(rows: int = BOARD_ROWS, cols: int = BOARD_COLS) -> list[list[RGB]]:
    return [[PIECE_COLORS["EMPTY"]] * cols for _ in range(rows)]


def _place_piece_cells(
    grid: list[list[str | None]],
    samples: list[list[RGB]],
    piece: str,
    origin_row: int,
    origin_col: int,
    rotation: int = 0,
) -> None:
    for dr, dc in PIECE_ROTATION_STATES[piece][rotation]:
        r, c = origin_row + dr, origin_col + dc
        grid[r][c] = piece
        samples[r][c] = PIECE_COLORS[piece]


class TestInferCurrentPiece(unittest.TestCase):
    def test_detects_spawning_piece_by_shape_at_top(self) -> None:
        grid = _empty_grid()
        samples = _empty_samples()
        _place_piece_cells(grid, samples, "T", origin_row=0, origin_col=4)

        result = _infer_current_piece(grid, samples)

        self.assertIsNotNone(result)
        piece, min_row = result.piece, result.min_row
        self.assertEqual(piece, "T")
        self.assertEqual(min_row, 0)

    def test_detects_piece_that_has_descended_below_top_rows(self) -> None:
        # 操作中ミノは盤面上部に限らずどこにあってもよい(以前は上端4行にしか
        # 対応しておらず、ソフトドロップ後に検出できなくなる欠陥があった)。
        grid = _empty_grid()
        samples = _empty_samples()
        _place_piece_cells(grid, samples, "L", origin_row=10, origin_col=2)

        result = _infer_current_piece(grid, samples)

        self.assertIsNotNone(result)
        piece, min_row = result.piece, result.min_row
        self.assertEqual(piece, "L")
        self.assertEqual(min_row, 10)

    def test_naive_search_limit_hides_falling_piece_bridged_over_gap(self) -> None:
        # TestSettledTopRow.test_floating_falling_piece_over_empty_columns_
        # is_not_settled と同じ盤面。以前は_settled_top_row(grid)が16を返し、
        # 操作中のIミノ(行16)自体が探索範囲外になって見つからなかった。
        # 支えの有無で判定するようになり18が返るため、search_limitを
        # 省略してもIミノが正しく検出される。
        grid = _empty_grid()
        samples = _empty_samples()
        grid[18][0] = "O"
        grid[18][1] = "O"
        grid[19][0] = "O"
        grid[19][1] = "O"
        grid[19][7] = "L"
        grid[19][8] = "L"
        grid[19][9] = "L"
        for c in range(2, 6):
            grid[16][c] = "I"
            samples[16][c] = PIECE_COLORS["I"]

        detection = _infer_current_piece(grid, samples)
        self.assertIsNotNone(detection)
        self.assertEqual((detection.piece, detection.min_row), ("I", 16))

    def test_explicit_search_limit_recovers_falling_piece_hidden_by_bridge(self) -> None:
        # 同じ盤面でも、呼び出し側(recognize())が前回の信頼値
        # (この場合は本物の着地済み領域の上端である18)をsearch_limitとして
        # 明示的に渡せば、Iミノは探索範囲内(0〜17行目)に収まり正しく
        # 検出できる。これがrecognize()のprevious_settled_top_row_hintに
        # よる2tickデバウンス対策の土台になる。
        grid = _empty_grid()
        samples = _empty_samples()
        grid[18][0] = "O"
        grid[18][1] = "O"
        grid[19][0] = "O"
        grid[19][1] = "O"
        grid[19][7] = "L"
        grid[19][8] = "L"
        grid[19][9] = "L"
        for c in range(2, 6):
            grid[16][c] = "I"
            samples[16][c] = PIECE_COLORS["I"]

        result = _infer_current_piece(grid, samples, search_limit=18)

        self.assertIsNotNone(result)
        piece, min_row = result.piece, result.min_row
        self.assertEqual(piece, "I")
        self.assertEqual(min_row, 16)

    def test_ignores_settled_blocks_below_search_limit(self) -> None:
        # 着地済みブロック(最下段近く)だけがある場合、操作中ミノは存在しない
        # ので settled_top_row 以下しか探索されず None を返すべき。
        grid = _empty_grid()
        samples = _empty_samples()
        # 最下段2行を丸ごと埋める(着地済み領域として_settled_top_rowに認識させる)
        for r in (18, 19):
            for c in range(BOARD_COLS):
                grid[r][c] = "GARBAGE"
                samples[r][c] = PIECE_COLORS["GARBAGE"]

        result = _infer_current_piece(grid, samples)

        self.assertIsNone(result)

    def test_returns_none_when_component_merges_with_settled_blocks(self) -> None:
        # 操作中ミノが着地済みブロックと直接隣接して5マス以上の塊に
        # なってしまった場合は信頼できないとしてNoneを返すべき
        # (誤ったミノ種類を報告するより、認識失敗として扱う方が安全)。
        # Oミノのspawn形状は(0,1),(0,2),(1,1),(1,2)なので、
        # origin_row=8,origin_col=4だと実セルは列5,6に来る点に注意。
        grid = _empty_grid()
        samples = _empty_samples()
        _place_piece_cells(grid, samples, "O", origin_row=8, origin_col=4)
        # Oミノの直下(列5)に隣接するノイズブロックを1つ追加し、5マスの塊にする
        grid[10][5] = "GARBAGE"
        samples[10][5] = PIECE_COLORS["GARBAGE"]

        result = _infer_current_piece(grid, samples)

        self.assertIsNone(result)

    def test_falls_back_to_color_majority_when_only_three_cells_visible(self) -> None:
        # 4マス目が何らかの理由で欠けている(3マスしか見えない)場合、
        # 形状マッチングは使えないため色の多数決にフォールバックする。
        # Sミノのspawn形状(0,1),(0,2),(1,0),(1,1)のうち、(1,0)を除いた
        # (0,1),(0,2),(1,1)は互いに4方向隣接しており1つの連結成分になる。
        grid = _empty_grid()
        samples = _empty_samples()
        cells = [(0, 1), (0, 2), (1, 1)]
        for dr, dc in cells:
            r, c = 5 + dr, 4 + dc
            grid[r][c] = "S"
            samples[r][c] = PIECE_COLORS["S"]

        result = _infer_current_piece(grid, samples)

        self.assertIsNotNone(result)
        piece = result.piece
        self.assertEqual(piece, "S")

    def test_partial_i_j_without_hint_falls_back_to_color_median(self) -> None:
        # IとJは、片方の端(角)が欠けて3マスしか見えない場合、残りの3マスの
        # 形がどちらも完全に同じ一直線になり、形状だけでは区別できない。
        # ヒントがない場合は従来通り明度中央値(_resolve_i_j)にフォールバック
        # するべき(この場合はI_J_VALUE_THRESHOLD=0.82を超える明るいサンプル
        # なのでIと判定される)。
        grid = _empty_grid()
        samples = _empty_samples()
        cells = [(5, 4), (5, 5), (5, 6)]
        for r, c in cells:
            grid[r][c] = "I"
            samples[r][c] = RGB(230, 0, 0)  # V≈0.90 -> I

        result = _infer_current_piece(grid, samples)

        self.assertIsNotNone(result)
        piece = result.piece
        self.assertEqual(piece, "I")

    def test_partial_i_j_with_hint_overrides_noisy_color_median(self) -> None:
        # 実機ログで確認された不具合の回帰テスト: 盤面・HOLD・NEXT欄が
        # 一切変わっていないのに、current判定だけがI/J間を往復する現象が
        # あった。原因は、部分的に隠れたI/Jの色判定(明度中央値)がtickごとに
        # ノイズで揺らぐこと。previous_piece_hintを渡した場合、たとえ生の
        # 色判定が逆の結論(この場合は明るいのでI)を示していても、直前の
        # 確定値(J)をそのまま優先すべき(3マスしか見えないケースは新規
        # スポーン直後ではなくほぼ確実に同じミノが移動中であるため)。
        grid = _empty_grid()
        samples = _empty_samples()
        cells = [(5, 4), (5, 5), (5, 6)]
        for r, c in cells:
            grid[r][c] = "I"
            samples[r][c] = RGB(230, 0, 0)  # V≈0.90 -> 生の色判定は"I"

        result = _infer_current_piece(grid, samples, previous_piece_hint="J")

        self.assertIsNotNone(result)
        piece = result.piece
        self.assertEqual(piece, "J")

    def test_partial_non_i_j_piece_with_hint_overrides_color_majority(self) -> None:
        # 実機ログで確認された不具合の回帰テスト: I/J限定のデバウンス導入後も
        # 「盤面・HOLD・NEXT欄が一切変わっていないのにcurrent判定だけが
        # 往復する」現象がZ↔Iの組み合わせで再発した(同一の盤面スナップ
        # ショットに対しcurrent=Z→I→Zと3回連続で書き換えられていた)。
        # 色の多数決フォールバックはI/J以外の組み合わせでも同様に信頼性が
        # 低いため、previous_piece_hintがI/J以外(この場合はZ)であっても、
        # 生の色判定の結論を上書きして優先すべき。
        grid = _empty_grid()
        samples = _empty_samples()
        cells = [(5, 4), (5, 5), (5, 6)]
        for r, c in cells:
            grid[r][c] = "I"
            samples[r][c] = RGB(230, 0, 0)  # 生の色判定は"I"

        result = _infer_current_piece(grid, samples, previous_piece_hint="Z")

        self.assertIsNotNone(result)
        piece = result.piece
        self.assertEqual(piece, "Z")

    def test_full_four_cell_shape_match_ignores_hint(self) -> None:
        # 4マスきちんと見えている通常のケースでは、形状マッチングだけで
        # 判定が確定するため、previous_piece_hintが実際のミノ種と異なって
        # いても無視され、正しい形状が返されるべき(ヒントは3マスの
        # あいまいなケースのみに影響する)。
        grid = _empty_grid()
        samples = _empty_samples()
        _place_piece_cells(grid, samples, "J", origin_row=5, origin_col=4)

        result = _infer_current_piece(grid, samples, previous_piece_hint="I")

        self.assertIsNotNone(result)
        piece = result.piece
        self.assertEqual(piece, "J")


class TestResolveIJ(unittest.TestCase):
    def test_high_brightness_median_resolves_to_i(self) -> None:
        # I_J_VALUE_THRESHOLD=0.82。V≈0.90(明るい)のサンプルはIと判定されるべき。
        grid = _empty_grid()
        samples = _empty_samples()
        component = {(0, 0), (0, 1)}
        for r, c in component:
            grid[r][c] = "I"
            samples[r][c] = RGB(230, 0, 0)  # V=230/255≈0.90

        self.assertEqual(_resolve_i_j(component, grid, samples), "I")

    def test_low_brightness_median_resolves_to_j(self) -> None:
        # V≈0.77(暗め)のサンプルはJと判定されるべき。
        grid = _empty_grid()
        samples = _empty_samples()
        component = {(0, 0), (0, 1)}
        for r, c in component:
            grid[r][c] = "J"
            samples[r][c] = RGB(196, 0, 0)  # V=196/255≈0.77

        self.assertEqual(_resolve_i_j(component, grid, samples), "J")


class TestSettledTopRow(unittest.TestCase):
    def test_empty_board_returns_full_height(self) -> None:
        grid = _empty_grid()
        self.assertEqual(_settled_top_row(grid), BOARD_ROWS)

    def test_ignores_single_cell_noise(self) -> None:
        # 1マスだけのノイズ(透かし模様の誤検出等)は着地済み行とみなさない。
        grid = _empty_grid()
        grid[10][3] = "GARBAGE"
        self.assertEqual(_settled_top_row(grid), BOARD_ROWS)

    def test_tolerates_a_single_noisy_empty_row_within_settled_region(self) -> None:
        # 実機ログで確認された重大な不具合の回帰テスト: ライン消去エフェクト等の
        # ノイズで最下段付近の1行だけが一時的に「空」と誤認識されると、そこで
        # 即座に打ち切られ、実際にはまだ大量のブロックが残る盤面全体を「空」と
        # 誤判定してしまっていた(テトリスは重力で落下する性質上、着地済み領域で
        # 「下の行が空なのに上の行が埋まっている」ことは物理的にありえないため、
        # 1行だけの空判定はノイズとみなして無視し、さらに上まで探索を続けるべき)。
        grid = _empty_grid()
        grid[17][0] = "T"
        grid[17][1] = "T"
        # 行18が丸ごとノイズで空扱いになったと仮定(本来は何か埋まっているはず)
        grid[19][0] = "T"
        grid[19][1] = "T"

        self.assertEqual(_settled_top_row(grid), 17)

    def test_row_with_a_single_supported_cell_is_settled(self) -> None:
        # 実機で確認された不具合の回帰テスト(18:22:48): 縦向きミノの先端の
        # ように1マスだけ積み上がった行が、旧実装の「2マス以上埋まっている
        # 行だけを非空とみなす」条件で着地済み領域から外され、
        # _build_settled_boardがその行を丸ごと捨てていた。結果、既に置かれて
        # いるJミノがAIから見えず、その上にZミノの提案ドットが重なった。
        grid = _empty_grid()
        for c in range(0, 4):
            grid[19][c] = "O"
        grid[18][0] = "J"
        grid[18][1] = "J"
        # 行17は列1に1マスだけ(真下の(18,1)に支えがある実在のブロック)
        grid[17][1] = "J"

        self.assertEqual(_settled_top_row(grid), 17)

    def test_floating_single_cell_noise_is_still_rejected(self) -> None:
        # 支えのない孤立1マス(透かし絵柄等の誤検出)は、従来どおり
        # 着地済み領域とみなさないこと。ノイズ除去の目的は保つ。
        grid = _empty_grid()
        for c in range(0, 4):
            grid[19][c] = "O"
        # 列7は下が全て空なので、この1マスは物理的にありえない=ノイズ
        grid[15][7] = "T"

        self.assertEqual(_settled_top_row(grid), 19)

    def test_two_consecutive_empty_rows_are_treated_as_genuinely_empty(self) -> None:
        # ノイズ許容は1行までで、2行連続で空なら本当にそこで着地済み領域が
        # 終わっているとみなして打ち切るべき(ノイズ許容を無制限にすると、
        # 逆に本当に空いている領域まで着地済みとして誤って取り込んでしまう)。
        grid = _empty_grid()
        grid[15][0] = "T"
        grid[15][1] = "T"
        # 行16,17は本当に空(2行連続)
        grid[19][0] = "T"
        grid[19][1] = "T"

        self.assertEqual(_settled_top_row(grid), 19)

    def test_detects_settled_region_with_two_or_more_filled_cells(self) -> None:
        grid = _empty_grid()
        grid[19][0] = "T"
        grid[19][1] = "T"
        self.assertEqual(_settled_top_row(grid), 19)

    def test_floating_falling_piece_over_empty_columns_is_not_settled(self) -> None:
        # 実機ログ(2026-09-06)で確認されたバグの回帰テスト。操作中の
        # 横向きIミノ(4マス、着地済み領域の1行だけ上=間に空行が1つ)が、
        # _SETTLED_ROW_MAX_SKIP(1行分のノイズ許容)によって着地済み領域の
        # 一部として誤って取り込まれていた。
        # 「支えの有無」で判定するようになったため、下に何も無い列(2〜5)に
        # 浮いているIミノは着地済みとみなされなくなった。
        grid = _empty_grid()
        grid[18][0] = "O"
        grid[18][1] = "O"
        grid[19][0] = "O"
        grid[19][1] = "O"
        grid[19][7] = "L"
        grid[19][8] = "L"
        grid[19][9] = "L"
        # 行17は空(操作中ミノと着地済み領域の間の本物の隙間)。
        # 行16に横向きIミノ(4マス)が浮いている。
        grid[16][2] = "I"
        grid[16][3] = "I"
        grid[16][4] = "I"
        grid[16][5] = "I"

        self.assertEqual(_settled_top_row(grid), 18)


class TestFallingPieceSearchLimit(unittest.TestCase):
    """探索範囲と着地済み盤面が別の規則で求められることの回帰テスト。

    有識者資料[107]の指摘に対応する。「支えの有無」で着地済みを判定すると、
    空中の操作ミノも同じ列の下方にブロックがあるため支えありと判定され、
    着地済み領域へ取り込まれてしまう。実測でも高積み時の操作ミノ検出失敗率が
    77%→81%に悪化していた。探索範囲は保守的な規則で別に求める。
    """

    def test_vertical_piece_above_a_stack_stays_within_the_search_range(self) -> None:
        grid = _empty_grid()
        # 高く積まれた山(列0〜2、行14〜19)
        for r in range(14, 20):
            for c in range(0, 3):
                grid[r][c] = "GARBAGE"
        # 山の真上に浮いている操作中ミノ(縦向きI、列1の行10〜13)。
        # 列1の下方には山があるため、支え判定では全4マスが「支えあり」になる。
        for r in range(10, 14):
            grid[r][1] = "I"

        # 着地済み盤面側は包含的なので、操作ミノごと取り込んでしまう
        self.assertEqual(_settled_top_row(grid), 10)
        # 探索範囲側は保守的なので、操作ミノの全4マスを探索対象に残す
        self.assertEqual(
            _falling_piece_search_limit(grid),
            14,
            "操作ミノの行が探索範囲から外れている",
        )

    def test_wide_piece_directly_on_the_stack_is_a_known_limitation(self) -> None:
        # 保守的な規則でも、山の直上に接した「1行に2マス以上ある」操作ミノは
        # 区別できない(マスの数だけでは着地済みと見分けがつかない)。
        # これは既知の限界であり、解消には形状ベースの候補分解が要る。
        # 現状はrecognize()側のデバウンス(_bridge_looks_like_falling_piece)と
        # 前回値のヒントで補っている。
        grid = _empty_grid()
        for r in range(14, 20):
            for c in range(0, 3):
                grid[r][c] = "GARBAGE"
        for c in range(0, 4):
            grid[13][c] = "I"

        self.assertEqual(_falling_piece_search_limit(grid), 13)

    def test_search_limit_still_rejects_isolated_noise(self) -> None:
        # 保守的な規則でも、孤立した1マスのノイズは着地済みとみなさない。
        grid = _empty_grid()
        for c in range(0, 4):
            grid[19][c] = "O"
        grid[15][7] = "T"
        self.assertEqual(_falling_piece_search_limit(grid), 19)


class TestBridgeLooksLikeFallingPiece(unittest.TestCase):
    def test_floating_piece_with_real_gap_row_is_detected(self) -> None:
        # 完全な空行(隙間)を挟んで操作中ミノ(4マスのひとかたまり)だけが
        # 浮いている典型的なケース。
        bridge = _empty_grid(rows=2, cols=BOARD_COLS)
        bridge[0][2] = "I"
        bridge[0][3] = "I"
        bridge[0][4] = "I"
        bridge[0][5] = "I"
        # bridge[1]は完全な空行(操作中ミノと着地済み地形の間の本物の隙間)。

        self.assertTrue(_bridge_looks_like_falling_piece(bridge))

    def test_real_placement_without_a_genuine_empty_row_is_not_flagged(self) -> None:
        # L/J/T等は着地済みでも1マスしか埋まっていない行が自然に存在する
        # (この例では2行目が1マスだけ)。これは「疎ら」であって「完全な
        # 空行」ではないため、本物の設置として誤って棄却してはいけない。
        bridge = _empty_grid(rows=2, cols=BOARD_COLS)
        bridge[0][0] = "L"
        bridge[0][1] = "L"
        bridge[0][2] = "L"
        bridge[1][0] = "L"

        self.assertFalse(_bridge_looks_like_falling_piece(bridge))

    def test_large_irregular_terrain_with_a_noisy_empty_row_is_not_flagged(self) -> None:
        # 完全な空行があっても、非空マスの合計が5マス以上(本物の地形らしい
        # 量)であれば操作中ミノとはみなさない。
        bridge = _empty_grid(rows=2, cols=BOARD_COLS)
        for c in range(6):
            bridge[0][c] = "GARBAGE"
        # bridge[1]は完全な空行。

        self.assertFalse(_bridge_looks_like_falling_piece(bridge))

    def test_no_empty_row_at_all_is_not_flagged_even_if_small(self) -> None:
        # 完全な空行が1つも無い(本物の隙間が存在しない)場合は、
        # マス数がたまたま4以下でも操作中ミノとはみなさない。
        bridge = _empty_grid(rows=1, cols=BOARD_COLS)
        bridge[0][4] = "O"
        bridge[0][5] = "O"

        self.assertFalse(_bridge_looks_like_falling_piece(bridge))


class TestOverlaySelfContaminationCountermeasure(unittest.TestCase):
    """自己汚染対策が「盤面のマスク」ではなく「キャプチャからの除外」であることを固定化する。

    経緯: SetWindowDisplayAffinityをargtypes未指定で呼んでいた時期にHWNDが
    32bitへ切り詰められて除外が失敗しており、その失敗が握り潰されていた
    ため「除外APIは実機で効かない」と誤って結論された。回避策として
    「自分が描画したセルを強制的に空マスにする」処理が入ったが、これは
    人間が提案どおりに置いた直後の4マスまで盤面から消してしまう副作用が
    あった。argtypes修正後は除外が正常動作することを検証済みのため、
    マスク処理を撤去した。復活させないための回帰テスト。
    """

    def test_recognize_has_no_overlay_masking_parameter(self) -> None:
        # 盤面グリッドを自分の描画位置で空マス化する経路が復活していないこと。
        params = inspect.signature(recognize).parameters
        self.assertNotIn("own_overlay_cells", params)

    def test_mask_helper_no_longer_exists(self) -> None:
        self.assertFalse(hasattr(app, "_mask_own_overlay_cells"))


class TestExcludeWindowFromScreenCapture(unittest.TestCase):
    def test_returns_false_when_the_api_call_fails(self) -> None:
        # 除外失敗を静かに握り潰すと、盤面認識が原因不明の形で壊れる。
        # 呼び出し側が気づけるよう、必ずFalseを返すこと。
        widget = MagicMock()
        widget.winId.return_value = 12345

        fake_user32 = MagicMock()
        fake_user32.SetWindowDisplayAffinity.return_value = 0
        with patch("sys.platform", "win32"), patch(
            "ctypes.windll", create=True, new=MagicMock(user32=fake_user32)
        ):
            self.assertFalse(_exclude_window_from_screen_capture(widget))

    def test_returns_false_when_the_setting_is_not_actually_retained(self) -> None:
        # 戻り値がTRUEでも、読み戻した値が期待どおりでなければ除外は
        # 効いていない。TRUEだけを信用しないこと。
        widget = MagicMock()
        widget.winId.return_value = 12345

        fake_user32 = MagicMock()
        fake_user32.SetWindowDisplayAffinity.return_value = 1
        fake_user32.GetWindowDisplayAffinity.return_value = 1

        def _leave_affinity_unset(_hwnd, out_ptr):
            # 読み戻した値が0(除外なし)のまま、という状況を再現する。
            out_ptr._obj.value = 0
            return 1

        fake_user32.GetWindowDisplayAffinity.side_effect = _leave_affinity_unset
        with patch("sys.platform", "win32"), patch(
            "ctypes.windll", create=True, new=MagicMock(user32=fake_user32)
        ):
            self.assertFalse(_exclude_window_from_screen_capture(widget))


class TestRecognizePartialSuccess(unittest.TestCase):
    """有識者資料[001]「認識の部分成功を返す」への対応の回帰テスト。

    操作ミノが画像から読めなくても、正しく読めていた盤面・NEXT・HOLDまで
    捨てて全体を失敗扱いにしないこと。実機では認識失敗が稼働時間の45%を
    占めており、その間は手番の進行もHOLDの変化も追えなくなっていた。
    """

    def _calibration(self):
        from src.capture.calibrate import CalibrationResult

        return CalibrationResult(
            board_origin_x=0,
            board_origin_y=0,
            board_width=BOARD_COLS * 10,
            board_height=BOARD_ROWS * 10,
            cell_size=10,
            board_cols=BOARD_COLS,
            board_rows=BOARD_ROWS,
            hold_rect=(0, 0, 10, 10),
            next_rects=[(0, 0, 10, 10)] * 5,
        )

    def test_debounce_range_matches_the_board_range(self) -> None:
        # デバウンスの範囲は、盤面として切り出す範囲と必ず一致させること。
        # 一致していないと、盤面には含まれるのにデバウンスが掛からない行が
        # 生じる。それは積みの上端という最もノイズが多い領域で、そこの
        # 一瞬の誤読がそのままAIへ渡り、既存ブロックと重なる提案(干渉)の
        # 原因になる。
        calibration = self._calibration()
        capture = MagicMock()
        img = np.zeros((BOARD_ROWS * 10, BOARD_COLS * 10, 3), dtype=np.uint8)
        # 最下段は全て埋め、その1つ上は列1だけ埋める。こうすると包含的な
        # 上端(18)と保守的な上端(19)が食い違い、両者の取り違えを検出できる。
        img[(BOARD_ROWS - 1) * 10 :, :] = 200
        # 1マスだけのGARBAGEは演出ノイズとして捨てられるため、実際の
        # テンプレート画像を貼って「色のあるミノ1マス」にする。
        from src.vision.template_matcher import get_templates

        template = get_templates()["J"]
        cell = np.array(
            [[template[y * template.shape[0] // 10][x * template.shape[1] // 10] for x in range(10)]
             for y in range(10)],
            dtype=np.uint8,
        )
        img[(BOARD_ROWS - 2) * 10 : (BOARD_ROWS - 1) * 10, 10:20] = cell

        capture.grab.return_value = img

        seen: list[int] = []
        real = app._stabilize_settled_grid

        def spy(raw_grid, exclude_rows, prev_confirmed, prev_pending):
            seen.append(exclude_rows)
            return real(raw_grid, exclude_rows, prev_confirmed, prev_pending)

        detection = app.CurrentPieceDetection("T", 0, frozenset())
        with patch("src.app._build_settled_board", wraps=app._build_settled_board) as build:
            with patch("src.app._stabilize_settled_grid", side_effect=spy):
                with patch("src.app._infer_current_piece", return_value=detection):
                    recognize(calibration, capture)

        self.assertTrue(seen, "安定化が呼ばれていない")
        used_for_board = build.call_args.kwargs["exclude_rows"]
        self.assertEqual(used_for_board, BOARD_ROWS - 2, "前提が崩れている(盤面の上端)")
        self.assertEqual(
            seen[0], used_for_board, "デバウンスの範囲が盤面の範囲と一致していない"
        )

    def _recognize_with_grid(self, grid, detection):
        calibration = self._calibration()
        capture = MagicMock()
        img = np.zeros((BOARD_ROWS * 10, BOARD_COLS * 10, 3), dtype=np.uint8)
        img[(BOARD_ROWS - 1) * 10 :, :] = 200  # 暗転判定を避けるため盤面を空にしない
        capture.grab.return_value = img
        samples = _empty_samples()
        with patch("src.app.read_board_grid_with_samples", return_value=(grid, samples)):
            with patch("src.app._infer_current_piece", return_value=detection):
                return recognize(calibration, capture)

    def test_piece_resting_on_the_stack_is_kept_in_the_settled_board(self) -> None:
        # 【2026-09-11実機ログ】置いたばかりの縦Iが積みの上端より4段突き出して
        # いるため、次のミノがスポーンしたtickでも操作ミノと推定され、その
        # セルが着地済み盤面から除外されてAIへ渡った。AIはそのIの上にZを
        # 提案し、既存ブロックと重なった。積みに載っているミノは除外しないこと。
        grid = _empty_grid()
        for c in range(BOARD_COLS):
            grid[BOARD_ROWS - 1][c] = "GARBAGE"
        cells = frozenset((r, 9) for r in range(BOARD_ROWS - 5, BOARD_ROWS - 1))
        for r, c in cells:
            grid[r][c] = "I"
        detection = app.CurrentPieceDetection("I", BOARD_ROWS - 5, cells)

        result = self._recognize_with_grid(grid, detection)

        for r, c in cells:
            self.assertEqual(result.board.grid[r][c], "I", f"載っているIの({r},{c})が盤面から消えている")
            # ただし確定盤面(次tickのヒント・board_key)には入れない。入れると
            # ミノを横へ動かした後も2tick幻のブロックとして残り、その上に
            # 提案が出て空中に浮く(5回目の実機画像036)。
            self.assertIsNone(result.board_key[r][c], f"載っているIの({r},{c})がboard_keyに混入している")
            self.assertIsNone(result.confirmed_grid[r][c], f"載っているIの({r},{c})が確定盤面に混入している")

    def test_stem_above_the_conservative_limit_is_kept_when_the_piece_is_unreadable(self) -> None:
        # 【2026-09-11・7回目の実機ログ】置いたばかりの縦Lの柱(1マスしかない
        # 行)が光って操作ミノとして読めない瞬間、保守的な上限より上が
        # 丸ごと切り落とされて盤面から消え、AIがその上にOを提案して2手目
        # から干渉した。積みに連結しているマスは残すこと。
        grid = _empty_grid()
        for c in range(10):
            grid[19][c] = "GARBAGE"
        grid[19][0] = "L"
        grid[19][1] = "L"
        grid[18][0] = "L"  # 1マスだけの行(保守的な上限より上)
        grid[17][0] = "L"

        result = self._recognize_with_grid(grid, None)
        self.assertEqual(result.board.grid[18][0], "L", "柱が切り落とされている")
        self.assertEqual(result.board.grid[17][0], "L", "柱が切り落とされている")

    def test_floating_cells_above_the_conservative_limit_are_dropped_when_the_piece_is_unreadable(self) -> None:
        # 宙に浮いた(積みに連結していない)マスは従来どおり切り落とす。
        grid = _empty_grid()
        for c in range(10):
            grid[19][c] = "GARBAGE"
        grid[12][4] = "T"
        grid[12][5] = "T"
        grid[12][6] = "T"
        grid[11][5] = "T"

        result = self._recognize_with_grid(grid, None)
        self.assertIsNone(result.board.grid[12][5], "浮いたマスが盤面に残っている")

    def test_falling_piece_is_still_excluded_from_the_settled_board(self) -> None:
        # 真下が空いている(落下中の)ミノは従来どおり盤面から除外する。
        grid = _empty_grid()
        for c in range(BOARD_COLS):
            grid[BOARD_ROWS - 1][c] = "GARBAGE"
        cells = frozenset((r, 9) for r in range(BOARD_ROWS - 8, BOARD_ROWS - 4))
        for r, c in cells:
            grid[r][c] = "I"
        detection = app.CurrentPieceDetection("I", BOARD_ROWS - 8, cells)

        result = self._recognize_with_grid(grid, detection)

        for r, c in cells:
            self.assertIsNone(result.board.grid[r][c], f"落下中のIの({r},{c})が盤面に残っている")

    def test_returns_a_result_even_when_the_current_piece_cannot_be_inferred(self) -> None:
        calibration = self._calibration()
        capture = MagicMock()
        # 全体を覆う1枚の画像を返す。最下段に明るい灰色(=お邪魔ブロック相当)を
        # 置いて、盤面が空でないようにする。盤面・NEXT・HOLDが同時にすべて
        # 空だと「暗転・映像なし」として別途Noneが返るため。
        img = np.zeros((BOARD_ROWS * 10, BOARD_COLS * 10, 3), dtype=np.uint8)
        img[(BOARD_ROWS - 1) * 10 :, :] = 200
        capture.grab.return_value = img

        with patch("src.app._infer_current_piece", return_value=None):
            result = recognize(calibration, capture)

        self.assertIsNotNone(result, "操作ミノが読めないだけで全体を失敗にしている")
        self.assertIsNone(result.current_piece)
        self.assertIsNotNone(result.board)
        self.assertIsNotNone(result.next_slots_raw)


class TestEstimateNextShift(unittest.TestCase):
    """NEXTの移動量を候補比較で決めることの回帰テスト(有識者資料[039])。"""

    BASE = ("O", "L", "J", "S", "Z")

    def test_no_change(self) -> None:
        self.assertEqual(_estimate_next_shift(self.BASE, self.BASE), 0)

    def test_advanced_by_one(self) -> None:
        self.assertEqual(_estimate_next_shift(self.BASE, ("L", "J", "S", "Z", "T")), 1)

    def test_advanced_by_two(self) -> None:
        self.assertEqual(_estimate_next_shift(self.BASE, ("J", "S", "Z", "T", "I")), 2)

    def test_unreadable_slots_are_ignored(self) -> None:
        # 5枠中2枠が読めれば移動量を決められる。
        self.assertEqual(_estimate_next_shift(self.BASE, ("L", None, "S", None, None)), 1)

    def test_single_misread_slot_yields_no_decision(self) -> None:
        # 1枠だけ前回と違う。どの移動量でも矛盾なく説明できないので、
        # 推測で進行を決めない。
        self.assertIsNone(_estimate_next_shift(self.BASE, ("O", "L", "Z", "S", "Z")))

    def test_too_few_readable_slots_yields_no_decision(self) -> None:
        # 1枠しか読めていない場合は、たまたま一致しても移動量を決めない。
        self.assertIsNone(_estimate_next_shift(self.BASE, ("L", None, None, None, None)))

    def test_ambiguous_repeated_pattern_yields_no_decision(self) -> None:
        # 同じ種類が並ぶと複数の移動量が同時に成立しうる。一意でなければ決めない。
        base = ("T", "T", "T", "T", "T")
        self.assertIsNone(_estimate_next_shift(base, ("T", "T", "T", "T", "T")))


class TestDetectGarbageRise(unittest.TestCase):
    """おじゃまのせり上がり検出の回帰テスト。

    仕様「最善手は、相手からの妨害で段がせりあがる場合を除き、表示を
    切り替えない」の“除き”にあたる明示的な例外。これが実装されていなかった
    ため、攻撃を受けて着地位置が丸ごとずれても次の固定まで提案が再計算されず、
    実機で「相手の攻撃に追い付かない」と報告された。
    """

    def _key(self, rows_spec):
        """'.'と'#'の並びから盤面キーを作る(上詰め、残りは空行)。"""
        grid = [tuple([None] * BOARD_COLS) for _ in range(BOARD_ROWS - len(rows_spec))]
        for spec in rows_spec:
            grid.append(tuple("GARBAGE" if ch == "#" else None for ch in spec))
        return tuple(grid)

    def test_single_row_rise(self) -> None:
        before = self._key(["###.######"])
        after = self._key(["###.######", "#####.####"])
        self.assertEqual(_detect_garbage_rise(before, after), 1)

    def test_multi_row_rise(self) -> None:
        before = self._key(["###.######"])
        after = self._key(["###.######", "#####.####", "#.########"])
        self.assertEqual(_detect_garbage_rise(before, after), 2)

    def test_no_change_is_not_a_rise(self) -> None:
        board = self._key(["###.######"])
        self.assertEqual(_detect_garbage_rise(board, board), 0)

    def test_empty_board_is_not_a_rise(self) -> None:
        # 全行が空だと「何行ずらしても一致」してしまうため、誤検出しやすい。
        empty = self._key([])
        self.assertEqual(_detect_garbage_rise(empty, empty), 0)

    def test_piece_lock_is_not_a_rise(self) -> None:
        # ミノが固定されて4マス増えただけでは、全行が揃って上へ移動しない。
        before = self._key(["###.######"])
        after_rows = ["....##....", "###.######"]
        self.assertEqual(_detect_garbage_rise(before, self._key(after_rows)), 0)

    def test_rise_onto_an_empty_board(self) -> None:
        # 空の盤面へ最初のおじゃまが入る場合も検出できること。
        before = self._key([])
        after = self._key(["###.######"])
        self.assertEqual(_detect_garbage_rise(before, after), 1)


class TestDetectLock(unittest.TestCase):
    """ネクストが進む3種類の事象のうち、固定を伴うのは1つだけであることの確認。

    ・通常の固定       : NEXTが進む / HOLDは変わらない → 固定あり
    ・初回の空HOLD交換 : NEXTが進む / HOLDが変わる     → 固定なし
    ・既存HOLDとの交換 : NEXTは進まない / HOLDが変わる → 固定なし
    """

    def test_normal_lock(self) -> None:
        self.assertTrue(_detect_lock(next_advanced=True, hold_changed=False, had_previous_piece=True))

    def test_first_hold_from_empty_advances_next_without_locking(self) -> None:
        self.assertFalse(_detect_lock(next_advanced=True, hold_changed=True, had_previous_piece=True))

    def test_swap_with_existing_hold_does_not_advance_next(self) -> None:
        self.assertFalse(_detect_lock(next_advanced=False, hold_changed=True, had_previous_piece=True))

    def test_no_change_is_not_a_lock(self) -> None:
        self.assertFalse(_detect_lock(next_advanced=False, hold_changed=False, had_previous_piece=True))

    def test_very_first_spawn_is_not_a_lock(self) -> None:
        # 対局開始後の最初のスポーンでは、まだ何も置かれていない。
        self.assertFalse(_detect_lock(next_advanced=True, hold_changed=False, had_previous_piece=False))


class TestIsNextQueueImpossible(unittest.TestCase):
    def test_normal_queue_without_duplicates_is_possible(self) -> None:
        self.assertFalse(_is_next_queue_impossible(("O", "L", "S", "Z", "T")))

    def test_two_occurrences_across_bag_boundary_is_possible(self) -> None:
        # 5枠は最大2つの袋にまたがりうるため、同じ種類が2つまでは正常。
        self.assertFalse(_is_next_queue_impossible(("I", "O", "L", "S", "I")))

    def test_three_occurrences_is_impossible(self) -> None:
        # 実機ログで確認された不具合の回帰テスト:
        # ['I', 'I', 'O', 'S', 'I']のような、7-bag方式ではありえない
        # (同じ種類が5枠中3つ以上を占める)パターンを検知できること。
        self.assertTrue(_is_next_queue_impossible(("I", "I", "O", "S", "I")))


def _board_key_with_filled_count(count: int, width: int = BOARD_COLS, height: int = BOARD_ROWS) -> tuple[tuple[str | None, ...], ...]:
    """下段から`count`マスを"X"で埋めた盤面キーを作る(テスト用のダミーデータ)。"""
    grid = _empty_grid(rows=height, cols=width)
    filled = 0
    for r in range(height - 1, -1, -1):
        for c in range(width):
            if filled >= count:
                break
            grid[r][c] = "X"
            filled += 1
        if filled >= count:
            break
    return tuple(tuple(row) for row in grid)


class TestTspinLabel(unittest.TestCase):
    def _move(self, piece, cells, spin):
        from src.engine.cold_clear_client import ColdClearMove

        return ColdClearMove(
            use_hold=False, piece=piece, landing_cells=cells, nodes=0, nps=0.0,
            placement={"location": {}, "spin": spin},
        )

    def test_tspin_double_is_labeled(self) -> None:
        from src.app import _tspin_label
        from src.engine.board_state import BoardState

        board = BoardState()
        for r in (18, 19):
            for c in range(10):
                if c not in (4, 5, 6) or (r == 19 and c in (4, 6)):
                    board.grid[r][c] = "G"
        move = self._move("T", [(18, 4), (18, 5), (18, 6), (19, 5)], "full")
        self.assertEqual(_tspin_label(board, move), "狙い: Tスピンダブル(TSD)")

    def test_non_spin_moves_have_no_label(self) -> None:
        from src.app import _tspin_label
        from src.engine.board_state import BoardState

        self.assertIsNone(_tspin_label(BoardState(), self._move("T", [(19, 0), (19, 1), (19, 2), (18, 1)], "none")))
        self.assertIsNone(_tspin_label(BoardState(), self._move("S", [(19, 0), (19, 1), (18, 1), (18, 2)], "full")))


class TestPlanStepsOnScreen(unittest.TestCase):
    """読み筋(2手目以降)のうち画面座標のまま表示できる手の判定。"""

    def _move(self, piece, cells, plan):
        from src.engine.cold_clear_client import ColdClearMove

        return ColdClearMove(use_hold=False, piece=piece, landing_cells=cells, nodes=0, nps=0.0, plan=plan)

    def test_all_steps_are_shown_when_nothing_clears(self) -> None:
        from src.app import _plan_steps_on_screen
        from src.engine.board_state import BoardState

        move = self._move("O", [(19, 0), (19, 1), (18, 0), (18, 1)], [
            ("I", [(19, 2), (19, 3), (19, 4), (19, 5)]),
            ("T", [(17, 0), (17, 1), (17, 2), (16, 1)]),
        ])
        steps = _plan_steps_on_screen(BoardState(), move)
        self.assertEqual([s.piece for s in steps], ["I", "T"])

    def test_no_steps_when_the_first_move_clears_a_line(self) -> None:
        from src.app import _plan_steps_on_screen
        from src.engine.board_state import BoardState

        board = BoardState()
        for c in range(6):
            board.grid[19][c] = "G"
        move = self._move("I", [(19, 6), (19, 7), (19, 8), (19, 9)], [("T", [(18, 0), (18, 1), (18, 2), (17, 1)])])
        self.assertEqual(_plan_steps_on_screen(board, move), [])

    def test_steps_stop_after_the_move_that_clears_a_line(self) -> None:
        from src.app import _plan_steps_on_screen
        from src.engine.board_state import BoardState

        board = BoardState()
        for c in range(6):
            board.grid[19][c] = "G"
        move = self._move("O", [(18, 8), (18, 9), (17, 8), (17, 9)], [
            ("I", [(19, 6), (19, 7), (19, 8), (19, 9)]),  # この手でラインが消える
            ("T", [(18, 0), (18, 1), (18, 2), (17, 1)]),  # 消去後の座標なので表示しない
        ])
        steps = _plan_steps_on_screen(board, move)
        self.assertEqual([s.piece for s in steps], ["I"])


class TestIsPlausibleBoardTransition(unittest.TestCase):
    def test_no_previous_board_is_always_plausible(self) -> None:
        candidate = _board_key_with_filled_count(5)
        self.assertTrue(_is_plausible_board_transition(None, candidate, width=BOARD_COLS))

    def test_filled_count_increasing_is_plausible(self) -> None:
        previous = _board_key_with_filled_count(5)
        candidate = _board_key_with_filled_count(9)
        self.assertTrue(_is_plausible_board_transition(previous, candidate, width=BOARD_COLS))

    def test_filled_count_unchanged_is_plausible(self) -> None:
        previous = _board_key_with_filled_count(5)
        self.assertTrue(_is_plausible_board_transition(previous, previous, width=BOARD_COLS))

    def test_decrease_by_a_multiple_of_width_is_plausible(self) -> None:
        # 1行(列数ぶん)がライン消去で丸ごと消えるのは正常。
        previous = _board_key_with_filled_count(15)
        candidate = _board_key_with_filled_count(5)
        self.assertTrue(_is_plausible_board_transition(previous, candidate, width=BOARD_COLS))

    def test_decrease_not_a_multiple_of_width_is_implausible(self) -> None:
        # 実機動画で確認された不具合の回帰テスト: T-Spinダブル等の光
        # エフェクト直後、まだ残っているはずの設置済みブロックが列数の
        # 倍数にならない中途半端な数だけ「空」に誤読されるフレームが
        # あった。ライン消去では説明できないこの種の減少は信用しない。
        previous = _board_key_with_filled_count(15)
        candidate = _board_key_with_filled_count(1)
        self.assertFalse(_is_plausible_board_transition(previous, candidate, width=BOARD_COLS))

    def test_whole_board_flash_is_implausible(self) -> None:
        # 【2026-09-11・6回目の実機録画】4列消しの閃光で盤面全体が白くなり、
        # 全マスがGARBAGEと読まれる。増加方向なので従来は素通りし、消去と
        # 同時にスポーンしたミノの要求がほぼ全面ブロックの盤面で行われた。
        previous = _board_key_with_filled_count(20)
        candidate = _board_key_with_filled_count(20 + 60)
        self.assertFalse(_is_plausible_board_transition(previous, candidate, width=BOARD_COLS))

    def test_large_increase_is_plausible_when_it_is_a_garbage_rise(self) -> None:
        previous = _board_key_with_filled_count(20)
        candidate = _board_key_with_filled_count(20 + 27)
        self.assertTrue(
            _is_plausible_board_transition(previous, candidate, width=BOARD_COLS, garbage_rise=3)
        )

    def test_line_clear_right_after_locking_a_piece_is_plausible(self) -> None:
        # 【残課題・2026-09-11実機ログ】基準値は2tick安定を経た値なので、
        # 置いた直後のミノ(4マス)が取り込まれる前にライン消去が起きると、
        # 減少量は「10 − 4 = 6」のように列数の倍数にならない。これを
        # 「あり得ない遷移」と誤判定して要求を見送っていたため、ライン
        # 消去のたびに次の提案が1.5秒の保険まで出なかった。
        previous = _board_key_with_filled_count(16)
        for piece_cells_in_cleared_row in range(1, 5):
            candidate = _board_key_with_filled_count(16 - (BOARD_COLS - piece_cells_in_cleared_row))
            self.assertTrue(
                _is_plausible_board_transition(previous, candidate, width=BOARD_COLS),
                piece_cells_in_cleared_row,
            )

    def test_decrease_larger_than_a_piece_can_explain_is_still_implausible(self) -> None:
        # 補正はミノ1個分(最大4マス)まで。それでは説明できない減少は従来どおり弾く。
        previous = _board_key_with_filled_count(15)
        candidate = _board_key_with_filled_count(15 - (BOARD_COLS - 5))
        self.assertFalse(_is_plausible_board_transition(previous, candidate, width=BOARD_COLS))


class TestConnectedComponent(unittest.TestCase):
    def test_finds_all_four_cells_of_a_piece(self) -> None:
        grid = _empty_grid()
        samples = _empty_samples()
        _place_piece_cells(grid, samples, "I", origin_row=0, origin_col=3, rotation=0)

        cells = {(0 + dr, 3 + dc) for dr, dc in PIECE_ROTATION_STATES["I"][0]}
        start_r, start_c = next(iter(cells))
        component = _connected_component(grid, start_r, start_c, row_limit=BOARD_ROWS)

        self.assertEqual(component, cells)


class TestBuildSettledBoard(unittest.TestCase):
    def test_excludes_rows_above_settled_top_row(self) -> None:
        grid = _empty_grid()
        grid[19][0] = "T"
        grid[19][1] = "T"
        grid[0][5] = "I"  # 操作中ミノ相当。settled boardには含まれないはず

        board = _build_settled_board(grid, BOARD_COLS, BOARD_ROWS)

        self.assertEqual(board.grid[19][0], "T")
        self.assertIsNone(board.grid[0][5])

    def test_detected_piece_cells_can_be_removed_without_losing_the_row(self) -> None:
        # 探索範囲と着地済み盤面が重なる設計になったため、重なった領域で
        # 検出した操作ミノは「行ごと切り落とす」のではなく「そのセルだけ」を
        # 取り除く必要がある。同じ行にある実在のブロックを巻き添えにしないこと。
        grid = _empty_grid()
        # 行19: 実在のブロック(列0〜2)と、同じ行にある操作ミノ(列5〜6)
        for c in range(0, 3):
            grid[19][c] = "GARBAGE"
        grid[19][5] = "O"
        grid[19][6] = "O"

        board = _build_settled_board(grid, BOARD_COLS, BOARD_ROWS, exclude_rows=19)
        for r, c in [(19, 5), (19, 6)]:
            board.grid[r][c] = None

        self.assertEqual(board.grid[19][0], "GARBAGE")
        self.assertEqual(board.grid[19][2], "GARBAGE")
        self.assertIsNone(board.grid[19][5])
        self.assertIsNone(board.grid[19][6])

    def test_exclude_rows_hides_a_bridged_piece_over_supported_columns(self) -> None:
        # 「支えの有無」判定でも、操作中ミノが積み上がった列の真上に
        # 浮いている場合は支えがあるように見えるため、着地済み盤面へ
        # 紛れ込みうる(この誤混入が「提示の暴れ」「盤面が高くなるほど
        # 提示が出なくなる」の主因だった)。recognize()がexclude_rowsに
        # 前回の信頼値を明示的に渡す仕組みは、その場合の対策として残る。
        grid = _empty_grid()
        grid[18][0] = "O"
        grid[18][1] = "O"
        grid[19][0] = "O"
        grid[19][1] = "O"
        for c in range(2, 6):
            grid[16][c] = "I"

        # 支えの無い列に浮いているIミノは着地済みとみなされないため、
        # exclude_rowsを省略しても盤面に混入しない。
        naive_board = _build_settled_board(grid, BOARD_COLS, BOARD_ROWS)
        self.assertIsNone(naive_board.grid[16][2])

        fixed_board = _build_settled_board(grid, BOARD_COLS, BOARD_ROWS, exclude_rows=18)
        for c in range(2, 6):
            self.assertIsNone(fixed_board.grid[16][c])
        self.assertEqual(fixed_board.grid[18][0], "O")


class TestDebounceCoversTheWholeBoard(unittest.TestCase):
    """デバウンスの範囲が盤面の範囲と一致していることの回帰テスト。

    盤面は包含的な上端(_settled_top_row)で切り出すのに、セル単位の2tick
    デバウンスは保守的な上端(_falling_piece_search_limit)以降にしか
    掛かっていなかった。その間の行は積みの上端という最もノイズが多い領域で、
    そこの一瞬の誤読がそのままAIへ渡り、既存ブロックと重なる提案(干渉)の
    原因になっていた。
    """

    def test_row_inside_the_board_is_debounced(self) -> None:
        # 行17に1マスだけ積まれている状況。盤面には含まれる(支えがあるため)。
        grid = _empty_grid()
        for c in range(0, 4):
            grid[19][c] = "O"
        grid[18][0] = "J"
        grid[18][1] = "J"
        grid[17][1] = "J"
        board_top = _settled_top_row(grid)
        self.assertEqual(board_top, 17)
        # 保守的な上限はこの行を含まない = 旧実装ではデバウンス対象外だった
        self.assertGreater(_falling_piece_search_limit(grid), board_top)

        confirmed = [row[:] for row in grid]
        # 次のtickで(17,1)が一瞬だけ空に誤読される
        noisy = [row[:] for row in grid]
        noisy[17][1] = None

        stabilized, _pending = _stabilize_settled_grid(noisy, board_top, confirmed, None)

        self.assertEqual(
            stabilized[17][1], "J", "盤面に含まれる行がデバウンスされていない"
        )


class TestStabilizeSettledGrid(unittest.TestCase):
    # 実機ログの回帰テスト: 既に着地して完全に静止しているはずの1マスの
    # 色が、操作中ミノの位置や着地したばかりかどうかに関係なく、
    # フレームごとにI→J→Iのように勝手に入れ替わる現象が確認された。
    # 盤面のセル色判定(classify_color)は毎フレーム独立してサンプリング
    # されるだけで、前後のフレームとの整合性を確認する仕組みがなかった
    # ことが原因。着地済み領域(exclude_rows以降)の各マスについて、
    # 2tick連続で同じ新しい色が確認できて初めて確定するようにする。

    def test_first_call_trusts_raw_grid_as_is(self) -> None:
        # 比較対象(前回の確定値)がない初回は、生の値をそのまま信頼するしかない。
        raw = _empty_grid()
        raw[19][0] = "I"
        confirmed, pending = _stabilize_settled_grid(raw, exclude_rows=18, previous_confirmed_grid=None, previous_pending_grid=None)
        self.assertEqual(confirmed[19][0], "I")
        self.assertTrue(all(cell is None for row in pending for cell in row))

    def test_single_frame_color_flip_is_suppressed(self) -> None:
        # 実機ログの回帰テスト: (19,2)がJ→Iに1回だけ変化した瞬間は、
        # まだ確定させず前回の色(J)を維持すべき。
        previous_confirmed = _empty_grid()
        previous_confirmed[19][2] = "J"
        raw = _empty_grid()
        raw[19][2] = "I"

        confirmed, pending = _stabilize_settled_grid(
            raw, exclude_rows=18, previous_confirmed_grid=previous_confirmed, previous_pending_grid=None
        )

        self.assertEqual(confirmed[19][2], "J")  # まだ前回の色のまま
        self.assertEqual(pending[19][2], ("I",))  # 次tickの確認用に候補として記録

    def test_new_block_is_adopted_without_waiting(self) -> None:
        # 実機の回帰テスト。着地したばかりのミノがデバウンスのせいで1tick
        # (約100ms)盤面に入らず、その同じtickで固定を検出してAIへ質問する
        # ため、「今置いたミノがまだ無い盤面」を渡していた。保存済み履歴では
        # 提案マスの24.6%が実際にはブロックの上にあり、その全件で読み取り
        # 自体は正しく占有と読めていた(=盤面が古いことが原因)。
        # ミノの着地やおじゃまの上昇でブロックが現れるのは正常な事象であり、
        # 待つ理由がない。
        previous_confirmed = _empty_grid()   # そのマスは空だった
        raw = _empty_grid()
        raw[19][2] = "T"                     # ミノが着地して現れた

        confirmed, pending = _stabilize_settled_grid(
            raw, exclude_rows=18, previous_confirmed_grid=previous_confirmed, previous_pending_grid=None
        )

        self.assertEqual(confirmed[19][2], "T", "着地したブロックが盤面に入っていない")
        self.assertIsNone(pending[19][2], "即座に採用したのに保留が残っている")

    def test_stacked_new_blocks_are_adopted_when_the_piece_rests_on_the_stack(self) -> None:
        # 置いたミノの上側のマスは、真下が同じミノ(生の値)なので支えありとして即採用される。
        previous_confirmed = _empty_grid()
        previous_confirmed[19][2] = "G"
        raw = _empty_grid()
        raw[19][2] = "G"
        for r in (15, 16, 17, 18):  # 縦置きのIがGの上に載った
            raw[r][2] = "I"

        confirmed, _pending = _stabilize_settled_grid(
            raw, exclude_rows=10, previous_confirmed_grid=previous_confirmed, previous_pending_grid=None
        )
        for r in (15, 16, 17, 18):
            self.assertEqual(confirmed[r][2], "I", f"載っているIの行{r}が採用されていない")

    def test_floating_new_block_waits_for_a_second_observation(self) -> None:
        # 【2026-09-11・4回目の実機ログ】光の粒(スパークル)が1フレームだけ
        # ブロックと読まれると、即採用で幻のブロックが入り、消えるまで2tick
        # 「空になる確定待ち」が続く。粒は動き続けるので確定待ちが途切れず、
        # スポーン時の要求が盤面信頼のタイムアウトまで止まっていた(66回)。
        # 真下が空いている(宙に浮いた)出現は即採用しないこと。
        previous_confirmed = _empty_grid()
        raw = _empty_grid()
        raw[12][7] = "UNKNOWN"  # 宙に浮いた1マス

        confirmed, pending = _stabilize_settled_grid(
            raw, exclude_rows=10, previous_confirmed_grid=previous_confirmed, previous_pending_grid=None
        )
        self.assertIsNone(confirmed[12][7], "宙に浮いた出現が即採用されている")
        self.assertEqual(pending[12][7], ("UNKNOWN",))

    def test_floating_multi_row_effect_is_not_adopted_as_a_block(self) -> None:
        # 【2026-09-11・6回目の実機ログ】「TETRIS」文字や閃光は数行にまたがる。
        # 生の値の真下を支えとみなすと、下の行が上の行の支えになって塊ごと
        # 即採用され、幻のブロックになった。床から確定済みマスを経て連なる
        # 出現だけを採用すること。
        previous_confirmed = _empty_grid()
        previous_confirmed[19][3] = "G"
        raw = _empty_grid()
        raw[19][3] = "G"
        raw[10][3] = "T"  # 宙に浮いた2行の塊
        raw[11][3] = "T"

        confirmed, pending = _stabilize_settled_grid(
            raw, exclude_rows=5, previous_confirmed_grid=previous_confirmed, previous_pending_grid=None
        )
        self.assertIsNone(confirmed[10][3], "浮いた塊の上段が即採用されている")
        self.assertIsNone(confirmed[11][3], "浮いた塊の下段が即採用されている")
        self.assertEqual(pending[10][3], ("T",))

    def test_overhanging_cells_of_a_locked_piece_are_adopted_with_the_piece(self) -> None:
        # 【2026-09-11・7回目の実機ログ(保存画像023)】置いたJの張り出した
        # マス(真下が空)が「支えなし」として2tick待たされ、その間にAIが
        # そこへ配置を提案して干渉した。床か確定済みマスに接する出現に
        # 連結した出現は、同じミノとしてまとめて即採用すること。
        previous_confirmed = _empty_grid()
        for c in range(10):
            previous_confirmed[19][c] = "G"
        raw = [row[:] for row in previous_confirmed]
        # J(北向き): (17,0) と (18,0),(18,1),(18,2)。下段3マスはGに接して
        # 支えあり、(17,0)はそれらに連結しているので一緒に採用される。
        for r, c in ((17, 0), (18, 0), (18, 1), (18, 2)):
            raw[r][c] = "J"

        confirmed, pending = _stabilize_settled_grid(
            raw, exclude_rows=10, previous_confirmed_grid=previous_confirmed, previous_pending_grid=None
        )
        for r, c in ((17, 0), (18, 0), (18, 1), (18, 2)):
            self.assertEqual(confirmed[r][c], "J", f"置いたJの({r},{c})が採用されていない")
            self.assertIsNone(pending[r][c])

    def test_overhang_over_empty_cell_is_adopted_via_connection(self) -> None:
        # S(北向き): (18,1),(18,2) と (19,0),(19,1)。(18,2)の真下(19,2)は空。
        previous_confirmed = _empty_grid()
        raw = _empty_grid()
        for r, c in ((18, 1), (18, 2), (19, 0), (19, 1)):
            raw[r][c] = "S"
        confirmed, _pending = _stabilize_settled_grid(
            raw, exclude_rows=10, previous_confirmed_grid=previous_confirmed, previous_pending_grid=None
        )
        self.assertEqual(confirmed[18][2], "S", "張り出したマスが採用されていない")

    def test_block_disappearing_needs_two_consecutive_observations(self) -> None:
        # 実機の回帰テスト。「保留なし」と「空マス」をどちらもNoneで表して
        # いたため、ブロックが空マスへ変わる誤読では
        # 「保留なし(None) == 観測値(None)」が成立し、2tick待たずに1tickで
        # 採用されていた。盤面に一瞬の穴が空き、そこへ重なる配置がAIから
        # 提案される「干渉」の直接原因になっていた。
        previous_confirmed = _empty_grid()
        previous_confirmed[19][2] = "J"
        raw = _empty_grid()  # (19,2)が空に誤読された

        confirmed, pending = _stabilize_settled_grid(
            raw, exclude_rows=18, previous_confirmed_grid=previous_confirmed, previous_pending_grid=None
        )

        self.assertEqual(confirmed[19][2], "J", "1tickの誤読で盤面に穴が空いている")
        self.assertEqual(pending[19][2], (None,))

        # 2tick連続で空が観測されたら、本当に消えたとみなして採用する。
        confirmed2, _ = _stabilize_settled_grid(
            raw, exclude_rows=18, previous_confirmed_grid=previous_confirmed, previous_pending_grid=pending
        )
        self.assertIsNone(confirmed2[19][2])

    def test_color_change_confirmed_twice_in_a_row_is_adopted(self) -> None:
        # 2回連続で同じ新しい色が観測されたら、本物の変化として確定する
        # (揺らぎを無視するあまり、本当の設置・消去まで無視してはいけない)。
        previous_confirmed = _empty_grid()
        previous_confirmed[19][2] = "J"
        # 保留値は1要素のタプルで持つ(「保留なし」のNoneと、空マスの保留を
        # 区別するため。区別しないと、ブロックが空マスへ変わる誤読が
        # 2tick待たずに1tickで採用されてしまう)。
        previous_pending = _empty_grid()
        previous_pending[19][2] = ("I",)
        raw = _empty_grid()
        raw[19][2] = "I"

        confirmed, pending = _stabilize_settled_grid(
            raw, exclude_rows=18, previous_confirmed_grid=previous_confirmed, previous_pending_grid=previous_pending
        )

        self.assertEqual(confirmed[19][2], "I")
        self.assertIsNone(pending[19][2])

    def test_rows_above_exclude_rows_are_never_stabilized(self) -> None:
        # exclude_rows未満の行(操作中ミノが存在しうる領域)は、ミノの移動に
        # 伴って毎tick変化するのが正常なので、安定化の対象から外すべき
        # (安定化してしまうと操作中ミノの追跡が壊れる)。
        previous_confirmed = _empty_grid()
        previous_confirmed[5][3] = "T"
        raw = _empty_grid()
        raw[5][3] = "L"  # 操作中ミノが1行動いた想定

        confirmed, _pending = _stabilize_settled_grid(
            raw, exclude_rows=18, previous_confirmed_grid=previous_confirmed, previous_pending_grid=None
        )

        self.assertEqual(confirmed[5][3], "L")  # 即座に生の値が採用される

    def test_unrelated_cells_are_unaffected(self) -> None:
        # あるマスで色の入れ替わりが起きても、他の変化していないマスの
        # 確定値には一切影響しないべき。
        previous_confirmed = _empty_grid()
        previous_confirmed[19][0] = "O"
        previous_confirmed[19][2] = "J"
        raw = _empty_grid()
        raw[19][0] = "O"
        raw[19][2] = "I"

        confirmed, _pending = _stabilize_settled_grid(
            raw, exclude_rows=18, previous_confirmed_grid=previous_confirmed, previous_pending_grid=None
        )

        self.assertEqual(confirmed[19][0], "O")
        self.assertEqual(confirmed[19][2], "J")


if __name__ == "__main__":
    unittest.main()
