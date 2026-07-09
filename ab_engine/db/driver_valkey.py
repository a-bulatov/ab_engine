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


def decode_array(buf):
    l, buf = buf.split("\r\n",1)
    l = int(l[1:])
    ret = []
    while buf!="":
        if buf[0] == "$":
            item_l, buf = buf.split("\r\n",1)
            item_l = int(item_l[1:])
            item = buf[:item_l]
            if item_l > 0:
                buf = buf[item_l+2:]
                valid = len(item) == item_l
            else:
                item = None
                valid = True
        elif buf[0] == ":":
            item, buf = buf.split("\r\n",1)
            item = int(item[1:])
            valid = True
        elif buf[0] == "*":
            item, l2, valid = decode_array(buf)
            buf = buf[l2:]
        else:
            valid = False
        if not valid:
            break
        ret.append(item)
        if len(ret)==l:
            break
    return ret, len(buf), len(ret)==l


def decode_buf(buf):
    if buf[0] == "$":
        l, buf = buf.split("\r\n",1)
        l = int(l[1:])
        if l < 0:
            buf = None
            valid = True
        else:
            buf =buf[:l]
            valid = len(buf)==l
    elif buf[0] == ":":
        buf = buf.split("\r\n",1)[0][1:]
        buf = int(buf)
        valid = True
    elif buf[0] == "*":
        buf, l, valid = decode_array(buf)
    elif buf[0] == "-":
        buf = buf[1:-2]
        raise Exception(buf)
    elif buf[0] == "+":
        buf = True
        valid = True
    else:
        valid = buf.endswith("\r\n")
        buf = buf[:-2]
    return buf, valid


def prepare_cmd(query:str):
    cmd_parts, data, quot, quot2 = [], "", False, False
    for x in query:
        if x == '"' and not quot2:
            quot = not quot
        elif x == "'" and not quot:
            quot2 = not quot2
        elif quot or quot2:
            data += x
        elif x == " " and data != "":
            cmd_parts.append(data)
            data = ""
        else:
            data += x
    if data:
        cmd_parts.append(data)

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
        self._max_responses = 10
        self._multi = False
        self._conn: Optional[asyncio.StreamReader] = None
        self._read_task = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()

    @property
    def in_transaction(self)->bool:
        """возвращает открыта ли транзакция"""
        return self._conn is not None

    async def begin(self):
        await self._before_open()
        self._conn, self._writer = await asyncio.open_connection(self._redis_host, self._redis_port)
        if self._redis_db!=0:
            await self.sql(f"select {self._redis_db}")
        self._task = asyncio.create_task(self._read_loop())

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

        # Ждём ответ
        data, ret = b"", None
        try:
            for _ in range(self._max_responses):
                resp_chunk = await asyncio.wait_for(self._queue.get(), timeout=0.1)
                if resp_chunk:
                    data+=resp_chunk
                ret, valid = decode_buf(data.decode('utf-8'))
                if valid:
                    break
        except asyncio.TimeoutError:
            ...
        except Exception as e:
            # Ошибка чтения — соединение, скорее всего, разорвано
            await self.rollback()
            raise e
        return ret

    async def _read_loop(self) -> None:
        while self.in_transaction:
            try:
                while not self._conn.at_eof():
                    chunk = await self._conn.read(4096)
                    if not chunk:
                        break
                    await self._queue.put(chunk)
            except Exception as e:
                ...
            await asyncio.sleep(0.1)


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
            self._writer.close()
            await self._writer.wait_closed()
        finally:
            self._conn = None
            self._writer = None
            self._read_task = None
            await super().rollback()

    async def table_struct(self, table_name) -> dict:
        return {}