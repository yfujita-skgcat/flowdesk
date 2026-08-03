
# その他
- New した直後は Statistic ID が変更可能ですが、このとき <population名>_<Metric>_<Value domain>_<重複を避けるためのpostfix> を自動生成するようにしてください。Population targets, Metric, Value domain が変更されるたびに更新してください。また、一度決定(OKボタンを押した)したあとは、変更すると他の部分(このStatistic IDを参照しているコード)に影響があるため、変更しないようにしているのですよね? そうではれば、一度決定したあとEdit Statisticsで変更したときはstatistic IDは変更しないようにしてください。IDをあとから変更しても他に影響しないのであれば変更するようにしてください。
- Derived Paramters の挙動についても Edit Statistic と似たような挙動にしてください.
  - 最初は何もない.
  - New で追加する.
  - Definition ID について他の部分から参照されているなどで、あとで変更されると困る場合は、変更できないようにする. そうでなければOKで一度ダイアログを閉じ、再度開いたときにも変更できるようにする.
  - Definition ID は、new したときに自動生成するようにする. <Name>_<Source stage>_<expression(ある程度内容がわかる上で、短くなるように工夫する)>_<重複を避けるためのpostfix> で生成する.
  - Definition ID は、Source stage 等が変更されたときに自動更新するようにする. ただし、一度OKしたあと変更されると困る場合は、再度Derived Paramtersダイアログを開いたときにはIDは自動で更新されないようにする.
  - 左のリストに表示される文字列は、dervied parameter の内容がある程度わかるように工夫して表示する。
  - その他Edit Statistics と似たような挙動にする。


- close project を実装して、プロジェクトを閉じられるようにする
- File menu にあるopen directory とか open file とかはなに? 不要なら削除する。
- plot area に表示するパラメータ(APC-A)に名前を追加する様にしたい。例えば、iRFP670 (APC-A) などのようにしたい。
  - Channels パネルの一覧はプロジェクトで共通にする.
  - すべてのサンプルから集めたParameter 全部を


- Channels タブのParameterは現在ファイルごとに表示されているという認識だがあっているか? 例えばパラメータに別名をつけることを考えた場合、複数のファイルについて全部設定しないといけないのは面倒だが、Channels のParameterをプロジェクト内の全パラメータを表示して共通にしなかった理由はなにか?

下の表は、以下のようにしたらいいのでは?
実際のパラメータ                                plot area で一般的に使われるパラメータ名    実際の蛍光物質名など自由に記入できる項目
FL1-A                                           FITC-A                                      GFP
derived_parameterID                             Name (derived parameterの名前)              GFP / iRFP670

左の Samples の Rel の項目は必要ありますか? ほとんど意味をなしていないように見えます。
