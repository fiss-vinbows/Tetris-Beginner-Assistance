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

from .opener_data import EDUCATION_SOURCE_FORMS, OPENER_SOURCE_FORMS

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
    # 置いたときに自分の行がすべて揃って消える場合だけ置ける(別図から合流した
    # TSTのT。_mark_required_items参照)。
    must_clear: bool = False


@dataclass(frozen=True)
class OpenerForm:
    section: str
    existing: frozenset[tuple[int, int]]  # 既に置いてあるべきブロック
    items: tuple[FormItem, ...]  # この図で置くミノ
    text: str
    # ハードドロップで入らなくても回転入れで置けるとページに明記されているミノ種。
    tuck_pieces: frozenset[str] = frozenset()
    # Tスピン(砲)の形を作るのに必要なミノの番号(itemsの添字)。Noneなら全部。
    # 図どおり全部は置けないミノ順でも、ここに含まれるミノだけ置ければ
    # TST/TSDは打てる(パフェは諦める)。
    required: frozenset[int] | None = None

    def is_spin_only(self) -> bool:
        return all(item.spin for item in self.items)

    def spin_rows(self) -> frozenset[int]:
        return frozenset(r for item in self.items if item.spin for r, _c in item.cells)


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


def _with_required(form: OpenerForm, spin_rows: frozenset[int]) -> OpenerForm:
    """Tスピンで消える行に掛かるミノを「必要なミノ」として印を付けた図を返す。"""
    required = frozenset(i for i, item in enumerate(form.items) if any(r in spin_rows for r, _c in item.cells))
    if not required or len(required) == len(form.items):
        return form
    return OpenerForm(form.section, form.existing, form.items, form.text, form.tuck_pieces, required)


def _mark_required_items(forms: list[OpenerForm]) -> list[OpenerForm]:
    """【2026-09-12・利用者の方針】2巡目の図どおりに全部置けないミノ順でも、
    TST/TSDの形(砲)までは組み切る。Tスピンで消える行に掛かるミノだけを
    必須にし、その上に積むミノ(パフェ用)は置ければ置く扱いにする。

    Tスピンが同じ図に描かれている場合はその行から、はちみつ砲のように
    Tスピンだけ別の図(U)になっている場合は同じセクションのその図から、
    消える行を求める。

    【2026-09-14実機】別図のTスピンは、その図のTを「途中でも置けるスピン手」
    として合流させる(ただし行が揃って消えるときだけ置ける: must_clear)。はちみつ砲の2巡目でミノ順 O L S J T Z I・HOLD=Jの
    とき、Tは図に無く、HOLDのJもZの後でないと置けないためTを消費する手が
    なく、手順が組めずに提示を放棄していた。実際にはTが来た時点でTSTを
    打ち、消えた後にZ・I・Jを置いてパフェまで組めていた。合流させると
    O L S J T(spin) Z I J(H) の手順が見つかる。消去後の残り手順の座標は
    実行側(_check_opener_progress)が下へずらす。
    """
    result: list[OpenerForm] = []
    spin_only = [f for f in forms if f.is_spin_only()]
    for form in forms:
        if form.is_spin_only():
            result.append(form)
            continue
        if any(item.spin for item in form.items):
            result.append(_with_required(form, form.spin_rows()))
            continue
        # 同じセクションの、この図の続きにあたるTスピン図(既存ブロックが
        # この図の完成形に含まれるもの)を探す。
        completed = set(form.existing) | {cell for item in form.items for cell in item.cells}
        partner = next(
            (u for u in spin_only if u.section == form.section and u.existing <= completed), None
        )
        if partner is None:
            result.append(form)
            continue
        merged = OpenerForm(
            form.section,
            form.existing,
            form.items + tuple(FormItem(it.piece, it.cells, spin=True, last=False, must_clear=True) for it in partner.items),
            form.text,
            form.tuck_pieces,
        )
        result.append(_with_required(merged, partner.spin_rows()))
    return result


