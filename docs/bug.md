# plot画像のexport仕様

- plot area で右クリックにexportメニューを追加 -> png, jpg, svg, pdf 形式で保存可能にする
- Batch plot export などで複数のplotを一括でexportできるようにする
- その時のexport のファイル名はファイル名にWell名(A1, B2など)がある場合は、ファイル名の一番前にWell名を付与するようにする
- export後の画像を並べたときに、x, y 軸の軸スケールや軸の位置、ラベル、tics が揃うようにする
- 左のリストでoverlay などが有効になっているなら、その状態を反映した画像をexportするようにする
- export するときに、タイトルを入れるか、x label や y label を変更するか選べるようにする
- plot area の表示が再現されるよにexportすること。例えば、gate color が設定されているときは、export した画像でも gate color が反映されるようにする. また、ゲートが表示されているなら、export した画像でもゲートが表示されるようにする
- export 先のディレクトリを選んで実行すると、fcsファイルごとにexportされた画像が保存されるようにする
- plot area の縦横比は1:1でexportされるようにする
- overlay などで複数のplotが含まれる場合、ファイル名は1つの場合のファイル名を連結したものにしてください。例えば、A1とB2のplotの場合、overlay なしならA1.png, B2.pngになりますが、overlay ありの場合はA1_B2.pngのようにしてください.


