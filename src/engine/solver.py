"""最善手探索（ビームサーチ）

現在ピース・ホールド中のピース・ネクスト数手を踏まえ、
「今このピースをどこにどう置くべきか（ホールドすべきか否かを含む）」を決定する。

ホールドの分岐は最初の1手でのみ考慮する（テトリスのルール上、
1手につきホールド操作は1回までであり、2手目以降も毎回分岐させると
探索空間が指数的に増えるため）。2手目以降は各深さで得られたネクストピースを
そのまま置く前提でビームサーチを行う。
"""

from __future__ import annotations

from dataclasses import dataclass

from .board_state import BoardState
from .evaluator import DEFAULT_WEIGHTS, EvalWeights, evaluate_board
from .move_generator import Move, enumerate_moves

DEFAULT_BEAM_WIDTH = 20
DEFAULT_SEARCH_DEPTH = 5  # 現在ピース+ネクスト4手先まで（人間支援用途のため5手に設定）

# ホールドは実際の操作としてはタダではない（ユーザーが余分なキー操作をする必要がある）
# のに、評価関数上は何のコストも課していなかったため、盤面評価がわずかでも良くなる
# だけで毎手のようにホールドを提案してしまっていた（実プレイでは不自然な頻度）。
# ホールドを選ぶにはこの値以上スコアが上回っている必要がある、という軽いハードルを
# 設けることで、僅差なら素直に今の手駒を使う手を優先させる。
HOLD_PENALTY = 3.0


@dataclass
class BestMove:
    use_hold: bool
    piece: str
    rotation: int
    origin_col: int
    origin_row: int
    landing_cells: list[tuple[int, int]]
    score: float


@dataclass
class _SearchNode:
    board: BoardState
    queue: list[str]
    acc_score: float
    first_move: BestMove


def _expand_first_move(
    board: BoardState,
    piece: str,
    use_hold: bool,
    remaining_queue: list[str],
    weights: EvalWeights,
) -> list[_SearchNode]:
    nodes = []
    for move in enumerate_moves(board, piece):
        score = evaluate_board(move.resulting_board, move.lines_cleared, weights, move.eroded_cells)
        best_move = BestMove(
            use_hold=use_hold,
            piece=piece,
            rotation=move.rotation,
            origin_col=move.origin_col,
            origin_row=move.origin_row,
            landing_cells=move.landing_cells,
            score=score,
        )
        nodes.append(
            _SearchNode(
                board=move.resulting_board,
                queue=remaining_queue,
                acc_score=score,
                first_move=best_move,
            )
        )
    return nodes


def find_best_move(
    board: BoardState,
    current_piece: str,
    hold_piece: str | None,
    next_queue: list[str],
    beam_width: int = DEFAULT_BEAM_WIDTH,
    search_depth: int = DEFAULT_SEARCH_DEPTH,
    weights: EvalWeights = DEFAULT_WEIGHTS,
    allow_hold: bool = True,
) -> BestMove | None:
    """現状の最善手を返す。置く場所が一つもない（ゲームオーバー相当）場合はNone。

    allow_hold=Falseの場合、ホールド選択肢自体を候補から除外する。
    テトリスのルール上1手につきホールドは1回までなので、直前にホールドした
    ばかりの状況では、呼び出し側からFalseを渡すことで「実行できないのに
    また同じホールド提案が出る」という不自然な提案を避けられる。
    """

    candidates: list[_SearchNode] = []

    # 選択肢A: ホールドしない
    candidates += _expand_first_move(board, current_piece, False, list(next_queue), weights)

    # 選択肢B: ホールドする
    if allow_hold:
        if hold_piece is not None:
            piece_to_place = hold_piece
            queue_after_hold = list(next_queue)
            hold_candidates = _expand_first_move(board, piece_to_place, True, queue_after_hold, weights)
        elif next_queue:
            piece_to_place = next_queue[0]
            queue_after_hold = list(next_queue[1:])
            hold_candidates = _expand_first_move(board, piece_to_place, True, queue_after_hold, weights)
        else:
            hold_candidates = []
        for node in hold_candidates:
            node.acc_score -= HOLD_PENALTY
            node.first_move.score -= HOLD_PENALTY
        candidates += hold_candidates

    if not candidates:
        return None

    beam = sorted(candidates, key=lambda n: n.acc_score, reverse=True)[:beam_width]

    for _ in range(search_depth - 1):
        next_beam: list[_SearchNode] = []
        for node in beam:
            if not node.queue:
                # ネクスト情報が尽きたら、このノードはこれ以上深掘りできない
                next_beam.append(node)
                continue
            piece = node.queue[0]
            rest_queue = node.queue[1:]
            for move in enumerate_moves(node.board, piece):
                score = evaluate_board(move.resulting_board, move.lines_cleared, weights, move.eroded_cells)
                next_beam.append(
                    _SearchNode(
                        board=move.resulting_board,
                        queue=rest_queue,
                        acc_score=node.acc_score + score,
                        first_move=node.first_move,
                    )
                )
        if not next_beam:
            break
        beam = sorted(next_beam, key=lambda n: n.acc_score, reverse=True)[:beam_width]

    best_node = max(beam, key=lambda n: n.acc_score)
    return best_node.first_move
