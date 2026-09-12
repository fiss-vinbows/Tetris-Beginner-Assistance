# -*- mode: python ; coding: utf-8 -*-
# TBA (Tetris Beginner Assistance) の PyInstaller 設定。
# ビルド: tools/build_exe.py を実行する(dist/TBA/ に TBA.exe と必要ファイルを揃える)。

block_cipher = None

a = Analysis(
    ["tba_launcher.py"],
    pathex=["."],
    binaries=[],
    # ミノのテンプレート画像は読み取り専用データとして同梱する
    # (src/paths.py の resource_root() から参照)。
    datas=[("src/vision/templates/*.png", "src/vision/templates")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy", "pandas"],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TBA",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # コンソールを出さない(以前の pythonw 起動と同じ)
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="TBA",
)
