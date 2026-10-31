"""TBA のプラグイン(2026-10-30、利用者「PBA(../Puyopuyo)のようなプラグイン形式にし、最終的には PBA と統合した1つのツールにしたい」)

PBA の src/plugin_api.py と同じ形にしてある(統合しやすくするため)。

標準機能: 支援モード・シミュレーター・無限中あけREN・支援モードの設定(テンプレ・DPC・TDTD・継続パフェ)・思考エンジン Cold Clear 2・
Steam 版のウィンドウの検出(src/capture/window_detect.py。手動のキャリブレーションが要らない)。
それ以外はプラグインが足す。プラグインは plugins/<名前>/plugin.py に PLUGIN = Plugin(...) を書いて置く(src/plugin_loader.py が読む)。

プラグインができること(今の段階):
- full_auto: 全自動モード(Steam 版ぷよテト2の CPU 戦で、AI の手をキー入力で送る)の開始ボタンと設定をメイン画面に出す
- debug_log: 認識結果のログと画面の録画(debug_logs/)の切り替えをメイン画面に出す
- engines: 思考エンジン(TBP 互換。Cold Clear 2 の代わり)を足す。シミュレーターの「AI」で Cold Clear 2 と切り替えられる
- manual_calibration: 画面の手動キャリブレーションのボタンを出す(Switch のキャプチャボード用。ゲームのウィンドウが見つからない時に使う)
- local_versus: 全自動で 2P(右の盤面)も動かすチェックを出す(ローカル対戦。2P は仮想ゲームパッド)
- synced_input: 全自動の入力を Zetris 方式にする(画面の変化でゲームのフレームに合わせて送る。1P も仮想パッドにできる)
- memory_read: 全自動で、ゲームのメモリから操作中のミノ・NEXT・ミノの数を読み、固定をすぐ確かめる(1P・読むだけ)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Engine:
    label: str  # 候補欄・推奨欄・切り替えに出す名前
    exe: Path  # TBP 互換の思考エンジンの実行ファイル
    weights: Path | None = None  # エンジンへ --config で渡す評価の重み(省略可)


@dataclass(frozen=True)
class Plugin:
    id: str
    name: str
    description: str = ""
    # 配布してよいか。False のプラグイン(全自動モード等)は配布物(exe)に入れない
    distributable: bool = True
    full_auto: bool = False
    debug_log: bool = False
    manual_calibration: bool = False
    # 【2026-10-31】ローカル対戦: 全自動で 2P(右の盤面)も動かすチェックを出す(2P は仮想ゲームパッド)
    local_versus: bool = False
    # 【2026-10-31】Zetris 方式の入力: 画面の変化でゲームのフレームに合わせて入力を送る(src/auto/frame_sync.py)。1P も仮想パッドにできる
    synced_input: bool = False
    # 【2026-10-31】メモリ読み取り: 全自動で固定をメモリですぐ確かめる(src/auto/ppt2_memory.py。1P・読むだけ)
    memory_read: bool = False
    engines: dict[str, Engine] = field(default_factory=dict)
