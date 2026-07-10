# Flowdesk GUIデバッグ・自動テスト基盤 実装指示書

## 0. この指示書の位置づけ

本指示書は、Flowdeskリポジトリ専用の実装ガイドです。実装時は本ファイルを
`docs/implementation/qt-gui-debugging.md` として追加し、`docs/implementation/README.md`
の推奨実装順にも追記してください。

作業開始前に、必ず以下を読んでください。

- `AGENTS.md`
- `docs/architecture.md`
- `docs/headless_execution.md`
- `docs/ai_development_workflow.md`
- `docs/implementation/qt-integration.md`
- `docs/implementation/qt-interactive-plot-controls.md`
- `tests/test_qt_plot_widget.py`
- `logs/260709session04.md`

コードを変更する前に、現在の実装とテスト結果を確認し、変更予定ファイルと受け入れ条件を短く報告してください。

---

## 1. 対象プロジェクトの前提

Flowdeskは以下の構成です。

- Python 3.11以上
- PySide6
- pyqtgraph
- pytest
- GUIエントリーポイント
  - `python -m flowdesk_qt`
  - `flowdesk-gui`
- GUI実装: `src/flowdesk_qt/`
- 科学計算: `src/flowdesk_core/`
- プロジェクト保存: `src/flowdesk_storage/`
- CLI: `src/flowdesk_cli/`

現在の主なGUI構成は以下です。

- `MainWindow`: `src/flowdesk_qt/main_window.py`
- `SampleBrowser`: `src/flowdesk_qt/sample_browser.py`
- `ChannelSelector`: `src/flowdesk_qt/channel_selector.py`
- `PlotWidget`: `src/flowdesk_qt/plot_widget.py`
- `PlotToolbar`: `src/flowdesk_qt/plot_toolbar.py`
- `GateEditor`: `src/flowdesk_qt/gate_editor.py`
- `PopulationTree`: `src/flowdesk_qt/population_tree.py`

既存のGUI関連テストは主に `tests/test_qt_plot_widget.py` にあり、現在は
`QT_QPA_PLATFORM=offscreen`、独自の`QApplication`生成、手動の`close()`と
`deleteLater()`を使用しています。

このリポジトリには、少なくともアップロードされた版では次が不足しています。

- 安定した`objectName`
- `pytest-qt`を使った共通GUI fixture
- GUIテスト専用の実行スクリプト
- 失敗時スクリーンショットとUI状態JSONの自動保存
- GUI用のファイルログ設定
- GUIテストと非GUIテストのプロセス分離
- CI上のGUIテスト設定

また、`logs/260709session04.md`には、Qtテスト後にPySide6/shiboken由来と考えられる
segmentation faultが発生した履歴があります。後の実行では240テスト成功と記録されていますが、
GUIテスト基盤では再発時に原因を追跡できる構成にしてください。

---

## 2. 目的

Codexなどのコーディングエージェントが、手動操作なしで以下を反復できるようにしてください。

1. Flowdesk GUIをデバッグ設定で起動する
2. GUI操作またはGUI相当のイベントを再現する
3. Qt、pyqtgraph、Flowdesk内部状態を観察する
4. 失敗時にログ、スクリーンショット、UI状態を保存する
5. 根本原因を修正する
6. 同じ回帰テストを再実行する
7. GUI結果とheadless `PipelineRunner`結果が一致することを確認する
8. GUIテストと全体テストを別プロセスで実行し、Qt終了処理の問題を検出する

GUIテストを通すために、期待動作、科学計算結果、ゲート判定、アサーションを弱めてはいけません。

---

## 3. 絶対に維持する設計原則

### 3.1 科学計算の分離

`flowdesk_qt`に補償、変換、ゲート判定、集計などの科学計算を追加しないでください。
GUIはプロジェクト状態を編集し、`PipelineRunner`を呼び、結果を表示するだけにしてください。

### 3.2 GUIとheadless実行の一致

GUIで作成・編集したゲートは、`.flowdesk`保存後にCLIまたはPython APIで同じ結果を再現できなければなりません。
表示用downsampling済みデータを分析結果に使ってはいけません。

### 3.3 既存のコールバックAPIを無目的に全面改修しない

現在、`SampleBrowser`、`ChannelSelector`、`GateEditor`、`PlotWidget`は独自コールバックを使用しています。
GUIデバッグ基盤導入だけを理由に、すべてをQt `Signal`へ一括変換しないでください。
ただし、例外を黙って破棄する現在の挙動はデバッグを妨げるため、後述のとおり改善してください。