def _build_templates(sources=OPENER_SOURCE_FORMS) -> tuple[OpenerTemplate, ...]:
    templates = []
    for name_ja, name_en, url, source_forms in sources:
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
        templates.append(OpenerTemplate(name_ja, name_en, url, tuple(_mark_required_items(forms))))
    return tuple(templates)


OPENER_TEMPLATES: tuple[OpenerTemplate, ...] = _build_templates()
# 教育モードだけで使うテンプレ(開幕パフェ積み・DPC)。画像認識側の選択には使わない。
EDUCATION_TEMPLATES: tuple[OpenerTemplate, ...] = _build_templates(EDUCATION_SOURCE_FORMS)


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


def _srs_reachable(placed: set[tuple[int, int]], piece: str, cells: Cells, spin_entry: bool) -> bool:
    from src.engine.srs_reach import reachable20  # 循環importを避けるため遅延import

    return reachable20(frozenset(placed), piece, tuple(cells), spin_entry)


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
        # まずハードドロップだけで組める順番を探し、無ければSRSで実際に入れられる
        # 回転入れ(張り出しの下へ差し込む等)を全ミノに許して探し直す。
        # 【2026-09-23・教育モード】以前は回転入れをページに明記のあるミノ
        # (form.tuck_pieces)だけに限っていた(入れられるか判定できなかったため)。
        # そのため「Jの下へSを回転入れ」前提でしか組めないミノ順(はちみつ砲の
        # 2巡目 J L T I S Z O・HOLD=L)で図が見つからずAIに切り替わっていた。
        # 入れられない位置(2026-09-12の不具合)はSRSの到達判定で防ぐ。
        strict = plan_form(form, sequence, hold, placed, allow_tuck=False)
        if strict is None:
            strict = plan_form(form, sequence, hold, placed, allow_tuck=True)
        if strict is not None or form.required is None:
            return strict
        # 図どおりに全部は置けない。Tスピンに必要なミノだけの図で探し直す
        # (パフェは諦めて砲の形までは組む)。
        reduced = OpenerForm(
            form.section,
            form.existing,
            tuple(item for i, item in enumerate(form.items) if i in form.required),
            form.text,
            form.tuck_pieces,
        )
        return plan_form(reduced, sequence, hold, placed)

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
        if item.must_clear:
            # 【2026-09-23・教育モードの実画面】合流させたTSTのTを、形ができる前
            # (2巡目の最初)に穴へ置く手を推奨していた。Tスピンにならず教育用として
            # 誤り。Tスピンで消す行がすべて揃うときだけ置ける。TSTを打てる順が
            # 無いミノ順(例: T J Z O L I・HOLD=J)では図は組めない扱い(Noneで
            # テンプレを終え、AIの推奨手へ)。
            after = current_placed | set(item.cells)
            rows = {r for r, _c in item.cells}
            if not all((r, c) in after for r in rows for c in range(BOARD_COLS)):
                return False
        if item.spin:
            # 図の時点で張り出しの下にあるミノ(TSD等)。【2026-09-23】以前は
            # 「マスが空いていて支えがある」だけで置ける扱いにしていたため、屋根が
            # 早すぎて入らない・屋根が無くてTスピンにならない順番の手を推奨して
            # いた。通常SRSで出現位置から実際に入れられるか(Tは最後の操作が回転
            # で収まるか=Tスピンになるか)を確かめる(src.engine.srs_reach)。
            return _can_rest(current_placed, item.cells) and _srs_reachable(
                current_placed, item.piece, item.cells, item.piece == "T"
            )
        if _can_hard_drop(current_placed, item.cells):
            return True
        return (
            allow_tuck
            and _can_rest(current_placed, item.cells)
            and _srs_reachable(current_placed, item.piece, item.cells, False)
        )

    def candidates(piece: str, current_placed: set[tuple[int, int]], done: frozenset[int]) -> list[int]:
        return [
            i
            for i, item in enumerate(items)
            if i not in done and item.piece == piece and placeable(item, current_placed, done)
        ]

    # 【2026-09-23・利用者の指示】組める手順が複数あるときは、回転入れ(ハード
    # ドロップでは入らずソフトドロップが要る置き方)の少ない手順を優先する(操作
    # ミスしにくい)。以前は最初に見つかった手順を採用していたため、ハードドロップ
    # で置ける位置があるのに回転入れの位置を推奨することがあった。Tスピンの手は
    # 避けられないので数えない。同じ回数なら従来どおり操作中のミノを先に試す順。
    # 状態(何番目のミノか・HOLD・置いた図のミノ)ごとに結果を覚えて探索を抑える。
    memo: dict[tuple, tuple[int, list[OpenerStep]] | None] = {}

    def tuck_cost(item: FormItem, current_placed: set[tuple[int, int]]) -> int:
        return 0 if item.spin or _can_hard_drop(current_placed, item.cells) else 1

    def search(index: int, hold_piece: str | None, current_placed: set[tuple[int, int]], done: frozenset[int]):
        if len(done) == len(items):
            return 0, []
        if index >= len(sequence):
            return None
        key = (index, hold_piece, done)
        if key in memo:
            return memo[key]
        current = sequence[index]
        best: tuple[int, list[OpenerStep]] | None = None

        def consider(i: int, piece: str, use_hold: bool, next_index: int, next_hold: str | None) -> None:
            nonlocal best
            item = items[i]
            rest = search(next_index, next_hold, current_placed | set(item.cells), done | {i})
            if rest is None:
                return
            cost = rest[0] + tuck_cost(item, current_placed)
            if best is None or cost < best[0]:
                best = (cost, [OpenerStep(piece, item.cells, use_hold, item.spin)] + rest[1])

        # 1) 操作中のミノをそのまま置く
        for i in candidates(current, current_placed, done):
            consider(i, current, False, index + 1, hold_piece)
            if best is not None and best[0] == 0:
                break
        # 2) ホールドして、出てきたミノを置く
        if best is None or best[0] > 0:
            if hold_piece is None:
                if index + 1 < len(sequence):
                    nxt = sequence[index + 1]
                    for i in candidates(nxt, current_placed, done):
                        consider(i, nxt, True, index + 2, current)
                        if best is not None and best[0] == 0:
                            break
            else:
                for i in candidates(hold_piece, current_placed, done):
                    consider(i, hold_piece, True, index + 1, current)
                    if best is not None and best[0] == 0:
                        break
        memo[key] = best
        return best

    found = search(0, hold, placed_cells, frozenset())
    return None if found is None else found[1]


