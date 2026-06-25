from flowdesk_core.models import TransformSpec


def test_transform_model_can_be_created() -> None:
  spec = TransformSpec(
    id="asinh_fl1",
    name="asinh FL1-A",
    transform_type="asinh",
    parameter="FL1-A",
    settings={"cofactor": 150.0},
  )

  assert spec.settings["cofactor"] == 150.0
