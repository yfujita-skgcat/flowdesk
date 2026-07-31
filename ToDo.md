# Flowdesk LLM実装指令書

対象リポジトリ: `<repository-root>`

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
| B8.1 | `docs/implementation/analysis-settings-bundles.md` |
| B1 | `docs/implementation/groups-and-annotations.md` |
| B2, B5 | `docs/implementation/gate-engine-v2.md` |
| B3 | `docs/implementation/workspace-tree-and-undo.md` |
| B3.1 | `docs/implementation/gating-and-results-workspaces.md` |
| B3.2 | `docs/implementation/interactive-current-sample-preview.md` |
| B3.3 | `docs/implementation/results-integrated-current-sample-recalculation.md` |
| B4 | `docs/implementation/group-gating-and-overrides.md` |
| B6 | `docs/implementation/graph-window-v2.md` |
| B7 | `docs/implementation/overlay-and-backgating.md` |
| B7.1 | `docs/implementation/multi-sample-overlay-and-plot-presentation.md` |
| B7.2 | `docs/implementation/integrated-overlay-controls-and-plot-appearance.md` |
| B7.2.Density | `docs/implementation/density-event-coloring.md` |
| B7.3 | `docs/implementation/sample-sheet-results-and-batch-plot-export.md` |
| B7.3.E | `docs/implementation/plot-export-completion.md` |
| B7.4 | `docs/implementation/analysis-workflow-integration.md` |
| B7.5 | `docs/implementation/results-statistics-matrix.md` |
| B7.6 | `docs/implementation/unified-results-export-and-population-paths.md` |
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
| Performance parallel/progress | `docs/implementation/parallel-execution-and-progress.md` |

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
- [x] 済み: advanced Group modeで`user`、`compensation_controls`、`panel`、`acquisition`、`qc` roleを選んだGroupのcreate/rename/deleteとmembership編集（drag/drop）を追加する。roleはGroup metadataとして保存し、科学計算の意味を暗黙変更しない。
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

- [x] 済み: `docs/implementation/gate-engine-v2.md`を全文読み、ellipseの座標系、inclusive boundary、NaN/Inf、degenerate geometry semanticsを追記する。
- [x] 済み (ellipse): ellipseをcore model/evaluator/schemaへ追加する。center/radius/rotationをdata coordinatesで保存し、GUI近似polygonを解析に使わない。
- [x] 済み: rectangle/range/polygon/ellipseのinclusive boundary、有限値、NaN/Inf除外、ordered/non-degenerate geometryを定義しtestする。重複geometryの共有領域は意図的に両populationへ入り得ること、quadrantのexact shared threshold ownershipはquadrant実装で定義することを文書化する。
- [x] 済み: 全geometric gate（rectangle/range/polygon/ellipse）のnumeric editorを追加する。作成・編集値はdata coordinatesで保存し、coreのgeometry validationを再利用する。
- [x] 済み: Boolean gateをnested expression treeへmigrationし、AND/OR/NOTを任意に組み合わせる。legacy `operation/source_ids`はload時に`thresholds.expression`へ移行し、flat evaluatorとの後方互換を保つ。
- [x] 済み: expression treeのcycle、missing reference、scope violation、arityをrun前に拒否する。full-length maskでprecedenceとNOTを評価する。
- [x] 済み: GUI gate type selectorへellipseを接続済みとし、Boolean dialogへ任意nested expression JSON tree editorを追加する。GUIはJSONを保存し、tree validation/evaluationはcoreへ委譲する。
- [x] 済み: nested Booleanのproject save/load round-tripとGUI/headless membership一致testを追加する。

Auto/magnetic/tethered/clone gateはPhase B5まで実装しない。

### Phase B3: Gate hierarchy UXとUndo/Redo [S07/S14]

- [x] 済み: `docs/implementation/workspace-tree-and-undo.md`を全文読み、JSON互換project-state、定義のみのcommand payload、clean marker、依存invalid化のcommand contractを追記する。
- [x] 済み: `flowdesk_core.project_commands`に定義のみを扱うproject mutation commandとGUI非依存Undo/Redo stackを実装する。invalid mutationはstate/historyを変更せず、clean markerとstale理由を保持する。
- [x] 済み: gate create/edit/rename/delete/reparent/duplicate/subtree copyをGUI非依存command経由でUndo/Redo可能にする。GateEditorの既存操作も同じ定義専用stackへ接続する。
- [x] 済み: `WorkspaceTree`へsample、Population、statisticsをstable ID付きで統合し、MainWindowのsample/population navigationへ接続する。計算はExecutionReportと既存core結果を表示するだけにする。
- [x] 済み: Workspace navigation barにsample/population breadcrumb、parent移動、previous/next sample移動を追加する。表示状態のみを変更し、analysis definitionを変更しない。
- [x] 済み: GateEditor、WorkspaceTree、PopulationTreeのselectionをstable population/sample IDで双方向同期し、Plot highlightとbreadcrumbを更新する。selectionのみではdefinitionを変更しない。
- [x] 済み: `CopySubtreeAnalysisCommand`でresolved target strategy（population/sample/group scope）へsubtreeをatomic適用する。全targetの候補を事前検証し、一つでも失敗した場合は全targetを変更しない。
- [x] 済み: duplicate sibling name、cycle/missing parent、reference deleteを確定前preflightで表示し、失敗はUndo履歴へ追加しない。
- [x] 済み: MainWindowのUndo/Redo action・Ctrl+Z/Ctrl+Shift+Z・enabled labelを追加し、保存時clean markerを更新する。Undo後のgate変更は既存stale経路へ入り、cache/reportを破棄するGUI回帰testを追加する。

### Phase B3.1: Gating definitionとExecuted Results workspaceの分離 [S07/S14]

現在のGate hierarchy、WorkspaceTree、Population Results、Custom Statisticsの常時縦積みは廃止する。Gate definitionとsampleへ適用した実行結果は異なるlifecycleを持つため、一つの巨大tableへ統合しない。

- [x] 済み: `docs/implementation/gating-and-results-workspaces.md`を全文読み、increment 1（state separation）を実装する。
- [x] 済み: MainWindowの表示状態を`active_sample_id`、`display_population_id`、`selected_gate_id`へ分離する。gate selectionとpopulation membership filteringを同一stateとして扱わない。
- [x] 済み: increment 4（right-pane tabs and duplicate removal）を実装する。
- [x] 済み: 右paneを`Gating`と`Results`のtabへ変更し、3つのtableを同時に縦積み表示しない。
- [x] 済み: increment 2（Gating semantics）を実装し、Gate definitionのroot・表示操作を定義する。
- [x] 済み: Gate hierarchyの先頭列を`Gate definition`へ変更し、Pipeline実行前・失敗時・results stale時も定義編集を維持する。
- [x] 済み: Gate hierarchy選択は`selected_gate_id`とoutline highlightだけを変更する。暗黙にchild populationへplotを絞り込まず、軸・scaleも変更しない。
- [x] 済み: `Show Gate`はgateの軸・scaleへ移動し、親populationを表示してgate outlineを強調する。`Show Population`はcurrentなPipeline resultがある場合だけgate由来のchild populationを表示する。
- [x] 済み: increment 3（Results hierarchy model/widget）を実装し、`ExecutionReport`を唯一の結果データソースとするtree-tableを追加する。
- [x] 済み: `ResultsWorkspace`へ`Sample -> All Events -> Population`のtree-tableを追加し、`Events`、`% Parent`、`% Total`、`Status`をExecutionReportだけから表示する。
- [x] 済み: sample rowと`All Events` rowを分ける。sample row選択はactive sampleだけを変更し、`All Events` row選択は`display_population_id = "all_events"`として全event表示を復元する。
- [x] 済み（B7.5で置換予定）: statistic resultはResults workspaceのpopulation childだけに表示し、現在のWorkspaceとCustom Statistics間の表示重複をなくす。値を割合列位置へ置く互換表示はB7.5の動的Statistic列で廃止する。
- [x] 済み: increment 5（Hierarchy/Flat table mode）を実装する。
- [x] 済み: 同じResults modelから`Hierarchy`と`Flat table`を切替可能にする。Flat tableは`Sample | Population | Parent | Events | % Parent | % Total | Status`を持ち、population名へindentを埋め込まない。
- [x] 済み: increment 6（status policy and transitional documentation）を実装する。
- [x] 済み: stale、missing、zero events、undefined/error statisticをResultsWorkspaceで区別する。stale membershipでplotをfilterせず、gate definition自体は有効なまま保持する。
- [x] 済み: Gate selectionがplot filterを変更しないtest、Show Gateが親populationを表示するtest、明示All Eventsで全eventへ戻るtest、Results選択がgate編集対象を変えないtestを追加する。
- [x] 済み: Hierarchy/Flat tableの結果値、GUI/headless/CLIの既存event count/frequency経路、既存gate編集、Undo/Redo、population filtering、strict GUI teardownの回帰確認を実施する。
- [x] 済み（延期）: 旧WorkspaceTree/PopulationTreeの完全削除は、既存export/statistics callerとlegacy testのResults API移行後に行う。現段階では非表示のtransitional adapterとして保持する。

### Phase B3.2: revision-safe current-sample preview [S07/S14]

正式なmulti-sample結果、export、QC、diagnosticsは引き続き`Run Pipeline`のauthoritative `ExecutionReport`だけを使用する。gate編集後の操作性を改善するため、active sampleだけを同じcore pipeline stageで再計算する非authoritative previewを追加する。単純な常駐thread＋FIFO queueにはしない。

- [x] 済み: `docs/implementation/interactive-current-sample-preview.md`を全文読み、番号付きincrementを一つだけ実装する。
- [x] 済み: increment 1としてimmutableな`PreviewRequest`/`PreviewReport`とGUI非依存`PipelineRunner.preview_sample()`を追加する。full-resolution active sampleへcanonical processing orderを適用し、同一snapshotのbatch実行とmembership、count、frequency、statisticを一致させる。
- [x] 済み: increment 2として`analysis_revision`、`authoritative_result_revision`、`preview_result_revision`、`preview_status`を分離する。上流定義変更時はrevisionを増加し、変更gateと全descendantをworker開始前にstale化する。
- [x] 済み: increment 2としてstale descendant membershipをplot filterへ使用しない。対象populationのcurrent-revision結果がなければ`All Events`へfallbackするrevision stateとGUI回帰を追加する。
- [x] 済み: increment 3としてmouse releaseまたは有効なnumeric edit確定後に200–400 ms debounceするlatest-wins schedulerを追加する。pending jobをrevisionごとにFIFO実行せず、未実行jobを最新revisionへcoalesceする。
- [x] 済み: increment 3としてworkerへimmutable project/sample snapshotを渡し、最大worker数を1とする。実行中jobの強制terminateはせず、古いrevisionの完了結果をGUI適用前に破棄する。
- [x] 済み: increment 4としてworkerがローカルで完全なpreview resultを構築し、GUI threadでrevision照合後にcacheと表示をatomic交換する。workerからQt widget、pyqtgraph item、共有membership辞書を逐次更新しない。
- [x] 済み: increment 4としてplotへ`Current Sample Preview`を追加し、sample/population、Events、`% Parent`、`% Total`、statistics、preview revision/status、`Batch results stale`を明示する。authoritative Results rowへ無印で混在させない。
- [x] 済み: increment 5として下位population選択時にtarget populationとそのrequested statisticsをpreview requestへ渡す。他sample、Group QC、authoritative exportはpreview対象にせず`Run Pipeline`へ残す。
- [x] 済み: increment 5として`Run Pipeline`開始前にpending gate editをcommitし、新規preview投入を抑止する。batch reportを実行snapshotのrevisionと照合し、実行中にdefinitionが変わったreportをcurrentとして受理しない。
- [x] 済み: increment 6としてrepeated dragをcoalesceするtest、out-of-order completionを破棄するtest、ancestor変更直後のdescendant navigation test、preview/batch数値一致test、display downsampling非依存testを追加する。
- [x] 済み: increment 6としてproject/window close時にtimerとlate resultを無効化し、running workerを残さない。代表event数でfull-resolution preview、queue長、clean scheduler shutdownを確認する。

Preview値は保存済みanalysis definitionから再生成できるderived cacheであり、authoritative exportへ直接使用しない。全sample自動再計算や細粒度branch cache reuseは、correctnessとbenchmarkが揃うまで実装しない。

### Phase B3.3: Results-integrated current-sample recalculation [S07/S11/S14]

B3.2で実装したcore preview、revision guard、debounce、latest-wins scheduler、
immutable snapshot、obsolete result discardは維持する。

B3.2で導入した独立`Current Sample Preview` panelと、stale時に
`display_population_id`を`all_events`へ強制変更するpresentation policyは、
このPhaseで廃止する。

- [x] 済み: `docs/implementation/results-integrated-current-sample-recalculation.md`を全文読み、increment 1だけを実装した。
- [x] 済み: increment 1として、authoritative `ExecutionReport`をbaselineとして保持しつつ、accepted current-sample `PreviewReport`をsample/population/statistic単位でoverlayするQt非依存`RuntimeResultState`を追加した。rowごとにrevision、source provenance、`current`、`recalculating`、`stale`、`error`、`missing`を表現する。
- [x] 済み: increment 1として、gate変更時はactive sampleの変更gateおよび全descendantを`recalculating`、他sampleの同じ範囲を`stale`にし、旧値を削除せずcontextとして保持する。preview completion前に値を部分更新しないatomic acceptとobsolete revision拒否をunit testした。
- [x] 済み: increment 2として、`ResultsWorkspace`をauthoritative reportとaccepted preview overlayの表示面にし、active sampleのaccepted previewを同一revision単位でatomicに適用して該当populationおよびstatistic rowを`current`へ変更した。
- [x] 済み: increment 2として、Hierarchy/Flat tableの双方で同じmerged result-stateを表示し、preview値のsource/revisionを内部data roleとtooltipで確認可能にした。Qt内で科学計算は行わない。
- [x] 済み: increment 3として、gate変更時に`display_population_id`、active sample、axes、scale、zoomを維持し、`self._display_population_id = "all_events"`の強制resetを削除した。
- [x] 済み: increment 3として、background再計算中は現在表示中の旧membershipを保持し、plotへ`Recalculating — displayed events are from the previous revision`を明示した。accepted preview completion時にResults state、membership cache、plotをGUI threadで一括更新する経路を接続した。
- [x] 済み: increment 3として、現在表示しているPopulationが削除された、または同じsampleで利用可能な旧membershipが存在しない場合だけ、親Populationまたは`All Events`へfallbackすることをGUI testした。
- [x] 済み: increment 4として、独立`Current Sample Preview` panelをlayout、MainWindow caller、testsから削除し、batch-stale情報をResults workspaceのrow statusと既存status/bannerへ移した。
- [x] 済み: increment 4として、`Run Pipeline`成功時にauthoritative baselineを置換し、preview overlayとrow-level stale/recalculating stateを整理した。batchがstaleな間は、active sample rowが`current`でもauthoritative export、QC、diagnosticsをcurrentとして扱わない既存境界を維持した。
- [x] 済み: increment 4として、gate変更中のdescendant表示維持、旧値＋recalculating、obsolete result破棄、active sampleだけcurrent、他sample stale、Run Pipeline後の全row current、export拒否、strict QThread teardownを関連GUI E2Eと115件のGUI suiteで検証した。

### Phase B4: Group strategyとsample override review [S08]

- [x] `docs/implementation/group-gating-and-overrides.md`を全文読み、通常は Group 共通 geometry を編集すること、override は明示作成のみであること、override resolution/rebase/comparison warning policyを追記する。
- [x] Group共通gate definitionとsample-specific geometry overrideを別modelで表現する。override は Group の複数化とは独立した高度機能とし、既定では無効にする。
- [x] overrideにbase ID/version hash、delta/full geometry、author、time、reason、gate purpose（technical cleanup / comparison-critical）を保存する。
- [x] headless `PipelineRunner`でGroup共通strategyへselected sampleの明示overrideだけをdeterministically解決し、stale baseは再計算前に拒否する。
- [x] sample navigation中に同じPopulation path、axes、scale、view rangeを維持する。
- [x] shared/override/stale/missingをtree badgeとplot bannerで表示する。`results stale`（再計算が必要）と `override stale`（base変更によりrebaseが必要）を別状態として表示する。
- [x] 通常のgate drag/editは Group 共通 geometry を変更する。sample override は `このsample用のgate調整を作成` の意図的なcommandでだけ作成し、理由入力と影響範囲の確認を要求する。
- [x] GUIの明示override dialogからcore `CreateGateOverrideCommand`を呼び、GateEditorのshared geometryとplotのresolved geometryを分離する。
- [x] reset-to-group、promote-to-group、copy-to-selectedを別commandにする。comparison-critical gate のoverride/promoteは強いwarningと監査記録を必須にする。
- [x] Groupへsubtree適用前にchannel mappingを全sampleでvalidateする。
- [x] frequency outlier、gate boundary clipping、missing Population、override一覧、comparison-critical override warningをQC panelへ表示する。`missing` は0 eventsやdisplay fallbackと区別する。
- [x] GUI確認値とbatch headless resultsを一致させるE2E testを追加する。Group共通geometry、technical override、comparison-critical warning、stale base/rebaseは検証済み。missing channelはGUIにsubtree適用操作が存在せず実行対象がないためGUI E2Eをskipし、core atomic preflightで検証済み。

