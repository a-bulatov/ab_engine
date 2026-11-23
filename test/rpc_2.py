import asyncio
import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from ab_engine import Config, register_rpc_list, call_json, call_rpc
from ab_engine.rpc import RPCInterface
######
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse
from contextlib import asynccontextmanager
import asyncio


def hello():
    return "Здравствуй мир!"


async def tests():
    cfg = Config()
    # вызов метода hello
    ret = await call_rpc("hello")
    cfg.log(ret)

    # ждем 2 секунды в надежде, что starlette будет принимать запросы
    await asyncio.sleep(2)
    cfg.log("Сервер принимает запросы!","debug")
    # вызов метода web_hello будет завершен с ошибкой т.к. он внутри интерфейса и это не интерфейс по умолчанию
    try:
        ret = await call_rpc("web_hello")
        cfg.log(ret)
    except Exception as e:
        cfg.log(e)
    # создаем интерфейс для выполнения приватных методов
    cfg.log("Попытка отправить запрос себе","debug")
    itf =  RPCInterface(name="private")
    cfg.log("Через web запрос к себе же (poroxy):")
    ret = await itf.web_hello()
    cfg.log(ret)

    cfg.log("------------------------------------------------------------------")
    ret = await itf.hello2(name = "из интерфейса")
    cfg.log(ret)

    # вызов функции интерфейса без создания интерфейса
    ret = await call_rpc("private\\hello2", name = "из функции")
    cfg.log(ret)

    # вызов функции которая объявлена в 2-х интерфейсах
    ret = await call_rpc("hello2", name = "из публичного интерфейса")
    cfg.log(ret)


async def http_endpoint(request):
    """
    Выполняет запрос пришедший на HTTP API
    запрещает выполнение приватных методов через HTTP
    """
    x = await request.json()
    if "\\" in x.get("method","\\"):
        x = {"error": f"Невозможно выполнить {x.get("method")}"}
    else:
        x = await call_json(x)
    return JSONResponse(x)

@asynccontextmanager
async def lifespan(app: Starlette):
    # 1. Сервер еще не принимает запросы, запускаем задачу с тестами
    task = asyncio.create_task(tests())

    # 2. Передаем управление приложению — сервер начинает принимать запросы
    yield

    # 3. Очистка при остановке сервера (если задача еще не завершилась)
    if not task.done():
        task.cancel()


def init():
    Config("rpc.yaml")
    register_rpc_list(Config().API)
    app = Starlette(debug=False, routes=[Route("/api", endpoint=http_endpoint, methods=["POST"])], lifespan=lifespan,)
    return app

if __name__ == '__main__':
    import uvicorn
    app = init()
    uvicorn.run(app, port=5000, host="0.0.0.0")