### 3.4 小さな変更

GUI全体の書き直しは禁止します。既存の公開メソッドとテスト可能な補助メソッドを活用してください。

---

## 4. 依存関係とpytest設定

### 4.1 GUIテスト依存関係

`pyproject.toml`にGUIテスト専用extraを追加してください。

推奨例:

```toml
[project.optional-dependencies]
io = ["flowio", "flowkit"]
gui = ["PySide6", "pyqtgraph", "datashader"]
dev = ["pytest", "ruff", "mypy"]
gui-test = ["pytest-qt"]
```

インストール例をREADMEへ追加してください。

```bash
python -m pip install -e '.[io,gui,dev,gui-test]'
```

`pytest-qt`導入後も、既存テストを一度に全面書換えしないでください。新規テストから`qtbot`と`qapp`を使用し、
既存の手動`QApplication`管理は段階的に移行してください。

### 4.2 pytest marker

`pyproject.toml`へ最低限以下のmarkerを登録してください。

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
addopts = "-ra"
markers = [
  "gui: tests requiring PySide6 or pyqtgraph",
  "gui_e2e: end-to-end tests spanning MainWindow and PipelineRunner",
]
```

GUIテストファイルには`pytestmark = pytest.mark.gui`を設定してください。

---

## 5. テスト配置

既存テストを壊さない範囲で、GUIテストを以下に整理してください。

```text
tests/
├── gui/
│   ├── conftest.py
│   ├── helpers.py
│   ├── test_plot_widget.py
│   ├── test_sample_browser.py
│   ├── test_gate_editor.py
│   ├── test_main_window.py
│   └── test_gui_workflow.py
├── fixtures/
└── 既存のcore/storage/CLIテスト
```

`tests/test_qt_plot_widget.py`は既に有用な回帰テストを多数含むため、最初の変更では削除しないでください。
必要に応じて内容を上記ファイルへ段階的に移し、移動前後で同じテストが実行されることを確認してください。

`tests/gui/conftest.py`では、PySide6 import前にテスト用QPAを設定してください。

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYTHONFAULTHANDLER", "1")
```

コードのインデントは2スペースにしてください。

---

## 6. GUI部品の安定した識別子

現在のGUI部品には`objectName`がありません。主要なウィジェットとアクションへ安定した名前を設定してください。
画面座標や表示順序を識別子として使用しないでください。

最低限、以下に相当する名前を設定してください。

### `MainWindow`

- `flowdeskMainWindow`
- central splitter類
- status bar
- main toolbar

メニューとツールバーの`QAction`はローカル変数だけでなく、テスト可能な属性として保持してください。

- `actionOpenDirectory`
- `actionOpenFiles`
- `actionOpenProject`
- `actionSaveProject`
- `actionExportResults`
- `actionRunPipeline`
- `actionClearGates`
- `actionQuit`

### `SampleBrowser`

- `sampleBrowser`
- `sampleList`
- `channelMetadataTable`
- `addFcsFilesButton`
- `removeSampleButton`

### `ChannelSelector`

- `channelSelector`
- `xChannelCombo`
- `yChannelCombo`
- `xTransformCombo`
- `yTransformCombo`

### `GateEditor`

- `gateEditor`
- `gateTypeCombo`
- `parentPopulationCombo`
- `createGateButton`
- `deleteGateButton`
- `gateList`
- `gateStatusLabel`

### `PlotWidget`と`PlotToolbar`

- `plotWidget`
- `plotGraphicsLayout`
- `plotToolbar`
- `resetRobustRangeButton`
- `resetFullRangeButton`
- `exportPngButton`

### `PopulationTree`

- `populationTree`
- `populationResultsTable`
- `populationStatusLabel`

`objectName`追加によって表示文言、科学計算、保存形式を変更しないでください。

---

## 7. コールバック例外を黙って破棄しない

現在、複数箇所で次の形式が使われています。

```python
try:
  callback(...)
except Exception:
  pass
```

これはCodexによるデバッグを困難にします。

共通のコールバック実行補助を`src/flowdesk_qt/diagnostics.py`または同等の小さなモジュールへ実装してください。

要件:

- 通常モードでは`logger.exception()`で完全なtracebackを記録する
- `FLOWDESK_GUI_STRICT_CALLBACKS=1`の場合は、記録後に例外を再送出する
- `TypeError`をAPI互換判定に使っている箇所は、意図を確認して個別に扱う
- ユーザー操作中の例外を無条件に握りつぶさない
- 既存コールバックAPIの引数仕様を変更しない

