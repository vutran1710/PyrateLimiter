from datetime import datetime
from logging import getLogger
from time import monotonic, time

import pytest

# Make log messages visible on test failure (or with pytest -s)
getLogger("pyrate_limiter").setLevel("DEBUG")


@pytest.fixture(
    params=[
        None,
        monotonic,
        time,
        lambda: datetime.utcnow().timestamp(),
    ]
)
def time_function(request):
    """Parametrization for different time functions."""
    return request.param
