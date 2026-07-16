from flowdesk_core.annotations import (
  annotation_columns,
  annotation_table,
  fill_annotation_series,
  parse_annotation_csv,
  replace_annotation_values,
)
from flowdesk_core.models import AnnotationSpec


def test_annotation_columns_and_source_precedence() -> None:
  annotations = (
    AnnotationSpec("s1", "Condition", "old", "fcs"),
    AnnotationSpec("s1", "Condition", "new", "workspace"),
    AnnotationSpec("s2", "Dose", 3, "imported"),
  )
  assert annotation_columns(annotations) == ("Condition", "Dose")
  rows = annotation_table(("s1", "s2"), annotations)
  assert rows[0]["Condition"] == "new"
  assert rows[1]["Condition"] is None


def test_replace_and_fill_series_are_non_destructive() -> None:
  original = (AnnotationSpec("s1", "Condition", "old", "fcs"),)
  replaced = replace_annotation_values(original, "Condition", "old", "new")
  assert len(original) == 1
  assert replaced[-1].source == "workspace"
  series = fill_annotation_series(("s1", "s2"), "Dose", 1, 0.5)
  assert [item.value for item in series] == [1.0, 1.5]


def test_csv_annotation_import_types_values() -> None:
  imported = parse_annotation_csv(
    "sample_id,Condition,Dose\ns1,treated,2\ns2,control,\n"
  )
  assert [(item.sample_id, item.keyword, item.value) for item in imported] == [
    ("s1", "Condition", "treated"),
    ("s1", "Dose", 2),
    ("s2", "Condition", "control"),
  ]
