"""Switch 対応プラグイン: キャプチャボードで PC に映した画面を使うための、手動のキャリブレーションのボタンを出す。

標準では Steam 版ぷよぷよテトリス2のウィンドウを探して盤面・HOLD・NEXT の位置を求める(src/capture/window_detect.py)。
ゲームのウィンドウが見つからない時は、このプラグインのキャリブレーション(config/calibration.json)を使う。
"""

from src.plugin_api import Plugin

PLUGIN = Plugin(
    id="switch_capture",
    name="Switch 対応(手動キャリブレーション)",
    description="キャプチャボードで映した Switch 版の画面用に、盤面・HOLD・NEXT の位置を手動で指定するボタンを出します"
    "(Steam 版のウィンドウが見つかった時はそちらを優先します)",
    manual_calibration=True,
)
