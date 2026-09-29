//! 継続パフェ(パフェの後に続けて取るパフェ)の成功率を計算する。
//!
//! 【2026-09-29・利用者の指示】Python版(src/education/pc_odds.py)は1通りに38秒かかり
//! 実用にならなかったため、Rustで作り直す(Javaのsfinderは配布物に同梱しない方針)。
//!
//! 考え方はPython版と同じ:
//! - 見えているミノ(操作ミノ・HOLD・NEXT)の後に来うる並びを、7種1巡の規則で
//!   「今の袋の残り(順不同)→次の袋(順不同)」と全部作る。
//! - 並びごとに「全部知っていればパフェを組めるか」を調べ、最初の1手ごとに
//!   組めた並びの数を数える(solution-finderのpercentと同じ考え方)。
//! - 到達判定はsrc/engine/srs_reach.lock_positionsと同じ(通常SRS・左右移動・左右回転・
//!   1マスずつの落下)。座標は22行(非表示2行+可視20行)。
//!
//! 入力(標準入力、1行ずつ):
//!   1: 盤面の占有マス "r,c;r,c;..."(22行座標。空なら空行)
//!   2: 見えているミノ順(先頭が操作ミノ) 例 "TILJSZ"
//!   3: HOLD("-"なら空)
//!   4: 今の袋の残り(見えている範囲の後に出るミノの種類。"-"なら次は新しい袋)
//!   5: この手番でHOLDできるか(1/0)
//!   6: 時間の上限(ミリ秒)
//!   7: 見えない部分の個数の上限
//! 出力:
//!   "ok <ミノ> <HOLDを使うか1/0> <成功数> <調べた数> <段数> <手数> r,c;r,c;r,c;r,c"(今の1手)
//!   "plan <k>" と、続くk行 "<ミノ> <HOLDを使うか1/0> <ソフトドロップが要るか1/0> r,c;..."
//!   (見えているミノで決まる手順。先頭が今の1手、各手は前の手までの消去後の座標)
//!   または "none"(狙えるパフェの段数が無い)

use std::collections::HashMap;
use std::hash::{BuildHasherDefault, Hasher};
use std::io::{self, Read};
use std::sync::Arc as Rc;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::time::{Duration, Instant};

const ROWS: i32 = 22;
const COLS: i32 = 10;
const BASE: i32 = 16; // 盤面のビットは22行座標の16〜21行(下6段)だけを持つ
const MAX_HEIGHT: i32 = 6;
const NONE: u8 = 7; // HOLDが空
const LETTERS: &[u8; 7] = b"IOTSZJL";

type Board = u64; // bit = (r - BASE) * 10 + c

// src/education/rules.py の _SHAPES と同じ(行, 列)。回転状態 0=出現, 1=右, 2=180度, 3=左
const SHAPES: [[[(i32, i32); 4]; 4]; 7] = [
    // I
    [
        [(1, 0), (1, 1), (1, 2), (1, 3)],
        [(0, 2), (1, 2), (2, 2), (3, 2)],
        [(2, 0), (2, 1), (2, 2), (2, 3)],
        [(0, 1), (1, 1), (2, 1), (3, 1)],
    ],
    // O
    [[(0, 1), (0, 2), (1, 1), (1, 2)]; 4],
    // T
    [
        [(0, 1), (1, 0), (1, 1), (1, 2)],
        [(0, 1), (1, 1), (1, 2), (2, 1)],
        [(1, 0), (1, 1), (1, 2), (2, 1)],
        [(0, 1), (1, 0), (1, 1), (2, 1)],
    ],
    // S
    [
        [(0, 1), (0, 2), (1, 0), (1, 1)],
        [(0, 1), (1, 1), (1, 2), (2, 2)],
        [(1, 1), (1, 2), (2, 0), (2, 1)],
        [(0, 0), (1, 0), (1, 1), (2, 1)],
    ],
    // Z
    [
        [(0, 0), (0, 1), (1, 1), (1, 2)],
        [(0, 2), (1, 1), (1, 2), (2, 1)],
        [(1, 0), (1, 1), (2, 1), (2, 2)],
        [(0, 1), (1, 0), (1, 1), (2, 0)],
    ],
    // J
    [
        [(0, 0), (1, 0), (1, 1), (1, 2)],
        [(0, 1), (0, 2), (1, 1), (2, 1)],
        [(1, 0), (1, 1), (1, 2), (2, 2)],
        [(0, 1), (1, 1), (2, 0), (2, 1)],
    ],
    // L
    [
        [(0, 2), (1, 0), (1, 1), (1, 2)],
        [(0, 1), (1, 1), (2, 1), (2, 2)],
        [(1, 0), (1, 1), (1, 2), (2, 0)],
        [(0, 0), (0, 1), (1, 1), (2, 1)],
    ],
];

