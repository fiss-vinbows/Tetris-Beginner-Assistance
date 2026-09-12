"""TBA.exe をビルドして dist/TBA/ に配布物一式を揃える。

使い方: ./venv/Scripts/python.exe tools/build_exe.py
前提: venv に pyinstaller が入っていること、Cold Clear 2 がビルド済みであること。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "TBA"


def main() -> None:
    pyinstaller = ROOT / "venv" / "Scripts" / "pyinstaller.exe"
    subprocess.run([str(pyinstaller), "--noconfirm", "--clean", str(ROOT / "TBA.spec")], check=True, cwd=ROOT)

    # 利用者が触るファイル(exeと同じフォルダに置く。src/paths.py の app_root() 参照)
    cold_clear = ROOT / "external" / "cold-clear-2" / "target" / "release" / "cold-clear-2.exe"
    if not cold_clear.exists():
        sys.exit(f"Cold Clear 2 がビルドされていません: {cold_clear}")
    shutil.copy2(cold_clear, DIST / "cold-clear-2.exe")
    (DIST / "config").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "config" / "cold_clear_beginner.json", DIST / "config" / "cold_clear_beginner.json")
    calibration = ROOT / "config" / "calibration.json"
    if calibration.exists():
        shutil.copy2(calibration, DIST / "config" / "calibration.json")
    shutil.copy2(ROOT / "README.md", DIST / "README.md")
    print(f"配布物: {DIST}")


if __name__ == "__main__":
    main()
