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
