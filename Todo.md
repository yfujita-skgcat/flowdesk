# Flowdesk local LLM 修正・実装指令書

作業対象: `/home/yfujita/work/bin/python/flowdesk`

## 必ず守る前提

- `AGENTS.md` を最初に読み、Python は 2 spaces indentation を維持する。
- 機能実装前に該当する `docs/implementation/*.md` を読む。GUI は `docs/implementation/qt-integration.md` と `docs/implementation/qt-interactive-plot-controls.md`、プロット性能は `docs/implementation/performance-and-review.md`、gate は `docs/implementation/gate-engine.md`、headless 実行は `docs/implementation/pipeline-runner.md` を読む。
- `flowdesk_core` は PySide6 / Qt / `flowdesk_qt` に依存させない。
- GUI は科学計算を実装しない。GUI は project state を編集し、headless pipeline runner を呼び、結果を表示するだけにする。
- raw FCS event array は immutable として扱う。表示用 downsampling や表示範囲調整を analytical result に混ぜない。
- 解析順序は `raw FCS events -> compensation -> derived parameters -> transform -> gate membership -> population statistics -> export` を維持する。

## 現状確認

- `.direnv/python-3.12.13/bin/pytest -q`: 237 passed
- `.direnv/python-3.12.13/bin/ruff check src tests`: passed
- `pyenv exec pytest -q`: `numpy` / `flowio` が無く collection error。作業時は `.direnv/python-3.12.13/bin/...` を使う。
- GUI依存は venv に存在する: PySide6, pyqtgraph, numpy, flowio import OK。
- GUI関連の pytest は現状ほぼ無い。`tests/` は core/CLI/storage 中心。
- **2026-07-09 追加**: axis transform (linear/log10/asinh) の GUI 実装済み。`ChannelSelector` に X/Y scale の `QComboBox`、`PlotWidget` に `_apply_transform()` / `_update_log_mode()` を追加。
- **2026-07-09 追加**: 通常のFlowJo類似GUI操作の実装指示書を `docs/implementation/qt-interactive-plot-controls.md` に追加。プロット上のゲート作成/編集、logscale、plot/dot/gate color、population highlight、PNG export、テスト方針をここに集約。

## P0: 通常のGUIプロット操作を実装する

### 指示書

local LLM は実装前に必ず `docs/implementation/qt-interactive-plot-controls.md` を読むこと。

### 実装対象

- プロット上での rectangle gate 作成
- プロット上での polygon gate 作成
- range gate 作成
- gate 選択、移動、リサイズ、頂点編集、リネーム、削除、複製
- parent population 変更
- linear/log10/asinh のX/Y個別scale設定
- plot background color、dot color、dot opacity、dot size、gate outline/fill color の変更
- selected population の highlight / backgating
- robust range / full range reset
- current plot view のPNG export

### 実装ルール

- 表示設定と解析設定を分離する。
- 色、dot size、opacity、背景、grid、viewport は表示設定であり、pipeline result を変えてはいけない。
- gate、parent population、analysis transform は解析設定であり、project data と headless pipeline runner で再現可能にする。
- plot mouse 座標は pyqtgraph の scene/view 変換で data coordinate または transformed data coordinate に変換し、screen pixel を保存しない。
- log10 表示は `PlotItem.setLogMode(x=..., y=...)` など、点データと軸tickを同時に整合させるAPIを使う。`ViewBox.setLogMode()` 単独に戻さない。

### 受け入れ条件

- ユーザーが数値入力なしに plot 上で gate を作成・編集・削除できる。
- GUI作成 gate の population count が headless `PipelineRunner` と一致する。
- 色やdot size変更で population count が変わらない。
- linear/log10/asinh の表示で点群と gate overlay が一致する。
- exported PNG が現在の表示、色、scale、gate overlay を反映する。

## P0: GUIプロットで細胞ドットが下端に潰れて見える問題を直す

### 再現事実

offscreen で `data/1_A1.fcs` を `PlotWidget` に描画すると、FSC-H vs FSC-A のY軸が `6e+07` 付近まで広がり、点群が下端に潰れて見える。

確認した値:

- `data/1_A1.fcs` shape: `(31552, 14)`
- channel: `['FSC-H', 'FSC-A', 'SSC-H', 'SSC-A', ...]`
- `FSC-A`: p50 `198699`, p99 `2770903`, max `60867720`
- `SSC-A`: p50 `85781`, p99 `4843521`, max `37837696`

つまり autoRange が極端な外れ値を含んでおり、主要な細胞集団が表示上ほぼ見えない。

