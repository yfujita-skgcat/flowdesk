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
| B3.1 | `docs/implementation/gating-and-results-workspaces.md` |
| B3.2 | `docs/implementation/interactive-current-sample-preview.md` |
| B3.3 | `docs/implementation/results-integrated-current-sample-recalculation.md` |
| B4 | `docs/implementation/group-gating-and-overrides.md` |
| B6 | `docs/implementation/graph-window-v2.md` |
| B7 | `docs/implementation/overlay-and-backgating.md` |
| B7.1 | `docs/implementation/multi-sample-overlay-and-plot-presentation.md` |
| B7.2 | `docs/implementation/integrated-overlay-controls-and-plot-appearance.md` |
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
- [x] 済み: statistic resultはResults workspaceのpopulation childだけに表示し、現在のWorkspaceとCustom Statistics間の表示重複をなくす。
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
- [x] plot areaで`Ctrl + 左ボタンのドラッグ`を範囲変更（X/Y box zoomまたは範囲選択）に割り当てる。通常の左ドラッグ、Pan、gate rectangle/polygon/ROI編集、右クリックcontext menuと競合させず、開始・移動・終了・Esc/キャンセル・plot外終了を定義する。既存の右ドラッグ由来の範囲操作を置き換え、固定画面座標ではなくViewBoxのdata coordinatesを使う。
- [x] Qtテストで、compact dialogのminimum size/複数ページ遷移/Cancel、axis widthとtick fontのstyle適用、指数superscriptのlabel/export、Ctrl+左ドラッグのrange変更と他のmouse gesture非干渉をstable objectNameとsynthetic eventで検証する。GUI/headlessの科学的結果不変、project save/load、PNG/SVG/PDF再現を受け入れ条件にする。
- [ ] 実装後に`./tools/run-gui-tests.sh -q`、plot presentation/plot widget関連core test、ruff、`git diff --check`を実行し、小さいモニタ・高DPI・offscreen Qtで残る制限を記録する。

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

### Phase B8: Autosaveとcrash recovery [S14]

- [x] autosave interval、retention、disableをglobal preferenceとして追加する。
- [x] dirty projectだけをatomic autosaveする。
- [x] normal projectより新しいrecoveryをtimestamp比較で検出できるようにする。
- [x] recover copyを別pathで開き、元projectを自動上書きしない。
- [x] recovery retention、read-only、atomic save経路をtestする。QThread/disk-fullはGUI/OS依存のためintegration fixtureへ保留する。

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
