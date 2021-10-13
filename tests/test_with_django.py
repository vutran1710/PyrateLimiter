"""Testing with real redis
"""
from time import sleep

import django_redis
from django.conf import settings
from fakeredis import FakeStrictRedis

from pyrate_limiter import (BucketFullException, Duration, Limiter,
                            RedisBucket, RequestRate)

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

bucket_kwargs = {
    "bucket_name": "my-throttles",
    "redis_pool": redis_connection,
}

rate = RequestRate(2, 10 * Duration.SECOND)

limiter = Limiter(rate, bucket_class=SCRedisBucket, bucket_kwargs=bucket_kwargs)


def test_acquire():
    try:
        for _ in range(5):
            limiter.try_acquire("item-id")
            sleep(2)
    except BucketFullException as e:
        print(e.meta_info)
        assert round(e.meta_info["remaining_time"]) == 6
