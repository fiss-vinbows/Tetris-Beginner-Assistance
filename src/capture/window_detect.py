"""Steam(PC)版ぷよぷよテトリス2のウィンドウ検出(2026-10-30、利用者「Steam版でウィンドウキャプチャする機能を標準機能にしたい」)

PBA(../Puyopuyo/src/capture/window_detect.py)の仕組みをテトリス用にしたもの(最終的に PBA と統合するため、形をそろえる)。

ゲームのウィンドウを探し、その描画領域(クライアント領域。タイトルバー・枠を除く)の中の盤面・HOLD・NEXT枠の位置を、
2560×1440 の描画領域での位置(REFERENCE_LAYOUT)をその大きさに縮めて求める。16:9 でないウィンドウでは、
画面は縦横比を保って中央に描かれる(上下か左右に黒帯)とみなす。手動のキャリブレーション(Switch 対応プラグイン)は要らない。

座標は物理ピクセル(PyQt6 のプロセスは DPI を認識するので、Win32 の座標も物理ピクセルで返る。手動のキャリブレーションと同じ)。
"""

from __future__ import annotations

import ctypes
import json
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from ..paths import app_root
from .calibrate import CalibrationResult
from .screen_capture import CaptureRegion

# 【2026-10-30・利用者のスクリーンショット(テトリスの対戦、ウィンドウの描画領域 2560×1440)で測った位置】
# 盤面は格子の線から(1マス48画素、可視20段)、HOLD・NEXTは黒い箱の中のミノの部分。この位置で、
# 実際の画像認識が 操作中S・HOLD空・NEXT L O I J T・盤面空 と正しく読めることを確かめた(tests/test_window_detect.py)。
REFERENCE_SIZE = (2560, 1440)
REFERENCE_LAYOUT = CalibrationResult(
    board_origin_x=409,
    board_origin_y=211,
    board_width=480,
    board_height=960,
    cell_size=48,
    board_cols=10,
    board_rows=20,
    hold_rect=(263, 263, 124, 77),
    next_rects=[(946, 209, 112, 76), (939, 312, 112, 76), (939, 413, 112, 76), (939, 514, 112, 76), (939, 616, 112, 76)],
)
# 【2026-10-31】2P の盤面・HOLD・NEXT は 1P をそのまま右へずらした位置。
# 最初は縮小されたスクリーンショットで 1269px と測ったが、実機の録画(2560×1440 の原寸)では 10px 右にずれていた。
# おじゃまの穴のマスに隣の明るい縁が入って埋まった行と読まれ、AI が1段ずれた盤面で考えて 2P が止まった
# (debug_log_20261031_095936_2p)。原寸の録画で盤面の左端を 1P と比べて 1259px に直した(tests/test_window_detect.py)
P2_OFFSET_X = 1259
GAME_EXE_NAMES = ("puyopuyotetris2.exe",)
# ウィンドウのタイトル(利用者のスクリーンショットでは「PuyoPuyoTetris2」)
GAME_TITLE_KEYS = ("puyopuyotetris2", "ぷよぷよテトリス2")
# メイン画面の「ゲームのウィンドウを検出」で一覧から選んだウィンドウ(実行ファイル名とタイトル)。次からはこれでも探す
SAVED_WINDOW_PATH = app_root() / "config" / "game_window.json"
# 一覧に出すウィンドウの最小の大きさ(小さい道具のウィンドウを除く)
MIN_LIST_SIZE = (320, 180)


@dataclass(frozen=True)
class GameWindow:
    hwnd: int
    title: str
    left: int  # クライアント領域の左上(画面の物理ピクセル)
    top: int
    width: int
    height: int

    def region(self) -> CaptureRegion:
        return CaptureRegion(left=self.left, top=self.top, width=self.width, height=self.height)


@dataclass(frozen=True)
class SavedWindow:
    """利用者が選んだゲームのウィンドウ。exe(小文字のファイル名)が合えばそれ、無ければ title(正規化して一致)で探す。"""

    exe: str = ""
    title: str = ""

    def matches(self, title: str, exe: str) -> bool:
        if self.exe:
            return exe == self.exe
        return bool(self.title) and normalize_title(title) == normalize_title(self.title)


def load_saved_window(path: Path | None = None) -> SavedWindow | None:
    path = SAVED_WINDOW_PATH if path is None else path  # 呼んだ時点の置き場所(テストで差し替えられる)
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        saved = SavedWindow(exe=str(data.get("exe", "")).lower(), title=str(data.get("title", "")))
    except (OSError, ValueError, AttributeError):
        return None
    return saved if saved.exe or saved.title else None


def save_saved_window(saved: SavedWindow, path: Path | None = None) -> None:
    path = Path(SAVED_WINDOW_PATH if path is None else path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"exe": saved.exe, "title": saved.title}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_title(title: str) -> str:
    """比べやすいタイトル(™・®・記号・空白を除き、全角を半角に、小文字に)。"""
    title = "".join(c for c in title if c not in "™®©")
    return "".join(c for c in unicodedata.normalize("NFKC", title).lower() if c.isalnum())


def is_game_title(title: str) -> bool:
    norm = normalize_title(title)
    return any(key in norm for key in GAME_TITLE_KEYS)


def is_game_window(title: str, exe: str, saved: SavedWindow | None = None) -> bool:
    """ゲームのウィンドウか(決め打ちのタイトル・実行ファイル名か、利用者が選んだもの)。"""
    return is_game_title(title) or exe in GAME_EXE_NAMES or (saved is not None and saved.matches(title, exe))


