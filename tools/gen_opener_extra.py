"""DPC・開幕パフェ積みのページ(テトリス堂)から盤面図を取り出し、opener_data用の定義を出力する。

使い方: venv/Scripts/python.exe tools/gen_opener_extra.py > 出力.txt
出力を src/engine/opener_data.py の EDUCATION_SOURCE_FORMS に貼る。
"""
import html
import re
import sys
import urllib.request

sys.path.insert(0, ".")
from src.engine.openers import parse_form  # noqa: E402

DPC_URL = "https://shiwehi.com/tetris/template/dpc.php"
PCO_URL = "https://shiwehi.com/tetris/template/pcopener.php"
TOKEN = re.compile(r'<h4[^>]*>(.*?)</h4>|<div class="(ttt[^"]*)">(.*?)</div>', re.S)


def diagrams(url):
    with urllib.request.urlopen(url) as res:
        text = res.read().decode("utf-8")
    title = ""
    for m in TOKEN.finditer(text):
        if m.group(1) is not None:
            title = html.unescape(re.sub(r"<[^>]*>", "", m.group(1))).strip()
            continue
        lines = [ln.strip() for ln in m.group(3).splitlines() if ln.strip()]
        yield title, m.group(2), lines


def dpc():
    forms = []
    for title, cls, lines in diagrams(DPC_URL):
        if cls not in ("ttt", "ttt small") or not title:
            continue
        name = title.split("：")[0].strip()
        if not re.match(r"[IJOST]-\d", name):
            continue
        section = f"{name} > {'組み方' if cls == 'ttt' else 'パフェ'}"
        forms.append((section, lines))
    return forms


def pc_opener():
    forms, seen = [], set()
    for _title, cls, lines in diagrams(PCO_URL):
        if cls != "ttt" or any("c" in ln.lower() for ln in lines):
            continue
        if any(len(ln) != 10 for ln in lines) or tuple(lines) in seen:
            continue
        seen.add(tuple(lines))
        forms.append(("1巡目", lines))
    return forms


from src.education.rules import _SHAPES  # noqa: E402


def _shapes(piece):
    result = set()
    for cells in _SHAPES[piece]:
        r0 = min(r for r, _ in cells)
        c0 = min(c for r, c in cells if r == r0)
        result.add(frozenset((r - r0, c - c0) for r, c in cells))
    return result


def _partitions(cells, piece):
    """同じ種類のミノが隣接した塊を、ミノの形に分ける全通り。"""
    if not cells:
        return [[]]
    top = min(cells)
    out = []
    for shape in _shapes(piece):
        placed = {(top[0] + r, top[1] + c) for r, c in shape}
        if placed <= cells:
            for rest in _partitions(cells - placed, piece):
                out.append([placed, *rest])
    return out


def split_adjacent(lines):
    """8マス以上の同じ記号の塊を、分け方が1通りなら片方を大文字にして分ける。無理ならNone。"""
    grid = [list(ln) for ln in lines]
    seen = set()
    for r, row in enumerate(grid):
        for c, ch in enumerate(row):
            if ch in "-cCU" or (r, c) in seen or not ch.islower():
                continue
            group, stack = {(r, c)}, [(r, c)]
            while stack:
                y, x = stack.pop()
                for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                    if 0 <= ny < len(grid) and 0 <= nx < 10 and (ny, nx) not in group and grid[ny][nx] == ch:
                        group.add((ny, nx))
                        stack.append((ny, nx))
            seen |= group
            if len(group) == 4:
                continue
            parts = _partitions(group, ch.upper())
            if len(parts) != 1 or len(parts[0]) != 2:
                return None
            upper = ch.upper()
            second = parts[0][1]
            # 大文字の塊と隣接すると再び1つの塊になるので、その場合は諦める
            if any(0 <= y + dy < len(grid) and 0 <= x + dx < 10 and grid[y + dy][x + dx] == upper
                   for y, x in second for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                return None
            for y, x in second:
                grid[y][x] = upper
    return ["".join(row) for row in grid]


def emit(name_ja, name_en, url, forms):
    fixed = []
    for s, ln in forms:
        if parse_form("\n".join(ln), s) is None:
            split = split_adjacent(ln)
            if split is None:
                continue
            ln = split
        fixed.append((s, ln))
    ok = [(s, ln) for s, ln in fixed if parse_form("\n".join(ln), s) is not None]
    print(f"# {name_ja}: {len(ok)}/{len(forms)} 図を採用", file=sys.stderr)
    out = ["    (", f"        {name_ja!r},", f"        {name_en!r},", f"        {url!r},", "        ("]
    for section, lines in ok:
        out.append(f"            ({section!r}, \"\\n\".join({tuple(lines)!r})),")
    out += ["        ),", "    ),"]
    return "\n".join(out)


if __name__ == "__main__":
    print(emit("開幕パフェ積み", "PC Opener", PCO_URL, pc_opener()))
    print(emit("DPC", "DPC", DPC_URL, dpc()))
