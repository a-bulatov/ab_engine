from abc import ABC
from ..class_tools import classproperty
from .driver import RowFactory, Driver, _set_is_option
from pathlib import Path
from importlib.machinery import SourceFileLoader
from json5 import loads
from asyncio import BoundedSemaphore, wait_for, TimeoutError, sleep
from ..error import raise_error
from inspect import iscoroutinefunction
from typing import Callable
from gc import collect as garbage_collect

DRIVER_CLASSES = {}
_DRIVERS_ = {}
_LIMITS_ = {}
_CFG_ = None

def _check_cfg(key=""):
    global _CFG_
    if _CFG_ is None:
        from ..env import Config
        _CFG_ = Config()
    if key=="":
        return
    if _CFG_.hasattr("defaults"):
        return _CFG_.defaults.get(key)


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
        если вместо формата вернулся None - дальнейшее преобразование невозможно
        """
        return ret_data, row_factory

_set_is_option(Option.is_option)

class ALL(Option):
    ...

class DB(Option):
    """
    Соединение с БД
    """
    _TRASH_ = set()

    def __init__(self, connection_string: str=""):
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
            _check_cfg()
            connection_string = _CFG_.db_connection(connection_string)
        driver_name, connection_string = connection_string.split("://", 1)

        connection_string, conn_params = f"{connection_string}?".split("?",1)

        driver = DRIVER_CLASSES.get(driver_name)
        driver_path = None
        if conn_params:
            conn_params = conn_params[:-1].split("&")
            if "driver_path" in conn_params:
                driver_path = conn_params["driver_path"]
                del conn_params["driver_path"]
            conn_params = "?" + "&".join(conn_params)
        connection_string += conn_params
        if driver is None:
            if driver_path is None:
                driver_path = _check_cfg("db_driver_path")
            if driver_path is None:
                driver_path = Path(__file__).parent / f"driver_{driver_name}.py"
            elif isinstance(driver_path, str):
                driver_path = Path(driver_path) / f"driver_{driver_name}.py"
            m = driver_path.name
            driver_path = str(driver_path)
            if driver_path in _DRIVERS_:
                driver = _DRIVERS_[driver_path]
            else:
                m = m.split(".",1)[0] + f"_{len(_DRIVERS_)}"
                m = SourceFileLoader(m, driver_path ).load_module()
                driver = m.Driver
                _DRIVERS_[driver_path] = driver
        else:
            driver_path = ""

        self._hash = hash(driver_path + connection_string)
        if "LIMIT" in self._params:
            m = self._params["LIMIT"]
            del self._params["LIMIT"]
        else:
            m = 0
        self._conn_limit = None
        self.connection_limit = m
        self._connection = driver(connection_string, self._on_open_close)

    @property
    def connection_limit(self)->int:
        lmt = _LIMITS_.get(self._hash)
        return lmt._value if lmt else 0


    @connection_limit.setter
    def connection_limit(self, value:int):
        """
        Позволяет задать ограничение на количество таких соединений
        """
        if value<=0:
            if self._hash in _LIMITS_:
                del _LIMITS_[self._hash]
            return
        elif lmt:=_LIMITS_.get(self._hash):
            if lmt._waiters:
                lmt._value = value - len(lmt._waiters)
            else:
                lmt._value = value
        else:
            lmt = BoundedSemaphore(value)
            _LIMITS_[self._hash] = lmt
        self._conn_limit = lmt


    async def _on_open_close(self, close=False)->dict:
        if self._conn_limit:
            if close:
                await self._conn_limit.release()
                if self._hash not in _LIMITS_:
                    self._conn_limit = None
            elif self._hash not in _LIMITS_:
                self._conn_limit = None
            else:
                if self._conn_limit.locked():
                    await self.garbage_collect()
                await self._conn_limit.acquire()
        return self._params

    @property
    def connection(self)->Driver:
        return self._connection

    def __del__(self):
        if self.connection is not None and self.connection.in_transaction:
            DB._TRASH_.add(self.connection)

    @classmethod
    async def garbage_collect(cls, clear_mem=True):
        if clear_mem:
            garbage_collect()
        while len(DB._TRASH_)>0:
            x = DB._TRASH_.pop()
            await x.rollback()

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


class ITERATOR(Option):

    def __init__(self, page_size:int=200, async_delay=0.00000001):
        self._page_size = page_size
        self._delay = async_delay
        self._ofs = 0
        self._pos = page_size-1
        self._buf = None
        self._query = None
        self._db = None
        self._row_factory = None
        self._process = None

    def __call__(self, query, db=None, row_factory=RowFactory.DICT, process=None):
        if self._query:
            return None
        self._query = query
        self._db = db
        self._row_factory = row_factory
        self._process = process if isinstance(process, list) else []
        return self

    def __aiter__(self):
        self._ofs = -self._page_size
        self._pos = self._page_size - 1
        self._buf = None
        return self

    async def __anext__(self):
        await sleep(self._delay)
        self._pos += 1
        if self._buf and self._pos >= len(self._buf) and len(self._buf) < self._page_size:
            raise StopAsyncIteration
        elif self._pos >= self._page_size:
            self._ofs += self._page_size
            self._pos = 0
            q = await self._db.connection.page(self._query, self._page_size, self._ofs)
            self._buf = await self._db.connection.sql(q, one_row=False, row_factory=self._row_factory)
            if not self._buf:
                raise StopAsyncIteration
        return self._buf[self._pos]

