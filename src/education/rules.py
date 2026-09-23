"""教育モードのゲームルールと状態管理(画面に依存しない)。

【確定仕様(教育モード仕様書 第2・4・5・10章)】
- 操作と回転はぷよぷよテトリスを基準にした通常SRS。専用180度回転は無い。
- 自動落下なし・時間制限なし。接地しても自動固定せず、ハードドロップでのみ
  配置を確定する。ソフトドロップ(1マスずつ下へ)で接地した後も移動・回転を試せる。
- NEXTの表示と読みの範囲は5手まで。同一配列の再現用に保持する未表示の
  将来配列は、推奨手の判断へ渡さない(visible_next()だけを外部へ出す)。
- 一手戻す: ミノ1個の固定を単位に、回数制限なく練習開始状態まで戻れる。
- 同一配列でリセット: 開始条件(盤面・HOLD・ミノ列)を未表示分まで含めて再現。
- 別配列でリセット: 新しいミノ列で開始。

【この段階で仮置きしている未決事項】
- 出現位置: 可視20行の上に非表示2行を持ち、ミノは非表示行を含む上端
  (3x3の箱の左上が行0・列3、Iは行0・列3の4x4)に出現する。
- 方向キー(移動・ソフトドロップ)は押しっぱなしで連続入力(キーはOSの連打設定、コントローラーは170ms後に50ms間隔)。
- Tスピン判定はガイドラインの3コーナー方式(最後の操作が回転、Tの箱の四隅の
  うち3つ以上が埋まっている。向いている側の2隅が埋まっていれば正式、そうで
  なければミニ。ただし5番目の補正(TSTの補正)ならミニにしない)。
  STSD・インペリアルクロス等の形の名前は形の判定が必要なので未対応(TSD等と表示)。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

ROWS = 22  # 内部の行数(非表示2行 + 可視20行)
HIDDEN_ROWS = 2
COLS = 10
NEXT_VISIBLE = 5

Cell = tuple[int, int]

# 各ミノの回転状態(0=出現, 1=右回転, 2=180度, 3=左回転)の形。
# 座標は箱(JLSTZは3x3、Iは4x4、Oは2x2相当)内の(行, 列)。行は下向きが正。
# 通常SRSの基本回転(箱の中で回す)と同じ位置関係になるように定義している。
_SHAPES: dict[str, list[tuple[Cell, ...]]] = {
    "I": [
        ((1, 0), (1, 1), (1, 2), (1, 3)),
        ((0, 2), (1, 2), (2, 2), (3, 2)),
        ((2, 0), (2, 1), (2, 2), (2, 3)),
        ((0, 1), (1, 1), (2, 1), (3, 1)),
    ],
    "O": [((0, 1), (0, 2), (1, 1), (1, 2))] * 4,
    "T": [
        ((0, 1), (1, 0), (1, 1), (1, 2)),
        ((0, 1), (1, 1), (1, 2), (2, 1)),
        ((1, 0), (1, 1), (1, 2), (2, 1)),
        ((0, 1), (1, 0), (1, 1), (2, 1)),
    ],
    "S": [
        ((0, 1), (0, 2), (1, 0), (1, 1)),
        ((0, 1), (1, 1), (1, 2), (2, 2)),
        ((1, 1), (1, 2), (2, 0), (2, 1)),
        ((0, 0), (1, 0), (1, 1), (2, 1)),
    ],
    "Z": [
        ((0, 0), (0, 1), (1, 1), (1, 2)),
        ((0, 2), (1, 1), (1, 2), (2, 1)),
        ((1, 0), (1, 1), (2, 1), (2, 2)),
        ((0, 1), (1, 0), (1, 1), (2, 0)),
    ],
    "J": [
        ((0, 0), (1, 0), (1, 1), (1, 2)),
        ((0, 1), (0, 2), (1, 1), (2, 1)),
        ((1, 0), (1, 1), (1, 2), (2, 2)),
        ((0, 1), (1, 1), (2, 0), (2, 1)),
    ],
    "L": [
        ((0, 2), (1, 0), (1, 1), (1, 2)),
        ((0, 1), (1, 1), (2, 1), (2, 2)),
        ((1, 0), (1, 1), (1, 2), (2, 0)),
        ((0, 0), (0, 1), (1, 1), (2, 1)),
    ],
}
PIECES = tuple(_SHAPES.keys())

# 通常SRSの補正(キック)テーブル。(回転前, 回転後) → 試す順の(横, 縦)オフセット。
# 縦は上向きが正(ガイドラインの表記)。適用時に行方向へ符号を反転する。
_KICKS_JLSTZ: dict[tuple[int, int], tuple[tuple[int, int], ...]] = {
    (0, 1): ((0, 0), (-1, 0), (-1, 1), (0, -2), (-1, -2)),
    (1, 0): ((0, 0), (1, 0), (1, -1), (0, 2), (1, 2)),
    (1, 2): ((0, 0), (1, 0), (1, -1), (0, 2), (1, 2)),
    (2, 1): ((0, 0), (-1, 0), (-1, 1), (0, -2), (-1, -2)),
    (2, 3): ((0, 0), (1, 0), (1, 1), (0, -2), (1, -2)),
    (3, 2): ((0, 0), (-1, 0), (-1, -1), (0, 2), (-1, 2)),
    (3, 0): ((0, 0), (-1, 0), (-1, -1), (0, 2), (-1, 2)),
    (0, 3): ((0, 0), (1, 0), (1, 1), (0, -2), (1, -2)),
}
_KICKS_I: dict[tuple[int, int], tuple[tuple[int, int], ...]] = {
    (0, 1): ((0, 0), (-2, 0), (1, 0), (-2, -1), (1, 2)),
    (1, 0): ((0, 0), (2, 0), (-1, 0), (2, 1), (-1, -2)),
    (1, 2): ((0, 0), (-1, 0), (2, 0), (-1, 2), (2, -1)),
    (2, 1): ((0, 0), (1, 0), (-2, 0), (1, -2), (-2, 1)),
    (2, 3): ((0, 0), (2, 0), (-1, 0), (2, 1), (-1, -2)),
    (3, 2): ((0, 0), (-2, 0), (1, 0), (-2, -1), (1, 2)),
    (3, 0): ((0, 0), (1, 0), (-2, 0), (1, -2), (-2, 1)),
    (0, 3): ((0, 0), (-1, 0), (2, 0), (-1, 2), (2, -1)),
}

SPAWN_ROW = 0
SPAWN_COL = 3


def piece_cells(piece: str, orient: int, row: int, col: int) -> tuple[Cell, ...]:
    """箱の左上が(row, col)にあるときの、盤面上の4マス。"""
    return tuple((row + r, col + c) for r, c in _SHAPES[piece][orient % 4])


class PieceSequence:
    """7-bag方式のミノ列。シードが同じなら同じ列になる(同一配列の再現用)。

    練習中の推奨手にはvisible_next()の範囲(NEXT5)だけを渡すこと。
    peek()で先を覗けるのは、同一配列リセット・教材生成などの内部用途に限る。
    """

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self._rng = random.Random(seed)
        self._pieces: list[str] = []

    def _ensure(self, count: int) -> None:
        while len(self._pieces) < count:
            bag = list(PIECES)
            self._rng.shuffle(bag)
            self._pieces.extend(bag)

    def peek(self, index: int) -> str:
        self._ensure(index + 1)
        return self._pieces[index]


@dataclass(frozen=True)
class Snapshot:
    """一手戻す用に保存する、手番の開始時点(ミノが出現した直後、HOLD前)の状態。

    固定の直前ではなく手番の開始時点を保存するので、その手番で行ったHOLDも
    一緒に取り消され、繰り返し戻せば練習開始状態に戻る(仕様書10-1)。
    """

    board: tuple[tuple[str | None, ...], ...]
    current: str
    hold: str | None
    hold_used: bool
    sequence_index: int
    lines_cleared: int
    back_to_back: int
    combo: int
    last_clear: str | None


@dataclass
class GameState:
    """練習中の盤面・操作ミノ・HOLD・ミノ列と、やり直しの履歴。"""

    sequence: PieceSequence
    board: list[list[str | None]] = field(default_factory=lambda: [[None] * COLS for _ in range(ROWS)])
    current: str = ""
    orient: int = 0
    row: int = SPAWN_ROW
    col: int = SPAWN_COL
    hold: str | None = None
    hold_used: bool = False  # このミノでHOLDを使ったか(1手番に1回)
    sequence_index: int = 0  # 次にNEXTから出てくるミノの通し番号
    lines_cleared: int = 0
    # BtoB(Back to Back): テトリス・Tスピン消し(ミニ含む)が続いた回数。
    # -1=まだ無い/途切れた、0=1回目、1以上=BtoB×n。消去なしの固定では途切れない。
    back_to_back: int = -1
    combo: int = -1  # REN: 連続して消した回数-1(-1=途切れている)
    last_clear: str | None = None  # 直前の固定で消した役の名前(表示用)
    # 直前の固定で置いたミノと4マス(消去前の座標)。推奨手(テンプレ)の進行判定用。
    # おじゃまのせり上げ等、固定以外で手番が変わったらNone。
    last_lock: tuple[str, tuple[Cell, ...]] | None = None
    history: list[Snapshot] = field(default_factory=list)
    # 今の手番の開始時点。固定したときにhistoryへ積む。
    turn_start: Snapshot | None = None
    game_over: bool = False
    # 最後に成功した回転で使った補正の番号(0=補正なし)。直後に移動・落下
    # すればNoneに戻る。Tスピン判定(第2段階以降)の準備。
    last_rotation_kick: int | None = None

    @classmethod
    def new(cls, seed: int) -> "GameState":
        state = cls(sequence=PieceSequence(seed))
        state._begin_turn(state._take_next())
        return state

    # ---- 参照 ----
    def visible_next(self) -> tuple[str, ...]:
        """NEXT5。これより先は推奨手の判断へ渡さない。"""
        return tuple(self.sequence.peek(self.sequence_index + i) for i in range(NEXT_VISIBLE))

    def current_cells(self) -> tuple[Cell, ...]:
        return piece_cells(self.current, self.orient, self.row, self.col)

    def ghost_row(self) -> int:
        """今の向き・列のまま落としたときの箱の行(接地位置)。"""
        row = self.row
        while self._fits(self.current, self.orient, row + 1, self.col):
            row += 1
        return row

    def is_grounded(self) -> bool:
        return not self._fits(self.current, self.orient, self.row + 1, self.col)

    # ---- 操作(成功したらTrue) ----
    def move_left(self) -> bool:
        return self._shift(0, -1)

    def move_right(self) -> bool:
        return self._shift(0, 1)

    def soft_drop(self) -> bool:
        """1マス下へ。接地しても固定はしない(【2026-09-23・利用者の指示】
        一番下まで一気に落とさず1マスずつ。押しっぱなしで連続して降りる)。"""
        return self._shift(1, 0)

    def add_garbage(self, count: int, rng: random.Random | None = None) -> bool:
        """おじゃまブロックをcount段(1〜5)下からせり上げる。

        【2026-09-23・利用者の指示】穴の位置はランダム。複数段では、全段が同じ列に
        穴がある「直列」か、段ごとに穴の列が違う「バラ」かもランダムに決める。
        一手戻すで、せり上げる前(その手番の開始時点)に戻れる。
        操作中のミノが重なる場合は上へ押し上げる。上端からはみ出したら積み上がり。
        """
        if self.game_over or not 1 <= count <= 5:
            return False
        rng = rng or random.Random()
        if self.turn_start is not None:
            self.history.append(self.turn_start)
        if rng.random() < 0.5:
            holes = [rng.randrange(COLS)] * count  # 直列
        else:
            holes = [rng.randrange(COLS) for _ in range(count)]  # バラ
        self.last_lock = None
        overflow = any(cell is not None for row in self.board[:count] for cell in row)
        self.board = self.board[count:] + [
            ["GARBAGE" if c != hole else None for c in range(COLS)] for hole in holes
        ]
        while not self._fits(self.current, self.orient, self.row, self.col) and self.row > -4:
            self.row -= 1
        if overflow or not self._fits(self.current, self.orient, self.row, self.col):
            self.game_over = True
        self.turn_start = self._snapshot()
        return True

    def rotate_cw(self) -> bool:
        return self._rotate(1)

    def rotate_ccw(self) -> bool:
        return self._rotate(-1)

    def hard_drop(self) -> None:
        """接地位置まで落として固定し、ライン消去と次のミノの出現まで行う。"""
        if self.game_over:
            return
        if self.turn_start is not None:
            self.history.append(self.turn_start)
        drop_to = self.ghost_row()
        if drop_to != self.row:
            self.last_rotation_kick = None  # 落下した: 最後の操作は回転ではない
        self.row = drop_to
        spin = self._t_spin_kind()
        self.last_lock = (self.current, self.current_cells())
        for r, c in self.current_cells():
            self.board[r][c] = self.current
        cleared = [r for r in range(ROWS) if all(cell is not None for cell in self.board[r])]
        for r in cleared:
            del self.board[r]
            self.board.insert(0, [None] * COLS)
        self.lines_cleared += len(cleared)
        self._score_clear(len(cleared), spin)
        self.hold_used = False
        self._begin_turn(self._take_next())

    def _t_spin_kind(self) -> str | None:
        """固定する直前のTがTスピンか("full"/"mini")。3コーナー方式。"""
        if self.current != "T" or self.last_rotation_kick is None:
            return None
        corners = {(0, 0): None, (0, 2): None, (2, 0): None, (2, 2): None}
        for dr, dc in corners:
            r, c = self.row + dr, self.col + dc
            corners[(dr, dc)] = not (0 <= r < ROWS and 0 <= c < COLS) or self.board[r][c] is not None
        if sum(corners.values()) < 3:
            return None
        front = {0: ((0, 0), (0, 2)), 1: ((0, 2), (2, 2)), 2: ((2, 0), (2, 2)), 3: ((0, 0), (2, 0))}[self.orient]
        if all(corners[f] for f in front) or self.last_rotation_kick == 4:
            return "full"
        return "mini"

    def _score_clear(self, lines: int, spin: str | None) -> None:
        """消した役の名前・BtoB・RENを更新する。"""
        if lines == 0:
            self.combo = -1
            self.last_clear = {"full": "Tスピン", "mini": "Tスピン ミニ"}.get(spin or "")
            return
        if spin == "full":
            name = {1: "TSS(Tスピンシングル)", 2: "TSD(Tスピンダブル)", 3: "TST(Tスピントリプル)"}[lines]
        elif spin == "mini":
            name = {1: "Tスピン ミニ シングル", 2: "Tスピン ミニ ダブル"}.get(lines, "Tスピン ミニ")
        else:
            name = {1: "シングル", 2: "ダブル", 3: "トリプル", 4: "テトリス"}[lines]
        difficult = spin is not None or lines == 4
        self.back_to_back = self.back_to_back + 1 if difficult else -1
        self.combo += 1
        if all(cell is None for row in self.board for cell in row):
            name += " + パーフェクトクリア"
        self.last_clear = name

    def use_hold(self) -> bool:
        """HOLDと交換する(1手番に1回)。空ならNEXTから次のミノが出る。"""
        if self.game_over or self.hold_used:
            return False
        held, self.hold = self.hold, self.current
        self._spawn(held if held is not None else self._take_next())
        self.hold_used = True
        return True

    # ---- やり直し ----
    def undo(self) -> bool:
        """直前の固定をなかったことにし、その手番の開始時点(HOLD前)に戻す。"""
        if not self.history:
            return False
        snap = self.history.pop()
        self._restore(snap)
        return True

    def _restore(self, snap: Snapshot) -> None:
        self.board = [list(row) for row in snap.board]
        self.hold = snap.hold
        self.hold_used = snap.hold_used
        self.sequence_index = snap.sequence_index
        self.lines_cleared = snap.lines_cleared
        self.back_to_back = snap.back_to_back
        self.combo = snap.combo
        self.last_clear = snap.last_clear
        self.game_over = False
        self._spawn(snap.current)
        self.turn_start = snap

    def reset_same_sequence(self) -> "GameState":
        """同じミノ列(未表示の将来分も含む)で開始状態に戻す。"""
        return GameState.new(self.sequence.seed)

    def reset_new_sequence(self, seed: int | None = None) -> "GameState":
        """新しいミノ列で開始する。"""
        if seed is None:
            seed = random.SystemRandom().randrange(1 << 31)
        return GameState.new(seed)

    # ---- 内部 ----
    def _snapshot(self) -> Snapshot:
        return Snapshot(
            board=tuple(tuple(row) for row in self.board),
            current=self.current,
            hold=self.hold,
            hold_used=self.hold_used,
            sequence_index=self.sequence_index,
            lines_cleared=self.lines_cleared,
            back_to_back=self.back_to_back,
            combo=self.combo,
            last_clear=self.last_clear,
        )

    def _take_next(self) -> str:
        piece = self.sequence.peek(self.sequence_index)
        self.sequence_index += 1
        return piece

    def _begin_turn(self, piece: str) -> None:
        """新しい手番を始める(出現させ、その時点を一手戻す用に控える)。"""
        self._spawn(piece)
        self.turn_start = self._snapshot()

    def _spawn(self, piece: str) -> None:
        self.current = piece
        self.orient = 0
        self.row = SPAWN_ROW
        self.col = SPAWN_COL
        self.last_rotation_kick = None
        if not self._fits(piece, 0, SPAWN_ROW, SPAWN_COL):
            self.game_over = True

    def _fits(self, piece: str, orient: int, row: int, col: int) -> bool:
        for r, c in piece_cells(piece, orient, row, col):
            if not (0 <= r < ROWS and 0 <= c < COLS):
                return False
            if self.board[r][c] is not None:
                return False
        return True

    def _shift(self, drow: int, dcol: int) -> bool:
        if self.game_over or not self._fits(self.current, self.orient, self.row + drow, self.col + dcol):
            return False
        self.row += drow
        self.col += dcol
        self.last_rotation_kick = None
        return True

    def _rotate(self, direction: int) -> bool:
        """通常SRS: 回転して衝突したら補正テーブルの順に位置をずらして試す。"""
        if self.game_over or self.current == "O":
            return not self.game_over  # Oは回転しても形が変わらない
        new_orient = (self.orient + direction) % 4
        kicks = (_KICKS_I if self.current == "I" else _KICKS_JLSTZ)[(self.orient, new_orient)]
        for index, (dx, dy) in enumerate(kicks):
            row, col = self.row - dy, self.col + dx
            if self._fits(self.current, new_orient, row, col):
                self.orient = new_orient
                self.row, self.col = row, col
                self.last_rotation_kick = index
                return True
        return False


def visible_board(state: GameState) -> list[list[str | None]]:
    """可視20行の盤面(非表示行を除く)。"""
    return [list(row) for row in state.board[HIDDEN_ROWS:]]


__all__ = [
    "COLS",
    "HIDDEN_ROWS",
    "NEXT_VISIBLE",
    "PIECES",
    "ROWS",
    "GameState",
    "PieceSequence",
    "Snapshot",
    "piece_cells",
    "visible_board",
]
