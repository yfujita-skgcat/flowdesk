# Flowdesk機能拡張仕様

作成日: 2026-07-13

比較基準: [flowjo-manual.md](flowjo-manual.md)

対象: 現在のFlowdeskリポジトリ

## 1. 目的

Flowdeskを、Linuxを第一対象としながら、FlowJoに近い実験単位のflow cytometry解析環境へ発展させる。本仕様はFlowJoの画面をそのまま模倣することではなく、次の価値を実現することを目的とする。

- 科学的に正しい処理順序と完全な解析来歴
- GUIで作成した解析をCLI/Python APIでも同じ結果で再実行できること
- 多数sampleへ一貫した解析を適用し、差異だけを確認・調整できること
- ゲート、統計、表、図を一つのprojectに保存し、反復実験へ再利用できること
- raw FCS eventsを不変に保ち、補償、派生parameter、変換、gate、statisticsを派生状態として扱うこと

## 2. 現状評価

### 2.1 実装済みの基盤

現行コードとテストから、次は実装済みと判断する。

- FCS metadata/eventsの読込とsynthetic FCSの書込
- FCS spillover metadataの抽出
- user/imported compensation matrixの表現、channel alignment検証、matrix適用
- 安全なASTベースderived parameter式
- linear、log、asinh、`logicle_like`変換
- rectangle、polygon、range、boolean gate
- parent-child gate hierarchy、reparent、Boolean editor
- gate作成時のlinear/log10/asinh座標系の保存とheadless gate評価
- full event membership mask、count、frequency of parent/total
- `.flowdesk` directory project、JSON schema、save/load
- GUI、CLI、Python APIが共通の`PipelineRunner`を使用
- population選択によるplot filtering
- scatter、1D Count histogram、top/right marginal histogram
- `PlotViewSpec`、dot/scatter/histogram/CDF/density/pseudocolor/contourのGUI非依存display preparation
- `OverlaySpec`/`BackgatingSpec`、full membershipを使う1D/2D overlay/backgating preparation、GUI display layer API
- GUI-localなscatter color/size/opacity、background、gate color設定
- CSV/TSV population result export、PNG/SVG/PDF plot exportと基本metadata sidecar
- GUI test harness、callback exception検出、headless consistency tests

### 2.2 FlowJoとの機能差

| 領域 | 現在のFlowdesk | 不足度 | 本仕様 |
|---|---|---:|---|
| FCS/sample管理 | ファイル追加、metadata表示、削除 | 中 | S01, S02 |
| Group/annotation | `group_id`の最小fieldのみ。編集・動的Group・batch UIなし | 大 | S02 |
| Compensation | coreで既存行列を適用可能。controlからの算出・matrix GUIなし | 大 | S03 |
| Derived parameters | coreのみ。GUI editorと明示的error policyが不足 | 中 | S04 |
| Transforms | 基本変換あり。ただし`logicle_like`は近似で、FlowJo互換性を保証しない | 大 | S05 |
| Gating | rectangle/polygon/range/booleanと階層あり | 中 | S06, S07 |
| Batch gating | 全sampleに一つのstrategyを適用可能。Group template、copy、override確認UIなし | 大 | S08 |
| Plot | B6のplot type/display preparation/export基盤あり。完全なpresentation model/editorは未実装 | 中 | S09 |
| Backgating/overlay | B7のPopulation overlay/backgating基盤あり。cross-sample source model/editorは未実装 | 中 | S10 |
| Statistics | count/frequencyとcoreの基本関数はあるが、保存可能なstatistics definition/UIがない | 大 | S11 |
| Table Editor | fixed population exportのみ | 大 | S12 |
| Layout Editor | PNG exportのみ | 大 | S13 |
| Project safety | save/loadあり。undo/redo、autosave、recovery、migration UIなし | 中 | S14 |
| Templates/archive | なし | 大 | S15 |
| Interoperability | FCS中心。GatingML/WSP/ACS等なし | 大 | S16 |
| Specialized platforms | なし | 大 | S17-S21 |
| Plugin/scripting | CLI/Python APIはあるがplugin contractなし | 中 | S22 |
| Performance/QC | scatter downsamplingはあるが大規模benchmark、sample QC、cache policyが未完成 | 大 | S23 |
| Preferences/help/accessibility | GUI-local plot style等の局所controlのみ。優先順位付きproject/global presentation defaultsは未実装 | 中 | S24 |

