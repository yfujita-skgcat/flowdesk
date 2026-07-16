# Flowdesk LLM実装指令書

対象リポジトリ: `/home/yfujita/work/bin/python/flowdesk`

要求仕様: [specs.md](specs.md)

FlowJo機能参照: [flowjo-manual.md](flowjo-manual.md)

この文書には未実装の作業だけを記載する。上から順に進め、同時に複数Phaseを実装しないこと。チェックボックスは、記載されたtestと受け入れ条件をすべて満たした後だけ`[x]`へ変更すること。

## 0. 全Phase共通の絶対ルール

- [ ] 作業開始時に`AGENTS.md`、`specs.md`、`docs/architecture.md`、`docs/headless_execution.md`、`docs/processing_pipeline.md`、`docs/ai_development_workflow.md`を全文読む。
- [ ] 変更対象に対応する`.codex/skills/*/SKILL.md`と`docs/implementation/*.md`を読む。
- [ ] 対応するimplementation guideがなければ、production codeより先に追加し、`docs/implementation/README.md`へ登録する。
- [ ] 変更前に目的、変更予定file、受け入れ条件を短く記録する。
- [ ] Pythonは2 spaces indentを使う。無関係なfileをformatしない。
- [ ] `flowdesk_core`からPySide6、Qt、`flowdesk_qt`をimportしない。
- [ ] GUIへcompensation、transform、gate membership、statistics、model fitの科学計算を実装しない。
- [ ] raw FCS event arrayを変更しない。
- [ ] display-downsampled dataをgate、count、frequency、statistics、fitへ使用しない。
- [ ] 科学的結果を変える設定はproject schemaへ保存し、CLI/Python APIから再現可能にする。
- [ ] errorを黙ってzero、empty、全NaNへ変換しない。projectで明示されたpolicyとstructured diagnosticを使う。
- [ ] 既存のrectangle/polygon/range/boolean、gate hierarchy、population filtering、histogram、marginal、project save/loadを壊さない。
- [ ] assertionや許容誤差を理由なく弱めない。期待と実装が違う場合は科学的定義を確認する。
- [ ] 大きなFCSをrepositoryへ追加しない。通常testはsmall synthetic fixtureを使う。
- [ ] GUI testはstable objectNameを使い、固定sleepを使わず、QThreadを停止して終了する。
- [ ] 各Phase完了時に、実行test、残る制限、次の小taskを記録する。

### 0.1 Baseline command

各Phaseの最初に次を実行する。変更前failureがある場合は今回の変更と区別する。

```bash
git status --short
.direnv/python-3.12.13/bin/python -X faulthandler -m pytest -q
./tools/run-gui-tests.sh -q
.direnv/python-3.12.13/bin/ruff check src tests
.direnv/python-3.12.13/bin/mypy src/flowdesk_core src/flowdesk_storage src/flowdesk_cli
```

既存のuser変更をrevertしない。test commandが環境理由で実行不能なら、command、終了code、理由を記録する。

### 0.2 個別実装ガイド

各Phaseでは、最初に`docs/implementation/llm-task-protocol.md`と次の個別ガイドを全文読む。一度のLLM実行では、個別ガイドの番号付きincrementを一つだけ実装する。

| Phase | 個別ガイド |
|---|---|
| A1 | `docs/implementation/sample-catalog-and-channel-identity.md` |
| A2 | `docs/implementation/derived-parameter-editor.md` |
| A3 | `docs/implementation/scientific-transforms-v2.md` |
| A4-A5 | `docs/implementation/compensation-workspace.md` |
| A6 | `docs/implementation/statistics-definitions.md` |
| A7, B8 | `docs/implementation/project-migration-and-recovery.md` |
| B1 | `docs/implementation/groups-and-annotations.md` |
| B2, B5 | `docs/implementation/gate-engine-v2.md` |
| B3 | `docs/implementation/workspace-tree-and-undo.md` |
| B4 | `docs/implementation/group-gating-and-overrides.md` |
| B6 | `docs/implementation/graph-window-v2.md` |
| B7 | `docs/implementation/overlay-and-backgating.md` |
| C1 | `docs/implementation/table-editor.md` |
| C2 | `docs/implementation/layout-editor.md` |
| C3 | `docs/implementation/templates-and-mapping.md` |
| C4-C6, C8 | `docs/implementation/interoperability.md` |
| C7 | `docs/implementation/plate-workspace.md` |
| D1 | `docs/implementation/kinetics-platform.md` |
| D2 | `docs/implementation/proliferation-platform.md` |
| D3 | `docs/implementation/cell-cycle-platform.md` |
| D4 | `docs/implementation/population-comparison.md` |
| D5 | `docs/implementation/spectral-compensation.md` |
| D6 | `docs/implementation/extension-api.md` |
| D7 | `docs/implementation/preferences-and-accessibility.md` |
| Performance | `docs/implementation/performance-and-review.md` |

## Release A: Scientific foundation

