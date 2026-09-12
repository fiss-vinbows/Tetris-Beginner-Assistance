"""テンプレート画像とのピクセル一致率によるミノ種類判定。

Tetris99のAI「ジェフ」(https://gigazine.net/news/20250204-first-place-tetris-99-ai/)
が採用している「あらかじめ用意した色見本(テンプレート)とのピクセル単位の
一致度を比較し、一致度が閾値以上の場合だけ確定する」という設計を参考にした。

このプロジェクトが従来使っていた色相(Hue)ベースの判定(piece_colors.py)は、
I/Jのように色相が近いミノの取り違えや、光エフェクト・ゴースト表示など
「たまたま特定の色相に見えてしまうノイズ」に弱いことが実機ログで繰り返し
確認された。テンプレートマッチングは「決め打ちの色見本とどれだけ近いか」を
直接比較するため、想定外のノイズパターンに対しても、どのテンプレートとも
十分近くなければ素直に「不明(=空マス扱い)」として棄却できる。

空マス(EMPTY)は背景の透かし模様や照明の影響を受けやすく、決まった1つの
見た目を持たないためテンプレート化しない。GARBAGE(お邪魔ブロック)も
同様の理由でテンプレート化しない: 彩度がほぼゼロの灰色は「特定の色相」を
持たず明るさそのものが特徴のため、ライン消去等の光エフェクトで画面全体が
明るくなる瞬間、1枚の色見本との色差が大きくなりすぎて「一致しない」と
判定され、盤面全体が一瞬空に見えてしまう重大な誤読みが実機ログで確認
された(彩度のある7色のミノは色相さえ保たれていれば多少明るさが変わっても
一致率が大きく落ちない)。GARBAGEは呼び出し側(board_reader.py)で、
テンプレートに一致しなかったセルに対して、従来通りの彩度・明度の閾値
判定でフォールバック判定する。

7色のミノのいずれにも十分近くない場合に、Noneを返す(GARBAGEか空マスかは
呼び出し側で判定する)。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ..paths import resource_root

# 実行ファイル形式ではPyInstallerが同梱データとして展開した場所から読む。
TEMPLATES_DIR = resource_root() / "src" / "vision" / "templates"

# テンプレート化する7色のミノ。GARBAGE・空マスは意図的に含めない
# (モジュールdocstring参照)。
TEMPLATE_NAMES: tuple[str, ...] = ("I", "O", "T", "S", "Z", "J", "L")

# セル画像とテンプレート画像を比較する際、対応するピクセル同士のRGB距離が
# この値未満なら「一致」とみなす。実測に基づく暫定値で、実機での再調整が必要。
_PIXEL_MATCH_TOLERANCE = 60.0

# 最も一致率の高いテンプレートであっても、この一致率未満なら「どのテンプレート
# にも十分近くない」とみなし、空マスとして扱う。ジェフの実装は95%(グレースケール
# 二値化後)だが、このプロジェクトは色付きのまま比較し、かつグロス効果による
# セル内の明暗ムラの影響を受けるため、まずは緩めの値から始めて実機で調整する。
MATCH_THRESHOLD = 0.6


def load_templates(templates_dir: Path = TEMPLATES_DIR) -> dict[str, np.ndarray]:
    """7色分のテンプレート画像を読み込む。

    呼び出し側で1回だけ読み込み、使い回すことを想定している(毎フレーム
    ディスクから読み直すのは無駄なため)。通常はget_templates()経由で
    キャッシュ済みのものを使い、これを直接呼ぶのはテスト等に限る。
    """
    from PIL import Image

    templates: dict[str, np.ndarray] = {}
    for name in TEMPLATE_NAMES:
        path = templates_dir / f"{name}.png"
        templates[name] = np.array(Image.open(path).convert("RGB"))
    return templates


# テンプレート画像は起動後1回だけ読み込み、使い回す(毎フレームディスクから
# 読み直すのは無駄なため)。board_reader.py・next_hold_reader.pyの両方が
# 同じテンプレート集合を必要とするため、ここで一元的にキャッシュする。
_templates_cache: dict[str, np.ndarray] | None = None


def get_templates() -> dict[str, np.ndarray]:
    """キャッシュ済みのテンプレート集合を返す(初回のみディスクから読み込む)。"""
    global _templates_cache
    if _templates_cache is None:
        _templates_cache = load_templates()
    return _templates_cache


_representative_colors_cache: dict[str, np.ndarray] | None = None


# 代表色を求める際、「ミノ本体の画素」とみなす彩度のしきい値(画像内の
# 最大彩度に対する割合)。縁の写り込みやアンチエイリアスされた境界画素を
# 除き、ベタ塗り部分だけを集めるための値。
_BODY_CHROMA_RATIO = 0.6


def dominant_body_color(image: np.ndarray) -> np.ndarray | None:
    """画像内の「ミノ本体」の代表色(中央値)を返す。本体が無ければNone。

    彩度が画像内最大の_BODY_CHROMA_RATIO倍以上ある画素だけを本体とみなし、
    その中央値を取る。

    【1点サンプリングをやめた理由】以前は「最も彩度が高い1点」の色を
    そのまま代表色にしていたが、これは外れ値1画素に判定全体を委ねる
    方式であり、実機で2つの重大な誤認を生んでいた。

    (1) テンプレート側: J.pngの左端にHOLD欄のオレンジ色の縁取りが写り
        込んでおり、そのオレンジ画素の彩度(210)が青いJ本体の彩度(180)を
        上回るため、Jの代表色がオレンジ(213,115,3)として採取されていた。
        結果、実物の青いJはIの代表色に最も近くなり、実機ログ全体で
        NEXT/HOLD欄のJ認識回数が0回、Iが他の約2倍という状態だった。
    (2) サンプル側: ミノ表面の光沢(ハイライト)は本体色より明るく水色寄りに
        写るため、青いJの最大彩度点が(0,145,206)となり、Iの代表色との
        距離が14しかない。テンプレート側だけを直しても解決しない。

    中央値を使うことで、縁の写り込みも光沢も少数派として排除される。
    実測では、この方式でJの代表色は(0,82,181)、実物のJのサンプルは
    (0,83,181)となり距離1で正しく一致する(Iとの距離は75)。
    """
    patch_f = image.astype(np.float32)
    chroma = patch_f.max(axis=2) - patch_f.min(axis=2)
    max_chroma = float(chroma.max())
    if max_chroma < 1.0:
        return None
    body = patch_f[chroma >= max_chroma * _BODY_CHROMA_RATIO]
    if body.size == 0:
        return None
    return np.median(body, axis=0).astype(np.float32)


def get_template_representative_colors() -> dict[str, np.ndarray]:
    """各テンプレート画像の「ミノ本体の代表色」を、7色分まとめて返す。

    HOLD/NEXT欄のようにミノがミニチュアアイコンとして表示され、枠全体の
    大部分が背景(暗い透かし模様)で占められる場合、match_cell_template
    (枠全体をテンプレートとピクセル単位で比較する方式)は背景ピクセルに
    一致率を薄められてしまい、実機映像で一致率が0.4程度にしか達しない
    ことが判明した(枠全体がミノ色でほぼ埋まる盤面セルとは前提が異なる)。
    このため、HOLD/NEXT欄では「サンプル側のミノ本体の代表色」と
    「テンプレート側のミノ本体の代表色」同士を比較する方式
    (next_hold_reader.read_piece_from_patch参照)を使う。テンプレート
    画像自体は実機から採取した色見本のため、値だけハードコードする
    piece_colors.PIECE_COLORSより実際の見た目に近い。

    代表色の求め方はdominant_body_color参照(1点サンプリングは実機で
    重大な誤認を起こしたため使わない)。
    """
    global _representative_colors_cache
    if _representative_colors_cache is not None:
        return _representative_colors_cache
    colors: dict[str, np.ndarray] = {}
    for name, template in get_templates().items():
        color = dominant_body_color(template)
        if color is not None:
            colors[name] = color
    _representative_colors_cache = colors
    return colors


def _resize_nearest(image: np.ndarray, height: int, width: int) -> np.ndarray:
    """依存ライブラリ(cv2/PIL)を増やさない、最近傍補間による简易リサイズ。

    テンプレート画像とセルのパッチは、キャリブレーションのセルサイズの
    誤差により1〜2px程度サイズが異なることがあるため、比較前にサイズを
    揃える必要がある。色の一致率だけを見たいので、補間による色の混ざりが
    起きない最近傍法を使う。
    """
    src_h, src_w = image.shape[0], image.shape[1]
    row_idx = (np.arange(height) * src_h / height).astype(np.intp).clip(0, src_h - 1)
    col_idx = (np.arange(width) * src_w / width).astype(np.intp).clip(0, src_w - 1)
    return image[row_idx][:, col_idx]


# 特定のサイズへ合わせ済みのテンプレート(float32)のキャッシュ。
# キーは (テンプレート名, 高さ, 幅)。
_resized_template_cache: dict[tuple[int, int, int], tuple[np.ndarray, np.ndarray]] = {}


def _resized_template_f32(template: np.ndarray, height: int, width: int) -> np.ndarray:
    """指定サイズへ合わせたテンプレートをfloat32で返す(結果を再利用する)。

    盤面200セルそれぞれで7種類のテンプレートと比較するため、キャッシュが
    ないと1フレームあたり1400回も同じリサイズと型変換を繰り返すことになる。
    セルの大きさはキャリブレーションで決まりフレーム間で変わらないので、
    一度作った結果をそのまま使い回せる。
    """
    key = (id(template), height, width)
    cached = _resized_template_cache.get(key)
    if cached is None:
        resized = _resize_nearest(template, height, width).astype(np.float32)
        # 元のテンプレートへの参照も一緒に保持する。
        # 【なぜ必要か】idはオブジェクトが破棄されると再利用される。参照を
        # 持たないと、キャッシュに入れたテンプレートが解放された後、別の
        # テンプレートが同じidを取り、そのリサイズ結果として「別のミノの
        # 色見本」が返る。実際にテストで、光らせたLミノがどのテンプレートにも
        # 一致しないという誤った結果を生んだ。参照を持てばidは再利用されない。
        cached = (template, resized)
        _resized_template_cache[key] = cached
    return cached[1]


# 明るさ無視の再照合(match_cell_template参照)を試す条件: セル内の最大彩度
# (max-min)がこの値以上であること。
#
# 【なぜ省略しても結果が変わらないか】再照合の正規化(各画素から最小
# チャンネルを引く)では、正規化後の画素の最大成分がその画素の彩度そのものに
# なる。彩度が60未満の画素と、彩度が120以上のテンプレート本体画素との
# 距離は、ベクトルの大きさの差だけで必ず60以上になる(||a-b|| >= ||a||-||b||)。
# つまり最大彩度が60未満のセルは、再照合しても一致率がしきい値0.6に
# 届くことはなく、結果は常に「不一致」で変わらない。
#
# 【なぜ必要か】空マスや背景は必ず通常照合に失敗するので、無条件に
# 再照合すると盤面200セルのうち約190セルで7テンプレート分の計算を二重に
# 行うことになる。実機では盤面の読み取りが34ms→152msに悪化し、提案の
# 遅れとして利用者に体感された。空セルの背景は彩度20程度、通常ミノは
# 100以上なので、この値で両者を安全に分けられる。
_REMATCH_MIN_CHROMA = 60.0

# 一致判定に使う距離のしきい値の2乗。平方根を取らずに比較するために使う
# (単調増加なので、しきい値との大小関係は平方根を取っても変わらない)。
_PIXEL_MATCH_TOLERANCE_SQ = _PIXEL_MATCH_TOLERANCE**2


def _match_score(patch: np.ndarray, template: np.ndarray) -> float:
    """patchとtemplateのピクセル単位の一致率(0.0〜1.0)を返す。"""
    resized_template = _resized_template_f32(template, patch.shape[0], patch.shape[1])
    diff = patch.astype(np.float32) - resized_template
    squared_distance = (diff * diff).sum(axis=2)
    return float((squared_distance < _PIXEL_MATCH_TOLERANCE_SQ).mean())


def _match_score_ignoring_brightness(patch: np.ndarray, template: np.ndarray) -> float:
    """明るさの差を打ち消してから一致率を求める(match_cell_template参照)。

    各画素から「その画素の最小チャンネル」を引く。光エフェクトによる
    加算的な明るさの変化はこれで打ち消される。白灰色(全チャンネルが
    同程度)はすべて0になるため、ガベージや背景がミノに化けることはない。
    """
    resized_template = _resized_template_f32(template, patch.shape[0], patch.shape[1])
    patch_f = patch.astype(np.float32)
    normalized_patch = patch_f - patch_f.min(axis=2, keepdims=True)
    normalized_template = resized_template - resized_template.min(axis=2, keepdims=True)
    diff = normalized_patch - normalized_template
    squared_distance = (diff * diff).sum(axis=2)
    return float((squared_distance < _PIXEL_MATCH_TOLERANCE_SQ).mean())


def match_cell_template(
    patch: np.ndarray, templates: dict[str, np.ndarray], threshold: float = MATCH_THRESHOLD
) -> str | None:
    """セルの画像パッチを7色のテンプレートと比較し、最も近いミノ種類名を返す。

    最も一致率の高いテンプレートであっても、その一致率がthreshold未満
    (=どのテンプレートにも十分近くない)場合はNoneを返す(GARBAGEか空マスかは
    呼び出し側board_reader.pyが別途判定する)。

    threshold: 呼び出し元ごとに閾値を変えられるようにする。テンプレート画像
    自体は盤面セルから採取したものなので、HOLD/NEXT欄(ミニチュア表示で
    見た目がやや異なる)から呼ぶ場合は、呼び出し側(next_hold_reader.py)が
    別の閾値を渡すことを想定している。
    """
    best_name: str | None = None
    best_score = -1.0
    for name, template in templates.items():
        score = _match_score(patch, template)
        if score > best_score:
            best_score = score
            best_name = name

    if best_score >= threshold:
        return best_name

    # 【明るさの影響を除いてもう一度だけ試す】
    # 光エフェクトで明るくなったブロックは、基準色から全画素が同じ方向へ
    # ずれるため一致率が大きく落ちる。実機では、水色のIブロックが
    # RGB(1,153,212)なら一致率0.81なのに、光ってRGB(33,197,250)になると
    # 0.30まで落ちて「空マス」に化けていた(画素ごとの距離が約63で、
    # 許容距離60をわずかに超えるため全画素が不一致になる)。保存済みの
    # 生画像40枚では、実ブロックとみなせるセルの15.3%がこれで空に落ちて
    # いた。空いたマスへAIが配置を提案するため、既存ブロックと重なる
    # 「干渉」の直接原因になっていた。
    #
    # 光り方は概ね加算的なので、各画素から「その画素の最小チャンネル」を
    # 引くと明るさの差が打ち消される(例: 光ったIは(0,164,217)となり、
    # 通常のI(0,151,212)とほぼ一致する)。
    #
    # 【通常の判定に失敗したときだけ試す理由】
    # この正規化は明るさの情報を捨てるため、色相が近いIとJが互いに
    # 近づく。実測では、そのまま置き換えると19セルがI→Jへ変わった
    # (以前直したI/J取り違えの再発)。既に判定できているセルには触れず、
    # 落ちていたセルを拾うためだけに使う。
    # 彩度の低いセル(空マス・背景・ガベージ)は再照合しても一致し得ないので、
    # 計算せずに終了する(_REMATCH_MIN_CHROMA参照)。
    patch_f = patch.astype(np.float32)
    if float((patch_f.max(axis=2) - patch_f.min(axis=2)).max()) < _REMATCH_MIN_CHROMA:
        return None
    best_name = None
    best_score = -1.0
    for name, template in templates.items():
        score = _match_score_ignoring_brightness(patch, template)
        if score > best_score:
            best_score = score
            best_name = name
    if best_score < threshold:
        return None
    return best_name
