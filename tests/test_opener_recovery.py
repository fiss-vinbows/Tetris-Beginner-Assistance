"""開幕テンプレの手順位置の復元(src.engine.opener_recovery)の単体テスト。

人工的な盤面と手番で状態遷移を確認する。実画面の認識精度や演出による
欠落の実分布は対象外(実機で確認する)。
"""

from __future__ import annotations

import unittest

from src.engine.opener_recovery import (
    RecoveryGate,
    RecoveryState,
    RecoveryStep,
    TurnState,
    find_recovery,
    placement_invalid_reason,
)


class TestFindRecovery(unittest.TestCase):
    def setUp(self) -> None:
        self.first = RecoveryStep("O", ((18, 0), (18, 1), (19, 0), (19, 1)))
        self.second = RecoveryStep("I", ((19, 3), (19, 4), (19, 5), (19, 6)))
        self.turn = TurnState("O", None, ("I", "T", "S", "Z", "J"))
        self.state = RecoveryState(frozenset(), (self.first, self.second), self.turn)

    def test_zero_steps_matches_the_snapshot_itself(self) -> None:
        result = find_recovery(self.state, frozenset(), self.turn)
        self.assertEqual(result.status, "unique_within_bound")
        self.assertEqual(result.candidates[0].consumed, 0)

    def test_recovers_two_steps(self) -> None:
        board = frozenset(self.first.cells) | frozenset(self.second.cells)
        observed = TurnState("T", None, ("S", "Z", "J", "L", "O"))
        result = find_recovery(self.state, board, observed)
        self.assertEqual(result.status, "unique_within_bound")
        self.assertEqual(result.candidates[0].consumed, 2)
        self.assertEqual(result.candidates[0].state.remaining, ())
        # 本体の状態(起点)は書き換えない
        self.assertEqual(self.state.remaining, (self.first, self.second))

    def test_wrong_hold_does_not_match(self) -> None:
        result = find_recovery(self.state, frozenset(self.first.cells), TurnState("I", "L", ("T", "S", "Z", "J", "O")))
        self.assertEqual(result.status, "unresolved")

    def test_wrong_placement_does_not_match(self) -> None:
        # 手順と違う場所にOを置いた: 盤面が一致しないので復元しない
        wrong = frozenset(((18, 8), (18, 9), (19, 8), (19, 9)))
        result = find_recovery(self.state, wrong, TurnState("I", None, ("T", "S", "Z", "J", "L")))
        self.assertEqual(result.status, "unresolved")

    def test_hold_already_applied(self) -> None:
        step = RecoveryStep("I", self.second.cells, True)
        state = RecoveryState(frozenset(), (step,), self.turn)
        observed = TurnState("I", "O", ("T", "S", "Z", "J", "L"), False)
        result = find_recovery(state, frozenset(), observed)
        self.assertEqual(result.status, "unique_within_bound")
        self.assertTrue(result.candidates[0].pending_hold_applied)
        self.assertFalse(result.candidates[0].state.remaining[0].use_hold, "HOLD指示をもう一度出さない")

    def test_line_clear_shifts_remaining(self) -> None:
        board = frozenset((19, c) for c in range(6))
        first = RecoveryStep("I", ((19, 6), (19, 7), (19, 8), (19, 9)))
        second = RecoveryStep("O", ((17, 0), (17, 1), (18, 0), (18, 1)))
        state = RecoveryState(board, (first, second), TurnState("I", None, ("O", "T", "S", "Z", "J")))
        observed = TurnState("O", None, ("T", "S", "Z", "J", "L"))
        result = find_recovery(state, frozenset(), observed)
        self.assertEqual(result.status, "unique_within_bound")
        self.assertEqual(result.candidates[0].consumed, 1)
        self.assertEqual(set(result.candidates[0].state.remaining[0].cells), {(18, 0), (18, 1), (19, 0), (19, 1)})

    def test_unknown_future_stays_unresolved(self) -> None:
        # NEXTが見えていない先は照合できないので確定しない
        state = RecoveryState(frozenset(), (self.first,), TurnState("O", None, ()))
        result = find_recovery(state, frozenset(self.first.cells), TurnState("I", None, ("T",)))
        self.assertEqual(result.status, "unresolved")

    def test_unrecognized_piece_in_turn_is_rejected(self) -> None:
        result = find_recovery(self.state, frozenset(), TurnState("O", None, ("I", "?", "S", "Z", "J")))
        self.assertEqual(result.status, "unresolved")
        self.assertEqual(result.reason, "unknown_turn")

    def test_search_bound_is_respected(self) -> None:
        board = frozenset(self.first.cells) | frozenset(self.second.cells)
        observed = TurnState("T", None, ("S", "Z", "J", "L", "O"))
        self.assertEqual(find_recovery(self.state, board, observed, max_steps=1).status, "unresolved")


class TestPlacementInvalidReason(unittest.TestCase):
    def test_reasons(self) -> None:
        self.assertEqual(placement_invalid_reason(set(), [(19, 0)]), "invalid_cell_count")
        self.assertEqual(placement_invalid_reason(set(), [(18, c) for c in range(4)]), "unsupported")
        self.assertEqual(placement_invalid_reason(set(), [(20, c) for c in range(4)]), "out_of_bounds")
        self.assertEqual(placement_invalid_reason({(19, 0)}, [(19, c) for c in range(4)]), "collision")
        self.assertIsNone(placement_invalid_reason(set(), [(19, c) for c in range(4)]))


class TestRecoveryGate(unittest.TestCase):
    def test_same_frame_does_not_confirm_twice(self) -> None:
        state = RecoveryState(frozenset(), (RecoveryStep("O", ((18, 0), (18, 1), (19, 0), (19, 1))),), TurnState("O", None, ("I",)))
        result = find_recovery(state, frozenset(), state.turn)
        gate = RecoveryGate()
        self.assertIsNone(gate.accept(result, frame_id=1, trustworthy=True, observed_turn=state.turn))
        self.assertIsNone(gate.accept(result, frame_id=1, trustworthy=True, observed_turn=state.turn))
        self.assertIsNotNone(gate.accept(result, frame_id=2, trustworthy=True, observed_turn=state.turn))

    def test_untrustworthy_frame_resets_confirmations(self) -> None:
        state = RecoveryState(frozenset(), (RecoveryStep("O", ((18, 0), (18, 1), (19, 0), (19, 1))),), TurnState("O", None, ("I",)))
        result = find_recovery(state, frozenset(), state.turn)
        gate = RecoveryGate()
        self.assertIsNone(gate.accept(result, frame_id=1, trustworthy=True, observed_turn=state.turn))
        self.assertIsNone(gate.accept(result, frame_id=2, trustworthy=False, observed_turn=state.turn))
        self.assertIsNone(gate.accept(result, frame_id=3, trustworthy=True, observed_turn=state.turn))
        self.assertIsNotNone(gate.accept(result, frame_id=4, trustworthy=True, observed_turn=state.turn))


if __name__ == "__main__":
    unittest.main()
