"""支援モードの継続パフェのテスト。

【2026-09-29・利用者の要望】支援モードにも継続パフェを搭載する。
- 盤面(おじゃま込み)が低いときはいつでも計算し、パフェを狙えるなら手順を表示する。
- おじゃまが奇数行ならパフェにならないのでAIの提示。
- 継続パフェが組めない(成功率が低い)ときは通常のAIに戻す。
- テンプレ(DPC等)と両方組めるときの優先は設定で選ぶ。
"""

from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt6 import QtWidgets  # noqa: E402

from src.app import _PC_ODDS_TEMPLATE, AssistWorker, _bag_pool  # noqa: E402
from src.education.pc_odds import OddsMove  # noqa: E402
from src.education.pc_search import PCStep  # noqa: E402
from tests.test_assist_worker import _make_calibration, _move, _recognition  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

# 左端の列だけ空いたおじゃま行(20行座標)
def _garbage(rows: int) -> tuple[tuple[int, int], ...]:
    return tuple((19 - k, c) for k in range(rows) for c in range(1, 10))


def _with_garbage(rec, garbage_cells):
    for r, c in garbage_cells:
        rec.board.grid[r][c] = "GARBAGE"
    return dataclasses.replace(rec, board_key=tuple(tuple(row) for row in rec.board.grid))


class _FakeOdds:
    def __init__(self, move: OddsMove | None) -> None:
        self.move = move
        self.calls: list[tuple] = []

    def __call__(self, board, sequence, hold, pool, **kwargs):
        self.calls.append((frozenset(board), list(sequence), hold, frozenset(pool), kwargs))
        return self.move


# おじゃま2行(左端が空き)を、Iを縦に置いて消す手(22行座標)
I_WELL = PCStep("I", ((18, 0), (19, 0), (20, 0), (21, 0)), False)


def _odds(rate_success: int = 80, plan=(I_WELL,)) -> OddsMove:
    first = plan[0]
    return OddsMove(first.piece, first.cells, first.use_hold, rate_success, 100, 4, 5, tuple(plan))