// 通常SRSのキック(横, 縦)。縦は上向きが正。添字は [回転前][右回転なら1/左回転なら0]
fn kicks(piece: u8, from: usize, to: usize) -> [(i32, i32); 5] {
    let jlstz = |a: usize, b: usize| -> [(i32, i32); 5] {
        match (a, b) {
            (0, 1) => [(0, 0), (-1, 0), (-1, 1), (0, -2), (-1, -2)],
            (1, 0) => [(0, 0), (1, 0), (1, -1), (0, 2), (1, 2)],
            (1, 2) => [(0, 0), (1, 0), (1, -1), (0, 2), (1, 2)],
            (2, 1) => [(0, 0), (-1, 0), (-1, 1), (0, -2), (-1, -2)],
            (2, 3) => [(0, 0), (1, 0), (1, 1), (0, -2), (1, -2)],
            (3, 2) => [(0, 0), (-1, 0), (-1, -1), (0, 2), (-1, 2)],
            (3, 0) => [(0, 0), (-1, 0), (-1, -1), (0, 2), (-1, 2)],
            _ => [(0, 0), (1, 0), (1, 1), (0, -2), (1, -2)], // (0, 3)
        }
    };
    let i = |a: usize, b: usize| -> [(i32, i32); 5] {
        match (a, b) {
            (0, 1) => [(0, 0), (-2, 0), (1, 0), (-2, -1), (1, 2)],
            (1, 0) => [(0, 0), (2, 0), (-1, 0), (2, 1), (-1, -2)],
            (1, 2) => [(0, 0), (-1, 0), (2, 0), (-1, 2), (2, -1)],
            (2, 1) => [(0, 0), (1, 0), (-2, 0), (1, -2), (-2, 1)],
            (2, 3) => [(0, 0), (2, 0), (-1, 0), (2, 1), (-1, -2)],
            (3, 2) => [(0, 0), (-2, 0), (1, 0), (-2, -1), (1, 2)],
            (3, 0) => [(0, 0), (1, 0), (-2, 0), (1, -2), (-2, 1)],
            _ => [(0, 0), (-1, 0), (2, 0), (-1, 2), (2, -1)], // (0, 3)
        }
    };
    if piece == 0 { i(from, to) } else { jlstz(from, to) }
}

#[cfg(test)]
const SPAWN_ROW: i32 = 0;
#[cfg(test)]
const SPAWN_COL: i32 = 3;

#[cfg(test)]
fn occupied(board: Board, r: i32, c: i32) -> bool {
    r >= BASE && board >> ((r - BASE) * COLS + c) & 1 == 1
}

#[cfg(test)]
fn fits(board: Board, piece: u8, o: usize, row: i32, col: i32) -> bool {
    SHAPES[piece as usize][o].iter().all(|&(dr, dc)| {
        let (r, c) = (row + dr, col + dc);
        (0..ROWS).contains(&r) && (0..COLS).contains(&c) && !occupied(board, r, c)
    })
}

/// 出現位置からSRSで届き固定できる位置(下6段のビットマスク)。下6段より上に出る位置は含めない。
///
/// 動き(左右移動・左右回転と補正・1マスずつの落下)はsrc/engine/srs_reach.lock_positionsと同じ。
/// 速さのため、向きごと・行ごとに「置ける列」「届く列」をビットの並び(13列分)で持ち、
/// 行単位でまとめて広げる。盤面(下6段)より上は空なので、盤面のすぐ上の行では
/// すべての向き・列に届く(出現位置から回転・左右移動・落下で行ける)ものとして始める。
fn placements(board: Board, piece: u8) -> Vec<(u64, bool)> {
    // 行の添字 i = r - R0 + 2(r は22行座標の基準行)。基準列 a = c + 3(0..12)
    const R0: i32 = BASE - 4;
    const NR: usize = 16;
    const COLMASK: u16 = 0x1FFF;
    let p = piece as usize;
    let free = |r: i32| -> u16 {
        if r >= ROWS {
            0
        } else if r < BASE {
            0x3FF
        } else {
            (!(board >> ((r - BASE) * COLS)) & ROW_MASK) as u16
        }
    };
    let mut fit = [[0u16; NR]; 4];
    for o in 0..4 {
        for i in 0..NR {
            let r = i as i32 + R0 - 2;
            let mut m = COLMASK;
            for &(dr, dc) in &SHAPES[p][o] {
                m &= free(r + dr) << (3 - dc);
            }
            fit[o][i] = m & COLMASK;
        }
    }
    let shift = |x: u16, d: i32| -> u16 { if d >= 0 { (x << d) & COLMASK } else { x >> -d } };
    let mut reach = [[0u16; NR]; 4];
    let orients = if piece == 1 { 1 } else { 4 }; // Oは回転しても同じ
    for o in 0..orients {
        reach[o][2] = fit[o][2];
    }
    loop {
        let mut changed = false;
        for o in 0..orients {
            for i in 0..NR {
                let mut x = reach[o][i];
                if x == 0 {
                    continue;
                }
                loop {
                    let y = (x | x << 1 | x >> 1) & fit[o][i];
                    if y == x {
                        break;
                    }
                    x = y;
                }
                if x != reach[o][i] {
                    reach[o][i] = x;
                    changed = true;
                }
                if i + 1 < NR {
                    let down = x & fit[o][i + 1];
                    if down & !reach[o][i + 1] != 0 {
                        reach[o][i + 1] |= down;
                        changed = true;
                    }
                }
            }
        }
        if piece != 1 {
            for o in 0..4 {
                for i in 0..NR {
                    let src = reach[o][i];
                    if src == 0 {
                        continue;
                    }
                    for new in [(o + 3) % 4, (o + 1) % 4] {
                        let mut rem = src;
                        for (dx, dy) in kicks(piece, o, new) {
                            let i2 = i as i32 - dy;
                            if i2 < 0 || i2 >= NR as i32 {
                                continue; // この範囲の外へは補正で入らない(床より下・十分上)
                            }
                            let i2 = i2 as usize;
                            let ok = rem & shift(fit[new][i2], -dx); // 補正後の位置に置ける基準列
                            if ok == 0 {
                                continue;
                            }
                            let moved = shift(ok, dx);
                            if moved & !reach[new][i2] != 0 {
                                reach[new][i2] |= moved;
                                changed = true;
                            }
                            rem &= !ok; // 先に合った補正を使う
                            if rem == 0 {
                                break;
                            }
                        }
                    }
                }
            }
        }
        if !changed {
            break;
        }
    }
    // 真上から落とすだけ(上で回転・左右移動してハードドロップ)で届く固定位置
    let mut hard = [[0u16; NR]; 4];
    for o in 0..orients {
        let mut cols = fit[o][2];
        while cols != 0 {
            let a = cols.trailing_zeros() as usize;
            cols &= cols - 1;
            let mut i = 2;
            while i + 1 < NR && fit[o][i + 1] >> a & 1 == 1 {
                i += 1;
            }
            hard[o][i] |= 1 << a;
        }
    }
    let mut hard_masks: Vec<u64> = Vec::new();
    let mut out: Vec<u64> = Vec::new();
    for o in 0..orients {
        for i in 0..NR - 1 {
            let mut locked = reach[o][i] & !fit[o][i + 1];
            while locked != 0 {
                let a = locked.trailing_zeros() as i32;
                locked &= locked - 1;
                let (row, col) = (i as i32 + R0 - 2, a - 3);
                let mut mask = 0u64;
                let mut ok = true;
                for &(dr, dc) in &SHAPES[p][o] {
                    let r = row + dr;
                    if r < BASE {
                        ok = false;
                        break;
                    }
                    mask |= 1 << ((r - BASE) * COLS + col + dc);
                }
                if ok && !out.contains(&mask) {
                    out.push(mask);
                }
                if ok && hard[o][i] >> a & 1 == 1 && !hard_masks.contains(&mask) {
                    hard_masks.push(mask);
                }
            }
        }
    }
    // 真上から落とすだけで届く位置を先に(探索が先に見つける手順のソフトドロップが少なくなる)
    let mut result: Vec<(u64, bool)> = hard_masks.iter().map(|&m| (m, false)).collect();
    result.extend(out.into_iter().filter(|m| !hard_masks.contains(m)).map(|m| (m, true)));
    result
}

