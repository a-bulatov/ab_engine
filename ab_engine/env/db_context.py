from typing import Callable, Optional
from ..db import DB, sql, JSON, CALLBACK, TUPLE
from .config import Config, LogLevel
from json5 import loads, dumps
from ..db.table import EnvTable
from inspect import iscoroutinefunction
from ..error import raise_error, Error


class Property:

    def __init__(self, getter: Callable, setter: Callable ):
        self._getter = getter
        self._setter = setter

    @property
    def value(self):
        return self._getter()

    @value.setter
    def value(self, value):
        self._setter(value)


class DB_ENV:

    def __init__(self, connection: str="", db_params:Optional[set]=None, **kwargs):
        """
        Окружение для работы с БД
        :param connection: строка соеддинения или экземпляр DB_ENV, на основе которого нужно создать данный
        :param db_params: список переменных, которые должны передаваться в в окружение соединения с БД
        :param kwargs: значения переменных
        """
        self._db_params = set()
        self._params = {}
        if isinstance(connection, DB_ENV):
            env = connection
            self._db_params = env._db_params.copy()
            self._params = env._params.copy()
            connection = env.connection_string
        elif isinstance(connection, DB):
            connection = DB.connection.connection_string
        if db_params:
            self._db_params.update(db_params)
        self._params.update(kwargs)

        if "://" not in connection:
            connection = Config().db_connection(connection)
        if "{" in connection and connection.endswith("}"):
            connection, x = connection.split("{", 1)
            p = loads(f"{{{x}")
            for x in p:
                if not x in self._db_params:
                    self._db_params.add(x)
            if self._params:
                p.update(self._params)
            self._params = p
        self._connection_str = connection
        self._context = None
        self._on_commit = set()

    @property
    def connection_string(self):
        # возвращает строку соединения
        return self._connection_str

    def on_commit(self, callback:Callable, subscribe=True):
        """
        Позволяет добавить или удалить обработчик события подтверждения транзакции
        :param callback: функция, в которую первым атрибутом передается cсылка на окружение
                        если функция вернет False, то commit будет отменен и транзакция откатится (rollback)
        :param subscribe: True указывает, что данный обработчик подписывается на событие (по умолчанию)
        """
        if subscribe:
            self._on_commit.add(callback)
        elif callback in self._on_commit:
            self._on_commit.remove(callback)

    def __getitem__(self, key):
        if not self.has_item(key):
            raise_error("ENV_ATTR_NOT_EXISTS", name=key)
        ret = self._params.get(key)
        return ret.value if isinstance(ret, Property) else ret

    def __setitem__(self, key, value):
        x = self._params.get(key)
        if isinstance(x, Property):
            x.value = value
        else:
            self._params[key] = value

    def has_item(self, key):
        # возвращает True если в данном DB_ENV хранится переменная с именем key
        return key in self._params

    async def __aenter__(self):
        if self._context is not None:
            raise_error("ENV_CONTEXT_EXISTS")
        if self._db_params:
            s = self._connection_str + f"{{{dumps({x:self[x] for x in self._db_params if self.has_item(x)})}}}"
        else:
            s = self._connection_str
        self._context = DB(s)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if not self._context:
            return
        try:
            if not self._context.connection.in_transaction:
                return
            if exc_tb:
                await self.rollback()
            else:
                await  self.commit()
        finally:
            self._context = None

    async def sql(self, query, *args, **kwargs):
        # выполняет команду sql. если на момент вызова соединение с БД (транзакция) закрыто, то создает новое соединение

        def log_callback(q_text):
            cfg=Config()
            if cfg.log_level.value <= LogLevel.SQL.value and cfg.log_level != LogLevel.OFF:
                cfg.log(q_text, LogLevel.SQL)

        if self._context is None:
            await self.__aenter__()

        cmd, query = f"{query} ".split(" ", 1)
        cmd, query = cmd.strip().lower(), query.strip()
        if cmd=="*":
            query = "select * from\n" + query
        elif cmd==r"\call":
            query = await self._context.connection.parse_func(query, **kwargs)
        elif cmd==r"\d":
            return await self._context.connection.table_struct(query.strip())
        elif cmd=="\json":
            query, params = query.split("(", 1)
            if params.lower() in ("json)", "jsonb)"):
                args = (kwargs,) + args
                kwargs = {}
                params = await self._context.connection.cast("$1", params[:-1].lower())
            args = args + (JSON,)
            key = "P_RA+MS_" + str(id(self))
            query = await self._context.connection.parse_func(query, key)
            query = query.replace(f"'{key}'", params)
        elif cmd:
            query = f"{cmd} {query}"

        args = args + (self._context, CALLBACK(callback_function=log_callback, attribute_collection=self),)
        ret = await sql(query,*args, **kwargs)
        return ret

    @property
    def in_transaction(self):
        # возвращает True если в данном DB_ENV открыта транзакция
        return self._context.connection.in_transaction if self._context is not None else False

    async def commit(self):
        # подтверждает транзакцию и закрывает соединение с БД
        try:
            for x in list(self._on_commit):
                if iscoroutinefunction(x):
                    x = await x(self)
                else:
                    x = x(self)
                if x == False and self.in_transaction:
                    await self.rollback()
                    break
        except Exception as e:
            if self.in_transaction:
                self.rollback()
            raise e

        if self.in_transaction:
            await self._context.connection.commit()
        self._context = None

    async def rollback(self):
        # откатывает транзакцию и закрывает соединение с БД
        if self.in_transaction:
            await self._context.connection.rollback()
        self._context = None

    async def table(self, name, page_size=100, async_delay=0.000001, if_not_exists:Optional[list]=None):
        """
        :param name: имя таблицы
        :param page_size: количество строк таблицы, одновременно находящихся в памяти
        :param async_delay: задержка итерации цикла при использовании курсора как итератора
        :param if_not_exists: список команд, которые вызываются, если тавблица не существует
        :return: курсор для работы с таблицей
        """
        if self._context is None:
            await self.__aenter__()
        try:
            t = await EnvTable.create(name, self, page_size=page_size, async_delay=async_delay)
            return t
        except Error as e:
            if not e.code=="NA_TABLE" or not if_not_exists:
                raise e
        if isinstance(if_not_exists, str):
            if_not_exists = [if_not_exists]
        for x in if_not_exists:
            await self.sql(x)
        t = await EnvTable.create(name, self, page_size=page_size, async_delay=async_delay)
        return t

    @staticmethod
    async def garbage_collect():
        """
        сборка мусора и закрытие подвисших соединений
        """
        DB.garbage_collect()