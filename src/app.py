"""アプリ本体: メインウィンドウ + 支援モードのリアルタイムループ

通常時は設定用の不透明ウィンドウ（キャリブレーション実行・支援モード切り替え）として動作する。
「支援モード開始」を押すと、
  1. メインウィンドウを隠し
  2. 盤面周辺だけをカバーする透過・クリックスルーのオーバーレイウィンドウ(OverlayWindow)
  3. クリックスルーなしの小さな終了バッジ(ControlBadge)
を表示し、一定間隔でキャプチャ→盤面認識→最善手探索→オーバーレイ描画のループを回す。

安全設計の方針（過去に画面全体が操作不能になった事故を踏まえたもの）:
- オーバーレイは画面全体ではなく、盤面+HOLD+NEXT欄周辺の限定領域のみをカバーする
- クリックスルーのオーバーレイとは別に、クリックスルーなしの終了ボタン(ControlBadge)を必ず表示する
- 一定時間操作がなければ自動的に通常モードへ戻るセーフティタイマーを持つ

注意: 終了操作はクリックのみ（Escキーは意図的に使わない）。
以前Escキーショートカットを併用していたが、ゲーム側もポーズ操作にEscキーを
使うことが多く、オーバーレイ/バッジがフォーカスを奪うとゲームのポーズ操作を
横取りしてしまい、ユーザーがポーズしただけで支援モードが意図せず終了する事故が
実際に発生した。WA_ShowWithoutActivatingでフォーカス自体を奪わないようにした上で、
Escショートカットの実装自体も廃止している。
"""

from __future__ import annotations

import colorsys
import ctypes
import shutil
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass
from dataclasses import replace as dataclass_replace
from typing import NamedTuple
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# start.batを`pythonw`(コンソールウィンドウを表示しない実行形式)で起動した
# 場合、sys.stdout/stderrはNoneになる。この状態でprint()を呼ぶと
# AttributeErrorでワーカースレッドごとクラッシュしてしまうため、
# 起動直後にダミーの書き込み先へ差し替えて安全にする。
if sys.stdout is None or sys.stderr is None:
    import os

    _devnull = open(os.devnull, "w")
    if sys.stdout is None:
        sys.stdout = _devnull
    if sys.stderr is None:
        sys.stderr = _devnull

from PyQt6 import QtCore, QtGui, QtWidgets

from src.capture.calibrate import CONFIG_PATH, CalibrationResult, load_calibration, run_calibration
from src.capture.screen_capture import CaptureRegion, ScreenCapture
from src.engine.board_state import BoardState
from src.engine.cold_clear_client import ColdClearClient, ColdClearMove
from src.engine.openers import (
    OpenerForm,
    OpenerStep,
    OpenerTemplate,
    apply_step,
    choose_form,
    choose_opener,
    known_sequence,
)
from src.overlay.renderer import (
    PLAN_DOT_ALPHA,
    PLAN_DOT_RADIUS_RATIO,
    PlanStep,
    LANDING_DOT_OUTLINE_WIDTH,
    LANDING_DOT_RADIUS_RATIO,
    BoardLayout,
    OverlayDrawData,
    render_overlay,
)
from src.vision.board_reader import RGB, read_board_grid_with_samples
from src.vision.next_hold_reader import read_patch, read_piece_from_patch
from src.vision.piece_colors import ALL_PIECE_NAMES, I_J_VALUE_THRESHOLD, PIECE_COLORS
from src.vision.shape_matcher import match_piece_shape

OVERLAY_MARGIN = 40

# 認識失敗がこの回数連続したら、古い最善手を表示し続けず消す
# (ライン消去演出等の瞬間的な失敗は許容しつつ、ポーズ画面などの継続的な失敗には対応する)
MAX_CONSECUTIVE_RECOGNITION_FAILURES = 5

# Cold Clear 2との通信で起こりうる例外。応答なし(TimeoutError)、パイプ破損
# (OSError/ValueError)、プロセス終了(RuntimeError)、不正な応答(JSON)を含む。
# AIの不調は認識・表示を巻き込んで止める理由にならないため、まとめて受け止める。
COLD_CLEAR_ERRORS = (TimeoutError, OSError, ValueError, RuntimeError)

# 何かトラブルで終了操作ができなくなった場合の保険。この時間が経つと自動的に通常モードへ戻る。
SAFETY_TIMEOUT_MS = 10 * 60 * 1000  # 10分

# 認識結果デバッグログの出力先。最善手が実際の盤面と食い違って見える時、
# AIがそのtickで何を認識していたかを突き合わせて確認するために使う。
DEBUG_LOG_PATH = Path(__file__).resolve().parent.parent / "debug_log.txt"