### Phase B5: Auto、magnetic、tethered、clone gates [S06]

各gateを一つずつ独立subphaseで実装する。まとめて実装しない。

#### Auto gate subphase

- [x] `quantile_rectangle.v1` のprimary method、parameters、fit failure、determinismをimplementation guideへ記載する。
- [x] template definitionとsample-specific fitted geometry/provenance modelを分離する。
- [x] full Populationのfinite eventsだけを使う決定的fitとsynthetic numeric testを追加する。
- [x] headless runner、project save/load、GUI表示をAuto fit resultへ接続する。

#### Magnetic gate subphase

- [x] `largest_gap_range.v1` のprimary/reference method、parameters、fit failure、determinismをimplementation guideへ記載する。
- [x] template definitionとsample-specific fitted geometry/provenance modelを分離する。
- [x] full Populationのfinite eventsだけを使う決定的fitとsynthetic numeric testを追加する。
- [x] headless runner、project save/load、GUI表示をmagnetic fit resultへ接続する。

#### Tethered gate subphase

- [x] `translated_rectangle.v1` のanchor、offset、fit failure、determinismをimplementation guideへ記載する。
- [x] template definitionとsample-specific fitted geometry/provenance modelを分離する。
- [x] anchor geometryから決定的にtethered gateを生成するsynthetic numeric testを追加する。
- [x] headless runner、project save/load、GUI表示をtethered fit resultへ接続する。

#### Clone gate subphase

- [x] `clone_gate.v1` のleader、conflict policy、同期group、Undo behaviorをimplementation guideへ記載する。
- [x] template definitionとsample-specific synchronized geometryを分離する。
- [x] leader_winsとreject_conflict、apply/undoのsynthetic testを追加する。
- [x] clone同期をGUI-independent core commandとして実装し、GUIは結果表示に限定する。

- [x] 各numeric algorithmについてprimary/reference method、parameters、fit failure、determinismをimplementation guideへ記載する。cloneはnumeric fitではなく同期commandとして定義する。
- [x] template definitionとsample-specific fitted geometryまたは同期結果を分離する。
- [x] fitted resultまたは同期結果へinput/provenance、algorithm version、diagnostics、before/after stateを保存する。
- [x] manual override後の再fit policyをnumeric templateへ、cloneの競合policyを同期groupへ定義する。
- [x] clone gateの同期group、leader/conflict、Undo behaviorを定義する。
- [x] numeric fitはdensity downsamplingではなくfull Populationを使用する。
- [x] synthetic distributions、edge cases、clone conflict/undoでnumeric/core testする。

### Phase B6: Graph Window plot types [S09]

- [x] `docs/implementation/graph-window-v2.md`を全文読み、plot typeのaggregation/display policyを追記する。
- [x] `PlotViewSpec`をmodel化し、Population、axes、transforms、plot type、range、styleを保存する。
- [x] dot/scatter、pseudocolor、density、contour、histogram、CDFをcore display adapterへ段階実装する。
- [x] density/contour binningはfull selected Populationを入力にする。
- [x] rendering downsampleとdensity aggregationの設定を区別する。
- [x] duplicate graph view definitionとlinked sample navigation stateを保存可能にする。複数window UIは既存single-window構成では不適切なためview registryへ集約する。
- [x] selection、gate draw、pan/zoom modeをdisplay APIで排他的に表現する。
- [x] gate label、Population statistics、compensation badgeを既存GUI overlay経路で表示する。
- [x] PNGに加えSVG/PDF exportとmetadata sidecarを追加する。
- [x] 全plot typeについてempty、NaN/Inf、logicle caller input、large eventのcore display testを追加する。

### Phase B7: Overlayとbackgating [S10]

- [x] `docs/implementation/overlay-and-backgating.md`を全文読み、normalizationまたはprojection policyを追記する。
- [x] OverlaySpecとBackgatingSpecをcoreへ追加する。
- [x] 1D overlayのcount/mode/unit-area normalizationを実装する。
- [x] 2D overlayはPopulationごとの色とalphaを保存する。
- [x] backgatingはrunner membershipをancestor viewへ投影するだけにし、GUIで再評価しない。
- [x] target、parent background、ancestor gateを視覚的に区別するstyleを保存する。
- [x] project save/load、headless display preparation、GUI display layer APIを同じdefinitionで接続する。

### Phase B7.1: Multi-sample overlay and plot presentation [S09/S10/S13/S24]

> 2026-07-22 end-to-end監査: 以下のcheckはmodel/editor/persistence/export metadataの
> 完了履歴を示すが、persisted `overlay_sources`は現在のlive renderer入力ではない。
> Advanced Overlayの有効化とlive描画受け入れはPhase B7.4で未完了として扱う。

Phase B6/B7で完了した`PlotViewSpec`、plot type、display preparation、
`OverlaySpec`/`BackgatingSpec`、membership-based overlay preparation、export基盤を維持する。
それらの完了履歴は、multi-sample source selection、完全なstyle editor、
title/axis/legend編集が実装済みであることを意味しない。

実装前に`docs/implementation/multi-sample-overlay-and-plot-presentation.md`を全文読む。
一度のLLM/Codex実行では、以下の番号付きincrementを一つだけ実装し、後続incrementへ
着手しない。未実装項目は受け入れ条件を満たすまで`[ ]`のままにする。

#### Increment 1: Model and compatibility contract

- [x] 現行`OverlaySpec`/`PlotViewSpec`の不足を確認し、multi-sample overlay source、typed presentation style、schema extension、migration方針を定義する。
- [x] source sample、Population、X/Y parameter、X/Y transform、unitをstable identityで保存し、active sampleから独立したsource order/visibilityを表現する。
- [x] stable channel identityとsemantic parameter/unit/transformを使うGUI非依存compatibility resolverを追加し、compatible/incompatible/ambiguous/missingをstructured diagnosticで返す。ambiguous mappingをuser confirmationなしに確定しない。
- [x] presentation style modelをanalysis definitionから型として分離し、automatic assignmentとmanual override、plot typeごとのsupported style matrix、unsupported style validationを定義する。
- [x] source追加・削除・並べ替え・visibility、source style、title/axis display label/legendのsave/load/migration testを先に追加する。display labelとstable parameter IDを別fieldとしてround-tripする。

#### Increment 2: Overlay source selection GUI

- [x] overlay sourceの追加、削除、並べ替え、表示/非表示を行うGUIを追加し、sample、Population path、X/Y parameter/transformをstable IDで選択する。
- [x] compatible/incompatible/ambiguous/missingをtext/iconと詳細diagnosticで表示し、missing sourceをzero eventsとして表示しない。
- [x] sourceごとのcolor、alpha、legend labelの基本編集を追加し、manual overrideの有無を表示する。
- [x] source selection変更はdisplay definitionだけを更新し、gate、transform binding、membership、Statistic definitionを変更しない。
- [x] add/remove/reorder/visibility/style editをproject mutation Undo/Redo対象とし、active sample navigationやpipeline result revisionはUndo payloadへ含めない。

#### Increment 3: Plot style editor

- [x] title、optional subtitle/annotation、X/Y axis display label、legend visibility/position/orderを編集する。
- [x] sourceごとのmarker shape/size/color/alpha、line color/width/style、histogram fill/outline/alphaを編集する。
- [x] plot background、gate outline color/width/line style、plot typeごとのcolormap、title/axis/tick/legend fontを編集する。
- [x] plot typeごとのsupported/unsupported style matrixをUIとvalidatorで共有し、unsupported fieldを黙って無視しない。density/pseudocolor/contour固有styleは必要なら別subincrementとして一種類ずつ実装する。
- [x] automatic style assignmentとmanual override、reset-to-view-default、reset-to-project/global defaultを区別する。
- [x] edit中はdisplay-only previewを更新し、pipelineを再実行せず、scientific resultsが不変であることをtestする。

#### Increment 4: Renderer, export, persistence and reuse

- [x] GUI rendererとGUI非依存/headless export rendererが同じresolved source orderとpresentation definitionを使用する。
- [x] PNG/SVG/PDFへ同じtitle、axis labels、legend、source style、gate styleを適用し、metadata sidecarへsample/population/parameter/transform IDsとstyle provenanceを記録する。
- [x] project save/load/reload、duplicate plot/viewでoverlay sourceとpresentationを再現する。
- [x] Layout Editorがpresentation definitionを参照またはprovenance付き複製できるようにし、Layout独自overrideを科学定義から分離する。
- [x] Templateではsample ID固定参照とmapping可能なsource role/pathを区別し、ambiguous/missing mappingをconfirmation/diagnosticなしに適用しない。
- [x] style解決優先順位を`view override > project display default > global preference > built-in default`として実装し、resolved provenanceを確認可能にする。
- [x] GUI/headless/export consistency、font fallback、blank output、missing source、strict teardownをE2E testする。全体`pytest -q`で870件が通過し、Qt teardownのDeferredDelete flushも安全なevent処理へ修正した。

#### Phase B7.1 必須受け入れtest

- [x] 2つ以上の異なるsampleのPopulationをoverlayできる。
- [x] channel orderが異なるsampleでもstable identityにより正しい軸へmappingされる。
- [x] ambiguous/missing/incompatible channelをsilent fallbackしない。
- [x] source追加・削除・並べ替え・visibilityがsave/loadされる。
- [x] sourceごとのcolor、alpha、marker、legend labelがsave/loadされる。
- [x] title、axis display label、legend設定がsave/loadされる。
- [x] axis display label変更がparameter ID、transform ID、gate membership、科学計算を変更しない。
- [x] plot style変更がgate membership、count、frequency、statisticsを変更しない。
- [x] rendering downsampleを変更してもscientific valuesが変わらない。
- [x] GUI previewとPNG/SVG/PDF exportが同じsource順、label、styleを使用する。
- [x] unsupported styleは黙って無視せずvalidationまたはstructured diagnosticを出す。
- [x] missing overlay sourceをzero eventsとして表示しない。
- [x] project reload後にoverlayとstyleが再現される。
- [x] Layout Editorへ配置したplotが元のpresentation definitionと一致する。
- [x] headless環境でfont fallbackが発生してもblank outputやmissing sourceを成功扱いにしない。

### Phase B7.2: Integrated overlay controls and plot appearance UX [S07/S09/S10/S24]

> 2026-07-22 end-to-end監査: Samples paneのmanual/comparison overlayはlive描画へ
> 接続されている。一方、advanced `Overlay Sources...`との双方向同期およびpersisted
> advanced sourceのlive layer描画は確認できないため、Phase B7.4のguardを外さない。

Phase B7.1で完成したmulti-sample source model、typed presentation、compatibility
resolver、renderer/export、保存、Undo可能な汎用editorを維持する。B7.1の完了は、
日常的なgating中のmanual overlay、population color、plot appearance操作が統合UIから
利用できることを意味しない。通常操作をplot area、Gate hierarchy、Samples paneへ
統合し、高度なsource/axis/transform組合せには既存dialogを残す。

実装前に`docs/implementation/integrated-overlay-controls-and-plot-appearance.md`を全文読む。
一度のLLM/Codex実行では以下の番号付きincrementを一つだけ実装し、後続incrementへ
着手しない。Phase B7.1の完了checkや履歴は変更しない。

#### Increment 1: Interaction-state and precedence contract

- [x] 現行Samples list、active sample、overlay source、plot view、presentation状態を調査し、既存sample checkboxの意味を確認する。現行Samples listにはcheckboxがなく、行選択が`active_sample_id`を変更するため、新しい`Ov`専用列を計画し、別目的のcheckboxが将来存在しても転用しない。
- [x] `active_sample_id`、`display_population_id`、`selected_gate_id`、`manual_overlay_sample_ids`、`manual_overlay_colors`、`automatic_overlay_sources`、`comparison_set_definitions`、`overlay_mode`、`population_display_colors`、`plot_presentation`を独立状態として定義する。
- [x] manual overlayをactive sampleから分離し、active sample自身をoverlay sourceから除外して二重描画しないcontractを定義する。
- [x] 1対1と1対多を表現できる`ComparisonSet`/comparison role modelを科学的`SampleGroupSpec`・strategy bindingから分離して定義する。
- [x] population display colorをgate geometry、parent relationship、membership、statistics、pipeline revisionから分離したdisplay definitionとして定義する。
- [x] source deduplication、resolved label/style provenance、`manual source override > comparison source override > comparison role style > automatic source style`を定義し、最終color fallbackを`explicit overlay source > comparison role > sample automatic overlay > population display > plot default event`とする。
- [x] plot/view、project metadata、project display settings、global preferenceの保存範囲と、B7.1 projectを意味変更せず読むmigration方針を定義する。既存modelで表現可能な部分に不要なschemaを追加しない。
- [x] Qt非依存model、round-trip、deduplication、precedence、active/manual分離、科学値不変testをproduction codeより先に追加する計画を確定する。

#### Increment 2: Plot context appearance menu

- [x] plot areaの右クリックから`Plot Appearance...`、background、title、axis labels、fonts、legend、default event style、resetへ到達できるcontext menuを追加する。
- [x] context menuと既存Analysis menuは同じpresentation command/modelを呼び、別設定modelを作らない。
- [x] title、subtitle、X/Y display label、background、font、legend、default event color、dot size、opacityを編集し、resetはview overrideを除いて下位defaultを露出させる。
- [x] pan、gate drawing、ROI drag中の右クリック競合・誤作動を防ぎ、keyboardからも同じ操作へ到達できるようにする。
- [x] appearance変更でpipelineを実行せず、stable parameter ID、transform、gate coordinates、membership、statisticsを変更しないtestを追加する。
- [x] project reloadとGUI/PNG/SVG/PDFが同じpresentation definitionを使用するtestを追加する。

#### Increment 3: Gate hierarchy population colors

- [x] Gate hierarchyへ`Color`列とQColorDialogを使うswatchを追加し、hex直接入力を通常導線にしない。
- [x] row context menuへ`Population Color...`、`Gate Outline Color...`、`Use Population Color for Outline`、`Reset Population Color`を追加する。
- [x] active sample base layerでは最も深いdescendant population colorを優先し、同じ深さのoverlapはpersisted display z-order、未指定時はstable hierarchy preorderとstable population IDによる決定規則で解決する。
- [x] selected gate highlightをpopulation colorから分離し、outline、handle、selection markerで表示する。
- [x] population color変更がgate ID/geometry/parent、membership、count、frequency、statistics、pipeline revisionを変えないtestを追加する。

#### Increment 4: Samples manual overlay controls

- [x] Samples paneを少なくとも`Ov | Color | Relation | Name`相当の専用列を持つmodel/viewへ更新し、行選択はactive sample、`Ov` checkboxはmanual overlayだけを変更する。
- [x] `Color` swatchからQColorDialogを開き、Cancelではstateを変更しない。active sample行はcheckboxをdisabledにするか、二重描画されない理由をtooltipで示す。
- [x] checked sampleについて現在の`display_population_id`と同じstable population ID/path/mapping role、現在のstable X/Y parameter IDs、transforms、plot typeをB7.1 resolverで解決する。
- [x] missing population、ambiguous path、missing channel、incompatible unit/transform、unresolved sampleをwarning iconとtext/tooltipで示し、zero eventsやsilent omissionへ変換しない。
- [x] active sample navigation中もmanual overlay checkbox/colorをplot viewに維持し、persistent positive/negative/reference controlを常時表示できるようにする。role変更はGroup bindingや科学解析を変更しない。
- [x] simple controlsとadvanced `Overlay Sources...` dialogを同じsource/view stateへ同期し、異なるpopulation/axis/transformの高度設定はdialog側へ残す。
- [x] resolved layersを既存rendererへ接続し、active sample二重描画防止、色優先、fallback provenance、navigation維持をGUI E2E testする。

#### Increment 5: Comparison sets and automatic paired overlays

- [x] 1対1と1対多を保存できるComparisonSet membership、comparison role、role default colorをproject metadata/display settingsへ追加する。
- [x] sample multi-selection context menuへ`Create Comparison Set...`、`Pair Selected Samples...`、`Add to Comparison Set...`、`Edit Comparison Relation...`、`Remove from Comparison Set`を追加する。
- [x] Samples paneへ通常は`Manual only`と`Manual + comparison set`を示すoverlay mode selectorを追加し、必要性がtestで示された場合だけ`Comparison set only`を追加する。
- [x] `Manual + comparison set`でmanual checked samplesとactive sample所属setのother membersの和集合を解決し、active sample変更時にcomparison membersを再解決する。
- [x] 同一sampleがmanual、persistent control、comparison経路で重複しても一度だけ描画し、source override、role color、automatic style、labelを決定的に解決する。
- [x] pair双方向、1対多round-trip、manual+automatic同時使用、missing member diagnostic、Group/strategy非変更をtestする。

#### Increment 6: Persistence, export, migration and final UX cleanup

