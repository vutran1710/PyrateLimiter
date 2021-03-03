from logging import getLogger

# Make log messages visible on test failure (or with pytest -s)
getLogger("pyrate_limiter").setLevel("DEBUG")