### Phase A1: Sampleごとのchannel identity [S01]

#### 事前文書

- [x] 済み: `docs/implementation/sample-catalog-and-channel-identity.md`を全文読み、今回のincrementで確定したcontractと制限を追記する。
- [x] 済み: FCS `$PnN`、`$PnS`、detector、stain、array indexの使い分けを定義する。
- [x] 済み: sample間でchannel orderやshort nameが違う場合のmapping規則を定義する。

#### Core/model

- [x] 済み: `ChannelSpec`へ、安定ID、FCS index、primary name、short name、detector、stain、unit、raw metadataを欠落なく表せるfieldを追加する。既存project migrationを用意する。
- [x] 済み: `SampleData`または同等のGUI非依存input objectを追加し、sample ID、read-only events、sample固有channel specsを一体でrunnerへ渡す。
- [x] 済み: `PipelineRunner.run()`へsampleごとのchannel mappingを渡す新APIを追加する。既存`event_data + channel_names`はdeprecation-compatible wrapperとして残してよい。
- [x] 済み: compensation、derived parameter、transform、gateがcolumn positionではなくchannel identityで解決されるようにする。
- [x] 済み: duplicate channel label、missing parameter、ambiguous short nameをstructured errorにする。
- [x] 済み: input file fingerprintにsize、mtime、hash algorithm/hash valueを保存する。

#### Storage/GUI

- [x] 済み: project schemaとexample projectを新modelへ更新し、old versionからmigrationする。
- [x] 済み: Sample Browserへ選択可能なmetadata columns、sort/filter、channel mismatch badgeを追加する。
- [x] 済み: missing fileのreconnect dialogを追加し、hash/metadata一致を表示する。

#### 必須test

- [x] 済み: channel orderだけが異なる2 sampleでmarker指定のgate countが一致する。
- [x] 済み: `$PnN`が同じで`$PnS`が異なるcaseと、その逆を明示的にtestする。
- [x] 済み: ambiguous/missing channelでsilent fallbackしない。
- [x] 済み: sampleごとのraw arrayがread-onlyかつ変更されない。
- [x] 済み: old projectをmigrationし、save/reload/headless runできる。
- [x] 済み: GUIで表示するchannelとheadless runnerが参照するchannel IDが一致する。

#### 完了確認

```bash
.direnv/python-3.12.13/bin/python -m pytest -q tests/test_fcs_io.py tests/test_pipeline_runner.py tests/test_project_storage.py
./tools/run-gui-tests.sh -q
```

### Phase A2: Derived parameterの明示的failure policy [S04]

#### 事前文書

- [x] 済み: `docs/implementation/derived-parameter-editor.md`を全文読み、source stage、dependency graph、invalid value、run failure policyの確定事項を追記する。

#### Core

- [x] 済み: runner内の広い`except Exception`による全NaN置換を削除する。
- [x] 済み: `fail_run`、`fail_sample`、`emit_nan_with_warning`を型付きpolicyとしてmodel/schemaへ追加する。
- [x] 済み: `emit_nan_with_warning`時もexpression、sample、exception type、affected event countをExecutionReportへ記録する。
- [x] 済み: derived parameter間のdependency graphを構築し、topological orderで評価する。
- [x] 済み: unknown inputとcycleをrun開始前に拒否する。
- [x] 済み: unit、output channel ID、source stageを保存する。
- [x] 済み: derived stageの戻り値をeventsと更新済みchannel specsの組にし、後続transform/gateへ必ず同じ列対応を渡す。
- [x] 済み: canonical orderに反する`source_stage = transformed`は新規作成を禁止する。既存projectは黙って意味を変えず、migration diagnosticと明示的互換policyを用意する。

#### GUI

- [x] 済み: name、expression、inputs、source stage、unit、policyを編集するdialogを追加する。
- [x] 済み: channel/derived parameter挿入、syntax validation、error位置、small previewを提供する。
- [x] 済み: previewはcore evaluatorを使用し、GUI独自計算をしない。

#### 必須test

- [x] 済み: 三つのfailure policyをそれぞれtestする。
- [x] 済み: dependency chainとcycleをtestする。
- [x] 済み: division by zero、domain error、unknown parameter、all-NaN inputをtestする。
- [x] 済み: save/load/CLI runでpolicyとdiagnosticが維持される。
- [x] 済み: raw値参照とcompensated値参照が、derived stage後・transform前のcanonical順序を壊さないことをtestする。
- [x] 済み: derived parameterを後続transform、gate、statisticsで安定ID参照できることをtestする。

### Phase A3: 正式なLogicleとtransform model [S05]

#### 事前調査・文書

- [x] 済み: `docs/implementation/scientific-transforms-v2.md`を全文読み、選択した式、reference、toleranceを追記する。
- [x] 済み: Logicleのprimary paperまたは検証済みreference implementationを記載する。
- [x] 済み: parameter `T/W/M/A`、domain、inverse、tick generation、numeric toleranceを定義する。
- [x] 済み: FlowJo Biexと同値を保証しない場合、その名称を使用しないことを明記する。

