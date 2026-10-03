"""テトリス堂のTD系テンプレのページから図を抜き出し、src/engine/opener_data_td.py を作る。

【2026-09-30・利用者の要望】TDTD(袋がずれたままTD系テンプレを組み直す)に向けて、TD系テンプレの
データをできるだけ集める。袋ずれで余った1ミノの組み合わせによって、はちみつ砲・迷走砲・山岳積み2号
以外のTD系が向く場合があるため。

使い方: ./venv/Scripts/python.exe tools/import_td_templates.py
- 図の抜き出しは tools/import_opener_page.py と同じ(見出しを「 > 」でつないだものをセクション名にする)。
  大見出し(h2)で区切られたページ(皐月積み)は h2〜h4 を見出しとして読む。
- 行をまたいでミノが分かれて描かれた図などは、src/engine/openers.parse_form が読めないので収録しない。
- 既存ブロックだけの図(Tスピン後の地形)は収録しない(ガムシロ積みと同じ)。
"""

from __future__ import annotations

import html
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from import_opener_page import extract  # noqa: E402

from src.engine.openers import parse_form  # noqa: E402

BASE = "https://shiwehi.com/tetris/template/"
# テトリス堂のテンプレ一覧「TD系テンプレ(積み→TST→TSD)」のうち、まだ収録していないもの
TEMPLATES = (
    ("ホットケーキ積み", "Pancake Stacking", "pancake.php"),
    ("くろみつ砲", "Kuromitsu Cannon", "kuromitsu.php"),
    ("PC-Spin", "PC-Spin (Okey Version)", "pcspin_ok.php"),
    ("皐月積み", "Satsuki Stacking", "satsuki.php"),
    ("ベーカリーTD", "Bakery TD (Riif Stacking v5)", "bakery.php"),
    ("タンドリーチキン積み", "Tandoori Chicken Stacking (Riif Stacking v3)", "tandoori.php"),
)
OUT = ROOT / "src" / "engine" / "opener_data_td.py"


def extract_h2(page: str) -> list[tuple[str, str]]:
    """大見出し(h2)で区切られたページ用。「1巡目」の見出しから「関連ページ」「参考ページ」の手前まで。"""
    heads = {"2": "", "3": "", "4": ""}
    started = False
    out: list[tuple[str, str]] = []
    for m in re.finditer(r'<h([234])>(.*?)</h\1>|<div class="ttt">\s*(.*?)</div>', page, re.S):
        if m.group(1):
            level, title = m.group(1), html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
            if level == "2" and title in ("関連ページ", "参考ページ"):
                break
            if "1巡目" in title:
                started = True
            heads[level] = title
            for lower in ("3", "4"):
                if lower > level:
                    heads[lower] = ""
            continue
        if not started:
            continue
        lines = [line.strip() for line in m.group(3).strip().splitlines() if line.strip()]
        if lines and all(len(line) == 10 for line in lines):
            section = " > ".join(h for h in (heads["2"], heads["3"], heads["4"]) if h)
            out.append((section, "\n".join(lines)))
    return out


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(request, timeout=30).read().decode("utf-8")


def usable(text: str) -> bool:
    """収録する図か: 読める図で、置くミノがある(既存ブロックだけの図は除く)。"""
    form = parse_form(text)
    return form is not None and bool(form.items)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    blocks = []
    for name_ja, name_en, page in TEMPLATES:
        url = BASE + page
        source = fetch(url)
        forms = extract(source) if "<h3>1巡目" in source else extract_h2(source)
        kept = [(section, text) for section, text in forms if usable(text)]
        print(f"{name_ja}: 図{len(forms)}個のうち{len(kept)}個を収録")
        lines = [f"    (\n        {name_ja!r},\n        {name_en!r},\n        {url!r},\n        ("]
        for section, text in kept:
            rows = tuple(text.splitlines())
            lines.append(f"            ({section!r}, \"\\n\".join({rows!r})),")
        lines.append("        ),\n    ),")
        blocks.append("\n".join(lines))
        time.sleep(1)  # 相手のサーバーに負担をかけない
    OUT.write_text(
        '"""TD系テンプレ(TDTD用)の図。tools/import_td_templates.py で生成(手で編集しない)。\n\n'
        "【2026-09-30・利用者の要望】袋がずれたまま組み直すTDTDに向けて、テトリス堂のTD系テンプレを収録する。\n"
        "記号は opener_data.py と同じ。出典はそれぞれのURL(テトリス堂)。\n"
        '"""\n\n'
        "TD_EXTRA_SOURCE_FORMS = (\n" + "\n".join(blocks) + "\n)\n",
        encoding="utf-8",
        newline="\r\n",
    )
    print(f"書き出し: {OUT}")


if __name__ == "__main__":
    main()
