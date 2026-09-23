"""教育モードの推奨手(第2段階)。

【仕様(教育モード仕様書 第5・6章)】
- 推奨手が参照するのは盤面・操作ミノ・HOLD(使用可否)・NEXT5まで。同一配列の
  再現用に保持している未表示の将来配列は渡さない。
- 開幕は既存の開幕テンプレ(はちみつ砲・迷走砲・山岳積み2号・オリーブ積み)を
  優先し、それ以外はCold Clear 2(CC2)の探索結果を使う。
- 同じミノを操作中は提示を維持し、固定・HOLD・一手戻す・リセットで更新する。
- 推奨配置は通常SRSで出現位置から到達できることを確かめ、操作手順も求める。
  「最善手」は採用エンジンの探索範囲内の推奨手であり、数学的な最適を保証しない。

座標: 教育モードの盤面は非表示2行を含む22行、テンプレ(openers)とCC2の盤面
(BoardState)は可視20行。変換は行に HIDDEN_ROWS を足し引きする。
"""

from __future__ import annotations

import copy
import time
from collections import deque
from dataclasses import dataclass, field, replace

from src.education.rules import COLS, HIDDEN_ROWS, NEXT_VISIBLE, ROWS, SPAWN_COL, SPAWN_ROW, Cell, GameState
from src.engine.board_state import BoardState
from src.engine.openers import (
    OpenerForm,
    OpenerStep,
    OpenerTemplate,
    choose_form,
    choose_opener,
    full_rows_after,
    known_sequence,
    shift_cells_for_clears,
)

# CC2の結果を採用するまでの最短の思考時間(秒)。これより前に届いた浅い結果では
# 固定しない(同じミノの間は提示を維持するので、最初の結果の質が大事)。
MIN_THINK_SEC = 0.4


@dataclass(frozen=True)
class Recommendation:
    piece: str
    use_hold: bool
    cells: tuple[Cell, ...]  # 22行の盤面座標
    source: str  # 表示用(「開幕テンプレ はちみつ砲 / 1巡目」「AI(Cold Clear 2)」等)
    steps: tuple[str, ...] | None  # 操作手順。出現位置から到達できなければNone


@dataclass
class _OpenerTrack:
    """進行中の開幕テンプレ(1つの図)と次に置く手の位置。座標は20行。"""

    template: OpenerTemplate
    form: OpenerForm
    steps: list[OpenerStep]
    index: int = 0

    def current(self) -> OpenerStep | None:
        return self.steps[self.index] if self.index < len(self.steps) else None


def _board20(board: tuple | list) -> set[tuple[int, int]]:
    return {(r - HIDDEN_ROWS, c) for r in range(HIDDEN_ROWS, ROWS) for c in range(COLS) if board[r][c] is not None}


def _to22(cells) -> tuple[Cell, ...]:
    return tuple((r + HIDDEN_ROWS, c) for r, c in cells)


def find_path(state: GameState, piece: str, target: tuple[Cell, ...]) -> tuple[str, ...] | None:
    """出現位置からtargetへハードドロップで置く操作手順(通常SRS)。無ければNone。

    幅優先探索で最短の手順を求める。左右移動・左右回転・ソフトドロップ(1マス)の
    組み合わせで、ハードドロップしたときにtargetの4マスになる位置を探す。
    """
    sim = copy.copy(state)
    sim.game_over = False
    goal = frozenset(target)
    start = (0, SPAWN_ROW, SPAWN_COL)
    sim.current, sim.orient, sim.row, sim.col = piece, *start
    if not sim._fits(piece, 0, SPAWN_ROW, SPAWN_COL):
        return None
    ops = (("←", "move_left"), ("→", "move_right"), ("左回転", "rotate_ccw"), ("右回転", "rotate_cw"), ("↓", "soft_drop"))
    prev: dict[tuple[int, int, int], tuple[tuple[int, int, int], str] | None] = {start: None}
    queue = deque([start])
    while queue:
        pos = queue.popleft()
        sim.orient, sim.row, sim.col = pos
        if frozenset(_ghost_cells(sim)) == goal:
            path: list[str] = []
            node = pos
            while prev[node] is not None:
                node, label = prev[node]
                path.append(label)
            return _compress(list(reversed(path)) + ["ハードドロップ"])
        for label, method in ops:
            sim.orient, sim.row, sim.col = pos
            if getattr(sim, method)():
                nxt = (sim.orient, sim.row, sim.col)
                if nxt not in prev:
                    prev[nxt] = (pos, label)
                    queue.append(nxt)
    return None


