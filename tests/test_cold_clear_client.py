"""Cold Clear 2連携(cold_clear_client.py)のテスト。

座標変換ロジックはプロセス起動なしで検証できるが、実際の思考結果を
問い合わせるテストはCold Clear 2の実行ファイルが必要なため、
存在しない環境（未ビルド）では自動的にスキップする。
"""

from __future__ import annotations

import sys
import queue
import unittest
from unittest.mock import MagicMock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine.board_state import BoardState
from src.engine.cold_clear_client import (
    COLD_CLEAR_EXE,
    ColdClearClient,
    board_state_to_tbp_board,
    location_to_board_cells,
)

_HAS_COLD_CLEAR = COLD_CLEAR_EXE.exists()


class TestPlanParsing(unittest.TestCase):
    """suggestionの読み筋(plan。このフォーク独自のTBP拡張)の解釈。"""

    def _client_with_response(self, response: dict):
        client = ColdClearClient.__new__(ColdClearClient)
        client._board_height = 20
        client._send = MagicMock()
        client._recv = MagicMock(return_value=response)
        return client

    def test_plan_after_the_first_move_is_converted_to_board_cells(self) -> None:
        first = {"location": {"type": "O", "orientation": "north", "x": 8, "y": 0}, "spin": "none"}
        second = {"location": {"type": "T", "orientation": "north", "x": 4, "y": 0}, "spin": "none"}
        third = {"location": {"type": "I", "orientation": "north", "x": 1, "y": 0}, "spin": "none"}
        client = self._client_with_response(
            {"type": "suggestion", "moves": [first], "plan": [first, second, third], "move_info": {}}
        )

        move = client.poll_suggestion("T")

        self.assertEqual(move.piece, "O")
        self.assertEqual([piece for piece, _cells in move.plan], ["T", "I"])
        self.assertEqual(
            sorted(move.plan[0][1]),
            sorted(location_to_board_cells("T", "north", 4, 0, 20)),
        )

    def test_missing_plan_field_is_tolerated(self) -> None:
        # 本家のCold Clear 2(plan無し)でも動くこと。
        first = {"location": {"type": "O", "orientation": "north", "x": 8, "y": 0}, "spin": "none"}
        client = self._client_with_response({"type": "suggestion", "moves": [first], "move_info": {}})
        move = client.poll_suggestion("T")
        self.assertEqual(move.plan, [])


class TestBeginnerConfig(unittest.TestCase):
    """初心者向けの評価設定(config/cold_clear_beginner.json)の回帰テスト。

    実機で「難しい操作で現実的でない」提示(横向きIの下へSを潜り込ませる手)
    が報告された。ソフトドロップ距離への罰則を大きくし、Tスピン関連の
    加点を0にすることで、回転→横移動→ハードドロップで到達できる手を
    優先させる(自己対戦120手で潜り込み手 11件→0件)。
    """

    def test_config_file_exists_and_penalizes_softdrop(self) -> None:
        import json

        from src.engine.cold_clear_client import COLD_CLEAR_CONFIG

        self.assertTrue(COLD_CLEAR_CONFIG.exists(), "初心者向け設定ファイルが無い")
        weights = json.loads(COLD_CLEAR_CONFIG.read_text(encoding="utf-8"))["freestyle_weights"]
        self.assertLessEqual(weights["softdrop"], -5.0, "ソフトドロップの罰則が弱い")
        self.assertEqual(weights["tslot"], [0.0, 0.0, 0.0, 0.0])
        self.assertEqual(weights["spin_clears"], [0.0, 0.0, 0.0, 0.0])

    def test_client_passes_the_config_to_the_process(self) -> None:
        from unittest.mock import patch

        from src.engine import cold_clear_client as module

        with patch.object(module.subprocess, "Popen") as popen:
            popen.return_value.stdout = MagicMock()
            popen.return_value.stdin = MagicMock()
            try:
                # 起動後のinfo待ちで失敗するのは想定内(引数だけ検証する)。
                with patch.object(module.ColdClearClient, "_recv", return_value={"type": "info"}):
                    with patch.object(module.ColdClearClient, "_send"):
                        module.ColdClearClient()
            except Exception:  # noqa: BLE001
                pass
        args = popen.call_args.args[0]
        self.assertIn("--config", args, "初心者向け設定がプロセスに渡されていない")


