"""教育モードのルール(src.education.rules)の単体テスト。人工的な盤面・配列で確認する。"""

from __future__ import annotations

import unittest

from src.education.rules import COLS, HIDDEN_ROWS, NEXT_VISIBLE, ROWS, GameState, PieceSequence, piece_cells


def _fill(state: GameState, cells: set[tuple[int, int]], piece: str = "X") -> None:
    for r, c in cells:
        state.board[r][c] = piece


def _row(r: int, cols: range) -> set[tuple[int, int]]:
    return {(r, c) for c in cols}


class TestPieceSequence(unittest.TestCase):
    def test_same_seed_gives_same_sequence_and_each_bag_has_all_seven(self) -> None:
        a = PieceSequence(123)
        b = PieceSequence(123)
        first = [a.peek(i) for i in range(21)]
        self.assertEqual(first, [b.peek(i) for i in range(21)])
        for bag in (first[0:7], first[7:14], first[14:21]):
            self.assertEqual(sorted(bag), sorted("IOTSZJL"), "袋に7種類が1回ずつ入っていない")

    def test_different_seed_gives_different_sequence(self) -> None:
        self.assertNotEqual([PieceSequence(1).peek(i) for i in range(14)], [PieceSequence(2).peek(i) for i in range(14)])


class TestGameStateBasics(unittest.TestCase):
    def test_visible_next_is_exactly_five(self) -> None:
        state = GameState.new(7)
        self.assertEqual(len(state.visible_next()), NEXT_VISIBLE)
        # 操作ミノは配列の先頭、NEXT5はその続き
        self.assertEqual(state.current, state.sequence.peek(0))
        self.assertEqual(state.visible_next(), tuple(state.sequence.peek(i) for i in range(1, 6)))

    def test_no_auto_lock_after_soft_drop(self) -> None:
        # ソフトドロップで接地しても固定されず、移動・回転を続けられる
        state = GameState.new(7)
        state.current = "T"
        row_before = state.row
        self.assertTrue(state.soft_drop())
        self.assertEqual(state.row, row_before + 1, "ソフトドロップは1マスずつ")
        while state.soft_drop():
            pass
        self.assertTrue(state.is_grounded())
        board_before = [list(r) for r in state.board]
        self.assertTrue(state.move_left())
        self.assertTrue(state.rotate_cw() or True)  # 回転できるかは形状次第だが固定はしない
        self.assertEqual(state.board, board_before, "接地後に固定されている")
        self.assertEqual(state.history, [])

    def test_hard_drop_locks_clears_lines_and_spawns_next(self) -> None:
        state = GameState.new(7)
        state.current = "I"
        # 最下段の左6マスを埋めておき、Iを右側(列6〜9)へ横向きで落とす
        _fill(state, _row(ROWS - 1, range(0, 6)))
        state.col = 6
        expected_next = state.visible_next()[0]
        state.hard_drop()
        self.assertEqual(state.lines_cleared, 1)
        self.assertTrue(all(cell is None for cell in state.board[ROWS - 1]), "揃った行が消えていない")
        self.assertEqual(state.current, expected_next, "NEXTの先頭が操作ミノになっていない")
        self.assertEqual(len(state.history), 1)

    def test_hold_once_per_turn_and_empty_hold_takes_from_next(self) -> None:
        state = GameState.new(7)
        first = state.current
        next_head = state.visible_next()[0]
        self.assertTrue(state.use_hold())
        self.assertEqual(state.hold, first)
        self.assertEqual(state.current, next_head, "空のHOLDへ入れたら次のミノが出る")
        self.assertFalse(state.use_hold(), "同じ手番で2回HOLDできてしまう")
        state.hard_drop()
        current_after = state.current
        self.assertTrue(state.use_hold(), "次の手番でHOLDできない")
        self.assertEqual(state.current, first, "HOLDにあったミノが出てこない")
        self.assertEqual(state.hold, current_after)

    def test_undo_restores_board_hold_and_sequence(self) -> None:
        state = GameState.new(7)
        start_board = [list(r) for r in state.board]
        start_current, start_index = state.current, state.sequence_index
        state.use_hold()
        state.hard_drop()
        state.hard_drop()
        self.assertEqual(len(state.history), 2)
        self.assertTrue(state.undo())
        self.assertTrue(state.undo())
        self.assertEqual(state.board, start_board)
        self.assertEqual(state.current, start_current)
        self.assertEqual(state.sequence_index, start_index)
        self.assertIsNone(state.hold)
        self.assertFalse(state.undo(), "開始状態より前に戻れてしまう")

    def test_reset_same_sequence_reproduces_future_pieces(self) -> None:
        state = GameState.new(99)
        far = [state.sequence.peek(i) for i in range(30)]  # 未表示の将来分を含む
        for _ in range(5):
            state.hard_drop()
        again = state.reset_same_sequence()
        self.assertEqual([again.sequence.peek(i) for i in range(30)], far)
        self.assertEqual(again.sequence_index, 1)
        self.assertTrue(all(cell is None for row in again.board for cell in row))

    def test_reset_new_sequence_changes_pieces(self) -> None:
        state = GameState.new(99)
        other = state.reset_new_sequence(seed=100)
        self.assertNotEqual([state.sequence.peek(i) for i in range(14)], [other.sequence.peek(i) for i in range(14)])

    def test_game_over_when_spawn_is_blocked(self) -> None:
        # 出現位置の直下まで積み上がっている: 今のミノは出現位置で固定され、次が出せない
        state = GameState.new(7)
        _fill(state, {(r, c) for r in range(2, ROWS) for c in range(COLS - 1)})  # 各行に穴を残す(揃って消えないように)
        state.hard_drop()
        self.assertTrue(state.game_over)

    def test_visible_board_excludes_hidden_rows(self) -> None:
        from src.education.rules import visible_board

        state = GameState.new(7)
        self.assertEqual(len(visible_board(state)), ROWS - HIDDEN_ROWS)