#### Core

- [x] 済み: 現在の`logicle_like`を`legacy_logicle_approximation`へrenameするschema migrationを作る。
- [x] 済み: published Logicleのforward/inverseを実装する。optional dependencyを使う場合もversionとparameter mappingを保存する。
- [x] 済み: linear、log、asinh、logicleを共通Transform protocol/APIで扱う。
- [x] 済み: gate evaluator、plot coordinate conversion、tick生成が同じimplementationを使う。
- [x] 済み: project-level transformとgate axis transformを同じtransform ID参照へ統合し、同一parameterへ二重適用されないようにする。
- [x] 済み: analysis transformとdisplay-only view transformを型とschemaで区別する。
- [x] 済み: transform domain外とnon-convergenceをstructured errorにする。

#### GUI/migration

- [x] 済み: Transform Editorでtypeと全parameterを編集し、previewとinverse round-trip errorを表示する。
- [x] 済み: legacy project読込時に近似typeを勝手に正式Logicleへ変換しない。
- [x] 済み: legacy gateを正式Logicleへ移す場合は明示的duplicate/migrate operationと全イベント差分previewを提供する。Polygonは頂点再投影近似と明示し、compensation/derived parameterを含むprojectではcanonical-stage preview実装まで操作を停止する。

#### 必須test

- [x] 済み: reference vectorsに対するforward/inverse値を固定する。
- [x] 済み: negative、zero、linear region、large positive、boundaryをtestする。
- [x] 済み: `inverse(forward(x))`の誤差を定義済みtolerance内にする。
- [x] 済み: Logicle viewで作成したrectangle/polygonのGUI/headless membershipを一致させる。
- [x] 済み: linear/log/asinh既存gateを壊さない。

### Phase A4: Compensation bindingとdiagnostics [S03-P0]

#### 事前文書

- [x] 済み: `docs/implementation/compensation-workspace.md`を全文読み、binding、provenance、diagnosticの確定事項を追記する。
- [x] 済み: matrix source、channel alignment、sample/Group binding、provenance、diagnostic schemaを定義する。

#### Core/storage

- [x] 済み: global `default_compensation_matrix_id`だけでなく、sample/Group/execution profile単位のbindingを追加する。
- [x] 済み: binding priorityとconflict ruleを定義し、headless resolverで曖昧なgroup/duplicate target/unknown matrixを拒否する。
- [x] 済み: matrix ID、source、control IDs、algorithm/version、manual edits、created metadataを保存する。
- [x] 済み: finite、square、channel set、duplicate channel、condition numberを構造化diagnostic付きで検証する。
- [x] 済み: sampleごとにcompensated outputと構造化diagnosticsを生成し、raw inputを不変にする。
- [x] 済み: ExecutionReportへmatrix ID、source、channel order/index、binding根拠、condition warningを記録する。

#### GUI

- [x] 済み: Compensation Matrix list/editorを追加する。
- [x] 済み: matrix heat map、numeric cell editor、duplicate-before-edit、sample/Group applyを提供する。
- [x] 済み: compensated/uncompensated previewを同じPopulationで表示する。
- [x] 済み: applied matrix badgeとinvalid/stale statusをWorkspaceへ表示する。

#### 必須test

- [x] 済み: sample別に異なるmatrixを適用する。
- [x] 済み: channel permutationで同じ結果を得る。
- [x] 済み: singular、ill-conditioned、NaN、missing detectorをtestする。
- [x] 済み: manual editで元matrixが変わらない。
- [x] 済み: GUI previewとheadless compensated valuesが一致する。

### Phase A5: Traditional compensation calculation [S03-P1]

Phase A4完了後に開始する。

- [x] 済み: explicit control sampleとpositive/negative Populationを入力とするcalculation specをmodel化する。
- [x] 済み: linear/median background-subtracted method、minimum events、outlier policyを明示する。
- [x] 済み: asymmetric synthetic single-stain controlsからknown spill matrixを復元するcore algorithmを実装する。
- [x] 済み: detector × control assignment tableをGUIへ追加する。
- [x] 済み: cleanup/positive/negative gateをGraph Windowで編集するとcalculationをstale化する。
- [x] 済み: residual、slope、event count、condition numberをdiagnostic panelへ表示する。
- [x] 済み: calculated matrixをimmutable resultとして保存し、編集はduplicateで行う。
- [x] 済み: known synthetic fixturesとindependent calculationで数値検証する。

AutoSpill、spectral unmixing、autofluorescence extractionはこのPhaseへ混ぜない。

### Phase A6: 保存可能なStatistics definitions [S11]

#### 事前文書

- [x] 済み: `docs/implementation/statistics-definitions.md`を全文読み、raw-eventとdisplay-binned statisticsの選択を追記する。

#### Model/core

