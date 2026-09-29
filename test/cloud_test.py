import sys, asyncio, os
sys.path.insert(0, "ab_engine-0.2.0")
if os.path.exists("t.db"):
    os.remove("t.db")
from ab_engine import Config, register_rpc, call_json
from ab_engine.env import DB_ENV
from ab_engine.db import ONE, DB

Config({"database": "sqlite://t.db"})

def check(name, f):
    try:
        r = f()
        if asyncio.iscoroutine(r):
            r = asyncio.run(r)
        print(f"[{name}] OK ->", repr(r)[:200])
    except Exception as e:
        print(f"[{name}] EXC ->", type(e).__name__, str(e)[:200])

async def setup():
    async with DB_ENV() as env:
        await env.sql("""create table t(
 id integer primary key,
 a varchar(10),
 b integer
)""")
        await env.sql("insert into t values(1,'x',10),(2,'y',20),(3,'z',30)")
check("setup", setup)

def setitem():
    env = DB_ENV(a=2)
    env["a"] = 5
check("env[k]=v existing", setitem)

def setitem_new():
    env = DB_ENV()
    env["b"] = 5
check("env[k]=v new", setitem_new)

async def env_var():
    env = DB_ENV(a=2, b=5)
    return await env.sql("select $a * $b", ONE)
check("readme: $vars from env", env_var)

check("DB_ENV(DB_ENV)", lambda: DB_ENV(DB_ENV()))

@register_rpc
def ret_int():
    return 42

@register_rpc
def secret(user="guest", is_admin=False):
    return {"admin": is_admin}

check("rpc returns int", lambda: call_json({"method": "ret_int", "id": 1}))
check("rpc client sets is_admin",
      lambda: call_json({"method": "secret", "params": {"is_admin": True}, "id": 1}))
check("rpc error text leak",
      lambda: call_json({"method": "secret", "params": {"zzz": 1}, "id": 1}))

async def inj():
    d = DB("sqlite://t.db").connection
    return await d.parse_query("select * from t where id = any($ids::int[])",
                               ids=["1}'); drop table t; --"])
check("array injection", inj)

async def dt():
    import datetime, uuid
    d = DB("sqlite://t.db").connection
    return await d.parse_query("select $d, $u", d=datetime.date(2024, 1, 1), u=uuid.uuid4())
check("date/uuid unquoted", dt)

async def tables():
    env = DB_ENV()
    await env.sql("""create table u(
 id integer primary key,
 a varchar(10)
)""")
    await env.sql("insert into u values(100,'u-row')")
    t1 = await env.table("t")
    print(t1.row.a.value)
    id  = t1.row.id.value
    await env.sql("update t set a = 'aaa' where id = $1", id)
    await t1.refresh()
    await env.sql("update t set a = 'bbb' where id = $1", id)
    print(t1.row.a.value)
    t2 = await env.table("u")
    return ("t1.row.a ->", t1.row.a.value, "t1['a'] ->", t1["a"], "t2.row.a ->", t2["a"])
check("two Table objects share ROW props", tables)

async def filt():
    t = await DB_ENV().table("t")
    await t.filter(a="x", b=10)
check("filter(kwargs x2)", filt)

async def cnt_all():
    from ab_engine.db.option import ALL
    t = await DB_ENV().table("t")
    return await t.count(ALL)
check("count(ALL)", cnt_all)

async def same_tbl_cmp():
    t = await DB_ENV().table("t")
    return t.row.b > t.row.id
check("field vs field same table", same_tbl_cmp)

async def del_single_pk():
    t = await DB_ENV().table("t")
    await t.delete()
# check("delete() single pk", del_single_pk)

async def row_opt():
    from ab_engine.db import ROW as ROW_OPT
    t = await DB_ENV().table("t")
    return await t(ROW_OPT)
check("table(ROW option)", row_opt)

async def inj_int():
    t = await DB_ENV().table("t")
    return await t(t.row.id == "0 or 1=1")
check("int field injection", inj_int)

async def limit():
    db = DB("sqlite://t.db{LIMIT:2}")
    await db.connection.sql("select 1")
    await db.connection.commit()
check("LIMIT release", limit)

from ab_engine.rpc.rpc import _resolve_path
sys.argv[0] = "/srv/app/main.py"
print("[_resolve_path ../plugins/x.py] ->", _resolve_path("../plugins/x.py"))
print("[timer sleep for 3s interval] ->", (3000 / 4) // 1000)