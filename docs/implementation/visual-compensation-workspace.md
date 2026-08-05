# Visual Compensation Workspace Implementation Guide

Spec: `S03`
ToDo: `Phase A5.V`

## 1. 目的

単色controlから得たspillover matrixを数値だけで編集する現在の画面を、係数と
補償前後plotが相互に連動するreview/fine-tuning workspaceへ発展させる。

ユーザーが選択した一つの`source detector -> receiving detector`係数について、
同じcontrol eventを使ったUncompensated/Compensated plot、現在値、自動計算値、
残差diagnosticを同時に確認できるようにする。visual previewは判断支援であり、
科学計算の別実装や多色sampleの相関をゼロへ合わせる自動操作にしてはならない。

## 2. 実装前に必ず読むもの

次の順に全文を読む。

1. `AGENTS.md`
2. `docs/specs.md`の`S03`
3. `ToDo.md`の`Phase A4`、`A5`、`A5.V`
4. `docs/implementation/llm-task-protocol.md`
5. `docs/implementation/compensation-engine.md`
6. `docs/implementation/compensation-workspace.md`
7. `docs/implementation/interactive-current-sample-preview.md`のscheduler contract
8. `.codex/skills/compensation/SKILL.md`
9. `.codex/skills/qt-plot-widget/SKILL.md`
10. `.codex/skills/scientific-review/SKILL.md`

一度のLLM実行では、Section 14のincrementを一つだけ実装する。schema、core、
scheduler、GUI統合を一度に変更しない。

## 3. 現行実装の監査結果

### 3.0 このincrementで実装済みの範囲

次の実装を完了した。後続LLMはこれらの契約を置き換えず、Increment 5以降だけを
追加すること。

- `flowdesk_core.compensation_preview`に、immutable request/result、candidate全体を
  適用する補償前後配列、共有axis range、full-resolution pair diagnosticを追加した。
- `flowdesk_qt.compensation_preview_scheduler`に75 ms debounce、single worker、
  latest-wins、revision照合、shutdownを実装した。workerはQt widgetやlive projectを
  参照しない。
- `CompensationMatrixEditorDialog`はリサイズ可能な補償前後PlotWidget、matrix cellと
  source→receiving説明、percent表示の係数spinbox/slider、Reset、diagnosticを持つ。
- 通常のMainWindow起動経路からsampleのraw events、channel ID、全event population maskを
  workspaceへ渡す。control populationは未指定時に診断をundefinedとし、任意の多色sampleの
  相関を補償正解とは扱わない。
- calculated matrixは引き続きread-onlyで、`Save as Copy`を編集入口とする。raw eventと
  original matrixを変更しない。manual edit provenanceはcandidate matrixへ記録する。
- `CompensationWorkspaceDialog`がControls & Calculate、Matrix Preview、Application /
  Bindingsを同じSave and Apply/Cancel境界に組み込む。既存の`calculate_spillover_matrix()`を再利用し、GUI側に
  別の補償計算式を持たない。
- workspace起動時にはreportがfreshな場合だけsampleごとのpopulation masksを渡し、stale
  な場合はall_eventsのみを安全な候補として渡す。control populationが未解決のまま
  silentに別sampleへ置換されることはない。

この段階では、control populationを自動的に推定する機能、Undo/Redo、project round-tripを
含むworkspace E2E検証は未完了である。後続incrementで実装し、既存のA4/A5の計算・binding
経路を再実装してはならない。

### 3.1 保持する基盤

- `CompensationMatrixSpec`はstable channel ID、matrix、source、provenanceを保持する。
- matrixは`row = receiving detector`、`column = single-stain source detector`である。
- `apply_compensation()`はchannel IDで列をalignmentし、matrix inverseをraw eventの
  fluorescence blockへ適用した新しいarrayを返す。raw inputは変更しない。
- `calculate_spillover_matrix()`はexplicit control sample、positive/negative
  Population、background subtraction、outlier policyを使用する。
- calculated matrixはimmutable resultであり、manual editはduplicateへ保存する。
- binding resolver、condition number、ExecutionReport provenanceは既存のcanonical
  headless pathを使用する。

これらをQt側で再実装してはならない。

### 3.2 現在不足している点

- `MainWindow._on_edit_compensation()`は通常のMatrix Editor起動時に`sample_data`を
  渡していないため、通常操作ではpreview dataがない。
