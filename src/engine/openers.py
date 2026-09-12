"""開幕テンプレ: 盤面図(opener_data.py)から、実際のミノ順に合わせた手順をその場で組み立てる。

テンプレの解説ページは「Iが早いこと」「JとLの早い方で左右を決める」のように
ミノ順の条件と分岐で説明されているが、各巡の「最終形の図」さえあれば、
実際に出てきた順番に対して
  ・今のミノを図の位置へ置けるか(下に支えがあり、上が空いていて
    ハードドロップで入る)
  ・置けなければホールドして、ホールドしていたミノを置けるか
を全探索すれば手順が決まる(1巡7手なので探索は一瞬)。分岐の手順データを
手入力する必要がなく、写し間違いの余地も減る。

【巡をまたぐ進め方】
図には「既に置いてあるブロック('c')」が描かれている。ある巡の図を置き
終えたら、次はその盤面(既存ブロック)に一致する図を同じテンプレの中から
探し、実際のミノ順で組めるものを選ぶ。理想形/通常形/妥協形、左右反転、
Tスピンを打つ図などは、すべてこの「既存ブロックの一致」で自然に選ばれる。
'U'(Tスピンで入れるT)は、図の他のミノをすべて置いてから最後に入れる。
"""

from __future__ import annotations

from dataclasses import dataclass

from .opener_data import OPENER_SOURCE_FORMS

BOARD_ROWS = 20
BOARD_COLS = 10

Cells = tuple[tuple[int, int], ...]

_ALL_PIECES = "IOTSZJL"


@dataclass(frozen=True)
class FormItem:
    piece: str
    cells: Cells
    # ハードドロップでは入らない(既存ブロックの張り出しの下に入れる。
    # Tスピンや回転入れ)。図の既存ブロックが同じ列の上にある場合に立てる。
    spin: bool = False
    # 図の他のミノをすべて置いた後にだけ置く('U'で描かれたTスピン)。
    last: bool = False


@dataclass(frozen=True)
class OpenerForm:
    section: str
    existing: frozenset[tuple[int, int]]  # 既に置いてあるべきブロック
    items: tuple[FormItem, ...]  # この図で置くミノ
    text: str
    # ハードドロップで入らなくても回転入れで置けるとページに明記されているミノ種。
    tuck_pieces: frozenset[str] = frozenset()


# ページの注記で「後から回転入れできる」とされているミノ。
# (テンプレ名, セクション名) → ミノ種。左右反転の図では J↔L・S↔Z を読み替える。
# 迷走砲: 「2巡目の%Lは%Zを置いた後でも回転入れすることができます。(左回転)」
_TUCK_NOTES: dict[tuple[str, str], frozenset[str]] = {
    ("迷走砲", "理想形 > 2巡目"): frozenset("L"),
    ("迷走砲", "通常形 > %O>%Sの場合"): frozenset("L"),
    ("迷走砲", "通常形 > %S>%Oの場合"): frozenset("L"),
}
_MIRROR_PIECE = {"J": "L", "L": "J", "S": "Z", "Z": "S"}


@dataclass(frozen=True)
class OpenerTemplate:
    name_ja: str
    name_en: str
    source_url: str
    forms: tuple[OpenerForm, ...]


def _components(cells: list[tuple[int, int]]) -> list[Cells]:
    """4近傍で連結した塊に分ける。"""
    remaining = set(cells)
    groups: list[Cells] = []
    while remaining:
        start = min(remaining)
        stack = [start]
        group = {start}
        remaining.discard(start)
        while stack:
            r, c = stack.pop()
            for nr, nc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
                if (nr, nc) in remaining:
                    remaining.discard((nr, nc))
                    group.add((nr, nc))
                    stack.append((nr, nc))
        groups.append(tuple(sorted(group)))
    return groups


