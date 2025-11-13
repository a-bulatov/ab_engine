class ClassPropertyDescriptor(object):

    def __init__(self, fget, fset=None):
        self.fget = fget
        self.fset = fset

    def __get__(self, obj, klass=None):
        if klass is None:
            klass = type(obj)
        return self.fget.__get__(obj, klass)()

    def __set__(self, obj, value):
        if not self.fset:
            raise AttributeError("can't set attribute")
        type_ = type(obj)
        return self.fset.__get__(obj, type_)(value)

    def setter(self, func):
        if not isinstance(func, (classmethod, staticmethod)):
            func = classmethod(func)
        self.fset = func
        return self

def classproperty(func):
    if not isinstance(func, (classmethod, staticmethod)):
        func = classmethod(func)

    return ClassPropertyDescriptor(func)

def find_subclass(base, name):
    if base.__name__ == name:
        return base
    for cls in base.__subclasses__():
        cls = find_subclass(cls, name)
        if cls:
            return cls
    return None


class ReadOnlyPropDict:

    def __init__(self,  **kwargs):
        self._data = kwargs
        for x in kwargs:
            self._set_f(x)

    def _set_f(self, x):
        setattr(self.__class__, x, property(lambda p: self._data[x]))

    def __getitem__(self, item):
        return self._data[item]


class PropDict(ReadOnlyPropDict):

    def _set_f(self, x):
        def set_f(p, v):
            self._data[x] = v
        setattr(self.__class__, x, property(lambda p: self._data[x], set_f))