- [x] project reload後にmanual overlay、persistent control role、comparison set、source/role/population colors、plot appearance、overlay modeを復元する。
- [x] GUI、PNG、SVG、PDFで同じresolved source order/styleを使用し、metadata sidecarへdeduplication、fallback、resolved style provenance、diagnosticを記録する。
- [x] B7.1 projectをactive sampleとmanual overlayを混同せずmigrationし、schema version変更が必要な場合はこのincrementで別途明示する。
- [x] advanced dialogsとの責任分界を最終確認し、同じcommandへ到達する重複menu actionだけを整理する。advanced dialog自体は削除しない。
- [x] strict Qt teardown、keyboard navigation、accessible name/tooltip、non-color-only statusを含むGUI E2Eを追加する。
- [x] user guideとscreenshotsを最終UIへ更新する。READMEへ統合操作の利用導線を追記し、GUI回帰テストをスクリーンショット検証の入口とする。

#### Increment 7: Plot appearance compact editor, axes, ticks and range gesture

Plot appearanceの設定項目が増えたときも小さいモニタで操作できるようにし、軸・目盛りの視認性と範囲操作を改善する。既存の`PlotPresentationSpec`、表示専用設定、PNG/SVG/PDF出力、gate編集の座標・解析結果は変更しない。

- [x] `docs/implementation/integrated-overlay-controls-and-plot-appearance.md`へ、compact appearance editor、axis/tick style、superscript tick formatter、Ctrl+左ドラッグ範囲操作のUI/keyboard contractを追記する。production codeより先に画面サイズ、minimum size、focus/escape/cancel、保存範囲を確定する。
- [x] `Plot Appearance...`を一枚の大きなdialogから、`Background`、`Title/Labels`、`Fonts`、`Axes/Ticks`、`Legend/Event Style`など項目単位のcompact dialogまたはstacked pagesへ分割する。各画面はモニタ内に収まり、共通のtyped presentation command/modelを使い、Cancelで変更を破棄し、既存設定のproject/view/global provenanceを維持する。
- [x] plot areaのX/Y軸線（axis spine）と必要な枠線の太さを視認性のよい既定値へ変更し、設定可能な`axis_line_width`（または同等のdisplay-only field）を追加する。背景・軸色とのコントラスト、PNG/SVG/PDF、Reset、save/loadを確認し、gate outlineやdata strokeとは別設定にする。
- [x] 目盛りラベルのフォントを既定で現在より大きく太字にし、`tick_font_size`と`tick_font_weight`（またはtyped FontSpec）を設定可能にする。title/axis label/legend fontと独立させ、表示設定変更でpipeline、membership、count、frequency、statisticsを変更しない。
- [x] 目盛りの指数表記を文字列の`e+06`ではなく、仮数部と指数部を分離した右上付き文字として描画する。linear/log/asinh/analysis transformのtick値とラベル、負指数・負値・0、SVG/PDF/PNG出力で位置・読みやすさ・コピー時のfallbackを確認する。tick表示はcoreのtick座標・event value定義と一致させる。
- [x] plot areaで`Ctrl + 左ボタンのドラッグ`を、右クリックメニュー導入前の右ドラッグと同じ連続ズーム（押下位置を中心にX/Y範囲を拡大・縮小）へ割り当てる。通常の左ドラッグ、Pan、gate rectangle/polygon/ROI編集、右クリックcontext menuと競合させず、ViewBoxの既存倍率計算とdata-coordinate anchorを使う。
- [x] Qtテストで、compact dialogのminimum size/複数ページ遷移/Cancel、axis widthとtick fontのstyle適用、指数superscriptのlabel/export、Ctrl+左ドラッグのrange変更と他のmouse gesture非干渉をstable objectNameとsynthetic eventで検証する。GUI/headlessの科学的結果不変、project save/load、PNG/SVG/PDF再現を受け入れ条件にする。
- [x] 実装後に`./tools/run-gui-tests.sh -q`、plot presentation/plot widget関連core test、ruff、`git diff --check`を実行し、小さいモニタ・高DPI・offscreen Qtで残る制限を記録する。GUI 170件、core全902件、対象ruff、diff checkを完了。高DPI実機での目視確認は次のUX検証へ残す。

#### Phase B7.2 必須受け入れtest

Plot appearance:

- [x] plot areaの右クリックからappearance editorを開き、background、title、axis labels、font、legendを変更できる。
- [x] appearance変更でpipelineが実行されず、parameter ID、gate membership、statisticsが変わらない。
- [x] project reloadとPNG/SVG/PDFでappearanceが再現される。

Population color:

- [x] Gate hierarchyからpopulation colorを選択でき、nested populationではdeepest descendantが優先される。
- [x] sibling overlapの解決がdeterministicで、selected gate highlightとpopulation colorが混同されない。
- [x] population color変更で科学値とpipeline revisionが変化しない。

Manual/control overlay:

- [x] Samples listの専用`Ov` checkboxで別sampleを重ね、隣接swatchから色を変更できる。
- [x] active sampleは二重描画されず、active sample変更後もmanual overlayとpositive/negative control overlayが維持される。
- [x] explicit overlay colorがpopulation colorより優先し、未指定時だけfallbackとprovenanceを使用する。
- [x] checked sampleのsame population pathとstable axes/transformsが解決され、missing/incompatible sourceをzero eventsやsilent omissionにしない。
- [x] control role設定がGroup binding、gate strategy、scientific analysisを変更しない。

Comparison sets:

- [x] 2 sampleからpairを作り、どちらをactiveにしてもpartnerが自動overlayされる。
- [x] 1対多comparison setを保存・復元し、manual overlayとautomatic comparison overlayを同時使用できる。
- [x] 複数経路の同一sourceを一度だけ描画し、role color/source overrideの優先順位がdeterministicである。
- [x] missing comparison memberをsilentに無視しない。

Accessibility:

- [x] overlay、active、comparison、error状態を色だけで示さない。
- [x] checkbox、color swatch、relation iconにaccessible nameとtooltipがあり、keyboardだけで主要操作へ到達できる。
- [x] color dialogをCancelした場合はstateを変更しない。

#### Phase B7.2 post-completion follow-ups

The integrated overlay foundation and the following user-facing polish items from
`docs/bug.md` are now implemented. Keep their acceptance criteria with the checked
items so future changes do not regress the behavior.

- [x] Plot Presentationの色入力欄をQColorDialogまたは同等のカラーパレットから選択できるようにする。background、gate outline、source、line、histogram fill/outlineの各色でCancel時の非変更、hex値の正規化、project save/load、PNG/SVG/PDF表示一致を検証する。色変更はpipeline、gate geometry、membership、count、frequency、statisticsを変更しない。
- [x] Samples paneのmanual overlay色をクリアする`Clear Overlay Color`操作を追加する。色のクリアはsampleのoverlay選択状態やcomparison roleを変更せず、明示色を削除して自動色/fallbackへ戻す。project save/load、active sample変更、overlay描画、GUI/headless/exportの色解決を検証する。

#### Phase B7.2.Density: 滑らかな単一sample density color

現行の`Density color (single sample)`は、保存・overlay排他・表示専用という基本契約は
実装済みである。しかし固定128×128 occupancy grid、5色の最近傍色、表示downsample後の
入力によって、矩形の色ブロックと平坦な高密度領域が見える。詳細な実装指示、非目標、
アルゴリズム、cache key、test、benchmarkは
`docs/implementation/density-event-coloring.md`を唯一の正とする。一回のLLM実行で下記の
increment一つだけを実装する。

- [x] Increment 1: core NumPy estimatorを、全有効・変換後・viewport内イベントの
  aspect-aware histogram、Gaussian smoothing、bilinear interpolation、`log1p` + robust
  percentile normalization、連続256段階以上paletteへ置換する。raw/events、gate membership、
  count、frequency、statistics、pipeline revisionは不変であることを数値testする。
- [x] Increment 2: Qt previewでfull density inputとdisplay marker downsamplingを分離し、
  range/resize/transform/population/sample/revisionに対するdebounced cache invalidationを
  実装する。overlay中はdensityを無効にし、gating色へ戻す。20k/100k/1Mの測定を記録する。
- [x] Increment 3: batch PNG/SVG/PDFを同じcore estimator・logical viewport・event orderへ
  接続し、DPIがdensity値を変えないこと、vector modeで点や色を落とさないこと、sidecar
  provenance、GUI/export parity、user manualを完了する。

### Phase B7.3: Sample sheet、Results statistics、batch plot export [S02/S09/S11/S14]

サンプル名とは別に、利用者が指定する表示タイトルをExcel風の表で編集できるようにする。
同じ保存済みplot definitionを使い、全FCS sampleの画像をheadless/CLIから一括出力する。
また、Resultsからmean/medianを含む保存可能な統計定義を追加・選択・確認できるようにする。
これらは表示・export操作を起点にしても、compensation、transform、gate membership、raw eventを変更しない。

実装前に`docs/implementation/sample-sheet-results-and-batch-plot-export.md`を全文読む。
一度のLLM/Codex実行では、同ガイドの番号付きincrementを一つだけ実装し、後続incrementへ着手しない。

#### Increment 1: Sample title sheet

- [x] 既存`AnnotationSpec`を利用して、sample ID、読み取り専用のFCS file/name、編集可能な`sample_title`を一行ずつ表示するSample Sheet contractを定義する。`sample_title`はFCS keywordやraw metadataを変更せず、空欄時は明示されたdisplay-name fallbackを使う。
- [x] Qt model/viewベースの表を追加し、複数セル貼付け、fill series、undo/redo、型・重複・空値validation、filter/sort、Cancel時の非変更を実装する。セル座標やclipboard textを科学的IDとして扱わない。
- [x] titleのproject save/load、CSV import preview、headless annotation resolution、sample browser/overlay/Resultsでの一貫した表示名をtestする。stable sample ID、FCS path、runner inputはtitle編集で変化させない。

#### Increment 2: Saved batch plot export

- [x] `BatchPlotExportSpec`を保存可能なdisplay/export definitionとして定義する。対象sample（全件、Group、明示ID）、`PlotViewSpec`、output format/size/template、overwrite policy、missing/incompatible policy、metadata sidecarをstable IDで保持する。
- [x] GUI-independent export planner/runnerを追加し、各sampleについて既存のcompatibility resolver、full-resolution pipeline report、resolved overlay/presentation、headless rendererを同じ定義で呼ぶ。Qt widgetのscreen captureや表示downsampleを出力根拠にしない。
- [x] CLIとGUIから同じbatch runnerを呼び、PNGを先に、既存rendererが対応するSVG/PDFを追加する。sample titleを安全なfilename slugへ変換し、sample IDを衝突回避に残し、manifest/sidecarへresolved source/style/analysis revision/diagnosticを記録する。
- [x] empty population、missing file、unresolved/incompatible overlay、renderer failure、既存file collisionをsample別structured resultとして報告し、partial successを明示する。required outputの欠落やblank imageを成功扱いにしない。

#### Increment 3: Results statistic management

- [x] Results workspaceから`Add Statistic...`、edit、duplicate、remove、選択metric/parameter/population/percentile/source-stageを提供し、既存`StatisticSpec` editorと同一のGUI-independent command/validationを使う。mean、median、SD、CV、MAD、percentile等のmetricはcore定義に列挙されたものだけを選択可能にする。
- [x] Resultsにpopulation rowとは独立した統計detail/tableを追加し、値、unit、status、undefined reason、analysis revisionを表示する。empty/NaN/Inf/geometric-mean policyをQtで再計算・丸め判定しない。
- [x] `all_events`を対象にしたStatisticResultもResultsのAll Events行の直下へ表示し、計算済みなのにUIから見えない状態を防ぐ回帰テストを追加する。
- [x] statistic definitionの追加・変更・削除で結果をstale化し、`Run Pipeline`または既存current-sample preview経路でのみ更新する。統計の追加操作がgate/transform/compensation定義を変更しないことを保証する。
- [x] known-value core test、save/load/migration、GUI editor entrypoint、stale/current state、CLI/statistics exportとResults表示の一致を追加する。

#### Phase B7.3 必須受け入れtest

- [x] Sample Sheetで複数sampleのタイトルを表形式で編集・貼付け・保存/復元でき、FCS raw metadata、sample ID、path、eventsが不変である。
- [x] タイトル未指定、重複、空欄、CSV import validation、filter/sort、undo/redoが決定的に動作する。
- [x] 同じ`BatchPlotExportSpec`によるGUI起点とCLI起点の出力が、sample順、タイトル、plot definition、style provenance、analysis revisionにおいて一致する。
- [x] 全対象sampleのPNGが出力され、collision、missing/incompatible source、renderer error、partial failureがstructured reportとsidecarに残る。
- [x] バッチ画像exportの有無・表示downsample・style変更がraw events、membership、count、frequency、statisticsを変更しない。
- [x] Resultsからmean/medianなどのStatisticSpecを追加・編集でき、known values、undefined status、unit、revisionがheadless report/CLI exportと一致する。
- [x] GUIに科学計算または独自plot export定義を複製せず、core/headless runnerをGUIなしで実行できる。

#### Phase B7.3.E: Plot image export completion [docs/bug.md]

- [x] Batch Plot Exportのheadless rendererをGUI表示契約へ揃える。PNG/JPG/SVG/PDFで小さい半透明円、タイトル行とsource色、軸ラベル、transform由来のtick、実線gateを同じrenderer-neutral sceneから出力し、Qt screenshot/captureに依存しないことをtestする。詳細は`docs/implementation/plot-export-completion.md` Increment 7。
- [x] `current_view` Batch ExportでGUI ViewBox範囲、表示済み軸ラベル、tick書式、font requestをsnapshotし、raw FCS名や全data範囲へfallbackしない。上付き指数・縦Y軸labelを含め、詳細は`docs/implementation/plot-export-completion.md` Increment 8。
- [x] Canonical `PlotScene`をcoreに定義し、GUI表示、single export、Batch/CLI exportが同じscene（parameter/transform/range/tick/title/source style/gate geometry/clipping/z-order）だけを描画するよう統合する。GUIの編集handle・作成previewはscene外へ分離し、scene構築が科学的結果を変更しないことを検証する。詳細は`docs/implementation/plot-export-completion.md` Increment 9。
- [x] 同一`PlotScene`のGUI/export visual-equivalence testを追加し、geometry/style/fontの差を測定・制限する。backend差によるpixel完全一致は同一backend利用時だけの保証とし、cross-platformではscene一致と明示的toleranceを受け入れ条件にする。詳細は`docs/implementation/plot-export-completion.md` Increment 10。
- [x] GUIから実行するBatch Plot Exportは、GUIと同じQt/pyqtgraph `PlotWidget` adapterで描画する。CLIはPySide6がない環境でも動作するQt非依存rendererを維持し、Qt backendは明示選択時に使用する。
- [x] Batch Plot Exportで出力サイズや1:1設定がGUIの現在ViewBox範囲を上書きしないようにし、population display colorとoverlay source colorをGUIと同じ表示レイヤーへ反映する。

- [x] Increment 11: Batch Plot ExportのWidth/Height/DPIを、Width/Heightは96 DPI基準の論理canvas、DPIはPNG/JPEGのraster densityとして明確化する。新規definitionではDPI倍率に応じて実pixel数と全visual要素（font、tick、dot、line、margin）を同倍率で描画し、既存projectは`legacy_pixel_dimensions`互換modeで過去の出力pixel寸法を維持する。SVG/PDFはA4固定やQt/pyqtgraphのPixmap cacheを使わず、canvasからpage sizeを決めたvector primitive出力とする。effective pixel/physical sizeのUI preview、sidecar/manifest provenance、PNG/JPEG density metadata、PDF/SVGにfull-canvas rasterがないこと、GUI/CLI/batchのscene/canvas一致、resolution変更がscientific resultとdisplay-sampling identityを変えないことをtestする。実装、互換性、残る単一plot Qt PDFの制限は`docs/implementation/plot-export-completion.md` Increment 11に記載。
  - [x] Qt raster出力をlogical-size widgetからdevice-pixel-ratio付きpaint deviceへ描く方式に修正し、既定font・axis label・tick density・cosmetic pen・dot・gateを含む表示比率がDPIで変わらないことを正規化画像testと実FCS出力で確認した。

#### Phase B7.3.F: Lightweight SVG/PDF scatter export

実装前に`docs/implementation/lightweight-vector-scatter-export.md`を全文読む。
一度のLLM/Codex実行では、以下の番号付きincrementを一つだけ実装し、test、文書更新、
commitを完了してから停止する。後続incrementを同じ実行で開始しない。

- [x] Increment 12: `BatchPlotExportSpec`、schema、migrationへ
  `vector_scatter_mode = full_vector | compact_vector | hybrid_raster` と
  `hybrid_scatter_dpi`を追加する。既存definitionは`full_vector`、新規definitionは
  `hybrid_raster`/600 DPIへ解決する。Qt非依存`VectorScatterPlan`、mode別typed layer、
  point/style/z-order/sampling identityを含む決定的hashとprovenance skeletonを実装する。
  rendererの出力形式はまだ変更しない。`VectorScatterPlan`の決定的hash/provenance、
  旧定義のfull_vector解決、新規定義のhybrid_raster/600 DPI既定値を実装し、core testと
  schema互換testを追加した。
- [x] Increment 13: `full_vector`を実装する。SVGはmarkerを`<defs>`で一度定義して
  eventごとに`<use>`を配置し、PDFはmarker Form XObject、graphics state、Flate圧縮
  content streamを再利用する。1 rendered event = 1 placement、scatter imageなし、
  clip/source order/style/alphaの一致をparser testで保証し、既存projectの出力意味を維持する。
  SVGの`<use>`とPDF Form XObjectを実装し、1 rendered event = 1 placement、透明度・marker形状・
  z-order/source orderを保持するtestを追加した。
