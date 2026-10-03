"""無限中あけREN: 見えているミノでRENを続けられる手の解析(AI解析)。

【2026-09-25・利用者の要望】見えている段階でRENを続けられる手を解析して示す。
- 使うのは操作ミノ・HOLD・NEXT5だけ(未表示の配列は見ない)。
- 置き方は通常SRSで出現位置から届く位置だけ(srs_reach.lock_positions)。
- 毎手ラインが消える置き方だけをたどり、最も長くRENが続く手順を探す。
- 見えている範囲の最後でも、次のミノ(種類は見えないが必ず来る)と入れ替えてHOLDのミノを置ける。
- 同じ長さなら、置き終えた後の積み上がりが低い手順を選ぶ(次の手の選択肢が多い)。
- 【2026-10-03・利用者の指示】RENの消化は1手ごとに評価を改めて最大になるようにする。見えているミノで続く
  手数が同じなら、その後に来うるミノ(7種)のうち、HOLDも使ってラインを消せる種類が多い残り方を選ぶ
  (見えない先までRENが続きやすい手)。続く手数・その種類数・積み上がりの低さの順に比べる。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from src.education.rules import _SHAPES, COLS, HIDDEN_ROWS, ROWS
from src.engine.srs_reach import lock_positions

UNKNOWN = "?"  # 見えている範囲の次に来るミノ(種類は分からない)

Board = frozenset  # 22行座標の占有マス


@dataclass(frozen=True)
class RenStep:
    piece: str
    cells: tuple[tuple[int, int], ...]  # 22行座標
    use_hold: bool


@dataclass(frozen=True)
class RenPlan:
    steps: tuple[RenStep, ...]  # RENが続く手順(先頭がこの手番の手)
    visible: int  # 見えている範囲で置けるミノの数(全部つながればlen(steps)と同じ)

    @property
    def complete(self) -> bool:
        """見えているミノをすべて使ってRENが続く。"""
        return len(self.steps) >= self.visible


def _lock(board: Board, cells) -> tuple[Board, int]:
    placed = set(board) | set(cells)
    full = [r for r in range(ROWS) if all((r, c) in placed for c in range(COLS))]
    if not full:
        return frozenset(placed), 0
    return frozenset((r + sum(1 for f in full if f > r), c) for r, c in placed if r not in full), len(full)


def _stack_top(board: Board, well: range) -> int:
    """井戸(中央4列)に残っているブロックの高さ(低いほど次の手の選択肢が多い)。"""
    rows = [r for r, c in board if c in well]
    return ROWS - min(rows) if rows else 0


PIECES = "IOTSZJL"


@lru_cache(maxsize=100_000)
def _can_clear(board: Board, piece: str) -> bool:
    """そのミノを真上から落としてラインを消せる位置があるか(次の手の評価用の目安)。

    【2026-10-03】出現位置からのSRSの探索(lock_positions)は、20段まで積んだ深い井戸では1回5ms前後かかり、
    評価で数千回呼ぶと1手番に2秒を超えた。4列の井戸で消す置き方はほとんど真上から落とすだけで届くので、
    評価には向き・列ごとに真上から落とした位置だけを使う(実際に置く手は従来どおりSRSで探す)。
    """
    for shape in _SHAPES[piece]:
        rows = [r for r, _c in shape]
        cols = [c for _r, c in shape]
        for col in range(-min(cols), COLS - max(cols)):
            row = HIDDEN_ROWS - min(rows)
            if any((row + r, col + c) in board for r, c in shape):
                continue
            while all(row + r + 1 < ROWS and (row + r + 1, col + c) not in board for r, c in shape):
                row += 1
            cells = [(row + r, col + c) for r, c in shape]
            placed = board | set(cells)
            if any(all((r, c) in placed for c in range(COLS)) for r in {r for r, _c in cells}):
                return True
    return False


def _continuable(board: Board, held: str | None) -> int:
    """次に来うる7種のうち、RENを続けられる種類の数(そのミノか、HOLDのミノと入れ替えて消せる)。"""
    hold_ok = held not in (None, UNKNOWN) and _can_clear(board, held)
    return sum(1 for p in PIECES if hold_ok or _can_clear(board, p))


def find_ren_plan(board: Board, sequence: list[str], hold: str | None, can_hold: bool, well: range) -> RenPlan | None:
    """RENが最も長く続く手順。1手も続かなければNone。

    sequence: 先頭が操作ミノの、見えているミノ順。hold: 今のHOLD。can_hold: この手番でHOLDできるか。
    """
    board = frozenset(board)
    visible = len(sequence) + (1 if hold is not None else 0)

    @lru_cache(maxsize=None)
    def best(b: Board, index: int, held: str | None, first: bool):
        """(続く手数, 積み上がりの低さの評価, 手順)。"""
        options = []
        if index < len(sequence):
            options.append((sequence[index], False, index + 1, held))
        if not (first and not can_hold):
            if held is not None and held != UNKNOWN and index <= len(sequence):
                options.append((held, True, index + 1, sequence[index] if index < len(sequence) else UNKNOWN))
            elif held is None and index + 1 < len(sequence):
                options.append((sequence[index + 1], True, index + 2, sequence[index]))
        # ここで止まったときの評価: 次に来うるミノで続けられる種類の数、積み上がりの低さ
        result = (0, (_continuable(b, held), -_stack_top(b, well)), ())
        for piece, use_hold, next_index, next_held in options:
            if use_hold and held is not None and index < len(sequence) and piece == sequence[index]:
                continue  # 同じ種類のミノを入れ替えても結果は同じ
            for cells in sorted(lock_positions(b, piece)[0]):
                if any(r < HIDDEN_ROWS for r, _c in cells):
                    continue
                nb, cleared = _lock(b, cells)
                if cleared == 0:
                    continue  # 消えない置き方ではRENが途切れる
                length, low, rest = best(nb, next_index, next_held, False)
                candidate = (length + 1, low, (RenStep(piece, cells, use_hold), *rest))
                if candidate[:2] > result[:2]:
                    result = candidate
        return result

    length, _low, steps = best(board, 0, hold, True)
    return RenPlan(steps, visible) if length else None
