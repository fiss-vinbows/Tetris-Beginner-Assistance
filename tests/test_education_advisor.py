"""教育モードの推奨手(src.education.advisor)のテスト。CC2は偽物で置き換える。"""

from __future__ import annotations

import unittest

from src.education.advisor import Advisor, find_path
from src.education.rules import COLS, HIDDEN_ROWS, ROWS, GameState
from src.engine.cold_clear_client import ColdClearMove
from src.engine.openers import OPENER_TEMPLATES


class FakeEngine:
    """start_thinkingで受け取った局面を記録し、決めておいた手を返す。"""

    def __init__(self, move: ColdClearMove | None = None) -> None:
        self.started: list[tuple] = []
        self.move = move
        self.closed = False

    def start_thinking(self, board, current, hold, next_queue, disallow_hold=False) -> None:
        self.started.append((board, current, hold, tuple(next_queue), disallow_hold))

    def poll_suggestion(self, current):
        return self.move

    def close(self) -> None:
        self.closed = True


def _state_with_sequence(pieces: str) -> GameState:
    """先頭がpiecesになる配列のシードを探す(開幕テンプレの検証用)。"""
    for seed in range(200000):
        state = GameState.new(seed)
        if all(state.sequence.peek(i) == p for i, p in enumerate(pieces)):
            return state
    raise AssertionError("配列が見つからない")


class TestFindPath(unittest.TestCase):
    def test_path_to_a_simple_placement(self) -> None:
        state = GameState.new(1)
        # I横向きを右端(列6〜9)の最下段へ
        target = tuple((ROWS - 1, c) for c in range(6, 10))
        path = find_path(state, "I", target)
        self.assertEqual(path, ("→×3", "ハードドロップ"))

    def test_t_spin_double_slot_needs_rotation(self) -> None:
        state = GameState.new(1)
        b = ROWS - 1
        for c in list(range(0, 4)) + list(range(5, 10)):
            state.board[b][c] = "X"
        for c in list(range(0, 3)) + list(range(6, 10)):
            state.board[b - 1][c] = "X"
        for c in list(range(0, 3)) + list(range(5, 10)):
            state.board[b - 2][c] = "X"
        target = ((b - 1, 3), (b - 1, 4), (b - 1, 5), (b, 4))
        path = find_path(state, "T", target)
        self.assertIsNotNone(path, "TSDの穴へ届く手順が見つからない")
        self.assertIn("回転", path[-2], "最後の操作が回転になっていない(Tスピンにならない)")

    def test_unreachable_placement_returns_none(self) -> None:
        state = GameState.new(1)
        for c in range(COLS):
            state.board[ROWS - 2][c] = "X"  # 屋根
        self.assertIsNone(find_path(state, "O", ((ROWS - 1, 0), (ROWS - 1, 1), (ROWS - 2, 0), (ROWS - 2, 1))))


class TestAdvisorEngine(unittest.TestCase):
    def test_engine_receives_only_next_five_and_result_is_converted_to_22_rows(self) -> None:
        state = GameState.new(3)
        state.board[ROWS - 1][0] = "X"
        state.turn_start = state._snapshot()
        cells20 = [(19, 6), (19, 7), (19, 8), (19, 9)]
        engine = FakeEngine(ColdClearMove(use_hold=False, piece="I", landing_cells=cells20, nodes=0, nps=0.0))
        state.current = "I"
        advisor = Advisor(engine_factory=lambda: engine, opener_enabled=False)
        self.assertIsNone(advisor.update(state, now=0.0), "思考時間を待たずに固定している")
        board, current, hold, nexts, disallow = engine.started[0]
        self.assertEqual(nexts, state.visible_next(), "NEXT5以外を渡している")
        self.assertEqual(len(nexts), 5)
        self.assertEqual(board.grid[19][0], "G", "盤面の座標変換が違う")
        rec = advisor.update(state, now=1.0)
        self.assertEqual(rec.cells, tuple((r + HIDDEN_ROWS, c) for r, c in cells20))
        self.assertEqual(rec.source, "AI(Cold Clear 2)")
        self.assertIsNotNone(rec.steps)
        self.assertIs(advisor.update(state, now=2.0), rec, "同じミノの間に提示が変わっている")

    def test_hold_used_disables_hold_suggestion(self) -> None:
        state = GameState.new(3)
        state.use_hold()
        engine = FakeEngine()
        Advisor(engine_factory=lambda: engine, opener_enabled=False).update(state, now=0.0)
        self.assertTrue(engine.started[0][4], "HOLD済みなのにHOLDを禁止していない")

    def test_engine_failure_is_reported_not_raised(self) -> None:
        def broken():
            raise FileNotFoundError("cold-clear-2.exe")

        advisor = Advisor(engine_factory=broken, opener_enabled=False)
        self.assertIsNone(advisor.update(GameState.new(3), now=0.0))
        self.assertIn("AIを使えません", advisor.status)


