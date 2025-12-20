from enum import Enum
from json import dumps
from datetime import datetime
from abc import ABC, abstractmethod
from collections import namedtuple

_is_option = None

def _set_is_option(f):
    global _is_option
    _is_option = f


class RowFactory(Enum):
    """
    Варианты фабрик для возврата набора данных
    """
    ANY = 0
    TUPLE = 1
    DICT = 2
    NAMED_TUPLE = 3


def reencode(s):
    if s is None:
        return " NULL"
    elif isinstance(s, str):
        return f"'{s}'"
    return s


class Driver(ABC):

    LIKE = "LIKE"

    def __init__(self, connection_string, on_open_close=None):
        self._conn = None
        if isinstance(connection_string, Driver):
            self._conn_str = connection_string.connection_string
            self._on_open_close = on_open_close or connection_string._on_open_close
            return
        self._on_open_close = on_open_close
        self._conn_str = connection_string

    @property
    def connection_string(self):
        return self._conn_str

    @property
    def in_transaction(self)->bool:
        """возвращает открыта ли транзакция"""
        return self._conn is not None

    async def _before_open(self)->dict:
        if self._conn:
            raise RuntimeError("Transaction already open")
        if x := self._on_open_close:
            params = await x(False)
            if not params:
                params = {}
        else:
            params = {}
        return params

    @abstractmethod
    async def begin(self):
        """открывает транзакцию"""
        ...

    @abstractmethod
    async def sql(self, query, one_row=False, row_factory=RowFactory.DICT):
        """выполняет запрос
        query текст запроса
        one_row если True, то выполняется fetchone иначе fetch
        row_factory способ представления результата
        если набор данных пустой и one_row==False - возвращает []
        если набор данных пустой и one_row==True - возвращает None
        если запрос не возвращает результат - возвращает число обработанных строк (целое)
        """
        ...

    @abstractmethod
    async def commit(self):
        """подтверждает транзакцию и закрывает соединение"""
        ...

    async def rollback(self):
        """откатывает транзакцию и закрывает соединение"""
        if x:=self._on_open_close:
            await x(True)
        self._conn = None

    @staticmethod
    def var_to_sql(var, str_after=" "):
        if var is None:
            return " NULL"
        elif isinstance(var, str):
            var = var.replace("'", "''")
            return reencode(var)
        elif isinstance(var, (list, tuple)):
            if str_after[:6].lower() == '::json' or str_after[0] != ':':
                var = dumps(var, ensure_ascii=False).replace("'", "''")
                return reencode(var)
            else:
                var = ','.join(['NULL' if x is None else str(x) for x in var])
                return reencode(var)
        elif isinstance(var, set):
            var = ','.join('NULL' if x is None else str(x) for x in var)
            return reencode(var)
        elif isinstance(var, dict):
            var = dumps(var, ensure_ascii=False).replace("'", "''")
            return reencode(var)
        elif isinstance(var, datetime):
            return f" '{var}'"
        else:
            return f" {var}"

    async def parse_query(self, query, *args, **kwargs):
        """подставляет параметры в текст запроса"""
        if callback:=kwargs.get("__PARAM_CALLBACK_GETTER"):
            del kwargs["__PARAM_CALLBACK_GETTER"]
        qs = None
        for x in query.split("$"):
            if qs is None:
                qs = x
                continue
            n, p = '', 0
            if str(x[p]).isdigit():
                while p < len(x) and x[p].isdigit():
                    n += x[p]
                    p += 1
                n = int(n) - 1
                if n < 0 or n >= len(args):
                    raise AttributeError(f"Attribute with index {n} is not exists")
                n = args[n]
            else:
                while p < len(x) and not(x[p].isspace() or x[p] in "(:,)"):
                    n += x[p]
                    p += 1
                if n in kwargs:
                    n = kwargs[n]
                elif callback:
                    n = callback[n]
                else:
                    raise AttributeError(f"Attribute with name {n} is not exists")
            qs += f"{self.var_to_sql(n, x)}{x[p:]}"
            
        if qs:
            query = qs

        return query

    @staticmethod
    def is_option(what):
        global _is_option
        if _is_option:
            return _is_option(what)
        else:
            return None

    async def parse_func(self, func_name, *args, **kwargs):
        """
        Возвращает запрос для вызова функции func_name
        :param args: неименованные параметры
        :param kwargs: именованные параметры
        :return: запрос
        """
        ret = f"select {func_name}("
        for n in range(len(args)):
            if self.is_option(args[n]):
                break
            if n > 0:
                ret += ", "
            ret += f"${n+1}"
        for n, x in enumerate(kwargs):
            if n > 0:
                ret += ", "
            ret += f"${x}"
        ret += ")"
        return await self.parse_query(ret, *args, **kwargs)

    async def cast(self, param_name, to_type):
        """
        возвращает часть запроса для приведения типа
        :param param_name:
        :param to_type:
        :return:
        """
        return f"{param_name}::{to_type}"

    @staticmethod
    def ident_name(name:str)->str:
        return name

    TypeSpec = namedtuple("TypeSpec", ["type_name", "python_type", "autoincrement"])

    @staticmethod
    def _specify_type(defs):
        if defs.data_type in ("smallint", "integer", "bigint", "smallserial", "serial", "bigserial", "int"):
            pt = int
        elif defs.data_type in ("double precision", "numeric", "real", "decimal", "money", "float"):
            pt = float
        else:
            pt = str
        return Driver.TypeSpec(type_name=defs.data_type, python_type=pt, autoincrement=False)

    async def table_struct(self, table_name) -> dict:
        """
        возвращает структуру заданной таблицы
        """
        if not self.in_transaction:
            await self.begin()
        schema_name, table_name = f"{table_name}.".split(".", 1)
        if table_name=="":
            table_name = self.ident_name(schema_name)
            schema_name = None
        else:
            table_name = self.ident_name(table_name[:-1])
            schema_name = self.ident_name(schema_name)
        fltr = f"\nwhere ku.table_name='{table_name}'"
        if schema_name is not None:
            fltr += f" and ku.table_schema='{schema_name}'"
        qry =f"""select ku.column_name, ku.data_type, ku.is_nullable, ku.character_maximum_length, 
                       ku.numeric_precision, ku.numeric_scale, ku.column_default
                from information_schema.columns ku {fltr}
                order by ku.ordinal_position"""
        qry = await self.sql(qry, one_row=False, row_factory=RowFactory.NAMED_TUPLE)
        if not qry:
            return {}
        fields = []
        for x in qry:
            t = self._specify_type(x)
            field = {
                "name": x.column_name,
                "type": t.type_name,
                "not_null": x.is_nullable is not None and f'{x.is_nullable} '[0].upper() in "FNН",
                "python_type": t.python_type,
            }
            if t.autoincrement:
                field["autoincrement"] =True
            n = self.ident_name(field["name"])
            if n!=field["name"]:
                field["field"] = n
            if x.character_maximum_length:
                field["size"] = x.character_maximum_length
            elif field["python_type"]!=int and x.numeric_precision:
                n = f'{x.numeric_precision}.{x.numeric_scale}'
                field["size"] = float(n)
            fields.append(field)
        qry = f"""select
            x.constraint_name,
            x.constraint_type,
            x.column_name,
            x.reference_schema,
            x.reference_table,
            r.column_name reference_column
        from (
            select ku.constraint_name, tc.constraint_type, ku.column_name,
                   rt.table_schema reference_schema, rt.table_name reference_table,
                   row_number() over (partition by ku.constraint_name order by ku.ordinal_position) column_position
            from information_schema.key_column_usage ku
            inner join information_schema.table_constraints tc on tc.constraint_name = ku.constraint_name and tc.table_name = ku.table_name  and tc.table_schema = ku.table_schema
            left join information_schema.referential_constraints rc on rc.constraint_name = ku.constraint_name
            left join information_schema.table_constraints rt on rc.unique_constraint_name = rt.constraint_name
            {fltr}
            order by ku.constraint_name, ku.ordinal_position
            ) x
        left join (
            SELECT
                    tc.table_name, tc.table_schema, i2.COLUMN_NAME,
                    row_number() over (partition by tc.table_name, tc.table_schema order by  i2.ordinal_position) column_position
                FROM
                    information_schema.table_constraints tc
                JOIN
                    information_schema.key_column_usage i2
                    ON tc.constraint_name = i2.constraint_name
                WHERE
                    tc.constraint_type = 'PRIMARY KEY'
        ) r on x.reference_schema = r.table_schema and x.reference_table = r.table_name and x.column_position=r.column_position
        order by x.constraint_name, x.column_position
        """
        qry = await self.sql(qry, one_row=False, row_factory=RowFactory.NAMED_TUPLE)
        constraints = []
        item = {"name": None}
        for x in qry:
            if x.constraint_name!=item["name"]:
                if item["name"] is not None:
                    constraints.append(item)
                t = x.constraint_type[0].upper()
                if t == "P":
                    item = {
                        "name": x.constraint_name,
                        "fields": [],
                        "type": "primary key"
                    }
                elif t == "U":
                    item = {
                        "name": x.constraint_name,
                        "fields": [],
                        "type": "unique"
                    }
                elif t == "F":
                    item = {
                        "name": x.constraint_name,
                        "fields": {},
                        "table": f"{self.ident_name(x.reference_schema)}.{self.ident_name(x.reference_table)}",
                        "type": "foreign key"
                    }
                else:
                    item = {"name": None}
                    continue
            if item["type"][0] == "f":
                item["fields"][x.column_name] = x.reference_column
            else:
                item["fields"].append(x.column_name)
        if item["name"]:
            constraints.append(item)
        return {
            "table": f"{schema_name}.{table_name}" if schema_name else table_name,
            "fields": fields,
            "constraints": constraints
        }

    async def page(self, query, limit, offset):
        query = f"{query}\nlimit {limit}"
        if offset:
            query = f"{query}\noffset {offset}"
        return query

    async def get_position(self, table, key, filter):
        """
        возвращает номер первой строки table, отсортированной по key, соответствующей фильтру filter
        """
        n_field = "co_lu_mn__po_si_ti_on__by__ke_y"
        qry = f"""select row_number() over (order by {key}) {n_field}, t.* from {table} t"""
        qry = f"""select {n_field} from ({qry}) x where {filter} order by {n_field}"""
        x = await self.sql(qry, one_row=True, row_factory=RowFactory.TUPLE)
        if x:
            return x[0]
