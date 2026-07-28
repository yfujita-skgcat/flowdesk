# Flowdesk UI coverage report

- Source directory: `src/flowdesk_qt`
- Manual: `docs/user-manual/user_manual.md`
- Python GUI modules scanned: 36
- Literal objectName occurrences: 370
- Unique literal objectName values: 370
- Dynamic objectName expressions: 25
- Interactive UI text occurrences: 239
- Unique interactive UI text literals: 213
- Missing literal objectName values: 35
- Missing interactive UI text literals: 12

## Result

**FAIL:** One or more statically discoverable UI elements are absent.

## Dynamic objectName expressions

- `batch_plot_export_dialog.py:238` — `name`
- `batch_plot_export_dialog.py:246` — `name`
- `batch_plot_export_dialog.py:116` — `f'batchPlotFormat{value.upper()}CheckBox'`
- `channel_metadata.py:68` — `f'channelColumn_{key}'`
- `main_window.py:4549` — `'viewRange' + name.replace(' ', '')`
- `plot_export_dialog.py:101` — `object_name`
- `plot_style_editor.py:371` — `object_name`
- `plot_style_editor.py:383` — `button_name`
- `plot_style_editor.py:305` — `f'{field_name}FontFamilyEdit'`
- `plot_style_editor.py:307` — `f'{field_name}FontSizeSpinBox'`
- `plot_style_editor.py:309` — `f'{field_name}FontWeightCombo'`
- `plot_toolbar.py:198` — `f'{mode}InteractionModeButton'`
- `plot_widget.py:2532` — `action_id`
- `plot_widget.py:2545` — `f'plotExport{format_name.title()}Action'`
- `plot_widget.py:2575` — `f"plotAxisTicks{policy.title().replace('_', '')}"`
- `plot_widget.py:2596` — `f'plotLegendPosition{position_name.title()}'`
- `sample_browser.py:491` — `f'sampleRow_{sample.id}'`
- `sample_browser.py:496` — `f'overlayCheck_{sample.id}'`
- `sample_browser.py:510` — `f'overlayColor_{sample.id}'`
- `sample_browser.py:526` — `f'sampleName_{sample.id}'`
- `sample_browser.py:531` — `f'overlayRelation_{sample.id}'`
- `sample_browser.py:648` — `'overlayRole' + role.replace(' ', '')`
- `statistics_editor.py:972` — `f'statisticComputeCheck_{statistic_id}'`
- `statistics_editor.py:975` — `f'statisticShowCheck_{statistic_id}'`
- `transform_editor.py:148` — `f'transformSetting{name}Edit'`

## Missing literal objectName values

- `batch_plot_export_dialog.py:55` — `batchPlotExportDialog`
- `batch_plot_export_dialog.py:67` — `batchPlotDefinitionCombo`
- `batch_plot_export_dialog.py:76` — `batchPlotNewDefinitionButton`
- `batch_plot_export_dialog.py:80` — `batchPlotNameLineEdit`
- `batch_plot_export_dialog.py:82` — `batchPlotTargetCombo`
- `batch_plot_export_dialog.py:88` — `batchPlotSampleList`
- `batch_plot_export_dialog.py:95` — `batchPlotGroupCombo`
- `batch_plot_export_dialog.py:101` — `batchPlotViewCombo`
- `batch_plot_export_dialog.py:124` — `batchPlotRasterResolutionModeCombo`
- `batch_plot_export_dialog.py:128` — `batchPlotVectorScatterModeCombo`
- `batch_plot_export_dialog.py:136` — `batchPlotResolutionPreviewLabel`
- `batch_plot_export_dialog.py:148` — `batchPlotLayoutPolicyCombo`
- `batch_plot_export_dialog.py:164` — `batchPlotFilenameTemplateLineEdit`
- `batch_plot_export_dialog.py:166` — `batchPlotCollisionPolicyCombo`
- `batch_plot_export_dialog.py:172` — `batchPlotOutputDirectoryLineEdit`
- `batch_plot_export_dialog.py:174` — `batchPlotBrowseOutputButton`
- `batch_plot_export_dialog.py:215` — `batchPlotSaveDefinitionButton`
- `batch_plot_export_dialog.py:218` — `batchPlotRunExportButton`
- `batch_plot_export_dialog.py:221` — `batchPlotCancelButton`
- `main_window.py:547` — `actionSaveProjectAs`
- `main_window.py:554` — `actionSaveAnalysisSettings`
- `main_window.py:565` — `actionLoadAnalysisSettings`
- `main_window.py:599` — `actionUndoAnalysisSettings`
- `main_window.py:609` — `actionRedoAnalysisSettings`
- `main_window.py:768` — `actionCredits`
- `plot_export_dialog.py:55` — `plotExportOptionsDialog`
- `plot_export_dialog.py:58` — `plotExportFormatCombo`
- `plot_export_dialog.py:62` — `plotExportWidthSpinBox`
- `plot_export_dialog.py:66` — `plotExportHeightSpinBox`
- `plot_export_dialog.py:70` — `plotExportAspectCheckBox`
- `plot_export_dialog.py:93` — `plotExportDialogButtons`
- `plot_style_editor.py:140` — `plotTitleModeCombo`
- `plot_widget.py:2540` — `plotExportMenu`
- `plot_widget.py:2550` — `plotExportBatchAction`
- `sample_browser.py:658` — `clearOverlayColorAction`

## Missing interactive UI text literals

- `batch_plot_export_dialog.py:68` `addItem` — `New definition`
- `batch_plot_export_dialog.py:83` `addItem` — `All samples`
- `batch_plot_export_dialog.py:84` `addItem` — `Explicit samples`
- `batch_plot_export_dialog.py:125` `addItem` — `Legacy pixel dimensions`
- `batch_plot_export_dialog.py:126` `addItem` — `Scale pixels by DPI`
- `batch_plot_export_dialog.py:150` `addItem` — `Shared ranges`
- `batch_plot_export_dialog.py:167` `addItem` — `Fail on collision`
- `batch_plot_export_dialog.py:168` `addItem` — `Replace existing`
- `batch_plot_export_dialog.py:169` `addItem` — `Add suffix`
- `batch_plot_export_dialog.py:173` `QPushButton` — `Browse…`
- `results_export_dialog.py:41` `QCheckBox` — `Population counts and frequencies`
- `results_export_dialog.py:54` `QCheckBox` — `Include status and QC metadata`

## Scope limitation

This is a static source scan and does not import or run PySide6. Runtime-generated controls, conditional menu branches, standard `QDialogButtonBox` buttons, and controls whose labels are assembled from variables still require source review. These categories are documented explicitly in section 19.2 of the manual.