- `CompensationMatrixEditorDialog`のpreviewは、先頭最大10 eventについてraw値と
  compensated値を表に並べるだけで、分布、傾き、外れ値、軸範囲を確認できない。
- Matrix EditorとCalculation Editorが分離され、cell、control sample、diagnostic、
  bindingの関係が画面上で追跡しにくい。
- 現在の`residual_rms`はcalculation時のsource control単位diagnosticである。
  選択したsource/receiving pairのmanual candidateに対するresidual slope等とは
  同一ではない。既存fieldの意味を変更して流用しない。

## 4. 採用するユーザーワークフロー

最初の完成形は、リサイズ可能な大きいdialogとして実装する。modeless化はproject
revision競合、window close、複数workspaceのcommit競合を別途解決するまで行わない。

```text
Compensation Workspace
  Controls & Calculate
    detectorごとのcontrol sample / positive / negative Population
    Calculate
  Matrix Preview
    matrix cell selection
      -> source/receiving/controlを解決
      -> Before / After plot
      -> coefficient slider + numeric input
      -> pair diagnostic
  Application / Bindings
    matrixをsample / group / execution profileへ適用するbinding
    scopeとtargetの確認
```

### 4.1 新規計算

1. `Controls & Calculate` tabで`Compensation Controls` roleのGroupまたはexplicit sampleからcontrolを選ぶ。
2. detectorごとにsample、positive Population、negative Populationを指定する。
3. staleでないfull-resolution membershipを確認する。
4. existing core calculation APIでmatrixを計算する。
5. 全pairをreviewする。
6. calculated matrixをimmutable resultとして保存する。
7. sample/Group bindingを明示的に適用する。

Bindingsは係数を表すMatrixとは別に、どの対象へどのMatrixを適用するかを保存する。
単一matrixの調整時に混乱しないよう、Matrix Previewからは分離し、Application / Bindings
tabで編集する。既存のbinding model、resolver、project schemaは変更しない。

### 4.2 既存matrixの確認・微調整

1. FCS metadata、imported、user-defined、calculated matrixを選ぶ。
2. control provenanceがある場合は対応controlを自動選択する。複数候補や参照切れは
   推測せず、ユーザーに選択または修正を求める。
3. off-diagonal cellを選択し、Before/Afterとdiagnosticを確認する。
4. 必要なら`Save as Copy`用candidateを作成して係数を調整する。
5. originalを変更せず、新matrixを保存する。
6. binding変更はmatrix保存とは別操作で行う。

control provenanceがないmatrixでは、任意sampleの分布previewは許可するが、
`residual slope is acceptable`等のsingle-stain diagnosticを表示しない。通常の多色
sampleに存在する生物学的共発現を補償誤差と解釈してはならない。

## 5. 画面構成と操作契約

### 5.1 Matrix方向を明示する

matrix tableには次の固定headerを表示する。

```text
columns: Source channel (spill from) ->
rows:    Receiving channel (spill into) down
```

選択cellの説明はstable IDとproject display labelを使い、例えば
`FITC-A -> PE-A: spill from FITC-A into PE-A, 3.420%`とする。

- 対角cellは内部値`1.0`、表示`100%`で固定し編集不可とする。
- off-diagonal cellだけをfine-tuning対象にする。
- 係数cell一つの変更でも、preview計算は必ずmatrix全体を反転して適用する。
  逆行列のため、選択pair以外のcompensated値にも影響し得ることを隠さない。
- 表示名だけをidentityとして保存しない。保存・計算はstable channel IDを使う。

### 5.2 Before / After plot

cell `(receiving=PE-A, source=FITC-A)`を選択した場合:

- sample: FITC single-stain control
- X: source detector `FITC-A`
- Y: receiving detector `PE-A`
- left: Uncompensated raw source/receiving values
- right: candidate matrix適用後のcompensated source/receiving values

両plotは次を完全に共有する。

- sample IDとPopulation mask
- event identityとdisplay subset
- X/Y transform definition
- X/Y axis range
- point size、alpha、density color設定
- non-finite handlingと表示件数

軸rangeは片方ずつauto-rangeしてはならない。両側のfinite valuesのunionから一度だけ
求めるか、ユーザーが固定した同一rangeを使う。片側だけのrange変更は禁止する。

### 5.3 補償前後plotの同期契約

