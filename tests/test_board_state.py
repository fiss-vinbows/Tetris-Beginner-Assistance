"""board_state.pyのテスト。

is_placement_physically_validは、Cold Clear 2からの提案が実機動画で
「既に埋まっているマスに重なる」「支えがなく宙に浮いている」ように見える
瞬間が確認されたことを受けて追加した、提案の物理的妥当性を検証する安全網。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine.board_state import BoardState


class TestIsPlacementPhysicallyValid(unittest.TestCase):
    def test_empty_placement_is_invalid(self) -> None:
        board = BoardState()
        self.assertFalse(board.is_placement_physically_valid([]))

    def test_placement_resting_on_floor_is_valid(self) -> None:
        board = BoardState()
        # 最下段(row=height-1)に置くのは常に有効(床に支えられる)
        cells = [(19, 0), (19, 1), (19, 2), (19, 3)]
        self.assertTrue(board.is_placement_physically_valid(cells))

    def test_placement_resting_on_existing_blocks_is_valid(self) -> None:
        board = BoardState()
        board.grid[19][0] = "X"
        board.grid[19][1] = "X"
        # 既存ブロックの真上に置く(Oミノ相当)のは有効
        cells = [(18, 0), (18, 1), (19, 0), (19, 1)]
        # (19,0),(19,1)は既に埋まっているので、この配置自体は無効
        # (別のテストケースとして、埋まっているマスへの重なりを検証する)
        self.assertFalse(board.is_placement_physically_valid(cells))

    def test_placement_floating_above_existing_blocks_is_invalid(self) -> None:
        # 実機動画で確認された不具合の再現: 既存ブロックの上に1マス分の
        # 隙間を空けて浮いている配置は物理的にありえない。
        board = BoardState()
        board.grid[19][0] = "X"
        board.grid[19][1] = "X"
        # (18,0),(18,1)は空だが、その下(19,0),(19,1)は既に埋まっているので
        # 支えられている。しかしさらに1段上(17,0),(17,1)は、真下(18,0),(18,1)
        # が空なので宙に浮いている。
        cells = [(17, 0), (17, 1), (16, 0), (16, 1)]
        self.assertFalse(board.is_placement_physically_valid(cells))

    def test_placement_correctly_stacked_on_existing_blocks_is_valid(self) -> None:
        board = BoardState()
        board.grid[19][0] = "X"
        board.grid[19][1] = "X"
        # 既存ブロックのすぐ上(18行目)に積む配置は有効。
        cells = [(18, 0), (18, 1), (17, 0), (17, 1)]
        self.assertTrue(board.is_placement_physically_valid(cells))

    def test_placement_creating_a_hole_under_one_column_is_valid(self) -> None:
        # 実機で確認された重大な不具合の回帰テスト: テトリスのミノは剛体と
        # して落下するため、「いずれか1列でも真下が支えられていれば、ミノ
        # 全体がそこで静止する」のが正しい物理法則。他の列の下に空洞（穴）
        # ができるのは通常のプレイでも普通に起こる正常な配置であり、
        # 無効ではない。以前は「全セルが個別に支えられている」ことを
        # 誤って要求しており、この種の(実戦でごく普通に起こる)配置まで
        # 無効判定してしまい、「提案が全く来ない」という致命的な不具合に
        # つながっていた。
        board = BoardState()
        # 列1は行18から埋まっている(高さがある)。列0は完全に空(床まで空洞)。
        board.grid[18][1] = "X"
        board.grid[19][1] = "X"
        # Oミノを列0,1の行16,17に配置(列1の高さに合わせて止まった状態、
        # 列0の下(行18,19)には穴ができる)。
        cells = [(16, 0), (16, 1), (17, 0), (17, 1)]
        self.assertTrue(board.is_placement_physically_valid(cells))

    def test_placement_overlapping_existing_block_is_invalid(self) -> None:
        board = BoardState()
        board.grid[19][0] = "X"
        cells = [(19, 0), (19, 1), (19, 2), (19, 3)]
        self.assertFalse(board.is_placement_physically_valid(cells))

    def test_placement_out_of_bounds_is_invalid(self) -> None:
        board = BoardState()
        cells = [(19, 9), (19, 10), (19, 11), (19, 12)]
        self.assertFalse(board.is_placement_physically_valid(cells))

    def test_i_piece_standing_vertically_supports_itself(self) -> None:
        # Iミノを縦置きした場合、上の3マスは「同じ配置内の下のマス」に
        # 支えられているので有効(自己支持)。
        board = BoardState()
        cells = [(16, 0), (17, 0), (18, 0), (19, 0)]
        self.assertTrue(board.is_placement_physically_valid(cells))


if __name__ == "__main__":
    unittest.main()
