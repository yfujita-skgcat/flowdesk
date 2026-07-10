# Flowdesk local LLM 実装指令書

対象リポジトリ: `/home/yfujita/work/bin/python/flowdesk`

この指令書は `bug.md` の未処理項目を、Qwen3.6 27B が順番に実装できるよう細分化したものです。上から順に1項目ずつ作業してください。一度に全ファイルを大きく書き換えないでください。各Phaseが完了したら、そのPhaseのテストを通してから次へ進んでください。

## 0. 絶対に守るルール

1. 最初に次を全文読んでください。
   - `AGENTS.md`
   - `docs/architecture.md`
   - `docs/headless_execution.md`
   - `docs/ai_development_workflow.md`
   - `docs/implementation/qt-integration.md`
   - `docs/implementation/qt-interactive-plot-controls.md`
   - `docs/implementation/gate-engine.md`
   - `docs/implementation/population-statistics.md`
   - `docs/implementation/pipeline-runner.md`
   - `docs/implementation/qt-gui-debugging.md`
   - `.codex/skills/gate-engine/SKILL.md`
   - `.codex/skills/qt-plot-widget/SKILL.md`
   - `.codex/skills/scientific-review/SKILL.md`
   - `tests/test_qt_plot_widget.py`
   - `tests/gui/test_gui_workflow.py`
2. Pythonのインデントは2 spacesを使用してください。既存ファイルを無関係に整形しないでください。
3. `flowdesk_core` から PySide6、Qt、`flowdesk_qt` をimportしてはいけません。
4. GUIにgate membership、compensation、transform、population statisticsの科学計算を実装してはいけません。
5. raw FCS event arrayを変更してはいけません。表示用配列やmaskは別オブジェクトにしてください。
6. 表示downsampling済みデータをgate判定、event count、frequency計算に使用してはいけません。
7. GUIで表示するpopulation countは、同じprojectをheadless `PipelineRunner` で実行した結果と完全一致させてください。
8. rectangle/polygon/range/boolean gate、parent-child gate、通常のpyqtgraph pan/zoom、manual/robust/full rangeを壊してはいけません。
9. テストを通すためにassertion、期待値、scientific behaviorを弱めてはいけません。
10. `data/*.fcs` は変更・追加・commitしないでください。通常テストはsynthetic FCSを使い、real FCSテストはファイル不足時のみ理由付きskipにしてください。
11. 新しい分析結果やmembershipをGUIで必要とする場合、最初にcore model/APIとheadless runnerで表現してください。
12. 対応するimplementation guideが不足しているため、production code変更前に `docs/implementation/population-filtering-and-histograms.md` を追加してください。Goal、対象ファイル、科学計算と表示計算の境界、必須テスト、受け入れ条件を書いてください。`docs/implementation/README.md` にも追加してください。

## 1. 作業開始前のbaseline

コードを変更する前に以下を実行し、実際の終了コードと件数を記録してください。

```bash
.direnv/python-3.12.13/bin/python -c "import platform, PySide6, pyqtgraph, pytest; from PySide6.QtCore import qVersion; print(platform.python_version(), PySide6.__version__, qVersion(), pyqtgraph.__version__, pytest.__version__)"
./tools/run-gui-tests.sh -q
.direnv/python-3.12.13/bin/python -X faulthandler -m pytest -q
.direnv/python-3.12.13/bin/ruff check src tests
```

変更前に次の実装を確認してください。

- `src/flowdesk_core/gating_strategy.py`: 現在membership maskがどこで生成され、どこで破棄されるか。
- `src/flowdesk_core/execution_report.py`: GUIへ渡せる結果model。
- `src/flowdesk_core/pipeline_runner.py`: sampleごとのgate実行順序。
- `src/flowdesk_qt/main_window.py`: report受信、sample/channel切替、plot更新。
- `src/flowdesk_qt/population_tree.py`: 表示列と選択イベント。
- `src/flowdesk_qt/channel_selector.py`: X/Y候補。
- `src/flowdesk_qt/plot_widget.py`: scatter、range、overlay、downsampling。