補償前後plotは単に初期rangeを一致させるだけでは不十分である。次の項目を同一の
preview request/resultから設定する。

- sample、population mask、event identity、display subset、display max points
- X/Y channel、表示用transform、非有限値の除外規則
- 初期X/Y range（raw/compensatedの有限値union）
- マウスホイールによるzoom、ドラッグによるpan、ViewBoxの現在X/Y range
- point size、alpha、density/single color、grid、背景、軸ラベル

Sample titleとPopulation / gateをpreview selectorで選択し、不要な細胞を表示対象から
除外できる。X transform / Y transformはLinear、Log10、Asinhを表示用に選択できる。補償計算は常に
raw eventへcanonical compensationを適用し、transformはpreview描画と表示range/tickだけに
使う。軸ラベルとheat map headerは短いproject display labelを表示し、stable channel IDは
tooltipと内部データで保持する。

ViewBoxの`sigRangeChanged`は左右双方へ接続し、片側のzoom/panをもう片側へコピーする。
同期中フラグで再帰的なsignal連鎖を防ぐ。科学計算結果やraw eventは変更せず、表示状態
だけを同期する。将来どちらか一方だけを操作可能にする場合は、明示的なUIモードとして
追加し、既定では同期を維持する。

係数変更やFine adjustmentでは、変更前のViewBox rangeを保存して新しいpreview結果へ
復元する。Sample、Population、transformの変更は比較対象自体が変わるため保存rangeを
破棄し、coreが返す新しい共有rangeを使用する。

補償後の蛍光値は負になり得る。Log10で表示不能なeventを黙って除外して見栄えを
改善してはならない。linear、asinh、正式Logicle等から明示的に選び、現在transformで
表示不能なevent数をdiagnosticとして示す。

### 5.3 coefficient editor

選択cellに対し以下を一組だけ表示する。

- `Automatic/source coefficient`
- `Candidate coefficient`
- `Difference`（percentage points）
- local slider
- finite decimal numeric input
- `Reset to source value`
- `Undo` / `Redo`

UI既定表示はpercent、内部matrix値はfractionとする。

```text
UI 3.420% <-> persisted 0.03420
```

percent/fractionの単位をcontrol横へ常時表示し、変換をwidget callbackごとに重複実装
しない。pure helperを一つだけ作りtestする。負の係数と100%超を許容する。sliderは
現在値を中心とするlocal adjustment用であり、科学的なvalid rangeを定義しない。
slider外のfinite値はnumeric inputで受理し、sliderを再中心化する。silent clamp禁止。

初期slider windowはsource valueの前後5 percentage pointsを推奨するが、これは
presentation設定でありmatrixへ保存しない。stepは0.001 percentage point以下を扱える
ようにする。数値入力中のincomplete/invalid textはpreview requestを発行しない。

### 5.4 状態表示

常に次の3状態を区別して表示する。

1. `Source matrix`: projectに保存済みで変更しないmatrix。
2. `Candidate matrix`: dialog内だけに存在する未保存copy。
3. `Applied matrix`: binding resolverが対象sampleへ実際に選んだmatrix。

同じIDに見せたり、candidateをappliedとしてbadge表示してはならない。candidateがdirty
な状態でmatrix/sampleを切り替えるときはDiscard、Save as Copy、Cancelを明示する。

## 6. Core API contract

新規GUIより先にGUI非依存の同期APIを追加する。推奨moduleは
`src/flowdesk_core/compensation_preview.py`である。既存`compensation.py`を過度に肥大化
させないが、matrix alignment/applicationは既存public APIを呼ぶ。

### 6.1 Typed request

最低限、次をimmutable dataclassへ保持する。

```text
CompensationPreviewRequest
  request_id / revision
  sample_id
  source_matrix_id
  candidate_matrix_spec
  source_channel_id
  receiving_channel_id
  population_id
  positive_population_id | None
  negative_population_id | None
  raw_events (read-only input)
  ordered_channel_ids
  population masks
  display_max_points
  deterministic sampling seed/policy
  display transforms
  explicit outlier policy when a calculation spec exists
```

arrayをproject JSONへ埋め込まない。requestはruntime objectである。Qt widget、QObject、
mutable live project dictionaryをcoreへ渡さない。

### 6.2 Typed result

