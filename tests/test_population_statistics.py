from flowdesk_core.statistics import make_population_result


def test_population_result_frequencies() -> None:
  result = make_population_result(
    sample_id="s1",
    population_id="live",
    event_count=25,
    parent_count=50,
    total_count=100,
  )

  assert result.event_count == 25
  assert result.frequency_of_parent == 0.5
  assert result.frequency_of_total == 0.25