- [x] 済み: `StatisticSpec`を追加する。Population ID、parameter ID、metric、source stage、transform/binning policy、settings、formatを保持する。
- [x] 済み: count、frequency parent/totalを、full membership maskに基づき実装する。
- [x] 済み: mean、median、geometric mean、SD、CV、MAD、percentileを実装する。
- [x] 済み: empty、zero denominator、negative valuesを含むgeometric mean、NaN/Infのpolicyをmetricごとに定義する。
- [x] 済み: gate/matrix/transform変更時のdependency invalidationを実装する。
- [x] 済み: ExecutionReportへtyped statistic resultsとundefined reasonを追加する。

#### GUI/export

- [x] 済み: Add Statistic dialogをPopulation TreeとGraphから開けるようにする。
- [x] 済み: statisticsをPopulation配下のnodeとして表示し、stale/result statusを示す。
- [x] 済み: CSV/TSV exportでdefinition ID、display name、value、unit、statusを出力できるようにする。

#### 必須test

- [x] 済み: 各metricのknown values、empty、NaN/Infをtestする。
- [x] 済み: statistics定義のsave/load round-tripをtestする。
- [x] 済み: gate編集後stale、pipeline後更新をtestする。
- [x] 済み: GUI値、CLI export、Python API値を一致させる。

### Phase A7: Schema migration、atomic save、structured diagnostics [S14/S23]

- [x] 済み: `docs/implementation/project-migration-and-recovery.md`を全文読み、対象versionとmigration経路を追記する。
- [x] 済み: project schemaを厳密化し、ID reference integrityをvalidatorで検証する。(gate parent_population_id, statistics population_id, compensation bindings/calculations)
- [x] 済み: versionごとのmigration registryを作り、migration reportとbackupを生成する。(MigrationReport, _get_migration_path, ALL_KNOWN_VERSIONS)
- [x] 済み: temp pathへwrite、file/directory fsync、atomic replaceするsave手順を実装する。(atomic_write_json)
- [x] 済み: newer unsupported schemaをread-only以外で開かない。(migration前にreject、save前にvalidate)
- [x] 済み: ExecutionDiagnostic modelを追加し、severity、code、sample、population、stage、message、detailsを保持する。(既存: execution_report.py)
- [x] 済み: GUI diagnostics panelを追加する。
- [x] 済み: CLI machine-readable JSON outputを追加する。(既存: run_project.py でstderrへJSON出力)
- [x] 済み: interrupted save、invalid reference、old schema、newer schemaをtestする。

## Release B: Experiment-scale gating and review

多数 sample のゲート作成・確認・QC を、安全に拡張するRelease。内部では常に
Sample Group、Gating Strategy、binding を使うが、通常 GUI は `All Samples` と
`Default Strategy` の一組だけを表示し、従来どおり全 sample に共通 geometry を
適用する。Group は treatment/control の生物学的比較群ではなく、同じ解析定義を
適用できる panel、control、試料種別、取得形式、QC の単位として使う。比較対象の
treatment/control は原則として同じ Group strategy を共有する。

複数 Group/Strategy は明示的に有効化する高度機能とし、無効化しても保存済みの
Group、binding、override を削除・自動統合しない。sample 固有 geometry override は
さらに別の高度機能であり、既定では無効にする。Time、technical QC、scatter cleanup、
singlet のような技術的 gate と、比較対象となる marker-positive gate を区別し、後者の
override は強い warning と監査記録なしに比較結果へ使わない。

### Phase B1: Groupとannotation [S02]

- [x] 済み: `docs/implementation/groups-and-annotations.md`を全文読み、今回実装するrule grammarと通常GUIの範囲を追記する。
- [x] 済み: `SampleGroupSpec`、`AnnotationSpec`、safe membership rule、Group/Strategy bindingをmodel/schemaへ追加する。すべての新規projectには `all-samples` Group と `default-strategy` bindingを自動作成する。
- [x] 済み (基盤): All Samples、Compensation Controls、panel/取得形式/QC用 user groupの複数所属をmodelで表現し、treatment/controlの比較群だけを理由に別strategyを選ばない旨をadvanced GroupのGUI/helpへ明記する。通常GUIはAll Samples × Default Strategyのまま、明示toggleで既存Groupをread-only表示する。
- [ ] advanced Group modeでCompensation Controls、panel/取得形式/QC用user groupのcreate/edit/deleteとmembership編集を追加する。
- [x] 済み: keyword条件でdynamic group membershipをheadlessに解決し、同一sampleに競合するstrategy bindingがある場合は `conflicting_group_strategy_binding` と sample/group/strategy context を持つ `PipelineError` で、処理開始前に拒否する。
- [x] 済み (create/edit/delete): 通常GUIではGroup paneを隠し、All Samples × Default Strategyのみを操作する。`Use Multiple Analysis Groups`を明示的に有効化した時だけGroup paneとcreate/rename/deleteを表示する。
- [x] 済み: advanced Group modeでsample-ID一覧からGroup一覧へdrag/dropし、explicit `sample_ids`を更新する。重複dropは無視し、変更時はresultsをstale化する。
- [x] 済み: 高度Group表示を無効にしてもGroup、binding、overrideを削除・暗黙統合せず、`advanced_groups_enabled: false`として表示だけを簡易化する。複数bindingを保持する回帰testとstatus説明を追加する。
- [x] 済み (core): keyword columns、find/replace、fill series、typed CSV importをGUI非依存coreへ追加し、annotation source precedenceと非破壊性を検証する。
- [x] 済み: annotation editor GUIでkeyword columns、cell edit、find/replace、fill series、CSV paste/importを提供し、core操作と同じtyped contractを使う。
- [x] 済み: annotationはproject manifestへ保存・復元し、GUI編集とCSV importはproject側のtyped valuesだけを変更する。raw FCS bytesを変更しないことをround-trip testで確認する。
- [x] 済み: Group bindingしたstrategy/statisticsを新規memberへheadless runnerで自動適用する。non-empty `statistic_ids`はsample単位で選択し、空配列はproject全体定義を維持する。
- [x] 済み: `PipelineRunner.resolve_group_assignments()`をGUI/CLI/Python共通のinspection APIとして追加し、GUI通常・高度モードとheadlessのGroup member IDs・resolved strategy IDs一致testを追加する。

