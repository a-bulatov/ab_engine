from _imports import *


@register_rpc("version")
def SQL():
    # чтобы функция зарегистрировалась как запрос, она не должна быть корутиной, не должна иметь параметров и должна называться SQL
    # если такая функция вернет строку, то эта строка будет использоваться как запрос
    # если функция вернет tuple, то первый элемент - запрос, а остальные - параметры args
    return("select version()", ONE)


@register_rpc
async def mul(a, b):
    return a * b


@register_rpc
async def ver2(env):
    # функция RPC может быть корутиной
    # если у функции задан параметр с именем env, то в него будет передан текущий контекст (наследник DB_ENV)
    x = await env.sql("select version()", ONE)
    return x.split("(",1)[0]


def hello(name="World"):
    return f"Hello {name}!"


async def main():
    cfg=Config("test.toml")
    register_rpc("hello", hello)
    register_rpc("plugin", "_plugin.py:test")

    x = await call_rpc("mul", a=2, b=2)
    print(x)

    message = [
        {
            "method": "version",
            "id": 1
        },
        {
            "method": "ver2",
            "id": 2
        },
        {
            "method": "hello",
            "params": {"name": "all"},
            "id": 3
        },
        {
            "method": "plugin",
            "id": 4
        }
    ]
    lst = await call_json(message)
    for x in lst:
        print(x)


if __name__ == '__main__':
    run_async(main())