class TestDrainPending(unittest.TestCase):
    """新しい局面を渡す直前に、未読の応答を捨てることの回帰テスト。

    start_thinkingは送信するだけで応答を読まない。一方poll_suggestionは
    「suggestを送って1行読む」ため、前の局面に対する応答が残っていると、
    次に読んだ1行がその古い応答になる。要求と応答の対応が1つずつずれていき、
    ずれが溜まると最後は読み取りがブロックして応答待ちのタイムアウトになる
    (実機 crash_log.txt 2026-09-10T19:25:16)。
    """

    def _bare_client(self):
        # 実際のプロセスを起動せずに、キュー操作だけを検証する。
        client = ColdClearClient.__new__(ColdClearClient)
        client._read_queue = queue.Queue()
        return client

    def test_pending_responses_are_discarded(self) -> None:
        client = self._bare_client()
        for line in ('{"type":"suggestion"}', '{"type":"suggestion"}', '{"type":"info"}'):
            client._read_queue.put(line)

        client._drain_pending()

        self.assertTrue(client._read_queue.empty())

    def test_process_exit_marker_is_kept(self) -> None:
        # Noneはプロセス終了(EOF)の合図。捨てると異常終了に気づけなくなる。
        client = self._bare_client()
        client._read_queue.put('{"type":"suggestion"}')
        client._read_queue.put(None)

        client._drain_pending()

        self.assertIsNone(client._read_queue.get_nowait())
        self.assertTrue(client._read_queue.empty())


class TestStartThinkingDrains(unittest.TestCase):
    def test_start_thinking_discards_responses_for_the_previous_position(self) -> None:
        # 新しい局面を渡す時点で、それ以前の応答はすべて古い局面に対する
        # ものなので捨てること。捨てないと要求と応答の対応がずれていく。
        client = ColdClearClient.__new__(ColdClearClient)
        client._read_queue = queue.Queue()
        client._board_height = 20
        client._send = MagicMock()
        client._read_queue.put('{"type":"suggestion"}')

        client.start_thinking(BoardState(), "T", None, ["O", "L", "J", "S", "Z"])

        self.assertTrue(client._read_queue.empty(), "古い応答が残っている")
        client._send.assert_called_once()


class TestCloseIsRobust(unittest.TestCase):
    def test_close_survives_broken_pipes(self) -> None:
        # 実機の回帰テスト(crash_log.txt 2026-09-10T19:25:29)。
        # プロセスが既に異常終了していると、パイプの後始末自体がOSErrorを
        # 投げる。後始末の失敗で支援モードの停止処理が中断してはならない。
        client = ColdClearClient.__new__(ColdClearClient)
        proc = MagicMock()
        proc.stdin.write.side_effect = OSError(22, "Invalid argument")
        proc.stdin.close.side_effect = OSError(22, "Invalid argument")
        proc.stdout.close.side_effect = OSError(22, "Invalid argument")
        proc.terminate.side_effect = OSError(22, "Invalid argument")
        client._proc = proc

        client.close()  # 例外が外へ出ないこと


class TestCoordinateConversion(unittest.TestCase):
    """TBPの座標系(下から数えた行、中心+回転オフセット)からBoardState座標系への変換。

    実際にCold Clear 2から返ってきた既知の応答(例: 空盤面でIをnorthで
    x=4,y=0に置く)を元に、期待される着地マスと突き合わせて検証する。
    """

    def test_i_piece_north_orientation(self):
        # 実機で確認済み: 空盤面、Iをnorth、x=4,y=0 -> 最下段の列3,4,5,6
        cells = location_to_board_cells("I", "north", x=4, y=0, board_height=20)
        self.assertEqual(sorted(cells), [(19, 3), (19, 4), (19, 5), (19, 6)])

    def test_o_piece_north_orientation(self):
        # 実機で確認済み: 空盤面、Oをnorth、x=0,y=0 -> 最下段2行×列0,1
        cells = location_to_board_cells("O", "north", x=0, y=0, board_height=20)
        self.assertEqual(sorted(cells), [(18, 0), (18, 1), (19, 0), (19, 1)])

    def test_t_piece_north_orientation(self):
        # 実機で確認済み: 空盤面、Tをnorth、x=1,y=0
        cells = location_to_board_cells("T", "north", x=1, y=0, board_height=20)
        self.assertEqual(sorted(cells), [(18, 1), (19, 0), (19, 1), (19, 2)])

    def test_z_piece_north_orientation(self):
        # 実機で確認済み: 空盤面、Zをnorth、x=1,y=0
        cells = location_to_board_cells("Z", "north", x=1, y=0, board_height=20)
        self.assertEqual(sorted(cells), [(18, 0), (18, 1), (19, 1), (19, 2)])

    def test_j_piece_north_orientation(self):
        # 実機で確認済み: 空盤面、Jをnorth、x=1,y=0
        cells = location_to_board_cells("J", "north", x=1, y=0, board_height=20)
        self.assertEqual(sorted(cells), [(18, 0), (19, 0), (19, 1), (19, 2)])

    def test_s_piece_north_orientation(self):
        # 実機で確認済み: 空盤面、Sをnorth、x=8,y=0
        cells = location_to_board_cells("S", "north", x=8, y=0, board_height=20)
        self.assertEqual(sorted(cells), [(18, 8), (18, 9), (19, 7), (19, 8)])

    def test_l_piece_north_orientation(self):
        # 実機で確認済み: 空盤面、Lをnorth、x=8,y=0
        cells = location_to_board_cells("L", "north", x=8, y=0, board_height=20)
        self.assertEqual(sorted(cells), [(18, 9), (19, 7), (19, 8), (19, 9)])

    def test_board_state_to_tbp_board_flips_vertically_and_maps_garbage(self):
        board = BoardState()
        board.grid[19][0] = "T"  # BoardStateの最下段(row=19)
        board.grid[19][1] = "GARBAGE"

        tbp = board_state_to_tbp_board(board)

        # BoardStateのrow=19(最下段)はTBPのy=0(最下段)に対応する
        self.assertEqual(tbp[0][0], "T")
        self.assertEqual(tbp[0][1], "G")
        # 最上段(BoardStateのrow=0)はTBPのy=19相当で、空のはず
        self.assertTrue(all(cell is None for cell in tbp[19]))