### 対象ファイル

- `src/flowdesk_qt/plot_widget.py`
- `src/flowdesk_qt/channel_selector.py`
- 必要なら `src/flowdesk_qt/main_window.py`
- GUIテストを追加するなら `tests/test_qt_plot_widget.py` など

### 修正方針

1. `PlotWidget` に表示専用の robust auto-range を実装する。
   - 初期表示は finite values の percentile 範囲を使う。例: 0.5-99.5% または 1-99%。
   - percentile 範囲が潰れる場合だけ min/max に fallback。
   - 表示範囲調整は plot view のみ。event data や gate evaluation には絶対に使わない。
   - ユーザーが全範囲表示に戻せる API / UI も用意するのが望ましい。

2. 現在の `_auto_range()` は `ViewBox.autoRange()` だけなので外れ値に弱い。`setRange(xRange=..., yRange=..., padding=...)` を使い、表示範囲を deterministic にする。

3. `PlotWidget.plot_events()` の `symbolSize=2, pxMode=False` を見直す。
   - 細胞ドットの表示は pixel-size marker が自然。`pxMode=True` または pyqtgraph default を使う。
   - 大量点描画では `PlotDataItem` より `ScatterPlotItem` / `setData()` の使い方を確認し、描画が空にならないことをテストする。

4. log/asinh 表示時の non-positive / non-finite 値の扱いを明示する。
   - 表示から除外した点数を status か内部値で追跡できるようにする。
   - 除外は表示だけに限定し、解析には影響させない。

### 受け入れ条件

- `data/1_A1.fcs` の FSC-H vs FSC-A 初期表示で主要な細胞集団が画面内に見える。
- robust range を使っても、全イベント数や pipeline の gate membership は変わらない。
- offscreen Qt テストまたは小さな synthetic data の unit test で、外れ値1点があっても表示 range が外れ値だけに支配されないことを確認する。
- `.direnv/python-3.12.13/bin/pytest -q` と `.direnv/python-3.12.13/bin/ruff check src tests` が通る。

## P0: gate overlay と点群の座標系ズレを直す

### 問題

`plot_widget.py` は点群に asinh 表示変換を適用する一方、gate overlay は raw data coordinate のまま `RectROI` / `PolygonROI` として追加している。log10 は `ViewBox.setLogMode` を使う想定だが、gate overlay との整合性が未確認。これにより表示上の gate と実際の gate membership がズレる危険がある。

該当箇所:

- `src/flowdesk_qt/plot_widget.py`: `_apply_transform()`, `_update_log_mode()`, `_create_gate_item()`
- `src/flowdesk_qt/gate_editor.py`: `GateSpec` 作成
- `src/flowdesk_qt/main_window.py`: gate overlay refresh

### 修正方針

1. 表示 transform と解析 transform の責務を整理する。
   - 解析に使う transform は project model の `TransformSpec` として保存し、pipeline runner が実行する。
   - 一時的な表示 scale だけなら gate 作成時に raw coordinate へ逆変換できる必要がある。

2. `GateSpec.transform_id` を使うか、raw coordinate gate と display coordinate gate のどちらで保存するかを明確化する。
   - FlowJo類似アプリとしては、表示上で描いた gate と headless pipeline の gate 結果が一致することが最優先。

3. overlay 作成時は点群と同じ表示座標系に変換する。
   - raw coordinate gate を保存する場合、overlay の threshold / vertices を表示 transform 後の座標へ変換して描画する。
   - display coordinate gate を保存する場合、pipeline runner 側が同じ transform stage で評価できるよう `transform_id` と `TransformSpec` を project に保存する。

4. pyqtgraph の `ViewBox.setLogMode(axis, logMode)` で axis=`"x"`/`"y"` は有効（`"both"` は非サポート）。`PlotItem.setLogMode(x=..., y=...)` も存在し、表示上は同様の効果が得られる。現在の `plot_widget.py` は `ViewBox.setLogMode` を利用しており、gate overlay の座標系整合性が主な懸念点。

### 受け入れ条件

- linear/log10/asinh それぞれで、画面上の rectangle gate と headless pipeline の event_count が一致する synthetic test を追加する。
- gate overlay が現在選択中の X/Y channel と一致しない場合は表示しないか、明示的に警告する。
- gate 座標は screen pixel ではなく、再現可能な data coordinate または transformed data coordinate として保存される。

## P0: gate 作成・削除後にプロットが自動更新されない問題を直す

### 問題

