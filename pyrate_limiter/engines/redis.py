from json import loads, dumps
from pyrate_limiter.core import AbstractBucket


class RedisBucket(AbstractBucket):
    conn = None
    hash = None
    key = None
    __values__ = []

    def __init__(self, uri, hash='hash', key=None):
        from redis import Redis
        self.conn = Redis.from_url(uri)
        self.hash = hash

        if key:
            self.config(key=key)

    def config(self, key='key'):
        self.key = key
        values = self.conn.hget(self.hash, self.key)

        try:
            loaded_values = loads(values)
            if type(loaded_values) != list:
                self.conn.hset(self.hash, key, dumps([]))
                self.__values__ = []
            else:
                self.__values__ = loaded_values
        except Exception:
            self.conn.hset(self.hash, key, dumps([]))
            self.__values__ = []

    def append(self, item):
        self.__values__.append(item)
        self.conn.hset(self.hash, self.key, dumps(self.__values__))

    def values(self):
        return self.__values__

    def update(self, new_list):
        self.conn.hset(self.hash, self.key, dumps(new_list))
        self.__values__ = new_list
