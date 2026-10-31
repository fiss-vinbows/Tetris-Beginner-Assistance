"""plugins/ フォルダのプラグインを読み込み、有効・無効を管理する(2026-10-30。PBA の src/plugin_loader.py と同じ形)。

各プラグインは plugins/<名前>/plugin.py に PLUGIN = Plugin(...) を書く。有効・無効は TBA の「プラグイン」画面で切り替え、
config/plugins.json に無効にしたものだけを保存する(新しく置いたプラグインは有効で始まる)。読み込めないプラグインは理由を残して飛ばす。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .paths import app_root
from .plugin_api import Engine, Plugin

PLUGIN_DIR = app_root() / "plugins"
CONFIG_PATH = app_root() / "config" / "plugins.json"


def discover(plugin_dir: Path | None = None) -> tuple[list[Plugin], dict[str, str]]:
    """プラグインを読み込む。(読み込めたプラグイン, {フォルダ名: 読み込めなかった理由})。"""
    found, errors = discover_folders(plugin_dir)
    return [plugin for _folder, plugin in found], errors


def discover_folders(plugin_dir: Path | None = None) -> tuple[list[tuple[Path, Plugin]], dict[str, str]]:
    """プラグインを読み込む。([(フォルダ, プラグイン)], {フォルダ名: 読み込めなかった理由})。配布物の作成でも使う。"""
    plugin_dir = PLUGIN_DIR if plugin_dir is None else plugin_dir  # 呼んだ時点の置き場所(テストで差し替えられる)
    plugins: list[tuple[Path, Plugin]] = []
    errors: dict[str, str] = {}
    if not plugin_dir.is_dir():
        return plugins, errors
    for folder in sorted(p for p in plugin_dir.iterdir() if p.is_dir() and (p / "plugin.py").exists()):
        name = f"tba_plugin_{folder.name}"
        try:
            spec = importlib.util.spec_from_file_location(name, folder / "plugin.py", submodule_search_locations=[str(folder)])
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            plugin = getattr(module, "PLUGIN")
            if not isinstance(plugin, Plugin):
                raise TypeError("PLUGIN が Plugin ではありません")
            plugins.append((folder, plugin))
        except Exception as exc:  # 1つのプラグインの不具合で TBA を止めない
            errors[folder.name] = f"{type(exc).__name__}: {exc}"
    return plugins, errors


def load_disabled(path: Path | None = None) -> set[str]:
    path = CONFIG_PATH if path is None else path
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {str(x) for x in data.get("disabled", [])}


def save_disabled(disabled: set[str], path: Path | None = None) -> None:
    path = Path(CONFIG_PATH if path is None else path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"disabled": sorted(disabled)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@dataclass
class PluginManager:
    plugins: list[Plugin] = field(default_factory=list)
    disabled: set[str] = field(default_factory=set)
    errors: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, plugin_dir: Path | None = None, config: Path | None = None) -> "PluginManager":
        plugins, errors = discover(plugin_dir)
        return cls(plugins, load_disabled(config), errors)

    @property
    def enabled(self) -> list[Plugin]:
        return [p for p in self.plugins if p.id not in self.disabled]

    def full_auto(self) -> bool:
        return any(p.full_auto for p in self.enabled)

    def debug_log(self) -> bool:
        return any(p.debug_log for p in self.enabled)

    def manual_calibration(self) -> bool:
        return any(p.manual_calibration for p in self.enabled)

    def local_versus(self) -> bool:
        return any(p.local_versus for p in self.enabled)

    def synced_input(self) -> bool:
        return any(p.synced_input for p in self.enabled)

    def memory_read(self) -> bool:
        return any(p.memory_read for p in self.enabled)

    def engines(self) -> dict[str, Engine]:
        """有効なプラグインが足した思考エンジン({ID: Engine})。"""
        out: dict[str, Engine] = {}
        for p in self.enabled:
            out.update(p.engines)
        return out