### 2.3 現行実装で先に是正すべき科学的リスク

1. `logicle_like`は簡略近似であり、published LogicleやFlowJo Biexと数値同値ではない。名称、永続化、gate座標に対して誤解を生む。
2. `PipelineRunner`は複数sampleに一つの`channel_names`を渡すAPIを中心としており、sampleごとにchannel順序やidentityが違う場合の安全性が不足する。
3. derived parameter評価失敗時に、runnerが例外を捕捉してNaN列へ置換する経路がある。失敗がreportで明示されず解析が続くのは危険である。
4. statistics関数は存在するが、どのPopulation、parameter、source stage、transformで計算したかを保存する定義modelがない。
5. project schemaの多くが自由形式で、参照整合性、version migration、sample別compensation/transform/channel mappingの検証が弱い。
6. derived parameter追加後のchannel identityを後続stageへ渡すAPIが明確でなく、配列列と`channel_names`がずれる危険がある。
7. project-level transformとgateが保持するaxis scaleが独立に適用され得るため、同じparameterを二重変換しない一貫した座標modelが必要である。

これらはUI拡張より先に解消する。

## 3. 全機能に共通する必須原則

### 3.1 処理順序

すべての解析は次の順序を維持する。

```text
raw FCS events
  -> compensation
  -> derived parameters
  -> transform
  -> gate membership
  -> population statistics
  -> export
```

### 3.2 Headless parity

- 科学的結果を変えるGUI操作はproject modelへ保存する。
- GUIはproject stateを編集し、`PipelineRunner`を呼び、結果を表示するだけにする。
- GUI内でcompensation、gate membership、statistics fitを再実装しない。
- 同一project、同一input、同一software versionではGUI/CLI/Python APIのevent countと数値結果を一致させる。

### 3.3 Data immutabilityと座標

- raw event arrayはread-onlyとし、すべてのstageで新しいview/resultを返す。
- display-downsampled eventsをgate、statistics、histogram count、model fitへ使わない。
- geometric gateはparameter identity、source stage、axis transform ID、作成座標系を保持する。
- viewの軸変換がgate定義と異なる場合、gateを暗黙変換して編集しない。定義に一致するviewへ移動するか、明示的な複製操作を使う。

### 3.4 Provenanceとerror policy

- input file fingerprint、FCS metadata、matrix、transform、gate、statistics definition、software/pipeline versionをExecutionReportへ記録する。
- 欠損channel、参照切れ、fit失敗、NaN/Inf、unsupported FCSはsample単位で構造化diagnosticを返す。
- error、warning、skipを区別する。errorを暗黙にNaNやzeroへ変換しない。
- 部分成功時は成功sampleと失敗sampleを明示し、exportにstatus列を含められるようにする。

## 4. 目標ユーザーワークフロー

### W1. 実験を読み込み、整理する

ユーザーは複数FCSまたはdirectoryを読み込み、keyword列を表示し、condition、donor、panel、plateなどでGroupを作る。channel対応が不一致のsampleは読み込み時に警告され、解析開始前に修正できる。

### W2. Compensationを作成する

単染色controlをCompensation Groupへ割り当て、detectorごとのpositive/negative Populationを確認し、matrixを算出する。補償前後plot、residual、condition number、spreading diagnosticを見て承認し、対象Groupへ適用する。

### W3. 代表sampleでgating strategyを作る

複数Graphを開き、rectangle/polygon/ellipse/range/quadrantを使って階層を作る。breadcrumbとPopulation treeは同期し、Undo/Redoが使える。別軸で子Populationを作り、Boolean、backgating、overlayで妥当性を確認する。

