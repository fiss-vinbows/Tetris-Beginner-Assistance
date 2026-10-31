"""ゲームのウィンドウを一覧から選ぶ画面(2026-10-30。PBA の src/window_dialog.py と同じ役割)。

決め打ちの実行ファイル名・タイトルでゲームのウィンドウが見つからない時に、表示中のウィンドウから選んでもらい、
実行ファイル名(読めなければタイトル)を config/game_window.json に覚える(ゲームを起動し直しても次から見つかる)。
"""

from __future__ import annotations

from PyQt6 import QtWidgets

from .capture.window_detect import SavedWindow, WindowEntry


class WindowPickDialog(QtWidgets.QDialog):
    def __init__(self, entries: list[WindowEntry], parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ゲームのウィンドウを選ぶ")
        self.entries = entries
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel(
            "ぷよぷよテトリス2のウィンドウが自動では見つかりませんでした。表示中のウィンドウから選んでください。"
        ))
        self.list = QtWidgets.QListWidget()
        for e in entries:
            w = e.window
            self.list.addItem(f"{w.title}  ({e.exe or '実行ファイル名不明'}・{w.width}×{w.height})")
        if entries:
            self.list.setCurrentRow(0)
        self.list.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(self.list)
        box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)
        self.resize(640, 360)

    def selected(self) -> SavedWindow | None:
        """選んだウィンドウを覚える形(実行ファイル名があればそれ、無ければタイトル)。"""
        row = self.list.currentRow()
        if row < 0 or row >= len(self.entries):
            return None
        e = self.entries[row]
        return SavedWindow(exe=e.exe) if e.exe else SavedWindow(title=e.window.title)
