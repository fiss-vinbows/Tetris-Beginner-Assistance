"""教育モードのキー割り当て(仕様書4-1: 利用者が変更できる)。

config/education_keys.json に保存する。無ければ初期値で作る。
この段階ではキーボードのみ。コントローラーは後の段階で同じ「操作名→入力」の
形に載せる(PyQt6にゲームパッドの入力機能が無く、別ライブラリの導入が要るため)。

キー名はQtの表記(Qt.Key の名前から "Key_" を除いたもの。例: "Left", "Z", "Space")。
修飾キーは "Shift+R" のように "+" で前置する(Shift/Ctrl/Alt)。
"""

from __future__ import annotations

import json
from pathlib import Path

from PyQt6 import QtCore, QtGui

from src.paths import app_root

KEYS_PATH = app_root() / "config" / "education_keys.json"

# 操作名 → 説明(設定画面や一覧表示に使う)
ACTIONS: dict[str, str] = {
    "move_left": "左へ移動",
    "move_right": "右へ移動",
    "rotate_ccw": "左回転",
    "rotate_cw": "右回転",
    "soft_drop": "ソフトドロップ(接地まで落とす。固定しない)",
    "hard_drop": "ハードドロップ(固定)",
    "hold": "ホールド",
    "undo": "一手戻す",
    "reset_same": "同一配列でリセット",
    "reset_new": "別配列でリセット",
    "cycle_candidate": "次の候補",
    "screenshot": "画像を保存",
    "toggle_hints": "提示の表示/非表示",
    "toggle_priority": "テンプレ優先/AI優先",
}

# 初期割り当て(仕様書では未決。利用者と合意した仮置き 2026-09-22)
DEFAULT_BINDINGS: dict[str, str] = {
    "move_left": "Left",
    "move_right": "Right",
    "rotate_ccw": "Z",
    "rotate_cw": "X",
    "soft_drop": "Down",
    "hard_drop": "Space",
    "hold": "C",
    "undo": "Backspace",
    "reset_same": "R",
    "reset_new": "Shift+R",
    # 【2026-09-24】仮の初期キー(設定ファイルで変更できる)
    "cycle_candidate": "F2",
    "screenshot": "F12",
    "toggle_hints": "F3",
    "toggle_priority": "F4",
}

_MODIFIERS = {
    "Shift": QtCore.Qt.KeyboardModifier.ShiftModifier,
    "Ctrl": QtCore.Qt.KeyboardModifier.ControlModifier,
    "Alt": QtCore.Qt.KeyboardModifier.AltModifier,
}


def load_bindings(path: Path = KEYS_PATH) -> dict[str, str]:
    """保存済みの割り当てを読む。無い・壊れている・不足している項目は初期値で補う。"""
    bindings = dict(DEFAULT_BINDINGS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for action in ACTIONS:
                value = data.get(action)
                if isinstance(value, str) and value:
                    bindings[action] = value
    except (OSError, ValueError):
        pass
    return bindings


def save_bindings(bindings: dict[str, str], path: Path = KEYS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bindings, ensure_ascii=False, indent=2), encoding="utf-8")


def key_event_name(event: QtGui.QKeyEvent) -> str | None:
    """キーイベントを "Shift+R" のような割り当て用の名前にする。修飾キー単独ならNone。"""
    key = QtCore.Qt.Key(event.key())
    name = key.name.removeprefix("Key_")
    if name in ("Shift", "Control", "Alt", "Meta", "unknown"):
        return None
    prefix = "".join(f"{label}+" for label, flag in _MODIFIERS.items() if event.modifiers() & flag)
    return prefix + name


def action_for(bindings: dict[str, str], event_name: str) -> str | None:
    """キー名に割り当てられた操作名。無ければNone。"""
    for action, key_name in bindings.items():
        if key_name == event_name:
            return action
    return None


# ---- 押しっぱなしの連続入力(キーリピート)の設定 ----
# 【2026-09-23・利用者の指示】OSのキーリピートに頼らず独自に設ける
# (OSの設定次第で単押しでも2マス動いていた)。キーボードとコントローラー共通。
REPEAT_PATH = app_root() / "config" / "education_repeat.json"
# 連続入力が始まるまで / 左右移動の繰り返しの間隔 / ソフトドロップの繰り返しの間隔
# 【2026-09-23・利用者の指示】ソフトドロップはもっと速く: 左右移動と別に設定し、
# 押しっぱなしにしたらすぐ(待ち時間なしで)この間隔で降り続ける。
DEFAULT_REPEAT = {"delay_ms": 170, "interval_ms": 50, "soft_interval_ms": 20}
REPEAT_LIMITS = {"delay_ms": (50, 1000), "interval_ms": (0, 500), "soft_interval_ms": (0, 500)}


def load_repeat(path: Path = REPEAT_PATH) -> dict[str, int]:
    settings = dict(DEFAULT_REPEAT)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for key, (low, high) in REPEAT_LIMITS.items():
            value = data.get(key) if isinstance(data, dict) else None
            if isinstance(value, int) and low <= value <= high:
                settings[key] = value
    except (OSError, ValueError):
        pass
    return settings


def save_repeat(settings: dict[str, int], path: Path = REPEAT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


# ---- 表示の設定(提示の表示/非表示、テンプレ優先/AI優先) ----
# 【2026-09-24・利用者の要望】トグルで切り替え、次回も同じ状態で開く
VIEW_PATH = app_root() / "config" / "education_view.json"
DEFAULT_VIEW = {"show_hints": True, "prefer_ai": False}


def load_view(path: Path = VIEW_PATH) -> dict[str, bool]:
    settings = dict(DEFAULT_VIEW)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in DEFAULT_VIEW:
            value = data.get(key) if isinstance(data, dict) else None
            if isinstance(value, bool):
                settings[key] = value
    except (OSError, ValueError):
        pass
    return settings


def save_view(settings: dict[str, bool], path: Path = VIEW_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
