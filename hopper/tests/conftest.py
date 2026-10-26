import pytest

from app import guard


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    """Every test starts with empty rate-limit and Claude-budget counters."""
    guard.reset()
    yield
    guard.reset()
