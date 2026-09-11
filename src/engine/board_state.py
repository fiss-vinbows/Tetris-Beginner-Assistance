"""テトリス盤面の論理表現（衝突判定・設置・ライン消去）"""

from __future__ import annotations

from dataclasses import dataclass, field

from .piece_defs import PIECE_ROTATION_STATES

BOARD_WIDTH = 10
BOARD_HEIGHT = 20


@dataclass
class BoardState:
    width: int = BOARD_WIDTH
    height: int = BOARD_HEIGHT
    # grid[row][col] = ミノ種類名 or None（空）。row=0が最上段。
    grid: list[list[str | None]] = field(default_factory=lambda: None)

    def __post_init__(self) -> None:
        if self.grid is None:
            self.grid = [[None] * self.width for _ in range(self.height)]

    def clone(self) -> "BoardState":
        return BoardState(
            width=self.width,
            height=self.height,
            grid=[row[:] for row in self.grid],
        )

    def is_valid_position(self, piece: str, rotation: int, origin_row: int, origin_col: int) -> bool:
        shape = PIECE_ROTATION_STATES[piece][rotation % 4]
        for dr, dc in shape:
            r, c = origin_row + dr, origin_col + dc
            if c < 0 or c >= self.width or r >= self.height:
                return False
            if r >= 0 and self.grid[r][c] is not None:
                return False
        return True

    def hard_drop_row(self, piece: str, rotation: int, origin_col: int) -> int | None:
        """指定の回転・列でハードドロップした際の最終origin_rowを返す（設置不可ならNone）"""
        test_row = 0
        if not self.is_valid_position(piece, rotation, test_row, origin_col):
            return None
        while self.is_valid_position(piece, rotation, test_row + 1, origin_col):
            test_row += 1
        return test_row

    def place_piece(self, piece: str, rotation: int, origin_row: int, origin_col: int) -> "BoardState":
        """新しい盤面（コピー）にミノを設置して返す"""
        new_board = self.clone()
        shape = PIECE_ROTATION_STATES[piece][rotation % 4]
        for dr, dc in shape:
            r, c = origin_row + dr, origin_col + dc
            if 0 <= r < self.height and 0 <= c < self.width:
                new_board.grid[r][c] = piece
        return new_board

    def clear_lines(self) -> tuple["BoardState", int]:
        """揃った行を消去し、(新しい盤面, 消去行数) を返す"""
        remaining_rows = [row for row in self.grid if any(cell is None for cell in row)]
        cleared = self.height - len(remaining_rows)
        new_rows = [[None] * self.width for _ in range(cleared)] + remaining_rows
        new_board = self.clone()
        new_board.grid = new_rows
        return new_board, cleared

    def row_transitions(self) -> int:
        """各行内で「埋 -> 空」または「空 -> 埋」に切り替わる回数の合計。

        Dellacherieのアルゴリズムで採用されている特徴量の一つ。
        盤面の壁も「埋まっている」とみなして数えるため、行の両端も
        遷移としてカウントされる（壁際で凸凹しているほど値が増える）。
        """
        total = 0
        for row in self.grid:
            prev = True  # 左の壁は「埋まっている」扱い
            for cell in row:
                filled = cell is not None
                if filled != prev:
                    total += 1
                prev = filled
            if not prev:  # 右の壁も「埋まっている」扱い
                total += 1
        return total

    def column_transitions(self) -> int:
        """各列内で「埋 -> 空」または「空 -> 埋」に切り替わる回数の合計。

        row_transitionsの列版。床（盤面の一番下）は「埋まっている」扱い。
        """
        total = 0
        for c in range(self.width):
            prev = False  # 天井の上は「空いている」扱い
            for r in range(self.height):
                filled = self.grid[r][c] is not None
                if filled != prev:
                    total += 1
                prev = filled
            if not prev:  # 床は「埋まっている」扱い
                total += 1
        return total

    def column_heights(self) -> list[int]:
        heights = []
        for c in range(self.width):
            h = 0
            for r in range(self.height):
                if self.grid[r][c] is not None:
                    h = self.height - r
                    break
            heights.append(h)
        return heights

    def count_holes(self) -> int:
        """各列で「上にブロックがあるのに空いているマス」の数を数える"""
        holes = 0
        for c in range(self.width):
            block_found = False
            for r in range(self.height):
                if self.grid[r][c] is not None:
                    block_found = True
                elif block_found:
                    holes += 1
        return holes

    def is_placement_physically_valid(self, cells: list[tuple[int, int]]) -> bool:
        """指定されたセル集合が、現在の盤面上で物理的に置ける配置かを判定する。

        Cold Clear 2から返ってきた提案(landing_cells)を、実機の動画で
        「着地済みブロックとの間に隙間を空けて宙に浮いている」ように見える
        瞬間や、既に別のブロックで埋まっているマスに重なって見える瞬間が
        確認された。原因（盤面認識のズレ、座標変換の誤り等）がどこにあるか
        を問わず、少なくとも「物理的にありえない提案」を弾く安全網として、
        呼び出し側(AssistWorker)でこの判定を使う。

        条件:
        1. 全セルが盤面の範囲内にあり、かつ現在空いている(None)こと
        2. ミノは剛体として落下するため、「いずれか1列でも真下が支え
           られていれば、ミノ全体がそこで静止する」のがテトリスの
           物理法則である。他の列の下に空洞（穴）ができるのは通常の
           プレイでも普通に起こる正常な配置であり、無効ではない。
           そのため「全セルが個別に支えられている」ことまでは要求せず、
           「配置内の各列の最下端セルのうち、少なくとも1つが支えられて
           いる（真下が盤面の最下段または既存ブロック）」ことだけを見る。
           （以前はセル単位で全支持を要求しており、穴を作る通常の配置
           まで誤って無効判定してしまう重大なバグがあった）
        """
        if not cells:
            return False
        for r, c in cells:
            if r < 0 or r >= self.height or c < 0 or c >= self.width:
                return False
            if self.grid[r][c] is not None:
                return False

        bottom_per_col: dict[int, int] = {}
        for r, c in cells:
            if c not in bottom_per_col or r > bottom_per_col[c]:
                bottom_per_col[c] = r

        return any(
            r + 1 >= self.height or self.grid[r + 1][c] is not None
            for c, r in bottom_per_col.items()
        )