### W4. Groupへ解析を展開する

strategyまたはsubtreeをGroupへ適用し、前後sampleを同じ軸・表示で巡回する。共通定義とsample-specific overrideを区別し、override一覧から外れたgateを監査できる。

### W5. 統計表と図を作る

Population、parameter、metric、keyword、formulaをTable Definitionへ追加し、Groupでbatch生成する。Layoutへplot、overlay、statistics、table、annotationを配置し、PDF/SVG/PNGへ再現可能に出力する。

### W6. 保存、再実行、再利用する

projectを保存し、autosave/recoveryを利用する。CLIで同じprojectを実行して同じ結果を得る。サンプルを除いたtemplateを次の実験へ適用し、input対応の差を解決して再実行する。

## 5. 詳細仕様

### S01. Sample catalogとchannel identity [P0]

#### 機能

- sampleごとにpath/URI、file size、mtime、hash、FCS version、event count、channel一覧、keywords、spillover sourceを保持する。
- channelは配列位置ではなく安定IDで参照し、`$PnN`、`$PnS`、detector、stain名、indexを区別する。
- sampleごとのchannel mappingをPipeline inputとして渡す。全sample共通`channel_names`依存を廃止または互換wrapperに限定する。
- file missing/moved時の再接続UIを提供し、hashとmetadataで候補を照合する。
- sample import時にduplicate、同名別path、channel order差、parameter不足を診断する。

#### UI

- Workspace左paneをsample tableにし、表示列を選択可能にする。
- filter、sort、multi-select、keyword column、status badgeを提供する。
- Sample Properties dialogでraw metadataを閲覧できるが、raw FCSは変更しない。

#### 受け入れ条件

- channel順序が異なる2 sampleで同じmarker指定の解析結果が正しい。
- sampleを移動後に再接続してもfingerprint不一致を検出する。
- import/exportを通してunknown FCS keywordsを失わない。

### S02. Groupとannotation [P1]

#### Model

- `SampleGroupSpec`: id、name、role、color、membership rule、explicit sample IDs、analysis bindings。
- `AnnotationSpec`: keyword name、value、source (`fcs`/`workspace`/`imported`)、sample ID、type。
- membership ruleは安全な比較式のみとし、任意Pythonを実行しない。

#### UI

- All Samples、Compensation Controlsとuser groupをWorkspaceに表示する。
- Group作成・編集、sample drag/drop、keyword条件によるdynamic membership、CSV annotation import、fill series、find/replaceを提供する。
- 同一sampleの複数Group所属を許可する。

#### 受け入れ条件

- Groupへ結び付けたstrategy/statisticsが既存と新規memberへ適用される。
- workspace annotation編集でFCS file bytesが変わらない。
- GUIで作成したdynamic GroupをCLIで同じmember集合として解決できる。

### S03. Compensation workspace [P0/P1]

#### Core

- matrixのsource、control sample、positive/negative Population、channel mapping、algorithm、parameter、作成時刻、software version、manual edit履歴を保存する。
- sample/Groupごとにmatrix bindingを持たせ、一つのglobal defaultだけに依存しない。
- traditional compensationをsingle-stain controlから計算する。使用した回帰法とbackground定義を明示する。
- matrix singular/ill-conditioned、missing detector、non-finite、order mismatchを拒否する。
- compensation diagnosticsを構造化結果として返す。

#### UI

- Compensation Controls roleのsample assignment。
- detector × control table、positive/negative Population selector。
- editable matrix heat map、補償前後preview、residual plot。
- matrix複製後のmanual edit。元matrixは変更しない。
- Group/sampleへの適用とbadge表示。

#### 後続範囲

- spectral unmixing、AutoSpill/autofluorescence extraction、spreading matrixはtraditional compensation完成後の独立仕様とする。

#### 受け入れ条件

- known synthetic spilloverから許容誤差内でmatrixを復元する。
- channel order違いでも名前/ID alignmentで同じ補償結果になる。
- GUI preview、headless result、exported valuesが一致する。
- raw eventsが不変である。