class TestAssistPcOdds(unittest.TestCase):
    def setUp(self) -> None:
        self.cold_clear = MagicMock()
        self.cold_clear.poll_suggestion.return_value = _move("A")

    def _worker(self, fake, first: bool = False) -> AssistWorker:
        worker = AssistWorker(
            _make_calibration(), self.cold_clear, debug_log_path=None, opener_enabled=True, pc_odds_enabled=True,
            pc_odds_first=first,
        )
        worker._pc_odds_search_func = fake
        return worker

    def _tick(self, worker, rec, t: float = 1000.0) -> None:
        with patch("src.app.time.monotonic", return_value=t):
            with patch("src.app.recognize", return_value=rec):
                worker._tick_once(capture=MagicMock())

    def _tick_until_done(self, worker, rec) -> None:
        self._tick(worker, rec)
        if worker._pc_odds_search is not None:
            self.assertTrue(worker._pc_odds_search.done.wait(5))
        self._tick(worker, rec, 1000.1)

    def _garbage_rec(self, rows: int):
        rec = _recognition(current_piece="I", hold_piece="O", next_queue=("T", "S", "Z", "J", "L"))
        return _with_garbage(rec, _garbage(rows))

    def test_odd_garbage_rows_fall_back_to_ai(self) -> None:
        fake = _FakeOdds(_odds())
        worker = self._worker(fake)
        self._tick_until_done(worker, self._garbage_rec(1))
        self.assertEqual(fake.calls, [], "おじゃまが奇数行なのに継続パフェを計算した")
        self.assertIsNone(worker._opener)

    def test_even_garbage_rows_offer_the_plan(self) -> None:
        fake = _FakeOdds(_odds())
        worker = self._worker(fake)
        self._tick_until_done(worker, self._garbage_rec(2))
        self.assertEqual(len(fake.calls), 1)
        board, sequence, hold, _pool, kwargs = fake.calls[0]
        # おじゃまも含めた盤面(22行座標)を渡し、スレッド数を抑える
        self.assertEqual(len(board), 18)
        self.assertTrue(all(r >= 20 for r, _c in board))
        self.assertEqual((sequence[:6], hold), (["I", "T", "S", "Z", "J", "L"], "O"))
        self.assertLess(kwargs["threads"], 16)
        run = worker._opener
        self.assertIsNotNone(run, "継続パフェの手順を提示していない")
        self.assertIs(run.template, _PC_ODDS_TEMPLATE)
        self.assertTrue(run.with_garbage)
        self.assertEqual(run.steps[0].cells, ((16, 0), (17, 0), (18, 0), (19, 0)))  # 20行座標
        self.assertIn("成功率80%", run.form.section)

    def test_low_rate_falls_back_to_ai_without_recomputing(self) -> None:
        fake = _FakeOdds(_odds(rate_success=30))
        worker = self._worker(fake)
        rec = self._garbage_rec(2)
        self._tick_until_done(worker, rec)
        self.assertIsNone(worker._opener)
        self._tick(worker, rec, 1000.2)
        self.assertEqual(len(fake.calls), 1, "同じ局面で計算し直している")

    def test_high_board_is_not_computed(self) -> None:
        fake = _FakeOdds(_odds())
        worker = self._worker(fake)
        rec = _recognition(current_piece="I", hold_piece="O", filled_cells=((12, 0), (19, 0)))
        self._tick_until_done(worker, rec)
        self.assertEqual(fake.calls, [])

    def test_garbage_rise_stops_the_plan(self) -> None:
        fake = _FakeOdds(_odds())
        worker = self._worker(fake)
        rec = self._garbage_rec(2)
        self._tick_until_done(worker, rec)
        self.assertIsNotNone(worker._opener)
        worker._update_opener(rec, locked_now=False, garbage_rise=1)
        self.assertIsNone(worker._opener, "せり上がっても継続パフェの手順を続けている")

    def _dpc_rec(self):
        # パフェ直後: 盤面が空、HOLDに前の袋のT、操作ミノIが袋の先頭(DPCを組める条件)
        return _recognition(current_piece="I", hold_piece="T", next_queue=("O", "T", "S", "Z", "J"))

    def test_template_first_prefers_the_dpc(self) -> None:
        fake = _FakeOdds(_odds(plan=(PCStep("I", ((21, 0), (21, 1), (21, 2), (21, 3)), False),)))
        worker = self._worker(fake, first=False)
        worker._opener_locks = 20
        self._tick_until_done(worker, self._dpc_rec())
        self.assertEqual(worker._opener.template.name_ja, "DPC")
        self.assertEqual(fake.calls, [])

    def test_pc_odds_first_prefers_the_continuous_pc(self) -> None:
        fake = _FakeOdds(_odds(plan=(PCStep("I", ((21, 0), (21, 1), (21, 2), (21, 3)), False),)))
        worker = self._worker(fake, first=True)
        worker._opener_locks = 20
        rec = self._dpc_rec()
        self._tick(worker, rec)
        self.assertIsNone(worker._opener, "計算中にDPCを始めた")
        self.assertTrue(worker._pc_odds_search.done.wait(5))
        self._tick(worker, rec, 1000.1)
        self.assertIs(worker._opener.template, _PC_ODDS_TEMPLATE)

    def test_falls_back_to_the_dpc_when_the_continuous_pc_is_unlikely(self) -> None:
        fake = _FakeOdds(_odds(rate_success=10))
        worker = self._worker(fake, first=True)
        worker._opener_locks = 20
        self._tick_until_done(worker, self._dpc_rec())
        self.assertEqual(worker._opener.template.name_ja, "DPC")


class TestBagPool(unittest.TestCase):
    def test_pool_after_the_visible_pieces(self) -> None:
        # 操作ミノが袋の2個目(通し番号8): 見えている6個で袋の最後(13番)まで → 次は新しい袋
        self.assertEqual(_bag_pool(8, list("SZTIJL")), frozenset())
        # 通し番号9から6個(9〜14): 14番は次の袋の先頭 → 残りはそれ以外の6種
        self.assertEqual(_bag_pool(9, list("SZTIJL")), frozenset("IOTSZJ"))
        # 袋の先頭から7個(7個目を補った): 次は新しい袋
        self.assertEqual(_bag_pool(7, list("SZTIJLO")), frozenset())


if __name__ == "__main__":
    unittest.main()
