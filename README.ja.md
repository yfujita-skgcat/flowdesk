# flowdesk

Flowdeskは、FlowJoに似たフローサイトメトリー解析アプリケーションを目指す、開発初期段階のPythonプロジェクトです。Linuxを主対象としていますが、クロスプラットフォームでの動作を想定しています。

## MVPの範囲

- FCSサンプル、チャンネル、補償行列、派生パラメータ、変換、ゲート、母集団ツリー、エクスポート記録を表現します。
- 科学計算をGUIから独立したコアモジュールで実行します。
- プロジェクトをGUI、CLI、Python APIから実行できる`.flowdesk`ディレクトリバンドルとして保存します。
- 初期ドキュメント、スキーマ、エージェント向けガイド、合成データのテストを提供します。

## 対象外

- 完全なFlowJo互換性
- 完全なGatingML対応
- 本番品質のGUI動作
- 本番用FCSパーサーや大規模ファイルの描画

## 想定技術スタック

Python 3.11以降、NumPy、Polarsまたはpandas、FlowIOおよび/またはFlowKit、PySide6、pyqtgraph、Datashader、pytest、ruff、mypyを使用します。

## 開発環境のセットアップ

```bash
direnv allow
# まだ有効になっていない場合は仮想環境を有効化
. .direnv/python-3.12.13/bin/activate
python -m pip install -e '.[dev]'
```

GUIテストを含む追加グループは次のようにインストールします。

```bash
python -m pip install -e '.[gui,dev,gui-test]'
```

## Windows/macOS向けデスクトップパッケージのビルド

現在のFlowdeskは、PyInstallerのOSネイティブな`onedir`形式をビルドします。GUI用の`flowdesk`とヘッドレスCLI用の`flowdesk-cli`が`dist/`以下に生成されます。これは開発用・ポータブルなディレクトリ形式であり、Windowsインストーラーや署名・公証済みmacOS DMGはまだ生成しません。

PyInstallerはクロスコンパイラーではありません。実行対象と同じOS・CPUアーキテクチャ上でビルドしてください。Python 3.11以降のクリーンな仮想環境を使用します（リポジトリの開発環境ではPython 3.12を使用）。ビルド環境にはGit、ネイティブwheelに必要なC/C++ツールチェーン、`build/`と`dist/`を作成できるディスク容量が必要です。macOSでは環境作成前にApple Command Line Toolsを`xcode-select --install`で導入してください。Windowsでは64-bit版の最新PythonとPowerShellまたはコマンドプロンプトを使用します。

リポジトリのルートで、パッケージとビルド依存をインストールします。

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# Windows cmd.exe:    .venv\Scripts\activate.bat
# macOS/Linux:        source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[gui,dev]"
```

GUIとCLIの両方をビルドします。

```bash
python tools/package.py build
```

macOSまたはLinuxでは、同じ処理を次でも実行できます。

```bash
make package
```

Windowsでは、リポジトリのMakefileがPOSIXシェル向けのため、Pythonコマンドを直接実行します。成果物は次の場所に作られます。

```text
dist/flowdesk/       GUIアプリケーション（flowdeskまたはflowdesk.exe）
dist/flowdesk-cli/   ヘッドレスCLI（flowdesk-cliまたはflowdesk-cli.exe）
```

ビルド後にパッケージのsmoke testを実行してください。Qtプラグインを含めてGUIが起動することを確認します。プロジェクトとFCSファイルを渡すと、パッケージ化されたCLIのパイプラインも実行します。

```bash
python tools/package.py smoke
python tools/package.py smoke \
  --project path/to/project.flowdesk \
  --fcs path/to/sample.fcs
```

レポートは既定で`artifacts/package-smoke/`に保存されます。ビルド来歴は次のように保存できます。

```bash
python tools/package.py manifest \
  --output artifacts/package-smoke/build-manifest.json