class TestGarbage(unittest.TestCase):
    def test_garbage_rises_with_one_hole_per_row_and_can_be_undone(self) -> None:
        import random

        for seed in range(20):
            state = GameState.new(3)
            _fill(state, {(ROWS - 1, 0)})
            state.turn_start = state._snapshot()  # 盤面を手で置いたので手番開始時点を取り直す
            before = [list(r) for r in state.board]
            self.assertTrue(state.add_garbage(3, random.Random(seed)))
            rows = state.board[ROWS - 3:]
            for row in rows:
                self.assertEqual(row.count(None), 1, "おじゃま1段に穴が1つでない")
                self.assertTrue(all(c in (None, "GARBAGE") for c in row))
            self.assertEqual(state.board[ROWS - 4][0], "X", "既存のブロックが3段上がっていない")
            self.assertTrue(state.undo())
            self.assertEqual(state.board, before, "一手戻すでせり上げ前に戻らない")

    def test_garbage_holes_are_sometimes_aligned_and_sometimes_scattered(self) -> None:
        import random

        kinds = set()
        for seed in range(40):
            state = GameState.new(3)
            state.add_garbage(4, random.Random(seed))
            holes = [row.index(None) for row in state.board[ROWS - 4:]]
            kinds.add("直列" if len(set(holes)) == 1 else "バラ")
        self.assertEqual(kinds, {"直列", "バラ"})

    def test_garbage_count_is_limited_to_one_to_five(self) -> None:
        state = GameState.new(3)
        self.assertFalse(state.add_garbage(0))
        self.assertFalse(state.add_garbage(6))

    def test_garbage_pushes_the_current_piece_up_and_can_top_out(self) -> None:
        state = GameState.new(3)
        while state.soft_drop():
            pass
        row = state.row
        state.add_garbage(2)
        self.assertEqual(state.row, row - 2, "操作中のミノが押し上げられていない")
        self.assertFalse(state.game_over)
        state2 = GameState.new(3)
        _fill(state2, {(1, 0)})
        state2.add_garbage(2)
        self.assertTrue(state2.game_over, "上端からはみ出したのに積み上がりにならない")