def parse_form(text: str, section: str = "", tuck_pieces: frozenset[str] = frozenset()) -> OpenerForm | None:
    """テキスト盤面図を解釈する。ミノが4マスの塊になっていない図はNone。"""
    lines = [line for line in text.splitlines() if line]
    if not lines or any(len(line) != BOARD_COLS for line in lines):
        return None
    existing: set[tuple[int, int]] = set()
    by_symbol: dict[str, list[tuple[int, int]]] = {}
    for i, line in enumerate(lines):
        row = BOARD_ROWS - len(lines) + i
        for col, ch in enumerate(line):
            if ch == "-":
                continue
            if ch in "cC":
                existing.add((row, col))
            else:
                by_symbol.setdefault(ch, []).append((row, col))
    items: list[FormItem] = []
    for symbol, cells in by_symbol.items():
        if symbol == "U":
            piece, last = "T", True
        elif symbol.upper() in _ALL_PIECES:
            piece, last = symbol.upper(), False
        else:
            return None
        for group in _components(cells):
            if len(group) != 4:
                return None
            # 既存ブロックが同じ列の上にあるミノは、図の上ではハードドロップで
            # 入らない(TSDのT、回転入れのLなど)。
            group_set = set(group)
            blocked = any(
                (rr, c) in existing for r, c in group for rr in range(r) if (rr, c) not in group_set
            )
            items.append(FormItem(piece, group, spin=last or blocked, last=last))
    if not items:
        return None
    return OpenerForm(
        section=section, existing=frozenset(existing), items=tuple(items), text=text, tuck_pieces=tuck_pieces
    )


def mirror_form_text(text: str) -> str:
    """左右反転した図(列を反転し、J↔L・S↔Zを入れ替える)。"""
    table = str.maketrans("jlszJLSZ", "ljzsLJZS")
    return "\n".join(line[::-1].translate(table) for line in text.splitlines())


def _build_templates() -> tuple[OpenerTemplate, ...]:
    templates = []
    for name_ja, name_en, url, source_forms in OPENER_SOURCE_FORMS:
        forms: list[OpenerForm] = []
        seen: set[str] = set()
        for section, text in source_forms:
            tuck = _TUCK_NOTES.get((name_ja, section), frozenset())
            for mirrored, variant in ((False, text), (True, mirror_form_text(text))):
                if variant in seen:
                    continue
                seen.add(variant)
                pieces = frozenset(_MIRROR_PIECE.get(p, p) for p in tuck) if mirrored else tuck
                form = parse_form(variant, section, pieces)
                if form is not None:
                    forms.append(form)
        templates.append(OpenerTemplate(name_ja, name_en, url, tuple(forms)))
    return tuple(templates)


OPENER_TEMPLATES: tuple[OpenerTemplate, ...] = _build_templates()


@dataclass(frozen=True)
class OpenerStep:
    piece: str
    cells: Cells
    use_hold: bool  # ホールドしてから置く(置くミノは操作中のミノではない)
    spin: bool = False


def _can_hard_drop(placed: set[tuple[int, int]], cells: Cells) -> bool:
    """cellsの位置へ、上から真っ直ぐ落として置けるか。

    ・マスが空いている
    ・各マスの上方(同じ列でそのマスより上)にブロックがない(潜り込み不要)
    ・少なくとも1マスが床か既存ブロックの上に載る
    """
    cell_set = set(cells)
    for r, c in cells:
        if (r, c) in placed:
            return False
        for rr in range(r):
            if (rr, c) in placed and (rr, c) not in cell_set:
                return False
    return any(r + 1 >= BOARD_ROWS or (r + 1, c) in placed for r, c in cells)


def _can_rest(placed: set[tuple[int, int]], cells: Cells) -> bool:
    """cellsが空いていて、床か既存ブロックの上に載るか(入れ方は問わない)。"""
    if any(cell in placed for cell in cells):
        return False
    return any(r + 1 >= BOARD_ROWS or (r + 1, c) in placed for r, c in cells)