# このapp.pyモジュールが最初にimportされた（＝プロセスが起動した）時点での
# app.py自身の最終更新時刻。モジュールレベルで一度だけ評価されるため、
# その後app.pyがファイルシステム上で書き換えられても値は変わらない。
# 以前は「支援モード開始」のたびにPath(__file__).stat().st_mtime()を
# その場で読み直していたが、これは常に「ファイルの現在の状態」を返すだけで、
# 「今動いているプロセスが実際にどのバージョンのコードを読み込んで起動したか」
# とは無関係だった。Pythonは一度importしたモジュールをメモリに保持し続け、
# ファイルが後から変更されてもプロセスを再起動しない限りコードは古いまま
# なので、メインウィンドウを再起動せずに支援モードの開始・終了だけを
# 繰り返すと、ログには常に「最新のタイムスタンプ」が記録されてしまい、
# 実際には古いコードのまま動いていることを検出できないという重大な欠陥が
# あった。モジュール読み込み時に固定することで、この矛盾を解消する。
_APP_MODULE_LOAD_TIME = datetime.fromtimestamp(Path(__file__).stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")

# 実際にキャリブレーション座標で切り出した生画像の保存先（直近1回分を上書き）。
# テキストログだけでは分からない「座標そのもののズレ」を画像で直接確認するため。
DEBUG_FRAMES_DIR = Path(__file__).resolve().parent.parent / "debug_frames"

# 支援モード中の画面録画(暫定機能)の保存先。実機での不具合報告のたびに
# 別途画面録画ソフトで撮り直すのが手間だという要望を受け、キャリブレーション
# 済みの撮影範囲(盤面+HOLD+NEXT欄)をアプリ自身で録画できるようにする。
# 支援モード開始のたびに上書きする(直近1回分のみ保持)。
DEBUG_VIDEO_PATH = Path(__file__).resolve().parent.parent / "debug_capture.mp4"

# 画面録画の目標フレームレート。毎tick(IDLE_SLEEP_MS=8ms間隔)書き出すと
# ファイルサイズ・エンコード負荷が過大になるため間引く。人間が後から見て
# 状況を追うには15fps程度で十分。
VIDEO_RECORD_FPS = 15.0

# 提案が実際に変化した瞬間ごとに、debug_framesの内容をタイムスタンプ付きで
# ローテーション保存する履歴フォルダ。DEBUG_FRAMES_DIRは常に「直近1回分を
# 上書き」するだけなので、ユーザーが「今おかしい」と気づいた時には既に
# 上書きされてしまい、問題の瞬間を後から確認できないという指摘を受けて
# 導入した。「提案が変化した瞬間」だけを対象にすることで、保存件数を
# 現実的な数に抑えつつ、揺れ・点滅の原因調査に必要な画像を確実に残す。
DEBUG_FRAMES_HISTORY_DIR = Path(__file__).resolve().parent.parent / "debug_frames_history"
FRAME_HISTORY_SIZE = 40


def _settled_top_row(grid: list[list[str | None]]) -> int:
    """着地済みブロックの最上段の行インデックスを返す。

    盤面の一番下から上に向かって「ある程度埋まっている行」が連続する限り遡り、
    それ未満の行が現れたところで打ち切る。着地済みブロックの上端を求めることで、
    それより下を「着地済み領域」、上を「操作中ピースが存在しうる領域」として区別する。
    全行が空ならlen(grid)を返す。

    「1マスでもブロックがあれば非空行」という判定だと、盤面中腹の1マスだけの
    ノイズ誤検出（透かし絵柄等）がそのままsettled_top_rowを大きく狂わせてしまう
    （そこから最下段まで「連続した非空行」とみなされてしまうため）。

    これを「2マス以上埋まっている行だけを非空とみなす」で回避していたが、
    縦向きミノの先端のように実際に1マスだけ積み上がっている行まで除外して
    しまい、_build_settled_boardがその行を丸ごと捨てるため、AIにも
    is_placement_physically_validにも既存ブロックが見えなくなっていた。
    実機で、既に置かれているJミノの上にZミノの提案ドットが重なる不具合として
    確認された(18:22:48、settled_top_row=18で行17の青ブロックが盤面から欠落)。

    そこでマスの数ではなく「支えの有無」で判定する。テトリスの重力の性質上、
    宙に浮いた孤立マスは存在しえないため、最下段にあるか真下にブロックが
    あるマスだけを実在とみなせば、ノイズ除去の目的を保ったまま、1マスしか
    積まれていない実在の行を消さずに済む。

    さらに、最下段付近の1行だけがノイズ（ライン消去エフェクトの閃光等で
    一時的に色判定が乱れる）で「空」扱いになると、そこで即座に打ち切られて
    しまい、実際にはまだ大量のブロックが残っている盤面全体を「空」と誤認識
    してしまう重大な問題が実機ログで確認された（着地済み領域はテトリスの
    重力の性質上「下の行が空なのに上の行が埋まっている」ことは物理的に
    ありえないため、1行だけの空判定はほぼ確実にノイズである）。そのため、
    空行が_SETTLED_ROW_MAX_SKIP行以内であれば無視してさらに上まで遡り、
    それを超えて連続したら本当に空領域とみなして打ち切る。
    """
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    top = rows
    consecutive_empty = 0
    for r in range(rows - 1, -1, -1):
        supported = 0
        for c in range(cols):
            if grid[r][c] is None:
                continue
            # 最下段、または同じ列の下方にブロックがあるマスだけを
            # 「支えのある実在のブロック」とみなす。真下1マスではなく
            # 下方全体を見るのは、_SETTLED_ROW_MAX_SKIPで許容している
            # 「ノイズで1行だけ空に見える行」を挟んでも支えを見失わない
            # ようにするため。宙に浮いた孤立マス(透かし絵柄等の誤検出)は
            # 下に何も無いため、従来どおり除外される。
            if r == rows - 1 or any(grid[rr][c] is not None for rr in range(r + 1, rows)):
                supported += 1
        if supported >= 1:
            top = r
            consecutive_empty = 0
        else:
            consecutive_empty += 1
            if consecutive_empty > _SETTLED_ROW_MAX_SKIP:
                break
    return top


def _falling_piece_search_limit(grid: list[list[str | None]]) -> int:
    """操作中ミノを探す範囲の下限（この行より上を探索する）を返す。

    【_settled_top_rowと別の規則を使う理由】
    以前はこの2つを同じ1つの行インデックスで兼ねていた。しかし両者が
    求めるものは正反対である。

      ・着地済み盤面(_settled_top_row)  : 実在するブロックを取りこぼさない
                                          よう、できるだけ多くの行を含めたい
      ・操作ミノの探索範囲(この関数)     : 落下中のミノを見落とさないよう、
                                          できるだけ広い範囲を残したい

    1つの値で分割している限り、片方を広げれば必ずもう片方が狭まる。
    実際、着地済み判定を「支えの有無」に変えて包含的にしたところ、高積み時に
    落下中のミノが着地済み領域へ取り込まれ、操作ミノの検出失敗率が
    実測で77%→81%に悪化した(空中のミノも同じ列の下方にブロックがあるため、
    支えがあると判定されてしまう)。

    そこで探索範囲側は保守的な規則を使う。「2マス以上埋まっている行」だけを
    着地済みとみなすため、1〜4マスしかない落下中のミノを取り込みにくい。
    その分、探索範囲と着地済み盤面は重なりうるが、重なった領域で検出した
    操作ミノのセルはrecognize()が盤面から個別に取り除く。
    """
    rows = len(grid)
    top = rows
    consecutive_empty = 0
    for r in range(rows - 1, -1, -1):
        if sum(1 for cell in grid[r] if cell is not None) >= 2:
            top = r
            consecutive_empty = 0
        else:
            consecutive_empty += 1
            if consecutive_empty > _SETTLED_ROW_MAX_SKIP:
                break
    return top


# _settled_top_row参照。ライン消去エフェクト等による1行だけの一時的な
# 認識ノイズを許容するための、連続空行の許容枚数。
_SETTLED_ROW_MAX_SKIP = 1




def _connected_component(
    grid: list[list[str | None]], start_r: int, start_c: int, row_limit: int
) -> set[tuple[int, int]]:
    """(start_r, start_c)から色を問わず非Noneセルが4方向連結している集合を返す(row_limit行目までに限定)。

    色ではなく「何かブロックがあるかどうか」だけで連結判定することで、
    盤面認識のノイズで一部セルの色判定がわずかにブレても塊として拾える。
    """
    cols = len(grid[0])
    visited: set[tuple[int, int]] = set()
    stack = [(start_r, start_c)]
    while stack:
        r, c = stack.pop()
        if (r, c) in visited:
            continue
        if r < 0 or r >= row_limit or c < 0 or c >= cols:
            continue
        if grid[r][c] is None:
            continue
        visited.add((r, c))
        stack.extend([(r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)])
    return visited


def _resolve_i_j(
    component: set[tuple[int, int]],
    grid: list[list[str | None]],
    samples: list[list[RGB]],
) -> str:
    """I/Jは色相が近く、セルごとに独立してclassify_colorすると（グロス効果による
    明度ムラのせいで）セルによってI/J判定がバラバラになり、多数決の結果が
    不安定になることが実機で確認された。そのため、連結成分内でI/Jと判定された
    セルの生サンプルを集め、明度の中央値でI/Jを1回だけ判定し直す。
    """
    values = [
        colorsys.rgb_to_hsv(samples[rr][cc].r / 255, samples[rr][cc].g / 255, samples[rr][cc].b / 255)[2]
        for rr, cc in component
        if grid[rr][cc] in ("I", "J")
    ]
    if not values:
        return "J"
    median_v = statistics.median(values)
    return "I" if median_v >= I_J_VALUE_THRESHOLD else "J"


class CurrentPieceDetection(NamedTuple):
    """操作中ミノの検出結果。

    cells: そのミノが占めるセル座標。探索範囲と着地済み盤面が重なりうる
    設計(_falling_piece_search_limit参照)になったため、着地済み盤面から
    操作ミノを取り除くには「どの行より上か」ではなく実際のセルが要る。
    """

    piece: str
    min_row: int
    cells: frozenset[tuple[int, int]]


def _is_resting_on_stack(grid: list[list[str | None]], cells: frozenset[tuple[int, int]]) -> bool:
    """推定した操作ミノが、着地済みブロックか床の上に載っているか。

    ミノのいずれかのマスの真下(自分のマスを除く)が最下段の外かブロックなら
    「載っている」。落下中のミノは真下が空いている。

    【なぜ必要か(2026-09-11実機ログ)】置いたばかりの縦向きIミノが、積みの
    上端より4段突き出しているため、次のミノがスポーンしたtickでも「落下中の
    操作ミノ」と推定され、そのセルが着地済み盤面から除外されてAIへ渡って
    いた。AIはそのIの上にZを提案し、既存ブロックと重なる「干渉」になった。
    9/10の対策は操作ミノの「種類」をNEXT履歴に切り替えたが、セルの除外は
    画像の推定のまま残っていた。載っているミノは(操作中であれ置いた直後で
    あれ)そのマスに配置できないので、盤面に含めておく方が安全である。
    """
    rows = len(grid)
    for r, c in cells:
        if (r + 1, c) in cells:
            continue
        if r + 1 >= rows or grid[r + 1][c] is not None:
            return True
    return False


def _infer_current_piece(
    grid: list[list[str | None]],
    samples: list[list[RGB]],
    previous_piece_hint: str | None = None,
    search_limit: int | None = None,
) -> CurrentPieceDetection | None:
    """操作中ピースを推定する。

    操作中のピースはスポーン直後の盤面最上部だけでなく、ソフトドロップ/ハードドロップで
    素早く下まで移動することも多く、盤面のどこにあってもおかしくない。そのため、
    「着地済みブロックの上端(_settled_top_row)より上」という判定だけを使い、
    固定の行数(盤面上端何行、等)には制限しない
    （以前は上端4行にしか探索範囲を限定しておらず、ミノが少し下に降りただけで
    検出できなくなる欠陥があった）。

    相手からの攻撃でGARBAGE(おじゃまブロック)が上部までせり上がっている場合があるため、
    実ミノ7種(ALL_PIECE_NAMES)以外は対象から除外する。

    さらに、透かし絵柄等のノイズで1マスだけ誤判定されるケースに対応するため、
    テトリミノが4マスの塊であることを利用する。判定は色ではなく、まず形状
    （4マスの相対配置）で行う。テトリミノは7種・全回転状態を通じて形状が
    完全に一意（重複なしを事前検証済み）なため、色ベースの判定（グロス効果に
    よる明度ムラ、I/Jの色相が非常に近い等で実機で誤判定が頻発した）より
    ずっと頑健。4マスきちんと検出できた場合は形状マッチングのみで判定し、
    3マスしか見えない（一部が隠れている等）場合のみ、色の多数決にフォールバックする。
    5マス以上の大きな塊(着地済みブロックとの誤結合等)は信頼しない。

    previous_piece_hint: 直前に確定していた操作中ミノ種(呼び出し側が保持する
    状態)。色の多数決フォールバックが使われるのは「4マスの形状マッチングが
    使えない(3マスしか見えない、または未知の形になっている)」場合に限られ、
    これはミノが下まで移動して既存ブロックと部分的に重なって見える最中に
    ほぼ限られる(新規スポーン直後は常に4マスとも視界良好なため)ため、
    直前と同じミノである可能性が極めて高い。そのため、色の多数決フォール
    バックに入った時点で、previous_piece_hintが使えるなら常にそちらを
    優先する(I/Jに限定していた頃は、実機ログでZ↔Iのように別の組み合わせ
    でも盤面・HOLD・NEXT欄が一切変わっていないのにcurrent判定だけが往復
    する不具合が確認され、色の多数決自体がこの関数内で最も信頼性の低い
    経路であることが判明したため、対象をI/Jに限定せず全ミノ種に広げた)。
    ヒントが使えない場合のみ、I/J限定の明度中央値判定(_resolve_i_j)に
    フォールバックする。本当に新しいミノがスポーンした場合は、スポーン
    直後は4マスとも視界良好なので上の形状マッチングで正しく判定される
    ため、この優先付けによる実害はない。

    search_limit: 探索対象を「この行より上」に限定する境界。呼び出し側が
    省略した場合は_settled_top_row(grid)をそのまま使うが、recognize()は
    ピースの誤混入対策のデバウンスを適用した実効値を明示的に渡す
    (詳細はrecognize()のコメント参照)。
    """
    if search_limit is None:
        search_limit = _settled_top_row(grid)
    checked: set[tuple[int, int]] = set()
    for r in range(search_limit):
        for c, cell in enumerate(grid[r]):
            if (r, c) in checked or cell not in ALL_PIECE_NAMES:
                continue
            component = _connected_component(grid, r, c, search_limit)
            checked |= component
            min_row = min(rr for rr, _cc in component)
            if len(component) == 4:
                shape_result = match_piece_shape(component)
                if shape_result is not None:
                    return CurrentPieceDetection(shape_result, min_row, frozenset(component))
            if 3 <= len(component) <= 4:
                # 形状が一致しなかった(4マス揃っているのに未知の形、通常は
                # 認識ノイズで実際は他のブロックと誤結合している等)場合や、
                # 3マスしか見えない場合は、色の多数決にフォールバックする。
                colors = Counter(
                    grid[rr][cc] for rr, cc in component if grid[rr][cc] in ALL_PIECE_NAMES
                )
                if colors:
                    best_color = colors.most_common(1)[0][0]
                    if previous_piece_hint in ALL_PIECE_NAMES:
                        # 実機ログで、I/J以外の組み合わせ(例: Z↔I)でも、
                        # 盤面・HOLD・NEXT欄が一切変わっていないのに
                        # current判定だけが往復する不具合が確認された。
                        # 4マスの形状マッチングが使えない(=3マスしか
                        # 見えていない、または未知の形になっている)時点で、
                        # 色の多数決による判定自体がこの関数の中で最も
                        # 信頼性が低い経路であり、I/J以外の組み合わせでも
                        # 同種の誤判定が起こり得ることが判明したため、
                        # 対象をI/Jに限定せず、直前の確定値が使える場合は
                        # 常にそちらを優先する(本当に新しいミノがスポーン
                        # した場合は、スポーン直後は4マスとも視界良好なので
                        # 上の形状マッチングで正しく判定されるため実害はない)。
                        best_color = previous_piece_hint
                    elif best_color in ("I", "J"):
                        best_color = _resolve_i_j(component, grid, samples)
                    return CurrentPieceDetection(best_color, min_row, frozenset(component))
    return None


def _bridge_looks_like_falling_piece(bridge_rows: list[list[str | None]]) -> bool:
    """空行を1行分だけ許容して橋渡しされた行(_settled_top_row参照)の中身が、
    操作中ミノそのものである可能性が高いかどうかを判定する。

    実機ログ(2026-09-06)で、操作中ミノ(current_pieceは変化していない)が
    着地済み領域のすぐ上を落下している間、そのミノ自身の行が着地済み
    領域として誤って橋渡しされ続ける不具合が確認された。当初は「2tick
    連続で同じ値になったら確定する」という他のデバウンスと同じ手法を
    試みたが、テトリスの重力が緩やかな場面ではミノが何十tickも同じ行に
    静止し続けることがあり(実機ログでも、current=Zのまま複数tickにわたり
    盤面上の同じ位置に"Z"の残骸が現れ続けるパターンを確認)、何tick待っても
    「本物の設置」と区別がつかず時間ベースのデバウンスでは原理的に解決
    できないと判明した。

    そこで単一フレームの情報だけで判定できる2つの構造的な手がかりを使う。

    (1) 橋渡し区間の中に「1マスも埋まっていない完全な空行」が実在するか。
    本物の設置(ミノが着地済み地形に直接隣接している)であれば、ミノは
    必ずどこかの行で着地済み地形と接しているため、橋渡し区間の中に
    完全な空行が入り込む余地はない(L/J/T等は着地時でも1マスしか埋まって
    いない行が自然にあるが、それは「疎ら」であって「完全に空」ではない
    ため誤検知しない)。逆に、まだ宙に浮いているミノと着地済み地形の間には
    必ず本物の隙間(完全な空行)が存在する。この完全な空行の有無だけが、
    「疎らな行を含む本物の設置」と「宙に浮いているミノ」を単一フレームで
    確実に区別できる手がかりになる。

    (2) 完全な空行が存在する場合に限り、空行を除いた非空マスの合計が
    4マス以下(一部が隠れていれば3マス以下)のひとかたまりであるかも
    確認する。操作中ミノは常にちょうど4マスなので、これに一致しない
    (5マス以上、または複数の塊に分かれている)場合は、たまたま盤面の
    奥深くに完全な空行のノイズが生じただけの別の状況である可能性が高く、
    ここでは踏み込んで棄却しない。
    """
    if not any(all(cell is None for cell in row) for row in bridge_rows):
        return False
    filled = [
        (r, c) for r, row in enumerate(bridge_rows) for c, cell in enumerate(row) if cell is not None
    ]
    if not filled or len(filled) > 4:
        return False
    cols = len(bridge_rows[0]) if bridge_rows else 0
    visited: set[tuple[int, int]] = set()
    stack = [filled[0]]
    while stack:
        r, c = stack.pop()
        if (r, c) in visited:
            continue
        visited.add((r, c))
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < len(bridge_rows) and 0 <= nc < cols and bridge_rows[nr][nc] is not None:
                stack.append((nr, nc))
    return visited == set(filled)


# NEXTの移動量を推定する際に考慮する最大の進行数。これを超える進行は
# 「取りこぼし」とみなし、履歴から操作ミノを決めずに再同期へ委ねる。
_MAX_NEXT_SHIFT = 2

# 移動量を確定するために必要な、前回の確定値と一致した枠の最小数。
# 5枠のうち最低2つが読めて一致することを条件にする(有識者資料の
# 「NEXT5のうち最低2つを読み、残りを記憶する」方針に対応)。
_MIN_NEXT_SLOT_MATCHES = 2


def _estimate_next_shift(
    baseline: tuple[str | None, ...], observed: tuple[str | None, ...]
) -> int | None:
    """観測したNEXT5枠が、前回の確定値から何個進んだ結果かを推定する。

    一意に決められない場合はNoneを返す（＝この観測では判断しない）。

    【「1枠でも違えば進行」をやめた理由】
    以前は「読めた枠のどれか1つでも前回と違えば、窓全体が1つ繰り上がった」と
    みなしていた。しかしこれは1枠の誤読がそのまま1手の進行として記録される
    ことを意味する。確定値は自分自身を基準に更新されるため、一度ずれると
    元に戻る仕組みがなく、ずれが累積し続ける。

    実機で、認識の部分成功を導入して「操作ミノが読めないtick」も手番判定へ
    到達するようになった結果、NEXT欄が乱れやすい高積み局面でこの誤進行が
    多発した。next_advancedが168回/分(通常の3〜5倍)発火し、そのうち66%は
    NEXT列が変わっていないのに発火していた。ずれた履歴から求めた操作ミノで
    AIへ質問→結果を棄却→画像へ再同期→再計算、という高速振動になっていた。

    そこで、移動量の候補(0〜_MAX_NEXT_SHIFT個)それぞれについて観測と
    前回値の一致・不一致を数え、不一致がなく十分な一致数を持つ候補が
    ちょうど1つに定まるときだけ、その移動量を採用する。候補が絞れなければ
    「まだ分からない」として観測を続ける(推測で進行を決めない)。
    """
    scores: dict[int, int] = {}
    for shift in range(_MAX_NEXT_SHIFT + 1):
        matches = 0
        mismatched = False
        for i, value in enumerate(observed):
            if value is None:
                continue  # この枠は読めなかった。判断材料にしない。
            j = i + shift
            if j >= len(baseline) or baseline[j] is None:
                continue  # 前回値が無い位置。捏造せず比較対象から外す。
            if value == baseline[j]:
                matches += 1
            else:
                mismatched = True
                break
        if not mismatched and matches >= _MIN_NEXT_SLOT_MATCHES:
            scores[shift] = matches
    if len(scores) != 1:
        # 候補が無い(どの移動量でも説明できない)か、複数残って一意に
        # 決まらない。どちらの場合も推測で進めない。
        return None
    return next(iter(scores))


def _find_single_slot_conflict(
    baseline: tuple[str | None, ...], observed: tuple[str | None, ...]
) -> tuple[int, int, str] | None:
    """観測が「基準のちょうど1枠だけ」と矛盾している場合、その枠を特定する。

    戻り値: (移動量, 矛盾している基準側の枠番号, 観測された値)。
    不一致が1枠・一致が_MIN_NEXT_SLOT_MATCHES以上の移動量候補がちょうど
    1つに定まらなければNone。

    【なぜ必要か(残課題2-2・2026-09-11実機ログ)】ゲーム開始のカウント
    ダウン表示(オレンジ色の大きな数字)がNEXT5枠目に重なり、5枠目が
    数秒間一貫して「L」と誤読された。同じ誤読が複数tick続くため
    「別の観測と一致したら確定」では除外できず、基準に誤りが残る。
    _estimate_next_shiftは不一致ゼロを要求するので、以後どの移動量でも
    説明できず、再アンカーまでNEXTの進行が止まって2手目の提案が出なかった
    (2セッション連続で同じ症状)。矛盾が1枠に限られるなら、その枠だけを
    再確認して補正できる(呼び出し側で「同じ枠・同じ値の矛盾が2tick
    続いたら基準を置き換える」として使う)。
    """
    found: tuple[int, int, str] | None = None
    for shift in range(_MAX_NEXT_SHIFT + 1):
        matches = 0
        conflicts: list[tuple[int, str]] = []
        for i, value in enumerate(observed):
            if value is None:
                continue
            j = i + shift
            if j >= len(baseline) or baseline[j] is None:
                continue
            if value == baseline[j]:
                matches += 1
            else:
                conflicts.append((j, value))
        if len(conflicts) == 1 and matches >= _MIN_NEXT_SLOT_MATCHES:
            if found is not None:
                return None  # 候補が複数あり一意に決まらない
            found = (shift, conflicts[0][0], conflicts[0][1])
    return found


# おじゃまブロックのせり上がりとして許容する最大行数。これを超える変化は
# せり上がりとみなさず、通常の盤面変化として扱う。
_MAX_GARBAGE_RISE = 6


def _detect_garbage_rise(
    previous: tuple[tuple[str | None, ...], ...],
    current: tuple[tuple[str | None, ...], ...],
) -> int:
    """盤面全体が何行せり上がったかを返す。せり上がっていなければ0。

    相手の攻撃でおじゃまブロックが下から挿入されると、既存の積みがそのまま
    上へ移動する。「前回の盤面の各行が、今回の盤面で同じ内容のままN行だけ
    上にある」ことを確認して判定する(有識者資料[049])。

    ミノの固定(4マス増える)やライン消去(下方向へ移動)では、全行が揃って
    上へ移動するという条件を満たさないため、それらと区別できる。

    【なぜこれが必要か】
    仕様は「最善手は、相手からの妨害で段がせりあがる場合を除き、表示を
    切り替えない」であり、せり上がりは提案を切り替えてよい明示的な例外で
    ある。しかし実装のsignificant_changeはネクストの進行しか見ておらず、
    この例外が存在しなかった。そのため攻撃を受けて着地位置が丸ごとずれても、
    次にミノを置くまで提案が再計算されず、利用者は自分で判断するしか
    なくなっていた(実機で「相手の攻撃に追い付かない」として報告された)。
    """
    rows = len(previous)
    if rows == 0 or len(current) != rows or current == previous:
        return 0
    width = len(previous[0]) if previous[0] else 0
    if width == 0:
        return 0
    for rise in range(1, min(_MAX_GARBAGE_RISE, rows) + 1):
        # 前回の行rが、今回は行r-riseに来ているはず。
        if not all(previous[r] == current[r - rise] for r in range(rise, rows)):
            continue
        # 押し出された上端rise行は、前回すべて空だったはず。
        # (天井まで積んでいる場合は情報が失われるので判定しない)
        if not all(all(cell is None for cell in previous[r]) for r in range(rise)):
            continue
        # 下端に現れたrise行が、おじゃま行らしく埋まっていること。
        # 全行が空の盤面など「ずらしても一致してしまう」状態を除くために必要。
        # おじゃま行は穴が1つだけ空いた状態で挿入される。
        if all(
            sum(1 for cell in current[rows - 1 - k] if cell is not None) >= width - 2
            for k in range(rise)
        ):
            return rise
    return 0


def _detect_lock(next_advanced: bool, hold_changed: bool, had_previous_piece: bool) -> bool:
    """ミノが実際に盤面へ固定されたかを判定する。

    ネクストが進む事象は3種類あり、そのうち固定を伴うのは1つだけである。

    ・通常の固定       : NEXTが進む / HOLDは変わらない → 固定あり
    ・初回の空HOLD交換 : NEXTが進む / HOLDが変わる     → 固定なし
    ・既存HOLDとの交換 : NEXTは進まない / HOLDが変わる → 固定なし

    したがって「NEXTが進み、かつHOLDが変わっていない」ことが固定の条件になる。
    NEXTの進行だけでは固定と同一視できない点に注意する(初回のホールドは
    固定なしでNEXTを1つ消費する)。

    固定の検出は、表示中の提案を消してよい唯一の根拠として使う。認識に
    失敗したことは「置いた」ことを意味しないため、提案を消す理由にしない。

    had_previous_piece: 直前の手番が存在したか。対局開始後の最初のスポーン
    では、まだ何も置かれていないのでNEXTが進んでも固定ではない。
    """
    return had_previous_piece and next_advanced and not hold_changed


def _turn_key(
    current_piece: str | None, hold_piece: str | None, next_queue: tuple[str, ...]
) -> tuple[str | None, str | None, tuple[str, ...]]:
    """「今どの手番か」を表す識別情報。

    Cold Clear 2への要求(start_thinking)と、返ってきた結果(poll_suggestion)を
    結び付けるために使う。盤面そのものは含めない: 操作中ミノが落下して
    着地済み領域の判定に取り込まれる過程で盤面キーは正常に変化しうるため、
    盤面まで含めると同じ手番の途中で不一致になってしまう。
    """
    return (current_piece, hold_piece, next_queue)


def _available_pieces(
    current_piece: str | None, hold_piece: str | None, next_queue: tuple[str, ...]
) -> set[str | None]:
    """今の手番で実際に置くことができるミノの種類。

    操作中のミノに加え、HOLDにミノがあればそれ、HOLDが空ならホールド操作で
    引き出されるNEXTの先頭が候補になる。ここに含まれないミノの配置提案は、
    現在の局面では実行不可能なので表示してはならない。
    """
    pieces: set[str | None] = {current_piece}
    if hold_piece:
        pieces.add(hold_piece)
    elif next_queue:
        pieces.add(next_queue[0])
    return pieces


def _is_next_queue_impossible(next_queue: tuple[str, ...]) -> bool:
    """7-bag方式では起こり得ないネクストキューのパターンを検知する。

    1つの袋の中に同じミノ種類は1つしか入らない。ネクスト5枠は最大2つの
    袋にまたがりうるため同じ種類が2つ出現することはあり得るが、3つ以上
    出現することは理論上ありえない。実機ログで、画面演出等のノイズにより
    1tickだけnext欄の認識が支離滅裂になり(例: ['I','I','O','S','I'])、
    存在しないはずのミノを使った提案が出る不具合が確認されたため、この
    ようなフレームは呼び出し側で棄却できるようにする。
    """
    return any(count >= 3 for count in Counter(next_queue).values())


# 1つのミノを構成するマス数。_is_plausible_board_transitionで、置いた直後の
# ミノが基準値に取り込まれる前にライン消去が起きた場合の減少量を補正する。
_PIECE_CELL_COUNT = 4


# 1tickの間に増えてよいマス数の上限。ミノ1個(4マス)に、確定盤面が数tick
# 遅れて2個分をまとめて取り込む場合を見込んで2個分とする。おじゃまの
# せり上がりは別途_detect_garbage_riseで検出し、この上限の対象外にする。
_MAX_PLAUSIBLE_CELL_INCREASE = _PIECE_CELL_COUNT * 2


def _is_plausible_board_transition(
    previous_board_key: tuple[tuple[str | None, ...], ...] | None,
    candidate_board_key: tuple[tuple[str | None, ...], ...],
    width: int,
    garbage_rise: int = 0,
) -> bool:
    """着地済み盤面の変化が、テトリスのルール上あり得る遷移か(=このtickの
    読み取りを信用してよいか)を判定する。

    実際に高精度なTetris認識AI/botの多くは、画面の1フレームをそのまま
    信じるのではなく「その変化がゲームのルール上あり得るか」を検証してから
    判断に使う。既存の`_discard_sparse_garbage_rows`(ガベージ行が疎らなら
    演出ノイズとみなす)も同じ考え方に基づく。

    一度埋まったマスは、(1)新しいミノの設置やガベージの追加で他のマスが
    さらに埋まる、(2)ライン消去で行ごと消える、のいずれかでしか「空」に
    戻らない。(2)は必ず「揃った行(=そのゲームの列数ぶん)」単位で起こるため、
    埋まっているマスの総数が減る場合、その減少量は必ず列数の倍数になる
    はず。実機動画で、T-Spinダブル等の派手な光エフェクトの直後に、まだ
    残っているはずの設置済みブロックのマスが一時的に「空」と誤読され、
    その誤った盤面のままCold Clear 2に渡されて「既存ブロックと干渉する
    ように見える提案」「振動」につながっていたことを確認した。この種の
    フレームは、減少量が列数の倍数にならない不自然な形で現れるため、
    それを検知してこのtickの盤面読み取りを棄却できるようにする。
    """
    if previous_board_key is None:
        return True

    def _filled_count(board_key: tuple[tuple[str | None, ...], ...]) -> int:
        return sum(1 for row in board_key for cell in row if cell is not None)

    previous_filled = _filled_count(previous_board_key)
    candidate_filled = _filled_count(candidate_board_key)
    if candidate_filled >= previous_filled:
        # 【2026-09-11・6回目の実機録画】4列消し等の閃光で盤面全体が白く
        # なる瞬間、全マスが白灰色(GARBAGE)と読まれる。減少ではなく大幅な
        # 「増加」なので従来は素通りし、消去と同時にスポーンした新しい
        # ミノの要求が、ほぼ全面ブロックの盤面で行われて意味のない提案に
        # なっていた。1tickで増えるのはミノ1〜2個分までで、それ以上は
        # おじゃまのせり上がり(呼び出し側が別途検出)でなければ信用しない。
        if garbage_rise:
            return True
        return candidate_filled - previous_filled <= _MAX_PLAUSIBLE_CELL_INCREASE
    # 【2026-09-11・実機ログで判明】previous_board_keyは「2tick連続で同じ」
    # という確認を経た基準値なので、置いた直後のミノ(4マス)がまだ基準値に
    # 取り込まれる前にライン消去が起きると、減少量は「10×消去行数 − 置いた
    # ミノのマス数(1〜4)」になり、列数の倍数にならない。つまりライン消去を
    # 伴う固定はほぼ毎回「あり得ない遷移」と誤判定され、その手番の
    # start_thinkingが見送られていた(実測: 約110秒で23回、復帰は1.5秒の
    # タイムアウト保険頼み。「消した後の提示が遅い」の直接原因)。
    # 置いたミノのマス数ぶん(0〜4)を足せば列数の倍数になる減少は正常とみなす。
    decrease = previous_filled - candidate_filled
    return any((decrease + added) % width == 0 for added in range(_PIECE_CELL_COUNT + 1))


def _drop_cells_not_connected_to(grid: list[list[str | None]], anchor_row: int) -> None:
    """anchor_rowより上のマスのうち、anchor_row以降の領域に4近傍で連結していないものを空にする。"""
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    keep: set[tuple[int, int]] = set()
    stack = [(r, c) for r in range(anchor_row, rows) for c in range(cols) if grid[r][c] is not None]
    keep.update(stack)
    while stack:
        r, c = stack.pop()
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols and (nr, nc) not in keep and grid[nr][nc] is not None:
                keep.add((nr, nc))
                stack.append((nr, nc))
    for r in range(min(anchor_row, rows)):
        for c in range(cols):
            if grid[r][c] is not None and (r, c) not in keep:
                grid[r][c] = None


def _build_settled_board(
    grid: list[list[str | None]],
    cols: int,
    rows: int,
    exclude_rows: int | None = None,
) -> BoardState:
    if exclude_rows is None:
        exclude_rows = _settled_top_row(grid)
    board = BoardState(width=cols, height=rows)
    for r in range(exclude_rows, rows):
        for c in range(cols):
            board.grid[r][c] = grid[r][c]
    return board


def _stabilize_settled_grid(
    raw_grid: list[list[str | None]],
    exclude_rows: int,
    previous_confirmed_grid: list[list[str | None]] | None,
    previous_pending_grid: list[list[str | None]] | None,
) -> tuple[list[list[str | None]], list[list[str | None]]]:
    """着地済み領域(exclude_rows以降)の各マスの変化を、方向によって扱いを変えて確定する。

    ・空 → ブロック : 待たずに即座に採用する(真下に支えがある場合。
                       宙に浮いた出現は光の粒等のノイズなので2tick待つ)
    ・ブロック → 空 : 2tick連続で同じ観測を要求する
    ・ブロック → 別のブロック : 2tick連続で同じ観測を要求する

    誤りの害が非対称であることに基づく。「無いブロックがある」と誤っても
    AIは別の場所へ置くだけだが、「あるブロックが無い」と誤ると必ずその
    マスへ配置が提案され、干渉になる。

    実機ログで、既に着地して完全に静止しているはずの1マスの色が、他の
    条件(操作中ミノの位置、着地したばかりかどうか)に一切関係なく、
    フレームごとにI→J→Iのように勝手に入れ替わる現象が確認された
    (操作中ミノが盤面に橋渡しされる問題とは別物であることを実機ログの
    diffで確認済み)。盤面の色判定(classify_color)は毎フレーム独立して
    セル内の彩度最大点をサンプリングしているだけで、前後のフレームとの
    整合性を確認する仕組みが一切なかったことが原因と考えられる。操作中
    ミノの判定(_resolve_i_j)や盤面全体の変化検知(board_key_changed)には
    それぞれ個別の安定化があったが、着地済みマス1つ1つの色そのものには
    抜けていた。

    exclude_rows未満の行(操作中ミノが存在しうる領域)は、ミノの移動に
    伴って毎tick変化するのが正常なので、安定化の対象から外し常に生の
    値をそのまま使う。

    戻り値: (今回採用するgrid, 次tickへ引き継ぐpending_grid)
    """
    rows = len(raw_grid)
    cols = len(raw_grid[0]) if rows else 0
    if previous_confirmed_grid is None:
        # 初回は比較対象がないため、生の値をそのまま信頼するしかない。
        return raw_grid, [[None] * cols for _ in range(rows)]

    confirmed = [row[:] for row in raw_grid]
    next_pending: list[list[tuple[str | None] | None]] = [[None] * cols for _ in range(rows)]
    for c in range(cols):
        # 下から上へ処理する。「支え」の判定(下記)で、同じtickに支えありとして
        # 採用したばかりの真下のマス(confirmed[r+1][c])を参照するため。
        for r in range(rows - 1, exclude_rows - 1, -1):
            raw = raw_grid[r][c]
            prev_confirmed = previous_confirmed_grid[r][c]
            if raw == prev_confirmed:
                continue
            if prev_confirmed is None and raw is not None:
                # 【ブロックが「現れた」変化は待たずに採用する】
                # 誤りの害が非対称であるため、増える方向と減る方向で扱いを
                # 変える。「無いブロックがある」と誤ってもAIは別の場所へ置く
                # だけだが、「あるブロックが無い」と誤ると必ずそのマスへ
                # 配置が提案され、干渉になる。
                #
                # 実機で、着地したばかりのミノがこの待機のせいで1tick
                # (約100ms)盤面に入らず、その同じtickで固定を検出して
                # AIへ質問するため、「今置いたミノがまだ無い盤面」を渡して
                # いた。保存済み履歴では、提案マスの24.6%が実際にはブロックの
                # 上にあり、その全件で読み取り自体は正しく占有と読めていた
                # (=盤面が古いことが原因)。「Iミノを置いた瞬間にJミノが
                # 干渉した」という報告に一致する。
                #
                # ミノの着地やおじゃまの上昇でブロックが現れるのは正常な
                # 事象であり、待つ理由がない。
                #
                # 【2026-09-11・4回目の実機ログ】ただし「支えのないマス」は
                # 例外とする。ライン消去やコンボの光の粒(スパークル)が1フレーム
                # だけブロックと読まれると、即採用で幻のブロックが盤面に入り、
                # 消えるまで2tick「空になる確定待ち」が続く。粒は動き続ける
                # ので確定待ちが途切れず、スポーン時の要求が盤面信頼の
                # タイムアウト(0.3秒)まで止まっていた(約2分で66回)。着地した
                # ミノやおじゃまは必ず床か既存ブロックの上に載っているので、
                # 真下が空いている出現だけを2tick待たせても取りこぼさない。
                #
                # 支えは「確定済みのマス」(前回の確定値)か床に限る。生の値だけを
                # 支えにすると、ライン消去の「TETRIS」文字や閃光のように数行に
                # またがるエフェクトが、下の行を上の行の支えにして塊ごと即採用
                # され、幻のブロックとして残る(6回目の実機ログ: 4列消しの後に
                # 盤面信頼のタイムアウトが4回連続し、その盤面で空中の提案)。
                #
                # 【2026-09-11・7回目の実機ログ】ただし「真下」だけを見ると、
                # 置いたミノのうち張り出した部分(J/L/S/Zの真下が空いているマス)
                # が2tick待たされ、その間にAIがそこへ配置を提案して干渉した
                # (保存画像023: Jの張り出しマスが盤面から欠けていた)。ミノは
                # 4マスがつながった塊なので、「確定済みマスか床に接する出現」
                # とそれに連結した出現をまとめて採用する(下の後処理)。ここでは
                # まず床・確定済みマスに直接接するものだけ採用しておく。
                supported = r + 1 >= rows or previous_confirmed_grid[r + 1][c] is not None
                if supported:
                    confirmed[r][c] = raw
                    continue
            prev_pending = previous_pending_grid[r][c] if previous_pending_grid is not None else None
            # 【保留値は1要素のタプルで包む】
            # 以前は保留値をそのまま入れ、「保留なし」もNoneで表していた。
            # 空マスもNoneなので、ブロックが空マスへ変わる誤読では
            # 「保留なし(None) == 観測値(None)」が成立してしまい、2tick待たずに
            # 1tickで即座に採用されていた。盤面に一瞬の穴が空き、そこへ
            # 重なる配置がAIから提案される「干渉」の直接原因になっていた。
            # 包んでおけば、空マスの保留は(None,)、保留なしはNoneとなり
            # 区別できる。
            if prev_pending == (raw,):
                # 2tick連続で同じ新しい値が観測されたので確定する。
                confirmed[r][c] = raw
            else:
                # 初めて確定値と異なる値が来た。まだ確定させず前回の値を維持する。
                confirmed[r][c] = prev_confirmed
                next_pending[r][c] = (raw,)

    # 【出現の塊をまとめて採用する後処理】上で採用した(支えのある)出現に
    # 4近傍で連結している「まだ保留中の出現」は、同じミノの一部なので
    # 一緒に採用する。床にも確定済みマスにも接していない塊(宙に浮いた
    # エフェクト)は保留のまま残る。
    def _is_new_appearance(rr: int, cc: int) -> bool:
        return raw_grid[rr][cc] is not None and previous_confirmed_grid[rr][cc] is None

    stack = [
        (rr, cc)
        for rr in range(exclude_rows, rows)
        for cc in range(cols)
        if _is_new_appearance(rr, cc) and confirmed[rr][cc] is not None
    ]
    while stack:
        rr, cc = stack.pop()
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nr, nc = rr + dr, cc + dc
            if not (exclude_rows <= nr < rows and 0 <= nc < cols):
                continue
            if _is_new_appearance(nr, nc) and confirmed[nr][nc] is None:
                confirmed[nr][nc] = raw_grid[nr][nc]
                next_pending[nr][nc] = None
                stack.append((nr, nc))
    return confirmed, next_pending


@dataclass(frozen=True)
class RecognitionResult:
    # 画像から読み取れた操作中ミノ。読めなかった場合はNone(部分成功)。
    # 種類はNEXT履歴からも求められるため、Noneでも他の観測は利用できる。
    current_piece: str | None
    # 操作中ミノが占める最小行。盤面最上部に近いほどスポーン直後の可能性が高い。
    current_piece_min_row: int
    hold_piece: str | None
    # HOLD欄の状態を確定できたか。Falseなら「空欄なのか読めなかったのか
    # 分からない」状態で、hold_pieceのNoneを空欄と解釈してはいけない。
    hold_known: bool
    next_queue: tuple[str, ...]
    # NEXT欄5枠それぞれの生の読み取り結果を、位置を保ったまま(認識失敗枠は
    # None)保持する。next_queueは認識失敗枠を詰めて除外してしまうため
    # (1箇所の誤読が後続すべての位置をズラしてしまう)、新規スポーン検知
    # (AssistWorker._compute_next_advanced参照)にはこちらを使う。
    next_slots_raw: tuple[str | None, ...]
    board: BoardState
    # 盤面グリッドをタプル化したキャッシュキー。BoardStateはミュータブルで
    # 等価比較・ハッシュができないため、認識結果の変化検知に別途これを使う。
    board_key: tuple[tuple[str | None, ...], ...]
    # 着地済みブロックの最上段行（_settled_top_row参照。デバウンス適用後の実効値）。
    settled_top_row: int
    # デバウンス適用前の生のsettled_top_row。呼び出し側(AssistWorker)が
    # 次tickへ渡す信頼値を更新するかどうかの判定に使う。
    raw_settled_top_row: int
    # 着地済み領域で、まだ1回しか観測されていない新しい色の候補
    # (_stabilize_settled_grid参照)。次tickにそのままヒントとして渡すことで、
    # 2tick連続で同じ新しい色が確認できた時だけ確定させるデバウンスを実現する。
    pending_grid: list[list[str | None]]
    # デバウンス済みの着地済み盤面(載っている操作ミノを重ねる前)。呼び出し側が
    # 次tickのprevious_confirmed_grid_hintに使う。boardは AI入力用にこれへ
    # 載っているミノを重ねたもの(recognize参照)。
    confirmed_grid: list[list[str | None]] | None = None


def recognize(
    calibration: CalibrationResult,
    capture: ScreenCapture,
    debug_save_dir: Path | None = None,
    previous_piece_hint: str | None = None,
    previous_settled_top_row_hint: int | None = None,
    previous_confirmed_grid_hint: list[list[str | None]] | None = None,
    previous_pending_grid_hint: list[list[str | None]] | None = None,
) -> RecognitionResult | None:
    """1フレーム分のキャプチャ→盤面認識を行う。操作中ピースが検出できない場合はNone。

    debug_save_dirを指定すると、実際にキャリブレーション座標で切り出した
    盤面・ホールド・ネクストの生画像をそこへ保存する（直近1回分を上書き）。
    「HOLD欄の座標が実際の画面とズレている」ような認識結果とキャプチャ画像の
    食い違いを、テキストログだけでなく画像で直接確認できるようにするため。

    previous_piece_hint: _infer_current_piece参照。I/Jが部分的に隠れて
    形状だけでは判定できない場合に、直前の確定値を優先するためのヒント。

    previous_settled_top_row_hint: 直前tickで信頼していたsettled_top_row。
    操作中ピースが着地済みブロックのすぐ上(1行の隙間以内)を落下している
    瞬間、_settled_top_rowのノイズ許容(_SETTLED_ROW_MAX_SKIP)がピース自身の
    行を「着地済み領域の一部」として誤って取り込んでしまうことが実機ログで
    確認された(current_pieceは正しく検出されたまま、着地済み盤面に
    存在しないはずのピースの断片が現れては消えるノイズとなり、Cold Clear 2
    への入力が毎回微妙に異なるため「提案が暴れる」「盤面が高くなるほど
    ピースが着地済み領域に近づく機会が増え悪化する(中盤以降ほど提案が
    出なくなる)」という報告に直結していた)。生のsettled_top_rowが前回の
    信頼値より小さく(=より多くの行を着地済みとみなす方向へ)なった場合、
    橋渡し候補の行が操作中ピース自身らしいか(_bridge_looks_like_falling_
    piece参照)を単一フレームの構造で判定し、そうであれば前回の信頼値の
    ままにする。

    previous_confirmed_grid_hint, previous_pending_grid_hint:
    _stabilize_settled_grid参照。着地済み領域の色判定を1枚の画像だけで
    即断せず、2tick連続で同じ新しい色が確認できて初めて確定するための
    状態。呼び出し側(AssistWorker)が前回のRecognitionResult.board.gridと
    pending_gridをそのまま次tickへ渡し続ける。previous_confirmed_gridは
    board_reader.read_board_grid_with_samplesにもそのまま渡され、光
    エフェクトで一時的にテンプレート不一致になったセルを直前の確定値で
    救済するためにも使われる(board_reader._classify_as_garbage_or_empty参照)。
    """
    board_w = calibration.board_width
    board_h = calibration.board_height
    board_region = CaptureRegion(calibration.board_origin_x, calibration.board_origin_y, board_w, board_h)
    hold_region = CaptureRegion(*calibration.hold_rect)

    # 盤面・ホールド・ネクスト5枠を個別にgrab()すると、mssの呼び出し回数分
    # オーバーヘッドが積み重なる（実測で7回個別=約72ms、全体を1回にまとめると
    # 約20msと3.6倍の差があった）。全部を含む最小矩形を1回だけキャプチャし、
    # 各領域はnumpyのスライスで切り出す方が大幅に高速。
    min_x, min_y, max_x, max_y = _region_bounds(calibration)
    full_img = capture.grab(CaptureRegion(min_x, min_y, max_x - min_x, max_y - min_y))

    def _crop(region: CaptureRegion):
        x0 = region.left - min_x
        y0 = region.top - min_y
        return full_img[y0 : y0 + region.height, x0 : x0 + region.width]

    board_img = _crop(board_region)
    hold_img = _crop(hold_region)
    next_imgs = [_crop(CaptureRegion(*rect)) for rect in calibration.next_rects]

    if debug_save_dir is not None:
        import cv2

        debug_save_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(debug_save_dir / "board.png"), board_img[:, :, ::-1])
        cv2.imwrite(str(debug_save_dir / "hold.png"), hold_img[:, :, ::-1])
        for i, img in enumerate(next_imgs):
            cv2.imwrite(str(debug_save_dir / f"next{i}.png"), img[:, :, ::-1])

    grid, samples = read_board_grid_with_samples(
        board_img,
        cols=calibration.board_cols,
        rows=calibration.board_rows,
        previous_grid_hint=previous_confirmed_grid_hint,
    )
    # 着地済み盤面に含める行の上端(包含的。1マスでも支えがあれば実在とみなす)。
    settled_board_top_row = _settled_top_row(grid)
    # 操作ミノを探す範囲の上限(保守的。落下中のミノを取り込みにくい)。
    # 両者は別々の規則で求める(理由は_falling_piece_search_limit参照)。
    raw_settled_top_row = _falling_piece_search_limit(grid)
    if previous_settled_top_row_hint is not None and raw_settled_top_row < previous_settled_top_row_hint:
        # 生の値が前回の信頼値より「より多くの行を着地済みとみなす」方向に
        # 動いた場合、新たに橋渡しされた行(bridge_rows)の中身が操作中ミノ
        # 自身(合計4マス以下のひとかたまり)である可能性を構造的にチェックする。
        # 当初は「2tick連続で同じ値になったら確定」という時間ベースの
        # デバウンスを試みたが、緩やかな重力の下でミノが何十tickも同じ行に
        # 静止し続けることがあり、時間経過では原理的に区別できないと
        # 実機ログで判明したため、単一フレームの構造的判定に切り替えた
        # (詳細は_bridge_looks_like_falling_pieceのdocstring参照)。
        bridge_rows = grid[raw_settled_top_row:previous_settled_top_row_hint]
        if _bridge_looks_like_falling_piece(bridge_rows):
            effective_settled_top_row = previous_settled_top_row_hint
        else:
            effective_settled_top_row = raw_settled_top_row
    else:
        effective_settled_top_row = raw_settled_top_row
    # 【操作ミノが読めなくても、他の観測は捨てない】
    # 以前はここでNoneを返し、正しく読めていた盤面・NEXT・HOLDまで丸ごと
    # 破棄していた。実機では認識失敗が稼働時間の45%を占めており、その間
    # 手番の進行もHOLDの変化も追えなくなっていた。操作ミノの種類は
    # NEXT履歴からも求められる(_expected_current_piece参照)ため、
    # 画像から読めないことは全体の失敗を意味しない。
    inferred = _infer_current_piece(
        grid, samples, previous_piece_hint=previous_piece_hint, search_limit=effective_settled_top_row
    )

    hold_reading = read_patch(hold_img)
    hold_piece = hold_reading.piece if hold_reading.piece in ALL_PIECE_NAMES else None
    # 「空欄」と「読めなかった」を区別する。読めなかっただけの状態を空欄と
    # 解釈すると、空HOLDへの初回格納(固定なしでNEXTを消費する)と取り違え、
    # 固定の検出を誤る(有識者資料[035])。
    hold_known = hold_piece is not None or hold_reading.is_empty
    next_pieces_raw = [read_piece_from_patch(img) for img in next_imgs]
    next_queue = tuple(p for p in next_pieces_raw if p in ALL_PIECE_NAMES)
    # next_queueは認識失敗枠を詰めて除外するため、位置情報を保った生の
    # 5枠版も別途保持する(next_slots_rawのdocstring参照)。
    next_slots_raw = tuple(p if p in ALL_PIECE_NAMES else None for p in next_pieces_raw)

    if _is_next_queue_impossible(next_queue):
        return None

    if inferred is not None:
        # 操作ミノのセルが分かっているので、着地済み盤面は包含的に切り出し、
        # そのセルだけを個別に取り除く。行単位で切り落とす旧方式と違い、
        # 同じ行にある実在のブロックを巻き添えにしない。
        board_top_row = settled_board_top_row
        board = _build_settled_board(
            grid, calibration.board_cols, calibration.board_rows, exclude_rows=board_top_row
        )
        for r, c in inferred.cells:
            if r >= board_top_row:
                board.grid[r][c] = None
    else:
        # 操作ミノがどこにあるか分からない。包含的に切り出すと、盤面に紛れた
        # 操作ミノをそのまま着地済みとしてAIへ渡す恐れがあるため、保守的な
        # 上限より上は「その領域に4近傍で連結しているマス」だけ採用する。
        #
        # 【2026-09-11・7回目の実機ログ】以前は保守的な上限より上を丸ごと
        # 切り落としていたため、置いたばかりの縦向きLの柱(1マスしかない行)が
        # 光って操作ミノとして読めない瞬間に盤面から消え、AIがその上に
        # Oを提案して2手目から干渉した。積みに連結しているマスは着地済み
        # ブロック(か積みに載っている操作ミノ)であり、宙に浮いた操作ミノ
        # だけが切り落とされる。
        board_top_row = settled_board_top_row
        board = _build_settled_board(
            grid, calibration.board_cols, calibration.board_rows, exclude_rows=board_top_row
        )
        _drop_cells_not_connected_to(board.grid, effective_settled_top_row)
    # 【デバウンスの範囲は盤面の範囲と必ず一致させる】
    # 以前はここに保守的な値(effective_settled_top_row)を渡していたため、
    # 盤面には含まれるのにセル単位の2tickデバウンスが掛からない行が生じて
    # いた。それは積みの上端という最もノイズが多い領域であり、そこの一瞬の
    # 誤読がそのままAIへ渡って、既存ブロックと重なる提案(干渉)の原因に
    # なっていた。包括的な安定化(_stabilize_recognition)を通り抜けるように
    # した際に表面化した。
    board.grid, pending_grid = _stabilize_settled_grid(
        board.grid, board_top_row, previous_confirmed_grid_hint, previous_pending_grid_hint
    )
    board_key = tuple(tuple(row) for row in board.grid)
    # 呼び出し側が次tickのデバウンスのヒントに使う「確定した着地済み盤面」。
    # 下で載っているミノを重ねる前の値を保持する。
    confirmed_grid = [row[:] for row in board.grid]

    # 【2026-09-11】積みの上に載っているミノ(置いた直後の縦Iなど。
    # _is_resting_on_stack参照)は、AIへ渡す盤面にだけ重ねる。当初は着地済み
    # 盤面から除外しない方式にしたが、そのマスが「空→占有は即採用」で
    # 確定盤面に残り、ミノを横に動かした後も2tick幻のブロックとして残って
    # AIへ渡り、幻の上に提案が出て空中に浮く不具合になった(5回目の実機
    # 画像036)。確定盤面(board_key・次tickのヒント)には含めず、このtickの
    # AI入力と配置の物理検査にだけ反映する。
    if inferred is not None and _is_resting_on_stack(grid, inferred.cells):
        for r, c in inferred.cells:
            if r >= board_top_row and board.grid[r][c] is None:
                board.grid[r][c] = inferred.piece

    # ゲームプレイ中でない画面（ポーズ・ゲームオーバー等）を、待ち時間なしで
    # その場のtickだけで弾く。ネクスト2手目以降はライン消去エフェクトや
    # 文字表示で隠れることがあり信頼できないため見ない。ネクスト1手目・
    # ホールド・盤面の3つが同時に「何もない」場合だけを対象にする
    # （通常プレイ中はこの3つが同時に空になることはまずないため誤検知しない）。
    next_piece_1_ok = bool(next_pieces_raw) and next_pieces_raw[0] in ALL_PIECE_NAMES
    board_is_empty = all(cell is None for row in board.grid for cell in row)
    if not next_piece_1_ok and hold_piece is None and board_is_empty:
        return None

    return RecognitionResult(
        current_piece=inferred.piece if inferred is not None else None,
        current_piece_min_row=inferred.min_row if inferred is not None else 0,
        hold_piece=hold_piece,
        hold_known=hold_known,
        next_queue=next_queue,
        next_slots_raw=next_slots_raw,
        board=board,
        board_key=board_key,
        settled_top_row=effective_settled_top_row,
        raw_settled_top_row=raw_settled_top_row,
        pending_grid=pending_grid,
        confirmed_grid=confirmed_grid,
    )


