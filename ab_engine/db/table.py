from ..class_tools import ReadOnlyPropDict
from .option import DB, PAGE, ONE, ROW, DICT, TUPLE, OBJECT, ALL
from ..error import raise_error
from .processor import sql
import asyncio


class ROW(ReadOnlyPropDict):

    def __str__(self):
        s = ""
        for x in self._data:
            v = str(self._data[x].value).replace("\t","    ")
            s += f" {x}: {v}" + "\t"
        return s[:-1]

    def __getitem__(self, item):
        if item not in self._data:
            raise_error("FIELD_NOT_FOUND", name=item)
        return self._data[item]


class Field:

    class _Condition:

        class Name(str):
            ...

        @staticmethod
        def _lquot(p_type, v):
            if v is None:
                return "NULL"
            elif isinstance(v, Field._Condition.Name):
                return v
            v = str(v)
            if p_type not in (int, float, bool):
                v = f"""'{v.replace("'","''")}'"""
            return v

        def __init__(self, left, op, right):
            if isinstance(right, Field):
                if right._table == left._table:
                    right = Field._Condition.Name(right.name)
                right = right.value
            if not isinstance(left, Field):
                raise_error("NOT_LFIELD")
            elif op in ("%", "//"):
                x = left._table._db.connection.LIKE
                op = x if op == "%" else f"NOT {x}"
                if left._p_type!=str:
                    raise_error("BAD_OP_FOR", op=op, name=str(left._p_type))
                elif not isinstance(right, (str, Field._Condition.Name)):
                    raise_error("BAD_OP_FOR", op=op, name=str(right))
                right = self._lquot(left._p_type, right)
            elif isinstance(right, (list, set, tuple)):
                if op not in ("==", "!=", "in"):
                    raise_error("BAD_OP_FOR", op=op, name=str(right))
                elif op == "!=":
                    op = "not in"
                else:
                    op = "in"
                right = ",".join([self._lquot(left._p_type, x) for x in right])
            elif right is None:
                if op not in ("==", "!="):
                    raise_error("BAD_OP_FOR", op=op, name=str(right))
                elif op == "==":
                    op = "is"
                else:
                    op = "is not"
                self._qry = f"{left()} {op} NULL"
                return
            else:
                right = self._lquot(left._p_type, right)
            self._extras = []
            self._qry = f"{left()} {op} {right}"

        def __or__(self, other):
            self._extras.append(('or', other))
            return self

        def __and__(self, other):
            self._extras.append(('and', other))
            return self

        def __call__(self):
            q = self._qry
            for x in self._extras:
                q += f" {x[0]} {x[1]} "
            if self._extras:
                q = f"({q})"
            return q

        def __repr__(self):
            return self()

    def __init__(self, defs: dict, table):
        self._table = table
        self._p_type = defs.get("python_type")
        self._db_type = defs.get("type")
        self._name = defs.get("name")
        self._not_null = defs.get("not_null", False)
        x = defs.get("field")
        if x and self._name!=x:
            self._in_db_name=defs.get("field")

    def __repr__(self):
        return f"{self.table.name}.{self.name}"

    @property
    def table(self):
        """ссылка на таблицу, к которой относится поле"""
        return self._table

    @property
    def name(self):
        """имя поля"""
        return self._name

    @property
    def python_type(self):
        """тип python, соответствующий значениям поля"""
        return self._p_type

    @property
    def not_null(self):
        """признак того, что поле не может принимать значение None"""
        return self._not_null

    @property
    def value(self):
        """возвращает значение поля"""
        ptr = self._table._ptr
        buf = self._table._page
        if buf is None or len(buf)<=ptr or ptr<0:
            return None
        return buf[ptr][self.name]

    @value.setter
    def value(self, value):
        """устанавливает значение поля"""
        if self.table._key == 1:
            raise_error("NA_PK", name = self._table.name)
        if self.python_type is None:
            raise_error("NOT_ERD_DT", name = self._db_type)
        ptr = self.table._ptr
        buf = self.table._page
        if buf is None or len(buf) <= ptr or ptr < 0:
            raise_error("BAD_CURSOR", table=self.table.name)
        if value is None and self._not_null:
            raise_error("NOT_NULL", name=self.name)
        else:
            value = self.python_type(value)
        if buf[ptr][self.name]!=value:
            self.table._field_changed(ptr, self.name)
            buf[ptr][self.name] = value

    def __lt__(self, other):
        return Field._Condition(self, "<", other)

    def __le__(self, other):
        return Field._Condition(self, "<=", other)

    def __eq__(self, other):
        return Field._Condition(self, "=", other)

    def __ne__(self, other):
        return Field._Condition(self, "!=", other)

    def __gt__(self, other):
        return Field._Condition(self, ">", other)

    def __ge__(self, other):
        return Field._Condition(self, ">=", other)

    def __contains__(self, other):
        return Field._Condition(self, "in", other)

    def __mod__(self, other):
        return Field._Condition(self, "%", other)

    def __floordiv__(self, other):
        return Field._Condition(self, "//", other)

    def __call__(self, *args, **kwargs):
        if hasattr(self, "_in_db_name"):
            return self._in_db_name
        return self.name

    async def _agg_query(self, field_agg):
        q = f"select {field_agg} from {self.table.name}"
        if self.table._filter:
            q = f"{q} where {self.table._filter}"
        ret = await sql(q, self.table._db, ONE)
        if self.table._auto_close_conn:
            self.table._db.rollback()
        return ret

    async def min(self):
        """возвращает минимальное значение поля с учетом текущего фильтра таблицы"""
        return await self._agg_query(f"min({self()})")

    async def max(self):
        """возвращает максимальное значение поля с учетом текущего фильтра таблицы"""
        return await self._agg_query(f"max({self()})")

    async def avg(self):
        """возвращает среднее значение поля с учетом текущего фильтра таблицы"""
        return await self._agg_query(f"avg({self()})")

    async def sum(self):
        """возвращает сумму значений поля с учетом текущего фильтра таблицы"""
        return await self._agg_query(f"sum({self()})")

    async def count(self):
        """возвращает количество уникальных значений поля с учетом текущего фильтра таблицы"""
        return await self._agg_query(f"count(distinct {self()})")


