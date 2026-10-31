"""パフェ探索を別プロセスで動かす(src/education/pc_process.py)のテスト。

【2026-10-04・利用者の指摘(シミュレーターが重い)】裏のスレッドで探すとGILを取り合い、キー入力・画面の更新が
最大1秒止まっていた。別のプロセスで探す。中あけRENの練習中はパフェを探さない。
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tests.config_isolation  # noqa: E402,F401
from src.education.advisor import Advisor, manual_templates  # noqa: E402
from src.education.pc_process import PcSearchProcess  # noqa: E402
from src.education.pc_search import TIMEOUT, find_perfect_clear  # noqa: E402
from src.education.rules import GameState  # noqa: E402
from tests.test_education_advisor import FakeEngine  # noqa: E402

# 2段パフェ: 下2段が左6列埋まり、右4列にI横2本で消える(I・Iが見えている)
BOARD = frozenset((r, c) for r in (20, 21) for c in range(6))
SEQUENCE = ["I", "I", "O", "T", "S"]


class TestPcSearchProcess(unittest.TestCase):
    def setUp(self) -> None:
        self.process = PcSearchProcess()

    def tearDown(self) -> None:
        self.process.close()

    def test_same_result_as_in_process(self) -> None:
        expected = find_perfect_clear(BOARD, SEQUENCE, None)
        self.assertTrue(expected, "前提: パフェが見つかる局面")
        found = self.process.submit(BOARD, SEQUENCE, None, True, 3.0).result(timeout=60)
        self.assertEqual(found, expected)

    def test_new_request_cancels_the_old_one(self) -> None:
        self.process.submit(BOARD, SEQUENCE, None, True, 3.0).result(timeout=60)  # 子プロセスを起動しておく
        # 空の盤面・7個で長く探す依頼を出した直後に次の依頼を出すと、前の探索は打ち切られてすぐ次へ移る
        long_one = self.process.submit(frozenset(), list("IOTSZJL"), None, True, 30.0)
        start = time.monotonic()
        quick = self.process.submit(BOARD, SEQUENCE, None, True, 3.0)
        self.assertTrue(quick.result(timeout=60))
        self.assertLess(time.monotonic() - start, 10, "前の探索が打ち切られていない")
        self.assertEqual(long_one.result(timeout=60), TIMEOUT, "打ち切られた探索は時間切れ扱い(結果は使わない)")


class TestNoPcSearchInRenPractice(unittest.TestCase):
    def test_ren_practice_skips_pc_search(self) -> None:
        advisor = Advisor(engine_factory=FakeEngine, odds_search=lambda *a, **k: None, pc_async=True)
        advisor.preferred_id = next(iter(manual_templates()))
        advisor.update(GameState.new(4), now=0.0)
        self.assertIsNone(advisor._pc_process, "中あけRENの練習中にパフェを探している")
        self.assertFalse(advisor.pc_pending)
        advisor.close()


if __name__ == "__main__":
    unittest.main()