- [x] Increment 14: `compact_vector`を実装する。同一styleごとにmarker footprintを
  spatial hashで決定的に非重複batchへ分割し、半透明dotの重なり濃度を失わない
  compound pathを最大4096 marker単位でSVG/PDFへ出力する。座標誤差を
  `1e-4` logical px以下にし、full vectorとのsame-backend RMSE、rare color、
  dense/sparse/duplicate/multi-source、path/node削減をtestする。単純な全circle unionは禁止する。
  3×3 residue spatial hashと同一cell slotで非重複compound batchを作り、SVG/PDFのpathへ
  出力する実装と、重複点・決定性・path削減のtestを追加した。
  大規模layerのhot pathではcellスケールとfloor関数、辞書lookupを一度だけ束縛して
  per-eventの計算を削減した。これはbatch順序・slot・compound pathを変更しない。
- [x] Increment 15: `hybrid_raster`を実装する。既存の決定的display pointsだけを
  canonical source-over順で透明lossless scatter layerへ描画し、SVGは埋め込みPNG、
  PDFはsoft mask付きImage XObjectとしてplot rectangleへ配置する。grid/axes/ticks/text/
  gates/legendはvectorのまま保持し、full-canvas raster、JPEG、silent DPI低下を禁止する。
  raster bounds/DPI/pixel size/encoding/point-plan hashをprovenanceへ記録し、canonical
  rasterとのRMSE、tile seam、rare-event visibility、memory limitをtestする。
  透明RGBA PNG scatter layerを共通生成し、SVGはembedded PNG、PDFはsoft-mask付きImage
  XObjectとしてplot rectangleへ配置する実装と、画像・DPI・provenanceのtestを追加した。
  alpha=1.0のマーカーだけは同じpixel-center predicateによるopaque row-maskを使い、
  alpha<1.0のsource-over合成とdensity/overlay色は従来の順序依存経路を維持する。
- [x] Increment 16: Batch Plot Export GUIへ3 mode selector、hybrid時だけ有効なscatter DPI、
  point/node/path/pixel/memory preflightを追加し、CLI/headlessと同じ保存済みplanを実行する。
  resource limit時はmodeを自動変更せずstructured failure/warningを返す。sidecar/manifest、
  cancel/save/restore/strict/partial failure、旧project互換、ユーザーマニュアルを完成する。
  GUI selector、hybrid DPI、canvas/memory preflight表示、CLIの同一spec実行、structured
  preflight diagnosticsのsidecar/manifest記録を実装した。resource limit時はmodeを変更せず失敗する。
- [x] Increment 17: 1k/5k/20k/100k/1M points、sparse/dense/overlap、複数alpha/color/source、
  rare populationを含む決定的benchmarkを追加する。bytes、時間、peak RSS、SVG DOM数、
  PDF resource/command数、parse/open/rasterize時間、visual RMSE、科学的結果の完全一致を測る。
  最初にthresholdなしbaselineを保存し、安定したCI metricだけに回帰thresholdを設定する。
  Hybridの大規模出力改善、Compactのnode削減、Fullの完全配置、3 mode間でraw events、
  membership、counts、frequencies、statistics、sampling identityが不変であることをrelease
  acceptanceとする。`vector_scatter_benchmark.py`と決定的fixture、3 modeのbytes/time/RSS/
  SVG/PDF構造測定、chunk制限、layer hash/event count不変性検査を追加した。thresholdはbaseline
  保存時点では未設定とし、CI回帰値を固定しない。

`docs/bug.md` のplot画像export要求は、既存のsingle PNG/SVG/PDF exportと
`BatchPlotExportSpec`だけでは完了していない。実装前に
`docs/implementation/plot-export-completion.md`を全文読む。一度のLLM/Codex実行では
同ガイドの番号付きincrementを一つだけ実装する。

- [x] Increment 1: GUI/CLI共通のtyped export options、JPEG format、portable filename
  slug、well prefix、multi-source prefix、collision/provenanceをcore/schema/migrationへ
  追加する。wellは明示plate assignmentを優先し、filename tokenの暫定fallbackは
  provenanceを残して曖昧な文字列をwellと扱わない。
- [x] Increment 2: canonical processed displayとresolved overlay/presentation/gateから
  renderer-neutral export sceneを作る。batchではshared transformed range、axes、ticks、
  marginsをpreflightして、比較画像のplot originと軸表示を揃える。
  - [x] persisted export optionsをcore rendererへ渡し、サイズと1:1 aspect、title/label/legendの表示制御を反映する。
  - [x] `shared_ranges` のcanonical transformed X/Y boundsをbatch開始前に計算する。
  - [x] overlay、gate、ticks、marginを共通sceneとして出力する。
- [x] Increment 3: plot area右クリックのExport submenu、PNG/JPEG/SVG/PDF、Batch Plot
  Export導線、format/path/1:1/layout/inclusion options dialogを追加する。toolbarと
  context menuは同一request builderだけを使う。
- [x] Increment 4: single/batch、overlay/gate/color/title、well filename、collision、
  missing/incompatible source、renderer failureのcore/CLI/GUI E2E testとユーザーマニュアルを
  完了する。exportがraw events、membership、statistics、analysis revisionを変更しないことを
  検証する。GUI exportでは編集用gate handleを隠し、outlineを実線にする。
- [x] Increment 5: `Results -> Batch Plot Export...` とplot area右クリックの同一dialogから
  `BatchPlotExportSpec`を新規作成・編集・選択して実行できるようにする。target、plot view、
  format、size/DPI、1:1、layout、表示要素、filename template、collision/strictness、output
  directoryを指定し、project保存後に既存CLI/headless runnerだけで実行する。output directoryは
  projectへ保存しない。cancel、save失敗、partial failure、複数definition選択のGUI testを追加する。
- [x] Increment 6: Batch Plot Exportが現在のplot viewと異なる先頭FCS channelへfallbackする
  回帰を修正する。project保存時にactive viewのstable X/Y parameter ID、transform ID、
  population、plot type、overlay/presentationを一つの`PlotViewSpec`として同期し、CLIは
  不完全viewを明示的に失敗させる。`PipelineRunner.prepare_display_sample()`の出力へtransformを
  再適用しない。axis label/tick/gateが同一の座標系・definitionからrenderされることを
  PNG/SVG/PDF/sidecarでE2E検証する。

受け入れ条件:

- [x] single exportとbatch exportが、選択されたoverlay、gate、presentation、title、axis
  label/tick、色を定義どおりに出力し、sidecar/manifestへresolved provenanceを残す。
- [x] overlayなしのwell `A1`は`A1_*.png`、A1/B2 overlayは`A1_B2_*.png`となり、Windows、
  macOS、Linuxで安全なファイル名かつ衝突検出後も決定的である。
- [x] batch shared-layout exportは、全出力でX/Y range、tick位置、plot area位置、label余白を
  揃え、PNG/JPEG/SVG/PDFの対応rendererで非空の出力を作る。
- [x] toolbar/right-click/GUI batch/CLI batchが同じexport definitionを使い、GUIに独自の
  scientific computationまたは別plot identityを作らない。
- [x] Batch Plot Export dialogから設定なしのprojectでもdefinitionを作成して実行でき、保存済み
  definitionを選択・更新・再実行できる。出力先はユーザーがその都度指定し、project移動後も
  保存済みdefinitionが有効である。
- [x] Batch Plot Exportは現在選択中のFITC/APC等の軸、formal transform ID、population、
  visible overlay、gate、axis label/tickをsingle exportと同じdefinitionで出力する。不完全な
  viewが先頭FCS channelや空のlabel/gateへ暗黙fallbackすることはない。

### Phase B7.4: Analysis workflow integration [S02/S04/S05/S07/S09/S10/S11/S14]

既存Phaseでcore model、editor、保存形式が完成していても、通常GUIのselector、plot、
Results、Sample Sheet、live overlayへ接続されていない機能はend-to-end完了とみなさない。
このPhaseではDerived Parameterを通常のparameterとして利用可能にし、transform authoring、
statistics、sample metadata、overlay、menuの責任を利用者のworkflowに合わせて統合する。

実装前に`docs/implementation/analysis-workflow-integration.md`を全文読む。一度の
LLM/Codex実行では番号付きincrementを一つだけ実装し、dialogの表示またはsave/loadだけで
完了にしない。各incrementのcore/GUI/headless/CLI acceptance testが通るまで`[ ]`を維持する。

#### Increment 1: 未完成featureのguardとmenu ownership

- [x] 未実装期間は`Advanced Overlay Sources... (Not implemented)`をAnalysisからPlot/Viewへ移し、development/alphaではdisabled、releaseでは非表示にした。Increment 7のlive-layer/E2E完了後は同じcapability policyでPlot/View actionを有効化し、未接続editorを開かない。
- [x] Samples paneの`Ov`が現在のsupported overlay workflowであることをtooltip/statusへ示す。既存projectの`overlay_sources`は削除・変換せずround-tripする。
- [x] `Analysis -> Population Statistics...`を削除し、ResultsのAdd/Edit/Duplicate/Remove/Manageへ統合する。Population/Graphのshortcutも同じcommand/validatorだけを呼ぶ。
- [x] top-level `Sample Annotations...`を削除し、通常導線を`Data -> Sample Sheet...`へ統合する。`Analysis Transforms...`は`Manage Parameter Transforms...`へ改称し、display-only actionをAnalysisから除く。
- [x] menu location、label、objectName、enabled/visible state、tooltip、keyboard access、project/pipeline非変更をGUI testする。

#### Increment 2: 共通Parameter Catalog

- [x] acquired channelとderived outputをstable parameter IDで表すGUI非依存catalog/resolverを追加する。display name、kind、unit/source provenance、definition/expression、inputs、sample applicability、available/missing/stale/error/not-run、structured diagnosticを保持する。
- [x] catalogをX/Y axis、Channel/Parameter Information、Gate、Transform、Results Statistic、simple Overlayのparameter候補へ供給する。widgetごとの独自listを作らない。canonical processed display未実装の間、X/Yではderived entryを可視・disabledとする。
- [x] acquired順+derived display順を決定的に維持し、同名別ID、missing input、cycle、sample差、stale/errorでもentryを隠さず理由を表示する。
- [x] definition追加・編集・run/failure・project reload後にselector/statusを更新し、現在のstable IDを維持できない場合は先頭channelへsilent fallbackしない。
- [x] Parameters画面で`Parameter | Type | Source | Expression | Unit | Status`を表示し、FCS raw metadataはread-only detailとして保持する。

#### Increment 3: canonical processed display request/result

- [x] immutable project/sample snapshot、revision、Population、X/Y parameter/transform ID、plot type、display sampling policyを持つGUI非依存request/result APIを追加する。authoritative `ExecutionReport`へmutable GUI cacheを埋め込まない。
- [x] coreでraw -> compensation -> derived -> transform -> full-resolution membership -> population selection -> display preparation/downsampleの順に実行し、Qtでderived columnや科学計算を再実装しない。
- [x] 通常plotの科学座標源をraw `_event_data`からcanonical processed resultへ切り替える。failure時にrawへfallbackしてcurrent表示せず、last-valid stale/error bannerまたはnon-success placeholderを使う。
- [x] current-sample schedulerのdebounce/latest-wins/revision check/atomic adoptionを維持し、obsolete result、project replace、window close、worker exceptionをtestする。
- [x] known compensated+derived+transformed values、zero events、NaN、missing input/population、downsample不変性、raw immutability、preview/batch/CLI一致をtestする。

#### Increment 4: Derived Parameterの全GUI接続

- [x] derived outputをX/Y軸で選択し、synthetic ratioを正しい座標でplotできるようにする。定義直後はnot-run/staleとして見え、run後にcurrentへ更新し、errorでもentryを消さない。
- [x] derived軸上でrectangle/polygon/range gateを作成・編集し、GUI preview、authoritative batch、CLI/Pythonのmembership/count/frequencyを一致させる。
- [x] 同じderived stable IDをTransform、mean/median Statistic、compatible simple overlay、exportで使用し、save/reload後も同じID・unit・provenanceを解決する。
- [x] derived definitionの編集・削除前にderived dependency、transform、gate、statistic、view参照を列挙する。参照中はblockまたは明示的dependency-aware operationを要求し、silent cascade deleteしない。

#### Increment 5: transform authoringの一本化とlegacy migration

- [x] 軸に`Linear | Log10 | Asinh | Logicle | Custom...`の一つのtransform selectorだけを表示し、正式なimmutable/versioned `TransformSpec` registryと同じproject commandを使う。別のlegacy display transform計算を新規作成に使わない。
- [x] quick optionはparameter/settingsが完全一致する定義をreuseし、なければ新規versionを作る。plot axisと新規gateは同じtransform IDまたは明示されたidentity bindingを保存し、events、gate coordinates、membership、ticksで一度だけ適用する。
- [x] 参照中definitionはin-place変更せずduplicate/version作成と明示的gate/view migration previewを使う。compensation/derived後のcanonical inputで差分を評価する。
- [x] legacy `x_scale`/`y_scale`は読み込み可能にし、`Legacy Log10/Asinh`と表示して、geometry/membershipを維持する明示的migrationを提供する。legacy Logicle approximationをformal Logicleへsilent変換しない。
- [x] plot transform変更でnative compensated/derived domainのmean/medianが変化しないことをtestする。transformed statisticは`StatisticSpec`でvalue spaceとtransform IDを明示した場合だけ許可する。

#### Increment 6: Results StatisticsとSample Sheetの最終統合

- [x] ResultsだけでAdd/Edit/Duplicate/Remove/Manage Statisticを完結し、Parameter Catalogからacquired/derivedを選択する。Events/%Parent/%Total常設列とnamed/exportable StatisticSpecを区別する。
- [x] `Add Statistic...`でダイアログを開くだけでは未確定のStatisticSpecを追加せず、明示的な`New`クリック時だけ新規定義を作成する。
- [x] Sample Sheetを`Sample ID | File | Sample name | Title | annotation columns...`へ拡張し、Columns、Add Annotation Column、CSV import、paste、find/replace、fill series、Undo/Redo、type/provenance diagnosticを一画面で提供する。
- [x] FCS keyword/file/nameはread-only、Titleはworkspace `sample_title`、その他はtyped workspace/imported annotationとして既存core commandを使い、raw FCS metadata/eventsを変更しない。
- [x] `sample_title`変更はdisplay/exportだけ、Group rule参照annotation変更は影響assignment/resultをstale化、未参照annotation変更はanalysis revisionを変えないdependency-aware invalidationを実装する。
- [x] save/reload、GUI preview、Run Pipeline、CLI/export、annotation/group resolutionの一致と、cancel/invalid import/raw immutabilityをtestする。

#### Increment 7: Advanced Overlay end-to-end（科学的use case確定後のみ）

- [x] Samples paneの通常overlayで不足する科学的workflow（control/treatmentの名前付きPopulation比較）を文書化する。advanced source差分はsample、Population、label、style、visibility、orderへ限定し、active plotのparameter、transform、unit、plot type、range、bins、normalizationを全sourceで共有する。
- [x] 異なるchannel IDを比較する場合は明示的canonical parameter mappingを使う。sample別calibrationは共通unitへの変換として別定義し、per-layer arbitrary parameter/linear-log混在を拒否する。
- [x] simple/advanced sourceを同一のstatus resolverとprocessed-display requestへ接続し、membership、parameter、transform、dimensionality compatibilityを検証する。visible invalid sourceはaccept/render/exportでblockし、hidden definitionは保存する。
- [x] persisted advanced sourceをlive layerへ接続し、simple controlsとの同一renderer経路、save/reload、GUI export metadata、headless-compatible source順/style/provenanceを実装する。
- [x] Batch Plot CLIもraw event配列を直接plotせず、`PipelineRunner.prepare_display_sample`でderived/compensation/membershipを解決してからPNG/SVG/PDFへ渡す。
- [x] dialog stateやsidecarだけでなく、実際のlive plotted layer/dataを検証するE2E testを追加した後にcapability guardを有効化した。

#### Increment 8: Derived/transform non-finite value policy [scientific correctness]

`log(x)`、ratioの分母ゼロ、compensation後の負値、overflowなどで生じる`NaN`/`+Inf`/
`-Inf`を、表示上の都合だけで黙って解析から除外してはならない。policy、影響event数、
value domainはprojectに保存し、GUI/headless/CLI/exportで同じ結果とQCを返す。

