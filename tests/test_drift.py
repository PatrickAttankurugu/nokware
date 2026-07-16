from nokware.drift import is_drift


def test_score_drop_is_drift():
    assert is_drift(0.80, baseline=0.95)          # 15.8% relative drop
    assert not is_drift(0.90, baseline=0.95)      # 5.3% drop, under threshold
    assert not is_drift(0.5, baseline=None)       # no baseline, no drift


def test_latency_increase_is_drift():
    assert is_drift(2600, baseline=2000, higher_is_worse=True)
    assert not is_drift(2100, baseline=2000, higher_is_worse=True)
