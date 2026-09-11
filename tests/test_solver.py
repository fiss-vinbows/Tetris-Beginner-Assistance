"""思考ルーチン（evaluator・solver）だけを画像認識から切り離して検証するテスト。

画像認識（盤面キャプチャ・色/形状判定）と思考ルーチンのどちらに問題があるかを
切り分けるため、正解が自明な局面をBoardStateとして直接組み立て、
find_best_moveが妥当な手を選べているかを検証する。

これらのテストが全て通れば、実機で「最善手がおかしい」と感じた場合の原因は
思考ルーチンではなく、画像認識（盤面の読み取りが実際の画面とズレている）側を
疑うべき、という切り分けができる。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine.board_state import BoardState
from src.engine.solver import find_best_move


def make_board(column_defs: dict[int, list[int]], width: int = 10, height: int = 20) -> BoardState:
    """列ごとに「下から何段目が埋まっているか」を指定して盤面を組み立てる。

    column_defs = {列番号: [下から数えた行インデックスのリスト]}
    指定しなかった列は完全に空として扱う。
    """
    board = BoardState(width=width, height=height)
    for col, rows_from_bottom in column_defs.items():
        for r in rows_from_bottom:
            board.grid[height - 1 - r][col] = "X"
    return board


def landed_columns(best) -> set[int]:
    return {c for _r, c in best.landing_cells}


class TestWellFilling(unittest.TestCase):
    """深い井戸（Iミノ用の縦穴）が1箇所だけある盤面では、Iミノをそこに
    縦置きしてライン消去するのが明確な正解になる。"""

    def test_single_column_well_is_filled_by_vertical_I(self):
        # 列5だけ完全に空(深さ4)、他の9列は高さ4で埋まっている(穴なし)
        column_defs = {c: [0, 1, 2, 3] for c in range(10) if c != 5}
        board = make_board(column_defs)

        best = find_best_move(board, current_piece="I", hold_piece=None, next_queue=["O", "T", "L"])

        self.assertIsNotNone(best)
        self.assertEqual(best.piece, "I")
        self.assertFalse(best.use_hold)
        self.assertEqual(landed_columns(best), {5}, "Iミノは深さ4の井戸(列5)に縦置きされるべき")


class TestLineClearPreference(unittest.TestCase):
    """ライン消去できる手がある場合はそれを選ぶべき。"""

    def test_prefers_clearing_a_line_over_stacking_elsewhere(self):
        # 列0-8が高さ1で埋まっている(穴なし)。列9だけ空。
        # Iミノを横向きで置いても列9は埋まらないが、Jミノ(縦棒+横1)なら
        # 列9に縦置き部分をはめ込みライン消去できる。
        column_defs = {c: [0] for c in range(9)}
        board = make_board(column_defs)

        best = find_best_move(board, current_piece="J", hold_piece=None, next_queue=["O", "T", "L"])

        self.assertIsNotNone(best)
        # J字を回転させて列9に落とすと1ライン消去できるはず
        result_board = board.place_piece(best.piece, best.rotation, best.origin_row, best.origin_col)
        _cleared, lines = result_board.clear_lines()
        self.assertGreaterEqual(lines, 1, "ライン消去できる手が存在するのに選ばれていない")


class TestHoleAvoidance(unittest.TestCase):
    """段差のある盤面にOミノを置く時、穴を作らない置き方がある場合はそちらを選ぶべき。"""

    def test_avoids_creating_a_hole_when_flat_spot_exists(self):
        # 列0,1は高さ2(平ら)。列2は高さ0。列3以降は高さ3(段差)。
        # Oミノを列0-1(平らな場所)に置けば穴ゼロ。列2-3等の段差がある場所に
        # 置くと必ず穴ができる。
        column_defs = {0: [0, 1], 1: [0, 1]}
        for c in range(3, 10):
            column_defs[c] = [0, 1, 2]
        board = make_board(column_defs)

        best = find_best_move(board, current_piece="O", hold_piece=None, next_queue=["T", "L", "S"])

        self.assertIsNotNone(best)
        placed = board.place_piece(best.piece, best.rotation, best.origin_row, best.origin_col)
        result_board, _lines = placed.clear_lines()
        self.assertEqual(
            result_board.count_holes(), 0,
            f"平らな置き場所があるのに穴を作る手を選んでしまった: landing={best.landing_cells}",
        )


class TestHoldNotOverused(unittest.TestCase):
    """ホールドしなくても十分な手がある単純な局面では、ホールドを提案しないべき。"""

    def test_empty_board_does_not_hold(self):
        board = BoardState()
        best = find_best_move(board, current_piece="I", hold_piece=None, next_queue=["J", "O", "S", "L", "T"])

        self.assertIsNotNone(best)
        self.assertFalse(best.use_hold, "空の盤面でホールドする理由はないはず")


class TestReproducedFieldCase(unittest.TestCase):
    """2026-09-04の実機動画で「最善手がおかしい」と指摘された局面の簡略再現。

    列3,4,5が完全に空、列2に浮きブロックの下の穴が1つある変則的な地形。
    Iミノは、少なくとも新たな穴を増やさない置き方を選ぶべき。
    """

    def test_does_not_add_new_holes_on_irregular_field(self):
        column_defs = {
            0: [0, 1, 2, 3],
            1: [0, 1, 2, 3],
            2: [0, 2, 3],  # 1段目(下から2番目)が穴
            6: [0],
            7: [0, 1, 2, 3],
            8: [0, 1, 2, 3],
            9: [0, 1, 2],
        }
        board = make_board(column_defs)
        holes_before = board.count_holes()

        best = find_best_move(board, current_piece="I", hold_piece="I", next_queue=["L", "O", "T", "S", "Z"])

        self.assertIsNotNone(best)
        result_board = board.place_piece(best.piece, best.rotation, best.origin_row, best.origin_col)
        cleared_board, _lines = result_board.clear_lines()
        self.assertLessEqual(
            cleared_board.count_holes(), holes_before,
            f"既存の穴({holes_before}個)より穴を増やす手を選んでしまった: landing={best.landing_cells}",
        )


if __name__ == "__main__":
    unittest.main()
