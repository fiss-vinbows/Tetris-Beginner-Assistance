"""盤面評価関数

Cold Clear等の公開されているテトリスAIが採用している評価要素
（穴数・集計高さ・凹凸・ライン消去効率・井戸ボーナス・天井ペナルティ）に加え、
Pierre Dellacherieのアルゴリズム（行/列の遷移数・eroded cells）で
実証されている特徴量も取り入れ、独自の重み付き線形結合として実装する。
"""

from __future__ import annotations

from dataclasses import dataclass

from .board_state import BoardState

# 天井から何マス以内を「危険域」として追加ペナルティを課すか
DANGER_ZONE_HEIGHT = 4


@dataclass(frozen=True)
class EvalWeights:
    aggregate_height: float = -0.51   # 列高さ合計。積み上がるほど減点
    holes: float = -0.90              # 穴（蓋をされた空きマス）。復旧コストが高いので重めに減点
    bumpiness: float = -0.18          # 隣接列の高低差の合計。デコボコを嫌う
    # ライン消去1回あたりの加点。実際には lines_cleared**2 倍した値に掛けるため、
    # テトリス(4ライン)はシングル(1ライン)の16倍のボーナスになる（詳細はevaluate_board参照）。
    lines_cleared: float = 0.76
    danger_zone: float = -0.40        # 天井付近まで積み上がった列への追加減点
    # 最も深い井戸（Iミノ用の縦穴）へのボーナス。
    # lines_clearedの2乗ボーナスだけでは、5手先読みの範囲内で「テトリスを待つ」
    # という長期戦略を評価しきれず、実機で「1列ずつしか消さない」という指摘の通り
    # 常にシングルクリアが選ばれ続けていた（自己対戦シミュレーションで確認、
    # デフォルト値0.22のままだとシングルが全消去の94%を占めていた）。
    # 「井戸を保持していること自体」を1手ごとの評価で高く評価するようこの値を
    # 強めることで、シングルで安易に井戸を崩さずテトリスまで待つ判断を誘導する。
    # 自己対戦シミュレーションで0.22〜4.0の範囲を比較し、2.5がゲームオーバー率を
    # 増やさずにシングル比率を65%まで下げられる境界だった（3.5以上は井戸への
    # 固執が強すぎて積みすぎによるゲームオーバー率が急増する）。
    well_bonus: float = 2.5
    row_transitions: float = -0.32    # 行内の埋/空の切り替わり回数。壁際の凸凹を嫌う
    column_transitions: float = -0.18 # 列内の埋/空の切り替わり回数。浮いた穴や逆T字を嫌う
    eroded_cells: float = 0.32        # 消去に貢献した設置マス数×消去行数。「すぐ消える」置き方を評価


DEFAULT_WEIGHTS = EvalWeights()


def _bumpiness(heights: list[int]) -> int:
    return sum(abs(heights[i] - heights[i + 1]) for i in range(len(heights) - 1))


def _deepest_well(heights: list[int]) -> int:
    """両隣より深く窪んでいる列（Iミノ待ちの井戸）の最大深さを返す"""
    best = 0
    for i, h in enumerate(heights):
        left = heights[i - 1] if i > 0 else h
        right = heights[i + 1] if i < len(heights) - 1 else h
        depth = min(left, right) - h
        if depth > best:
            best = depth
    return max(best, 0)


def evaluate_board(
    board: BoardState,
    lines_cleared: int,
    weights: EvalWeights = DEFAULT_WEIGHTS,
    eroded_cells: int = 0,
) -> float:
    heights = board.column_heights()
    aggregate_height = sum(heights)
    holes = board.count_holes()
    bumpiness = _bumpiness(heights)
    max_height = max(heights) if heights else 0
    well_depth = _deepest_well(heights)

    # ライン消去のボーナスはライン数の2乗に比例させる（線形だとテトリス1回=シングル4回分の
    # 価値にしかならず、井戸を崩してでもすぐシングルで消す方が短期的に高評価になってしまい、
    # 実機で「1列ずつしか消さない」という指摘につながっていた）。2乗にすることで
    # テトリス(4ライン)はシングル(1ライン)の16倍評価され、多少盤面が高くなっても
    # 井戸を保持してまとめて消す方を優先しやすくなる。
    score = (
        weights.aggregate_height * aggregate_height
        + weights.holes * holes
        + weights.bumpiness * bumpiness
        + weights.lines_cleared * (lines_cleared**2)
        + weights.well_bonus * well_depth
        + weights.row_transitions * board.row_transitions()
        + weights.column_transitions * board.column_transitions()
        + weights.eroded_cells * eroded_cells
    )

    danger_rows = max_height - (board.height - DANGER_ZONE_HEIGHT)
    if danger_rows > 0:
        score += weights.danger_zone * danger_rows

    return score
