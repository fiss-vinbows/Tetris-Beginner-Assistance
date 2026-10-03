"""継続パフェ(パフェの後に続けて取るパフェ)の成功率のテスト。

【2026-09-28・利用者の要望】開幕パフェ以降、連続パフェを取れる可能性が高い置き方を案内する。
計算はRust製の pc-odds.exe(native/pc-odds)。未ビルドの環境では、exeを使うテストは飛ばす。
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.education.advisor import PC_ODDS_ID, Advisor  # noqa: E402
from src.education.pc_odds import OddsMove, available, best_odds_move, parse_result, request_text  # noqa: E402
from src.education.rules import GameState  # noqa: E402
from tests.test_education_advisor import FakeEngine  # noqa: E402

needs_exe = unittest.skipUnless(available(), "pc-odds.exe が未ビルド(native/pc-odds で cargo build --release)")


class TestProtocol(unittest.TestCase):
    def test_request_lists_board_sequence_hold_pool(self) -> None:
        text = request_text({(21, 0), (20, 1)}, list("TIL"), None, {"Z", "S"}, False, 1.5, 5)
        self.assertEqual(text.splitlines(), ["20,1;21,0", "TIL", "-", "SZ", "0", "1500", "5"])

    def test_parse_result(self) -> None:
        move = parse_result("ok T 1 83 84 4 10 20,4;21,3;21,4;21,5")
        self.assertEqual(move, OddsMove("T", ((20, 4), (21, 3), (21, 4), (21, 5)), True, 83, 84, 4, 10))
        self.assertAlmostEqual(move.rate, 83 / 84)
        self.assertIsNone(parse_result("none"))

    def test_parse_plan(self) -> None:
        move = parse_result("ok T 0 84 84 4 10 20,4;21,3;21,4;21,5\nplan 2\nT 0 0 20,4;21,3;21,4;21,5\nO 1 1 20,0;20,1;21,0;21,1\n")
        self.assertEqual([(st.piece, st.use_hold) for st in move.plan], [("T", False), ("O", True)])
        self.assertEqual(move.plan[1].cells, ((20, 0), (20, 1), (21, 0), (21, 1)))


@needs_exe
class TestRustSolver(unittest.TestCase):
    def test_second_pc_with_hold_matches_solution_finder(self) -> None:
        # solution-finder(percent)でも100%(84/84)の局面: HOLD O・T I L J S Z・袋の残りT I
        move = best_odds_move(frozenset(), list("TILJSZ"), "O", {"T", "I"}, time_limit=10.0)
        self.assertEqual((move.success, move.total, move.height, move.pieces), (84, 84, 4, 10))
        # 見えているミノで決まる手順(読めている手数まで)。先頭は今の1手、手順は見えているミノだけ
        self.assertGreaterEqual(len(move.plan), 2)
        self.assertEqual((move.plan[0].piece, move.plan[0].cells), (move.piece, move.cells))
        self.assertTrue(all(st.piece in "TILJSZO" for st in move.plan))

    def test_counts_per_first_move_not_per_sequence(self) -> None:
        # solution-finderは並びごとに1手目も選べるので100%(840/840)だが、1手目を1つに決めると
        # 組めない並びが残る(以前の調査で787/840)。案内に使うのは1手目を決めた成功率
        move = best_odds_move(frozenset(), list("ZIJSOL"), "Z", set(), time_limit=10.0)
        self.assertEqual(move.total, 840)
        self.assertLess(move.success, 840)
        self.assertGreater(move.rate, 0.9)

    def test_no_hold_after_pc_needs_five_unknown_pieces(self) -> None:
        # HOLDが空のパフェ直後は、4段パフェに見えない5個が要る(以前は上限4個で0%になっていた)
        move = best_odds_move(frozenset(), list("LIOSJT"), None, set(), time_limit=10.0)
        self.assertEqual((move.height, move.total), (4, 2520))
        # 手順を先まで決める分、最初の1手だけのとき(約100%)から3%以内で下がることがある
        self.assertGreater(move.rate, 0.96)

    def test_answers_within_one_second(self) -> None:
        # 【2026-09-29】1手目を選ぶ段階の最初の1回(候補全部×並び8通り)が時間内に終わらず、
        # 上限1秒では答えが出なかった局面(5秒なら100%)。最初は並び2通りから試す
        move = best_odds_move(frozenset(), list("SZTIJL"), "J", {"O", "S", "Z"}, time_limit=1.0)
        self.assertIsNotNone(move)
        self.assertGreater(move.rate, 0.9)

    def test_cancel_stops_the_process(self) -> None:
        import threading

        cancel = threading.Event()
        cancel.set()
        self.assertIsNone(best_odds_move(frozenset(), list("LIOSJT"), None, set(), time_limit=10.0, cancel=cancel))


class _FakeOdds:
    """計算の代わり。呼ばれた引数を覚え、決まった1手を返す。"""

    def __init__(self, move: OddsMove | None) -> None:
        self.move = move
        self.calls: list[tuple] = []

    def __call__(self, board, sequence, hold, pool, **kwargs):
        self.calls.append((frozenset(board), list(sequence), hold, frozenset(pool), kwargs.get("can_hold")))
        return self.move


# 空の盤面に、Tを出現位置の向き・列のまま落とす手(22行座標)
T_FLAT = OddsMove("T", ((20, 4), (21, 3), (21, 4), (21, 5)), False, 70, 84, 4, 10)


def _after_pc_state() -> GameState:
    """パフェ直後(空の盤面): 操作ミノT・HOLD O、2巡目の3個目まで配った状態。"""
    state = GameState.new(1, None, None, ("T", "O", 9))
    state.sequence._prefix = tuple("IJLOSTZ") + tuple("SOTILJZ") + tuple("IJLOSTZ")
    return state


class TestAdvisorOdds(unittest.TestCase):
    def test_offered_right_after_a_pc_with_bag_pool(self) -> None:
        state = _after_pc_state()
        fake = _FakeOdds(T_FLAT)
        advisor = Advisor(engine_factory=FakeEngine, odds_search=fake)
        rec = advisor.update(state, now=0.0)
        self.assertEqual(len(fake.calls), 1)
        board, sequence, hold, pool, can_hold = fake.calls[0]
        self.assertEqual((board, hold, can_hold), (frozenset(), "O", True))
        self.assertEqual(sequence[:6], ["T", *state.visible_next()])
        # 見えている最後のミノの後に今の袋から出る残り(配った・見えている分だけから求める)
        last = 8 + len(sequence) - 1
        dealt = {state.sequence.peek(i) for i in range(last // 7 * 7, last + 1)}
        self.assertEqual(pool, frozenset() if (last + 1) % 7 == 0 else frozenset("IJLOSTZ") - dealt)
        labels = {c.source_id: c.label for c in advisor.candidates()}
        self.assertEqual(labels.get(PC_ODDS_ID), "継続パフェ 83%")
        if advisor.active_id == PC_ODDS_ID:
            self.assertEqual(rec.cells, T_FLAT.cells)
            self.assertIn("成功率83%(70/84通り)", rec.source)

    def test_not_computed_at_practice_start(self) -> None:
        # 練習開始の空の盤面(HOLDも空)は開幕テンプレに任せる
        fake = _FakeOdds(T_FLAT)
        advisor = Advisor(engine_factory=FakeEngine, odds_search=fake)
        advisor.update(GameState.new(1), now=0.0)
        self.assertEqual(fake.calls, [])

    def test_recomputed_while_the_advice_is_followed(self) -> None:
        state = _after_pc_state()
        fake = _FakeOdds(T_FLAT)
        advisor = Advisor(engine_factory=FakeEngine, odds_search=fake)
        advisor.update(state, now=0.0)
        state.hard_drop()  # 案内どおりに置く(候補欄で選んでいなくても続けて計算する)
        self.assertEqual(set(state.last_lock[1]), set(T_FLAT.cells))
        advisor.update(state, now=0.0)
        self.assertEqual(len(fake.calls), 2)

    def test_plan_is_followed_without_recomputing(self) -> None:
        # 【2026-09-29・利用者の指摘(待ち時間)】案内した手順どおりに置いている間は計算し直さず、
        # 手順の残りをガイドに示す
        from dataclasses import replace

        from src.education.pc_search import PCStep, placements

        state = _after_pc_state()
        after_t = frozenset(T_FLAT.cells)
        second = state.visible_next()[0]
        cells2 = placements(after_t, second)[0]
        plan = (PCStep("T", T_FLAT.cells, False), PCStep(second, cells2, False))
        fake = _FakeOdds(replace(T_FLAT, plan=plan))
        advisor = Advisor(engine_factory=FakeEngine, odds_search=fake)
        rec = advisor.update(state, now=0.0)
        advisor.choose(PC_ODDS_ID)
        rec = advisor.update(state, now=0.0)
        self.assertEqual([p for p, _c in rec.guide], ["T", second])
        state.hard_drop()
        rec = advisor.update(state, now=0.0)
        self.assertEqual(len(fake.calls), 1, "手順どおりなので計算し直さない")
        self.assertEqual((rec.piece, rec.cells), (second, cells2))
        self.assertEqual(len(rec.guide), 1)

    def test_not_recomputed_after_a_different_placement(self) -> None:
        state = _after_pc_state()
        fake = _FakeOdds(T_FLAT)
        advisor = Advisor(engine_factory=FakeEngine, odds_search=fake)
        advisor.update(state, now=0.0)
        state.move_left()
        state.hard_drop()
        advisor.update(state, now=0.0)
        self.assertEqual(len(fake.calls), 1)

    def test_low_rate_is_only_listed(self) -> None:
        low = OddsMove("T", T_FLAT.cells, False, 10, 84, 4, 10)
        advisor = Advisor(engine_factory=FakeEngine, odds_search=_FakeOdds(low))
        advisor.update(_after_pc_state(), now=0.0)
        self.assertIn(PC_ODDS_ID, [c.source_id for c in advisor.candidates()])
        self.assertNotEqual(advisor.active_id, PC_ODDS_ID)

    def test_chosen_candidate_is_kept(self) -> None:
        advisor = Advisor(engine_factory=FakeEngine, odds_search=_FakeOdds(T_FLAT))
        state = _after_pc_state()
        advisor.update(state, now=0.0)
        self.assertTrue(advisor.choose(PC_ODDS_ID) or advisor.active_id == PC_ODDS_ID)
        rec = advisor.update(state, now=0.0)
        self.assertEqual(rec.cells, T_FLAT.cells)


class _GuardSequence:
    """見えている範囲(known_until番まで)より先を読んだら失敗させるミノ列(未表示の配列を覗かない確認)。"""

    def __init__(self, base, known_until: int) -> None:
        self.base = base
        self.known_until = known_until

    def peek(self, index: int) -> str:
        if index > self.known_until:
            raise AssertionError(f"未表示のミノ(番号{index})を読んだ")
        return self.base.peek(index)

    def __getattr__(self, name):
        if name == "base":
            raise AttributeError(name)  # 複製の途中(baseがまだ無い)で無限に呼び合わない
        return getattr(self.base, name)


class TestPrefetch(unittest.TestCase):
    """【2026-09-29・利用者の指示】待ち時間を減らすため、次の手番の計算を先読みしておく。"""

    def _advisor(self, fake) -> Advisor:
        advisor = Advisor(engine_factory=FakeEngine, odds_search=fake, prefetch_enabled=True)
        self.addCleanup(advisor.close)
        return advisor

    def test_inputs_for_each_possible_next_piece_without_peeking(self) -> None:
        state = _after_pc_state()
        fake = _FakeOdds(T_FLAT)  # 手順が1手だけ → 置いた後に計算が要る
        advisor = self._advisor(fake)
        advisor.update(state, now=0.0)
        advisor.choose(PC_ODDS_ID)
        advisor.update(state, now=0.0)
        last = state.sequence_index + 4
        real = state.sequence
        state.sequence = _GuardSequence(real, last)
        inputs = advisor._prefetch_inputs(state)
        state.sequence = real
        pool = frozenset("IJLOSTZ") - {real.peek(i) for i in range(last // 7 * 7, last + 1)} if (last + 1) % 7 else frozenset("IJLOSTZ")
        self.assertEqual(len(inputs), len(pool))
        # 仮に置いたミノは、袋の残りの種類を1つずつ
        self.assertEqual({seq[5] for _b, seq, _h, _p, _c in inputs}, pool)
        # 置いた後の盤面はTを置いた形
        self.assertTrue(all(board == frozenset(T_FLAT.cells) for board, *_rest in inputs))

    def test_prefetched_result_is_used_without_waiting(self) -> None:
        state = _after_pc_state()
        fake = _FakeOdds(T_FLAT)
        advisor = self._advisor(fake)
        advisor.update(state, now=0.0)
        advisor.choose(PC_ODDS_ID)
        advisor.update(state, now=0.0)
        self.assertTrue(advisor._prefetch, "先読みを始めている")
        for future, _cancel in list(advisor._prefetch.values()):
            future.result(timeout=10)
        calls = len(fake.calls)
        state.hard_drop()  # 案内どおりに置く
        rec = advisor.update(state, now=0.0)
        self.assertEqual(len(fake.calls), calls, "先読みした結果を使い、計算し直さない")
        self.assertIn(advisor._odds_key, advisor._odds_cache, "実際に来たミノの先読みを使った")
        self.assertFalse(advisor.odds_pending)
        del rec


if __name__ == "__main__":
    unittest.main()
