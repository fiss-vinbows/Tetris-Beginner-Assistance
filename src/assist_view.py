"""支援モードの設定(提示する候補の表示/非表示)。

【2026-10-04・利用者の要望】シミュレーターの「表示する候補」欄と同じく、支援モードでも開幕TD・
パフェ後・パフェ・テンプレ全体の有無をトグルスイッチで切り替える。起動画面に直接並べ
(【2026-10-04・利用者の指示】起動画面が小さいので別画面にせず合体)、config/assist_view.json に保存して次回も同じ状態で開く。
REN・6-3積み・開幕パフェ積みは支援モードにまだ提示の仕組みが無いため、実装してから追加する。
"""

from __future__ import annotations

import json
from pathlib import Path

from PyQt6 import QtCore, QtWidgets

from src.engine.openers import DPC_TEMPLATE_NAME, OPENER_TEMPLATES, TD_EXTRA_TEMPLATES, TD_TEMPLATE_NAMES
from src.paths import app_root

ASSIST_VIEW_PATH = app_root() / "config" / "assist_view.json"

SHOW_PREFIX = "show:"
TDTD_ID = "TDTD"
PC_ODDS_ID = "継続パフェ"
# templates: テンプレ全体を使うか(オフなら開幕TD・DPC・TDTDを出さない)
# pc_odds_first: テンプレと継続パフェの両方を組めるとき継続パフェを優先
# tdtd_first: DPCとTDTDの両方を組めるときTDTDを優先
# template_full_plan: テンプレの間は表示手数に関係なく、その図(7種1巡)の残りの手をすべて表示する
DEFAULT_ASSIST_VIEW = {"templates": True, "pc_odds_first": False, "tdtd_first": False, "template_full_plan": False}
# 【2026-10-04・利用者の要望】最善手の表示手数(1〜5)も記憶する
DEFAULT_PLAN_DEPTH = 3
PLAN_DEPTH_RANGE = (1, 5)


def td_template_names() -> list[str]:
    """設定欄に並べる開幕TDテンプレ(支援モードの開幕で使うもの→TDTD向けに集めたもの)。"""
    return [t.name_ja for t in OPENER_TEMPLATES + TD_EXTRA_TEMPLATES if t.name_ja in TD_TEMPLATE_NAMES]


def filter_items() -> list[tuple[str, str, str]]:
    """(見出し, 候補のID, 表示名)。テンプレはテンプレ名がID。"""
    items = [("開幕TD", name, name) for name in td_template_names()]
    items += [
        ("パフェ後", DPC_TEMPLATE_NAME, "DPC"),
        ("パフェ後", TDTD_ID, "TDTD"),
        ("パフェ", PC_ODDS_ID, "継続パフェ"),
    ]
    return items


def load_assist_view(path: Path | None = None) -> dict:
    path = ASSIST_VIEW_PATH if path is None else path  # 呼んだ時点の置き場所(テストで差し替えられる)
    settings: dict = dict(DEFAULT_ASSIST_VIEW, plan_depth=DEFAULT_PLAN_DEPTH)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return settings
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, bool) and (key in DEFAULT_ASSIST_VIEW or key.startswith(SHOW_PREFIX)):
                settings[key] = value
        depth = data.get("plan_depth")
        if isinstance(depth, int) and not isinstance(depth, bool) and PLAN_DEPTH_RANGE[0] <= depth <= PLAN_DEPTH_RANGE[1]:
            settings["plan_depth"] = depth
    return settings


def save_assist_view(settings: dict, path: Path | None = None) -> None:
    path = ASSIST_VIEW_PATH if path is None else path  # 呼んだ時点の置き場所(テストで差し替えられる)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def is_shown(settings: dict[str, bool], source_id: str) -> bool:
    return settings.get(SHOW_PREFIX + source_id, True)


