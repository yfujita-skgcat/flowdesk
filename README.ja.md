# flowdesk

<p align="center">
  <a href="README.md">English</a> |
  <strong>日本語</strong>
</p>

Flowdesk は、Linux-first の FlowJo 類似フローサイトメトリー解析アプリケーションを
開発するための初期段階の Python プロジェクトです。

利用者向けの操作方法と機能説明は、[ユーザーマニュアル](docs/user-manual/user_manual.md)
を参照してください。

## MVP の範囲

- FCS sample、channel、compensation matrix、derived parameter、transform、gate、population tree、export recordを扱う。
- 科学的な解析処理を GUI 非依存の core module に保持する。
- project を `.flowdesk` directory bundle として保存し、GUI、CLI、Python API から実行する。
- schema、実装ガイド、agent guidance、synthetic test を提供する。

## 対象外

- FlowJo 完全互換
- GatingML 完全対応
- production GUI の完成
- production FCS parser と大規模ファイル描画

## クレジットとライセンス

Copyright (c) 2026 Yoshihiko Fujita (`yfujita.skgcat@gmail.com`)。

Flowdesk は BSD 3-Clause License で配布されます。完全な本文は [LICENSE](LICENSE) を
参照してください。クレジットは `flowdesk --help`、`flowdesk --credits`、GUI の Help
メニューからも確認できます。

## 想定する技術スタック

Python 3.11+、NumPy、FlowIO または FlowKit、PySide6、pyqtgraph、pytest、ruff、mypy など。

## 開発環境

```bash
direnv allow
. .direnv/python-3.12.13/bin/activate
python -m pip install -e '.[dev]'
```

GUI と GUI test の依存も入れる場合:

```bash
python -m pip install -e '.[gui,dev,gui-test]'
```

## Desktop package の build

現在は PyInstaller の native `onedir` package を作成します。GUI (`flowdesk`) と
headless CLI (`flowdesk-cli`) が `dist/` 以下に生成されます。Windows installer、
署名済み macOS DMG、Linux AppImage はまだ提供していません。

PyInstaller は cross-compiler ではありません。実行対象と同じ OS、CPU architecture
で build してください。

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[gui,dev]"
python tools/package.py build
```

macOS/Linux では次も使用できます。

```bash
make package
```

生成物:

```text
dist/flowdesk/       GUI application (flowdesk または flowdesk.exe)
dist/flowdesk-cli/   headless CLI (flowdesk-cli または flowdesk-cli.exe)
```

package smoke test:

```bash
python tools/package.py smoke
python tools/package.py smoke \
  --project path/to/project.flowdesk \
  --fcs path/to/sample.fcs
```

test report は既定で `artifacts/package-smoke/` に保存されます。

```bash
python tools/package.py manifest \
  --output artifacts/package-smoke/build-manifest.json
```

build と smoke test を続けて行う場合:

```bash
make package-check
```

各 OS の native runner で検証し、日本語や空白を含む path、project save/load、export、
recovery、GUI と headless `PipelineRunner` の population count を確認してください。
`build/`、`dist/`、package smoke artifact は commit しないでください。

GitHub Actions には Windows、Linux、macOS の native package workflow があります。
現状は portable artifact であり、installer、AppImage、署名、notarization は別の release
workflow が必要です。

patch version の更新:

```bash
make upversion
```

version source は `src/flowdesk_qt/_version.py` です。setuptools、GUI、CLI が同じ source
を使用します。version を commit した後、tag を作成・pushする場合:

```bash
make pushtag
```

## Test

```bash
pytest
```

Makefile の主な target:

```bash
make test
make lint
make type-check
make check
make fmt
make test-all
make clean
make help
```

## CLI の使い方

package を install すると `flowdesk` command が使用できます。

```bash
# 保存済み project を headless 実行して Results を出力
flowdesk run path/to/project.flowdesk --output results.tsv

# FCS metadata を確認
flowdesk inspect path/to/sample.fcs

# 複数 FCS に gate を適用
flowdesk batch-gate path/to/project.flowdesk file1.fcs file2.fcs

# クレジットと license を表示
flowdesk --credits
```

`flowdesk --help` の末尾にもクレジットが表示されます。

## GUI の使い方

GUI は optional dependency です。

```bash
python -m pip install -e '.[gui,dev]'

# data なしで起動
python -m flowdesk_qt

# directory の FCS を読み込んで起動
python -m flowdesk_qt --data-dir data/
```

GUI test と debug:

```bash
./tools/run-gui-tests.sh
./tools/run-single-gui-test.sh tests/gui/test_gui_workflow.py::test_load_gate_run_and_match_headless
make test-all
./tools/run-gui-debug.sh --data-dir data/
```

GUI の Help メニューには About と Credits があり、copyright、連絡先、年、BSD 3-Clause
License を表示します。

## Architecture

```text
raw FCS events
  -> compensation
  -> derived parameters
  -> transform
  -> gate membership
  -> population statistics
  -> export
```

- `flowdesk_core`: GUI 非依存の科学計算
- `flowdesk_storage`: `.flowdesk` directory の project I/O
- `flowdesk_cli`: `run`、`inspect`、`batch-gate` などの CLI entry point
- `flowdesk_qt`: optional な PySide6 GUI

raw event data は不変として扱い、表示用 downsampling は gate count、frequency、statistics
には使用しません。

## 現在の状況

compensation、derived parameter、transform、gate、population statistics、TSV/CSV export、
project save/load、GUI の sample browser、scatter/histogram、gate hierarchy、population
filtering、pipeline 実行、analysis settings bundle を実装済みです。

未実装または限定的な項目は、FlowJo 完全互換、GatingML 完全対応、production GUI、
大規模 FCS rendering、Release C の table/layout/template/interoperability 機能です。
