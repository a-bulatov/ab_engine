from _imports import *
import sys

async def test():
    Config("test.toml", env_map={"auth":{"USER":"user"}})
    Config().log(f"User: {Config().auth['user']}")
    x = await sql("select version()", ONE)  # для БД по умолчанию (defaults) можно не передавать DB
    Config().log(f"Postgres version: {x}")
    data = await sql("select * from generate_series(1,50) order by 1", ITERATOR(5))
    async for x in data:
        print(x)
    print("----------------------------------")

def test_log():
    c = Config({'logging': {'level': 'off'}})
    print(c.log_level)   # LogLevel.OFF
    print(c.logger)
    c.log("Не выведется")# <RootLogger root (Level -1)>

if __name__ == '__main__':
    print(sys.executable)
    test_log()
    #run_async(test())