```text
CompensationPreviewResult
  request_id / revision
  sample_id and population IDs
  source/receiving stable IDs
  source matrix ID and candidate matrix hash
  uncompensated display x/y
  compensated display x/y
  shared display event indices
  shared axis/transform metadata
  full event count and displayed event count
  pair diagnostic or explicit undefined reason
  matrix inspection result / condition number
  structured diagnostics
```

返却arrayはQtから科学結果として再利用できないことを型・命名・docstringで明示する。
full-resolution diagnosticとdisplay arraysを別fieldにする。

### 6.3 候補matrix適用

- `inspect_compensation_matrix()`でshape、finite、channel alignment、conditionを検証する。
- fatal matrixはplotを更新せず、最後に成功したpreviewへ`stale`表示を重ねる。
- `apply_compensation()`で全fluorescence blockへcandidate matrixを適用する。
- raw blockをその場で変更しない。
- display transformはcompensation後に適用する。
- candidate matrixはrunnerのauthoritative cacheやproject stateへ挿入しない。

## 7. Pair diagnosticの科学的定義

single-stain controlとpositive/negative Populationが明示されている場合だけ計算する。
既存calculation specのoutlier policyを使い、同じevent inclusionを保持する。新しい暗黙の
outlier policyをGUIが選ばない。

候補補償後のsourceを`x`、receivingを`y`とし、negative Population medianを各channel
から引いたpositive eventを`x'`、`y'`とする。finiteかつ既存policyで採用されたeventに
対して次を計算する。

```text
residual slope = dot(x', y') / dot(x', x')
correlation = Pearson correlation(x', y')
receiving median difference = median(y_positive) - median(y_negative)
```

- denominatorが0、varianceが0、event不足、non-finiteの場合は値`0`を返さず、stable
  undefined reasonを返す。
- positive count、negative count、excluded/non-finite/outlier countを併記する。
- automatic coefficient、candidate coefficient、差分を返す。
- condition numberはmatrix全体について既存inspection結果を使う。
- 現在の`CompensationCalculationChannelDiagnostic.residual_rms`は意味を変更しない。
  pair用には別の`CompensationPairDiagnostic`を追加する。
- tolerance、warning threshold、良否判定はreferenceまたはsynthetic validationで根拠を
  文書化するまで自動合否にしない。最初は数値とundefined/warningだけを表示する。

## 8. Display subsetとfull-resolutionの分離

drag中のplot更新は、対象Populationからstable event indexに基づきdeterministicに最大
10,000–20,000 eventを抽出してよい。同じrequest条件では同じindexを返す。

次は常にfull-resolution eventで計算する。

- residual slope/correlation/median difference
- event/outlier/non-finite count
- matrix validationとcondition number
- 保存matrix値
- binding、pipeline、statistics、export

`display_max_points`を変更してもこれらが変化しないtestを必須とする。

## 9. 非同期preview contract

`ProcessedDisplayScheduler`の設計を参照し、compensation専用schedulerを
`src/flowdesk_qt/compensation_preview_scheduler.py`へ置く。既存schedulerへcandidate
matrix固有の意味を無理に追加しない。

- debounce: 50–100 ms、既定75 ms。
- worker count: 1。
- pending requestは常に最新一件へ置換する。
- running requestを強制終了しない。
- result revision、matrix hash、sample、pair、Populationがcurrent stateと一致した場合だけ
  GUI threadで採用する。
- obsolete resultをcache、plot、diagnosticへ反映しない。
- workerはwidgetを読み書きしない。
- dialog close時にtimer/pendingを停止し、thread pool完了を安全に待つ。

slider drag中はdisplay resultを優先する。slider releaseまたはnumeric value commit後に
full-resolution diagnostic requestを発行する。同じrevisionのdisplay/diagnostic resultを
混同しない。

## 10. 保存、provenance、binding

### 10.1 Save as Copy

manual candidateは必ず新しいstable matrix IDで保存する。

- original/calculated/imported matrixをin-place変更しない。
- `source`は既存duplicate policyに従う。
- `provenance.derived_from_matrix_id`へsource IDを保存する。
- dirty cellごとに`CompensationManualEditSpec`を保存する。
- 同一sessionで同じcellを複数回動かした場合、source old valueからfinal new valueまでを
  一件へconsolidateする。途中操作はtransient Undo historyとし、projectを肥大化させない。
- old/newはfractionで保存する。
- row/columnはstable channel IDで保存する。
- optional reason未入力を許す場合も、edited_at/editorは可能な範囲で記録する。