class TestSRS(unittest.TestCase):
    """通常SRSの回転と補正(キック)の代表例。"""

    def _state_with(self, piece: str, orient: int = 0, row: int = 0, col: int = 3) -> GameState:
        state = GameState.new(1)
        state.current, state.orient, state.row, state.col = piece, orient, row, col
        state.hold_used = False
        return state

    def test_basic_rotation_shapes(self) -> None:
        # 右回転4回で元に戻り、各状態は4マス・盤面内
        for piece in "IOTSZJL":
            state = self._state_with(piece, row=5, col=3)
            start = state.current_cells()
            for _ in range(4):
                self.assertTrue(state.rotate_cw(), f"{piece}が空中で回転できない")
            self.assertEqual(state.current_cells(), start, f"{piece}の右回転4回が元に戻らない")

    def test_wall_kick_at_left_wall(self) -> None:
        # 左壁に接した縦向きのTを回すと、通常SRSの補正(+1)で1列右へずれて回転する
        state = self._state_with("T", orient=1, row=5, col=-1)  # 箱の左端が壁の外(縦T: 列0〜1を占有)
        self.assertEqual({c for _r, c in state.current_cells()}, {0, 1})
        self.assertTrue(state.rotate_cw(), "壁際で補正されずに回転が失敗した")
        self.assertEqual(state.orient, 2)
        self.assertGreaterEqual(min(c for _r, c in state.current_cells()), 0)
        self.assertEqual(state.last_rotation_kick, 1, "補正の1番目(+1,0)が使われていない")

    def test_i_piece_kick_at_right_wall(self) -> None:
        # 右壁に接した縦向きIを回転 → 横向きは壁の外へ出るので補正で左へずれる
        state = self._state_with("I", orient=1, row=5, col=7)  # 縦I: 列9
        self.assertEqual({c for _r, c in state.current_cells()}, {9})
        self.assertTrue(state.rotate_cw())
        self.assertEqual(state.orient, 2)
        self.assertTrue(all(0 <= c < COLS for _r, c in state.current_cells()))
        self.assertIsNotNone(state.last_rotation_kick)

    def test_t_spin_double_slot_is_reachable_by_rotation(self) -> None:
        # TSDの典型: 縦向きのTを2列幅の入口(列3〜4)へ落とし、右回転すると
        # 通常SRSの補正(+1,-1)=3番目で張り出しの下の3列幅の穴へ入る。
        #   行21: ####.#####  (穴=(21,4))
        #   行20: ###...####  (Tの横3マスが入る)
        #   行19: ###..#####  (張り出し=(19,5))
        bottom = ROWS - 1
        state = self._state_with("T", orient=1, row=0, col=2)  # 縦T(軸が列3)
        _fill(state, _row(bottom, range(0, 4)) | _row(bottom, range(5, 10)))
        _fill(state, _row(bottom - 1, range(0, 3)) | _row(bottom - 1, range(6, 10)))
        _fill(state, _row(bottom - 2, range(0, 3)) | _row(bottom - 2, range(5, 10)))
        while state.soft_drop():
            pass
        self.assertEqual(state.row, bottom - 3, "縦Tが入口の底まで落ちていない")
        self.assertTrue(state.rotate_cw(), "TSDの穴へ回転入れできない")
        self.assertEqual(
            set(state.current_cells()),
            {(bottom - 1, 3), (bottom - 1, 4), (bottom - 1, 5), (bottom, 4)},
            "Tが穴の位置(下向き)に入っていない",
        )
        self.assertEqual(state.last_rotation_kick, 2, "通常SRSの3番目の補正が使われていない")
        state.hard_drop()
        self.assertEqual(state.lines_cleared, 2, "TSDで2行消えていない")

    def test_rotation_fails_when_all_kicks_collide(self) -> None:
        state = self._state_with("I", orient=0, row=5, col=3)
        # Iの横向きの周囲を完全に囲む(上下の行を埋める)
        _fill(state, _row(4, range(COLS)) | _row(7, range(COLS)) | _row(3, range(COLS)) | _row(8, range(COLS)))
        _fill(state, _row(5, range(0, 3)) | _row(5, range(7, 10)) | _row(6, range(COLS)))
        self.assertFalse(state.rotate_cw())
        self.assertEqual(state.orient, 0)

    def test_piece_cells_offsets(self) -> None:
        self.assertEqual(piece_cells("O", 0, 0, 3), ((0, 4), (0, 5), (1, 4), (1, 5)))


