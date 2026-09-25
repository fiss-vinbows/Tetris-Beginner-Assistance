"""教育モードの追加5機能(2026-09-24)のテスト。

盤面エディタ・1〜3巡目のツモ順設定・定跡への合流復帰・候補の循環切替と難度(◎○△)・
スクリーンショット。画面は表示せずoffscreenで動かす。CC2は偽物で置き換える。
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

from src.education.advisor import AI_ID, Advisor, candidate_templates, rejoin_form  # noqa: E402
from src.education.rules import COLS, GARBAGE, HIDDEN_ROWS, PIECES, ROWS, GameState, PieceSequence  # noqa: E402
from src.education.window import BoardDraft, PracticeWindow, move_in_bag, stroke_cells  # noqa: E402
from src.engine.openers import known_sequence  # noqa: E402
from src.engine.srs_reach import difficulty_mark, find_path, find_path_min_soft, soft_drop_sections  # noqa: E402
from tests.test_education_advisor import FakeEngine, _state_with_sequence  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

BAGS = ("TIOSZJL", "LJZSOIT", "IJLOSTZ")


def _empty_board() -> list[list[str | None]]:
    return [[None] * COLS for _ in range(ROWS)]


def _place(state: GameState, piece: str, cells22) -> None:
    """操作ミノ(piece)を手順どおりに動かしてcells22へ置く。"""
    assert state.current == piece
    ops = {"←": state.move_left, "→": state.move_right, "左回転": state.rotate_ccw, "右回転": state.rotate_cw, "↓": state.soft_drop}
    path = find_path(state, piece, tuple(cells22))
    assert path is not None
    for step in path:
        if step == "ハードドロップ":
            continue
        name, _, times = step.partition("×")
        for _ in range(int(times or 1)):
            assert ops[name]()
    state.hard_drop()


class TestConfiguredSequence(unittest.TestCase):
    def test_first_three_bags_are_replaced_and_later_bags_match_the_seed(self) -> None:
        original = PieceSequence(42)
        configured = PieceSequence(42, BAGS)
        self.assertEqual("".join(configured.peek(i) for i in range(21)), "".join(BAGS))
        self.assertEqual([configured.peek(i) for i in range(21, 70)], [original.peek(i) for i in range(21, 70)])

    def test_no_bags_is_the_same_as_before(self) -> None:
        self.assertEqual([PieceSequence(7, None).peek(i) for i in range(30)], [PieceSequence(7).peek(i) for i in range(30)])
        seq = PieceSequence(7)
        self.assertEqual("".join("".join(b) for b in seq.seed_bags()), "".join(seq.peek(i) for i in range(21)))

    def test_invalid_bags_are_rejected(self) -> None:
        for bags in (BAGS[:2], ("TIOSZJJ", *BAGS[1:]), ("TIOSZJ", *BAGS[1:])):
            with self.assertRaises(ValueError):
                PieceSequence(1, bags)
        with self.assertRaises(ValueError):
            PieceSequence(1).peek(-1)


class TestStartBoard(unittest.TestCase):
    def _board(self) -> list[list[str | None]]:
        board = _empty_board()
        for c in range(COLS - 1):
            board[ROWS - 1][c] = GARBAGE
        board[ROWS - 2][0] = "T"
        return board

    def test_reset_same_reproduces_edited_board_and_bags(self) -> None:
        state = GameState.new(5, BAGS, self._board())
        self.assertEqual(state.current, "T")
        self.assertEqual(state.visible_next(), tuple("IOSZJ"))
        start_board = [list(row) for row in state.board]
        state.hard_drop()
        state.use_hold()
        again = state.reset_same_sequence()
        self.assertEqual(again.board, start_board)
        self.assertEqual((again.current, again.hold, again.sequence_index, again.history), ("T", None, 1, []))
        self.assertEqual(again.sequence.bags, state.sequence.bags)
        self.assertNotEqual(again.practice_id, state.practice_id, "別の練習として扱われない")

    def test_reset_new_keeps_the_board_but_drops_the_configured_bags(self) -> None:
        state = GameState.new(5, BAGS, self._board())
        other = state.reset_new_sequence(seed=6)
        self.assertEqual(other.board, state.board)
        self.assertIsNone(other.sequence.bags)
        self.assertEqual(other.sequence.seed, 6)

    def test_invalid_start_boards_are_rejected(self) -> None:
        hidden = _empty_board()
        hidden[0][0] = GARBAGE
        full = _empty_board()
        full[ROWS - 1] = [GARBAGE] * COLS
        bad_value = _empty_board()
        bad_value[ROWS - 1][0] = "Q"
        for board, word in ((hidden, "非表示"), (full, "揃っている"), (bad_value, "未対応")):
            with self.assertRaises(ValueError) as ctx:
                GameState.new(1, None, board)
            self.assertIn(word, str(ctx.exception))

    def test_undo_returns_to_the_edited_start(self) -> None:
        state = GameState.new(5, BAGS, self._board())
        start = [list(row) for row in state.board]
        state.use_hold()  # 空HOLD: ツモを1個余計に消費する
        self.assertEqual(state.sequence_index, 2)
        state.hard_drop()
        state.undo()
        self.assertEqual(state.board, start)
        self.assertEqual((state.current, state.hold, state.sequence_index), ("T", None, 1))


class TestSoftDropDifficulty(unittest.TestCase):
    def test_hard_drop_placement_needs_no_soft_drop(self) -> None:
        state = GameState.new(1)
        path, sections = find_path_min_soft(state, "I", tuple((ROWS - 1, c) for c in range(6, 10)))
        self.assertEqual(sections, 0)
        self.assertEqual(path[-1], "ハードドロップ")

    def test_tuck_under_an_overhang_counts_one_section(self) -> None:
        state = GameState.new(1)
        b = ROWS - 1
        state.board[b - 2][0] = GARBAGE  # 左端の張り出し(屋根)
        # 屋根の下(列0〜1の最下段2行)へOを入れる: 列1〜2で下ろしてから左へ差し込む
        cells = ((b - 1, 0), (b - 1, 1), (b, 0), (b, 1))
        path, sections = find_path_min_soft(state, "O", cells)
        self.assertEqual(sections, 1, path)
        self.assertEqual(soft_drop_sections(path), 1)

    def test_sections_and_marks(self) -> None:
        self.assertEqual(soft_drop_sections(("↓×16", "→", "ハードドロップ")), 1)
        self.assertEqual(soft_drop_sections(("↓×3", "→", "右回転", "↓", "ハードドロップ")), 2)
        self.assertEqual(soft_drop_sections(("→×2", "ハードドロップ")), 0)
        self.assertEqual([difficulty_mark(n) for n in (0, 1, 2, 5, None)], ["◎", "○", "△", "△", "評価待ち"])

    def test_t_spin_entry_counts_the_drop(self) -> None:
        state = GameState.new(1)
        b = ROWS - 1
        for c in list(range(0, 4)) + list(range(5, 10)):
            state.board[b][c] = "X"
        for c in list(range(0, 3)) + list(range(6, 10)):
            state.board[b - 1][c] = "X"
        for c in list(range(0, 3)) + list(range(5, 10)):
            state.board[b - 2][c] = "X"
        target = ((b - 1, 3), (b - 1, 4), (b - 1, 5), (b, 4))
        path, sections = find_path_min_soft(state, "T", target, spin_entry=True)
        self.assertIn("回転", path[-2])
        self.assertGreaterEqual(sections, 1, "Tスピンの下降を数えていない")


class TestRejoin(unittest.TestCase):
    def test_swapped_order_rejoins_the_opener(self) -> None:
        # 【要望3】予定はI→Lの順だが、Iをホールドして先にLを置いた。盤面が図の途中形と
        # 一致するので、残りの手順で定跡へ戻る。
        state = _state_with_sequence("ILSTZOJ")
        advisor = Advisor(engine_factory=FakeEngine)
        first = advisor.update(state, now=0.0)
        name = advisor.active_id
        self.assertIn(name, first.source)
        track = advisor._tracks[name][0]
        l_cells = next(tuple((r + HIDDEN_ROWS, c) for r, c in s.cells) for s in track.steps if s.piece == "L")
        state.use_hold()
        _place(state, "L", l_cells)
        rec = advisor.update(state, now=0.0)
        self.assertIsNotNone(rec)
        self.assertIn(name, rec.source)
        self.assertIn("定跡に復帰", rec.source)
        self.assertEqual(advisor.active_id, name)

    def test_extra_block_does_not_rejoin(self) -> None:
        template = next(t for t in candidate_templates() if t.name_ja == "迷走砲")
        form = next(f for f in template.forms if not f.existing and len(f.items) >= 6)
        partial = set(form.items[0].cells) | {(0, 0)}  # 図に無いブロックが1つ多い
        pieces = [it.piece for it in form.items]
        self.assertIsNone(rejoin_form(template, partial, pieces[1:] + ["I"] * 2, None))
        exact = set(form.items[1].cells)
        self.assertIsNotNone(rejoin_form(template, exact, [pieces[0], *pieces[2:]], None))

    def test_off_template_placement_still_falls_back_to_ai(self) -> None:
        state = _state_with_sequence("ILSTZOJ")
        engine = FakeEngine()
        advisor = Advisor(engine_factory=lambda: engine)
        advisor.update(state, now=0.0)
        state.move_right()
        state.hard_drop()
        advisor.update(state, now=0.0)
        self.assertEqual(advisor.active_id, AI_ID)
        self.assertEqual(len(engine.started), 1)


class TestCandidateSelection(unittest.TestCase):
    def test_cycle_goes_through_all_candidates_without_moving_the_game(self) -> None:
        state = _state_with_sequence("ILSTZOJ")
        engine = FakeEngine()
        advisor = Advisor(engine_factory=lambda: engine)
        advisor.update(state, now=0.0)
        ids = [c.source_id for c in advisor.candidates()]
        self.assertEqual(ids[-1], AI_ID)
        self.assertNotIn("オリーブ積み", ids, "利用者の指示で候補に含めない")
        self.assertGreaterEqual(len(ids), 2)
        board_before = [list(row) for row in state.board]
        seen = [advisor.active_id]
        for _ in range(len(ids)):
            self.assertTrue(advisor.cycle())
            rec = advisor.update(state, now=1.0)
            seen.append(advisor.active_id)
            if advisor.active_id != AI_ID:
                self.assertIn(advisor.active_id, rec.source)
        self.assertEqual(seen[0], seen[-1], "一巡して最初に戻らない")
        self.assertEqual(sorted(set(seen)), sorted(ids))
        self.assertEqual(state.board, board_before)
        self.assertEqual(len(engine.started), 1, "AIを選んだときだけ問い合わせる")

    def test_candidates_have_difficulty_marks(self) -> None:
        state = _state_with_sequence("ILSTZOJ")
        advisor = Advisor(engine_factory=FakeEngine)
        rec = advisor.update(state, now=0.0)
        self.assertEqual(rec.scope, "この図の完成まで")
        self.assertIsNotNone(rec.soft_sections)
        names = {t.name_ja for t in candidate_templates()}
        for cand in advisor.candidates():
            if cand.source_id in names:
                self.assertIn(cand.mark, ("◎", "○", "△"))

    def test_preferred_template_comes_back_and_explicit_ai_is_kept(self) -> None:
        advisor = Advisor(engine_factory=FakeEngine)
        name = candidate_templates()[1].name_ja
        advisor.preferred_id = name
        advisor._template_recs = {}
        advisor._select()
        self.assertEqual(advisor.active_id, AI_ID, "組めない間はAIで提示する")
        advisor._template_recs = {name: object()}
        advisor._select()
        self.assertEqual(advisor.active_id, name, "組めるようになったら希望のテンプレへ戻る")
        advisor.preferred_id = AI_ID
        advisor._select()
        self.assertEqual(advisor.active_id, AI_ID, "明示的に選んだAIを勝手に切り替えた")

    def test_ai_only_cannot_cycle(self) -> None:
        advisor = Advisor(engine_factory=FakeEngine, opener_enabled=False)
        advisor.update(GameState.new(3), now=0.0)
        self.assertEqual([c.source_id for c in advisor.candidates()], [AI_ID])
        self.assertFalse(advisor.cycle())

    def test_visible_information_only(self) -> None:
        # NEXT5が同じでそれ以降だけ違う2配列では、同じ推奨になる(未表示の配列を覗かない)
        a = GameState.new(1, ("ILSTZOJ", "IJLOSTZ", "IJLOSTZ"))
        b = GameState.new(1, ("ILSTZOJ", "ZTSOLJI", "ZTSOLJI"))
        rec_a = Advisor(engine_factory=FakeEngine).update(a, now=0.0)
        rec_b = Advisor(engine_factory=FakeEngine).update(b, now=0.0)
        self.assertEqual((rec_a.source, rec_a.cells), (rec_b.source, rec_b.cells))


class TestEditorHelpers(unittest.TestCase):
    def test_stroke_is_one_undo_and_does_not_toggle(self) -> None:
        board = _empty_board()
        draft = BoardDraft(board)
        draft.begin_stroke()
        for cell in stroke_cells((ROWS - 1, 0), (ROWS - 1, 5)):
            draft.paint(*cell, GARBAGE)
        for cell in stroke_cells((ROWS - 1, 5), (ROWS - 1, 0)):  # 往復しても消えない
            draft.paint(*cell, GARBAGE)
        draft.finish_stroke()
        self.assertEqual(sum(v is not None for v in draft.cells[ROWS - 1]), 6)
        self.assertIsNone(board[ROWS - 1][0], "元の盤面を書き換えた")
        self.assertTrue(draft.undo())
        self.assertEqual(draft.cells, board)
        self.assertFalse(draft.undo())

    def test_stroke_cells_interpolates(self) -> None:
        cells = list(stroke_cells((0, 0), (3, 6)))
        self.assertEqual(cells[0], (0, 0))
        self.assertEqual(cells[-1], (3, 6))
        for (r0, c0), (r1, c1) in zip(cells, cells[1:]):
            self.assertLessEqual(max(abs(r1 - r0), abs(c1 - c0)), 1, "セルを飛ばしている")

    def test_move_in_bag_inserts_instead_of_swapping(self) -> None:
        self.assertEqual("".join(move_in_bag("IJLOSTZ", 1, 4)), "ILOSJTZ")
        with self.assertRaises(ValueError):
            move_in_bag("IJLOSTZ", 0, 7)


class TestWindowFeatures(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = FakeEngine()
        state = _state_with_sequence("ILSTZOJ")
        self.window = PracticeWindow(seed=state.sequence.seed, advisor=Advisor(engine_factory=lambda: self.engine))
        self.addCleanup(self.window.close)

    def test_f2_cycles_the_candidate(self) -> None:
        before = self.window.advisor.active_id
        event = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_F2, QtCore.Qt.KeyboardModifier.NoModifier)
        self.window.keyPressEvent(event)
        active = self.window.advisor.active_id
        self.assertNotEqual(active, before)
        marked = [b.text() for b in self.window.candidate_buttons if b.text().startswith("▶")]
        self.assertEqual(len(marked), 1)
        self.assertIn("ColdClear2" if active == AI_ID else active, marked[0])

    def test_candidate_button_selects_directly(self) -> None:
        last = self.window.candidate_buttons[-1]
        last.click()
        self.assertEqual(self.window.advisor.active_id, AI_ID)
        self.assertEqual(self.window.advisor.preferred_id, AI_ID)

    def test_screenshot_is_saved_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.window.screenshot_dir = Path(tmp) / "shots"
            first = self.window.save_screenshot()
            second = self.window.save_screenshot()
            self.assertIsNotNone(first)
            self.assertNotEqual(first, second, "同じ秒の画像を上書きした")
            self.assertTrue(first.exists() and first.stat().st_size > 0)
            self.assertIn("保存しました", self.window.notice.text())

    def test_screenshot_failure_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "file"
            blocker.write_text("x", encoding="utf-8")
            self.window.screenshot_dir = blocker / "shots"  # ファイルの下にフォルダは作れない
            self.assertIsNone(self.window.save_screenshot())
            self.assertIn("失敗", self.window.notice.text())

    def test_board_editor_apply_and_reject(self) -> None:
        window = self.window
        original = window.state
        bad = _empty_board()
        bad[0][0] = GARBAGE
        self.assertIsNotNone(window._start_practice_with_board(bad))
        self.assertIs(window.state, original, "開始できない盤面で状態を変えた")
        good = _empty_board()
        good[ROWS - 1][0] = GARBAGE
        self.assertIsNone(window._start_practice_with_board(good))
        self.assertIsNot(window.state, original)
        self.assertEqual(window.state.board[ROWS - 1][0], GARBAGE)
        self.assertEqual(window.state.current, original.sequence.peek(0))
        window.perform("hard_drop")
        window.perform("reset_same")
        self.assertEqual(window.state.board[ROWS - 1][0], GARBAGE, "同一配列リセットで編集盤面が消えた")

    def test_bag_setting_starts_new_practice(self) -> None:
        window = self.window
        self.assertIsNone(window._start_practice_with_bags(BAGS))
        self.assertEqual(window.state.current, "T")
        self.assertEqual(window.state.visible_next(), tuple("IOSZJ"))
        seed_bags = window.state.sequence.seed_bags()
        self.assertIsNone(window._start_practice_with_bags(seed_bags))
        self.assertIsNone(window.state.sequence.bags, "元の並びは指定なしと同じ扱い")

    def test_pad_buttons_held_when_dialog_closes_are_ignored_until_released(self) -> None:
        window = self.window
        window._pad_blocked = {"hard_drop"}
        history = len(window.state.history)
        window._handle_pad_actions({"hard_drop"}, 0)
        self.assertEqual(len(window.state.history), history, "押しっぱなしが持ち越された")
        window._handle_pad_actions(set(), 16)
        window._handle_pad_actions({"hard_drop"}, 32)
        self.assertEqual(len(window.state.history), history + 1)


class TestKnownSequenceWithConfiguredBags(unittest.TestCase):
    def test_seventh_piece_is_inferred_from_configured_bag(self) -> None:
        state = GameState.new(9, BAGS)
        nexts = state.visible_next()
        self.assertEqual(known_sequence(state.current, nexts, None, 0), list(BAGS[0]))
        self.assertEqual(set(PIECES), set(BAGS[0]))


if __name__ == "__main__":
    unittest.main()