/// テスト用の参照実装: 出現位置から1マスずつ幅優先で調べる(srs_reach.lock_positionsと同じ動き)。
/// 出現位置からSRSで届き固定できる位置(下6段のビットマスク)。下6段より上に出る位置は含めない。
#[cfg(test)]
fn placements_ref(board: Board, piece: u8) -> Vec<u64> {
    const OFF: i32 = 4;
    const H: usize = (ROWS + 2 * OFF) as usize;
    const W: usize = (COLS + 2 * OFF) as usize;
    let mut out = Vec::new();
    if !fits(board, piece, 0, SPAWN_ROW, SPAWN_COL) {
        return out;
    }
    let mut seen = vec![false; 4 * H * W];
    let idx = |o: usize, r: i32, c: i32| (o * H + (r + OFF) as usize) * W + (c + OFF) as usize;
    let mut queue = vec![(0usize, SPAWN_ROW, SPAWN_COL)];
    seen[idx(0, SPAWN_ROW, SPAWN_COL)] = true;
    let mut head = 0;
    while head < queue.len() {
        let (o, row, col) = queue[head];
        head += 1;
        if !fits(board, piece, o, row + 1, col) {
            let mut mask = 0u64;
            let mut ok = true;
            for &(dr, dc) in &SHAPES[piece as usize][o] {
                let r = row + dr;
                if r < BASE {
                    ok = false;
                    break;
                }
                mask |= 1 << ((r - BASE) * COLS + col + dc);
            }
            if ok && !out.contains(&mask) {
                out.push(mask);
            }
        }
        for (nr, nc) in [(row, col - 1), (row, col + 1), (row + 1, col)] {
            if !seen[idx(o, nr, nc)] && fits(board, piece, o, nr, nc) {
                seen[idx(o, nr, nc)] = true;
                queue.push((o, nr, nc));
            }
        }
        if piece == 1 {
            continue; // Oは回転しても同じ
        }
        for new in [(o + 3) % 4, (o + 1) % 4] {
            for (dx, dy) in kicks(piece, o, new) {
                let (nr, nc) = (row - dy, col + dx);
                if fits(board, piece, new, nr, nc) {
                    if !seen[idx(new, nr, nc)] {
                        seen[idx(new, nr, nc)] = true;
                        queue.push((new, nr, nc));
                    }
                    break;
                }
            }
        }
    }
    out
}

const ROW_MASK: u64 = (1 << COLS) - 1;

/// 置いて揃った行を消した盤面と、消えた行数。
fn lock(board: Board, mask: u64) -> (Board, i32) {
    let placed = board | mask;
    let mut out = 0u64;
    let mut cleared = 0;
    // 下の段(k=5)から順に、揃っていない行だけを下から詰める
    let mut dst = 5i32;
    for k in (0..6i32).rev() {
        let row = placed >> (k * COLS) & ROW_MASK;
        if row == ROW_MASK {
            cleared += 1;
        } else {
            out |= row << (dst * COLS);
            dst -= 1;
        }
    }
    (if cleared == 0 { placed } else { out }, cleared)
}

