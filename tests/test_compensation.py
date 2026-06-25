from flowdesk_core.compensation import validate_compensation_matrix
from flowdesk_core.models import CompensationMatrixSpec


def test_compensation_matrix_model_can_be_created() -> None:
  spec = CompensationMatrixSpec(
    id="comp1",
    name="FCS spillover",
    source="fcs_metadata_spillover",
    channels=("FL1-A", "FL2-A"),
    matrix=((1.0, 0.1), (0.2, 1.0)),
  )

  validate_compensation_matrix(spec)
  assert spec.channels == ("FL1-A", "FL2-A")
