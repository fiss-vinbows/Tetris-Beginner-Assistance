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

import copy
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace

import src.engine.openers as openers
from src.education.rules import COLS, HIDDEN_ROWS, NEXT_VISIBLE, PIECES, ROWS, Cell, GameState
from src.engine.board_state import BoardState
from src.engine.openers import (
    OpenerForm,
    OpenerStep,
    OpenerTemplate,
    carried_pieces,
    choose_form,
    full_rows_after,
    known_sequence,
    plan_form,
    shift_cells_for_clears,
    tuck_count,
    TD_TEMPLATE_NAMES,
    TDTD_DISCARDS,
)
from src.education.pc_odds import best_odds_move
from src.education import ren_stack
from src.education.ren_search import find_ren_plan
from src.education.pc_search import TIMEOUT, PCStep, find_perfect_clear, has_tetris
from src.education.six_three import WELL_COL, best_move
from src.engine.srs_reach import difficulty_mark, find_path, find_path_min_soft

# CC2の結果を採用するまでの最短の思考時間(秒)。これより前に届いた浅い結果では
# 固定しない(同じミノの間は提示を維持するので、最初の結果の質が大事)。
MIN_THINK_SEC = 0.4

AI_ID = "cc2"
AI_LABEL = "ColdClear2"
PC_ID = "pc"
# 【2026-09-28・利用者の要望】継続パフェ(パフェの後に続けて取るパフェ)。見えないミノも含めて
# 成功率が一番高い置き方を案内する(pc_odds.py)。5連続までを視野に、パフェ直後と、その案内に
# 従っている間(と候補欄で選んでいる間)だけ計算する(1回に数秒かかるため)
PC_ODDS_ID = "pc-odds"
PC_ODDS_LABEL = "継続パフェ"
ODDS_TIME_LIMIT = 1.0  # 計算の上限(秒)。【2026-09-29・利用者の指摘(少し遅い)】2秒から縮めた
ODDS_AUTO_MIN = 0.5  # 自動で選ぶのは成功率がこれ以上のとき(低いときは候補欄に出すだけ)
# 【2026-09-24・利用者の要望】6-3積み(左から7列目を井戸にしてテトリスで消す)。候補欄の1つ
SIX_THREE_ID = "6-3"
SIX_THREE_LABEL = "6-3積み"
# 【2026-09-24・利用者の指示】候補の切替対象に含めないテンプレ
EXCLUDED_TEMPLATES = frozenset({"オリーブ積み"})
# パフェ後にHOLDへ繰り越したミノを使って組むテンプレ(1巡目の図はHOLDがあるときだけ使う)
CARRY_TEMPLATES = frozenset({"DPC"})
# 【2026-10-02・利用者の要望】候補が多すぎるので、設定欄で表示を切り替える(Advisor.hidden)。
# テンプレはテンプレ名、それ以外はこのID。隠した候補は計算もしない(動作を軽くする)
TDTD_ID = "TDTD"
# 【2026-10-03・利用者の要望】種3の中あけRENを積んで消す練習。積む部分はテンプレ(中開け4列REN)、
# 積み終えて中央4列に3マスのタネだけが残った形になったら、無限中あけRENと同じ推奨手で消し続ける
REN_ID = "ren"
REN_LABEL = "中あけREN"
REN_WELL = range(3, 7)  # 中央4列(src/education/ren.py の WELL と同じ)
# 積み増し(図が続かなくなった後、左右3列ずつを評価で積む。src/education/ren_stack.py)
REN_STACK_ID = "ren-stack"
REN_STACK_LABEL = "中あけ積み"
# 左右の低い方がこの段数に達したら、積み増しから消すRENへ切り替える。【2026-10-03・利用者の指示】
# 20段目(可視の一番上)まで積み込むことを想定する。20段以内に積める手が無くなったときも切り替える
REN_STACK_TARGET = 20

__all__ = ["AI_ID", "PC_ID", "PC_ODDS_ID", "SIX_THREE_ID", "Advisor", "Candidate", "Recommendation", "find_path", "rejoin_form"]


@dataclass(frozen=True)
class Recommendation:
    piece: str
    use_hold: bool
    cells: tuple[Cell, ...]  # 22行の盤面座標
    source: str  # 表示用(「開幕テンプレ はちみつ砲 / 1巡目」「AI(Cold Clear 2)」等)
    steps: tuple[str, ...] | None  # 操作手順。出現位置から到達できなければNone
    soft_sections: int | None = None  # 難度の評価範囲で必要なソフトドロップの区間数
    scope: str = ""  # 難度の評価範囲(「この図の完成まで」「この1手」)
    # 【2026-09-24・利用者の指示】DPCによるパフェと探索したパフェを区別し、パフェの後に
    # 何へつながるか(開幕へ/DPCへ/袋ずれ。bag_status参照)を示す
    label: str = ""  # 候補欄の名前(空ならテンプレ名)
    after_pc: str | None = None  # パフェ後の袋の状態(パフェ以外はNone)
    tetris: bool = False  # テトリス(4列消し)を含むパフェ
    # 【2026-09-29・利用者の指示】ブラウザー版のように、テンプレの図・パフェの手順で置く予定の
    # ミノ(次の1手を含む)を盤面に薄く示す。(ミノ, 22行座標)を今の盤面の座標で並べる
    guide: tuple[tuple[str, tuple[Cell, ...]], ...] = ()


class _HypoSequence:
    """先読み用のミノ列: 見えている範囲(known_until番まで)は元の列、その次に配られるミノは仮の種類。

    未表示の配列を覗かないよう、見えている範囲より先を読もうとしたら LookupError にする。
    """

    def __init__(self, base, known_until: int, hypo: dict[int, str]) -> None:
        self.base = base
        self.known_until = known_until
        self.hypo = hypo

    def peek(self, index: int) -> str:
        if index in self.hypo:
            return self.hypo[index]
        if index > self.known_until:
            raise LookupError("先読みで未表示のミノを読もうとした")
        return self.base.peek(index)

    def __getattr__(self, name):
        if name == "base":
            raise AttributeError(name)  # 複製の途中(baseがまだ無い)で無限に呼び合わない
        return getattr(self.base, name)