const ALL60: u64 = (1u64 << 60) - 1;
// 各行の左端(列0)・右端(列9)のビット
const LEFT_COL: u64 = {
    let mut m = 0u64;
    let mut k = 0;
    while k < 6 {
        m |= 1 << (k * 10);
        k += 1;
    }
    m
};
const RIGHT_COL: u64 = LEFT_COL << 9;

/// パフェの高さ以下の空きマスが、どれも4の倍数の大きさの塊か(打ち切り用。pc_search._regions_okと同じ)。
/// 塊はビット演算の塗りつぶしで求める(1マスずつ調べるより速い)。
fn regions_ok(board: Board, height: i32) -> bool {
    let top = 6 - height;
    let area: u64 = if top <= 0 { ALL60 } else { ALL60 & !((1u64 << (top * COLS)) - 1) };
    let mut empty = area & !board;
    while empty != 0 {
        let mut fill = empty & empty.wrapping_neg(); // 一番下位のビットから塗り始める
        loop {
            let grown = (fill
                | (fill << 1 & !LEFT_COL)
                | (fill >> 1 & !RIGHT_COL)
                | fill << COLS
                | fill >> COLS)
                & empty;
            if grown == fill {
                break;
            }
            fill = grown;
        }
        if fill.count_ones() % 4 != 0 {
            return false;
        }
        empty &= !fill;
    }
    true
}

/// 整数のキー向けの速いハッシュ(FxHashと同じ計算。標準のSipHashは遅い)。
#[derive(Default, Clone, Copy)]
struct FxHasher(u64);

impl Hasher for FxHasher {
    fn finish(&self) -> u64 {
        self.0
    }
    fn write(&mut self, bytes: &[u8]) {
        for &b in bytes {
            self.write_u64(b as u64);
        }
    }
    fn write_u64(&mut self, v: u64) {
        self.0 = (self.0.rotate_left(5) ^ v).wrapping_mul(0x51_7c_c1_b7_27_22_0a_95);
    }
    fn write_u8(&mut self, v: u8) {
        self.write_u64(v as u64);
    }
}

type FastMap<K, V> = HashMap<K, V, BuildHasherDefault<FxHasher>>;

/// パフェの高さより上にはみ出さないか。
fn within(mask: u64, h: i32) -> bool {
    let top = 6 - h;
    top <= 0 || mask & ((1u64 << (top * COLS)) - 1) == 0
}

struct Solver {
    nodes: u64, // 調べた局面の数(時間切れの確認に使う)
    deadline: Instant,
    expired: bool, // 時間切れ(この後の失敗は確かめ切っていない)
    memo: FastMap<(u64, u64), bool>,
    moves: FastMap<(Board, u8), Rc<Vec<(u64, bool)>>>,
}

/// パフェの手順の1手(maskは前の手までの消去後の座標)。
#[derive(Clone, PartialEq, Eq, Hash)]
struct Step {
    piece: u8,
    use_hold: bool,
    mask: u64,
    soft: bool, // ソフトドロップが要る
}

/// ソフトドロップの回数の上限を付けないとき
const NO_LIMIT: u8 = 15;

impl Solver {
    fn new(deadline: Instant) -> Self {
        Solver { nodes: 0, deadline, expired: false, memo: FastMap::default(), moves: FastMap::default() }
    }

    fn placements(&mut self, board: Board, piece: u8) -> Rc<Vec<(u64, bool)>> {
        self.moves.entry((board, piece)).or_insert_with(|| Rc::new(placements(board, piece))).clone()
    }