最低限、以下のモジュールを確認してください。

- `channel_selector.py`
- `sample_browser.py`
- `gate_editor.py`
- `plot_toolbar.py`
- `plot_widget.py`

GUIテストは原則としてstrict callback modeで実行してください。

---

## 8. ログと未処理例外

### 8.1 GUIログ設定

現在は各モジュールにloggerがありますが、GUI起動時のファイルログ設定がありません。
`src/flowdesk_qt/diagnostics.py`にGUI用ログ初期化を実装してください。

保存先例:

```text
artifacts/gui/<run-id>/logs/application.log
```

ログには以下を含めてください。

- 日時
- level
- logger名
- process ID
- thread名
- メッセージ
- traceback

以下をログに出力しないでください。

- FCSイベント配列全体
- 認証情報
- 不必要な個人情報
- 大きなプロジェクト内容全体

### 8.2 未処理例外

`sys.excepthook`を置き換える場合は、元のhookを保持し、ログ保存後に元のhookも呼んでください。
Qtのイベント処理中に発生した例外を「成功」として終了させないでください。

### 8.3 CLI引数または環境変数

既存の`--data-dir`を維持したまま、必要に応じて以下を追加してください。

- `--debug-artifacts-dir`
- `--log-level`
- `--test-mode`

ただし、GUIデバッグのためだけにlocalhost APIや外部待受ポートを追加しないでください。
このプロジェクトではテストコードから`MainWindow`へ直接アクセスできます。

---

## 9. 構造化UI状態

`MainWindow`またはdiagnosticsモジュールに、JSON serializableなデバッグ状態を返す機能を追加してください。

例:

```python
def debug_state(self) -> dict[str, object]:
  ...
```

最低限、以下を含めてください。

- application name/version
- window title、visible/enabled状態
- project idとproject path
- current sample id
- 読み込まれたsample id、name、path、event count、channel count
- X/Y channel
- X/Y transform
- plot range mode
- current view range
- active gate creation type
- gate一覧
  - id
  - name
  - type
  - parent
  - parameters
  - thresholdsまたはcoordinates
- gate editorの選択行とstatus text
- pipeline workerの有無、running状態、errorの型とメッセージ
- population report statusと各populationのevent count
- `_results_stale`
- main status bar text

FCSイベント配列そのものは含めないでください。

保存先:

```text
artifacts/gui/<run-id>/tests/<sanitized-node-id>/ui-state.json
```

JSON化に失敗しても、元のテスト失敗を隠さないでください。

---

## 10. 失敗時スクリーンショットとartifact

pytest hookとfixtureを使い、GUIテスト失敗時に以下を自動保存してください。

```text
artifacts/gui/<run-id>/
├── environment.json
├── pytest.log
├── logs/
│   └── application.log
└── tests/
    └── <sanitized-node-id>/
        ├── main-window.png
        ├── visible-dialog-01.png
        ├── ui-state.json
        └── failure.txt
```

要件:

- テストが登録した`MainWindow`または対象widgetを`grab()`で保存する
- 必要に応じて`QApplication.topLevelWidgets()`のvisible widgetも保存する
- screenshot取得失敗はログへ記録する
- screenshot取得失敗でテスト本来の例外を置き換えない
- 正常テストでは大量の画像を生成しない
- ファイル名に`/`、`::`、空白などをそのまま使わない

`artifacts/`をGit管理対象外にしてください。ZIPに`.gitignore`が含まれていないため、実リポジトリの
`.gitignore`を確認し、存在しなければ作成してください。

---

## 11. QThreadと終了処理

`MainWindow`は`_PipelineWorker(QThread)`を使用しています。Qt object lifetimeの不整合はsegmentation faultや
`QThread: Destroyed while thread is still running`の原因になるため、以下を実装・検証してください。

- `_on_pipeline_finished()`でworkerの結果を取得後、workerを安全に`deleteLater()`する
- `_worker = None`へする順序を明確にする
- 終了後にsignalが残って二重処理されないようにする
- テスト終了時にrunning workerを残さない
- `MainWindow.closeEvent()`を追加する場合、実行中threadを無条件に`terminate()`しない
- 中断非対応の`PipelineRunner`に対し、見かけだけのキャンセル成功を実装しない
- GUIテストでは`qtbot.waitSignal()`または`qtbot.waitUntil()`で完了を待つ
- 固定の`time.sleep()`や長い`QTest.qWait()`で誤魔化さない

