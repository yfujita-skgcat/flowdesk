# Flowdesk UI coverage report

- Source directory: `src/flowdesk_qt`
- Manual: `docs/user_manual.md`
- Python GUI modules scanned: 28
- Literal objectName occurrences: 325
- Unique literal objectName values: 325
- Dynamic objectName expressions: 19
- Interactive UI text occurrences: 196
- Unique interactive UI text literals: 172
- Missing literal objectName values: 0
- Missing interactive UI text literals: 0

## Result

**PASS:** Every literal `setObjectName(...)` value and every literal label used by actions, buttons, checkboxes, menus, tabs, and combo-box items found by the static scan is represented in the manual.

## Dynamic objectName expressions

- `channel_metadata.py:68` — `f'channelColumn_{key}'`
- `main_window.py:3923` — `'viewRange' + name.replace(' ', '')`
- `plot_style_editor.py:326` — `object_name`
- `plot_style_editor.py:260` — `f'{field_name}FontFamilyEdit'`
- `plot_style_editor.py:262` — `f'{field_name}FontSizeSpinBox'`
- `plot_style_editor.py:264` — `f'{field_name}FontWeightCombo'`
- `plot_toolbar.py:190` — `f'{mode}InteractionModeButton'`
- `plot_widget.py:2141` — `action_id`
- `plot_widget.py:2168` — `f"plotAxisTicks{policy.title().replace('_', '')}"`
- `plot_widget.py:2189` — `f'plotLegendPosition{position_name.title()}'`
- `sample_browser.py:482` — `f'sampleRow_{sample.id}'`
- `sample_browser.py:487` — `f'overlayCheck_{sample.id}'`
- `sample_browser.py:501` — `f'overlayColor_{sample.id}'`
- `sample_browser.py:517` — `f'sampleName_{sample.id}'`
- `sample_browser.py:522` — `f'overlayRelation_{sample.id}'`
- `sample_browser.py:639` — `'overlayRole' + role.replace(' ', '')`
- `statistics_editor.py:867` — `f'statisticComputeCheck_{statistic_id}'`
- `statistics_editor.py:870` — `f'statisticShowCheck_{statistic_id}'`
- `transform_editor.py:148` — `f'transformSetting{name}Edit'`

## Missing literal objectName values

None.

## Missing interactive UI text literals

None.

## Scope limitation

This is a static source scan and does not import or run PySide6. Runtime-generated controls, conditional menu branches, standard `QDialogButtonBox` buttons, and controls whose labels are assembled from variables still require source review. These categories are documented explicitly in section 19.2 of the manual.