- [x] `DerivedParameterSpec`と`StatisticSpec`にstableなnon-finite value policyを追加する。統計のdefaultは`strict`（non-finiteが一つでもあれば`undefined`）とし、有限値だけを集計する`exclude_invalid`は明示的opt-inにする。`clip`/epsilon置換は明示的な値・単位・科学的根拠を保存し、暗黙に行わない。
- [x] `StatisticResult`とlong/wide exportに`n_total`、`n_valid`、`n_invalid`、`invalid_fraction`、policy、undefined reasonを追加する。Resultsでは値を表示する場合も除外数・割合を確認可能にし、QCなしの「成功」にしない。
- [x] plot/histogramでは非有限座標を描画せず、parameter ID、expression、source stage、transform ID、invalid reason別event数をdisplay diagnosticへ出す。gate membershipでは非有限座標をgate外とし、gateごとの除外数を`ExecutionReport.diagnostics`へ残す。
- [x] `log(x + 1)`、asinh、logicle、censoring/LODなどは別々の明示的な科学定義として扱う。`log(x+1)`は非負量でzeroを定義域へ含める根拠がある場合だけ許可し、compensation後に負値を取り得るfluorescenceにはasinh/logicleまたは文書化されたcensoringを優先する。
- [x] derived `log(x)`で`x = 0`、`log(x + 1)`、negative compensated value、division by zero、overflowをsynthetic fixtureでtestする。GUI preview、Run Pipeline、CLI/Python、CSV/TSV exportでvalue、status、QC count、raw immutabilityが一致するE2E testを追加する。
- [x] existing project migrationを用意し、旧StatisticSpecのNaN除外挙動をsilentに変更しない。migration policyとversionをmanifest/provenanceに記録し、旧projectは明示的な互換modeまたはupgrade確認を要求する。historical manifestは`exclude_invalid` compatibility modeへ移行し、diagnosticを残す。

実装済みの下位項目:

- [x] `StatisticSpec.non_finite_policy`（`strict`/`exclude_invalid`）をschema、manifest validator、pipeline、Statistics Editorへ接続し、persisted pipelineではstrictを既定にする。
- [x] `StatisticResult`とQC-aware statistic exportへvalid/invalid event count、fraction、policyを追加する。旧QC情報なしの直接exportは従来headerを維持する。
- [x] `DerivedParameterSpec`にも`non_finite_policy`を保存し、Derived Parameter Editor、schema、manifest validator、headless parserでstableにround-tripする。Derived stageはevent alignmentを維持して非有限値を診断し、下流StatisticSpecがstrict/exclude_invalidを明示的に適用する。
- [x] 極端なLog10 viewportの逆変換overflow warningを表示計算に限定して抑制し、解析値を変更しないfixtureを追加する。
- [x] Display preparationとgeometric gate evaluationがNaN/+Inf/-Infを有限値へ変換せず、由来parameter・expression・stage・transform ID・理由別件数を診断情報へ保持するfixtureを追加する。
- [x] Derived evaluation自体も非有限出力を`derived_parameter_nonfinite_values`として記録し、expression、output ID、policy、NaN/+Inf/-Inf別件数をpreview/Run Pipelineへ渡す。
- [x] core fixtureで`log(x)`、`log(x+1)`、zero/negative domain、division-by-zero、asinh/logicle、raw immutabilityを確認する。
- [x] GUI previewとCLI/Python TSV exportを同じsynthetic derived sampleで実行し、strict/exclude_invalidの値・status・QC count・raw immutabilityを比較する。

#### Phase B7.4 必須受け入れtest

- [x] Derived ParameterがParameters、X/Y、Gate、Transform、Statistic、simple Overlay、exportで同じstable IDとして利用でき、reload後のCLI/Python結果と一致する。
- [x] GUI plotがcanonical compensation/derived/transform済みdataを使用し、raw fallback、double transform、stale-as-current、display-downsampled scientific resultがない。
- [x] transform authoring pathが一つで、新規gateの座標・membership・tickと同じdefinitionを使い、legacy migrationが固定membership fixtureを維持する。
- [x] Statistics管理がResultsへ、title/annotation管理がSample Sheetへ、display操作がPlot/Viewへ整理され、重複entry pointが別modelを作らない。
- [x] title、参照annotation、未参照annotationのinvalidationがdependencyどおりで、raw FCS bytes/eventsは不変である。
- [x] Advanced Overlayはlive render/save/reload/export E2E完了後にcapability guardを解除し、visible incompatible sourceをblockしつつ既存保存definitionを失わない。
- [x] 全GUI testがstable objectNameとstrict callback handlingを使い、終了時にQThreadが残らない。

### Phase B7.5: Results Statistics matrixと計算対象管理 [S07/S11/S14]

現在のStatistic child rowはmean等の値を`% Total`列位置へ表示するため、列の科学的意味が
誤っている。Populationを行、named Statisticを動的列とするmatrixへ移行し、複数Population
への一括適用と計算対象の制御をGUI/headless共通の保存定義として実装する。

実装前に`docs/implementation/results-statistics-matrix.md`を全文読み、一度のLLM実行では
番号付きincrementを一つだけ実装する。

#### Increment 1: Model、migration、runtime identity

- [x] `StatisticSpec.population_id`を後方互換な明示的`population_ids`へ拡張し、一つのstable Statistic IDを複数Populationへ割り当てられるようにする。GUIのAll/Subtree選択はaccept時点のstable ID集合として保存し、後から追加したgateを暗黙に含めない。
- [x] `compute_enabled`を保存可能なanalysis stateとして追加する。legacy definitionは単一targetかつenabledとして移行し、同名definitionを自動mergeしない。
- [x] `(sample_id, statistic_id, population_id)`をResult/preview/runtime cacheの一意keyにし、同じStatisticを複数Populationへ適用しても上書きされないcore testを追加する。

#### Increment 2: Headless multi-population executionと局所invalidation

- [x] `PipelineRunner`がenabled Statisticだけを明示target Populationごとにfull-resolution membershipで計算し、Group binding、preview、CLI/Python、disabled provenanceへ同じ定義を適用する。
- [x] sample/stage/parameter/transformの値列とmembershipを再利用し、analysis revision、upstream dependency、Statistic ID、Population ID、non-finite policyを含むcache keyと局所invalidationを実装する。display downsampleやviewport visibilityを計算条件にしない。
- [x] mean/median/percentile、overlapping hierarchy、empty/undefined/non-finite、disabled、複数sampleのknown-value testと計測fixtureを追加する。

#### Increment 3: Results wide matrixとQC detail

- [x] statistic child rowを廃止し、`Sample/Population | Events | % Parent | % Total | Population Status | <Statistic columns...>`へ変更する。mean等の値を割合列へ表示しない。
- [x] unassigned、disabled、not run、stale、undefined/error、valid zero、currentをcell単位で区別し、header/cell tooltipへstable ID、parameter、metric、value domain、unit、QC count、reason、revisionを表示する。色だけに依存しない。
- [x] standard列固定、横scroll、column chooser、順序/幅/visibility保存とlong-form Statistics Detailを、同じ`StatisticResult` snapshotの表示として実装する。Qtで値を再計算しない。

#### Increment 4: Population scopeとCompute/Show管理

- [x] Add/Manage Statisticへ`Current population`、`Current and descendants`、`Selected populations...`、`All current populations`を追加し、checkbox hierarchyで明示targetを編集する。既定は呼出元Populationとする。
- [x] Manage Statisticsへ`Compute | Show | Statistic | Parameter | Metric | Value domain | Applies to | Status`表と、Resultsの`Columns...`を追加する。`Compute`はanalysis revisionと該当resultを更新し、`Show`はdisplay stateだけを変更してpipelineを実行しない。
- [x] Newの明示操作、cancel、duplicate、remove dependency、Undo/Redo、save/reload、missing target、empty selection、stable objectNameをGUI testする。
  - [x] Newの明示操作、cancel、duplicate、save/reload、および主要ウィジェットのstable objectNameをGUI testする。
  - [x] remove dependency、Undo/Redo、missing target、empty selectionの専用UIとGUI testを追加する。

#### Increment 5: Export、preview、migration cleanup、E2E

- [x] GUI wide/detail、authoritative Run Pipeline、current-sample preview、Python API、long/wide CSV/TSVが全`(sample, statistic, population)` key、値、unit、status、QC、revisionで一致するようにする。wide statistic exportはstable Statistic ID metadata blockとPopulation行を保持し、long形式はQCを保持する。
- [x] legacy child-row Results view stateを移行して旧描画経路を削除し、hiddenとdisabledを混同しない。disabled definitionを削除せず、exportで値を捏造しない。
- [x] column hide/reorder、scroll、display downsampleがmembership/statisticsを変えないE2E test、full core/GUI test、thread shutdown、mean/median/percentile matrix benchmarkを完了する。

#### Phase B7.5 必須受け入れtest

- [x] 同一StatisticをAll Eventsと複数gateへ割り当てると、sampleごとに一つの共有列とPopulation別の独立cellが表示され、値が`% Parent`/`% Total`へ入らない。
- [x] `Show`変更はanalysis revision、headless/export値、gate membershipを変更せず、`Compute`変更は該当Statisticだけを再計算する。
- [x] Population target、source stage/transform、non-finite policy、unit、QC、disabled provenanceがsave/reload後もGUI/CLI/Pythonで一致する。
- [x] unassigned、disabled、not run、stale、undefined/error、zero/currentを色以外でも識別でき、表示操作やdownsamplingが科学計算を変更しない。

### Phase B7.6: Population full path と統合 Results Export [S17]

現行実装には Population-only export と Statistics-only export が残っており、
Population は `population_id`、gate hierarchy の表示 path は未提供である。この
incrementでは両者を一つの authoritative report から統合し、GUI・CLI・Python APIで
同じcore writerを使える状態にする。実装前に
`docs/implementation/unified-results-export-and-population-paths.md`を全文読む。

#### 未実装項目

- [x] coreに共通の`validate_gate_name()`を追加し、空白名とASCII `/`をGateSpec、全gate command、manifest、schema、GUI入力、CLI/project loadで拒否する。legacyのslash名はsilent migrationせず、strategy ID、gate ID、gate名を含む診断を返す。
- [x] coreにpopulation hierarchyの保存順preorderを使うfull-path builderを追加する。親子解決はIDだけで行い、unknown parent、cycle、duplicate IDを明示的に拒否する。sampleごとの実適用strategy/group bindingを解決する。
- [x] population resultとstatistic resultを`sample_id × population_id`のtyped row modelへ統合し、full path、root頻度、百分率、blank/zero、sample title、custom statistic列、重複表示名、internal ID metadata、QCをwide/long writerで出力する。
- [x] GUIの2つのResults export actionを`Export Results...`へ統合し、toolbarも同じhandlerへ接続する。Wide/Long、population/custom、internal ID、QC、TSV/CSV、stale/no-result/hierarchy failureのdialogを実装する。
- [x] `flowdesk run --output`を統合wideの標準動作にし、`--layout`、`--include-internal-ids`、`--include-qc`を追加する。`--statistics-output`を残す場合はstderrへdeprecated warningを出し、互換APIとしてのみ扱う。batch-gateも可能な範囲で同じwriterに合わせる。
- [x] GateSpec、commands、manifest/schema、path、wide/long、GUI、CLIのbehavior testを追加し、既存の科学計算結果とpopulation ID生成規則を変更しないことを確認する。

#### 完了条件

- [x] GUIのResults exportが1項目だけになり、Population full pathとcustom statisticsが同一ファイルに出力される。
- [x] GUIとCLIが同一core export implementationを使用し、stale resultsを出力しない。
- [x] schema、manifest、core API、commands、GUI、CLIのいずれからもASCII `/`付きgate名を保存できない。
- [x] 正式チェックを完了する。`.direnv`環境の全pytest（1009 passed）、GUIテスト（222 passed）、`ruff check src tests`、`make type-check`（core/storage/CLI 52ファイル）が通過済み。`pyenv exec pytest`と`pyenv exec mypy src`は、pyenv環境にプロジェクトの任意依存（NumPy/PySide6/flowio）が未導入のため、`.direnv`のsite-packagesを`PYTHONPATH`へ指定して同じ検証を実行した。Qtを含む`mypy src`全体は、既存Qtコードの未注釈箇所を含むため正式対象外とし、Makefileの型チェック対象を完了条件とする。

### Phase B8: Autosaveとcrash recovery [S14]

- [x] autosave interval、retention、disableをglobal preferenceとして追加する。
- [x] dirty projectだけをatomic autosaveする。
- [x] normal projectより新しいrecoveryをtimestamp比較で検出できるようにする。
- [x] recover copyを別pathで開き、元projectを自動上書きしない。
- [x] recovery retention、read-only、atomic save経路をtestする。QThread/disk-fullはGUI/OS依存のためintegration fixtureへ保留する。

### Phase B8.1: Analysis settings bundle [S14]

実験データや既存の結果を含めず、別projectの現在のsampleへ再利用可能な解析定義だけを
保存・読込する。実装前に`docs/implementation/analysis-settings-bundles.md`を全文読む。

- [x] `.flowdesk-settings` directory bundle用のversioned `AnalysisSettingsSpec`、schema、migration、atomic save/loadを追加する。通常の`.flowdesk` projectから同じspecを抽出できるようにする。
- [x] gate hierarchy、analysis transforms、derived parameters、unbound compensation matrices、statistics、auto-gate templates、内部参照を含むplot viewsだけを保存対象にする。sample path/ID/fingerprint、raw events、execution report/cache、group membership、annotations、gate override、compensation binding/control assignment、export output path、UI session stateは保存しない。
- [x] target sample catalogに対するchannel/parameterと内部IDのstrict preflightをcoreへ実装する。missing/ambiguous channel、invalid dependency、unknown gate/transform/statistic参照では一切変更しない。channel mappingやdefinition mergeは実装しない。
- [x] importをreplace-onlyのdefinition commandとして実装する。targetのproject ID、sample catalog、FCS参照、fingerprint、target-only表示状態を維持し、成功時はResults/preview/cacheを破棄して`analysis_settings_loaded`でstale化する。Undo/Redoも同じstate境界を保つ。
- [x] Fileメニューへ`Save Analysis Settings...`と`Load Analysis Settings...`を追加する。load dialogは`.flowdesk-settings`と`.flowdesk` projectを選択可能にし、置換対象・除外対象・互換性診断・Pipeline再実行要件を確認後に適用する。
- [x] settings round-trip、project-source extraction、source Results非移植、target sample保持、失敗時atomicity、undo/redo、GUI/headless Pipeline一致、Windows/macOS/LinuxのUnicode/空白pathをtestする。
- [x] `docs/user-manual/user_manual.md`へ保存/読み込み、replace semantics、除外項目、互換性エラー、Results再計算必須を記載する。

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
- [x] saved Batch Plot Export definitionをCLI queueへ追加する。`--queue-export-id`を複数指定でき、
  definitionごとの安全なoutput subdirectory、既存runtime parallelism/memory設定、共通cancel、
  `fail-fast`/`continue` policyを使用する。GUIの`Run Saved Queue`も同じheadless adapter、
  progress、cancel、runtime-only設定で実行する。plugin queue、definition間の並列実行は未実装。
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
- [x] load（deterministic fixture construction）、compensation、derived、transform、gating、
  statisticsをbenchmark JSONのstage boundariesへ分離して記録する。renderはcanonical pipelineと
  混同せず、既存のbatch/vector benchmarkで別計測する。
- [x] `flowdesk_storage.cache.build_pipeline_cache_key`を追加し、sample ID、input fingerprint、
  software/cache algorithm version、execution profile、全上流definitionの累積stage hashを含める。
  display/export/runtime設定は除外し、cache payloadの読み書きはまだ有効化しない。
- [x] compensation変更はcompensation以降、derived変更はderived以降、transform/gate/statistics変更は
  それぞれのstage以降を無効化するkey回帰テストを追加した。raw event自体はfingerprintだけを参照し、
  cacheへ保存しない。
- [x] GUI schedulerの同一project snapshot内にbounded in-memory display-stage LRUを追加した。
  immutable raw event array identityを保持してcompensation/derived/transform結果を最大4 entry・128 MiBで
  再利用し、project snapshot変更時はrunnerごと破棄する。authoritative preview、gate membership、
  statisticsはcacheせず、永続payload cacheとは別機能として扱う。
- [ ] runnerへprogress、cancel、memory budget、sample-level parallelismを追加する。実装は下記の
  `Parallel execution and progress`を上から一incrementずつ行う。
- [x] scatter downsampling変更でscientific count/statisticsが変わらないことをGUI回帰testで確認する。
- [x] rare-event visibilityの限界をGUI status bannerとuser manualへ表示する。

### Parallel execution and progress [docs/bug.md / S23]

`docs/implementation/parallel-execution-and-progress.md`を全文読み、
`llm-task-protocol.md`に従って一度のLLM実行で一incrementだけ実装する。GUI sample
切替、authoritative `Run Pipeline`、Batch Plot Exportを同じ「並列化」で一括変更しない。
2026-07-29の設計判断として、メインウィンドウで一つのsampleを選択して表示する処理は、
そのactive sampleだけを処理する。他sampleのpipeline処理を待って表示する設計ではない。
従って、この経路の優先事項はsample間並列化ではなく、latest-wins scheduler、既存cache、
density数値処理、Qt描画payloadの削減である。`Run Pipeline`のsample単位並列化は、全sampleを
対象とするauthoritative batch実行だけに適用する。1 sample内の任意event分割は、全population
normalization、parent/Boolean/automatic gate、deterministic sampling、invalid-value policy、結果順序を
変えない純粋kernelであることをprofileと数学的merge testで示すまで実装しない。
2026-07-30の追加判断として、single-sample表示で待たせているのは他sampleの解析ではなく、
選択sampleのprocessed-display準備、density推定/normalization、per-event color/brushの生成、
pyqtgraphへのpayload転送と描画である。個々のeventの色付けが見かけ上独立でも、densityは
表示population全体から得るglobal histogram、smoothing、normalizationに依存し、Qt item更新は
GUI threadに限定される。そのため、まずsemantic cacheのhit率、viewport非依存density fieldの
再利用、重複`setData()`とper-event Qt payloadの削減を測定して改善する。NumPyの純粋数値kernelを
off-thread化または固定bin histogramとしてchunk化する案は、global reductionを一度だけ行い、
unchunkedと色・順序・normalizationが一致し、memoryとshutdownが安全であることをtestで示せた
場合に限る。Python eventごとのthread分割や、Qt/pyqtgraph objectをworkerから更新する実装は行わない。
2026-07-29の実測では、example FCSのdensity plot全体が約325–329 ms、そのうちdensity
数値計算が約77–130 ms、uniform plotでも約189–192 msであった。現在はdensity modeで
uniform scatterを一度送信した後にdensity brushで再送信し、processed-display cache missも
既存schedulerを使わずGUI threadで同期処理している。このため、汎用parallel runtimeより
Increment 1–3のinteractive hot path最適化を先に完了する。

