"""継続パフェ(パフェの後に続けて取るパフェ)の成功率。

【2026-09-28・利用者の要望】開幕パフェ以降、連続でパフェを取れるかは運の要素があるが、
取れる可能性が高い置き方がある。5連続までを視野に、見えているミノだけでは取り切れない
パフェについて、置き方ごとの成功率を出して一番高い置き方を案内する。

計算はRust製の pc-odds.exe(native/pc-odds/)で行う。
【2026-09-29】Pythonで書いた版は並び1通りに38秒かかり実用にならなかった。Javaの
solution-finderは配布物に同梱しない方針(利用者の判断)のため、Rustで作り直した。

- 見えているミノ(操作ミノ・HOLD・NEXT)の後に来うる並びを、7種1巡の規則で
  「今の袋の残り(順不同)→次の袋(順不同)」と全部作る。
- 並びごとに「全部知っていればパフェを組めるか」を調べ、最初の1手ごとに成功した並びの
  割合を数える(solution-finderのpercentと同じ考え方。実際には見えないミノの前に置く手も
  決めるので、成功率は上限の目安)。
- 候補が多いときは勝ち抜き方式(少ない並びで試し、上位半分を残して並びを倍に)で選ぶ。
  時間の上限を超えたら、そこまでに数え切った並びでの割合を返す。
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from src.education.pc_search import PCStep
from src.paths import app_root, is_frozen

# cargo build --release(native/pc-odds)で生成される実行ファイル。
# 実行ファイル形式(TBA.exe)では、同じフォルダに置いた pc-odds.exe を使う。
PC_ODDS_EXE = (
    app_root() / "pc-odds.exe"
    if is_frozen()
    else app_root() / "native" / "pc-odds" / "target" / "release" / "pc-odds.exe"
)

MAX_UNKNOWN = 5  # 見えない部分は5個まで(HOLDが空のパフェ直後は5個要る)
_WINDOW_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # 黒い窓を出さない


@dataclass(frozen=True)
class OddsMove:
    piece: str
    cells: tuple[tuple[int, int], ...]  # 22行座標
    use_hold: bool
    success: int  # パフェを組めた並びの数
    total: int  # 調べた並びの数
    height: int  # パフェの段数
    pieces: int  # パフェまでに置くミノの数
    # 【2026-09-29・利用者の指示】見えているミノで決まる手順(先頭が今の1手、各手は前の手までの
    # 消去後の座標)。組み方が複数あるときはソフトドロップの少ないもの。ガイドに示し、従っている
    # 間は計算し直さない(先まで決めると成功率が下がるときは、下がらない手数まで)
    plan: tuple[PCStep, ...] = ()

    @property
    def rate(self) -> float:
        return self.success / self.total if self.total else 0.0


def available(exe: Path | None = None) -> bool:
    return (exe or PC_ODDS_EXE).exists()


def request_text(board, sequence, hold, bag_pool, can_hold: bool, time_limit: float, max_unknown: int) -> str:
    """pc-odds.exe に渡す入力(1行ずつ。native/pc-odds/src/main.rs の先頭の説明参照)。"""
    cells = ";".join(f"{r},{c}" for r, c in sorted(board))
    return "\n".join(
        [
            cells,
            "".join(sequence),
            hold or "-",
            "".join(sorted(bag_pool)) or "-",
            "1" if can_hold else "0",
            str(max(int(time_limit * 1000), 1)),
            str(max_unknown),
        ]
    ) + "\n"


def _cells(text: str) -> tuple[tuple[int, int], ...]:
    return tuple(sorted(tuple(int(v) for v in cell.split(",")) for cell in text.split(";")))  # type: ignore[misc]


def parse_result(text: str) -> OddsMove | None:
    """pc-odds.exe の出力("ok ..." の行と、続く "plan k" とk行の手順)。"""
    lines = text.strip().splitlines()
    parts = lines[0].split() if lines else []
    if len(parts) != 8 or parts[0] != "ok":
        return None
    plan: list[PCStep] = []
    if len(lines) > 1 and lines[1].startswith("plan "):
        for line in lines[2 : 2 + int(lines[1].split()[1])]:
            piece, hold, _soft, cells = line.split()
            plan.append(PCStep(piece, _cells(cells), hold == "1"))
    return OddsMove(
        piece=parts[1],
        cells=_cells(parts[7]),
        use_hold=parts[2] == "1",
        success=int(parts[3]),
        total=int(parts[4]),
        height=int(parts[5]),
        pieces=int(parts[6]),
        plan=tuple(plan),
    )


def best_odds_move(
    board,
    sequence: list[str],
    hold: str | None,
    bag_pool,
    *,
    can_hold: bool = True,
    time_limit: float = 2.0,
    max_unknown: int = MAX_UNKNOWN,
    cancel: threading.Event | None = None,
    exe: Path | None = None,
    threads: int | None = None,
) -> OddsMove | None:
    """成功率が一番高い最初の1手(OddsMove)。狙えるパフェが無い・計算できないときはNone。

    board: 22行座標の占有マス。sequence: 先頭が操作ミノの、見えているミノ順。hold: 今のHOLD。
    bag_pool: sequenceの最後のミノの後に、今の袋から出る残りのミノの種類(空なら次は新しい袋)。
    can_hold: この手番でまだHOLDできるか。
    cancel: 別スレッドで計算するときの打ち切りの合図。立ったら計算を止めてNoneを返す。
    threads: 計算に使うスレッド数の上限(Noneなら最大16)。支援モードでは画像認識と取り合わないよう減らす。
    """
    exe = exe or PC_ODDS_EXE
    if not sequence or not exe.exists():
        return None
    text = request_text(board, sequence, hold, bag_pool, can_hold, time_limit, max_unknown)
    try:
        proc = subprocess.Popen(
            [str(exe)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            creationflags=_WINDOW_FLAGS,
            env=None if threads is None else {**os.environ, "PC_ODDS_THREADS": str(threads)},
        )
    except OSError:
        return None
    out: list[str] = []
    reader = threading.Thread(target=lambda: out.append(proc.communicate(text)[0]), daemon=True)
    reader.start()
    give_up = time.monotonic() + time_limit + 5.0  # 応答しなくなったときの保険
    while reader.is_alive():
        reader.join(0.02)
        if (cancel is not None and cancel.is_set()) or time.monotonic() > give_up:
            proc.kill()
            reader.join(1.0)
            return None
    if not out:
        return None
    return parse_result(out[0])