### S04. Derived Parameter Editorとerror policy [P0]

- GUIでname、expression、source stage、input parameter、unit、invalid-value policyを編集する。
- syntax highlight、parameter挿入、preview、validation error位置を提供する。
- pipelineは式評価失敗を黙って全NaNにしない。`fail_sample`、`fail_run`、明示的`emit_nan_with_warning`からprojectで選ぶ。
- derived parameter間の依存順序を解決し、cycleを拒否する。
- derived stageは追加後のchannel specsとevent columnsを一体で返し、後続transform/gateへ渡す。
- canonical orderに反する既存`source_stage = transformed`は新規作成を禁止し、migration時に明示的errorまたは互換実行として報告する。raw値を入力に使う場合も、derived parameterを追加するstage自体はcompensation後・transform前に固定する。
- statistic/gate/exportが安定IDでderived parameterを参照する。

### S05. Scientifically defined transforms [P0]

- `logicle_like`を正式なLogicle実装へ置換するか、非互換の近似であることが明確なlegacy typeへmigrationする。
- linear、log、arcsinh、Logicleを、式・parameter・inverse・domain policy付きで実装する。
- Biexを実装する場合はFlowJo互換を名乗る数値fixtureと許容誤差を文書化する。互換検証できない場合は独自type名にする。
- transformはparameter/channelおよび必要ならcompensation bindingに対応づける。
- tick generation、inverse coordinate conversion、gate evaluationが同じtransform objectを使う。
- project-level parameter transformとgate axis transformを同じID参照へ統合し、pipelineで一度だけ適用する。display-only view transformとの違いをmodelで明示する。
- transform変更時、異なる座標定義のgateを暗黙変形しない。`Show Gate`、定義複製、明示migrationを提供する。

### S06. Gate engine拡張 [P1]

- ellipse、quadrant、offset quadrantをcore modelとrunnerに追加する。
- boundary inclusion規則、NaN/Inf規則、overlap規則を型ごとに定義する。
- manual numeric editorを全geometric gateに提供する。
- Boolean expressionを二項listだけでなくnested expression treeとして表現し、AND/OR/NOTの優先順位をUIで可視化する。
- gate rename、duplicate、subtree delete、copy/paste、multi-selectをUndo可能にする。
- auto/magnetic/tethered/clone gateは、algorithmとsample-specific resultを分離したmodelを設計してから実装する。

### S07. Gating definitionとResults workspace UX [P1]

- Gate definitionの編集と、sampleへ適用したResultsの閲覧を別workspaceとして表示する。
- `active_sample_id`、`selected_gate_id`、`display_population_id`を独立した状態として扱う。
- Gate hierarchyのselectionは編集対象とoutline highlightを変更するが、plotの表示Populationを暗黙変更しない。
- `Show Gate`はgateの親Population、対応axes/scale、gate outlineを表示する。
- Results workspaceをPopulation count、% parent、% total、Statistic resultの唯一の表示面とする。
- gate変更時も現在のsample、表示Population、axes、scale、zoomを維持する。
- gate変更直後は、変更gateおよびdescendantの旧値を残したまま`recalculating`と表示する。
- active sampleをGUI非依存core pipelineでbackground再計算し、完了した同一revisionの結果をResultsとplotへatomicに反映する。
- active sampleの更新済み行は`current`、他sampleの影響を受ける行は`stale`とする。
- stale/recalculatingなplot membershipを表示する場合は明確なbannerを表示し、current resultとして誤認させない。
- Result rowはrevisionとsource provenanceを内部で保持する。表示上の`current`はそのsample rowが現在定義と一致することを表し、multi-sample batchがcurrentであることを意味しない。
- `Run Pipeline`は全sample、Group、QC、diagnostics、exportのauthoritative実行境界として維持する。
- breadcrumbで祖先へ移動し、前後sampleを同じPopulation pathとviewで巡回する。
- subtreeをdrag/dropまたはCopy Analysis操作で別Population、sample、Groupへ複製する。
- invalid parent、cycle、missing source、duplicate sibling nameを操作確定前に表示する。
- gate definition側にはsource axes/scale、shared/override statusを表示し、count、% parent、% total、Statistic resultはResults workspaceで表示する。