実装の優先順位は次の通りとする。新たな「全CPUを使う」一般並列化は、計測で優位性を示すまで
追加しない。

1. 未完のIncrement 3を、viewport非依存density fieldの再利用、semantic cache完全性、
   per-event Qt payload削減、cache/rapid-interaction/shutdown回帰testとして完了させる。
   worker-owned NumPy arrayをQtへ安全に受け渡せることを再現性あるtestで確認できない場合、
   off-thread density kernelは保留し、同一threadでの再計算除去を優先する。
2. Increment 6でBatch Plot Exportのsource preparationを明示分離し、進捗、cancel、atomic
   staged outputを追加する。これは後続の並列renderと安全な比較の前提であり、まず逐次結果を
   固定する。
3. Increment 7–8でimmutableなper-sample resultとdeterministic mergeを完成後に、bounded
   sample-level pipeline parallelismを追加する。GUIのactive-sample表示には流用しない。
4. Increment 9以降はrenderer reentrancy、memory budget、sequential/parallel parityを確認してから
   batch rendering parallelism、prefetch、限定的なdensity histogram chunkingを検討する。

single-sample表示の改善候補は、次の優先順で判定する。これはauthoritative pipelineのsample間
thread backend（Increment 8）とは別の計画である。

| 優先度 | 対象 | 実装境界 | 必須の同一性/安全性確認 |
|---|---|---|---|
| 高 | 同一display identityの再表示 | GUI thread cacheと既存scatterの再利用 | 色・点順序・gate/labelの表示がcold pathと一致すること |
| 高 | densityのglobal数値field | renderer-neutral NumPy array、latest-wins workerは将来候補 | viewport変更で色が変化せず、global normalizationがunchunkedと一致すること |
| 高 | per-event Qt payload | GUI threadの最小payload表現 | rare event、alpha、draw order、selection、interactionを維持すること |
| 保留 | density histogramのchunk化 | coreの固定bin整数histogramを合算後、一回だけsmoothing/normalization | chunk境界・worker数で色indexが完全一致し、peak memoryとshutdownを計測すること |
| 対象外 | 任意eventのPython thread分割 | なし | parent/Boolean/automatic gate、sampling、invalid値、結果順序を変えない証明がないため実装しない |

#### Increment 1: densityの重複描画除去とhot-path計測（完了）

- [x] density modeでは同じ点を最初にuniform colorで送信せず、最終density colorを準備して
  main scatterへ一度だけ送信する。single color/population color pathは変更しない。
- [x] main scatterのdata-bearing `setData()` call-count testと、変更前後の点、順序、色、density
  normalization parity testを追加した。pyqtgraph constructorの空`setData()`は対象外とする。
- [x] `make benchmark-density`でdensity数値計算とcold widget全体を別々にJSONへ記録する
  opt-in benchmarkを追加した。2026-07-29のsynthetic 2,200 events × 5回では全体中央値
  53.9 ms、density数値計算中央値11.1 msであった。絶対時間thresholdは通常CIへ追加しない。

#### Increment 2: processed-display schedulerの実経路接続（完了）

- [x] `MainWindow._queue_processed_display()`の同期
  `PipelineRunner.prepare_display_sample()`呼出しを既存`ProcessedDisplayScheduler`経路へ
  置換する。scheduler classが存在するだけで非同期化済みと判断しない。
- [x] immutable request、one-worker、debounce/coalescing、latest-wins、analysis/project
  revision check、error reporting、shutdown contractを維持する。
- [x] worker結果/cacheをGUI threadでのみ適用し、late resultがcurrent sampleを上書きせず、
  relevantなreplotを一度だけ行う。
- [x] 遅延workerでA→B→Cを高速選択し、Cだけが表示され、B由来のfailureがCのplotを消さず、
  schedulerのsnapshot/coalescingとwindow close時のworker待機をtestする。

#### Increment 3: density数値処理のoff-thread化とsemantic cache

- [x] densityをrenderer-neutralなhistogram/smoothing/global normalization/color-index結果と
  GUI presentationへ分離する。数値arrayだけをowned workerで計算し、`QBrush`、pyqtgraph
  item、widget mutationはGUI threadに限定する。
- [x] `id(array)`だけに依存するcache keyを廃止し、canonical processed-display identity
  （analysis/display revision、sample/population、axes、transform、display event selection）を
  含むsemantic keyへ変更した。density algorithm/parametersは現時点で固定実装のため、可変化する
  incrementで明示version/parameterをkeyへ追加する。
- [x] whole-population densityがviewport非依存というcontractの範囲ではpan/zoomでdensity
  fieldを再利用し、generation checkでstale resultを破棄する。viewport変更だけで同じeventの
  density colorを変えない。semantic key、latest-wins scheduler、pan/zoom/stale GUI testで確認済み。
- [x] profiling後にper-event Qt payloadの再生成を最小化する。同一density色配列とalphaでは
  `QBrush`リストを再利用し、dot size/opacity変更でもdraw order、rare color、alpha、selection、
  interactionを維持する。palette groupingによるdraw order変更はまだ採用しない。
- [x] 新規/default設定ではfinite display maximumを維持する。明示的な`0 (all events)`は
  勝手にsamplingせず、large event+density時のperformance status/warningを表示する。
- [x] 同一semantic processed-display identityのdensity再描画では、解決済みのcolorsと既存
  `ScatterPlotItem`を再利用し、gate/label-only replotでper-event `setData()`を再送信しない。
  unchangedな`PlotItem.setLogMode()`も再実行しない。dot size/opacity変更はQt payloadだけを
  更新し、whole-population density推定/normalizationは再実行しない。2026-07-30にはdensity
  scatterのdot size/opacity更新を`ScatterPlotItem.setSize()`/`setBrush()`へ分離し、既存event
  X/Yを`setData()`で再送信しないようにした。
- [x] MainWindowのprocessed-display cacheを4件・推定256 MiBのLRUへ制限し、sample削除・再接続・
  project置換時に対象配列とmembership maskを破棄する。evictionは表示cacheだけに作用し、
  authoritative reportや科学計算結果は変更しない。cache上限とsample切替回帰testを追加した。
- [x] 4 MiB以上のFCSをactive sampleとして選択した場合、raw FCS読込をone-worker latest-wins
  schedulerへ移した。loaded/failed signalのGUI-thread適用、stale selection破棄、close時waitを実装し、
  小さいfixtureは既存の同期経路を維持する。schedulerのcoalescing/shutdown testを追加した。
- [x] `benchmark-density`へwarm semantic density replotを追加した。2026-07-29の20,000 events
  ×5回のoffscreen環境ではcold `plot_events`中央値216.0 msに対して、cached replot中央値は
  1.75 msだった。これは同一環境の表示測定であり、CI thresholdや解析speedupではない。
  2026-07-30の20,000 events ×3回では、X/Yを再送信しないsize update中央値73.2 ms、
  opacity update中央値148.6 ms、cold `plot_events`中央値234.8 msだった。opacityはeventごとの
  brush更新を伴うため、これをdensity数値kernelのspeedupと解釈しない。
- [x] density gridのseparable Gaussian smoothingを`np.apply_along_axis`のPython callbackから
  `sliding_window_view` + `tensordot`のベクトル化passへ置換した。edge padding、kernel、軸順序の
  数値契約を維持し、旧実装との差は浮動小数点丸め（最大約4e-16）以内である。20,000 eventsの
  density numeric中央値は今回の環境で71.9 ms（5回）だった。これは環境依存の診断値でありCI thresholdではない。
- [x] cached/uncachedのcolor一致、semantic context変更時のcache invalidation、rapid pan/zoom/sample
  switch、shutdownをfocused testで確認した。stale density/display結果はcurrent requestへ適用されない。

#### Increment 4: benchmark baselineと共通runtime control（進行中）

- [x] 10万events × 8 samples、100万events × 8 samples、1000万events × 2 samplesの
  deterministic synthetic profileを追加し、seed、channel数、expected population count、
  OS/Python/NumPy/Qt/CPU、worker数、peak RSSをJSONへ記録する。生成event array/FCSはcommit
  しない。`make benchmark-pipeline`はcanonical pipelineだけを測定し、defaultではsmall
  profileを実行する。
- [x] display preparation/density numeric、canonical pipeline、batch source preparation、rendererを
  別々に計測する診断入口を整備した。`make benchmark-density`、pipeline benchmark、Batch Export
  manifestのplanning/preparation/render phase timingを使い、rendering時間をanalysis speedupとして
  報告しない。絶対時間thresholdは設定しない。
- [x] Qt非依存の`ExecutionOptions`、`ExecutionControl`、`ProgressEvent`、
  `CancellationToken`、typed cancellation outcomeを定義する。control未指定時は既存の
  sequential APIと結果を維持する。
- [x] progressのphase、completed/total単調性、callback failure、cooperative cancellation、
  Qt非依存性のcontract testを先に追加する。

#### Increment 5: sequential pipeline progress/cancel（完了）

- [x] project-wide planning、compensation control計算、sampleごとの
  compensation/derived/transform/gating/statistics、QC/finalizeへprogress checkpointを追加
  する。このincrementではsample loopを並列化しない。
- [x] cancelはstage間で協調的に確認し、実行中NumPy処理やthreadを強制終了しない。cancelした
  authoritative runはpartial result/cacheをcurrentとして返さず、GUIは以前のreportを保持して
  stale表示する。coreは`ExecutionCancelled`をraiseして途中reportを返さない。
- [x] CLI/Python/GUIが同じcontrol contractを使用し、uncancelled reportが変更前と完全一致する
  test、cancel時のexit/statusとraw event不変testを追加する。Python APIとCLI adapterは同じ
  controlを受け取りCLIはcancel時にexit code 130を返す。Qtはstatus barのphase/sample count
  progressと`Cancel Pipeline` actionを同じcontrolへ接続し、cancel後もprevious Resultsを
  staleとして残す。

#### Increment 6: Batch Export phase分割と進捗GUI

- [x] `batch_plot_command()`の「最初のrender callbackで全sampleを準備する」処理を、
  planning、unique source loading/preparation、shared range、scene build、render、
  sidecar、manifestへ明示的に分割する。
- [x] overlayのbase/source依存graphを事前に構築し、同じsourceを一度だけ準備する。
  `shared_ranges`は全required source準備後のbarrierとし、source/order/color/gate/labelを
  completion順で変えない。render時に依存graphを再構築せず、targetごとのsource順を再利用する。
- [x] sequentialのままper-item/per-format progress、cooperative cancel、atomic staged output、
  `cancelled`/`not_started`を含むmanifestを実装する。coordinatorだけがmanifestを書く。
- [x] bounded source preparationの完了をcoordinator threadからsource単位でprogressへ通知する。
  GUIは`preparing_sources` phase中に`prepared source n/total`とsource IDを表示できるが、
  `completed_units`は出力unitの進捗として0のまま保持する。workerからQtやprogress sinkを直接
  呼ばず、source完了順はscene、shared range、manifest、出力順へ影響させない。既存のzero-argument
  `prepare()` APIは互換性のため維持する。
- [x] `shared_ranges`の全source範囲はイベント配列を連結せず、sourceごとのmin/maxをcoordinatorで
  reduceする。共有範囲の値を変えずに、準備段階の一時メモリを削減した。
- [x] 同じsourceが複数targetのbase/overlayとして使われる場合、sourceと実際のboundsをキーに
  normalized座標、表示mask、event color順を一度だけ作成して再利用する。`shared_ranges`と
  `current_view`の双方で、boundsが異なるtargetは別entryとして保持する。ゲートgeometryも
  軸、transform、bounds、outline色をキーにtarget間で一度だけ構築する。軸tickもbounds、
  transform、policyをキーにtarget間で再利用する。不変なsample/style/color lookupもexport
  単位で前計算し、render callbackごとの辞書構築と線形探索を避ける。persisted source styleは
  sourceごとに浅いcopyして再利用する。normalized layer cacheは
  source数に応じた最大256 entryかつ推定128 MiBのLRUとしてboundedに保持し、単一payloadが
  上限を超える場合はcacheしない。
- [x] 同一source/boundsを複数render workerが同時に要求した場合のnormalized layer重複計算を
  per-key single-flightで抑制する。計算中のkeyは待機eventを共有し、結果のcache、LRU byte accounting、
  source順は従来どおりcoordinator-ownedで管理する。
- [x] 並列renderで同一sceneのgate geometryまたはaxis tickがcache missになる場合も、keyごとの
  single-flight eventで一方だけが計算する。待機中にglobal cache lockを保持せず、例外時は待機workerを
  解放し、LRU eviction、gate順、tick値、出力parityを維持する。
- [x] Batch ExportをGUI threadから同期実行せずowned workerで実行し、
  `batchPlotProgressDialog`、`batchPlotProgressBar`、`batchPlotProgressSummary`、
  `batchPlotProgressCurrentItem`、`batchPlotProgressCancelButton`、
  `batchPlotProgressDetails`を追加する。status barにも`completed/total`を表示する。
- [x] cancel、failure、project/window closeでworkerを安全に終了し、late signal、truncated final
  file、`QThread: Destroyed while thread is still running`がないGUI testを追加する。

#### Increment 7: immutable sample resultとdeterministic merge

- [x] `_run_full_pipeline()`のsample loop本体を、immutable inputから完全な
  `SampleExecutionResult`を返すQt非依存関数へ抽出する。workerから共有list/report/cacheへ
  append/mutationしない。
- [x] derived plan、Group/strategy/statistic assignment、calculated compensation matrixをworker
  開始前に一度だけ解決し、cross-sample QCは全sample merge後に実行する。
- [x] coordinatorがproject sample順でpopulation results、membership mask、statistics、
  diagnostics、messages、input files、auto/magnetic/tethered fitをmergeする。future完了順を
  report順へ使用しない。
- [x] fake executor相当の逆順`SampleExecutionResult`をmergeしても、input files、messages、fit
  records、failed sample countがproject順になるtestを追加する。このincrementも実worker並列化は
  行わない。
  このincrementも実worker並列化は行わない。

#### Increment 8: bounded thread sample-level parallelism

- [x] `sequential`/`thread` backendとpositive `max_workers`をruntime optionとして追加する。
  project scientific definitionへcallback/thread objectを保存しない。
- [x] input events bytes、compensated/derived/transformed temporary、membershipを含む保守的な
  sample memory estimatorを追加し、requested workers、sample数、CPU、memory budget、numeric
  library inner threadsからeffective worker数を決める。全CPUを無条件に使わない。
- [x] pending futureのcancel、active taskの協調終了、sample failure policy、deterministic merge、
  resolved backend/worker/memory provenanceを実装する。
- [x] workers=1/2/Nでcount、frequency、membership mask、statistics、diagnostics、report order、
  raw eventsがsequentialと一致するtestを追加する。通常CIに絶対時間thresholdを置かない。
  2026-07-30のopt-in small benchmark（100,000 events × 8、fallback root population）では
  sequential中央値3.37 ms、thread/2 workers中央値4.65 ms、scientific report hash一致だった。
  この軽量workloadでspeedupは得られなかったため、thread backendは明示指定時のみとし、defaultを
  sequentialから変更しない。headless CLIは`--execution-backend thread`、`--max-workers`、
  `--memory-budget-mib`でこのruntime optionを明示指定でき、resolved worker数を表示する。
  代表的なcompensation/derived/gating workloadで再計測する。
- [x] GUIのAnalysis → `Pipeline Execution Settings...`から同じruntime optionを明示指定できる。
  既定sequential、thread/max-workers/memory budgetはsession-onlyでproject定義へ保存せず、
  `_PipelineWorker`へ同じ`ExecutionOptions`を渡す。GUI active sample切替やevent chunk分割には流用しない。

#### 並列化の懸念・注意点・保留事項（2026-07-30）

Increment 8の実装時点で、次の境界を明記しておく。ここに記載した保留事項が解消されるまでは、
thread backendを既定値にしたり、GUI描画へ自動適用したりしない。

- [x] **適用範囲**: `thread` backendはheadlessのauthoritative `Run Pipeline`におけるsample間の
  並列化だけを対象とする。メインウィンドウのactive sample切替、Qt/pyqtgraph描画、density colorの
  計算をこのworkerへ移してはいけない。
