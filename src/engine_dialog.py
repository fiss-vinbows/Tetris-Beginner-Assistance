"""「エンジンの登録」画面(2026-10-31。PBA の src/registry_dialogs.py と同じ形)"""

from __future__ import annotations

from pathlib import Path

from PyQt6 import QtWidgets

from .engine.registry import DEFAULT_ENGINE, EngineEntry, Registry


class EngineRegistryDialog(QtWidgets.QDialog):
    """思考エンジンの登録。実行ファイルを選び、名前と重み(省略可)を付ける。TBP 互換(Cold Clear 2 と同じやり取り)のエンジンに限る。"""

    def __init__(self, registry: Registry, reserved: set[str] | None = None, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("思考エンジンの登録")
        self.engines = [EngineEntry(e.name, e.exe, e.weights) for e in registry.engines]
        self._reserved = {DEFAULT_ENGINE} | (reserved or set())  # Cold Clear 2・プラグインのエンジンの名前
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel(
            "TBP 互換(Cold Clear 2 と同じ標準入出力のやり取り)の思考エンジンを登録できます。\n"
            "登録したエンジンは、メイン画面の「思考エンジン」の一覧に並びます。"
        ))
        self.list = QtWidgets.QListWidget()
        layout.addWidget(self.list)
        row = QtWidgets.QHBoxLayout()
        add = QtWidgets.QPushButton("追加…")
        add.clicked.connect(self._add)
        row.addWidget(add)
        remove = QtWidgets.QPushButton("削除")
        remove.clicked.connect(self._remove)
        row.addWidget(remove)
        row.addStretch(1)
        layout.addLayout(row)
        box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)
        self._refresh()

    def _refresh(self) -> None:
        self.list.clear()
        for e in self.engines:
            self.list.addItem(f"{e.name}  —  {e.exe}" + (f"  (重み: {e.weights})" if e.weights else ""))

    def add_engine(self, name: str, exe: str, weights: str = "") -> str | None:
        """登録を足す。登録できなければ理由を返す。"""
        name = name.strip()
        if not name:
            return "名前を入れてください"
        if name in self._reserved or any(e.name == name for e in self.engines):
            return f"「{name}」はもう使われている名前です"
        if not Path(exe).exists():
            return f"実行ファイルが見つかりません: {exe}"
        if weights and not Path(weights).exists():
            return f"重みのファイルが見つかりません: {weights}"
        self.engines.append(EngineEntry(name, exe, weights))
        self._refresh()
        return None

    def _add(self) -> None:
        exe, _ = QtWidgets.QFileDialog.getOpenFileName(self, "思考エンジンの実行ファイル", "", "実行ファイル (*.exe);;すべて (*)")
        if not exe:
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "名前", "一覧に出す名前:", text=Path(exe).stem)
        if not ok:
            return
        weights = ""
        if QtWidgets.QMessageBox.question(self, "重み", "評価の重みのファイル(--config で渡すもの)を指定しますか?") \
                == QtWidgets.QMessageBox.StandardButton.Yes:
            weights, _ = QtWidgets.QFileDialog.getOpenFileName(self, "評価の重み", "", "JSON (*.json);;すべて (*)")
        error = self.add_engine(name, exe, weights)
        if error:
            QtWidgets.QMessageBox.warning(self, "登録できません", error)

    def _remove(self) -> None:
        row = self.list.currentRow()
        if 0 <= row < len(self.engines):
            del self.engines[row]
            self._refresh()
