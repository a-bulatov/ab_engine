import sys, os
sys.path.append(os.path.dirname(__file__))
from driver import Driver as BaseDriver, RowFactory
try:
    from mysql.connector.aio import connect
except ImportError:
    raise Exception("For use MySQL driver, you need to install mysql.connector\n$ pip install mysql-connector-python")
from collections import namedtuple

def as_is(description, data):
    return data

def as_dict(description, data):
    fields = [column[0] for column in description]
    if isinstance(data, list):
        for n, row in enumerate(data):
            data[n] = {key: value for key, value in zip(fields, row)}
        return data
    return {key: value for key, value in zip(fields, data)}

def as_namedtuple(description, data):
    fields = [column[0].lower() for column in description]
    cls = namedtuple("Row", fields)
    if isinstance(data, list):
        for n, row in enumerate(data):
            data[n] = cls._make(row)
        return data
    return cls._make(data)

_FACTORY_ = {
    RowFactory.ANY.value: as_is,
    RowFactory.TUPLE.value: as_is,
    RowFactory.DICT.value: as_dict,
    RowFactory.NAMED_TUPLE.value: as_namedtuple,
}


class Driver(BaseDriver):

    def __init__(self, connection_string, on_open_close=None):
        """
        localhost:3306/mysql?user=root&password=root
        """
        if "{" in connection_string:
            connection_string, options = connection_string.split("{", 1)

        super().__init__(connection_string, on_open_close)

        if "/" in self.connection_string:
            x, options = self.connection_string.split("/", 1)
        else:
            x, options = self.connection_string.split("?", 1)
        if ":" in x:
            x, y = x.split(":")
            self._conn_params = {
                "host": x,
                "port": int(y),
            }
        else:
            self._conn_params = {
                "host": x,
                "port": 3306,
            }
        if "?" in options:
            x, options = options.split("?",1)
            self._conn_params["database"] = x
        for x in options.split("&"):
            k, v = x.split("=", 1)
            self._conn_params[k] = v

    async def begin(self):
        await self._before_open()
        self._conn = await connect(**self._conn_params)

    async def sql(self, query, one_row=False, row_factory=RowFactory.DICT):
        if self._conn is None:
            await self.begin()
        cur = await self._conn.cursor()
        try:
            await cur.execute(query)
            descr = cur.description
            if descr:
                descr = descr.copy()
                if one_row:
                    data = await cur.fetchone()
                else:
                    data = await cur.fetchall()
            else:
                return cur.rowcount
        finally:
            try:
                await cur.close()
            except Exception as e:
                pass
        return _FACTORY_[row_factory.value](descr, data)

    async def commit(self):
        if not self._conn:
            raise RuntimeError("Transaction is not open")
        await self._conn.commit()
        await self.rollback()

    async def rollback(self):
        if not self._conn:
            return
        if x := self._on_open_close:
            await x(True)
        await self._conn.close()
        self._conn = None