- [x] **イベント分割の扱い**: 1サンプル内のeventを任意のchunkへ分割する方式は採用しない。gate、
  frequency、statistics、diagnostics、順序依存の前処理で逐次実行と数学的に同値であること、chunk
  境界の再現性、メモリとmergeコストを証明できるまでIncrement 11で保留する。
- [x] **既定値とGIL**: 小規模fallback workloadではthread/2がsequentialより遅かった。Python処理が
  GILを保持する部分やfuture作成・mergeの固定費が大きい workloadでは高速化を期待しない。native
  NumPy等がGILを解放する代表的なcompensation/derived/gating workloadを別途計測するまで、既定値は
  `sequential`のままとする。
- [x] **numeric libraryの過剰並列**: BLAS/OpenMP/numexpr等の内部thread数とsample worker数が
  掛け合わされるとoversubscriptionになる。現在のworker数解決は環境変数・既知のruntimeを考慮するが、
  全ての実装を強制的に制御するものではない。実環境のbackendを確認し、nested parallelismとCPU負荷を
  代表データで検証する。
- [x] **メモリ予算**: estimatorは入力events、派生配列、membership等を含む保守的な近似であり、
  Python allocator・NumPy temporary・native libraryのpeak RSSを完全には保証しない。1サンプル分が
  予算を超えても実行を拒否するハード上限ではなく、effective workersを1へ抑える安全側のヒューリスティック
  である。大規模FCSで実測peak RSS、swap、OOMを確認し、必要なら警告と推定式を改訂する。
  Batch Exportではunique overlay source、normalized/mask、event color、vector/hybrid rasterの
  item単位working setも推定し、単一sourceだけを見てworker数を決めない。
- [x] **raw dataと共有状態**: workerはraw FCS eventsを変更せず、共有project/cache/diagnostics
  listへ直接書き込まない。derived/compensationの一時配列はworker内で所有し、結果はcoordinatorが
  input sample順にmergeする。raw event hashとsequential parityを回帰テストで維持する。
- [x] **cancelと失敗**: cancelは協調的であり、実行中のNumPy/native kernelを強制停止できない。
  active taskは安全なstage境界で終了し、部分的なauthoritative resultを採用しない。failure/cancel時も
  完了順をreport順にせず、無関係sampleの結果・診断・出力を破壊しないことを検証する。
- [x] **provenance**: resolved backend、worker数、memory budget等は`ExecutionReport`のruntime
  provenanceであり、projectのscientific definitionへ保存しない。runtimeが異なってもscientific
  result hashの比較対象からprovenanceを除外する。
- [x] **代表 workloadの性能ゲート**: `pipeline_benchmark --profile representative`へidentity
  compensation、derived ratio、transform、rectangle gate、count/mean statisticsを含む8 sample ×
  100,000 eventのdeterministic profileを追加し、sequential/threadのwall time、peak RSS、report hash、
  inner-thread解決を測定した。2026-07-31のLinux測定はsequential 86.7 ms/84,776 KiB、thread/2
  52.7 ms/103,440 KiB、hash一致だった。これは診断値であり、real instrument dataとWindows/PyInstaller
  検証は未完了なのでthread backendは明示opt-inのまま維持する。
- [x] `tools/benchmark_batch_plot.py`へ`--project`/`--export-id`を追加し、保存済みBatch Exportを
  sequential/threadの別processで実行してmanifest phase、出力SHA-256、output bytes、peak RSS、open-file数を
  JSONへ記録する。実FCSの8出力はbyte parityを確認できるが、thread/2は2026-07-31に約1.06倍の速度と
  約1.74倍のRSSだったため、既定sequentialとCLI opt-in threadを維持する。これは代表writer/gate
  workloadの測定入口であり、`--scientific-stages`で一時projectへidentity compensation、derived
  ratio、gate countを追加できる。2026-07-31に実FCS 8出力でscientific stages付きbyte parityを確認した。
  `--timeout-seconds`でchild processのハングをtimeout status/exit 124として記録できる。Windows/PyInstaller検証は未完了。
- [x] 同じbenchmarkへ`--memory-budget-mib`を追加し、synthetic/project両モードでresolved worker数、
  memory limiting factor、出力parityを比較できるようにする。memory budgetはruntime診断だけであり、
  project definitionやBatch Exportの既定設定へ保存しない。
- [x] **Batch Plot Exportの限定的並列化**: overlay依存、`shared_ranges` barrierをcoordinatorで
  解決し、必要sourceのFCS読込・display準備とimmutableなprepared output itemをCLIの明示指定時だけ
  bounded thread executorへ渡す実装を追加した。GUI実行と既定値は逐次のままとし、GUIは明示opt-in時だけ使用し、rendererのQt object操作はworkerで
  行わない。temporary/atomic replace、cancel、plan順manifest、PNG/SVG/PDF parityを確認済み。
  ただし、代表的なcompensation/derived/gating workload、Windows/PyInstaller、rendererの詳細な
  reentrancy/GIL profileは未完了であり、既定並列化へ変更しない。
- [x] source-preparation workerごとにthread-localな`PipelineRunner`を所有させ、display-stage LRUを
  worker間で共有しないようにした。raw event、prepared array、source順のmerge契約は変更せず、並列準備回帰testで
  workerごとに別runnerが使われることを確認した。thread-local化後も実FCS出力のSHA-256は逐次と一致し、
  thread backendの速度を既定化する根拠にはしていない。
- [ ] **Batch Plot Export並列化の残りの検証**: rendererのreentrancy、共有mutable state、Qt backend、
  overlayのshared range barrier、Windows/PyInstaller終了処理を検証する。検証完了前にthread backendを既定値へ変更したり、
  GUIへ自動適用したりしない。代表FCSでの出力parityとpeak RSSの測定は実施済みだが、
  `--scientific-stages`でcompensation/derived/gate/statisticsを追加したworkloadもLinuxで測定済みである。
  同一process内のPNG/SVG/PDF再実行parity smoke testは追加済みだが、native Windows/PyInstaller終了処理は未検証。
  2026-07-31の実FCS再測定は逐次21.286 s/314,208 KiB、thread/2 21.153 s/523,059 KiBで、
  speedは1.006倍、RSSは約1.66倍だった。出力SHA-256は一致したが、既定並列化の根拠にはしない。
- [x] **density numeric workerの限定的導入**: MainWindowのdensity表示だけをlatest-winsの一worker
  schedulerへ移し、read-only NumPy view（writable入力だけcopy）とsemantic keyでrenderer-neutralな色配列を計算する。
  QBrush、ScatterPlotItem、brush適用はGUI threadだけで行い、stale結果を破棄する。同期exportはpending
  densityを解決してから描画し、MainWindow/PlotWidget close時にworkerを待つ。viewport不変性、cached/
  uncached parity、rapid replot、shutdownをfocused testで確認した。cold worker中は大きなplaceholder
  scatterを描かず、計算完了後に一度だけデータを送る。
- [x] **density histogramのbounded-memory合算**: 入力250,000 event単位のfixed-bin
  `histogram2d`を決定的な順序でint64合算し、全chunkの合算後に一度だけglobal smoothing/
  normalizationを行う経路を追加した。既定色、query順、viewport不変性、uncached結果は従来と一致し、
  1,000,000 event診断で色とmetadataが一致した。これは逐次のメモリ境界であり、任意のevent chunk
  worker、densityのworker間並列化、GUI thread外のQt object操作ではない。
- [x] **density histogram/chunkの限定的並列化**: `DensityColorConfig.histogram_workers`を
  明示指定した場合だけ、独立fixed-bin chunkのヒストグラム計算をbounded thread poolで実行する。
  coordinatorはchunk/input順にint64 countを合算し、global smoothing/normalizationは一度だけ行う。
  worker 1/2/4の色hash一致と1,000,000 eventの198.4/143.3/110.4 msを確認した。既定は1 workerで、
  GUI自動適用、任意event worker、Qt object操作は行わない。
- [x] **density chunk workerのメモリ予算制御**: `histogram_memory_budget_bytes`を追加し、
  chunkごとのfloat/int histogramとmasked x/y/boolean slice working setからactive worker数を保守的に制限する。予算が小さい
  場合は1 workerへfallbackし、色結果を変えない。これは全FCS配列やRSSを制限するprocess-wide
  budgetではない。
- [x] **density batch cancellation checkpoint**: density estimatorへ任意のcoordinator-owned callbackを追加し、
  batch exportでhistogram chunk完了間、global smoothing/query前後にcancelを確認する。active NumPy callを強制停止せず、
  追加chunkを開始しない安全境界でcancelled manifestへ遷移する。
- [x] **density入力一時コピーの削減**: chunking時に元の変換済み配列を直接分割し、各chunk内で
  visibility maskを適用することで、全visibleイベントの`x[visible]`/`y[visible]`一括コピーを避ける。
  小さいvisible populationは従来のsingle-histogram fast pathを維持する。
- [x] **density palette変換のベクトル化**: eventごとのPython f-string list comprehensionをNumPy
  character bufferへ置換し、1,000,000色の文字列が完全一致することと98.2 ms（新）/3,108.5 ms（旧）を
  確認した。palette、hex表現、event順は変更しない。
- [x] **headless density runtime controls**: `batch-plot` CLIへ`--density-workers`と
  `--density-memory-budget-mib`を追加し、保存済みBatch Export定義へ書き込まずdensity色準備だけへ
  適用する。CLI parserと`DensityColorConfig`の受け渡しをテストした。
- [x] **GUI batch density runtime controls**: Batch Plot Export dialogへ同じdensity worker数と
  density memory budgetを追加し、保存済みdefinitionへ書き込まずheadless workerへ渡す。
  GUI object名、runtime-only保持、CLI/coreとの設定一致、worker受け渡しをテストした。
- [x] **density execution provenance**: density metadataとbatch sidecarへrequested/effective
  histogram workersとmemory budgetを記録し、budgetによるworker削減を結果と区別して監査可能にした。
- [x] **density batch E2E**: `data/analysis.flowdesk`のdensity viewを4 samples・PNG/PDFで実行し、
  8出力のsidecar provenance、非空出力、budget有無のbyte/SHA-256一致を確認した。代表sampleは
  chunk閾値未満のため実効workerは1であり、大規模real-FCSのchunk speedupやWindows検証とは区別する。
- [x] **density benchmark runtime controls**: `tools/benchmark_density_plot.py`へdensity worker数と
  memory budget引数、JSON provenanceを追加した。numeric kernelだけへ設定を適用し、cold PlotWidgetは
  default configのまま測定するため、GUI描画性能とnumeric worker効果を混同しない。実効worker数と
  peak RSSもJSONへ記録する。
- [x] **density large-input profile**: 1,000,000 synthetic events、worker=4、64 MiB budgetで
  numeric median 215.4 ms、effective worker=4、peak RSS 324,712 KiBを確認した。synthetic診断値であり、
  default変更やplatform-wide RSS保証の根拠にはしない。
- [x] **Windows density runtime smoke**: Windows package workflowへ同じ1,000,000 event density
  benchmarkを追加し、effective workersとpeak RSSのJSONをartifactへ保存する。native GUI操作と
  PyInstaller close/error検証は別の残課題として維持する。
- [x] **Windows representative batch export smoke**: Windows package workflowで追跡済みの
  `data/analysis.flowdesk` と `batch-export-2c72921e28a9` を使い、4 samples・保存済み定義の
  PNG/PDF batch exportを実行する。density runtime controlsも明示して、native Windowsでの
  FCS path解決、writer import、sidecar/manifest生成、非ゼロ出力を確認し、成果物をartifactへ
  保存する。これはPyInstaller化された実行ファイルのshutdownやGUI操作の検証ではない。
- [x] **density batch memory estimate**: Batch Plot Exportのbounded render worker推定へ、density
  色配列、normalized density query、512×512 histogram/smoothing working setを保守的に加算した。
  density overlayではなく単一source時だけ適用し、densityの出力色・worker既定値・科学的結果は変更しない。
- [x] **batch display-stage fast path**: all-events batch viewでpopulation membership/statisticsが
  不要、かつpopulation display colorも未設定の場合、authoritative previewを実行せず同じcoreの
  compensation/derived/transform stageだけを`ProcessedDisplayLayer`へ返す経路を追加した。
  selected populationまたはpopulation colorが必要な場合は従来のpreviewを要求し、実FCS PNG/PDFの
  SHA-256 parityを確認した。GUIの`prepare_display_sample`契約とscientific pipelineは変更しない。
- [ ] **density workerの運用統合**: Windows/PyInstaller lifecycle、
  大規模実FCSでのpeak RSSとcancel/closeを検証し、既定値変更の可否を判断する。
- [x] **hybrid rasterの小配列ベクトル化を不採用とする記録**: alpha<1 markerの内側pixel
  ループを行単位NumPy配列へ置換する試行は、`data/analysis.flowdesk`（4 samples、PNG/PDF）で
  出力SHA-256を維持したものの、sequential renderが約21.2秒から約53.8秒へ悪化した。
  小さな一時配列生成が支配的だったため実装を取り消した。今後は大きなbatch化またはC実装を、
  pixel-center判定・描画順・alpha合成のparityと実FCS benchmarkで確認するまで導入しない。
- [x] **hybrid rasterのalpha合成をC実装へ移行する**: pixel-center maskは従来どおりNumPyで
  決定し、marker単位のRGBA tileをPillow `alpha_composite`へ渡してPythonのpixel内側loopを除去した。
  旧実装とのPDF raster比較（150/600 DPI）で4 samplesの画像が完全一致し、PDF単独実FCS exportは
  約18.5秒から約13.1秒へ短縮した。Pillowがない場合は明示的なexport errorとし、alpha順序・透明背景・
  source orderを変更しない。
- [x] **hybrid rasterの協調キャンセル**: marker 256件ごととsource境界でcoordinator-owned
  cancellation callbackを確認し、activeなPillow/NumPy処理を強制停止せず安全境界で終了する。
  cancellation時に不完全なPDF/SVGをpublishせず、通常時のpixel mask、event order、出力parityを変更しない
  regression testを追加する。
- [x] **PNG/JPEG描画の協調キャンセル**: per-sourceの256 event checkpointとsource完了境界を追加し、
  PNGの最終save前、JPEGのtemporary PNG変換中にcancelを伝播する。cancel時はfinal outputとsidecarを
  publishせず、成功時の画像、DPI metadata、event orderを変更しない。
- [x] **SVG/PDF vector描画の協調キャンセル**: full-vector、compact-vector、hybrid以外のscatter
  loopにもsource/256 event checkpointを追加する。cancel時はvector commandの構築途中で終了し、final
  fileとsidecarをpublishせず、通常時のpath order、gate、tick、font、byte parityを維持する。
- [ ] **process backendの採否**: GIL回避だけを理由にprocess backendを追加しない。Windows spawn、
  FCS配列のpickle/コピー、メモリ倍増、診断・cancel・再現性の複雑化を含む実測と運用要件を確認し、
  Increment 11のdecision recordで採否を決定する。
- [ ] **GUI/配布環境の確認**: GUIはQt thread affinityとshutdown時のworker未残留を守る。CLI flagsは
  opt-inのままとし、Windows/PyInstallerでworker終了、Ctrl-C、例外伝播、ログとresolved provenanceを
  確認する。
- [x] CLIの`run`/`batch-plot`へ一時的なSIGINT handlerを接続し、Ctrl-Cを共通`CancellationToken`へ
  伝達する。batchは完了済み出力とcancelled manifestを保持し、終了コード130を返す。handlerは終了時に復元する。

#### Batch Export のFCS単位並列化に関する明示的な判断（2026-07-30）

FCSファイル間のイベント配列そのものは独立しているため、依存関係を解決した後の
prepared `(sample, view, format bundle)` は並列化候補である。ただし「FCSごとにスレッドを
作るだけ」にはしない。target/group解決、overlay source、`shared_ranges`、補正・derived・
transform、軸範囲、density normalization、vector preflightは複数出力で共有されるため、
これらを各workerで重複実行すると結果の基準、メモリ使用量、処理時間が悪化する。最終出力先、
Qt/pyqtgraph object、共有mutable cacheもworker間で同時に触れてはならない。

- [x] 依存関係と共有範囲をcoordinatorで逐次確定し、immutable prepared itemを作ってから、
  CLIで明示指定された場合だけbounded thread executorへ渡す。
- [x] 同一sampleのPNG/SVG/PDFはprepared sceneとcolour mappingを再利用し、FCS読込・変換を
  formatごとに繰り返さない。output pathのstaged/atomic replaceとmanifest順序はcoordinatorが管理する。
- [x] representative FCSで、逐次/並列の科学的結果・writer parityとpeak RSSを測定した。
  data/analysis.flowdesk（4 samples、PNG/PDF、DPI 300）で逐次は22.10 s/284,840 KB、thread/2は
  23.06 s/476,864 KBで、8出力のバイトとSHA-256は完全一致した。threadは約0.96倍と遅く、RSSは約1.67倍
  増加したため、逐次を既定値として維持する。Windows/PyInstaller、renderer reentrancy、
  compensation/derived/gatingを含む代表workloadは未検証である。
- [ ] GUIのactive sample切替へこのbatch workerを流用しない。GUIは選択sampleだけをlatest-winsで
  処理し、Qt/pyqtgraph mutationはGUI threadに限定する。
