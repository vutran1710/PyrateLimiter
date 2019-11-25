class BucketFullException(Exception):
    pass


class InvalidInitialValues(Exception):
    def __init__(self):
        self.message = 'Initial values must be a list'