`GateEditor` は gate 作成/削除時に変更通知を出していない。`MainWindow` は `on_gate_selected()` だけ購読しており、gate 作成直後に overlay が再描画されない。

該当箇所:

- `src/flowdesk_qt/gate_editor.py`: `_create_gate_dialog()`, `finish_polygon_gate()`, `_delete_selected_gate()`, `add_gate()`, `clear_gates()`
- `src/flowdesk_qt/main_window.py`: `_connect_signals()`, `_replot()`, `_on_gate_selected()`

### 修正方針

1. `GateEditor` に `on_gates_changed(callback)` を追加する。
2. gate add/delete/clear/polygon finish ですべて changed callback を発火する。
3. `MainWindow` は changed callback で `_replot()` または overlay refresh を呼ぶ。
4. `_on_gate_selected()` の `pass` は最低限、選択 gate の highlight または no-op コメントに整理する。

### 受け入れ条件

- rectangle/range/polygon gate 作成後、再度チャンネルを触らなくても overlay または gate list が即時反映される。
- gate 削除後、overlay も消える。
- GUI unit test で callback 発火を確認する。

## P0: GateEditor が現在の X/Y channel を受け取っていない問題を直す

### 問題

`MainWindow._replot()` は `x_name` / `y_name` を得ているが、`GateEditor.set_plot_channels()` を呼んでいない。そのため作成される `GateSpec.x_parameter/y_parameter` が空文字のままになる可能性がある。pipeline runner は parameter lookup に失敗し、gating error から root population fallback になる。

該当箇所:

- `src/flowdesk_qt/main_window.py`: `_on_sample_selected()`, `_on_channel_changed()`, `_replot()`
- `src/flowdesk_qt/gate_editor.py`: `set_plot_channels()`, `_create_gate_dialog()`

### 修正方針

1. sample selection と channel selection のたびに `self._gate_editor.set_plot_channels(x_name, y_name)` を呼ぶ。
2. `GateEditor` 側で x/y channel が未設定なら gate 作成を禁止する。
3. gate 作成ダイアログに現在の channel 名を表示し、どの軸に対する gate か分かるようにする。

### 受け入れ条件

- GUIから作った rectangle gate の `GateSpec.x_parameter/y_parameter` が現在の combo box と一致する。
- pipeline run 後、gate population が root fallback だけではなく、作成 gate の population result を出す。

## P1: polygon gate の plot click 入力が未接続

### 問題

`GateEditor` には `receive_polygon_vertex()` / `finish_polygon_gate()` があるが、`PlotWidget` は click/double-click event を実装しておらず、`MainWindow` も接続していない。`PlotWidget.screen_to_data()` も `mapFromGlobal()` を使っており、pyqtgraph scene/view coordinate として正しいか疑わしい。

該当箇所:

- `src/flowdesk_qt/plot_widget.py`: `screen_to_data()`, mouse callbacks
- `src/flowdesk_qt/gate_editor.py`: polygon collection methods
- `src/flowdesk_qt/main_window.py`: signal wiring

### 修正方針

1. pyqtgraph の `Scene.sigMouseClicked` / `ViewBox.mapSceneToView()` を使って data coordinate を得る。
2. single click で vertex 追加、double click または明示ボタンで polygon finish を実装する。
3. polygon 作成中の仮 overlay を表示する。
4. channel/transform変更時に polygon 作成中ならキャンセルまたは座標系を明示的に保持する。

### 受け入れ条件

- 3点以上クリックして polygon gate を作成できる。
- 作成された vertices は screen pixel ではなく data coordinate または transformed data coordinate。
- synthetic data で polygon gate の画面 overlay と pipeline event_count が一致する。

## P1: 複数サンプル pipeline 実行時の channel_names が1つだけ

### 問題

`MainWindow._worker` には `self._channel_names` だけが渡される。複数サンプルで channel 構成が違う場合、選択中サンプルの channel_names で全サンプルを処理してしまう。

該当箇所:

- `src/flowdesk_qt/main_window.py`: `_PipelineWorker`, `_on_run_pipeline()`
- `src/flowdesk_core/pipeline_runner.py`: `PipelineRunner.run(..., event_data, channel_names)`

### 修正方針

1. 最小修正: GUI は channel_names が全サンプルで同一か検証し、違う場合は pipeline 実行を拒否する。
2. より良い修正: `PipelineRunner.run()` が `sample_id -> channel_names` mapping を受け取れるよう core API を拡張し、GUI/CLI/headless テストを追加する。
3. 後者を選ぶ場合は implementation guide を更新してから実装する。