def format_board_debug(recognition: RecognitionResult, best: ColdClearMove | None) -> str:
    """認識結果と最善手を人間が読めるテキストに変換する（実機デバッグ用）。

    盤面認識の誤り（浮いたブロック、穴の見落とし等）を、複雑な地形で
    最善手が明らかにおかしいと感じた時に切り分けられるようにするためのもの。
    列は0始まり、各セルは着地済みなら先頭1文字（例: I,J,L,O,S,T,Z）、
    空マスは'.'、今回の提案の着地マスは'#'で表示する。
    """
    landing = set(best.landing_cells) if best is not None else set()
    lines = []
    board = recognition.board
    top = recognition.settled_top_row
    for r in range(top, board.height):
        row_chars = []
        for c in range(board.width):
            if (r, c) in landing:
                row_chars.append("#")
            elif board.grid[r][c] is not None:
                row_chars.append(board.grid[r][c][0])
            else:
                row_chars.append(".")
        lines.append("".join(row_chars))

    header = (
        f"current={recognition.current_piece} "
        f"hold={recognition.hold_piece} "
        f"next={list(recognition.next_queue)}"
    )
    if best is not None:
        header += f" -> best: piece={best.piece} use_hold={best.use_hold} nodes={best.nodes} nps={best.nps:.0f}"
    else:
        header += " -> best: なし"
    return header + "\n" + "\n".join(lines)


def _region_bounds(calibration: CalibrationResult) -> tuple[int, int, int, int]:
    """盤面+HOLD+NEXT欄すべてを含む最小矩形を返す (min_x, min_y, max_x, max_y)"""
    board_w = calibration.board_width
    board_h = calibration.board_height

    rects = [
        (calibration.board_origin_x, calibration.board_origin_y, board_w, board_h),
        calibration.hold_rect,
        *calibration.next_rects,
    ]
    min_x = min(x for x, _y, _w, _h in rects)
    min_y = min(y for _x, y, _w, _h in rects)
    max_x = max(x + w for x, _y, w, _h in rects)
    max_y = max(y + h for _x, y, _w, h in rects)
    return min_x, min_y, max_x, max_y


def _grab_calibrated_region(calibration: CalibrationResult, capture: ScreenCapture):
    """盤面+HOLD+NEXT欄すべてを含む最小矩形(_region_bounds参照)をRGB画像として取得する。

    画面録画(暫定機能)用。recognize()内部でも同じ範囲を毎tickキャプチャして
    いるが、録画は間引いて(VIDEO_RECORD_FPS)行うため、あえて独立してこの
    範囲だけを都度取得する。
    """
    min_x, min_y, max_x, max_y = _region_bounds(calibration)
    return capture.grab(CaptureRegion(min_x, min_y, max_x - min_x, max_y - min_y))


def _draw_suggestion_on_bgr_frame(
    bgr_frame,
    calibration: CalibrationResult,
    region_origin_x: int,
    region_origin_y: int,
    draw_data: OverlayDrawData,
) -> None:
    """最善手の色ドットを、録画用フレーム(mssキャプチャのBGR画像)に直接合成する。

    オーバーレイウィンドウ自体は自己汚染防止(_exclude_window_from_screen_capture
    参照)のため画面キャプチャから除外されており、録画にも一切映らない。
    そのため盤面認識には一切関与しないこの録画専用フレームに対してのみ、
    cv2で提案内容を焼き込む。座標系はrenderer.render_overlayと違い
    DPRの補正が不要（mssは常に物理ピクセル座標を返すため）。
    """
    import cv2

    radius = round(calibration.cell_size * LANDING_DOT_RADIUS_RATIO)
    rgb = PIECE_COLORS[draw_data.piece]
    fill_color_bgr = (rgb.b, rgb.g, rgb.r)
    outline_color_bgr = (255, 255, 255)

    for row, col in draw_data.landing_cells:
        center_x = (
            calibration.board_origin_x - region_origin_x + col * calibration.cell_size + calibration.cell_size // 2
        )
        center_y = (
            calibration.board_origin_y - region_origin_y + row * calibration.cell_size + calibration.cell_size // 2
        )
        cv2.circle(bgr_frame, (center_x, center_y), radius, fill_color_bgr, thickness=-1, lineType=cv2.LINE_AA)
        cv2.circle(
            bgr_frame,
            (center_x, center_y),
            radius,
            outline_color_bgr,
            thickness=LANDING_DOT_OUTLINE_WIDTH,
            lineType=cv2.LINE_AA,
        )
    # 読み筋(2手目以降)は小さいドット+番号。
    plan_radius = max(2, round(calibration.cell_size * PLAN_DOT_RADIUS_RATIO))
    for index, step in enumerate(draw_data.plan_steps or [], start=2):
        rgb = PIECE_COLORS[step.piece]
        color = (rgb.b, rgb.g, rgb.r)
        for row, col in step.cells:
            center_x = (
                calibration.board_origin_x - region_origin_x + col * calibration.cell_size + calibration.cell_size // 2
            )
            center_y = (
                calibration.board_origin_y - region_origin_y + row * calibration.cell_size + calibration.cell_size // 2
            )
            cv2.circle(bgr_frame, (center_x, center_y), plan_radius, color, thickness=-1, lineType=cv2.LINE_AA)
        if step.cells:
            row, col = min(step.cells)
            text_x = calibration.board_origin_x - region_origin_x + col * calibration.cell_size + 2
            text_y = calibration.board_origin_y - region_origin_y + row * calibration.cell_size + calibration.cell_size - 4
            cv2.putText(bgr_frame, str(index), (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    # ラベル(開幕テンプレ名など)。cv2の内蔵フォントは日本語を描けないので、
    # 括弧内の英語名だけをHOLD欄の下に焼き込む。
    if draw_data.label:
        ascii_lines = [line for line in draw_data.label.splitlines() if line.isascii()]
        hx, hy, hw, hh = calibration.hold_rect
        for i, line in enumerate(ascii_lines):
            cv2.putText(
                bgr_frame,
                line.strip("()"),
                (hx - region_origin_x, hy - region_origin_y + hh + 20 + i * 18),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )


def _draw_next_debug_dots_on_bgr_frame(
    bgr_frame,
    calibration: CalibrationResult,
    region_origin_x: int,
    region_origin_y: int,
    next_slots: tuple[str | None, ...],
) -> None:
    """【2026-09-07・暫定のデバッグ機能】OverlayWindow._draw_next_debug_dots
    と同じ内容を、録画用フレームにも合成する(実機の画面上だけでなく、
    録画した動画でもNEXT欄の認識結果を確認できるようにするため)。
    確認が終わったら削除する想定の一時的なコード。
    """
    import cv2

    radius = 8
    for rect, label in zip(calibration.next_rects, next_slots):
        x, y, w, _h = rect
        center_x = x - region_origin_x + w - radius - 4
        center_y = y - region_origin_y + radius + 4
        if label is not None and label in PIECE_COLORS:
            rgb = PIECE_COLORS[label]
            cv2.circle(bgr_frame, (center_x, center_y), radius, (rgb.b, rgb.g, rgb.r), thickness=-1, lineType=cv2.LINE_AA)
            cv2.circle(bgr_frame, (center_x, center_y), radius, (255, 255, 255), thickness=2, lineType=cv2.LINE_AA)
        else:
            cv2.line(
                bgr_frame,
                (center_x - radius, center_y - radius),
                (center_x + radius, center_y + radius),
                (0, 0, 255),
                thickness=3,
                lineType=cv2.LINE_AA,
            )
            cv2.line(
                bgr_frame,
                (center_x - radius, center_y + radius),
                (center_x + radius, center_y - radius),
                (0, 0, 255),
                thickness=3,
                lineType=cv2.LINE_AA,
            )


def _exclude_window_from_screen_capture(widget: QtWidgets.QWidget) -> bool:
    """このウィンドウを画面キャプチャ(mss等)の対象から除外する。成功したらTrueを返す。

    実機の生画像(debug_frames_history)を目視確認して判明した重大な設計
    ミス: recognize()が使うScreenCapture(mss)は、実際に画面上へ合成された
    結果をそのまま撮影するため、支援モードの各オーバーレイウィンドウ
    (提案の色ドット・「支援モード中」バッジ)自体が画面上に描かれたまま
    写り込み、次tickの盤面認識がそれを本物のブロックとして誤読していた。
    「current_pieceは変化していないのに着地済み盤面に存在しないはずの
    ミノの残骸が現れる」という、これまで何度も再発してきた不具合の多くは、
    盤面認識ロジック側のノイズではなく、この自己汚染(オーバーレイが自分
    自身をキャプチャしてしまう)が真因だった可能性が高い。

    Windows 10 2004以降が提供するSetWindowDisplayAffinity(
    WDA_EXCLUDEFROMCAPTURE)を使うと、人間の目には物理ディスプレイ上に
    普通に表示されたまま、BitBlt/PrintWindow・DXGI Desktop Duplication
    (mss等の画面キャプチャ手段はこれらを使う)からは除外できる。
    ネイティブウィンドウハンドル(HWND)が必要なため、winId()でウィンドウの
    実体を確定させてから呼ぶ必要がある(show()より前だとQtがまだ実際の
    ウィンドウを作成していないことがある)。

    【この関数が失敗を握り潰してはいけない理由】
    かつてargtypes未指定でHWNDが32bitへ切り詰められ、この呼び出しが実際
    には失敗していた時期がある。当時は失敗が静かに握り潰されていたため
    「除外APIは実機で効かない」と誤って結論され、その回避策として盤面の
    セルを強制的に空マス化する処理が長期間残り続けた(その処理は固定直後の
    ブロックまで消してしまう副作用があった)。argtypes修正後は、mssが使う
    BitBlt+CAPTUREBLTの経路でも除外が正常に機能することを検証済み
    (除外なし=識別色3600画素が写り込み、除外あり=0画素)。
    同じ誤診断を繰り返さないよう、失敗した場合は静かに諦めず必ず
    呼び出し側へ報告する。

    【保険: 将来この方式が使えなくなった場合】
    Windows 10 2004より前や、将来OS側の仕様変更でこのAPIが機能しなく
    なった場合の代替案として、Windows Graphics Capture(WGC)による
    「ゲームウィンドウ単体のキャプチャ」への移行がある。WGCはデスクトップ
    全体ではなく対象ウィンドウだけを取得するため、そもそも自分の
    オーバーレイが写り込む余地がなくなる(副次的に、画面上での盤面の
    揺れの一部も解消できる)。現時点では本APIが機能しているため移行は
    不要と判断している。
    """
    if sys.platform != "win32":
        return False
    WDA_EXCLUDEFROMCAPTURE = 0x00000011
    try:
        import ctypes.wintypes

        # HWNDはポインタサイズ(64bit環境では64bit)のため、argtypesを明示
        # しないとctypesのデフォルト変換(32bit int)によって上位ビットが
        # 欠落する恐れがある。
        set_display_affinity = ctypes.windll.user32.SetWindowDisplayAffinity
        set_display_affinity.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.DWORD]
        set_display_affinity.restype = ctypes.wintypes.BOOL

        hwnd = ctypes.wintypes.HWND(int(widget.winId()))
        if not set_display_affinity(hwnd, WDA_EXCLUDEFROMCAPTURE):
            return False

        # 設定が実際に保持されているかを読み戻して確認する。戻り値がTRUE
        # でも期待した値が入っていなければ除外は効いていない。
        get_display_affinity = ctypes.windll.user32.GetWindowDisplayAffinity
        get_display_affinity.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.DWORD)]
        get_display_affinity.restype = ctypes.wintypes.BOOL
        affinity = ctypes.wintypes.DWORD(0)
        if not get_display_affinity(hwnd, ctypes.byref(affinity)):
            return False
        return affinity.value == WDA_EXCLUDEFROMCAPTURE
    except (OSError, AttributeError):
        # Windows 10 2004より前のバージョン等、APIが使えない環境。
        return False


class OverlayWindow(QtWidgets.QWidget):
    """盤面周辺だけをカバーする透過・クリックスルーの描画専用ウィンドウ"""

    def __init__(self, calibration: CalibrationResult) -> None:
        super().__init__()
        self.calibration = calibration
        self.draw_data: OverlayDrawData | None = None
        # 【2026-09-07・暫定のデバッグ機能】NEXT欄のテンプレートマッチングが
        # 実機で本当に正しく認識できているかを目視確認するための一時的な
        # 可視化。next_debug_readyのdocstring参照。確認が終わったら削除する。
        self.next_debug_slots: tuple[str | None, ...] | None = None

        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.Tool
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        # このウィンドウがフォーカス(キーボード入力)を奪わないようにする。
        # 奪ってしまうと、ゲーム側のEscキー操作(ポーズ等)がこのウィンドウに
        # 吸われてしまう恐れがある。
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating)
        # QtにWindowsのシステム背景描画を一切させない（透過ウィンドウで
        # 提案が短時間に何度も切り替わると、update()による非同期の再描画が
        # Windows側の画面合成に追いつかず、前の提案のピクセルが消えないまま
        # 新しい提案が別の場所に描かれ「2つの提案が同時に見える」ことが
        # 実機で確認された）。この属性とrepaint()の併用で、Qt側のバッファと
        # 画面表示のズレを避ける。
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground)

        # 画面キャプチャ(mss)は物理ピクセル座標を使うが、PyQt6のウィンドウ配置は
        # 論理ピクセル座標(DPIスケール適用後)を使う。DPIスケールが100%でない環境
        # （マルチモニタでモニタごとに異なるスケールが設定されている場合など）では
        # 変換しないと表示位置が大きくずれるため、devicePixelRatioで補正する。
        # 対象ゲーム画面がプライマリスクリーンにある前提の簡易対応
        # （他モニタでの利用は将来対応）。
        self.dpr = QtWidgets.QApplication.primaryScreen().devicePixelRatio()

        min_x, min_y, max_x, max_y = _region_bounds(calibration)
        # 描画計算はすべて物理ピクセル座標系のoriginを基準に行う
        self.origin_x = min_x - OVERLAY_MARGIN
        self.origin_y = min_y - OVERLAY_MARGIN
        width_physical = (max_x - min_x) + OVERLAY_MARGIN * 2
        height_physical = (max_y - min_y) + OVERLAY_MARGIN * 2

        self.setGeometry(
            round(self.origin_x / self.dpr),
            round(self.origin_y / self.dpr),
            round(width_physical / self.dpr),
            round(height_physical / self.dpr),
        )

    def update_next_debug_data(self, slots: tuple[str | None, ...]) -> None:
        """【2026-09-07・暫定のデバッグ機能】next_debug_ready参照。"""
        self.next_debug_slots = slots
        self.repaint()

    def update_draw_data(self, data: OverlayDrawData | None) -> None:
        self.draw_data = data
        # update()はイベントループに再描画を予約するだけの非同期呼び出しで、
        # 短時間に連続して呼ばれると（段階的思考により提案がすぐ更新される
        # ケースで起こりやすい）、Windows側の画面合成のタイミングとズレて
        # 「前の提案が画面から消える前に次の提案が別の場所に描かれ、両方
        # 同時に見える」不具合が実機で確認された。repaint()で即座に同期的に
        # 描画させることで、常にその時点の最新状態だけが画面に反映されるようにする。
        self.repaint()
        # repaint()はQt側の描画(バックバッファへの書き込み)を同期的に完了
        # させるが、それがWindows Desktop Window Manager(DWM)の画面合成に
        # いつ反映されるかまでは保証しない。実機動画で、Qt側は正しく1つの
        # 状態だけを描いているはずなのに、画面には複数世代の提案（例えば
        # 直前のホールド提案と最新の通常提案）が同時に見える現象が確認
        # された。これはDWMの合成タイミングとQtの描画完了タイミングが
        # ずれることが原因と考えられるため、DwmFlush()で次のDWM合成
        # サイクルまで明示的に待ち、Qt側の最新の描画結果を確実に画面へ
        # 反映させてから戻る。
        if sys.platform == "win32":
            try:
                ctypes.windll.dwmapi.DwmFlush()
            except OSError:
                pass

    def paintEvent(self, event: QtCore.QEvent) -> None:  # noqa: N802
        painter = QtGui.QPainter(self)
        # WA_TranslucentBackgroundのウィンドウは、update()のたびにQtが必ず
        # 背景を透明にクリアしてくれるとは限らない（環境によっては前フレームの
        # ピクセルが残ったまま新しい描画が上書きされずに重なることがある）。
        # CompositionMode_Sourceで塗ることで、アルファ含めて確実に全面クリア
        # してから描く。これをしないと、ミノがスポーンして提案が切り替わった
        # 瞬間に「前回の提案と今回の提案が両方見える」という不具合が起きる。
        painter.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 0))
        painter.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceOver)

        if self.draw_data is not None:
            c = self.calibration
            # board_origin_x/y・cell_sizeは丸めずfloatのまま渡す(BoardLayoutの
            # docstring参照)。ここで丸めると、_cell_rectが列・行数分掛け算する
            # 際に誤差が蓄積し、盤面下部・右側ほど実機表示がズレる不具合になる。
            layout = BoardLayout(
                board_origin_x=(c.board_origin_x - self.origin_x) / self.dpr,
                board_origin_y=(c.board_origin_y - self.origin_y) / self.dpr,
                cell_size=c.cell_size / self.dpr,
                hold_rect=(
                    round((c.hold_rect[0] - self.origin_x) / self.dpr),
                    round((c.hold_rect[1] - self.origin_y) / self.dpr),
                    round(c.hold_rect[2] / self.dpr),
                    round(c.hold_rect[3] / self.dpr),
                ),
            )
            render_overlay(painter, layout, self.draw_data)

        # 【2026-09-07・暫定のデバッグ機能】next_debug_ready参照。
        if self.next_debug_slots is not None:
            self._draw_next_debug_dots(painter)
        painter.end()

    def _draw_next_debug_dots(self, painter: QtGui.QPainter) -> None:
        """【2026-09-07・暫定のデバッグ機能】NEXT欄5枠それぞれの右端寄りに、
        実際に認識できたミノの色でドットを描く(認識できていない枠は
        赤い×印にする)。実機でNEXT欄の中身と見比べて、テンプレート
        マッチングが正しく機能しているかを目視確認するためのもの。
        確認が終わったら削除する想定の一時的なコード。

        枠の外側(右)に描くと、画面録画のキャプチャ範囲(_region_bounds、
        OVERLAY_MARGINを含まない)からはみ出し、動画に映らないという
        指摘を受けた。枠の内側・右端寄りに描くことで、実機の画面・
        録画の両方で確認できるようにする。
        """
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        c = self.calibration
        radius = 8.0
        for rect, label in zip(c.next_rects, self.next_debug_slots):
            x, y, w, h = rect
            center_x = (x - self.origin_x) / self.dpr + w / self.dpr - radius - 4
            center_y = (y - self.origin_y) / self.dpr + radius + 4
            if label is not None and label in PIECE_COLORS:
                rgb = PIECE_COLORS[label]
                painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 255), 2))
                painter.setBrush(QtGui.QBrush(QtGui.QColor(rgb.r, rgb.g, rgb.b, 255)))
                painter.drawEllipse(QtCore.QPointF(center_x, center_y), radius, radius)
            else:
                painter.setPen(QtGui.QPen(QtGui.QColor(255, 0, 0, 255), 3))
                painter.drawLine(
                    QtCore.QPointF(center_x - radius, center_y - radius),
                    QtCore.QPointF(center_x + radius, center_y + radius),
                )
                painter.drawLine(
                    QtCore.QPointF(center_x - radius, center_y + radius),
                    QtCore.QPointF(center_x + radius, center_y - radius),
                )


