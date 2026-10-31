"""TBA (Tetris Beginner Assistance) の起動スクリプト。

実行ファイル(PyInstaller)のエントリポイント。ソースから起動する場合は
従来どおり `python -m src.app` でもよい。
"""

import multiprocessing

if __name__ == "__main__":
    # 【2026-10-04】パフェ探索を別プロセスで動かす(src/education/pc_process.py)。exeから子プロセスを
    # 起動したときは、ここで子プロセスとしての処理に入る(画面のモジュールを読み込む前に)
    multiprocessing.freeze_support()
    from src.app import main

    main()
