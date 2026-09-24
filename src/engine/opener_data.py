"""開幕テンプレの盤面図データ。

テトリス堂(https://shiwehi.com/tetris/)の各テンプレページに掲載されている
テキスト盤面図を、ページのセクション(1巡目/2巡目/3巡目)ごとに写したもの。
このファイルは scratchpad の gen_opener_data.py で自動生成した(手で編集しない)。
開幕パフェ積み・DPCは tools/gen_opener_extra.py で生成(同じ種類のミノが隣接する図は
片方を大文字にして分けた。読み込めない図は除外)。

記号: '-'=空、'c'/'C'=既に置いてあるブロック、小文字=この巡で置くミノ、
大文字(J/L/S/Z/I)=ホールドしてあったミノ、'U'=Tスピンで入れるT。
下の行ほど盤面の下(最下行が盤面の最下段)。
"""

from __future__ import annotations

# (日本語名, 英語名, 出典URL, ((セクション名, 盤面図), ...))
OPENER_SOURCE_FORMS: tuple[tuple[str, str, str, tuple[tuple[str, str], ...]], ...] = (
    (
        "迷走砲",
        "Stray Cannon",
        "https://shiwehi.com/tetris/template/meisou.php",
        (
            ("1巡目とミノ順", "\n".join(('----------', '----------', 'i---------', 'ils-t--j--', 'ilsstt-joo', 'illst-jjoo'))),
            ("1巡目とミノ順", "\n".join(('----------', '----------', 'i------zz-', 'ils-t--jzz', 'ilsstt-joo', 'illst-jjoo'))),
            ("理想形 > 2巡目", "\n".join(('----------', '------ooji', 's--z--ooji', 'sszz---jji', 'cszlllUcci', 'ccclcUUccc', 'ccccccUccc', 'ccccc-cccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'jjjllliiii', 'zzjloocccc', 'czzcoocccc', 'ccccUUUccc', 'cccccUcccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'llljjjiiii', 'loozzjcccc', 'cooczzcccc', 'ccccUUUccc', 'cccccUcccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'jjjslliiii', 'zzjsslcccc', 'czzcslcccc', 'ccccUUUccc', 'cccccUcccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'slloojiiii', 'ssloojcccc', 'cslcjjcccc', 'ccccUUUccc', 'cccccUcccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'oojslliiii', 'oojsslcccc', 'cjjcslcccc', 'ccccUUUccc', 'cccccUcccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'slljjjiiii', 'sslzzjcccc', 'cslczzcccc', 'ccccUUUccc', 'cccccUcccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'oosslliiii', 'oojjjlcccc', 'csscjlcccc', 'ccccUUUccc', 'cccccUcccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'zzljooiiii', 'llljjjcccc', 'czzcoocccc', 'ccccUUUccc', 'cccccUcccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'slljooiiii', 'ssljjjcccc', 'cslcoocccc', 'ccccUUUccc', 'cccccUcccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'oojslliiii', 'oojsslcccc', 'cjjczzcccc', 'ccccszzccc', 'ccccclcccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'oojjjziiii', 'oosszzcccc', 'cssczUcccc', 'ccccjUUccc', 'cccccUcccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'llljjjiiii', 'lootttcccc', 'cooczzcccc', 'cccctzzccc', 'cccccjcccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'slljjjiiii', 'ssltttcccc', 'cslczzcccc', 'cccctzzccc', 'cccccjcccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'sllootiiii', 'ssloozcccc', 'cslczzcccc', 'cccczttccc', 'ccccctcccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'oojjjtiiii', 'oossjzcccc', 'cssczzcccc', 'cccczttccc', 'ccccctcccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'oossltiiii', 'oolllzcccc', 'czzczzcccc', 'cccczttccc', 'ccccctcccc'))),
            # 【2026-09-24】通常形(%O>%J)。文献にあるが取り込まれていなかった(実画面 practice_20260924_195802)
            ("通常形 > %O>%Sの場合", "\n".join(("-jj-------", "-js------i", "-jss--zz-i", "-oos---zzi", "coolllUcci", "ccclcUUccc", "ccccccUccc", "ccccc-cccc"))),
            ("通常形 > %O>%Sの場合 > 3巡目 - パフェ狙い", "\n".join(("iccslloojj", "iccssloojc", "icccslccjc", "icccUUUccc", "cccccUcccc"))),
            ("通常形 > %O>%Sの場合 > TSTドネイト", "\n".join(("----------", "-oo-----ll", "-ooj-----l", "iccjjjssUl", "icczzssUUc", "iccczzccUc", "iccc---ccc", "ccccc-cccc"))),
            ("通常形 > %O>%Sの場合 > TSTドネイト後", "\n".join(("----------", "--------ll", "ioo-----zl", "ioos---zzl", "iccss-jzcc", "icccs-jjjc", "ccccUUUccc", "cccccUcccc"))),
            ("通常形 > %S>%Oの場合", "\n".join(("----------", "-joo-----i", "-joo--zz-i", "jjss---zzi", "csslllUZZi", "ccclcUUcZZ", "ccccccUccc", "ccccc-cccc"))),
            ("通常形 > %S>%Oの場合 > 3巡目", "\n".join(("----------", "---jj---s-", "iooj----ss", "iooj-zzlls", "iccc--zzlc", "iccc--cclc", "ccccUUUccc", "cccccUcccc"))),
            ("別パターン > 2巡目%I早の場合", "\n".join(('--------jj', '--s-----ji', '--ss--zzji', '-oos---zzi', 'coolllUcci', 'ccclcUUccc', 'ccccccUccc', 'ccccc-cccc'))),
            ("別パターン > 2巡目%I早の場合", "\n".join(('----------', 'ijjslloocc', 'ijcssloocc', 'ijccslcccc', 'icccUUUccc', 'cccccUcccc'))),
            ("別パターン > 2巡目%I早の場合", "\n".join(('----------', 'ijjzzloocc', 'ijcllloocc', 'ijcczzcccc', 'icccUUUccc', 'cccccUcccc'))),
            ("別パターン > 2巡目%I早の場合", "\n".join(('----------', 'ijjoosslcc', 'ijcoolllcc', 'ijccsscccc', 'icccUUUccc', 'cccccUcccc'))),
            ("別パターン > 2巡目%I早の場合", "\n".join(('----------', 'llloojjjcc', 'lzcoossjcc', 'zzccsscccc', 'zcccUUUccc', 'cccccUcccc'))),
            ("別パターン > 2巡目%I早の場合", "\n".join(('----------', 'lllzzjjjcc', 'oociiiijcc', 'oocczzcccc', 'lccctttccc', 'ccccctcccc'))),
            ("別パターン > 2巡目%I早の場合", "\n".join(('----------', 'ijjootttcc', 'ijcoolllcc', 'ijccslcccc', 'icccsstccc', 'cccccscccc'))),
            ("別パターン > 2巡目%I早の場合", "\n".join(('----------', 'ijjslloocc', 'ijcssloocc', 'ijcczzcccc', 'icccszzccc', 'ccccclcccc'))),
            ("別パターン > 2巡目%I早の場合", "\n".join(('----------', 'ijjoolllcc', 'ijcoozsscc', 'ijcczzcccc', 'iccczssccc', 'ccccclcccc'))),
            ("別パターン > 2巡目%I早の場合", "\n".join(('----------', 'ijjstttlcc', 'ijcsslllcc', 'ijcczzcccc', 'icccszzccc', 'ccccctcccc'))),
            ("別パターン > 2巡目%I早の場合", "\n".join(('----------', 'ijjstttzcc', 'ijcsstzzcc', 'ijccllcccc', 'icccslzccc', 'ccccclcccc'))),
            ("別パターン > 2巡目%I早の場合", "\n".join(('----------', 'jjjiiiizcc', 'oocjjjzzcc', 'ooccsjcccc', 'lcccsszccc', 'cccccscccc'))),
            ("別パターン > 2巡目%I早の場合", "\n".join(('----------', 'lllstttzcc', 'oocssjzzcc', 'ooccsjcccc', 'lcccjjzccc', 'ccccctcccc'))),
            ("別パターン > 1巡目%z左置きパターン", "\n".join(('--z-------', '-zz-------', '-zoo--jjji', 'ZZoo---sji', 'cZZlllUssi', 'ccclcUUcsi', 'ccccccUccc', 'ccccc-cccc'))),
            ("別パターン > 1巡目%z左置きパターン", "\n".join(('----------', 'jjciiiiloo', 'jcczzllloo', 'jccczzcccc', 'ccccUUUccc', 'cccccUcccc'))),
            ("別パターン > 1巡目%z左置きパターン", "\n".join(('----------', 'jjcooiiiil', 'jccoosslll', 'jcccsscccc', 'ccccUUUccc', 'cccccUcccc'))),
            ("別パターン > 1巡目%z左置きパターン", "\n".join(('----------', 'jjcsiiiioo', 'jccssllloo', 'jcccslcccc', 'ccccUUUccc', 'cccccUcccc'))),
            ("別パターン > 1巡目%z左置きパターン", "\n".join(('----------', 'jjciiiizoo', 'jcctttzzoo', 'jcccllcccc', 'cccctlzccc', 'ccccclcccc'))),
            ("別パターン > 1巡目%z左置きパターン", "\n".join(('----------', 'jjcsiiiioo', 'jccsstttoo', 'jcccllcccc', 'ccccsltccc', 'ccccclcccc'))),
            ("別パターン > 1巡目%z左置きパターン", "\n".join(('----------', 'jjcslllzoo', 'jccssizzoo', 'jccclicccc', 'ccccsizccc', 'cccccicccc'))),
            ("別パターン > 1巡目%z左置きパターン", "\n".join(('----------', 'jjcstttloo', 'jccssllloo', 'jccczzcccc', 'ccccszzccc', 'ccccctcccc'))),
            ("別パターン > 1巡目%z左置きパターン", "\n".join(('----------', 'jjcstttzoo', 'jccsstzzoo', 'jcccllcccc', 'ccccslzccc', 'ccccclcccc'))),
            ("別パターン > 1巡目%z左置きパターン", "\n".join(('----------', 'jjcsiiiioo', 'jccssllloo', 'jccczzcccc', 'ccccszzccc', 'ccccclcccc'))),
        ),
    ),
    (
        "はちみつ砲",
        "Honey Cup",
        "https://shiwehi.com/tetris/template/honeycup.php",
        (
            ("1巡目とミノ順", "\n".join(('----------', '----------', '-ss-------', 'ssl----t--', 'lll-zzttoo', 'iiii-zztoo'))),
            ("1巡目とミノ順", "\n".join(('----------', '----------', '-------zz-', '--t----jzz', 'oottss-jjj', 'ootss-iiii'))),
            ("理想形 > 2巡目", "\n".join(('----------', 'iiii------', 'JJss--jj--', 'Jss---jlll', 'Jcc-zzjloo', 'ccc--zzcoo', 'ccc-cccccc', 'cccc-ccccc'))),
            ("理想形 > 2巡目", "\n".join(('----------', 'iiii------', 'JJss--lj--', 'Jss---ljjj', 'Jcc-zzlloo', 'ccc--zzcoo', 'ccc-cccccc', 'cccc-ccccc'))),
            ("理想形 > 2巡目", "\n".join(('----------', 'iiii------', 'jjss--oo--', 'jss---oolJ', 'jcc-zzlllJ', 'ccc--zzcJJ', 'ccc-cccccc', 'cccc-ccccc'))),
            ("理想形 > 2巡目", "\n".join(('----------', 'illl------', 'ilss--jj--', 'iss---jooJ', 'icc-zzjooJ', 'ccc--zzcJJ', 'ccc-cccccc', 'cccc-ccccc'))),
            ("理想形 > 2巡目", "\n".join(('----------', 'ijjj------', 'iooj--ls--', 'ioo---lssJ', 'icc-zzllsJ', 'ccc--zzcJJ', 'ccc-cccccc', 'cccc-ccccc'))),
            ("理想形 > 2巡目", "\n".join(('----------', 'cccc------', 'cccc--cc--', 'ccc---cccc', 'CCCUCCCCCC', 'CCCUUCCCCC', 'CCCUCCCCCC', 'cccc-ccccc'))),
            ("理想形 > 2巡目", "\n".join(('----------', '----------', '----------', '----------', 'cccc------', 'cccc--cc--', 'ccc---cccc', 'cccc-ccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiillljjj', 'cccclsszzj', 'ccccsscczz', 'ccctttcccc', 'cccctccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiijjzsll', 'ccccjzzssl', 'ccccjzccsl', 'ccctttcccc', 'cccctccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiilllooj', 'cccclssooj', 'ccccssccjj', 'ccctttcccc', 'cccctccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiijjzlll', 'ccccjzzloo', 'ccccjzccoo', 'ccctttcccc', 'cccctccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiijjjsll', 'ccccoojssl', 'ccccooccsl', 'ccctttcccc', 'cccctccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiiloojjj', 'ccccloozzj', 'ccccllcczz', 'ccctttcccc', 'cccctccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiijsszzl', 'ccccjjjlll', 'ccccsscczz', 'ccctttcccc', 'cccctccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiijsslll', 'ccccjjjloo', 'ccccssccoo', 'ccctttcccc', 'cccctccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiiooljjj', 'cccclllzzj', 'ccccoocczz', 'ccctttcccc', 'cccctccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiijjjzzl', 'ccccoojlll', 'ccccoocczz', 'ccctttcccc', 'cccctccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiijjzlll', 'ccccjzzloo', 'ccccssccoo', 'cccsszcccc', 'ccccjccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiilllooj', 'cccctttooj', 'ccccssccjj', 'cccsstcccc', 'cccclccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiillljjj', 'cccctttzzj', 'ccccsscczz', 'cccsstcccc', 'cccclccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiitoojjj', 'ccccsoozzj', 'ccccsscczz', 'cccttscccc', 'cccctccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiitoozzl', 'ccccsoolll', 'ccccsscczz', 'cccttscccc', 'cccctccccc'))),
            ("妥協形 > 2巡目", "\n".join(('--------oo', 'i-------oo', 'i-ss--l-jj', 'iss---l-jJ', 'icc-zzlljJ', 'ccc--zzcJJ', 'ccc-cccccc', 'cccc-ccccc'))),
            ("妥協形 > 2巡目", "\n".join(('--------oo', 'i-------oo', 'i-ss--l-jj', 'iss---l-jJ', 'ICCUZZlljJ', 'CCCUUZZCJJ', 'CCCUCCCCCC', 'cccc-ccccc'))),
            ("妥協形 > 2巡目 > 3巡目 - TSTドネイト", "\n".join(('----------', 'jj------oo', 'j-----l-oo', 'jUzzlllicc', 'cUUzzssicc', 'cUccsscicc', 'ccc---cicc', 'cccc-ccccc'))),
            ("妥協形 > 2巡目 > 3巡目 - TSTドネイト", "\n".join(('----------', 'jj--------', 'js-----ioo', 'jss---zioo', 'ccs--zzicc', 'c----zcicc', 'cccUUUcccc', 'ccccUccccc'))),
            ("妥協形 > 2巡目 > 3巡目 - TSTドネイト", "\n".join(('----------', 'jj--------', 'js-----ioo', 'jss----ioo', 'ccsl---icc', 'clll--cicc', 'ccc---cccc', 'cccc-ccccc'))),
            ("妥協形 > 2巡目 > 3巡目 - TSTドネイト", "\n".join(('----------', 'jj--------', 'js-----ioo', 'jss---zioo', 'ccsl-zzicc', 'clll-zcicc'))),
            ("妥協形 > 2巡目 > 3巡目 - パフェ狙い", "\n".join(('----------', 'lljiiiiooc', 'cljjjssooc', 'clccsscccc', 'ccctttcccc', 'cccctccccc'))),
            ("妥協形 > 2巡目 > 3巡目 - パフェ狙い", "\n".join(('----------', 'lliiiizooc', 'cljjjzzooc', 'clccjzcccc', 'ccctttcccc', 'cccctccccc'))),
            ("妥協形 > 2巡目 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiijjzooc', 'cllljzzooc', 'clccjzcccc', 'ccctttcccc', 'cccctccccc'))),
            ("妥協形 > 2巡目 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiijssooc', 'cllljjjooc', 'clccsscccc', 'ccctttcccc', 'cccctccccc'))),
            ("妥協形 > 2巡目 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiijjzooc', 'cllljzzooc', 'clccsscccc', 'cccsszcccc', 'ccccjccccc'))),
            ("妥協形 > 2巡目 > 3巡目 - パフェ狙い", "\n".join(('----------', 'llsiiiiooc', 'clsstttooc', 'clccjjcccc', 'cccsjtcccc', 'ccccjccccc'))),
            ("妥協形 > 2巡目 > 3巡目 - パフェ狙い", "\n".join(('----------', 'lliiiizooc', 'cltttzzooc', 'clccjjcccc', 'ccctjzcccc', 'ccccjccccc'))),
            ("妥協形 > 2巡目 > 3巡目 - パフェ狙い", "\n".join(('----------', 'llsjjjzooc', 'clssizzooc', 'clccizcccc', 'cccsijcccc', 'cccciccccc'))),
            ("妥協形 > 2巡目 > 3巡目 - パフェ狙い", "\n".join(('----------', 'lljtttzooc', 'cljjjzzooc', 'clccsscccc', 'cccsszcccc', 'cccctccccc'))),
            ("妥協形 > 2巡目 > 3巡目 - パフェ狙い", "\n".join(('----------', 'llstttjjjc', 'clssiiiijc', 'clccoocccc', 'cccsoocccc', 'cccctccccc'))),
            ("妥協形 > 2巡目 > 3巡目 - パフェ狙い", "\n".join(('----------', 'llstttzooc', 'clsstzzooc', 'clccjjcccc', 'cccsjzcccc', 'ccccjccccc'))),
            ("妥協形 > 2巡目 > 3巡目 - パフェ狙い", "\n".join(('----------', 'tttjlllooc', 'ciiiissooc', 'ctccsscccc', 'cccjjjcccc', 'cccclccccc'))),
        ),
    ),
    (
        "山岳積み2号",
        "Mountainous Stacking 2",
        "https://shiwehi.com/tetris/template/mountainous2.php",
        (
            ("1巡目とミノ順", "\n".join(('----------', '------l---', '------l---', 'is----ll--', 'iss----t--', 'ijs-zzttoo', 'ijjj-zztoo'))),
            ("1巡目とミノ順", "\n".join(('----------', '---j------', '---j------', '--jj----zi', '--t----zzi', 'oottss-zli', 'ootss-llli'))),
            ("理想形 > 2巡目", "\n".join(('----------', 'jjoo------', 'jsoo--c--i', 'jss---clli', 'ccsUzzccli', 'cccUUzzcli', 'cccUcccccc', 'cccc-ccccc'))),
            ("理想形 > 2巡目", "\n".join(('----------', '----------', '----------', '----------', 'cccc------', 'cccc--c--c', 'ccc---cccc', 'cccc-ccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiillljjj', 'cccclssooj', 'ccccsscooc', 'ccctttcccc', 'cccctccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiijjjlll', 'ccccoojlss', 'ccccoocssc', 'ccctttcccc', 'cccctccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiijjzlll', 'ccccjzzlss', 'ccccjzcssc', 'ccctttcccc', 'cccctccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiijjzloo', 'ccccjzzloo', 'ccccjzcllc', 'ccctttcccc', 'cccctccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiijjzzoo', 'ccccjllloo', 'ccccjlczzc', 'ccctttcccc', 'cccctccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiiooljss', 'ccccllljjj', 'ccccoocssc', 'ccctttcccc', 'cccctccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiiooljjz', 'ccccllljzz', 'ccccoocjzc', 'ccctttcccc', 'cccctccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiijjzloo', 'ccccjzzloo', 'ccccsscllc', 'cccsszcccc', 'ccccjccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiisllloo', 'ccccsszzoo', 'cccctsczzc', 'cccttlcccc', 'cccctccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiillljjj', 'cccctttooj', 'ccccsscooc', 'cccsstcccc', 'cccclccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiillljjz', 'cccctttjzz', 'ccccsscjzc', 'cccsstcccc', 'cccclccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiitoojjz', 'ccccsoojzz', 'ccccsscjzc', 'cccttscccc', 'cccctccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiitllloo', 'ccccslzzoo', 'ccccssczzc', 'cccttscccc', 'cccctccccc'))),
            ("理想形 > 3巡目 - パフェ狙い", "\n".join(('----------', 'iiiitjzzoo', 'ccccsjjjoo', 'ccccssczzc', 'cccttscccc', 'cccctccccc'))),
            ("通常形 > 2巡目", "\n".join(('----------', '--------ss', 'oojj--cssi', 'ooj---clli', 'ccjUzzccli', 'cccUUzzcli', 'cccUcccccc', 'cccc-ccccc'))),
            ("通常形 > 2巡目", "\n".join(('----------', '--------ss', 'iiii--cssl', 'jjj---clll', 'ccjUzzccoo', 'cccUUzzcoo', 'cccUcccccc', 'cccc-ccccc'))),
            ("通常形 > 2巡目", "\n".join(('----------', '--------LL', 'iiii--lllL', 'jjj---lssL', 'ccjUzzssoo', 'cccUUzzcoo', 'cccUcccccc', 'cccc-ccccc'))),
            ("通常形 > 2巡目", "\n".join(('----------', '----------', '----------', '----------', '--------cc', 'cccc--cccc', 'ccc---cccc', 'cccc-ccccc'))),
            ("通常形 > 3巡目", "\n".join(('----------', 'oojiiiilll', 'oojjjsslcc', 'ccccsscccc', 'ccctttcccc', 'cccctccccc'))),
            ("通常形 > 3巡目", "\n".join(('----------', 'oollljiiii', 'oolzzjjjcc', 'cccczzcccc', 'ccctttcccc', 'cccctccccc'))),
            ("通常形 > 3巡目", "\n".join(('----------', 'jiiiioolll', 'jjjzzoolcc', 'cccczzcccc', 'ccctttcccc', 'cccctccccc'))),
            ("通常形 > 3巡目", "\n".join(('----------', 'ooiiiizlll', 'ootttzzlcc', 'ccccjjcccc', 'ccctjzcccc', 'ccccjccccc'))),
            ("通常形 > 3巡目", "\n".join(('----------', 'oostttiiii', 'oosstlllcc', 'ccccjjcccc', 'cccsjlcccc', 'ccccjccccc'))),
            ("通常形 > 3巡目", "\n".join(('----------', 'oostttzlll', 'oosstzzlcc', 'ccccjjcccc', 'cccsjzcccc', 'ccccjccccc'))),
            ("通常形 > 3巡目", "\n".join(('----------', 'ooiiiizlll', 'oojjjzzlcc', 'ccccsscccc', 'cccsszcccc', 'ccccjccccc'))),
            ("通常形 > 3巡目", "\n".join(('----------', 'oosjjjzlll', 'oossizzlcc', 'ccccizcccc', 'cccsijcccc', 'cccciccccc'))),
            ("妥協系 > 2巡目", "\n".join(('-ss-------', 'ss--------', 'oojj--c--i', 'ooj---clli', 'ccjUzzccli', 'cccUUzzcli', 'cccUcccccc', 'cccc-ccccc'))),
            ("妥協系 > 2巡目", "\n".join(('----------', '----------', '----------', '-cc-------', 'cc--------', 'cccc--c--c', 'ccc---cccc', 'cccc-ccccc'))),
        ),
    ),
    (
        "オリーブ積み",
        "Olive Stacking",
        "https://shiwehi.com/tetris/template/olive.php",
        (
            ("組み方とミノ順 > 1巡目とミノ順", "\n".join(('----------', '----------', '--z-------', '-zz------j', '-zl--t-ssj', 'ool-ttssjj', 'ooll-tiiii'))),
            ("組み方とミノ順 > 1巡目とミノ順", "\n".join(('----------', '----------', '-------s--', 'l------ss-', 'lzz-t--js-', 'llzztt-joo', 'iiiit-jjoo'))),
            ("組み方とミノ順 > 理想形 > 2巡目", "\n".join(('----------', 'lloo------', 'iloo--s--z', 'ilc---sszz', 'iccUjjjszc', 'iccUUcjccc', 'cccUcccccc', 'cccc-ccccc'))),
            ("組み方とミノ順 > 理想形 > 2巡目", "\n".join(('----------', '----------', '----------', '----------', 'lloo------', 'iloo--s--z', 'ilc---sszz', 'cccc-ccccc'))),
            ("組み方とミノ順 > 理想形 > 3巡目", "\n".join(('----------', 'iiiillljjj', 'cccclssooj', 'ccccsscooc', 'ccctttcccc', 'cccctccccc'))),
            ("組み方とミノ順 > 理想形 > 3巡目", "\n".join(('----------', 'iiiijjjlll', 'ccccoojlss', 'ccccoocssc', 'ccctttcccc', 'cccctccccc'))),
            ("組み方とミノ順 > 理想形 > 3巡目", "\n".join(('----------', 'iiiijjzlll', 'ccccjzzlss', 'ccccjzcssc', 'ccctttcccc', 'cccctccccc'))),
            ("組み方とミノ順 > 理想形 > 3巡目", "\n".join(('----------', 'iiiijjzloo', 'ccccjzzloo', 'ccccjzcllc', 'ccctttcccc', 'cccctccccc'))),
            ("組み方とミノ順 > 理想形 > 3巡目", "\n".join(('----------', 'iiiijjzzoo', 'ccccjllloo', 'ccccljczzc', 'ccctttcccc', 'cccctccccc'))),
            ("組み方とミノ順 > 理想形 > 3巡目", "\n".join(('----------', 'iiiiooljss', 'ccccllljjj', 'ccccoocssc', 'ccctttcccc', 'cccctccccc'))),
            ("組み方とミノ順 > 理想形 > 3巡目", "\n".join(('----------', 'iiiiooljjz', 'ccccllljzz', 'ccccoocjzc', 'ccctttcccc', 'cccctccccc'))),
            ("組み方とミノ順 > 理想形 > 3巡目", "\n".join(('----------', 'iiiijjzloo', 'ccccjzzloo', 'ccccsscllc', 'cccsszcccc', 'ccccjccccc'))),
            ("組み方とミノ順 > 理想形 > 3巡目", "\n".join(('----------', 'iiiisllloo', 'ccccsszzoo', 'cccctsczzc', 'cccttlcccc', 'cccctccccc'))),
            ("組み方とミノ順 > 理想形 > 3巡目", "\n".join(('----------', 'iiiillljjj', 'cccctttooj', 'ccccsscooc', 'cccsstcccc', 'cccclccccc'))),
            ("組み方とミノ順 > 理想形 > 3巡目", "\n".join(('----------', 'iiiillljjz', 'cccctttjzz', 'ccccsscjzc', 'cccsstcccc', 'cccclccccc'))),
            ("組み方とミノ順 > 理想形 > 3巡目", "\n".join(('----------', 'iiiitoojjz', 'ccccsoojzz', 'ccccsscjzc', 'cccttscccc', 'cccctccccc'))),
            ("組み方とミノ順 > 理想形 > 3巡目", "\n".join(('----------', 'iiiitllloo', 'ccccslzzoo', 'ccccssczzc', 'cccttscccc', 'cccctccccc'))),
            ("組み方とミノ順 > 理想形 > 3巡目", "\n".join(('----------', 'iiiitjzzoo', 'ccccsjjjoo', 'ccccssczzc', 'cccttscccc', 'cccctccccc'))),
            ("組み方とミノ順 > 通常形 > 2巡目", "\n".join(('oo--------', 'oo--------', 'illl--s--z', 'ilc---sszz', 'iccUjjjszc', 'iccUUcjccc', 'cccUcccccc', 'cccc-ccccc'))),
            ("組み方とミノ順 > 通常形 > 2巡目", "\n".join(('----------', '----------', '----------', 'oo--------', 'oo--------', 'illl--s--z', 'ilc---sszz', 'cccc-ccccc'))),
            ("組み方とミノ順 > 通常形 > 3巡目", "\n".join(('----------', 'ccoollljjz', 'ccoolssjzz', 'ccccsscjzc', 'ccctttcccc', 'cccctccccc'))),
            ("組み方とミノ順 > 通常形 > 3巡目", "\n".join(('----------', 'ccoojjzlll', 'ccoojzzlss', 'ccccjzcssc', 'ccctttcccc', 'cccctccccc'))),
            ("組み方とミノ順 > 通常形 > 3巡目", "\n".join(('----------', 'ccoojjiiii', 'ccoojlllss', 'ccccjlcssc', 'ccctttcccc', 'cccctccccc'))),
            ("組み方とミノ順 > 通常形 > 3巡目", "\n".join(('----------', 'ccjiiiiloo', 'ccjjjssloo', 'ccccsscllc', 'ccctttcccc', 'cccctccccc'))),
            ("組み方とミノ順 > 通常形 > 3巡目", "\n".join(('----------', 'ccooliiiiz', 'ccooljjjzz', 'ccccllcjzc', 'ccctttcccc', 'cccctccccc'))),
            ("組み方とミノ順 > 通常形 > 3巡目", "\n".join(('----------', 'ccllljiiii', 'cclzzjjjss', 'cccczzcssc', 'ccctttcccc', 'cccctccccc'))),
            ("組み方とミノ順 > 通常形 > 3巡目", "\n".join(('----------', 'cciiiizloo', 'ccjjjzzloo', 'ccccjzcllc', 'ccctttcccc', 'cccctccccc'))),
            ("組み方とミノ順 > 通常形 > 3巡目", "\n".join(('----------', 'cciiiizlll', 'ccjjjzzlss', 'ccccjzcssc', 'ccctttcccc', 'cccctccccc'))),
            ("組み方とミノ順 > 通常形 > 3巡目", "\n".join(('----------', 'ccjjjllloo', 'cciiiizzoo', 'ccccjlczzc', 'ccctttcccc', 'cccctccccc'))),
            ("組み方とミノ順 > 通常形 > 3巡目", "\n".join(('----------', 'ccjzzlllss', 'ccjjjliiii', 'cccczzcssc', 'ccctttcccc', 'cccctccccc'))),
            ("組み方とミノ順 > 通常形 > 3巡目", "\n".join(('----------', 'cclllssjjz', 'ccliiiijzz', 'ccccsscjzc', 'ccctttcccc', 'cccctccccc'))),
            ("組み方とミノ順 > 通常形 > 3巡目", "\n".join(('----------', 'cclllssjjj', 'ccliiiiooj', 'ccccsscooc', 'ccctttcccc', 'cccctccccc'))),
            ("組み方とミノ順 > 通常形 > 3巡目", "\n".join(('----------', 'cciiiizzoo', 'ccjjjllloo', 'ccccjlczzc', 'ccctttcccc', 'cccctccccc'))),
            ("組み方とミノ順 > 通常形 > 3巡目", "\n".join(('----------', 'ccsiiiijjj', 'ccsslllooj', 'cccclzcooc', 'cccszzcccc', 'cccczccccc'))),
            ("組み方とミノ順 > 通常形 > 3巡目", "\n".join(('----------', 'cciiiizlll', 'cctttzzlss', 'ccccjjcssc', 'ccctjzcccc', 'ccccjccccc'))),
            ("組み方とミノ順 > 通常形 > 3巡目", "\n".join(('----------', 'cciiiizloo', 'cctttzzloo', 'ccccjjcllc', 'ccctjzcccc', 'ccccjccccc'))),
            ("組み方とミノ順 > 通常形 > 3巡目", "\n".join(('----------', 'cctttllloo', 'cciiiizzoo', 'ccccjjczzc', 'ccctjlcccc', 'ccccjccccc'))),
            ("組み方とミノ順 > 通常形 > 3巡目", "\n".join(('----------', 'ccjjjllloo', 'cciiiizzoo', 'ccccssczzc', 'cccsslcccc', 'ccccjccccc'))),
            ("組み方とミノ順 > 通常形 > 3巡目", "\n".join(('----------', 'ccoollljjz', 'ccootttjzz', 'ccccsscjzc', 'cccsstcccc', 'cccclccccc'))),
            ("組み方とミノ順 > 通常形 > 3巡目", "\n".join(('----------', 'ccoojjtttz', 'ccooiiiizz', 'ccccjlctzc', 'ccclllcccc', 'ccccjccccc'))),
            ("組み方とミノ順 > 通常形 > 3巡目", "\n".join(('----------', 'ccsiiiiloo', 'ccsstttloo', 'ccccjjcllc', 'cccsjtcccc', 'ccccjccccc'))),
            ("組み方とミノ順 > 通常形 > 3巡目", "\n".join(('----------', 'ccsjjjzloo', 'ccssizzloo', 'ccccizcllc', 'cccsijcccc', 'cccciccccc'))),
            ("組み方とミノ順 > 通常形 > 3巡目", "\n".join(('----------', 'ccslliiiiz', 'ccssljjjzz', 'ccccoocjzc', 'cccsoocccc', 'cccclccccc'))),
            ("組み方とミノ順 > 妥協形 > 2巡目", "\n".join(('--oo------', '--oo------', 'illl--s--z', 'ilc---sszz', 'iccUjjjszc', 'iccUUcjccc', 'cccUcccccc', 'cccc-ccccc'))),
            ("組み方とミノ順 > 妥協形 > 2巡目", "\n".join(('----------', '----------', '----------', '--oo------', '--oo------', 'illl--s--z', 'ilc---sszz', 'cccc-ccccc'))),
            ("組み方とミノ順 > 妥協形 > 3巡目", "\n".join(('----------', 'ooccjjiiii', 'ooccjlllss', 'ccccjlcssc', 'ccctttcccc', 'cccctccccc'))),
            ("組み方とミノ順 > 妥協形 > 3巡目", "\n".join(('----------', 'ooccllljjz', 'oocclssjzz', 'ccccsscjzc', 'ccctttcccc', 'cccctccccc'))),
            ("組み方とミノ順 > 妥協形 > 3巡目", "\n".join(('----------', 'ooccjjzlll', 'ooccjzzlss', 'ccccjzcssc', 'ccctttcccc', 'cccctccccc'))),
            ("組み方とミノ順 > 妥協形 > 3巡目", "\n".join(('----------', 'ooccliiiiz', 'ooccljjjzz', 'ccccllcjzc', 'ccctttcccc', 'cccctccccc'))),
            ("組み方とミノ順 > 妥協形 > 3巡目", "\n".join(('----------', 'ooccjjtttz', 'oocciiiizz', 'ccccjlctzc', 'ccclllcccc', 'ccccjccccc'))),
            ("組み方とミノ順 > 妥協形 > 3巡目", "\n".join(('----------', 'ooccijtttz', 'ooccijjjzz', 'ccccilctzc', 'ccclllcccc', 'cccciccccc'))),
            ("組み方とミノ順 > 妥協形 > 3巡目", "\n".join(('----------', 'ooccllljjz', 'oocctttjzz', 'ccccsscjzc', 'cccsstcccc', 'cccclccccc'))),
            ("組み方とミノ順 > 1パターン確定 > 2巡目", "\n".join(('----------', '-------oo-', 'illl--sooz', 'ilc---sszz', 'iccUjjjszc', 'iccUUcjccc', 'cccUcccccc', 'cccc-ccccc'))),
            ("組み方とミノ順 > 1パターン確定 > 2巡目", "\n".join(('----------', '-------ss-', 'illl--ssoo', 'ilc---zzoo', 'iccUjjjzzc', 'iccUUcjccc', 'cccUcccccc', 'cccc-ccccc'))),
            ("組み方とミノ順 > 1パターン確定 > 2巡目", "\n".join(('----------', '-------zs-', 'illl--zzss', 'ilc---zoos', 'iccUjjjooc', 'iccUUcjccc', 'cccUcccccc', 'cccc-ccccc'))),
            ("組み方とミノ順 > 1パターン確定 > 2巡目", "\n".join(('----------', '-------zz-', 'illl--oozz', 'ilc---ooss', 'iccUjjjssc', 'iccUUcjccc', 'cccUcccccc', 'cccc-ccccc'))),
            ("組み方とミノ順 > 1パターン確定 > 2巡目", "\n".join(('----------', '----------', '----------', '----------', '-------oo-', 'illl--sooz', 'ilc---sszz', 'cccc-ccccc'))),
            ("組み方とミノ順 > 1パターン確定 > 3巡目", "\n".join(('----------', 'oolllssjjj', 'ooliiiiccj', 'ccccsscccc', 'ccctttcccc', 'cccctccccc'))),
            ("組み方とミノ順 > 1パターン確定 > 3巡目", "\n".join(('----------', 'lllzzoojjj', 'liiiiooccj', 'cccczzcccc', 'ccctttcccc', 'cccctccccc'))),
            ("組み方とミノ順 > 1パターン確定 > 3巡目", "\n".join(('----------', 'llltttzjjj', 'liiiizzccj', 'ccccsscccc', 'cccsszcccc', 'cccctccccc'))),
            ("組み方とミノ順 > 1パターン確定 > 3巡目", "\n".join(('----------', 'oosiiiijjj', 'oosslllccj', 'cccclzcccc', 'cccszzcccc', 'cccczccccc'))),
            ("組み方とミノ順 > 1パターン確定 > 3巡目", "\n".join(('----------', 'oostttzjjj', 'oosslzzccj', 'cccclzcccc', 'cccsllcccc', 'cccctccccc'))),
        ),
    ),
)


# 【2026-09-24・利用者の要望】教育モードだけで使うテンプレ(開幕パフェ積み・DPC)。
# 画像認識側(OPENER_TEMPLATES)には含めない。tools/gen_opener_extra.py でページから生成。
EDUCATION_SOURCE_FORMS: tuple[tuple[str, str, str, tuple[tuple[str, str], ...]], ...] = (
    (
        '開幕パフェ積み',
        'PC Opener',
        'https://shiwehi.com/tetris/template/pcopener.php',
        (
            ('1巡目', "\n".join(('----------', 'llli----ss', 'looi---sst', 'jooi--zztt', 'jjji---zzt'))),
            ('1巡目', "\n".join(('----------', 'zz----ijjj', 'tzz---iooj', 'ttss--iool', 'tss---illl'))),
            ('1巡目', "\n".join(('----------', 'iiii----ss', 'jjll---sst', 'jool--zztt', 'jool---zzt'))),
            ('1巡目', "\n".join(('----------', 'loojzz----', 'loojtzz---', 'lljjttss--', 'iiiitss---'))),
            ('1巡目', "\n".join(('----------', 'jiiii----t', 'jjjss---tt', 'oossl--zzt', 'oolll---zz'))),
        ),
    ),
    (
        'DPC',
        'DPC',
        'https://shiwehi.com/tetris/template/dpc.php',
        (
            ('I-01 Fake Butter DPC > 組み方', "\n".join(('----------', '-----l----', '---lll----', 'sUUUzjiiii', 'ssUzzjjjoo', '-s-zIIIIoo'))),
            ('I-01 Fake Butter DPC > パフェ', "\n".join(('----------', 'izztttjjll', 'iszztcjool', 'isscccjool', 'icsccccccc'))),
            ('I-01 Fake Butter DPC > パフェ', "\n".join(('----------', 'izztttlooj', 'iszztclooj', 'issccclljj', 'icsccccccc'))),
            ('I-02 ペリカンDPC > 組み方', "\n".join(('----------', '-----oo--i', '-----oo--i', 'szzUUUjjji', 'sszzUlllji', '-s---lIIII'))),
            ('I-02 ペリカンDPC > パフェ', "\n".join(('----------', 'iootttlljj', 'ioostccljc', 'izzssccljc', 'iczzsccccc'))),
            ('I-02 ペリカンDPC > パフェ', "\n".join(('----------', 'izztttlljj', 'iszztccljc', 'issooccljc', 'icsooccccc'))),
            ('I-03 TKI DPC > 組み方', "\n".join(('----------', '--ssz---oo', '-sszz--joo', 'lllzUUUjjj', 'lIIIIUiiii'))),
            ('I-03 TKI DPC > 組み方', "\n".join(('----------', '--lll---oo', '-zlss--joo', 'zzssUUUjjj', 'zIIIIUiiii'))),
            ('I-03 TKI DPC > 組み方', "\n".join(('----------', '--jjj---ss', '-zooj--ssl', 'zzooUUUlll', 'zIIIIUiiii'))),
            ('I-03 TKI DPC > パフェ', "\n".join(('----------', 'ijjsstttoo', 'ijsslltzoo', 'ijccclzzcc', 'icccclzccc'))),
            ('I-04 BAD TKI DPC > 組み方', "\n".join(('----------', '--ssz--jj-', '-sszz--joo', 'lllzUUUjoo', 'lIIIIUiiii'))),
            ('I-04 BAD TKI DPC > 組み方', "\n".join(('----------', '--lll--jj-', '-zlss--joo', 'zzssUUUjoo', 'zIIIIUiiii'))),
            ('I-04 BAD TKI DPC > 組み方', "\n".join(('----------', '--jjj--ls-', '-zooj--lss', 'zzooUUUlls', 'zIIIIUiiii'))),
            ('I-04 BAD TKI DPC > パフェ', "\n".join(('----------', 'ijjsstzzll', 'ijsstttzzl', 'ijcccooccl', 'iccccooccc'))),
            ('I-05 くるまDPC > 組み方', "\n".join(('----------', '-------s--', '-------ssI', 'jiiiiUUUsI', 'jjjlzzUooI', '-lll-zzooI'))),
            ('I-05 くるまDPC > パフェ', "\n".join(('----------', 'ilstttjjoo', 'ilsstzjcoo', 'illszzjccc', 'iccczccccc'))),
            ('I-05 くるまDPC > パフェ', "\n".join(('----------', 'illlssjjoo', 'iltsszjcoo', 'itttzzjccc', 'iccczccccc'))),
            ('I-05 くるまDPC > パフェ', "\n".join(('----------', 'izztttssoo', 'ijzztsscoo', 'ijjjlllccc', 'iccclccccc'))),
            ('I-06 > 組み方', "\n".join(('----------', '---------j', 'i-----s--j', 'il--zzssjj', 'ilUUUzzsoo', 'illUIIIIoo'))),
            ('I-06 > パフェ', "\n".join(('----------', 'llliiiittt', 'loojjjzztc', 'coossjczzc', 'ccsscccccc'))),
            ('I-06 > パフェ', "\n".join(('----------', 'jjjllliiii', 'zzjltttooc', 'czzsstcooc', 'ccsscccccc'))),
            ('I-06 > パフェ', "\n".join(('----------', 'siiiijjttt', 'ssloojzztc', 'csloojczzc', 'ccllcccccc'))),
            ('I-07 > 組み方', "\n".join(('i---------', 'i---------', 'i-----s---', 'illl--ssoo', 'jlzzUUUsoo', 'jjjzzUIIII'))),
            ('I-07 > パフェ', "\n".join(('----------', 'ciiiizzjjj', 'coosllzztj', 'coosslcttt', 'ccccslcccc'))),
            ('I-07 > パフェ', "\n".join(('----------', 'cllliiiioo', 'clsstttjoo', 'csszztcjjj', 'cccczzcccc'))),
            ('J-01 > 組み方', "\n".join(('----------', '---------i', 'j------lli', 'jjjssUUUli', 'oosszzUJli', 'oo---zzJJJ'))),
            ('J-01 > パフェ', "\n".join(('----------', 'szzjjjiiii', 'sszztjlllc', 'csoottlccc', 'ccootccccc'))),
            ('J-01 > パフェ', "\n".join(('----------', 'oosjjjiiii', 'oosstjlllc', 'czzsttlccc', 'cczztccccc'))),
            ('J-02 > 組み方', "\n".join(('----------', '-j-------i', '-j-----lli', 'jjszzUUUli', 'oosszzUJli', 'oo-s---JJJ'))),
            ('J-02 > パフェ', "\n".join(('----------', 'jjioolllss', 'jciooltssc', 'jcizzttccc', 'cciczztccc'))),
            ('J-02 > パフェ', "\n".join(('----------', 'jjzziiiiss', 'jctzzllssc', 'jcttoolccc', 'cctcoolccc'))),
            ('J-03 > 組み方', "\n".join(('----------', '----------', '---ll-z--i', 'sUUUlzzooi', 'ssUJlzjooi', '-s-JJJjjji'))),
            ('J-03 > パフェ', "\n".join(('----------', 'illlsszjjj', 'iltsszzooj', 'ittcczcooc', 'ictccccccc'))),
            ('J-03 > パフェ', "\n".join(('----------', 'iiiisszjjj', 'tllsszzooj', 'ttlcczcooc', 'tclccccccc'))),
            ('J-04 > 組み方', "\n".join(('--------oo', '--------oo', '--------jj', 'l--zz-s-jJ', 'lUUUzzssjJ', 'llUiiiisJJ'))),
            ('J-04 > パフェ', "\n".join(('----------', 'jjsszllicc', 'jsszztlicc', 'joozttlicc', 'coocctcicc'))),
            ('J-04 > パフェ', "\n".join(('----------', 'oolsjjjicc', 'oolsstjicc', 'zzllstticc', 'czzcctcicc'))),
            ('O-01 くるまDPC > 組み方', "\n".join(('----------', '-------s--', '-------ssi', 'llljjUUUsi', 'lOOjzzUooi', '-OOj-zzooi'))),
            ('O-01 くるまDPC > 組み方', "\n".join(('----------', '-------j--', '-------jjj', 'siiiiUUUll', 'ssoozzUOOl', '-soo-zzOOl'))),
            ('O-01 くるまDPC > パフェ', "\n".join(('----------', 'ilstttjjoo', 'ilsstzjcoo', 'illszzjccc', 'iccczccccc'))),
            ('O-01 くるまDPC > パフェ', "\n".join(('----------', 'illlssjjoo', 'iltsszjcoo', 'itttzzjccc', 'iccczccccc'))),
            ('O-01 くるまDPC > パフェ', "\n".join(('----------', 'izztttssoo', 'ijzztsscoo', 'ijjjlllccc', 'iccclccccc'))),
            ('O-02 JB DPC > 組み方', "\n".join(('-----s----', '-----ss--i', 'lllUUUsooi', 'loojUzzooi', '-oojjjzz-i'))),
            ('O-02 JB DPC > パフェ', "\n".join(('----------', 'izzlltttoo', 'ijzzlctsoo', 'ijjjlccssc', 'icccccccsc'))),
            ('O-02 JB DPC > パフェ', "\n".join(('----------', 'iljjjtttoo', 'ilzzjctsoo', 'illzzccssc', 'icccccccsc'))),
            ('O-03 ダブルハートDPC > 組み方', "\n".join(('----------', '-------s--', '-------ssi', 'lllzzUUUsi', 'loojzzUooi', '-oojjj-ooi'))),
            ('O-03 ダブルハートDPC > 組み方', "\n".join(('----------', '-------s--', '-------ssi', 'jjjooUUUsi', 'zzjoolUooi', '-zzlll-ooi'))),
            ('O-03 ダブルハートDPC > パフェ', "\n".join(('----------', 'izzlltttoo', 'ijzzlstcoo', 'ijjjlssccc', 'icccccsccc'))),
            ('O-03 ダブルハートDPC > パフェ', "\n".join(('----------', 'ilszztttoo', 'ilsszztcoo', 'illsjjjccc', 'icccccjccc'))),
            ('O-03 ダブルハートDPC > パフェ', "\n".join(('----------', 'iljjjtttoo', 'ilzzjstcoo', 'illzzssccc', 'icccccsccc'))),
            ('O-04 TSD DPC > 組み方', "\n".join(('----------', '-z--------', 'zz-------i', 'zUUUllooji', 'OOUsslooji', 'OOss-l-jji'))),
            ('O-04 TSD DPC > パフェ', "\n".join(('----------', 'llltttiiii', 'lcootzjjss', 'ccoozzjssc', 'cccczcjccc'))),
            ('O-04 TSD DPC > パフェ', "\n".join(('----------', 'llliiiissz', 'lcoojjsszz', 'ccoojtttzc', 'ccccjctccc'))),
            ('O-04 TSD DPC > パフェ', "\n".join(('----------', 'lllzooiiii', 'lczzoojjss', 'ccztttjssc', 'cccctcjccc'))),
            ('O-05a TKI DPC > 組み方', "\n".join(('----------', '---szz--oo', 'l--sszz-oo', 'lUUUsjjjOO', 'llUiiiijOO'))),
            ('O-05a TKI DPC > 組み方', "\n".join(('----------', '---jjj--oo', 'l--zzjs-oo', 'lUUUzzssOO', 'llUiiiisOO'))),
            ('O-05a TKI DPC > パフェ', "\n".join(('----------', 'tttzzllioo', 'stjjzzlioo', 'ssjccclicc', 'csjccccicc'))),
            ('O-05b TKI DPC別形 > 組み方', "\n".join(('----------', '---szz-oo-', 'l--sszzoo-', 'lUUUsjjjOO', 'llUiiiijOO'))),
            ('O-05b TKI DPC別形 > 組み方', "\n".join(('----------', '---jjj-oo-', 'l--zzjsoo-', 'lUUUzzssOO', 'llUiiiisOO'))),
            ('O-05b TKI DPC別形 > パフェ', "\n".join(('----------', 'tttzzllooi', 'stjjzzlooi', 'ssjccclcci', 'csjcccccci'))),
            ('O-05b TKI DPC別形 > パフェ', "\n".join(('----------', 'oojjssiiii', 'oojsstttll', 'zzjccctccl', 'czzccccccl'))),
            ('O-06 > 組み方', "\n".join(('----------', '-----s----', 'l----ss---', 'lzzUUUsjjj', 'llzzUooOOj', 'iiii-ooOO-'))),
            ('O-06 > パフェ', "\n".join(('----------', 'szztttllli', 'sszztclooi', 'csjjjccooi', 'ccccjcccci'))),
            ('O-06 > パフェ', "\n".join(('----------', 'jjjtttllli', 'zzjstclooi', 'czzssccooi', 'ccccscccci'))),
            ('O-06 > パフェ', "\n".join(('----------', 'llltttjjji', 'loostczzji', 'coosscczzi', 'ccccscccci'))),
            ('O-07 > 組み方', "\n".join(('----------', '------z---', '-----zz--j', 'llloozUUUj', 'lOOoossUjj', '-OO-ssiiii'))),
            ('O-07 > パフェ', "\n".join(('----------', 'ijjjtttlll', 'ioojztclss', 'ioozzccssc', 'icczcccccc'))),
            ('O-07 > パフェ', "\n".join(('----------', 'illltttjjj', 'ilssztcooj', 'isszzccooc', 'icczcccccc'))),
            ('O-07 > パフェ', "\n".join(('----------', 'llliiiijjj', 'lzstttcooj', 'zzsstccooc', 'zccscccccc'))),
            ('O-07 > パフェ', "\n".join(('----------', 'iiiitttloo', 'jjssztcloo', 'jsszzccllc', 'jcczcccccc'))),
            ('O-08 > 組み方', "\n".join(('----------', '--z-------', 'izz-------', 'izUUUllooj', 'iOOUsslooj', 'iOOss-l-jj'))),
            ('O-08 > パフェ', "\n".join(('----------', 'oollzziiii', 'ooclszzjjj', 'ccclsstttj', 'cccccsctcc'))),
            ('S-01 くるまDPC > 組み方', "\n".join(('----------', '-------s--', '-------ssi', 'SlljjUUUsi', 'SSljzzUooi', '-Slj-zzooi'))),
            ('S-01 くるまDPC > パフェ', "\n".join(('----------', 'ilstttjjoo', 'ilsstzjcoo', 'illszzjccc', 'iccczccccc'))),
            ('S-01 くるまDPC > パフェ', "\n".join(('----------', 'illlssjjoo', 'iltsszjcoo', 'itttzzjccc', 'iccczccccc'))),
            ('S-01 くるまDPC > パフェ', "\n".join(('----------', 'izztttssoo', 'ijzztsscoo', 'ijjjlllccc', 'iccclccccc'))),
            ('S-02 JB DPC > 組み方', "\n".join(('----------', '-----s----', '-----ss--i', 'SllUUUsooi', 'SSljUzzooi', '-Sljjjzz-i'))),
            ('S-02 JB DPC > パフェ', "\n".join(('----------', 'izzlltttoo', 'ijzzlctsoo', 'ijjjlccssc', 'icccccccsc'))),
            ('S-02 JB DPC > パフェ', "\n".join(('----------', 'iljjjtttoo', 'ilzzjctsoo', 'illzzccssc', 'icccccccsc'))),
            ('S-03 トラックDPC > 組み方', "\n".join(('----------', '------z---', '-----zz--i', 'oojjjzUUUi', 'oossjSSUli', '-ss-SSllli'))),
            ('S-03 トラックDPC > 組み方', "\n".join(('----------', '------z---', '-----zz--j', 'SlloozUUUj', 'SSloossUjj', '-Sl-ssiiii'))),
            ('S-03 トラックDPC > パフェ', "\n".join(('----------', 'illltttjjj', 'ilssztcooj', 'isszzccooc', 'icczcccccc'))),
            ('S-03 トラックDPC > パフェ', "\n".join(('----------', 'ijjjtttlll', 'ioojztclss', 'ioozzccssc', 'icczcccccc'))),
            ('S-03 トラックDPC > パフェ', "\n".join(('----------', 'llliiiijjj', 'lzstttcooj', 'zzsstccooc', 'zccscccccc'))),
            ('S-03 トラックDPC > パフェ', "\n".join(('----------', 'iiiitttloo', 'jjssztcloo', 'jsszzccllc', 'jcczcccccc'))),
            ('S-04 ダブルハートDPC > 組み方', "\n".join(('----------', '-------s--', '-------ssi', 'SllzzUUUsi', 'SSljzzUooi', '-Sljjj-ooi'))),
            ('S-04 ダブルハートDPC > パフェ', "\n".join(('----------', 'izzlltttoo', 'ijzzlstcoo', 'ijjjlssccc', 'icccccsccc'))),
            ('S-04 ダブルハートDPC > パフェ', "\n".join(('----------', 'ilszztttoo', 'ilsszztcoo', 'illsjjjccc', 'icccccjccc'))),
            ('S-04 ダブルハートDPC > パフェ', "\n".join(('----------', 'iljjjtttoo', 'ilzzjstcoo', 'illzzssccc', 'icccccsccc'))),
            ('S-05 ライムDPC > 組み方', "\n".join(('----------', '---oo-----', 'i--oo-----', 'iUUUsszzll', 'ijUssSSzzl', 'ijjjSS---l'))),
            ('S-05 ライムDPC > パフェ', "\n".join(('----------', 'slliiiittt', 'sslccoojtz', 'cslccoojzz', 'ccccccjjzc'))),
            ('S-05 ライムDPC > パフェ', "\n".join(('----------', 'jjjiiiiloo', 'zzjccllloo', 'czzcctttss', 'cccccctssc'))),
            ('S-05 ライムDPC > パフェ', "\n".join(('----------', '---------j', '---------j', 'llliiii-jj', 'looccsUUUz', 'cooccssUzz', 'ccccccs-zc'))),
            ('S-06a LongS DPC > 組み方', "\n".join(('----------', 'j---------', 'jjj-------', 'ooUUUziiii', 'oolUzzssSS', 'lll-zssSS-'))),
            ('S-06a LongS DPC > 組み方', "\n".join(('----------', 'j---------', 'jjj-------', 'ooUUUssSSz', 'oolUssSSzz', 'lll-iiiiz-'))),
            ('S-06a LongS DPC > パフェ', "\n".join(('----------', 'tttsslooji', 'ctsszlooji', 'ccczzlljji', 'ccczccccci'))),
            ('S-06a LongS DPC > パフェ', "\n".join(('----------', 'tttssjjlli', 'ctsszjooli', 'ccczzjooli', 'ccczccccci'))),
            ('S-06a LongS DPC > パフェ', "\n".join(('----------', 'zztttssooi', 'czztssjooi', 'cccllljjji', 'ccclccccci'))),
            ('S-06a LongS DPC > パフェ', "\n".join(('----------', 'tttssiiiil', 'ctsszoolll', 'ccczzoojjj', 'ccczcccccj'))),
            ('S-06b LongS DPC別形 > 組み方', "\n".join(('----------', '--l-------', 'lll-------', 'jjUUUziiii', 'jooUzzssSS', 'joo-zssSS-'))),
            ('S-06b LongS DPC別形 > 組み方', "\n".join(('----------', '--l-------', 'lll-------', 'jjUUUssSSz', 'jooUssSSzz', 'joo-iiiiz-'))),
            ('S-06b LongS DPC別形 > パフェ', "\n".join(('----------', 'ootttjjssi', 'ooctzjssli', 'ccczzjllli', 'ccczccccci'))),
            ('S-06b LongS DPC別形 > パフェ', "\n".join(('----------', 'ootttlllji', 'ooctzlssji', 'ccczzssjji', 'ccczccccci'))),
            ('S-06b LongS DPC別形 > パフェ', "\n".join(('----------', 'ootttsszji', 'ooctsszzji', 'ccclllzjji', 'ccclccccci'))),
            ('S-06c LongS DPC別形 > パフェ', "\n".join(('----------', 'cStttjjlli', 'cSStzjooli', 'ccSzzjooli', 'ccczccccci'))),
            ('S-06c LongS DPC別形 > パフェ', "\n".join(('----------', 'cStttlooji', 'cSStzlooji', 'ccSzzlljji', 'ccczccccci'))),
            ('S-06c LongS DPC別形 > パフェ', "\n".join(('----------', 'cSzztttooi', 'cSSzztjooi', 'ccSllljjji', 'ccclccccci'))),
            ('S-06c LongS DPC別形 > パフェ', "\n".join(('----------', 'cSzziiiioo', 'cSSzztttoo', 'ccSllltjjj', 'ccclcccccj'))),
            ('S-06c LongS DPC別形 > パフェ', "\n".join(('----------', 'cStttiiiil', 'cSStzoolll', 'ccSzzoojjj', 'ccczcccccj'))),
            ('S-07 ドリームDPC > 組み方', "\n".join(('----------', '----------', '----zz---i', 'jjUUUzzlli', 'jooUssSSli', 'joossSS-li'))),
            ('S-07 ドリームDPC > パフェ', "\n".join(('----------', '----------', '----------', 'iiiicctttc', 'ccccccctcc'))),
            ('S-07 ドリームDPC > パフェ', "\n".join(('----------', 'jjiiiitttz', 'joolllstzz', 'joolccsszc', 'cccccccscc'))),
            ('S-07 ドリームDPC > パフェ', "\n".join(('----------', 'jjziiiiloo', 'jzzssllloo', 'jzsscctttc', 'ccccccctcc'))),
            ('S-07 ドリームDPC > パフェ', "\n".join(('----------', 'looiiiijjj', 'loosstttzj', 'llsscctzzc', 'ccccccczcc'))),
            ('S-07 ドリームDPC > パフェ', "\n".join(('----------', 'zzllooiiii', 'jzzloosttt', 'jjjlccsstc', 'cccccccscc'))),
            ('S-08 > 組み方', "\n".join(('----------', '--------l-', '---ss---l-', 'oossUUUzll', 'oojjjUzzSS', 'iiiij-zSS-'))),
            ('S-08 > パフェ', "\n".join(('----------', 'jjzztttssi', 'joozztssci', 'joocclllci', 'ccccclccci'))),
            ('S-08 > パフェ', "\n".join(('----------', 'ootttssjji', 'ooltsszjci', 'lllcczzjci', 'ccccczccci'))),
            ('S-09 > 組み方', "\n".join(('----------', 'i-z-------', 'izz-------', 'izUUUoojjj', 'iSSUloossj', 'SSlll-ss--'))),
            ('S-09 > パフェ', "\n".join(('----------', 'tttloojjji', 'ctcloozsji', 'cccllzzssi', 'ccccczccsi'))),
            ('S-09 > パフェ', "\n".join(('----------', 'tttjjiiiil', 'ctcjszzlll', 'cccjsszzoo', 'cccccsccoo'))),
            ('S-09 > パフェ', "\n".join(('----------', 'tttjjjiiii', 'ctcoojzsll', 'cccoozzssl', 'ccccczccsl'))),
            ('S-09 > パフェ', "\n".join(('----------', 'tttllliiii', 'ctclsszooj', 'cccsszzooj', 'ccccczccjj'))),
            ('S-10 > 組み方', "\n".join(('----------', '----z-----', '---zz----j', 'SllzUUUssj', 'SSlooUssjj', '-Sloo-iiii'))),
            ('S-10 > パフェ', "\n".join(('----------', 'ijjjtttlll', 'ioojctzlss', 'ioocczzssc', 'icccczcccc'))),
            ('S-10 > パフェ', "\n".join(('----------', 'ijjjtttssz', 'ioojctsszz', 'ioocclllzc', 'icccclcccc'))),
            ('S-11 Fake Butter DPC > 組み方', "\n".join(('----------', '-----l----', '---lll----', 'sUUUzjjjoo', 'ssUzzSSjoo', '-s-zSSiiii'))),
            ('S-11 Fake Butter DPC > 組み方', "\n".join(('----------', '----j-----', '----jjj---', 'llloos---z', 'lSSooss-zz', 'SSiiiis-z-'))),
            ('S-11 Fake Butter DPC > パフェ', "\n".join(('----------', 'izztttjjll', 'iszztcjool', 'isscccjool', 'icsccccccc'))),
            ('S-11 Fake Butter DPC > パフェ', "\n".join(('----------', 'izztttlooj', 'iszztclooj', 'issccclljj', 'icsccccccc'))),
            ('S-12 > 組み方', "\n".join(('----------', '----j-----', '----jjj---', 'lllooSUUUz', 'lssooSSUzz', 'ssiiiiS-z-'))),
            ('S-12 > パフェ', "\n".join(('----------', 'jjlltttssi', 'joolctsszi', 'joolccczzi', 'ccccccczci'))),
            ('S-12 > パフェ', "\n".join(('----------', 'loojtttssi', 'loojctsszi', 'lljjccczzi', 'ccccccczci'))),
            ('S-13a > 組み方', "\n".join(('----------', '--oolll---', '-zoolss--j', 'zzSSss---j', 'zSSiiii-jj'))),
            ('S-13a > パフェ', "\n".join(('----------', 'ijjtzzlloo', 'ijtttzzloo', 'ijccccclss', 'iccccccssc'))),
            ('S-13a > パフェ', "\n".join(('----------', 'ijjsstzzll', 'ijsstttzzl', 'ijcccccool', 'iccccccooc'))),
            ('S-13b > 組み方', "\n".join(('----------', '---oojjj--', 'l--oozzjS-', 'lTTTsszzSS', 'llTssiiiiS'))),
            ('S-13b > 組み方', "\n".join(('----------', '---oojjj--', 'l--oossjS-', 'lTTTsszzSS', 'llTiiiizzS'))),
            ('S-13b > パフェ', "\n".join(('----------', 'oojjsstlli', 'oojsstttli', 'zzjcccccli', 'czzcccccci'))),
            ('S-13b > パフェ', "\n".join(('----------', 'jjsstzzlli', 'jsstttzzli', 'joocccccli', 'coocccccci'))),
            ('S-14 > 組み方', "\n".join(('----------', '-----oo---', '----loo---', '-zlllss--j', 'zzSSssUUUj', 'zSSiiiiUjj'))),
            ('S-14 > パフェ', "\n".join(('----------', 'itttsszzll', 'ijtsscczzl', 'ijjjcccool', 'iccccccooc'))),
            ('S-14 > パフェ', "\n".join(('----------', 'izztttlloo', 'ijzztccloo', 'ijjjccclss', 'iccccccssc'))),
            ('T-01 > 組み方', "\n".join(('----------', '------z---', 'j----zz--i', 'jjjsszUUUi', 'oossTTTUli', 'oo---Tllli'))),
            ('T-02 > 組み方', "\n".join(('----------', '----------', '-z-----lli', 'zzoosUUUli', 'zjoossUTli', '-jjj-sTTTi'))),
            ('T-03 > 組み方', "\n".join(('----------', '--------oo', '--------oo', 'l--iiiijjj', 'lUUUssTzzj', 'llUssTTTzz'))),
            ('T-04 > 組み方', "\n".join(('----------', 'jj------li', 'jUUUzsllli', 'jTUzzssooi', 'TTTz--sooi'))),
            ('T-04 > 組み方', "\n".join(('----------', 'jj------ss', 'jUUUzoossl', 'jTUzzoolll', 'TTTz--iiii'))),
            ('T-04 > パフェ', "\n".join(('----------', '----------', '----------', 'ccjjjlllcc', 'ccccjlcccc'))),
        ),
    ),
)