### S08. Group strategy、template gate、sample override [P1]

- Group共通strategyとsample-specific gate position overrideを別objectで保存する。
- overrideは元definition ID、差分、作成者、時刻、理由を保持する。
- Groupへsubtreeを適用したとき、channel/marker mappingを検証してからatomicに反映する。
- sample navigatorで同じviewを保ったまま全sampleを確認する。
- override一覧、missing Population、異常frequency、edge-clipped gateをQC panelへ表示する。
- reset-to-group、promote-override-to-group、copy-to-selectedの差異を明示する。

### S09. Graph Window拡張 [P1]

- dot/scatter、pseudocolor、density、contour、zebra相当、histogram、CDFを提供する。
- 表示集計はfull selected Populationから作り、rendering downsampleと科学計算を分離する。
- plot type、stable parameter IDs、transform IDs、range、aggregation、rendering設定、presentation参照を`PlotViewSpec`として保存する。
- 複数Graph tab/window、duplicate view、linked sample navigationを提供する。
- gate作成中、selection、pan/zoomのmodeを視覚的に区別する。
- plot上にPopulation名、count、frequency、axis scale、compensation stateを選択表示する。
- SVG/PDF/PNG exportにtitle、axis、legend、gate labelを含め、metadata sidecarを出力できる。

#### Plot presentation definition

- 保存可能なdisplay-only definitionとして、plot title、optional subtitle/annotation、X/Y axis display label、legend visibility/position/order、sourceごとのlegend labelを表現する。
- scatter/dotではsourceごとのcolor、alpha、marker shape、marker sizeを表現する。
- line系表示ではline color、line width、line styleを、histogramではfill、outline、alphaを表現する。
- plot background、gate outline color/width/line style、plot typeごとのsupported colormapを表現する。
- title、axis label、tick、legendのfont family、size、weight等を、backendで検証可能なdisplay definitionとして表現する。
- automatic style assignmentとmanual overrideを区別し、manual overrideのないsourceだけをdeterministicな自動割当対象とする。
- internal parameter IDとaxis display labelは別fieldとする。axis display labelを変更してもparameter ID、transform、gate coordinate、membership、statisticsを変更しない。
- plot typeごとにsupported style matrixを定義し、unsupported styleを黙って無視せずvalidationまたはstructured diagnosticにする。

### S10. Overlayとbackgating [P1]

- 複数Populationの1D/2D overlayを色、line、normalization方式とともに保存する。
- normalizationはcount、mode、unit areaなどを明示する。
- backgatingはtarget membershipを各ancestor viewへ投影し、targetとparent backgroundを区別する。
- GUIはrunnerが返したfull membershipを使用し、再gateしない。
- overlay/backgating definitionをLayoutへ配置し、headless renderできる。

#### Overlay source model

- 各overlay sourceはstable source ID、sample ID、population IDまたはmapping可能なpopulation path/role、表示名、X/Y parameter ID、X/Y transform ID、visibility、orderを保持する。
- active sampleとは独立したsource一覧として保存し、異なるsampleの同じPopulation pathだけでなく、明示的に選択した異なるPopulationも同じplotへoverlayできる。
- GUIからsourceを追加、削除、並べ替え、表示/非表示にでき、その状態をprojectへ保存する。
- missing sample、missing Population、missing channelをzero eventsや空layerへ変換せず、source identityを含むstructured diagnosticとGUI状態を表示する。
- channel mappingがambiguousな場合はuser confirmationなしに推測しない。

#### Scientific compatibility

