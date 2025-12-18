from _imports import *

async def test():
    Config("test.toml", env_map={"auth":{"USER":"user"}})
    Config().log(f"User: {Config().auth['user']}")
    x = await sql("select version()", ONE)  # для БД по умолчанию (defaults) можно не передавать DB
    Config().log(f"Postgres version: {x}")
    data = await sql("select * from generate_series(1,50) order by 1", ITERATOR(5))
    async for x in data:
        print(x)
    print("----------------------------------")

if __name__ == '__main__':
    run_async(test())