### Phase B2: Gate engine v2 [S06]

- [ ] `docs/implementation/gate-engine-v2.md`を全文読み、今回実装するgate型のboundary semanticsを追記する。
- [ ] ellipse、quadrant、offset quadrantをcore model/evaluator/schemaへ追加する。
- [ ] inclusive boundary、shared boundary、NaN/Inf、degenerate geometryを定義しtestする。
- [ ] 全geometric gateのnumeric editorを追加する。
- [ ] Boolean gateをnested expression treeへmigrationし、AND/OR/NOTを任意に組み合わせる。
- [ ] expression treeのcycle、missing reference、scope violationをrun前に拒否する。
- [ ] GUI toolbarへ新gate typeとBoolean expression tree editorを追加する。
- [ ] project round-tripとGUI/headless membership一致testを追加する。

Auto/magnetic/tethered/clone gateはPhase B5まで実装しない。

### Phase B3: Gate hierarchy UXとUndo/Redo [S07/S14]

- [ ] `docs/implementation/workspace-tree-and-undo.md`を全文読み、今回追加するcommand contractを追記する。
- [ ] project mutation commandとUndo stackをGUI非依存modelまたはapplication layerに実装する。
- [ ] gate create/edit/rename/delete/reparent/duplicate/subtree copyをUndo/Redo可能にする。
- [ ] sample、Population、statisticsを一つのhierarchy viewへ統合する。
- [ ] breadcrumb、parent、previous/next sample navigationを追加する。
- [ ] selectionとPlot/Hierarchyを双方向同期する。
- [ ] subtree Copy Analysisを別Population/sample/Groupへatomicに適用する。
- [ ] duplicate sibling name、cycle、reference deleteを確定前に表示する。
- [ ] Undo後もcache/reportが正しくstale化されるtestを追加する。

### Phase B4: Group strategyとsample override review [S08]

- [ ] `docs/implementation/group-gating-and-overrides.md`を全文読み、通常は Group 共通 geometry を編集すること、override は明示作成のみであること、override resolution/rebase/comparison warning policyを追記する。
- [ ] Group共通gate definitionとsample-specific geometry overrideを別modelで表現する。override は Group の複数化とは独立した高度機能とし、既定では無効にする。
- [ ] overrideにbase ID/version hash、delta/full geometry、author、time、reason、gate purpose（technical cleanup / comparison-critical）を保存する。
- [ ] sample navigation中に同じPopulation path、axes、scale、view rangeを維持する。
- [ ] shared/override/stale/missingをtree badgeとplot bannerで表示する。`results stale`（再計算が必要）と `override stale`（base変更によりrebaseが必要）を別状態として表示する。
- [ ] 通常のgate drag/editは Group 共通 geometry を変更する。sample override は `このsample用のgate調整を作成` の意図的なcommandでだけ作成し、理由入力と影響範囲の確認を要求する。
- [ ] reset-to-group、promote-to-group、copy-to-selectedを別commandにする。comparison-critical gate のoverride/promoteは強いwarningと監査記録を必須にする。
- [ ] Groupへsubtree適用前にchannel mappingを全sampleでvalidateする。
- [ ] frequency outlier、gate boundary clipping、missing Population、override一覧、comparison-critical override warningをQC panelへ表示する。`missing` は0 eventsやdisplay fallbackと区別する。
- [ ] GUI確認値とbatch headless resultsを一致させるE2E testを追加する。Group共通geometry、technical override、comparison-critical override warning、stale base/rebase、missing channelをそれぞれ検証する。

### Phase B5: Auto、magnetic、tethered、clone gates [S06]

各gateを一つずつ独立subphaseで実装する。まとめて実装しない。