@dataclass(frozen=True)
class _OddsRecommendation(Recommendation):
    """継続パフェの推奨手(成功率を持つ)。"""

    odds_rate: float = 0.0


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
    tdtd: bool = False  # TDTD(袋がずれたままTD系テンプレを組み直している)
    # 手順の各手(添字)のソフトドロップの区間数。図に従っている間は変わらないので覚えて使い回す
    # (【2026-10-02・利用者の指摘(動作が重い)】毎手番、全テンプレの残りの手を全部探し直していた)
    soft_steps: dict = field(default_factory=dict)

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
    """候補に並べるテンプレ(並び順が候補欄の順)。開幕パフェ積み・DPCは教育モード専用。

    【2026-09-30・利用者の要望】TDTD向けに集めたTD系テンプレも並べる。オリーブ積み(EXCLUDED_TEMPLATES)は
    通常は出さず、TDTD(袋がずれたまま組み直す)として始めたときだけ使う(_sync_track)。
    """
    return (
        tuple(openers.OPENER_TEMPLATES)
        + tuple(openers.TD_EXTRA_TEMPLATES)
        + tuple(openers.EDUCATION_TEMPLATES)
        + tuple(openers.REN_TEMPLATES)
    )


def manual_templates() -> frozenset[str]:
    """候補欄で選んだときだけ使うテンプレ(自動では選ばない)。中開け4列RENはTD系の開幕と相いれないため。"""
    return frozenset(t.name_ja for t in openers.REN_TEMPLATES)


def ren_ready(board) -> bool:
    """中あけRENを消していける形か: 中央4列にタネの3マスだけがあり、その行の左右6列が埋まっている。"""
    well = [(r, c) for r, c in board if c in REN_WELL]
    if len(well) != 3:
        return False
    side = [c for c in range(COLS) if c not in REN_WELL]
    return all((r, c) in board for r in {r for r, _c in well} for c in side)


def placed_count(sequence_index: int, hold: str | None) -> int:
    """これまでに置いたミノの数(配られた数 - 操作ミノ - HOLDのミノ)。おじゃま・一手戻すの影響を受けない。"""
    return sequence_index - 1 - (1 if hold is not None else 0)


def _prefer_older_same_piece(state: GameState, rec: Recommendation | None) -> Recommendation | None:
    """操作ミノとHOLDのミノが同じ種類で、HOLDのほうが古い袋のミノなら、HOLDして古いほうを置く案内にする。

    【2026-09-27・利用者の指示(ブラウザー版で見つかった不具合の予防)】HOLDを使わない手を優先すると、
    新しい袋のミノを置いて前の袋のミノをHOLDに残す。置く形は同じでも袋の区切りがずれ、それがパフェの
    最後の1手だと、パフェ後に開幕テンプレを始められない(bag_status が「袋ずれ」になる)。
    """
    if (
        rec is None
        or rec.use_hold
        or state.hold_used
        or state.hold != rec.piece
        or state.current != rec.piece
        or state.hold_index is None
        or state.current_index is None
        or state.hold_index >= state.current_index
    ):
        return rec
    return replace(rec, use_hold=True, steps=None if rec.steps is None else ("ホールド", *rec.steps))


def bag_status(placed: int, hold: str | None, current_index: int | None = None, hold_index: int | None = None) -> str:
    """袋の区切りから、次に組めるテンプレの種類。

    【2026-09-24・利用者と確認】ゲームではHOLDは一度使うと空に戻らないので、HOLDの有無ではなく
    置いた数で判断する。文献(DPCのページ)どおり、DPCを終えるとちょうどミノが5巡し、再び開幕
    テンプレを組める。8ラインパフェ(20個)の後は、3巡目の1個をHOLDに繰り越してDPCを組む。
    - "開幕": 置いた数が7の倍数(HOLDのミノも今の袋のもの)
    - "DPC": 置いた数が7の倍数-1で、HOLDに前の袋のミノを繰り越している
    - "袋ずれ": それ以外

    【2026-09-25・実画面 practice_20260925_222055】置いた数だけでは、前の袋のミノをHOLDしたまま
    新しい袋のミノを先に置いた状態(置いた数は7の倍数でも袋はずれている)を「開幕」と誤判定し、
    パフェ後に開幕テンプレが出なかった。操作ミノ・HOLDのミノの配列上の番号が分かるときは、
    まだ置いていないミノの番号で判断する:
    - "開幕": まだ置いていない一番古いミノが袋の先頭(前の袋は置き終え、HOLDも新しい袋のミノ)
    - "DPC": 操作ミノが袋の先頭で、HOLDのミノが1つ前の袋のもの(繰り越し)
    番号が分からない(途中局面から始めた練習)ときは置いた数で判断する。
    """
    if current_index is not None and (hold is None or hold_index is not None):
        oldest = current_index if hold is None else min(current_index, hold_index)
        if oldest % 7 == 0:
            return "開幕"
        if hold is not None and current_index % 7 == 0 and hold_index // 7 == current_index // 7 - 1:
            return "DPC"
        return "袋ずれ"
    if placed % 7 == 0:
        return "開幕"
    if placed % 7 == 6 and hold is not None:
        return "DPC"
    return "袋ずれ"