- overlay sourceは同じsemantic parameter、軸、transform、unitへ一意に解決できる場合だけ同じplotへ描画する。
- sample間でchannel orderが異なってもstable channel identityでparameterを解決する。
- incompatible、ambiguous、missingなsourceはstructured diagnosticとGUI表示で拒否し、silent fallbackしない。
- sourceのcolor、label、marker、line、alpha、font等はdisplay-only definitionとし、gate membership、count、frequency、Statistic resultを変更しない。
- rendering downsampleはoverlay描画だけに適用し、membership、normalizationの入力event集合、statisticsを変更しない。

#### Export and reuse

- GUI previewとPNG/SVG/PDF exportは同じoverlay source順とplot presentation definitionを使用する。
- export metadata sidecarへsource sample/population、parameter IDs、transform IDs、source順、visibility、style definition、diagnosticを記録する。
- Layout Editorは同じplot presentation definitionを参照するか、明示的に複製したsnapshotを使用する。Layout側で科学計算を再実装しない。
- Templateへ保存するsourceは、必要に応じsample IDそのものではなくmapping可能なsample role、population path/role、parameter roleを保持し、適用時にmapping planとuser confirmationを要求できるようにする。
- font fallbackやrenderer backend差による完全なpixel一致は保証しないが、source順、label、style semantics、objectの欠落、blank outputは検証する。

### S11. Statistics definitions [P0/P1]

#### Model

- `StatisticSpec`: id、name、population reference、parameter reference、metric、source stage、transform/binning policy、settings、format。
- count、frequency parent/total、mean、median、geometric mean、mode、SD、CV、MAD、robust SD/CV、percentileを段階的に実装する。
- raw-event statisticsとdisplay-binned statisticsを別metric/policyとして区別する。既定はfull event values上の明示的NaN-aware計算とする。
- custom formulaは他statistics IDとkeywordsだけを安全な式で参照する。

#### UI

- Population treeまたはGraphからAdd Statistic dialogを開く。
- metric、parameter、percentile、formatを選び、結果をlive nodeとして表示する。
- gate/transform/matrix変更時に依存statisticsをstale化する。
- active sampleの依存statisticsはbackground current-sample実行後にResults workspaceへatomicに反映する。
- 他sampleのstatisticsは`Run Pipeline`までstaleとし、authoritative export/QCにはcurrentなbatch resultだけを使用する。

#### 受け入れ条件

- definitionをproject save/load後も保持する。
- GUI、CLI export、Python APIが同じ値とundefined理由を返す。
- empty Population、all-NaN、zero denominatorのpolicyをfixtureで固定する。

### S12. Table Editor [P1]

- `TableDefinitionSpec`と`TableColumnSpec`をprojectへ保存する。
- 列sourceはsample keyword、Population statistic、platform result、safe formula、constantとする。
- row iterationをsample、Group、Population path、plate wellから選択可能にする。
- column reorder、rename、number format、hidden、sort、filter、conditional formattingを提供する。
- previewとbatch generationを同じcore table runnerで実行する。
- CSV/TSVを必須、XLSXをoptional dependencyとして提供する。
- exportにproject ID、run ID、pipeline version、input fingerprintをsidecarまたはmetadata sheetとして含める。

### S13. Layout Editorとheadless rendering [P2]

- page、grid、plot、overlay、table、statistic text、legend、shape、annotationのscene modelを保存する。
- objectの位置・sizeはdevice-independent unitで保持する。
- align、distribute、group、lock、duplicate、z-order、multi-select、Undo/Redoを提供する。
- sample/Group/keyword iterationとfiltered batchを定義する。
- GUI previewとheadless rendererが同じlayout modelを使用する。
- plot/overlay objectはS09/S10のpresentation definitionを参照するか、provenance付きで複製する。Layout固有の位置・size・annotation overrideと科学計算を分離する。
- PNG、SVG、PDFを優先し、HTML/PowerPointは後続とする。
- font fallbackとmissing glyphをdiagnosticに記録する。

### S14. Undo/Redo、autosave、recovery、migration [P0]