def known_sequence(
    current_piece: str | None,
    next_queue: tuple[str, ...],
    hold_piece: str | None = None,
    bag_position: int | None = None,
) -> list[str] | None:
    """操作ミノ+NEXT5枠から、分かる範囲のミノ順を返す。

    bag_position: 「最後にNEXTから配られたミノ」(直前にHOLDしていなければ
    操作ミノ、HOLDした直後ならHOLD欄のミノ)の、対局開始からの通し番号。
    Noneなら袋(7-bag)の位置が不明。

    7個目は、袋の位置が分かっていて(bag_positionが7の倍数=そのミノが
    袋の先頭)、その袋の6個が判明しているときだけ確定する。以前は
    「6種類がすべて異なれば同じ袋」とみなして補っていたが、この推論は
    成立しない。例: 前袋 T S Z J L I O / 次袋 T S Z J I L O で、前袋末尾の
    Iを操作中・NEXTが次袋先頭のO T S Z Jだと6種類はすべて異なるが、
    7個目は不足しているLではなく次袋のI。袋の境目をまたいだ観測に
    誤った7個目を渡すと、組めない図を提示してしまう。
    """
    if current_piece is None or len(next_queue) != 5:
        return None
    seen = [current_piece, *next_queue]
    if not set(seen) <= set(_ALL_PIECES):
        return None
    if bag_position is None or bag_position % 7 != 0 or len(set(next_queue)) != 5:
        return seen
    # 袋の先頭のミノは、操作ミノかHOLD欄のどちらか(HOLDした直後なら後者)。
    # NEXT5個と同じ袋なので種類が重ならないはず。どちらか一方に絞れた
    # ときだけ、袋の残り1種類を7個目として確定する。
    heads = {p for p in (current_piece, hold_piece) if p is not None and p not in next_queue}
    if len(heads) != 1:
        return seen
    (missing,) = set(_ALL_PIECES) - heads - set(next_queue)
    return [*seen, missing]


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
    # 【2026-09-23・利用者の指示】同じ優先度(置くミノの数)の図が複数組めるときは、
    # 回転入れ(ソフトドロップが要る置き方)の少ない図を選ぶ。以前は最初に組めた図を
    # 採用していたため、ハードドロップで置ける別の図があるのに回転入れの多い図を
    # 推奨していた。回転入れの数が同じなら従来どおり並び順が先の図。
    best: tuple[int, int, OpenerForm, list[OpenerStep]] | None = None
    for form in sorted(template.forms, key=lambda f: -len(f.items)):
        if best is not None and len(form.items) < best[1]:
            break
        if form.is_spin_only():
            # Tスピンだけの図: 消える行の既存ブロックが揃い、スロットが空いて
            # いれば打てる(上に積むミノが図と違っていても構わない)。
            rows = form.spin_rows()
            needed = {cell for cell in form.existing if cell[0] in rows}
            slot = {cell for item in form.items for cell in item.cells}
            if not needed <= target or slot & target:
                continue
        elif not form.existing <= target or len(target - form.existing) >= 4:
            continue
        steps = plan_form(form, sequence, hold)
        if steps is not None:
            cost = tuck_count(form.existing, steps)
            if best is None or cost < best[0]:
                best = (cost, len(form.items), form, steps)
            if cost == 0:
                break
    return None if best is None else (best[2], best[3])


