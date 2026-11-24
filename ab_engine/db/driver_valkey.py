import sys, os
sys.path.append(os.path.dirname(__file__))
from driver import Driver as BaseDriver, RowFactory

import asyncio
from typing import Optional, Callable, Any

_FACTORY_ = {
    RowFactory.ANY.value: None,
    RowFactory.TUPLE.value: None,
    RowFactory.DICT.value: None,
    RowFactory.NAMED_TUPLE.value: None,
}


def _unescape(b: bytes) -> str:
    # данные приходят в виде unicode_escape (так их кодирует prepare_cmd)
    return b.decode('utf-8', errors='ignore').encode('utf-8').decode('unicode-escape')


def decode_frame(buf: bytes):
    """Разбирает один полный RESP-кадр из buf.

    Возвращает (value, consumed, complete):
      value    - разобранное значение (str/int/list/None/True/Exception)
      consumed - сколько байт занимает кадр
      complete - False, если данных пока недостаточно для полного кадра
    """
    if not buf:
        return None, 0, False
    t = buf[0:1]
    if t in (b"+", b"-", b":"):
        i = buf.find(b"\r\n")
        if i < 0:
            return None, 0, False
        body = buf[1:i]
        if t == b"+":
            return True, i + 2, True
        if t == b"-":
            return Exception(body.decode('utf-8', 'ignore')), i + 2, True
        try:
            return int(body), i + 2, True
        except ValueError:
            return None, 0, False
    if t == b"$":
        return _decode_bulk(buf)
    if t == b"*":
        return _decode_array(buf)
    # inline-строка (в RESP-командах не встречается)
    i = buf.find(b"\r\n")
    if i < 0:
        return None, 0, False
    return buf[:i].decode('utf-8', 'ignore'), i + 2, True


def _decode_bulk(buf: bytes):
    i = buf.find(b"\r\n")
    if i < 0:
        return None, 0, False
    try:
        ln = int(buf[1:i])
    except ValueError:
        return None, 0, False
    if ln < 0:
        return None, i + 2, True
    start = i + 2
    end = start + ln
    if len(buf) < end + 2:
        return None, 0, False
    return _unescape(buf[start:end]), end + 2, True


def _decode_array(buf: bytes):
    i = buf.find(b"\r\n")
    if i < 0:
        return None, 0, False
    try:
        n = int(buf[1:i])
    except ValueError:
        return None, 0, False
    if n < 0:
        return None, i + 2, True
    pos = i + 2
    items = []
    for _ in range(n):
        if pos >= len(buf):
            return None, 0, False
        item, consumed, complete = decode_frame(buf[pos:])
        if not complete:
            return None, 0, False
        items.append(item)
        pos += consumed
    return items, pos, True


def prepare_cmd(query:str):
    cmd_parts, data, quot, quot2 = [], "", False, False
    for x in query:
        if x == '"' and not quot2:
            quot = not quot
        elif x == "'" and not quot:
            quot2 = not quot2
        elif quot or quot2:
            data += x
        elif x == " " and data == "":
            ...
        elif x == " ":
            cmd_parts.append(data.encode("unicode_escape").decode("ascii"))
            data = ""
        else:
            data += x
    if data:
        cmd_parts.append(data.encode("unicode_escape").decode("ascii"))

    data = ["*%s\r\n" % len(cmd_parts)]
    for arg in cmd_parts:
        if arg is None:
            data.append('$-1\r\n')
        else:
            s = str(arg)
            data.append('$%s\r\n%s\r\n' % (len(s), s))
    return "".join(data)


class Driver(BaseDriver):

    def __init__(self, connection_string, on_open_close=None, notify=None):
        """
        valkey://10.0.0.57:6379/0
        """
        super().__init__(connection_string, on_open_close, notify)
        x, p = connection_string.rsplit("/",1)
        self._redis_db = int(p)
        self._redis_host, p = x.rsplit(":", 1)
        self._redis_port  = int(p)
        self._redis_timeout = 10
        self._multi = False
        self._conn: Optional[asyncio.StreamReader] = None
        self._read_task = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._pending: asyncio.Queue = asyncio.Queue()
        self._buffer = b""

    @property
    def in_transaction(self)->bool:
        """возвращает открыта ли транзакция"""
        return self._conn is not None

    async def begin(self):
        await self._before_open()
        self._conn, self._writer = await asyncio.open_connection(self._redis_host, self._redis_port)
        self._buffer = b""
        self._read_task = asyncio.create_task(self._read_loop())
        if self._redis_db!=0:
            await self.sql(f"select {self._redis_db}")

    async def sql(self, query, one_row=False, row_factory=RowFactory.DICT):
        if not self.in_transaction:
            await self.begin()

        if query.upper()=="MULTI":
            self._multi = True
        elif query.upper()=="EXEC":
            self._multi = False

        data = prepare_cmd(query)
        self._writer.write(data.encode('utf-8'))
        await self._writer.drain()

        fut = asyncio.get_running_loop().create_future()
        await self._pending.put(fut)
        try:
            ret = await asyncio.wait_for(fut, self._redis_timeout)
            return ret
        except Exception:
            # ошибка запроса или таймаут — рвём соединение
            await self.rollback()
            raise

    async def _read_loop(self) -> None:
        while self.in_transaction:
            conn = self._conn
            if conn is None:
                break
            try:
                chunk = await conn.read(4096)
            except asyncio.CancelledError:
                raise
            except Exception:
                break
            if not chunk:
                break
            self._buffer += chunk
            # разбираем все полные кадры из буфера
            while True:
                frame, consumed, complete = decode_frame(self._buffer)
                if not complete:
                    break
                self._buffer = self._buffer[consumed:]
                if isinstance(frame, list) and frame and frame[0] in ("message", "pmessage", "smessage"):
                    await self._notify_callback(frame[1:])
                else:
                    fut = await self._pending.get()
                    if not fut.done():
                        if isinstance(frame, Exception):
                            fut.set_exception(frame)
                        else:
                            fut.set_result(frame)

    async def commit(self):
        if not self.in_transaction:
            raise RuntimeError("Transaction is not open")
        if self._multi:
            await self.sql("exec")
        await self.rollback()

    async def rollback(self):
        if not self.in_transaction:
            return

        try:
            self._conn = None
            self._writer.close()
            await self._writer.wait_closed()
        finally:
            self._writer = None
            if self._read_task is not None:
                self._read_task.cancel()
            self._read_task = None
            await super().rollback()

    async def table_struct(self, table_name) -> dict:
        return {}

    async def parse_query(self, query, *args, **kwargs):
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
            x = x[p:]
            qs = f"{qs}{n}{x}"

        if qs:
            query = qs

        return query
