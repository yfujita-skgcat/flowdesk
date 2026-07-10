# Flowdesk local LLM 修正・実装指令書

作業対象: `/home/yfujita/work/bin/python/flowdesk`

この ToDo は `bug.md` の項目順に並べた未処理タスクです。既存 ToDo にあった以下の完了済み項目は削除済みです: robust auto-range、basic gates changed callback、GateEditor への X/Y channel 同期、plot 上の rectangle/polygon gate 作成、polygon click wiring、PNG plot export。

## 必ず守る前提

- 最初に `AGENTS.md` を読み、Python は 2 spaces indentation を維持する。
- 実装前に該当する `docs/implementation/*.md` を読む。GUI は `docs/implementation/qt-integration.md` と `docs/implementation/qt-interactive-plot-controls.md`、gate は `docs/implementation/gate-engine.md`、population/export は `docs/implementation/population-statistics.md` と `docs/implementation/export-and-cli.md`、headless 実行は `docs/implementation/pipeline-runner.md` を読む。
- `flowdesk_core` は PySide6 / Qt / `flowdesk_qt` に依存させない。
- GUI は科学計算を実装しない。GUI は project state を編集し、headless pipeline runner を呼び、結果を表示・保存するだけにする。
- raw FCS event array は immutable として扱う。表示用 downsampling、表示範囲、色、opacity は analytical result に混ぜない。
- 解析順序は `raw FCS events -> compensation -> derived parameters -> transform -> gate membership -> population statistics -> export` を維持する。

## 現状確認メモ

- `src/flowdesk_qt/plot_widget.py` には `on_gate_geometry_changed()` があり、ROI 移動・編集後に更新 gate を通知できる。
- ただし `src/flowdesk_qt/main_window.py` の `_on_gate_geometry_changed()` は `GateEditor.update_gate(..., notify=False)` で保存しており、結果 invalidation や Population Results の stale 表示対策がない。
- `src/flowdesk_qt/sample_browser.py` は `Path(path).stem` を sample id にしており、同じ FCS の再追加や同名別パスの衝突を防いでいない。削除 UI もない。
- `src/flowdesk_qt/channel_selector.py` の `set_channels()` は sample 変更ごとに X/Y combo を初期値へ戻す。
- `src/flowdesk_qt/population_tree.py` は表示のみで、Population Results の GUI export はない。core 側には `flowdesk_core.export.write_population_results()` / `write_export_records()` がある。
- core 側には boolean gate と parent-child hierarchy の評価実装があるが、GUI から parent population や boolean gate を作る UI がない。

## P0-1: gate 移動・編集後に Population Results を stale にしない

### bug.md 対応

「ゲートを作成後 Run Pipeline をクリックしたら統計量が Population Results に出てくるが、その後にゲートを移動しても値が変わらない。」

### 対象ファイル

- `src/flowdesk_qt/main_window.py`
- `src/flowdesk_qt/gate_editor.py`
- `src/flowdesk_qt/plot_widget.py`
- `tests/test_qt_plot_widget.py` または新規 GUI test

### 修正方針

1. ROI 編集完了時に `MainWindow._on_gate_geometry_changed()` が gate state を更新したあと、既存 Population Results を明示的に stale 扱いにする。
   - 最小実装: `PopulationTree.clear()` を呼び、status に「gate changed; rerun pipeline」を表示する。
   - さらに良い実装: gate/transform/sample 変更後に「Run Pipeline が必要」状態を MainWindow に持たせる。
2. `GateEditor.update_gate(..., notify=False)` のままだと変更通知を抑制するため、必要なら `notify=True` にするか、overlay 再描画ループを起こさない専用の invalidation callback を追加する。
3. gate 移動後に自動で pipeline を再実行する場合でも、必ず `_on_run_pipeline()` / `PipelineRunner` 経由にする。GUI 内で event_count を直接計算しない。
4. gate edit 後の overlay、gate list、project manifest、pipeline 実行時の `GateSpec` が同じ更新済み座標を参照することを確認する。

### 受け入れ条件

- rectangle ROI を移動またはリサイズした後、古い Population Results がそのまま有効に見えない。
- gate edit 後に Run Pipeline を再実行すると、更新後 gate の event_count が表示される。
- GUI test で `_on_gate_geometry_changed()` 後に `GateEditor.gates()[index]` が更新され、Population Results が clear または stale 表示になることを確認する。
- headless `PipelineRunner` で同じ更新済み gate を評価した event_count と GUI 表示結果が一致する。

## P0-2: Add FCS Files 後にサンプルを除外・削除できるようにする

### bug.md 対応

「Add FCS Files.. で FCS を追加したのち、除外する方法がない。」

### 対象ファイル

- `src/flowdesk_qt/sample_browser.py`
- `src/flowdesk_qt/main_window.py`
- `tests/test_qt_plot_widget.py` または `tests/test_qt_sample_browser.py`

### 修正方針

