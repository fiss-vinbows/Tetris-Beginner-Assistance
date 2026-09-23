"""教育モードの練習ウィンドウとキー割り当てのテスト(画面は表示せずoffscreenで動かす)。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

from src.education import keybindings  # noqa: E402
from src.education.window import PracticeWindow  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _key(window: PracticeWindow, key: QtCore.Qt.Key, modifiers=QtCore.Qt.KeyboardModifier.NoModifier, auto_repeat: bool = False) -> None:
    event = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, key, modifiers, 0, 0, 0, "", auto_repeat)
    window.keyPressEvent(event)


def _release(window: PracticeWindow, key: QtCore.Qt.Key) -> None:
    event = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyRelease, key, QtCore.Qt.KeyboardModifier.NoModifier)
    window.keyReleaseEvent(event)


class TestKeyBindings(unittest.TestCase):
    def test_defaults_are_used_when_file_is_missing_or_broken(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "none.json"
            self.assertEqual(keybindings.load_bindings(missing), keybindings.DEFAULT_BINDINGS)
            broken = Path(tmp) / "broken.json"
            broken.write_text("{not json", encoding="utf-8")
            self.assertEqual(keybindings.load_bindings(broken), keybindings.DEFAULT_BINDINGS)

    def test_saved_bindings_override_defaults_and_missing_actions_fall_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "keys.json"
            path.write_text(json.dumps({"hard_drop": "Up", "hold": ""}), encoding="utf-8")
            loaded = keybindings.load_bindings(path)
            self.assertEqual(loaded["hard_drop"], "Up")
            self.assertEqual(loaded["hold"], keybindings.DEFAULT_BINDINGS["hold"], "空の値は初期値に戻す")
            self.assertEqual(loaded["move_left"], "Left")
            keybindings.save_bindings(loaded, path)
            self.assertEqual(keybindings.load_bindings(path), loaded)

    def test_key_event_name_includes_modifiers(self) -> None:
        event = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_R, QtCore.Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(keybindings.key_event_name(event), "Shift+R")
        self.assertEqual(keybindings.action_for(keybindings.DEFAULT_BINDINGS, "Shift+R"), "reset_new")
        self.assertEqual(keybindings.action_for(keybindings.DEFAULT_BINDINGS, "R"), "reset_same")
        plain = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Shift, QtCore.Qt.KeyboardModifier.ShiftModifier)
        self.assertIsNone(keybindings.key_event_name(plain), "修飾キー単独は操作にしない")


class TestGamepadInputs(unittest.TestCase):
    def test_raw_values_map_to_input_names(self) -> None:
        from src.education.gamepad import inputs_from_raw

        self.assertEqual(inputs_from_raw(0b101, 0xFFFF, 32767, 32767), {"Button1", "Button3"})
        self.assertEqual(inputs_from_raw(0, 27000, 32767, 32767), {"PovLeft"})
        self.assertEqual(inputs_from_raw(0, 13500, 32767, 32767), {"PovRight", "PovDown"})
        self.assertEqual(inputs_from_raw(0, 0xFFFF, 0, 65535), {"X-", "Y+"})


class TestPracticeWindow(unittest.TestCase):
    def setUp(self) -> None:
        from src.education.advisor import Advisor

        # 推奨手のAI(CC2)は起動せず、何も返さない偽物を使う
        fake = type("E", (), {"start_thinking": lambda *a, **k: None, "poll_suggestion": lambda *a: None, "close": lambda s: None})
        self.window = PracticeWindow(seed=5, advisor=Advisor(engine_factory=fake, opener_enabled=False))
        self.window.isActiveWindow = lambda: True  # offscreenでは常に非アクティブになるため
        self.window.bindings = dict(keybindings.DEFAULT_BINDINGS)
        self.window.repeat = dict(keybindings.DEFAULT_REPEAT)  # 利用者の保存済み設定に左右されないように

    def test_keys_drive_the_game_state(self) -> None:
        state = self.window.state
        col_before = state.col
        _key(self.window, QtCore.Qt.Key.Key_Left)
        _release(self.window, QtCore.Qt.Key.Key_Left)
        self.assertEqual(state.col, col_before - 1)
        _key(self.window, QtCore.Qt.Key.Key_X)
        _release(self.window, QtCore.Qt.Key.Key_X)
        self.assertEqual(state.orient, 1 if state.current != "O" else 0)
        row_before = state.row
        _key(self.window, QtCore.Qt.Key.Key_Down)
        _release(self.window, QtCore.Qt.Key.Key_Down)
        self.assertEqual(state.row, row_before + 1, "ソフトドロップは1マスずつ")
        while state.soft_drop():
            pass
        self.assertEqual(state.history, [], "ソフトドロップで固定されている")
        for key in (QtCore.Qt.Key.Key_Space, QtCore.Qt.Key.Key_C):
            _key(self.window, key)
            _release(self.window, key)
        self.assertEqual(len(state.history), 1, "ハードドロップで固定されていない")
        self.assertIsNotNone(state.hold)
        _key(self.window, QtCore.Qt.Key.Key_Backspace)
        self.assertEqual(len(state.history), 0)
        self.assertIsNone(state.hold, "一手戻すでHOLDも手番開始時点に戻っていない")

    def test_os_auto_repeat_is_ignored_and_own_repeat_is_used(self) -> None:
        # 【2026-09-23実機】OSのキーリピートで単押しでも2マス動いていた。
        # OSの自動リピートは無視し、独自の設定(開始170ms・間隔50ms)で連続入力する。
        w = self.window
        w.repeat = {"delay_ms": 170, "interval_ms": 50, "soft_interval_ms": 20}
        state = w.state
        col = state.col
        clock = [0.0]
        w._clock = type("C", (), {"elapsed": lambda _self: clock[0]})()
        _key(w, QtCore.Qt.Key.Key_Left)
        _key(w, QtCore.Qt.Key.Key_Left, auto_repeat=True)  # OSのリピートは無視
        self.assertEqual(state.col, col - 1)
        clock[0] = 100
        w._on_tick()
        self.assertEqual(state.col, col - 1, "連続入力の開始が早すぎる")
        clock[0] = 170
        w._on_tick()
        self.assertEqual(state.col, col - 2, "押しっぱなしで連続入力されない")
        clock[0] = 220
        w._on_tick()
        self.assertEqual(state.col, col - 3)
        _release(w, QtCore.Qt.Key.Key_Left)
        clock[0] = 400
        w._on_tick()
        self.assertEqual(state.col, col - 3, "離した後も動き続けている")
        _key(w, QtCore.Qt.Key.Key_Space)
        clock[0] = 800
        w._on_tick()
        self.assertEqual(len(state.history), 1, "ハードドロップが押しっぱなしで連続する")

    def test_soft_drop_repeats_quickly_without_the_move_delay(self) -> None:
        w = self.window
        w.repeat = {"delay_ms": 170, "interval_ms": 50, "soft_interval_ms": 20}
        clock = [0.0]
        w._clock = type("C", (), {"elapsed": lambda _self: clock[0]})()
        row = w.state.row
        _key(w, QtCore.Qt.Key.Key_Down)
        for t in (20, 40, 60):
            clock[0] = t
            w._on_tick()
        self.assertEqual(w.state.row, row + 4, "ソフトドロップが左右移動の待ち時間を待っている")
        self.assertEqual(w.state.history, [])

    def test_clear_label_shows_back_to_back_and_clear_name(self) -> None:
        state = self.window.state
        state.back_to_back, state.last_clear, state.combo = 2, "TSD(Tスピンダブル)", 1
        self.window.refresh()
        text = self.window.clear_label.text()
        self.assertIn("BtoB ×2", text)
        self.assertIn("TSD", text)
        self.assertIn("1 REN", text)

    def test_zero_interval_moves_to_the_wall(self) -> None:
        w = self.window
        w.repeat = {"delay_ms": 100, "interval_ms": 0, "soft_interval_ms": 20}
        clock = [0.0]
        w._clock = type("C", (), {"elapsed": lambda _self: clock[0]})()
        _key(w, QtCore.Qt.Key.Key_Left)
        clock[0] = 100
        w._on_tick()
        self.assertFalse(w.state.move_left(), "壁まで一気に動いていない")

    def test_hold_frame_is_highlighted_after_holding(self) -> None:
        self.assertFalse(self.window.hold_view.highlighted)
        _key(self.window, QtCore.Qt.Key.Key_C)
        self.assertTrue(self.window.hold_view.highlighted, "ホールドした手番で黄色の枠になっていない")
        _key(self.window, QtCore.Qt.Key.Key_Space)
        self.assertFalse(self.window.hold_view.highlighted, "次の手番でも枠が残っている")

    def test_garbage_button_raises_selected_rows(self) -> None:
        self.window.garbage_spin.setValue(3)
        self.window.garbage_btn.click()
        bottom = self.window.state.board[-3:]
        self.assertTrue(all(row.count("GARBAGE") == 9 for row in bottom))

    def test_pad_press_repeat_and_release(self) -> None:
        w = self.window
        state = w.state
        col = state.col
        w._handle_pad_actions({"move_right"}, 0)
        self.assertEqual(state.col, col + 1, "押した瞬間に動かない")
        w._handle_pad_actions({"move_right"}, 100)
        self.assertEqual(state.col, col + 1, "連続入力の開始が早すぎる")
        w._handle_pad_actions({"move_right"}, 200)
        self.assertEqual(state.col, col + 2, "押しっぱなしで連続入力されない")
        w._handle_pad_actions({"rotate_cw"}, 300)
        w._handle_pad_actions({"rotate_cw"}, 600)
        orient = state.orient
        w._handle_pad_actions({"rotate_cw"}, 900)
        self.assertEqual(state.orient, orient, "回転が押しっぱなしで連続する")
        w._handle_pad_actions(set(), 1000)
        self.assertEqual(w._pad_tracker.pressed, set())

    def test_pad_mapping_dialog_assigns_new_press_and_removes_duplicates(self) -> None:
        from src.education.window import PadMappingDialog

        dialog = PadMappingDialog({"hold": ["Button3"], "undo": []}, self.window)
        dialog.start_waiting("undo")
        dialog.feed(set())
        dialog.feed({"Button3"})
        self.assertEqual(dialog.bindings["undo"], ["Button3"])
        self.assertEqual(dialog.bindings["hold"], [], "重複した割り当てが残っている")
        self.assertIsNone(dialog.waiting_for)

    def test_reset_keys_replace_the_state(self) -> None:
        seed = self.window.state.sequence.seed
        _key(self.window, QtCore.Qt.Key.Key_Space)
        _key(self.window, QtCore.Qt.Key.Key_R)
        self.assertEqual(self.window.state.sequence.seed, seed)
        self.assertEqual(self.window.state.history, [])
        self.assertIs(self.window.board_view.state, self.window.state, "盤面の描画が古い状態を見ている")
        _key(self.window, QtCore.Qt.Key.Key_R, QtCore.Qt.KeyboardModifier.ShiftModifier)
        self.assertNotEqual(self.window.state.sequence.seed, seed)

    def test_next_and_hold_views_follow_the_state(self) -> None:
        state = self.window.state
        self.assertEqual([v.piece for v in self.window.next_views], list(state.visible_next()))
        _key(self.window, QtCore.Qt.Key.Key_C)
        self.assertEqual(self.window.hold_view.piece, state.hold)
        self.assertEqual([v.piece for v in self.window.next_views], list(state.visible_next()))

    def test_window_paints_without_error(self) -> None:
        self.window.resize(600, 800)
        image = QtGui.QImage(self.window.size(), QtGui.QImage.Format.Format_ARGB32)
        self.window.render(image)
        self.assertFalse(image.isNull())


if __name__ == "__main__":
    unittest.main()
