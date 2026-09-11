@echo off
REM テトリス支援AI 起動用バッチファイル
REM ダブルクリックするだけで仮想環境を有効化してapp.pyを起動する
REM
REM pythonw(コンソールウィンドウを表示しない実行形式)を使うことで、
REM アプリ(GUI)を閉じてもコンソール画面だけ残り続ける問題を解消している
REM (以前はpythonを使い、エラー内容を読めるようpauseも入れていたが、
REM 正常終了時にもコンソールが残り続けてしまうという指摘を受けた)。
REM エラー発生時の診断はdebug_log.txt側で行う想定。
cd /d "%~dp0"
call venv\Scripts\activate.bat
start "" venv\Scripts\pythonw.exe -m src.app
