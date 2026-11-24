import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from ab_engine import Config, register_rpc_list, call_json, call_rpc
from ab_engine.rpc import RPCInterface
## Дополнительные библиотеки, требуемые для теста. в реальном приложении могут быть использованы другие ###
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse
from contextlib import asynccontextmanager
import asyncio, os, signal


def hello():
    # функция для вызываемая для теста (self)
    return "Здравствуй мир!"


async def tests():
    # демонстрация/тест работы
    cfg = Config()
    # вызов метода hello
    ret = await call_rpc("hello")
    cfg.log(ret)

    # ждем секунду в надежде, что starlette будет принимать запросы
    await asyncio.sleep(1)
    cfg.log("Сервер принимает запросы!","debug")

    cfg.log("------------------------------------------------------------------")
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

    # пример работы с valkey через функции интерфейса
    cfg.log("------------------------------------------------------------------")
    itf = RPCInterface(name="valkey")
    await itf.set(key="test_key", value=10)
    ret = await itf.get(key="test_key")
    cfg.log(f"test_key = {ret}")
    await itf.set(key="test_key", value=20)
    ret = await itf.get(key="test_key")
    cfg.log(f"test_key = {ret}")

    #остановка приложения
    os.kill(os.getpid(), signal.SIGTERM)

async def http_endpoint(request):
    # в эту функцию, по HTTP, приходят запросы JsonRPC
    x = await request.json()
    if "\\" in x.get("method","\\"):
        x = {"error": f"Невозможно выполнить {x.get("method")}"}
    else:
        x = await call_json(x)
    return JSONResponse(x)

@asynccontextmanager
async def lifespan(app: Starlette):
    # Нужен для библиотеки starlette, чтобы синхронизировать запуск демонстрационной функции
    # 1. Сервер еще не принимает запросы, запускаем задачу с тестами
    task = asyncio.create_task(tests())
    # 2. Передаем управление приложению — сервер начинает принимать запросы
    yield
    # 3. Очистка при остановке сервера (если задача еще не завершилась)
    if not task.done():
        task.cancel()

if __name__ == '__main__':
    import uvicorn
    # Инициализация
    Config("rpc.yaml")
    register_rpc_list(Config().API) # регистрация API
    app = Starlette(debug=False, routes=[Route("/api", endpoint=http_endpoint, methods=["POST"])], lifespan=lifespan)
    # запуск
    uvicorn.run(app, port=5000, host="0.0.0.0")
