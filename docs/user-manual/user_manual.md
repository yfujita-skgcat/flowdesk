# Flowdesk ユーザーマニュアル

**対象実装:** `rep(10).zip` に含まれる Flowdesk GUI  
**確認日:** 2026-07-23  
**対象バージョン表示:** Flowdesk 0.1.0  
**対象アーカイブ SHA-256:** `f40e76d38c04a75ae6634f705eb2d35c1bc98b951adc41d8b617e76b4def8918`

> [!IMPORTANT]
> この文書はスクリーンショットだけでなく、`src/flowdesk_qt/` の実装、メニュー接続、ダイアログ、右クリックメニュー、GUI テストを基準に作成している。Flowdesk はまだ early-stage であり、画面に存在する項目の一部は機能が限定的、または保存済み定義がないと実行できない。

**UI 網羅性検査:** 静的検査では、literal `objectName` 325件と、action・button・checkbox・menu・tab・combo-box item の一意な表示文字列172件について、マニュアル内の記載漏れは0件だった。詳細は [coverage_report.md](coverage_report.md) を参照。動的生成 control と標準 Qt dialog button は、19.2節で別途確認している。

## 目次

1. [Flowdesk の基本概念](#1-flowdesk-の基本概念)
2. [起動方法](#2-起動方法)
3. [基本的な解析手順](#3-基本的な解析手順)
4. [メイン画面](#4-メイン画面)
5. [メニューバー](#5-メニューバー)
6. [メインツールバー](#6-メインツールバー)
7. [Samples ペイン](#7-samples-ペイン)
8. [Plot Parameters](#8-plot-parameters)
9. [プロットツールバーとプロット操作](#9-プロットツールバーとプロット操作)
10. [Gating タブ](#10-gating-タブ)
11. [Results タブ](#11-results-タブ)
12. [Channels タブ](#12-channels-タブ)
13. [ステータスバー](#13-ステータスバー)
14. [各ダイアログ](#14-各ダイアログ)
15. [保存とエクスポート](#15-保存とエクスポート)
16. [キーボードショートカット](#16-キーボードショートカット)
17. [よくある操作と注意点](#17-よくある操作と注意点)
18. [現行実装上の制限](#18-現行実装上の制限)
19. [UI 網羅性一覧](#19-ui-網羅性一覧)

---

## 1. Flowdesk の基本概念

Flowdesk では、次の三つの選択状態を区別する必要がある。

|状態|意味|選択する場所|影響|
|---|---|---|---|
|Active sample|現在表示・編集対象としているサンプル|Samples リスト|プロット、チャンネル情報、プレビュー対象|
|Display population|プロットに表示する population|Results ワークスペース|表示イベントの絞り込み|
|Selected gate|定義を編集・表示するゲート|Gate hierarchy|ゲート編集、親変更、色、geometry 編集|

これらは独立した状態である。例えば、Results で子 population を表示しながら、Gate hierarchy では別の gate を選択できる。

### 1.1 表示と科学計算の区別

`Display max points` による点数制限、色、背景、凡例、フォント、軸ラベル、オーバーレイは**表示専用**である。ゲート membership、イベント数、frequency、統計、TSV/CSV 出力は全イベントを使う。

### 1.2 Results の鮮度

Gate、compensation、derived parameter、analysis transform、statistic definition などを変更すると Results は `stale` になる。`Run Pipeline` または Results の `Auto` による再計算が完了するまで、古い結果を最新値として扱わない。

---

## 2. 起動方法

GUI 依存関係を含めてインストールする。

```bash
python -m pip install -e '.[io,gui,dev]'
```

空の状態で起動する。

```bash
python -m flowdesk_qt
```

起動時にディレクトリ内の FCS を読み込む。

```bash
python -m flowdesk_qt --data-dir data/
```

---

## 3. 基本的な解析手順

1. **File → Open Directory...**、**File → Open Files...**、または **Add FCS Files...** で FCS を読み込む。
2. Samples リストで active sample を選ぶ。
3. `X axis`、`Y axis`、必要なら analysis transform を選ぶ。
4. Gating タブで gate type と parent population を選び、`Create Gate` を実行する。
5. 子 gate は parent を選ぶか、対象 gate を選択して `Create Child Gate` を使う。
6. Results → `Add Statistic...` または `Manage Statistics...` で統計定義を作る。
7. **Run Pipeline** を実行する。
8. Results タブで event count、frequency、統計値、status を確認する。
9. **Export Results...**、またはプロットの PNG/SVG/PDF export を行う。
10. **Save Project...** で `.flowdesk` directory bundle として保存する。

### 3.1 CLIでResultsを出力する

保存済みprojectはGUIと同じcore pipeline・export writerを使って実行できる。

```bash
flowdesk run project.flowdesk --output results.tsv
flowdesk run project.flowdesk --output results.tsv --layout long --include-qc
```

`--include-internal-ids` はstable sample/population IDとhierarchy metadataを追加する。
`--statistics-output` は互換用のdeprecated statistic-only exportであり、新規用途では
統合された `--output` を使用する。

---

## 4. メイン画面

![Flowdesk main window](assets/main-window.png)

画面は左から Samples、中央の Plot、右の Gating/Results/Channels に分かれる。境界は splitter でドラッグして幅を変更できる。

|領域|役割|
|---|---|
|メニューバー|プロジェクト、解析定義、結果、表示設定への入口|
|Main Toolbar|頻用する読み込み、pipeline、結果 export|
|Samples|FCS 管理、active sample、manual overlay、comparison relation|
|Plot Parameters|X/Y parameter、analysis transform、表示点数|
|Plot Toolbar|viewport、画像 export、statistic、interaction mode、marginal histogram|
|Plot area|scatter/histogram、gate overlay、右クリック表示設定|
|Gating|gate 作成・階層・親・geometry・色|
|Results|population/statistic 結果、表示 population、sample navigation|
|Channels|parameter catalog と FCS channel metadata|
|Status bar|処理状態と compensation 状態|

ウィンドウ幅が不足すると、plot toolbar の右端に `»` が表示され、収まらない項目が overflow menu に入る。

---

## 5. メニューバー

### 5.1 File

|項目|ショートカット|説明|
|---|---:|---|
|Open Directory...|Ctrl+O|選択したディレクトリ直下の `*.fcs` を読み込む。サブディレクトリは再帰検索しない。|
|Open Files...|Ctrl+Shift+O|複数の FCS ファイルを個別選択して読み込む。|
|Open Project...|—|既存 `.flowdesk` directory bundle を開く。より新しい recovery copy がある場合は、別コピーとして復元するか確認される。|
|Save Project...|Ctrl+S|現在の解析定義、サンプル参照、表示設定を `.flowdesk` directory bundle として保存する。選択したパスに `.flowdesk` suffix がなければ付加される。|
|Exit|Ctrl+Q|Flowdesk を終了する。|

`Open Samples` toolbar button は名称とは異なり、現行実装では **Open Directory...** と同じ処理を呼ぶ。

### 5.2 Edit

|項目|ショートカット|説明|
|---|---:|---|
|Undo Gate Change|Ctrl+Z|直前の gate 作成、削除、rename、reparent、geometry 変更などを元に戻す。|
|Redo Gate Change|Ctrl+Shift+Z|取り消した gate change をやり直す。|
|Create Sample Gate Override...|—|選択中の sample と gate に対し、監査情報付き sample-specific geometry override を作る。通常の比較では shared group geometry を優先する。|
|Undo Overlay Source Change|—|Advanced Overlay Sources または Plot Presentation の変更を戻す。|
|Redo Overlay Source Change|—|取り消した overlay/presentation change をやり直す。|

Undo/Redo は操作可能な履歴がないと disabled になる。Gate history と overlay/presentation history は別スタックである。

### 5.3 Analysis

|項目|ショートカット|説明|
|---|---:|---|
|Run Pipeline|Ctrl+R|読み込まれた全 sample を GUI-independent pipeline で再計算する。実行中は二重実行できない。|
|Derived Parameters...|—|式から derived parameter を定義、validate、preview する。|
|Compensation...|—|compensation matrix と binding を定義・検証する。|
|Compensation Calculations...|—|single-color control 等から matrix calculation を定義・実行し、matrix として保存する。|
|Manage Parameter Transforms...|—|parameter ごとの formal analysis transform を定義する。|
|Use Multiple Analysis Groups|checkable|advanced Group panel を表示する。通常の treatment/control 比較は同じ Group、異なる panel/control/QC のみ分離する設計。|
|Clear Gates|Ctrl+G|全 gate を消去し、plot の gate creation 状態も解除する。|

`Use Multiple Analysis Groups` をオフにしても、保存済み Group 定義は削除・merge されず、panel が隠れるだけである。

### 5.4 Results

|項目|説明|
|---|---|
|Add Statistic...|新しい persisted statistic definition を作成する。初期 population は All Events。|
|Manage Statistics...|既存 statistics の Compute/Show と適用 population をまとめて管理する。|
|Export Results...|最新かつ non-stale な population metrics と custom statistics を wide/long TSV/CSV に書き出す。|
|Batch Plot Export...|保存済み `BatchPlotExportSpec` を使って batch export する。project の保存と定義済み spec が必要。|

### 5.5 Data

|項目|説明|
|---|---|
|Sample Sheet...|sample title と workspace annotation を表形式で編集する。stable sample ID、file path、元の sample name は変更しない。|
|Channel / Parameter Information|read-only parameter information workspace に focus を移す。情報は Channels タブにある。現行コードでは明示的な tab index 切替ではなく focus request である。|

### 5.6 Plot

|項目|説明|
|---|---|
|Overlay Samples|Samples ペインの `Ov` column を使うよう focus と status message で案内する。|
|Advanced Overlay Sources...|sample/population/parameter/transform 単位の persisted overlay source を編集する。現行アーカイブでは有効。|
|Plot Presentation...|title、axis label、legend、source style、font など表示専用設定を編集する。|

### 5.7 Help

|項目|説明|
|---|---|
|About Flowdesk|アプリ名、概要、version 0.1.0 を表示する。|

---

## 6. メインツールバー

|ボタン|説明|
|---|---|
|Open Samples|ディレクトリを選び、直下の FCS を読み込む。個別ファイル選択は File → Open Files... または Add FCS Files... を使う。|
|Run Pipeline|Analysis → Run Pipeline と同じ。|
|Export Results|Results → Export Results... と同じ。population metrics と custom statistics を統合して出力する。|

---

## 7. Samples ペイン

### 7.1 上部 controls

|control|選択肢・操作|説明|
|---|---|---|
|Filter samples…|文字入力|sample name、path、status に対する case-insensitive filter。表示だけを絞り、project から削除しない。|
|Sort|Name / Path / Status|sample list の並び順を変更する。active sample は stable ID で維持される。|
|Overlay mode|Manual only / Manual + comparison set|manual `Ov` のみ、または manual と comparison set の両方を overlay source とする。コードには `comparison_only` の復元対応もあるが、GUI combo には表示されない。|

### 7.2 sample row

|列|control|説明|
|---|---|---|
|Ov|checkbox|その sample を manual overlay として追加・削除する。active sample 自身は overlay にできず disabled。|
|Col|color button|overlay color を QColorDialog で選ぶ。active sample の base layer 色には使わない。|
|Name|sample row selection|クリックすると active sample になる。先頭記号は channel/file status。|
|Rel|表示ラベル|`active`、manual、reference、positive_control 等の relation/status。ラベル自体はクリック操作を持たない。|

status 記号は概ね `✓`=channel match、`↕`=order differs、`≠`=channel mismatch、`!`=fingerprint mismatch、`?`=missing である。tooltip には display title、元の name、path、event count、status が表示される。

### 7.3 Samples list の右クリックメニュー

複数選択は Ctrl/Shift を使う。

|項目|表示条件|説明|
|---|---|---|
|Pair Selected Samples...|2 sample 以上選択|選択 sample から comparison set を作る。最初を reference、残りを target とする。|
|Create Comparison Set...|2 sample 以上選択|現行実装では Pair Selected Samples... と同じ comparison set creation を実行する。|
|Add to Comparison Set...|2 sample 以上選択|最新の comparison set に target として追加する。set がなければ新規作成する。|
|Edit Comparison Relation...|comparison set が存在|現行コードでは専用 editor を開かず、overlay state の再通知だけを行う。実質的に未完成の入口。|
|Remove from Comparison Set|comparison set が存在|対象 sample を comparison set から外す。member が 2 未満になった set は削除される。|
|Use as Persistent Overlay|常時|対象 sample の manual overlay をオンにする。|
|Set Overlay Role → Positive control|常時|overlay role を `positive_control` にする。|
|Set Overlay Role → Negative control|常時|overlay role を `negative_control` にする。|
|Set Overlay Role → Reference|常時|overlay role を `reference` にする。|
|Clear Overlay Role|常時|明示 role を削除する。|

### 7.4 下部 buttons

|ボタン|説明|
|---|---|
|Add FCS Files...|複数 FCS を個別選択して追加する。無効な FCS しか選ばれなかった場合は warning。|
|Remove Selected|現在の active/current row を project session から外す。ディスク上の FCS は削除しない。次の sample が自動選択される。|
|Reconnect…|missing または移動した sample を新しい FCS path に接続する。stored fingerprint と異なる場合は、identity replacement を明示確認する。|

---

## 8. Plot Parameters

|control|選択肢|説明|
|---|---|---|
|X axis|acquired/available derived parameter|横軸 parameter。invalid derived definition は一覧に見えても disabled になる場合がある。|
|Y axis|parameter / Count|通常は縦軸 parameter。`Count` を選ぶと 1D histogram mode になる。|
|X transform|Linear / Log10 / Asinh / Logicle / Custom…|X parameter に formal analysis transform を作成または選択する。|
|Y transform|Linear / Log10 / Asinh / Logicle / Custom…|Y parameter に formal analysis transform を作成または選択する。Count mode では意味を持たない。|
|Display max points|0–10,000,000、step 5,000|scatter の layer ごとに描画する最大点数。`0 (all events)` は全有限 event を描画。解析結果は常に全 event。|

### 8.1 transform selector の挙動

`Linear` は当該 parameter の置換可能な transform を外す。`Log10`、`Asinh`、`Logicle` は既定 settings で新しい persisted transform definition を作る。`Custom…` は Analysis Transforms dialog を開く。

既存 transform が gate 等から参照されている場合、quick selector から in-place replacement は拒否される。新しい transform ID を作り、gate の `Migrate Transform` を使う。

---

## 9. プロットツールバーとプロット操作

### 9.1 toolbar controls

|control|種類|説明|
|---|---|---|
|Reset Robust Range|button|表示範囲を各軸 0.5–99.5 percentile の robust range に戻す。|
|Reset Full Range|button|有限値の full data range に戻す。outlier も含む。|
|Export 1:1|toggle|PNG/SVG/PDF export 時だけ X/Y の表示 unit を等しくする。通常画面の aspect を固定するものではない。|
|Export PNG|button|現在の plot view を PNG と sidecar metadata に export。|
|Export SVG|button|current plot を SVG vector export。|
|Export PDF|button|current plot を PDF vector export。|
|Add Statistic|button|current graph context から statistic editor を開き、X parameter を初期値にする。|
|Pan|exclusive toggle|通常の pyqtgraph navigation mode。plot 右クリック menu は Pan かつ gate creation 中でない時だけ開く。|
|Select|exclusive toggle|interaction state を `select` にする。現行コードには独自の region/event selection 処理は実装されていない。|
|Gate|exclusive toggle|interaction state を `gate` にする。これだけでは gate creation は開始せず、Gating tab の Create Gate を使う。|
|Marginals|toggle|2D scatter の X/Y marginal histogram を表示する。1D Count histogram では利用不可。|

### 9.2 plot mouse operation

|操作|挙動|
|---|---|
|通常の drag / wheel|Pan mode では pyqtgraph の通常 navigation に委譲される。|
|Ctrl + left drag|旧 right-drag 相当の continuous range zoom。button-down point を中心に scale する。box zoom ではない。|
|rectangle gate creation 中の left drag|rectangle preview を表示し、release で gate を作成する。|
|polygon gate creation 中の left click|vertex を追加する。|
|polygon gate creation 中の double click|polygon を確定する。|
|gate overlay drag|editable geometry を移動・変更し、短い debounce 後に結果を stale/preview 更新する。|

### 9.3 plot area の右クリックメニュー

右クリック menu は Pan mode で gate creation 中でない場合のみ表示される。

|項目|説明|
|---|---|
|Plot Appearance...|Plot Presentation dialog を開く。|
|View Range → Set numeric range...|X minimum、X maximum、Y minimum、Y maximum を数値入力する。min は max より小さい必要がある。|
|Axis Ticks → Auto (recommended)|transform と range に応じる推奨 tick policy。|
|Axis Ticks → Decades only|主に log-like axis で decade label を優先。|
|Axis Ticks → 1–2–5 labels|1–2–5 系列の label policy。|
|Axis Ticks → Legacy automatic|従来の automatic tick behavior。|
|Legend → Show Legend|現行 handler では直接 toggle せず Plot Presentation dialog を開く。|
|Legend → Position → Right/Left/Top/Bottom/Inside|現行 handler では直接位置変更せず Plot Presentation dialog を開く。|
|Reset View Appearance|current view の presentation mapping を空に戻し、default 解決に戻す。analysis は再実行しない。|

### 9.4 plot banner

plot 上部の黄系 banner は、sample gate override status、results stale reason、membership freshness などを表示する。banner は警告表示であり、イベントそのものではない。

---

## 10. Gating タブ

### 10.1 gate creation controls

|control|選択肢・説明|
|---|---|
|Gate type|`rectangle`、`range`、`polygon`、`ellipse`、`boolean`|
|Parent population|All Events または既存 gate population。新しい gate の評価対象。|
|creation context label|parent、sample、current axes、scale/transform IDs を表示する。|
|Create Gate|選択 gate type で新規作成。rectangle/polygon は plot interaction、range/ellipse/boolean は dialog。|
|Create Child Gate|選択 gate を parent とする child-gate mode に入り、その後 Create Gate と同様の作成へ進む。|
|Delete Selected|選択 gate を削除する。child gate や Boolean source から参照される gate は削除拒否。|

### 10.2 Gate hierarchy

|column|意味|
|---|---|
|Gate definition|表示名。gate 行は inline rename 可能。tooltip に stable ID、parent、expression 等。|
|Type|rectangle、range、polygon、ellipse、boolean。root は `root`。|
|Axes / Scale|X/Y parameter と gate coordinate scale。|
|Expression|Boolean gate の AND/OR/NOT source summary。|
|Color|population display color swatch。|

`All Events` は root で削除・geometry edit できない。Gate hierarchy の選択は selected gate を変更するが、display population を自動的に同じものへ変えるとは限らない。

### 10.3 selected gate detail controls

|control|説明|
|---|---|
|Show Gate|selected gate の geometry が見えるよう plot parameter/range を合わせる。|
|Show Population|selected gate population を display population として表示する。fresh membership が必要な場合がある。|
|Migrate Transform|selected geometric gate を新しい analysis transform coordinate に移す preview を開く。compensation/derived parameter がある project では canonical preview 未対応として停止する場合がある。|
|selected parent combo|selected gate の新しい parent candidate。|
|Apply Parent|reparent の妥当性と dependent を確認後、parent を変更する。cycle 等は拒否。|
|Edit Boolean|Boolean gate の operation、source population、optional nested expression JSON を編集する。|
|Edit Geometry|rectangle/range/polygon/ellipse の数値 geometry を編集する。|
|status label|Ready、drag instruction、polygon instruction、hidden reason 等。|

画面幅が小さいと detail row のボタンが圧縮される。右ペインを広げると全文を確認しやすい。

### 10.4 Gate hierarchy 右クリック menu

|項目|説明|
|---|---|
|Population Color...|population 内 event の display color を選ぶ。|
|Gate Outline Color...|gate outline 専用色を選ぶ。|
|Use Population Color for Outline|outline 色を population color と連動させる toggle。|
|Reset Population Color|population color、outline color、連動指定を reset。|

色変更は表示専用であり、membership、counts、statistics を変えない。

---

## 11. Results タブ

### 11.1 navigation bar

|control|説明|
|---|---|
|breadcrumb|`sample title / All Events / parent / child` の現在位置を表示する。|
|Parent|現在の display population の親へ移動する。root では disabled。|
|Previous Sample|sample list の前の sample に移動し、可能なら同じ population を表示する。|
|Next Sample|sample list の次の sample に移動し、可能なら同じ population を表示する。|

### 11.2 Results controls

|control|種類|説明|
|---|---|---|
|Auto|checkbox|analysis definition change 後、300 ms coalescing を経て canonical full-sample pipeline を自動再実行する。|
|view mode|combo|Hierarchy / Flat table / Statistics detail。|
|Add Statistic...|button|選択 population を初期 target として statistic editor を開く。statistic row 選択時は対応 population を推定する。|
|Manage Statistics...|button|Compute、Show、Applies to を compact table で管理する。|
|Columns...|instant popup|dynamic statistic columns の表示/非表示。analysis の Compute flag は変えない。statistics がない時は disabled。|

### 11.3 Results view modes

#### Hierarchy

sample の下に All Events と gate hierarchy を展開する。selection により active sample と display population が変わる。

#### Flat table

sample/population を階層化せず row として表示する。列は基本的に次のとおり。

|列|意味|
|---|---|
|Sample / Population|sample または population name|
|Events|population event count|
|% Parent|parent population に対する割合|
|% Total|All Events に対する割合|
|dynamic statistic columns|Show が有効な statistic 値|
|Status|current、stale、recalculating、zero events、undefined、missing、not run、disabled、error 等|

#### Statistics detail

|列|意味|
|---|---|
|Sample|sample display name|
|Population|statistic target population|
|Statistic|statistic display name|
|Value|format 済み値、未定義は `-`|
|Unit|unit|
|Status|ok/current/undefined/stale 等|
|n valid|有限・有効イベント数|
|n total|対象総イベント数|
|Reason|undefined reason|
|Revision|result revision|

status text は色分けされるが、値自体の意味を色で変更しない。tooltip には source、revision、freshness、n_invalid、invalid_fraction、non-finite policy 等が表示される。

### 11.4 Pipeline Diagnostics

|列|説明|
|---|---|
|Severity|error、warning、info 等|
|Code|diagnostic code|
|Stage|pipeline stage|
|Sample|対象 sample ID|
|Message|詳細 message|

status label は diagnostic 件数と report status、または `Diagnostics stale; rerun pipeline` / `No diagnostics` を表示する。

---

## 12. Channels タブ

### 12.1 parameter catalog table

|列|説明|
|---|---|
|Parameter|display label と stable parameter ID|
|Type|acquired / derived|
|Source|raw、compensated、transformed、definition ID|
|Expression|derived expression|
|Unit|unit|
|Status|available、invalid、missing dependency 等|

invalid definition の詳細は cell tooltip に出る。

### 12.2 FCS metadata table

上部に Sample、Channel status、File path が表示される。file path は mouse selection/copy 可能。

`Columns` popup の全 toggle は次のとおり。

|column toggle|内容|初期表示|
|---|---|---:|
|Stable ID|Flowdesk の channel stable ID|非表示|
|$PnN|FCS primary parameter name|表示|
|$PnS|FCS short/stain name|表示|
|Detector|detector metadata|表示|
|Stain|stain metadata|表示|
|Unit|unit|非表示|
|FCS index|parameter index|表示|
|Gain (PnG)|FCS `$PnG`|非表示|
|Exponent (PnE)|FCS `$PnE`|非表示|
|Range (PnR)|FCS `$PnR`|非表示|

FCS metadata table は read-only で sorting 可能である。

---

## 13. ステータスバー

左側には `Ready`、読み込み件数、pipeline running/completed、export path、interaction mode、axis tick policy などが表示される。

右側の compensation badge は次の状態を示す。

|表示|意味|
|---|---|
|🟢 Comp: matrix name|valid matrix が current sample に適用|
|🟡 Comp: ... cond=...|condition number が warning threshold 以上|
|🔴 Comp: none|適用 matrix なし|
|⚠️ Comp: message|invalid、unknown matrix、inspection failure|
|`(stale)` suffix|compensation を含む results が現在の definition に対して古い|

---

## 14. 各ダイアログ

### 14.1 Create Gate / Edit Gate Geometry

共通 control は `Gate name`、`OK`、`Cancel`。

#### rectangle

`X min`、`X max`、`Y min`、`Y max` を入力する。ただし通常の Create Gate は dialog ではなく plot drag で作る。Edit Geometry では数値入力を使う。

#### range

`Parameter min` と `Parameter max` を入力する。X parameter の 1D range gate。

#### polygon

`Vertices (data coordinates)` table に X/Y vertices が表示・編集される。新規作成時は OK 後に plot で vertex を置き、double click で終了する。

#### ellipse

`Center X`、`Center Y`、`Radius X`、`Radius Y`、`Rotation (radians)` を入力する。nonlinear scale の既存 ellipse は display coordinate と gate coordinate の変換を介して編集する。

#### boolean

|control|説明|
|---|---|
|Operation|and / or / not|
|Source populations|hierarchy tree から複数選択。NOT は最低 1 source、AND/OR は最低 2 source。|
|Nested expression JSON (optional)|複雑な nested Boolean expression を JSON で直接指定。例 `{"op":"and","children":[...]}`。|

### 14.2 Gate transform migration preview

source event count、candidate event count、gained、lost、scientific equivalence warning を表示する。選択肢は QMessageBox の `Duplicate`、`Migrate`、`Cancel`。Polygon の nonlinear transform migration は直線 edge の科学的同等性を保証しない近似である。

### 14.3 Create Sample Gate Override

|control|説明|
|---|---|
|impact label|override が選択 sample だけに適用され、group strategy を clone しないことと affected samples を表示。|
|Geometry mode|Full geometry / Typed delta|
|Coordinates JSON|coordinate array。例 `[[x1, y1], [x2, y2]]`。|
|Thresholds JSON|gate-specific thresholds object。|
|Author|required。|
|Reason (required)|override 理由。空欄不可。|
|Gate purpose|Technical cleanup / Comparison-critical|
|OK / Cancel|JSON と required fields を validate。OK 後にさらに confirmation がある。|

### 14.4 Derived Parameters

左に definition list と `New` / `Delete`、右に次の form がある。

|control|説明|
|---|---|
|Definition ID|definition の stable ID。|
|Name|display name。|
|Output channel ID|後続 transform/gate/statistic から参照する stable parameter ID。|
|Unit|optional unit。|
|Source stage|compensated / raw。既存 project に legacy `transformed` がある場合のみ表示。|
|Failure policy|emit_nan_with_warning / fail_sample / fail_run|
|Non-finite policy|`Strict (report invalid events)` / `Exclude invalid values explicitly`。前者は invalid event を報告し、後者は invalid value を明示的に除外する。|
|Expression|安全な式。placeholder は `signal / reference`。|
|Inputs|依存 parameter を複数選択。|
|Expression helper combo|acquired parameter と先行 derived output の候補。|
|Insert parameter|cursor 位置へ stable parameter ID を挿入。|
|Validate|syntax、dependency、cycle、output ID 等を core validator で検査。|
|Preview|current sample の最大 200 event 程度を canonical processing path で評価する診断 preview。|
|diagnostic label|validation code と message。|
|preview label|finite count、min/median/max、invalid fraction 等の summary。|
|OK / Cancel|全定義 validation 後に commit、または変更破棄。|

### 14.5 Compensation Matrices

#### Matrices list

`New`、`Duplicate`、`Delete` で matrix definition を管理する。

#### matrix form

|control|説明|
|---|---|
|Matrix ID|stable ID。|
|Name|display name。|
|Source|user_defined / fcs_metadata_spillover / imported / calculated|
|Notes|任意メモ。|
|Channels|matrix に含める fluorescence channel。multi-selection。|
|Add Channel|selected available channel を matrix に追加。|
|Remove Channel|matrix から channel を除く。|
|Matrix Heat Map Preview|row/column が channel の matrix table。係数を編集・確認する。|
|Validate|shape、finite values、diagonal、invertibility/condition 等を inspect。|
|diagnostic label|validity と condition number、または errors。|

#### Bindings list / Binding Editor

|control|説明|
|---|---|
|Bindings New / Delete|matrix binding を追加・削除。|
|Binding ID|stable binding ID。|
|Matrix|対象 matrix。|
|Scope|sample / group / execution_profile|
|Target ID|scope に対応する sample/group/profile ID。|
|Notes|任意メモ。|

#### Compensated / Uncompensated Preview

|control|説明|
|---|---|
|Sample combo|event data が GUI に読み込まれている sample。|
|Preview|current matrix を selected sample に適用する。|
|Preview table|Channel、Uncompensated、Compensated の代表 summary。|

`OK` は定義全体を validate して保存、`Cancel` は破棄する。

### 14.6 Compensation Calculations

|control|説明|
|---|---|
|Calculations list|calculation definition 一覧。|
|New / Delete|calculation を追加・削除。|
|Calculation ID|stable ID。|
|Name|display name。|
|Regression|linear / median|
|Outlier Policy|iqr / zscore / none|
|Min Positive Events|positive population の最低 event 数。default 100。|
|Min Negative Events|negative population の最低 event 数。default 50。|
|Notes|任意メモ。|
|Detector × Control Assignments|Detector Channel、Control Sample、Positive Population、Negative Population の表。各 cell は combo。|
|Add Control / Delete Control|assignment row を追加・削除。|
|Run Calculation|sample data と population membership から spillover calculation を実行。|
|Save Matrix|成功した calculation result を compensation matrix として保存。|
|Calculation Diagnostics|detector ごとの Pos/Neg Events、Median、Slope、Residual RMS、Outliers。|
|Condition number|calculated matrix の condition number。|
|diagnostic label|spec error、missing data、成功/失敗。|
|OK / Cancel|calculation definitions を保存または破棄。|

### 14.7 Analysis Transforms

左に transform list と `New` / `Delete`、右に次の項目がある。

|control|説明|
|---|---|
|Transform ID|versioned stable ID。gate 等が参照する。|
|Name|display name。|
|Parameter|対象 acquired/derived parameter。invalid derived は disabled。|
|Type|linear / log / asinh / logicle。legacy project にだけ legacy_logicle_approximation。|
|scale, offset|linear settings。|
|base, invalid_value_policy|log settings。policy は to_nan / to_zero / clip_to_one。|
|cofactor|asinh setting。|
|T, W, M, A, implementation_version|published logicle settings。implementation_version は read-only。|
|w, td, tn|legacy logicle approximation settings。該当 type のみ。|
|Preview|current sample から最大 200 finite values を使い inverse round-trip error を表示。|
|OK / Cancel|valid definitions を保存、または破棄。使用中 transform の変更・削除は main window 側で拒否される。|

### 14.8 Population Statistics editor

#### definition list buttons

|button|説明|
|---|---|
|New|pending defaults を使って新規 statistic を作る。|
|Delete|選択 definition を削除。downstream reference がある場合は保護される。|
|Duplicate|選択 definition を新 ID 用に複製。|
|Clear All|全 definition を削除。|
|Undo / Redo|dialog 内の statistic definition edits を取り消し/やり直し。gate undo とは別。|

#### statistic form

|control|説明|
|---|---|
|Statistic ID|stable definition ID。|
|Name|Results column/detail に表示する名称。|
|Population targets|base population、scope、Targets... の組み合わせ。|
|scope: Current population|base population のみ。|
|scope: Current population and descendants|base と全 descendants。|
|scope: Selected populations...|Targets... tree で明示選択。|
|scope: All current populations|現在存在する全 population。|
|Parameter|value metric の parameter。count/frequency では `(none)` 可。|
|Metric|count / frequency_of_parent / frequency_of_total / mean / median / geometric_mean / stddev / cv / mad / percentile|
|Source Stage|raw / compensated / transformed|
|Transform|`(native value space)`、または persisted transform ID。|
|Non-finite policy|`Strict (undefined on any NaN/Inf)` / `Exclude invalid values (explicit)`。前者は NaN/Inf が一つでもあれば未定義とし、後者は invalid value を明示的に除外する。|
|Percentile q|metric が percentile の時だけ使用。|
|Format|display/export formatting hint。|
|Notes|任意メモ。|
|Compute enabled|pipeline で計算するか。オフは definition を残して計算停止。|
|diagnostic label|missing target、invalid parameter/metric setting 等。|
|OK / Cancel|全 definition を validate して保存、または破棄。|

### 14.9 Select statistic populations

population hierarchy の各 row に checkbox があり、statistic target を stable ID で複数選択する。`OK` で確定、`Cancel` で変更しない。

### 14.10 Manage Statistics

|列・control|説明|
|---|---|
|Compute checkbox|analysis pipeline で計算するか。変更すると Results stale。|
|Show checkbox|Results dynamic column を表示するか。表示専用で再計算不要。|
|Statistic|name。|
|Parameter|parameter label。|
|Metric|metric。|
|Value domain|transform ID または source stage。|
|Applies to|target population 一覧。double click または Edit Applies to... で変更。|
|Edit Applies to...|選択 row の target chooser を開く。|
|OK / Cancel|Compute/Show/targets を commit、または破棄。|

### 14.11 Sample Sheet

|control|説明|
|---|---|
|Filter samples...|全 column を対象に case-insensitive filter。|
|table|Sample ID、File、Sample name、Title、annotation columns。sorting 可能。|
|Sample ID|read-only stable identity。|
|File|read-only path。|
|Sample name|read-only FCS/source name。|
|Title|editable display title。|
|FCS-derived annotation cell|read-only。workspace column を追加して override する設計。|
|Add Annotation Column…|新しい editable workspace annotation column を追加。|
|Paste|clipboard の TSV を貼り付け。基本形式は sample ID + title。未知/重複 ID は全体を拒否し partial overwrite しない。|
|Import CSV…|annotation CSV を validate して merge。未知 sample ID は拒否。|
|Fill Titles…|prefix を入力し、全 sample に `prefix1`, `prefix2`... を設定。|
|Find/Replace…|workspace/editable annotation の文字列を一括置換。FCS-derived 値は変更しない。|
|Undo / Redo|Sample Sheet dialog 内の title/annotation edits。|
|OK / Cancel|annotations を保存、または破棄。|

### 14.12 Multiple Analysis Groups panel

Analysis → Use Multiple Analysis Groups をオンにすると Gating tab 下部に表示される。

|control|説明|
|---|---|
|sample list|sample IDs の drag source。|
|group list|group name、role、explicit member count、dynamic rule の有無。sample を drop すると membership 追加。|
|Add|role (`user`, `compensation_controls`, `panel`, `acquisition`, `qc`) と name を入力して group を作る。|
|Rename|selected group の display name を変更。|
|Delete|selected group を削除。ただし `all-samples` は削除しない。|

現行 panel には group から individual sample を除く専用 UI がない。

### 14.13 Advanced Overlay Sources

左側に source list と `Add`、`Remove`、`Up`、`Down` があり、右側に source detail がある。

|control|説明|
|---|---|
|Sample|source sample。|
|Population ID/path|source population。|
|X parameter|source X parameter。必須。|
|Y parameter|source Y parameter。`(none)` 可。|
|X transform / Y transform|persisted transform または `(none)`。|
|Legend label|legend text。|
|Color|`#RRGGBB`。|
|Alpha|0.0–1.0。|
|Visible|source を描画するか。|
|Compatibility|compatible/missing/incompatible と詳細。visible source が compatible でないと OK を拒否。|
|Add|最初の sample/channel から default source を作る。|
|Remove|source 削除。|
|Up / Down|描画・凡例 order を変更。|
|OK / Cancel|source list を保存、または破棄。|

### 14.14 Plot Presentation

#### General tab

|control|説明|
|---|---|
|Title|plot title。current sample title と連動する場合がある。|
|Subtitle/annotation|subtitle。|
|X axis display label / Y axis display label|parameter ID を変えず、表示 label だけ変更。|
|Show legend|legend visibility。|
|Legend position|right / left / top / bottom / inside|
|Legend order list|source order。Up/Down で変更。|
|Plot background|`#RRGGBB`。|
|Gate outline color|default gate outline color。individual population setting が優先する場合がある。|
|Gate outline width|0.1–100。|
|Gate outline style|solid / dashed / dotted / dashdot。|
|Axis line width|0.5–20。|
|Colormap|例 `viridis`。plot type に非対応なら disabled/validation error。|

#### Sources tab

|control|説明|
|---|---|
|Source|style 対象 source。|
|Provenance|automatic / manual override / resolved default の由来。|
|Marker shape|Automatic / Circle / Square / Triangle / Cross / Plus|
|Marker size|scatter marker size。|
|Source color|event/marker color。|
|Source alpha|0–1。|
|Line color / width / style|line plot 対応 style。|
|Histogram fill / outline / alpha|histogram 対応 style。|
|Reset source to automatic|manual_fields を消し automatic policy に戻す。|
|Project default|project default style に解決。|
|Global default|global default style に解決。|

非対応 style field は tooltip で `Unsupported for ...` と示される。

#### Fonts tab

Title font、Axis label font、Tick font、Legend font のそれぞれに `family`、`size`、`weight` (`normal`, `bold`, `light`) がある。

下部 status は valid、unsupported/invalid の詳細を示す。`OK` は validation 成功時だけ受理する。

### 14.15 Set View Range

`X minimum`、`X maximum`、`Y minimum`、`Y maximum` の double spin box と、各軸の expected input coordinate hint、`OK` / `Cancel` がある。minimum ≥ maximum は拒否される。

### 14.16 Sample Annotations（内部・未接続）

`AnnotationEditorDialog` は sample ID × keyword table と `OK` / `Cancel` を持つが、現行 main menu から呼ぶ action は接続されていない。通常は Sample Sheet を使う。

### 14.17 非表示の互換 view

`PopulationTree` と `WorkspaceTree` は transitional adapter として生成されるが、main window では `setVisible(False)` で非表示である。ユーザーが操作する current Results UI は `ResultsWorkspace` である。

---

## 15. 保存とエクスポート

### 15.1 project save

`.flowdesk` は単一ファイルではなく directory bundle である。保存対象には sample reference、fingerprint、gates、compensation、derived parameters、transforms、statistics、groups、annotations、overlays、plot presentation などが含まれる。raw event array 自体を project に埋め込む前提ではないため、FCS 移動後は Reconnect が必要になる。

### 15.2 Population Results / Statistics

Results → **Export Results...** を選び、Wide table または Long detail table、
population metrics、custom statistics、internal ID、QC/status metadata を選択する。
population metrics と custom statistics の少なくとも一方を選ぶ必要がある。
TSV または CSV を選び、Results がない、または stale の場合は export できない。

Wide形式は1行を Sample × Population とし、Populationは `All Events/Live/GFP+`
のようなgate階層full pathで出力する。内部の安定識別子はPopulation pathではなく
`Population ID`であり、`Include internal IDs and hierarchy metadata`で追加できる。
% Parent と % Total は百分率として出力され、rootの% Parentは空欄、rootの% Totalは
100になる。欠損値は空欄で、数値0とは区別される。

Long形式はpopulation metricsとcustom statisticsを同じ表に出力し、`Result Type`
で `population` と `statistic` を区別する。status、undefined reason、statisticの
QC情報も保持する。

gate名にはASCII `/`を使用できない。これは `/`をpopulation full pathの区切り文字として
予約しているためである。全角の`／`は禁止対象ではない。gate名変更時も内部の
Population IDは変わらない。

### 15.3 Plot PNG/SVG/PDF

current view、presentation、visible overlays、population colors、display sampling definition 等を使って export する。`Export 1:1` は export-only aspect option。visible advanced overlay が incompatible なら export は拒否される。

### 15.4 Batch Plot Export

現行 GUI には `BatchPlotExportSpec` を新規作成する editor がない。保存済み project に spec があり、project が先に保存されている場合に、最初の spec を指定 output directory へ実行する。

---

## 16. キーボードショートカット

|shortcut|action|
|---|---|
|Ctrl+O|Open Directory...|
|Ctrl+Shift+O|Open Files...|
|Ctrl+S|Save Project...|
|Ctrl+Z|Undo Gate Change|
|Ctrl+Shift+Z|Redo Gate Change|
|Ctrl+R|Run Pipeline|
|Ctrl+G|Clear Gates|
|Ctrl+Q|Exit|

OS/Qt 環境によって標準 key sequence の表示が異なる場合がある。

---

## 17. よくある操作と注意点

### 17.1 plot に一部の点しか見えない

`Display max points` が 20,000 などに設定されている。表示 sampling だけであり、gate/statistics は全 event を使う。rare population を visually 確認したい時は上限を増やすか 0 にする。

### 17.2 Results が赤い stale のまま

Gate、transform、compensation、statistic 等を変更した後である。Run Pipeline を実行するか Results の Auto をオンにする。実行中、最新 revision 以外の preview/result は採用されない。

### 17.3 gate を削除できない

child gate の parent、または Boolean gate source として参照されている。先に dependent gate の parent/source を変更または削除する。

### 17.4 active sample の Ov checkbox が押せない

active sample は base layer なので、自分自身を overlay source として二重描画しない仕様。別 sample を active にするか、別 sample の Ov を選ぶ。

### 17.5 transformed axis と gate の再現性

formal analysis transform を使う gate は transform ID を保存する。使用中 transform を直接書き換えず、新 ID を作成して Migrate Transform を使う。

### 17.6 Channels menu を選んでも tab が切り替わらない

現行 `Channel / Parameter Information` action は widget に focus request を送るだけで、tab index を明示変更するコードがない。Channels tab を手動で選択する。

---

## 18. 現行実装上の制限

|項目|現状|
|---|---|
|製品成熟度|README で early-stage、production GUI behavior は non-goal/未完とされている。|
|Select interaction mode|独自 event/region selection 処理は未実装。|
|Gate interaction mode|toolbar toggle だけでは gate creation を開始しない。|
|Edit Comparison Relation...|専用 editor は未実装で、state 通知のみ。|
|Channel / Parameter Information action|明示 tab 切替なし。|
|Legend context submenu|直接変更ではなく Plot Presentation dialog を開く。|
|Group membership removal|Group panel に個別 removal UI がない。|
|Batch export definition editor|GUI にはない。保存済み spec が必要。|
|AnnotationEditorDialog|main menu に未接続。Sample Sheet が current UI。|
|gate migration canonical preview|compensation/derived parameter を含む場合は安全のため停止する。|
|large-file rendering / FlowJo compatibility|完全対応ではない。|
|統合Results exportのCLI|`flowdesk run --output`、`--layout`、internal ID、QC optionを提供する。旧`--statistics-output`は互換用deprecated option。|

---

## 19. UI 網羅性一覧

以下は source code の `setObjectName(...)` を基準にした control inventory である。動的 ID は pattern で示す。この一覧により、main window、dialog、context menu、非表示 compatibility widget を追跡できる。


### 19.1 objectName inventory

|module|objectName / pattern|
|---|---|
|`annotation_editor.py`|`annotationEditorDialog`|
|`annotation_editor.py`|`annotationTable`|
|`annotation_editor.py`|`annotationDialogButtons`|
|`channel_metadata.py`|`channelMetadataWorkspace`|
|`channel_metadata.py`|`channelMetadataSampleLabel`|
|`channel_metadata.py`|`channelMetadataStatusLabel`|
|`channel_metadata.py`|`channelMetadataFileLabel`|
|`channel_metadata.py`|`channelMetadataTable`|
|`channel_metadata.py`|`channelColumnButton`|
|`channel_metadata.py`|`f'channelColumn_{key}'`|
|`channel_metadata.py`|`parameterCatalogTable`|
|`channel_selector.py`|`channelSelector`|
|`channel_selector.py`|`xChannelCombo`|
|`channel_selector.py`|`yChannelCombo`|
|`channel_selector.py`|`xTransformCombo`|
|`channel_selector.py`|`yTransformCombo`|
|`channel_selector.py`|`xAnalysisTransformCombo`|
|`channel_selector.py`|`yAnalysisTransformCombo`|
|`channel_selector.py`|`displayMaxPointsSpinBox`|
|`compensation_editor.py`|`compensationMatrixEditorDialog`|
|`compensation_editor.py`|`compensationMatrixList`|
|`compensation_editor.py`|`compensationNewMatrixButton`|
|`compensation_editor.py`|`compensationDuplicateMatrixButton`|
|`compensation_editor.py`|`compensationDeleteMatrixButton`|
|`compensation_editor.py`|`compensationBindingList`|
|`compensation_editor.py`|`compensationNewBindingButton`|
|`compensation_editor.py`|`compensationDeleteBindingButton`|
|`compensation_editor.py`|`compensationMatrixIdEdit`|
|`compensation_editor.py`|`compensationMatrixNameEdit`|
|`compensation_editor.py`|`compensationSourceCombo`|
|`compensation_editor.py`|`compensationNotesEdit`|
|`compensation_editor.py`|`compensationChannelsList`|
|`compensation_editor.py`|`compensationAddChannelButton`|
|`compensation_editor.py`|`compensationRemoveChannelButton`|
|`compensation_editor.py`|`compensationHeatMap`|
|`compensation_editor.py`|`compensationValidateButton`|
|`compensation_editor.py`|`compensationDiagnosticLabel`|
|`compensation_editor.py`|`compensationDialogButtons`|
|`compensation_editor.py`|`compensationBindingIdEdit`|
|`compensation_editor.py`|`compensationBindingMatrixCombo`|
|`compensation_editor.py`|`compensationBindingScopeCombo`|
|`compensation_editor.py`|`compensationBindingTargetEdit`|
|`compensation_editor.py`|`compensationBindingNotesEdit`|
|`compensation_editor.py`|`compensationPreviewSampleCombo`|
|`compensation_editor.py`|`compensationPreviewButton`|
|`compensation_editor.py`|`compensationPreviewTable`|
|`compensation_editor.py`|`compensationCalculationEditorDialog`|
|`compensation_editor.py`|`compensationCalculationList`|
|`compensation_editor.py`|`compensationNewCalcButton`|
|`compensation_editor.py`|`compensationDeleteCalcButton`|
|`compensation_editor.py`|`compensationCalcIdEdit`|
|`compensation_editor.py`|`compensationCalcNameEdit`|
|`compensation_editor.py`|`compensationCalcRegressionCombo`|
|`compensation_editor.py`|`compensationCalcOutlierCombo`|
|`compensation_editor.py`|`compensationCalcMinPosEdit`|
|`compensation_editor.py`|`compensationCalcMinNegEdit`|
|`compensation_editor.py`|`compensationCalcNotesEdit`|
|`compensation_editor.py`|`compensationControlTable`|
|`compensation_editor.py`|`compensationAddControlButton`|
|`compensation_editor.py`|`compensationDeleteControlButton`|
|`compensation_editor.py`|`compensationCalcRunButton`|
|`compensation_editor.py`|`compensationCalcSaveButton`|
|`compensation_editor.py`|`compensationCalcDiagnosticTable`|
|`compensation_editor.py`|`compensationCalcConditionLabel`|
|`compensation_editor.py`|`compensationCalcDiagnosticLabel`|
|`compensation_editor.py`|`compensationCalcDialogButtons`|
|`derived_parameter_editor.py`|`derivedParameterEditorDialog`|
|`derived_parameter_editor.py`|`derivedParameterDefinitionList`|
|`derived_parameter_editor.py`|`derivedParameterNewButton`|
|`derived_parameter_editor.py`|`derivedParameterDeleteButton`|
|`derived_parameter_editor.py`|`derivedParameterDefinitionIdEdit`|
|`derived_parameter_editor.py`|`derivedParameterNameEdit`|
|`derived_parameter_editor.py`|`derivedParameterOutputIdEdit`|
|`derived_parameter_editor.py`|`derivedParameterUnitEdit`|
|`derived_parameter_editor.py`|`derivedParameterSourceStageCombo`|
|`derived_parameter_editor.py`|`derivedParameterPolicyCombo`|
|`derived_parameter_editor.py`|`derivedParameterNonFinitePolicyCombo`|
|`derived_parameter_editor.py`|`derivedParameterExpressionEdit`|
|`derived_parameter_editor.py`|`derivedParameterInputsList`|
|`derived_parameter_editor.py`|`derivedParameterInsertParameterCombo`|
|`derived_parameter_editor.py`|`derivedParameterInsertParameterButton`|
|`derived_parameter_editor.py`|`derivedParameterValidateButton`|
|`derived_parameter_editor.py`|`derivedParameterPreviewButton`|
|`derived_parameter_editor.py`|`derivedParameterDiagnosticLabel`|
|`derived_parameter_editor.py`|`derivedParameterPreviewLabel`|
|`derived_parameter_editor.py`|`derivedParameterDialogButtons`|
|`diagnostics_panel.py`|`diagnosticsPanel`|
|`diagnostics_panel.py`|`pipelineDiagnosticsTable`|
|`diagnostics_panel.py`|`pipelineDiagnosticsStatusLabel`|
|`gate_editor.py`|`polygonCoordinatesTable`|
|`gate_editor.py`|`booleanSourcePopulationTree`|
|`gate_editor.py`|`booleanExpressionEditor`|
|`gate_editor.py`|`populationColorContextMenu`|
|`gate_editor.py`|`populationColorAction`|
|`gate_editor.py`|`gateOutlineColorAction`|
|`gate_editor.py`|`usePopulationColorForOutlineAction`|
|`gate_editor.py`|`resetPopulationColorAction`|
|`gate_editor.py`|`gateEditor`|
|`gate_editor.py`|`gateTypeCombo`|
|`gate_editor.py`|`parentPopulationCombo`|
|`gate_editor.py`|`gateCreationContextLabel`|
|`gate_editor.py`|`createGateButton`|
|`gate_editor.py`|`deleteGateButton`|
|`gate_editor.py`|`createChildGateButton`|
|`gate_editor.py`|`showGateButton`|
|`gate_editor.py`|`showPopulationButton`|
|`gate_editor.py`|`migrateGateTransformButton`|
|`gate_editor.py`|`applyGateParentButton`|
|`gate_editor.py`|`editBooleanGateButton`|
|`gate_editor.py`|`editGateGeometryButton`|
|`gate_editor.py`|`selectedGateParentCombo`|
|`gate_editor.py`|`gateList`|
|`gate_editor.py`|`gateHierarchyTree`|
|`gate_editor.py`|`gateStatusLabel`|
|`gate_override_editor.py`|`gateOverrideDialog`|
|`gate_override_editor.py`|`gateOverrideImpactLabel`|
|`gate_override_editor.py`|`gateOverrideCoordinatesEdit`|
|`gate_override_editor.py`|`gateOverrideThresholdsEdit`|
|`gate_override_editor.py`|`gateOverrideReasonEdit`|
|`gate_override_editor.py`|`gateOverrideAuthorEdit`|
|`group_panel.py`|`groupSampleList`|
|`group_panel.py`|`groupList`|
|`group_panel.py`|`groupPanel`|
|`group_panel.py`|`addGroupButton`|
|`group_panel.py`|`renameGroupButton`|
|`group_panel.py`|`deleteGroupButton`|
|`main_window.py`|`compensationStatusIndicator`|
|`main_window.py`|`compensationStatusLabel`|
|`main_window.py`|`flowdeskMainWindow`|
|`main_window.py`|`actionOpenDirectory`|
|`main_window.py`|`actionOpenFiles`|
|`main_window.py`|`actionOpenProject`|
|`main_window.py`|`actionSaveProject`|
|`main_window.py`|`actionExportResults`|
|`main_window.py`|`toolbarExportResults`|
|`main_window.py`|`actionQuit`|
|`main_window.py`|`actionUndoGateChange`|
|`main_window.py`|`actionRedoGateChange`|
|`main_window.py`|`actionCreateGateOverride`|
|`main_window.py`|`actionUndoOverlaySourceChange`|
|`main_window.py`|`actionRedoOverlaySourceChange`|
|`main_window.py`|`actionRunPipeline`|
|`main_window.py`|`actionDerivedParameters`|
|`main_window.py`|`actionCompensation`|
|`main_window.py`|`actionCompensationCalculations`|
|`main_window.py`|`actionTransforms`|
|`main_window.py`|`actionAdvancedGroups`|
|`main_window.py`|`actionClearGates`|
|`main_window.py`|`actionAddStatistic`|
|`main_window.py`|`actionStatistics`|
|`main_window.py`|`actionBatchPlotExport`|
|`results_export_dialog.py`|`resultsExportDialog`, `resultsExportLayoutCombo`, `resultsExportPopulationCheck`, `resultsExportStatisticsCheck`, `resultsExportInternalIdsCheck`, `resultsExportQcCheck`, `resultsExportDialogButtons`|
|`main_window.py`|`actionSampleSheet`|
|`main_window.py`|`actionParameterInformation`|
|`main_window.py`|`actionOverlaySamples`|
|`main_window.py`|`actionOverlaySources`|
|`main_window.py`|`actionPlotPresentation`|
|`main_window.py`|`mainToolbar`|
|`main_window.py`|`mainContentSplitter`|
|`main_window.py`|`mainOuterSplitter`|
|`main_window.py`|`mainStatusBar`|
|`main_window.py`|`gatingResultsTabs`|
|`main_window.py`|`workspaceNavigationBar`|
|`main_window.py`|`workspaceBreadcrumbLabel`|
|`main_window.py`|`workspaceParentButton`|
|`main_window.py`|`previousSampleButton`|
|`main_window.py`|`nextSampleButton`|
|`main_window.py`|`gateTransformMigrationPreview`|
|`main_window.py`|`'viewRange' + name.replace(' ', '')`|
|`overlay_source_editor.py`|`overlaySourceEditorDialog`|
|`overlay_source_editor.py`|`overlaySourceList`|
|`overlay_source_editor.py`|`addOverlaySourceButton`|
|`overlay_source_editor.py`|`removeOverlaySourceButton`|
|`overlay_source_editor.py`|`moveOverlaySourceUpButton`|
|`overlay_source_editor.py`|`moveOverlaySourceDownButton`|
|`overlay_source_editor.py`|`overlaySourceDetails`|
|`overlay_source_editor.py`|`overlaySourceSampleCombo`|
|`overlay_source_editor.py`|`overlaySourcePopulationCombo`|
|`overlay_source_editor.py`|`overlaySourceXParameterCombo`|
|`overlay_source_editor.py`|`overlaySourceYParameterCombo`|
|`overlay_source_editor.py`|`overlaySourceXTransformCombo`|
|`overlay_source_editor.py`|`overlaySourceYTransformCombo`|
|`overlay_source_editor.py`|`overlaySourceLegendEdit`|
|`overlay_source_editor.py`|`overlaySourceColorEdit`|
|`overlay_source_editor.py`|`overlaySourceAlphaSpinBox`|
|`overlay_source_editor.py`|`overlaySourceVisibilityCheckBox`|
|`overlay_source_editor.py`|`overlaySourceCompatibilityLabel`|
|`overlay_source_editor.py`|`overlaySourceDialogButtons`|
|`plot_style_editor.py`|`plotStyleEditorDialog`|
|`plot_style_editor.py`|`plotAppearancePages`|
|`plot_style_editor.py`|`plotTitleEdit`|
|`plot_style_editor.py`|`plotSubtitleEdit`|
|`plot_style_editor.py`|`plotXAxisDisplayLabelEdit`|
|`plot_style_editor.py`|`plotYAxisDisplayLabelEdit`|
|`plot_style_editor.py`|`plotLegendVisibleCheckBox`|
|`plot_style_editor.py`|`plotLegendPositionCombo`|
|`plot_style_editor.py`|`plotLegendOrderList`|
|`plot_style_editor.py`|`moveLegendSourceUpButton`|
|`plot_style_editor.py`|`moveLegendSourceDownButton`|
|`plot_style_editor.py`|`plotBackgroundColorEdit`|
|`plot_style_editor.py`|`plotGateOutlineColorEdit`|
|`plot_style_editor.py`|`plotGateOutlineWidthSpinBox`|
|`plot_style_editor.py`|`plotAxisLineWidthSpinBox`|
|`plot_style_editor.py`|`plotColormapEdit`|
|`plot_style_editor.py`|`plotStyleSourceCombo`|
|`plot_style_editor.py`|`plotStyleSourceProvenanceLabel`|
|`plot_style_editor.py`|`plotMarkerShapeCombo`|
|`plot_style_editor.py`|`plotMarkerSizeSpinBox`|
|`plot_style_editor.py`|`plotSourceColorEdit`|
|`plot_style_editor.py`|`plotSourceAlphaSpinBox`|
|`plot_style_editor.py`|`plotSourceLineColorEdit`|
|`plot_style_editor.py`|`plotSourceLineWidthSpinBox`|
|`plot_style_editor.py`|`plotHistogramFillColorEdit`|
|`plot_style_editor.py`|`plotHistogramOutlineColorEdit`|
|`plot_style_editor.py`|`plotHistogramAlphaSpinBox`|
|`plot_style_editor.py`|`resetSourceStyleButton`|
|`plot_style_editor.py`|`resetSourceToProjectDefaultButton`|
|`plot_style_editor.py`|`resetSourceToGlobalDefaultButton`|
|`plot_style_editor.py`|`f'{field_name}FontFamilyEdit'`|
|`plot_style_editor.py`|`f'{field_name}FontSizeSpinBox'`|
|`plot_style_editor.py`|`f'{field_name}FontWeightCombo'`|
|`plot_style_editor.py`|`plotStyleValidationLabel`|
|`plot_style_editor.py`|`plotStyleDialogButtons`|
|`plot_style_editor.py`|`object_name`|
|`plot_toolbar.py`|`plotToolbar`|
|`plot_toolbar.py`|`resetRobustRangeButton`|
|`plot_toolbar.py`|`resetFullRangeButton`|
|`plot_toolbar.py`|`exportAspect1To1Button`|
|`plot_toolbar.py`|`exportPngButton`|
|`plot_toolbar.py`|`exportSvgButton`|
|`plot_toolbar.py`|`exportPdfButton`|
|`plot_toolbar.py`|`addStatisticFromGraphButton`|
|`plot_toolbar.py`|`f'{mode}InteractionModeButton'`|
|`plot_toolbar.py`|`toggleMarginalHistogramsButton`|
|`plot_widget.py`|`plotWidget`|
|`plot_widget.py`|`plotStatusBanner`|
|`plot_widget.py`|`plotGraphicsLayout`|
|`plot_widget.py`|`plotAppearanceContextMenu`|
|`plot_widget.py`|`action_id`|
|`plot_widget.py`|`plotViewRangeMenu`|
|`plot_widget.py`|`plotSetNumericRange`|
|`plot_widget.py`|`plotAxisTicksMenu`|
|`plot_widget.py`|`f"plotAxisTicks{policy.title().replace('_', '')}"`|
|`plot_widget.py`|`plotLegendMenu`|
|`plot_widget.py`|`plotShowLegend`|
|`plot_widget.py`|`plotLegendPositionMenu`|
|`plot_widget.py`|`f'plotLegendPosition{position_name.title()}'`|
|`population_tree.py`|`populationTree`|
|`population_tree.py`|`populationResultsTable`|
|`population_tree.py`|`populationStatusLabel`|
|`population_tree.py`|`populationStatisticsTree`|
|`population_tree.py`|`addStatisticFromPopulationTreeButton`|
|`results_workspace.py`|`resultsWorkspace`|
|`results_workspace.py`|`resultsWorkspaceTree`|
|`results_workspace.py`|`resultsAutoRecalculateCheck`|
|`results_workspace.py`|`resultsViewModeSelector`|
|`results_workspace.py`|`resultsAddStatisticButton`|
|`results_workspace.py`|`resultsManageStatisticsButton`|
|`results_workspace.py`|`resultsStatisticColumnsButton`|
|`sample_browser.py`|`f'sampleRow_{sample.id}'`|
|`sample_browser.py`|`f'overlayCheck_{sample.id}'`|
|`sample_browser.py`|`f'overlayColor_{sample.id}'`|
|`sample_browser.py`|`f'sampleName_{sample.id}'`|
|`sample_browser.py`|`f'overlayRelation_{sample.id}'`|
|`sample_browser.py`|`pairSelectedSamplesAction`|
|`sample_browser.py`|`createComparisonSetAction`|
|`sample_browser.py`|`addToComparisonSetAction`|
|`sample_browser.py`|`editComparisonRelationAction`|
|`sample_browser.py`|`removeFromComparisonSetAction`|
|`sample_browser.py`|`persistentOverlayAction`|
|`sample_browser.py`|`'overlayRole' + role.replace(' ', '')`|
|`sample_browser.py`|`clearOverlayRoleAction`|
|`sample_browser.py`|`sampleBrowser`|
|`sample_browser.py`|`sampleList`|
|`sample_browser.py`|`sampleListHeader`|
|`sample_browser.py`|`sampleHeaderOv`|
|`sample_browser.py`|`sampleHeaderCol`|
|`sample_browser.py`|`sampleHeaderName`|
|`sample_browser.py`|`sampleHeaderRel`|
|`sample_browser.py`|`sampleFilterEdit`|
|`sample_browser.py`|`sampleSortCombo`|
|`sample_browser.py`|`addFcsFilesButton`|
|`sample_browser.py`|`removeSampleButton`|
|`sample_browser.py`|`reconnectSampleButton`|
|`sample_browser.py`|`overlayModeSelector`|
|`sample_sheet.py`|`sampleSheetDialog`|
|`sample_sheet.py`|`sampleSheetFilterEdit`|
|`sample_sheet.py`|`sampleSheetTable`|
|`sample_sheet.py`|`sampleSheetAddAnnotationColumnButton`|
|`sample_sheet.py`|`sampleSheetPasteButton`|
|`sample_sheet.py`|`sampleSheetImportCsvButton`|
|`sample_sheet.py`|`sampleSheetFillSeriesButton`|
|`sample_sheet.py`|`sampleSheetFindReplaceButton`|
|`sample_sheet.py`|`sampleSheetUndoButton`|
|`sample_sheet.py`|`sampleSheetRedoButton`|
|`sample_sheet.py`|`sampleSheetDialogButtons`|
|`statistics_editor.py`|`statisticPopulationTargetsDialog`|
|`statistics_editor.py`|`statisticPopulationTargetsList`|
|`statistics_editor.py`|`statisticsEditorDialog`|
|`statistics_editor.py`|`statisticDefinitionList`|
|`statistics_editor.py`|`statisticNewButton`|
|`statistics_editor.py`|`statisticDeleteButton`|
|`statistics_editor.py`|`statisticDuplicateButton`|
|`statistics_editor.py`|`statisticClearButton`|
|`statistics_editor.py`|`statisticUndoButton`|
|`statistics_editor.py`|`statisticRedoButton`|
|`statistics_editor.py`|`statisticIdEdit`|
|`statistics_editor.py`|`statisticNameEdit`|
|`statistics_editor.py`|`statisticPopulationCombo`|
|`statistics_editor.py`|`statisticPopulationScopeCombo`|
|`statistics_editor.py`|`statisticPopulationTargetsButton`|
|`statistics_editor.py`|`statisticParameterCombo`|
|`statistics_editor.py`|`statisticMetricCombo`|
|`statistics_editor.py`|`statisticSourceCombo`|
|`statistics_editor.py`|`statisticTransformCombo`|
|`statistics_editor.py`|`statisticNonFinitePolicyCombo`|
|`statistics_editor.py`|`statisticPercentileQEdit`|
|`statistics_editor.py`|`statisticPercentileQLabel`|
|`statistics_editor.py`|`statisticFormatEdit`|
|`statistics_editor.py`|`statisticNotesEdit`|
|`statistics_editor.py`|`statisticComputeEnabledCheck`|
|`statistics_editor.py`|`statisticDiagnosticLabel`|
|`statistics_editor.py`|`statisticDialogButtons`|
|`statistics_editor.py`|`statisticManagementDialog`|
|`statistics_editor.py`|`statisticManagementTable`|
|`statistics_editor.py`|`statisticEditTargetsButton`|
|`statistics_editor.py`|`statisticManagementDialogButtons`|
|`statistics_editor.py`|`f'statisticComputeCheck_{statistic_id}'`|
|`statistics_editor.py`|`f'statisticShowCheck_{statistic_id}'`|
|`transform_editor.py`|`transformEditorDialog`|
|`transform_editor.py`|`transformDefinitionList`|
|`transform_editor.py`|`transformNewButton`|
|`transform_editor.py`|`transformDeleteButton`|
|`transform_editor.py`|`transformIdEdit`|
|`transform_editor.py`|`transformNameEdit`|
|`transform_editor.py`|`transformParameterCombo`|
|`transform_editor.py`|`transformTypeCombo`|
|`transform_editor.py`|`f'transformSetting{name}Edit'`|
|`transform_editor.py`|`transformInvalidValuePolicyCombo`|
|`transform_editor.py`|`transformImplementationVersionEdit`|
|`transform_editor.py`|`transformPreviewButton`|
|`transform_editor.py`|`transformPreviewLabel`|
|`transform_editor.py`|`transformDialogButtons`|
|`workspace_tree.py`|`workspaceTree`|
|`workspace_tree.py`|`workspaceHierarchyTree`|

### 19.2 objectName を持たないが文書化対象の control

|control|場所|
|---|---|
|File/Edit/Analysis/Results/Data/Plot/Help menu headings|MainWindow menu bar|
|About Flowdesk action|Help menu|
|Open Samples / Run Pipeline / Export Results toolbar actions|Main Toolbar|
|Gate dialog OK / Cancel and gate-specific spin boxes|Create/Edit Gate dialog|
|Gate override Geometry mode / Gate purpose combo / OK / Cancel|GateOverrideDialog|
|Group Add/Rename/Delete input dialogs|GroupPanel|
|Sample Sheet Add column / Fill / Find/Replace input dialogs|SampleSheetDialog|
|Color chooser dialogs|Samples overlay, population, gate outline|
|FCS/project/open/save/export file dialogs|MainWindow and SampleBrowser|
|Compensation binding and calculation cell combos|Compensation dialogs|
|Statistic target tree checkboxes|Select statistic populations|
|Plot Presentation line-style combos|General and Sources tabs|
|QDialogButtonBox OK / Cancel standard buttons|All definition dialogs|
|Migration Duplicate / Migrate / Cancel buttons|Gate transform migration QMessageBox|