    /// seq(先頭が操作ミノ)・HOLDで、残りleft個を置いてパフェにできるか(深さ優先。成功が1つ見つかれば止まる)。
    /// budget: ソフトドロップが要る手を使える回数(NO_LIMITなら制限なし)。
    fn solve(&mut self, b: Board, seq: &[u8], held: u8, h: i32, left: i32, budget: u8) -> bool {
        self.nodes += 1;
        if left == 0 {
            return b == 0;
        }
        if self.expired || self.nodes % 512 == 0 && Instant::now() > self.deadline {
            self.expired = true;
            return false;
        }
        let mut code = 0u64;
        for (i, &p) in seq.iter().take(left as usize + 1).enumerate() {
            code |= (p as u64 + 1) << (i * 4); // 使いうるのは先頭left+1個まで
        }
        let key = (b, code | (held as u64) << 48 | (h as u64) << 52 | (left as u64) << 56 | (budget as u64) << 60);
        if let Some(&got) = self.memo.get(&key) {
            return got;
        }
        let mut ok = false;
        'outer: for (piece, rest, next_held) in options(seq, held, true).into_iter().flatten() {
            for &(mask, soft) in self.placements(b, piece).iter() {
                if !within(mask, h) || soft && budget == 0 {
                    continue; // パフェの高さより上にはみ出す・ソフトドロップをもう使えない
                }
                let (nb, cleared) = lock(b, mask);
                let nh = h - cleared;
                if nb != 0 && !regions_ok(nb, nh) {
                    continue;
                }
                let nbudget = if budget == NO_LIMIT { NO_LIMIT } else { budget - soft as u8 };
                if self.solve(nb, rest, next_held, nh, left - 1, nbudget) {
                    ok = true;
                    break 'outer;
                }
            }
        }
        if !ok && self.expired {
            return false; // 調べ切っていない失敗は覚えない
        }
        self.memo.insert(key, ok);
        ok
    }

    /// solveで組めると分かった局面から、その手順を取り出す(同じ順に試して最初に組める手をたどる)。
    fn path(&mut self, b: Board, seq: &[u8], held: u8, h: i32, left: i32, budget: u8) -> Option<Vec<Step>> {
        if left == 0 {
            return if b == 0 { Some(Vec::new()) } else { None };
        }
        for (k, (piece, rest, next_held)) in options(seq, held, true).into_iter().flatten().enumerate() {
            for &(mask, soft) in self.placements(b, piece).iter() {
                if !within(mask, h) || soft && budget == 0 {
                    continue;
                }
                let (nb, cleared) = lock(b, mask);
                let nh = h - cleared;
                if nb != 0 && !regions_ok(nb, nh) {
                    continue;
                }
                let nbudget = if budget == NO_LIMIT { NO_LIMIT } else { budget - soft as u8 };
                if self.solve(nb, rest, next_held, nh, left - 1, nbudget) {
                    let mut out = vec![Step { piece, use_hold: k > 0, mask, soft }];
                    out.extend(self.path(nb, rest, next_held, nh, left - 1, nbudget)?);
                    return Some(out);
                }
            }
        }
        None
    }

    /// ソフトドロップが要る手の数が最も少ないパフェの手順(組めない・時間切れならNone)。
    fn min_soft_path(&mut self, b: Board, seq: &[u8], held: u8, h: i32, left: i32) -> Option<Vec<Step>> {
        for budget in 0..=(left.min(NO_LIMIT as i32 - 1) as u8) {
            if self.solve(b, seq, held, h, left, budget) {
                return self.path(b, seq, held, h, left, budget);
            }
            if self.expired {
                return None;
            }
        }
        None
    }
}

/// seqの先頭の手番で置けるミノと、残りの並び・次のHOLD(pc_odds._optionsと同じ)。最大2つ。
fn options(seq: &[u8], held: u8, can_hold: bool) -> [Option<(u8, &[u8], u8)>; 2] {
    if seq.is_empty() {
        return [None, None];
    }
    let first = Some((seq[0], &seq[1..], held));
    if !can_hold {
        return [first, None];
    }
    let second = if held != NONE {
        if held != seq[0] { Some((held, &seq[1..], seq[0])) } else { None } // 同じ種類を入れ替えても結果は同じ
    } else if seq.len() > 1 {
        Some((seq[1], &seq[2..], seq[0]))
    } else {
        None
    };
    [first, second]
}

fn permutations(items: &[u8], k: usize) -> Vec<Vec<u8>> {
    if k == 0 {
        return vec![vec![]];
    }
    let mut out = Vec::new();
    for (i, &x) in items.iter().enumerate() {
        let mut rest = items.to_vec();
        rest.remove(i);
        for mut tail in permutations(&rest, k - 1) {
            tail.insert(0, x);
            out.push(tail);
        }
    }
    out
}

/// 見えている範囲の後に来うる、count個のミノの並び(今の袋の残りpool→次の袋)。
fn unknown_sequences(pool: &[u8], count: usize) -> Vec<Vec<u8>> {
    let all: Vec<u8> = (0..7).collect();
    let pool: Vec<u8> = if pool.is_empty() { all } else { pool.to_vec() };
    if count == 0 {
        return vec![vec![]];
    }
    let head = count.min(pool.len());
    let firsts = permutations(&pool, head);
    if count == head {
        return firsts;
    }
    let rest = unknown_sequences(&[], count - head);
    let mut out = Vec::new();
    for a in &firsts {
        for b in &rest {
            out.push([a.as_slice(), b.as_slice()].concat());
        }
    }
    out
}

/// 成功率を数える候補: 見えているミノで決まる手順(1手目だけ、または読めている分の手順)と、
/// それを置いた後の状態。
#[derive(Clone)]
struct Cand {
    steps: Vec<Step>,
    board: Board,
    height: i32,
    pos: usize,               // 並び全体(見えている分+見えない分)で次に来るミノの位置
    held: u8,                 // 置いた後のHOLD(held_fromがあればそちらを使う)
    held_from: Option<usize>, // HOLDが見えないミノのとき、並び全体の何番目か
    left: i32,                // パフェまでに残りいくつ置くか
    soft: u32,                // 手順のうちソフトドロップが要る手の数
}

impl Cand {
    fn held_in(&self, full: &[u8]) -> u8 {
        self.held_from.map_or(self.held, |i| full[i])
    }
}

struct Found {
    plan: Vec<Step>, // 見えているミノで決まる手順(先頭が今の1手)
    success: u64,
    total: u64,
    height: i32,
    pieces: i32,
}

