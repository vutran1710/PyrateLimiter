# pylint: disable=C0114,C0115
class BucketFullException(Exception):
    pass


class InvalidParams(Exception):
    def __init__(self, param_name: str):
        super(InvalidParams, self).__init__()
        self.message = 'Parameters missing or invalid:{}'.format(param_name)


class InvalidInitialValues(ValueError):
    def __init__(self):
        super(InvalidInitialValues, self).__init__()
        self.message = 'Initial values must be a list'
