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
        self.assertTrue(has_empty(startable_template(mountain, None, "開幕")))
        self.assertFalse(has_empty(startable_template(mountain, "Z", "DPC")), "前の袋のミノを繰り越して1巡目の図を使う")
        self.assertFalse(has_empty(startable_template(mountain, None, "袋ずれ")), "袋の途中から1巡目の図を使う")
        self.assertTrue(has_empty(startable_template(dpc, "S", "DPC")))
        self.assertFalse(has_empty(startable_template(dpc, None, "開幕")), "繰り越しミノが無いのにDPC")


class TestEducationOnlyTemplates(unittest.TestCase):
    def test_vision_templates_are_unchanged(self) -> None:
        self.assertEqual([t.name_ja for t in OPENER_TEMPLATES], ["迷走砲", "はちみつ砲", "山岳積み2号", "オリーブ積み", "ガムシロ積み"])
        self.assertEqual([t.name_ja for t in EDUCATION_TEMPLATES], ["開幕パフェ積み", "DPC"])
        self.assertEqual(
            [t.name_ja for t in candidate_templates()], ["迷走砲", "はちみつ砲", "山岳積み2号", "ガムシロ積み", "開幕パフェ積み", "DPC"]
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
        self.assertIsNone(find_perfect_clear(frozenset(), list("IOTSZJ"), None, time_limit=30), "このミノ順では2段パフェにならない")
        tall = frozenset((r, 0) for r in range(ROWS - 8, ROWS))  # 8段の柱: 5手では消し切れない
        self.assertIsNone(find_perfect_clear(tall, list("IOTSZJ"), None, time_limit=30))
        import threading

        cancel = threading.Event()
        cancel.set()  # 局面が変わって打ち切られた探索は「未判定」を返す
        self.assertEqual(find_perfect_clear(_pc_opener_board(), list("IOTSZJ"), None, cancel=cancel), TIMEOUT)

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


# 実画面 practice_20260924_195802 / 195905(迷走砲の1巡目をZも置く形で組み、HOLD=T)
MEISOU_FIRST_BAG_ROWS = ("i------zz-", "ils-t--jzz", "ilsstt-joo", "illst-jjoo")
# 195905: 通常形(%O>%S)の2巡目をTスピンの前まで組んだ盤面
MEISOU_NORMAL_ROWS = ("-jj-------", "-js------i", "-jss--zz-i", "-oos---zzi", "coolllUcci", "ccclcUUccc", "ccccccUccc", "ccccc-cccc")


def _board_rows(rows) -> list[list[str | None]]:
    board = [[None] * COLS for _ in range(ROWS)]
    for i, line in enumerate(rows):
        for c, ch in enumerate(line):
            if ch not in "-U":
                board[ROWS - len(rows) + i][c] = GARBAGE
    return board


class TestMeisouNormalForm(unittest.TestCase):
    def test_meisou_continues_when_o_comes_before_j(self) -> None:
        # 修正前は通常形(%O>%J)の図がデータに無く、理想形を組めない順番だとAIへ移っていた
        state = GameState.new(1, ("IZLSTJO", "TOZJLSI", "IJLOSTZ"), _board_rows(MEISOU_FIRST_BAG_ROWS), ("O", "T", 9))
        advisor = Advisor(engine_factory=FakeEngine)
        rec = advisor.update(state, now=0.0)
        self.assertEqual(advisor.active_id, "迷走砲")
        self.assertIn("%O>%Sの場合", rec.source)

    def test_honey_cup_spin_only_form_does_not_claim_a_meisou_board(self) -> None:
        # 修正前ははちみつ砲の「TSTだけの図」が迷走砲の盤面に一致し「はちみつ砲」と表示した
        state = GameState.new(1, None, _board_rows(MEISOU_NORMAL_ROWS), ("L", "T", 15))
        advisor = Advisor(engine_factory=FakeEngine)
        rec = advisor.update(state, now=0.0)
        ids = [c.source_id for c in advisor.candidates()]
        self.assertNotIn("はちみつ砲", ids)
        self.assertEqual(advisor.active_id, "迷走砲")
        self.assertIn("迷走砲", rec.source)


class TestTallPerfectClear(unittest.TestCase):
    def test_eight_line_pc_is_searched(self) -> None:
        # 修正前は6段までしか探さなかった。TST→I J O L Z Tの順なら8段パフェになる
        board = frozenset((r, c) for r, row in enumerate(_board_rows(MEISOU_NORMAL_ROWS)) for c, v in enumerate(row) if v)
        steps = find_perfect_clear(board, list("TIJOLZT"), None, can_hold=False, time_limit=10)
        self.assertIsInstance(steps, list)
        self.assertEqual(len(steps), 7)
        # 実際の順番(HOLD=T, L Z I O J T S)でも、TST→L→HOLDしてI→O→J→Z→Tで取れる
        # (実画面 practice_20260924_201639〜201701。以前は取れないと誤判定していた)
        steps = find_perfect_clear(board, list("LZIOJTS"), "T", time_limit=10)
        self.assertIsInstance(steps, list)
        self.assertEqual(len(steps), 7)


class TestFastPlacements(unittest.TestCase):
    def test_every_placement_is_reachable_by_srs(self) -> None:
        from src.engine.srs_reach import find_path

        board = frozenset((r, c) for r, row in enumerate(_board_rows(MEISOU_NORMAL_ROWS)) for c, v in enumerate(row) if v)
        state = GameState.new(1, None, _board_rows(MEISOU_NORMAL_ROWS))
        for piece in "IJLOSTZ":
            found = placements(board, piece)
            self.assertTrue(found)
            for cells in found:
                self.assertIsNotNone(find_path(state, piece, cells), f"{piece}{cells}はSRSで届かない")


class TestAsyncPerfectClear(unittest.TestCase):
    def test_pc_search_runs_in_background_and_is_discarded_on_new_turn(self) -> None:
        import time

        board = [[None] * COLS for _ in range(ROWS)]
        for r, c in _pc_opener_board():
            board[r][c] = GARBAGE
        state = GameState.new(1, ("IJLOSTZ", "IOTSZJL", "IJLOSTZ"), board, ("I", None, 8))
        advisor = Advisor(engine_factory=FakeEngine, pc_async=True)
        self.addCleanup(advisor.close)
        advisor.update(state, now=0.0)
        self.assertTrue(advisor.pc_pending, "別スレッドで探していない")
        deadline = time.monotonic() + 5
        while advisor.pc_pending and time.monotonic() < deadline:
            time.sleep(0.01)
            rec = advisor.update(state, now=0.0)
        self.assertEqual(advisor.active_id, PC_ID)
        self.assertIn("パフェ", rec.source)
        # 局面が変わったら古い探索の結果は使わない
        state.use_hold()
        advisor.update(state, now=0.0)
        self.assertIsNone(advisor._pc_rec)


class TestPerfectClearAfterTst(unittest.TestCase):
    """【実画面 practice_20260924_201639〜201701】TST後(HOLD空、L Z I O J T)で、人間はL→HOLDして
    I→O→J→Z→Tでパフェを取れたが、候補に出なかった。原因は2つ:
    ・4の倍数でない空きマスの塊を打ち切っていた(Jを置いたときに1行消えて塊がつながる)
    ・見えている範囲の最後で、次のミノと入れ替えてHOLDのミノを置く手を認めていなかった"""

    def _after_tst(self) -> frozenset:
        from src.education.pc_search import _lock

        rows = MEISOU_NORMAL_ROWS
        board = frozenset((r, c) for r, row in enumerate(_board_rows(rows)) for c, v in enumerate(row) if v)
        top = ROWS - len(rows)
        slot = tuple((top + i, c) for i, line in enumerate(rows) for c, ch in enumerate(line) if ch == "U")
        return _lock(board, slot)[0]

    def test_pc_is_found_with_only_visible_pieces(self) -> None:
        steps = find_perfect_clear(self._after_tst(), list("LZIOJT"), None)
        self.assertIsInstance(steps, list)
        self.assertEqual([s.piece for s in steps][-1], "T", "最後はHOLDのTを次のミノと入れ替えて置く")
        self.assertTrue(steps[-1].use_hold)

    def test_human_line_including_a_mid_line_clear_is_valid(self) -> None:
        # 人間の手順(L, I, O, Jで1行消える, Z, T)が探索の置き方と一致して実際にパフェになる
        from src.education.pc_search import _lock

        b = self._after_tst()
        for piece, cells in (
            ("L", ((17, 5), (18, 3), (18, 4), (18, 5))),
            ("I", ((17, 0), (18, 0), (19, 0), (20, 0))),
            ("O", ((17, 6), (17, 7), (18, 6), (18, 7))),
            ("J", ((17, 8), (17, 9), (18, 8), (19, 8))),
        ):
            self.assertIn(cells, placements(b, piece))
            b = _lock(b, cells)[0]
        self.assertEqual(find_perfect_clear(b, list("ZT"), None, can_hold=False)[-1].piece, "T")

    def test_advisor_offers_the_pc_after_tst(self) -> None:
        board = [[None] * COLS for _ in range(ROWS)]
        for r, c in self._after_tst():
            board[r][c] = GARBAGE
        state = GameState.new(1, None, board, ("L", None, 15))
        state.sequence._prefix = tuple("IJLOSTZIJLOSTZ") + tuple("LZIOJTS")
        advisor = Advisor(engine_factory=FakeEngine)
        rec = advisor.update(state, now=0.0)
        self.assertIn(PC_ID, [c.source_id for c in advisor.candidates()])
        for _ in range(7):
            if advisor.active_id != PC_ID:
                advisor.choose(PC_ID)
                rec = advisor.update(state, now=0.0)
            _follow(state, rec)
            if state.last_clear and "パーフェクトクリア" in state.last_clear:
                break
            rec = advisor.update(state, now=0.0)
        self.assertIn("パーフェクトクリア", state.last_clear or "")


class TestDpcAndTetrisPerfectClear(unittest.TestCase):
    def test_labels_distinguish_search_pc_and_show_dpc_loop(self) -> None:
        board = [[None] * COLS for _ in range(ROWS)]
        for r, c in _pc_opener_board():
            board[r][c] = GARBAGE
        state = GameState.new(1, ("IJLOSTZ", "IOTSZJL", "IJLOSTZ"), board, ("I", None, 8))
        advisor = Advisor(engine_factory=FakeEngine)
        rec = advisor.update(state, now=0.0)
        self.assertIn("(探索)", rec.label)
        self.assertIn(rec.after_pc, ("開幕", "DPC", "袋ずれ"))
        label = next(c.label for c in advisor.candidates() if c.source_id == PC_ID)
        self.assertRegex(label, r"→(開幕へ|DPCへ|袋ずれ\(ループ崩れ\))$")

    def test_after_pc_counts_placed_pieces(self) -> None:
        from src.education.advisor import _after_pc, bag_status

        # 置いた数で判断する(HOLDは一度使うと空に戻らないので、HOLDの有無では判断しない)
        self.assertEqual(bag_status(0, None), "開幕")
        self.assertEqual(bag_status(35, "O"), "開幕", "DPC後(5巡)にHOLDがあっても開幕テンプレを組める")
        self.assertEqual(bag_status(20, "Z"), "DPC", "8ラインパフェ後はDPC")
        self.assertEqual(bag_status(20, None), "袋ずれ")
        self.assertEqual(bag_status(17, "Z"), "袋ずれ")
        # 置いた数13(操作ミノI・HOLD空・次は14番)から1個置くと14個 → 開幕
        state = GameState.new(1, None, None, ("I", None, 14))
        self.assertEqual(_after_pc(state, [False]), "開幕")
        # HOLDに繰り越しがあり置いた数が12(次は14番)から1個置くと13個 → DPC
        held = GameState.new(1, None, None, ("I", "Z", 14))
        self.assertEqual(_after_pc(held, [False]), "DPC")

    def test_openers_come_back_after_dpc(self) -> None:
        # 【2026-09-24】DPCを終えると5巡(35個)で、HOLDには6巡目のミノが残る。以前は「HOLDが空」を
        # 開幕テンプレの条件にしていたため、DPCの後に開幕テンプレが出なかった
        state = GameState.new(1, None, None, ("I", "O", 37))
        state.sequence._prefix = tuple("IJLOSTZ" * 5) + tuple("OILSTZJ")
        advisor = Advisor(engine_factory=FakeEngine)
        advisor.update(state, now=0.0)
        ids = [c.source_id for c in advisor.candidates()]
        self.assertIn("迷走砲", ids)
        self.assertNotIn("DPC", ids)

    def test_tetris_pc_is_preferred_over_a_template(self) -> None:
        advisor = Advisor(engine_factory=FakeEngine)
        template = Recommendation("I", False, (), "", (), soft_sections=0)
        advisor._template_recs = {candidate_templates()[0].name_ja: template}
        advisor._pc_rec = Recommendation("I", False, (), "", (), soft_sections=3, tetris=True)
        advisor._select()
        self.assertEqual(advisor.active_id, PC_ID, "テトリスパフェよりテンプレを優先した")
        advisor._pc_rec = Recommendation("I", False, (), "", (), soft_sections=0, tetris=False)
        advisor._select()
        self.assertNotEqual(advisor.active_id, PC_ID, "テトリスでないパフェはテンプレを優先")

    def test_search_prefers_a_pc_with_a_tetris(self) -> None:
        from src.education.pc_search import has_tetris

        # 右端の縦1列だけ空いた4段: Iを縦に入れるテトリスで消せる。
        board = frozenset((r, c) for r in range(ROWS - 4, ROWS) for c in range(COLS - 1))
        steps = find_perfect_clear(board, list("I"), None)
        self.assertIsInstance(steps, list)
        self.assertTrue(has_tetris(board, steps))

    def test_pc_plan_is_kept_while_followed(self) -> None:
        # 【2026-09-24】2段パフェの途中で見えるミノが増え、7手のテトリスパフェへ切り替わった
        state = GameState.new(1, None, None, ("O", "I", 15))
        state.sequence._prefix = tuple("IJLOSTZIJLOSTZ") + tuple("OJLOJSZ")
        advisor = Advisor(engine_factory=FakeEngine)
        rec = advisor.update(state, now=0.0)
        counts = []
        for _ in range(6):
            counts.append(rec.source)
            _follow(state, rec)
            if state.last_clear and "パーフェクトクリア" in state.last_clear:
                break
            rec = advisor.update(state, now=0.0)
        self.assertIn("パーフェクトクリア", state.last_clear or "")
        self.assertEqual(len(counts), 5, f"途中で別のパフェに切り替わった: {counts}")


class TestFastReachability(unittest.TestCase):
    def test_same_result_as_path_search(self) -> None:
        from src.education.rules import piece_cells
        from src.engine.srs_reach import find_path, lock_positions

        state = GameState.new(1)
        b = ROWS - 1
        for c in list(range(0, 4)) + list(range(5, 10)):
            state.board[b][c] = "X"
        for c in list(range(0, 3)) + list(range(6, 10)):
            state.board[b - 1][c] = "X"
        for c in list(range(0, 3)) + list(range(5, 10)):
            state.board[b - 2][c] = "X"
        state.board[b - 4][1] = "X"
        board = frozenset((r, c) for r in range(ROWS) for c in range(COLS) if state.board[r][c])
        for piece in "TSZ":
            plain, spin = lock_positions(board, piece)
            for orient in range(4):
                for row in range(ROWS - 6, ROWS):
                    for col in range(-2, COLS):
                        cells = piece_cells(piece, orient, row, col)
                        if any(not (0 <= r < ROWS and 0 <= c < COLS) or (r, c) in board for r, c in cells):
                            continue
                        if not any(r + 1 >= ROWS or (r + 1, c) in board for r, c in cells):
                            continue
                        target = tuple(sorted(cells))
                        self.assertEqual(find_path(state, piece, target) is not None, target in plain, target)
                        if piece == "T":
                            self.assertEqual(
                                find_path(state, piece, target, spin_entry=True) is not None, target in spin, target
                            )


class TestToggleSwitches(unittest.TestCase):
    def test_switches_show_their_state(self) -> None:
        from src.education.window import ToggleSwitch

        window = PracticeWindow(seed=0, advisor=Advisor(engine_factory=FakeEngine))
        self.addCleanup(window.close)
        for switch in (window.hints_btn, window.priority_btn, window.show_rec_check, window.show_steps_check):
            self.assertIsInstance(switch, ToggleSwitch)
            self.assertEqual(switch.focusPolicy(), QtCore.Qt.FocusPolicy.NoFocus, "盤面のキー操作を奪う")
            switch.grab()  # 描画で例外が出ない
        window.show_steps_check.click()
        self.assertFalse(window.show_steps_check.isChecked())
        self.assertNotIn("操作手順", window.rec_label.text())


class TestDpcCarriedPiece(unittest.TestCase):
    """【実画面 practice_20260924_210537〜210624】HOLD=Z(Z繰り越し)なのにO繰り越し用のO-05aを選び、
    TSDの後に続くパフェの図が合わず途中で切れた。DPCの組み方は繰り越しミノが一致する図だけ使う。"""

    def test_setup_matches_the_carried_piece(self) -> None:
        from src.education.advisor import carried_pieces

        state = GameState.new(1, ("JILOTSZ", "ILOTSZJ", "IJLOSTZ"), None, ("I", "Z", 8))
        advisor = Advisor(engine_factory=FakeEngine)
        rec = advisor.update(state, now=0.0)
        self.assertEqual(advisor.active_id, "DPC")
        self.assertNotIn("O-05a", rec.source)
        self.assertTrue(rec.source.split("/ ")[-1].startswith("S-"), rec.source)
        track = advisor._tracks["DPC"][0]
        self.assertIn("Z", carried_pieces(track.form))

    def test_carried_pieces_of_forms(self) -> None:
        from src.education.advisor import carried_pieces

        dpc = EDUCATION_TEMPLATES[1]
        setups = [f for f in dpc.forms if not f.existing]
        self.assertTrue(all(carried_pieces(f) for f in setups), "繰り越しミノが分からない組み方の図がある")
        o02 = next(f for f in setups if f.section.startswith("O-02"))
        self.assertEqual(carried_pieces(o02), frozenset("O"), "大文字の無い図はパターン名で判断する")


class TestBagStatusByPieceIndex(unittest.TestCase):
    """【実画面 practice_20260925_222055】DPCの途中から「テトリスパフェ →開幕へ」に従ったら、パフェ後に
    開幕テンプレが出なかった。前の袋のSをHOLDしたまま新しい袋のミノを先に置いていた(置いた数は35で
    7の倍数)。置いた数ではなく、まだ置いていないミノ(操作ミノ・HOLD)の番号で判断する。"""

    def test_status_uses_unplaced_piece_indices(self) -> None:
        from src.education.advisor import bag_status

        self.assertEqual(bag_status(35, "S", 36, 34), "袋ずれ", "前の袋のミノをHOLDしている")
        self.assertEqual(bag_status(35, "S", 36, 35), "開幕", "HOLDも新しい袋のミノ")
        self.assertEqual(bag_status(35, None, 35, None), "開幕")
        self.assertEqual(bag_status(20, "Z", 21, 20), "DPC", "3巡目のミノを繰り越し、操作ミノは4巡目の先頭")
        self.assertEqual(bag_status(20, "Z", 22, 20), "袋ずれ")
        self.assertEqual(bag_status(35, "S"), "開幕", "番号が分からないときは置いた数で判断")

    def test_rules_track_piece_indices(self) -> None:
        state = GameState.new(1)
        self.assertEqual((state.current_index, state.hold_index), (0, None))
        state.use_hold()  # 空のHOLDへ: 0番をHOLDし、1番が操作ミノ
        self.assertEqual((state.current_index, state.hold_index), (1, 0))
        state.hard_drop()
        self.assertEqual((state.current_index, state.hold_index), (2, 0))
        state.use_hold()  # 入れ替え: 0番が操作ミノ、2番をHOLD
        self.assertEqual((state.current_index, state.hold_index), (0, 2))
        state.undo()  # 直前に固定した手番(1手目)の開始時点(HOLD前)に戻る
        self.assertEqual((state.current_index, state.hold_index), (0, None))

    def test_tetris_pc_that_breaks_the_loop_is_labelled(self) -> None:
        from src.engine.srs_reach import find_path  # noqa: F401  (画像の局面の再現)

        cells = [(19, c) for c in range(1, 10)] + [(18, c) for c in (4, 5, 7, 8, 9)] + [(17, 5), (17, 7)]
        board = [[None] * COLS for _ in range(ROWS)]
        for r, c in cells:
            board[r + HIDDEN_ROWS][c] = GARBAGE
        state = GameState.new(1202165697, None, board, ("I", "L", 31))
        advisor = Advisor(engine_factory=FakeEngine)
        advisor.update(state, now=0.0)
        labels = {c.source_id: c.label for c in advisor.candidates()}
        self.assertIn("袋ずれ", labels[PC_ID], "ループが崩れるテトリスパフェを「開幕へ」と表示した")
        self.assertIn("開幕へ", labels["DPC"])
        self.assertEqual(advisor.active_id, PC_ID, "テトリスパフェの優先はそのまま(利用者の指示)")
