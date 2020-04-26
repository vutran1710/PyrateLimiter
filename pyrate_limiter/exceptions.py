# pylint: disable=C0114,C0115


class BucketFullException(Exception):
    pass


class InvalidParams(Exception):
    def __init__(self, param_name: str):
        super(InvalidParams, self).__init__()
        self.message = f'Parameters missing or invalid:{param_name}'


class ImmutableClassProperty(Exception):
    def __init__(self, class_instance, prop: str):
        """ Mutating class property is forbidden
        """
        super(ImmutableClassProperty, self).__init__()
        self.message = f'{class_instance}.{prop} must not be mutated'
