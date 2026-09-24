"""教育モードの推奨手(第2段階)。

【仕様(教育モード仕様書 第5・6章)】
- 推奨手が参照するのは盤面・操作ミノ・HOLD(使用可否)・NEXT5まで。同一配列の
  再現用に保持している未表示の将来配列は渡さない。
- 開幕は既存の開幕テンプレ(はちみつ砲・迷走砲・山岳積み2号)を優先し、
  それ以外はCold Clear 2(CC2)の探索結果を使う。
- 同じミノを操作中は提示を維持し、固定・HOLD・一手戻す・リセットで更新する。
- 推奨配置は通常SRSで出現位置から到達できることを確かめ、操作手順も求める。
  「最善手」は採用エンジンの探索範囲内の推奨手であり、数学的な最適を保証しない。
- 【2026-09-24・利用者の要望】成立するテンプレとCC2を候補として並べ、利用者が
  循環切替できる。オリーブ積みは候補に含めない(利用者の指示)。手順を外れても、
  盤面が図の途中形と完全に一致すれば定跡へ復帰する(置き順の入れ替え等)。
  難度はソフトドロップの区間数で◎(0回)・○(1回)・△(2回以上)を示す。

座標: 教育モードの盤面は非表示2行を含む22行、テンプレ(openers)とCC2の盤面
(BoardState)は可視20行。変換は行に HIDDEN_ROWS を足し引きする。
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace

import src.engine.openers as openers
from src.education.rules import COLS, HIDDEN_ROWS, NEXT_VISIBLE, ROWS, Cell, GameState
from src.engine.board_state import BoardState
from src.engine.openers import (
    OpenerForm,
    OpenerStep,
    OpenerTemplate,
    choose_form,
    full_rows_after,
    known_sequence,
    plan_form,
    shift_cells_for_clears,
    tuck_count,
)
from src.education.pc_search import TIMEOUT, find_perfect_clear
from src.engine.srs_reach import difficulty_mark, find_path, find_path_min_soft

# CC2の結果を採用するまでの最短の思考時間(秒)。これより前に届いた浅い結果では
# 固定しない(同じミノの間は提示を維持するので、最初の結果の質が大事)。
MIN_THINK_SEC = 0.4

AI_ID = "cc2"
AI_LABEL = "ColdClear2"
PC_ID = "pc"
# 【2026-09-24・利用者の指示】候補の切替対象に含めないテンプレ
EXCLUDED_TEMPLATES = frozenset({"オリーブ積み"})
# パフェ後にHOLDへ繰り越したミノを使って組むテンプレ(1巡目の図はHOLDがあるときだけ使う)
CARRY_TEMPLATES = frozenset({"DPC"})

__all__ = ["AI_ID", "PC_ID", "Advisor", "Candidate", "Recommendation", "find_path", "rejoin_form"]


@dataclass(frozen=True)
class Recommendation:
    piece: str
    use_hold: bool
    cells: tuple[Cell, ...]  # 22行の盤面座標
    source: str  # 表示用(「開幕テンプレ はちみつ砲 / 1巡目」「AI(Cold Clear 2)」等)
    steps: tuple[str, ...] | None  # 操作手順。出現位置から到達できなければNone
    soft_sections: int | None = None  # 難度の評価範囲で必要なソフトドロップの区間数
    scope: str = ""  # 難度の評価範囲(「この図の完成まで」「この1手」)


@dataclass(frozen=True)
class Candidate:
    """候補欄の1行。source_idはテンプレ名かAI_ID。"""

    source_id: str
    label: str
    mark: str  # ◎○△ / 評価待ち / 探索中 / 使用不可 / 空
    scope: str


@dataclass
class _OpenerTrack:
    """進行中の開幕テンプレ(1つの図)と次に置く手の位置。座標は20行。"""

    template: OpenerTemplate
    form: OpenerForm
    steps: list[OpenerStep]
    index: int = 0
    rejoined: bool = False  # 手順を外れた後、盤面が合流して復帰した

    def current(self) -> OpenerStep | None:
        return self.steps[self.index] if self.index < len(self.steps) else None


def _board20(board: tuple | list) -> set[tuple[int, int]]:
    return {(r - HIDDEN_ROWS, c) for r in range(HIDDEN_ROWS, ROWS) for c in range(COLS) if board[r][c] is not None}


def _to22(cells) -> tuple[Cell, ...]:
    return tuple((r + HIDDEN_ROWS, c) for r, c in cells)


def board_state_for_engine(state: GameState) -> BoardState:
    """CC2へ渡す可視20行の盤面(占有だけ分かればよい)。"""
    board = BoardState()
    for r in range(HIDDEN_ROWS, ROWS):
        for c in range(COLS):
            if state.board[r][c] is not None:
                board.grid[r - HIDDEN_ROWS][c] = "G"
    return board


def candidate_templates() -> tuple[OpenerTemplate, ...]:
    """候補に並べるテンプレ(並び順が候補欄の順)。開幕パフェ積み・DPCは教育モード専用。"""
    return tuple(t for t in openers.OPENER_TEMPLATES if t.name_ja not in EXCLUDED_TEMPLATES) + tuple(
        openers.EDUCATION_TEMPLATES
    )


def startable_template(
    template: OpenerTemplate, hold: str | None, bag_head: bool, continuing: bool = False
) -> OpenerTemplate:
    """今の手番から使える図だけのテンプレ。

    【2026-09-24・実画面 practice_20260924_190040】パフェ後(操作ミノは袋の先頭、HOLD=Z)
    に、山岳積み2号の1巡目の図をHOLDのZ(前の袋のミノ)を使って組む手順を推奨した。
    7種1巡からずれた組み方なので、空の盤面から組む1巡目の図(既存ブロックの無い図)は、
    通常のテンプレではHOLDが空で操作ミノが袋の先頭のときだけ使う。DPCは逆に、
    パフェ後にHOLDへ繰り越したミノがあり、操作ミノが袋の先頭のときだけ使う。

    【2026-09-24・実画面 practice_20260924_195905】Tスピンだけの図(はちみつ砲のTST等)は
    一致判定がゆるく、同じTSTの形を持つ迷走砲の盤面にも一致して「はちみつ砲」と表示した。
    Tスピンだけの図は、そのテンプレを続けてきた場合(continuing)だけ使う。
    """
    carry = template.name_ja in CARRY_TEMPLATES
    allow_empty = bag_head and ((hold is not None) if carry else (hold is None))
    forms = template.forms
    if not allow_empty:
        forms = tuple(f for f in forms if f.existing)
    if not continuing:
        forms = tuple(f for f in forms if not f.is_spin_only())
    return template if forms == template.forms else replace(template, forms=forms)


def rejoin_form(
    template: OpenerTemplate, board: set[tuple[int, int]], sequence: list[str], hold: str | None
) -> tuple[OpenerForm, list[OpenerStep]] | None:
    """盤面が図の途中形(既存ブロック+図のミノの一部)と完全に一致すれば、残りの手順。

    【2026-09-24・利用者の要望】手順が前後して一度テンプレを外れても、局面が
    合流したら定跡の提示へ戻す(例: 予定A→Bを実際はB→Aの順に置いた)。
    盤面の占有が完全に一致するときだけ復帰する(余分なブロックは許さない)。
    HOLDとツモ順は、残りの手順をそのミノ順で組めるか(plan_form)で確かめる。
    ライン消去を挟んだ途中形はまだ扱わない(図の座標と盤面がずれるため)。
    """
    best: tuple[tuple[int, int], OpenerForm, list[OpenerStep]] | None = None
    for form in template.forms:
        if not form.existing <= board:
            continue
        extra = board - form.existing
        if not extra:
            continue  # 図の開始時点そのもの(choose_formの担当)
        done = {i for i, item in enumerate(form.items) if set(item.cells) <= extra}
        if not done or len(done) == len(form.items):
            continue
        if set().union(*(form.items[i].cells for i in done)) != extra:
            continue
        rest = OpenerForm(
            form.section,
            form.existing,
            tuple(item for i, item in enumerate(form.items) if i not in done),
            form.text,
            form.tuck_pieces,
        )
        steps = plan_form(rest, sequence, hold, placed=set(board))
        if steps is None:
            continue
        # 回転入れの少ない手順、同じなら置くミノの多い図(choose_formと同じ優先)
        key = (tuck_count(board, steps), -len(form.items))
        if best is None or key < best[0]:
            best = (key, form, steps)
    return None if best is None else (best[1], best[2])


@dataclass
class Advisor:
    """練習中の局面に対する推奨手を出す。window側から毎tick update() を呼ぶ。"""

    engine_factory: object = None  # 引数なしで呼ぶとCC2クライアント(互換物)を返す
    opener_enabled: bool = True
    status: str = ""
    # 利用者が選んだ提示元(テンプレ名かAI_ID)。Noneなら自動(ソフトドロップの少ないテンプレ→AI)。
    preferred_id: str | None = None
    # 今実際に提示している提示元。希望のテンプレが一時的に組めない間はAI_ID。
    active_id: str | None = None
    # 【2026-09-24・利用者の要望】自動選択でテンプレよりAIを優先する(パフェは優先のまま)
    prefer_ai: bool = False
    _engine: object = None
    _engine_failed: bool = False
    _turn_key: tuple | None = None
    _requested_at: float | None = None
    _ai_rec: Recommendation | None = None
    _template_recs: dict[str, Recommendation] = field(default_factory=dict)
    # テンプレ名 → 手番(固定した数) → 追跡状態
    _tracks: dict[str, dict[int, _OpenerTrack | None]] = field(default_factory=dict)
    _practice_id: int | None = None
    _auto_id: str | None = None  # 自動選択で提示中のテンプレ(組める間は切り替えない)
    _pc_rec: Recommendation | None = None  # 見えているミノで取れるパフェの1手目
    pc_timed_out: bool = False  # パフェ探索が時間切れ(未判定)
    # 【2026-09-24・利用者の指摘】ホールド時に重かった。画面ではパフェ探索を別スレッドで
    # 行い、画面を止めない(pc_async=True)。テスト等では同期で探す。
    pc_async: bool = False
    pc_pending: bool = False  # 別スレッドで探索中
    _pc_future: object = None
    _pc_cancel: object = None
    _executor: object = None

    def close(self) -> None:
        self._cancel_pc()
        if self._executor is not None:
            self._executor.shutdown(wait=False)
            self._executor = None
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
        if state.practice_id != self._practice_id:  # リセット・盤面編集(別の練習)
            self._practice_id = state.practice_id
            self._tracks = {}
            self._auto_id = None
        key = (len(state.history), state.hold_used, state.current, state.sequence_index, id(state.turn_start))
        if key != self._turn_key:
            self._turn_key = key
            self._ai_rec = None
            self._requested_at = None
            self._template_recs = self._compute_template_recs(state) if self.opener_enabled else {}
            self._pc_rec = None
            if self.opener_enabled:
                self._start_pc(state)
            self._select()
        if self._pc_future is not None and self._pc_future.done():
            self._finish_pc(state)
        if self.active_id == PC_ID:
            return self._pc_rec
        if self.active_id == AI_ID:
            if self._requested_at is None:
                self._start_engine(state, now)
            if self._ai_rec is None and self._requested_at is not None and now - self._requested_at >= MIN_THINK_SEC:
                self._ai_rec = self._poll_engine(state)
            return self._ai_rec
        return self._template_recs.get(self.active_id or "")

    def candidates(self) -> tuple[Candidate, ...]:
        """候補欄に並べる、今の局面で成立する提示元(テンプレの順→AI)。"""
        result = []
        for template in candidate_templates():
            rec = self._template_recs.get(template.name_ja)
            if rec is not None:
                result.append(Candidate(template.name_ja, template.name_ja, difficulty_mark(rec.soft_sections), rec.scope))
        if self._pc_rec is not None:
            # 【2026-09-24・利用者の指示】パフェは候補欄に分岐として出す
            result.append(Candidate(PC_ID, self._pc_rec.source, difficulty_mark(self._pc_rec.soft_sections), self._pc_rec.scope))
        if self._engine_failed:
            mark, scope = "使用不可", ""
        elif self._ai_rec is not None:
            mark, scope = difficulty_mark(self._ai_rec.soft_sections), self._ai_rec.scope
        elif self.active_id == AI_ID and self._requested_at is not None:
            mark, scope = "探索中", ""
        else:
            mark, scope = "", ""
        result.append(Candidate(AI_ID, AI_LABEL, mark, scope))
        return tuple(result)

    def choose(self, source_id: str) -> bool:
        """提示元を選ぶ(候補の直接選択)。盤面・操作ミノ・履歴は変えない。"""
        if source_id not in [c.source_id for c in self.candidates()]:
            return False
        changed = source_id != self.active_id
        self.preferred_id = source_id
        self.active_id = source_id
        return changed

    def cycle(self) -> bool:
        """次の候補へ切り替える(テンプレの順→AI→最初へ)。候補が1つなら何もしない。"""
        ids = [c.source_id for c in self.candidates()]
        if len(ids) < 2:
            return False
        position = ids.index(self.active_id) if self.active_id in ids else -1
        return self.choose(ids[(position + 1) % len(ids)])

    def set_prefer_ai(self, value: bool) -> None:
        """テンプレ優先/AI優先の切替。利用者が明示的に選んだ候補の選択は解除する。"""
        self.prefer_ai = value
        self.preferred_id = None
        self._select()

    def _select(self) -> None:
        """希望(preferred_id)を保ったまま、今の局面で実際に提示する候補を決める。"""
        available = [t.name_ja for t in candidate_templates() if t.name_ja in self._template_recs]
        # 【2026-09-24・利用者の指示】テンプレを続けている間はテンプレを優先し、
        # それ以外(AIで提示する局面)で5手以内のパフェが見えればパフェを提示する。
        fallback = PC_ID if self._pc_rec is not None else AI_ID
        if self.preferred_id is not None:
            # 希望のテンプレが一時的に組めない間はパフェかAIで提示し、組めるようになったら戻る。
            # 明示的にAIを選んだ場合は、テンプレが組めても勝手に切り替えない。
            if self.preferred_id == AI_ID or self.preferred_id in available:
                self.active_id = self.preferred_id
            else:
                self.active_id = fallback
            return
        if self.prefer_ai:
            self.active_id = fallback
            return
        if self._auto_id not in available and available:
            # 【2026-09-23・利用者の指示】ソフトドロップの少ないテンプレを選ぶ(同じなら並び順)
            def cost(name: str) -> tuple:
                sections = self._template_recs[name].soft_sections
                return (sections is None, sections or 0, available.index(name))

            self._auto_id = min(available, key=cost)
        self.active_id = self._auto_id if self._auto_id in available else fallback

    # ---- 開幕テンプレ ----
    def _compute_template_recs(self, state: GameState) -> dict[str, Recommendation]:
        recs: dict[str, Recommendation] = {}
        for template in candidate_templates():
            rec = self._from_track(state, self._sync_track(state, template))
            # 実際に置ける操作手順が無い手は候補にしない
            if rec is not None and rec.steps is not None:
                recs[template.name_ja] = rec
        return recs

    def _pc_inputs(self, state: GameState):
        """パフェ探索に渡す(盤面, ミノ順, HOLD, HOLDできるか)。見えている範囲だけ。"""
        sequence, _hold, _board = self._turn_sequence(state)
        if sequence is None:
            return None
        snap = state.turn_start
        if state.hold_used:
            # この手番でHOLD済み: 今の操作ミノから、HOLDせずに置く手順だけを探す
            rest = sequence[2:] if snap.hold is None else sequence[1:]
            sequence = [state.current, *rest]
        board = frozenset((r, c) for r in range(ROWS) for c in range(COLS) if state.board[r][c] is not None)
        return board, sequence, state.hold, not state.hold_used

    def _start_pc(self, state: GameState) -> None:
        self._cancel_pc()
        self.pc_timed_out = False
        inputs = self._pc_inputs(state)
        if inputs is None:
            return
        board, sequence, hold, can_hold = inputs
        if not self.pc_async:
            self._pc_rec = self._pc_recommendation(
                state, find_perfect_clear(board, sequence, hold, can_hold=can_hold)
            )
            return
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pc_search")
        self._pc_cancel = threading.Event()
        self._pc_future = self._executor.submit(
            find_perfect_clear, board, sequence, hold, can_hold=can_hold, time_limit=3.0, cancel=self._pc_cancel
        )
        self.pc_pending = True

    def _cancel_pc(self) -> None:
        """局面が変わった: 古い探索を打ち切り、結果を使わない。"""
        if self._pc_cancel is not None:
            self._pc_cancel.set()
        self._pc_future = None
        self._pc_cancel = None
        self.pc_pending = False

    def _finish_pc(self, state: GameState) -> None:
        """別スレッドの探索結果を受け取る(同じ局面の依頼の結果だけが残っている)。"""
        future, self._pc_future = self._pc_future, None
        self._pc_cancel = None
        self.pc_pending = False
        try:
            found = future.result()
        except Exception:  # noqa: BLE001 - 探索の失敗で画面を止めない
            return
        self._pc_rec = self._pc_recommendation(state, found)
        if self._pc_rec is not None:
            self._select()

    def _pc_recommendation(self, state: GameState, found) -> Recommendation | None:
        """パフェ探索の結果から1手目の推奨を作る(ソフトドロップの多さは問わない)。"""
        if found == TIMEOUT:
            self.pc_timed_out = True  # 未判定(無いとは断定しない)
            return None
        if not found:
            return None
        first = found[0]
        path = find_path_min_soft(state, first.piece, first.cells)
        if path is None:
            return None
        return Recommendation(
            piece=first.piece,
            use_hold=first.use_hold,
            cells=first.cells,
            source=f"パフェ(あと{len(found)}手)",
            steps=(("ホールド",) if first.use_hold else ()) + path[0],
            soft_sections=_pc_soft_sections(state, found),
            scope="パフェまで",
        )

    def _sync_track(self, state: GameState, template: OpenerTemplate) -> _OpenerTrack | None:
        turn = len(state.history)
        tracks = self._tracks.setdefault(template.name_ja, {})
        # 一手戻す・やり直しでは、その手番で記録済みの進行状態を使う
        for stale in [t for t in tracks if t > turn]:
            del tracks[stale]
        if turn in tracks:
            return tracks[turn]
        prev = tracks.get(turn - 1)
        track: _OpenerTrack | None = None
        if prev is not None and state.last_lock is not None:
            track = self._advance_track(state, prev)
        if track is None:
            # 開始時・手順を外れた後: 今の局面から組める図か、図の途中形への合流を探す。
            # 【2026-09-24】以前は一度外れると(前の手番がNone)探し直さず、盤面が
            # 合流しても定跡へ戻れなかった。
            track = self._start_track(state, template, rejoin=turn > 0)
        tracks[turn] = track
        return track

    def _turn_sequence(self, state: GameState) -> tuple[list[str] | None, str | None, set[tuple[int, int]]]:
        """手番開始時点(HOLD前)に見えていたミノ順(操作ミノ+NEXT5)・HOLD・盤面。"""
        snap = state.turn_start
        if snap is None:
            return None, None, set()
        nexts = tuple(state.sequence.peek(snap.sequence_index + i) for i in range(NEXT_VISIBLE))
        # 袋の位置は配ったミノの数から分かる(未表示の配列を見ているわけではない)。
        # 【2026-09-24・実画面 practice_20260924_191133】手番の開始時点(HOLD前)の袋の先頭は
        # 必ず操作ミノ(HOLDのミノは前の手番から持っているもの)。以前はHOLDも先頭の候補に
        # 渡していたため「先頭がどちらか分からない」扱いになり、7個目を補えず、HOLDのL+
        # 次の袋の8個を使うはちみつ砲の2巡目を組めなかった。
        sequence = known_sequence(snap.current, nexts, None, snap.sequence_index - 1)
        return sequence, snap.hold, _board20(snap.board)

    def _start_track(
        self, state: GameState, template: OpenerTemplate, rejoin: bool = False, continuing: bool = False
    ) -> _OpenerTrack | None:
        sequence, hold, board = self._turn_sequence(state)
        if sequence is None:
            return None
        bag_head = (state.turn_start.sequence_index - 1) % 7 == 0
        got = choose_form(startable_template(template, hold, bag_head, continuing), board, sequence, hold)
        if got is None:
            # 盤面エディタで図の途中形を作って始めた場合も、ここで合流する
            got = rejoin_form(template, board, sequence, hold)
        else:
            rejoin = False
        if got is None:
            return None
        form, steps = got
        return _OpenerTrack(template, form, list(steps), rejoined=rejoin)

    def _advance_track(self, state: GameState, prev: _OpenerTrack) -> _OpenerTrack | None:
        step = prev.current()
        piece, cells22 = state.last_lock  # type: ignore[misc]
        placed20 = {(r - HIDDEN_ROWS, c) for r, c in cells22}
        if step is None or step.piece != piece or set(step.cells) != placed20:
            return None  # 手順と違う置き方: 合流点を探し、無ければAIの推奨手に戻す
        before = _board20(state.history[-1].board)
        cleared = full_rows_after(before, step.cells)
        rest = [replace(st, cells=shift_cells_for_clears(st.cells, cleared)) if cleared else st for st in prev.steps[prev.index + 1 :]]
        track = _OpenerTrack(prev.template, prev.form, prev.steps[: prev.index + 1] + rest, prev.index + 1, prev.rejoined)
        if track.current() is None:
            # 図を置き終えた: 同じテンプレの続きの図(2巡目以降)を探す
            return self._start_track(state, prev.template, continuing=True)
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
        if track.template.name_ja in CARRY_TEMPLATES:
            kind = "テンプレ"
            section = track.form.section  # DPCはパターン名(「S-03 トラックDPC > 組み方」等)まで示す
        else:
            kind = "開幕テンプレ"
            section = track.form.section.split(" > ")[-1]
        # 操作手順も、難度(◎○△)と同じくソフトドロップの区間が最も少ない経路で示す
        path = find_path_min_soft(state, step.piece, cells, spin_entry=step.spin and step.piece == "T")
        return Recommendation(
            piece=step.piece,
            use_hold=use_hold,
            cells=cells,
            source=f"{kind} {track.template.name_ja} / {section}" + (" (定跡に復帰)" if track.rejoined else ""),
            steps=None if path is None else (("ホールド",) if use_hold else ()) + path[0],
            soft_sections=_form_soft_sections(state, track),
            scope="この図の完成まで",
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
        path = find_path_min_soft(state, move.piece, cells)
        return Recommendation(
            piece=move.piece,
            use_hold=use_hold,
            cells=cells,
            source="AI(Cold Clear 2)",
            steps=None if path is None else (("ホールド",) if use_hold else ()) + path[0],
            soft_sections=None if path is None else path[1],
            scope="この1手",
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


def _form_soft_sections(state: GameState, track: _OpenerTrack) -> int | None:
    """今の手から図の完成までに必要なソフトドロップの区間数(置けない手があればNone)。

    盤面に図の手を順に置き(揃った行は消して残りの手の座標をずらす)、各手を
    ソフトドロップの区間が最少の経路で数えて合計する。
    """
    sim = GameState(sequence=state.sequence)
    sim.board = [list(row) for row in state.board]
    steps = list(track.steps[track.index :])
    total = 0
    while steps:
        step = steps.pop(0)
        cells = _to22(step.cells)
        path = find_path_min_soft(sim, step.piece, cells, spin_entry=step.spin and step.piece == "T")
        if path is None:
            return None
        total += path[1]
        cleared = full_rows_after(_board20(sim.board), step.cells)
        for r, c in cells:
            sim.board[r][c] = step.piece
        for r in sorted(r + HIDDEN_ROWS for r in cleared):
            del sim.board[r]
            sim.board.insert(0, [None] * COLS)
        if cleared:
            steps = [replace(st, cells=shift_cells_for_clears(st.cells, cleared)) for st in steps]
    return total


def _pc_soft_sections(state: GameState, steps) -> int | None:
    """パフェの手順(消去後の座標で並んだ手)に必要なソフトドロップの区間数の合計。"""
    sim = GameState(sequence=state.sequence)
    sim.board = [list(row) for row in state.board]
    total = 0
    for step in steps:
        path = find_path_min_soft(sim, step.piece, step.cells)
        if path is None:
            return None
        total += path[1]
        for r, c in step.cells:
            sim.board[r][c] = step.piece
        for r in [r for r in range(ROWS) if all(cell is not None for cell in sim.board[r])]:
            del sim.board[r]
            sim.board.insert(0, [None] * COLS)
    return total
