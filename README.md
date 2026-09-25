# TBA (Tetris Beginner Assistance)

ぷよぷよテトリスの画面をリアルタイムで認識し、最善手をオーバーレイ表示する支援AI。

## 目的・構想

初心者のためのテトリスの最善手を提示するソフト。ネクスト・ホールド・現状の
地形を鑑みた最善手をドットで表示し、人間が操作する。Switchなどのゲーム機から
キャプチャボードでPC上にテトリスの画面を表示するため、正確かつ素早い画像認識が
求められる。最善手は、相手からの妨害で段がせりあがる場合を除き表示を切り替えず、
切り替えるタイミングはネクスト・ネクネク(2手先)・ホールドにあるテトリミノが
変化した時とする。思考AIはCold Clear 2を用いる。

## 構成

- `src/capture/` — 画面キャプチャ・キャリブレーション
- `src/vision/` — 盤面・ホールド・ネクスト欄の画像認識
- `src/engine/` — 盤面表現、および思考エンジン
  - `board_state.py`, `piece_defs.py`, `move_generator.py`, `evaluator.py`, `solver.py` — 自前のビームサーチ思考ルーチン（現在はテスト・自己対戦検証専用。実際の支援モードでは使っていない）
  - `cold_clear_client.py` — 実際の思考エンジンである [Cold Clear 2](https://github.com/MinusKelvin/cold-clear-2) をサブプロセスとして呼び出すクライアント
- `src/overlay/` — 最善手のオーバーレイ描画
- `src/education/` — シミュレーター（練習画面）と無限中あけREN。画像認識を使わず自前の盤面で練習する
- `src/app.py` — アプリ本体（メインウィンドウ、認識→思考ループ）
- `tests/` — 単体テスト（自前思考ルーチン、盤面認識、`app.py`のミノ検出・状態遷移ロジック、Cold Clear 2座標変換・統合、オーバーレイ座標計算など）
- `tools/` — 自己対戦シミュレーター、デバッグ用スクリプト

## セットアップ

### 1. Python環境

```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

### 2. Cold Clear 2 のビルド（初回のみ）

Rustツールチェインが必要。未インストールなら:

```bash
winget install --id Rustlang.Rustup -e --source winget
```

インストール後、新しいターミナルを開くか `$env:Path += ";$env:USERPROFILE\.cargo\bin"` でPATHを通してから:

```bash
git clone https://github.com/MinusKelvin/cold-clear-2.git external/cold-clear-2
cd external/cold-clear-2
cargo build --release
```

`external/cold-clear-2/target/release/cold-clear-2.exe` が生成されていればOK。`src/engine/cold_clear_client.py`の`COLD_CLEAR_EXE`がこのパスを参照している。

### 3. キャリブレーション

`start.bat`を実行し、「キャリブレーションを実行」から盤面・ホールド・ネクスト欄の位置を指定する（同じウィンドウ配置・解像度である限り再利用できる）。

## 起動

### 実行ファイル形式(配布物)

`dist/TBA/` に揃えた一式(`TBA.exe`、`_internal/`、`cold-clear-2.exe`、`config/`)を
任意のフォルダに置き、`TBA.exe` をダブルクリックする。Python や Rust の
インストールは不要。設定(`config/calibration.json`)・デバッグログ・録画は
`TBA.exe` と同じフォルダに作られる。

配布物の作り方(開発環境で):

```bash
venv\Scripts\pip install pyinstaller
venv\Scripts\python.exe tools\build_exe.py
```

配布物では、実機の画面キャプチャを含むデバッグログ・画面録画機能(`src/paths.py`の
`is_frozen()`で判定)を無効化しており、メイン画面にチェックボックス自体が
表示されない。ソースから起動した場合(開発時)はこれまで通り利用できる。

起動アイコン(`assets/icon.ico`、`TBA.spec`の`icon`から参照)を作り直す場合:

```bash
venv\Scripts\python.exe tools\generate_icon.py
```

### ソースから起動(開発時)

```bash
start.bat
```

`start.bat`は`pythonw.exe`でアプリを起動する（アプリを閉じてもコンソールが
残らないようにするため）。`pythonw`環境では`sys.stdout`/`sys.stderr`が`None`
になるため、`src/app.py`冒頭でその場合はダミーの書き込み先（`os.devnull`）に
差し替えている。

コードを修正した場合、支援モードの開始・終了だけでなく**アプリ本体（メイン
ウィンドウ）ごと再起動しないと変更が反映されない**点に注意（Pythonは一度
importしたモジュールをメモリに保持し続けるため）。

## シミュレーター（練習画面）

メインウィンドウの「シミュレーターを開く」から起動する。画像認識・キャプチャを使わず、
自前の盤面で積み方を練習する（自動落下なし、ハードドロップでのみ固定）。

- 操作は通常SRS（180度回転なし）。キーボード・コントローラーの割り当てを画面から変更できる
- 一手戻す、同一配列／別配列でリセット、盤面エディタ（ツモ・HOLDを保ったまま盤面だけ変更も可）、
  1〜3巡目のツモ順設定（ドラッグで並べ替え）、スクリーンショット保存
- 推奨手はNEXT5までの情報だけで出す。HOLDの下の候補欄から切り替えられる（F2）
  - 開幕テンプレ（迷走砲・はちみつ砲・山岳積み2号・開幕パフェ積み）、DPC
  - 見えているミノで取れるパフェ（テトリスを含むパフェを優先）。パフェ後に
    「→開幕へ／→DPCへ／→袋ずれ(ループ崩れ)」を表示
  - 6-3積み（左から7列目を井戸にしてテトリスで消す）、ColdClear2
- 難度はソフトドロップの回数で ◎（0回）○（1回）△（2回以上）
- 提示・優先（テンプレ／AI）・推奨配置・操作手順はトグルスイッチで切り替える

## 無限中あけREN

メインウィンドウの「無限中あけRENを開く」から起動する（シミュレーターとは別のモード）。
左右6列が常に埋まった（灰色）中央4列で4列RENを練習する。参考:
[テトリス堂「無限4列RENゲーム」](https://shiwehi.com/tetris/game/i4lr.php)

- 開始時は中央4列の最下段に3マスのタネがある（初手から置けるものだけ）
- 置いた手でラインが消えなければRENが途切れて終了
- AI解析（トグルで表示／非表示）: 見えているミノ（7種1巡から確定するミノを含む）で
  RENが最も長く続く手順を示す

## デバッグ機能

メイン画面の「認識結果をログに出力する」にチェックを入れて支援モードを開始すると:

- `debug_logs/debug_log_YYYYMMDD_HHMMSS.txt` — 新しいミノがスポーンするたび、または提案が更新されるたびに、認識した盤面・最善手をテキストで記録。支援モードを開始するたびに新しいファイルになり、前回までの記録は上書きされない。
- `debug_frames/` — 実際にキャリブレーション座標で切り出した盤面・ホールド・ネクストの生画像（直近1回分を上書き）
- `debug_frames_history/` — 提案が実際に変化した瞬間ごとに、タイムスタンプ・盤面テキスト付きでローテーション保存する生画像（直近`FRAME_HISTORY_SIZE`件分）。「今おかしい」と気づいた時には`debug_frames/`が既に上書きされていることがあるため、こちらで過去の瞬間を遡って確認できる。
- `crash_log.txt` — 支援モードのワーカースレッドで未処理例外が発生した場合に、詳細なトレースバックを記録する（`pythonw`環境ではコンソールにトレースバックが表示されないため）。

「最善手がおかしい」と感じた時は、テキストログのパターンだけで判断せず、`debug_frames_history/`の生画像を直接目視確認すること（画像認識のズレなのか、思考ロジックの問題なのか、あるいは別の要因かを切り分けやすい）。

### 画面録画機能（暫定）

不具合報告のたびに別の画面録画ソフトで撮り直す手間を省くため、メイン画面の「支援モード中の画面を録画する」にチェックを入れると、支援モード開始から終了まで、キャリブレーション済みの範囲（盤面+HOLD+NEXT欄）を`debug_logs/debug_capture_YYYYMMDD_HHMMSS.mp4`に録画し続ける。ログ機能と同様、支援モードを開始するたびに新しいファイルになり上書きされない（テキストログを同時に有効にした場合、両者は同じ日時のファイル名になり突き合わせやすい）。実画面をキャプチャするため、オーバーレイの提案（色ドット）も外部の画面録画ソフトで撮った場合と同様に映り込む。フレームレートはファイルサイズ・エンコード負荷を抑えるため15fps程度に間引いている（`VIDEO_RECORD_FPS`）。各フレームには`datetime.now().isoformat()`がタイムスタンプとして焼き込まれており、テキストログ・`debug_frames_history/`の記録と実時刻で直接突き合わせられる。

## テスト

```bash
venv\Scripts\python -m unittest discover -s tests -v
```

自前思考ルーチンの単体テスト（穴回避、井戸埋め、ライン消去優先など）、GARBAGE行判定の単体テストに加え、Cold Clear 2との座標変換・統合テスト（`tests/test_cold_clear_client.py`）を含む。統合テスト部分は`external/cold-clear-2/target/release/cold-clear-2.exe`が存在する環境でのみ実行され、未ビルドなら自動的にスキップされる。

## 自己対戦シミュレーター（`tools/`）

- `self_play_sim.py` — 自前solver.pyでの自己対戦。評価関数のチューニング検証用。
- `cold_clear_self_play.py` — Cold Clear 2での自己対戦。実際に使っているエンジンの品質（穴の発生率、ライン消去の内訳、パーフェクトクリアの発生）を検証する。`--garbage-chance`で1手ごとにGARBAGE行がせり上がる確率を指定でき、対戦中の攻撃を受けながらの安定性（ゲームオーバー率、クラッシュの有無）を検証できる。

```bash
venv\Scripts\python tools/cold_clear_self_play.py --seeds 5 --max-moves 100 --think-seconds 0.3 --garbage-chance 0.1
```

`think_seconds`を短くすると実運用に近い速度になるが手の質は落ち、長くするとパーフェクトクリアのような複数手先の計画も見つけやすくなる（実際の支援モードは、ユーザーがそのミノを操作している時間をそのまま思考時間として使う段階的方式のため、この引数と単純比較はできない）。

## 速度計測ツール（`tools/`）

「提案が遅い」と感じた際に、どこにボトルネックがあるかを切り分けるための計測スクリプト。

- `bench_latency.py` — Cold Clear 2プロセスとの通信（start_thinking/poll_suggestion）1回あたりのレイテンシを計測。
- `bench_recognize.py` — `recognize()`内部（画面キャプチャ・盤面読み取り・HOLD/NEXT読み取り）の時間内訳を計測。実際のキャリブレーション座標を使うため、`config/calibration.json`が必要。
- `bench_capture_strategy.py` — 画面キャプチャを1回にまとめる方式と、盤面/HOLD/NEXTの3回に分ける方式を比較する。

実測では通信は1〜3ms程度でボトルネックにならず、`recognize()`側（特にmssの画面キャプチャが約18〜20ms）が支配的だった。キャプチャ回数を減らす方向（現行の1回にまとめる方式）が分割方式より高速であることを確認済み。GPUベースの高速キャプチャ（dxcam等のDesktop Duplication API）はメディアン1.5ms程度と大幅に速い一方、静止フレームで頻繁に`None`を返す不安定さと、全画面排他モードのゲームで動作しないことがある既知の制約があるため、現時点では採用を見送っている。

## ライセンス

TBA本体は[MIT License](LICENSE)。

思考エンジンである[Cold Clear 2](https://github.com/MinusKelvin/cold-clear-2)はMIT/Apache-2.0のデュアルライセンスで、サブプロセス（`cold-clear-2.exe`）として実行時に呼び出す形で利用している。実行ファイル形式の配布物にはこのバイナリを同梱するため、`tools/build_exe.py`が`external/cold-clear-2/`のライセンス文（`LICENSE-MIT`・`LICENSE-APACHE`）を`dist/TBA/licenses/`にコピーし、再配布条件（著作権表示・許諾文の同梱）を満たしている。