```

macOSまたはLinuxでは`make package-check`でビルドとsmoke testを一括実行できます。配布前には対象OSのクリーンなマシンでテストしてください。特に、日本語や空白を含むパス、プロジェクトの保存・再読込、各種エクスポート、recovery・ログの保存先、GUIの母集団数とヘッドレス`PipelineRunner`の結果が一致することを確認します。

OS固有の署名やインストーラー作成は、現在のビルド入口には含まれません。

- Windows: `dist/flowdesk/`をInno Setupなどで包むことはできますが、インストーラー設定はまだありません。
- macOS: `onedir`成果物から`.app`を構成できますが、Developer ID署名、Hardened Runtime、公証、DMG作成は別のリリースワークフローが必要です。
- Linux: AppImage生成はまだ含まれていません。

`build/`、`dist/`、パッケージsmoke testの成果物はコミットしないでください。対応OSごとにネイティブrunnerを使い、配布時にはmanifestに記録されたPython、PySide6、NumPy、FlowIOのバージョンを保管してください。

### GitHub ActionsでWindows版をビルドする

リポジトリには`.github/workflows/package-windows.yml`を用意しています。ネイティブな`windows-latest` runner上でGUIとCLIをビルドし、coreテストとパッケージsmoke testを実行し、ビルドmanifestを作成して、`Flowdesk-Windows-x64.zip`をActions artifactとしてアップロードします。

GitHubの**Actions → Package Windows → Run workflow**から手動実行できます。また、`v0.1.0`のようなタグをpushした場合にも実行されます。生成されるのはポータブルZIPであり、インストーラーではありません。成果物はworkflow完了後の実行結果からダウンロードできます。パッケージは未署名のため、コード署名、SmartScreenの評価、Inno Setupインストーラーは今後のリリースworkflowで対応します。

Linux用の`package-linux.yml`とmacOS用の`package-macos.yml`も用意しています。それぞれ`ubuntu-22.04`と`macos-14`上で実行し、`Flowdesk-Linux-x86_64.tar.gz`と`Flowdesk-macOS-arm64.zip`を別々のartifactとしてアップロードします。これらはPyInstallerのnativeディレクトリパッケージです。AppImage、macOSの`.app`/DMG、署名、公証はまだ対応していません。

`pyproject.toml`に記載されたversionからタグを作成してpushするには、version変更を先にcommitしてから次を実行します。

```bash
make pushtag
```

`v<project version>`形式のタグを作成してpushします。既存タグを上書きすることはありません。

## テスト

```bash
pytest
```

### Makefileの利用

```bash
make test        # 全テスト（pytest -v）
make lint        # src/とtests/のruff
make type-check  # core、storage、CLIのmypy
make check       # lint + type-check
make fmt         # src/とtests/のruff formatter
make all         # fmt + check + test
make clean       # ビルド成果物とキャッシュを削除
make help        # 利用可能なターゲットを表示
```

## CLIの利用

パッケージを`pip install -e .`でインストールすると、`flowdesk`コマンドを利用できます。

```bash
# 保存済みプロジェクトを実行して結果を出力
flowdesk run path/to/project.flowdesk --output results.tsv

# FCSファイルのメタデータを確認
flowdesk inspect path/to/sample.fcs

