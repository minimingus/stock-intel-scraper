import math
import pytest
from src.twitter_intel.scorer import _decay_weight


def test_decay_weight_today_is_one():
    assert _decay_weight(0) == pytest.approx(1.0)


def test_decay_weight_90_days_is_half():
    assert _decay_weight(90) == pytest.approx(0.5, rel=0.01)


def test_decay_weight_270_days_is_eighth():
    # 3 half-lives → 0.125
    assert _decay_weight(270) == pytest.approx(0.125, rel=0.01)


from src.twitter_intel.scorer import _frequency_multiplier


def test_frequency_multiplier_low_volume():
    # 1 call/week — value is 1/log(1 + e)
    assert _frequency_multiplier(1.0) == pytest.approx(1 / math.log(1 + math.e), rel=0.01)


def test_frequency_multiplier_decreases_with_volume():
    # Higher frequency → lower multiplier
    assert _frequency_multiplier(50.0) < _frequency_multiplier(1.0)


def test_frequency_multiplier_always_positive():
    for cpw in [0.1, 1.0, 10.0, 100.0]:
        assert _frequency_multiplier(cpw) > 0