1. `SampleBrowser` に選択 sample を削除する UI を追加する。例: `Remove Selected` button。
2. `SampleBrowser` から sample removal callback を発火し、`MainWindow` が以下を同期削除する。
   - `_event_data[sample_id]`
   - current selection / plot
   - Population Results の stale/clear
   - project manifest に含まれる sample list
3. 削除後の選択状態を定義する。
   - 次の sample があれば選択する。
   - 何もなければ plot、channel selector、Population Results を clear する。
4. サンプル削除は解析結果に影響する project state 変更なので、pipeline 再実行が必要な状態にする。

### 受け入れ条件

- GUI で追加済み FCS を選択して削除できる。
- 削除された sample は `_event_data` と次回 `_build_project_manifest()` から消える。
- 削除後に Run Pipeline しても除外済み sample の result が出ない。
- 削除操作に関する GUI test を追加する。

## P0-3: 同じ FCS の重複追加を防ぐ

### bug.md 対応

「同じ FCS を繰り返し追加できてしまう。この仕様に意味があるなら残してよいが、もし意味がないなら、追加済みの FCS は除外するようにしてほしい。」

### 対象ファイル

- `src/flowdesk_qt/sample_browser.py`
- 必要なら `src/flowdesk_qt/main_window.py`
- tests

### 修正方針

1. 同じ絶対 path の FCS は重複追加しない。`Path(path).resolve()` を GUI-side の既読 path set で管理する。
2. 同じ stem だが別ディレクトリの FCS は別 sample として扱う。現状の `sample_id = Path(path).stem` は衝突するため、stable で一意な id に変更する。
   - 例: `stem + "_" + sha1(resolved_path)[:8]`
   - 表示名は stem のままでよい。
3. duplicate skip の件数を status/message に出せるようにする。最低限、追加件数が正しく返るようにする。

### 受け入れ条件

- 同一ファイル path を複数回追加しても sample list に 1 件だけ表示される。
- 同じ stem の別ファイルは別 sample id として保持され、`_event_data` key が衝突しない。
- duplicate skip と same-stem different-path の test を追加する。

## P1-4: gate 作成中の仮形状 preview を表示する

### bug.md 対応

「ゲート作成時に、ゲート確定前のゲートの形を決めているときにその形が表示されるようにしてほしい。」

### 対象ファイル

- `src/flowdesk_qt/plot_widget.py`
- `src/flowdesk_qt/main_window.py`
- `tests/test_qt_plot_widget.py`

### 修正方針

1. rectangle 作成中は drag start から現在位置までの temporary rectangle ROI/graphics item を表示する。
2. polygon 作成中はクリック済み vertices と現在 mouse position を temporary polyline として表示する。
3. preview item は確定前の表示専用 state とし、`GateSpec` や pipeline result に入れない。
4. gate 作成完了、キャンセル、sample/channel/transform 変更時に preview を確実に消す。

### 受け入れ条件

- rectangle drag 中に仮 rectangle が見える。
- polygon vertex 追加中に仮 polyline が見える。
- 確定前 preview は Run Pipeline に影響しない。
- preview cleanup の unit test または offscreen GUI test を追加する。

## P1-5: sample 変更時に X/Y axis 選択を保持する

### bug.md 対応

「Samples の選択を変更すると、毎回 X axis, Y axis の設定がリセットされる。選択を変更しても、前回の設定を保持するようにしてほしい。」

### 対象ファイル

- `src/flowdesk_qt/channel_selector.py`
- `src/flowdesk_qt/main_window.py`
- tests

### 修正方針

1. `ChannelSelector.set_channels()` に現在の X/Y channel 名を渡すか、内部で現在値を保持して、次 sample に同名 channel がある場合は復元する。
2. 同名 channel がない場合だけ既定値へ fallback する。その場合は status に fallback 理由を出す。
3. X/Y scale (`linear` / `log10` / `asinh`) も sample 変更で維持する。

### 受け入れ条件

- sample A で X/Y を変更後、同じ channel set の sample B に切り替えても X/Y selection が維持される。
- 選択 channel が存在しない sample では安全に fallback し、空 channel の gate を作らない。
- test を追加する。

## P1-6: manual axis range を sample 変更後も保持する

### bug.md 対応

「X axis, Y axis の範囲が manual 設定の場合に、Samples の選択を変更すると、範囲が毎回違う。複数の FCS sample 間で同じ範囲を使用することが多いので、Samples の選択を変更しても、前回の範囲設定を保持するようにしてほしい。」

### 対象ファイル

- `src/flowdesk_qt/plot_widget.py`
- `src/flowdesk_qt/plot_toolbar.py`
- `src/flowdesk_qt/main_window.py`
- tests

### 修正方針

1. plot view range の mode を明示する。
   - `robust_auto`
   - `full_auto`
   - `manual`
2. ユーザーが pan/zoom した場合、または将来 manual range 入力をした場合は `manual` として現在の ViewBox range を保持する。
3. sample 変更時、`manual` なら保持済み range を新 sample に適用する。`robust_auto` / `full_auto` なら従来どおり sample ごとに計算してよい。
4. log10 axis では ViewBox range が log-space か raw-space かを明確化し、既存 `_robust_range_for_axis()` と矛盾させない。

