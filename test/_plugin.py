def test(**kwargs):
    if kwargs:
        return {"kwargs": str(kwargs)}
    return {"message":"from plugin!!"}

async def async_test():
    print("is async!!")

async def with_env(env, **kwargs):
    x = env.data.copy()
    x.update(kwargs)
    return x