baselineで失敗した場合、今回の変更前から失敗していることを報告し、原因を切り分けてください。既存のユーザー変更をrevertしてはいけません。

## Phase 1: Population Resultsの名称と列名を修正する [実装済み]

### 1-1. Population表示をgate名へ揃える [実装済み]

問題: Population Resultsは`population_id`を表示しているため、Defined gatesに表示される`GateSpec.name`と一致しません。

実装要件:

1. `PopulationTree` にpopulation idから表示名を解決するための明示的なAPIを追加してください。例: `set_population_names(dict[str, str])`。名前解決をtable描画中の文字列解析で行わないでください。
2. root population `all_events` は `All Events` と表示してください。
3. gate populationは `GateSpec.id -> GateSpec.name` のmappingで表示してください。
4. parent-childを表す既存indentは維持してください。indentの後ろにgate名を表示してください。
5. population idは失わないでください。最低限 `QTableWidgetItem` の `Qt.UserRole` にpopulation idを保存し、選択処理が表示名に依存しないようにしてください。
6. 同名gateが複数あっても内部処理はidで区別してください。
7. gate rename、gate追加・削除、project再読込後にmappingを更新してください。
8. exportは従来どおりpopulation idを出力してください。GUI表示名をTSV/CSVのpopulation idへ混ぜないでください。

対象ファイル候補:

- `src/flowdesk_qt/population_tree.py`
- `src/flowdesk_qt/main_window.py`
- `tests/test_qt_plot_widget.py` または `tests/gui/test_main_window.py`

必須テスト:

- gate idが`gate_ab12`、nameが`CD45 positive`の場合、Population列は`CD45 positive`を表示する。
- itemの`Qt.UserRole`は`gate_ab12`を保持する。
- rootは`All Events`と表示する。
- rename後に表示が更新されるがidは変わらない。
- parent-child indentが維持される。
- export結果は表示名ではなく従来のpopulation idを保持する。

### 1-2. frequency列見出しを変更する [実装済み]

次の見出しだけを変更してください。

- `Freq. of Parent` -> `% of Parent`
- `Freq. of Total` -> `% of Total`

注意:

- 値を100倍しないでください。今回のbugは表記変更だけです。既存値は0〜1のfraction表示のまま維持してください。値のpercent化は別仕様なので勝手に変更しないでください。
- coreの`frequency_of_parent`、`frequency_of_total`のフィールド名やexport headerを変更しないでください。

必須テスト:

- table header文字列が正確に`% of Parent`、`% of Total`である。
- table cell値とexport値が変更前と同じである。

Phase 1確認コマンド:

```bash
./tools/run-single-gui-test.sh <追加したPhase-1-test-node-id> -q
./tools/run-gui-tests.sh -q
.direnv/python-3.12.13/bin/ruff check src tests
```

## Phase 2: Population membershipをheadless pipelineの正式な結果として取得可能にする [実装済み]

このPhaseはPhase 3の表示絞り込みに必要です。GUIでgateを再評価してはいけません。

### 2-1. core APIを設計する

要件:

1. `evaluate_gating_strategy()` 内で生成しているroot/gate population maskを、統計結果と一緒に取得できるGUI非依存APIを追加してください。
2. 既存の `evaluate_gating_strategy()` の戻り値と既存callerを壊さないでください。推奨方法は、新しい結果dataclassまたは新しい関数を追加し、既存関数を互換wrapperとして維持することです。
3. membership maskはsample id、population idと対応づけてください。
4. maskは必ずfull event dataと同じ長さのboolean arrayにしてください。
5. maskをimmutableにしてください。少なくとも返却前に `setflags(write=False)` を設定するか、外部変更から守る明確な方法を実装してください。
6. root mask、rectangle、polygon、range、boolean、parent-childのmaskを返してください。
7. event countは必ず`mask.sum()`と一致させてください。
8. compensation、derived parameters、analysis transformsを適用した後のcanonical pipeline順序でgateを評価してください。
9. `ExecutionReport`へmembershipを含める場合、既存report API・summary・placeholder modeを壊さないでください。巨大maskをJSON debug stateや通常exportへ書き出してはいけません。
10. `MainWindow.debug_state()`にはmask本体を入れず、population idとmask長またはcountだけを入れてください。