### 受け入れ条件

- manual range mode で sample を切り替えても X/Y range が維持される。
- robust/full reset を押すと manual mode から抜け、期待する auto range に戻る。
- range 保持は表示だけに作用し、gate membership や population count を変えない。

## P1-7: Population Results を GUI から export できるようにする

### bug.md 対応

「Population Results を export できるようにしてほしい。」

### 対象ファイル

- `src/flowdesk_qt/population_tree.py`
- `src/flowdesk_qt/main_window.py`
- `src/flowdesk_core/export.py` は既存 API を利用する。原則 GUI のために core export logic を複製しない。
- tests

### 修正方針

1. Population Results 用の `Export Results...` action/button を追加する。plot PNG export と混同しない名前にする。
2. `PopulationTree.last_report()` から `ExecutionReport.population_results` を取得し、core export API で TSV/CSV を保存する。
3. 結果がない場合は export を拒否し、Run Pipeline が必要なことを表示する。
4. gate/sample 変更後に stale 扱いになっている場合は、古い結果を export しない。再実行を促す。

### 受け入れ条件

- Run Pipeline 後、Population Results を TSV または CSV として保存できる。
- 保存内容は core export tests と同じ header/値形式になる。
- stale または empty results は export できない。
- GUI 側は `flowdesk_core.export` を呼ぶだけで、独自 CSV 生成ロジックを持たない。

## P2-8: gate hierarchy / boolean gate の GUI 方針を実装する

### bug.md 対応

「gate hierarchy の方法がわからない。gate A かつ gate B のような条件で gate を作成したいが、どうすればよいかわからない。未実装ならば、実装方針、計画を建てる。」

### 現状

- core には `GateSpec.parent_population_id`、parent-child hierarchy、boolean gate (`operation`: `and` / `or` / `not`, `source_ids`) がある。
- GUI は gate type combo が `rectangle` / `range` / `polygon` のみで、parent population 選択や boolean gate 作成 UI がない。

### 対象ファイル

- `src/flowdesk_qt/gate_editor.py`
- `src/flowdesk_qt/population_tree.py`
- `src/flowdesk_qt/main_window.py`
- core 変更が必要なら `docs/implementation/gate-engine.md` を更新してから実装する。
- tests

### 実装計画

1. まず parent population 選択 UI を追加する。
   - 新規 gate 作成時に parent population を選べるようにする。
   - 初期値は `all_events`。
   - 既存 gates を parent 候補に出す。
2. 次に boolean gate UI を追加する。
   - gate type に `boolean` を追加する。
   - operation (`and` / `or` / `not`) と source gate/population ids を選択できる dialog を作る。
   - `and` では「gate A かつ gate B」を `GateSpec(gate_type="boolean", thresholds={"operation": "and", "source_ids": [...]})` として保存する。
3. gate dependency validation を入れる。
   - 存在しない source id / parent id を選べない。
   - 循環参照を防ぐ。
   - boolean gate は source gate より後に評価される順序にする。
4. Population Results に parent-child 関係が分かる表示を追加する。最低限、population id と parent id が分かるようにする。

### 受け入れ条件

- GUI で child gate を作成し、parent population によって event_count が制限される。
- GUI で `gate A AND gate B` の boolean gate を作成できる。
- 作成された hierarchy / boolean gate は headless `PipelineRunner` で同じ結果になる。
- invalid parent/source/cycle を作れない、または pipeline 実行前に明確な error になる。

## 追加で残すべき既知リスク

### P2: 複数サンプル pipeline 実行時の channel_names が 1 つだけ

`MainWindow._worker` には `self._channel_names` だけが渡される。複数 sample で channel 構成が違う場合、選択中 sample の channel_names で全 sample を処理して silent wrong result になる可能性がある。最小修正は GUI で channel_names が全 sample 同一か検証し、違う場合は pipeline 実行を拒否すること。

### P2: GUI-created project manifest の永続化・再現性

`MainWindow._build_project_manifest()` は GUI 内の一時 dict であり、`.flowdesk` project として保存・再読込する UI がない。gate/sample/transform を project storage schema と揃え、保存 project を CLI/headless runner で再実行できるようにする。

## 推奨作業順

1. P0-1 gate edit 後の stale result / rerun 動線。
2. P0-2 sample remove。
3. P0-3 duplicate FCS skip と unique sample id。
4. P1-5 X/Y axis selection persistence。
5. P1-6 manual axis range persistence。
6. P1-7 Population Results export。
7. P1-4 gate creation preview。
8. P2-8 hierarchy / boolean gate GUI。

## 実行コマンド

```bash
.direnv/python-3.12.13/bin/pytest -q
.direnv/python-3.12.13/bin/ruff check src tests
.direnv/python-3.12.13/bin/python -c "import PySide6, pyqtgraph, numpy, flowio; print('gui/io deps ok')"
```

GUI の手動確認:

```bash
flowdesk-gui --data-dir data/
```
