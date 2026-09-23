"""教育モードのUSBコントローラー入力(Windows標準のwinmmジョイスティックAPI)。

PyQt6にはゲームパッドの入力機能が無いため、追加のライブラリを入れずに使える
Windows標準のwinmm.dll(joyGetPosEx)をctypesで呼ぶ。一般的なUSBゲームパッド
(DirectInput互換)とXInput系(Xboxコントローラー等)の両方が見える。

入力は "Button1"〜"Button32"、十字キー(POV)は "PovUp/PovDown/PovLeft/PovRight"、
スティックは "X-/X+/Y-/Y+" という名前で扱う。割り当ては操作名→入力名のリストで
config/education_pad.json に保存する。
"""

from __future__ import annotations

import ctypes
import json
import sys
from pathlib import Path

from src.education.keybindings import ACTIONS
from src.paths import app_root

PAD_PATH = app_root() / "config" / "education_pad.json"

# 初期割り当て(仮置き)。別配列リセットは誤操作防止のため初期状態では割り当てない。
DEFAULT_PAD_BINDINGS: dict[str, list[str]] = {
    "move_left": ["PovLeft", "X-"],
    "move_right": ["PovRight", "X+"],
    "soft_drop": ["PovDown", "Y+"],
    "hard_drop": ["PovUp", "Y-"],
    "rotate_ccw": ["Button1"],
    "rotate_cw": ["Button2"],
    "hold": ["Button5", "Button6"],
    "undo": ["Button7"],
    "reset_same": ["Button8"],
    "reset_new": [],
}

_AXIS_THRESHOLD = 0.5  # 中心からの割合がこれを超えたら倒したとみなす


class _JOYINFOEX(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in (
        "dwSize", "dwFlags", "dwXpos", "dwYpos", "dwZpos", "dwRpos", "dwUpos", "dwVpos",
        "dwButtons", "dwButtonNumber", "dwPOV", "dwReserved1", "dwReserved2",
    )]


_JOY_RETURNALL = 0xFF
_POV_CENTERED = 0xFFFF


def inputs_from_raw(buttons: int, pov: int, x: int, y: int) -> set[str]:
    """winmmの生の値を入力名の集合にする(軸は0〜65535、中心32767)。"""
    active = {f"Button{i + 1}" for i in range(32) if buttons & (1 << i)}
    if pov != _POV_CENTERED:
        deg = pov / 100.0
        if deg >= 315 or deg <= 45:
            active.add("PovUp")
        if 45 <= deg <= 135:
            active.add("PovRight")
        if 135 <= deg <= 225:
            active.add("PovDown")
        if 225 <= deg <= 315:
            active.add("PovLeft")
    for name, value in (("X", x), ("Y", y)):
        offset = (value - 32767.5) / 32767.5
        if offset <= -_AXIS_THRESHOLD:
            active.add(f"{name}-")
        elif offset >= _AXIS_THRESHOLD:
            active.add(f"{name}+")
    return active


class Gamepad:
    """接続されている最初のコントローラーを読む。無ければconnected()がFalse。"""

    def __init__(self) -> None:
        self._winmm = ctypes.WinDLL("winmm") if sys.platform == "win32" else None
        self.device_id: int | None = None
        self.find()

    def _read(self, device_id: int) -> _JOYINFOEX | None:
        if self._winmm is None:
            return None
        info = _JOYINFOEX()
        info.dwSize = ctypes.sizeof(_JOYINFOEX)
        info.dwFlags = _JOY_RETURNALL
        if self._winmm.joyGetPosEx(device_id, ctypes.byref(info)) != 0:
            return None
        return info

    def find(self) -> bool:
        self.device_id = next((i for i in range(16) if self._read(i) is not None), None)
        return self.device_id is not None

    def connected(self) -> bool:
        return self.device_id is not None

    def poll(self) -> set[str]:
        """今押されている入力。切断されたら空集合(押しっぱなしが残らない)。"""
        if self.device_id is None:
            return set()
        info = self._read(self.device_id)
        if info is None:
            self.device_id = None
            return set()
        return inputs_from_raw(info.dwButtons, info.dwPOV, info.dwXpos, info.dwYpos)


def load_pad_bindings(path: Path = PAD_PATH) -> dict[str, list[str]]:
    bindings = {action: list(inputs) for action, inputs in DEFAULT_PAD_BINDINGS.items()}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for action in ACTIONS:
                value = data.get(action)
                if isinstance(value, list) and all(isinstance(v, str) for v in value):
                    bindings[action] = value
    except (OSError, ValueError):
        pass
    return bindings


def save_pad_bindings(bindings: dict[str, list[str]], path: Path = PAD_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bindings, ensure_ascii=False, indent=2), encoding="utf-8")


def actions_for_inputs(bindings: dict[str, list[str]], inputs: set[str]) -> set[str]:
    return {action for action, names in bindings.items() if inputs & set(names)}
