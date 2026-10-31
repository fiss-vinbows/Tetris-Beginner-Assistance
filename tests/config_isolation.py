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

from src.engine import cold_clear_client  # noqa: E402

cold_clear_client.ENGINE_CONFIG = _DIR / "engine.json"

from src import plugin_loader  # noqa: E402

# 【2026-10-30】プラグインも本番のもの(非公開のものを含む)を読まない。使うテストは一時フォルダに置く
plugin_loader.PLUGIN_DIR = _DIR / "plugins"
plugin_loader.CONFIG_PATH = _DIR / "plugins.json"

from src.capture import window_detect  # noqa: E402

# 【2026-10-30】一覧から選んだゲームのウィンドウ(config/game_window.json)も本番のものを読まない
window_detect.SAVED_WINDOW_PATH = _DIR / "game_window.json"

from src.engine import registry  # noqa: E402

# 【2026-10-31】登録・選択した思考エンジン(config/engines.json)も本番のものを読まない
registry.REGISTRY_PATH = _DIR / "engines.json"