fn thread_count() -> usize {
    std::env::var("PC_ODDS_THREADS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or_else(|| std::thread::available_parallelism().map(|n| n.get()).unwrap_or(4).min(16))
        .max(1)
}

/// 候補cands(番号)を、並びtails[from..to]で調べて成功数を返す(並びと候補の組をスレッドで分ける)。
/// 時間切れになった組は数えず、Noneを返す。
fn evaluate(
    all: &[Cand],
    cands: &[usize],
    seq: &[u8],
    tails: &[Vec<u8>],
    from: usize,
    to: usize,
    solvers: &mut [Solver],
    deadline: Instant,
) -> Option<Vec<u64>> {
    let jobs: Vec<(usize, usize)> = cands.iter().enumerate().flat_map(|(k, _)| (from..to).map(move |t| (k, t))).collect();
    let next = AtomicUsize::new(0);
    let timed_out = AtomicBool::new(false);
    let parts: Vec<Vec<u64>> = std::thread::scope(|s| {
        let handles: Vec<_> = solvers
            .iter_mut()
            .map(|solver| {
                let (jobs, next, timed_out) = (&jobs, &next, &timed_out);
                s.spawn(move || {
                    let mut counts = vec![0u64; cands.len()];
                    loop {
                        let j = next.fetch_add(1, Ordering::Relaxed);
                        if j >= jobs.len() {
                            break;
                        }
                        if Instant::now() > deadline {
                            timed_out.store(true, Ordering::Relaxed);
                            break;
                        }
                        let (k, t) = jobs[j];
                        let c = &all[cands[k]];
                        let full: Vec<u8> = [seq, tails[t].as_slice()].concat();
                        if solver.solve(c.board, &full[c.pos..], c.held_in(&full), c.height, c.left, NO_LIMIT) {
                            counts[k] += 1;
                        }
                    }
                    if solver.expired {
                        timed_out.store(true, Ordering::Relaxed);
                    }
                    counts
                })
            })
            .collect();
        handles.into_iter().map(|h| h.join().unwrap()).collect()
    });
    if timed_out.load(Ordering::Relaxed) {
        return None;
    }
    let mut counts = vec![0u64; cands.len()];
    for part in parts {
        for (k, v) in part.into_iter().enumerate() {
            counts[k] += v;
        }
    }
    Some(counts)
}

/// 勝ち抜き方式(逐次半減法)で候補の成功数を数える。
/// 全候補を少ない並びで試し、成功数の多い上位半分を残して並びを倍に増やす、を繰り返す
/// (halve=falseなら全候補を残して並びだけ増やす)。戻り値は(候補ごとの成功数, 数え切った並びの数,
/// 最後まで残った候補)。
fn tournament(
    all: &[Cand],
    seq: &[u8],
    tails: &[Vec<u8>],
    solvers: &mut [Solver],
    deadline: Instant,
    halve: bool,
) -> (Vec<u64>, usize, Vec<usize>) {
    let n = tails.len();
    let mut cands: Vec<usize> = (0..all.len()).collect();
    let mut counts: Vec<u64> = vec![0; all.len()];
    let mut done = 0usize;
    // 最初は並び2通りから(候補が多いと、8通りでも短い時間の上限内に1回目が終わらず答えが出なかった)
    let mut batch = n.min(2);
    loop {
        let to = (done + batch).min(n);
        match evaluate(all, &cands, seq, tails, done, to, solvers, deadline) {
            Some(add) => {
                for (k, v) in add.into_iter().enumerate() {
                    counts[cands[k]] += v;
                }
                done = to;
            }
            None => break, // 時間切れ: ここまでに数え切った並びで答える
        }
        if done == n {
            break;
        }
        if halve && cands.len() > 1 {
            // 成功数の多い順(同数なら先に並んだ手=HOLDしない手)に並べ、上位半分を残す
            // (同数の候補をすべて残すと、全部100%のときに減らず全候補を数え切ってしまう)
            cands.sort_by_key(|&i| (std::cmp::Reverse(counts[i]), i));
            cands.truncate((cands.len() + 1) / 2);
        }
        batch = if cands.len() > 1 { done } else { (n - done).min(done.max(8)) }; // 並びを倍に
    }
    cands.sort_by_key(|&i| (std::cmp::Reverse(counts[i]), i));
    (counts, done, cands)
}

/// パフェの手順pathから、見えているミノ(先頭visible個とHOLD)だけで決まる頭の部分を取り出し、
/// firstに続けた候補にする。見えないミノを置く手の手前まで。
fn known_prefix(first: &Cand, path: &[Step], full: &[u8], visible: usize) -> Cand {
    let mut c = first.clone();
    let mut held = c.held_in(full);
    let mut held_known = c.held_from.is_none();
    let mut held_idx = c.held_from.unwrap_or(0);
    for st in path {
        let (known, np, nheld, nknown, nidx) = if !st.use_hold {
            (c.pos < visible, c.pos + 1, held, held_known, held_idx)
        } else if held != NONE {
            (held_known, c.pos + 1, full[c.pos], c.pos < visible, c.pos)
        } else {
            (c.pos + 1 < visible, c.pos + 2, full[c.pos], c.pos < visible, c.pos)
        };
        if !known {
            break;
        }
        let (nb, cleared) = lock(c.board, st.mask);
        c.board = nb;
        c.height -= cleared;
        c.left -= 1;
        c.soft += st.soft as u32;
        c.steps.push(st.clone());
        c.pos = np;
        held = nheld;
        held_known = nknown;
        held_idx = nidx;
    }
    c.held = held;
    c.held_from = if held_known { None } else { Some(held_idx) };
    c
}

/// 成功率がほぼ同じとみなす差(最初の1手だけ決めたときからこの範囲で下がる手順までガイドに出す)
const RATE_TOLERANCE: f64 = 0.03;

/// 成功率が一番高い最初の1手を選び、それに続く「見えているミノで決まる手順」を選ぶ。
/// 手順を先まで決めるほど、見えないミノに合わせて変えられる余地が減って成功率が下がるので、
/// 成功率が最初の1手だけのときとほぼ同じ範囲で、なるべく先まで(同じならソフトドロップが最少)。
/// 【2026-09-29・利用者の指示】継続パフェの組み方が複数あるときは、ソフトドロップが最も少ない
/// ものを選び、読めている手数だけガイドを表示する。
fn odds_for_height(
    board: Board,
    seq: &[u8],
    hold: u8,
    pool: &[u8],
    height: i32,
    pieces: i32,
    unknown: usize,
    can_hold: bool,
    started: Instant,
    deadline: Instant,
) -> Option<Found> {
    let mut firsts = Vec::new();
    let mut solver0 = Solver::new(deadline);
    for (k, (piece, rest, next_held)) in options(seq, hold, can_hold).into_iter().flatten().enumerate() {
        let consumed = seq.len() - rest.len();
        for &(mask, soft) in solver0.placements(board, piece).iter() {
            if !within(mask, height) {
                continue;
            }
            let (nb, cleared) = lock(board, mask);
            let nh = height - cleared;
            if nb != 0 && !regions_ok(nb, nh) {
                continue;
            }
            firsts.push(Cand {
                steps: vec![Step { piece, use_hold: k > 0, mask, soft }], // 2つ目の選択肢はHOLDを使う手
                board: nb,
                height: nh,
                pos: consumed,
                held: next_held,
                held_from: None,
                left: pieces - 1,
                soft: soft as u32,
            });
        }
    }
    if firsts.is_empty() {
        return None;
    }
    let mut tails = unknown_sequences(pool, unknown);
    // 並びを乱れた順に(途中で打ち切っても抽選と同じになる)。xorshiftで決まった順に混ぜる
    let mut state = 0x9E3779B97F4A7C15u64;
    for i in (1..tails.len()).rev() {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        tails.swap(i, (state % (i as u64 + 1)) as usize);
    }
    // 1段目(時間の半分まで): 成功率が一番高い最初の1手
    let half = started + (deadline - started) / 2;
    let mut solvers: Vec<Solver> = (0..thread_count()).map(|_| Solver::new(half)).collect();
    let (counts, done, order) = tournament(&firsts, seq, &tails, &mut solvers, half, true);
    // 覚えた局面(数十万件)を片付けると0.5秒ほどかかるため、片付けずに終える(プロセスの終了で解放される)
    std::mem::forget(solvers);
    std::mem::forget(solver0);
    if done == 0 {
        return None;
    }
    let first = &firsts[order[0]];
    let mut found = Found { plan: first.steps.clone(), success: counts[order[0]], total: done as u64, height, pieces };
    if counts[order[0]] == 0 {
        return Some(found);
    }

    // 2段目(残りの時間): いくつかの並びでソフトドロップが最少のパフェ手順を求め、その頭の部分
    // (見えているミノで決まる手順)を候補にする
    let mut solvers: Vec<Solver> = (0..thread_count()).map(|_| Solver::new(deadline)).collect();
    let sample: Vec<&Vec<u8>> = tails.iter().take(32).collect();
    let next = AtomicUsize::new(0);
    let paths: Vec<Vec<Cand>> = std::thread::scope(|s| {
        let handles: Vec<_> = solvers
            .iter_mut()
            .map(|solver| {
                let (sample, next) = (&sample, &next);
                s.spawn(move || {
                    let mut out = Vec::new();
                    loop {
                        let j = next.fetch_add(1, Ordering::Relaxed);
                        if j >= sample.len() || Instant::now() > deadline {
                            break;
                        }
                        let full: Vec<u8> = [seq, sample[j].as_slice()].concat();
                        if let Some(path) =
                            solver.min_soft_path(first.board, &full[first.pos..], first.held_in(&full), first.height, first.left)
                        {
                            // 見えているミノで決まる手順と、その途中まで(先の手ほど見えないミノに
                            // 合わせて変えられる余地があり、決めると成功率が下がることがある)
                            let whole = known_prefix(first, &path, &full, seq.len());
                            for len in 1..whole.steps.len() {
                                out.push(known_prefix(first, &path[..len], &full, seq.len()));
                            }
                        }
                    }
                    out
                })
            })
            .collect();
        handles.into_iter().map(|h| h.join().unwrap()).collect()
    });
    let mut prefixes: Vec<Cand> = Vec::new();
    for c in paths.into_iter().flatten() {
        if !prefixes.iter().any(|p| p.steps == c.steps) {
            prefixes.push(c);
        }
    }
    if prefixes.is_empty() {
        std::mem::forget(solvers);
        return Some(found);
    }
    // 候補の手順の成功数を数え(全候補を残して並びを増やす)、最初の1手だけ決めたときと成功率が
    // ほぼ同じ手順のうち、決める手数が最も長いもの(同じならソフトドロップが最少)を選ぶ
    let (pc, pdone, _order) = tournament(&prefixes, seq, &tails, &mut solvers, deadline, false);
    std::mem::forget(solvers);
    if pdone == 0 {
        return Some(found);
    }
    let first_rate = found.success as f64 / found.total as f64;
    let Some(pick) = (0..prefixes.len())
        .filter(|&i| pc[i] as f64 / pdone as f64 >= first_rate - RATE_TOLERANCE)
        .min_by_key(|&i| (std::cmp::Reverse(prefixes[i].steps.len()), prefixes[i].soft, std::cmp::Reverse(pc[i]), i))
    else {
        return Some(found); // どの手順も成功率が下がる: 最初の1手だけ
    };
    found.plan = prefixes[pick].steps.clone();
    found.success = pc[pick];
    found.total = pdone as u64;
    Some(found)
}

fn cells_text(mask: u64) -> String {
    let mut cells = Vec::new();
    for bit in 0..60 {
        if mask >> bit & 1 == 1 {
            cells.push(format!("{},{}", BASE + bit / COLS, bit % COLS));
        }
    }
    cells.join(";")
}

fn piece_code(ch: u8) -> Option<u8> {
    LETTERS.iter().position(|&l| l == ch).map(|p| p as u8)
}

fn main() {
    let mut input = String::new();
    io::stdin().read_to_string(&mut input).unwrap();
    let lines: Vec<&str> = input.lines().map(|l| l.trim()).collect();
    let get = |i: usize| lines.get(i).copied().unwrap_or("");
    let mut board: Board = 0;
    for cell in get(0).split(';').filter(|s| !s.is_empty()) {
        let mut it = cell.split(',').map(|v| v.trim().parse::<i32>().unwrap());
        let (r, c) = (it.next().unwrap(), it.next().unwrap());
        if r < BASE {
            println!("none"); // 6段より高い盤面は扱わない
            return;
        }
        board |= 1 << ((r - BASE) * COLS + c);
    }
    let seq: Vec<u8> = get(1).bytes().filter_map(piece_code).collect();
    let hold = get(2).bytes().next().and_then(piece_code).unwrap_or(NONE);
    let pool: Vec<u8> = get(3).bytes().filter_map(piece_code).collect();
    let can_hold = get(4) != "0";
    let limit_ms: u64 = get(5).parse().unwrap_or(3000);
    let max_unknown: usize = get(6).parse().unwrap_or(4);
    if seq.is_empty() {
        println!("none");
        return;
    }
    let started = Instant::now();
    let deadline = started + Duration::from_millis(limit_ms);
    let filled = board.count_ones() as i32;
    let mut stack_height = 0;
    for k in 0..6 {
        if board >> (k * COLS) & ROW_MASK != 0 {
            stack_height = 6 - k;
            break;
        }
    }
    let mut best: Option<Found> = None;
    for height in stack_height.max(1)..=MAX_HEIGHT {
        let empty = height * COLS - filled;
        if empty <= 0 || empty % 4 != 0 {
            continue;
        }
        let pieces = empty / 4;
        // ミノの列から引く数: HOLDにミノがあれば置く数と同じ、空なら最後にHOLDに1個残る分だけ多い
        let need = if hold != NONE { pieces } else { pieces + 1 } as usize;
        let unknown = need.saturating_sub(seq.len());
        if unknown > max_unknown {
            break;
        }
        if let Some(found) = odds_for_height(board, &seq, hold, &pool, height, pieces, unknown, can_hold, started, deadline) {
            if found.success == 0 {
                continue; // この段数では組めない: 次の段数を調べる
            }
            let better = match &best {
                None => true,
                Some(b) => found.success * b.total > b.success * found.total,
            };
            if better {
                best = Some(found);
            }
        }
        if let Some(b) = &best {
            if b.success == b.total {
                break;
            }
        }
    }
    match best {
        None => println!("none"),
        Some(f) => {
            let first = &f.plan[0];
            println!(
                "ok {} {} {} {} {} {} {}",
                LETTERS[first.piece as usize] as char,
                first.use_hold as u8,
                f.success,
                f.total,
                f.height,
                f.pieces,
                cells_text(first.mask)
            );
            // 見えているミノで決まる手順(各手は前の手までの消去後の座標)
            println!("plan {}", f.plan.len());
            for st in &f.plan {
                println!("{} {} {} {}", LETTERS[st.piece as usize] as char, st.use_hold as u8, st.soft as u8, cells_text(st.mask));
            }
        }
    }
    // 出力したらすぐ終える(覚えた局面の片付けを待たない)
    use std::io::Write;
    let _ = io::stdout().flush();
    std::process::exit(0);
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 行ごとのビット演算版と、出現位置から1マスずつ調べる参照実装が一致するか(乱数の盤面で)。
    #[test]
    fn fast_placements_match_reference() {
        let mut state = 12345u64;
        let mut rnd = || {
            state ^= state << 13;
            state ^= state >> 7;
            state ^= state << 17;
            state
        };
        for _ in 0..3000 {
            let height = (rnd() % 6 + 1) as i32;
            let density = rnd() % 70 + 10;
            let mut board: Board = 0;
            for k in (6 - height)..6 {
                for c in 0..COLS {
                    if rnd() % 100 < density {
                        board |= 1 << (k * COLS + c);
                    }
                }
            }
            for piece in 0..7u8 {
                let mut a: Vec<u64> = placements(board, piece).into_iter().map(|(m, _soft)| m).collect();
                let mut b = placements_ref(board, piece);
                a.sort();
                b.sort();
                assert_eq!(a, b, "board={:#x} piece={}", board, piece);
            }
        }
    }
}