- [x] GUI Batch Exportダイアログへruntime-onlyの`Sequential`/`Bounded threads`、`Max workers`、
  `Memory budget`を追加する。thread backendは明示選択時だけ有効で、worker数・memory budgetは
  projectのBatch Plot Export定義へ保存しない。既定sequential、Qt object操作なし、manifest provenanceと
  sequential/thread parityを維持する。

#### Increment 9: bounded Batch Export parallel rendering

実装状況（2026-07-30）: bounded executorを実装した。overlay/shared range解決はcoordinatorで行い、
必要sourceのFCS読込・display準備と準備済みsample/viewのformat bundleを明示指定時だけthreadで
実行できる。GUIと既定値は逐次のままとし、GUIはダイアログで明示opt-inした場合だけ使用し、manifestにはpreparation/renderのexecution provenanceを記録する。
実PNG/SVG/PDF writer
parityとoverlay/shared_rangesのthreadテストを追加した。8 samples × 5,000 eventsのsynthetic
prepared layerではsequential 1.833 s、thread/2 1.580 s、出力bytes一致（18,317,448）だったが、
実FCSのcompensation/derived/gating workloadでは未測定であり、Windows/PyInstaller確認も残るため、
既定値へ変更しない。

実FCSの`data/analysis.flowdesk`（4 samples、`max_points=0`、PNG/PDF、DPI 300、hybrid raster）では、
2026-07-30にsequential 22.63 s / 最大RSS 270,084 KB、thread/2 21.43 s / 最大RSS 483,888 KBを
測定した。8出力のサイズとSHA-256は完全一致したが、speedupは約1.06倍、peak RSSは約1.8倍だった。
compensation/derived parameterを含む代表workloadとWindows/PyInstaller確認は未完了であり、threadは
明示指定時だけ許可し、既定値へ変更しない。

VectorRenderCache追加後の再測定ではsequential 21.96 s / 最大RSS 284,388 KB、
thread/2 23.09 s / 最大RSS 497,968 KBとなり、8出力のハッシュは引き続き完全一致した。
ベクター準備の重複は除去できたが、threadの既定化を支持する速度向上は確認できない。

source preparation並列化後に同じ実FCSを再測定したところ、sequentialは22.03 s / 最大RSS 289,888 KB、
thread/2は24.90 s / 最大RSS 489,036 KBだった。source preparation phaseはthreadで約0.04 s、render phaseは
24.56 sで、8出力のPNG/PDF SHA-256は完全一致した。現行workloadでは準備並列化による総時間短縮は確認できず、
thread backendを既定化しない判断を維持する。

設計判断: 「1 FCS = 1 thread」は一般則にしない。FCSは入力sourceであり、実行単位ではない。overlayは
複数FCSに依存し、`shared_ranges`は複数sourceの決定的reduceを必要とし、同一FCSから複数view・複数formatが
生成される。また、source配列やdensity結果を複数出力で再利用できるため、FCSをそのまま各threadへ渡すと
重複読込・重複変換・メモリ増加・出力順序の非決定性を招く。したがって、(1)必要sourceだけを一度prepareし、
(2)依存関係を解決し、(3)必要sourceをbounded workerでprepareしてsource順へmergeし、(4)共有範囲をreduceし、
(5)source順・色・title・gateを含むimmutable prepared output itemを作り、(6)そのitemをbounded executorでrenderする。
overlayなし・一source・共有範囲なしだけが単純な独立ケースであり、
それ以外はdependency barrier後に並列化する。この判断は`docs/implementation/parallel-execution-and-progress.md`
の「Why the worker unit is not simply one FCS file」と一致させる。

- [x] 「1 FCS = 1 worker」とは定義しない。FCSはsource/dependencyの単位であり、overlay出力は
  複数FCSへ依存し、1 FCSから複数view/formatが生成され得る。全source準備、overlay dependency、
  `shared_ranges`を解決した後のimmutable `prepared output item`をexecutorの最小仕事単位とする。
- [x] 明示的thread backendでは、target/overlay依存sourceのFCS読込・display準備もbounded workerで
  実行する。完了順によらずsource順にmergeしてからshared rangeをreduceし、worker数・推定source
  working set・制限要因をmanifestへ記録する。既定逐次、GUIは明示opt-in、Qt object操作なしを維持する。
- [x] overlayなし、共通軸範囲なし、必要sourceが1 sampleだけの出力について、source準備完了後は
  sample間で独立にrender可能であることを確認し、sequential/threadのPNG/SVG/PDF byte parity testを追加した。
  同一sceneからPNG/SVG/PDFを作る場合は、formatごとの完全独立jobとsample/view単位bundleの両方を
  benchmarkし、prepared arrayの再利用、peak memory、cancel granularityを比較して仕事単位を決める。
- [x] 同一sample/viewのformat bundleでは、prepared scene、normalized layer、event colorをformat間で
  再利用し、最後のformat後に短命cacheを解放する。2 formatでscene preparationが一度だけになるtestと
  実writerのbyte parityを追加した。実FCS再測定後もthreadのspeedupは安定せず、既定値は逐次とする。
- [x] overlay source styleをtarget/sourceごとに再走査せず、export開始時に作成したsource-ID indexを
  scene構築で再利用する。first-match style precedenceと出力parityを維持する。
- [x] source preparation時に有限なX/Y extremaを一度だけ計算し、`current_view`のactive range、
  `shared_ranges`のreduce、density boundsで再利用する。空sourceは従来どおりexportを失敗させ、
  normalized event arraysやPNG/SVG/PDFのbytesを変更しない。
- [x] target数・view range数に比例して増えていたgate geometry/tick cacheを各256 entryのLRUへ
  bounded化する。hit時の順序を更新し、evictionはpresentation cacheだけに作用して出力順、gate
  geometry、tick labels、scientific resultsを変更しない。
- [x] format失敗・途中cancelでもitem-scopedのprepared scene、normalized layer、event color、hybrid
  rasterを即時解放する。成功bundleのformat間再利用は維持し、coordinator終了時には残存cacheを全解放して
  長いbatchで失敗itemがメモリを蓄積しない。
- [x] normalized layer cacheの座標とevent colorをPython tupleからread-only NumPy配列へ変更し、cache内の
  Python object数とmemory estimateを削減した。writerはsequenceとして同じ値を読むため、PNG/SVG/PDFの
  event order・色・座標・byte parityを維持する。実FCS sequential再測定は21.82 s / 286,008 KBで、既存の
  21.96 s / 284,388 KB測定と同程度のため、速度向上を既定化の根拠にはしない。
- [x] source preparationで作成していた未使用の`raw_x`/`raw_y`コピーとmetadataを削除した。以後の
  scene、gate、tick、writerはtransform後のprepared layerだけを参照するため、PNG/SVG/PDFのbytesと
  event orderは変わらない。実FCS sequentialは21.97 s / 286,408 KBで、既知の全SHA-256と一致した。
- [x] thread source preparationのfuture投入をeffective worker数までにbounded化し、完了したsourceを
  source順へmergeする。大量sourceで未実行candidateをfutureへ一括queueせず、cancel/failure時の
  pending futureも協調的に解放する。manifestへsubmitted/peak in-flight source数を記録し、source
  orderと出力parityを維持する。
- [x] 同一sample/viewのSVG/PDFでは、compact scatter batchとhybrid scatter rasterを一度だけ構築し、
  format間でimmutableなvector render cacheを再利用する。単一色のfull-vectorでも同じ正規化座標
  planをformat間で再利用し、event colorがある場合は描画順を変えないためcache groupingを行わない。
  event order/color、point plan、sidecar metadata、出力bytesを変更しない回帰testを追加した。
  full-vector cacheは複数format bundleでのみ構築し、単一formatでは追加working setを作らない。
  compact/hybrid cacheではcompact batchまたはhybrid rasterと重複するlayer planを保持しない。
  100,000点のoffscreen診断ではSVG/PDF bundleが0.452 sから0.442 sとなったが、差は小さいため
  worker数やvector modeの既定値を変更する根拠にはしない。
- [x] batch targetがexplicit/groupの場合は、target sampleとoverlay依存sourceだけをprepareする。
  `shared_ranges`は必要source全体をreduceし、vector preflightは各output itemの最大event数で判定する。
  無関係sampleのFCS load、transform、density準備を行わず、unknown overlay sourceのvalidationは維持する。
- [x] headless core rendererのreentrancyと共有mutable global stateがないことをtestしてから、
  prepared output itemをbounded executorへ渡す。Qt/pyqtgraph/QPainter/QPixmapをworkerで
  操作しない。実writerを複数threadから呼び出すparity testでPNG/SVG/PDFのbyte一致を確認した。
- [x] rendererがGILを保持するか、native処理で解放するかをprofileし、thread worker数1/2/4で
  wall time、peak RSS、open file数を測定した。8 samples × 5,000 eventsのcompact-vector profileでは
  thread/2は0.965倍、thread/4は0.686倍（いずれもsequential比）で、peak RSSはそれぞれ約1.38倍、
  約1.95倍だった。threadで再現可能なspeedupがないため既定並列化を有効にせず、process backendは
  Increment 11のmemory/copy/Windows spawn評価へ送る。
- [x] `tools/benchmark_batch_plot.py`へ標準ライブラリで取得できるpeak RSSと終了時open-file数の
  診断値を追加した。OSが値を提供しない場合はnullとし、これは性能ゲートの補助データであって
  CIの絶対thresholdではない。
- [x] workerごとに一意なtemporary output/sidecarを所有させ、成功時だけsame-filesystem atomic
  replaceする。collision policy対象外の既存fileを削除しない。thread cancellationの回帰testも追加した。
- [x] batch manifestのexecution provenanceへjob unit、planned/submitted/completed item数、実際の
  `peak_in_flight_items`を記録し、bounded executorが指定上限を超えない回帰testを追加した。
- [x] batch manifestのexecution provenanceへplanning、source preparation、render、totalのwall-clock
  phase timingsを追加した。解析準備とrendererの時間を分離して測定し、並列化の効果を誤って
  authoritative analysis speedupとして報告しない。
- [x] overlay shared source、`shared_ranges` barrier、複数format、strict/partial failure、
  cancellationでもmanifestのitem順、filename、scene、source order、statusをplan順に保つ。
- [x] sequential/parallel PNG/SVG/PDFでscene/sidecar、gate位置、軸label、dot order/colorが一致
  し、failure/cancelが成功済み・無関係fileを破損しないtestを追加した。worker数はsample数だけで
  なく、estimated prepared-scene bytes、format temporary bytes、rendererの安全上限でboundする。

#### Increment 10: optional adjacent-sample prefetch

- [x] Increment 1–3後にcache hit/miss、sample切替latency、stage別時間、peak memoryを再計測する。
  density benchmark、processed-display cache telemetry、bounded cache/pre-fetch testを実施し、
  portabilityを伴わない値は診断値として実装ガイドへ記録した。
- [x] active display完了後500 msで、隣接する未読込の4 MiB以上FCSを一件だけlow-priority
  prefetchする。active requestはpending prefetchをsupersedeし、prefetch raw sampleは一件だけ保持する。
- [x] cache有無/prefetch有無でdisplay array、preview membership/count/statisticsが一致し、
  current sampleのplotをprefetch完了時に再描画しないGUI testを追加した。
- [x] schedulerの再接続競合を修正した。同じsample IDでもFCS pathが変わった場合は新しい
  `(sample_id, path)` requestをpendingへ保持し、古いpathの完了/失敗通知を破棄してから新pathを
  読み込む。これによりreconnect中に古いraw eventがGUIへ混入しない。
- [ ] 実FCSでprefetch有無のsample切替latency、peak memory、キャンセル/closeを計測し、効果が
  再現しない環境では自動prefetchを無効化する判断を記録する。現在のdata/ FCSはすべて4 MiB未満のため、
  prefetch実パスの測定は未実施である。`tools/benchmark_prefetch.py`で生成した300,000 eventの
  4.8 MiB FCSでは同期/非同期のevent countとraw hashが一致することを確認したが、これはinstrument
  dataのlatency・peak memory・GUI cancel/closeを代替しない。既存の`data/9_A3.fcs`を
  `--path`で測定できるようbenchmarkを拡張し、2026-07-31 Linuxの一回の測定では
  2,248,944 bytes、32.7 ms（同期）/7.5 ms（scheduler）、event count/hash一致、peak RSS
  121,408 KiBだった（OS cache等の影響を受ける診断値）。
  ただし4 MiB閾値未満なのでこれはprefetch実パスの測定ではなく、scheduler経路の実FCS smokeである。

#### Increment 11: event chunk/process backendの採否

- [x] Increment 3後のdensity profileとIncrement 8後のthread/render profileをreviewし、
  event chunkまたはprocess backendの必要性を記録した。CPU core数だけでは追加しない。
- [x] densityのfixed-bin chunk実装は、global sum・smoothing・normalization parityを検証できる
  profileとmemory budgetが揃うまで追加しない。現行の一worker renderer-neutral estimatorを維持する。
- [x] Windows `spawn`、shared-memory、aggregate memory、cancel/cleanupのprocess設計条件を確認し、
  巨大event arrayをpickleするbackendは実装しない判断を記録した。
- [x] 2026-07-30のBatch Export benchmark（8×5,000）はthread/2が0.976倍、16×10,000は0.866倍で、
  peak RSSもthreadで約1.4倍だった。再現可能なspeedupがないため、既定sequentialとCLI opt-in threadを
  維持し、event chunk/process backendを本incrementでは実装しない。

#### 完了条件

- [x] GUI sample切替はlatest-winsかつresponsiveで、density main scatterを一度だけ送信し、
  viewport変更だけでdensity colorを変えず、unsafeなevent chunk並列化を使わない。
- [x] Run Pipelineは進捗・cancel・memory-bounded sample並列化を提供し、scientific resultと
  deterministic orderがsequentialと一致する。
- [x] Batch Plot Exportはsample/item進捗・cancel・bounded並列化を提供し、overlay、gate、軸、
  label、dot、sidecar、manifestがsequentialと一致する。
- [x] GUI/CLI/Python APIは同じQt非依存control/runnerを使用し、success/failure/cancel/close後に
  thread/processを残さない。
- [x] user-visibleなprogress/cancel/performance設定を公開するincrementで
  `docs/user-manual/user_manual.md`を同時更新する。

## Release E: OS配布とリリース自動化 [P1]

配布準備のPhase 1（必須依存、`python -m flowdesk_qt`、OS標準のユーザー領域、
パッケージmetadataからのversion取得）は完了済みである。以下は、Python未導入の
ユーザーへWindows、macOS、Linux用アプリを配布するための未実装項目である。
一度の作業では、下記Phaseを複数同時に実装しない。

- [ ] `docs/implementation/packaging-and-release.md`を読み、PyInstallerの対象module、Qt plugin、NumPy/flowioのnative library、metadata収集方針を確定する。
- [ ] `packaging/flowdesk.spec`を追加し、PyInstaller `onedir` buildをLinux、Windows、macOSで再現できるようにする。
- [ ] PyInstaller成果物をPython未導入のclean環境で起動するpackage smoke testを追加する。GUI起動、FCS読込、Pipeline、project save/load、TSV/CSV/PNG/SVG/PDF exportを確認する。
- [x] PyInstaller package smokeへ、native `flowdesk-cli` executableによる保存済みBatch Plot Export
  の実行を追加した。3 OS workflowで`data/analysis.flowdesk`の4 samplesを実行し、非空PNG/PDF、
  sidecar、batch manifestを確認する。これはclean環境でのGUI操作、QThread終了、batch thread
  backendのreentrancyを代替しない。
- [ ] Windows向けにInno Setupまたは同等のinstallerを追加する。ユーザー領域へのインストール、Start Menu、uninstaller、upgrade、必要なら`.fcs`関連付けを確認する。
- [ ] macOS向けに`.app`とDMGを追加する。arm64を先行対象とし、必要に応じてx86_64またはuniversal buildを定義する。
- [ ] macOSのDeveloper ID code signing、Hardened Runtime、notarization、ticket stapleをCIで実行できるようにする。秘密情報がない場合は署名工程を安全にskipして理由を記録する。
- [ ] Linux向けにUbuntu 22.04相当をbuild baselineとするAppImageを追加し、Ubuntu 22.04/24.04、Debian、Fedoraで起動確認する。
- [ ] OSごとのpackage smoke testをGitHub Actionsまたは同等のnative runnerで実行する。Windows、macOS、Linuxをcross-compileで代用しない。
- [ ] tagから3 OSのbuild、artifact upload、GitHub Release作成までを自動化するrelease workflowを追加する。
- [ ] 配布物へLICENSE、Qt/PySide6、NumPy、FlowIO、pyqtgraph等のthird-party licenseと入手方法を含める。
- [ ] 各配布物のSHA-256 checksum、build version、source commit、build OSをrelease metadataへ記録する。
- [ ] 配布物を実機またはclean VMでinstall、起動、更新、uninstallし、ユーザー書込み領域、Unicode/空白を含むFCS path、Ctrl-C、QThread終了を確認する。
- [ ] Windows SmartScreen、macOS Gatekeeper、Linux executable permission/AppImage制約を含む既知の制限とユーザー向け手順を`README.md`と`docs/user-manual/user_manual.md`へ追記する。

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
