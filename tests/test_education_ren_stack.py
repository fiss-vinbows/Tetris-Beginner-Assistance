"""種3の中あけRENを積んで消す練習(シミュレーター)のテスト。

【2026-10-03・利用者の要望】種3(中央4列の底に置く3マスのタネ)の中あけRENを積む練習をシミュレーターでする。
積む部分はテトリス堂の「開幕中開け4列REN」の図(1巡目)、その後は評価で左右3列ずつを積み増し
(src/education/ren_stack.py)、左右が目標の高さになったら無限中あけRENと同じ推奨手で消していく。
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tests.config_isolation  # noqa: E402,F401  本番の設定ファイルを使わない
from PyQt6 import QtWidgets  # noqa: E402

from src.education import ren_stack  # noqa: E402
from src.education.advisor import REN_ID, REN_STACK_ID, Advisor, manual_templates, ren_ready  # noqa: E402
from src.education.rules import GameState  # noqa: E402
from src.engine import openers  # noqa: E402
from tests.test_education_advisor import FakeEngine  # noqa: E402
from tests.test_education_round2 import _follow  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
REN_TEMPLATE = "中開け4列REN(種3)"
SIDES = (0, 1, 2, 7, 8, 9)


class TestRenTemplate(unittest.TestCase):
    def test_template_is_read_from_the_page(self) -> None:
        template = openers.REN_TEMPLATES[0]
        self.assertEqual(template.name_ja, REN_TEMPLATE)
        first = [f for f in template.forms if not f.existing]
        self.assertGreaterEqual(len(first), 3, "基本系の3通り")
        seeds = []
        for form in first:
            cells = {cell for item in form.items for cell in item.cells}
            seeds.append(sum(1 for _r, c in cells if 3 <= c <= 6))
        # 中央4列に置くのはタネの3マスだけ(レベル2「タネの後入れ」はTをHOLDしておくので0マス)
        self.assertTrue(set(seeds) <= {0, 3}, seeds)
        self.assertGreaterEqual(seeds.count(3), 3, "基本系の3通り")

    def test_listed_but_not_chosen_automatically(self) -> None:
        for seed in range(4):
            advisor = Advisor(engine_factory=FakeEngine, odds_search=lambda *a, **k: None)
            advisor.update(GameState.new(seed), now=0.0)
            self.assertNotIn(advisor.active_id, manual_templates(), "対局開始で自動選択された")


class TestRenReady(unittest.TestCase):
    def test_ready_when_only_the_seed_is_in_the_well(self) -> None:
        board = frozenset((r, c) for r in range(16, 22) for c in SIDES) | {(21, 3), (21, 4), (21, 5)}
        self.assertTrue(ren_ready(board))
        # 【2026-10-04】種は3マスとは限らない(おじゃまの段が消えると変わる)。種のある行の左右が埋まっていればよい
        self.assertTrue(ren_ready(board | {(20, 3)}), "種が4マス")
        self.assertFalse(ren_ready(frozenset((r, c) for r in range(16, 22) for c in SIDES)), "種が無い")
        self.assertFalse(ren_ready(board - {(21, 0)}), "タネの行の左右が埋まっていない")

    def test_stack_evaluation_dislikes_a_one_column_slot(self) -> None:
        flat = frozenset((r, c) for r in range(14, 22) for c in SIDES) | {(21, 3), (21, 4), (21, 5)}
        slot = flat - {(r, 9) for r in range(14, 20)}  # 右端の列だけ低い
        self.assertGreater(ren_stack.evaluate(flat), ren_stack.evaluate(slot))


class TestBuildAndClear(unittest.TestCase):
    def test_build_stack_then_ren(self) -> None:
        # 【2026-10-03・利用者の指示】20段目まで積み込む想定。試行(seed 4)では、1巡目の図→積み増しで
        # 左右を18〜20段まで積み、RENが18手続いた
        state = GameState.new(4)
        advisor = Advisor(engine_factory=FakeEngine, odds_search=lambda *a, **k: None)
        advisor.update(state, now=0.0)
        self.assertTrue(advisor.choose(REN_TEMPLATE))
        stages = []
        for _ in range(120):
            rec = advisor.update(state, now=0.0)
            if rec is None or advisor.active_id not in (REN_TEMPLATE, REN_STACK_ID, REN_ID):
                break
            stages.append({REN_TEMPLATE: "T", REN_STACK_ID: "S", REN_ID: "R"}[advisor.active_id])
            _follow(state, rec)
        flow = "".join(stages)
        self.assertTrue(flow.startswith("T" * 7), flow)
        self.assertIn("S", flow)
        self.assertIn("R" * 10, flow, f"RENが続かない: {flow}")
        self.assertGreaterEqual(flow.index("R"), 30, "20段まで積まずにRENを始めた")
        self.assertLess(flow.index("T" * 7) + 7, flow.index("R"))


class TestStackAndRenQuality(unittest.TestCase):
    def test_stack_does_not_cover_the_gap_left_by_the_first_bag(self) -> None:
        # 1巡目の図(基本系の1つ目)は右端の1マス(18行9列)を空けている。2026-10-03の試行では積み増しが
        # その上にJを置いてふさぎ、その行でRENが3手で途切れた(穴の減点が小さかった)
        rows = ["..........", ".......i..", ".......i..", "lll....is.", "loo....iss", "joo...tzzs", "jjj..tttzz"]
        board = frozenset((22 - len(rows) + i, c) for i, line in enumerate(rows) for c, ch in enumerate(line) if ch != ".")
        board |= {(r, c) for r in (16, 17) for c in (0, 1, 2)}
        move = ren_stack.best_move(board, "J", None, list("OLSZT"), True)
        after = board | set(move.cells)
        covered = (18, 9) not in after and any((r, 9) in after for r in range(18))
        self.assertFalse(covered, f"穴をふさいだ: {move}")

    def test_ren_prefers_a_shape_that_more_pieces_can_continue(self) -> None:
        # 【2026-10-03・利用者の指示】RENの消化は1手ごとに評価を改めて最大になるようにする
        from src.education.ren_search import _continuable

        sides = frozenset((r, c) for r in range(2, 22) for c in (0, 1, 2, 7, 8, 9))
        flat = sides | {(21, 3), (21, 4), (21, 5)}  # ###.(右端の1マスだけ空き)
        # 次に来るミノによっては続かない(数え方: 7種のうちラインを消せる種類)
        self.assertLess(_continuable(flat, None), 7)
        self.assertGreater(_continuable(flat, None), 0)
        self.assertEqual(_continuable(flat, "I"), 7, "HOLDのIで必ず続く")


class TestPanel(unittest.TestCase):
    def test_panel_has_the_ren_switches(self) -> None:
        from src.education.window import PracticeWindow

        window = PracticeWindow(seed=0, advisor=Advisor(engine_factory=FakeEngine))
        self.addCleanup(window.close)
        for source_id in (REN_TEMPLATE, REN_STACK_ID, REN_ID):
            self.assertIn(source_id, window.filter_checks)


class TestRenAfterUndo(unittest.TestCase):
    """【2026-10-04・利用者の指摘/実画面 practice_20261004_145206】REN消化中に置き間違えて中あけの形を崩し、
    一手戻すと、提示が中あけ積みに変わってREN消化のガイドが出なくなっていた。"""

    def test_undo_after_mistake_returns_to_ren(self) -> None:
        from src.education.rules import COLS, GARBAGE, HIDDEN_ROWS, ROWS

        board = [[None] * COLS for _ in range(ROWS)]
        for r in range(HIDDEN_ROWS, ROWS):
            for c in (0, 1, 2, 7, 8, 9):
                board[r][c] = GARBAGE
        for c in (3, 4, 5):
            board[ROWS - 1][c] = GARBAGE  # タネ(3マス)
        state = GameState.new(5, board=tuple(tuple(r) for r in board))
        advisor = Advisor(engine_factory=FakeEngine, odds_search=lambda *a, **k: None)
        advisor.preferred_id = next(iter(manual_templates()))
        for _ in range(6):
            _follow(state, advisor.update(state, now=0.0))  # RENを6回(左右が20段より低くなる)
        self.assertEqual(advisor.active_id, REN_ID)
        # 中央に縦にして置き、中あけの形を崩す(RENが途切れる)
        state.rotate_cw()
        while state.move_left():
            pass
        for _ in range(3):
            state.move_right()
        state.hard_drop()
        advisor.update(state, now=0.0)
        # 置き間違えで提示がAIに切り替わった状態(実画面と同じ)。種の数が変わっても中あけとみなすようになった
        # (2026-10-04)ため、この置き方ではRENのまま続くことがあるので、切り替わった状態を作る
        advisor.active_id = "cc2"
        state.undo()
        rec = advisor.update(state, now=0.0)
        self.assertEqual(advisor.active_id, REN_ID, "一手戻した後に中あけ積みへ切り替わった")
        self.assertTrue(rec.guide, "REN消化のガイドが無い")


class TestRenWithGarbageBelow(unittest.TestCase):
    """【2026-10-04・利用者の指摘/実画面 practice_20261004_152417】中あけの形のまま下からおじゃまが4段せり上がると、
    下の段の中央4列のマスまで数えて中あけではないと判定し、REN消化・積み増しの提示がAIに変わっていた。"""

    def _state(self, height: int, tane: bool):
        import random

        from src.education.rules import COLS, ROWS

        board = [[None] * COLS for _ in range(ROWS)]
        for r in range(ROWS - height, ROWS):
            for c in (0, 1, 2, 7, 8, 9):
                board[r][c] = "L"  # 実際の練習と同じく、左右はミノのブロック
        if tane:
            for c in (3, 4, 5):
                board[ROWS - 1][c] = "J"
        state = GameState.new(5, board=tuple(tuple(r) for r in board))
        return state, random

    def _advisor(self):
        advisor = Advisor(engine_factory=FakeEngine, odds_search=lambda *a, **k: None)
        advisor.preferred_id = next(iter(manual_templates()))
        return advisor

    def test_ren_continues_after_garbage(self) -> None:
        state, random = self._state(20, tane=True)
        advisor = self._advisor()
        advisor.update(state, now=0.0)
        self.assertEqual(advisor.active_id, REN_ID)
        state.add_garbage(4, random.Random(0))
        rec = advisor.update(state, now=0.0)
        self.assertEqual(advisor.active_id, REN_ID, "おじゃまの後にAIへ変わった")
        self.assertTrue(rec.guide)

    def test_stacking_continues_after_garbage(self) -> None:
        state, random = self._state(10, tane=False)
        advisor = self._advisor()
        advisor.preferred_id = REN_STACK_ID
        advisor.update(state, now=0.0)
        self.assertEqual(advisor.active_id, REN_STACK_ID)
        state.add_garbage(4, random.Random(0))
        advisor.update(state, now=0.0)
        self.assertEqual(advisor.active_id, REN_STACK_ID, "おじゃまの後に積み増しがAIへ変わった")


class TestRenWithChangedSeed(unittest.TestCase):
    """【2026-10-04・利用者の指摘】おじゃまの穴にミノが入っておじゃまの段も消えると、種(中央4列のマス)が3マスから
    5・9マス等に変わる。以前は種がちょうど3マスでないとRENの提示をやめていた。"""

    def test_ren_is_shown_while_it_can_continue(self) -> None:
        from src.education.advisor import REN_WELL
        from src.education.ren_search import find_ren_plan
        from src.education.rules import COLS, GARBAGE, ROWS

        board = [[None] * COLS for _ in range(ROWS)]
        for r in range(2, ROWS - 2):
            for c in (0, 1, 2, 7, 8, 9):
                board[r][c] = "L"
        for c in (3, 4, 5):
            board[ROWS - 3][c] = "J"  # 種3
        for r in (ROWS - 2, ROWS - 1):  # おじゃま2段(中央の3列目に穴)
            board[r] = [GARBAGE] * COLS
            board[r][3] = None
        state = GameState.new(6, board=tuple(tuple(r) for r in board))  # 4手目に種が5マスになる配列
        advisor = Advisor(engine_factory=FakeEngine, odds_search=lambda *a, **k: None)
        advisor.preferred_id = next(iter(manual_templates()))
        seeds = set()
        for turn in range(12):
            rec = advisor.update(state, now=0.0)
            cells = frozenset((r, c) for r in range(ROWS) for c in range(COLS) if state.board[r][c] is not None)
            seeds.add(sum(1 for _r, c in cells if c in REN_WELL and state.board[_r][c] != GARBAGE))
            if advisor.active_id != REN_ID:
                inputs = advisor._pc_inputs(state)
                self.assertIsNone(find_ren_plan(cells, inputs[1], inputs[2], inputs[3], REN_WELL),
                                  f"{turn}手目: RENを続けられるのに提示が止まった")
                break
            _follow(state, rec)
        self.assertTrue(seeds - {3}, "前提: 種が3マス以外になる流れ")


if __name__ == "__main__":
    unittest.main()