- [ ] 各algorithmについてprimary/reference method、parameters、fit failure、determinismをimplementation guideへ記載する。
- [ ] template definitionとsample-specific fitted geometryを分離する。
- [ ] fitted resultへinput hash、algorithm version、diagnosticsを保存する。
- [ ] manual override後の再fit policyを定義する。
- [ ] clone gateの同期group、leader/conflict、Undo behaviorを定義する。
- [ ] density downsamplingではなくfull Populationをfitへ使用する。
- [ ] synthetic distributionsとedge casesでnumeric testする。

### Phase B6: Graph Window plot types [S09]

- [ ] `docs/implementation/graph-window-v2.md`を全文読み、今回追加するplot typeのaggregation/display policyを追記する。
- [ ] `PlotViewSpec`をmodel化し、Population、axes、transforms、plot type、range、styleを保存する。
- [ ] dot/scatter、pseudocolor、density、contour、histogram、CDFを段階実装する。
- [ ] density/contour binningはfull selected Populationを入力にする。
- [ ] rendering downsampleとdensity aggregationの設定を区別する。
- [ ] duplicate graph tab/windowとlinked sample navigationを追加する。
- [ ] selection、gate draw、pan/zoom modeをtoolbarで排他的に表示する。
- [ ] gate label、Population statistics、compensation badgeをoverlay可能にする。
- [ ] PNGに加えSVG/PDF exportとmetadata sidecarを追加する。
- [ ] 全plot typeについてempty、NaN/Inf、logicle、large eventのtestを追加する。

### Phase B7: Overlayとbackgating [S10]

- [ ] `docs/implementation/overlay-and-backgating.md`を全文読み、normalizationまたはprojection policyを追記する。
- [ ] OverlaySpecとBackgatingSpecをcore/storageへ追加する。
- [ ] 1D overlayのcount/mode/unit-area normalizationを実装する。
- [ ] 2D overlayはPopulationごとの色とalphaを保存する。
- [ ] backgatingはrunner membershipをancestor viewへ投影するだけにし、GUIで再評価しない。
- [ ] target、parent background、ancestor gateを視覚的に区別する。
- [ ] project save/load、headless render、GUI displayを同じdefinitionでtestする。

### Phase B8: Autosaveとcrash recovery [S14]

- [ ] autosave interval、retention、disableをglobal preferenceとして追加する。
- [ ] dirty projectだけをatomic autosaveする。
- [ ] normal projectより新しいrecoveryがある場合だけ起動時に選択肢を表示する。
- [ ] recover copyを別pathで開き、元projectを自動上書きしない。
- [ ] QThread実行中、save中、crash途中、disk fullをtestする。

## Release C: Reports, reuse, interoperability

解析結果を表・図・レポートとして整理し、別実験へ再利用し、外部形式や共同研究者と
安全に交換するRelease。Table、Layout、Template、archive、interoperability はすべて
保存可能な definition と headless runner を先に作り、GUI preview と CLI batch output が
同じ値・同じ provenance を使う。

### Phase C1: Table Editor [S12]

- [ ] `docs/implementation/table-editor.md`を全文読み、今回追加するcolumn sourceまたはiterator contractを追記する。
- [ ] `TableDefinitionSpec`と`TableColumnSpec`をmodel/schemaへ追加する。
- [ ] keyword、StatisticSpec、platform result、constant、安全なformula列を実装する。
- [ ] sample/Group/Population path/plate well iterationをcore table runnerへ実装する。
- [ ] column reorder、rename、number format、hidden、sort、filterをGUIへ追加する。
- [ ] conditional formattingはdisplay definitionとして保存し、数値を変更しない。
- [ ] previewとbatch exportで同じcore runnerを使う。
- [ ] CSV/TSVとprovenance sidecarを実装する。XLSXはoptional dependencyとして後から追加する。
- [ ] gate変更後の再計算とGUI/CLI table一致をE2E testする。

### Phase C2: Layout modelとrenderer [S13]

- [ ] `docs/implementation/layout-editor.md`を全文読み、今回追加するscene objectまたはrenderer contractを追記する。
- [ ] page、plot、overlay、table、statistic text、legend、shape、annotationのscene modelを作る。
- [ ] device-independent units、z-order、style、font fallbackを定義する。
- [ ] Qt非依存headless renderer interfaceを先に実装する。
- [ ] PNG、SVG、PDFの順にoutput backendを実装する。
- [ ] GUIへselect/move/resize、align/distribute、group/lock、duplicate、Undo/Redoを追加する。
- [ ] sample/Group/keyword iterationとfiltered batchを実装する。
- [ ] GUI previewとheadless outputのobject count、text value、statisticsを一致させる。
- [ ] image comparisonはfont差を考慮しつつ、blank outputやmissing plotを厳格に検出する。

### Phase C3: Template [S15]

