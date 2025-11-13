from _imports import *

async def test():
    Config("test.toml", env_map={"auth":{"USER":"user"}})
    Config().log(Config().auth['user'])

if __name__ == '__main__':
    run_async(test())