設計候補:

- `PopulationMembership` のようなcore dataclassを追加する。
- sampleごとの`population_id`とread-only boolean maskをtupleで保持する。
- `ExecutionReport`にdefault empty tupleのfieldを追加する。

対象ファイル候補:

- `src/flowdesk_core/models.py`
- `src/flowdesk_core/gating_strategy.py`
- `src/flowdesk_core/execution_report.py`
- `src/flowdesk_core/pipeline_runner.py`
- `tests/test_gates.py`
- `tests/test_pipeline_runner.py`
- `tests/test_project_headless_execution.py`

必須coreテスト:

- root maskは全eventがTrue。
- child maskはparent mask外で必ずFalse。
- boolean gate maskが既存event countと一致。
- 各`PopulationResult.event_count == membership.mask.sum()`。
- mask shape/dtype/read-onlyを検証。
- 複数sampleでsample idが混ざらない。
- GUI依存なしでimport・実行可能。
- raw input arrayが変更されない。

Phase 2確認コマンド:

```bash
.direnv/python-3.12.13/bin/python -X faulthandler -m pytest -q tests/test_gates.py tests/test_pipeline_runner.py tests/test_project_headless_execution.py
rg -n "flowdesk_qt|PySide6|Qt" src/flowdesk_core src/flowdesk_cli
.direnv/python-3.12.13/bin/ruff check src/flowdesk_core tests
```

## Phase 3: 表示プロットを選択populationだけに絞り込む

期待workflow例:

1. `FSC-A` vs `SSC-A`でgateを作る。
2. pipelineを実行する。
3. Population Resultsでそのgateを選択する。
4. X/Yを`FSC-A` vs `FL1-A`へ変更する。
5. 選択gateに属するeventだけがscatterへ表示される。

### 3-1. PopulationTreeの選択API

1. row選択時にpopulation idを通知するcallback APIを追加してください。既存callback方式に合わせ、全面的なQt Signal移行はしないでください。
2. callback引数は表示名ではなく`population_id`と`sample_id`にしてください。同じpopulationが複数sampleにあるためsample idも必要です。
3. callbackは `flowdesk_qt.diagnostics.invoke_callback()` を通してください。例外を握りつぶしてはいけません。
4. `all_events`を選ぶと全event表示へ戻してください。
5. report clear/stale、sample削除、project再読込時は無効な選択を解除してください。

### 3-2. MainWindowでmembershipを表示へ適用する

1. `PipelineRunner`が返したmembershipだけを使用してください。GUIでthresholdやpolygonを評価しないでください。
2. 現在sampleと選択populationに対応するfull-length maskを取得してください。
3. `_replot()`でX/Y raw columnを取得した後、同じmaskをX/Y両方へ適用し、その後に`PlotWidget.plot_events()`へ渡してください。
4. downsamplingはmask適用後の表示処理として行って構いません。ただしmembership countはfull mask由来のままにしてください。
5. X/Y channelをgate作成時とは異なるchannelへ変更しても同じmembershipを適用してください。
6. sampleを切り替えた場合、同じpopulation idがそのsampleのreportにあればそのsample用maskを使い、なければ`all_events`へ戻してください。
7. gate追加・編集・削除後は既存どおりresultをstaleにし、古いmembershipで表示しないでください。
8. plot上のgate overlay表示条件は既存のX/Y parameter一致ルールを維持してください。population絞り込みとoverlay表示を混同しないでください。
9. plot statusまたはPopulation Results statusで、選択population名とfull event countを確認できるようにしてください。
10. population selectionはdisplay stateです。gate定義やanalysis resultを変更しないため、選択だけでpipeline再実行やproject analysis state変更を行わないでください。

### 3-3. 必須テスト

synthetic FCSを使うGUI E2Eを追加してください。