def _ghost_cells(sim: GameState) -> tuple[Cell, ...]:
    row = sim.ghost_row()
    saved = sim.row
    sim.row = row
    cells = sim.current_cells()
    sim.row = saved
    return cells


def _compress(path: list[str]) -> tuple[str, ...]:
    """同じ操作の連続を「→×2」のようにまとめる。"""
    out: list[str] = []
    count = 0
    for i, op in enumerate(path):
        count += 1
        if i + 1 == len(path) or path[i + 1] != op:
            out.append(f"{op}×{count}" if count > 1 else op)
            count = 0
    return tuple(out)


def board_state_for_engine(state: GameState) -> BoardState:
    """CC2へ渡す可視20行の盤面(占有だけ分かればよい)。"""
    board = BoardState()
    for r in range(HIDDEN_ROWS, ROWS):
        for c in range(COLS):
            if state.board[r][c] is not None:
                board.grid[r - HIDDEN_ROWS][c] = "G"
    return board


@dataclass
class Advisor:
    """練習中の局面に対する推奨手を出す。window側から毎tick update() を呼ぶ。"""

    engine_factory: object = None  # 引数なしで呼ぶとCC2クライアント(互換物)を返す
    opener_enabled: bool = True
    status: str = ""
    _engine: object = None
    _engine_failed: bool = False
    _turn_key: tuple | None = None
    _recommendation: Recommendation | None = None
    _requested_at: float | None = None
    _tracks: dict[int, _OpenerTrack | None] = field(default_factory=dict)
    _seed: int | None = None

    def close(self) -> None:
        if self._engine is not None and hasattr(self._engine, "close"):
            try:
                self._engine.close()
            except Exception:  # noqa: BLE001 - 終了処理の失敗で画面を止めない
                pass
        self._engine = None

    # ---- 公開 ----
    def update(self, state: GameState, now: float | None = None) -> Recommendation | None:
        now = time.monotonic() if now is None else now
        if state.game_over:
            return None
        if state.sequence.seed != self._seed:  # リセット(別の練習)
            self._seed = state.sequence.seed
            self._tracks = {}
        key = (len(state.history), state.hold_used, state.current, state.sequence_index, id(state.turn_start))
        if key != self._turn_key:
            self._turn_key = key
            self._recommendation = None
            self._requested_at = None
            track = self._sync_track(state)
            rec = self._from_track(state, track)
            if rec is not None:
                self._recommendation = rec
                return rec
            self._start_engine(state, now)
        if self._recommendation is None and self._requested_at is not None and now - self._requested_at >= MIN_THINK_SEC:
            self._recommendation = self._poll_engine(state)
        return self._recommendation

    # ---- 開幕テンプレ ----
    def _sync_track(self, state: GameState) -> _OpenerTrack | None:
        turn = len(state.history)
        # 一手戻す・やり直しでは、その手番で記録済みの進行状態を使う
        for stale in [t for t in self._tracks if t > turn]:
            del self._tracks[stale]
        if turn in self._tracks:
            return self._tracks[turn]
        track: _OpenerTrack | None = None
        if self.opener_enabled:
            prev = self._tracks.get(turn - 1)
            if turn == 0:
                track = self._start_track(state, None)
            elif prev is not None and state.last_lock is not None:
                track = self._advance_track(state, prev)
        self._tracks[turn] = track
        return track

    def _turn_sequence(self, state: GameState) -> tuple[list[str] | None, str | None, set[tuple[int, int]]]:
        """手番開始時点(HOLD前)に見えていたミノ順(操作ミノ+NEXT5)・HOLD・盤面。"""
        snap = state.turn_start
        if snap is None:
            return None, None, set()
        nexts = tuple(state.sequence.peek(snap.sequence_index + i) for i in range(NEXT_VISIBLE))
        # 袋の位置は配ったミノの数から分かる(未表示の配列を見ているわけではない)
        sequence = known_sequence(snap.current, nexts, snap.hold, snap.sequence_index - 1)
        return sequence, snap.hold, _board20(snap.board)

    def _start_track(self, state: GameState, template: OpenerTemplate | None) -> _OpenerTrack | None:
        sequence, hold, board = self._turn_sequence(state)
        if sequence is None:
            return None
        if template is None:
            if board or hold is not None:
                return None
            chosen = choose_opener(sequence, hold, board)
            if chosen is None:
                return None
            template, form, steps = chosen
        else:
            got = choose_form(template, board, sequence, hold)
            if got is None:
                return None
            form, steps = got
        return _OpenerTrack(template, form, list(steps))

    def _advance_track(self, state: GameState, prev: _OpenerTrack) -> _OpenerTrack | None:
        step = prev.current()
        piece, cells22 = state.last_lock  # type: ignore[misc]
        placed20 = {(r - HIDDEN_ROWS, c) for r, c in cells22}
        if step is None or step.piece != piece or set(step.cells) != placed20:
            return None  # 手順と違う置き方: テンプレをやめてAIの推奨手に戻す
        before = _board20(state.history[-1].board)
        cleared = full_rows_after(before, step.cells)
        rest = [replace(st, cells=shift_cells_for_clears(st.cells, cleared)) if cleared else st for st in prev.steps[prev.index + 1 :]]
        track = _OpenerTrack(prev.template, prev.form, prev.steps[: prev.index + 1] + rest, prev.index + 1)
        if track.current() is None:
            # 図を置き終えた: 同じテンプレの続きの図(2巡目以降)を探す
            return self._start_track(state, prev.template)
        return track

    def _from_track(self, state: GameState, track: _OpenerTrack | None) -> Recommendation | None:
        step = track.current() if track is not None else None
        if step is None:
            return None
        use_hold = step.use_hold and not state.hold_used
        piece_now = state.current
        if step.use_hold and state.hold_used:
            use_hold = False  # 指示どおりHOLDした後: 今の操作ミノで置く
        if not use_hold and piece_now != step.piece:
            return None  # 手順と違うHOLDをした: この手番はAIに任せる
        cells = _to22(step.cells)
        section = track.form.section.split(" > ")[-1]
        return Recommendation(
            piece=step.piece,
            use_hold=use_hold,
            cells=cells,
            source=f"開幕テンプレ {track.template.name_ja} / {section}",
            steps=self._steps(state, step.piece, cells, use_hold),
        )

    # ---- CC2 ----
    def _start_engine(self, state: GameState, now: float) -> None:
        engine = self._get_engine()
        if engine is None:
            return
        try:
            engine.start_thinking(
                board_state_for_engine(state),
                state.current,
                state.hold,
                list(state.visible_next()),  # NEXT5まで(将来配列は渡さない)
                disallow_hold=state.hold_used,
            )
            self._requested_at = now
            self.status = "AIが考えています…"
        except Exception as exc:  # noqa: BLE001
            self._fail(exc)

    def _poll_engine(self, state: GameState) -> Recommendation | None:
        if self._engine is None:
            return None
        try:
            move = self._engine.poll_suggestion(state.current)
        except Exception as exc:  # noqa: BLE001
            self._fail(exc)
            return None
        if move is None:
            return None
        use_hold = move.use_hold and not state.hold_used
        cells = _to22(move.landing_cells)
        self.status = ""
        return Recommendation(
            piece=move.piece,
            use_hold=use_hold,
            cells=cells,
            source="AI(Cold Clear 2)",
            steps=self._steps(state, move.piece, cells, use_hold),
        )

    def _get_engine(self):
        if self._engine is None and not self._engine_failed:
            if self.engine_factory is None:
                from src.engine.cold_clear_client import ColdClearClient

                self.engine_factory = ColdClearClient
            try:
                self._engine = self.engine_factory()
            except Exception as exc:  # noqa: BLE001
                self._fail(exc)
        return self._engine

    def _fail(self, exc: Exception) -> None:
        self._engine_failed = True
        self.close()
        self.status = f"AIを使えません: {exc}"

    @staticmethod
    def _steps(state: GameState, piece: str, cells: tuple[Cell, ...], use_hold: bool) -> tuple[str, ...] | None:
        path = find_path(state, piece, cells)
        if path is None:
            return None
        return (("ホールド",) if use_hold else ()) + path