### 受け入れ条件

- channel mismatch 時に silent wrong result を出さない。
- 複数サンプル実行のテストを追加する。

## P1: sample id の衝突対策

### 問題

`SampleBrowser._add_single_file()` は `Path(path).stem` を sample id にしている。同名ファイルを別ディレクトリから読むと `_event_data` key が衝突する。

### 修正方針

- sample id は stable かつ一意にする。例: path hash を suffix にする。
- 表示名は stem のままでよい。
- project manifest と execution report に同じ sample id が入ることを確認する。

### 受け入れ条件

- 同じ stem の2ファイルを読み込んでも別サンプルとして保持される。

## P1: GUI-created project manifest の永続化・再現性を強化

### 問題

`MainWindow._build_project_manifest()` は GUI内の一時 dict を作るだけで、project storage schema との整合性や保存/再読込が不十分。`project_version` も含まれていない。GUIで作った解析が完全に headless reproduction できる保証が弱い。

### 修正方針

1. `docs/implementation/project-storage.md` と `docs/implementation/pipeline-runner.md` を読んで、GUI状態を project model/storage と揃える。
2. GUIで作った gate/transform/sample selection を `.flowdesk` project として保存できるようにする。
3. 保存した project を CLI `flowdesk run` で実行し、GUI結果と同じ population results になるテストを追加する。

### 受け入れ条件

- GUI作成 gate を含む project が保存できる。
- 保存 project を headless runner / CLI で再実行できる。

## P2: compensation / derived parameters / transforms の GUI設定が未実装

### 現状

core には compensation, derived parameters, transforms, pipeline runner のテストがある。一方、GUIからこれらを設定・保存する UI はほぼ無い。

### 修正方針

優先順位:

1. FCS metadata spillover の検出と、適用/未適用の選択。
2. fluorescence channel の既定表示 transform 設定。
3. project model に保存される analysis transform 設定。
4. derived parameter editor。

### 受け入れ条件

- GUIで設定した compensation/transform が project manifest に保存され、headless pipeline runner で同じ結果になる。

## P2: GUIテスト基盤を追加

### 修正方針

- `pytest-qt` を導入するか、Qt offscreen の最小テストで始める。
- optional GUI dependency なので、依存が無い環境では skip する。
- まず以下をテストする:
  - `flowdesk_qt` import
  - `PlotWidget.plot_events()` が外れ値付きデータでも robust range を設定する
  - `GateEditor` の `on_gates_changed` callback
  - `MainWindow` が channel変更時に `GateEditor` へ x/y channel を渡す
  - GUIで作った gate を `PipelineRunner` が評価できる

## P2: ドキュメントの実装済み表記を更新

### 問題

`README.md` には GUIが「2D scatter plots, gate editing, pipeline execution」まで実装済みと読める記述があるが、現状は production GUI behavior には未実装/不具合が残る。

### 修正方針

- P0/P1 修正後、README の status を実態に合わせて更新する。
- 「GUIは初期実装」「large-file rendering / robust gate editing は作業中」など、過大表現を避ける。
- axis transform (linear/log10/asinh) は2026-07-09に実装済みであることを反映する。

## 推奨作業順

1. P0の `PlotWidget` robust auto-range と marker pxMode 修正。
2. P0の channel sync（`set_plot_channels` 接続）と gates changed callback 修正。
3. P0の gate overlay 座標系を整理し、linear表示でまず GUI gate と pipeline result を一致させる。
4. P0の gate overlay を asinh/log10 表示でも座標整合させる（2-3が完了してから）。
5. P1の polygon click wiring。
6. P1の複数サンプル channel_names 問題。
7. project save/load と GUI-created analysis の headless reproduction。

## 実行コマンド

```bash
.direnv/python-3.12.13/bin/pytest -q
.direnv/python-3.12.13/bin/ruff check src tests
.direnv/python-3.12.13/bin/python -c "import PySide6, pyqtgraph, numpy, flowio; print('gui/io deps ok')"
```

GUIの手動確認:

```bash
flowdesk-gui --data-dir data/
```

※ `python -m flowdesk_qt` は動作しない。entry point は `flowdesk-gui`。

期待する手動確認:

- `data/1_A1.fcs` を選んだ直後、FSC-H vs FSC-A の主要点群が見える。
- X/Y channel を変えると plot と gate editor の対象 channel が同期する。
- rectangle gate 作成直後に overlay が出る。
- Run Pipeline 後、root population だけでなく gate population も表示される。