- project mutationをcommandとして記録し、gate作成/編集/削除/reparent、annotation、matrix binding、table/layout editをUndo/Redo可能にする。
- scientific result cacheはUndo historyに直接埋め込まず、state hashで無効化する。
- atomic save、autosave interval、crash recovery、read-only recovery openを提供する。
- schema versionごとのforward migrationを実装し、migration前backupとreportを作る。
- newer unsupported versionを黙って書き換えない。

### S15. Templateとportable archive [P1/P2]

- Templateはsample eventsを含めず、Group rules、channel roles、compensation setup、gating strategies、statistics、tables、layoutsを保持する。
- template適用時にmarker/channel mapping wizardを開き、曖昧対応をユーザー確認する。
- portable archiveはproject、FCS、derived/plugin outputs、checksums、manifestをまとめる。
- archive展開時はpath traversal、checksum mismatch、duplicate IDsを拒否する。

### S16. Interoperability [P2]

- GatingML 2.0 import/exportを最初の交換形式とする。
- unsupported gate/transformは無視せず、構造化compatibility reportを返す。
- compensated/derived/gated PopulationのFCS exportでは元metadata、追加metadata、event selection、parameter namingを明示する。
- WSP importは別projectとして段階実装し、まずsample reference、compensation、basic gates、hierarchy、transformsのread-only importから始める。
- FlowJo固有Biexやplugin nodeを完全変換できない場合はopaque metadataとwarningを保持する。
- de-identification toolは削除keywordのpreview、policy file、audit reportを提供し、元FCSを上書きしない。

### S17. Plate workspace [P2]

- 6/12/24/48/96/384 well plate、well-to-sample mapping、condition、dose、replicateをmodel化する。
- CSV paste/import、well selection、heat map、missing/duplicate well診断を提供する。
- Group、Table、Layout iterationがplate metadataを参照できる。

### S18. Kinetics platform [P3]

- Population、time parameter、response parameter/statistic、time windows、baseline policyを保存する。
- Time欠損時のevent-number近似は仮定したflow rateと警告を必須にする。
- max、time-to-max、slope、AUC、responding fractionをfull membershipで計算する。
- manual/automatic range fitのalgorithm versionとfit diagnosticsを保存する。

### S19. Proliferation platform [P3]

- dye parameter、generation 0、generation count、peak ratio、CV constraints、background/modelを保存する。
- generation model、fit residual、uncertainty、division index、proliferation index、percent dividedを出力する。
- model fitとgeneration gate生成を分離し、生成gateのprovenanceを保持する。
- reference implementationまたはpublished synthetic datasetsで数値検証する。

### S20. Cell Cycle platform [P3]

- DNA parameter、model type、G1/G2 constraints、background、debris、doublet policyを保存する。
- G0/G1、S、G2/M割合、fit residual、convergence statusを出力する。
- model failureを成功値として表示せず、diagnosticとmanual initial valuesを提供する。

### S21. Population Comparison [P3]

- test/control Population集合、parameter、normalization、statistics methodを保存する。
- histogram/CDF/difference overlayとKS、Overton、必要に応じprobability binningを実装する。
- multiple comparison、minimum event count、zero/empty control policyを明示する。
- methodごとにpublished definitionとnumeric fixtureを用意する。

### S22. Extension APIとautomation [P2]

- CLI/Python APIをversioned public surfaceとして文書化する。
- pluginは別processを既定とし、input Population reference、allowed outputs、resource limits、version、provenanceをmanifestで宣言する。
- plugin出力はderived parameter、Population、table、artifactとして明示的にimportする。
- project内scriptの任意自動実行を禁止し、信頼確認とsandbox policyを設ける。
- GUIなしのbatch queue、sample selector、output directory、failure policyをCLIで指定できる。

### S23. Performance、cache、QC [P0-P2]

- 10万、100万、1000万eventsのsynthetic benchmark profileを用意する。
- display downsamplingは決定的seed/algorithmを選べ、選択Populationのrare eventを消す危険をUI表示する。
- cache keyはinput fingerprintと全上流definition hashを含む。
- matrix/derived/transform/gate変更時の無効化境界をtestする。
- memory budget、cancel、progress、sample-level parallelismをrunner APIへ追加する。
- QC panelにfile/channel mismatch、event count anomaly、time discontinuity、boundary pileup、compensation warning、gate frequency outlier、overrideを表示する。