class Table:

    class _FILTER(ALL):
        ...

    def __init__(self, table_struct:dict, db:DB, page_size=100, auto_close_conn=True, async_delay=0.001):
        self._table = table_struct["table"]
        self._db = db
        self._delay = async_delay
        self._page_size = page_size
        self._auto_close_conn = auto_close_conn
        self._ptr = None
        self._changed = set()
        self._offset = 0
        self._page = None
        self._filter = ""
        self._row = ROW(**{x["name"]:Field(x, self) for x in table_struct.get("fields", [])})
        self._key = 1
        constraint = table_struct.get("constraints")
        for x in  constraint:
            if x["type"]=="primary key":
                self._key_fields = x["fields"]
                self._key = ', '.join(self._row[f]() for f in self._key_fields)
                break
        if self._key == 1:
            for x in constraint:
                if x["type"] == "unique":
                    self._key_fields = x["fields"]
                    self._key = ', '.join(self._row[f]() for f in self._key_fields)
                    break

    @property
    def key(self):
        """
        :return:  имя ключа или список полей составного ключа
        """
        if self._key==1:
            return None
        if isinstance(self._key_fields, list) and len(self._key_fields)==1:
            return self._key_fields[0]
        return self._key_fields

    @key.setter
    def key(self, value):
        """
        позволяет установить имя ключа или список имен полей составного ключа, отличный от
        полученного из БД при инициализации таблицы
        """
        if isinstance(value, Field):
            value = [value.name,]
        elif isinstance(value, str):
            value = [value,]
        elif isinstance(value, (list,tuple,set)):
            value = list(value)
        else:
            raise_error("ER_KEY_LST")
        for x in value:
            self.row[x]
        self._key_fields = value
        self._key = ', '.join(self._key_fields)

    def _field_changed(self, ptr, field):
        self._changed.add(ptr)

    @property
    def field_names(self)->tuple:
        """
        :return:  tuple с именами полей таблицы
        """
        return tuple(self.row._data.keys())

    @property
    def name(self):
        """
        :return: имя таблицы
        """
        return self._table

    @property
    def row(self) -> ROW:
        """
        поля текущей строки таблице, к полям можно оброщаться через строковое имя в квадратных скобках, либо по имени через точку
        т.е. t.row.id и t.row["id"] это одно и то же
        """
        return self._row

    @classmethod
    async def create(cls, table_name, db:DB, page_size=100, auto_close_conn=True, async_delay=0.0001):
        """
        Создает объект для работы с указанной таблицей.
        При работе таблица сортируется по ключу, если ключа нет, то по первому полю
        :param table_name: Иья таблицы
        :param db: опция DB для соединения с БД
        :param page_size: размер окна для чтения таблицы
        :param auto_close_conn: если True, то соединение автоматически закрывается после каждого чтения или записи таблицы
        :param async_delay: время передачи управления другим процессам при использовании таблицы как итератора
        :return:
        """
        table_struct = await db.connection.table_struct(table_name)
        if table_struct is None:
            raise_error("NA_TABLE", name=table_name)
        if auto_close_conn:
            await db.connection.rollback()
        t = cls(table_struct, db, page_size, auto_close_conn, async_delay)
        await t.first()
        return t

    @property
    def position(self):
        """строка, на которой стоит курсор (счет с 0)"""
        return self._offset + (self._ptr or 0)


    async def seek(self, *args, **kwargs):
        if kwargs or len(args) != 1 or (len(args) > 1 and not isinstance(args[0], int)):
            if self._filter:
                self._filter = ""
                await self.first()
            f = self._gen_filter(*args, **kwargs)
            position = await self._db.connection.get_position(self._table, ','.join(self._key_fields), f)
            if position:
                position -= 1
            else:
                position = 0
        else:
            position = args[0]
        """устанавливает курсор на заданную строку"""
        if position == 0:
            await self.first()
            return True
        elif position < 0:
            cnt = await sql(f"select count(*) from {self._table} {self._filter}", self._db, ONE)
            position = cnt + position
            if position < 0:
                position = 0
        else:
            cnt = None
        need_ofs = (position // self._page_size) * self._page_size
        need_ptr = position - need_ofs
        if need_ofs == self._offset:
            self._ptr = need_ptr
            if cnt is not None and self._auto_close_conn:
                await self._db.connection.rollback()
            return True
        if self._page:
            await self.save()
        self._page = await self(Table._FILTER, PAGE(self._page_size + 1, need_ofs))
        if not self._page:
            await self.last()
            return False
        self._ptr = need_ptr
        self._offset = need_ofs
        return True

    async def next(self):
        """
        переход на следующую запись
        если таблица еще не читалась - читает ее и встает на первую запись
        """

        if self.EOF:
            return False
        p = self.position + 1
        await self.seek(p)
        if p > self.position:
            self._ptr += 1
        return not self.EOF

    async def prior(self):
        """
        переход на предыдущую запись
        """
        p = self.position
        if p <= 0:
            return False
        await self.seek(p-1)
        return not self.BOF

    async def first(self):
        """
        переход на первую запись курсора
        """
        self._page = await self(Table._FILTER, PAGE(self._page_size + 1, 0))
        self._ptr = self._offset = 0
        return not self.EOF

    async def last(self):
        """
        переход на последнюю запись
        """
        await self.save()
        cnt = await sql(f"select count(*) from {self._table} {self._filter}", self._db, ONE)
        self._offset = cnt - self._page_size
        if self._offset < 0:
            self._offset = 0
        self._page = await self(Table._FILTER, PAGE(self._page_size+1, self._offset))
        self._ptr = len(self._page) - 1
        return not self.BOF

    @property
    def BOF(self):
        """
        :return: True, если курсор на первой записи
        """
        return (self._ptr or 0) == 0 and self._offset == 0

    @property
    def EOF(self):
        """
        :return: True, если курсор на последней записи
        """
        if self._page is None:
            return False
        p = len(self._page)
        return self._ptr >= p and p <= self._page_size

    def __aiter__(self):
        self._ptr = None
        return self

    async def __anext__(self):
        await asyncio.sleep(self._delay)
        if self._ptr is None:
            await self.first()
        else:
            await self.next()
        if self.EOF:
            raise StopAsyncIteration
        return self.row


    def __getitem__(self, item):
        return self.row[item].value

    def __setitem__(self, key, value):
        f = self.row[key]
        f.value = value

    def _gen_filter(self, *args, **kwargs)->str:

        def gen_op(lst, op):
            ret = ""
            for x in lst:
                if ret:
                    ret += f" {op} "
                if isinstance(x, Field._Condition):
                    v = x()
                elif isinstance(x, list):
                    v = gen_op(x, "or")
                elif isinstance(x, tuple):
                    v = gen_op(x,"and")
                else:
                    raise_error("BAD_V_COND", v=x)
                v = v.strip()
                if v=="":
                    raise_error("EXPR_ERROR", x=v)
                ret += f"({v})"
            return ret

        qry = gen_op(args, "and")
        nms = self.field_names
        for x in kwargs:
            if x not in nms:
                raise_error("NA_FIELD", field=x, table=self._table)
            if qry:
                qry += "and"
            qry += f"{x} = {Field._Condition._lquot(self.row._data[x]._p_type, kwargs[x])}"
        return qry

    async def filter(self, *args, **kwargs):
        """
        Задает фильтр для таблицы
        в args можно перечислять операции сравнения, например t.row.v == 1, где t - объект таблицы, м - имя поля
        операции сравнения в args могут объединяться в tuple и тогда относятся друг к другу по AND, либо в list - тогда OR
        args это tuple, соответственно соединение AND
        например, filter(t.row.a==1,[t.row.b==2,t.row.b==3]) будет преобразовано в: t.a = 1 and (t.b = 2 or t.b = 3)
        list и tuple могут быть вложены в другие list и tuple

        В kwargs все проще: ключ это имя поля, а значение - значение поля. При этом условия связаны по AND
        например, filter(a=1, b=2) будет преобразовано в: t.a = 1 and t.b = 2
        """
        if not args and not kwargs:
            self._filter = ""
        else:
            self._filter = "where " + self._gen_filter(*args, **kwargs)
        await self.first()

    async def save(self, *args, **kwargs):
        """
        При вызове без параметров, сохраняет текущие изменения в таблице
        Если в args[0] передан список записей - сохраняет его
        Если в kwargs переданы значения полей - сохраняет запись
        ---
        В случае если в таблице уже есть запись с таким ключем, как в записи, переданной в save
        происходит обновление записи, иначе вставка.
        """
        if not args and not kwargs:
            # save без аргументов = запись изменений -----------------------------------------------------------
            if self._changed:
                await self.save([self._page[x] for x in self._changed])
                self._changed.clear()
            return
        elif args:
            # список записей в первом args = сохранение каждой записи ------------------------------------------
            auto = self._auto_close_conn
            try:
                self._auto_close_conn = False
                for x in args[0]:
                    await self.save(**x)
            finally:
                self._auto_close_conn = auto
            if auto:
                await self._db.connection.commit()
            return
        #### запись **kwargs -----------------------------------------------------------------------------------
        key = ""
        if self._key_fields:
            chk = {x:kwargs[x] for x in self._key_fields if x in kwargs}
            if len(chk)==len(self._key_fields):
                for x in chk:
                    if key:
                        key += " and "
                    key += f"{self.row[x]()} = {self._db.connection.var_to_sql(chk[x])}"
        qry = ""
        if key:
            chk = await sql(f"select 1 from {self._table} where {key}", self._db, ONE)
            if chk:
                # запись найдена - обновление
                for x in kwargs:
                    if x in self._key_fields:
                        continue
                    if qry:
                        qry += ",\n"
                    qry += f"{self.row[x]()} = {self._db.connection.var_to_sql(kwargs[x])}"
                qry = f"update {self.name} set\n {qry}\n where {key}"
        if qry=="":
            # запись не найдена - вставка
            key = ""
            for x in kwargs:
                if key:
                    key += ", "
                    qry += ", "
                key += self.row[x]()
                qry += self._db.connection.var_to_sql(kwargs[x])
            qry = f"insert into {self.name}({key})\nvalues({qry})"
        await sql(qry, self._db)
        if self._auto_close_conn:
            await self._db.connection.commit()

    async def delete(self, *args, **kwargs):
        """
        При вызове без параметров удаляет строку, на которой стоит курсор
        Если вызван с параметрами - удаляет записи соответствующие фильтру, заданному параметрами
        """
        if args or kwargs:
            qry = self._gen_filter(*args, **kwargs)
        elif self.key:
            qry = {x:self.row[x].value for x in self.key}
        else:
            qry = {x:self.row[x].value for x in self.row._data.keys()}
        if isinstance(qry, dict):
            flds, qry = qry, ""
            for x in flds:
                if qry:
                    qry += " and "
                qry += f"{self.row[x]()} = {self._db.connection.var_to_sql(self.row[x].value)}"
        qry = f"delete from {self.name} where {qry}"
        await sql(qry, self._db)
        if self._auto_close_conn:
            await self._db.connection.commit()

    async def count(self, *args, **kwargs):
        """
        :param args:  --/- Если заданы, то по ним строится фильтр (аналогично filter). Иначе используется фильтр таблицы
        :param kwargs: /   Если в args передать опцию ALL, то результат будет вычислен по всей таблице (без фильтра)
        :return: Количество записей в таблице
        """
        fltr, n = "", 0
        while n < len(args):
            if args[n]==ALL:
                fltr = None
                del args[n]
            else:
                n += 1
        if fltr=="":
            fltr = "where " + self._gen_filter(*args, **kwargs) if args or kwargs else self._filter
        else:
            fltr = ""
        cnt = await sql(f"select count(*) from {self._table} {fltr}", self._db, ONE)
        if self._auto_close_conn:
            await self._db.connection.rollback()
        return cnt

    async def __call__(self, *args, **kwargs):
        """
        Возвращает данные таблицы как список строк
        умеет модифицировать результат посредством опций ONE, ROW, DICT, TUPLE, OBJECT и PAGE
        кроме того, в args и kwargs можно передать условия фильтра (аналогично filter)
        Если в args передать опцию ALL, то результат будет вычислен по всей таблице (без фильтра)
        """
        args = list(args)
        n, opts, fltr = 0, [], ""
        while n < len(args):
            if args[n] == Table._FILTER and fltr=="":
                fltr = self._filter
                del args[n]
            elif args[n] == ALL:
                fltr = None
                del args[n]
            elif isinstance(args[n], PAGE) or args[n] in (ONE, ROW, DICT, TUPLE, OBJECT):
                opts.append(args[n])
                del args[n]
            else:
                n += 1
        if (args or kwargs) and fltr is not None:
            fltr = "where " + self._gen_filter(*args, **kwargs)
        if fltr is None:
            fltr = ""
        args = opts
        args.append(self._db)
        ret = await sql(f"select * from {self._table} {fltr} order by {self._key}", *args)

        if self._auto_close_conn:
            await self._db.connection.rollback()
        return ret


class EnvTable(Table):

    @classmethod
    async def create(cls, table_name, env, page_size=100, async_delay=0.0001):
        table_struct = await env.sql("\d "+table_name)
        if not table_struct:
            raise_error("NA_TABLE", name=table_name)
        t = cls(table_struct, env, page_size, async_delay)
        await t.first()
        return t

    def __init__(self, table_struct: dict, env, page_size=100, async_delay=0.001):
        super().__init__(table_struct, env._context, page_size, False, async_delay)
        self._env = env

    def _field_changed(self, ptr, field):
        super()._field_changed(ptr, field)
        self._env.on_commit(self.save)

    async def save(self, *args, **kwargs):
        if len(args)>0 and args[0]==self._env:
            args = args[1:]
        await super().save(*args, **kwargs)
        if not args and not kwargs:
            self._env.on_commit(self.save, False)
