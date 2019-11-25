class BucketFullException(Exception):
    pass


class InvalidInitialValues(Exception):
    def __init__(self):
        super(InvalidInitialValues, self).__init__()
        self.message = 'Initial values must be a list'
