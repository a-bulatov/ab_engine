import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from ab_engine.rpc import register, call_rpc, HTTP
from ab_engine.env import DB_ENV
from base64 import b64encode
from asyncio import run

def set_headers(endpoint:str, headers:dict, env:DB_ENV):
    user = env["user"] # получаем пользователя из окружения
    user = b64encode(user.encode("utf-8")).decode("utf-8")
    headers["Authorization"] = f"Basic {user}" # например, передаем пользователя в Authorization Basic

async def main():
    # задаем callback для редактирования заголовков
    HTTP.getHeaders = set_headers

    # регистрируем RPC функцию-proxy
    register("test", "http://0.0.0.0:5000/api:enum_get")  # заменить url и имя метода через : на подходящие

    # создаем окружение, в котором передаем пользователя
    env = DB_ENV(user = "Test User")

    # выполнение функции в контексте окружения. имена параметров такие была мала их вероятность в сообщении
    ret = await call_rpc("test", current_rpc_environment_for_call = env)
    print(ret)

if __name__ == '__main__':
    run(main())
