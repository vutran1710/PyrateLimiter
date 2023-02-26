from datetime import datetime
from logging import basicConfig
from time import monotonic
from time import time

import pytest

# Make log messages visible on test failure (or with pytest -s)
basicConfig(level="INFO")
# Uncomment for more verbose output:
# getLogger("pyrate_limiter").setLevel("DEBUG")


time_functions_params = [
    None,
    monotonic,
    time,
    lambda: datetime.utcnow().timestamp(),
]


@pytest.fixture(params=time_functions_params * 2)
def time_function(request):
    """Parametrization for different time functions."""
    return request.param
