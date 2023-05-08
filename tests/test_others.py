from pyrate_limiter.abstracts.rate import Duration
from pyrate_limiter.abstracts.rate import Rate


def test_duration():
    assert int(Duration.SECOND) == 1000
    assert Duration.SECOND.value == 1000

    assert Duration.SECOND * 60 == Duration.MINUTE.value == int(Duration.MINUTE)
    assert Duration.MINUTE * 60 == Duration.HOUR.value == int(Duration.HOUR)
    assert Duration.HOUR * 24 == Duration.DAY.value == int(Duration.DAY)
    assert Duration.DAY * 7 == Duration.WEEK.value == int(Duration.WEEK)


def test_readable_duration():
    assert Duration.readable(300) == "300ms"

    assert Duration.readable(1000) == "1.0s"
    assert Duration.readable(1300) == "1.3s"

    assert Duration.readable(Duration.SECOND * 3.5) == "3.5s"
    assert Duration.readable(Duration.SECOND * 60 * 24 + Duration.SECOND * 30) == "24.5m"

    assert Duration.readable(Duration.MINUTE * 3.5) == "3.5m"
    assert Duration.readable(Duration.MINUTE * 60 + Duration.MINUTE * 30) == "1.5h"

    assert Duration.readable(Duration.HOUR * 3.5) == "3.5h"
    assert Duration.readable(Duration.DAY * 3.5) == "3.5d"
    assert Duration.readable(Duration.WEEK * 3.5) == "3.5w"


def test_rate():
    rate = Rate(1000, Duration.SECOND)
    assert str(rate) == "limit=1000/1.0s"
    assert repr(rate) == "limit=1000/1000"

    rate = Rate(1000, Duration.SECOND * 3)
    assert str(rate) == "limit=1000/3.0s"
    assert repr(rate) == "limit=1000/3000"

    rate = Rate(1000, 3500)
    assert str(rate) == "limit=1000/3.5s"

    rate = Rate(1000, Duration.MINUTE * 3.5)
    assert str(rate) == "limit=1000/3.5m"

    rate = Rate(1000, Duration.MINUTE * 3)
    assert str(rate) == "limit=1000/3.0m"