class ControlBadge(QtWidgets.QWidget):
    """支援モード中に常時表示する、クリックスルーなしの小さな終了バッジ。

    オーバーレイ本体はクリックスルーにするため、ユーザーが確実にクリックで
    支援モードを終了できる手段をこのバッジ経由で必ず確保する。
    """

    def __init__(self, on_stop) -> None:  # noqa: ANN001
        super().__init__()
        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.Tool
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        # このウィンドウがフォーカスを奪ってゲーム側のキー操作(ポーズ等)を横取りしないよう、
        # アクティブ化せずに表示する。意図的にクリックスルーは設定しない
        # (クリックによる終了だけは必ず機能させたいため)。
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating)

        layout = QtWidgets.QHBoxLayout(self)
        label = QtWidgets.QLabel("支援モード中")
        label.setStyleSheet("color: white; background: rgba(0,0,0,190); padding: 4px 8px;")
        layout.addWidget(label)

        stop_btn = QtWidgets.QPushButton("終了")
        stop_btn.clicked.connect(on_stop)
        layout.addWidget(stop_btn)

        self.resize(220, 44)
        screen = QtWidgets.QApplication.primaryScreen().geometry()
        self.move(screen.width() - self.width() - 20, 20)


@dataclass
class _ColdClearContinuation:
    """Cold Clear 2が内部に持っている局面の写し(探索木の引き継ぎ用)。

    board: Cold Clear 2へ渡した(ライン消去済みの)着地済み盤面。
    queue: Cold Clear 2の内部キュー(reserve=ホールド相当を除く)。TBPの
      startでholdを渡さなかった場合は操作ミノがreserveになりqueue=NEXT、
      holdを渡した場合はqueue=[操作ミノ, *NEXT]になる(cold-clear-2の
      create_bot参照)。playのたびに先頭が1つ消費され、new_pieceで末尾に足す。
    """

    board: BoardState
    queue: list[str]
    # Cold Clear 2内部のreserve(ホールド相当)のミノ種。startでholdを渡さなかった
    # 場合は操作ミノが入る。playで指した手がreserveなら、queueの先頭がreserveに
    # なる(cold-clear-2のGameState::advance参照)。
    reserve: str


@dataclass
class _OpenerRun:
    """進行中の開幕テンプレの1つの図(src.engine.openers参照)。"""

    template: OpenerTemplate
    form: OpenerForm
    steps: list[OpenerStep]
    # 図を置き始める前の盤面(おじゃまを除く占有)。手順を進めるたびに
    # apply_stepで更新し、ライン消去による詰めも反映する。
    board: set[tuple[int, int]]
    index: int = 0  # 次に置く手
    # 固定を検知してから、盤面が手順どおりになったのをまだ確認できていない
    # 場合の検知時刻。Noneなら確認待ちではない。
    awaiting_since: float | None = None

    def current_step(self) -> OpenerStep | None:
        return self.steps[self.index] if self.index < len(self.steps) else None

    def expected_after_current(self) -> set[tuple[int, int]]:
        return apply_step(self.board, self.steps[self.index].cells)

    def as_move(self) -> ColdClearMove:
        """今の手をCold Clear 2の提案と同じ形にして返す(読み筋は残りの手順)。"""
        step = self.steps[self.index]
        plan = [(s.piece, list(s.cells)) for s in self.steps[self.index + 1 :]]
        return ColdClearMove(
            use_hold=step.use_hold,
            piece=step.piece,
            landing_cells=list(step.cells),
            nodes=0,
            nps=0.0,
            placement=None,
            plan=plan,
        )


def _non_garbage_cells(board: BoardState) -> set[tuple[int, int]]:
    """おじゃま(GARBAGE)を除いた占有マス。テンプレの図はおじゃまの上に載る前提。"""
    return {
        (r, c)
        for r, row in enumerate(board.grid)
        for c, cell in enumerate(row)
        if cell is not None and cell != "GARBAGE"
    }


def _garbage_row_count(board: BoardState) -> int:
    """盤面の下から続くおじゃま行の数(穴を除きGARBAGEで埋まった行)。"""
    count = 0
    for r in range(board.height - 1, -1, -1):
        row = board.grid[r]
        garbage = sum(1 for cell in row if cell == "GARBAGE")
        if garbage >= board.width - 2 and all(cell in (None, "GARBAGE") for cell in row):
            count += 1
        else:
            break
    return count


def _board_occupancy(board: BoardState) -> tuple[tuple[bool, ...], ...]:
    """占有だけを比較するための盤面キー(種類は無視)。"""
    return tuple(tuple(cell is not None for cell in row) for row in board.grid)


def _board_after_placement(board: BoardState, piece: str, cells: tuple[tuple[int, int], ...]) -> BoardState:
    """boardにcellsのミノを置き、揃った行を消した盤面を返す。"""
    placed = board.clone()
    for r, c in cells:
        if 0 <= r < placed.height and 0 <= c < placed.width:
            placed.grid[r][c] = piece
    cleared, _ = placed.clear_lines()
    return cleared


def _plan_steps_on_screen(board: BoardState, move: ColdClearMove) -> list[PlanStep]:
    """読み筋(2手目以降)のうち、今の画面座標のまま表示できる手を返す。

    ライン消去が起きると、それ以降の手の着地マスは(盤面が下へ詰まるため)
    今の画面上の位置と対応しなくなる。1手目から順に仮想的に置いていき、
    ラインが消える手までを表示対象にする(その手自身は消去前の座標なので
    表示できる。次の手からは表示しない)。
    """
    steps: list[PlanStep] = []
    if not move.plan:
        return steps
    placed = board.clone()
    for r, c in move.landing_cells:
        if 0 <= r < placed.height and 0 <= c < placed.width:
            placed.grid[r][c] = move.piece
    placed, cleared = placed.clear_lines()
    if cleared:
        return steps
    for piece, cells in move.plan:
        steps.append(PlanStep(piece=piece, cells=list(cells)))
        for r, c in cells:
            if 0 <= r < placed.height and 0 <= c < placed.width:
                placed.grid[r][c] = piece
        placed, cleared = placed.clear_lines()
        if cleared:
            break
    return steps