### 10.2 Apply

SaveとApplyを一つの暗黙操作にしない。Applyは保存済みmatrix IDだけを対象にする。

- scopeとtargetを明示する。
- 既存bindingとのpriority/conflictをcore resolverでpreflightする。
- 成功時にanalysis revisionを一度だけ進め、compensation以降をstale化する。
- candidate previewをauthoritative resultへ昇格しない。`Run Pipeline`が必要である。
- Cancel時はmatrix、binding、revision、results stale stateを変更しない。

新しいpersisted fieldが必要になった場合は、core model→schema→migration→round-trip testの
順に実装する。preview slider range、selected tab、selected pairは科学definitionではない
ため、matrixへ保存しない。

## 11. Qtの責務

推奨target:

- new: `src/flowdesk_qt/compensation_workspace.py`
- new: `src/flowdesk_qt/compensation_preview_scheduler.py`
- modify: `src/flowdesk_qt/main_window.py`
- transitional modify: `src/flowdesk_qt/compensation_editor.py`
- reuse: current canonical plot scene/widget APIs

Qtが行ってよいこと:

- request snapshot作成とcore API呼出し
- slider/spinbox同期
- matrix cell、plot、diagnostic表示
- revision/latest-wins管理
- project commandの発行

Qtで禁止すること:

- matrix inverse、background subtraction、regression、correlationの計算
- channel IDを表示名やcolumn位置から推測
- gate membershipの再計算
- raw event arrayの変更
- display subsetからdiagnosticを計算
- widget値を直接project dictionaryへ逐次書込み

## 12. Plot backendの再利用

新しいscatter rendererを作らない。Main plot/Exportで使うcanonical plot scene、transform、
tick、density color、point styleの共通部を再利用する。ただしpreviewはinteraction専用で、
authoritative export sceneとして保存しない。

Before/Afterのplot parity testでは、pixel screenshotだけでなく次のscene metadataを比較する。

- sample、Population、event indices
- X/Y parameter IDs
- transform IDs
- data range
- title/axis label
- point count

## 13. Errorとwarning

最低限、stable codeを用意する。

- `compensation_preview_control_missing`
- `compensation_preview_population_missing`
- `compensation_preview_population_stale`
- `compensation_preview_pair_invalid`
- `compensation_preview_transform_unsupported`
- `compensation_preview_insufficient_events`
- `compensation_preview_nonfinite`
- existing matrix inspection error/warning codes

errorをidentity matrix、uncompensated success、空plotへ変換しない。最後に成功したplotを残す
場合は`stale preview; current candidate failed`と明示する。

## 14. Increment別LLM指示

### Increment 1: Core request/resultとdiagnostic

対象:

- `src/flowdesk_core/compensation_preview.py`
- 必要最小限の`src/flowdesk_core/models.py`
- `tests/test_compensation_preview.py`

非対象: Qt、schema、binding UI、pairwise view。

test-firstで、2-channel asymmetric synthetic events、negative background、channel order
permutation、invalid matrix、zero variance、display limit差を固定する。手計算可能な小配列で
residual slope等を検証し、raw arrayのbytesとwriteable flagを前後比較する。

### Increment 2: Scheduler

対象:

- `src/flowdesk_qt/compensation_preview_scheduler.py`
- `tests/gui/test_compensation_preview_scheduler.py`

非対象: production workspace UI。fake executorでdebounce、pending replacement、obsolete
result rejection、exception delivery、shutdownをtestする。固定sleepではなくsignal/event loopを
使う。

### Increment 3: Matrix/plot連動

対象:

- `src/flowdesk_qt/compensation_workspace.py`
- `src/flowdesk_qt/main_window.py`
- current plot scene adapter
- `tests/gui/test_compensation_workspace.py`

非対象: coefficient編集、保存、Calculation Editor統合。最初はread-only candidateで、cell
選択から正しいsource/receiving/control/axesが解決され、同一event indexのBefore/Afterが
描画されることをtestする。

### Increment 4: Candidate editとSave as Copy

対象:

- core percent/fraction helperまたはcandidate builder
- workspace controls
- project command/model/schemaは必要な場合だけ
- core/storage/GUI tests

非対象: binding applyとPairwise overview。original不変、Reset、Undo/Redo、invalid text、
negative/>100%、manual edit consolidation、Cancel無変更をtestする。

