"""ライン消去直後の盤面の誤読と、既存ブロックと重なった提示の取り消し(2026-09-26)のテスト。

実画面 debug_capture_20260926_075054 の22秒: テトリスの直後、盤面に重なる「TETRIS」の文字の下の
赤いブロックが空と読まれ(文字の部分は別の列でUNKNOWN)、その盤面でAIに質問したためOが既存ブロックと
重なる位置に提示され、文字が消えた後もそのまま残った。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.app import AssistWorker, _predict_board_after_line_clear  # noqa: E402
from tests.test_assist_worker import _make_calibration, _move, _recognition  # noqa: E402

# テトリス直前に確定していた盤面(ログの行10〜19。Iを左から2列目に入れて行12〜15が消える)
BEFORE_ROWS = (
    "...U.....L",
    "..ZZT..LLL",
    "I.ZTTTZJJJ",
    "I.LOOZZSSJ",
    "I.LOOZSSOO",
    "I.LLJJZSOO",
    "GGGGGGGGG.",
    "GGGGGGGGG.",
    ".GGGGGGGGG",
    ".GGGGGGGGG",
)
# 消去直後の読み取り: 行14の赤(列3)が文字に隠れて空、文字の部分(列4・列7)がUNKNOWN
MISREAD_ROWS = ("....U..U.L", "..ZZT..LLL", "GGGGGGGGG.", "GGGGGGGGG.", ".GGGGGGGGG", ".GGGGGGGGG")
EXPECTED_ROWS = ("...U.....L", "..ZZT..LLL", "GGGGGGGGG.", "GGGGGGGGG.", ".GGGGGGGGG", ".GGGGGGGGG")


def _key(rows: tuple[str, ...]) -> tuple[tuple[str | None, ...], ...]:
    rows = ("..........",) * (20 - len(rows)) + rows
    return tuple(tuple(None if ch == "." else ("UNKNOWN" if ch == "U" else ch) for ch in row) for row in rows)


def _cells(rows: tuple[str, ...]) -> tuple[tuple[int, int], ...]:
    top = 20 - len(rows)
    return tuple((top + i, c) for i, row in enumerate(rows) for c, ch in enumerate(row) if ch != ".")


class TestPredictBoardAfterLineClear(unittest.TestCase):
    def test_hidden_block_is_restored_and_text_noise_removed(self) -> None:
        predicted = _predict_board_after_line_clear(_key(BEFORE_ROWS), _key(MISREAD_ROWS))
        self.assertEqual(predicted, _key(EXPECTED_ROWS))

    def test_no_line_clear_returns_none(self) -> None:
        before = _key(BEFORE_ROWS)
        self.assertIsNone(_predict_board_after_line_clear(before, before))
        self.assertIsNone(_predict_board_after_line_clear(None, before))

    def test_noisy_read_is_not_mistaken_for_a_line_clear(self) -> None:
        # 読み取りでほとんどのブロックが消えた(光エフェクト等): 消去では説明できないので予測しない
        before = _key(("#########.", "#####....."))
        self.assertIsNone(_predict_board_after_line_clear(before, _key(("#.........",))))

    def test_single_line_clear_keeps_the_rest_of_the_placed_piece(self) -> None:
        # 最下段の空き1マスにLの縦棒の下端を入れて1列消し: Lの残り3マスは消えた行の外に残る
        before = _key(("..........", "..........", "#########."))
        after = _key(("........##", ".........#"))
        self.assertEqual(_predict_board_after_line_clear(before, after), after)


class TestWorkerUsesPredictedBoard(unittest.TestCase):
    def setUp(self) -> None:
        self.cold_clear = MagicMock()
        self.worker = AssistWorker(_make_calibration(), self.cold_clear, debug_log_path=None)
        self.received: list[object] = []
        self.worker.draw_data_ready.connect(self.received.append)

    def _tick(self, recognition, now: float) -> None:
        with patch("src.app.time.monotonic", return_value=now):
            with patch("src.app.recognize", return_value=recognition):
                self.worker._tick_once(capture=MagicMock())

    def test_ai_gets_the_predicted_board_right_after_a_tetris(self) -> None:
        self.cold_clear.poll_suggestion.return_value = None
        before = _recognition(current_piece="I", filled_cells=_cells(BEFORE_ROWS), settled_top_row=10)
        self._tick(before, 1000.0)
        self._tick(before, 1000.05)
        self.cold_clear.start_thinking.reset_mock()
        misread = _recognition(
            current_piece="O",
            filled_cells=_cells(MISREAD_ROWS),
            next_queue=("L", "J", "S", "Z", "I"),
            settled_top_row=14,
        )
        self._tick(misread, 1000.1)
        self.cold_clear.start_thinking.assert_called_once()
        board = self.cold_clear.start_thinking.call_args[0][0]
        self.assertIsNotNone(board.grid[14][3], "文字に隠れた赤いブロックが空のままAIに渡った")
        self.assertIsNone(board.grid[14][4], "文字の誤読(UNKNOWN)がAIに渡った")
        self.assertIsNone(board.grid[14][7])

    def test_suggestion_overlapping_a_block_is_cancelled_and_recomputed(self) -> None:
        # 提示の一部(左下)に後から既存ブロックが見えるようになった(文字が消えた等)
        base = tuple((19, c) for c in range(7))
        self.cold_clear.poll_suggestion.return_value = _move("O", landing_cells=[(17, 5), (17, 6), (18, 5), (18, 6)])
        first = _recognition(current_piece="O", filled_cells=base)
        self._tick(first, 1000.0)
        self.assertEqual(self.received[-1].piece, "O")
        self.cold_clear.start_thinking.reset_mock()
        self.cold_clear.poll_suggestion.return_value = None
        blocked = _recognition(current_piece="O", filled_cells=base + ((18, 5),))
        self._tick(blocked, 1000.05)
        self.cold_clear.start_thinking.assert_not_called()  # 1tickだけなら取り消さない(置いた瞬間の光等)
        self._tick(blocked, 1000.1)
        self.assertIsNone(self.received[-1], "重なった提示が消えていない")
        self.cold_clear.start_thinking.assert_called_once()

    def test_placing_on_the_suggestion_is_not_treated_as_interference(self) -> None:
        # 提示どおりに置いた(4マスすべて埋まった)場合は取り消し・再計算の対象外
        base = ((19, 0), (19, 1), (19, 2), (19, 3), (19, 4))
        cells = [(18, 5), (18, 6), (19, 5), (19, 6)]
        self.cold_clear.poll_suggestion.return_value = _move("O", landing_cells=cells)
        self._tick(_recognition(current_piece="O", filled_cells=base), 1000.0)
        self.cold_clear.start_thinking.reset_mock()
        self.cold_clear.poll_suggestion.return_value = None
        placed = _recognition(current_piece="O", filled_cells=base + tuple(cells))
        self._tick(placed, 1000.05)
        self._tick(placed, 1000.1)
        self.cold_clear.start_thinking.assert_not_called()


if __name__ == "__main__":
    unittest.main()
