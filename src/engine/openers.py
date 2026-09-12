"""開幕テンプレ(1巡目)の定義と、実際のミノ順に合わせた手順の組み立て。

テンプレの形は「テトリス堂(https://shiwehi.com/tetris/)」の各ページに
テキストで掲載されている1巡目の盤面図をそのまま写したもの(小文字の
ミノ記号、'-'は空マス、下の行ほど盤面の下)。左右反転の形もページの
掲載どおり別の図として持つ。

【手順は事前に書かず、その場で組み立てる】
テンプレの解説は「Iが早いこと」「JとLの早い方で左右を決める」のように
ミノ順の条件と分岐で説明されるが、1巡目に限れば「最終形の各ミノの位置」が
分かれば、実際に出てきた順番に対して
  ・今のミノをテンプレの位置へ置けるか(下に支えがあり、上が空いていて
    ハードドロップで入る)
  ・置けなければホールドして、ホールドしていたミノを置けるか
を全探索すれば手順が決まる(7手なので探索は一瞬)。これなら分岐の
手順データを手入力する必要がなく、写し間違いの余地も減る。
どの順でも置けない場合、そのテンプレはその手番順では組めない。
"""

from __future__ import annotations

from dataclasses import dataclass

BOARD_ROWS = 20
BOARD_COLS = 10

Cells = tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class OpenerTemplate:
    name_ja: str
    name_en: str
    # 1巡目の最終形(複数あれば左右反転などの別形)。各要素はテキスト盤面図。
    forms: tuple[str, ...]


# テトリス堂の各ページ「1巡目とミノ順」より。
OPENER_TEMPLATES: tuple[OpenerTemplate, ...] = (
    OpenerTemplate(
        name_ja="はちみつ砲",
        name_en="Honey Cup",
        forms=(
            "----------\n"
            "-ss-------\n"
            "ssl----t--\n"
            "lll-zzttoo\n"
            "iiii-zztoo",
            "----------\n"
            "-------zz-\n"
            "--t----jzz\n"
            "oottss-jjj\n"
            "ootss-iiii",
        ),
    ),
    OpenerTemplate(
        name_ja="迷走砲",
        name_en="Stray Cannon",
        forms=(
            "i---------\n"
            "ils-t--j--\n"
            "ilsstt-joo\n"
            "illst-jjoo",
        ),
    ),
    OpenerTemplate(
        name_ja="山岳積み2号",
        name_en="Mountainous Stacking 2",
        forms=(
            "------l---\n"
            "------l---\n"
            "is----ll--\n"
            "iss----t--\n"
            "ijs-zzttoo\n"
            "ijjj-zztoo",
            "---j------\n"
            "---j------\n"
            "--jj----zi\n"
            "--t----zzi\n"
            "oottss-zli\n"
            "ootss-llli",
        ),
    ),
    OpenerTemplate(
        name_ja="オリーブ積み",
        name_en="Olive Stacking",
        forms=(
            "--z-------\n"
            "-zz------j\n"
            "-zl--t-ssj\n"
            "ool-ttssjj\n"
            "ooll-tiiii",
            "-------s--\n"
            "l------ss-\n"
            "lzz-t--js-\n"
            "llzztt-joo\n"
            "iiiit-jjoo",
        ),
    ),
)


def parse_form(form: str) -> dict[str, Cells]:
    """テキスト盤面図を {ミノ種: 着地マス(row, col)} に変換する。最下行がrow=19。"""
    lines = [line for line in form.splitlines() if line]
    cells: dict[str, list[tuple[int, int]]] = {}
    for i, line in enumerate(lines):
        row = BOARD_ROWS - len(lines) + i
        for col, ch in enumerate(line):
            if ch == "-":
                continue
            cells.setdefault(ch.upper(), []).append((row, col))
    result: dict[str, Cells] = {}
    for piece, cs in cells.items():
        if len(cs) != 4:
            raise ValueError(f"テンプレ図の{piece}が4マスではない: {cs}")
        result[piece] = tuple(sorted(cs))
    return result


@dataclass(frozen=True)
class OpenerStep:
    piece: str
    cells: Cells
    use_hold: bool  # ホールドしてから置く(置くミノは操作中のミノではない)


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


def plan_opener(form_cells: dict[str, Cells], sequence: list[str]) -> list[OpenerStep] | None:
    """実際のミノ順(先頭が操作中のミノ)に対して、テンプレを組む手順を返す。

    各手番で「操作中のミノを置く」か「ホールドして、ホールドにあったミノ
    (空なら次のミノ)を置く」のどちらかを選ぶ。ホールドの入れ替えは各手番
    1回まで。全7手を置ける手順が無ければNone。
    """
    # 形に含まれないミノ(はちみつ砲のJなど)は、1巡目の間ホールドに残す
    # 想定。形のミノがすべてミノ順に含まれていれば組める可能性がある。
    if len(sequence) != 7 or len(set(sequence)) != 7 or not set(form_cells) <= set(sequence):
        return None

    def search(index: int, hold: str | None, placed: set[tuple[int, int]], done: set[str]) -> list[OpenerStep] | None:
        if len(done) == len(form_cells):
            return []
        if index >= len(sequence):
            return None
        current = sequence[index]
        # 1) 操作中のミノをそのまま置く(形に含まれないミノはホールドへ回すしかない)
        if current in form_cells and current not in done and _can_hard_drop(placed, form_cells[current]):
            rest = search(index + 1, hold, placed | set(form_cells[current]), done | {current})
            if rest is not None:
                return [OpenerStep(current, form_cells[current], use_hold=False)] + rest
        # 2) ホールドして、出てきたミノを置く
        if hold is None:
            # 空のHOLDへ格納: 操作ミノがHOLDへ入り、次のミノが操作対象になる
            if index + 1 < len(sequence):
                nxt = sequence[index + 1]
                if nxt in form_cells and nxt not in done and _can_hard_drop(placed, form_cells[nxt]):
                    rest = search(index + 2, current, placed | set(form_cells[nxt]), done | {nxt})
                    if rest is not None:
                        return [OpenerStep(nxt, form_cells[nxt], use_hold=True)] + rest
        else:
            if hold in form_cells and hold not in done and _can_hard_drop(placed, form_cells[hold]):
                rest = search(index + 1, current, placed | set(form_cells[hold]), done | {hold})
                if rest is not None:
                    return [OpenerStep(hold, form_cells[hold], use_hold=True)] + rest
        return None

    return search(0, None, set(), set())


def choose_opener(sequence: list[str]) -> tuple[OpenerTemplate, list[OpenerStep]] | None:
    """1巡目のミノ順に対して組めるテンプレを探し、最初に見つかったものと手順を返す。"""
    for template in OPENER_TEMPLATES:
        for form in template.forms:
            steps = plan_opener(parse_form(form), sequence)
            if steps is not None:
                return template, steps
    return None