def worker_options(settings: dict[str, bool]) -> dict:
    """設定をAssistWorkerの引数に直す。"""
    tdtd = is_shown(settings, TDTD_ID)
    return {
        "opener_enabled": settings["templates"],
        "pc_odds_enabled": is_shown(settings, PC_ODDS_ID),
        "pc_odds_first": settings["pc_odds_first"],
        "tdtd_mode": ("first" if settings["tdtd_first"] else "fallback") if tdtd else "off",
        "dpc_enabled": is_shown(settings, DPC_TEMPLATE_NAME),
        "excluded_templates": frozenset(name for name in td_template_names() if not is_shown(settings, name)),
        "plan_depth": settings["plan_depth"],
        "template_full_plan": settings["template_full_plan"],
    }


class AssistSettingsPanel(QtWidgets.QWidget):
    """支援モードの設定欄(起動画面に置く)。切り替えるたびに保存する。"""

    def __init__(self, parent: QtWidgets.QWidget | None = None, path: Path | None = None) -> None:
        from src.education.window import MiniSwitch

        super().__init__(parent)
        self.path = path
        self.settings = load_assist_view(path)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        depth_row = QtWidgets.QHBoxLayout()
        depth_row.addWidget(QtWidgets.QLabel("最善手の表示手数(1〜5):"))
        self.plan_depth_spin = QtWidgets.QSpinBox()
        self.plan_depth_spin.setRange(*PLAN_DEPTH_RANGE)
        self.plan_depth_spin.setValue(self.settings["plan_depth"])
        self.plan_depth_spin.setToolTip(
            "1なら今のミノの置き場所だけ、2以上なら2手目以降の読み筋も"
            "小さいドット+番号で表示します。ラインが消える手より先は表示しません。"
        )
        self.plan_depth_spin.valueChanged.connect(self._on_plan_depth_changed)
        depth_row.addWidget(self.plan_depth_spin)
        depth_row.addStretch(1)
        layout.addLayout(depth_row)
        # 【2026-10-04・利用者の要望】テンプレに限り、7種1巡の図の手をすべて表示するか選べる
        self.full_plan_switch = MiniSwitch()
        self.full_plan_switch.setChecked(self.settings["template_full_plan"])
        self.full_plan_switch.toggled.connect(lambda on: self._set("template_full_plan", on))
        layout.addLayout(self._row("テンプレ・パフェの間は、手順をすべて表示する", self.full_plan_switch, indent=0))
        full_note = QtWidgets.QLabel(
            "オンにすると、テンプレ(7種1巡の図)や途中で見えたパフェの手順を組んでいる間は、表示手数に関係なく"
            "残りの手をすべて番号つきで表示します。AIの提案は表示手数どおりです。"
            "ラインが消える手より先は位置がずれるため表示しません。"
        )
        full_note.setWordWrap(True)
        full_note.setStyleSheet("color: gray;")
        layout.addWidget(full_note)

        # テンプレ全体の有無(オフなら開幕TD・パフェ後のスイッチは操作できない)
        self.templates_switch = MiniSwitch()
        layout.addLayout(self._row("<b>テンプレを使う</b>", self.templates_switch, indent=0))
        self.templates_switch.setChecked(self.settings["templates"])
        self.templates_switch.toggled.connect(self._on_templates_toggled)

        panel = QtWidgets.QGroupBox("支援モードで提示する候補")
        box = QtWidgets.QVBoxLayout(panel)
        box.setSpacing(3)
        self.switches: dict[str, MiniSwitch] = {}
        self.groups: dict[str, str] = {}
        heading = None
        for group, source_id, label in filter_items():
            if group != heading:
                # カテゴリ(開幕TD・パフェ後等)を区切り線で分ける(シミュレーターと同じ)
                if heading is not None:
                    box.addSpacing(4)
                    box.addWidget(self._line())
                heading = group
                box.addWidget(QtWidgets.QLabel(f"<b>{group}</b>"))
            switch = MiniSwitch()
            switch.setChecked(is_shown(self.settings, source_id))
            switch.toggled.connect(lambda on, s=source_id: self._set(SHOW_PREFIX + s, on))
            box.addLayout(self._row(label, switch))
            self.switches[source_id] = switch
            self.groups[source_id] = group
        layout.addWidget(panel)

        self.tdtd_combo = self._combo(
            layout, "DPCとTDTDの両方を組めるとき:", ["DPCを優先", "TDTDを優先"], "tdtd_first",
            "TDTD: TD系テンプレで8段パフェを取った後、袋がずれたままTD系テンプレを1巡目から組み直します。\n"
            "DPCはパフェ後ほぼ必ず組めるため、「DPCを優先」ではTDTDはほとんど出ません。",
        )
        # 【2026-10-04・利用者の指示】途中でパフェが見えたとき、それを優先するかをスイッチで選び、説明を載せる
        self.pc_odds_first_switch = MiniSwitch()
        self.pc_odds_first_switch.setChecked(self.settings["pc_odds_first"])
        self.pc_odds_first_switch.toggled.connect(lambda on: self._set("pc_odds_first", on))
        layout.addLayout(self._row("途中でパフェが見えたら、テンプレよりパフェを優先する", self.pc_odds_first_switch, indent=0))
        self.pc_odds_first_note = QtWidgets.QLabel(
            "オン: 対局の途中(テンプレの図を1つ組み終えた後やパフェの後)、次に組む形を選ぶときに、"
            "パフェを取れる見込みが50%以上ある手順が見えていれば、テンプレ(DPC・TDTD・2巡目以降の図)より"
            "そちらを提示します。\n"
            "オフ: 続けられるテンプレがあればテンプレを提示し、テンプレが組めないときだけパフェの手順を提示します。\n"
            "※対局開始(盤面もHOLDも空)は、どちらでも開幕テンプレを優先します。"
        )
        self.pc_odds_first_note.setWordWrap(True)
        self.pc_odds_first_note.setStyleSheet("color: gray;")
        layout.addWidget(self.pc_odds_first_note)
        note = QtWidgets.QLabel("設定は、次に支援モードを開始したときから反映されます。")
        note.setStyleSheet("color: gray;")
        layout.addWidget(note)
        layout.addStretch(1)
        self._apply_enabled()

    @staticmethod
    def _line() -> QtWidgets.QFrame:
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        return line

    @staticmethod
    def _row(label: str, switch: QtWidgets.QWidget, indent: int = 8) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(indent, 0, 0, 0)
        row.addWidget(QtWidgets.QLabel(label))
        row.addStretch(1)
        row.addWidget(switch)
        return row

    def _combo(self, layout: QtWidgets.QVBoxLayout, label: str, items: list[str], key: str, tip: str) -> QtWidgets.QComboBox:
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label))
        combo = QtWidgets.QComboBox()
        combo.addItems(items)
        combo.setCurrentIndex(1 if self.settings[key] else 0)
        combo.setToolTip(tip)
        combo.currentIndexChanged.connect(lambda i, k=key: self._set(k, i == 1))
        row.addWidget(combo)
        row.addStretch(1)
        layout.addLayout(row)
        return combo

    def _set(self, key: str, value: bool) -> None:
        self.settings[key] = value
        save_assist_view(self.settings, self.path)
        self._apply_enabled()

    def _on_plan_depth_changed(self, value: int) -> None:
        self.settings["plan_depth"] = value
        save_assist_view(self.settings, self.path)

    def _on_templates_toggled(self, on: bool) -> None:
        self._set("templates", on)

    def _apply_enabled(self) -> None:
        """テンプレを使わないときは開幕TD・パフェ後を操作できない。両方を組める状況が無い優先設定も操作できない。"""
        templates = self.settings["templates"]
        self.full_plan_switch.setEnabled(templates)
        for source_id, switch in self.switches.items():
            switch.setEnabled(templates or self.groups[source_id] == "パフェ")
        self.tdtd_combo.setEnabled(
            templates and is_shown(self.settings, DPC_TEMPLATE_NAME) and is_shown(self.settings, TDTD_ID)
        )
        self.pc_odds_first_switch.setEnabled(templates and is_shown(self.settings, PC_ODDS_ID))