# 複数のFCSファイルへゲートを一括適用
flowdesk batch-gate path/to/project.flowdesk --fcs file1.fcs file2.fcs
```

### エクスポート形式

CLIの`run`は既定で母集団統計をTSVとして出力します。`--csv`でCSVにできます。未定義の頻度などの`NaN`は`--nan-policy`で制御できます。

- `string_nan`（既定）: 文字列`NaN`を書き込む
- `empty`: セルを空にする
- `zero`: `0`を書き込む

## GUIの利用

PySide6ベースのGUIはオプション依存です。

```bash
python -m pip install -e '.[gui,dev]'
python -m flowdesk_qt
python -m flowdesk_qt --data-dir data/
```

GUIテストとデバッグは次のコマンドで実行します。

```bash
./tools/run-gui-tests.sh
./tools/run-single-gui-test.sh tests/gui/test_gui_workflow.py::test_load_gate_run_and_match_headless
make test-all
./tools/run-gui-debug.sh --data-dir data/
```

GUIテストは既定でoffscreen Qt backendを使用します。X11固有の動作には`FLOWDESK_GUI_BACKEND=xvfb ./tools/run-gui-tests.sh`を使用します。通常起動時のログとdebug artifactはOS固有のユーザーアプリケーションデータ領域に保存され、`--debug-artifacts-dir`で明示的な保存先を指定できます。

### 主なGUI操作

派生パラメータは**Analysis → Derived Parameters**から作成します。定義ID、表示名、安定した出力チャンネルID、式、入力元ステージ（`raw`または`compensated`）、単位、失敗時ポリシーを指定し、**Validate**で検証、**Preview**で最大200イベントを診断できます。Previewは診断用であり、ゲート・統計・エクスポートは常に全イベントを使います。

分析変換は**Analysis → Analysis Transforms**から作成します。`linear`、`log`、`asinh`、Gating-MLの`logicle`を選択できます。変換IDを参照するゲートは同じ変換をCLIとPython runnerでも使用します。ゲートが参照中の変換は直接変更・削除できないため、新しい変換IDを作成して**Migrate Transform**を使用します。非線形変換でのポリゴン移行は近似です。

キーボードショートカットは次のとおりです。

| ショートカット | 操作 |
|---|---|
| `Ctrl+O` | FCSを含むディレクトリを開く |
| `Ctrl+Shift+O` | FCSファイルを指定して開く |
| `Ctrl+R` | 解析パイプラインを実行 |
| `Ctrl+G` | すべてのゲートをクリア |
| `Ctrl+Q` | アプリケーションを終了 |

### ゲートと母集団階層

ゲートは親子の母集団階層として評価されます。表示用に間引いた点は母集団数に使用されません。

1. サンプルを読み込み、X/Yチャンネルと軸スケールを選択します。
2. **Gate Editor**で`rectangle`、`polygon`、`range`のいずれかを選び、親を`All Events`に設定します。
3. **Create Gate**でゲートを作成し、`Ctrl+R`または**Run Pipeline**で実行します。
4. 子ゲートは階層ツリーで親を選び、**Create Child Gate**から作成します。

`boolean`ゲートでは既存の母集団を`and`、`or`、`not`で組み合わせます。`AND`はすべてのソースに存在するイベント、`OR`は少なくとも1つに存在するイベント、`NOT`は選択ソースに存在しないイベントです。Boolean結果も指定した親母集団に制限されます。親の変更は**Apply Parent**で検証され、自己参照・子孫参照・循環は拒否されます。

従来の幾何ゲートは作成時の`linear`、`log10`、`asinh`軸を保存します。新しい分析変換は軸ごとの安定した変換IDを保存します。どちらも全解像度の値を同じ座標系へ変換してからゲートを評価するため、CLIとGUIで結果を再現できます。

## アーキテクチャ

```text
raw FCS events
  -> compensation
  -> derived parameters
  -> transform
  -> gate membership
  -> population statistics
  -> export
```

- `flowdesk_core`: 科学計算ロジック（GUI非依存）
- `flowdesk_storage`: `.flowdesk`ディレクトリの入出力
- `flowdesk_cli`: `run`、`inspect`、`batch-gate`のCLI入口
- `flowdesk_qt`: PySide6 GUI（オプション依存）

## 現在の状態

コアのデータクラス、パイプラインrunner、FCS入出力、補償、派生パラメータ、変換、ゲート、母集団統計、TSV/CSV出力、CLIコマンド、合成データテストを実装済みです。PySide6 GUIでは、サンプルブラウザー、scatter/histogram plot、階層ツリーとBooleanゲート編集、母集団フィルター、検証付き親変更、パイプライン実行を利用できます。

未実装なのは、完全なFlowJo互換性、完全なGatingML対応、本番品質のGUI動作、大規模FCS描画です。

詳細なGUI操作、派生パラメータ、変換、ゲート階層、Booleanゲート、overlay設定については、英語版READMEの各節および`docs/user-manual/user_manual.md`を参照してください。