class AssistWorker(QtCore.QThread):
    """支援モードの認識→思考ループを、UIスレッドをブロックせず回すワーカー。

    以前は QTimer で TICK_INTERVAL_MS ごとに _tick をメインスレッドで実行していたが、
    1回分の処理（画面キャプチャ＋認識＋Cold Clear思考）が150msを超えることが多く、
    QTimerは処理完了後にしか次のtimeoutを発火しないため、実質的な周期が
    処理時間に引きずられてどんどん間延びしていた（実機で「提案がまだ遅い」と
    報告された）。ここでは別スレッドで固定間隔の待機を挟まないループを回し、
    変化がなかった時だけ短いIDLE_SLEEP_MSで休むことで、新しいミノのスポーンに
    対する反応を「1回分の処理時間」程度まで縮める。
    """

    draw_data_ready = QtCore.pyqtSignal(object)  # OverlayDrawData | None
    # 【2026-09-07・暫定のデバッグ機能】NEXT欄のテンプレートマッチングが
    # 実際に正しく認識できているかを実機で目視確認できるよう、毎tickの
    # 生の認識結果(recognition.next_slots_raw、5枠・認識失敗はNone)を
    # そのまま流す。本採用の機能ではないため、確認が終わったら削除する。
    next_debug_ready = QtCore.pyqtSignal(object)  # tuple[str | None, ...]
    # Cold Clear 2プロセスとの通信で致命的なエラーが起きた時に発行する。
    # 以前はstart_thinking/poll_suggestion内の例外を一切捕まえておらず、
    # Cold Clear 2プロセスが何らかの理由でクラッシュすると、ワーカースレッド
    # 全体が例外で停止し、UIは正常に見えるのに裏では提案が二度と更新されない
    # という気付きにくい壊れ方をする恐れがあった。ここで検知してメイン
    # スレッドに伝え、ユーザーに分かる形で支援モードを終了させる。
    fatal_error = QtCore.pyqtSignal(str)

    # 有意な変化がない間、CPU使用率を抑えるための最小待機時間。
    # 短すぎるとポーリングでCPUを占有し、長すぎると反応が遅れる。
    # Cold Clear 2との通信自体は1回あたり1ms未満(実測)と極めて高速なため、
    # ボトルネックにはならない。一方この値は「新しいミノがスポーンしてから
    # 次にrecognize()が呼ばれるまでの最大遅延」に直結するため、体感速度への
    # 影響が大きい。「提案がまだ遅い」という指摘を受け、CPU負荷が問題にならない
    # 範囲で20msから短縮した。
    IDLE_SLEEP_MS = 8

    # 同じミノを操作している間、Cold Clear 2への再問い合わせ(poll_suggestion)は
    # この間隔以上空けてから行う。段階的思考の導入で提案がどんどん更新される
    # ようになった一方、更新頻度が高すぎるとオーバーレイの再描画がWindows側の
    # 画面合成に追いつかず「前の提案が消える前に次の提案が別の場所に描かれ、
    # 一瞬両方見える」不具合が実機で確認された。新規スポーン直後は即座に
    # 問い合わせる（この間隔は適用しない）。
    POLL_INTERVAL_SEC = 0.1

    # 表示中の提案がこの時間以上更新されずに残り続けた場合、強制的に
    # クリアする最後の手段の保険（詳細は_last_draw_data_set_timeのコメント
    # 参照）。
    # 以前は0.8秒だったが、これは「1手を0.8秒以内に置く」ことを暗黙の前提に
    # した値であり、対象である初心者の操作速度と合っていなかった。提案を
    # 消してよいのは固定を検出した時だけ(_detect_lock参照)という設計に
    # 変えたため、この保険は固定の検出自体が壊れた場合にのみ働けばよい。
    # 人間が1手に費やしうる時間より十分長い値にする。
    STALE_DRAW_DATA_TIMEOUT_SEC = 15.0

    # 認識失敗が続いている間、表示中の提案を維持する上限時間。
    # 認識できないことは「置いた」ことを意味しないので原則として提案は
    # 維持するが、対局終了後の結果画面や映像の途絶では認識失敗が延々と
    # 続き、その間STALE_DRAW_DATA_TIMEOUT_SECの判定にも到達しない
    # (認識に成功したtickでしか評価されないため)。そのまま無関係な画面に
    # 提案が残り続けるのを防ぐ上限として設ける。
    # 実機では、通常プレイ中の認識失敗は最長でも約1.3秒、積みが天井near
    # まで達した場面でも約8秒だった。この値を超える連続失敗は、対局が
    # 終わったか映像が変わったと考えるのが妥当。
    # 併せて、資料の「21段目以上の固定状態が不明なら提示を停止する」という
    # 方針とも整合する。
    SUGGESTION_HOLD_DURING_FAILURE_SEC = 5.0

    # _is_plausible_board_transitionが「あり得ない変化」と判定し続ける状態が
    # この時間以上続いたら、汚れている可能性を承知の上でその時点の盤面を
    # 受け入れる保険（詳細は_tick_once内のboard_data_trustworthy周りの
    # コメント参照）。実機動画で確認されたT-Spin等の光エフェクトは
    # 0.5秒程度で収まっていたため、以前は1.0秒としていたが、それでも
    # 「長時間提示が来ない」という報告が続いたため、提案が止まって見える
    # 時間そのものを短くする目的で0.3秒まで縮めた(この値を短くしても、
    # 「毎tick再判定する」という仕組み自体は変わらないため、本当に
    # クリーンな読み取りに戻ればそちらが優先される。デメリットは
    # 汚れたデータを受け入れる頻度がわずかに増えることだけで、
    # 「提案が長時間止まる」ことに比べればはるかに軽微)。
    # 【2026-09-11・6回目の実機録画】0.3秒では、4列消しの「TETRIS」表示や
    # 閃光(約1.5秒続く)の途中で強制受理が4回連続し、エフェクトが混ざった
    # 盤面で提案して空中・干渉になった。エフェクトの継続時間を超える値にする。
    # 長すぎると本当に読めない場面で提案が止まるが、間違った提案を出すより
    # ましと判断する(仕様「正確な画像認識」)。
    BOARD_TRUST_TIMEOUT_SEC = 1.0

    # 【以下は2026-09-07の全面設計変更前の経緯】新規スポーン検知
    # (piece_changed/respawned_same_piece/next_prefix_changed/
    # board_key_changed)が束になっても、実機では「盤面・HOLD欄が実際には
    # 何度も変化しているのに、この4条件が同時にすべて機能しない」時間が
    # 20秒近く続き、その間ずっと提案が更新されないままトップアウトする
    # 致命的な不具合が実機動画で確認された(HOLD欄の色が複数回変化=実際に
    # 何度もミノが入れ替わっていたにも関わらず、4条件のどれも
    # significant_changeを検知できていなかった。個々の検知条件を後から
    # いくら継ぎ足しても、未知の組み合わせで4条件すべてが同時に沈黙する
    # 可能性を完全には潰せない)。原因の特定・対症療法を積み重ねるのではなく、
    # 「検知条件が何であれ、一定時間ごとに強制的に最新の認識結果で
    # 思考をやり直す」という無条件の保険を最後の砦として設ける。これにより
    # 「提案が止まって見える」時間そのものに上限がかかる。
    #
    # 【2026-09-07・全面設計変更】上記4条件は、落下中のミノ・盤面認識由来の
    # ノイズにそれぞれ独立して弱いという構造的な問題があったため、
    # ネクスト欄5枠のうち認識できている枠の変化だけを見る単一の検知
    # (next_advanced、_tick_once参照)に統一した。この保険自体は、
    # ネクスト欄5枠が長時間まとめて認識不能になるような未知の状況への
    # 備えとして、そのまま残す。
    MAX_SIGNIFICANT_CHANGE_SILENCE_SEC = 1.5

    # 認識結果全体(current_piece, hold_piece, next_queue, board_key)を
    # 「意味のある変化」として提案へ反映する前に、この回数だけ連続して
    # 同じ内容が観測されることを要求する(_stabilize_recognition参照)。
    # Tetris99のAI「ジェフ」が採用している「安定した画像が得られるまで
    # 待機してから状態を読み取る」設計を参考にした。これまでの対策
    # (I/J誤判定・ゴーストの誤検出・光エフェクトのブレなど)は、いずれも
    # 「1枚の画像だけで即断する」という前提の上で、既知のノイズパターンを
    # 1つずつ後追いで潰す方式だったため、新しいノイズパターンが出るたびに
    # 別の穴が開き続けていた。
    #
    # 【1(=待たない)にした経緯】
    # 実機の処理時間の計測で、この待機が「提示が遅い」の主因だと判明した。
    # 足止めしたtick数は中央値4、95百分位15〜18、最大28。1tickが約80ms
    # (画像取得と認識が60ms、録画16ms)なので、中央値で約320ms、95百分位で
    # 1.2〜1.4秒、最悪2.2秒を、認識できているのに待つだけに使っていた。
    # AIへの問い合わせは中央値1.1msで全く遅くない。
    #
    # この層は、各項目の個別対策が揃う前に入れた包括的な安全網だった。
    # 現在は項目ごとに、より的確な対策が入っている:
    #   ・NEXT     : 移動量の候補比較(_estimate_next_shift)
    #   ・盤面     : セル単位の2tickデバウンス(_stabilize_settled_grid)と
    #                board_keyの2tickデバウンス
    #   ・操作ミノ : NEXT履歴からの導出と、食い違いが続いた場合の再同期
    #   ・AI結果   : 手番キーによる照合と、提案ミノの実在検証
    # そのため、全項目に一律で待機を課す価値より、遅延の害が上回ると判断した。
    # 1にすると最初の観測をそのまま採用する(=この層を通り抜ける)。
    # ノイズが再発する場合は、まずこの値を2〜3へ戻して切り分けること。
    RECOGNITION_STABILITY_TICKS = 1

    # 上記の安定化を待っている間に、認識結果が一切安定しないまま
    # この時間が経過した場合、汚れている可能性を承知の上でその時点の
    # 最新の認識結果を強制的に採用する(既存のBOARD_TRUST_TIMEOUT_SECと
    # 同じ考え方の保険。安定待ちを導入したことで「いつまでも提案が
    # 来ない」事態を新たに生まないようにする)。
    RECOGNITION_STABILITY_TIMEOUT_SEC = 1.0

    def __init__(
        self,
        calibration: CalibrationResult,
        cold_clear: ColdClearClient,
        debug_log_path: Path | None,
        record_video: bool = False,
        opener_enabled: bool = False,
        plan_depth: int = 3,
    ) -> None:
        super().__init__()
        self.calibration = calibration
        self.cold_clear = cold_clear
        # 対局開始時に開幕テンプレ(src.engine.openers)を提示するか。
        self._opener_enabled = opener_enabled
        # 表示する手数(1=今の手だけ、最大5)。2手目以降が読み筋ドットになる。
        self._plan_depth = max(1, min(5, plan_depth))
        self._debug_log_path = debug_log_path
        self._debug_log_file = None
        # 画面録画(暫定機能)。有効な場合、支援モード中キャリブレーション
        # 済みの範囲(盤面+HOLD+NEXT欄)をDEBUG_VIDEO_PATHへmp4で書き出す。
        self._record_video = record_video
        self._video_writer = None
        self._last_video_frame_time: float = 0.0
        # 【2026-09-07・暫定のデバッグ機能】next_debug_ready参照。
        self._last_next_debug_slots: tuple[str | None, ...] | None = None
        self._running = True
        self._last_current_piece: str | None = None
        # 【2026-09-07・ユーザー指示で全面設計変更】新規スポーン(=「手が
        # 進んだ」)の検知は、ネクスト欄5枠のうち認識できている枠が変化した
        # 場合にのみ発火する方式に統一した。以前はcurrent_piece(落下中の
        # ミノ)の形状変化・位置変化・着地済み盤面の変化もそれぞれ独立した
        # 検知条件として使っていたが、いずれも「落下中のミノ・盤面認識」由来の
        # ノイズに弱く、個別にデバウンスを継ぎ足しても新しいノイズパターンが
        # 出るたびに別の穴が開き続けていた。ユーザーの整理により、そもそも
        # 「手が進んだかどうか」は落下中のミノやホールドの状態とは無関係に
        # 「ネクスト・ネクネクが変化したかどうか」だけで判定すべきという
        # 設計方針に統一した(_compute_next_advanced参照)。
        #
        # ネクスト欄は5枠あり、そのうち1〜2枠が誤読で認識できなくても
        # 残りの枠から変化を確認できるため、next[:2]の2要素だけを見る
        # 旧方式より構造的に頑健(1箇所の誤読がそのまま誤判定に直結しない)。
        # 直近に確定したtickでの、ネクスト5枠の内容(認識できていない枠は
        # None=保留のまま位置を保持する。next_queueのように詰めて除外すると
        # 1箇所の誤読が後続すべての位置をズラしてしまうため使わない)。
        self._confirmed_next_slots: tuple[str | None, ...] | None = None
        # _confirmed_next_slotsが「1回の観測だけから作った暫定の基準」か。
        # 次の観測が移動量0〜2で整合すれば確定し、整合しなければ待たずに
        # 差し替える(残課題2-2)。
        self._next_baseline_provisional = False
        # 直近tickでの着地済み盤面(board_key)。current_pieceの形状比較・
        # スポーン行しきい値・NEXT欄先頭比較がすべて同時に機能しなくなる
        # 場面（後述）でも新規スポーンを取りこぼさないための最終手段として使う。
        self._last_board_key: tuple[tuple[str | None, ...], ...] | None = None
        # board_key変化を2tick連続で確認するためのデバウンス用候補値。
        self._pending_board_key: tuple[tuple[str | None, ...], ...] | None = None
        # 直近tickで信頼した「着地済み領域の最上段行」(settled_top_row、
        # デバウンス適用後の実効値)。次tickのrecognize()へ
        # previous_settled_top_row_hintとして渡し、操作中ピースが着地済み
        # ブロックのすぐ近く(1行の隙間以内)を落下している時に、そのピース
        # 自身の行が着地済み領域の一部として誤って取り込まれるのを防ぐ
        # (詳細はrecognize()・_bridge_looks_like_falling_pieceのコメント参照)。
        self._last_settled_top_row: int | None = None
        # 着地済みマスの色安定化用(_stabilize_settled_grid参照)。直近tickで
        # 確定した盤面グリッドと、まだ1回しか観測されていない新しい色の
        # 候補(pending)。次tickのrecognize()へヒントとして渡し続けることで、
        # 「1枚の画像だけで色を即断せず、2tick連続で同じ新しい色が確認
        # できて初めて確定する」を実現する。
        self._last_confirmed_grid: list[list[str | None]] | None = None
        self._last_pending_grid: list[list[str | None]] | None = None
        # 認識結果全体の安定化用(_stabilize_recognition参照)。直近tickで
        # 観測されている(current_piece, hold_piece, next_queue, board_key)の
        # 組と、それが何tick連続で観測され続けているか。
        self._stability_candidate_key: tuple | None = None
        self._stability_candidate_count: int = 0
        # 上記の組が現在の値に変わった(観測され始めた)時刻。タイムアウト
        # 判定(RECOGNITION_STABILITY_TIMEOUT_SEC)に使う。
        self._stability_candidate_since: float = 0.0
        # 最後に「安定した」と判定され、以降の提案生成に実際に使われた
        # 認識結果。まだ一度も安定していない場合はNone。
        self._last_stabilized_recognition: RecognitionResult | None = None
        # board_data_trustworthy(_tick_once参照)が最後にTrueだった時刻。
        # BOARD_TRUST_TIMEOUT_SEC以上信頼できる読み取りが得られない状態が
        # 続いた場合の強制受理タイムアウトに使う。
        self._last_board_trustworthy_time: float = 0.0
        # 最後にsignificant_change(新規スポーン検知)が成立した時刻。
        # MAX_SIGNIFICANT_CHANGE_SILENCE_SEC以上これが成立しない状態が
        # 続いた場合の強制リフレッシュに使う。
        self._last_significant_change_time: float = 0.0
        self._prev_hold_piece: str | None = "UNKNOWN"
        # 現在のミノについて実際にdisallow_holdを適用しているかどうか。
        # hold_piece訂正時にもこの状態を引き継ぐために保持する。
        self._disallow_hold_active = False
        self._consecutive_recognition_failures = 0
        # 認識失敗が連続し始めた時刻(_note_recognition_failure参照)。
        # 失敗していない間はNone。
        self._recognition_failure_started_at: float | None = None
        # 現在Cold Clear 2へ質問している局面の識別情報(_turn_key参照)。
        # start_thinkingのたびに更新し、結果を表示する前に照合する。
        self._thinking_turn_key: tuple[str | None, str | None, tuple[str, ...]] | None = None
        # NEXTの窓から出ていったミノ(=新しい操作ミノ)。スポーン直後の画像は
        # 直前に固定したミノをまだ含むため画像認識より信頼できる。
        self._expected_current_piece: str | None = None
        # 画像認識の操作ミノが_last_current_pieceと食い違い続けたtick数。
        # スポーン直後の一時的な食い違いと、本当にズレた状態を区別する
        # (_resync_current_piece_if_desynced参照)。
        self._current_piece_disagreement_ticks = 0
        # 手番キーがCold Clear 2への要求時と食い違い続けたtick数。
        self._turn_key_mismatch_ticks = 0
        # NEXTの移動量を判断できなかったtick数(_estimate_next_shift参照)。
        self._next_shift_undecided_ticks = 0
        # 直前tickで観測が基準の1枠だけと矛盾していた場合の(枠番号, 観測値)。
        # 同じ矛盾が2tick続いたら基準のその枠を置き換える
        # (_find_single_slot_conflict参照)。
        self._next_slot_conflict: tuple[int, str] | None = None
        # 「物理的に成立しない提案を破棄」を同じ提案について毎tick記録しない
        # ための、最後に記録した提案(ミノ種, 着地マス)。
        self._last_logged_invalid_move_key: tuple[str, tuple[tuple[int, int], ...]] | None = None
        # 処理段ごとの所要時間(_record_latency参照)。
        self._latency_samples: dict[str, list[float]] = {}
        # 安定化待ちで足止めしたtick数(_stabilize_recognition参照)。
        self._stability_hold_ticks = 0
        # Cold Clear 2との通信が壊れているか(_handle_cold_clear_failure参照)。
        self._cold_clear_broken = False
        self._cold_clear_retry_at = 0.0
        # 局面を渡すべきなのにまだ渡せていない状態か(操作ミノ不明、盤面が
        # 信用できない等)。Trueの間は毎tick要求を試みる。
        # 支援モード開始直後は必ずTrueから始める。
        self._needs_start_thinking = True
        self._last_valid_draw_data: OverlayDrawData | None = None
        # _last_valid_draw_dataを最後に更新した時刻。ライン消去・着地演出等の
        # エフェクトが原因で盤面認識が一時的に乱れると、「実行済みで既に
        # 無効なはずの提案」が新しい提案に置き換わるまでの間、表示され
        # 続けてしまうことが実機動画で確認された（着地演出中、新しい
        # ミノの認識自体は問題なくできているように見えるのに、なぜか
        # 古い提案がすぐには消えない現象。正確な原因は特定できていないが、
        # 何らかの理由で認識が乱れている可能性が高い）。認識の乱れそのもの
        # を直接解消するのは難しいため、保険として「一定時間ごとに新しい
        # 提案が来ない場合は、古い提案を強制的にクリアする」というタイム
        # アウトを設ける。
        self._last_draw_data_set_time: float = 0.0
        # 直近にログへ書いたColdClearMove。「思考が進んでより良い手が
        # 見つかった時だけ」ログに追記するために、前回との差分比較に使う。
        self._last_logged_move_key: tuple | None = None
        self._last_poll_time: float = 0.0
        # DEBUG_FRAMES_HISTORY_DIRのローテーション用カウンタ。
        self._frame_history_counter = 0
        # 提案の安定化用。探索が浅い段階と深まった段階とで、best.use_hold
        # だけでなく着地位置(landing_cells)自体も覆るケースが実機ログで
        # 確認された（例: 同じOミノに対し、nodes=51の浅い探索では列8-9、
        # nodes=166920まで深まると列5-6、さらにnodes=681614まで深まると
        # また列8-9に戻る、という着地位置の往復）。もしユーザーが提示された
        # 通りにミノを動かし始めた直後に提案が別の配置へ切り替わると、
        # 「操作の途中で梯子を外される」体験になり実用性を著しく損なう
        # （実際に「提示したように置こうとしたら急に違う手を提示されて
        # 使い物にならない」との報告を受けた）。use_holdだけでなく配置
        # 全体(use_hold, piece, landing_cells)を対象に安定化する。
        # 型は (use_hold, piece, landing_cellsのタプル) の3要素タプル。
        # _committed_placement: そのミノについて最後に確定・表示した配置
        self._committed_placement: tuple[str, tuple[tuple[int, int], ...]] | None = None
        # 提示済み配置のTBP上の手(Placement辞書。playで伝え直す用)。
        self._committed_placement_tbp: dict | None = None
        # 提示済みの手そのもの(読み筋を含む)。同じ配置が届いた時にこれを返す。
        self._committed_move: ColdClearMove | None = None
        # Cold Clear 2の探索木を引き継げる状態か(_ColdClearContinuation参照)。
        # Noneなら次の要求は従来どおりstartで局面を渡し直す。
        self._cc_continuation: _ColdClearContinuation | None = None
        # 要求を見送ったtickで固定(HOLD変化なしのnext_advanced)があったか。
        # 再試行のtickで探索木の引き継ぎ(play)を判断するために持ち越す。
        self._cc_pending_lock = False
        # 進行中の開幕テンプレ(_OpenerRun参照)。Noneなら通常どおりAIの提案を出す。
        self._opener: _OpenerRun | None = None
        # 直前に1つの図を置き終えたテンプレ。次の図(2巡目以降)はこのテンプレの
        # 中から、今の盤面に既存ブロックが一致するものを探す。図が見つから
        # なかったり中断したらNoneに戻し、次に盤面が空になるまで始めない。
        self._opener_continuing: OpenerTemplate | None = None
        # 「該当なし」を同じミノ順で毎tick記録しないための控え。
        self._opener_declined_sequence: list[str] | None = None

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:  # noqa: D102 - QThreadの規約通りの名前
        capture = ScreenCapture()
        if self._debug_log_path is not None:
            self._debug_log_file = open(self._debug_log_path, "a", encoding="utf-8")
            # _APP_MODULE_LOAD_TIME(モジュールがプロセスに読み込まれた時点の
            # app.py更新時刻。詳細は定義箇所のコメント参照)を記録する。
            # これが実際のapp.pyのファイル更新時刻より古ければ、メイン
            # ウィンドウのプロセスを再起動しないまま支援モードだけを
            # 使い続けている、という判断ができる。
            self._debug_log_file.write(
                f"\n===== 支援モード開始 {QtCore.QDateTime.currentDateTime().toString()} "
                f"(app.pyロード時刻: {_APP_MODULE_LOAD_TIME}) =====\n"
            )
        try:
            while self._running:
                try:
                    self._tick_once(capture)
                except Exception as exc:  # noqa: BLE001 - 詳細は下記コメント参照
                    # 以前はCold Clear 2との通信エラー(RuntimeError/OSError/
                    # ValueError)だけを狙い撃ちでキャッチしていたが、それ以外の
                    # 型の例外（_tick_once内の新機能のバグ等、予期しないもの）が
                    # 起きた場合、ここでキャッチされずワーカースレッドがそのまま
                    # 静かに終了し、「支援モードをクリックするとクラッシュする」
                    # としか分からない、原因追跡が極めて困難な壊れ方をする実害が
                    # 実際に確認された。さらにpythonw(コンソール非表示)化した
                    # ことで、この手のトレースバックが完全にどこにも表示されなく
                    # なっていた。原因の型を問わず全てここで捕捉し、crash_log.txt
                    # に詳細なトレースバックを残した上で、ユーザーに分かる形で
                    # 支援モードを終了させる。
                    import traceback

                    crash_log_path = Path(__file__).resolve().parent.parent / "crash_log.txt"
                    with open(crash_log_path, "a", encoding="utf-8") as f:
                        f.write(f"\n===== クラッシュ {datetime.now().isoformat()} =====\n")
                        traceback.print_exc(file=f)
                    print(f"予期しないエラー: {exc}")
                    self.fatal_error.emit(str(exc))
                    break
        finally:
            capture.close()
            if self._debug_log_file is not None:
                self._debug_log_file.close()
            if self._video_writer is not None:
                self._video_writer.release()
                self._video_writer = None

    def _tick_once(self, capture: ScreenCapture) -> None:
        tick_started = time.perf_counter()
        if self._record_video:
            video_started = time.perf_counter()
            self._record_video_frame(capture)
            self._record_latency("録画の書き出し", time.perf_counter() - video_started)
        debug_dir = DEBUG_FRAMES_DIR if self._debug_log_file is not None else None
        recognize_started = time.perf_counter()
        try:
            recognition = recognize(
                self.calibration,
                capture,
                debug_save_dir=debug_dir,
                previous_piece_hint=self._last_current_piece,
                previous_settled_top_row_hint=self._last_settled_top_row,
                previous_confirmed_grid_hint=self._last_confirmed_grid,
                previous_pending_grid_hint=self._last_pending_grid,
            )
        except Exception as exc:  # noqa: BLE001 - 認識失敗の1フレームでループ全体を止めない
            # pythonw環境ではsys.stdoutがdevnullに差し替えられており、
            # print()だけでは何も報告されないのと同じになる(28番の
            # 録画エラーで判明した教訓と同じ)。デバッグログが有効な場合は
            # そちらにも必ず記録する。
            print(f"認識エラー: {exc}")
            if self._debug_log_file is not None:
                self._debug_log_file.write(f"\n===== 認識エラー: {exc} =====\n")
                self._debug_log_file.flush()
            recognition = None
        self._record_latency("画像取得と認識", time.perf_counter() - recognize_started)

        if recognition is None:
            self._consecutive_recognition_failures += 1
            self._note_recognition_failure()
            if self._consecutive_recognition_failures >= MAX_CONSECUTIVE_RECOGNITION_FAILURES:
                self._last_current_piece = None
                self._expected_current_piece = None
                self._confirmed_next_slots = None
                self._next_baseline_provisional = False
                self._cc_continuation = None
                self._last_board_key = None
                self._pending_board_key = None
                self._last_settled_top_row = None
                self._last_confirmed_grid = None
                self._last_pending_grid = None
                self._stability_candidate_key = None
                self._stability_candidate_count = 0
                self._last_stabilized_recognition = None
                self._prev_hold_piece = "UNKNOWN"
                self._disallow_hold_active = False
                # 【表示中の提案はここでは消さない】
                # 仕様は「提示した配置は、実際にミノを置くまで変更しない」で
                # あり、認識できないことは「置いた」ことを意味しない。
                # 以前はここで提案をクリアしていたため、認識失敗のたびに
                # 提案が消えていた。実機の録画解析では、提案が表示されて
                # いない時間が稼働時間の46%(76.2秒/167秒、99区間、中央値
                # 536ms)に達し、その合計は認識失敗の合計時間(78.7秒)と
                # ほぼ一致していた。特に積みが高いほど認識失敗が長引くため
                # (top<=8で平均1.08秒・最大8.09秒)、支援が最も必要な局面で
                # 提案が消えるという本末転倒な挙動になっていた。
                # 提案を消すのは固定を検出した時だけにする(_detect_lock参照)。
                # ただし対局終了後の結果画面などでは認識失敗が延々と続くため、
                # 上限を超えたら無関係な画面に提案を残さないようクリアする。
                if (
                    self._last_valid_draw_data is not None
                    and self._recognition_failure_started_at is not None
                    and time.monotonic() - self._recognition_failure_started_at
                    >= self.SUGGESTION_HOLD_DURING_FAILURE_SEC
                ):
                    self._last_valid_draw_data = None
                    self._last_draw_data_set_time = time.monotonic()
                    self.draw_data_ready.emit(None)
                    if self._debug_log_file is not None:
                        self._debug_log_file.write(
                            "----- 認識失敗が続いたため表示中の提案をクリア -----\n"
                        )
                        self._debug_log_file.flush()
                # NEXT欄のデバッグ表示(ドット/×)は、認識できていない事実を
                # 反映させる。これを更新しないと、認識に失敗し続けている間
                # 「最後に成功したtickの結果」が画面と録画に残り続け、実際
                # には読めている枠が×のまま表示され続ける。実機の不具合
                # 調査で、この古い表示を「NEXTが認識できていない」証拠だと
                # 誤読しかけたため、表示が実態から乖離しないようにする。
                blank_slots = (None,) * len(self.calibration.next_rects)
                if self._last_next_debug_slots != blank_slots:
                    self._last_next_debug_slots = blank_slots
                    self.next_debug_ready.emit(blank_slots)
            self.msleep(self.IDLE_SLEEP_MS)
            return

        if self._consecutive_recognition_failures > 0:
            self._note_recognition_recovered()
        self._consecutive_recognition_failures = 0

        # 【2026-09-07・暫定のデバッグ機能】next_debug_ready参照。
        self._last_next_debug_slots = recognition.next_slots_raw
        self.next_debug_ready.emit(recognition.next_slots_raw)

        # 次tickのrecognize()へ渡すsettled_top_rowの信頼値を更新する。
        # recognize()側で既に「橋渡し候補が操作中ミノ自身らしいか」を
        # 単一フレームの構造で判定済み(_bridge_looks_like_falling_piece)
        # なので、ここでは単純にこのtickの実効値(settled_top_row)を
        # そのまま次回の基準値として引き継ぐだけでよい(時間ベースの
        # デバウンスは、緩やかな重力でミノが何tickも同じ行に静止し続ける
        # ケースを区別できず不十分だったため廃止した)。
        self._last_settled_top_row = recognition.settled_top_row
        # 次tickのrecognize()へ渡す着地済みマスの色安定化状態を更新する
        # (_stabilize_settled_grid参照)。board.gridは既に安定化後の値。
        self._last_confirmed_grid = (
            recognition.confirmed_grid if recognition.confirmed_grid is not None else recognition.board.grid
        )
        self._last_pending_grid = recognition.pending_grid

        # ここまでは、recognize()内部の細かい安定化(境界推定・色安定化等)の
        # ためのヒント更新であり、常に生の(今tickの)認識結果を使う。
        # 以降の「新規スポーン検知・提案生成」には、_stabilize_recognitionで
        # 複数tick分の安定を確認した結果を使う(詳細はそのdocstring参照)。
        recognition = self._stabilize_recognition(recognition)

        # 現在表示中の提案が指す着地マスが、最新の盤面認識では既に
        # ブロックで埋まっている場合、その提案は「もう実行された過去の
        # ミノに対するもの」であり、既に無効。新しいミノがスポーンして
        # から新しい提案が計算し終わるまでのわずかな間、この「もう存在
        # しないはずのミノの置き場所」がそのまま画面に残り続ける現象が
        # 実機の動画で確認された（例: Iを配置した直後も一瞬「Iをここに
        # 置け」という提案が消えずに表示され続ける）。新しい提案を待つより、
        # 古い無効な提案を即座に消す方がユーザーの混乱を防げる。
        #
        # ただし「1マスでも埋まっていたらクリア」(any)だと、盤面認識の
        # ノイズで1マスだけ誤って「埋まっている」と判定された瞬間に、
        # まだ実行されていない正当な提案までクリアしてしまい、それが
        # 「表示が一瞬消えてすぐ復活する」という新たな点滅の原因になる
        # おそれがある。本当にそのミノが設置されたのであれば4マス全てが
        # 埋まるはずなので、全マスが埋まっている場合だけクリアすることで
        # 1マスノイズへの耐性を持たせる。
        #
        # ここで即座にemit(None)してしまうと、この同じtick内で直後に
        # 新しい提案が得られてすぐemit(new_data)された場合、「一瞬空白→
        # 即座に新しい提案」という2段階の描画更新が1tickの間に発生して
        # しまう。Windows側の画面合成がこの短時間の2度更新に追いつかず、
        # オーバーレイがちらつく（実機動画で確認）原因になっていたため、
        # ここでは判定だけ行い、実際のemitはこのtickの最終的な結果が
        # 確定した後（新しい提案が得られなければその時にemit(None)する）
        # まで遅らせる。
        stale_suggestion_detected = (
            self._last_valid_draw_data is not None
            and self._last_valid_draw_data.landing_cells
            and all(
                recognition.board.grid[r][c] is not None
                for r, c in self._last_valid_draw_data.landing_cells
            )
        )
        # 上記の着地マス判定は、ライン消去・着地演出等のエフェクトで盤面
        # 認識が一時的に乱れると機能しないことがある（実機動画で、着地演出
        # 中に新しいミノ自体は認識できているのに、なぜか古い提案がすぐには
        # 消えない現象を確認した。正確な原因は特定できていない）。保険として、
        # 表示中の提案が一定時間更新されずに残り続けている場合も、強制的に
        # クリア対象とする。
        if (
            not stale_suggestion_detected
            and self._last_valid_draw_data is not None
            and (time.monotonic() - self._last_draw_data_set_time) >= self.STALE_DRAW_DATA_TIMEOUT_SEC
        ):
            stale_suggestion_detected = True

        # 【2026-09-07・ユーザー指示で全面設計変更】「手が進んだ」(=新しい
        # ミノについて考え直すべきタイミング)の検知は、落下中のミノ
        # (current_piece)の形・位置にも、ホールドの状態にも、着地済み盤面
        # にも依存せず、ネクスト欄5枠のうち認識できている枠が変化したか
        # どうかだけで判定する。ネクストキューは新規スポーンの瞬間にしか
        # 動かず、ホールド操作では消費されない、というゲームルール上の
        # 不変条件を使う。
        #
        # next_queue(認識失敗枠を詰めて除外したもの)ではなく、位置を保った
        # 生の5枠(next_slots_raw)を使う。認識できていない枠は「保留」として
        # 比較対象から単純に除外し(値を確定させず、次tick以降の再認識に
        # 任せる)、5枠中で認識できている残りの枠だけで判定する。5枠中の
        # どれか1〜2枠が誤読・認識失敗しても、構造上すべての枠が同時に
        # 失敗することは考えにくいため、next[:2]の2要素だけを見ていた
        # 旧方式より頑健(1箇所の誤読がそのまま誤判定に直結しない)。
        next_advanced = False
        # NEXTの移動量。Noneは「判断できなかった」。初回はNoneのままにする。
        next_shift: int | None = None
        next_slots = recognition.next_slots_raw
        if self._confirmed_next_slots is None:
            # 【2026-09-07・実機ログ解析で発見したバグを修正】このアプリの
            # 起動後・支援モード開始後、最初のtickでは比較対象がなく
            # next_advancedをTrueにできないため、ここまではFalseのままに
            # なっていた。以前の設計(piece_changed)では「直前値がNone」
            # という状態自体が「現在値と食い違う」ため自然に初回だけ
            # Trueになっていたが、next_advanced一本化でこの初回検知が
            # 失われていた。結果として最初のミノについてはMAX_
            # SIGNIFICANT_CHANGE_SILENCE_SEC(最大1.5秒)のタイムアウト
            # 保険が発動するまで最初の提案が出ず、「提示が遅い」の一因に
            # なっていた。初回は無条件でnext_advancedを立てる。
            #
            # 【2026-09-11・残課題2-2】ただし1回の観測だけから作った基準は
            # 暫定とする。以前は無検証で確定していたため、1枠でも誤読が
            # あると移動量推定(不一致ゼロを要求)がどの移動量でも説明でき
            # なくなり、再アンカー(15tick≒3秒)までNEXTの進行が止まった。
            # 実機では最初の1枚が('J','O','S','T','L')、実際は
            # ('O','S','T','Z','L')で、L/Zの1枠だけで2手目(S)の提案が
            # 出なかった。暫定の間は、次の観測が整合しなければ待たずに
            # 差し替える(下記shift is None分岐)。
            self._confirmed_next_slots = next_slots
            self._next_baseline_provisional = True
            next_advanced = True
            # 初回は比較対象が無く、消費されたミノを履歴から求められない。
            self._expected_current_piece = None
        else:
            baseline = self._confirmed_next_slots
            shift = _estimate_next_shift(baseline, next_slots)
            if shift is None:
                # 基準の1枠だけと矛盾しているなら、その枠を再確認する。
                # 同じ枠・同じ値の矛盾が2tick続いたら、基準側の誤読とみなして
                # 置き換え、移動量を推定し直す(_find_single_slot_conflict参照)。
                # 1tickだけの遷移途中画像は2tick続かないので置き換えに至らない。
                conflict = _find_single_slot_conflict(baseline, next_slots)
                if conflict is not None and self._next_slot_conflict == conflict[1:]:
                    _shift, slot_index, value = conflict
                    corrected = list(baseline)
                    corrected[slot_index] = value
                    if self._debug_log_file is not None:
                        self._debug_log_file.write(
                            f"----- NEXT基準の{slot_index}枠目を再確認して補正: "
                            f"{baseline} -> {tuple(corrected)} -----\n"
                        )
                        self._debug_log_file.flush()
                    baseline = tuple(corrected)
                    self._confirmed_next_slots = baseline
                    self._next_slot_conflict = None
                    shift = _estimate_next_shift(baseline, next_slots)
                else:
                    self._next_slot_conflict = conflict[1:] if conflict is not None else None
            else:
                self._next_slot_conflict = None
            next_shift = shift
            if shift is None and self._next_baseline_provisional:
                # 暫定の基準と整合しない。1回の観測だけの基準を信じて
                # 待ち続けるより、今回の観測で作り直す方が早く正しい基準に
                # 収束する(残課題2-2)。基準は暫定のまま、次の観測で改めて
                # 整合を確認する。
                if self._debug_log_file is not None:
                    self._debug_log_file.write(
                        f"----- 暫定のNEXT基準を差し替え: {baseline} -> {next_slots} -----\n"
                    )
                    self._debug_log_file.flush()
                self._confirmed_next_slots = next_slots
                self._expected_current_piece = None
            elif shift is None:
                # 移動量を一意に決められない。推測で進行を決めず、確定値も
                # 変えずに次の観測を待つ(_estimate_next_shift参照)。
                self._next_shift_undecided_ticks += 1
                if (
                    self._next_shift_undecided_ticks >= self.NEXT_REANCHOR_TICKS
                    and sum(1 for v in next_slots if v is not None) >= 4
                ):
                    # 判断できない状態が続いている。確定値が実際の並びから
                    # 大きくずれている(_MAX_NEXT_SHIFTを超えて進んだ、
                    # 対局が変わった等)可能性が高く、このままでは永久に
                    # 復帰できないため、今読めている並びを新しい基準にする。
                    # 何手進んだかは分からないので、操作ミノは履歴から
                    # 決めず画像の判定に委ねる。
                    if self._debug_log_file is not None:
                        self._debug_log_file.write(
                            f"----- NEXT履歴を再アンカー: {self._confirmed_next_slots} -> "
                            f"{next_slots} ({self._next_shift_undecided_ticks}tick判断不能) -----\n"
                        )
                        self._debug_log_file.flush()
                    # 【2026-09-11・残課題2-2】取り直した並びも暫定とし、
                    # 次の観測と整合してから確定する(起動時と同じ)。
                    self._confirmed_next_slots = next_slots
                    self._next_baseline_provisional = True
                    self._expected_current_piece = None
                    self._next_shift_undecided_ticks = 0
            elif shift >= 1:
                self._next_shift_undecided_ticks = 0
                # 別の観測が移動量1〜2で整合した。基準は確定とみなす。
                self._next_baseline_provisional = False
                # 認識できている枠のうち少なくとも1つが前回の確定値と
                # 異なっていた。ネクストキューは新規スポーンでしか動かない
                # ため、これは「1つ手が進んで、5枠の窓全体が1つ繰り上がった」
                # ことを意味する。末尾に入る新しい5枠目は、このtickで
                # 認識できていればその値、できなければ保留(None)のまま
                # 次tick以降で埋まるのを待つ。
                # NEXTの窓から出ていったbaseline[0]が、新しい操作ミノになる。
                # 通常の固定でも、HOLDが空の状態でのホールドでも、NEXTの
                # 先頭が操作ミノになる点は同じ(_expected_current_piece参照)。
                # 2つ以上進んでいた場合は手を取りこぼしているため、履歴から
                # 操作ミノを決めず画像の判定に委ねる。
                self._expected_current_piece = baseline[0] if shift == 1 else None
                self._confirmed_next_slots = tuple(baseline[shift:]) + tuple(
                    next_slots[len(next_slots) - shift :]
                )
                next_advanced = True
            else:
                self._next_shift_undecided_ticks = 0
                # 別の観測が移動量0で整合した。基準は確定とみなす。
                self._next_baseline_provisional = False
                # shift == 0。まだ手は進んでいない。ただし、これまで保留
                # (None)だった枠がこのtickで初めて認識できていれば、
                # その分だけ確定値として埋める(退行はせず前進のみ)。
                merged = list(baseline)
                for i, raw_value in enumerate(next_slots):
                    if merged[i] is None and raw_value is not None:
                        merged[i] = raw_value
                self._confirmed_next_slots = tuple(merged)
        # board_keyの2tick確認済み基準値は、significant_changeのトリガーとしては
        # もう使わない(上記next_advancedに一本化)が、_is_plausible_board_
        # transition(下記のboard_data_trustworthy判定)が「前回信頼できた盤面」
        # との比較に使い続けるため、この基準値の更新自体は引き続き必要。
        # 妥当性検証(下記)用に、このtickでの更新前の基準値を保持しておく。
        previous_confirmed_board_key = self._last_board_key

        # 「前回確定したboard_key(基準値)」との差分が2tick連続で同じ値に
        # なった時だけ、基準値そのものを更新して変化を確定する。基準値を
        # 毎tick無条件で最新値に更新してしまうと、1回目の差分がそのまま
        # 次tickの基準値になり、2回目のtickで「基準値と一致する」ため
        # 差分なしと判定されてしまい、デバウンスが機能しなくなる
        # (基準値の更新は確定時にのみ行う必要がある)。
        board_key_diff_cells: list[tuple[int, int, str | None, str | None]] = []
        if self._last_board_key is None:
            self._last_board_key = recognition.board_key
            board_key_changed = False
            self._pending_board_key = None
        else:
            previous_board_key_for_diff = self._last_board_key
            raw_board_key_changed = recognition.board_key != self._last_board_key
            if raw_board_key_changed and self._pending_board_key == recognition.board_key:
                board_key_changed = True
                # 「光エフェクト以外にも原因があるのでは」という指摘の調査用:
                # board_key_changedが具体的にどのセルの変化で発火したかが
                # 分からないと、原因が(1)ハードドロップの列エフェクトによる
                # 色誤読なのか、(2)操作中ピースがまだ落下中で境界判定
                # (_settled_top_row)がtickごとに微妙にブレているだけなのか、
                # を区別できない。差分セルをすべて記録する。
                for r, (old_row, new_row) in enumerate(zip(previous_board_key_for_diff, recognition.board_key)):
                    for c, (old_cell, new_cell) in enumerate(zip(old_row, new_row)):
                        if old_cell != new_cell:
                            board_key_diff_cells.append((r, c, old_cell, new_cell))
                self._last_board_key = recognition.board_key
                self._pending_board_key = None
            else:
                board_key_changed = False
                self._pending_board_key = recognition.board_key if raw_board_key_changed else None
        # board_key_changed自体はもうsignificant_changeのトリガーには使わないが、
        # デバッグログには引き続き記録する(board_data_trustworthy判定の
        # 調査に役立つため)。
        significant_change = next_advanced
        # 【2026-09-11・実機ログで判明】交換を内部に反映するだけでは、Cold
        # Clear 2は交換前の局面を考え続ける。その結果は手番照合で棄却され
        # 続け(交換19回に対し棄却57件=毎回きっかり3件)、3tick連続で食い
        # 違って初めて思考をやり直していた。交換を反映した時点で現在の
        # 局面を渡し直す。表示中の配置は仕様どおり触らない
        # (_committed_placementはnext_advancedでしか解除しない)。
        forced_by_hold_swap = self._apply_hold_swap_if_any(recognition, next_shift)
        if forced_by_hold_swap:
            significant_change = True
        # 操作ミノが分からず局面を渡せなかった場合は、渡せるようになるまで
        # 毎tick試す(_needs_start_thinking参照)。
        if self._needs_start_thinking:
            significant_change = True
        # 【仕様上の明示的な例外】相手の攻撃でおじゃまがせり上がった場合は、
        # 同じ手番の途中でも提案を計算し直してよい(CLAUDE.md「最善手は、
        # 相手からの妨害で段がせりあがる場合を除き、表示を切り替えない」)。
        # せり上がると着地位置が丸ごとずれるため、これを実装しないと攻撃を
        # 受けた直後の提案が実態と合わなくなる。
        garbage_rise = 0
        if previous_confirmed_board_key is not None:
            garbage_rise = _detect_garbage_rise(previous_confirmed_board_key, recognition.board_key)
        if garbage_rise:
            significant_change = True
            # この手番について提示済みの配置は、せり上がりで無効になった。
            # 新しい配置を提示できるよう確定状態を解除する。
            self._committed_placement = None
            if self._debug_log_file is not None:
                self._debug_log_file.write(
                    f"----- おじゃまのせり上がりを検出: {garbage_rise}行 -----\n"
                )
                self._debug_log_file.flush()
        # 操作ミノの種類はNEXT履歴を優先するが、画像と長く食い違うようなら
        # 履歴側が取りこぼしている可能性が高いので画面を正として同期し直す。
        forced_by_resync = False
        if not next_advanced and self._resync_current_piece_if_desynced(recognition):
            significant_change = True
            forced_by_resync = True

        # 【2026-09-07・ログ出力順序のバグを修正】以前はこの直後で
        # significant_changeをログに記録してから、下記のタイムアウト保険で
        # significant_changeをTrueに上書きしていた。そのため、タイムアウト
        # 保険が実際にsignificant_changeを発火させたケースが一切ログに
        # 記録されず(記録時点ではまだFalseのまま)、「なぜこのタイミングで
        # 新しい思考が始まったのか」を実機ログから追えなくなっていた
        # (振動の原因調査中に発見: next_advancedの記録がないのに新しい
        # start_thinkingが呼ばれているように見える箇所があった)。
        # ログに記録する前に、タイムアウト保険の判定を先に済ませる。
        #
        # 「手が進んだ」の検知をnext_advanced1本に統一しても、実機では
        # ネクスト欄5枠すべてが長時間認識できなくなる、といった未知の
        # 状況が起こりうる。原因の特定・対症療法を重ねる代わりに、「一定時間
        # 更新がなければ強制的に最新の認識結果で思考をやり直す」という
        # 無条件の保険を最後の砦として設ける。
        now_significant_change = time.monotonic()
        forced_by_timeout = False
        if significant_change:
            self._last_significant_change_time = now_significant_change
        elif now_significant_change - self._last_significant_change_time >= self.MAX_SIGNIFICANT_CHANGE_SILENCE_SEC:
            significant_change = True
            forced_by_timeout = True
            self._last_significant_change_time = now_significant_change

        if significant_change and self._debug_log_file is not None:
            diff_text = ""
            if board_key_diff_cells:
                diff_text = " diff=" + ",".join(
                    f"({r},{c}):{old}->{new}" for r, c, old, new in board_key_diff_cells
                )
            if garbage_rise:
                reason = f"おじゃまのせり上がり({garbage_rise}行)"
            elif forced_by_timeout:
                reason = "MAX_SIGNIFICANT_CHANGE_SILENCE_SEC(タイムアウト保険)"
            elif forced_by_hold_swap:
                reason = "HOLD交換"
            elif forced_by_resync:
                # 再同期による発火をnext_advancedと記録すると、ログ上
                # 「NEXT列が変わっていないのにnext_advancedが発火した」ように
                # 見えて原因の切り分けを誤らせる(実際に誤らせた)。
                reason = "操作ミノの再同期"
            else:
                reason = "next_advanced"
            self._debug_log_file.write(
                f"\n----- significant_change発火: {reason} "
                f"(current={recognition.current_piece} confirmed_next_slots={self._confirmed_next_slots}"
                f" settled_top_row={recognition.settled_top_row}){diff_text} -----\n"
            )
            self._debug_log_file.flush()

        # T-Spin等の派手な光エフェクトの直後、まだ残っているはずの設置済み
        # ブロックが一時的に「空」と誤読され、その誤った盤面のままCold
        # Clear 2に渡されて「既存ブロックと干渉するように見える提案」
        # 「振動」につながっていたことが実機動画で確認された(詳細は
        # _is_plausible_board_transitionのdocstring参照)。この場合、
        # start_thinkingへの通知自体を今回のtickでは見送り、次tick以降
        # (エフェクトが収まり盤面認識が正常に戻った後)に自然に再試行させる
        # ことで、汚れたデータをCold Clear 2の判断材料にしないようにする。
        board_data_trustworthy = _is_plausible_board_transition(
            previous_confirmed_board_key, recognition.board_key, recognition.board.width, garbage_rise
        )
        # 【2026-09-11・録画とログで判明】ライン消去では、行が消えるのと同じ
        # フレームで次のミノがスポーンする。一方、着地済みマスの「ブロック→空」
        # は2tick連続の観測を要求するため、スポーン検知のtickではAIへ渡す
        # 盤面に消えたはずの行がまだ残っている。その盤面で要求すると、
        # 消えた行の上に提案が出て「空中に提示」されるか、行が消えた後の
        # 盤面で物理的に成立せず黙って捨てられ「何も提示されない」まま
        # タイムアウト保険を待つことになった。確定待ちのマスがある間は
        # 盤面を信用せず、確定した次のtickで要求する(上記の再試行で
        # 拾われる。最大でも1tickの遅れ)。
        # 対象は「空になる」保留だけ。置いた直後のミノは光って種類不明
        # (UNKNOWN)で読まれ、次のtickで本来の色に変わるため、色の変化まで
        # 対象にするとほぼ毎手番で保留が発生し、盤面信頼のタイムアウト
        # (0.3秒)まで要求が止まった(3回目の実機ログ: 保留61回、タイムアウト
        # 67回)。占有が変わらない色の変化はAIの判断に影響しない。
        board_settling = any(
            cell is not None and cell[0] is None for row in recognition.pending_grid for cell in row
        )
        if board_settling and board_data_trustworthy:
            board_data_trustworthy = False
            if significant_change and self._debug_log_file is not None:
                pending_cells = [
                    (r, c, cell[0])
                    for r, row in enumerate(recognition.pending_grid)
                    for c, cell in enumerate(row)
                    if cell is not None
                ]
                self._debug_log_file.write(
                    f"----- 盤面の確定待ちのため要求を保留: {pending_cells[:8]} -----\n"
                )
                self._debug_log_file.flush()
        # 実機動画で確認された致命的な不具合の回帰対策: 激しい連続コンボ(REN)
        # のように、断続的な光エフェクトや盤面の急激な変化が長く続く場面では、
        # board_keyが2tick連続で安定する瞬間がなかなか訪れず、上の
        # board_data_trustworthyの基準値(previous_confirmed_board_key)が
        # 何十秒も更新されないまま「あり得ない変化」の判定が延々と続き、
        # start_thinkingが一切呼ばれなくなる(=提案が更新されないまま
        # トップアウトする)事態が確認された。BOARD_TRUST_TIMEOUT_SEC以上
        # 信頼できる読み取りが一度も得られていない場合は、汚れている
        # 可能性を承知の上でこのtickの盤面を受け入れ、基準値も直ちに
        # 現在値へ再同期する(再同期しないと次tickもまた古い基準値と
        # 比較されて弾かれ続けてしまう)。「間違った提案が時々出る」方が
        # 「39秒間まったく提案が出ない」よりはるかにましという判断。
        now_board_trust = time.monotonic()
        if not board_data_trustworthy and (
            now_board_trust - self._last_board_trustworthy_time >= self.BOARD_TRUST_TIMEOUT_SEC
        ):
            # この保険が実際にいつ・どれだけの頻度で発動しているかが
            # わからないと、「提案が来ない」報告の原因がこの保険自体の
            # 発動間隔(BOARD_TRUST_TIMEOUT_SEC)なのか、それとも全く別の
            # 原因なのかを次回切り分けられない。デバッグログが有効なら
            # 発動の瞬間を必ず記録する。
            if self._debug_log_file is not None:
                blocked_sec = now_board_trust - self._last_board_trustworthy_time
                self._debug_log_file.write(
                    f"\n===== board_data_trustworthyタイムアウト発動 "
                    f"(信頼できる読み取りが{blocked_sec:.2f}秒得られなかったため強制受理) =====\n"
                )
                self._debug_log_file.flush()
            board_data_trustworthy = True
            self._last_board_key = recognition.board_key
            self._pending_board_key = None
            if board_settling:
                # 【2026-09-12・実機ログ】ライン消去・REN等のエフェクトが続いて
                # 確定待ちが途切れないまま強制受理すると、消えた行の古いマスと
                # 下へ詰まった新しいマスが二重に残った盤面でAIに要求し、その
                # 幻のマスの上に提案が出て空中に浮いた。強制受理のときは
                # 「最新の読みで空」のマス(空になる確定待ち)を空として扱う。
                cleaned = recognition.board.clone()
                for r, row in enumerate(recognition.pending_grid):
                    for c, cell in enumerate(row):
                        if cell is not None and cell[0] is None:
                            cleaned.grid[r][c] = None
                recognition = dataclass_replace(recognition, board=cleaned)
        if board_data_trustworthy:
            self._last_board_trustworthy_time = now_board_trust

        if significant_change and not board_data_trustworthy:
            # 【2026-09-11・実機ログで判明】このtickの盤面が信用できず要求を
            # 見送る。しかしnext_advancedの発火はこのtickで消費済み
            # (_confirmed_next_slotsは既に進んでいる)なので、何もしないと
            # この手番の要求は二度と起きず、1.5秒のタイムアウト保険まで
            # 提案が出なかった(実測: 約110秒で保険が41回発火)。盤面を
            # 信用できるtickで改めて要求できるよう、毎tick再試行させる。
            self._needs_start_thinking = True
            # 【2026-09-11・3回目の実機ログで判明】新しいミノについて提示
            # 済みの配置(_committed_placement)の解除は下の要求ブロックの
            # 中で行っているため、要求を見送るとそのまま残る。再試行の
            # tickではnext_advancedは既に消費されていて解除されず、新しい
            # ミノに対するAIの結果が「この手番は提示済み」としてすべて
            # 黙って捨てられ、次のミノまで何も表示されなかった(132手番中
            # 提示28回。「3手目が提示されない」)。見送る場合もここで解除する。
            # 空のHOLDへの格納(HOLDが変わってNEXTが進む)は固定ではないので
            # 解除しない(下の要求ブロックと同じ判定)。
            hold_changed_now = (
                recognition.hold_known
                and self._prev_hold_piece != "UNKNOWN"
                and recognition.hold_piece != self._prev_hold_piece
            )
            if next_advanced and not hold_changed_now:
                self._committed_placement = None
                self._cc_pending_lock = True
        if significant_change and board_data_trustworthy:
            # 新しいミノがスポーンした時だけCold Clear 2に新しい局面を渡し、
            # バックグラウンドでの継続思考を開始させる。同じミノを操作している
            # 間（significant_change=Falseの通常tick）はstart_thinkingを
            # 呼ばない。ここで毎回startし直すと、Cold Clear 2の探索が
            # 都度ゼロからやり直しになり、パーフェクトクリアのような
            # 複数手先の計画を要する手を見つける前に思考が打ち切られて
            # しまう（実機で確認された問題）。
            # 【2026-09-07・全面設計変更に伴い簡略化】以前はホールド操作
            # そのもの(piece_changed等)もsignificant_changeの引き金に
            # なりえたため、「ネクストキューが進んでいないのにcurrentが
            # 直前のholdと一致する」ケースを“確実なホールドスワップ”として
            # 検知し、HOLD欄の画像判定(ノイズに弱い)を信じずcurrentから
            # 導出する、という特別扱いが必要だった。しかし今はsignificant_
            # change自体がnext_advanced(ネクスト/ネクネクが進んだ)の時にしか
            # 発火しないため、このブロックに到達する時点で「ネクストキューが
            # 進んでいない」ケースはそもそも存在しない(ホールド操作単独では
            # ここに到達しない)。よって、かつての特別扱いは常に不成立の
            # 死んだ分岐になっていたため撤去し、実機動画で確認済みの通り
            # (通常の新規スポーンではHOLD欄は静止画像で画像判定自体が
            # 正しく機能する)、常にHOLD欄の画像判定をそのまま信じる。
            old_hold_piece = self._prev_hold_piece
            # 固定検出用に、更新前の「直前の手番の操作ミノ」を控えておく。
            previous_piece = self._last_current_piece
            # HOLD欄が読めなかった場合、そのNoneを「空欄」と解釈してはいけない
            # (有識者資料[035])。直前に確定していた値を維持し、変化の有無は
            # 判定不能として扱う。
            effective_hold_piece = (
                recognition.hold_piece if recognition.hold_known else old_hold_piece
            )
            # 【操作中ミノの種類は画像ではなくNEXT履歴から決める】
            # next_advancedが発火するtickでは、直前に固定したミノがまだ
            # 着地済み領域に取り込まれておらず、_infer_current_pieceが
            # それを操作中ミノとして返してしまう。実機ログでは
            # next_advanced 49回中15回(31%)でこの誤りが起き、そのうち
            # 87%が「直前の手番のミノ」だった。誤った局面でCold Clear 2に
            # 質問すると、以降の結果が手番照合で全て棄却され、タイムアウト
            # 保険が働くまで提案が出ない(「提案が遅い」の主因)。
            # NEXTの窓から出ていったミノが新しい操作ミノになるという
            # ゲームのルールは画像のブレに影響されないため、そちらを使う
            # (プロジェクトの構想「以降の種類はNEXTとHOLDの履歴を利用する」)。
            self._last_current_piece = self._expected_current_piece or recognition.current_piece
            # HOLD交換で発火した場合、_apply_hold_swap_if_anyが_prev_hold_pieceを
            # 既に更新しているので差分では検知できない。交換した事実から
            # 「この手番でHOLDは使用済み」と判定する。
            just_held = forced_by_hold_swap or (
                old_hold_piece != "UNKNOWN" and effective_hold_piece != old_hold_piece
            )
            if recognition.hold_known:
                self._prev_hold_piece = effective_hold_piece
            # このミノについて実際にdisallow_holdを適用したかどうかを覚えておく。
            # ただし、おじゃまのせり上がりで再計算する場合は新しいミノが
            # 出現したわけではないので、この手番でHOLDを使用済みかどうかの
            # 判定を引き継ぐ(ここで作り直すとFalseに戻り、既に使った
            # HOLDを前提とする提案を採用しうる)。
            if not garbage_rise:
                self._disallow_hold_active = just_held
            # HOLDの状態が確定できていない間は、変化の有無が分からないので
            # 固定と断定しない(誤って提案を消さない方へ倒す)。
            if recognition.hold_known and _detect_lock(
                next_advanced, just_held, previous_piece is not None
            ):
                # 前のミノが実際に置かれた。その提案はもう役目を終えている
                # ので消す(実際のemitは、このtickで新しい提案が得られな
                # かった場合に後段でまとめて行う。ここで即座にemitすると
                # 「消える→すぐ新しい提案」の2段階更新になり、Windows側の
                # 画面合成が追いつかずちらつくため)。
                stale_suggestion_detected = True
            # 新しいミノについてだけ、確定していない状態に戻す。
            #
            # 【タイムアウト保険では解除しない】
            # significant_changeはnext_advanced以外に、一定時間更新が無い
            # 場合の保険(MAX_SIGNIFICANT_CHANGE_SILENCE_SEC=1.5秒)でも発火する。
            # ここで一緒に確定を解除していたため、1手に1.5秒以上かけると
            # 同じ手番の途中で提案が別の配置に差し替わっていた。実機ログでは
            # タイムアウト保険が1手あたり0.7回(90回/129手)発火しており、
            # 「少なくとも1回は提示が変わってどこに置けばよいか分からなくなる」
            # という報告に一致する。初心者が1手に1.5秒以上かけるのは普通で
            # あり、仕様「提示した配置は、実際にミノを置くまで変更しない」に
            # 反する。保険の目的はAIへ現在の局面を渡し直すことなので、
            # 表示中の配置まで作り直す必要はない。
            #
            # 【空のHOLDへの格納でも解除しない(2026-09-11・5回目の実機ログ)】
            # HOLDが空の状態でホールドするとNEXTが1つ進むが、手番は
            # 変わっていない(提示済みの「ホールドしてZを置く」を利用者が
            # 実行している途中)。ここで解除すると、ホールド直後に届いた
            # 別の配置に差し替わり、初手で提示が振動した。固定(HOLDが
            # 変わらずにNEXTが進んだ)のときだけ解除する。
            # 【探索木の引き継ぎ(play)の判断材料】このtickで固定があったか。
            # 要求を見送ったtickの固定は_cc_pending_lockで持ち越されている。
            # 提示済み配置(_committed_placement)は下で解除するので、その前に控える。
            locked_now = (next_advanced and not just_held) or self._cc_pending_lock
            self._cc_pending_lock = False
            self._update_opener(recognition, locked_now=locked_now, garbage_rise=garbage_rise)
            committed_before_lock = self._committed_placement
            committed_tbp_before_lock = self._committed_placement_tbp
            if next_advanced and not just_held:
                self._committed_placement = None
                self._committed_placement_tbp = None
            # これからCold Clear 2へ質問する局面の識別情報を覚えておく。
            # 返ってきた結果を表示する前に現在の認識と照合し、別の手番の
            # 結果を表示しないようにする(_is_suggestion_for_current_turn参照)。
            self._thinking_turn_key = _turn_key(
                self._last_current_piece, effective_hold_piece, recognition.next_queue
            )
            if self._last_current_piece is None:
                # NEXT履歴からも画像からも操作ミノが分からない。何を置くのか
                # 決まっていない局面をAIへ渡しても意味がないので要求しない。
                # ただし次のnext_advancedやタイムアウト保険(1.5秒)を待つと、
                # 支援モードに入った直後に何も出ない時間が長くなる。
                # 要求できるようになったら即座に出せるよう、毎tick試させる。
                self._thinking_turn_key = None
                self._needs_start_thinking = True
                self.msleep(self.IDLE_SLEEP_MS)
                return
            self._needs_start_thinking = False
            if not self._try_restart_cold_clear():
                # AIが壊れていて、まだ作り直せる時刻になっていない。
                # 認識と表示は続けたいので、ここでは要求を見送るだけにする。
                self.msleep(self.IDLE_SLEEP_MS)
                return
            try:
                self._request_thinking(
                    recognition,
                    effective_hold_piece,
                    just_held=just_held,
                    locked_now=locked_now,
                    committed=committed_before_lock,
                    committed_tbp=committed_tbp_before_lock,
                    garbage_rise=garbage_rise,
                    forced_by_resync=forced_by_resync,
                )
            except COLD_CLEAR_ERRORS as exc:
                self._handle_cold_clear_failure(exc)
                self.msleep(self.IDLE_SLEEP_MS)
                return

        # 新規スポーン直後は即座に、それ以外（同じミノを操作中）は
        # POLL_INTERVAL_SECより短い間隔では問い合わせない。段階的思考の
        # 導入で提案がどんどん更新されるようになった一方、更新頻度が
        # 高すぎるとオーバーレイの再描画がWindows側の画面合成に追いつかず
        # 「前後2つの提案が一瞬両方見える」不具合が実機で確認されたため。
        now = time.monotonic()
        should_poll = significant_change or (now - self._last_poll_time) >= self.POLL_INTERVAL_SEC
        if not should_poll:
            # pollをスキップする場合でも、このtickで古い提案が無効と判定
            # されていれば、それだけは反映してから戻る（次にpollされる
            # までの間、実行済みの古い提案を表示し続けてしまうのを防ぐ）。
            if stale_suggestion_detected:
                self._last_valid_draw_data = None
                self._last_draw_data_set_time = time.monotonic()
                self.draw_data_ready.emit(None)
            self.msleep(self.IDLE_SLEEP_MS)
            return

        if self._cold_clear_broken:
            # 作り直しは次のsignificant_changeで試みる。壊れたまま問い合わせると
            # 1回あたり応答待ちの時間(既定5秒)を丸ごと浪費し、認識も止まる。
            self.msleep(self.IDLE_SLEEP_MS)
            return
        if self._thinking_turn_key is None:
            # まだ一度も局面を渡していない。Cold Clear 2は考える対象が無い
            # ので、問い合わせても応答が返らず応答待ちのタイムアウト(既定5秒)を
            # 丸ごと浪費する。実機で、支援モードに入った直後の操作ミノが
            # まだ読めない状況でこれが起き、「開始してから5秒程度何も
            # 表示されない」という症状になっていた
            # (ログ: 起動直後に「Cold Clear 2から5.0秒間応答がありませんでした」)。
            self.msleep(self.IDLE_SLEEP_MS)
            return
        self._last_poll_time = now
        poll_started = time.perf_counter()
        try:
            best = self.cold_clear.poll_suggestion(self._last_current_piece)
        except COLD_CLEAR_ERRORS as exc:
            self._handle_cold_clear_failure(exc)
            self.msleep(self.IDLE_SLEEP_MS)
            return
        if significant_change:
            # start_thinkingを送った直後はまだ何も計算できておらずNoneが
            # 返ることがある。その場合、前のミノに対する古い提案を表示し
            # 続けるより一瞬だけ待つ方がましなので、ごく短い間隔で数回だけ
            # リトライする（実測では0.1秒未満でも初期解が得られている）。
            retry = 0
            while best is None and retry < 6:
                self.msleep(5)
                try:
                    best = self.cold_clear.poll_suggestion(self._last_current_piece)
                except COLD_CLEAR_ERRORS as exc:
                    self._handle_cold_clear_failure(exc)
                    self.msleep(self.IDLE_SLEEP_MS)
                    return
                retry += 1

        # 【要求時と同じ基準でHOLDを見る】
        # 要求時はHOLDが読めなければ直前の確定値を使う(effective_hold_piece)。
        # 照合側だけが生の値を使うと、HOLDが一瞬読めなくなっただけで必ず
        # 食い違い、その間のAI結果がすべて棄却されて提示が遅れる。
        effective_hold_for_key = (
            recognition.hold_piece
            if recognition.hold_known
            else (self._prev_hold_piece if self._prev_hold_piece != "UNKNOWN" else None)
        )
        current_turn_key = _turn_key(
            self._last_current_piece, effective_hold_for_key, recognition.next_queue
        )
        # 探索木を引き継いでいる間は、新しく読めたNEXTをCold Clear 2へ足す。
        if self._cc_continuation is not None and recognition.hold_known:
            try:
                self._sync_cc_queue(effective_hold_for_key)
            except COLD_CLEAR_ERRORS as exc:
                self._handle_cold_clear_failure(exc)
                self.msleep(self.IDLE_SLEEP_MS)
                return
        if self._thinking_turn_key == current_turn_key:
            self._turn_key_mismatch_ticks = 0
        self._record_latency("AIへの問い合わせ", time.perf_counter() - poll_started)

        if best is not None and self._thinking_turn_key != current_turn_key:
            # Cold Clear 2は「start_thinkingで渡した局面」について考え続けて
            # おり、その結果はいつ返ってきても当時の局面に対する答えである。
            # 実機ログで、操作中ミノがJ→Lに変わった後にJ向けの提案が届いて
            # そのまま表示され、HOLDにもNEXTにも存在しないJの配置が提示
            # される現象を確認した(17:48:10、current=L hold=T
            # next=['O','S','Z','I','Z'] に対し best: piece=J)。要求と結果を
            # 手番で結び付け、別の手番の結果は表示しない。
            if self._debug_log_file is not None:
                self._debug_log_file.write(
                    f"----- 古い手番のAI結果を破棄: 提案={best.piece} "
                    f"要求時={self._thinking_turn_key} 現在={current_turn_key} -----\n"
                )
                self._debug_log_file.flush()
            best = None
            # 【タイムアウト保険を待たずに立て直す】この不一致が続く限り、
            # Cold Clear 2は古い局面を考え続けるため何を返しても棄却される。
            # 以前はMAX_SIGNIFICANT_CHANGE_SILENCE_SECのタイムアウト保険が
            # 発火するまで提案が出ず、しかも保険が発火するたびに
            # _committed_placementがリセットされて提案が入れ替わり、
            # 「提案が遅い」「振動する」の直接の原因になっていた。ここで
            # 即座に現在の局面で思考をやり直す。既に提示済みの配置
            # (_committed_placement)は仕様どおり維持したまま行うため、
            # 立て直し自体が振動を生むことはない。
            # ただし1tickだけの食い違い(HOLD欄の認識ノイズ等)で毎回
            # 思考を開始し直すと、Cold Clear 2の探索が都度ゼロからやり直しに
            # なり、複数手先の計画を要する手を見つけられなくなる。
            # 連続して食い違い続けた場合だけ立て直す。
            self._turn_key_mismatch_ticks += 1
            if (
                board_data_trustworthy
                and self._turn_key_mismatch_ticks >= self.TURN_KEY_MISMATCH_RETHINK_TICKS
            ):
                self._turn_key_mismatch_ticks = 0
                self._thinking_turn_key = current_turn_key
                # 局面を渡し直すので、Cold Clear 2の内部局面との対応は失われる。
                self._cc_continuation = None
                try:
                    self.cold_clear.start_thinking(
                        recognition.board,
                        self._last_current_piece,
                        recognition.hold_piece,
                        list(recognition.next_queue),
                        disallow_hold=self._disallow_hold_active,
                    )
                except COLD_CLEAR_ERRORS as exc:
                    self._handle_cold_clear_failure(exc)
                    self.msleep(self.IDLE_SLEEP_MS)
                    return

        self._check_opener_progress(recognition)
        self._maybe_start_opener(recognition)
        if self._opener is not None and self._opener.current_step() is not None:
            # 開幕テンプレ進行中はAIの提案の代わりにテンプレの手を出す。
            # 以降の検査(実行可能なミノか、物理的に成立するか)は同じように通す。
            best = self._opener.as_move()

        if best is not None and best.piece not in _available_pieces(
            self._last_current_piece, recognition.hold_piece, recognition.next_queue
        ):
            # 手番の照合をすり抜けた場合の保険。提案されたミノが操作中でも
            # HOLDでもないなら、その提案は現在の局面では実行できない。
            if self._debug_log_file is not None:
                self._debug_log_file.write(
                    f"----- 実行不可能なミノの提案を破棄: 提案={best.piece} "
                    f"current={self._last_current_piece} hold={recognition.hold_piece} -----\n"
                )
                self._debug_log_file.flush()
            best = None

        if best is not None and not recognition.board.is_placement_physically_valid(best.landing_cells):
            # 【2026-09-11】黙って捨てると「提案が出ない」の原因を追えない
            # (実機で、ライン消去前の盤面で得た提案が消去後の盤面で成立せず、
            # 痕跡なく捨てられ続けていた)。捨てた事実をログに残す。
            if self._debug_log_file is not None and self._last_logged_invalid_move_key != (
                best.piece,
                tuple(best.landing_cells),
            ):
                self._last_logged_invalid_move_key = (best.piece, tuple(best.landing_cells))
                self._debug_log_file.write(
                    f"----- 物理的に成立しない提案を破棄: 提案={best.piece} "
                    f"cells={list(best.landing_cells)} -----\n"
                )
                self._debug_log_file.flush()
            # Cold Clear 2からの提案が、認識した盤面上では「既に埋まって
            # いるマスに重なる」「支えがなく宙に浮いている」等、物理的に
            # ありえない配置になっている瞬間が実機動画で確認された（原因は
            # 盤面認識のズレか座標変換の誤りか特定できていないが、原因を
            # 問わず、少なくともこの種の提案はユーザーに見せるべきではない）。
            # このtickでは新しい提案が得られなかったものとして扱う。
            best = None

        if best is not None:
            best = self._stabilize_suggestion(best)

        if best is not None:
            draw_data = OverlayDrawData(
                piece=best.piece,
                landing_cells=best.landing_cells,
                use_hold=best.use_hold,
                plan_steps=_plan_steps_on_screen(recognition.board, best)[: self._plan_depth - 1],
                label=(
                    f"開幕テンプレ\n{self._opener.template.name_ja}\n{self._opener.form.section.split(' > ')[-1]}"
                    if self._opener is not None
                    else None
                ),
            )
            if draw_data != self._last_valid_draw_data:
                self._last_valid_draw_data = draw_data
                self._last_draw_data_set_time = time.monotonic()
                self.draw_data_ready.emit(draw_data)
                if self._debug_log_file is not None:
                    self._save_frame_history(recognition, best)

            if self._debug_log_file is not None:
                move_key = (best.piece, best.use_hold, tuple(best.landing_cells))
                if move_key != self._last_logged_move_key:
                    self._last_logged_move_key = move_key
                    self._debug_log_file.write(format_board_debug(recognition, best) + "\n\n")
                    self._debug_log_file.flush()
        elif stale_suggestion_detected:
            # このtickで新しい提案が得られなかった場合に限り、ここで
            # 初めて古い無効な提案をクリアする（emitは1tickにつき最大1回に
            # 抑える。新しい提案が得られた場合はそちらが優先され、この
            # 分岐には入らない）。
            self._last_valid_draw_data = None
            self._last_draw_data_set_time = time.monotonic()
            self.draw_data_ready.emit(None)

        self._record_latency("tick全体", time.perf_counter() - tick_started)
        self._report_latency_if_ready()
        if not significant_change:
            self.msleep(self.IDLE_SLEEP_MS)

    def _record_video_frame(self, capture: ScreenCapture) -> None:
        """画面録画(暫定機能)。キャリブレーション済みの範囲(盤面+HOLD+NEXT欄)を
        VIDEO_RECORD_FPSで間引きながらDEBUG_VIDEO_PATHへmp4として書き出す。

        不具合報告のたびに別の画面録画ソフトで撮り直す手間をなくすための
        暫定対応。実画面をキャプチャするため、オーバーレイの提案(色ドット)
        も外部の画面録画ソフトで撮った場合と同様に映り込む。
        """
        now = time.monotonic()
        if now - self._last_video_frame_time < 1.0 / VIDEO_RECORD_FPS:
            return
        self._last_video_frame_time = now
        try:
            import cv2

            region_min_x, region_min_y, _max_x, _max_y = _region_bounds(self.calibration)
            frame = _grab_calibrated_region(self.calibration, capture)
            height, width = frame.shape[0], frame.shape[1]
            if self._video_writer is None:
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                self._video_writer = cv2.VideoWriter(
                    str(DEBUG_VIDEO_PATH), fourcc, VIDEO_RECORD_FPS, (width, height)
                )
            bgr_frame = frame[:, :, ::-1].copy()
            # オーバーレイ自体は自己汚染防止のためこのフレームに映らないので、
            # 現在表示中の提案(色ドット)をこの録画専用フレームにだけ合成する。
            if self._last_valid_draw_data is not None:
                _draw_suggestion_on_bgr_frame(
                    bgr_frame, self.calibration, region_min_x, region_min_y, self._last_valid_draw_data
                )
            # 【2026-09-07・暫定のデバッグ機能】next_debug_ready参照。
            if self._last_next_debug_slots is not None:
                _draw_next_debug_dots_on_bgr_frame(
                    bgr_frame, self.calibration, region_min_x, region_min_y, self._last_next_debug_slots
                )
            # debug_log.txt(datetime.now().isoformat())やdebug_frames_history
            # のinfo.txtと同じ形式の実時刻をフレームに焼き込む。以前は
            # 「支援モード開始」時刻からの経過秒数で動画とログの対応する
            # 瞬間を推測していたが、tickの処理が重い局面では実際の録画
            # フレームレートがVIDEO_RECORD_FPSより低下し、動画の見かけの
            # 長さ(フレーム数/宣言fps)が実際の経過時間より短くなる
            # (=動画が実時間より早送りに圧縮される)ことがあり、この推測が
            # 大きくずれて不具合発生時刻の特定が困難になっていた。フレーム
            # 自体に実時刻を焼き込めば、この種の推測が一切不要になる。
            timestamp_text = datetime.now().isoformat()
            cv2.rectangle(bgr_frame, (0, 0), (width, 22), (0, 0, 0), -1)
            cv2.putText(
                bgr_frame,
                timestamp_text,
                (2, 16),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0),
                1,
                cv2.LINE_AA,
            )
            self._video_writer.write(bgr_frame)
        except Exception as exc:  # noqa: BLE001 - 録画の失敗で支援モード自体を止めない
            # pythonw環境ではsys.stdoutがdevnullに差し替えられているため、
            # print()だけでは何が起きたかが完全に失われ、後から録画が
            # いつ・なぜ止まったのか追跡できなくなる(実機で、まさに一番
            # 見たかった致命的な不具合の瞬間の直前で録画が無言で止まって
            # いたことがあった)。デバッグログが有効なら、そちらにも
            # 痕跡を残す。
            print(f"画面録画エラー: {exc}")
            if self._debug_log_file is not None:
                self._debug_log_file.write(f"\n===== 画面録画エラー(録画を停止しました): {exc} =====\n")
                self._debug_log_file.flush()
            self._record_video = False

    # 画像認識の操作ミノがNEXT履歴由来の値と食い違っても、これだけのtick数を
    # 超えて続かない限りは画像側のノイズとみなす。next_advancedが発火する
    # tickでは直前に固定したミノがまだ画像に残っており、実機ログでは
    # この食い違いが数tickで解消していた。
    CURRENT_PIECE_DESYNC_TICKS = 8

    # NEXTの移動量を判断できない状態がこのtick数続いたら、今読めている並びを
    # 新しい基準として取り直す。確定値は自分自身を基準に更新されるため、
    # 一度大きくずれると自力では復帰できない(有識者資料[045])。
    NEXT_REANCHOR_TICKS = 15

    # 手番キーがこのtick数だけ連続で食い違ったら、現在の局面で思考を
    # やり直す。1tickだけの食い違い(HOLD欄の認識ノイズ等)で毎回
    # start_thinkingし直すと探索がゼロからやり直しになるため。
    TURN_KEY_MISMATCH_RETHINK_TICKS = 3

    def _apply_hold_swap_if_any(self, recognition: RecognitionResult, next_shift: int | None) -> bool:
        """既存HOLDとの交換を検出し、内部が持つ操作ミノを入れ替える。

        戻り値: 交換を反映したらTrue(呼び出し側が現在の局面を渡し直す)。

        ネクストが進まないのに操作ミノが変わる経路(有識者資料[037])。
        HOLDに既にミノがある状態でホールドすると、操作中のミノとHOLDの
        中身が入れ替わる。NEXTは1つも進まない。

        【これが無いと何が起きるか】
        操作ミノの種類はNEXT履歴から決めている(_expected_current_piece)が、
        ホールド交換ではNEXTが動かないので履歴側は古いミノのままになる。
        画像は新しいミノを映しているので両者が食い違い続け、8tick後に
        _resync_current_piece_if_desyncedが「画像が正しい」と判断して
        操作ミノを入れ替える。その際に提示済みの配置まで解除されるため、
        手番の途中で提案が別のミノの配置に差し替わる。実機で
        「Lミノ提示の後にIミノを提示する振動」として報告された
        (実機ログでは再同期が13回/137手、AI結果の棄却もHOLD不一致が161件)。

        交換を即座に反映すれば、食い違い自体が起きない。
        なお仕様は「不要なHOLDでも提示した配置は変更しない」なので、
        ここでは内部の追跡だけを直し、表示中の配置には触れない。
        """
        if next_shift != 0 or not recognition.hold_known:
            # NEXTが確実に「1つも進んでいない」と分かった場合だけ扱う。
            # 移動量を判断できなかった(None)tickを「進んでいない」と
            # みなすと、NEXTの進行が確定する前にHOLD欄の変化だけが先に
            # 見えた瞬間を交換と誤認する。
            return False
        old_hold = self._prev_hold_piece
        new_hold = recognition.hold_piece
        if old_hold == "UNKNOWN" or new_hold == old_hold:
            return False
        if old_hold is None:
            # 【空のHOLDへの初回格納は交換ではない】
            # HOLDが空の状態でホールドすると、操作中のミノはHOLDへ入るが、
            # 代わりに出てくるミノはHOLDではなくNEXTの先頭である。
            # これを交換として扱うと、操作ミノに「空だったHOLDの中身」=None
            # を入れてしまい、以降の局面がすべて壊れる。実機で、2手目以降
            # 干渉が連続する重大な不具合になった
            # (ログ: 「HOLD交換を検出: 操作ミノ I -> None」)。
            # この場合はNEXTが進むので、通常の経路で正しく処理される。
            return False
        if new_hold is None:
            # HOLDが空になる交換は通常の操作では起こらない。誤読の可能性が
            # 高いので追従しない。
            return False
        if new_hold != self._last_current_piece:
            # 「今の操作ミノがHOLDへ入った」形になっていない。ホールド交換
            # 以外の原因(誤読、取りこぼし)が疑われるので、ここでは判断せず
            # 従来どおり再同期の判定に委ねる。
            return False
        if self._debug_log_file is not None:
            self._debug_log_file.write(
                f"----- HOLD交換を検出: 操作ミノ {self._last_current_piece} -> {old_hold} -----\n"
            )
            self._debug_log_file.flush()
        self._last_current_piece = old_hold
        self._expected_current_piece = old_hold
        self._prev_hold_piece = new_hold
        # この手番ではHOLDを使い切った。
        self._disallow_hold_active = True
        # 食い違いの計数もやり直す(交換前の値との差で再同期させない)。
        self._current_piece_disagreement_ticks = 0
        return True

    def _resync_current_piece_if_desynced(self, recognition: RecognitionResult) -> bool:
        """画像の操作ミノとNEXT履歴由来の値がずれ続けていたら、画像側へ合わせ直す。

        操作ミノの種類はNEXT履歴から求める方が信頼できるが、こちらが
        取りこぼす可能性(ホールド操作の見落とし、NEXTイベントの欠落等)は
        残る。履歴を無条件に信じ続けると、間違った局面の提案を確信を持って
        出し続けることになるため、画像と長く食い違ったら実際の画面を正とし、
        その局面で思考をやり直す。

        戻り値: 再同期を行ったらTrue。
        """
        if (
            self._last_current_piece is None
            # 画像から読めなかっただけの場合は「食い違い」ではない。
            # これを食い違いとして数えると、認識が苦しい高積み局面ほど
            # 誤って画像側(=読めていない)へ再同期してしまう。
            or recognition.current_piece is None
            or recognition.current_piece == self._last_current_piece
        ):
            self._current_piece_disagreement_ticks = 0
            return False

        self._current_piece_disagreement_ticks += 1
        if self._current_piece_disagreement_ticks < self.CURRENT_PIECE_DESYNC_TICKS:
            return False

        if self._debug_log_file is not None:
            self._debug_log_file.write(
                f"----- 操作ミノを画像へ再同期: {self._last_current_piece} -> "
                f"{recognition.current_piece} ({self._current_piece_disagreement_ticks}tick不一致) -----\n"
            )
            self._debug_log_file.flush()
        self._current_piece_disagreement_ticks = 0
        self._last_current_piece = recognition.current_piece
        self._expected_current_piece = recognition.current_piece
        self._committed_placement = None
        self._committed_placement_tbp = None
        return True

    # 各段の所要時間をこの件数ぶん貯めてから、統計をログへ書き出す。
    LATENCY_REPORT_SAMPLES = 200

    def _record_latency(self, stage: str, seconds: float) -> None:
        """処理段ごとの所要時間を貯める(有識者資料[084][085])。

        「提示が遅い」という報告に対して、どの区間が遅いのかを推測ではなく
        実測で示すために入れる。平均だけでは詰まりが見えないので、中央値・
        95百分位・最大値を出す。取得待ちが主因なら探索を短くしても解決
        しないため、区間を分けて測ることが必要になる。
        """
        self._latency_samples.setdefault(stage, []).append(seconds * 1000.0)

    def _report_latency_if_ready(self) -> None:
        ticks = self._latency_samples.get("tick全体", [])
        if len(ticks) < self.LATENCY_REPORT_SAMPLES or self._debug_log_file is None:
            return
        lines = ["", "----- 処理時間の統計(ミリ秒) -----"]
        for stage, values in self._latency_samples.items():
            if not values:
                continue
            ordered = sorted(values)
            n = len(ordered)
            median = ordered[n // 2]
            p95 = ordered[min(n - 1, int(n * 0.95))]
            lines.append(
                f"  {stage}: 件数={n} 中央値={median:.1f} 95%={p95:.1f} 最大={max(ordered):.1f}"
            )
        self._debug_log_file.write("\n".join(lines) + "\n")
        self._debug_log_file.flush()
        self._latency_samples = {}

    # Cold Clear 2の作り直しを試みるまでの待ち時間。失敗が続く状況で
    # 起動を連打しても復帰しないため、間隔を空ける。
    COLD_CLEAR_RESTART_COOLDOWN_SEC = 3.0

    def _handle_cold_clear_failure(self, exc: Exception) -> None:
        """Cold Clear 2との通信が壊れたとき、ループを止めずに作り直す準備をする。

        実機で、Cold Clear 2が5秒間応答しなくなり、その例外がワーカースレッドの
        外まで伝播してループが停止した(crash_log.txt 2026-09-10T19:25:16)。
        認識も表示も同じスレッドで動いているため、NEXTの表示が最後の値のまま
        固まり、提示も出なくなった。さらに後始末のclose()も壊れたパイプで
        OSErrorを投げ、支援モードを復帰できない状態になった。

        AIの不調は、認識・表示まで巻き込んで止める理由にはならない
        (有識者資料[114])。ここで受け止め、間隔を空けて作り直す。
        """
        if self._debug_log_file is not None:
            self._debug_log_file.write(f"\n----- Cold Clear 2との通信が壊れました: {exc} -----\n")
            self._debug_log_file.flush()
        try:
            self.cold_clear.close()
        except Exception:  # noqa: BLE001 - 後始末の失敗で流れを止めない
            pass
        self._cold_clear_broken = True
        self._cold_clear_retry_at = time.monotonic() + self.COLD_CLEAR_RESTART_COOLDOWN_SEC
        # 壊れる前の要求に対する答えはもう来ない。表示中の提案も根拠を失う。
        self._thinking_turn_key = None
        self._committed_placement = None
        self._committed_placement_tbp = None
        # 作り直したプロセスは何も知らない。探索木の引き継ぎもやり直し。
        self._cc_continuation = None
        if self._last_valid_draw_data is not None:
            self._last_valid_draw_data = None
            self._last_draw_data_set_time = time.monotonic()
            self.draw_data_ready.emit(None)

    def _try_restart_cold_clear(self) -> bool:
        """壊れたCold Clear 2の作り直しを試みる。使える状態ならTrueを返す。"""
        if not self._cold_clear_broken:
            return True
        if time.monotonic() < self._cold_clear_retry_at:
            return False
        try:
            self.cold_clear = ColdClearClient()
        except Exception as exc:  # noqa: BLE001 - 起動失敗でもループは続ける
            self._cold_clear_retry_at = time.monotonic() + self.COLD_CLEAR_RESTART_COOLDOWN_SEC
            if self._debug_log_file is not None:
                self._debug_log_file.write(f"----- Cold Clear 2の再起動に失敗: {exc} -----\n")
                self._debug_log_file.flush()
            return False
        self._cold_clear_broken = False
        # 作り直した直後は何も考えていない。現在の局面を渡し直すまで提案は
        # 出さない。渡し直しは毎tick試す。
        self._thinking_turn_key = None
        self._needs_start_thinking = True
        if self._debug_log_file is not None:
            self._debug_log_file.write("----- Cold Clear 2を作り直しました -----\n")
            self._debug_log_file.flush()
        return True

    def _note_recognition_failure(self) -> None:
        """recognize()がNoneを返した(操作中ミノを検出できなかった)ことを記録する。

        従来、認識失敗は例外時しかログに残らず、「recognize()が正常にNoneを
        返した」場合は完全に無記録だった。そのため実機で「提案が更新されない」
        「NEXTの×が消えない」という症状が出ても、認識が失敗し続けているのか、
        認識は成功していて別の理由で更新されないのかを、後から区別できな
        かった。連続失敗の開始時刻と継続時間を記録し、失敗フレームの生画像も
        1件だけ履歴に残す(毎tick保存すると履歴が失敗画像で埋まるため)。
        """
        if self._recognition_failure_started_at is not None:
            return
        self._recognition_failure_started_at = time.monotonic()
        if self._debug_log_file is not None:
            self._debug_log_file.write(
                f"\n----- 認識失敗の開始 {datetime.now().isoformat()} "
                f"(直前: current={self._last_current_piece} "
                f"settled_top_row={self._last_settled_top_row}) -----\n"
            )
            self._debug_log_file.flush()
            self._save_history_snapshot(
                "認識失敗(recognize()がNoneを返した)フレームの生画像\n"
                f"直前に認識できていた操作中ミノ: {self._last_current_piece}\n"
            )

    def _note_recognition_recovered(self) -> None:
        """認識失敗の連続が解消したときに、その継続時間と回数を記録する。"""
        started = self._recognition_failure_started_at
        self._recognition_failure_started_at = None
        if started is None or self._debug_log_file is None:
            return
        self._debug_log_file.write(
            f"----- 認識失敗から復帰 継続 {time.monotonic() - started:.2f}秒 "
            f"({self._consecutive_recognition_failures}tick連続) -----\n"
        )
        self._debug_log_file.flush()

    def _save_frame_history(self, recognition: RecognitionResult, best: ColdClearMove) -> None:
        """提案が実際に変化した瞬間の生画像・盤面テキストを、タイムスタンプ付きで
        ローテーション保存する（直近FRAME_HISTORY_SIZE件分）。

        DEBUG_FRAMES_DIRは常に「直近1回分を上書き」するだけなので、ユーザーが
        「今おかしい」と気づいた時には既に上書きされてしまい、問題の瞬間の
        画像を後から確認できないという指摘を受けて導入した。「提案が実際に
        変化した瞬間」だけを対象にすることで、保存件数を現実的な数に抑えつつ、
        揺れ・点滅の原因調査に必要な画像を確実に残す。
        """
        self._save_history_snapshot(
            f"変化番号: {self._frame_history_counter + 1}\n\n" + format_board_debug(recognition, best)
        )

    def _save_history_snapshot(self, body_text: str) -> None:
        """DEBUG_FRAMES_DIRの生画像一式を履歴スロットへローテーション保存する。

        呼び出し元は_save_frame_history(提案が変化した瞬間)と
        _note_recognition_failure(認識失敗が続き始めた瞬間)の2つ。
        recognize()は操作中ミノの推論より前に生画像を保存するため、
        認識が失敗したtickでも、その失敗フレームの画像は残っている。
        """
        self._frame_history_counter += 1
        slot = self._frame_history_counter % FRAME_HISTORY_SIZE
        slot_dir = DEBUG_FRAMES_HISTORY_DIR / f"{slot:03d}"
        shutil.rmtree(slot_dir, ignore_errors=True)
        if DEBUG_FRAMES_DIR.exists():
            shutil.copytree(DEBUG_FRAMES_DIR, slot_dir)
        else:
            slot_dir.mkdir(parents=True, exist_ok=True)
        (slot_dir / "info.txt").write_text(
            f"{datetime.now().isoformat()}\n" + body_text, encoding="utf-8"
        )

    def _stabilize_recognition(self, recognition: RecognitionResult) -> RecognitionResult:
        """認識結果全体を1tickの画像だけで即断せず、複数tick連続で同じ内容が
        確認できて初めて「確定」として以降の提案生成に使う。

        Tetris99のAI「ジェフ」(https://gigazine.net/news/20250204-first-place-tetris-99-ai/)
        が採用している「安定した画像が得られるまで待機してから状態を読み取る」
        という設計を参考にした。これまでの対策(I/J誤判定・ゴーストの誤検出・
        光エフェクトのブレなど)は、いずれも「1枚の画像だけで即断する」という
        前提の上で、既知のノイズパターンを1つずつ後追いで潰す方式だったため、
        新しいノイズパターンが出るたびに別の穴が開き続けていた。「意味のある
        変化を検出したら、画面が落ち着くまで待ってから初めて読み取る」という
        前提そのものに変えることで、まだ見つかっていないノイズパターンにも
        構造的に強くなることを狙う。

        比較キーには、操作中ミノの正確な位置(current_piece_min_row)を含め
        ない(自由落下中は常に変わるのが正常なため、含めると永久に安定
        しなくなる)。current_piece・hold_piece・next_queue・board_key
        (=着地済み盤面)という「意味のある状態」だけを見る。

        RECOGNITION_STABILITY_TICKS回連続で同じキーが観測されるか、
        RECOGNITION_STABILITY_TIMEOUT_SEC経過して一切安定しない場合に、
        その時点の最新の認識結果を採用する。まだ確定条件を満たさない間は、
        前回確定した認識結果をそのまま使い続ける(一度も確定していない
        起動直後だけは、反応の遅れを避けるため生の値をそのまま使う)。

        既存の個別デバウンス(next_advancedの5枠比較、board_keyの2tick
        デバウンス等)は撤去せずそのまま残している(このメソッドは、それらの
        さらに手前に位置する追加の安全網)。
        """
        key = (recognition.current_piece, recognition.hold_piece, recognition.next_queue, recognition.board_key)
        now = time.monotonic()

        if key != self._stability_candidate_key:
            self._stability_candidate_key = key
            self._stability_candidate_count = 0
            self._stability_candidate_since = now
        self._stability_candidate_count += 1

        is_stable = self._stability_candidate_count >= self.RECOGNITION_STABILITY_TICKS
        timed_out = now - self._stability_candidate_since >= self.RECOGNITION_STABILITY_TIMEOUT_SEC

        if is_stable or timed_out:
            if self._stability_hold_ticks:
                # 何tick足止めしたかを記録する。安定化待ちが「提示が遅い」の
                # 主要因かどうかを、推測ではなく実測で判断するため。
                self._record_latency(
                    "安定化待ち(tick数)", self._stability_hold_ticks / 1000.0
                )
                self._stability_hold_ticks = 0
            self._last_stabilized_recognition = recognition
            return recognition
        self._stability_hold_ticks += 1

        if self._last_stabilized_recognition is not None:
            return self._last_stabilized_recognition
        # 起動直後、まだ一度も安定していない場合のみ、反応の遅れを避ける
        # ため生の値をそのまま使う。
        return recognition

    def _update_opener(self, recognition: RecognitionResult, *, locked_now: bool, garbage_rise: int) -> None:
        """開幕テンプレの開始判定(図の選択)と、固定の検知。

        開始: 盤面が空・HOLDが空の手番では、1巡目のミノ順で組めるテンプレを
        探す。1つの図を置き終えた後は、同じテンプレの中から今の盤面に
        既存ブロックが一致し、今のミノ順(操作ミノ+NEXT5枠、同じ袋なら
        残り1つも確定)とホールドで組める図を探して続ける(2巡目以降)。
        進行: 固定を検知したら確認待ちにし、_check_opener_progressで盤面が
        手順どおりになったか毎tick確かめる。
        """
        opener = self._opener
        if opener is not None:
            if garbage_rise and recognition.board_key == self._last_board_key:
                # 【2026-09-12・利用者の指示】おじゃまがせり上がっても、テンプレの
                # 形はその上にそのまま載るので続行する。手順の座標をせり上がった
                # 行数ぶん上へずらす(盤面の上端からはみ出すなら諦める)。
                # せり上がりは基準の盤面(2tick確認済み)が更新されるまで毎tick
                # 検知されるため、基準が今の盤面に更新されたtickだけで1回ずらす。
                shifted: list[OpenerStep] = []
                for step in opener.steps:
                    cells = tuple((r - garbage_rise, c) for r, c in step.cells)
                    if any(r < 0 for r, _c in cells):
                        self._log_opener(f"中断(おじゃま{garbage_rise}行で盤面上端を超える)")
                        self._opener = None
                        self._opener_continuing = None
                        return
                    shifted.append(OpenerStep(step.piece, cells, step.use_hold, step.spin))
                opener.steps = shifted
                opener.board = {(r - garbage_rise, c) for r, c in opener.board}
                self._log_opener(f"おじゃま{garbage_rise}行: 手順を上へずらして続行")
            if locked_now and opener.awaiting_since is None:
                # 固定を検知した。盤面が手順どおりになったかは、光っている
                # 置いたばかりのミノが読み切れていない等で同じtickには確定
                # できないことがあるため、ここでは確認待ちにして毎tick
                # (_check_opener_progress)確かめる。
                opener.awaiting_since = time.monotonic()

    def _maybe_start_opener(self, recognition: RecognitionResult) -> None:
        """テンプレが進行中でなければ、始められる図を探す(毎tick)。

        図を置き終えるのは固定の数tick後(確認待ちの解消時)で、その時点では
        次のミノの手番が既に始まっている。要求のタイミングだけで探すと
        次の図の最初の手を通常のAI提案で出してしまうため、毎tick確認する。
        """
        if self._opener is not None or not self._opener_enabled or not recognition.hold_known:
            return
        board_cells = _non_garbage_cells(recognition.board)
        if not board_cells:
            # 盤面が空: 新しい対局。前のテンプレの続きは忘れる。
            self._opener_continuing = None
        if any(cell is not None and cell[0] is None for row in recognition.pending_grid for cell in row):
            return  # 盤面がまだ確定していない(消えた行が残っている等)
        sequence = known_sequence(self._last_current_piece, recognition.next_queue)
        if sequence is None:
            return
        hold = recognition.hold_piece
        # 【2026-09-12・利用者の指示】おじゃまが来ていても図は続ける。図は
        # 盤面の最下段から描かれているので、おじゃま行の数だけ下へずらした
        # 座標で既存ブロックを照合し、手順は上へ戻す。
        garbage_rows = _garbage_row_count(recognition.board)
        matched_cells = {(r + garbage_rows, c) for r, c in board_cells}
        if self._opener_continuing is not None:
            chosen_form = choose_form(self._opener_continuing, matched_cells, sequence, hold)
            if chosen_form is None:
                self._log_opener(
                    f"次の図が見つからず終了 {self._opener_continuing.name_ja} ミノ順={''.join(sequence)} hold={hold}"
                )
                self._opener_continuing = None
                return
            template = self._opener_continuing
            form, steps = chosen_form
        else:
            if board_cells or hold is not None:
                return
            chosen = choose_opener(sequence, hold, matched_cells)
            if chosen is None:
                if self._opener_declined_sequence != sequence:
                    self._opener_declined_sequence = sequence
                    self._log_opener(f"該当なし ミノ順={''.join(sequence)}")
                return
            template, form, steps = chosen
        if garbage_rows:
            steps = [
                OpenerStep(st.piece, tuple((r - garbage_rows, c) for r, c in st.cells), st.use_hold, st.spin)
                for st in steps
            ]
            if any(r < 0 for st in steps for r, _c in st.cells):
                self._log_opener(f"おじゃま{garbage_rows}行で図が盤面上端を超えるため始めない")
                self._opener_continuing = None
                return
        self._opener = _OpenerRun(template=template, form=form, steps=steps, board=set(board_cells))
        self._opener_continuing = None
        # AIの提案を先に出していた場合でも、この手番からテンプレの手に切り替える。
        self._committed_placement = None
        self._committed_placement_tbp = None
        self._committed_move = None
        self._log_opener(
            f"開始 {template.name_ja} [{form.section}] ミノ順={''.join(sequence)} hold={hold} 手順="
            + " ".join(f"{s.piece}{'(H)' if s.use_hold else ''}{'(spin)' if s.spin else ''}" for s in steps)
        )

    # 固定を検知してから、盤面が手順どおりになるのをこの秒数まで待つ。
    # 超えたら手順から外れたとみなしてテンプレをやめる。
    OPENER_CONFIRM_TIMEOUT_SEC = 1.5

    def _check_opener_progress(self, recognition: RecognitionResult) -> None:
        """固定後、盤面が手順どおりになったかを毎tick確認して手順を進める。

        【即断しない理由(2026-09-12実機)】固定を検知したtickの盤面は、置いた
        ばかりのミノが光って種類不明・一部未読になっていることがあり、
        厳密な一致で即断すると手順どおりに置いているのにテンプレが中断した。
        「期待するマスがすべて埋まっている」ことを確認できた時点で進め、
        期待と無関係なマスが1ミノ分以上(4マス以上)埋まったら別の場所に
        置いたとみなして中断する。どちらも確認できないまま一定時間が過ぎた
        場合も中断する。Tスピン等でラインが消える手は、消去後の盤面
        (apply_step)と比べる。図を置き終えたら次の図を探す(_update_opener)。
        """
        opener = self._opener
        if opener is None or opener.awaiting_since is None:
            return
        actual = _non_garbage_cells(recognition.board)
        expected = opener.expected_after_current()
        extra = actual - expected
        if expected <= actual and len(extra) < 4:
            opener.board = expected
            opener.index += 1
            opener.awaiting_since = None
            if opener.current_step() is None:
                self._log_opener(f"図を置き終えた [{opener.form.section}]")
                self._opener_continuing = opener.template
                self._opener = None
            return
        elapsed = time.monotonic() - opener.awaiting_since
        if len(extra) >= 4 or elapsed >= self.OPENER_CONFIRM_TIMEOUT_SEC:
            self._log_opener(
                f"中断(手順と異なる盤面 {elapsed:.1f}秒) 期待={sorted(expected)} 実際={sorted(actual)}"
            )
            self._opener = None
            self._opener_continuing = None

    def _log_opener(self, text: str) -> None:
        if self._debug_log_file is not None:
            self._debug_log_file.write(f"----- 開幕テンプレ: {text} -----\n")
            self._debug_log_file.flush()

    def _request_thinking(
        self,
        recognition: RecognitionResult,
        effective_hold_piece: str | None,
        *,
        just_held: bool,
        locked_now: bool,
        committed: tuple[str, tuple[tuple[int, int], ...]] | None,
        committed_tbp: dict | None,
        garbage_rise: int,
        forced_by_resync: bool,
    ) -> None:
        """Cold Clear 2へ局面を伝える。可能なら探索木を引き継ぎ、無理ならstartで渡し直す。

        【引き継ぎ(play)の条件】利用者が提示どおりに置いた場合だけ。
        「Cold Clear 2が持っている盤面に提示した配置を置いてライン消去した
        結果」と「今認識している盤面」の占有が一致することで確認する。
        一致しなければ(別の場所に置いた、おじゃま、エフェクトの混入等)
        従来どおりstartで渡し直す。提示と実際の盤面の両方で確認するので、
        推測で木を進めることはない(資料「先行計算は実際の固定後局面との
        一致確認ができる場合のみ」)。

        固定以外の契機(ホールド、タイムアウト保険)では、引き継ぎ中なら
        局面を渡し直さない。Cold Clear 2の内部モデルはホールドと操作ミノを
        対称に扱う(reserve/queue)ため、ホールド操作で局面は変わらない。
        ただし提示が無い状態でのホールドは、従来どおりdisallow_hold付きで
        渡し直す(ホールドの往復を防ぐため)。
        """
        cont = self._cc_continuation
        reason: str | None = None
        if cont is None:
            reason = "引き継ぎ元なし"
        elif garbage_rise or forced_by_resync:
            reason = "おじゃま/再同期"
        elif locked_now:
            if committed is None or committed_tbp is None:
                reason = "提示なしで固定"
            else:
                piece, cells = committed
                expected = _board_after_placement(cont.board, piece, cells)
                actual, _ = recognition.board.clear_lines()
                if _board_occupancy(expected) != _board_occupancy(actual):
                    reason = "提示と異なる盤面"
                elif not cont.queue:
                    reason = "内部キューが空"
                else:
                    self.cold_clear.advance_thinking(committed_tbp, [])
                    cont.board = expected
                    # 内部の進み方: 指した手がqueueの先頭ならそれを消費、
                    # reserveならqueueの先頭がreserveへ移る。どちらもqueueは
                    # 先頭が1つ減る。
                    if piece != cont.queue[0] and piece == cont.reserve:
                        cont.reserve = cont.queue[0]
                    cont.queue.pop(0)
                    if self._debug_log_file is not None:
                        self._debug_log_file.write(
                            f"----- 探索木を引き継ぎ(play): {piece} {list(cells)} -----\n"
                        )
                        self._debug_log_file.flush()
                    self._sync_cc_queue(effective_hold_piece)
                    return
        else:
            # ホールド・タイムアウト保険など固定以外の契機。
            if just_held and committed is None:
                reason = "提示なしでホールド"
            else:
                actual, _ = recognition.board.clear_lines()
                if _board_occupancy(cont.board) != _board_occupancy(actual):
                    reason = "盤面が内部局面と不一致"
                else:
                    self._sync_cc_queue(effective_hold_piece)
                    return

        if self._debug_log_file is not None and cont is not None:
            self._debug_log_file.write(f"----- 探索木を引き継がずstart: {reason} -----\n")
            self._debug_log_file.flush()
        self.cold_clear.start_thinking(
            recognition.board,
            self._last_current_piece,
            effective_hold_piece,
            list(recognition.next_queue),
            disallow_hold=just_held,
        )
        # 引き継ぎはNEXT5枠がすべて読めている時だけ始める。欠けたまま始めると
        # 以後どのNEXTを渡したか対応が取れない。disallow_hold(ホールド偽装)で
        # 渡した局面も、内部のreserveが実際と違うので引き継がない。
        if (
            not just_held
            and self._last_current_piece is not None
            and len(recognition.next_queue) == 5
            and all(slot is not None for slot in recognition.next_slots_raw)
        ):
            cleared, _ = recognition.board.clear_lines()
            if effective_hold_piece is None:
                queue = list(recognition.next_queue)
                reserve = self._last_current_piece
            else:
                queue = [self._last_current_piece, *recognition.next_queue]
                reserve = effective_hold_piece
            self._cc_continuation = _ColdClearContinuation(board=cleared, queue=queue, reserve=reserve)
        else:
            self._cc_continuation = None

    def _sync_cc_queue(self, hold_piece: str | None) -> None:
        """Cold Clear 2の内部キューと実際のNEXTを突き合わせ、未送信のNEXTを足す。

        Cold Clear 2は「reserve(ホールド相当)1つ + queue」で局面を持ち、
        実際のホールドと操作ミノのどちらがreserveかは対称に扱う。実際の
        {操作ミノ, ホールド}のうちreserveでない方がqueueの先頭、その後ろに
        NEXT5枠が続く(ホールドが空ならqueue=NEXT5枠)。

        【7回目の実機ログ】以前は「実際のホールドが空でなければ[操作ミノ,
        *NEXT]」としていたため、startでholdなし(操作ミノがreserve)の後に
        利用者が空HOLDへ格納すると、内部=[NEXT...]と実際=[操作ミノ, NEXT...]
        がずれて引き継ぎを15回中止していた。内部のreserveを追跡して比較する。
        一致しなければ引き継ぎをやめる(次の要求でstartに戻る)。
        """
        cont = self._cc_continuation
        if cont is None:
            return
        slots = list(self._confirmed_next_slots) if self._confirmed_next_slots is not None else []
        current = self._last_current_piece

        def _aligns(real: list[str | None]) -> bool:
            return all(
                real[i] is None or real[i] == cont.queue[i] for i in range(min(len(cont.queue), len(real)))
            )

        # 実際のキュー相当の候補。ホールドの表示がNEXTの進行より先に変わる
        # 遷移途中のtick(HOLD欄は新しいのにNEXTは古い)では、どちらが
        # reserveか一意に決められないため、両方の解釈を試して整合する方を採る。
        candidates: list[list[str | None]] = [slots]
        if hold_piece is not None and current is not None:
            other = hold_piece if current == cont.reserve else current
            candidates.insert(0, [other, *slots])
        real = next((cand for cand in candidates if _aligns(cand)), None)
        if real is None:
            if self._debug_log_file is not None:
                self._debug_log_file.write(
                    f"----- 探索木の引き継ぎを中止: NEXTが不一致 内部={cont.queue} 実際={candidates[0]} -----\n"
                )
                self._debug_log_file.flush()
            self._cc_continuation = None
            return
        new_pieces: list[str] = []
        for i in range(len(cont.queue), len(real)):
            if real[i] is None:
                break
            new_pieces.append(real[i])
        if new_pieces:
            self.cold_clear.add_new_pieces(new_pieces)
            cont.queue.extend(new_pieces)

    def _stabilize_suggestion(self, move: ColdClearMove) -> ColdClearMove | None:
        """そのミノについて最初に提示した配置を、置くまで変更しない。

        仕様は「提示した配置は、実際にミノを置くまで変更しない」であり、
        人間の置きミス・不要なホールド・移動できなくなった場合も途中で
        変更しない。ユーザーが提示どおりに操作し始めた直後に切り替わると
        「操作の途中で梯子を外される」体験になり実用性を損なうため。

        【時間ベースのロックをやめた理由】以前は「最初の提案から
        SUGGESTION_LOCK_SEC(0.4秒)は無視し、それ以降は2回連続で同じ新しい
        配置が来たら切り替える」という近似だった。しかしCold Clear 2の
        段階的思考では深い探索の結果が1秒前後してから届くため、ロックが
        切れた後に配置が入れ替わる「提案の振動」が実機ログで確認された
        (17:47:42、同一局面のまま best: piece=Z use_hold=True nodes=14188
        → best: piece=S use_hold=False nodes=648201)。仕様は時間ではなく
        「置くまで」なので、手番が変わるまで一切切り替えない実装に改めた。
        _committed_placementは新規スポーン時にNoneへ戻される。

        【トレードオフ】最初に届く提案は探索が浅い(1〜2万ノード程度)ため、
        深い探索(数十万ノード)の結果より手の質が落ちる場合がある。表示の
        速さと手の質のどちらを優先するかは、実機で評価して決める必要がある
        (初回表示前に短い思考時間を設ける案が代替として考えられる)。
        """
        # use_holdは比較に含めない。「ホールドしてZを置く」を提示し、利用者が
        # ホールドした後に届く同じ配置は「Zを置く(ホールド不要)」になる。
        # 同じ配置なら同じ提案として受け入れ、HOLD欄の強調だけが消える。
        placement = (move.piece, tuple(move.landing_cells))

        if self._committed_placement is None:
            self._committed_placement = placement
            self._committed_placement_tbp = move.placement
            # 読み筋(2手目以降)も一緒に固定する。探索が深まって2手目以降だけが
            # 変わっても表示を揺らさない(1手目と同じく「置くまで変更しない」)。
            self._committed_move = move
            return move

        if placement == self._committed_placement:
            return self._committed_move if self._committed_move is not None else move

        # この手番については既に配置を提示済みなので、探索が深まって別の
        # 配置が返ってきても切り替えない。
        return None


class MainWindow(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("テトリス初心者支援AI")
        self.resize(360, 160)

        self.calibration: CalibrationResult | None = None
        self.assist_mode = False
        self.last_valid_draw_data: OverlayDrawData | None = None
        self.overlay: OverlayWindow | None = None
        self.badge: ControlBadge | None = None
        self.cold_clear: ColdClearClient | None = None
        # 認識→思考ループの実体はAssistWorker(別スレッド)が持つ。以前はここに
        # current_piece追跡やhold追跡の状態を持っていたが、ワーカースレッド側に
        # 移した（詳細はAssistWorkerのdocstring参照）。
        self.worker: AssistWorker | None = None

        self.safety_timer = QtCore.QTimer(self)
        self.safety_timer.setSingleShot(True)
        self.safety_timer.timeout.connect(self._stop_assist_mode)

        self._build_normal_ui()
        self._refresh_calibration_status()

    # ---------- 通常モードUI ----------
    def _build_normal_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        self.status_label = QtWidgets.QLabel()
        layout.addWidget(self.status_label)

        calibrate_btn = QtWidgets.QPushButton("キャリブレーションを実行")
        calibrate_btn.clicked.connect(self._on_calibrate_clicked)
        layout.addWidget(calibrate_btn)

        self.assist_btn = QtWidgets.QPushButton("支援モード開始")
        self.assist_btn.clicked.connect(self._on_toggle_assist)
        layout.addWidget(self.assist_btn)

        self.debug_log_checkbox = QtWidgets.QCheckBox(
            f"認識結果をログに出力する ({DEBUG_LOG_PATH.name} / {DEBUG_FRAMES_DIR.name}\\)"
        )
        self.debug_log_checkbox.setToolTip(
            "最善手が明らかにおかしいと感じた時、AIが実際に何を盤面として"
            "認識していたかを突き合わせて確認するためのデバッグ用ログです。\n"
            f"テキストログに加えて、実際にキャリブレーション座標で切り出した"
            f"盤面・ホールド・ネクストの生画像を{DEBUG_FRAMES_DIR.name}フォルダに"
            "直近1回分保存します（座標そのもののズレを画像で確認できます）。"
        )
        layout.addWidget(self.debug_log_checkbox)

        self.record_video_checkbox = QtWidgets.QCheckBox(
            f"支援モード中の画面を録画する ({DEBUG_VIDEO_PATH.name}、暫定機能)"
        )
        self.record_video_checkbox.setToolTip(
            "不具合報告のたびに別の画面録画ソフトで撮り直す手間を省くための"
            "暫定機能です。キャリブレーション済みの範囲(盤面+HOLD+NEXT欄)を"
            f"支援モード中ずっと{DEBUG_VIDEO_PATH.name}に録画します"
            "(次回の支援モード開始時に上書きされます)。\n"
            "画面キャプチャなので、オーバーレイの提案(色ドット)も"
            "外部の画面録画ソフトと同様に映り込みます。"
        )
        layout.addWidget(self.record_video_checkbox)

        self.opener_checkbox = QtWidgets.QCheckBox("開幕テンプレを提示する(はちみつ砲・迷走砲・山岳積み2号・オリーブ積み)")
        self.opener_checkbox.setChecked(True)

        depth_row = QtWidgets.QHBoxLayout()
        depth_row.addWidget(QtWidgets.QLabel("最善手の表示手数(1〜5):"))
        self.plan_depth_spin = QtWidgets.QSpinBox()
        self.plan_depth_spin.setRange(1, 5)
        self.plan_depth_spin.setValue(3)
        self.plan_depth_spin.setToolTip(
            "1なら今のミノの置き場所だけ、2以上なら2手目以降の読み筋も"
            "小さいドット+番号で表示します。ラインが消える手より先は表示しません。"
        )
        depth_row.addWidget(self.plan_depth_spin)
        depth_row.addStretch(1)
        layout.addLayout(depth_row)
        self.opener_checkbox.setToolTip(
            "対局開始時(盤面とHOLDが空)のミノ順から組める開幕テンプレを選び、"
            "1巡目の手順をAIの提案の代わりに表示します。テンプレ名は"
            "HOLD欄の下に表示します。提示と違う場所に置くと通常のAI提案に戻ります。"
        )
        layout.addWidget(self.opener_checkbox)

        hint = QtWidgets.QLabel(
            "支援モード中は画面右上の「終了」ボタンで終了できます"
            "（ゲーム側のEscキー操作と競合しないよう、Escキーは使いません）"
        )
        hint.setStyleSheet("color: gray;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.setLayout(layout)

    def _refresh_calibration_status(self) -> None:
        if CONFIG_PATH.exists():
            self.calibration = load_calibration()
            self.status_label.setText(f"キャリブレーション: 読み込み済み ({CONFIG_PATH})")
        else:
            self.calibration = None
            self.status_label.setText("キャリブレーション: 未設定")

    def _on_calibrate_clicked(self) -> None:
        run_calibration()
        self._refresh_calibration_status()

    def _on_toggle_assist(self) -> None:
        if self.assist_mode:
            self._stop_assist_mode()
        else:
            self._start_assist_mode()

    # ---------- 支援モード ----------
    def _start_assist_mode(self) -> None:
        if self.calibration is None:
            QtWidgets.QMessageBox.warning(self, "エラー", "先にキャリブレーションを実行してください")
            return

        try:
            self.cold_clear = ColdClearClient()
        except (FileNotFoundError, RuntimeError, TimeoutError, OSError) as exc:
            # TimeoutErrorは、起動直後のinfoメッセージ待ちでCold Clear 2から
            # 応答が得られなかった場合（例: pythonw環境でsubprocessの
            # コンソール確保が不安定になりパイプ通信が機能しない等）に発生
            # しうる。以前はこの型を捕まえておらず、メインスレッドの
            # 未処理例外としてアプリが不安定な状態になってしまっていた
            # （実機のcrash_log.txtで確認）。原因そのもの
            # （cold_clear_client.pyのcreationflags指定）は別途修正したが、
            # 万一同様の問題が再発しても、アプリを巻き込まず通常のエラー
            # ダイアログで済むよう、ここでも幅広く捕捉しておく。
            QtWidgets.QMessageBox.critical(self, "エラー", f"Cold Clear 2の起動に失敗しました:\n{exc}")
            return

        self.hide()

        self.overlay = OverlayWindow(self.calibration)
        self.overlay.show()
        overlay_excluded = _exclude_window_from_screen_capture(self.overlay)

        self.badge = ControlBadge(on_stop=self._stop_assist_mode)
        self.badge.show()
        badge_excluded = _exclude_window_from_screen_capture(self.badge)

        # 画面キャプチャからの除外に失敗した場合、自分が描いたドットを
        # 自分で盤面ブロックとして読んでしまう(自己汚染)。これは盤面認識が
        # 静かに壊れる形で現れ、原因の特定が非常に困難なため、黙って
        # 続行せず必ず利用者へ知らせる
        # (_exclude_window_from_screen_captureのdocstring参照)。
        if not (overlay_excluded and badge_excluded):
            QtWidgets.QMessageBox.warning(
                self,
                "警告",
                "オーバーレイを画面キャプチャから除外できませんでした。\n"
                "表示中のドットを盤面のブロックとして誤認識する可能性があります。",
            )

        self.assist_mode = True
        self.last_valid_draw_data = None

        debug_log_path = DEBUG_LOG_PATH if self.debug_log_checkbox.isChecked() else None
        record_video = self.record_video_checkbox.isChecked()
        self.worker = AssistWorker(
            self.calibration,
            self.cold_clear,
            debug_log_path,
            record_video=record_video,
            opener_enabled=self.opener_checkbox.isChecked(),
            plan_depth=self.plan_depth_spin.value(),
        )
        # 別スレッド(worker)からのシグナルなので、必ずメインスレッドの
        # イベントループ経由で_on_draw_data_readyが呼ばれるよう明示する
        # （AutoConnectionでも通常は自動的にQueuedConnectionになるはずだが、
        # オーバーレイの2重表示不具合の調査の一環として明示的に固定した）。
        self.worker.draw_data_ready.connect(
            self._on_draw_data_ready, QtCore.Qt.ConnectionType.QueuedConnection
        )
        # 【2026-09-07・暫定のデバッグ機能】next_debug_ready参照。
        self.worker.next_debug_ready.connect(
            self._on_next_debug_ready, QtCore.Qt.ConnectionType.QueuedConnection
        )
        self.worker.fatal_error.connect(self._on_fatal_error, QtCore.Qt.ConnectionType.QueuedConnection)
        self.worker.start()

        self.safety_timer.start(SAFETY_TIMEOUT_MS)

    def _stop_assist_mode(self) -> None:
        self.safety_timer.stop()

        if self.worker is not None:
            # ワーカーはCold Clear 2が応答不能になったとき自分で作り直す
            # (_handle_cold_clear_failure参照)。その場合こちらが持っている
            # 参照は古いものになるので、後始末は必ずワーカー側の現物に対して
            # 行う(でないと作り直した方のプロセスが残り続ける)。
            self.cold_clear = self.worker.cold_clear
            self.worker.stop()
            # workerは_tick_once内でCold Clear 2からの応答をブロッキング
            # 読み込みしているため、万一プロセスが応答不能（デッドロック等）
            # に陥った場合、stop()でフラグを立てるだけでは抜け出せない。
            # 一定時間待って終わらなければ、アプリごとフリーズさせるより
            # 強制終了する方がまし。
            if not self.worker.wait(3000):
                self.worker.terminate()
                self.worker.wait()
            self.worker = None

        if self.cold_clear is not None:
            self.cold_clear.close()
            self.cold_clear = None

        if self.overlay is not None:
            self.overlay.close()
            self.overlay = None
        if self.badge is not None:
            self.badge.close()
            self.badge = None

        self.assist_mode = False
        self.show()

    def _on_draw_data_ready(self, draw_data: OverlayDrawData | None) -> None:
        self.last_valid_draw_data = draw_data
        if self.overlay is not None:
            self.overlay.update_draw_data(draw_data)

    def _on_next_debug_ready(self, slots: tuple[str | None, ...]) -> None:
        """【2026-09-07・暫定のデバッグ機能】next_debug_ready参照。"""
        if self.overlay is not None:
            self.overlay.update_next_debug_data(slots)

    def _on_fatal_error(self, message: str) -> None:
        # workerは既に自分でループを抜けているため、ここでは
        # プロセス/ウィンドウの後始末と、ユーザーへの通知だけを行う。
        self._stop_assist_mode()
        QtWidgets.QMessageBox.critical(
            self, "エラー", f"Cold Clear 2との通信が切断されました。支援モードを終了します。\n{message}"
        )

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        if self.worker is not None:
            # ワーカーはCold Clear 2が応答不能になったとき自分で作り直す
            # (_handle_cold_clear_failure参照)。その場合こちらが持っている
            # 参照は古いものになるので、後始末は必ずワーカー側の現物に対して
            # 行う(でないと作り直した方のプロセスが残り続ける)。
            self.cold_clear = self.worker.cold_clear
            self.worker.stop()
            if not self.worker.wait(3000):
                self.worker.terminate()
                self.worker.wait()
        if self.overlay is not None:
            self.overlay.close()
        if self.badge is not None:
            self.badge.close()
        super().closeEvent(event)


def _log_uncaught_exception(exc_type, exc_value, exc_traceback) -> None:
    """メインスレッドで発生した未処理例外をcrash_log.txtに記録する。

    pythonw(コンソール非表示)で起動すると、通常なら標準エラー出力に
    出るはずのトレースバックがどこにも表示されなくなり、「クリックしたら
    落ちた」以上の情報が一切得られなくなる（AssistWorker側のQThread内
    例外は別途run()で捕捉しているが、メインスレッド側、例えば
    _start_assist_mode自体で起きた例外はこちらでしか拾えない）。
    """
    import traceback

    crash_log_path = Path(__file__).resolve().parent.parent / "crash_log.txt"
    with open(crash_log_path, "a", encoding="utf-8") as f:
        f.write(f"\n===== クラッシュ(メインスレッド) {datetime.now().isoformat()} =====\n")
        traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)


def main() -> None:
    sys.excepthook = _log_uncaught_exception
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
