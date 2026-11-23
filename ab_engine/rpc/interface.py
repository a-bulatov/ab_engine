from .json_rpc import JSON_RPC
from .fnc import Fnc
from .rpc import call_rpc
from ..error import error


class Caller:

    def __init__(self, f, rpc, name):
        self._f = f
        self._n = name
        self._rpc = rpc

    async def __call__(self, **kwargs):
        env = self._rpc._get_env(None, None)
        ret = await self._f(env, **kwargs)
        return ret

    @property
    def __doc__(self):
        x = self._f.help
        return x

    def __repr__(self) -> str:
        return self._rpc._name + self._n

class RPCInterface(JSON_RPC):

    def __init__(self, name="", connection = None):
        super().__init__(connection)
        self._name =  "" if name=="" else name + "\\"
        f = None
        for x in Fnc.registry:
            if self._name != "" and x.startswith(self._name):
                f = Fnc.registry[x]
                x = x.split("\\")[1]
            elif self._name == "" and "\\" not in x:
                f = Fnc.registry[x]
            else:
                continue
            setattr(self, x, Caller(f, self, x))
        if f is None:
            raise error("RPC_BAD_ITF", name = self._name)

    async def _rpc(self, env, method, params):
        # можно перезагрузить в наследниках, чтобы например, вызывать команды мз другого списка
        f = Fnc.search(self._name + method)
        if f is None:
            return self.rpc_error(-32601)
        if isinstance(params, list):
            params = {"LIST_OF_PARAMS": params}
        elif not isinstance(params, dict):
            raise error("BAD_RPC_FORMAT", name=method)
        return await call_rpc(f, env, **params)

    async def __call__(self, message, **kwargs):
        if isinstance(message, str):
            x = await self({
                "method": message,
                "params": kwargs
            })
            return x
        elif not isinstance(message, dict):
            raise error(-32700)
        x = await super().__call__(message)
        return x

    def _get_env(self, message, ext, only_new=False):
        env = super()._get_env(message, ext, only_new)
        if not env.has_item("RPC_INTERFACE"):
            env["RPC_INTERFACE"] = self._name[:-1]
        return env