if __name__ == "__main__":
    unittest.main()


class TestClearNames(unittest.TestCase):
    """消した役の名前・BtoB・RENの判定。"""

    def _tsd_state(self) -> GameState:
        bottom = ROWS - 1
        state = GameState.new(1)
        state.current, state.orient, state.row, state.col = "T", 1, 0, 2
        _fill(state, _row(bottom, range(0, 4)) | _row(bottom, range(5, 10)))
        _fill(state, _row(bottom - 1, range(0, 3)) | _row(bottom - 1, range(6, 10)))
        _fill(state, _row(bottom - 2, range(0, 3)) | _row(bottom - 2, range(5, 10)))
        while state.soft_drop():
            pass
        return state

    def test_tsd_is_named_and_starts_back_to_back(self) -> None:
        state = self._tsd_state()
        self.assertTrue(state.rotate_cw())
        state.hard_drop()
        self.assertEqual(state.last_clear, "TSD(Tスピンダブル)")
        self.assertEqual(state.back_to_back, 0, "1回目はBtoBではない")

    def test_same_drop_without_rotation_is_not_a_t_spin(self) -> None:
        # 回転せずに落として行を消しても、Tスピンではなく通常のシングル
        state = GameState.new(1)
        state.current = "T"
        _fill(state, _row(ROWS - 1, range(0, 3)) | _row(ROWS - 1, range(6, 10)))
        state.hard_drop()
        self.assertEqual(state.last_clear, "シングル")

    def test_tetris_then_tetris_is_back_to_back_and_single_breaks_it(self) -> None:
        state = GameState.new(1)
        for _ in range(2):
            state.current, state.orient, state.row, state.col = "I", 1, 0, 7  # 縦I: 列9
            _fill(state, {(r, c) for r in range(ROWS - 4, ROWS) for c in range(9)})
            state.hard_drop()
            self.assertEqual(state.last_clear, "テトリス + パーフェクトクリア")
        self.assertEqual(state.back_to_back, 1, "テトリス2連続でBtoB×1になっていない")
        self.assertEqual(state.combo, 1, "REN数が数えられていない")
        state.current, state.orient, state.row, state.col = "I", 0, 0, 6
        _fill(state, _row(ROWS - 1, range(0, 6)) | {(ROWS - 2, 0)})
        state.hard_drop()
        self.assertEqual(state.last_clear, "シングル")
        self.assertEqual(state.back_to_back, -1, "シングルでBtoBが途切れていない")
        state.hard_drop()  # 消さない固定
        self.assertEqual(state.combo, -1, "消さなかったのにRENが続いている")

    def test_undo_restores_back_to_back_and_last_clear(self) -> None:
        state = self._tsd_state()
        state.rotate_cw()
        state.turn_start = state._snapshot()
        state.hard_drop()
        state.undo()
        self.assertIsNone(state.last_clear)
        self.assertEqual(state.back_to_back, -1)
