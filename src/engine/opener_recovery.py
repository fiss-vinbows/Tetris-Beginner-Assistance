"""開幕テンプレの手順位置の復元(認識欠落後)。

【背景(2026-09-13実機・有識者レビュー2026-09-14)】ライン消去の演出(キャラの
イラスト等)が盤面を覆っている間はrecognize()がNoneを返すが、その間も
プレイヤーの手は進む。演出明けの盤面は「次の1手を置いた後の期待盤面」と
一致しないため、従来は期待外4マス以上で即中断していた(2巡目以降が出なく
なる主因)。猶予を延ばすだけでは、既に2手以上進んだ盤面は1手後の期待盤面
に戻らないので解決しない。

ここでは、最後に確定したテンプレ状態(盤面・残り手順・手番)から残りの手順を
順番どおりに0手・1手・2手…と進めた候補を作り、観測した盤面と手番(操作
ミノ・HOLD・NEXT・HOLD可否)に一致する候補を探す。一意に一致したときだけ、
その位置から手順を再開する。

【この部品が保証しないこと】
- 一意性は「探索上限(max_steps)の範囲内で一意」という意味で、上限を超えて
  進んだ可能性まで否定しない。NEXTの照合(予測した残りNEXTが観測の先頭と
  一致すること)を独立した証拠として使うが、確定はRecoveryGateで複数の
  独立したキャプチャにわたって同じ候補が一致することを要求する。
- 配置の判定はセル数・範囲・衝突・支持のみで、回転入れの経路は検証しない。
- 図をまたぐ復元、途中のおじゃま変化、手順の順序入替は扱わない。
- 未知のミノ種を推測で埋めない(観測にないNEXTは照合しない)。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from .openers import BOARD_COLS, BOARD_ROWS, apply_step, full_rows_after, shift_cells_for_clears

PIECES = frozenset("IOTSZJL")
Cell = tuple[int, int]


def placement_invalid_reason(occupied: set[Cell], cells: Sequence[Cell]) -> str | None:
    """配置が盤面上で成立しない理由を返す(成立するならNone)。

    invalid_cell_count: 異なる4マスでない / out_of_bounds: 盤面外 /
    collision: 既に埋まっている / unsupported: どのマスの真下にも支えがない
    """
    if len(cells) != 4 or len(set(cells)) != 4:
        return "invalid_cell_count"
    for row, col in cells:
        if not (0 <= row < BOARD_ROWS and 0 <= col < BOARD_COLS):
            return "out_of_bounds"
        if (row, col) in occupied:
            return "collision"
    placed = set(cells)
    if not any(row + 1 == BOARD_ROWS or ((row + 1, col) not in placed and (row + 1, col) in occupied) for row, col in placed):
        return "unsupported"
    return None


@dataclass(frozen=True)
class RecoveryStep:
    """手順の1手(app側のOpenerStepと同じ内容。app側の型に依存しないための写し)。"""

    piece: str
    cells: tuple[Cell, ...]
    use_hold: bool = False
    spin: bool = False


@dataclass(frozen=True)
class TurnState:
    """手番の観測/予測: 操作ミノ・HOLD・NEXT・この手番でHOLDを使えるか。"""

    current: str
    hold: str | None
    next_queue: tuple[str, ...]
    hold_allowed: bool = True


@dataclass(frozen=True)
class RecoveryState:
    """最後に確定したテンプレ状態(盤面・残り手順・手番)。"""

    board: frozenset[Cell]
    remaining: tuple[RecoveryStep, ...]
    turn: TurnState


@dataclass(frozen=True)
class RecoveryCandidate:
    consumed: int  # 最後の確定状態から何手進んだか
    state: RecoveryState  # その位置の状態(残り手順の座標は消去後にずらし済み)
    pending_hold_applied: bool = False  # 次の手のHOLD交換だけ済んでいる(固定はまだ)


@dataclass(frozen=True)
class RecoveryResult:
    status: str  # unique_within_bound / ambiguous / unresolved
    candidates: tuple[RecoveryCandidate, ...]
    reason: str = ""


def _valid_turn(turn: TurnState) -> bool:
    return (
        turn.current in PIECES
        and (turn.hold is None or turn.hold in PIECES)
        and all(piece in PIECES for piece in turn.next_queue)
    )


def _hold(turn: TurnState) -> TurnState | None:
    """HOLD交換後の手番。空のHOLDへの格納はNEXTを1つ消費する。"""
    if not turn.hold_allowed:
        return None
    if turn.hold is not None:
        return TurnState(turn.hold, turn.current, turn.next_queue, False)
    if not turn.next_queue:
        return None
    return TurnState(turn.next_queue[0], turn.current, turn.next_queue[1:], False)


def _lock(turn: TurnState) -> TurnState | None:
    """固定後の手番(NEXTの先頭が操作ミノになり、HOLDは再び使える)。"""
    if not turn.next_queue:
        return None
    return TurnState(turn.next_queue[0], turn.hold, turn.next_queue[1:], True)


def _matches(predicted: TurnState, observed: TurnState) -> bool:
    """予測した手番が観測と矛盾しないか。

    予測に残っているNEXTが1つ以上あり、それが観測NEXTの先頭と一致することを
    要求する(見えていない将来を勝手に埋めない)。
    """
    return (
        predicted.current == observed.current
        and predicted.hold == observed.hold
        and predicted.hold_allowed == observed.hold_allowed
        and bool(predicted.next_queue)
        and len(observed.next_queue) >= len(predicted.next_queue)
        and observed.next_queue[: len(predicted.next_queue)] == predicted.next_queue
    )


def _advance_board(
    board: frozenset[Cell], remaining: tuple[RecoveryStep, ...]
) -> tuple[frozenset[Cell], tuple[RecoveryStep, ...]] | None:
    """残り手順の先頭を置いた後の盤面と、消去に合わせてずらした残り手順。"""
    step = remaining[0]
    if placement_invalid_reason(set(board), step.cells) is not None:
        return None
    cleared = full_rows_after(set(board), step.cells)
    board_after = frozenset(apply_step(set(board), step.cells))
    rest: list[RecoveryStep] = []
    for item in remaining[1:]:
        if any(row in cleared for row, _col in item.cells):
            # 消える行にまたがる未配置のミノは図の前提が崩れるので再計画が要る
            return None
        rest.append(replace(item, cells=tuple(shift_cells_for_clears(item.cells, cleared))))
    return board_after, tuple(rest)


def find_recovery(
    initial: RecoveryState,
    observed_board: frozenset[Cell],
    observed_turn: TurnState,
    *,
    max_steps: int = 3,
) -> RecoveryResult:
    """同じ図の予定順序で0〜max_steps手進めた候補から、観測に一致するものを探す。

    本体の状態は書き換えない。一致が1つならunique_within_bound、複数なら
    ambiguous、無ければunresolved(reasonに理由)。
    """
    if max_steps < 0:
        raise ValueError("max_steps must be nonnegative")
    if not _valid_turn(initial.turn) or not _valid_turn(observed_turn):
        return RecoveryResult("unresolved", (), "unknown_turn")
    matches: list[RecoveryCandidate] = []
    state = initial
    exhausted = False
    limit = min(max_steps, len(initial.remaining))
    for consumed in range(limit + 1):
        if state.board == observed_board and _matches(state.turn, observed_turn):
            matches.append(RecoveryCandidate(consumed, state))
        if state.remaining and state.remaining[0].use_hold:
            held = _hold(state.turn)
            if held is not None and state.board == observed_board and _matches(held, observed_turn):
                # 次の手のHOLD交換だけ済んでいる。残り先頭のuse_holdは消して
                # 「もう一度HOLDせよ」と指示しないようにする。
                rest = (replace(state.remaining[0], use_hold=False), *state.remaining[1:])
                matches.append(RecoveryCandidate(consumed, RecoveryState(state.board, rest, held), True))
        if consumed == limit:
            break
        step = state.remaining[0]
        turn = _hold(state.turn) if step.use_hold else state.turn
        if turn is None or turn.current != step.piece:
            exhausted = True
            break
        next_turn = _lock(turn)
        after = _advance_board(state.board, state.remaining)
        if next_turn is None or after is None:
            exhausted = True
            break
        state = RecoveryState(after[0], after[1], next_turn)
    if len(matches) == 1:
        return RecoveryResult("unique_within_bound", tuple(matches))
    if matches:
        return RecoveryResult("ambiguous", tuple(matches))
    return RecoveryResult("unresolved", (), "known_sequence_or_geometry_limit" if exhausted else "no_match_within_bound")


@dataclass
class RecoveryGate:
    """独立したキャプチャで同じ候補が続けて一致したときだけ確定する。

    frame_idは呼び出し側が「別のキャプチャ」であることを保証する識別子を渡す
    (同じ画像を再処理した連番は独立した観測にならない)。
    """

    required_frames: int = 2
    last_frame_id: object = None
    key: object = None
    confirmations: int = 0

    def reset(self) -> None:
        self.last_frame_id = None
        self.key = None
        self.confirmations = 0

    def accept(
        self,
        result: RecoveryResult,
        *,
        frame_id: object,
        trustworthy: bool,
        observed_turn: TurnState,
    ) -> RecoveryCandidate | None:
        if frame_id == self.last_frame_id:
            return None
        self.last_frame_id = frame_id
        if not trustworthy or result.status != "unique_within_bound":
            self.key = None
            self.confirmations = 0
            return None
        candidate = result.candidates[0]
        key = (candidate, observed_turn)
        if key != self.key:
            self.key = key
            self.confirmations = 1
        else:
            self.confirmations += 1
        if self.confirmations >= self.required_frames:
            self.key = None
            self.confirmations = 0
            return candidate
        return None
