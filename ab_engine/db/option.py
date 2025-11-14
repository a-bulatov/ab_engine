from abc import ABC
from ..class_tools import classproperty
from .driver import RowFactory, Driver, _set_is_option
from pathlib import Path
from importlib.machinery import SourceFileLoader
from json5 import loads
from asyncio import BoundedSemaphore, wait_for, TimeoutError
from ..error import raise_error
from inspect import iscoroutinefunction
from typing import Callable

_DRIVERS_ = {}
_LIMITS_ = {}
_CFG_ = None

def _check_cfg():
    global _CFG_
    if _CFG_ is None:
        from ..env import Config
        _CFG_ = Config()
    return _CFG_

class Option(ABC):

    @staticmethod
    def is_option(x):
        if isinstance(x, Option):
            return True
        while hasattr(x, "__base__"):
            if x.__base__ == Option:
                return True
            x = x.__base__
        return False

    @classproperty
    def row_factory(cls)->RowFactory:
        return RowFactory.ANY

    @classproperty
    def can_process(cls):
        return False

    @classproperty
    def one_row(cls):
        return None

    @staticmethod
    async def process(ret_data, connection, row_factory):
        """
        Возвращает преобразованный набор данных и формат
        если вместо формата вернулся Nonme - дальнейшее преобразование невозможно
        """
        return ret_data, row_factory

_set_is_option(Option.is_option)

class ALL(Option):
    ...

class DB(Option):
    """
    Соединение с БД
    """
    def __init__(self, connection_string: str):
        connection_string = connection_string.strip()
        if connection_string.startswith("jdbc:"):
            connection_string = connection_string[5:]
        if connection_string.endswith("}"):
            connection_string, params = connection_string.split("{",1)
            self._params = loads(f"{{{params}")
            for x in tuple(self._params.keys()):
                if "$" in x:
                    v = self._params[x]
                    del self._params[x]
                    self._params[x.replace("$",".")] = v
        else:
            self._params = {}
        if "://" not in connection_string:
            connection_string = _check_cfg().db_connection(connection_string)
        driver, connection_string = connection_string.split("://", 1)

        connection_string, conn_params = f"{connection_string}?".split("?",1)
        driver_path = None
        if conn_params:
            conn_params = conn_params[:-1].split("&")
            if "driver_path" in conn_params:
                driver_path = conn_params["driver_path"]
                del conn_params["driver_path"]
            else:
                driver_path = _check_cfg().defaults.get("db_driver_path")
            conn_params = "?" + "&".join(conn_params)
        connection_string += conn_params

        if driver_path is None:
            driver_path = Path(__file__).parent / f"driver_{driver}.py"
        elif isinstance(driver_path, str):
            driver_path = Path(driver_path) / f"driver_{driver}.py"
        m = driver_path.name
        driver_path = str(driver_path)
        if driver_path in _DRIVERS_:
            driver = _DRIVERS_[driver_path]
        else:
            m = m.split(".",1)[0] + f"_{len(_DRIVERS_)}"
            m = SourceFileLoader(m, driver_path ).load_module()
            driver = m.Driver
            _DRIVERS_[driver_path] = driver
        if "LIMIT" in self._params:
            m = self._params["LIMIT"]
            del self._params["LIMIT"]
        else:
            m = 0
        if m > 0:
            if lmt:=_LIMITS_.get(driver_path + connection_string):
                if lmt._waiters:
                    lmt._value = m - len(lmt._waiters)
                else:
                    lmt._value = m
            else:
                lmt = BoundedSemaphore(m)
                _LIMITS_[driver_path + connection_string] = lmt
            self._conn_limit = lmt
        self._connection = driver(connection_string, self._on_open_close)

    async def _on_open_close(self, close=False)->dict:
        if hasattr(self, "_conn_limit"):
            if close:
                await self._conn_limit.release()
            else:
                await self._conn_limit.acquire()
        return self._params

    @property
    def connection(self)->Driver:
        return self._connection

class TIMEOUT(Option):

    def __init__(self, time_sec:float, raise_error:bool=True):
        self._time_sec = time_sec
        self._raise_error = raise_error

    async def __call__(self, func):
        try:
            return await wait_for(func, self._time_sec)
        except TimeoutError as e:
            if self._raise_error:
                raise e
            return None

