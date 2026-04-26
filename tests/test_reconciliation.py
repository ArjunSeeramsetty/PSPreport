from psp_pipeline.pipelines.reconciliation import compute_variance_pct


def test_variance_pct_nominal():
    value = compute_variance_pct(operational_value=105.0, settlement_value=100.0)
    assert round(value, 2) == 5.0


def test_variance_pct_handles_zero_division():
    assert compute_variance_pct(operational_value=100.0, settlement_value=0.0) is None


def test_variance_pct_handles_missing_inputs():
    assert compute_variance_pct(operational_value=None, settlement_value=100.0) is None