### Increment 5: Controls/Application統合

既存Calculation Editorのcore-backed挙動をworkspaceへ移し、旧dialogは一時的なthin adapterに
する。二つのscientific calculation pathを残さない。Save、Apply、Run Pipelineの境界と
stale statusをE2E testする。migration期間終了後だけunused UI/codeを削除する。

実装対象は`src/flowdesk_qt/compensation_workspace.py`と`MainWindow`の起動・commit経路である。
`CompensationCalculationEditorDialog`と`CompensationMatrixEditorDialog`はworkspace内の
canonical formとして再利用する。各editorの科学計算を複製した別実装を作らない。

### Increment 6: Pairwise overview

上記すべてのacceptance test完了後だけ開始する。thumbnailはread-only、click navigation、
lazy rendering、bounded cacheを実装する。1 pairごとの独立event copyやsliderを作らない。

## 15. 必須test matrix

### Core

- identityとknown asymmetric matrix。
- channel order permutation。
- missing/duplicate/nonfinite/singular/ill-conditioned channel/matrix。
- raw event immutability。
- negative compensated values。
- positive/negative mask不足とstale参照。
- pair diagnostic known valueとundefined reason。
- display downsampleを変えたfull diagnostic不変性。

### GUI

- stable objectNameでmatrix cell、sample、Population、slider、numeric inputを操作する。
- row/column方向とX/Y mappingが逆転しない。
- Before/Afterが同じevent indices/ranges/transformsを使う。
- rapid slider eventsでlatest resultだけ採用する。
- invalid candidateでlast valid resultをstale表示する。
- calculated matrixが編集不能で、Save as Copy後だけ編集可能になる。
- Cancelでprojectがbyte-equivalent、Saveで新ID/provenance、Applyでbindingだけが変わる。
- dialog close後にQThread/QRunnable callbackがwidgetへ到達しない。

### GUI/headless/storage

- GUI candidate previewと直接core APIのcompensated valuesが一致する。
- 保存copyをbindingしてPipelineRunnerを実行した値がpreview full valuesと一致する。
- project save/load後にmatrix、manual edits、binding、report provenanceが一致する。
- CLI/Python APIがGUIをimportせず同じmatrixを適用する。

## 16. Performance acceptance

開発用referenceとして、20,000 display events、8–12 detector程度で以下を目標に計測する。
絶対値をtest timeoutのpass/failへ直結させず、benchmark artifactへ記録する。

- slider停止からpreview request開始: debounce込み100 ms程度。
- cached inputでdisplay result: median 150 ms以下を目標。
- UI thread block: 16 ms超の連続blockを避ける。
- full diagnosticはrelease後background実行としdrag frameを妨げない。
- memoryはevent count×pair数で増えず、同時candidate jobは一つ。

## 17. 完了条件

- 数値cell、source/receiving説明、Before/After plot、candidate editor、pair diagnosticが連動する。
- raw→compensation→derived→transform→gateのcanonical orderを壊さない。
- visual previewのためにraw、matrix、binding、membership、statisticsを暗黙変更しない。
- original matrixを変更せず、保存copyに完全なmanual provenanceがある。
- display downsamplingはscientific diagnosticと保存結果へ影響しない。
- GUI/headless/storageのparity testが通る。
- `docs/user-manual/user_manual.md`へ実装済みworkflowと制限を同じ変更で記載する。
- legacy editorを残す場合は用途と廃止条件を明記し、二重計算pathを持たない。

## 18. 最終検証

各incrementのfocused testに加え、最終incrementで次を実行する。

```bash
python -m pytest -q tests/test_compensation.py tests/test_compensation_preview.py
python -m pytest -q tests/test_pipeline_runner.py tests/test_project_storage.py
./tools/run-gui-tests.sh -q
python -m pytest -m "not gui"
ruff check src tests
mypy src/flowdesk_core src/flowdesk_storage src/flowdesk_cli
```

環境上実行できないcommandは成功扱いにせず、command、exit code、理由、代替証拠を完了報告へ
記載する。

## 19. 明示的な非対象

- AutoSpillまたは新しい補償推定algorithm。
- spectral unmixing/autofluorescence extraction。
- spreading error/modelの新規科学定義。
- 多色sampleの相関をゼロへ最適化する自動調整。
- raw FCSへのmatrix書戻し。
- previewだけを根拠にauthoritative export/resultを更新すること。
