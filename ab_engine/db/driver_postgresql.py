import sys, os
sys.path.append(os.path.dirname(__file__))
from driver import Driver as BaseDriver, RowFactory
from psycopg import AsyncConnection
import psycopg.rows as rows


_FACTORY_ = {
    RowFactory.ANY.value: rows.tuple_row,
    RowFactory.TUPLE.value: rows.tuple_row,
    RowFactory.DICT.value: rows.dict_row,
    RowFactory.NAMED_TUPLE.value: rows.namedtuple_row,
}

def _col_type(col_type, type_cat):
    if type_cat == "S":
        return str
    elif type_cat == "N":
        if col_type in ("smallint", "integer", "bigint", "smallserial", "serial", "bigserial"):
            return int
        else:
            return float
    return str

class Driver(BaseDriver):

    LIKE = "ILIKE"

    def __init__(self, connection_string, on_open_close=None):
        """
        localhost:5432/postgres?user=postgres&password=postgres
        """
        super().__init__(connection_string, on_open_close)
        host, options = self.connection_string.split("/", 1)
        if ":" in host:
            host, port = host.split(":", 1)
            port = int(port.strip())
        else:
            port = None
        options = options.split("?", 1)
        dbname = options[0]
        if len(options) == 2:
            options = options[1].replace("&", " ")
        else:
            options = ""
        self._conn_str = f"host={host} dbname={dbname}"
        if port is not None:
            self._conn_str += f" port={port}"
        if options != "":
            self._conn_str += " " + options

    @property
    def in_transaction(self):
        return self._conn is not None

    async def begin(self):
        params = await self._before_open()
        self._conn = await AsyncConnection.connect(self.connection_string)
        for x in params:
            if x == "TIMEZONE":
                await self._conn.execute(f"set session timezone '{params[x]}'")
            else:
                await self._conn.execute(f"SET {x} = '{params[x]}'")

    async def sql(self, query, one_row=False, row_factory=RowFactory.DICT):
        if self._conn is None:
            await self.begin()
        async with self._conn.cursor() as acur:

            acur.row_factory = _FACTORY_[row_factory.value]

            await acur.execute(query)
            descr = acur.description
            if not descr:
                return acur.rowcount
            if one_row:
                ret = await acur.fetchone()
            else:
                ret = await acur.fetchall()
                if not ret:
                    ret = []
        return ret

    async def commit(self):
        if not self._conn:
            raise RuntimeError("Transaction is not open")
        await self._conn.commit()
        await self.rollback()

    async def rollback(self):
        if not self._conn:
            return
        await self._conn.close()
        await super().rollback()

    @staticmethod
    def _specify_type(defs):
        if defs.column_default and str(defs.column_default).startswith("nextval("):
            if defs.data_type == "integer":
                return BaseDriver.TypeSpec(type_name="serial", python_type=int, autoincrement=True)
            elif defs.data_type == "bigint":
                return BaseDriver.TypeSpec(type_name="bigserial", python_type=int, autoincrement=True)
            elif defs.data_type == "smallint":
                return BaseDriver.TypeSpec(type_name="smallserial", python_type=int, autoincrement=True)
        return BaseDriver._specify_type(defs)

    @staticmethod
    def ident_name(name: str) -> str:
        """
            Эмулирует поведение PostgreSQL функции quote_ident().
            """
        if name is None:
            return "NULL"
        # Проверяем, является ли строка валидным идентификатором
        if (name[0].isalpha() or name[0] == '_') \
                and all(char.isalnum() or char == '_' for char in name) \
                and name == name.lower():
            return name
        # Удваиваем существующие двойные кавычки
        name = name.replace('"', '""')
        # Заключаем в двойные кавычки
        return f'"{name}"'