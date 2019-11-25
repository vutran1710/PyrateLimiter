from pyrate_limiter.core import AbstractBucket
from pyrate_limiter.exceptions import InvalidInitialValues


class LocalBucket(AbstractBucket):

    __values__ = []

    def __init__(self, initial_values=[]):
        if initial_values and type(initial_values) != list:
            raise InvalidInitialValues

        self.__values__ = initial_values

    def append(self, item):
        self.__values__.append(item)

    def values(self):
        return self.__values__

    def update(self, new_list):
        self.__values__ = new_list