### S24. Preferences、help、accessibility [P2]

- global preferenceとproject display settingを分離する。
- plot defaults、number format、autosave、performance、theme、font、export defaultsを設定する。
- display styleの優先順位は、plot/view単位の明示override、project display default、global preference、built-in defaultの順とする。各layerはpresentationだけを上書きし、stable parameter/source identityや科学定義を変更しない。
- reset、import/export preferenceを提供する。
- stable Qt objectName、keyboard navigation、shortcut一覧、color-onlyでないstatus表現、context helpを備える。
- scientific defaultを変更したときは既存projectの解析結果を暗黙変更しない。

## 6. 優先順位とrelease境界

### Release A: Scientific foundation

S01、S03のmatrix binding/diagnostics、S04、S05、S11、S14のschema migration、S23のcorrectness benchmarkを完了する。既存MVPを科学的に監査可能な状態にする。

### Release B: Experiment-scale gating

S02、S06、S07、S08、S09、S10、S14のUndo/Autosaveを完了する。Groupへstrategyを適用し、全sampleを効率良く確認できる状態にする。

### Release C: Reports and reuse

S12、S13、S15、S16のGatingML/FCS export、S17を完了する。表・図・template・交換形式を提供する。

### Release D: Specialized analysis and ecosystem

S18-S22、S24を段階的に実装する。各scientific platformは独立releaseとし、数値検証なしに一括実装しない。

## 7. 非目標

- FlowJoのライセンス管理、商標、画面デザインを複製しない。
- 初期releaseで全FlowJo pluginや全vendor formatとの完全互換を約束しない。
- cloud連携をlocal projectの科学的再現性より優先しない。
- approximate algorithmを互換実装として表示しない。
- specialized platformをUIだけ先に作らない。core model、runner、numeric validationが先である。

## 8. Test strategy

### 8.1 Core tests

- synthetic eventsで各stageの既知値を固定する。
- property-based testsでgate boundary、channel permutation、NaN/Inf、empty Populationを検証する。
- raw input arrayのbytesとwriteabilityが変化しないことを検証する。
- serialization round-tripとschema migrationを検証する。

### 8.2 Reference tests

- Logicle、compensation、platform modelはpublished equationまたは独立実装のfixtureと比較する。
- FlowJoと比較したfixtureを使用する場合、FlowJo version、transform setting、matrix、input hash、export procedureを記録する。
- 数値差を単に「見た目が近い」で承認しない。

### 8.3 GUI tests

- screen coordinateではなくstable objectNameとwidget stateを使用する。
- fixed sleepを避け、signal/event loopで完了を待つ。
- callback exception、QThread shutdown、stale resultを厳格に検出する。
- GUI count/statisticsと同じprojectのheadless `PipelineRunner`結果を完全一致させる。

### 8.4 Performance tests

- scientific countはevent数に関係なく同じであることを検証する。
- rendering benchmarkとanalysis benchmarkを分離する。
- benchmark regressionは環境情報とdataset seedを記録する。

## 9. Definition of Done

各仕様項目は次をすべて満たしたときだけ完了とする。

1. 対応する`docs/implementation/*.md`がproduction codeより先に追加・更新されている。
2. core modelとproject schemaで表現できる。
3. GUIなしで`PipelineRunner`または専用headless runnerから実行できる。
4. GUIは同じcore APIを使用する。
5. save/load、CLI再実行、exportのround-trip testがある。
6. scientific edge cases、invalid input、diagnosticがtestされている。
7. GUI対象機能はoffscreen GUI testと必要なE2E testがある。
8. `ruff`、`mypy`対象、core tests、GUI tests、full suiteが成功する。
9. READMEとuser-facing操作説明が更新される。
10. remaining limitationと非互換性が明記される。