class DICT(Option):
    """
    Указывает, что результат следует вернуть как список dict (по умолчанию)
    """
    @classproperty
    def row_factory(cls) -> RowFactory:
        return RowFactory.DICT

class TUPLE(Option):
    """
    Указывает, что результат следует вернуть как список tuple
    """
    @classproperty
    def row_factory(cls) -> RowFactory:
        return RowFactory.TUPLE

class OBJECT(Option):
    """
    Указывает, что результат следует вернуть как список namedtuple
    """
    @classproperty
    def row_factory(cls) -> RowFactory:
        return RowFactory.NAMED_TUPLE

class ROW(Option):
    """
    Указывает, что нужно вернуть только первую строку из выборки
    """
    @classproperty
    def one_row(cls):
        return True

class ONE(ROW):
    """
    Указывает, что нужно вернуть только значение первого поля из первой строки выборки
    """
    @classproperty
    def can_process(cls):
        return True

    @staticmethod
    async def process(ret_data, connection, row_factory):
        if isinstance(ret_data, (int, None.__class__)):
            return ret_data, None
        match row_factory:
            case RowFactory.TUPLE:
                return ret_data[0], None
            case RowFactory.DICT:
                return ret_data[tuple(ret_data.keys())[0]], None
            case RowFactory.NAMED_TUPLE:
                x = ret_data._fields
                if len(x) < 1:
                    return None, None
                x = x[0]
                return getattr(ret_data, x), None
            case _:
                return ret_data, None

class JSON(ONE):
    """
    Указывает, что значение первого поля в первой строке следует привести к dict или list
    """
    @staticmethod
    async def process(ret_data, connection, row_factory):
        ret_data, _ = await ONE.process(ret_data, connection, row_factory)
        if isinstance(ret_data, (dict, list)):
            return ret_data, None
        elif isinstance(ret_data, str):
            return loads(ret_data), None
        else:
            raise_error("NOT_CONV_DICT_LIST", data=ret_data)

class ROLLBACK(Option):
    """
    Указывает, что после выполнения запроса соединение должно быть закрыто с откатом транзакции
    """
    @classproperty
    def can_process(cls):
        return True

    @staticmethod
    async def process(ret_data, connection, row_factory):
        if connection.in_transaction:
            await connection.rollback()
        return ret_data, row_factory

class COMMIT(Option):
    """
    Указывает, что после выполнения запроса соединение должно быть закрыто с подтверждением транзакции
    """
    @classproperty
    def can_process(cls):
        return True

    @staticmethod
    async def process(ret_data, connection, row_factory):
        if connection.in_transaction:
            await connection.commit()
        return ret_data, row_factory

class PAGE(Option):

    def __init__(self, limit:int, offset:int=0):
        """
        Ограничивает количество записей на странице и задает смещение первой записи страницы от начала выборки
        :param limit: максимальное количество строк
        :param offset: смещение от начала
        """
        if not(isinstance(limit, int) and isinstance(offset, int)) or limit < 0 or offset < 0:
            raise_error("BAD_LIMIT_OFFSET")
        self._limit = limit
        self._offset = offset

    async def __call__(self, connection, query):
        query = await connection.page(query, self._limit, self._offset)
        return query

    def __str__(self):
        return f"PAGE(limit={self._limit}, offset={self._offset})"


class CALLBACK(Option):

    def __init__(self, callback_function:Callable, attribute_collection=None, *args, **kwargs):
        """
        Позволяет вернуть запрос с подставленными параметрами из функции sql и доработать его или вывести в лог
        если callback_function возвращает строку, то именно эта строка станет запросом
        :param callback_function: ссылка на функцию, которой передается текст запроса
        """
        self._callback = callback_function
        self._args = args
        self._kwargs = kwargs
        self._attrs = attribute_collection

    async def __call__(self, query):
        if not self._callback:
            return query
        if iscoroutinefunction(self._callback):
            x = await self._callback(query, *self._args, **self._kwargs)
        else:
            x = self._callback(query, *self._args, **self._kwargs)
        return x or query

    def __getitem__(self, item):
        if self._attrs is None:
            raise_error("ATTR_NOT_FOUND", name=item)
        return self._attrs[item]