- [ ] `docs/implementation/templates-and-mapping.md`を全文読み、mapping evidenceとconfirmation policyを追記する。
- [ ] sample events/pathを除外し、Group rules、channel roles、matrix setup、strategy、statistics、tables、layoutsを保存する。
- [ ] template apply時のchannel/marker mapping planをcoreで生成する。
- [ ] GUI wizardでexact、suggested、ambiguous、missing mappingを表示する。
- [ ] user確認なしにambiguous mappingを確定しない。
- [ ] template適用結果をatomicに保存し、cancel時はprojectを変更しない。
- [ ] 別channel order、別detector label、missing markerのfixturesをtestする。

### Phase C4: Portable archive [S15]

- [ ] archive manifest、checksums、project、FCS、derived artifactsのformatを文書化する。
- [ ] create/list/verify/extract CLIを実装する。
- [ ] path traversal、symlink escape、checksum mismatch、duplicate IDを拒否する。
- [ ] GUIにarchive progress、size estimate、include/exclude一覧を表示する。
- [ ] archive round-trip後のheadless resultが元projectと一致するtestを追加する。

### Phase C5: GatingMLとFCS export [S16]

- [ ] `docs/implementation/interoperability.md`を全文読み、今回扱うformat/versionのsupport matrixを追記する。
- [ ] GatingML 2.0の対応gate/transform matrixを記載する。
- [ ] basic rectangle/polygon/range/ellipse/quadrant/hierarchyのimport/exportを実装する。
- [ ] Booleanとunsupported transformはcompatibility reportへ記録し、黙って落とさない。
- [ ] importしたgateをprojectへ保存し、headless評価できるようにする。
- [ ] selected PopulationのFCS exportを実装し、元metadataとworkspace annotationのsourceを区別する。
- [ ] exportは新fileへ行い、input FCSを上書きしない。
- [ ] external validatorまたはindependent libraryでround-tripを検証する。

### Phase C6: WSP read-only import [S16]

- [ ] WSP version/feature support matrixを文書化する。
- [ ] sample reference、basic compensation、basic gates、hierarchy、axis transformをread-only parserで取り込む。
- [ ] FlowJo Biex、plugin node、unsupported platformをopaque metadataとwarningとして保持する。
- [ ] import結果を新しい`.flowdesk` projectへ保存し、元WSPを変更しない。
- [ ] public/synthetic WSP fixtureの出所とlicenseを記録する。
- [ ] FlowJoと同じ結果を主張する場合はversion、input hash、settings、toleranceをfixtureに含める。

### Phase C7: Plate workspace [S17]

- [ ] `docs/implementation/plate-workspace.md`を全文読み、plate formatまたはimport mapping contractを追記する。
- [ ] plate format、well、sample mapping、condition、dose、replicateをmodel化する。
- [ ] CSV paste/import、well grid selection、missing/duplicate well診断を実装する。
- [ ] plate heat mapはStatisticSpecを入力にし、GUI独自統計を使わない。
- [ ] Group、Table、Layout iterationへwell metadataを接続する。
- [ ] 96/384 wellとpartial plateをtestする。

### Phase C8: De-identification [S16]

- [ ] removal/replace/hash policy fileをschema化する。
- [ ] previewで対象keywordと変更後値を表示する。
- [ ] new FCS/archiveへ出力し、元fileを上書きしない。
- [ ] audit reportへinput/output hash、policy、removed keysを記録する。
- [ ] required FCS keywordを壊さないvalidationを追加する。

## Release D: Specialized platforms and ecosystem

一般的な gating を超える専門解析（kinetics、proliferation、cell cycle、population
comparison、spectral/AutoSpill）と、安全な extension/batch ecosystem を扱うRelease。
各platformは独立した scientific contract、reference fixture、headless runner を先に
定義し、近似結果を互換実装として誤表示しない。plugin は別process・明示permission・
検証済みoutputを既定とする。

各platformは独立Phaseとして実装し、core model、numeric reference tests、headless runner、GUI、Table/Layout integrationの順を守る。

### Phase D1: Kinetics [S18]

- [ ] `docs/implementation/kinetics-platform.md`を全文読み、今回実装するmetricの式とreferenceを追記する。
- [ ] KineticsSpec、time windows、baseline、metrics、diagnosticsをmodel化する。
- [ ] max、time-to-max、slope、AUC、responding fractionを実装する。
- [ ] Time欠損時のevent-number近似はflow-rate仮定とwarningを必須にする。
- [ ] manual/automatic rangesをdeterministicにし、algorithm versionを保存する。
- [ ] GUI plot、Table columns、Layout objectを追加する。
- [ ] irregular time、duplicate time、empty window、low eventsをtestする。

### Phase D2: Proliferation [S19]

- [ ] `docs/implementation/proliferation-platform.md`を全文読み、model、formula、reference fixtureを追記する。
- [ ] dye、generation 0、peak ratio、CV、generation count、background/modelを保存する。
- [ ] fit residual、convergence、uncertaintyをresultへ含める。
- [ ] division index、proliferation index、percent divided、generation countsをreference definitionで実装する。
- [ ] model fitとgeneration gate生成を別commandにする。
- [ ] published/synthetic reference datasetでnumeric validationする。
- [ ] failed fitを成功表示しないGUI testを追加する。