def startable_template(
    template: OpenerTemplate, hold: str | None, status: str, continuing: bool = False, allow_tdtd: bool = True
) -> OpenerTemplate:
    """今の手番から使える図だけのテンプレ。

    【2026-09-24・実画面 practice_20260924_190040】パフェ後(操作ミノは袋の先頭、HOLD=Z)
    に、山岳積み2号の1巡目の図をHOLDのZ(前の袋のミノ)を使って組む手順を推奨した。
    7種1巡からずれた組み方なので、空の盤面から組む1巡目の図(既存ブロックの無い図)は、
    袋の区切りがそろっているとき(bag_status=="開幕")だけ使う。DPCの組み方の図は、
    前の袋のミノをHOLDに繰り越しているとき(bag_status=="DPC")だけ使う。
    (当初は「HOLDが空」を条件にしていたが、HOLDは一度使うと空に戻らないため、DPCを
    終えた後に開幕テンプレが出なくなっていた。)

    【2026-09-24・実画面 practice_20260924_195905】Tスピンだけの図(はちみつ砲のTST等)は
    一致判定がゆるく、同じTSTの形を持つ迷走砲の盤面にも一致して「はちみつ砲」と表示した。
    Tスピンだけの図は、そのテンプレを続けてきた場合(continuing)だけ使う。
    """
    carry = template.name_ja in CARRY_TEMPLATES
    # 【2026-09-30・利用者の要望】TDTD: DPCを組める状態(前の袋のミノを繰り越し)でも、TD系テンプレは
    # 袋がずれたまま1巡目の図から組み直せる(候補として並べ、自動選択はDPCを優先する)
    tdtd = allow_tdtd and template.name_ja in TD_TEMPLATE_NAMES and status == "DPC"
    allow_empty = status == ("DPC" if carry else "開幕") or tdtd
    forms = template.forms
    if not allow_empty:
        forms = tuple(f for f in forms if f.existing)
    elif carry:
        # 【2026-09-24・実画面 practice_20260924_210537〜210624】HOLD=Z(Z繰り越し)なのに
        # O繰り越し用のO-05aを選び、TSDの後に続くパフェの図が合わず途中で切れた。
        # DPCの組み方の図は、図の大文字(繰り越したミノ)がHOLDのミノと一致するものだけ使う。
        forms = tuple(f for f in forms if f.existing or hold in carried_pieces(f))
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
    # 手番(固定した数) → 進めているパフェの残り手順。手順どおりに置いている間は探し直さない
    # (【2026-09-24】2段パフェの途中で見えるミノが増え、7手のテトリスパフェへ切り替わった)
    _pc_plans: dict = field(default_factory=dict)
    # 表示しない候補(テンプレ名・DPC・TDTD_ID・SIX_THREE_ID・PC_ODDS_ID)。計算もしない
    hidden: frozenset = frozenset()
    # 6-3積みの推奨手(選んでいるときだけ計算する。画面では別スレッド)
    _s63_rec: Recommendation | None = None
    _s63_future: object = None
    s63_pending: bool = False
    # 継続パフェ(成功率つき)。odds_searchは計算の関数(テストでは差し替える)
    odds_search: object = best_odds_move
    _odds_rec: Recommendation | None = None
    _ren_rec: Recommendation | None = None  # 中あけRENを消していく推奨手
    _ren_stack_rec: Recommendation | None = None  # 中あけRENの積み増しの推奨手
    _ren_tall: bool = False  # 左右が積み増しの目標の高さに達している
    _odds_future: object = None
    _odds_cancel: object = None
    odds_pending: bool = False
    # 手番(固定した数) → 継続パフェの残り手順(見えているミノで決まる分)。従っている間は計算し直さない
    _odds_plans: dict = field(default_factory=dict)
    _odds_meta: object = None  # 手順を計算したときの成功率など(OddsMove)
    # 【2026-09-29・利用者の指示】先読み計算: 次の手番で計算が要るとき(パフェ・継続パフェの手順の最後の
    # 1手)、案内どおりに置いた後の局面を、次にNEXTへ出うるミノ(袋の残りの種類)ごとに裏で計算しておく
    prefetch_enabled: bool | None = None  # Noneなら画面(pc_async)のときだけ
    _odds_cache: dict = field(default_factory=dict)  # 計算の入力 → 結果(OddsMove)
    _prefetch: dict = field(default_factory=dict)  # 計算の入力 → (future, 打ち切りの合図)
    _prefetch_executor: object = None
    _prefetch_turn: object = None  # 先読みを始めた手番(同じ手番で二重に始めない)
    _odds_key: object = None  # 計算中・表示中の継続パフェの入力

    def close(self) -> None:
        self._cancel_pc()
        self._cancel_odds()
        self._cancel_prefetch()
        if self._prefetch_executor is not None:
            self._prefetch_executor.shutdown(wait=False)
            self._prefetch_executor = None
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
        return _prefer_older_same_piece(state, self._update(state, now))

    def _update(self, state: GameState, now: float | None = None) -> Recommendation | None:
        now = time.monotonic() if now is None else now
        if state.game_over:
            return None
        if state.practice_id != self._practice_id:  # リセット・盤面編集(別の練習)
            self._practice_id = state.practice_id
            self._tracks = {}
            self._pc_plans = {}
            self._odds_plans = {}
            self._odds_meta = None
            self._odds_cache = {}
            self._cancel_prefetch()
            self._auto_id = None
        key = (len(state.history), state.hold_used, state.current, state.sequence_index, id(state.turn_start))
        if key != self._turn_key:
            self._turn_key = key
            self._ai_rec = None
            self._requested_at = None
            self._template_recs = self._compute_template_recs(state) if self.opener_enabled else {}
            self._pc_rec = None
            self._s63_rec = None
            self._s63_future = None
            self.s63_pending = False
            self._odds_rec = None
            self._ren_rec = self._ren_recommendation(state) if self.opener_enabled else None
            self._ren_stack_rec = self._ren_stack_recommendation(state) if self.opener_enabled else None
            if self.opener_enabled and self._ren_rec is None and self._ren_stack_rec is None and self._wants_ren():
                # 積み増せる手が無い(20段以内に置けない等): 消していくRENの推奨手を計算する
                self._ren_rec = self._ren_recommendation(state, force=True)
            if self.opener_enabled:
                self._start_pc(state)
                self._start_odds(state)
            self._select()
        if self._pc_future is not None and self._pc_future.done():
            self._finish_pc(state)
        if self._odds_future is not None and self._odds_future.done():
            self._finish_odds(state)
        self._collect_prefetch()
        self._maybe_prefetch(state)
        if self.active_id == PC_ID:
            return self._pc_rec
        if self.active_id == PC_ODDS_ID:
            return self._odds_rec
        if self.active_id == REN_ID:
            return self._ren_rec
        if self.active_id == REN_STACK_ID:
            return self._ren_stack_rec
        if self.active_id == SIX_THREE_ID:
            return self._six_three(state)
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
                result.append(Candidate(template.name_ja, _candidate_label(rec, template.name_ja), difficulty_mark(rec.soft_sections), rec.scope))
        if self._pc_rec is not None:
            # 【2026-09-24・利用者の指示】パフェは候補欄に分岐として出す
            result.append(Candidate(PC_ID, _candidate_label(self._pc_rec, "パフェ"), difficulty_mark(self._pc_rec.soft_sections), self._pc_rec.scope))
        if self._ren_stack_rec is not None:
            rec = self._ren_stack_rec
            result.append(Candidate(REN_STACK_ID, rec.label, difficulty_mark(rec.soft_sections), rec.scope))
        if self._ren_rec is not None:
            result.append(Candidate(REN_ID, self._ren_rec.label, difficulty_mark(self._ren_rec.soft_sections), self._ren_rec.scope))
        if self._odds_rec is not None:
            result.append(Candidate(PC_ODDS_ID, self._odds_rec.label, difficulty_mark(self._odds_rec.soft_sections), self._odds_rec.scope))
        elif self.odds_pending:
            result.append(Candidate(PC_ODDS_ID, PC_ODDS_LABEL, "探索中", ""))
        if self._engine_failed:
            mark, scope = "使用不可", ""
        elif self._ai_rec is not None:
            mark, scope = difficulty_mark(self._ai_rec.soft_sections), self._ai_rec.scope
        elif self.active_id == AI_ID and self._requested_at is not None:
            mark, scope = "探索中", ""
        else:
            mark, scope = "", ""
        s63 = self._s63_rec
        s63_mark = "探索中" if self.s63_pending else (difficulty_mark(s63.soft_sections) if s63 else "")
        if self.opener_enabled and SIX_THREE_ID not in self.hidden:
            result.append(Candidate(SIX_THREE_ID, SIX_THREE_LABEL, s63_mark, "この1手" if s63 else ""))
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
        manual = manual_templates()
        if self.preferred_id in manual and self.preferred_id not in available:
            # 中開け4列RENの図が続かなくなった: 左右が目標の高さになるまで積み増し、なったら消していくRENへ
            # いったんRENを始めたら、続く限りRENのまま(消すと左右が低くなるが、積み増しに戻るとRENが途切れる)
            tall = self._ren_stack_rec is None or self._ren_tall or self.active_id == REN_ID
            if self._ren_rec is not None and tall:
                self.active_id = REN_ID
                return
            if self._ren_stack_rec is not None:
                self.active_id = REN_STACK_ID
                return
        if self.preferred_id == REN_ID and self._ren_rec is not None:
            self.active_id = REN_ID
            return
        if self.preferred_id == REN_STACK_ID and self._ren_stack_rec is not None:
            self.active_id = REN_STACK_ID
            return
        if self.preferred_id is None and self._pc_rec is not None and self._pc_rec.tetris:
            # 【2026-09-24・利用者の指示】テトリスを含むパフェが取れるなら、ソフトドロップが
            # 要ってもテンプレより優先する(利用者が候補を選んでいる間は選択を尊重する)
            self.active_id = PC_ID
            return
        # 【2026-09-24・利用者の指示】テンプレを続けている間はテンプレを優先し、
        # それ以外(AIで提示する局面)で5手以内のパフェが見えればパフェを提示する。
        # 見えているミノで取れるパフェが無ければ、成功率の高い継続パフェ(パフェ直後とその続き)
        if self._pc_rec is not None:
            fallback = PC_ID
        elif self._odds_rec is not None and self._odds_rate >= ODDS_AUTO_MIN:
            fallback = PC_ODDS_ID
        else:
            fallback = AI_ID
        if self.preferred_id is not None:
            # 希望のテンプレが一時的に組めない間はパフェかAIで提示し、組めるようになったら戻る。
            # 明示的にAIを選んだ場合は、テンプレが組めても勝手に切り替えない。
            if self.preferred_id in (AI_ID, SIX_THREE_ID) or self.preferred_id in available:
                self.active_id = self.preferred_id
            elif self.preferred_id == PC_ODDS_ID and (self._odds_rec is not None or self.odds_pending):
                self.active_id = PC_ODDS_ID
            else:
                self.active_id = fallback
            return
        if self.prefer_ai:
            self.active_id = fallback
            return
        # 中開け4列RENは候補欄で選んだときだけ(自動では選ばない)
        available = [name for name in available if name not in manual]
        if self._auto_id not in available and available:
            # 【2026-09-23・利用者の指示】ソフトドロップの少ないテンプレを選ぶ(同じなら並び順)
            def cost(name: str) -> tuple:
                rec = self._template_recs[name]
                sections = rec.soft_sections
                # 【2026-09-30・利用者の指示】パフェ後はDPCをTDTDより優先する
                return ("TDTD" in rec.label, sections is None, sections or 0, available.index(name))

            self._auto_id = min(available, key=cost)
        self.active_id = self._auto_id if self._auto_id in available else fallback

    # ---- 開幕テンプレ ----
    def set_hidden(self, hidden) -> None:
        """表示しない候補を変える。次の更新で候補を計算し直す。"""
        self.hidden = frozenset(hidden)
        self._turn_key = None
        self._tracks = {}  # 隠したテンプレ・TDTDで始めた手順を使い続けない
        self._auto_id = None
        if self.preferred_id in self.hidden:
            self.preferred_id = None

    def _compute_template_recs(self, state: GameState) -> dict[str, Recommendation]:
        recs: dict[str, Recommendation] = {}
        # 中あけRENの練習中は、ほかのテンプレを計算しない(左右が高い盤面では図の照合が重く、使わない)。
        # 積み増し・消す段階に入った後は、中開け4列RENの図(1巡目)にも戻らないので計算しない
        if self._wants_ren() and self.active_id in (REN_ID, REN_STACK_ID):
            return recs
        only = manual_templates() if self._wants_ren() else None
        for template in candidate_templates():
            if template.name_ja in self.hidden or (only is not None and template.name_ja not in only):
                continue
            rec = self._from_track(state, self._sync_track(state, template))
            # 実際に置ける操作手順が無い手は候補にしない
            if rec is not None and rec.steps is not None:
                recs[template.name_ja] = rec
        return recs

    def _six_three(self, state: GameState) -> Recommendation | None:
        """6-3積みの推奨手。画面(pc_async)では別スレッドで計算し、終わるまではNone。"""
        if self._s63_rec is not None:
            return self._s63_rec
        if self._s63_future is None:
            args = (
                frozenset((r, c) for r in range(ROWS) for c in range(COLS) if state.board[r][c] is not None),
                state.current,
                state.hold,
                list(state.visible_next()),  # NEXT5まで
                not state.hold_used,
            )
            if not self.pc_async:
                self._s63_rec = self._s63_recommendation(state, best_move(*args))
                return self._s63_rec
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="education_search")
            self._s63_future = self._executor.submit(best_move, *args)
            self.s63_pending = True
            return None
        if self._s63_future.done():
            future, self._s63_future = self._s63_future, None
            self.s63_pending = False
            try:
                self._s63_rec = self._s63_recommendation(state, future.result())
            except Exception:  # noqa: BLE001 - 計算の失敗で画面を止めない
                self._s63_rec = None
        return self._s63_rec

    @staticmethod
    def _s63_recommendation(state: GameState, move) -> Recommendation | None:
        if move is None:
            return None
        use_hold = move.use_hold and not state.hold_used
        path = find_path_min_soft(state, move.piece, move.cells)
        return Recommendation(
            piece=move.piece,
            use_hold=use_hold,
            cells=move.cells,
            source=f"6-3積み(井戸: 左から{WELL_COL + 1}列目)",
            steps=None if path is None else (("ホールド",) if use_hold else ()) + path[0],
            soft_sections=None if path is None else path[1],
            scope="この1手",
        )

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

    def _continuing_pc(self, state: GameState, plans: dict | None = None):
        """進めているパフェの残り手順(手順どおりに置いていれば)。この手番の最初の手から。

        plans: 手番 → 手順。省略時は見えているミノで探したパフェ(継続パフェの手順にも使う)。
        """
        plans = self._pc_plans if plans is None else plans
        turn = len(state.history)
        for stale in [t for t in plans if t > turn]:
            del plans[stale]
        prev = plans.get(turn - 1)
        if turn not in plans and prev and len(prev) > 1 and state.last_lock is not None:
            if set(state.last_lock[1]) == set(prev[0].cells):
                plans[turn] = prev[1:]
        plan = plans.get(turn)
        if not plan:
            return None
        first = plan[0]
        if state.hold_used:
            if not first.use_hold and first.piece != state.current:
                return None  # 手順と違うHOLDをした
            plan = [replace(first, use_hold=False), *plan[1:]]  # HOLDは済んでいる
        elif first.piece != (state.hold if first.use_hold else state.current):
            return None
        return plan

    def _start_pc(self, state: GameState) -> None:
        self._cancel_pc()
        self.pc_timed_out = False
        plan = self._continuing_pc(state)
        if plan is not None:
            self._pc_rec = self._pc_recommendation(state, plan)
            return
        inputs = self._pc_inputs(state)
        if inputs is None:
            return
        board, sequence, hold, can_hold = inputs
        if not self.pc_async:
            found = find_perfect_clear(board, sequence, hold, can_hold=can_hold)
            self._remember_pc(state, found)
            self._pc_rec = self._pc_recommendation(state, found)
            return
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="education_search")
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
        self._remember_pc(state, found)
        self._pc_rec = self._pc_recommendation(state, found)
        if self._pc_rec is not None:
            self._select()

    def _remember_pc(self, state: GameState, found) -> None:
        if isinstance(found, list) and found:
            self._pc_plans[len(state.history)] = found

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
        board = frozenset((r, c) for r in range(ROWS) for c in range(COLS) if state.board[r][c] is not None)
        tetris = has_tetris(board, found)
        label = "テトリスパフェ(探索)" if tetris else "パフェ(探索)"
        return Recommendation(
            piece=first.piece,
            use_hold=first.use_hold,
            cells=first.cells,
            source=f"{label} あと{len(found)}手",
            steps=(("ホールド",) if first.use_hold else ()) + path[0],
            soft_sections=_pc_soft_sections(state, found),
            scope="パフェまで",
            label=label,
            after_pc=_after_pc(state, [s.use_hold for s in found]),
            tetris=tetris,
            guide=_pc_guide(board, found),
        )

    # ---- 中あけREN(積み増し) ----
    def _wants_ren(self) -> bool:
        """中あけRENの練習中か(候補欄で中開け4列REN・中あけ積み・中あけRENのどれかを選んでいる)。"""
        return self.preferred_id in manual_templates() | {REN_ID, REN_STACK_ID}

    def _ren_stack_recommendation(self, state: GameState) -> Recommendation | None:
        """中央4列を空けたまま左右3列ずつを積む手(図が続かなくなった後)。中あけRENの練習中だけ計算する。"""
        self._ren_tall = False
        if REN_STACK_ID in self.hidden or not self._wants_ren():
            return None
        board = frozenset((r, c) for r in range(ROWS) for c in range(COLS) if state.board[r][c] is not None)
        if sum(1 for _r, c in board if c in REN_WELL) > 3:
            return None  # 中央4列が埋まっている(中あけの形ではない)
        self._ren_tall = min(ren_stack.side_heights(board)) >= REN_STACK_TARGET
        # 要らないときは計算しない(2手先まで読むので重い): 図に従っている間と、RENが続いている間。
        # 候補欄で中あけ積みを選んでいるときは常に計算する
        if self.preferred_id != REN_STACK_ID:
            if any(name in self._template_recs for name in manual_templates()):
                return None
            if self._ren_rec is not None and (self._ren_tall or self.active_id == REN_ID):
                return None
        move = ren_stack.best_move(board, state.current, state.hold, list(state.visible_next()), not state.hold_used)
        if move is None:
            return None
        use_hold = move.use_hold and not state.hold_used
        path = find_path_min_soft(state, move.piece, move.cells)
        if path is None:
            return None
        left, right = ren_stack.side_heights(board)
        return Recommendation(
            piece=move.piece,
            use_hold=use_hold,
            cells=move.cells,
            source=f"中あけ積み 左右3列ずつを{REN_STACK_TARGET}段目まで積む(今 左{left}段・右{right}段)",
            steps=(("ホールド",) if use_hold else ()) + path[0],
            soft_sections=path[1],
            scope="この1手",
            label=REN_STACK_LABEL,
        )

    # ---- 中あけREN(積み終えた後に消していく) ----
    def _ren_recommendation(self, state: GameState, force: bool = False) -> Recommendation | None:
        """中央4列にタネの3マスが残る形なら、RENが最も長く続く手順の1手目(無限中あけRENと同じ探索)。"""
        if REN_ID in self.hidden:
            return None
        board = frozenset((r, c) for r in range(ROWS) for c in range(COLS) if state.board[r][c] is not None)
        if not ren_ready(board):
            return None
        # 積み増しの途中(左右が目標の高さに達しておらず、RENを始めていない)は計算しない(重い)。
        # 積み増せる手が無くなったときは呼び出し側が force で計算し直す
        if (
            not force
            and self._wants_ren()
            and self.preferred_id != REN_ID
            and self.active_id != REN_ID
            and min(ren_stack.side_heights(board)) < REN_STACK_TARGET
        ):
            return None
        inputs = self._pc_inputs(state)
        if inputs is None:
            return None
        _board, sequence, hold, can_hold = inputs
        plan = find_ren_plan(board, sequence, hold, can_hold, REN_WELL)
        if plan is None:
            return None
        first = plan.steps[0]
        use_hold = first.use_hold and not state.hold_used
        path = find_path_min_soft(state, first.piece, first.cells)
        if path is None:
            return None
        known = f"見えている{plan.visible}個すべてで" if plan.complete else f"見えている{plan.visible}個のうち{len(plan.steps)}手先まで"
        return Recommendation(
            piece=first.piece,
            use_hold=use_hold,
            cells=first.cells,
            source=f"中あけREN {known}RENが続く",
            steps=(("ホールド",) if use_hold else ()) + path[0],
            soft_sections=path[1],
            scope="この1手",
            label=f"{REN_LABEL} {len(plan.steps)}手",
            guide=_pc_guide(board, [PCStep(st.piece, st.cells, st.use_hold) for st in plan.steps]),
        )

    # ---- 継続パフェ(成功率つき) ----
    @property
    def _odds_rate(self) -> float:
        return getattr(self._odds_rec, "odds_rate", 0.0) or 0.0

    def _wants_odds(self, state: GameState, board) -> bool:
        """継続パフェの成功率を計算する局面か(1回に数秒かかるので限る)。"""
        if PC_ODDS_ID in self.hidden:
            return False
        if board and min(r for r, _c in board) < ROWS - 6:
            return False  # 6段より高い盤面はパフェを狙わない
        if self.preferred_id == PC_ODDS_ID:
            return True  # 候補欄で選んでいる
        turn = len(state.history)
        if not board:
            # パフェの直後(練習開始の空の盤面=HOLDも空は、開幕テンプレに任せる)
            return turn > 0 or state.hold is not None
        prev = self._odds_plans.get(turn - 1)
        return bool(prev) and state.last_lock is not None and set(state.last_lock[1]) == set(prev[0].cells)

    def _odds_inputs(self, state: GameState):
        """成功率の計算に渡す(盤面, ミノ順, HOLD, 袋の残り, HOLDできるか)。見えている範囲だけ。"""
        inputs = self._pc_inputs(state)
        if inputs is None:
            return None
        board, sequence, hold, can_hold = inputs
        turn_sequence, _hold, _board = self._turn_sequence(state)
        snap = state.turn_start
        # 見えている最後のミノの通し番号。袋の区切りは配った数から分かる(未表示の配列は見ない)
        last = snap.sequence_index - 1 + len(turn_sequence) - 1
        if (last + 1) % 7 == 0:
            pool = frozenset()  # 袋の最後まで見えている(7個目を補ったときも。補ったミノの番号は読まない)
        else:
            start = last // 7 * 7
            pool = frozenset(PIECES) - {state.sequence.peek(i) for i in range(start, last + 1)}
        return board, sequence, hold, pool, can_hold

    def _start_odds(self, state: GameState) -> None:
        self._cancel_odds()
        board = frozenset((r, c) for r in range(ROWS) for c in range(COLS) if state.board[r][c] is not None)
        # 【2026-09-29・利用者の指摘(待ち時間)】案内した手順どおりに置いている間は計算し直さない
        plan = self._continuing_pc(state, self._odds_plans)
        if plan is not None and self._odds_meta is not None:
            self._odds_rec = self._odds_recommendation(state, self._odds_meta, plan)
            return
        if not self._wants_odds(state, board):
            return
        inputs = self._odds_inputs(state)
        if inputs is None:
            return
        board, sequence, hold, pool, can_hold = inputs
        key = _odds_key(inputs)
        self._odds_key = key
        self._collect_prefetch()
        if key in self._odds_cache:
            # 先読みで計算済み: 待たずに示す
            self._cancel_prefetch()
            self._odds_rec = self._odds_recommendation(state, self._odds_cache[key])
            return
        running = self._prefetch.pop(key, None)
        self._cancel_prefetch()  # 実際に来なかったミノの先読みは捨てる
        if running is not None:
            # 先読みが計算中: その結果を待つ(最初から計算し直さない)
            self._odds_future, self._odds_cancel = running
            self.odds_pending = True
            return
        if not self.pc_async:
            move = self.odds_search(board, sequence, hold, pool, can_hold=can_hold, time_limit=ODDS_TIME_LIMIT)
            self._odds_cache[key] = move
            self._odds_rec = self._odds_recommendation(state, move)
            return
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="education_search")
        self._odds_cancel = threading.Event()
        self._odds_future = self._executor.submit(
            self.odds_search, board, sequence, hold, pool, can_hold=can_hold, time_limit=ODDS_TIME_LIMIT, cancel=self._odds_cancel
        )
        self.odds_pending = True

    def _cancel_odds(self) -> None:
        """局面が変わった: 古い計算を止め、結果を使わない。"""
        if self._odds_cancel is not None:
            self._odds_cancel.set()
        self._odds_future = None
        self._odds_cancel = None
        self.odds_pending = False

    def _finish_odds(self, state: GameState) -> None:
        future, self._odds_future = self._odds_future, None
        self._odds_cancel = None
        self.odds_pending = False
        try:
            move = future.result()
        except Exception:  # noqa: BLE001 - 計算の失敗で画面を止めない
            return
        if move is not None and self._odds_key is not None:
            self._odds_cache[self._odds_key] = move
        self._odds_rec = self._odds_recommendation(state, move)
        self._select()

    # ---- 先読み計算 ----
    def _prefetch_inputs(self, state: GameState) -> list[tuple]:
        """次の手番で継続パフェの計算が要るなら、案内どおりに置いた後の局面の計算の入力を、
        次にNEXTへ出うるミノごとに返す。要らない・作れないときは空。"""
        turn = len(state.history)
        if self.active_id == PC_ID:
            plan, rec = self._pc_plans.get(turn), self._pc_rec  # パフェの最後の1手 → 次はパフェ直後
        elif self.active_id == PC_ODDS_ID:
            plan, rec = self._odds_plans.get(turn), self._odds_rec  # 継続パフェの手順の最後の1手
        else:
            return []
        if not plan or len(plan) != 1 or rec is None or rec.steps is None:
            return []
        if rec.use_hold and state.hold is None and not state.hold_used:
            return []  # HOLDが空でHOLDすると2個配られる(先読みは1個まで)
        last = state.sequence_index + NEXT_VISIBLE - 1  # 見えている最後のミノの番号
        if (last + 1) % 7 == 0:
            pool = frozenset(PIECES)
        else:
            pool = frozenset(PIECES) - {state.sequence.peek(i) for i in range(last // 7 * 7, last + 1)}
        out = []
        for piece in sorted(pool):
            try:
                sim = copy.deepcopy(state, {id(state.sequence): state.sequence})  # ミノ列は変えないので共有
                sim.sequence = _HypoSequence(state.sequence, last, {last + 1: piece})
                if not _play(sim, rec):
                    return []
                board = frozenset((r, c) for r in range(ROWS) for c in range(COLS) if sim.board[r][c] is not None)
                if board and not self._wants_odds(sim, board):
                    return []
                inputs = self._odds_inputs(sim)
            except LookupError:
                return []
            if inputs is not None:
                out.append(inputs)
        return out

    def _maybe_prefetch(self, state: GameState) -> None:
        enabled = self.pc_async if self.prefetch_enabled is None else self.prefetch_enabled
        if not enabled or not self.opener_enabled or self._prefetch_turn == self._turn_key:
            return
        if self.active_id not in (PC_ID, PC_ODDS_ID):
            return
        rec = self._pc_rec if self.active_id == PC_ID else self._odds_rec
        if rec is None:
            return  # 推奨手がまだ(計算中)
        self._prefetch_turn = self._turn_key
        if self._prefetch_executor is None:
            # 1つずつ順に(同時に走らせると、それぞれが全スレッドを取り合って遅くなる)
            self._prefetch_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="education_prefetch")
        for inputs in self._prefetch_inputs(state):
            key = _odds_key(inputs)
            if key in self._odds_cache or key in self._prefetch:
                continue
            board, sequence, hold, pool, can_hold = inputs
            cancel = threading.Event()
            future = self._prefetch_executor.submit(
                self.odds_search, board, sequence, hold, pool, can_hold=can_hold, time_limit=ODDS_TIME_LIMIT, cancel=cancel
            )
            self._prefetch[key] = (future, cancel)

    def _collect_prefetch(self) -> None:
        """終わった先読みの結果を覚える。"""
        for key, (future, _cancel) in list(self._prefetch.items()):
            if future.done():
                del self._prefetch[key]
                try:
                    move = future.result()
                except Exception:  # noqa: BLE001 - 計算の失敗で画面を止めない
                    continue
                if move is not None:
                    if len(self._odds_cache) > 200:
                        self._odds_cache.clear()
                    self._odds_cache[key] = move

    def _cancel_prefetch(self) -> None:
        for future, cancel in self._prefetch.values():
            cancel.set()
            future.cancel()
        self._prefetch = {}

    def _odds_recommendation(self, state: GameState, move, plan=None) -> Recommendation | None:
        """継続パフェの推奨手。plan: 続けている手順の残り(省略時はmoveの手順を今から始める)。"""
        if move is None or move.success == 0:
            return None
        turn = len(state.history)
        if plan is None:
            steps = list(move.plan) or [PCStep(move.piece, move.cells, move.use_hold)]
            if state.hold_used:
                steps[0] = replace(steps[0], use_hold=False)  # HOLDは済んでいる
            self._odds_plans[turn] = steps
            self._odds_meta = move
            plan = steps
        first = plan[0]
        use_hold = first.use_hold and not state.hold_used
        path = find_path_min_soft(state, first.piece, first.cells)
        if path is None:
            return None
        board = frozenset((r, c) for r in range(ROWS) for c in range(COLS) if state.board[r][c] is not None)
        percent = int(move.rate * 100)  # 切り捨て(100%は全部の並びで組めたときだけ)
        placed = move.pieces - (len(move.plan or (None,)) - len(plan))  # パフェまでの残り手数
        return _OddsRecommendation(
            piece=first.piece,
            use_hold=use_hold,
            cells=first.cells,
            source=(
                f"継続パフェ 成功率{percent}%({move.success}/{move.total}通り)・{move.height}段パフェまであと{placed}手"
                f"・ガイドは読めている{len(plan)}手"
            ),
            steps=(("ホールド",) if use_hold else ()) + path[0],
            soft_sections=_pc_soft_sections(state, plan),
            scope=f"ガイドの{len(plan)}手",
            label=f"{PC_ODDS_LABEL} {percent}%",
            odds_rate=move.rate,
            guide=_pc_guide(board, plan),
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
        if template.name_ja in EXCLUDED_TEMPLATES and (track is None or not track.tdtd):
            track = None  # オリーブ積みはTDTDのときだけ
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
        self, state: GameState, template: OpenerTemplate, rejoin: bool = False, continuing: bool = False, tdtd: bool = False
    ) -> _OpenerTrack | None:
        sequence, hold, board = self._turn_sequence(state)
        if sequence is None:
            return None
        snap = state.turn_start
        status = bag_status(placed_count(snap.sequence_index, hold), hold, snap.current_index, snap.hold_index)
        # TDTDの2巡目以降は、余りのミノを図の外へ置く手を許す(【2026-10-01・利用者の指示】TSDまでは打ち切る)
        discards = TDTD_DISCARDS if tdtd and continuing else 0
        allow_tdtd = TDTD_ID not in self.hidden
        got = choose_form(
            startable_template(template, hold, status, continuing, allow_tdtd), board, sequence, hold, discards=discards
        )
        if got is None:
            # 盤面エディタで図の途中形を作って始めた場合も、ここで合流する
            got = rejoin_form(template, board, sequence, hold)
        else:
            rejoin = False
        if got is None:
            return None
        form, steps = got
        # 袋がずれた状態(繰り越しあり)から1巡目の図を始めたらTDTD。続きの図(2巡目以降)も引き継ぐ
        tdtd = tdtd or (template.name_ja in TD_TEMPLATE_NAMES and not form.existing and status == "DPC")
        return _OpenerTrack(template, form, list(steps), rejoined=rejoin, tdtd=tdtd)

    def _advance_track(self, state: GameState, prev: _OpenerTrack) -> _OpenerTrack | None:
        step = prev.current()
        piece, cells22 = state.last_lock  # type: ignore[misc]
        placed20 = {(r - HIDDEN_ROWS, c) for r, c in cells22}
        if step is None or step.piece != piece or set(step.cells) != placed20:
            return None  # 手順と違う置き方: 合流点を探し、無ければAIの推奨手に戻す
        before = _board20(state.history[-1].board)
        cleared = full_rows_after(before, step.cells)
        rest = [replace(st, cells=shift_cells_for_clears(st.cells, cleared)) if cleared else st for st in prev.steps[prev.index + 1 :]]
        track = _OpenerTrack(
            prev.template, prev.form, prev.steps[: prev.index + 1] + rest, prev.index + 1, prev.rejoined, prev.tdtd, prev.soft_steps
        )
        if track.current() is None:
            # 図を置き終えた: 同じテンプレの続きの図(2巡目以降)を探す
            return self._start_track(state, prev.template, continuing=True, tdtd=prev.tdtd)
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
            source=f"{kind} {track.template.name_ja}{'(TDTD: 袋がずれたまま)' if track.tdtd else ''} / {section}"
            + (" (定跡に復帰)" if track.rejoined else ""),
            steps=None if path is None else (("ホールド",) if use_hold else ()) + path[0],
            soft_sections=_form_soft_sections(state, track),
            scope="この図の完成まで",
            guide=tuple((st.piece, _to22(st.cells)) for st in track.steps[track.index :]),
            **({"label": f"{track.template.name_ja}(TDTD)"} if track.tdtd else _dpc_pc_info(state, track)),
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
    ソフトドロップの区間が最少の経路で数えて合計する。各手の区間数は track.soft_steps に覚え、
    次の手番からは探し直さない(図に従っている間は変わらない)。
    """
    cache = track.soft_steps
    indices = range(track.index, len(track.steps))
    if all(i in cache for i in indices):
        return None if any(cache[i] is None for i in indices) else sum(cache[i] for i in indices)
    sim = GameState(sequence=state.sequence)
    sim.board = [list(row) for row in state.board]
    steps = list(track.steps[track.index :])
    total = 0
    index = track.index
    while steps:
        step = steps.pop(0)
        cells = _to22(step.cells)
        if index not in cache:
            path = find_path_min_soft(sim, step.piece, cells, spin_entry=step.spin and step.piece == "T")
            cache[index] = None if path is None else path[1]
        if cache[index] is None:
            return None
        total += cache[index]
        index += 1
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


def _odds_key(inputs) -> tuple:
    board, sequence, hold, pool, can_hold = inputs
    return (frozenset(board), tuple(sequence), hold, frozenset(pool), can_hold)


_PLAY_OPS = {"←": "move_left", "→": "move_right", "左回転": "rotate_ccw", "右回転": "rotate_cw", "↓": "soft_drop"}


def _play(state: GameState, rec: Recommendation) -> bool:
    """推奨手の操作手順どおりに置く(先読み用)。置いた場所が推奨の位置になればTrue。"""
    if rec.use_hold and not state.use_hold():
        return False
    for step in rec.steps or ():
        if step in ("ホールド", "ハードドロップ"):
            continue
        name, _, times = step.partition("×")
        for _ in range(int(times or 1)):
            if not getattr(state, _PLAY_OPS[name])():
                return False
    state.hard_drop()
    return state.last_lock is not None and set(state.last_lock[1]) == set(rec.cells)


def _pc_guide(board, steps) -> tuple[tuple[str, tuple[Cell, ...]], ...]:
    """パフェの手順(各手は前の手までの消去後の座標)を、今の盤面の座標に直して並べる。

    途中で行が消えると、その後の手は下へずれた座標で表されるので、消えた行を挟んだ元の
    行へ戻す(今の盤面の上に1枚の図として重ねて示すため)。
    """
    placed = set(board)
    rows = list(range(ROWS))  # 消去後の行 → 今の盤面の行(Noneは今の盤面より上)
    guide = []
    for step in steps:
        guide.append((step.piece, tuple(sorted((rows[r], c) for r, c in step.cells if rows[r] is not None))))
        placed |= set(step.cells)
        full = [r for r in range(ROWS) if all((r, c) in placed for c in range(COLS))]
        if full:
            rows = [None] * len(full) + [rows[r] for r in range(ROWS) if r not in full]
            placed = {(r + sum(1 for f in full if f > r), c) for r, c in placed if r not in full}
    return tuple(guide)


def _after_pc(state: GameState, hold_flags: list[bool]) -> str:
    """手順(各手でHOLDするか)を置き終えた後の袋の状態("開幕"/"DPC"/"袋ずれ")。

    置いた数は手順の手数だけ増える。HOLDは一度使うと空に戻らない。
    操作ミノ・HOLDの番号も手順どおりに追いかける(次に配られるのはstate.sequence_index番)。
    """
    held = state.hold
    current_index, hold_index, deal = state.current_index, state.hold_index, state.sequence_index
    for i, use_hold in enumerate(hold_flags):
        if use_hold and (i == 0 and state.hold_used):
            use_hold = False  # この手番のHOLDは済んでいる
        if not use_hold:
            current_index, deal = deal, deal + 1  # 操作ミノを置き、次が配られる
        elif held is None:
            held = "?"  # 操作ミノをHOLDし、次のミノを置き、さらに次が配られる
            hold_index, current_index, deal = current_index, deal + 1, deal + 2
        else:
            hold_index, current_index, deal = current_index, deal, deal + 1  # HOLDと入れ替えて置く
    return bag_status(placed_count(state.sequence_index, state.hold) + len(hold_flags), held, current_index, hold_index)


def _dpc_pc_info(state: GameState, track: _OpenerTrack) -> dict:
    """DPCのパフェの図なら、候補欄の名前とパフェ後の袋の状態。"""
    if track.template.name_ja not in CARRY_TEMPLATES or "パフェ" not in track.form.section.split(" > ")[-1]:
        return {}
    return {"label": "DPCパフェ", "after_pc": _after_pc(state, [s.use_hold for s in track.steps[track.index :]])}


def _candidate_label(rec: Recommendation, default: str) -> str:
    label = rec.label or default
    if rec.after_pc is not None:
        # 【2026-09-25・利用者の指示】袋ずれはループが崩れることを示す(優先の順位は変えない)
        label += {"開幕": " →開幕へ", "DPC": " →DPCへ"}.get(rec.after_pc, " →袋ずれ(ループ崩れ)")
    return label