def plan_form(
    form: OpenerForm,
    sequence: list[str],
    hold: str | None,
    placed: set[tuple[int, int]] | None = None,
    allow_tuck: bool | None = None,
) -> list[OpenerStep] | None:
    """実際のミノ順(先頭が操作中のミノ)とホールドに対して、図を組む手順を返す。

    各手番で「操作中のミノを置く」か「ホールドして、ホールドにあったミノ
    (空なら次のミノ)を置く」のどちらかを選ぶ。Tスピンの手('U')は他のミノを
    すべて置いた後にだけ置ける。図のミノをすべて置ける手順が無ければNone。

    allow_tuck: 張り出しの下へ回転入れするミノ(form.tuck_pieces)を許すか。
    Noneなら、まずハードドロップだけで組める手順を探し、無ければ許して
    探し直す。テトリス堂の図には「Lは左回転で後入れできる」のように
    ハードドロップでは入らない置き方を前提にした形があるため(迷走砲の
    2巡目)。ページに明記のないミノは、入れ方が実際にあるか分からない
    (張り出しの下へ横から入れられるとは限らない)ので許さない。
    """
    if allow_tuck is None:
        strict = plan_form(form, sequence, hold, placed, allow_tuck=False)
        if strict is not None or not form.tuck_pieces:
            return strict
        return plan_form(form, sequence, hold, placed, allow_tuck=True)

    placed_cells = set(placed) if placed is not None else set(form.existing)
    items = form.items
    last_count = sum(1 for it in items if it.last)
    # 分かっているミノ順の先に「種類不明のミノ」を2つ足す。図の最後の手が
    # ホールドしていたミノなら、次に来るミノが何であれホールドと入れ替えて
    # 置けるため(例: TをホールドしておいてTスピンを最後に打つ)、既知の
    # ミノ順だけでは手順が組めない形を救う。不明のミノ自体は置けない。
    sequence = [*sequence, "?", "?"]

    def placeable(item: FormItem, current_placed: set[tuple[int, int]], done: frozenset[int]) -> bool:
        if item.last and len(done) < len(items) - last_count:
            return False
        if item.spin:
            # 図の時点で張り出しの下にあるミノ(TSD等)は、入れ方を問わず
            # マスが空いていれば置ける扱い。他のミノの置き順には影響させない。
            return _can_rest(current_placed, item.cells)
        if _can_hard_drop(current_placed, item.cells):
            return True
        return allow_tuck and item.piece in form.tuck_pieces and _can_rest(current_placed, item.cells)

    def candidates(piece: str, current_placed: set[tuple[int, int]], done: frozenset[int]) -> list[int]:
        return [
            i
            for i, item in enumerate(items)
            if i not in done and item.piece == piece and placeable(item, current_placed, done)
        ]

    def search(index: int, hold_piece: str | None, current_placed: set[tuple[int, int]], done: frozenset[int]):
        if len(done) == len(items):
            return []
        if index >= len(sequence):
            return None
        current = sequence[index]
        # 1) 操作中のミノをそのまま置く
        for i in candidates(current, current_placed, done):
            rest = search(index + 1, hold_piece, current_placed | set(items[i].cells), done | {i})
            if rest is not None:
                return [OpenerStep(current, items[i].cells, False, items[i].spin)] + rest
        # 2) ホールドして、出てきたミノを置く
        if hold_piece is None:
            if index + 1 < len(sequence):
                nxt = sequence[index + 1]
                for i in candidates(nxt, current_placed, done):
                    rest = search(index + 2, current, current_placed | set(items[i].cells), done | {i})
                    if rest is not None:
                        return [OpenerStep(nxt, items[i].cells, True, items[i].spin)] + rest
        else:
            for i in candidates(hold_piece, current_placed, done):
                rest = search(index + 1, current, current_placed | set(items[i].cells), done | {i})
                if rest is not None:
                    return [OpenerStep(hold_piece, items[i].cells, True, items[i].spin)] + rest
        return None

    return search(0, hold, placed_cells, frozenset())


