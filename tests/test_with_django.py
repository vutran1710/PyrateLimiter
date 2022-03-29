"""Testing with real redis
"""
from time import sleep

import django_redis
from django.conf import settings
from fakeredis import FakeStrictRedis

from pyrate_limiter import BucketFullException
from pyrate_limiter import Duration
from pyrate_limiter import Limiter
from pyrate_limiter import RedisBucket
from pyrate_limiter import RequestRate

# Mocking django config
settings.configure()

django_redis.DefaultClient = FakeStrictRedis
django_redis.get_redis_connection = lambda _: FakeStrictRedis()

settings.CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://dummy-host",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    }
}


class SCRedisBucket(RedisBucket):
    """Override RedisBucket to use django-redis default client"""

    def get_connection(self):
        return self._pool


# Initialize limiter with django-redis connection
redis_connection = django_redis.get_redis_connection("default")


rate = RequestRate(2, 10 * Duration.SECOND)


def test_acquire(time_function):
    # Separate buckets used to distinct values from previous run,
    # as time_function return value has different int part.
    bucket_kwargs = {
        "bucket_name": str(time_function),
        "redis_pool": redis_connection,
    }

    limiter = Limiter(
        rate,
        bucket_class=SCRedisBucket,
        bucket_kwargs=bucket_kwargs,
        time_function=time_function,
    )

    try:
        for _ in range(5):
            limiter.try_acquire("item-id")
            sleep(2)
    except BucketFullException as err:
        print(err.meta_info)
        assert round(err.meta_info["remaining_time"]) == 6
