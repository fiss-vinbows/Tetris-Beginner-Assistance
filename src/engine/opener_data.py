"""開幕テンプレの盤面図データ。

テトリス堂(https://shiwehi.com/tetris/)の各テンプレページに掲載されている
テキスト盤面図を、ページのセクション(1巡目/2巡目/3巡目)ごとに写したもの。
このファイルは scratchpad の gen_opener_data.py で自動生成した(手で編集しない)。

記号: '-'=空、'c'/'C'=既に置いてあるブロック、小文字=この巡で置くミノ、
大文字(J/L/S/Z/I)=ホールドしてあったミノ、'U'=Tスピンで入れるT。
下の行ほど盤面の下(最下行が盤面の最下段)。
"""

from __future__ import annotations

# (日本語名, 英語名, 出典URL, ((セクション名, 盤面図), ...))
OPENER_SOURCE_FORMS: tuple[tuple[str, str, str, tuple[tuple[str, str], ...]], ...] = (
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
