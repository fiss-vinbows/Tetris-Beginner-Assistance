"""メイン画面の 1P / 2P / 一人用の設定の枠(2026-10-31、利用者「TBA のインターフェースを PBA と同じにしたい」)

PBA の SideSettings と同じ形。枠ごとに
- 思考エンジン(2P は「使わない」も選べる。使わない側は支援モードを動かさない)
- 全自動モードのスイッチとキー割り当て(全自動を許可するプラグインが有効な時だけ出す)
- 仮想パッドの状態とボタン(2P だけ。ゲームの参加の画面で仮想パッドを 2P に割り当てる)
- 支援の設定(テンプレ・DPC 等。src/assist_view.py の設定欄を枠ごとのファイルで持つ)
を持つ。
"""

from __future__ import annotations

from pathlib import Path

from PyQt6 import QtCore, QtWidgets

from src import assist_view
from src.assist_view import AssistSettingsPanel
from src.engine.registry import NO_ENGINE, Registry, available_engines

SIDE_TITLES = {"1p": "1P(左の盤面)", "2p": "2P(右の盤面)", "solo": "自分の盤面"}


def side_view_path(side: str) -> Path:
    """枠ごとの支援の設定のファイル。1P は今までの config/assist_view.json(呼んだ時点の置き場所。テストで差し替えられる)。"""
    path = assist_view.ASSIST_VIEW_PATH
    return path if side == "1p" else path.with_name(f"assist_view_{side}.json")


class SideSettings(QtWidgets.QGroupBox):
    """1P / 2P / 一人用の枠。"""

    engine_changed = QtCore.pyqtSignal()

    def __init__(self, side: str, open_keys, parent: QtWidgets.QWidget | None = None) -> None:  # noqa: ANN001
        from src.education.window import MiniSwitch

        super().__init__(SIDE_TITLES[side], parent)
        self.side = side
        form = QtWidgets.QVBoxLayout(self)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("思考エンジン:"))
        self.engine_combo = QtWidgets.QComboBox()
        self.engine_combo.setToolTip(
            "この盤面で使う思考エンジン(支援モードは次に開始した時から)。"
            + ("\n「使わない」の時は 2P の支援・全自動を動かしません。" if side == "2p" else "")
        )
        self.engine_combo.currentTextChanged.connect(self._on_engine_selected)
        row.addWidget(self.engine_combo, 1)
        form.addLayout(row)

        # 全自動(全自動を許可するプラグインが有効な時だけ出す。set_autoplay_available)
        self.autoplay_box = QtWidgets.QWidget()
        auto_form = QtWidgets.QVBoxLayout(self.autoplay_box)
        auto_form.setContentsMargins(0, 0, 0, 0)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("<b>全自動モード</b>"))
        self.autoplay = MiniSwitch()
        self.autoplay.setToolTip(
            "AI の手を、ゲームのウィンドウが前面にある間キー入力"
            + ("(2P は仮想ゲームパッド)" if side == "2p" else "")
            + "で送ります。\nSteam 版・CPU 戦(ローカル対戦)専用です。オンライン対戦では使わないでください。"
        )
        row.addWidget(self.autoplay)
        row.addStretch(1)
        keys_btn = QtWidgets.QPushButton("キー割り当て")
        keys_btn.clicked.connect(lambda: open_keys(side))
        row.addWidget(keys_btn)
        auto_form.addLayout(row)
        # 仮想パッドは最初に使った時につなぎ、TBA を閉じるまで外さない。ゲームの参加の画面でボタンを押してこの側に割り当てる。
        # 1P・一人用は Zetris 方式の入力プラグインで 1P も仮想パッドにする時に使う(set_pad_available)
        self.pad_side = "2p" if side == "2p" else "1p"
        self.pad_row = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(self.pad_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QtWidgets.QLabel("仮想パッド:"))
        self.pad_label = QtWidgets.QLabel("つないでいない")
        row.addWidget(self.pad_label, 1)
        for text, button in (("A を押す", "PAD_A"), ("START を押す", "PAD_START")):
            btn = QtWidgets.QPushButton(text)
            btn.setToolTip("仮想パッドのボタンを押します。ゲームの参加の画面で押して、この側に割り当ててください")
            btn.clicked.connect(lambda _c=False, b=button: self.tap_pad(b))
            row.addWidget(btn)
        auto_form.addWidget(self.pad_row)
        form.addWidget(self.autoplay_box)

        # 支援の設定(テンプレ・DPC 等)。縦に長いのでスクロールできるようにする
        self.view_panel = AssistSettingsPanel(path=side_view_path(side))
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setWidget(self.view_panel)
        form.addWidget(scroll, 1)
        self.refresh_engines()

    # ---- 思考エンジン ----
    def refresh_engines(self) -> None:
        registry = Registry.load()
        names = list(available_engines(registry))
        if self.side == "2p":
            names.insert(0, NO_ENGINE)
        current = registry.side_selection(self.side)
        self.engine_combo.blockSignals(True)
        self.engine_combo.clear()
        self.engine_combo.addItems(names)
        self.engine_combo.setCurrentText(current if current in names else names[0])
        self.engine_combo.blockSignals(False)

    def _on_engine_selected(self, name: str) -> None:
        if not name:
            return
        registry = Registry.load()
        registry.set_side_selection(self.side, name)
        registry.save()
        self.engine_changed.emit()

    def uses_engine(self) -> bool:
        """この枠の支援(と全自動)を動かすか。2P で「使わない」なら動かさない。"""
        return self.engine_combo.currentText() != NO_ENGINE

    # ---- 全自動 ----
    def set_autoplay_available(self, available: bool) -> None:
        self.autoplay_box.setVisible(available)
        if not available:
            self.autoplay.setChecked(False)

    def set_pad_available(self, available: bool) -> None:
        """仮想パッドの行を出すか(2P は全自動が使える時いつも、1P は Zetris 方式の入力プラグインがある時)。"""
        self.pad_row.setVisible(available)

    def autoplay_on(self) -> bool:
        return self.autoplay_box.isVisibleTo(self) and self.autoplay.isChecked()

    def tap_pad(self, button: str) -> None:
        """仮想パッドのボタンを短く押す(ゲームの参加の画面で 2P に割り当てる)。"""
        from src.auto.pad_input import pad_status, send_pad

        status = pad_status()
        if status != "ok":
            self.pad_label.setText(
                "vgamepad が入っていません" if status == "no_vgamepad" else "作れません(ViGEmBus ドライバーを入れてください)"
            )
            return
        send_pad(button, True, self.pad_side)
        QtCore.QTimer.singleShot(100, lambda: send_pad(button, False, self.pad_side))
        self.pad_label.setText("つないでいます")
