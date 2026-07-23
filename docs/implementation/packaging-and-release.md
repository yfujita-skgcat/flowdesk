# Packaging and Release

## Status

Phase 1の配布準備は実装済みである。

- `pyproject.toml`に`numpy`と`flowio`を必須依存として定義した。
- GUI依存を`gui` extraへ分離し、`PySide6`と`pyqtgraph`を定義した。
- `python -m flowdesk_qt`のmodule entry pointを追加した。
- `QStandardPaths`を使い、recovery、ログ、debug artifactの保存先をOS標準のユーザー領域へ移した。
- アプリversionを`importlib.metadata`から取得し、GUI表示とdebug stateで共有するようにした。
- `tools/package.py`をOS共通のnative build/smoke/manifest入口として追加した。
- GUI用`flowdesk`とheadless用`flowdesk-cli`を別のonedir成果物として生成する。
- Makefileは`tools/package.py`を呼ぶLinux/macOS向けの便利なラッパーとし、WindowsではPythonから直接実行できる。
- GUI smoke testはJSON reportでQt version、platform、MainWindow生成を検証し、Qt platformの指定は明示時だけ行う。
- PyInstallerの標準hookを優先し、collectorではpyqtgraphのデータだけを追加収集する。

次のPhase 2以降は未実装であり、PyInstaller specやOS installerを追加する前に、各Phaseを個別に完了させる。

## Goal

Pythonをインストールしていないユーザーが、Windows、macOS、LinuxでFlowdeskを簡単に導入できる配布物を作る。
科学計算は既存のGUI-independent pipelineを使用し、パッケージング処理が結果計算を変更してはならない。

## Distribution model

```text
Python source
  -> PyInstaller onedir
     -> Windows: Inno Setup installer
     -> macOS: .app -> signed/notarized DMG
     -> Linux: AppDir -> AppImage
```

PyInstallerはOSごとのnative build runnerで実行する。PyInstaller成果物を別OS向けにcross-compileしてはならない。
初期のPyInstaller形式は`onedir`とし、onefile化は起動時間、temporary extraction、antivirus、デバッグ性を検証してから別incrementで判断する。

## Phase 2: PyInstaller build

対象候補:

- `packaging/flowdesk.spec`
- `packaging/collect_qt.py`または同等のhook/helper
- `src/flowdesk_qt/__main__.py`
- `tests/packaging/`

specでは次を明示的に検証する。

- `flowdesk_qt`と`flowdesk_core`の全importが収集される。
- PySide6のplatform plugin、SVG plugin、Qt resourceが収集される。
- NumPy、flowioとnative libraryの依存が成果物に含まれる。
- `importlib.metadata`でpackage versionを取得できるか、build時のversion情報を安全に埋め込む。
- output directory、temporary directory、ユーザー書込み領域がinstall directoryを参照しない。

## Phase 3: package smoke test

Python未導入のclean環境で、少なくとも次を確認する。

- アプリが起動し、Qt platform pluginエラーがない。
- 日本語、空白、長いパスにあるFCSを開ける。
- compensation、derived parameter、transform、gate、Pipelineが動く。
- projectの保存・再読込ができる。
- CSV、TSV、PNG、SVG、PDFを出力できる。
- autosave/recovery、ログ、debug artifactをユーザー書込み可能領域へ保存する。
- 終了時にQThreadが残らない。

開発環境でのpytest成功だけではpackage smoke testの代替にならない。package後の実行ログとversionをartifactへ保存する。

## Phase 4: OS-specific installers

### Windows

Inno Setupまたは同等のinstallerで、ユーザー権限インストール、Start Menu、uninstaller、upgradeを提供する。
初期install先は`%LOCALAPPDATA%\\Programs\\Flowdesk`を基本とし、管理者権限を必須にしない。
`.fcs`関連付けは別optionとして扱い、既存関連付けを黙って上書きしない。

### macOS

`.app`をDMGへ入れて配布する。arm64を初期対象とし、Intel対応が必要になったらx86_64またはuniversal buildを別途定義する。
外部配布ではDeveloper ID、Hardened Runtime、notarization、ticket stapleを行う。署名なしartifactは開発用として明示し、release artifactと混同しない。

### Linux

Ubuntu 22.04相当をbuild baselineとするAppImageを作る。Ubuntu 22.04/24.04、Debian、Fedoraで起動確認し、glibc互換性の最低条件をrelease noteへ記載する。
必要性が確認できるまで、deb/rpmをAppImageと同時に必須化しない。

## Phase 5: CI and release

tag `vX.Y.Z`を起点に、次をnative runnerで実行する。

1. core/GUI test、lint、type check
2. Windows、macOS、LinuxのPyInstaller build
3. package smoke test
4. 署名/notarization（秘密情報が設定されたrelease jobのみ）
5. SHA-256 checksumとbuild provenance生成
6. GitHub Releaseへのartifact upload

失敗したOSのartifactを成功扱いで公開してはならない。署名情報、source commit、build runner、versionをrelease metadataへ保存する。

## Licensing

配布物へFlowdeskのlicenseと、少なくともPySide6/Qt、NumPy、FlowIO、pyqtgraphのthird-party license情報を含める。
ライセンス選択やLGPL遵守は法的助言ではないため、外部公開前に確認する。配布物の生成とlicense文書の更新を別工程にせず、同じrelease workflowで検証する。

## Acceptance criteria

- Windows installer、macOS DMG、Linux AppImageをnative runnerから再現できる。
- Python未導入のclean環境で各配布物が起動する。
- GUIのcount、statistics、exportがheadless PipelineRunnerの結果と一致する。
- 日本語/空白を含むFCS path、project save/load、autosave/recoveryが機能する。
- install、upgrade、uninstallとユーザー書込み領域を確認する。
- checksum、version、source commit、build OS、license情報がreleaseへ添付される。
- package buildで既存のcore/GUI testを削除、skip、xfailしない。