- 4 eventsから2 eventsを選ぶgateを作る。
- pipeline完了をsignal/event loopで待つ。固定sleepを使用しない。
- gate populationを選択後、scatterへ渡された点数が2である。
- X/Yをgate作成時と異なる組み合わせへ変更しても点数が2のまま。
- `all_events`選択後は4点へ戻る。
- Population Resultsのevent countとmembership sumと表示対象full countが一致。
- gate編集後にreport/membershipがstaleとなり、古い2点表示を使用しない。
- GUIとheadless runnerのpopulation countが完全一致。
- display downsampling値を変更してもheadless countが変わらない。

real FCSテストを拡張してください。

- `data/*.fcs` を2つ以上読み、各sampleで`all_events`表示できる。
- 1つのgateをpipelineで評価し、sample切替ごとに対応するsampleのmembershipが使われる。
- FCS不足時だけ理由付きskip。
- real FCS自体や期待event countをrepositoryへ固定コピーしない。

Phase 3確認コマンド:

```bash
./tools/run-single-gui-test.sh <population-filter-e2e-node-id> -q
./tools/run-gui-tests.sh -q
.direnv/python-3.12.13/bin/python -X faulthandler -m pytest -q
.direnv/python-3.12.13/bin/ruff check src tests
```

## Phase 4: Y軸のCount選択で1D histogramを表示する

### 4-1. ChannelSelector

1. Y channel候補へ明示的なdisplay-only option `Count`を追加してください。
2. 実FCS channel名と衝突しない内部値を使用してください。表示文字列`Count`だけをchannel idとして科学計算へ渡さないでください。必要ならrole dataまたは定数を使ってください。
3. Xは通常channelを選択し、YがCountの場合だけ1D histogram modeにしてください。
4. Count選択中はY transformを無効化するか、histogramへ適用されないことがUI上明確な状態にしてください。
5. sample切替時もCount選択を可能な限り維持してください。

### 4-2. PlotWidgetの1D histogram mode

1. scatterとhistogramを明示的な別modeとして実装してください。例: `plot_histogram(values, ...)`。既存`plot_events(x, y)`へ多数の`None`分岐を無理に追加しないでください。
2. histogramは表示機能です。bin数/bin幅はdisplay settingとして扱い、gate membershipやpopulation statisticsへ混ぜないでください。
3. histogram inputには、Phase 3で選択されたpopulationのfull membership適用後データを使用してください。
4. NaN/Infを除外してください。除外数をdebug stateまたはstatusで確認可能にしてください。
5. X transformの扱いを明示してください。linear/log10/asinhで空画像や不正rangeを作らないでください。
6. Y軸labelは`Count`にしてください。bin countは0以上にしてください。
7. mode切替時に古いscatter、ROI、histogram itemが重なって残らないようにしてください。
8. histogram表示中のgate作成・編集をどう扱うか明示してください。最低限、2D rectangle/polygon作成buttonを無効化または明確に拒否し、誤った2D gateを作らないでください。range gateはX軸上で作成可能でも構いませんが、headless再現可能なraw/data座標で保存してください。
9. PNG exportがhistogramを含むことを確認してください。
10. sample/channel切替、population切替、robust/full rangeでcrashしないでください。

必須テスト:

- Y=`Count`でscatterではなくhistogram itemが存在する。
- histogram bin countの合計が有限な選択population event数と一致する。表示downsamplingをhistogram countへ使わない。
- all eventsとgate population切替で合計が変わる。
- Yを通常channelへ戻すと2D scatterへ戻り、古いhistogram itemが消える。
- linear/log10/asinh XでPNGがnonblank。
- histogram中に2D gateを誤作成できない。
- `debug_state()`にplot modeを追加し、raw values全体は含めない。

## Phase 5: 2D plotの上・右にmarginal histogramを表示する

### 5-1. UI mode

1. `PlotToolbar`へmarginal histogramの表示/非表示を切り替えるcheckable controlを追加してください。
2. 安定した`objectName`を設定してください。例: `toggleMarginalHistogramsButton`。
3. この設定はdisplay-onlyです。population count、gate、project analysis stateを変更してはいけません。
4. projectへ保存する場合は `plot_display_settings` 配下へ保存し、`transforms`やgate定義へ混ぜないでください。

