from typing import Protocol, Optional
from .fnc import Fnc
from ..env import DB_ENV, Config
from ..error import error

# функция принимает на вход имя интерфейса, url и сообщение JsonRPC
class RpcCallback(Protocol):

    async def __call__(self, interface_name:Optional[str], endpoint:str, message:dict) -> dict:
        ...

# функция принимает на вход имя интерфейса и список заголовков.
# может поменять заголовки. не вызывается, если задан CallbackPOST
class HeadersCallback(Protocol):

    def __call__(self, interface_name:Optional[str], endpoint:str, headers:dict):
        ...

class HTTP(Fnc):

    getHeaders : Optional[HeadersCallback] = None
    doRpc : Optional[RpcCallback] = None
    AsyncClient = None


    def __init__(self, name:str, method: str, help: str, endpoint: str):
        super().__init__(name, help)
        self._url = endpoint.strip()
        self._rpc = method.strip()

    async def __call__(self, env, **kwargs):
        if self._url.startswith("@"):
            url = self._url[1:].split(".")
            cfg = Config()._settings
            while len(url) > 0:
                cfg = cfg.get(url.pop(0))
                if len(url) == 0:
                    self._url = str(cfg)
                    break
                if not isinstance(cfg, dict):
                    raise error("BAD_REFERENCE", reference=self._url)

        if isinstance(env, DB_ENV):
            env = env["RPC_INTERFACE"] if env.has_item("RPC_INTERFACE") else None
        else:
            env = str(env)
        ret = await self.request(env, kwargs)
        if "error" in ret:
            return {"error": ret["error"]}
        return ret["result"]

    async def request(self, interface, params):
        params = {
            "jsonrpc": "2.0",
            "method": self._rpc,
            "params": params
        }
        if HTTP.doRpc is not None:
            ret = await HTTP.doRpc(interface, self._url, params)
            return ret
        header = {
            "Content-Type": "application/json"
        }
        if HTTP.getHeaders is not None:
            HTTP.getHeaders(interface, self._url, header)
        if HTTP.AsyncClient is None:
            try:
                import httpx
                HTTP.AsyncClient = httpx.AsyncClient
            except Exception as e:
                raise error("NEED_LIB", lib = "pip install httpx")
        async with HTTP.AsyncClient() as client:
            ret = await client.post(
                url = self._url,
                headers = header,
                json = params
            )
        if ret.status_code == 200:
            return ret.json()
        else:
            return {"error": f"{ret.status_code} {ret.reason_phrase}"}



