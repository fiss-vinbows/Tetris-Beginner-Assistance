"""AssistWorker._tick_once()の状態遷移ロジックのテスト。

ホールド振動防止(disallow_hold)、新規スポーン検知(significant_change)、
ポーリング間隔制御といった、これまで実機でしか検証できていなかった
複雑な状態遷移を、recognize()とColdClearClientをモック化して検証する。
「ホールドを提示する枠問題」「提案が2通り見える」等、過去に実機で
報告された不具合の多くがこのロジックに起因していたため、回帰保護として
重要度が高い。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt6 import QtWidgets

from src.app import (
    MAX_CONSECUTIVE_RECOGNITION_FAILURES,
    AssistWorker,
    RecognitionResult,
    _turn_key,
)
from src.capture.calibrate import CalibrationResult
from src.engine.board_state import BoardState
from src.engine.cold_clear_client import ColdClearMove

# PyQt6のシグナル/スロット機構にはQCoreApplicationのインスタンスが必要。
_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def _make_calibration() -> CalibrationResult:
    return CalibrationResult(
        board_origin_x=0,
        board_origin_y=0,
        board_width=580,
        board_height=1160,
        cell_size=58,
        board_cols=10,
        board_rows=20,
        hold_rect=(0, 0, 148, 88),
        next_rects=[(0, 0, 154, 90)] * 5,
    )


def _recognition(
    current_piece: str = "T",
    current_piece_min_row: int = 0,
    hold_piece: str | None = None,
    hold_known: bool = True,
    next_queue: tuple[str, ...] = ("O", "L", "J", "S", "Z"),
    next_slots_raw: tuple[str | None, ...] | None = None,
    filled_cells: tuple[tuple[int, int], ...] = (),
    settled_top_row: int = 20,
    raw_settled_top_row: int | None = None,
    pending_cells: tuple[tuple[int, int], ...] = (),
    pending_color_cells: tuple[tuple[int, int], ...] = (),
) -> RecognitionResult:
    board = BoardState()
    for r, c in filled_cells:
        board.grid[r][c] = "X"
    pending_grid: list[list[tuple[str | None] | None]] = [[None] * board.width for _ in range(board.height)]
    for r, c in pending_cells:
        pending_grid[r][c] = (None,)  # 「空」への変化を1回観測した保留状態
    for r, c in pending_color_cells:
        pending_grid[r][c] = ("O",)  # 別の色への変化を1回観測した保留状態(占有は不変)
    if next_slots_raw is None:
        # next_queueをそのまま5枠(欠番はNone)に展開する。認識失敗枠を
        # 意図的に挟みたいテストはnext_slots_rawを明示的に渡すこと。
        next_slots_raw = tuple(next_queue[i] if i < len(next_queue) else None for i in range(5))
    return RecognitionResult(
        current_piece=current_piece,
        current_piece_min_row=current_piece_min_row,
        hold_piece=hold_piece,
        hold_known=hold_known,
        next_queue=next_queue,
        next_slots_raw=next_slots_raw,
        board=board,
        board_key=tuple(tuple(row) for row in board.grid),
        settled_top_row=settled_top_row,
        raw_settled_top_row=raw_settled_top_row if raw_settled_top_row is not None else settled_top_row,
        pending_grid=pending_grid,
    )


def _move(
    piece: str,
    use_hold: bool = False,
    landing_cells: list[tuple[int, int]] | None = None,
) -> ColdClearMove:
    return ColdClearMove(
        use_hold=use_hold,
        piece=piece,
        landing_cells=landing_cells if landing_cells is not None else [(19, 0)],
        nodes=100,
        nps=1000.0,
        placement={"location": {"type": piece, "orientation": "north", "x": 1, "y": 0}, "spin": "none"},
    )


class TestAssistWorkerTickOnce(unittest.TestCase):
    def setUp(self) -> None:
        self.cold_clear = MagicMock()
        self.worker = AssistWorker(_make_calibration(), self.cold_clear, debug_log_path=None)
        self.received_draw_data: list[object] = []
        self.worker.draw_data_ready.connect(self.received_draw_data.append)

    def test_new_spawn_calls_start_thinking_and_emits_suggestion(self) -> None:
        self.cold_clear.poll_suggestion.return_value = _move("T")
        with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
            self.worker._tick_once(capture=MagicMock())

        self.cold_clear.start_thinking.assert_called_once()
        _, kwargs = self.cold_clear.start_thinking.call_args
        self.assertFalse(kwargs.get("disallow_hold", False))
        self.assertEqual(len(self.received_draw_data), 1)
        self.assertEqual(self.received_draw_data[0].piece, "T")

    def test_same_piece_without_poll_interval_elapsed_does_not_call_start_thinking_again(self) -> None:
        self.cold_clear.poll_suggestion.return_value = _move("T")
        with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
            self.worker._tick_once(capture=MagicMock())  # 1回目: 新規スポーン
            self.cold_clear.start_thinking.reset_mock()
            self.worker._tick_once(capture=MagicMock())  # 2回目: 同じミノ、変化なし

        # 同じミノを操作中は、ミノがスポーンした時にしかstart_thinkingを
        # 呼ばない(継続思考を無駄にリセットしないため)。
        self.cold_clear.start_thinking.assert_not_called()

    def test_hold_right_after_a_hold_operation_disallows_hold_again(self) -> None:
        # シナリオ: ミノAが来てBをホールド(hold_piece: None→A)し、
        # 次にミノBが操作対象になる。この直後のtickではdisallow_hold=Trueに
        # なるべき(ホールドの振動を防ぐため)。
        self.cold_clear.poll_suggestion.return_value = _move("A2")
        with patch("src.app.recognize", return_value=_recognition(current_piece="A1", hold_piece=None)):
            self.worker._tick_once(capture=MagicMock())  # 初回: hold_piece=None(UNKNOWNから変化なし)

        self.cold_clear.start_thinking.reset_mock()
        with patch(
            "src.app.recognize",
            # holdが空から埋まる初回のホールドは、通常スポーンと同じく
            # NEXTキューを消費する(ゲームルール上、空のholdへの初回投入だけは
            # 通常スポーンと区別がつかないため)。next_advancedを発火させる
            # ため、next_queueも進める。
            return_value=_recognition(current_piece="B1", hold_piece="A1", next_queue=("L", "J", "S")),
        ):
            self.worker._tick_once(capture=MagicMock())  # ホールド直後: hold_pieceがNone->A1に変化

        _, kwargs = self.cold_clear.start_thinking.call_args
        self.assertTrue(kwargs.get("disallow_hold", False))

    def test_hold_swap_without_next_advance_rethinks_the_swapped_position_immediately(self) -> None:
        # 【2026-09-11・実機ログで判明】以前は「ホールド交換はsignificant_
        # changeを発火させず、既存の提案が表示され続けるので正しい」として
        # start_thinkingを呼ばなかった。しかしCold Clear 2は交換前の局面を
        # 考え続けるため、その結果は手番照合で棄却され続け(交換19回に対し
        # 棄却57件=毎回きっかり3件)、3tick連続の食い違いで初めて思考を
        # やり直していた。交換を反映した時点で、交換後の局面(操作ミノ=
        # 元のHOLD、HOLD使用済み)を即座に渡し直すこと。
        same_next_queue = ("Z", "T", "L")
        self.cold_clear.poll_suggestion.return_value = _move("O")
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="O", hold_piece="I", next_queue=same_next_queue),
        ):
            self.worker._tick_once(capture=MagicMock())  # 初回: hold=Iで確定

        self.cold_clear.start_thinking.reset_mock()
        with patch(
            "src.app.recognize",
            # 本物のホールド操作でcurrentがI(=直前のhold)に変化。
            # NEXTキューは変化なし(ホールドはキューを消費しないため)。
            return_value=_recognition(current_piece="I", hold_piece="O", next_queue=same_next_queue),
        ):
            self.worker._tick_once(capture=MagicMock())

        self.cold_clear.start_thinking.assert_called_once()
        args, kwargs = self.cold_clear.start_thinking.call_args
        self.assertEqual(args[1], "I", "交換後の操作ミノで要求していない")
        self.assertEqual(args[2], "O", "交換後のHOLDで要求していない")
        self.assertTrue(kwargs.get("disallow_hold"), "交換後はHOLD使用済みのはず")
        # 手番キーも交換後の局面に更新され、以降の結果が棄却されないこと。
        self.assertEqual(self.worker._thinking_turn_key, ("I", "O", same_next_queue))

    def test_new_spawn_without_swap_trusts_fresh_hold_reading(self) -> None:
        # 実機動画(タイムスタンプ付き録画)で確認された不具合の回帰テスト:
        # たまたま同じ形のミノが連続スポーンし(7-bagの袋境界をまたいで
        # 同じ種類が連続することはあり得る)、かつその間に本当にホールドが
        # 使われていた場合、current_pieceの見た目だけでは「新規スポーン」
        # と判定できても「ホールドスワップ」とまでは判定できない
        # (current_pieceがholdの直前の値と一致しないため)。この場合、
        # HOLD欄の画像判定は静止画像でありスワップ直後の切り替え
        # アニメーションのような一時的な乱れがないため、正しく機能して
        # いることを直接確認した。それにも関わらず「スワップと確実に
        # 判定できない場合はholdを前回値のまま変化なしとみなす」実装だと、
        # 正しく読み取れている新しいhold値を誤って古い値で上書きして
        # しまっていた。スワップと確実に判定できるケース以外は、常に
        # HOLD欄の画像判定を信じるべき。
        self.cold_clear.poll_suggestion.return_value = _move("J")
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="J", hold_piece="L", next_queue=("Z", "T", "L")),
        ):
            self.worker._tick_once(capture=MagicMock())  # 初回: hold=Lで確定

        self.cold_clear.start_thinking.reset_mock()
        new_recognition = _recognition(
            # 新規スポーン(next_prefixの変化で検知)だが、たまたま同じ
            # "J"の形が連続。hold欄は本物のホールド操作で正しく"J"に
            # 変化している(この場合、直前のholdがLでcurrentがJなので、
            # current==old_holdではなくスワップとは確実に判定できない)。
            current_piece="J", hold_piece="J", next_queue=("T", "L", "S"),
        )
        # 【2026-09-07】next_prefix_changedは2tick連続確認のデバウンスを
        # 経るようになったため、同じ新しいnext_prefixを2回連続で与える。
        with patch("src.app.recognize", return_value=new_recognition):
            self.worker._tick_once(capture=MagicMock())  # 1tick目: まだ確定しない(保留)
        with patch("src.app.recognize", return_value=new_recognition):
            self.worker._tick_once(capture=MagicMock())  # 2tick連続で確定

        args = self.cold_clear.start_thinking.call_args.args
        self.assertEqual(args[2], "J")  # 前回値"L"ではなく、正しく読み取れた"J"
        self.assertEqual(self.worker._prev_hold_piece, "J")

    def test_hold_piece_noise_during_same_piece_is_ignored(self) -> None:
        # 実機ログで確認された不具合の回帰テスト: ホールドは現在操作中
        # ミノとの入れ替えでしか変化しないというゲームルール上、同じミノを
        # 操作中にHOLD欄の認識結果が変わることはあり得ない。以前はこれを
        # 「認識が一瞬ブレて後から訂正された」とみなしCold Clear 2への
        # 再送信で"訂正"していたが、この前提自体が誤りだった: current
        # picture(操作中ミノ)を確定的な手がかりとして使えるにも関わらず
        # HOLD欄の画像判定を信じ直すと、逆に本物のノイズをそのまま
        # 採用してしまう(実機ログで、O→Iへの正当なホールド操作の直後、
        # 新しいholdが理論上唯一あり得る値"O"ではなく無関係な"J"に化ける
        # 不具合として確認された)。同じミノを操作中のHOLD欄の変化は
        # 常にノイズとして無視し、start_thinking自体を呼ばないべき。
        self.cold_clear.poll_suggestion.return_value = _move("A2")
        with patch("src.app.recognize", return_value=_recognition(current_piece="A1", hold_piece=None)):
            self.worker._tick_once(capture=MagicMock())  # 初回: hold=None

        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="B1", hold_piece="A1"),
        ):
            self.worker._tick_once(capture=MagicMock())  # ホールド直後: disallow_hold=Trueで確定

        self.cold_clear.start_thinking.reset_mock()
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch(
                "src.app.recognize",
                # 同じB1を操作中なのにHOLD欄の認識が一瞬ブレる(ノイズ)
                return_value=_recognition(current_piece="B1", hold_piece="NOISE"),
            ):
                self.worker._tick_once(capture=MagicMock())

        # currentが変わっていない以上、ホールドの変化はゲームルール上
        # あり得ないノイズなので、再送信自体が起きないべき。
        self.cold_clear.start_thinking.assert_not_called()

    def test_next_advance_alone_triggers_significant_change(self) -> None:
        # 【2026-09-07・全面設計変更】current_pieceの見た目(落下中のミノの
        # 形状マッチング結果)が変わらなくても、ネクスト欄5枠のうち
        # 認識できている枠が変化していれば、それだけで新規スポーンとして
        # 検知すべき(7-bagで同じミノ種が連続する場合でも確実に検知できる)。
        # 5枠すべてが正しく認識できていれば、1tickの変化で即座に確定する
        # (2tickの確認待ちは不要。ネクストキューは新規スポーン時にしか
        # 動かないというルールを直接の根拠とするため)。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="T", next_queue=("O", "L", "J", "S", "Z")),
        ):
            self.worker._tick_once(capture=MagicMock())

        self.cold_clear.start_thinking.reset_mock()
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="T", next_queue=("L", "J", "S", "Z", "I")),
        ):
            self.worker._tick_once(capture=MagicMock())

        self.cold_clear.start_thinking.assert_called_once()

    def test_unrecognized_next_slot_is_pending_and_does_not_block_or_falsely_trigger(self) -> None:
        # 【2026-09-07・ユーザー指示】ネクスト欄5枠のうち認識できなかった
        # 枠(None)は「保留」として比較対象から除外すべきで、(1)他の枠に
        # 変化がなければ誤って新規スポーン扱いにしてはいけない、(2)後の
        # tickでその枠が認識できるようになれば、変化なしとして確定値に
        # 反映されるべき(退行はせず前進のみ)。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="T", next_queue=("O", "L", "J", "S", "Z")),
        ):
            self.worker._tick_once(capture=MagicMock())

        self.cold_clear.start_thinking.reset_mock()
        # 1枠目(O)だけが認識失敗(None)。残り4枠は変化なし。
        with patch(
            "src.app.recognize",
            return_value=_recognition(
                current_piece="T",
                next_queue=("L", "J", "S", "Z"),
                next_slots_raw=(None, "L", "J", "S", "Z"),
            ),
        ):
            self.worker._tick_once(capture=MagicMock())

        # 保留枠があるだけで、他の枠は変化していないため新規スポーンでは
        # ないと判定されるべき。
        self.cold_clear.start_thinking.assert_not_called()

    def test_next_advance_detected_even_when_one_slot_stays_unrecognized(self) -> None:
        # 【2026-09-07・ユーザー指示の核心】ネクスト欄5枠のうち1〜2枠が
        # 認識できなくても、残りの枠だけで新規スポーンを正しく検知できる
        # べき(5枠中2枠以上さえ認識できていれば、1つの誤読・認識失敗が
        # そのまま誤判定に直結しない)。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="T", next_queue=("O", "L", "J", "S", "Z")),
        ):
            self.worker._tick_once(capture=MagicMock())

        self.cold_clear.start_thinking.reset_mock()
        # ("O","L","J","S","Z")が1つ進んで("L","J","S","Z",新規)になった状態。
        # 3枠目と5枠目は認識失敗(None)だが、読めた3枠が「1つ進んだ」で
        # 矛盾なく説明できるので検知できるべき。
        with patch(
            "src.app.recognize",
            return_value=_recognition(
                current_piece="T",
                next_queue=("L", "J", "Z"),
                next_slots_raw=("L", "J", None, "Z", None),
            ),
        ):
            self.worker._tick_once(capture=MagicMock())

        self.cold_clear.start_thinking.assert_called_once()

    def test_single_misread_slot_does_not_advance_the_queue(self) -> None:
        # 実機の回帰テスト: 「読めた枠のどれか1つでも前回と違えば進行」と
        # みなしていたため、1枠の誤読がそのまま1手の進行として記録されて
        # いた。確定値は自分自身を基準に更新されるため、一度ずれると元に
        # 戻らず累積する。実機ではnext_advancedが168回/分(通常の3〜5倍)
        # 発火し、ずれた履歴から求めた操作ミノでAIへ質問→棄却→再同期→
        # 再計算という高速振動になっていた。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="T", next_queue=("O", "L", "J", "S", "Z")),
        ):
            self.worker._tick_once(capture=MagicMock())
            # 2回目の観測で基準を確定させる(1回だけの基準は暫定。残課題2-2)。
            self.worker._tick_once(capture=MagicMock())

        self.cold_clear.start_thinking.reset_mock()
        # 3枠目だけが誤読されている(他の4枠は前回と同じ=進んでいない)。
        with patch(
            "src.app.recognize",
            return_value=_recognition(
                current_piece="T",
                next_queue=("O", "L", "Z", "S", "Z"),
                next_slots_raw=("O", "L", "Z", "S", "Z"),
            ),
        ):
            self.worker._tick_once(capture=MagicMock())

        self.cold_clear.start_thinking.assert_not_called()
        self.assertEqual(
            self.worker._confirmed_next_slots,
            ("O", "L", "J", "S", "Z"),
            "1枠の誤読で確定値がずれている",
        )

    def test_mid_transition_reading_does_not_start_a_cascade(self) -> None:
        # 実機で起きた高速振動の回帰テスト。ネクスト欄の各枠は同時に更新
        # されるとは限らず、1枠だけ先に新しい値になった「遷移途中」の画像が
        # 撮れることがある。旧規則(1枠でも違えば進行)はこれを進行とみなし、
        # 確定値を1つずらしてしまう。確定値は自分自身を基準に更新されるため
        # 一度ずれると元に戻らず、以降は毎フレーム「違う」と判定されて
        # 進行が連鎖する。実機の録画では、真の進行131回に対して旧規則は
        # 2836回も進行と判定していた。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="T", next_queue=("O", "L", "J", "S", "Z")),
        ):
            self.worker._tick_once(capture=MagicMock())
            # 2回目の観測で基準を確定させる(1回だけの基準は暫定。残課題2-2)。
            self.worker._tick_once(capture=MagicMock())

        self.cold_clear.start_thinking.reset_mock()
        # 1枠目だけが次の値("L")に変わり、残りはまだ古いままの遷移途中。
        with patch(
            "src.app.recognize",
            return_value=_recognition(
                current_piece="T",
                next_queue=("L", "L", "J", "S", "Z"),
                next_slots_raw=("L", "L", "J", "S", "Z"),
            ),
        ):
            self.worker._tick_once(capture=MagicMock())

        self.cold_clear.start_thinking.assert_not_called()
        self.assertEqual(self.worker._confirmed_next_slots, ("O", "L", "J", "S", "Z"))

        # 全枠が更新された正しい画像が来たら、そこで初めて1つ進んだと判定する。
        with patch(
            "src.app.recognize",
            return_value=_recognition(
                current_piece="T",
                next_queue=("L", "J", "S", "Z", "T"),
                next_slots_raw=("L", "J", "S", "Z", "T"),
            ),
        ):
            self.worker._tick_once(capture=MagicMock())
        self.cold_clear.start_thinking.assert_called_once()
        self.assertEqual(self.worker._confirmed_next_slots, ("L", "J", "S", "Z", "T"))

    def test_misread_first_frame_is_replaced_instead_of_blocking_progress(self) -> None:
        # 【残課題2-2・2026-09-11実機ログ】支援モード開始直後の最初の1枚が
        # ('J','O','S','T','L')と読まれたが、実際は('O','S','T','Z','L')
        # だった。以前は最初の1枚を無検証で基準にしていたため、L/Zの1枠の
        # 食い違いでどの移動量でも説明できず、再アンカー(15tick)まで
        # 進行が止まり、2手目の提案が出なかった。1回だけの基準は暫定とし、
        # 整合しない観測が来たら待たずに差し替えること。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        misread = ("J", "O", "S", "T", "L")
        actual = ("O", "S", "T", "Z", "L")
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="J", next_queue=misread, next_slots_raw=misread),
        ):
            self.worker._tick_once(capture=MagicMock())
        self.assertEqual(self.worker._confirmed_next_slots, misread)

        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="J", next_queue=actual, next_slots_raw=actual),
        ):
            self.worker._tick_once(capture=MagicMock())
        self.assertEqual(self.worker._confirmed_next_slots, actual, "誤読した初回の基準が残っている")

        # 差し替えた基準も暫定: 同じ観測がもう一度来て確定する。
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="J", next_queue=actual, next_slots_raw=actual),
        ):
            self.worker._tick_once(capture=MagicMock())

        # ここでJを置き、NEXTが1つ進む。2手目(O)の提案が待たずに出ること。
        self.cold_clear.start_thinking.reset_mock()
        advanced = ("S", "T", "Z", "L", "I")
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece=None, next_queue=advanced, next_slots_raw=advanced),
        ):
            self.worker._tick_once(capture=MagicMock())
        self.cold_clear.start_thinking.assert_called_once()
        self.assertEqual(self.worker._last_current_piece, "O", "2手目の操作ミノが履歴から決まっていない")
        self.assertEqual(self.worker._confirmed_next_slots, advanced)

    def test_persistent_single_slot_misread_is_corrected_instead_of_blocking_progress(self) -> None:
        # 【残課題2-2・2026-09-11実機ログ(2回目)】ゲーム開始のカウントダウン
        # 表示がNEXT5枠目に重なり、5枠目が数秒間一貫して「L」と誤読された
        # (実際はT)。同じ誤読が続くため「別の観測との一致」では除外できず、
        # 基準('J','L','S','I','L')が確定してしまう。Jがスポーンして
        # ('L','S','I','T','Z')が観測されると、移動量1でL/Tの1枠だけが
        # 矛盾し、不一致ゼロを要求する推定はどの移動量も返せず、再アンカー
        # まで進行が止まった。1枠だけの矛盾が2tick続いたら基準のその枠を
        # 置き換え、進行を判定すること。
        self.cold_clear.poll_suggestion.return_value = _move("J")
        misread = ("J", "L", "S", "I", "L")
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="J", next_queue=misread, next_slots_raw=misread),
        ):
            for _ in range(3):  # カウントダウン中: 同じ誤読が続いて確定する
                self.worker._tick_once(capture=MagicMock())
        self.assertEqual(self.worker._confirmed_next_slots, misread)

        self.cold_clear.start_thinking.reset_mock()
        spawned = ("L", "S", "I", "T", "Z")
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece=None, next_queue=spawned, next_slots_raw=spawned),
        ):
            self.worker._tick_once(capture=MagicMock())  # 1回目: 矛盾を控える
            self.assertEqual(self.worker._confirmed_next_slots, misread)
            self.worker._tick_once(capture=MagicMock())  # 2回目: 5枠目を補正して進行

        self.assertEqual(self.worker._confirmed_next_slots, spawned, "5枠目の誤読が補正されていない")
        self.assertEqual(self.worker._last_current_piece, "J", "進行後の操作ミノが履歴から決まっていない")
        self.cold_clear.start_thinking.assert_called_once()

    def test_single_frame_conflict_does_not_rewrite_the_baseline(self) -> None:
        # 矛盾が1tickで消える(遷移途中の画像)場合は基準を書き換えない。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        stable = ("O", "L", "J", "S", "Z")
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="T", next_queue=stable, next_slots_raw=stable),
        ):
            self.worker._tick_once(capture=MagicMock())
            self.worker._tick_once(capture=MagicMock())

        transitional = ("L", "L", "J", "S", "Z")
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="T", next_queue=transitional, next_slots_raw=transitional),
        ):
            self.worker._tick_once(capture=MagicMock())
        self.assertEqual(self.worker._confirmed_next_slots, stable)

        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="T", next_queue=stable, next_slots_raw=stable),
        ):
            self.worker._tick_once(capture=MagicMock())
        self.assertEqual(self.worker._confirmed_next_slots, stable)
        self.assertIsNone(self.worker._next_slot_conflict)

    def test_confirmed_baseline_is_not_replaced_by_a_single_inconsistent_frame(self) -> None:
        # 差し替えは暫定の基準に限る。確定済みの基準は、1枚の整合しない
        # 観測(遷移途中の画像など)では動かさない(高速振動の再発防止)。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        stable = ("O", "L", "J", "S", "Z")
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="T", next_queue=stable, next_slots_raw=stable),
        ):
            self.worker._tick_once(capture=MagicMock())
            self.worker._tick_once(capture=MagicMock())  # 確定

        inconsistent = ("I", "T", "O", "J", "L")
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="T", next_queue=inconsistent, next_slots_raw=inconsistent),
        ):
            self.worker._tick_once(capture=MagicMock())
        self.assertEqual(self.worker._confirmed_next_slots, stable)

    def test_sustained_undecided_reanchors_the_next_history(self) -> None:
        # 確定値は自分自身を基準に更新されるため、_MAX_NEXT_SHIFTを超えて
        # 進んでしまうと自力では復帰できない。判断できない状態が続いたら、
        # 今読めている並びを新しい基準として取り直すこと。
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="T", next_queue=("O", "L", "J", "S", "Z")),
        ):
            self.worker._tick_once(capture=MagicMock())

        # どの移動量でも説明できない並び(=大きくずれた状態)が続く
        far = ("I", "T", "O", "J", "L")
        for _ in range(AssistWorker.NEXT_REANCHOR_TICKS):
            with patch(
                "src.app.recognize",
                return_value=_recognition(current_piece="T", next_queue=far, next_slots_raw=far),
            ):
                self.worker._tick_once(capture=MagicMock())

        self.assertEqual(self.worker._confirmed_next_slots, far, "NEXT履歴が復帰できていない")
        # 何手進んだか分からないので、操作ミノは履歴から決めない
        self.assertIsNone(self.worker._expected_current_piece)

    def test_first_suggestion_for_a_new_piece_is_committed_immediately(self) -> None:
        # 新規スポーン直後の最初の提案は反応の遅れを避けるため無条件で採用する。
        # ホールド提案なので、提案されるミノはHOLDに実在している必要がある
        # (実在しないミノの提案は_available_pieces検証で棄却されるため)。
        self.cold_clear.poll_suggestion.return_value = _move("A2", use_hold=True)
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="A1", hold_piece="A2"),
        ):
            self.worker._tick_once(capture=MagicMock())

        self.assertEqual(len(self.received_draw_data), 1)
        self.assertTrue(self.received_draw_data[0].use_hold)

    def test_single_hold_reversal_from_shallow_search_is_suppressed(self) -> None:
        # 実機ログで確認された不具合の回帰テスト: 探索が浅い段階でuse_holdの
        # 結論が一時的に覆っても、その1回だけでは切り替えず、確定済みの
        # 提案を維持すべき(ユーザーがその都度追従すると「ホールドを行ったり
        # 来たりする」振動につながるため)。
        self.cold_clear.poll_suggestion.return_value = _move("A1", use_hold=False)
        with patch("src.app.time.monotonic", return_value=999.0):
            with patch("src.app.recognize", return_value=_recognition(current_piece="A1")):
                self.worker._tick_once(capture=MagicMock())  # 初回確定: use_hold=False

        # 同じミノを操作中、探索が浅い段階でuse_hold=Trueに一時的に覆る
        # (POLL_INTERVAL_SEC=0.1は超えるがSTALE_DRAW_DATA_TIMEOUT_SEC=0.8
        # 未満の現実的な間隔にする)
        with patch("src.app.time.monotonic", return_value=999.15):
            self.cold_clear.poll_suggestion.return_value = _move("B", use_hold=True)
            with patch("src.app.recognize", return_value=_recognition(current_piece="A1")):
                self.worker._tick_once(capture=MagicMock())

        # pollは実際に行われた(単にポーリング間隔で弾かれたのではない)ことを確認した上で、
        # 1回だけの逆転では表示が更新されないはず(受信リストに追加なし)。
        self.cold_clear.poll_suggestion.assert_called()
        self.assertEqual(len(self.received_draw_data), 1)
        self.assertFalse(self.received_draw_data[0].use_hold)

    def test_placement_never_changes_within_the_same_turn(self) -> None:
        # 仕様「提示した配置は、実際にミノを置くまで変更しない」の回帰テスト。
        # 以前は「最初の提案から0.4秒(SUGGESTION_LOCK_SEC)は無視し、以降は
        # 2回連続で同じ新配置が来たら切り替える」という時間ベースの近似
        # だったが、Cold Clear 2の深い探索結果は1秒前後してから届くため、
        # ロックが切れた後に配置が入れ替わる「提案の振動」が実機ログで
        # 確認された(17:47:42、同一局面のまま piece=Z use_hold=True
        # nodes=14188 → piece=S use_hold=False nodes=648201)。手番が
        # 変わるまでは、何回連続で新しい配置が来ても切り替えないこと。
        self.cold_clear.poll_suggestion.return_value = _move("A1", use_hold=False)
        with patch("src.app.time.monotonic", return_value=999.0):
            with patch("src.app.recognize", return_value=_recognition(current_piece="A1")):
                self.worker._tick_once(capture=MagicMock())  # 初回確定

        # 探索が深まって別の配置が何度届いても、同じ手番の間は無視する。
        self.cold_clear.poll_suggestion.return_value = _move("A1", use_hold=False, landing_cells=[(19, 5)])
        # STALE_DRAW_DATA_TIMEOUT_SECを超えると別の保険が働くため、その範囲内で検証する。
        for elapsed in (0.15, 0.30, 0.55, 0.75):
            with patch("src.app.time.monotonic", return_value=999.0 + elapsed):
                with patch("src.app.recognize", return_value=_recognition(current_piece="A1")):
                    self.worker._tick_once(capture=MagicMock())

        self.cold_clear.poll_suggestion.assert_called()
        self.assertEqual(len(self.received_draw_data), 1)

    def test_new_turn_allows_a_new_placement(self) -> None:
        # 「置くまで変更しない」は手番の中の話であり、次のミノに進んだら
        # 当然新しい配置を提示できること(永久に固まってしまわないこと)。
        self.cold_clear.poll_suggestion.return_value = _move("A1", use_hold=False)
        with patch("src.app.time.monotonic", return_value=999.0):
            with patch("src.app.recognize", return_value=_recognition(current_piece="A1")):
                self.worker._tick_once(capture=MagicMock())

        # ネクストが進んで次の手番になる。新しい操作ミノはNEXTの窓から
        # 出ていった"O"(既定のnext_queueの先頭)になる。
        next_queue = ("L", "J", "S", "Z", "I")
        self.cold_clear.poll_suggestion.return_value = _move("O", use_hold=False, landing_cells=[(19, 5)])
        with patch("src.app.time.monotonic", return_value=999.5):
            with patch(
                "src.app.recognize",
                return_value=_recognition(current_piece="A2", next_queue=next_queue),
            ):
                self.worker._tick_once(capture=MagicMock())

        self.assertEqual(len(self.received_draw_data), 2)
        self.assertEqual(self.received_draw_data[-1].landing_cells, [(19, 5)])

    def test_single_landing_position_change_with_same_use_hold_is_suppressed(self) -> None:
        # 実機ログで確認された不具合の回帰テスト: use_holdは同じ(False)の
        # ままでも、探索が浅い段階と深まった段階とで着地位置(landing_cells)
        # 自体が大きく変わることがあった(例: 同じOミノに対し列8-9→列5-6→
        # また列8-9、という往復)。ユーザーが提示された通りに操作し始めた
        # 直後にこの切り替えが起きると「操作の途中で梯子を外される」体験
        # になるため、use_holdが同じでも着地位置が変わる場合は1回きりの
        # 変化を無視すべき。
        self.cold_clear.poll_suggestion.return_value = _move(
            "O", use_hold=False, landing_cells=[(19, 8), (19, 9), (18, 8), (18, 9)]
        )
        with patch("src.app.time.monotonic", return_value=999.0):
            with patch("src.app.recognize", return_value=_recognition(current_piece="O")):
                self.worker._tick_once(capture=MagicMock())  # 初回確定: 列8-9

        self.received_draw_data.clear()
        # 探索が進み、同じuse_hold=Falseのまま着地位置が列5-6に変わる
        self.cold_clear.poll_suggestion.return_value = _move(
            "O", use_hold=False, landing_cells=[(19, 5), (19, 6), (18, 5), (18, 6)]
        )
        with patch("src.app.time.monotonic", return_value=999.15):
            with patch("src.app.recognize", return_value=_recognition(current_piece="O")):
                self.worker._tick_once(capture=MagicMock())

        # 1回だけの位置変化では表示が更新されないはず
        self.assertEqual(len(self.received_draw_data), 0)

    def test_landing_position_never_changes_within_the_same_turn(self) -> None:
        # 着地位置についても「置くまで変更しない」こと。探索が深まって
        # 別の列が最善になっても、同じ手番の間は最初の提示を維持する
        # (操作の途中で梯子を外さないため)。
        self.cold_clear.poll_suggestion.return_value = _move(
            "O", use_hold=False, landing_cells=[(19, 8), (19, 9), (18, 8), (18, 9)]
        )
        with patch("src.app.time.monotonic", return_value=999.0):
            with patch("src.app.recognize", return_value=_recognition(current_piece="O")):
                self.worker._tick_once(capture=MagicMock())  # 初回確定: 列8-9

        new_cells = [(19, 5), (19, 6), (18, 5), (18, 6)]
        self.cold_clear.poll_suggestion.return_value = _move("O", use_hold=False, landing_cells=new_cells)
        for elapsed in (0.15, 0.30, 0.55, 0.75):
            with patch("src.app.time.monotonic", return_value=999.0 + elapsed):
                with patch("src.app.recognize", return_value=_recognition(current_piece="O")):
                    self.worker._tick_once(capture=MagicMock())

        self.assertEqual(len(self.received_draw_data), 1)
        self.assertEqual(
            self.received_draw_data[0].landing_cells, [(19, 8), (19, 9), (18, 8), (18, 9)]
        )

    def test_current_piece_is_taken_from_next_history_not_the_spawn_frame_image(self) -> None:
        # 実機ログの回帰テスト: next_advancedが発火するtickでは、直前に固定
        # したミノがまだ着地済み領域に取り込まれておらず、画像認識が
        # それを操作中ミノとして返す(49回中15回で発生、うち87%が直前の手番の
        # ミノだった)。この誤った局面でCold Clear 2に質問すると以降の結果が
        # 全て棄却され、提案が出なくなる。NEXTの窓から出ていったミノを
        # 操作ミノとして使うこと。
        self.cold_clear.poll_suggestion.return_value = _move("O")
        # 初回tickでNEXT履歴の基準を作る(next_queueの既定は("O","L","J","S","Z"))
        with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
            self.worker._tick_once(capture=MagicMock())

        # 次のスポーン。画像は直前のミノ"T"を返し続けるが、NEXTは進んでいる
        # ので、実際の操作ミノは窓から出ていった"O"であるべき。
        self.cold_clear.start_thinking.reset_mock()
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="T", next_queue=("L", "J", "S", "Z", "I")),
        ):
            self.worker._tick_once(capture=MagicMock())

        self.cold_clear.start_thinking.assert_called_once()
        args = self.cold_clear.start_thinking.call_args[0]
        self.assertEqual(args[1], "O", f"画像の'T'ではなくNEXT履歴の'O'を使うべき: {args[1]}")

    def test_persistent_disagreement_resyncs_to_the_image(self) -> None:
        # NEXT履歴を優先しても、履歴側が取りこぼす可能性(ホールドの見落とし
        # 等)は残る。画像と長く食い違い続けたら画面を正として同期し直し、
        # 間違った局面の提案を出し続けないこと。
        self.cold_clear.poll_suggestion.return_value = _move("O")
        with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
            self.worker._tick_once(capture=MagicMock())
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="T", next_queue=("L", "J", "S", "Z", "I")),
        ):
            self.worker._tick_once(capture=MagicMock())
        self.assertEqual(self.worker._last_current_piece, "O")

        # 画像が"T"だと言い続ける(=履歴側がずれている)
        self.cold_clear.start_thinking.reset_mock()
        for _ in range(AssistWorker.CURRENT_PIECE_DESYNC_TICKS):
            with patch(
                "src.app.recognize",
                return_value=_recognition(current_piece="T", next_queue=("L", "J", "S", "Z", "I")),
            ):
                self.worker._tick_once(capture=MagicMock())

        self.assertEqual(self.worker._last_current_piece, "T")
        self.cold_clear.start_thinking.assert_called()

    def test_suggestion_for_an_unavailable_piece_is_rejected(self) -> None:
        # 手番の照合をすり抜けた場合の保険: 提案されたミノが操作中でも
        # HOLDでもなければ、その配置は現在の局面では実行できない。
        self.cold_clear.poll_suggestion.return_value = _move("Z", use_hold=True)
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="T", hold_piece="O", next_queue=("S", "L", "J", "I", "T")),
        ):
            self.worker._tick_once(capture=MagicMock())

        self.assertEqual(len(self.received_draw_data), 0)

    def test_storing_into_empty_hold_keeps_the_displayed_placement(self) -> None:
        # 【2026-09-11・5回目の実機ログ】初手で「ホールドしてZを置く」を提示。
        # 利用者がホールドするとHOLDが空→SになりNEXTが1つ進むが、これは
        # 固定ではなく同じ手番の途中である。以前はnext_advancedだけで
        # 提示済み配置を解除していたため、ホールド直後に届いた別の配置へ
        # 差し替わり、初手で提示が振動した。空HOLDへの格納では解除しないこと。
        self.cold_clear.poll_suggestion.return_value = _move("Z", use_hold=True, landing_cells=[(19, 0)])
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch(
                "src.app.recognize",
                return_value=_recognition(current_piece="S", hold_piece=None, next_queue=("Z", "J", "O", "I", "T")),
            ):
                self.worker._tick_once(capture=MagicMock())
        self.assertEqual(self.received_draw_data[-1].landing_cells, [(19, 0)])

        # ホールド: HOLD=S、Zが操作ミノに、NEXTが1つ進む。AIは別の配置を返す。
        self.cold_clear.poll_suggestion.return_value = _move("Z", use_hold=False, landing_cells=[(19, 6)])
        with patch("src.app.time.monotonic", return_value=1000.2):
            with patch(
                "src.app.recognize",
                return_value=_recognition(current_piece="Z", hold_piece="S", next_queue=("J", "O", "I", "T", "L")),
            ):
                self.worker._tick_once(capture=MagicMock())
        shown = [d for d in self.received_draw_data if d is not None]
        self.assertEqual(shown[-1].landing_cells, [(19, 0)], "空HOLDへの格納で提示が差し替わっている")

    def test_hold_swap_from_empty_hold_uses_the_first_next_piece(self) -> None:
        # HOLDが空の状態でホールドすると、NEXTの先頭が操作ミノになる。
        # そのミノの提案は「実行可能」として扱うこと(過剰に棄却しない)。
        self.cold_clear.poll_suggestion.return_value = _move("S", use_hold=True)
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="T", hold_piece=None, next_queue=("S", "L", "J", "I", "T")),
        ):
            self.worker._tick_once(capture=MagicMock())

        self.assertEqual(len(self.received_draw_data), 1)
        self.assertEqual(self.received_draw_data[0].piece, "S")

    def test_hold_piece_flip_during_same_piece_does_not_resend(self) -> None:
        # 上のテストと同種の回帰テスト: 同じミノを操作中にHOLD欄の
        # 認識結果だけが変わっても(ゲームルール上あり得ない)、
        # start_thinkingへの再送信は起こさず、直前に確定していたhold値
        # (この場合はZ)を保持し続けるべき。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        with patch("src.app.time.monotonic", return_value=999.0):
            with patch(
                "src.app.recognize",
                return_value=_recognition(current_piece="T", hold_piece="Z"),
            ):
                self.worker._tick_once(capture=MagicMock())  # 新規スポーン: hold=Z

        self.cold_clear.start_thinking.reset_mock()
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch(
                "src.app.recognize",
                return_value=_recognition(current_piece="T", hold_piece="L"),
            ):
                self.worker._tick_once(capture=MagicMock())  # 同じミノなのにhold=Lに変化(認識ノイズ)

        self.cold_clear.start_thinking.assert_not_called()
        self.assertEqual(self.worker._prev_hold_piece, "Z")

    def test_persistent_turn_key_mismatch_rethinks_without_waiting_for_the_timeout(self) -> None:
        # 実機ログの回帰テスト: 手番キーが食い違っている間、Cold Clear 2は
        # 古い局面を考え続けるため何を返しても棄却され、以前は
        # MAX_SIGNIFICANT_CHANGE_SILENCE_SECのタイムアウト保険が発火する
        # まで提案が出なかった(「提案が遅い」の直接の原因)。食い違いが
        # 続いたら保険を待たずに現在の局面で思考をやり直すこと。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        with patch("src.app.time.monotonic", return_value=999.0):
            with patch(
                "src.app.recognize",
                return_value=_recognition(current_piece="T", hold_piece="Z"),
            ):
                self.worker._tick_once(capture=MagicMock())

        self.cold_clear.start_thinking.reset_mock()
        # HOLDが変わった状態が続く(=要求時の局面と食い違い続ける)
        for i in range(AssistWorker.TURN_KEY_MISMATCH_RETHINK_TICKS):
            with patch("src.app.time.monotonic", return_value=1000.0 + i * 0.15):
                with patch(
                    "src.app.recognize",
                    return_value=_recognition(current_piece="T", hold_piece="L"),
                ):
                    self.worker._tick_once(capture=MagicMock())

        self.cold_clear.start_thinking.assert_called_once()
        # 立て直しでは、既に提示済みの配置を消さない(消すと振動になる)。
        self.assertIsNotNone(self.worker._committed_placement)

    def test_stale_suggestion_is_cleared_once_its_landing_cells_are_filled(self) -> None:
        # 実機の動画で確認された不具合の回帰テスト: 新しいミノがスポーンして
        # から新しい提案が計算し終わるまでのわずかな間、既に実行済み(盤面に
        # 反映済み)の古い提案がそのまま表示され続け、「もう存在しないはずの
        # ミノの置き場所」を提案しているように見えてしまっていた。表示中の
        # 提案の着地マスが最新の盤面で埋まっていたら、新しい提案を待たず
        # 即座にクリアすべき。
        self.cold_clear.poll_suggestion.return_value = _move("I")
        with patch("src.app.recognize", return_value=_recognition(current_piece="I")):
            self.worker._tick_once(capture=MagicMock())  # 初回: (19,0)への提案が確定

        self.received_draw_data.clear()
        self.cold_clear.poll_suggestion.return_value = None
        with patch(
            "src.app.recognize",
            # current_pieceは変わっていない(significant_change=False)が、
            # 提案していたセル(19,0)が既に埋まっている(=実行済み)状態。
            return_value=_recognition(current_piece="I", filled_cells=((19, 0),)),
        ):
            self.worker._tick_once(capture=MagicMock())

        self.assertEqual(self.received_draw_data, [None])

    def test_stale_clear_and_new_suggestion_in_same_tick_emit_only_once(self) -> None:
        # 実機動画で確認された「ちらつき」の回帰テスト: 新しいミノが
        # スポーンし、かつ古い提案の着地マスが既に埋まっている場合、
        # 同じtick内で「クリア」と「新しい提案」の両方の条件が同時に
        # 成立する。ここでemit(None)とemit(new_data)を両方呼んでしまうと、
        # 1tickの間にオーバーレイが「一瞬消えて、すぐ新しい提案が表示
        # される」という2段階の描画更新が発生し、Windows側の画面合成が
        # 追いつかずちらつく原因になっていた。新しい提案が得られる場合は
        # そちらを優先し、emitは1回だけにすべき。
        self.cold_clear.poll_suggestion.return_value = _move("I")
        with patch("src.app.recognize", return_value=_recognition(current_piece="I")):
            self.worker._tick_once(capture=MagicMock())  # 初回: (19,0)への提案が確定

        self.received_draw_data.clear()
        self.cold_clear.poll_suggestion.return_value = _move("L", landing_cells=[(19, 1)])
        with patch(
            "src.app.recognize",
            # 新しいミノ(L)がスポーンし、かつ直前の提案していたセル(19,0)は
            # 既に埋まっている(=Iが実行済み)。next_queueも進める(next_advanced
            # がTrueにならないとstart_thinking自体が呼ばれないため)。
            return_value=_recognition(
                current_piece="L", filled_cells=((19, 0),), next_queue=("L", "J", "S", "Z", "I")
            ),
        ):
            self.worker._tick_once(capture=MagicMock())

        self.assertEqual(len(self.received_draw_data), 1)
        self.assertEqual(self.received_draw_data[0].piece, "L")

    def test_stale_suggestion_is_force_cleared_after_timeout_even_if_not_detected_as_filled(self) -> None:
        # 実機動画で確認された不具合の回帰テスト: 着地演出等のエフェクトで
        # 盤面認識が一時的に乱れると、着地マス判定(all埋まっている)が
        # 機能せず、既に実行済みのはずの古い提案が長時間居座り続けることが
        # あった。着地マス判定に頼らず、一定時間(STALE_DRAW_DATA_TIMEOUT_SEC)
        # 更新がなければ強制的にクリアする保険が機能することを確認する。
        self.cold_clear.poll_suggestion.return_value = _move("I")
        with patch("src.app.time.monotonic", return_value=2000.0):
            with patch("src.app.recognize", return_value=_recognition(current_piece="I")):
                self.worker._tick_once(capture=MagicMock())  # 初回確定

        self.received_draw_data.clear()
        self.cold_clear.poll_suggestion.return_value = None
        # 着地マスは埋まっていない(=all判定は不成立)が、タイムアウト
        # 時間を大幅に超過している。
        timeout = AssistWorker.STALE_DRAW_DATA_TIMEOUT_SEC
        with patch("src.app.time.monotonic", return_value=2000.0 + timeout + 0.1):
            with patch("src.app.recognize", return_value=_recognition(current_piece="I")):
                self.worker._tick_once(capture=MagicMock())

        self.assertEqual(self.received_draw_data, [None])

    def test_stale_suggestion_is_not_cleared_when_only_partially_filled(self) -> None:
        # 「1マスでも埋まっていたらクリア」(any)だと、盤面認識のノイズで
        # たった1マスだけ誤って「埋まっている」と判定された瞬間に、まだ
        # 実行されていない正当な提案までクリアしてしまい、それが表示の
        # 点滅につながるおそれがある。本当にそのミノが設置されたので
        # あれば提案の4マス全てが埋まるはずなので、一部だけが埋まっている
        # 場合はノイズとみなしクリアしないべき。
        self.cold_clear.poll_suggestion.return_value = _move(
            "O", landing_cells=[(18, 0), (18, 1), (19, 0), (19, 1)]
        )
        with patch("src.app.recognize", return_value=_recognition(current_piece="O")):
            self.worker._tick_once(capture=MagicMock())  # 初回: 4マスへの提案が確定

        self.received_draw_data.clear()
        self.cold_clear.poll_suggestion.return_value = None
        with patch(
            "src.app.recognize",
            # 4マスのうち1マスだけがノイズで誤って埋まっていると認識された状態。
            return_value=_recognition(current_piece="O", filled_cells=((18, 0),)),
        ):
            self.worker._tick_once(capture=MagicMock())

        self.assertEqual(self.received_draw_data, [])

    def test_physically_invalid_suggestion_is_rejected(self) -> None:
        # 実機動画で確認された不具合の回帰テスト: Cold Clear 2からの提案が
        # 「既に埋まっているマスに重なる」「支えがなく宙に浮いている」等、
        # 認識した盤面上では物理的にありえない配置になっている瞬間が
        # あった。原因を問わず、このような提案はそのtickでは採用せず、
        # 新しい提案が得られなかったものとして扱うべき。
        self.cold_clear.poll_suggestion.return_value = _move("I", landing_cells=[(19, 0)])
        with patch(
            "src.app.recognize",
            # 提案先(19,0)が既に埋まっている(=物理的にありえない)。
            return_value=_recognition(current_piece="I", filled_cells=((19, 0),)),
        ):
            self.worker._tick_once(capture=MagicMock())

        self.assertEqual(len(self.received_draw_data), 0)

    def test_recognition_failure_below_threshold_keeps_last_suggestion(self) -> None:
        self.cold_clear.poll_suggestion.return_value = _move("T")
        with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
            self.worker._tick_once(capture=MagicMock())

        with patch("src.app.recognize", return_value=None):
            self.worker._tick_once(capture=MagicMock())

        # MAX_CONSECUTIVE_RECOGNITION_FAILURES未満の失敗では、まだ提案を
        # 消すシグナル(None)を送らないはず。
        self.assertNotIn(None, self.received_draw_data)

    def test_retries_poll_suggestion_when_initial_result_is_none_after_spawn(self) -> None:
        # start_thinking直後はCold Clear 2がまだ何も計算できておらずNoneが
        # 返ることがある。その場合、古い提案を表示し続けるより短い間隔で
        # 数回リトライして初期解を待つべき(実機で0.1秒未満でも初期解が
        # 得られることを確認済み)。
        self.cold_clear.poll_suggestion.side_effect = [None, None, _move("T")]
        with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
            self.worker._tick_once(capture=MagicMock())

        self.assertEqual(self.cold_clear.poll_suggestion.call_count, 3)
        self.assertEqual(len(self.received_draw_data), 1)
        self.assertEqual(self.received_draw_data[0].piece, "T")

    def test_gives_up_after_max_retries_and_emits_nothing(self) -> None:
        # リトライ上限(6回)に達しても解が得られない場合、無理に古い値を
        # 使わず、単に今回は何もemitしない(前回有効な提案が表示され続ける)。
        self.cold_clear.poll_suggestion.return_value = None
        with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
            self.worker._tick_once(capture=MagicMock())

        # 初回poll + リトライ6回 = 7回呼ばれるはず
        self.assertEqual(self.cold_clear.poll_suggestion.call_count, 7)
        self.assertEqual(len(self.received_draw_data), 0)

    def test_poll_interval_suppresses_repeated_polling_for_same_piece(self) -> None:
        # POLL_INTERVAL_SEC未満の間隔で同じミノに対しpoll_suggestionを
        # 連発しないことを確認する。これは「前後2つの提案が一瞬両方見える」
        # 実機不具合の対策として導入された制御で、IDLE_SLEEP_MSを
        # 20ms→8msに短縮した際にもこの制御自体は独立して機能し続ける
        # べき(IDLE_SLEEP_MSは新規スポーン検知の反応性にのみ影響し、
        # 同一ミノ操作中のポーリング頻度はPOLL_INTERVAL_SECだけで決まる)。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
                self.worker._tick_once(capture=MagicMock())  # 新規スポーン: 必ずpoll

        self.cold_clear.poll_suggestion.reset_mock()
        with patch("src.app.time.monotonic", return_value=1000.05):  # 50ms後(間隔未満)
            with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
                self.worker._tick_once(capture=MagicMock())

        self.cold_clear.poll_suggestion.assert_not_called()

        with patch("src.app.time.monotonic", return_value=1000.15):  # 150ms後(間隔超過)
            with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
                self.worker._tick_once(capture=MagicMock())

        self.cold_clear.poll_suggestion.assert_called_once()

    def test_board_key_change_alone_does_not_trigger_significant_change(self) -> None:
        # 【2026-09-07・ユーザー指示で全面設計変更】「手が進んだ」の検知は
        # ネクスト欄5枠(next_advanced)のみに一本化された。着地済み盤面
        # (board_key)が変化しても、ネクスト・ネクネクが変化していなければ
        # 新規スポーンとして扱ってはいけない(落下中のミノ・盤面認識由来の
        # 変化は無関係、という仕様)。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        with patch(
            "src.app.recognize",
            return_value=_recognition(
                current_piece="T", current_piece_min_row=0, filled_cells=()
            ),
        ):
            self.worker._tick_once(capture=MagicMock())  # 初回スポーン

        self.cold_clear.start_thinking.reset_mock()
        new_recognition = _recognition(
            current_piece="T", current_piece_min_row=0, filled_cells=((19, 0),)
        )
        with patch("src.app.recognize", return_value=new_recognition):
            self.worker._tick_once(capture=MagicMock())
        with patch("src.app.recognize", return_value=new_recognition):
            self.worker._tick_once(capture=MagicMock())

        self.cold_clear.start_thinking.assert_not_called()

    def test_single_frame_board_noise_does_not_trigger_significant_change(self) -> None:
        # 実機ログで確認された新たな不具合の回帰テスト: board_key変化を
        # 単発(1tick)で即significant_changeとして扱うと、盤面認識の
        # 1フレームだけのノイズ(1マスだけの誤読)を拾って毎tick「新規
        # スポーン」と誤検知し、_committed_placementや探索(start_thinking)
        # が毎tick リセットされ続けて「着地位置が往復する(振動)」
        # 「探索が常に浅いまま(nodes=0付近)」という致命的な不具合を
        # 引き起こしていた。ノイズで1tickだけ変化し、次のtickで元の
        # 状態に戻る場合はsignificant_changeを発火させてはいけない。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        stable_recognition = _recognition(
            current_piece="T", current_piece_min_row=0, next_queue=(), filled_cells=()
        )
        with patch("src.app.recognize", return_value=stable_recognition):
            self.worker._tick_once(capture=MagicMock())  # 初回スポーン

        self.cold_clear.start_thinking.reset_mock()
        noisy_recognition = _recognition(
            current_piece="T", current_piece_min_row=0, next_queue=(), filled_cells=((19, 0),)
        )
        with patch("src.app.recognize", return_value=noisy_recognition):
            self.worker._tick_once(capture=MagicMock())  # ノイズで1tickだけ変化

        with patch("src.app.recognize", return_value=stable_recognition):
            self.worker._tick_once(capture=MagicMock())  # 次のtickで元に戻る

        self.cold_clear.start_thinking.assert_not_called()

    def test_implausible_board_cell_count_drop_blocks_start_thinking(self) -> None:
        # 実機動画で確認された不具合の回帰テスト: T-Spinダブル等の光
        # エフェクト直後、まだ残っているはずの設置済みブロックが列数の
        # 倍数にならない中途半端な数だけ「空」に誤読されるフレームがあり、
        # その誤った盤面のままCold Clear 2に渡されて「既存ブロックと
        # 干渉するように見える提案」「振動」につながっていた。新規スポーン
        # (significant_change)自体は検知できていても、盤面の変化がライン
        # 消去では説明できない不自然な減少の場合はstart_thinkingを
        # 見送るべき。
        self.cold_clear.poll_suggestion.return_value = _move("A")
        stable_recognition = _recognition(
            current_piece="A",
            filled_cells=tuple((19, c) for c in range(10)) + tuple((18, c) for c in range(5)),
        )
        with patch("src.app.recognize", return_value=stable_recognition):
            self.worker._tick_once(capture=MagicMock())  # 初回: 15マス埋まった状態で確定

        self.cold_clear.start_thinking.reset_mock()
        # 新しいミノ(B)がスポーンしたように見えるが、盤面は15マス→1マスと
        # 列数(10)の倍数にならない形で減っている(=エフェクトによる誤読を疑う)。
        # next_queueも進める(next_advancedがTrueにならないとそもそも
        # start_thinkingの検討自体が行われないため)。
        noisy_recognition = _recognition(
            current_piece="B", filled_cells=((19, 0),), next_queue=("L", "J", "S", "Z", "I")
        )
        with patch("src.app.recognize", return_value=noisy_recognition):
            self.worker._tick_once(capture=MagicMock())

        self.cold_clear.start_thinking.assert_not_called()

    def test_plausible_line_clear_cell_count_drop_allows_start_thinking(self) -> None:
        # 上のテストの対比: ライン消去で説明できる減少(列数ぶんちょうど)は
        # 正常に受理されるべき。
        self.cold_clear.poll_suggestion.return_value = _move("A")
        stable_recognition = _recognition(
            current_piece="A",
            filled_cells=tuple((19, c) for c in range(10)) + tuple((18, c) for c in range(5)),
        )
        with patch("src.app.recognize", return_value=stable_recognition):
            self.worker._tick_once(capture=MagicMock())  # 初回: 15マス埋まった状態で確定

        self.cold_clear.start_thinking.reset_mock()
        # 新しいミノ(B)がスポーンし、かつ1行(10マス)がライン消去で消えた
        # (15マス→5マス、10マス減=列数の倍数)。next_queueも進める。
        cleared_recognition = _recognition(
            current_piece="B", filled_cells=tuple((18, c) for c in range(5)), next_queue=("L", "J", "S", "Z", "I")
        )
        with patch("src.app.recognize", return_value=cleared_recognition):
            self.worker._tick_once(capture=MagicMock())

        self.cold_clear.start_thinking.assert_called_once()

    def test_i_j_misclassification_flicker_does_not_cause_repeated_resets(self) -> None:
        # 実機ログで確認された不具合の回帰テスト: I/Jは色相が非常に近く
        # (_resolve_i_j参照)、盤面・HOLD・NEXT欄が全tickで完全に同一の
        # まま、current判定だけが"J"→"I"→"J"→"I"...と交互に入れ替わり
        # 続ける現象があった。同じ物理ミノに対する1tickだけの揺らぎで
        # start_thinkingが何度もリセットされる(=提案が振動する)のを
        # 防ぐべき。
        self.cold_clear.poll_suggestion.return_value = _move("J")
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="J", next_queue=("Z", "T", "L")),
        ):
            self.worker._tick_once(capture=MagicMock())  # 初回スポーン: J

        self.cold_clear.start_thinking.reset_mock()
        # 盤面・HOLD・NEXT欄は一切変化していないのに、current判定だけが
        # I/J間で往復する(色相ゆらぎのシミュレーション)。
        for piece in ("I", "J", "I", "J"):
            with patch(
                "src.app.recognize",
                return_value=_recognition(current_piece=piece, next_queue=("Z", "T", "L")),
            ):
                self.worker._tick_once(capture=MagicMock())

        self.cold_clear.start_thinking.assert_not_called()

    def test_i_j_change_without_next_advance_never_retriggers(self) -> None:
        # 【2026-09-07・全面設計変更】以前はcurrent_piece(落下中のミノ)の
        # I/J間の変化についても、2tick連続確認で「本物の変化」を検知する
        # 仕組みがあった。しかし「手が進んだ」の検知をnext_advancedのみに
        # 統一したことで、current_pieceが実際にJからIへ変わったとしても
        # (本物の変化であっても)、next_queueが変化しない限りは
        # significant_changeを発火させない。
        self.cold_clear.poll_suggestion.return_value = _move("J")
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="J", next_queue=("Z", "T", "L")),
        ):
            self.worker._tick_once(capture=MagicMock())  # 初回スポーン: J

        self.cold_clear.start_thinking.reset_mock()
        for _ in range(3):
            with patch(
                "src.app.recognize",
                return_value=_recognition(current_piece="I", next_queue=("Z", "T", "L")),
            ):
                self.worker._tick_once(capture=MagicMock())

        self.cold_clear.start_thinking.assert_not_called()

    def test_last_confirmed_piece_is_passed_to_recognize_as_hint(self) -> None:
        # _infer_current_piece(app.py)のI/J誤判定対策(previous_piece_hint)が
        # 機能するには、AssistWorkerが直前に確定したミノ種を毎tick
        # recognize()へ渡し続ける必要がある。この配線自体を固定化する。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        with patch("src.app.recognize", return_value=_recognition(current_piece="T")) as mock_recognize:
            self.worker._tick_once(capture=MagicMock())

        self.assertIsNone(mock_recognize.call_args.kwargs.get("previous_piece_hint"))

        with patch("src.app.recognize", return_value=_recognition(current_piece="T")) as mock_recognize:
            self.worker._tick_once(capture=MagicMock())

        self.assertEqual(mock_recognize.call_args.kwargs.get("previous_piece_hint"), "T")

    def test_last_confirmed_settled_top_row_is_passed_to_recognize_as_hint(self) -> None:
        # 実機ログ(2026-09-06)で確認された不具合の回帰テスト:
        # 操作中ピースが着地済み領域のすぐ近くを落下している時、
        # _settled_top_rowのノイズ許容がピース自身を着地済み領域に
        # 誤って取り込んでしまうことがあった(詳細はrecognize()の
        # previous_settled_top_row_hint参照)。この対策が機能するには、
        # AssistWorkerが直前に信頼したsettled_top_rowを毎tick
        # recognize()へ渡し続ける必要がある。この配線自体を固定化する。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        with patch(
            "src.app.recognize", return_value=_recognition(current_piece="T", settled_top_row=18)
        ) as mock_recognize:
            self.worker._tick_once(capture=MagicMock())

        self.assertIsNone(mock_recognize.call_args.kwargs.get("previous_settled_top_row_hint"))

        with patch(
            "src.app.recognize", return_value=_recognition(current_piece="T", settled_top_row=18)
        ) as mock_recognize:
            self.worker._tick_once(capture=MagicMock())

        self.assertEqual(mock_recognize.call_args.kwargs.get("previous_settled_top_row_hint"), 18)

    def test_worker_adopts_recognitions_effective_settled_top_row_unconditionally(self) -> None:
        # 「操作中ミノが着地済み領域の一部として誤って橋渡しされるか」の
        # 判定自体はrecognize()側で単一フレームの構造(_bridge_looks_like_
        # falling_piece)を使って完結している(緩やかな重力でミノが何tickも
        # 静止し続けると2tickデバウンスでは区別できないことが実機ログで
        # 判明したため、時間ベースのデバウンスは廃止した)。AssistWorker側は
        # recognize()が返した実効値(settled_top_row)をそのまま次tickの
        # ヒントとして引き継ぐだけでよい。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        with patch("src.app.recognize", return_value=_recognition(current_piece="T", settled_top_row=18)):
            self.worker._tick_once(capture=MagicMock())
        self.assertEqual(self.worker._last_settled_top_row, 18)

        with patch("src.app.recognize", return_value=_recognition(current_piece="T", settled_top_row=16)):
            self.worker._tick_once(capture=MagicMock())
        self.assertEqual(self.worker._last_settled_top_row, 16)

        with patch("src.app.recognize", return_value=_recognition(current_piece="T", settled_top_row=19)):
            self.worker._tick_once(capture=MagicMock())
        self.assertEqual(self.worker._last_settled_top_row, 19)

    def test_displayed_overlay_cells_are_not_passed_to_recognize(self) -> None:
        # 回帰テスト: かつて「表示中のドットの座標を盤面から強制的に空マス
        # 化する」自己汚染対策が入っていたが、これは人間が提案どおりに
        # 置いた直後の4マス(ドットが乗ったまま実際には埋まっているマス)まで
        # 盤面から消してしまっていた。真の原因はSetWindowDisplayAffinityの
        # HWND切り詰めによる除外失敗であり、そちらを修正済みのため、
        # マスク方式は撤去した。復活させないこと。
        self.cold_clear.poll_suggestion.return_value = _move("T", landing_cells=[(19, 0), (19, 1)])
        with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
            self.worker._tick_once(capture=MagicMock())

        with patch("src.app.recognize", return_value=_recognition(current_piece="T")) as mock_recognize:
            self.worker._tick_once(capture=MagicMock())

        # 提案を表示した次のtickでも、その座標がrecognize()へ渡らないこと。
        self.assertNotIn("own_overlay_cells", mock_recognize.call_args.kwargs)

    def test_next_debug_marks_are_cleared_when_recognition_keeps_failing(self) -> None:
        # 回帰テスト: NEXT欄のデバッグ表示(ドット/×)は認識成功時にしか
        # 更新されず、recognize()がNoneを返し続ける間は「最後に成功した
        # tickの結果」が画面と録画に残り続けていた。そのため、実際には
        # 読めている枠が×のまま表示され、不具合調査で「NEXTが認識でき
        # ていない」証拠だと誤読される原因になっていた。認識に失敗し続け
        # たら、表示も「読めていない」状態へ更新すること。
        received: list[object] = []
        self.worker.next_debug_ready.connect(received.append)

        self.cold_clear.poll_suggestion.return_value = _move("T")
        with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
            self.worker._tick_once(capture=MagicMock())
        self.assertTrue(any(x is not None for x in received[-1]))

        with patch("src.app.recognize", return_value=None):
            for _ in range(MAX_CONSECUTIVE_RECOGNITION_FAILURES):
                self.worker._tick_once(capture=MagicMock())

        self.assertTrue(
            all(x is None for x in received[-1]),
            f"認識失敗が続いても古い表示が残っている: {received[-1]}",
        )

    def test_record_video_frame_throttles_to_target_fps_and_creates_writer_once(self) -> None:
        # 画面録画(暫定機能)の回帰テスト: VIDEO_RECORD_FPSより短い間隔で
        # 呼ばれた場合は書き込みをスキップし、VideoWriterは1回だけ生成
        # されるべき(呼ぶたびに新規作成すると録画が壊れる)。
        import numpy as np

        from src import app as app_module

        dummy_frame = np.zeros((10, 10, 3), dtype=np.uint8)
        interval = 1.0 / app_module.VIDEO_RECORD_FPS
        worker = AssistWorker(_make_calibration(), self.cold_clear, debug_log_path=None, record_video=True)
        with (
            patch("src.app._grab_calibrated_region", return_value=dummy_frame),
            patch("cv2.VideoWriter") as mock_writer_cls,
            patch("cv2.VideoWriter_fourcc", return_value=0),
            patch(
                "src.app.time.monotonic",
                side_effect=[1000.0, 1000.0 + interval / 2, 1000.0 + interval * 1.5],
            ),
        ):
            worker._record_video_frame(MagicMock())  # 1回目: 書き込む(初回)
            worker._record_video_frame(MagicMock())  # 2回目: 間隔未満なのでスキップ
            worker._record_video_frame(MagicMock())  # 3回目: 間隔超過なので書き込む

        mock_writer_cls.assert_called_once()
        self.assertEqual(mock_writer_cls.return_value.write.call_count, 2)

    def test_board_trust_timeout_forces_acceptance_after_prolonged_implausibility(self) -> None:
        # 実機動画で確認された致命的な不具合の回帰テスト: 激しい連続コンボ
        # (REN)等で盤面が断続的に大きく変化し続けると、board_data_
        # trustworthyの基準値が2tick連続で安定する瞬間が長時間訪れず、
        # 「あり得ない変化」の判定が延々と続いてstart_thinkingが一切
        # 呼ばれなくなり、39秒間まったく提案が更新されないままトップ
        # アウトする事態が実機で発生した。BOARD_TRUST_TIMEOUT_SEC以上
        # 信頼できる読み取りが得られない場合は、汚れている可能性を承知の
        # 上でその時点の盤面を強制的に受け入れるべき。
        self.cold_clear.poll_suggestion.return_value = _move("A")
        stable_recognition = _recognition(
            current_piece="A",
            filled_cells=tuple((19, c) for c in range(10)) + tuple((18, c) for c in range(5)),
        )
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch("src.app.recognize", return_value=stable_recognition):
                self.worker._tick_once(capture=MagicMock())  # 初回: 15マス埋まった状態で確定

        self.cold_clear.start_thinking.reset_mock()
        # next_advancedはboard_data_trustworthyの結果に関わらず(next_queueが
        # 動けば)確定するため、各tickでnext_queueをそれぞれ1つ分進めて
        # 「その時点で本物の新規スポーンがあった」状態を保つ。
        timeout = AssistWorker.BOARD_TRUST_TIMEOUT_SEC
        noisy_recognition_1 = _recognition(
            current_piece="B", filled_cells=((19, 0),), next_queue=("L", "J", "S", "Z", "I")
        )
        with patch("src.app.time.monotonic", return_value=1000.0 + timeout / 2):
            with patch("src.app.recognize", return_value=noisy_recognition_1):
                self.worker._tick_once(capture=MagicMock())  # タイムアウト未満: まだ拒否される

        self.cold_clear.start_thinking.assert_not_called()

        noisy_recognition_2 = _recognition(
            current_piece="B", filled_cells=((19, 0),), next_queue=("J", "S", "Z", "I", "O")
        )
        with patch("src.app.time.monotonic", return_value=1000.0 + timeout + 0.1):
            with patch("src.app.recognize", return_value=noisy_recognition_2):
                self.worker._tick_once(capture=MagicMock())  # タイムアウト超過: 強制受理される

        self.cold_clear.start_thinking.assert_called_once()

    def test_request_skipped_for_untrustworthy_board_is_retried_next_tick(self) -> None:
        # 【残課題・2026-09-11実機ログ】next_advancedのtickで盤面が信用
        # できないと要求を見送るが、next_advancedはそのtickで消費済み
        # (_confirmed_next_slotsが進む)のため、以前はこの手番の要求が二度と
        # 起きず、1.5秒のタイムアウト保険まで提案が出なかった(約110秒で
        # 41回発火)。盤面を信用できる次のtickで改めて要求すること。
        self.cold_clear.poll_suggestion.return_value = _move("A")
        stable_recognition = _recognition(
            current_piece="A",
            filled_cells=tuple((19, c) for c in range(10)) + tuple((18, c) for c in range(5)),
        )
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch("src.app.recognize", return_value=stable_recognition):
                self.worker._tick_once(capture=MagicMock())  # 初回: 15マスで確定
        self.cold_clear.start_thinking.reset_mock()

        # 新規スポーン(next_queueが進む)と同時に、ライン消去では説明できない
        # 減少(15→1)が観測された: 要求は見送られる。
        noisy = _recognition(current_piece="B", filled_cells=((19, 0),), next_queue=("L", "J", "S", "Z", "I"))
        with patch("src.app.time.monotonic", return_value=1000.05):
            with patch("src.app.recognize", return_value=noisy):
                self.worker._tick_once(capture=MagicMock())
        self.cold_clear.start_thinking.assert_not_called()

        # 次のtickで盤面が元どおり信用できる値に戻った(next_queueは進まない)。
        # タイムアウト保険(1.5秒)も盤面信頼タイムアウト(0.3秒)も経過していない
        # が、見送った要求はここで出るべき。
        recovered = _recognition(
            current_piece="B",
            filled_cells=tuple((19, c) for c in range(10)) + tuple((18, c) for c in range(5)),
            next_queue=("L", "J", "S", "Z", "I"),
        )
        with patch("src.app.time.monotonic", return_value=1000.1):
            with patch("src.app.recognize", return_value=recovered):
                self.worker._tick_once(capture=MagicMock())
        self.cold_clear.start_thinking.assert_called_once()

    def test_spawn_while_cleared_rows_are_still_pending_waits_for_the_board_to_settle(self) -> None:
        # 【2026-09-11・録画とログで判明】ライン消去では行が消えるのと同じ
        # フレームで次のミノがスポーンするが、「ブロック→空」の確定には
        # 2tickかかるため、スポーン検知のtickの盤面には消えた行が残っている。
        # その盤面で要求すると、消えた行の上に提案が出て空中に提示されるか、
        # 消去後の盤面で物理的に成立せず黙って捨てられて何も表示されない
        # まま1.5秒の保険を待っていた。確定待ちのマスがある間は要求を
        # 保留し、確定した次のtickで要求すること。
        self.cold_clear.poll_suggestion.return_value = _move("A")
        bottom_rows = tuple((r, c) for r in (18, 19) for c in range(10))
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch("src.app.recognize", return_value=_recognition(current_piece="A", filled_cells=bottom_rows)):
                self.worker._tick_once(capture=MagicMock())
        self.cold_clear.start_thinking.reset_mock()

        # スポーン(next_queueが進む)。2行消えたが、盤面ではまだ保留中
        # (前回の値が維持されている)。
        settling = _recognition(
            current_piece="B",
            filled_cells=bottom_rows,
            pending_cells=bottom_rows,
            next_queue=("L", "J", "S", "Z", "I"),
        )
        with patch("src.app.time.monotonic", return_value=1000.1):
            with patch("src.app.recognize", return_value=settling):
                self.worker._tick_once(capture=MagicMock())
        self.cold_clear.start_thinking.assert_not_called()

        # 次のtickで確定(2行が消えた盤面)。ここで要求されること。
        settled = _recognition(current_piece="B", filled_cells=(), next_queue=("L", "J", "S", "Z", "I"))
        with patch("src.app.time.monotonic", return_value=1000.2):
            with patch("src.app.recognize", return_value=settled):
                self.worker._tick_once(capture=MagicMock())
        self.cold_clear.start_thinking.assert_called_once()
        board = self.cold_clear.start_thinking.call_args.args[0]
        self.assertTrue(
            all(cell is None for row in board.grid for cell in row), "消えた行が残った盤面で要求している"
        )

    def test_deferred_spawn_still_lets_the_new_piece_be_displayed(self) -> None:
        # 【2026-09-11・3回目の実機ログ】要求を見送ったtickでは提示済み配置の
        # 解除も行われず、再試行のtickではnext_advancedが消費済みで解除
        # されない。新しいミノの結果がすべて「提示済み」として黙って捨て
        # られ、次のミノまで何も表示されなかった(132手番中提示28回)。
        self.cold_clear.poll_suggestion.return_value = _move("A", landing_cells=[(17, 0)])
        bottom_rows = tuple((r, c) for r in (18, 19) for c in range(10))
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch("src.app.recognize", return_value=_recognition(current_piece="A", filled_cells=bottom_rows)):
                self.worker._tick_once(capture=MagicMock())
        self.assertEqual(self.received_draw_data[-1].landing_cells, [(17, 0)])

        settling = _recognition(
            current_piece="B", filled_cells=bottom_rows, pending_cells=bottom_rows,
            next_queue=("L", "J", "S", "Z", "I"),
        )
        with patch("src.app.time.monotonic", return_value=1000.1):
            with patch("src.app.recognize", return_value=settling):
                self.worker._tick_once(capture=MagicMock())  # 見送り

        self.cold_clear.poll_suggestion.return_value = _move("O", landing_cells=[(19, 5)])  # 履歴上の新しい操作ミノはO
        settled = _recognition(current_piece="B", filled_cells=(), next_queue=("L", "J", "S", "Z", "I"))
        with patch("src.app.time.monotonic", return_value=1000.2):
            with patch("src.app.recognize", return_value=settled):
                self.worker._tick_once(capture=MagicMock())  # 再試行して要求
        shown = [d for d in self.received_draw_data if d is not None]
        self.assertEqual(shown[-1].piece, "O", "新しいミノの提案が表示されていない")
        self.assertEqual(shown[-1].landing_cells, [(19, 5)])

    def test_color_only_pending_cells_do_not_defer_the_request(self) -> None:
        # 置いた直後のミノはUNKNOWN→本来の色と読みが変わるが占有は同じ。
        # 色の保留で要求を止めると、ほぼ毎手番で盤面信頼タイムアウト(0.3秒)
        # まで待つことになる(3回目の実機ログ: 保留61回、タイムアウト67回)。
        self.cold_clear.poll_suggestion.return_value = _move("A")
        bottom = tuple((19, c) for c in range(10))
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch("src.app.recognize", return_value=_recognition(current_piece="A", filled_cells=bottom)):
                self.worker._tick_once(capture=MagicMock())
        self.cold_clear.start_thinking.reset_mock()

        rec = _recognition(
            current_piece="B", filled_cells=bottom + ((18, 0), (18, 1)),
            pending_color_cells=((18, 0), (18, 1)), next_queue=("L", "J", "S", "Z", "I"),
        )
        with patch("src.app.time.monotonic", return_value=1000.1):
            with patch("src.app.recognize", return_value=rec):
                self.worker._tick_once(capture=MagicMock())
        self.cold_clear.start_thinking.assert_called_once()

    def test_prolonged_silence_forces_refresh_even_when_no_signal_changes(self) -> None:
        # 実機動画(タイムスタンプ付き録画で正確に確認)で発見された致命的な
        # 不具合の回帰テスト: HOLD欄の色が動画上で複数回変化しており
        # 実際には何度もミノが入れ替わっていたにも関わらず、piece_changed・
        # respawned_same_piece・next_prefix_changed・board_key_changedの
        # 4条件が約20秒間すべて同時に成立せず、その間ずっと提案が更新
        # されないままトップアウトした。個々の検知条件の対策を重ねる
        # のではなく、「4条件が何であれ、MAX_SIGNIFICANT_CHANGE_SILENCE_SEC
        # 以上経過したら強制的に最新の認識結果で思考をやり直す」という
        # 無条件の保険が機能することを確認する。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        # NEXTが1枠読めていない状態で始め、探索木の引き継ぎ(引き継ぎ中は
        # 盤面が一致していれば渡し直さない)を無効にしておく。
        partial = ("O", "L", "J", "S", None)
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch(
                "src.app.recognize",
                return_value=_recognition(current_piece="T", next_queue=("O", "L", "J", "S"), next_slots_raw=partial),
            ):
                self.worker._tick_once(capture=MagicMock())  # 初回スポーン

        self.cold_clear.start_thinking.reset_mock()
        silence = AssistWorker.MAX_SIGNIFICANT_CHANGE_SILENCE_SEC
        with patch("src.app.time.monotonic", return_value=1000.0 + silence / 2):
            with patch(
                "src.app.recognize",
                return_value=_recognition(current_piece="T", next_queue=("O", "L", "J", "S"), next_slots_raw=partial),
            ):
                self.worker._tick_once(capture=MagicMock())  # 沈黙時間未満: まだ何も起きない

        self.cold_clear.start_thinking.assert_not_called()

        with patch("src.app.time.monotonic", return_value=1000.0 + silence + 0.1):
            # current/hold/next/盤面すべて前回と全く同じに見えても、
            # 沈黙時間を超えたら強制的にリフレッシュされるべき。
            with patch(
                "src.app.recognize",
                return_value=_recognition(current_piece="T", next_queue=("O", "L", "J", "S"), next_slots_raw=partial),
            ):
                self.worker._tick_once(capture=MagicMock())

        self.cold_clear.start_thinking.assert_called_once()

    # ---- 探索木の引き継ぎ(play) ----
    _T_CELLS = [(19, 0), (19, 1), (19, 2), (18, 1)]

    def _spawn_t_with_suggestion(self) -> None:
        """初手T、NEXT5枠すべて読めている状態で提案(T)を確定させる。"""
        self.cold_clear.poll_suggestion.return_value = _move("T", landing_cells=list(self._T_CELLS))
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
                self.worker._tick_once(capture=MagicMock())
                self.worker._tick_once(capture=MagicMock())  # NEXT基準を確定
        self.assertIsNotNone(self.worker._cc_continuation, "引き継ぎ元が作られていない")
        self.cold_clear.start_thinking.reset_mock()

    def test_following_the_suggestion_advances_the_search_tree_instead_of_restarting(self) -> None:
        # 利用者が提示どおりに置いた: startで渡し直さず、play(提示した手)と
        # new_piece(新しく見えたNEXT)で探索木を引き継ぐこと。
        self._spawn_t_with_suggestion()
        self.cold_clear.poll_suggestion.return_value = _move("O", landing_cells=[(19, 8), (19, 9), (18, 8), (18, 9)])
        advanced = ("L", "J", "S", "Z", "I")
        with patch("src.app.time.monotonic", return_value=1000.5):
            with patch(
                "src.app.recognize",
                return_value=_recognition(
                    current_piece=None, filled_cells=tuple(self._T_CELLS),
                    next_queue=advanced, next_slots_raw=advanced,
                ),
            ):
                self.worker._tick_once(capture=MagicMock())

        self.cold_clear.start_thinking.assert_not_called()
        self.cold_clear.advance_thinking.assert_called_once()
        placement = self.cold_clear.advance_thinking.call_args.args[0]
        self.assertEqual(placement["location"]["type"], "T")
        self.cold_clear.add_new_pieces.assert_called_once_with(["I"])
        self.assertEqual(self.worker._cc_continuation.queue, ["L", "J", "S", "Z", "I"])
        # 新しいミノ(O)の提案は通常どおり表示される。
        shown = [d for d in self.received_draw_data if d is not None]
        self.assertEqual(shown[-1].piece, "O")

    def test_storing_into_empty_hold_keeps_the_continuation_in_sync(self) -> None:
        # 【7回目の実機ログ】startでholdなし(操作ミノがreserve)の後に空HOLDへ
        # 格納すると、内部=[NEXT...]と実際=[操作ミノ, NEXT...]がずれて
        # 引き継ぎを中止していた(15回)。内部のreserveを追跡して一致させること。
        self._spawn_t_with_suggestion()
        # ホールド: HOLD=T、操作ミノ=O(NEXT先頭)、NEXTが1つ進む。
        advanced = ("L", "J", "S", "Z", "I")
        with patch("src.app.time.monotonic", return_value=1000.3):
            with patch(
                "src.app.recognize",
                return_value=_recognition(current_piece="O", hold_piece="T", next_queue=advanced, next_slots_raw=advanced),
            ):
                self.worker._tick_once(capture=MagicMock())
        self.assertIsNotNone(self.worker._cc_continuation, "空HOLDへの格納で引き継ぎが中止されている")
        self.cold_clear.add_new_pieces.assert_called_once_with(["I"])
        self.assertEqual(self.worker._cc_continuation.queue, ["O", "L", "J", "S", "Z", "I"])

    def test_hold_shown_before_next_advances_does_not_break_the_continuation(self) -> None:
        # 【7回目の実機ログ】空HOLDへ格納した瞬間、HOLD欄は新しい値(T)なのに
        # NEXTはまだ進んでいない遷移途中のtickがある。以前はこれを
        # 内部=[NEXT...] 実際=[T, NEXT...] の不一致とみなして引き継ぎを
        # 中止していた(15回)。どちらの解釈でも整合すれば続けること。
        self._spawn_t_with_suggestion()
        stale_next = ("O", "L", "J", "S", "Z")
        with patch("src.app.time.monotonic", return_value=1000.3):
            with patch(
                "src.app.recognize",
                return_value=_recognition(current_piece="T", hold_piece="T", next_queue=stale_next, next_slots_raw=stale_next),
            ):
                self.worker._tick_once(capture=MagicMock())
        self.assertIsNotNone(self.worker._cc_continuation, "遷移途中のtickで引き継ぎが中止されている")

    def test_placing_elsewhere_restarts_the_search(self) -> None:
        # 提示と違う場所に置いた: 盤面が内部局面と一致しないのでstartでやり直す。
        self._spawn_t_with_suggestion()
        self.cold_clear.poll_suggestion.return_value = _move("O")
        advanced = ("L", "J", "S", "Z", "I")
        elsewhere = ((19, 7), (19, 8), (19, 9), (18, 8))
        with patch("src.app.time.monotonic", return_value=1000.5):
            with patch(
                "src.app.recognize",
                return_value=_recognition(
                    current_piece=None, filled_cells=elsewhere, next_queue=advanced, next_slots_raw=advanced
                ),
            ):
                self.worker._tick_once(capture=MagicMock())

        self.cold_clear.advance_thinking.assert_not_called()
        self.cold_clear.start_thinking.assert_called_once()

    def test_timeout_refresh_keeps_the_tree_when_the_board_matches(self) -> None:
        # タイムアウト保険: 引き継ぎ中で盤面が内部局面と一致していれば
        # 渡し直さない(渡し直すと深めた探索が捨てられる)。
        self._spawn_t_with_suggestion()
        silence = AssistWorker.MAX_SIGNIFICANT_CHANGE_SILENCE_SEC
        with patch("src.app.time.monotonic", return_value=1000.0 + silence + 0.1):
            with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
                self.worker._tick_once(capture=MagicMock())
        self.cold_clear.start_thinking.assert_not_called()
        self.assertIsNotNone(self.worker._cc_continuation)

    def test_timeout_refresh_restarts_when_the_board_differs(self) -> None:
        # 盤面が内部局面と食い違っている(固定を取りこぼした等)なら渡し直す。
        self._spawn_t_with_suggestion()
        silence = AssistWorker.MAX_SIGNIFICANT_CHANGE_SILENCE_SEC
        with patch("src.app.time.monotonic", return_value=1000.0 + silence + 0.1):
            with patch(
                "src.app.recognize",
                return_value=_recognition(current_piece="T", filled_cells=((19, 5), (19, 6))),
            ):
                self.worker._tick_once(capture=MagicMock())
        self.cold_clear.start_thinking.assert_called_once()

    def test_continuation_is_not_started_when_a_next_slot_is_unreadable(self) -> None:
        # NEXTが欠けたまま引き継ぎを始めると、以後どのNEXTを渡したか対応が
        # 取れなくなる。5枠すべて読めている時だけ引き継ぎ元を作ること。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        partial = ("O", "L", "J", "S", None)
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="T", next_queue=("O", "L", "J", "S"), next_slots_raw=partial),
        ):
            self.worker._tick_once(capture=MagicMock())
        self.assertIsNone(self.worker._cc_continuation)

    def test_plan_steps_are_frozen_with_the_first_move(self) -> None:
        # 読み筋(2手目以降)も1手目と一緒に固定する。探索が深まって2手目だけ
        # 変わった結果が届いても、表示中の読み筋を揺らさないこと。
        from src.engine.cold_clear_client import ColdClearMove

        def move_with_plan(second_cells):
            return ColdClearMove(
                use_hold=False, piece="T", landing_cells=[(19, 0), (19, 1), (19, 2), (18, 1)],
                nodes=0, nps=0.0, placement={"location": {}, "spin": "none"},
                plan=[("O", second_cells)],
            )

        self.cold_clear.poll_suggestion.return_value = move_with_plan([(19, 8), (19, 9), (18, 8), (18, 9)])
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
                self.worker._tick_once(capture=MagicMock())
        first = self.received_draw_data[-1]
        self.assertEqual(first.plan_steps[0].cells, [(19, 8), (19, 9), (18, 8), (18, 9)])

        self.cold_clear.poll_suggestion.return_value = move_with_plan([(19, 5), (19, 6), (18, 5), (18, 6)])
        with patch("src.app.time.monotonic", return_value=1000.5):
            with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
                self.worker._tick_once(capture=MagicMock())
        shown = [d for d in self.received_draw_data if d is not None]
        self.assertEqual(shown[-1].plan_steps[0].cells, [(19, 8), (19, 9), (18, 8), (18, 9)], "読み筋が途中で変わっている")

    # ---- 開幕テンプレ ----
    def _opener_worker(self):
        worker = AssistWorker(_make_calibration(), self.cold_clear, debug_log_path=None, opener_enabled=True)
        received: list[object] = []
        worker.draw_data_ready.connect(received.append)
        return worker, received

    def test_opener_overrides_the_ai_suggestion_at_game_start(self) -> None:
        # 盤面・HOLDが空で1巡目のミノ順が分かる手番では、組めるテンプレの
        # 手をAIの提案の代わりに出し、テンプレ名をラベルに載せること。
        worker, received = self._opener_worker()
        self.cold_clear.poll_suggestion.return_value = _move("I", landing_cells=[(19, 5), (19, 6), (19, 7), (19, 8)])
        # I L S T Z O J → はちみつ砲(左)が組める(Iを最下段左に置く)
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch("src.app.recognize", return_value=_recognition(current_piece="I", next_queue=("L", "S", "T", "Z", "O"))):
                worker._tick_once(capture=MagicMock())
        self.assertIsNotNone(worker._opener)
        self.assertEqual(worker._opener.template.name_ja, "はちみつ砲")
        shown = received[-1]
        self.assertEqual(shown.piece, "I")
        self.assertEqual(sorted(shown.landing_cells), [(19, 0), (19, 1), (19, 2), (19, 3)])
        self.assertIn("はちみつ砲", shown.label)
        self.assertTrue(shown.plan_steps, "テンプレの残り手順が読み筋として出ていない")

    def test_opener_advances_when_the_piece_is_placed_as_shown(self) -> None:
        worker, received = self._opener_worker()
        self.cold_clear.poll_suggestion.return_value = _move("I")
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch("src.app.recognize", return_value=_recognition(current_piece="I", next_queue=("L", "S", "T", "Z", "O"))):
                worker._tick_once(capture=MagicMock())
                worker._tick_once(capture=MagicMock())
        first_cells = tuple(worker._opener.steps[0].cells)
        # 提示どおりIを置いた: NEXTが進み、盤面にIの4マス。
        with patch("src.app.time.monotonic", return_value=1000.5):
            with patch(
                "src.app.recognize",
                return_value=_recognition(current_piece=None, filled_cells=first_cells, next_queue=("S", "T", "Z", "O", "J")),
            ):
                worker._tick_once(capture=MagicMock())
        self.assertIsNotNone(worker._opener, "手順どおりなのにテンプレが中断された")
        self.assertEqual(worker._opener.index, 1)
        self.assertEqual(received[-1].piece, worker._opener.steps[1].piece)

    def test_opener_is_abandoned_when_the_piece_is_placed_elsewhere(self) -> None:
        worker, received = self._opener_worker()
        self.cold_clear.poll_suggestion.return_value = _move("L", landing_cells=[(19, 0), (19, 1), (19, 2), (18, 2)])
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch("src.app.recognize", return_value=_recognition(current_piece="I", next_queue=("L", "S", "T", "Z", "O"))):
                worker._tick_once(capture=MagicMock())
                worker._tick_once(capture=MagicMock())
        with patch("src.app.time.monotonic", return_value=1000.5):
            with patch(
                "src.app.recognize",
                return_value=_recognition(
                    current_piece=None, filled_cells=((19, 6), (19, 7), (19, 8), (19, 9)), next_queue=("S", "T", "Z", "O", "J")
                ),
            ):
                worker._tick_once(capture=MagicMock())
        self.assertIsNone(worker._opener, "手順と違う置き方なのにテンプレが続いている")
        shown = [d for d in received if d is not None]
        self.assertEqual(shown[-1].piece, "L", "AIの提案に戻っていない")
        self.assertIsNone(shown[-1].label)

    def test_opener_waits_for_a_partially_read_piece_instead_of_aborting(self) -> None:
        # 【2026-09-12実機】固定を検知したtickでは置いたばかりのミノが光って
        # 一部しか読めないことがある。厳密一致で即断すると手順どおりなのに
        # テンプレが中断した。期待するマスが揃うまで待って進めること。
        worker, received = self._opener_worker()
        self.cold_clear.poll_suggestion.return_value = _move("I")
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch("src.app.recognize", return_value=_recognition(current_piece="I", next_queue=("L", "S", "T", "Z", "O"))):
                worker._tick_once(capture=MagicMock())
                worker._tick_once(capture=MagicMock())
        first_cells = tuple(worker._opener.steps[0].cells)
        partial = first_cells[:2]
        with patch("src.app.time.monotonic", return_value=1000.5):
            with patch(
                "src.app.recognize",
                return_value=_recognition(current_piece=None, filled_cells=partial, next_queue=("S", "T", "Z", "O", "J")),
            ):
                worker._tick_once(capture=MagicMock())
        self.assertIsNotNone(worker._opener, "一部しか読めていない段階で中断している")
        self.assertEqual(worker._opener.index, 0)
        with patch("src.app.time.monotonic", return_value=1000.6):
            with patch(
                "src.app.recognize",
                return_value=_recognition(current_piece=None, filled_cells=first_cells, next_queue=("S", "T", "Z", "O", "J")),
            ):
                worker._tick_once(capture=MagicMock())
        self.assertIsNotNone(worker._opener)
        self.assertEqual(worker._opener.index, 1)

    def test_plan_depth_limits_the_number_of_shown_steps(self) -> None:
        from src.engine.cold_clear_client import ColdClearMove

        worker = AssistWorker(_make_calibration(), self.cold_clear, debug_log_path=None, plan_depth=2)
        received: list[object] = []
        worker.draw_data_ready.connect(received.append)
        self.cold_clear.poll_suggestion.return_value = ColdClearMove(
            use_hold=False, piece="T", landing_cells=[(19, 0), (19, 1), (19, 2), (18, 1)], nodes=0, nps=0.0,
            placement={"location": {}, "spin": "none"},
            plan=[("O", [(19, 8), (19, 9), (18, 8), (18, 9)]), ("I", [(19, 4), (19, 5), (19, 6), (19, 7)])],
        )
        with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
            worker._tick_once(capture=MagicMock())
        self.assertEqual(len(received[-1].plan_steps), 1, "表示手数2なら読み筋は1手だけ")

    def test_opener_continues_after_a_garbage_rise_by_shifting_the_steps_up(self) -> None:
        # 【2026-09-12・利用者の指示】おじゃまがせり上がってもテンプレの形は
        # その上に載るので続行する。手順の座標をせり上がった行数ぶん上へずらす。
        worker, received = self._opener_worker()
        self.cold_clear.poll_suggestion.return_value = _move("I")
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch("src.app.recognize", return_value=_recognition(current_piece="I", next_queue=("L", "S", "T", "Z", "O"))):
                worker._tick_once(capture=MagicMock())
                worker._tick_once(capture=MagicMock())
        first_cells = tuple(worker._opener.steps[0].cells)  # I: (19,0)〜(19,3)
        with patch("src.app.time.monotonic", return_value=1000.5):
            with patch(
                "src.app.recognize",
                return_value=_recognition(current_piece=None, filled_cells=first_cells, next_queue=("S", "T", "Z", "O", "J")),
            ):
                worker._tick_once(capture=MagicMock())
                worker._tick_once(capture=MagicMock())  # 盤面を確定
        self.assertEqual(worker._opener.index, 1)
        second_before = worker._opener.steps[1].cells

        # おじゃま2行: Iが2行上へ、最下2行はGARBAGE(1列だけ穴)
        risen = _recognition(
            current_piece="L", filled_cells=tuple((r - 2, c) for r, c in first_cells), next_queue=("S", "T", "Z", "O", "J")
        )
        for r in (18, 19):
            for c in range(10):
                if c != 4:
                    risen.board.grid[r][c] = "GARBAGE"
        from dataclasses import replace
        risen = replace(risen, board_key=tuple(tuple(row) for row in risen.board.grid))
        with patch("src.app.time.monotonic", return_value=1000.8):
            with patch("src.app.recognize", return_value=risen):
                worker._tick_once(capture=MagicMock())
                worker._tick_once(capture=MagicMock())
        self.assertIsNotNone(worker._opener, "おじゃまでテンプレが中断されている")
        self.assertEqual(
            sorted(worker._opener.steps[1].cells), sorted((r - 2, c) for r, c in second_before), "手順が上へずれていない"
        )

    def test_opener_continues_into_the_second_bag_with_a_matching_form(self) -> None:
        # 【2026-09-12実機】1巡目を置き終えると通常のAI提案に戻り、2巡目が
        # テンプレと別物になっていた。置き終えた盤面に既存ブロックが一致する
        # 次の図(2巡目)を同じテンプレから探して続けること。
        from src.engine.openers import OPENER_TEMPLATES, apply_step, choose_opener

        worker, received = self._opener_worker()
        tpl, form, steps = choose_opener(list("ILSTZOJ"))
        board: set = set()
        for step in steps:
            board = apply_step(board, step.cells)
        # 1巡目を置き終えた直後の状態を作る: 続きを探すテンプレと、盤面・HOLD=J。
        worker._opener_continuing = tpl
        self.cold_clear.poll_suggestion.return_value = _move("T", landing_cells=[(11, 0), (11, 1), (11, 2), (10, 1)])
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch(
                "src.app.recognize",
                return_value=_recognition(
                    current_piece="T", hold_piece="J", filled_cells=tuple(board), next_queue=("O", "S", "Z", "I", "J")
                ),
            ):
                worker._tick_once(capture=MagicMock())
        self.assertIsNotNone(worker._opener, "2巡目の図が始まっていない")
        self.assertIn("2巡目", worker._opener.form.section)
        shown = received[-1]
        self.assertIn("2巡目", shown.label)
        self.assertEqual(shown.piece, worker._opener.steps[0].piece)

    def test_opener_is_not_started_when_disabled(self) -> None:
        self.cold_clear.poll_suggestion.return_value = _move("I")
        with patch("src.app.recognize", return_value=_recognition(current_piece="I", next_queue=("L", "S", "T", "Z", "O"))):
            self.worker._tick_once(capture=MagicMock())
        self.assertIsNone(self.worker._opener)

    def test_recognition_failure_does_not_clear_the_suggestion(self) -> None:
        # 仕様「提示した配置は、実際にミノを置くまで変更しない」の回帰テスト。
        # 認識できないことは「置いた」ことを意味しないので、提案を消す理由に
        # ならない。以前は認識失敗が5tick続くと提案をクリアしていたため、
        # 実機の録画解析で、提案が表示されていない時間が稼働時間の46%
        # (76.2秒/167秒)に達し、その合計が認識失敗の合計時間(78.7秒)と
        # ほぼ一致していた。特に積みが高いほど認識失敗が長引くため
        # (top<=8で平均1.08秒・最大8.09秒)、支援が最も必要な局面で提案が
        # 消えるという本末転倒な挙動になっていた。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
            self.worker._tick_once(capture=MagicMock())
        self.assertIsNotNone(self.received_draw_data[-1])

        with patch("src.app.recognize", return_value=None):
            for _ in range(MAX_CONSECUTIVE_RECOGNITION_FAILURES * 3):
                self.worker._tick_once(capture=MagicMock())

        self.assertIsNotNone(
            self.received_draw_data[-1],
            f"認識失敗で提案が消えた: {self.received_draw_data[-1]}",
        )
        self.assertIsNotNone(self.worker._last_valid_draw_data)

    def test_very_long_recognition_failure_eventually_clears_the_suggestion(self) -> None:
        # 認識失敗中も提案は維持するが、対局終了後の結果画面や映像の途絶では
        # 認識失敗が延々と続き、その間はSTALE_DRAW_DATA_TIMEOUT_SECの判定にも
        # 到達しない(認識に成功したtickでしか評価されないため)。無関係な画面に
        # 提案が残り続けないよう、上限を超えたらクリアすること。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
                self.worker._tick_once(capture=MagicMock())
        self.assertIsNotNone(self.received_draw_data[-1])

        limit = AssistWorker.SUGGESTION_HOLD_DURING_FAILURE_SEC
        # 認識失敗が始まる(この時刻が起点になる)
        with patch("src.app.time.monotonic", return_value=1000.1):
            with patch("src.app.recognize", return_value=None):
                for _ in range(MAX_CONSECUTIVE_RECOGNITION_FAILURES):
                    self.worker._tick_once(capture=MagicMock())
        self.assertIsNotNone(self.received_draw_data[-1])

        # 起点から上限手前まではまだ維持される
        with patch("src.app.time.monotonic", return_value=1000.1 + limit - 0.5):
            with patch("src.app.recognize", return_value=None):
                self.worker._tick_once(capture=MagicMock())
        self.assertIsNotNone(self.received_draw_data[-1])

        # 上限を超えたらクリアされる
        with patch("src.app.time.monotonic", return_value=1000.1 + limit + 0.5):
            with patch("src.app.recognize", return_value=None):
                self.worker._tick_once(capture=MagicMock())
        self.assertIsNone(self.received_draw_data[-1])

    def test_lock_is_detected_even_when_the_current_piece_image_is_unreadable(self) -> None:
        # 有識者資料[001]「認識の部分成功を返す」への対応の回帰テスト。
        # 以前は操作ミノが画像から読めないと、正しく読めていた盤面・NEXT・
        # HOLDまで丸ごと捨てて全体を失敗扱いにしていた。実機では認識失敗が
        # 稼働時間の45%を占めており、その間は手番の進行もHOLDの変化も
        # 追えなくなっていた。操作ミノの種類はNEXT履歴からも求められるので、
        # 画像から読めないことは全体の失敗を意味しない。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        with patch("src.app.recognize", return_value=_recognition(current_piece="T", hold_piece="Z")):
            self.worker._tick_once(capture=MagicMock())
        self.assertIsNotNone(self.received_draw_data[-1])

        # 操作ミノは画像から読めない(current_piece=None)が、NEXTは進んでおり
        # HOLDは変わっていない = 通常の固定。これを検出できること。
        self.cold_clear.poll_suggestion.return_value = None
        with patch(
            "src.app.recognize",
            return_value=_recognition(
                current_piece=None, hold_piece="Z", next_queue=("L", "J", "S", "Z", "I")
            ),
        ):
            self.worker._tick_once(capture=MagicMock())

        self.assertIsNone(
            self.received_draw_data[-1],
            "操作ミノが読めないだけで固定検出が止まっている",
        )
        # NEXT履歴から新しい操作ミノを決められていること
        self.assertEqual(self.worker._last_current_piece, "O")

    def test_unreadable_current_piece_is_not_counted_as_disagreement(self) -> None:
        # 画像から読めなかっただけの場合を「NEXT履歴との食い違い」として
        # 数えると、認識が苦しい高積み局面ほど誤って画像側へ再同期して
        # しまう(読めていない値を正としてしまう)。
        self.cold_clear.poll_suggestion.return_value = _move("O")
        with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
            self.worker._tick_once(capture=MagicMock())
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="T", next_queue=("L", "J", "S", "Z", "I")),
        ):
            self.worker._tick_once(capture=MagicMock())
        self.assertEqual(self.worker._last_current_piece, "O")

        for _ in range(AssistWorker.CURRENT_PIECE_DESYNC_TICKS * 2):
            with patch(
                "src.app.recognize",
                return_value=_recognition(current_piece=None, next_queue=("L", "J", "S", "Z", "I")),
            ):
                self.worker._tick_once(capture=MagicMock())

        self.assertEqual(
            self.worker._last_current_piece, "O", "読めない値へ再同期してしまっている"
        )

    def test_garbage_rise_triggers_a_new_suggestion_within_the_same_turn(self) -> None:
        # 仕様「最善手は、相手からの妨害で段がせりあがる場合を除き、表示を
        # 切り替えない」の“除き”にあたる明示的な例外の回帰テスト。
        # せり上がると着地位置が丸ごとずれるため、同じ手番の途中でも計算し直す。
        # これが無かったため、攻撃を受けても次の固定まで提案が更新されず、
        # 実機で「相手の攻撃に追い付かず、人間の独断で決めてしまう」と
        # 報告された。
        bottom = tuple((19, c) for c in range(10) if c != 3)

        self.cold_clear.poll_suggestion.return_value = _move("T", landing_cells=[(18, 0)])
        with patch("src.app.recognize", return_value=_recognition(current_piece="T", filled_cells=bottom)):
            self.worker._tick_once(capture=MagicMock())
        self.assertEqual(len(self.received_draw_data), 1)

        # 同じ手番のまま(NEXTは進んでいない)、おじゃまが1行せり上がる。
        risen = tuple((18, c) for c in range(10) if c != 3) + tuple(
            (19, c) for c in range(10) if c != 5
        )
        self.cold_clear.start_thinking.reset_mock()
        self.cold_clear.poll_suggestion.return_value = _move("T", landing_cells=[(17, 0)])
        with patch("src.app.time.monotonic", return_value=999.5):
            with patch(
                "src.app.recognize",
                return_value=_recognition(current_piece="T", filled_cells=risen),
            ):
                self.worker._tick_once(capture=MagicMock())

        self.cold_clear.start_thinking.assert_called_once()
        self.assertEqual(len(self.received_draw_data), 2, "せり上がり後に提案が更新されていない")
        self.assertEqual(self.received_draw_data[-1].landing_cells, [(17, 0)])

    def test_garbage_rise_preserves_whether_hold_was_already_used(self) -> None:
        # せり上がりでの再計算は新しいミノの出現ではないので、この手番で
        # HOLDを使用済みかどうかの判定を作り直してはいけない。
        # 作り直すとFalseに戻り、既に使ったHOLDを前提とする提案を採用しうる。
        bottom = tuple((19, c) for c in range(10) if c != 3)
        self.cold_clear.poll_suggestion.return_value = _move("T", landing_cells=[(18, 0)])
        # 新規スポーン時にHOLDが変化している = この手番でHOLDを使った
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece="T", hold_piece="Z", filled_cells=bottom),
        ):
            self.worker._tick_once(capture=MagicMock())
        with patch(
            "src.app.recognize",
            return_value=_recognition(
                current_piece="T",
                hold_piece="I",
                next_queue=("L", "J", "S", "Z", "I"),
                filled_cells=bottom,
            ),
        ):
            self.worker._tick_once(capture=MagicMock())
        self.assertTrue(self.worker._disallow_hold_active)

        risen = tuple((18, c) for c in range(10) if c != 3) + tuple(
            (19, c) for c in range(10) if c != 5
        )
        with patch("src.app.time.monotonic", return_value=999.5):
            with patch(
                "src.app.recognize",
                return_value=_recognition(
                    current_piece="T",
                    hold_piece="I",
                    next_queue=("L", "J", "S", "Z", "I"),
                    filled_cells=risen,
                ),
            ):
                self.worker._tick_once(capture=MagicMock())

        self.assertTrue(
            self.worker._disallow_hold_active, "せり上がりでHOLD使用済みの判定が消えている"
        )

    def test_latency_report_is_written_once_enough_samples_are_collected(self) -> None:
        # 「提示が遅い」に対して、どの区間が遅いのかを推測ではなく実測で
        # 示すための計測(有識者資料[084][085])。十分な件数が貯まったら
        # 中央値・95百分位・最大値をログへ出し、貯めた分は捨てること
        # (貯め続けるとメモリを圧迫し、古い区間の値が混ざる)。
        written: list[str] = []
        log = MagicMock()
        log.write.side_effect = written.append
        self.worker._debug_log_file = log

        for i in range(AssistWorker.LATENCY_REPORT_SAMPLES):
            self.worker._record_latency("tick全体", 0.05)
            self.worker._record_latency("画像取得と認識", 0.03)
        self.worker._report_latency_if_ready()

        text = "".join(written)
        self.assertIn("処理時間の統計", text)
        self.assertIn("画像取得と認識", text)
        self.assertEqual(self.worker._latency_samples, {})

    def test_latency_report_is_not_written_before_enough_samples(self) -> None:
        log = MagicMock()
        self.worker._debug_log_file = log
        self.worker._record_latency("tick全体", 0.05)
        self.worker._report_latency_if_ready()
        log.write.assert_not_called()

    def test_cold_clear_timeout_does_not_stop_the_worker_loop(self) -> None:
        # 実機の回帰テスト(crash_log.txt 2026-09-10T19:25:16)。
        # Cold Clear 2が5秒間応答しなくなり、その例外がワーカースレッドの外まで
        # 伝播してループが停止した。認識も表示も同じスレッドなので、NEXTの表示が
        # 最後の値のまま固まり、提示も出なくなった。AIの不調は認識・表示まで
        # 巻き込んで止める理由にならない(有識者資料[114])。
        self.cold_clear.poll_suggestion.side_effect = TimeoutError(
            "Cold Clear 2から5.0秒間応答がありませんでした"
        )
        with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
            self.worker._tick_once(capture=MagicMock())  # 例外が外へ出ないこと

        self.assertTrue(self.worker._cold_clear_broken)
        self.cold_clear.close.assert_called_once()

        # 壊れている間は問い合わせを繰り返さない(1回あたり応答待ちの時間を
        # 丸ごと浪費し、認識まで止まるため)。
        self.cold_clear.poll_suggestion.reset_mock()
        with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
            self.worker._tick_once(capture=MagicMock())
        self.cold_clear.poll_suggestion.assert_not_called()

    def test_cold_clear_is_recreated_after_the_cooldown(self) -> None:
        # 壊れたら作り直して復帰できること。連打しても復帰しないので間隔を空ける。
        self.cold_clear.poll_suggestion.side_effect = TimeoutError("応答なし")
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
                self.worker._tick_once(capture=MagicMock())
        self.assertTrue(self.worker._cold_clear_broken)

        cooldown = AssistWorker.COLD_CLEAR_RESTART_COOLDOWN_SEC
        new_client = MagicMock()
        # 待ち時間が明けたら、次のsignificant_changeで作り直される
        with patch("src.app.ColdClearClient", return_value=new_client):
            with patch("src.app.time.monotonic", return_value=1000.0 + cooldown + 0.1):
                with patch(
                    "src.app.recognize",
                    return_value=_recognition(
                        current_piece="O", next_queue=("L", "J", "S", "Z", "I")
                    ),
                ):
                    self.worker._tick_once(capture=MagicMock())

        self.assertFalse(self.worker._cold_clear_broken)
        self.assertIs(self.worker.cold_clear, new_client)
        new_client.start_thinking.assert_called_once()

    def test_broken_cold_clear_clears_the_displayed_suggestion(self) -> None:
        # 壊れる前の要求に対する答えはもう来ない。表示中の提案も根拠を失うので消す。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
                self.worker._tick_once(capture=MagicMock())
        self.assertIsNotNone(self.received_draw_data[-1])

        # POLL_INTERVAL_SECを超えた時刻にしないと、そもそも問い合わせが行われない。
        self.cold_clear.poll_suggestion.side_effect = OSError(22, "Invalid argument")
        with patch("src.app.time.monotonic", return_value=1000.2):
            with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
                self.worker._tick_once(capture=MagicMock())
        self.assertIsNone(self.received_draw_data[-1])

    def test_timeout_insurance_does_not_change_the_displayed_placement(self) -> None:
        # 実機の回帰テスト。significant_changeはnext_advanced以外に、一定時間
        # 更新が無い場合の保険(MAX_SIGNIFICANT_CHANGE_SILENCE_SEC=1.5秒)でも
        # 発火する。ここで確定状態まで解除していたため、1手に1.5秒以上かけると
        # 同じ手番の途中で提案が別の配置へ差し替わっていた。実機ログでは
        # 1手あたり0.7回(90回/129手)発火しており、「少なくとも1回は提示が
        # 変わってどこに置けばよいか分からなくなる」という報告に一致する。
        # 初心者が1手に1.5秒以上かけるのは普通であり、仕様「提示した配置は、
        # 実際にミノを置くまで変更しない」に反する。
        self.cold_clear.poll_suggestion.return_value = _move("T", landing_cells=[(19, 0)])
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
                self.worker._tick_once(capture=MagicMock())
        self.assertEqual(len(self.received_draw_data), 1)

        # 探索が深まって別の配置が返るようになる
        self.cold_clear.poll_suggestion.return_value = _move("T", landing_cells=[(19, 5)])
        # タイムアウト保険が発火する時刻(ネクストは進んでいない)
        elapsed = AssistWorker.MAX_SIGNIFICANT_CHANGE_SILENCE_SEC + 0.1
        with patch("src.app.time.monotonic", return_value=1000.0 + elapsed):
            with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
                self.worker._tick_once(capture=MagicMock())

        shown = [d for d in self.received_draw_data if d is not None]
        self.assertEqual(
            shown[-1].landing_cells, [(19, 0)], "タイムアウト保険で提示が差し替わっている"
        )

    def test_does_not_poll_before_any_position_was_sent(self) -> None:
        # 実機の回帰テスト。支援モードに入った直後、操作ミノがまだ読めないと
        # 局面を渡せない。それでも問い合わせていたため、考える対象が無い
        # Cold Clear 2から応答が返らず、応答待ちのタイムアウト(既定5秒)を
        # 丸ごと浪費していた(「開始してから5秒程度何も表示されない」)。
        rec = _recognition(current_piece=None, next_slots_raw=(None,) * 5)
        # 1tick目は局面を渡せずに戻る(ここでは問い合わせに到達しない)。
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch("src.app.recognize", return_value=rec):
                self.worker._tick_once(capture=MagicMock())

        # 2tick目はポーリング間隔を超えており、抑止が無ければ問い合わせてしまう。
        with patch("src.app.time.monotonic", return_value=1000.5):
            with patch("src.app.recognize", return_value=rec):
                self.worker._tick_once(capture=MagicMock())

        self.cold_clear.poll_suggestion.assert_not_called()

    def test_poll_is_skipped_while_no_position_has_been_sent(self) -> None:
        # 二重の保険。局面を渡していない状態(_thinking_turn_keyがNone)では、
        # Cold Clear 2に考える対象が無いため応答が返らず、応答待ちの
        # タイムアウト(既定5秒)を丸ごと浪費する。通常は
        # _needs_start_thinkingにより先に要求へ進むが、その経路を通らずに
        # 問い合わせへ到達しても浪費しないことを保証する。
        self.worker._needs_start_thinking = False
        self.worker._thinking_turn_key = None
        self.worker._last_current_piece = "T"
        self.worker._confirmed_next_slots = ("O", "L", "J", "S", "Z")
        # タイムアウト保険が先に発火すると、その場でstart_thinkingが走って
        # しまい、この経路を検証できない。直前に発火した状態にしておく。
        self.worker._last_significant_change_time = 1000.4

        with patch("src.app.time.monotonic", return_value=1000.5):
            with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
                self.worker._tick_once(capture=MagicMock())

        self.cold_clear.poll_suggestion.assert_not_called()

    def test_retries_start_thinking_every_tick_until_the_piece_is_known(self) -> None:
        # 渡せるようになったら即座に出せるよう、次の手やタイムアウト保険を
        # 待たずに毎tick試すこと。
        with patch(
            "src.app.recognize",
            return_value=_recognition(current_piece=None, next_slots_raw=(None,) * 5),
        ):
            self.worker._tick_once(capture=MagicMock())
        self.assertTrue(self.worker._needs_start_thinking)
        self.cold_clear.start_thinking.assert_not_called()

        # 次のtickで操作ミノが読めたら、ネクストが進んでいなくても要求する。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        with patch("src.app.recognize", return_value=_recognition(current_piece="T")):
            self.worker._tick_once(capture=MagicMock())
        self.cold_clear.start_thinking.assert_called_once()
        self.assertFalse(self.worker._needs_start_thinking)

    def test_hold_swap_updates_the_current_piece_immediately(self) -> None:
        # 実機の回帰テスト。既存HOLDとの交換ではネクストが進まないため、
        # NEXT履歴から決めている操作ミノが古いまま残る。画像とは食い違い
        # 続け、8tick後の再同期で初めて入れ替わり、そのとき提示済みの配置まで
        # 解除されて手番の途中で提案が別のミノの配置へ差し替わっていた
        # (「Lミノ提示の後にIミノを提示する振動」)。交換を即座に反映して
        # 食い違い自体を起こさないこと(有識者資料[037])。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        with patch(
            "src.app.recognize", return_value=_recognition(current_piece="T", hold_piece="I")
        ):
            self.worker._tick_once(capture=MagicMock())
        self.assertEqual(self.worker._last_current_piece, "T")
        self.assertEqual(self.worker._prev_hold_piece, "I")

        # ホールド交換: 操作ミノTがHOLDへ入り、HOLDにあったIが操作ミノになる。
        # ネクストは進まない。
        with patch(
            "src.app.recognize", return_value=_recognition(current_piece="I", hold_piece="T")
        ):
            self.worker._tick_once(capture=MagicMock())

        self.assertEqual(self.worker._last_current_piece, "I", "HOLD交換が反映されていない")
        self.assertEqual(self.worker._prev_hold_piece, "T")
        self.assertTrue(self.worker._disallow_hold_active, "HOLD使用済みになっていない")

    def test_first_store_into_empty_hold_is_not_a_swap(self) -> None:
        # 実機の回帰テスト。HOLDが空の状態でホールドすると、操作中のミノは
        # HOLDへ入るが、代わりに出てくるミノはHOLDではなくNEXTの先頭である。
        # これを交換として扱うと、操作ミノに「空だったHOLDの中身」=Noneを
        # 入れてしまい、以降の局面がすべて壊れる。実機では2手目以降ずっと
        # 干渉が続く重大な不具合になった
        # (ログ:「HOLD交換を検出: 操作ミノ I -> None」)。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        with patch(
            "src.app.recognize", return_value=_recognition(current_piece="T", hold_piece=None)
        ):
            self.worker._tick_once(capture=MagicMock())
        self.assertEqual(self.worker._last_current_piece, "T")
        self.assertIsNone(self.worker._prev_hold_piece)

        # HOLDが空→Tへ。NEXTの進行はまだ観測できていない(同じ並びのまま)。
        with patch(
            "src.app.recognize", return_value=_recognition(current_piece="O", hold_piece="T")
        ):
            self.worker._tick_once(capture=MagicMock())

        self.assertIsNotNone(
            self.worker._last_current_piece, "空HOLDへの初回格納を交換と誤認している"
        )

    def test_swap_is_not_declared_while_the_next_shift_is_undecided(self) -> None:
        # NEXTの移動量を判断できなかったtickを「進んでいない」とみなすと、
        # NEXTの進行が確定する前にHOLD欄の変化だけが先に見えた瞬間を
        # 交換と誤認する。確実に0と分かった場合だけ扱うこと。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        with patch(
            "src.app.recognize", return_value=_recognition(current_piece="T", hold_piece="I")
        ):
            self.worker._tick_once(capture=MagicMock())
        self.assertEqual(self.worker._last_current_piece, "T")

        # NEXTが全枠読めず移動量が判断できない状態で、HOLDだけが変化する。
        with patch(
            "src.app.recognize",
            return_value=_recognition(
                current_piece="I", hold_piece="T", next_slots_raw=(None,) * 5
            ),
        ):
            self.worker._tick_once(capture=MagicMock())

        self.assertEqual(
            self.worker._last_current_piece, "T", "移動量が不明なのに交換と断定している"
        )

    def test_hold_swap_does_not_change_the_displayed_placement(self) -> None:
        # 仕様「人間の置きミス、不要なHOLDも途中で変更しない」。
        # 交換の反映は内部の追跡だけで、表示中の配置には触れないこと。
        self.cold_clear.poll_suggestion.return_value = _move("T", landing_cells=[(19, 0)])
        with patch(
            "src.app.recognize", return_value=_recognition(current_piece="T", hold_piece="I")
        ):
            self.worker._tick_once(capture=MagicMock())
        self.assertEqual(len(self.received_draw_data), 1)

        with patch("src.app.time.monotonic", return_value=999.5):
            with patch(
                "src.app.recognize", return_value=_recognition(current_piece="I", hold_piece="T")
            ):
                self.worker._tick_once(capture=MagicMock())

        shown = [d for d in self.received_draw_data if d is not None]
        self.assertEqual(shown[-1].landing_cells, [(19, 0)], "HOLD交換で提示が変わっている")

    def test_unreadable_hold_does_not_discard_every_ai_result(self) -> None:
        # 要求時はHOLDが読めなければ直前の確定値を使う。照合側だけが生の値を
        # 使うと、HOLDが一瞬読めなくなっただけで必ず食い違い、その間の
        # AI結果がすべて棄却されて提示が遅れる。基準を揃えること。
        self.cold_clear.poll_suggestion.return_value = _move("T", landing_cells=[(19, 0)])
        with patch("src.app.time.monotonic", return_value=1000.0):
            with patch(
                "src.app.recognize", return_value=_recognition(current_piece="T", hold_piece="I")
            ):
                self.worker._tick_once(capture=MagicMock())
        self.received_draw_data.clear()

        # HOLDが読めないtick。「古い手番の結果」として棄却されてはいけない。
        written: list[str] = []
        log = MagicMock()
        log.write.side_effect = written.append
        self.worker._debug_log_file = log

        self.cold_clear.poll_suggestion.return_value = _move("T", landing_cells=[(19, 5)])
        with patch("src.app.time.monotonic", return_value=1000.2):
            with patch(
                "src.app.recognize",
                return_value=_recognition(current_piece="T", hold_piece=None, hold_known=False),
            ):
                self.worker._tick_once(capture=MagicMock())

        self.assertNotIn(
            "古い手番のAI結果を破棄",
            "".join(written),
            "HOLDが読めないだけでAI結果が棄却されている",
        )

    def test_lock_clears_the_executed_suggestion(self) -> None:
        # 固定を検出したら、役目を終えた提案を消すこと(置いたミノの上に
        # ドットが残り続けるのを防ぐ)。固定=NEXTが進み、かつHOLDが
        # 変わっていないこと(_detect_lock参照)。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        with patch("src.app.recognize", return_value=_recognition(current_piece="T", hold_piece="Z")):
            self.worker._tick_once(capture=MagicMock())
        self.assertIsNotNone(self.received_draw_data[-1])

        # NEXTが進み、HOLDは変わらない = 通常の固定。
        # このtickでは新しい提案が得られない状況にして、クリアだけを見る。
        self.cold_clear.poll_suggestion.return_value = None
        with patch(
            "src.app.recognize",
            return_value=_recognition(
                current_piece="O", hold_piece="Z", next_queue=("L", "J", "S", "Z", "I")
            ),
        ):
            self.worker._tick_once(capture=MagicMock())

        self.assertIsNone(self.received_draw_data[-1])

    def test_unreadable_hold_does_not_overwrite_the_known_hold_state(self) -> None:
        # 有識者資料[035]への対応の回帰テスト。HOLD欄が読めなかっただけの
        # 状態を「空欄」と解釈すると、次に読めた時に「HOLDが変化した」と
        # 誤判定し、固定の検出を誤る(空HOLDへの初回格納は固定なしで
        # NEXTを消費するため)。読めない間は直前の確定値を維持すること。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        with patch("src.app.recognize", return_value=_recognition(current_piece="T", hold_piece="Z")):
            self.worker._tick_once(capture=MagicMock())
        self.assertEqual(self.worker._prev_hold_piece, "Z")

        # HOLD欄が読めない(空欄なのか不明なのか分からない)tick
        with patch(
            "src.app.recognize",
            return_value=_recognition(
                current_piece="O",
                hold_piece=None,
                hold_known=False,
                next_queue=("L", "J", "S", "Z", "I"),
            ),
        ):
            self.worker._tick_once(capture=MagicMock())

        self.assertEqual(
            self.worker._prev_hold_piece, "Z", "読めなかっただけのHOLDで確定値を上書きしている"
        )

    def test_lock_is_not_declared_while_the_hold_state_is_unknown(self) -> None:
        # HOLDの変化の有無が分からない間は、固定と断定しない
        # (誤って実行前の提案を消さない方へ倒す)。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        with patch("src.app.recognize", return_value=_recognition(current_piece="T", hold_piece="Z")):
            self.worker._tick_once(capture=MagicMock())
        self.assertIsNotNone(self.received_draw_data[-1])

        self.cold_clear.poll_suggestion.return_value = None
        with patch(
            "src.app.recognize",
            return_value=_recognition(
                current_piece="O",
                hold_piece=None,
                hold_known=False,
                next_queue=("L", "J", "S", "Z", "I"),
            ),
        ):
            self.worker._tick_once(capture=MagicMock())

        self.assertIsNotNone(
            self.received_draw_data[-1], "HOLDが不明なのに固定と断定して提案を消している"
        )

    def test_first_hold_from_empty_is_not_treated_as_a_lock(self) -> None:
        # HOLDが空の状態でホールドすると、固定していないのにNEXTが1つ進む。
        # これを固定とみなすと、まだ置いていない提案を消してしまう。
        self.cold_clear.poll_suggestion.return_value = _move("T")
        with patch("src.app.recognize", return_value=_recognition(current_piece="T", hold_piece=None)):
            self.worker._tick_once(capture=MagicMock())
        self.assertIsNotNone(self.received_draw_data[-1])

        # NEXTが進み、かつHOLDが空から埋まった = 初回のホールド(固定なし)
        self.cold_clear.poll_suggestion.return_value = None
        with patch(
            "src.app.recognize",
            return_value=_recognition(
                current_piece="O", hold_piece="T", next_queue=("L", "J", "S", "Z", "I")
            ),
        ):
            self.worker._tick_once(capture=MagicMock())

        self.assertIsNotNone(
            self.received_draw_data[-1],
            "初回のホールドを固定と誤判定して提案を消している",
        )

    def test_stabilize_recognition_uses_raw_value_before_anything_has_ever_stabilized(self) -> None:
        # Tetris99のAI「ジェフ」の「安定した画像が得られるまで待機してから
        # 状態を読み取る」設計を参考にした_stabilize_recognitionの回帰テスト。
        # アプリ起動直後、まだ一度も安定した認識結果が得られていない場合は、
        # 反応の遅れを避けるため生の値をそのまま使うべき。
        with patch("src.app.time.monotonic", return_value=1000.0):
            result = self.worker._stabilize_recognition(_recognition(current_piece="A"))
        self.assertEqual(result.current_piece, "A")

    def test_stabilize_recognition_passes_through_with_the_default_setting(self) -> None:
        # 既定値では待たずに最新の認識結果をそのまま使うこと。
        # 実機の計測で、この待機が「提示が遅い」の主因(足止め中央値4tick、
        # 1tick約80msなので約320ms、95百分位で1.2〜1.4秒)と判明したため、
        # 項目ごとの個別対策に役割を譲って通り抜けるようにした。
        self.assertEqual(AssistWorker.RECOGNITION_STABILITY_TICKS, 1)
        with patch("src.app.time.monotonic", return_value=1000.0):
            first = self.worker._stabilize_recognition(_recognition(current_piece="A"))
        self.assertEqual(first.current_piece, "A")
        with patch("src.app.time.monotonic", return_value=1000.01):
            second = self.worker._stabilize_recognition(_recognition(current_piece="B"))
        self.assertEqual(second.current_piece, "B", "既定値なのに待機している")

    def test_stabilize_recognition_ignores_single_tick_noise(self) -> None:
        # 既定値は1(=この層を通り抜ける)なので、機構そのものを検証するために
        # 明示的に3へ差し替える。値を戻したくなったときの保険として残す。
        self.worker.RECOGNITION_STABILITY_TICKS = 3
        # 意味のある変化(current_piece等)が1〜2tickだけ観測されても、
        # RECOGNITION_STABILITY_TICKS回連続で確認できるまでは、直前に
        # 安定していた結果を使い続けるべき(1枚の画像だけで即断しない)。
        with patch("src.app.time.monotonic", return_value=1000.0):
            for _ in range(self.worker.RECOGNITION_STABILITY_TICKS):
                stable = self.worker._stabilize_recognition(_recognition(current_piece="A"))
        self.assertEqual(stable.current_piece, "A")  # ここでAとして確定済み

        # ノイズで1tickだけ別の値(B)が観測される。
        with patch("src.app.time.monotonic", return_value=1000.01):
            result = self.worker._stabilize_recognition(_recognition(current_piece="B"))
        self.assertEqual(result.current_piece, "A")  # まだAのまま維持される

        # 次のtickで元のAに戻る。
        with patch("src.app.time.monotonic", return_value=1000.02):
            result = self.worker._stabilize_recognition(_recognition(current_piece="A"))
        self.assertEqual(result.current_piece, "A")

    def test_stabilize_recognition_confirms_after_enough_consecutive_ticks(self) -> None:
        # 既定値は1(=この層を通り抜ける)なので、機構そのものを検証するために
        # 明示的に3へ差し替える。値を戻したくなったときの保険として残す。
        self.worker.RECOGNITION_STABILITY_TICKS = 3
        # RECOGNITION_STABILITY_TICKS回連続で同じ新しい内容が観測されたら、
        # 本物の変化として確定し、以降の提案生成に反映されるべき。
        with patch("src.app.time.monotonic", return_value=1000.0):
            for _ in range(self.worker.RECOGNITION_STABILITY_TICKS):
                self.worker._stabilize_recognition(_recognition(current_piece="A"))

        with patch("src.app.time.monotonic", return_value=1000.1):
            result = self.worker._stabilize_recognition(_recognition(current_piece="B"))
        self.assertEqual(result.current_piece, "A")  # 1回目: まだ確定しない

        with patch("src.app.time.monotonic", return_value=1000.11):
            result = self.worker._stabilize_recognition(_recognition(current_piece="B"))
        self.assertEqual(result.current_piece, "A")  # 2回目: まだ確定しない

        with patch("src.app.time.monotonic", return_value=1000.12):
            result = self.worker._stabilize_recognition(_recognition(current_piece="B"))
        self.assertEqual(result.current_piece, "B")  # 3回目連続で確定

    def test_stabilize_recognition_forces_adoption_after_timeout(self) -> None:
        # 既定値は1(=この層を通り抜ける)なので、機構そのものを検証するために
        # 明示的に3へ差し替える。値を戻したくなったときの保険として残す。
        self.worker.RECOGNITION_STABILITY_TICKS = 3
        # 新しい値がRECOGNITION_STABILITY_TICKS回連続では確認できなくても、
        # その値が観測され始めてからRECOGNITION_STABILITY_TIMEOUT_SEC以上
        # 経過したら、汚れている可能性を承知の上で強制的に採用すべき
        # (安定待ちの導入によって「いつまでも提案が更新されない」事態を
        # 新たに生まないための保険)。
        with patch("src.app.time.monotonic", return_value=1000.0):
            for _ in range(self.worker.RECOGNITION_STABILITY_TICKS):
                self.worker._stabilize_recognition(_recognition(current_piece="A"))

        timeout = AssistWorker.RECOGNITION_STABILITY_TIMEOUT_SEC
        # 新しい値Bが観測され始める(まだRECOGNITION_STABILITY_TICKS回には届かない)。
        with patch("src.app.time.monotonic", return_value=1000.001):
            result = self.worker._stabilize_recognition(_recognition(current_piece="B"))
        self.assertEqual(result.current_piece, "A")  # まだタイムアウト前

        # Bが観測され始めた時刻からtimeout以上経過(2回目の観測のまま)。
        with patch("src.app.time.monotonic", return_value=1000.001 + timeout + 0.1):
            result = self.worker._stabilize_recognition(_recognition(current_piece="B"))
        self.assertEqual(result.current_piece, "B")  # タイムアウト超過で強制採用


if __name__ == "__main__":
    unittest.main()
