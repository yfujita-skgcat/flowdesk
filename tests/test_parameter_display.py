from flowdesk_core.parameter_display import parameter_display_label


def test_parameter_display_label_combines_annotation_and_plot_name() -> None:
  mappings = [{
    "parameter_id": "stable-fl2",
    "plot_label": "APC-A",
    "annotation": "iRFP670",
  }]
  assert parameter_display_label("stable-fl2", "FL2-A", mappings) == (
    "iRFP670 (APC-A)"
  )


def test_parameter_display_label_falls_back_without_mapping() -> None:
  assert parameter_display_label("stable-fl1", "FITC-A", ()) == "FITC-A"