class TestAdvisorOpener(unittest.TestCase):
    def setUp(self) -> None:
        import src.engine.openers as openers

        honey = next(t for t in OPENER_TEMPLATES if t.name_ja == "はちみつ砲")
        self._saved = openers.OPENER_TEMPLATES
        openers.OPENER_TEMPLATES = (honey,)
        self.addCleanup(lambda: setattr(openers, "OPENER_TEMPLATES", self._saved))

    def _play(self, state: GameState, advisor: Advisor):
        rec = advisor.update(state, now=0.0)
        if rec.use_hold:
            state.use_hold()
            rec = advisor.update(state, now=0.0)
            self.assertFalse(rec.use_hold, "HOLDした後もHOLDを指示している")
        # 手順どおりに操作して置く(操作手順が本当に届くことの確認も兼ねる)
        ops = {"←": state.move_left, "→": state.move_right, "左回転": state.rotate_ccw, "右回転": state.rotate_cw, "↓": state.soft_drop}
        for step in rec.steps:
            if step in ("ホールド", "ハードドロップ"):
                continue
            name, _, times = step.partition("×")
            for _ in range(int(times or 1)):
                self.assertTrue(ops[name](), f"操作手順{rec.steps}のとおりに動かせない")
        state.hard_drop()
        self.assertEqual(state.last_lock[1] and set(state.last_lock[1]), set(rec.cells), "手順どおりに操作しても推奨配置に置けない")
        return rec

    def test_template_is_recommended_and_followed_through_the_first_bag(self) -> None:
        state = _state_with_sequence("ILSTZOJ")
        engine = FakeEngine()
        advisor = Advisor(engine_factory=lambda: engine)
        recs = [self._play(state, advisor) for _ in range(6)]
        self.assertTrue(all("はちみつ砲" in r.source for r in recs), [r.source for r in recs])
        self.assertEqual(engine.started, [], "テンプレ中にAIへ問い合わせている")
        filled = {(r, c) for r in range(ROWS) for c in range(COLS) if state.board[r][c] is not None}
        self.assertEqual(len(filled), 24, "1巡目の形になっていない")

    def test_off_template_placement_falls_back_to_the_engine(self) -> None:
        state = _state_with_sequence("ILSTZOJ")
        engine = FakeEngine()
        advisor = Advisor(engine_factory=lambda: engine)
        rec = advisor.update(state, now=0.0)
        self.assertIn("はちみつ砲", rec.source)
        state.move_right()  # 手順と違う場所へ
        state.hard_drop()
        advisor.update(state, now=0.0)
        self.assertEqual(len(engine.started), 1, "手順を外れたのにAIへ切り替わっていない")

    def test_undo_restores_the_template_step(self) -> None:
        state = _state_with_sequence("ILSTZOJ")
        advisor = Advisor(engine_factory=FakeEngine)
        first = self._play(state, advisor)
        state.undo()
        self.assertEqual(advisor.update(state, now=0.0).cells, first.cells, "一手戻してもテンプレの1手目に戻らない")


if __name__ == "__main__":
    unittest.main()


class TestTemplateTSpinsAreExecutable(unittest.TestCase):
    """【2026-09-23】テンプレのTスピンの手が、実際には回転で入れられない順番で
    推奨され(操作手順が見つからない)、利用者が従えずAIへ切り替わっていた。"""

    def _follow(self, name: str, seed: int, moves: int = 24) -> list[str]:
        import src.engine.openers as openers

        saved = openers.OPENER_TEMPLATES
        openers.OPENER_TEMPLATES = tuple(t for t in saved if t.name_ja == name)
        self.addCleanup(lambda: setattr(openers, "OPENER_TEMPLATES", saved))
        state = GameState.new(seed)
        advisor = Advisor(engine_factory=FakeEngine)
        clears: list[str] = []
        ops = {"←": state.move_left, "→": state.move_right, "左回転": state.rotate_ccw, "右回転": state.rotate_cw, "↓": state.soft_drop}
        for _ in range(moves):
            rec = advisor.update(state, now=0.0)
            if rec is None:
                break
            self.assertIsNotNone(rec.steps, f"{rec.source}: {rec.piece}の操作手順が無い(入れられない位置)")
            if rec.use_hold:
                state.use_hold()
            for step in rec.steps:
                if step in ("ホールド", "ハードドロップ"):
                    continue
                name_, _, times = step.partition("×")
                for _ in range(int(times or 1)):
                    self.assertTrue(ops[name_]())
            state.hard_drop()
            self.assertEqual(set(state.last_lock[1]), set(rec.cells))
            if state.last_clear:
                clears.append(state.last_clear)
        return clears

    def test_honey_cup_tst_and_tsd_are_performed(self) -> None:
        # 修正前は配列12でTST、配列16で3巡目のTSDの操作手順が見つからなかった
        for seed in (12, 16):
            clears = self._follow("はちみつ砲", seed)
            self.assertTrue(any(c.startswith(("TST", "TSD")) for c in clears), f"配列{seed}: {clears}")


class TestFewerTucksArePreferred(unittest.TestCase):
    def test_second_bag_prefers_the_form_with_fewest_soft_drops(self) -> None:
        # 【2026-09-23・教育モードの実画面 配列#637142134】2巡目で、ハードドロップで
        # 置ける別の図があるのに、回転入れ(ソフトドロップ)が3回要る図を推奨した。
        # 組める図・手順の中から回転入れの少ないものを選ぶ。
        state = GameState.new(637142134)
        advisor = Advisor(engine_factory=FakeEngine)
        ops = {"←": state.move_left, "→": state.move_right, "左回転": state.rotate_ccw, "右回転": state.rotate_cw, "↓": state.soft_drop}
        soft_drop_moves = []
        for _ in range(14):
            rec = advisor.update(state, now=0.0)
            self.assertIsNotNone(rec)
            if any(step.startswith("↓") for step in rec.steps) and not rec.piece == "T":
                soft_drop_moves.append((len(state.history), rec.piece))
            if rec.use_hold:
                state.use_hold()
            for step in rec.steps:
                if step in ("ホールド", "ハードドロップ"):
                    continue
                name, _, times = step.partition("×")
                for _ in range(int(times or 1)):
                    self.assertTrue(ops[name]())
            state.hard_drop()
        self.assertEqual(state.last_clear, "TST(Tスピントリプル)")
        self.assertLessEqual(len(soft_drop_moves), 1, f"回転入れが多い: {soft_drop_moves}")
        self.assertTrue(all(turn >= 6 for turn, _p in soft_drop_moves), "1巡目でソフトドロップしている")
