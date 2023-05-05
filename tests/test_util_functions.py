from pyrate_limiter.abstracts import Rate
from pyrate_limiter.abstracts import RateItem
from pyrate_limiter.utils import binary_search
from pyrate_limiter.utils import validate_rate_list


def test_binary_search():
    """Testing binary-search that find item in array"""
    # Normal list of items
    items = [RateItem("item", nth * 2) for nth in range(5)]

    for item in items:
        print(item)

    assert binary_search(items, 0) == 0
    assert binary_search(items, 1) == 1
    assert binary_search(items, 2) == 1
    assert binary_search(items, 3) == 2

    # If the value is larger than the last item, idx would be -1
    assert binary_search(items, 11) == -1

    # Empty list
    items = []

    assert binary_search(items, 1) == 0
    assert binary_search(items, 2) == 0
    assert binary_search(items, 3) == 0


def test_rate_validator():
    rates = []
    assert validate_rate_list(rates) is False

    rates = [Rate(1, 1)]
    assert validate_rate_list(rates) is True

    rates = [Rate(2, 1), Rate(1, 1)]
    assert validate_rate_list(rates) is False

    rates = [Rate(1, 1), Rate(2, 1)]
    assert validate_rate_list(rates) is False

    rates = [Rate(1, 1), Rate(2, 2)]
    assert validate_rate_list(rates) is False

    rates = [Rate(2, 1), Rate(3, 2)]
    assert validate_rate_list(rates) is True

    rates = [Rate(1, 1), Rate(3, 2), Rate(4, 1)]
    assert validate_rate_list(rates) is False

    rates = [Rate(2, 1), Rate(3, 2), Rate(4, 3)]
    assert validate_rate_list(rates) is True
