"""テトリス堂のテンプレのページから、テキストの盤面図を見出し(セクション)ごとに抜き出す。

使い方: ./venv/Scripts/python.exe tools/import_opener_page.py <ページのURL>
出力: 見出しごとの図の一覧(src/engine/opener_data.py に書き写すための下書き)。

ページでは図が <div class="ttt"> の中に10列の文字で書かれている(記号は opener_data.py の説明と同じ)。
セクション名は h3 と h4 の見出しを「 > 」でつないだもの。どの図をどのセクション名で収録するかは
テンプレごとに確かめて決める(例: 2巡目の図とTSTの図は同じセクションに入れないと、TSTを2巡目の
続きとして組み合わせられない。src/engine/openers.py の _mark_required_items 参照)。
"""

from __future__ import annotations

import html
import re
import sys
import urllib.request


def extract(page: str) -> list[tuple[str, str]]:
    """(セクション名, 図) の一覧。ページの記事部分(最初の「1巡目」の見出し以降)だけを見る。"""
    start = page.find("<h3>1巡目")
    if start < 0:
        start = 0
    h3 = h4 = ""
    out: list[tuple[str, str]] = []
    for m in re.finditer(r'<h([34])>(.*?)</h\1>|<div class="ttt">\s*(.*?)</div>|<h2>', page[start:], re.S):
        if m.group(0) == "<h2>":
            break  # 関連ページ・参考ページ
        if m.group(1) == "3":
            h3, h4 = html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip(), ""
        elif m.group(1) == "4":
            h4 = html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
        else:
            lines = [line.strip() for line in m.group(3).strip().splitlines() if line.strip()]
            if lines and all(len(line) == 10 for line in lines):
                out.append((f"{h3} > {h4}" if h4 else h3, "\n".join(lines)))
    return out


def main() -> None:
    url = sys.argv[1]
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    page = urllib.request.urlopen(request, timeout=30).read().decode("utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    for section, text in extract(page):
        print(f"# {section}\n{text}\n")


if __name__ == "__main__":
    main()
