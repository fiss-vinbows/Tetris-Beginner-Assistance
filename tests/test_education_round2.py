"""教育モードの追加要望(2026-09-24 2回目)のテスト。

- 手番開始時の袋の先頭は操作ミノ(HOLDのミノではない)として7個目を補う(practice_20260924_191133)
- 1巡目の図はHOLDが空で袋の先頭のときだけ。パフェ後の繰り越しはDPC(practice_20260924_190040)
- 開幕パフェ積み・DPCは教育モード専用(画像認識側のテンプレは変えない)
- 5手以内のパフェの探索と、テンプレ優先の提示
- ツモ・HOLDを保ったまま盤面だけ編集
- キーボードの割り当て画面
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

from src.education import keybindings  # noqa: E402
from src.education.advisor import AI_ID, PC_ID, Advisor, Recommendation, candidate_templates, startable_template  # noqa: E402
from src.education.pc_search import TIMEOUT, find_perfect_clear, placements  # noqa: E402
from src.education.rules import COLS, GARBAGE, HIDDEN_ROWS, ROWS, GameState  # noqa: E402
from src.education.window import KeyMappingDialog, PracticeWindow  # noqa: E402
from src.engine.openers import EDUCATION_TEMPLATES, OPENER_TEMPLATES  # noqa: E402
from tests.test_education_advisor import FakeEngine  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

# practice_20260924_191133 の盤面(はちみつ砲の1巡目を組み終え、HOLD=L、操作ミノ=O)
HONEY_FIRST_BAG = {
    (19, 0), (19, 1), (18, 0), (18, 1), (17, 2), (18, 2), (19, 2), (18, 3), (19, 3), (19, 4), (18, 4), (18, 5),
    (19, 6), (19, 7), (19, 8), (19, 9), (18, 7), (18, 8), (18, 9), (17, 7), (16, 7), (16, 8), (17, 8), (17, 9),
}
# 開幕パフェ積みの基本形(文献の1つ目の図)
PC_OPENER_ROWS = ("llli----ss", "looi---sst", "jooi--zztt", "jjji---zzt")


def _board(cells20) -> list[list[str | None]]:
    board = [[None] * COLS for _ in range(ROWS)]
    for r, c in cells20:
        board[r + HIDDEN_ROWS][c] = GARBAGE
    return board


def _pc_opener_board() -> frozenset:
    return frozenset(
        (ROWS - len(PC_OPENER_ROWS) + i, c) for i, line in enumerate(PC_OPENER_ROWS) for c, ch in enumerate(line) if ch != "-"
    )


def _follow(state: GameState, rec) -> None:
    ops = {"←": state.move_left, "→": state.move_right, "左回転": state.rotate_ccw, "右回転": state.rotate_cw, "↓": state.soft_drop}
    if rec.use_hold:
        state.use_hold()
    for step in rec.steps:
        if step in ("ホールド", "ハードドロップ"):
            continue
        name, _, times = step.partition("×")
        for _ in range(int(times or 1)):
            assert ops[name]()
    state.hard_drop()
    assert set(state.last_lock[1]) == set(rec.cells)


class TestSeventhPieceAtTurnStart(unittest.TestCase):
    def test_honey_cup_second_bag_is_offered_before_placing_o(self) -> None:
        # 修正前は「HOLDのLが袋の先頭かもしれない」扱いで7個目(L)を補えず、HOLDのL+次の袋の
        # 8個を使う2巡目の図を組めなかった(Oを置いた後にだけ出てきた)
        state = GameState.new(1, ("IJLOSTZ", "OZJTSIL", "IJLOSTZ"), _board(HONEY_FIRST_BAG), ("O", "L", 8))
        advisor = Advisor(engine_factory=FakeEngine)
        rec = advisor.update(state, now=0.0)
        self.assertEqual(advisor.active_id, "はちみつ砲")
        self.assertIn("2巡目", rec.source)
        self.assertEqual(rec.piece, "O")


class TestFirstBagFormsNeedAlignedBag(unittest.TestCase):
    def test_no_first_bag_opener_after_pc_with_carried_piece(self) -> None:
        # パフェ後: 操作ミノTは袋の先頭、HOLD=Z(前の袋のミノ)。山岳積みの1巡目をZ込みで組まない
        state = GameState.new(1, ("IJLOSTZ", "IJLOSTZ", "TSJLZOI"), None, ("T", "Z", 15))
        advisor = Advisor(engine_factory=FakeEngine)
        rec = advisor.update(state, now=0.0)
        ids = [c.source_id for c in advisor.candidates()]
        for name in ("山岳積み2号", "はちみつ砲", "迷走砲", "開幕パフェ積み"):
            self.assertNotIn(name, ids)
        self.assertEqual(advisor.active_id, "DPC")
        self.assertIn("DPC", rec.source)

    def test_startable_template_rules(self) -> None:
        mountain = next(t for t in OPENER_TEMPLATES if t.name_ja == "山岳積み2号")
        dpc = next(t for t in EDUCATION_TEMPLATES if t.name_ja == "DPC")
        has_empty = lambda t: any(not f.existing for f in t.forms)  # noqa: E731
        self.assertTrue(has_empty(startable_template(mountain, None, True)))
        self.assertFalse(has_empty(startable_template(mountain, "Z", True)), "HOLDがあるのに1巡目の図を使う")
        self.assertFalse(has_empty(startable_template(mountain, None, False)), "袋の途中から1巡目の図を使う")
        self.assertTrue(has_empty(startable_template(dpc, "S", True)))
        self.assertFalse(has_empty(startable_template(dpc, None, True)), "繰り越しミノが無いのにDPC")


class TestEducationOnlyTemplates(unittest.TestCase):
    def test_vision_templates_are_unchanged(self) -> None:
        self.assertEqual([t.name_ja for t in OPENER_TEMPLATES], ["迷走砲", "はちみつ砲", "山岳積み2号", "オリーブ積み"])
        self.assertEqual([t.name_ja for t in EDUCATION_TEMPLATES], ["開幕パフェ積み", "DPC"])
        self.assertEqual(
            [t.name_ja for t in candidate_templates()], ["迷走砲", "はちみつ砲", "山岳積み2号", "開幕パフェ積み", "DPC"]
        )
        dpc = EDUCATION_TEMPLATES[1]
        self.assertTrue(any("組み方" in f.section for f in dpc.forms))
        self.assertTrue(any("パフェ" in f.section for f in dpc.forms))


class TestPerfectClearSearch(unittest.TestCase):
    def test_finds_pc_after_pc_opener_setup(self) -> None:
        steps = find_perfect_clear(_pc_opener_board(), list("IOTSZJ"), None)
        self.assertIsInstance(steps, list)
        self.assertLessEqual(len(steps), 5)
        board = set(_pc_opener_board())
        for step in steps:
            self.assertIn(tuple(sorted(step.cells)), placements(frozenset(board), step.piece), "SRSで届かない位置")
            board |= set(step.cells)
            full = [r for r in range(ROWS) if all((r, c) in board for c in range(COLS))]
            board = {(r + sum(1 for f in full if f > r), c) for r, c in board if r not in full}
        self.assertEqual(board, set(), "パフェになっていない")

    def test_no_pc_and_timeout(self) -> None:
        self.assertIsNone(find_perfect_clear(frozenset(), list("IOTSZJ"), None), "空の盤面はパフェ済み")
        tall = frozenset((r, 0) for r in range(ROWS - 8, ROWS))  # 8段の柱: 5手では消し切れない
        self.assertIsNone(find_perfect_clear(tall, list("IOTSZJ"), None))
        self.assertEqual(find_perfect_clear(_pc_opener_board(), list("IOTSZJ"), None, time_limit=0.0), TIMEOUT)

    def test_cannot_hold_first_when_hold_used(self) -> None:
        steps = find_perfect_clear(_pc_opener_board(), list("IOTSZJ"), "L", can_hold=False)
        if isinstance(steps, list):
            self.assertFalse(steps[0].use_hold)
            self.assertEqual(steps[0].piece, "I")


class TestPerfectClearCandidate(unittest.TestCase):
    def test_pc_is_offered_as_a_branch_when_no_template_continues(self) -> None:
        board = [[None] * COLS for _ in range(ROWS)]
        for r, c in _pc_opener_board():
            board[r][c] = GARBAGE
        state = GameState.new(1, ("IJLOSTZ", "IOTSZJL", "IJLOSTZ"), board, ("I", None, 8))
        advisor = Advisor(engine_factory=FakeEngine)
        rec = advisor.update(state, now=0.0)
        self.assertIn(PC_ID, [c.source_id for c in advisor.candidates()])
        self.assertEqual(advisor.active_id, PC_ID)
        self.assertIn("パフェ", rec.source)
        for _ in range(5):
            _follow(state, rec)
            if state.last_clear and "パーフェクトクリア" in state.last_clear:
                break
            rec = advisor.update(state, now=0.0)
        self.assertIn("パーフェクトクリア", state.last_clear or "")

    def test_template_is_preferred_over_pc_and_explicit_ai_is_kept(self) -> None:
        advisor = Advisor(engine_factory=FakeEngine)
        name = candidate_templates()[0].name_ja
        stub = Recommendation("I", False, (), "", (), soft_sections=0)
        advisor._template_recs = {name: stub}
        advisor._pc_rec = stub
        advisor._select()
        self.assertEqual(advisor.active_id, name, "テンプレを続けているのにパフェへ切り替えた")
        advisor._template_recs = {}
        advisor._select()
        self.assertEqual(advisor.active_id, PC_ID)
        advisor.preferred_id = AI_ID
        advisor._select()
        self.assertEqual(advisor.active_id, AI_ID)

    def test_pc_opener_is_followed_to_a_perfect_clear(self) -> None:
        state = GameState.new(0)
        advisor = Advisor(engine_factory=FakeEngine)
        advisor.update(state, now=0.0)
        self.assertTrue(advisor.choose("開幕パフェ積み"))
        for _ in range(12):
            rec = advisor.update(state, now=0.0)
            self.assertIn(advisor.active_id, ("開幕パフェ積み", PC_ID))
            _follow(state, rec)
            if state.last_clear and "パーフェクトクリア" in state.last_clear:
                break
        self.assertIn("パーフェクトクリア", state.last_clear or "")


class TestKeepQueueBoardEdit(unittest.TestCase):
    def test_board_only_edit_keeps_current_hold_and_next(self) -> None:
        window = PracticeWindow(seed=3, advisor=Advisor(engine_factory=FakeEngine))
        self.addCleanup(window.close)
        window.perform("hard_drop")
        window.perform("hold")
        before = (window.state.current, window.state.hold, window.state.visible_next())
        board = [[None] * COLS for _ in range(ROWS)]
        board[ROWS - 1][0] = GARBAGE
        self.assertIsNone(window._start_practice_with_board(board, keep_queue=True))
        state = window.state
        self.assertEqual((state.current, state.hold, state.visible_next()), before)
        self.assertEqual(state.board[ROWS - 1][0], GARBAGE)
        self.assertEqual(state.history, [])
        window.perform("hard_drop")
        window.perform("reset_same")
        self.assertEqual((window.state.current, window.state.hold, window.state.visible_next()), before)
        self.assertEqual(window.state.board[ROWS - 1][0], GARBAGE)

    def test_invalid_position_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            GameState.new(1, None, None, ("Q", None, 3))


class TestKeyMappingDialog(unittest.TestCase):
    def _press(self, dialog, key, modifiers=QtCore.Qt.KeyboardModifier.NoModifier) -> None:
        dialog.keyPressEvent(QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, key, modifiers))

    def test_assign_swaps_duplicates_and_escape_cancels(self) -> None:
        dialog = KeyMappingDialog(dict(keybindings.DEFAULT_BINDINGS))
        dialog.start_waiting("hard_drop")
        self._press(dialog, QtCore.Qt.Key.Key_Up)
        self.assertEqual(dialog.bindings["hard_drop"], "Up")
        dialog.start_waiting("hold")
        self._press(dialog, QtCore.Qt.Key.Key_Z)  # 左回転のキー → 入れ替え
        self.assertEqual(dialog.bindings["hold"], "Z")
        self.assertEqual(dialog.bindings["rotate_ccw"], "C")
        self.assertIn("入れ替え", dialog.message.text())
        dialog.start_waiting("undo")
        self._press(dialog, QtCore.Qt.Key.Key_Shift, QtCore.Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(dialog.waiting_for, "undo", "修飾キー単独で割り当てた")
        self._press(dialog, QtCore.Qt.Key.Key_Escape)
        self.assertIsNone(dialog.waiting_for)
        self.assertEqual(dialog.bindings["undo"], keybindings.DEFAULT_BINDINGS["undo"])
        self.assertEqual(len(set(dialog.bindings.values())), len(dialog.bindings), "キーが重複している")


if __name__ == "__main__":
    unittest.main()


class TestPerfectClearFromEmptyBoard(unittest.TestCase):
    def test_two_line_pc_right_after_a_pc(self) -> None:
        # 【実画面 practice_20260924_193201】パフェ直後の空の盤面(O・HOLD I・NEXT J L O J S)で、
        # 2段パフェが取れるのに候補に出ず、1手置いてから出ていた
        steps = find_perfect_clear(frozenset(), list("OJLOJS"), "I")
        self.assertIsInstance(steps, list)
        self.assertEqual(len(steps), 5)
        # NEXTを画像と同じ J L O J S にする(袋をまたぐ並びなので配列を直接用意する)
        state = GameState.new(1, None, None, ("O", "I", 15))
        state.sequence._prefix = tuple("IJLOSTZIJLOSTZ") + tuple("OJLOJSZ")
        self.assertEqual(state.visible_next(), tuple("JLOJS"))
        advisor = Advisor(engine_factory=FakeEngine)
        rec = advisor.update(state, now=0.0)
        self.assertIn(PC_ID, [c.source_id for c in advisor.candidates()])
        self.assertIn("パフェ", rec.source)
        for _ in range(5):
            _follow(state, rec)
            if state.last_clear and "パーフェクトクリア" in state.last_clear:
                break
            rec = advisor.update(state, now=0.0)
        self.assertIn("パーフェクトクリア", state.last_clear or "")


class TestToggles(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        from pathlib import Path

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.window = PracticeWindow(seed=0, advisor=Advisor(engine_factory=FakeEngine))
        self.window.view_path = Path(self.tmp.name) / "view.json"
        self.addCleanup(self.window.close)

    def test_hints_toggle_hides_everything_and_is_saved(self) -> None:
        window = self.window
        self.assertIsNotNone(window.board_view.recommendation)
        window.perform("toggle_hints")
        self.assertIsNone(window.board_view.recommendation)
        self.assertTrue(window.rec_label.isHidden())
        self.assertTrue(all(b.isHidden() for b in window.candidate_buttons))
        self.assertEqual(keybindings.load_view(window.view_path)["show_hints"], False)
        window.perform("toggle_hints")
        self.assertIsNotNone(window.board_view.recommendation)
        self.assertFalse(window.rec_label.isHidden())

    def test_priority_toggle_switches_between_template_and_ai(self) -> None:
        window = self.window
        self.assertNotEqual(window.advisor.active_id, AI_ID, "テンプレ優先なのにAI")
        window.perform("toggle_priority")
        self.assertEqual(window.advisor.active_id, AI_ID)
        self.assertTrue(keybindings.load_view(window.view_path)["prefer_ai"])
        window.perform("toggle_priority")
        self.assertNotEqual(window.advisor.active_id, AI_ID)

    def test_ai_priority_still_prefers_pc(self) -> None:
        advisor = Advisor(engine_factory=FakeEngine, prefer_ai=True)
        stub = Recommendation("I", False, (), "", (), soft_sections=0)
        advisor._template_recs = {candidate_templates()[0].name_ja: stub}
        advisor._pc_rec = stub
        advisor._select()
        self.assertEqual(advisor.active_id, PC_ID)
        advisor._pc_rec = None
        advisor._select()
        self.assertEqual(advisor.active_id, AI_ID)
