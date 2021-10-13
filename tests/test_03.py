"""Testing with real redis
"""
from os import environ
from time import sleep

from django.conf import settings
from django.core.cache import cache
from django_redis import get_redis_connection

from pyrate_limiter import (BucketFullException, Duration, Limiter,
                            MemoryListBucket, RedisBucket, RequestRate)

settings.configure()


class SCRedisBucket(RedisBucket):
    def get_connection(self):
        return self._pool


settings.CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://default:abc123@localhost:6379",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    }
}
pool = get_redis_connection("default")


bucket_kwargs = {"bucket_name": "my-throttles", "redis_pool": pool}

rate = RequestRate(2, 10 * Duration.SECOND)

limiter = Limiter(rate, bucket_class=SCRedisBucket, bucket_kwargs=bucket_kwargs)


def test_acquire():
    try:
        for _ in range(5):
            print(">>>>>> Sleeping")
            sleep(3)
            limiter.try_acquire("item-id")
    except BucketFullException as e:
        print(e.meta_info)


# {'error': 'Bucket for 200019946008641531 with Rate 2/10 is already full', 'identity': '200019946008641531', 'rate': '2/10', 'remaining_time': 82992.52364823502}
