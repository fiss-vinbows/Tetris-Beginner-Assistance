"""テトリス堂の「開幕中開け4列REN」のページから図を抜き出し、src/engine/opener_data_ren.py を作る。

【2026-10-03・利用者の要望】種3(中央4列の底に置く3マスのタネ)の中あけRENを積む練習をシミュレーターでする。

使い方: ./venv/Scripts/python.exe tools/import_ren_template.py
- ページの図は「基本系」(1巡目の組み方3通り)と「その後の積み方」(レベル1: 積み増し、レベル2: タネの後入れ)。
- 中央4列(空けておく井戸)の'B'は空きとして読む。積み増しの図の大文字(前に置いたミノ)は既存ブロックとして読む。
- 読めない記号を含む図・同じ図は収録しない。
"""

from __future__ import annotations

import html
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.engine.openers import parse_form  # noqa: E402

URL = "https://shiwehi.com/tetris/template/center4wideopener.php"
OUT = ROOT / "src" / "engine" / "opener_data_ren.py"
NAME_JA = "中開け4列REN(種3)"
NAME_EN = "Center 4-Wide REN Opener"


def figures(page: str) -> list[tuple[str, str]]:
    """(見出し, 図)。「基本系」から「練習用ゲーム」の手前まで。"""
    body = page[page.find("基本系") : page.find("練習用ゲーム")]
    h2 = h3 = ""
    out = []
    for m in re.finditer(r'<h([23])[^>]*>(.*?)</h\1>|<div class="ttt">\s*(.*?)</div>', body, re.S):
        title = html.unescape(re.sub(r"<[^>]+>", "", m.group(2) or "")).strip()
        if m.group(1) == "2":
            h2, h3 = title, ""
        elif m.group(1) == "3":
            h3 = title
        else:
            lines = [line.strip() for line in m.group(3).strip().splitlines() if line.strip()]
            out.append((f"{h2} > {h3}" if h3 else (h2 or "基本系"), "\n".join(lines)))
    return out


def convert(text: str) -> str:
    """井戸の'B'は空き、前に置いたミノ(大文字)は既存ブロック。"""
    return "\n".join(
        "".join("-" if ch == "B" else ("c" if ch.isupper() and ch not in "UC" else ch) for ch in line)
        for line in text.splitlines()
    )


def section_name(heading: str, form) -> str:
    level = heading.split(" > ")[-1].split("：")[0] if "レベル" in heading else "基本系"
    if not form.existing:
        return f"{level} > 1巡目"
    bags = len(form.existing) // 28 + 1  # 1巡目は7個(28マス)
    return f"{level} > {bags}巡目"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    request = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    page = urllib.request.urlopen(request, timeout=30).read().decode("utf-8")
    kept: list[tuple[str, str]] = []
    seen: set[str] = set()
    for heading, text in figures(page):
        text = convert(text)
        form = parse_form(text)
        if form is None or text in seen:
            continue
        seen.add(text)
        kept.append((section_name(heading, form), text))
    lines = [f"            ({section!r}, \"\\n\".join({tuple(text.splitlines())!r}))," for section, text in kept]
    OUT.write_text(
        '"""開幕中開け4列REN(種3)の図。tools/import_ren_template.py で生成(手で編集しない)。\n\n'
        "【2026-10-03・利用者の要望】種3の中あけRENを積む練習をシミュレーターでする。出典はテトリス堂。\n"
        "記号は opener_data.py と同じ(井戸の'B'は空き、前に置いたミノは既存ブロック'c'に読み替え済み)。\n"
        '"""\n\n'
        "REN_SOURCE_FORMS = (\n"
        f"    (\n        {NAME_JA!r},\n        {NAME_EN!r},\n        {URL!r},\n        (\n"
        + "\n".join(lines)
        + "\n        ),\n    ),\n)\n",
        encoding="utf-8",
        newline="\r\n",
    )
    print(f"{len(kept)}図を書き出し: {OUT}")
    for section, _text in kept:
        print(" ", section)


if __name__ == "__main__":
    main()