### 5-2. PlotWidget layout

1. 既存2D plotを中央/左下に置き、X marginal histogramを上、Y marginal histogramを右に配置してください。
2. pyqtgraphの`GraphicsLayoutWidget`、`PlotItem`、linked axisを使用してください。別windowや画像貼り付けで実装しないでください。
3. 上histogramのX axisをmain plotのX axisへlinkしてください。
4. 右histogramのY axisをmain plotのY axisへlinkしてください。
5. main plotのpan/zoomを維持し、linked histogramが追従することを確認してください。
6. marginal histogram inputはPhase 3の選択population dataにしてください。
7. histogram集計はfull selected populationを使ってください。scatter downsamplingの点だけで集計しないでください。
8. NaN/Infとlog10非正値を明示的に処理してください。
9. marginal表示ON/OFFでmain plotのgate overlay、ROI編集、rectangle drag、polygon clickを壊さないでください。
10. 1D Count modeではmarginal histogramを非表示または無効化してください。二重histogram layoutを曖昧にしないでください。
11. PNG exportに現在表示中のmarginal histogramを含めてください。
12. `debug_state()`にmarginal mode、bin数、表示対象population idを追加してください。event array全体は含めないでください。

必須テスト:

- toggle OFFでは既存2D plotだけ、ONではtop/right histogram itemが存在する。
- top histogram count合計とright histogram count合計が選択populationの有限event数と一致する。
- population切替で両histogramが更新される。
- sample切替で両histogramが更新される。
- main ViewBox range変更時にlinked axis rangeが一致する。
- marginal ONでもdefault mouse dragがViewBoxへ委譲される。
- rectangle/polygon gate作成とROI編集の既存テストが成功する。
- marginal ONのPNGがnonblankで、OFF画像とpixel内容が異なる。
- `data/*.fcs` の複数sample切替テストでもcrashせずrangeが有限。

Phase 4・5確認コマンド:

```bash
./tools/run-single-gui-test.sh <histogram-test-node-id> -q
./tools/run-single-gui-test.sh <marginal-histogram-test-node-id> -q
./tools/run-gui-tests.sh -q
.direnv/python-3.12.13/bin/python -X faulthandler -m pytest -q
.direnv/python-3.12.13/bin/ruff check src tests
```

## 6. 最終確認

全Phase完了後、次を順番に実行してください。

```bash
./tools/run-gui-tests.sh -q
make test-core
make test-all
.direnv/python-3.12.13/bin/python -X faulthandler -m pytest -q
.direnv/python-3.12.13/bin/ruff check src tests
git diff --check
rg -n "flowdesk_qt|PySide6|Qt" src/flowdesk_core src/flowdesk_cli
```

さらに次を確認してください。

- `artifacts/gui/<run-id>/environment.json`、`pytest.log`、`logs/application.log`が生成される。
- GUI test終了後にrunning QThreadがない。
- Qt teardownでsegmentation faultがない。
- callback例外がstrict modeで再送出される。
- core/storage/CLI testが壊れていない。
- `MainWindow.debug_state()`がJSON serialize可能で、FCS event arrayやmembership mask本体を含まない。
- GUI、Python API、CLIのpopulation countが一致する。
- display histogram/marginal histogramの設定がscientific resultを変更しない。

## 7. Phaseごとの報告形式

各Phase終了時に、以下を省略せず報告してください。

1. 変更したファイル。
2. 変更したclass/functionと目的。
3. scientific stateとdisplay stateをどう分離したか。
4. 実行したコマンドをそのまま記載。
5. 各コマンドの実際の終了コード。
6. passed/failed/skipped件数。
7. 生成されたartifactのpath。
8. 未実行項目と理由。
9. 未解決問題。
10. 次に実装する最小Phase。

完了したPhaseは `ToDo.md` から削除してください。未完了のPhase、未実行のテスト、既知の制限は削除してはいけません。
