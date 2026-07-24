# FlowJo v10 公式マニュアル機能要約

参照元: [FlowJo v10 Documentation](https://docs.flowjo.com/flowjo/)

確認日: 2026-07-13

## この文書について

この文書は、FlowJo公式Webマニュアルの全文転載やオフラインミラーではない。Flowdeskの要件分析に使えるよう、公式マニュアルに記載された概念、操作、画面、解析機能を日本語で構造化して要約したものである。詳細な手順、画面例、注意事項は各節の公式リンクを参照すること。

FlowJoは、FCSサンプル、ゲート、統計、表、グラフィカルレイアウトをWorkspaceにまとめ、保存後に同じ解析状態を再開できる統合環境である。典型的な解析は、サンプルを読み込み、群を作り、代表サンプルで解析を設計し、その解析を群へ展開して、表と図をバッチ生成する流れになる。

## 1. 基本ワークフロー

公式の[Getting Acquainted](https://docs.flowjo.com/flowjo/getting-acquainted/)が示す基本手順は次のとおり。

1. FCSサンプルをWorkspaceへ読み込む。
2. 関連するサンプルをGroupへ整理する。
3. 代表サンプルでゲート、統計、派生パラメータなどを設計する。
4. 設計した解析をGroup内のサンプルへ適用する。
5. サンプル間の分布差に応じて各ゲートを確認・調整する。
6. Layout Editorで複数サンプルの図を作る。
7. Table Editorで複数サンプルの統計表を作る。
8. 反復実験では、サンプルを含まないTemplateとして解析定義を再利用する。

解析対象は単独サンプルだけではない。Groupを単位にゲート、統計、表、図を反復適用し、実験全体を同じ方法で解析することがFlowJoの中核である。

## 2. Workspace、サンプル、メタデータ

### 2.1 Workspace

[Workspace](https://docs.flowjo.com/flowjo/workspaces-and-samples/ws-overview/)は次を保持する。

- 読み込んだサンプルとファイル参照
- GroupとGroupの役割
- サンプルまたはGroupに付与したゲート階層と統計ノード
- 取得時または解析時に定義した補償行列
- FCSキーワードとWorkspace内で追加した注釈
- Table Editorの表定義
- Layout Editorのレイアウト定義

通常のWorkspaceファイルはFCSイベント本体を内包せず、FCSファイルへの参照を保持する。サンプルが移動した場合は再接続が必要になる。状態バッジ、列、色、ステータス表示により、補償の有無、ファイル状態、Group所属などを確認できる。

### 2.2 サンプルとファイル

[Samples and File Types](https://docs.flowjo.com/flowjo/workspaces-and-samples/samples-and-file-types/)では、FCS、WSP/JO、ACSなどを扱う。サンプルまたはゲート済みイベントは外部解析用に書き出せる。サンプルプロパティから取得メタデータやキーワードを確認できる。

### 2.3 Group

[Groups](https://docs.flowjo.com/flowjo/workspaces-and-samples/ws-groups/)は、同じ解析を受けるサンプル集合である。Groupへゲートや統計を追加すると、既存メンバーだけでなく、後から加わったサンプルにも解析を適用できる。条件やキーワードに基づくGroup作成、Group編集、Group解析の削除、Group単位のバッチ処理を行える。

[Copying Gates](https://docs.flowjo.com/flowjo/graphs-and-gating/gw-gating/gw-gatecopying/)では、ゲート、統計、解析ノード、階層全体をサンプル、Population、Group、別Workspaceへドラッグして複製できる。コピー先の同一階層に同名Populationがある場合は置換を確認する。

### 2.4 KeywordsとAnnotation

[Keywords and Annotation](https://docs.flowjo.com/flowjo/workspaces-and-samples/keywords-and-annotation/)では、FCSヘッダーのキーワードをWorkspace列として表示し、解析用の注釈を追加・編集できる。検索置換、連番や系列の生成、Groupへの値コピー、表計算ソフトからの貼り付けに対応する。Workspace内の注釈変更はraw FCSを直接変更しない。

### 2.5 保存、Auto-Save、Template、Archive

[Saving your Analysis](https://docs.flowjo.com/flowjo/workspaces-and-samples/ws-savinganalysis/)では、通常Workspace、サンプルを除いたTemplate、FCSと解析をまとめたACS Archive、表形式の出力を使い分ける。[Auto-Save](https://docs.flowjo.com/flowjo/workspaces-and-samples/auto-save/)は設定した間隔でWorkspaceを保存する。[Templates](https://docs.flowjo.com/flowjo/advanced-features/maketemplate/)はGroup、ゲート、統計、表、レイアウトを新しい実験へ再適用する。[Archive Files](https://docs.flowjo.com/flowjo/workspaces-and-samples/archive-files/)は解析と関連データを一つの可搬コンテナにまとめる。

## 3. Graph Windowと表示

### 3.1 Graph Window

[The Graph Window](https://docs.flowjo.com/flowjo/graphs-and-gating/gw-overview/)はPopulationの表示、ゲート作成、統計追加の中心画面である。主なUIは次のとおり。

- ゲート作成ツール
- 現在のSampleとPopulation階層を示すbreadcrumb
- Undo/Redoと、親Population・前後Sampleへ移動するナビゲーション
- X/Yパラメータ選択
- 各軸の表示変換ボタン
- 2D/1Dプロット
- Graph複製と3D表示
- 表示オプション、Active Gate、Statisticsの各パネル

Populationごとに最後に使った軸、変換、表示形式を記憶する。同じPopulationを別のパラメータ対で同時表示するためにGraph Windowを複製できる。

### 3.2 プロット形式

[Data Visualization and Display](https://docs.flowjo.com/flowjo/graphs-and-gating/data-visualization-and-display/)は、二変量表示としてpseudocolor、contour、density、zebra、dot、統計heat mapなどを、一変量表示としてhistogramとCDFを提供する。表示ごとに解像度、平滑化、外れ値、前景色・背景色などを調整できる。

表示形式は解析対象イベントの定義と分離される。プロットの見た目を変えても、Populationそのものを別定義にしない。

### 3.3 軸変換

[Data Transformation](https://docs.flowjo.com/flowjo/graphs-and-gating/gw-transform-overview/)では、linear、log、biexponential、logicle、arcsinh、hyperlogなどを使って広いダイナミックレンジとゼロ近傍・負値を表示する。変換は記録済みrawイベントを書き換えず、表示と解析座標を定義する。

デジタルFCSでは、補償後に負値が生じ得るため、ゼロ近傍を線形的に、強い正値を対数的に表示するbiexponential/logicle系変換が重要になる。変換パラメータは補償行列やファイルに対応づけられ、同じ設定を再現できる必要がある。

### 3.4 Overlay、Backgating、Movie

複数Populationのhistogramやplotを重ねて比較できる。Backgatingは最終Populationを祖先の各ゲート図へ色付きで逆投影し、どの段階で細胞が選ばれたかを確認する。MovieはTimeまたは第三パラメータに沿って分布の時間変化を表示・出力する。

## 4. Gating

### 4.1 Population階層

[Gating](https://docs.flowjo.com/flowjo/graphs-and-gating/gw-gating/)は、親Population内のイベントから部分集合を作る操作である。作成されたPopulationは親の子になり、さらにその子をゲートして任意の深さの階層を作る。兄弟Populationは互いに独立した部分集合であり、同じ親の下で同名Populationは許可されない。

### 4.2 基本ゲート

FlowJoの基本ツールには次がある。

- Rectangle: 長方形領域
- Polygon/Pencil: 任意多角形または自由描画領域
- Ellipse: 楕円領域
- Range/Bisector: 一変量の範囲または閾値
- Quadrant: 共通交点で分割する4領域

ゲートは作成後に名前変更、頂点・辺・閾値編集、数値入力、コピー、削除ができる。ゲート内部のイベント数や親・全体に対する頻度を表示できる。

### 4.3 高度なゲート

[Advanced Gates and Gating Tools](https://docs.flowjo.com/flowjo/graphs-and-gating/advanced-gates/)には次が含まれる。

- Boolean/Boolean Combination: 既存PopulationをAND、OR、NOT系で合成
- Auto Gate: 確率密度や分布から領域を推定
- Magnetic Gate: 高密度領域に追従
- Quadrant、Offset Quadrant、Curly Quadrant、Auto-merged Quad
- Spider/BifurGate: 複数の接する領域で分割
- Manual Gate: 座標を数値入力
- Tethered Gate: percentile統計などに結び、サンプルごとに位置を追従
- Clone Gate: 同名ゲートの位置を同期

Boolean Populationも親Populationの制約を受け、元Populationへの参照と論理式を保存する。

### 4.4 バッチゲーティングとサンプル別調整

代表サンプルで作ったゲート階層をGroupへ適用し、各サンプルを前後に移動しながら位置を確認できる。Groupの共通定義を保ちつつ、分布差のあるサンプルではゲート位置を調整できる。解析のコピー、置換、同期の状態がUIから判別できる。

## 5. Compensation

[Compensation](https://docs.flowjo.com/flowjo/experiment-based-platforms/plat-comp-overview/)は、単染色controlから蛍光spilloverを推定し、multi-color sampleへ行列を適用する。主な流れは次のとおり。

1. Compensation Groupへcontrolを集める。
2. detector/parameterとpositive・negative controlを対応づける。
3. controlのcleanup gate、positive gate、negative gateを確認する。
4. 行列を計算し、診断plotと数値を確認する。
5. 行列に識別可能な名前を付け、sampleまたはGroupへ適用する。

[Compensation Matrix Editor](https://docs.flowjo.com/flowjo/experiment-based-platforms/plat-comp-overview/plat-comp-matrixwindow/)では、行列値、heat map、補償前後のhistogramまたは二変量plotを同時に確認し、複製した行列を手動編集できる。行列の由来、対象channel、control、編集履歴を区別することが重要である。

FlowJoはtraditional compensationに加え、spectral compensation、AutoSpill、autofluorescence extraction、spillover spreading matrixの表示を扱う。AutoSpillは反復回帰と自動化されたcontrol処理を用いるが、代表イベントを選ぶcleanup gateの確認は必要である。

## 6. Derived Parameters

[Derived Parameters](https://docs.flowjo.com/flowjo/experiment-based-platforms/derived-parameters/)は既存パラメータから新しいパラメータを作る。比、差、スケーリング、Time、Event Numberなどを定義し、Groupへ複製できる。派生パラメータはplot、gate、statistics、exportで通常のparameterと同様に参照される。

## 7. Statistics

[Statistics](https://docs.flowjo.com/flowjo/workspaces-and-samples/ws-statistics/)では、Populationに統計ノードを追加し、ゲート変更時やWorkspace再読込時に再計算する。代表例は次のとおり。

- Event count
- Frequency of parent、frequency of total
- Mean、median、mode
- Geometric mean
- Standard deviation、robust SD、CV、robust CV
- Median absolute deviation
- Percentile
- Parameter間の比や式からなるcustom formula

統計定義はPopulationとparameterを明示し、Workspace、Graph、Table、Layoutで同じ値を参照する。表や図に置いた値はゲート変更に追従する。

## 8. Table Editor

[Tabular Reports in the Table Editor](https://docs.flowjo.com/flowjo/tabular-reports/)は、Population統計、sample keyword、custom formulaを列として定義する。代表サンプルの定義をGroupへ反復し、全サンプル分の表を生成する。

主な機能は次のとおり。

- Population、statistics、keyword、formula列の追加
- 列名、数値書式、有効桁、非表示列の設定
- control値を固定したiteration
- Group、sample、population、keywordに基づくbatch/iteration
- heat mapとconditional formatting
- correlation、time series、line plot
- CSV、表計算形式、その他の表出力
- 表定義の保存と再計算

## 9. Layout Editor

[Graphical Reports in the Layout Editor](https://docs.flowjo.com/flowjo/graphical-reports/)は、plot、overlay、table、statistics、legend、図形、注釈をページ上へ配置するレポートエディタである。Populationを配置してtemplate tileを作り、Group内のサンプルへbatch展開する。

主な機能は次のとおり。

- plotの追加、複製、整列、グループ化、サイズ変更
- overlay、backgating、adjunct histogram
- live statistics、table、equation、legend
- 線、矩形、grid、textなどの描画・注釈
- sampleまたはkeywordによるiteration、filtered batching
- interactive layout、printer、HTML、animation、PowerPoint、PDF、画像への出力

## 10. Specialized analysis platforms

[Platforms](https://docs.flowjo.com/flowjo/experiment-based-platforms/)は通常のゲート・統計を超える解析を提供する。

### 10.1 Cell Cycle

DNA量分布へmodelをfitし、G0/G1、S、G2/Mなどの割合を推定する。model、制約、background/debris、doublet処理を調整し、別sampleへ同じmodelを展開する。

### 10.2 Proliferation

[Proliferation](https://docs.flowjo.com/flowjo/experiment-based-platforms/proliferation/)はCFSEなどの希釈ピークを世代modelへfitし、generation gate、division index、proliferation index、percent divided、世代別countなどを算出する。

### 10.3 Kinetics

[Kinetics](https://docs.flowjo.com/flowjo/experiment-based-platforms/kinetics/)はTimeに対するparameterまたはstatisticsの変化を解析する。時間区間を手動または自動設定し、最大応答、応答時刻、傾き、反応細胞率などを求める。Timeがない場合は一定流速を仮定した近似Timeを作れる。

### 10.4 Population Comparison

[Population Comparison](https://docs.flowjo.com/flowjo/experiment-based-platforms/population-comparison/)はtest Populationと一つ以上のcontrol Populationの分布を比較する。overlay/CDF/difference plotと、Overton percent positive、Kolmogorov-Smirnov系指標、probability binningなどを提供し、結果をTable Editorへ送れる。

### 10.5 Plate Editor

well位置へsampleを対応づけ、plate metadataを編集し、CSVからannotationを読み込み、titrationやplate-based assayを整理・可視化する。

### 10.6 FCS ScanとPlatform Overlay

多数ファイルの品質やparameter分布を一括確認し、platform固有のmodelや結果を複数sampleで重ねて比較する。

## 11. Advanced features and automation

[Advanced Features](https://docs.flowjo.com/flowjo/advanced-features/)には次がある。

- Command Lineによるheadless batch実行
- Templateによる解析再利用
- ACSによる解析・data・plugin outputの一括保存
- 次元削減、clustering、Cluster Explorer、結果の新規sampleへのforward propagation
- R toolsとScript Editorによる自動化
- plugin APIとExchangeから導入するPopulation/Workspace plugin
- remote dataとcloud連携
- FCSメタデータのde-identification
- spectral plot、spectral population viewer、panel評価指標

[Plugins](https://docs.flowjo.com/flowjo/plugins-2/)はPopulationへ作用する型とWorkspaceイベントへ作用する型に分かれ、外部解析結果を派生parameterやPopulationとしてWorkspaceへ戻せる。

## 12. Preferences、品質、操作支援

[Setting Your Preferences](https://docs.flowjo.com/flowjo/setting-your-preferences/)では、Workspace表示、plot/output、platform、toolの既定値を管理する。軸変換、表示形式、色、font、数値桁、exportなどを設定し、既定値へresetできる。

操作上は次が重要である。

- Undo/Redo
- keyboard shortcutとcontext menu
- breadcrumbと前後sample・親Population navigation
- context-sensitive help
- auto-saveとrecovery
- status badge、解析のstale/invalid表示
- 大規模データ向け表示解像度とperformance設定

## 13. FlowJoを参照するときの科学的注意

- raw event、補償済みevent、派生parameter、変換座標、gate membershipを混同しない。
- display downsamplingやplot binningを、明示なしにgate membershipへ使用しない。
- compensation matrix、transform parameter、control assignment、gate座標、statistics definitionを解析状態として保存する。
- Groupへ同じ解析を適用した場合でも、sample固有のchannel metadata、matrix、gate overrideを追跡する。
- TableやLayoutの値は、同じWorkspace定義をheadless実行して得る値と一致する必要がある。
- ソフトウェア間で統計値を比較するときは、rawイベント上の統計か、変換・binning後の統計かを確認する。

## 14. 主要な公式参照ページ

- [FlowJo v10 Documentation](https://docs.flowjo.com/flowjo/)
- [Getting Acquainted](https://docs.flowjo.com/flowjo/getting-acquainted/)
- [Workspaces and Samples](https://docs.flowjo.com/flowjo/workspaces-and-samples/)
- [Graphs and Gating](https://docs.flowjo.com/flowjo/graphs-and-gating/)
- [Table Editor](https://docs.flowjo.com/flowjo/tabular-reports/)
- [Layout Editor](https://docs.flowjo.com/flowjo/graphical-reports/)
- [Platforms](https://docs.flowjo.com/flowjo/experiment-based-platforms/)
- [Advanced Features](https://docs.flowjo.com/flowjo/advanced-features/)
- [Preferences](https://docs.flowjo.com/flowjo/setting-your-preferences/)
