from _imports import *

async def main():
    async with  DB_ENV("valkey") as env:
        x = await env.sql("set aaa 812")
        print(x)
        x = await env.sql("get aaa")
        print(x)

async def subscribe():
    notify = []
    env = DB_ENV("valkey", notify=notify)
    x = await env.sql("subscribe warnings")
    print(x)
    while True:
        if notify:
            print("Notification:")
            while len(notify) > 0:
                print("  ", notify.pop(0))
        await sleep(0.2)

if __name__ == '__main__':
    Config("test.toml")
    run_async(subscribe())