Qt終了時crashを再現した場合は、`PYTHONFAULTHANDLER=1`を有効にし、終了コード、stderr、最後に実行された
テストをartifactへ保存してください。

---

## 12. ネイティブダイアログ

現在、`QFileDialog`と`QMessageBox`は`MainWindow`、`SampleBrowser`、`GateEditor`から直接呼ばれています。
最初の実装では、GUIテストからネイティブファイルダイアログを実際に操作しないでください。

既存のテスト可能なAPIを優先してください。

- `SampleBrowser.add_samples_from_paths()`
- `SampleBrowser.add_samples_from_directory()`
- `MainWindow._save_project_to_path()`
- `MainWindow._load_project_from_path()`
- `MainWindow._export_population_results_to_path()`
- `PlotWidget.export_png()`

メニュー配線やエラーダイアログをテストする場合は、`monkeypatch`で`QFileDialog`と`QMessageBox`を置換してください。

同じpatchが多数重複するようになった場合のみ、薄い`DialogService`を導入してください。
GUIデバッグ基盤のために全面的な依存性注入リファクタリングを行わないでください。

---

## 13. GUIテスト実行スクリプト

このリポジトリでは既存の補助スクリプトが`tools/`にあるため、新規スクリプトも`tools/`へ配置してください。

### 13.1 `tools/run-gui-tests.sh`

要件:

- `set -euo pipefail`
- project rootを安全に解決する
- `PYTHONFAULTHANDLER=1`
- `FLOWDESK_GUI_STRICT_CALLBACKS=1`
- デフォルトは`QT_QPA_PLATFORM=offscreen`
- artifact run directoryを作成する
- 実行コマンド、Python、PySide6、Qt、pyqtgraph、pytestのversionを記録する
- GUI markerだけを実行する
- pytestの終了コードをそのまま返す
- stdout/stderrを`tee`で保存する

実行例:

```bash
./tools/run-gui-tests.sh
```

### 13.2 Xvfbモード

pyqtgraphの実イベントやX11依存挙動を確認するため、任意でXvfb実行を選べるようにしてください。

例:

```bash
FLOWDESK_GUI_BACKEND=xvfb ./tools/run-gui-tests.sh
```

Xvfbモードでは`QT_QPA_PLATFORM=xcb`を使用し、例えば以下で実行してください。

```bash
xvfb-run \
  --auto-servernum \
  --server-args="-screen 0 1920x1080x24" \
  python -X faulthandler -m pytest -m gui
```

`offscreen`とXvfbの結果が異なる場合は、その差を報告してください。

### 13.3 `tools/run-single-gui-test.sh`

使用例:

```bash
./tools/run-single-gui-test.sh \
  tests/gui/test_gui_workflow.py::test_load_gate_run_and_match_headless
```

テストnode idをそのままpytestへ渡し、artifactを保存してください。

### 13.4 `tools/run-gui-debug.sh`

現在のデスクトップセッションでGUIを起動し、ログを保存してください。

例:

```bash
./tools/run-gui-debug.sh --data-dir data/
```

このスクリプトはユーザーの実画面を使うため、`QT_QPA_PLATFORM=offscreen`を強制しないでください。

---

## 14. GUIテストとcoreテストのプロセス分離

Qt test teardownの影響を非GUIテストへ持ち越さないため、少なくとも安定化が確認できるまでは別プロセスで実行してください。

Makefileへ以下に相当するtargetを追加してください。

```make
.PHONY: test-core test-gui test-all gui-debug

test-core:
	pytest -m "not gui" tests/ -v

test-gui:
	./tools/run-gui-tests.sh

test-all:
	$(MAKE) test-core
	$(MAKE) test-gui

gui-debug:
	./tools/run-gui-debug.sh
```

既存の`make test`の意味を変更する場合はREADMEに明記してください。
`make test-all`はcoreとGUIを別Python processで実行してください。

---

## 15. 必須回帰テスト

### 15.1 起動と初期状態

`MainWindow`を作成して表示し、以下を確認してください。

- window titleが`Flowdesk`
- statusが`Ready`
- 主要widgetを`objectName`で取得できる
- sample、gate、population結果が初期状態で空
- workerが存在しない
- 未処理例外がない

### 15.2 synthetic FCSの読み込み

`flowdesk_core.fcs_io.write_fcs_file()`で小さなFCS fixtureを一時ディレクトリへ生成してください。

確認事項:

- `add_samples_from_paths()`で1 sample追加される
- sampleを選択できる
- event dataが`MainWindow`へ読み込まれる
- X/Y channel comboが更新される
- plotが空でない
- 同一pathの重複追加が拒否される

既存の重複pathと同名別pathのテストを維持してください。

### 15.3 channelと表示range

既存の以下の回帰を維持・整理してください。

- channel構成が同じsample間でX/Y選択が維持される
- manual view rangeがreplot後も維持される
- 通常時のmouse dragがpyqtgraph標準ViewBoxへ委譲される
- gate作成時だけmouse eventが捕捉される

### 15.4 rectangle/polygon gate

既存の次の挙動を回帰テストにしてください。

- rectangle gateはdrag start/endからdata座標で作成される
- polygon gateはclickでvertex追加、double clickで完了する
- duplicate final vertexが入らない
- gate overlay編集で`GateSpec`が更新される
- gate変更後にpopulation結果がstaleになる
- 通常のpan/zoomを壊さない

### 15.5 pipeline E2E

以下を1本の`gui_e2e`テストとして実装してください。

1. synthetic FCSを追加する
2. sampleを選択する
3. gateを追加する
4. `_on_run_pipeline()`を呼ぶ
5. workerの`finished`を待つ
6. `PopulationTree`へ結果が表示されることを確認する
7. 同じmanifestとevent dataを`PipelineRunner`でheadless実行する
8. population idごとのevent countが完全一致することを確認する
9. workerが終了・解放されていることを確認する

GUI tableの表示値だけでなく、`ExecutionReport`も確認してください。

### 15.6 project保存・再読込・CLI一致

既存の`test_gui_project_save_reload_and_headless_results_match`を維持してください。

確認事項:

- GUIから保存した`.flowdesk`を再読込できる
- gate id、parent、parameter、threshold/coordinatesが維持される
- display-only transformとanalysis transformを混同しない
- GUI、Python API、CLIでpopulation countが一致する

### 15.7 エラー経路

少なくとも以下をテストしてください。

- sampleなしでRun Pipeline
- channel mismatchでRun Pipelineが拒否される
- `PipelineRunner.run()`が例外を送出した場合
- 不正なgate dependency
- 参照されているparent gateの削除
- 不正FCS file

`QMessageBox`はpatchし、テストをblockさせないでください。
エラー後に`_worker`が残らず、statusとログに原因が残ることを確認してください。

### 15.8 callback例外

strict callback modeで、故意に例外を送出するcallbackを登録し、例外が記録・再送出されることを確認してください。
通常モードではログへtracebackが残ることを確認してください。

### 15.9 artifact生成

artifact helper自体をテストしてください。

- widget screenshotがPNGとして保存される
- UI stateがJSONとして保存される
- 保存失敗が元のテスト例外を隠さない

通常のtest suiteへ常時失敗するテストを追加してはいけません。
artifact確認用の意図的失敗は、手動実行専用サンプルまたはfixture unit testで検証してください。

---

## 16. CodexによるGUI不具合修正手順

GUI不具合を修正する際は、以下の順序を必須としてください。

1. `AGENTS.md`と関連implementation guideを読む
2. `./tools/run-single-gui-test.sh <node-id>`で既存再現を試す
3. 再現しない場合は、修正前に失敗する最小回帰テストを追加する
4. failure artifactのログ、PNG、UI stateを確認する
5. GUI表示問題か、project state問題か、core科学計算問題かを切り分ける
6. 最小限の修正を行う
7. 単一回帰テストを再実行する
8. `make test-gui`を実行する
9. `make test-core`を別processで実行する
10. `ruff check src tests`を実行する
11. 必要な場合だけmypy対象を更新して実行する
12. GUIとheadless結果の一致を確認する

以下は禁止します。

- テストを通すためのassert削除
- timeoutやsleepの無意味な増加
- GUI表示downsampleをgate計算へ使用
- headless再現不能なGUI専用分析状態
- callback例外の握りつぶし
- running QThreadを残したままテスト終了
- 実行していないテストを成功と報告

---

## 17. AGENTS.mdへの追記

既存内容を保持したまま、以下に相当する節を追加してください。

````markdown
## GUI Debugging

Flowdesk GUI uses PySide6 and pyqtgraph.

Run GUI tests with:

```bash
./tools/run-gui-tests.sh
```

Run one GUI test with:

```bash
./tools/run-single-gui-test.sh <pytest-node-id>
```

Run core and GUI tests in separate processes with:

```bash
make test-all
```