def known_sequence(current_piece: str | None, next_queue: tuple[str, ...]) -> list[str] | None:
    """操作ミノ+NEXT5枠から、分かる範囲のミノ順を返す。

    6つがすべて異なる種類なら同じ袋(7-bag)なので残り1つも確定できる。
    種類が重なる(袋の境目をまたぐ)場合は6つだけを返す。
    """
    if current_piece is None or len(next_queue) != 5:
        return None
    seen = [current_piece, *next_queue]
    if not set(seen) <= set(_ALL_PIECES):
        return None
    if len(set(seen)) == 6:
        (missing,) = set(_ALL_PIECES) - set(seen)
        return [*seen, missing]
    return seen


def choose_form(
    template: OpenerTemplate,
    board_cells: set[tuple[int, int]],
    sequence: list[str],
    hold: str | None,
) -> tuple[OpenerForm, list[OpenerStep]] | None:
    """今の盤面(おじゃまを除く占有)に既存ブロックが一致し、ミノ順で組める図を返す。

    一致は「図の既存ブロックがすべて盤面にあり、盤面にそれ以外のマスが
    1ミノ分未満(3マス以下)」で判定する。置いたばかりのミノが光って
    余分なマスとして読まれた程度なら次の図へ進めるようにするため。余分な
    マスは一時的な読み取りとみなし、手順の探索では無視する。
    """
    target = frozenset(board_cells)
    # 置くミノが多い図(ホールドに残さず7つ置く形)を優先する。迷走砲のように
    # 「Zをホールドしておく形」と「Zも置く形」の両方が載っている場合、
    # 2巡目以降の図は後者を前提にしているため。
    for form in sorted(template.forms, key=lambda f: -len(f.items)):
        if not form.existing <= target or len(target - form.existing) >= 4:
            continue
        steps = plan_form(form, sequence, hold)
        if steps is not None:
            return form, steps
    return None


def choose_opener(
    sequence: list[str], hold: str | None = None, board_cells: set[tuple[int, int]] | None = None
) -> tuple[OpenerTemplate, OpenerForm, list[OpenerStep]] | None:
    """組めるテンプレを探し、最初に見つかったものと図・手順を返す(既定は空の盤面)。"""
    cells = board_cells if board_cells is not None else set()
    for template in OPENER_TEMPLATES:
        chosen = choose_form(template, cells, sequence, hold)
        if chosen is not None:
            form, steps = chosen
            return template, form, steps
    return None


def full_rows_after(cells: set[tuple[int, int]], step_cells: Cells) -> list[int]:
    """ミノを置いた後に揃う(消える)行。"""
    result = set(cells) | set(step_cells)
    return [r for r in range(BOARD_ROWS) if all((r, c) in result for c in range(BOARD_COLS))]


def shift_cells_for_clears(cells: Cells, cleared_rows: list[int]) -> Cells:
    """消えた行より上のマスを、消えた行数ぶん下へずらす。

    図は「消える前」の座標で描かれている(TSDのTと、その後に置くミノが
    同じ図にある)ため、消去が起きたら残りの手の座標を実際の盤面に合わせる。
    """
    return tuple((r + sum(1 for fr in cleared_rows if fr > r), c) for r, c in cells)


def apply_step(cells: set[tuple[int, int]], step_cells: Cells) -> set[tuple[int, int]]:
    """盤面(占有マス集合)にミノを置き、揃った行を消して詰めた結果を返す。"""
    result = set(cells) | set(step_cells)
    full_rows = full_rows_after(cells, step_cells)
    if not full_rows:
        return result
    shifted: set[tuple[int, int]] = set()
    for r, c in result:
        if r in full_rows:
            continue
        drop = sum(1 for fr in full_rows if fr > r)
        shifted.add((r + drop, c))
    return shifted
