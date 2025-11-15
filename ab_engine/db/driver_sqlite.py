import sys, os
sys.path.append(os.path.dirname(__file__))
from driver import Driver as BaseDriver, RowFactory
from sqlite3 import connect as db_connect
from collections import namedtuple, OrderedDict


def dict_factory(cursor, row):
    fields = [column[0] for column in cursor.description]
    return {key: value for key, value in zip(fields, row)}


def namedtuple_factory(cursor, row):
    fields = [column[0] for column in cursor.description]
    cls = namedtuple("Row", fields)
    return cls._make(row)

_Info = namedtuple("Info", ["column_name", "data_type", "is_nullable", "character_maximum_length",
                       "numeric_precision", "numeric_scale", "column_default", "autoincrement", "pk"])

def _field_ifo_tuples(fields, str_fields):
    str_fields = str_fields["sql"].split("\n", 1)[1][:-1].strip().split("\n")
    str_def = {}
    for x in str_fields:
        n, x = x.strip().split(" ", 1)
        str_def[n] = x
    for n, row in enumerate(fields):
        if "(" in row["type"]:
            sz = row["type"].split("(")[1][:-1]
            sz = int(sz)
        else:
            sz = None
        ai = str_def[row["name"]]
        fields[n] = _Info(column_name=row["name"], data_type=row["type"].lower(), character_maximum_length=sz,
                          column_default=row["dflt_value"], is_nullable=row["notnull"] == 0 and row["pk"] == 0,
                          autoincrement=" autoincrement" in ai, pk=row["pk"],
                          numeric_precision=None, numeric_scale=None)
    return fields

_FACTORY_ = {
    RowFactory.ANY.value: None,
    RowFactory.TUPLE.value: None,
    RowFactory.DICT.value: dict_factory,
    RowFactory.NAMED_TUPLE.value: namedtuple_factory,
}

class Driver(BaseDriver):

    def __init__(self, connection_string, on_open_close=None):
        """
        test_db.sqlite
        """
        super().__init__(connection_string, on_open_close)

    async def begin(self):
        await self._before_open()
        self._conn = db_connect(self.connection_string)

    async def sql(self, query, one_row=False, row_factory=RowFactory.DICT):
        if self._conn is None:
            await self.begin()
        acur = self._conn.cursor()
        if x:=_FACTORY_[row_factory.value]:
            acur.row_factory = x
        acur.execute(query)
        descr = acur.description
        if not descr:
            return acur.rowcount
        if one_row:
            ret = acur.fetchone()
        else:
            ret = acur.fetchall()
            if not ret:
                ret = []
        return ret

    async def commit(self):
        if not self._conn:
            raise RuntimeError("Transaction is not open")
        self._conn.commit()
        await self.rollback()

    async def rollback(self):
        if not self._conn:
            return
        self._conn.close()
        await super().rollback()

    async def table_struct(self, table_name) -> dict:
        defs = await self.sql(f"select sql from sqlite_master where type='table' and name='{table_name}'", one_row=True)
        if not defs:
            return None
        fields = await self.sql(f"PRAGMA table_info('{table_name}')")
        fields, pk, defs = [], [], _field_ifo_tuples(fields, defs)
        for x in defs:
            t = self._specify_type(x)
            field = {
                "name": x.column_name,
                "type": t.type_name,
                "not_null": x.is_nullable is not None and f'{x.is_nullable} '[0].upper() in "FNН",
                "python_type": t.python_type,
            }
            if t.autoincrement or x.autoincrement:
                field["autoincrement"] = True
            n = self.ident_name(field["name"])
            if n != field["name"]:
                field["field"] = n
            if x.character_maximum_length:
                field["size"] = x.character_maximum_length
            elif field["python_type"] != int and x.numeric_precision:
                n = f'{x.numeric_precision}.{x.numeric_scale}'
                field["size"] = float(n)
            if x.pk:
                while len(pk) < x.pk:
                    pk.append(None)
                pk[x.pk-1] = x.column_name
            fields.append(field)
        constraints = []
        if pk:
            constraints.append({
                "type": "primary key",
                "fields": pk
            })
        defs = await self.sql(f"PRAGMA foreign_key_list('{table_name}')")
        fk = {}
        for x in defs:
            k = fk.get(x["id"], {"type": "foreign key", "table":x["table"], "fields":OrderedDict()})
            k["fields"][x["from"]] = x["to"]
            fk[x["id"]] = k
        for x in fk:
            constraints.append(fk[x])

        defs = await self.sql(f"select sql from sqlite_master where type = 'index'  and sql like '%UNIQUE INDEX % on {table_name} %'",
                              row_factory=RowFactory.TUPLE)
        for x in defs:
            x = x[0].split("(",1)[1][:-1]
            constraints.append({
                "type": "unique",
                "fields": [f.strip() for f in x.split(",")],
            })
        return {
            "table": table_name,
            "fields": fields,
            "constraints": constraints
        }