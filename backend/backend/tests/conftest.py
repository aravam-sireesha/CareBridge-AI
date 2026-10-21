import pytest

from app.services import security


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    """The sign-in rate limiter keeps counters in memory; every test starts with a clean slate."""
    security.reset_rate_limits()
    yield
    security.reset_rate_limits()
