"""TBA (Tetris Beginner Assistance) の起動スクリプト。

実行ファイル(PyInstaller)のエントリポイント。ソースから起動する場合は
従来どおり `python -m src.app` でもよい。
"""

from src.app import main

if __name__ == "__main__":
    main()