def content_rect(width: int, height: int) -> tuple[float, float, float]:
    """クライアント領域の中で画面が描かれる位置(左の余白, 上の余白, REFERENCE_SIZE に対する倍率)。"""
    rw, rh = REFERENCE_SIZE
    scale = min(width / rw, height / rh)
    return (width - rw * scale) / 2, (height - rh * scale) / 2, scale


def layout_calibration(window: GameWindow, side: str = "1p") -> CalibrationResult:
    """ウィンドウの大きさから求めた盤面・HOLD・NEXT枠(画面の物理ピクセル)。

    side: "1p"(左の盤面) / "2p"(右の盤面。ローカル対戦で 2P も全自動で動かす時)。
    """
    ox, oy, scale = content_rect(window.width, window.height)
    ox += window.left
    oy += window.top
    ref = REFERENCE_LAYOUT
    if side == "2p":
        ox += P2_OFFSET_X * scale

    def rect(r: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        x, y, w, h = r
        return round(ox + x * scale), round(oy + y * scale), round(w * scale), round(h * scale)

    left, top = round(ox + ref.board_origin_x * scale), round(oy + ref.board_origin_y * scale)
    return CalibrationResult(
        board_origin_x=left,
        board_origin_y=top,
        # 右端・下端を丸めてから幅を出す(幅を丸めると端が1px ずれることがある)
        board_width=round(ox + (ref.board_origin_x + ref.board_width) * scale) - left,
        board_height=round(oy + (ref.board_origin_y + ref.board_height) * scale) - top,
        cell_size=max(1, round(ref.cell_size * scale)),
        board_cols=ref.board_cols,
        board_rows=ref.board_rows,
        hold_rect=rect(ref.hold_rect),
        next_rects=[rect(r) for r in ref.next_rects],
    )


# ---- Win32(Windows だけ) ----

def _exe_name(pid: int) -> str:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_wchar_p,
                                                    ctypes.POINTER(ctypes.c_uint32)]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_uint32(len(buf))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        return buf.value.replace("/", "\\").rsplit("\\", 1)[-1].lower()
    finally:
        kernel32.CloseHandle(handle)


def client_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """ウィンドウのクライアント領域(左, 上, 幅, 高さ。画面の物理ピクセル)。最小化中・閉じた時は None。"""
    if sys.platform != "win32":
        return None
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    if not user32.IsWindow(hwnd) or user32.IsIconic(hwnd):
        return None
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    origin = wintypes.POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        return None
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None
    return origin.x, origin.y, width, height


def title_bar_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """ウィンドウのタイトルバー(左, 上, 幅, 高さ。画面の物理ピクセル)。枠なし・全画面・読めない時は None(PBA と同じ)。"""
    if sys.platform != "win32":
        return None
    from ctypes import wintypes

    client = client_rect(hwnd)
    if client is None:
        return None
    rect = wintypes.RECT()
    try:  # 見えている枠(Windows 10 以降は GetWindowRect に見えない縁が入るので DWM に聞く)
        dwmapi = ctypes.WinDLL("dwmapi")
        dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        ok = dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) == 0  # DWMWA_EXTENDED_FRAME_BOUNDS
    except OSError:
        ok = False
    if not ok:
        user32 = ctypes.WinDLL("user32")
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
    height = client[1] - rect.top
    if height < 16:
        return None
    return rect.left, rect.top, rect.right - rect.left, height


@dataclass(frozen=True)
class WindowEntry:
    """表示中のウィンドウ(一覧から選ぶ用)。"""

    window: GameWindow
    exe: str


def list_windows() -> list[WindowEntry]:
    """表示中でタイトルのある、ある程度大きいウィンドウ(画面の手前から順)。Windows 以外は空。"""
    if sys.platform != "win32":
        return []
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [enum_proc, wintypes.LPARAM]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    found: list[WindowEntry] = []

    def visit(hwnd, _lparam):  # noqa: ANN001, ANN202
        # 例外を外に出すと EnumWindows が途中で止まるので、1つのウィンドウの失敗は飛ばして続ける(PBA の実機の教訓)
        try:
            if not hwnd or not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            rect = client_rect(hwnd)
            if rect is None or rect[2] < MIN_LIST_SIZE[0] or rect[3] < MIN_LIST_SIZE[1]:
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            try:
                exe = _exe_name(pid.value)
            except OSError:
                exe = ""
            found.append(WindowEntry(GameWindow(int(hwnd), buf.value, *rect), exe))
        except Exception:  # noqa: BLE001
            pass
        return True

    user32.EnumWindows(enum_proc(visit), 0)
    return found


def find_game_window(saved: SavedWindow | None = None, windows: list[WindowEntry] | None = None) -> GameWindow | None:
    """表示中のぷよぷよテトリス2 のウィンドウ(実行ファイル名・タイトル、または利用者が選んだもの)。複数あれば一番大きいもの。
    Windows 以外・見つからない時は None。windows はテスト用(既定は list_windows())。"""
    if saved is None:
        saved = load_saved_window()
    entries = list_windows() if windows is None else windows
    found = [e.window for e in entries if is_game_window(e.window.title, e.exe, saved)]
    if not found:
        return None
    return max(found, key=lambda w: w.width * w.height)