### Phase D3: Cell Cycle [S20]

- [ ] `docs/implementation/cell-cycle-platform.md`を全文読み、model、constraints、reference fixtureを追記する。
- [ ] model type、DNA parameter、G1/G2 constraint、background、debris、doublet policyを保存する。
- [ ] G0/G1、S、G2/M fraction、fit residual、convergenceを出力する。
- [ ] initial valuesとconstraintsをGUIで編集できるようにする。
- [ ] reference distributionsとfailure casesをtestする。

### Phase D4: Population Comparison [S21]

- [ ] `docs/implementation/population-comparison.md`を全文読み、method definitionとreference fixtureを追記する。
- [ ] test/control populations、parameters、normalization、methodを保存する。
- [ ] histogram、CDF、difference overlayを実装する。
- [ ] KSとOvertonを先に実装し、probability binningは別subphaseにする。
- [ ] multiple controls、minimum events、empty control、multiple comparison policyを定義する。
- [ ] methodごとにindependent numeric fixtureを用意する。
- [ ] Table/Layout integrationを追加する。

### Phase D5: Spectral/AutoSpill extensions [S03]

- [ ] `docs/implementation/spectral-compensation.md`を全文読み、選択したalgorithm、reference、validation fixtureを追記する。
- [ ] conventional compensationと別のimplementation guide/modelにする。
- [ ] spectral unmixing reference、endmember/control assumptions、residual metricを定義する。
- [ ] AutoSpillを実装する場合はoriginal publicationのalgorithmとvalidation datasetに従う。
- [ ] autofluorescence extractionとspreading matrixを別result/provenanceとして保存する。
- [ ] approximate implementationをAutoSpill互換と表示しない。

### Phase D6: Extension APIとbatch queue [S22]

- [ ] `docs/implementation/extension-api.md`を全文読み、今回公開するAPI contractまたはpermission boundaryを追記する。
- [ ] Python/CLI public APIをversioned contractとして定義する。
- [ ] plugin manifestへinput type、output type、version、resource、permissionsを定義する。
- [ ] pluginは別processを既定とし、project内codeを自動実行しない。
- [ ] outputをderived parameter、Population、table、artifactとして検証してimportする。
- [ ] batch queueへsample selector、parallelism、cancel、failure policy、output dirを追加する。
- [ ] crashed/timeout/malformed pluginがprojectを破損しないtestを追加する。

### Phase D7: Preferences、help、accessibility [S24]

- [ ] `docs/implementation/preferences-and-accessibility.md`を全文読み、今回追加するpreference scopeまたはaccessibility criteriaを追記する。
- [ ] global preferenceとproject display settingsを分離する。
- [ ] plot defaults、number format、autosave、performance、theme、font、export defaultsを提供する。
- [ ] preference reset/import/exportを実装する。
- [ ] stable objectName、keyboard navigation、shortcut help、non-color-only statusを全主要画面で確認する。
- [ ] context helpを`flowjo-manual.md`ではなくFlowdesk固有README/user guideへ接続する。
- [ ] preference変更で既存projectのscientific definitionを暗黙変更しないtestを追加する。

## Performance track [S23]

以下はRelease Aから継続し、各release終了時に更新する。

- [ ] `docs/implementation/performance-and-review.md`へ10万、100万、1000万events profileを追加する。
- [ ] deterministic synthetic dataset generatorとseedを固定する。
- [ ] load、compensation、derived、transform、gating、statistics、renderを別々に計測する。
- [ ] cache keyへinput fingerprintと全上流definition hashを含める。
- [ ] matrix/derived/transform/gate/statistics変更時のcache invalidation testを追加する。
- [ ] runnerへprogress、cancel、memory budget、sample-level parallelismを追加する。
- [ ] scatter downsampling変更でscientific count/statisticsが変わらないことをtestする。
- [ ] rare-event visibilityの限界をGUIへ表示する。

## 各Phaseの最終確認template

Phaseを完了扱いにする前に、次を実行して結果を作業報告へ記載する。

```bash
.direnv/python-3.12.13/bin/python -X faulthandler -m pytest -q <phase-specific-tests>
.direnv/python-3.12.13/bin/ruff check src tests
.direnv/python-3.12.13/bin/mypy src/flowdesk_core src/flowdesk_storage src/flowdesk_cli
./tools/run-gui-tests.sh -q
make test-all
git diff --check
git status --short
```

さらに次を確認する。

- [ ] GUIをimportせずcore/headless testが実行できる。
- [ ] GUIのcount/statisticsがheadless結果と一致する。
- [ ] raw inputが変更されていない。
- [ ] project save/load/CLI round-tripが成功する。
- [ ] schema、implementation guide、README/user操作説明が更新されている。
- [ ] error/warning/skipがstructured diagnosticとして確認できる。
- [ ] remaining limitationsと次の小taskが明記されている。