@unittest.skipUnless(_HAS_COLD_CLEAR, "Cold Clear 2が未ビルドのためスキップ(external/cold-clear-2)")
class TestColdClearIntegration(unittest.TestCase):
    """実際にCold Clear 2プロセスを起動して確認する統合テスト。"""

    def setUp(self):
        self.client = ColdClearClient()

    def tearDown(self):
        self.client.close()

    def test_fills_the_only_open_column_with_vertical_I(self):
        board = BoardState()
        for c in range(10):
            if c != 5:
                for r in [16, 17, 18, 19]:
                    board.grid[r][c] = "X"

        move = self.client.suggest_move(board, "I", None, ["O", "T", "L"], think_seconds=0.3)

        self.assertIsNotNone(move)
        self.assertEqual(move.piece, "I")
        self.assertEqual({c for _r, c in move.landing_cells}, {5})

    def test_does_not_crash_on_board_with_fully_filled_rows(self):
        # 盤面認識のタイミング次第で、まれに「本来ならゲーム側で即座に
        # 消去されているはずの、完全に埋まった行」が紛れ込むことがある
        # （ライン消去演出中に認識した場合など）。この状態をそのまま
        # Cold Clear 2に渡すと、内部の評価ロジックが範囲外アクセスで
        # Rustパニックを起こしプロセスごとクラッシュすることを実際に
        # 確認した（the len is 5 but the index is 16 のようなエラー）。
        # start_thinking内でclear_lines()を通して防いでいることを確認する。
        board = BoardState()
        for r in range(20):
            for c in range(10):
                if not (r < 4 and c == 4):
                    board.grid[r][c] = "X"

        move = self.client.suggest_move(board, "I", None, ["O", "T", "L"], think_seconds=0.2)

        self.assertIsNotNone(move, "クラッシュして提案が得られなかった")
        self.assertEqual(move.piece, "I")
        self.assertEqual({c for _r, c in move.landing_cells}, {4})

    def test_disallow_hold_forces_current_piece_to_be_used(self):
        # ホールドすればより良い手がありそうな局面を用意しても、
        # disallow_hold=Trueならuse_hold=Falseになるはず。
        board = BoardState()
        row = ["X", "X", None, None, None, "X", "X", "X", None, None]
        for c, v in enumerate(row):
            board.grid[19][c] = v

        move = self.client.suggest_move(
            board, "S", "Z", ["O", "J", "I", "T", "S"], think_seconds=0.2, disallow_hold=True
        )
        self.assertIsNotNone(move)
        self.assertFalse(move.use_hold)

    def test_start_thinking_then_poll_returns_progressively_more_nodes(self):
        board = BoardState()
        self.client.start_thinking(board, "I", None, ["O", "T", "S", "Z", "J"])

        import time

        time.sleep(0.05)
        first = self.client.poll_suggestion("I")
        time.sleep(0.2)
        second = self.client.poll_suggestion("I")

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertGreaterEqual(second.nodes, first.nodes)


if __name__ == "__main__":
    unittest.main()
