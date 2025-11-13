from codecs import namereplace_errors

from .rpc import Fnc, call_rpc
from ..error import raise_error
from ..env import DB_ENV, Config, LogLevel
from json5 import loads as json_loads, dumps as json_dumps
from asyncio import gather
from ..error import error_msg


class JSON_RPC:

    @staticmethod
    def rpc_error(code, data=None, header=None):

        err = error_msg(code)
        if err.message is None:
            err.message = "Server error (UNKNOWN!!)"
            if not isinstance(code, int) or code > -32000 or code < -32099:
                code = -32000
            err.code = code
        code = {
            "code": err.code,
            "message": err.message,
        }
        if data:
            code["data"] = data if isinstance(data, (dict, list)) else str(data)
        code = {"error": code}
        if header:
            if "id" in header:
                code["id"] = header["id"]
        else:
            header = {}
        code["jsonrpc"] = header.get("jsonrpc", "2.0")
        return code

    def __init__(self, connection = None):
        self._con = connection

    async def _rpc(self, env, method, header, params):
        # можно перезагрузить в наследниках, чтобы например, вызывать команды мз другого списка
        f = Fnc.search(method)
        if f is None:
            return self.rpc_error(-32601, header=header)
        if isinstance(params, list):
            params = {"LIST_OF_PARAMS": params}
        elif not isinstance(params, dict):
            raise_error("BAD_RPC_FORMAT", name=method)
        return await call_rpc(f, env, **params)

    async def _call_one(self, env, message):
        if "method" not in message:
            return self.rpc_error(-32600, header=message)
        if "params" in message:
            params = message["params"]
            del message["params"]
        else:
            params = {}
        f = message['method']
        self.log(f"CALL:{f}")
        try:
            res = await self._rpc(env, f, message, params)
            if isinstance(res, tuple):
                res = list(res)
            elif not isinstance(res, (dict, list, str)):
                res = str(res)
            elif not (isinstance(res, dict) and len(res) == 1 and "error" in res):
                res = {"result": res}
            res["jsonrpc"]=message.get("jsonrpc", "2.0")
            if res["jsonrpc"]=="1.0":
                if "result" not in res:
                    res["result"] = None
                if "error" not in res:
                    res["error"] = None
            if "id" in message:
                res["id"] = message["id"]
        except Exception as e:
            res = self.rpc_error(-32000, data=e, header=message)
        if res.get("error") is not None:
            self.log(f"{f}: ERROR:\n{res['error']}!!")
            if env.in_transaction:
                await env.rollback()
        else:
            self.log(f"{f}: OK!")
        return res

    async def _call_part(self, message, ext_params=None):
        env = self._get_env(message=message, ext=ext_params,  only_new=True)
        ret = await self._call_one(env, message)
        if env.in_transaction:
            await env.commit()
        return ret

    def _get_env(self, message, ext, only_new=False):
        if not only_new and isinstance(self._con, DB_ENV):
            return self._con
        return DB_ENV(self._con, MESSAGE=message, EXT=ext)

    async def __call__(self, message, **kwargs):
        """
        Выполняет команду в соответствии с правилами JSON-RPC
        :param message: Тело сообщения, которое может быть представлено str, dict, list или tuple
                        Eсли сообщение является строкой, то сначала эта строка преобразуется в структуру python по
                        правилам json5. В результате преобразования сообщение станет dict или list
                        Если сообщение dict, то подразумевается, что в нем есть атрибут method, содержащий имя метода,
                        а также могут быть параметры:
                          params - параметры метода
                          id - идентификатор сообщения
                          прочие параметры, которые будут проигнорированы механизмом RPC
                        Eсли сообщение list, то каждый элемент списка должен быть dict, который будет обработан по правилам,
                        описанным выше. При этом, все dict переданные в списке будут обрабатываться параллельно. На
                        выходе будет получен list с результатами обработки каждого dict.
                        Если сообщение tuple, то оно будет выполнено почти как list, с той разницей, что dict будут
                        выполнены последовательно.
        :param kwargs:  Дополнительные параметры, которые будут доступны методам в параметре окружения EXT,
                        также в параметре MESSAGE доступно тело обрабатываемого сообщения (dict)
        :return:        список ответов, либо ответ (dict) содержащий атрибут result с ответом, либо error с сообщением
                        об ошибке.
        """
        if isinstance(message, str):
            try:
                message = json_loads(message)
            except Exception as e:
                return self.rpc_error(-32700, e)
            to_str = True
        else:
            to_str = False
        if isinstance(message, list):
            res = [self._call_part(x, ext_params=kwargs) for x in message]
            res = await gather(*res)
        elif isinstance(message, tuple):
            env = self._get_env(message=message, ext=kwargs)
            res = []
            for x in message:
                x = await self._call_one(env, x)
                res.append(x)
                if not env.in_transaction and isinstance(x, dict) and len(x) == 1 and "error" in x:
                    break
            if env.in_transaction:
                await env.commit()
        elif isinstance(self._con, DB_ENV):
            res = await self._call_one(self._con, message)
        else:
            env = self._get_env(message=message, ext=kwargs)
            res = await self._call_one(env, message)
            if env.in_transaction:
                await env.commit()
        return json_dumps(res, indent=4) if to_str else res

    @staticmethod
    def log(msg, level=LogLevel.DEBUG, *args, **kwargs):
        Config().log(msg, level, *args, **kwargs)


async def call_json(message:str|dict|list, connection="", ext_params=None):
    rpc = JSON_RPC(connection)
    ret = await rpc(message, ext_params=ext_params)
    return ret