def tuck_count(existing: frozenset[tuple[int, int]] | set[tuple[int, int]], steps: list[OpenerStep]) -> int:
    """手順のうち、ハードドロップでは入らずソフトドロップ(回転入れ)が要る手の数。

    Tスピンの手は避けられないので数えない。ライン消去は考えない(図の座標のまま)。
    """
    placed = set(existing)
    count = 0
    for step in steps:
        if not step.spin and not _can_hard_drop(placed, step.cells):
            count += 1
        placed |= set(step.cells)
    return count


def choose_opener(
    sequence: list[str], hold: str | None = None, board_cells: set[tuple[int, int]] | None = None
) -> tuple[OpenerTemplate, OpenerForm, list[OpenerStep]] | None:
    """組めるテンプレを探し、最初に見つかったものと図・手順を返す(既定は空の盤面)。"""
    cells = board_cells if board_cells is not None else set()
    # 【2026-09-23・利用者の指示】1巡目はソフトドロップ(回転入れ)を極力避ける。
    # ハードドロップだけで組めるテンプレがあればそれを選び(並び順が先のもの)、
    # どれも回転入れが要る場合だけ、回転入れの最も少ないテンプレを選ぶ。
    best: tuple[int, OpenerTemplate, OpenerForm, list[OpenerStep]] | None = None
    for template in OPENER_TEMPLATES:
        chosen = choose_form(template, cells, sequence, hold)
        if chosen is None:
            continue
        form, steps = chosen
        cost = tuck_count(form.existing, steps)
        if best is None or cost < best[0]:
            best = (cost, template, form, steps)
        if cost == 0:
            break
    return None if best is None else (best[1], best[2], best[3])


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
