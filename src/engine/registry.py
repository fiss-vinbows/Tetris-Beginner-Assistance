"""思考エンジンの登録と選択(2026-10-31、利用者「PBA のようにエンジン登録と思考エンジン選択機能を標準機能に」)

PBA の src/engine/registry.py と同じ考え方。選べるエンジンは
- 同梱の Cold Clear 2(既定。config/engine.json があればそちらに従う、従来どおり)
- プラグインが足したエンジン(src/plugin_api.py の engines)
- 利用者が登録したエンジン(TBP 互換の実行ファイル。config/engines.json)
選んだエンジンは支援モード・全自動・シミュレーターで使う。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from src.paths import app_root

REGISTRY_PATH = app_root() / "config" / "engines.json"
DEFAULT_ENGINE = "Cold Clear 2"
# 【2026-10-31・利用者の要望】PBA と同じく、1P・2P・一人用の枠ごとに思考エンジンを選ぶ。2P は「使わない」も選べる
NO_ENGINE = "使わない"
SIDES = ("1p", "2p", "solo")


@dataclass
class EngineEntry:
    name: str
    exe: str
    weights: str = ""  # エンジンへ --config で渡す評価の重み(省略可)


@dataclass
class Registry:
    engines: list[EngineEntry] = field(default_factory=list)
    selected: str = DEFAULT_ENGINE  # 1P(対戦モード)のエンジン。シミュレーターもこれを使う
    side_engines: dict[str, str] = field(default_factory=dict)  # 2P・一人用のエンジン

    def side_selection(self, side: str) -> str:
        if side == "1p":
            return self.selected
        return self.side_engines.get(side, NO_ENGINE if side == "2p" else DEFAULT_ENGINE)

    def set_side_selection(self, side: str, name: str) -> None:
        if side == "1p":
            self.selected = name
        else:
            self.side_engines[side] = name

    @classmethod
    def load(cls) -> "Registry":
        try:
            data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
            engines = [EngineEntry(e["name"], e["exe"], e.get("weights", "")) for e in data.get("engines", [])]
            sides = data.get("side_engines", {})
            sides = {k: v for k, v in sides.items() if k in SIDES and isinstance(v, str)} if isinstance(sides, dict) else {}
            return cls(engines, data.get("selected", DEFAULT_ENGINE), sides)
        except (OSError, ValueError, KeyError, TypeError):
            return cls()

    def save(self) -> None:
        REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {"engines": [vars(e) for e in self.engines], "selected": self.selected, "side_engines": self.side_engines}
        REGISTRY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def available_engines(registry: Registry | None = None) -> dict[str, tuple[Path, Path | None] | None]:
    """選べるエンジン {名前: (実行ファイル, 重み)}。Cold Clear 2 は None(従来どおり config/engine.json に従う)。"""
    from src.plugin_loader import PluginManager

    registry = registry or Registry.load()
    out: dict[str, tuple[Path, Path | None] | None] = {DEFAULT_ENGINE: None}
    for engine in PluginManager.load().engines().values():
        out.setdefault(engine.label, (engine.exe, engine.weights))
    for e in registry.engines:
        out.setdefault(e.name, (Path(e.exe), Path(e.weights) if e.weights else None))
    return out


def selected_engine(registry: Registry | None = None, side: str = "1p") -> tuple[str, tuple[Path, Path | None] | None]:
    """その枠で選んでいるエンジンの(名前, ColdClearClient に渡すもの)。選んだものが無くなっていれば Cold Clear 2。

    2P で「使わない」を選んでいる時は (NO_ENGINE, None)。
    """
    registry = registry or Registry.load()
    engines = available_engines(registry)
    name = registry.side_selection(side)
    if name == NO_ENGINE and side == "2p":
        return NO_ENGINE, None
    name = name if name in engines else DEFAULT_ENGINE
    return name, engines[name]
