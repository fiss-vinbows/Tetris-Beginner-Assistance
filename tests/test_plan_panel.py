"""情報パネルの「狙い」「今の手」(src/app.py の plan_panel_text)のテスト。

【2026-10-31・利用者の要望】PBA のように、狙っている手(テンプレの名前など)と今の手を情報パネルに出す。
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tests.config_isolation  # noqa: E402,F401
from PyQt6 import QtWidgets  # noqa: E402

from src.app import ControlBadge, plan_panel_text  # noqa: E402
from src.engine.cold_clear_client import ColdClearMove  # noqa: E402
from src.engine.board_state import BoardState  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def _move(piece, cells, use_hold=False, spin="none"):
    return ColdClearMove(piece=piece, landing_cells=cells, use_hold=use_hold, nodes=0, nps=0.0, placement={"spin": spin})


class TestPlanPanelText(unittest.TestCase):
    def test_template_aim_and_plain_move(self) -> None:
        text = plan_panel_text(BoardState(), _move("L", [(19, 0), (19, 1), (19, 2), (18, 2)]), "開幕テンプレ TKI")
        self.assertEqual(text, "狙い: 開幕テンプレ TKI\n今の手: L")

    def test_ai_move_with_hold_and_tetris(self) -> None:
        board = BoardState()
        for r in range(16, 20):
            for c in range(1, 10):
                board.grid[r][c] = "GARBAGE"
        board.grid[15][5] = "GARBAGE"  # 全消しにならないように
        text = plan_panel_text(board, _move("I", [(16, 0), (17, 0), (18, 0), (19, 0)], use_hold=True), None)
        self.assertEqual(text, "狙い: 定型なし(AIの手)\n今の手: I(HOLDして) 4ライン消し(テトリス)")

    def test_tspin_double(self) -> None:
        board = BoardState()
        for c in range(10):
            if c not in (3, 4, 5):
                board.grid[18][c] = "GARBAGE"
            if c != 4:
                board.grid[19][c] = "GARBAGE"
        board.grid[17][3] = "GARBAGE"
        board.grid[0][0] = "GARBAGE"
        text = plan_panel_text(board, _move("T", [(18, 3), (18, 4), (18, 5), (19, 4)], spin="full"), None)
        self.assertIn("今の手: T Tスピンダブル(TSD)", text)


class TestBadgeShowsPlan(unittest.TestCase):
    def test_set_plan(self) -> None:
        badge = ControlBadge(on_stop=lambda: None)
        try:
            badge.set_plan("狙い: 開幕テンプレ TKI\n今の手: L")
            self.assertEqual(badge.info.label.text(), "支援モード中\n狙い: 開幕テンプレ TKI\n今の手: L")
        finally:
            badge.close()

    @unittest.skipUnless((Path(__file__).resolve().parent.parent / "src" / "auto").is_dir(), "全自動(非公開)が無い")
    def test_auto_badge_keeps_status_and_plan(self) -> None:
        from src.auto.panel import AutoControlBadge

        badge = AutoControlBadge(on_stop=lambda: None, stop_key="F8")
        try:
            badge.set_plan("狙い: 定型なし(AIの手)\n今の手: O")
            badge.set_status("動いています")
            self.assertEqual(badge.info.label.text(), "全自動モード中(F8で停止)\n動いています\n狙い: 定型なし(AIの手)\n今の手: O")
        finally:
            badge.close()


if __name__ == "__main__":
    unittest.main()
