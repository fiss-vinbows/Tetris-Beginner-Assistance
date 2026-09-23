"""はちみつ砲 → 3巡目パフェの成立パターンをSQLiteにまとめる(試作)。

1. start_states.collect で「2巡目+TST後」の開始状態を集める
   (盤面・HOLD・今の袋から既に出たミノ)。
2. 各開始状態について、この後に来うるミノ順をsolution-finderのパターン記法で
   作り(HOLD, 今の袋の残りの順列, 必要なら次の袋の先頭)、sfinder path で
   ミノ順ごとのパフェ解を求める。
3. start_state / sequence_result の2表に保存する。

【注意】sfinderの成否は「使うミノ順を全部知っていれば組める」という意味。
練習中の推奨手が見られるのはNEXT5までなので、NEXT5の時点で成立を判断できる
かは別の計算(未実装)。回転はSRS(ソフトドロップ・回転入れ込み)。

使い方: venv\\Scripts\\python.exe tools\\pc_db\\build_db.py [サンプル配列数]
"""

from __future__ import annotations

import csv
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SFINDER_DIR = ROOT / "tools" / "sfinder"
DB_PATH = HERE / "honey_pc.sqlite"
sys.path.insert(0, str(HERE))

from start_states import board_text, collect  # noqa: E402

PIECES = "IOTSZJL"


def pc_lines_and_pieces(board: frozenset[tuple[int, int]]) -> tuple[int, int]:
    """全消しに必要なライン数と置くミノ数(盤面の高さ以上で、マス数が4の倍数になる最小)。"""
    height = 20 - min((r for r, _c in board), default=20)
    lines = max(height, 1)
    while (10 * lines - len(board)) % 4 != 0:
        lines += 1
    return lines, (10 * lines - len(board)) // 4


def pattern_for(hold: str | None, drawn: frozenset[str], pieces: int) -> str:
    """HOLD → 今の袋の残り(順列) → 次の袋の先頭、のsfinderパターン。"""
    remaining = "".join(p for p in PIECES if p not in drawn)
    parts = [hold] if hold else []
    take = min(len(remaining), pieces + (0 if hold else 1))
    parts.append(f"[{remaining}]p{take}")
    rest = pieces + (0 if hold else 1) - take
    if rest > 0:
        parts.append(f"*p{rest}")
    return ",".join(parts)


def field_file(board: frozenset[tuple[int, int]], lines: int) -> Path:
    path = SFINDER_DIR / "input" / "pc_db_field.txt"
    rows = ["".join("X" if (r, c) in board else "_" for c in range(10)) for r in range(20 - lines, 20)]
    path.write_text(f"{lines}\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def run_sfinder(board, lines: int, pattern: str) -> list[dict]:
    field = field_file(board, lines)
    out = SFINDER_DIR / "output" / "path.csv"
    out.unlink(missing_ok=True)
    subprocess.run(
        ["java", "-jar", "sfinder.jar", "path", "-fp", str(field), "-p", pattern, "-c", str(lines), "-f", "csv", "-k", "pattern"],
        cwd=SFINDER_DIR,
        check=True,
        capture_output=True,
    )
    with open(out, encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)  # 見出し(ツモ,対応地形数,使用ミノ,未使用ミノ,テト譜)
        return [
            {"sequence": r[0], "solutions": int(r[1]), "used": r[2], "unused": r[3], "fumens": r[4]}
            for r in reader
        ]


SCHEMA = """
CREATE TABLE start_state (
    id INTEGER PRIMARY KEY,
    template TEXT NOT NULL,
    board TEXT NOT NULL,          -- 下から見た行を'X'/'_'で(上の行が先)
    hold TEXT,
    drawn_in_bag TEXT NOT NULL,   -- 今の袋から既に出たミノ
    bag_position INTEGER NOT NULL,
    reduced INTEGER NOT NULL,     -- 途中で砲のみに縮小したか
    sample_count INTEGER NOT NULL,-- 試作の抽出で何回現れたか(出やすさの目安)
    pc_lines INTEGER NOT NULL,
    pc_pieces INTEGER NOT NULL,
    pattern TEXT NOT NULL,        -- sfinderに渡したミノ順パターン
    success INTEGER NOT NULL,
    total INTEGER NOT NULL
);
CREATE TABLE sequence_result (
    state_id INTEGER NOT NULL REFERENCES start_state(id),
    sequence TEXT NOT NULL,       -- HOLDを先頭にしたミノ順
    solutions INTEGER NOT NULL,   -- 0ならパフェ不可(全配列既知の条件で)
    used TEXT,
    unused TEXT,
    fumens TEXT,                  -- 解のテト譜(';'区切り)
    PRIMARY KEY (state_id, sequence)
);
"""


def main(samples: int) -> None:
    started = time.monotonic()
    found = collect(samples)
    groups: Counter = Counter()
    reduced_of: dict = {}
    skipped: Counter = Counter()
    for state, count in found.items():
        if state is None:
            continue
        # 対象は「2巡目を図どおりに組み、TSTを打った後」だけ。砲のみに縮小した
        # 盤面と、TSTを打つ前で図が終わっている盤面(高さ5以上)は3巡目パフェの
        # 前提が違うので除外する(件数だけ報告する)。
        if state.reduced:
            skipped["砲のみに縮小"] += count
            continue
        if 20 - min(r for r, _c in state.board) > 4:
            skipped["TST前で図が終わる"] += count
            continue
        key = (state.board, state.hold, state.drawn_in_bag, state.next_index % 7)
        groups[key] += count
        reduced_of[key] = reduced_of.get(key, False) or state.reduced
    print(f"抽出: {samples}配列 → 完走 {samples - found[None]}、対象外 {dict(skipped)}、開始状態 {len(groups)} 種類")

    DB_PATH.unlink(missing_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    for n, ((board, hold, drawn, pos), count) in enumerate(groups.most_common(), 1):
        lines, pieces = pc_lines_and_pieces(board)
        pattern = pattern_for(hold, drawn, pieces)
        rows = run_sfinder(board, lines, pattern)
        success = sum(1 for r in rows if r["solutions"] > 0)
        cur = db.execute(
            "INSERT INTO start_state (template, board, hold, drawn_in_bag, bag_position, reduced, sample_count,"
            " pc_lines, pc_pieces, pattern, success, total) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("はちみつ砲", board_text(board), hold, "".join(sorted(drawn)), pos, int(reduced_of[(board, hold, drawn, pos)]),
             count, lines, pieces, pattern, success, len(rows)),
        )
        db.executemany(
            "INSERT OR REPLACE INTO sequence_result VALUES (?,?,?,?,?,?)",
            [(cur.lastrowid, r["sequence"], r["solutions"], r["used"], r["unused"], r["fumens"]) for r in rows],
        )
        print(f"[{n}/{len(groups)}] HOLD={hold} 袋位置={pos} {pattern:<24} 成功 {success}/{len(rows)}")
    db.commit()
    db.close()
    print(f"保存: {DB_PATH}  ({time.monotonic() - started:.0f}秒)")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 20000)
