"""テストで本番の設定ファイル(config/education_*.json)を読み書きしないようにする。

【2026-10-03】画面(PracticeWindow等)を作るテストが本番の表示設定・リピート設定を読み込み、実機で
設定した内容(優先=AI等)によってテスト結果が変わった。また、リピート設定のテストが本番のファイルに
書き込んでいた。このモジュールを読み込むと、設定ファイルの置き場所を一時フォルダに差し替える。
"""

from __future__ import annotations

import atexit
import shutil
import tempfile
from pathlib import Path

from src.education import gamepad, keybindings

_DIR = Path(tempfile.mkdtemp(prefix="tba_test_config_"))
atexit.register(shutil.rmtree, _DIR, ignore_errors=True)

keybindings.KEYS_PATH = _DIR / "education_keys.json"
keybindings.REPEAT_PATH = _DIR / "education_repeat.json"
keybindings.VIEW_PATH = _DIR / "education_view.json"
gamepad.PAD_PATH = _DIR / "education_pad.json"

from src import assist_view  # noqa: E402

assist_view.ASSIST_VIEW_PATH = _DIR / "assist_view.json"
