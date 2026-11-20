from _imports import *

async def main():
    api = {
       "help": {
           "type": "web",
           "interface": "test",
           "url": "@http.proxy"
       }
    }
    register_rpc_list(api)
    itf = RPCInterface(name="test")
    ret = await itf.help()
    print(ret)

    ret = await call_rpc("test\\help", method="enum_get")
    print(ret)

if __name__ == '__main__':
    Config("test.toml")
    run_async(main())