Important rules:

- Use stable Qt object names instead of screen coordinates.
- GUI tests run with strict callback exception handling.
- Do not leave a QThread running at test shutdown.
- On failure, inspect screenshots, application logs, and UI state under `artifacts/gui/`.
- GUI population counts must match headless PipelineRunner results.
- Do not use display-downsampled data for scientific results.
- Do not weaken assertions or expected scientific behavior to make GUI tests pass.
````

---

## 18. READMEと実装ガイド一覧

READMEへ以下を追加してください。

- GUI test extraのinstall方法
- GUI test実行方法
- 単一GUI test実行方法
- offscreenとXvfbの使い分け
- artifact保存先
- 実GUIのdebug launch方法

`docs/implementation/README.md`には`qt-gui-debugging.md`を
`qt-integration.md`と`qt-interactive-plot-controls.md`の近くへ追加してください。

---

## 19. 実装順序

一度にすべてを大きく変更せず、以下の順序で実装してください。

### Phase 1: 観測可能性

1. baseline testを実行して記録する
2. `objectName`を追加する
3. GUIログ初期化を追加する
4. callback例外のloggingとstrict modeを追加する
5. UI state dumpを追加する

### Phase 2: テストartifact

1. `pytest-qt`を追加する
2. GUI markerとfixtureを追加する
3. failure screenshotとJSON保存を追加する
4. 既存GUIテストをstrict modeで実行する

### Phase 3: 実行分離

1. `tools/run-gui-tests.sh`を追加する
2. single testとdebug launch scriptを追加する
3. Makefileへ`test-core`、`test-gui`、`test-all`を追加する
4. Qt teardown後の終了コードを確認する

### Phase 4: E2E

1. synthetic FCS load testを追加する
2. QThread pipeline testを追加する
3. GUI/headless一致testを追加する
4. error path testを追加する

各Phase終了時に、変更ファイル、実行コマンド、結果、残課題を報告してください。

---

## 20. 完了条件

以下をすべて満たした場合のみ完了です。

- `./tools/run-gui-tests.sh`でGUIテストを手動操作なしに実行できる
- `./tools/run-single-gui-test.sh`で1件を再現できる
- 主要widgetとactionに安定した`objectName`がある
- callback例外が黙って破棄されない
- strict callback modeでGUIテストを実行できる
- 失敗時にPNG、application log、UI state JSONが保存される
- pipeline workerがテスト終了時にrunningでない
- GUIテストとcoreテストが別processで実行される
- rectangle/polygon gateの既存回帰が維持される
- 通常のpyqtgraph pan/zoomが維持される
- GUI、headless、CLIのpopulation countが一致する
- `ruff check src tests`が成功する
- 既存core/storage/CLIテストが壊れていない
- 実行したコマンドと実際の終了コードが報告される
- 未実行項目を成功と報告していない

---

## 21. 実装後の報告形式

以下の形式で報告してください。

### 調査結果

- Python:
- PySide6 / Qt:
- pyqtgraph:
- pytest:
- 使用QPA backend:
- baseline core tests:
- baseline GUI tests:
- baselineのcrash/警告:

### 変更ファイル

各ファイルについて、変更目的を1行ずつ記載してください。

### 実行コマンドと結果

```text
Command:
./tools/run-gui-tests.sh

Exit code:
0

Result:
...
```

```text
Command:
make test-core

Exit code:
0

Result:
...
```

```text
Command:
ruff check src tests

Exit code:
0

Result:
...
```

### artifact確認

- application log:
- screenshot:
- UI state JSON:
- pytest log:
- crash information:

### GUI/headless一致

- fixture:
- gate:
- GUI count:
- headless count:
- CLI count:

### 残課題

- 未実装:
- 環境依存:
- flaky test:
- Qt teardown上の懸念:

---

## 22. 最終指示

最初にコードを変更せず、現在の環境で以下を確認してください。

```bash
python --version
python -c 'import PySide6, pyqtgraph; print(PySide6.__version__, pyqtgraph.__version__)'
pytest -q
ruff check src tests
```

依存関係不足で実行できない場合は、既存の`.direnv/python-3.12.13`環境またはプロジェクトの正式な仮想環境を確認してください。
勝手に別のPython環境を正しい環境とみなさないでください。

その後、Phase 1から順に実装してください。大規模なGUIリファクタリングは避け、Flowdeskの既存アーキテクチャと
headless reproducibilityを維持したまま、Codexが再現・観察・修正・再検証できる基盤を構築してください。
