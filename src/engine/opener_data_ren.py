"""開幕中開け4列REN(種3)の図。tools/import_ren_template.py で生成(手で編集しない)。

【2026-10-03・利用者の要望】種3の中あけRENを積む練習をシミュレーターでする。出典はテトリス堂。
記号は opener_data.py と同じ(井戸の'B'は空き、前に置いたミノは既存ブロック'c'に読み替え済み)。
"""

REN_SOURCE_FORMS = (
    (
        '中開け4列REN(種3)',
        'Center 4-Wide REN Opener',
        'https://shiwehi.com/tetris/template/center4wideopener.php',
        (
            ('基本系 > 1巡目', "\n".join(('----------', '-------i--', '-------i--', 'lll----is-', 'loo----iss', 'joo---tzzs', 'jjj--tttzz'))),
            ('基本系 > 1巡目', "\n".join(('----------', '---------i', '---------i', 'jjj-----zi', 'lsj----zzi', 'lss---tzoo', 'lls--tttoo'))),
            ('基本系 > 1巡目', "\n".join(('----------', '----------', '--------t-', 'lll----tti', 'loo----sti', 'joo--zzssi', 'jjj---zzsi'))),
            ('レベル1 > 1巡目', "\n".join(('----------', '----------', '----------', '----------', '----------', '----------', '----------', '----------', '----------', '----------', '-------i--', '-------i--', 'lll----is-', 'loo----iss', 'joo---tzzs', 'jjj--tttzz'))),
            ('レベル1 > 2巡目', "\n".join(('----------', '----------', '----------', '----------', '----------', '----------', '-------i-z', '-------izz', 'jjj----izt', 'ooj----itt', 'ool----cst', 'lll----css', 'ccc----ccs', 'ccc----ccc', 'ccc---cccc', 'ccc--ccccc'))),
            ('レベル1 > 3巡目', "\n".join(('--------s-', '--------ss', '-------its', '-------itt', 'jjj----itz', 'ooj----izz', 'ool----czc', 'lll----ccc', 'ccc----ccc', 'ccc----ccc', 'ccc----ccc', 'ccc----ccc', 'ccc----ccc', 'ccc----ccc', 'ccc---cccc', 'ccc--ccccc'))),
            ('レベル1 > 3巡目', "\n".join(('--------z-', '-------zz-', '-------zti', '-------tti', 'jjj----sti', 'ooj----ssi', 'ool----csc', 'lll----ccc', 'ccc----ccc', 'ccc----ccc', 'ccc----ccc', 'ccc----ccc', 'ccc----ccc', 'ccc----ccc', 'ccc---cccc', 'ccc--ccccc'))),
            ('レベル2 > 1巡目', "\n".join(('----------', '----------', '----------', '----------', '-------i--', '-------i--', 'lll----is-', 'loo----iss', 'joo----zzs', 'jjj-----zz'))),
        ),
    ),
)
