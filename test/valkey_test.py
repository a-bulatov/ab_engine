from _imports import *


async def main():
    async with  DB_ENV("valkey") as env:
        x = await env.sql("set aaa 812")
        print(x)
        x = await env.sql("get aaa")
        print(x)

if __name__ == '__main__':
    Config("test.toml")
    run_async(main())