"""TBA.exe をビルドして dist/TBA/ に配布物一式を揃える。

使い方: ./venv/Scripts/python.exe tools/build_exe.py
前提: venv に pyinstaller が入っていること、Cold Clear 2 と pc-odds(native/pc-odds)がビルド済みであること。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "TBA"


def copy_distributable_plugins(source: Path, target: Path) -> list[str]:
    """配布してよいプラグイン(distributable=True)だけを配布物へ写す。写したプラグインのIDを返す。

    【2026-10-30】プラグイン方式(src/plugin_api.py)。全自動モード・ログ出力・非公開のプラグインは配布しない。
    """
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from src.plugin_loader import discover_folders

    if target.exists():
        shutil.rmtree(target)  # 前回の配布物に残った(今は配布しない)プラグインを消す
    found, errors = discover_folders(source)
    if errors:
        sys.exit(f"読み込めないプラグインがあります: {errors}")
    copied = []
    for folder, plugin in found:
        if plugin.distributable:
            shutil.copytree(folder, target / folder.name, ignore=shutil.ignore_patterns("__pycache__"))
            copied.append(plugin.id)
    print(f"配布するプラグイン: {copied or 'なし'}")
    return copied


def main() -> None:
    pyinstaller = ROOT / "venv" / "Scripts" / "pyinstaller.exe"
    subprocess.run([str(pyinstaller), "--noconfirm", "--clean", str(ROOT / "TBA.spec")], check=True, cwd=ROOT)

    # 利用者が触るファイル(exeと同じフォルダに置く。src/paths.py の app_root() 参照)
    cold_clear = ROOT / "external" / "cold-clear-2" / "target" / "release" / "cold-clear-2.exe"
    if not cold_clear.exists():
        sys.exit(f"Cold Clear 2 がビルドされていません: {cold_clear}")
    shutil.copy2(cold_clear, DIST / "cold-clear-2.exe")
    # 継続パフェの成功率の計算(native/pc-odds。src/education/pc_odds.py 参照)
    pc_odds = ROOT / "native" / "pc-odds" / "target" / "release" / "pc-odds.exe"
    if not pc_odds.exists():
        sys.exit(f"pc-odds がビルドされていません(native/pc-odds で cargo build --release): {pc_odds}")
    shutil.copy2(pc_odds, DIST / "pc-odds.exe")
    (DIST / "config").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "config" / "cold_clear_beginner.json", DIST / "config" / "cold_clear_beginner.json")
    calibration = ROOT / "config" / "calibration.json"
    if calibration.exists():
        shutil.copy2(calibration, DIST / "config" / "calibration.json")
    shutil.copy2(ROOT / "README.md", DIST / "README.md")
    shutil.copy2(ROOT / "LICENSE", DIST / "LICENSE")
    copy_distributable_plugins(ROOT / "plugins", DIST / "plugins")

    # cold-clear-2.exe(MIT/Apache-2.0デュアルライセンス)を同梱配布するため、
    # 再配布条件(著作権表示・許諾文の同梱)を満たすようライセンス文も添付する。
    cold_clear_licenses_dir = ROOT / "external" / "cold-clear-2"
    (DIST / "licenses").mkdir(exist_ok=True)
    for license_name in ("LICENSE-MIT", "LICENSE-APACHE"):
        shutil.copy2(cold_clear_licenses_dir / license_name, DIST / "licenses" / license_name)
    print(f"配布物: {DIST}")


if __name__ == "__main__":
    main()
