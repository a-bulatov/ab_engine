from _imports import *

async def with_transaction():
    async with DB_ENV() as env:
        await env.sql("create table if not exists t1(id serial primary key, v varchar)")
        x = await env.sql("select max(id) from t1", ONE)
        x = x+1 if x else 1
        await env.sql("insert into t1(v) values ('from env - '||$1)", x)
        await env.sql("insert into t1(v) values ('from env - '||$1)", x+1)
        await env.sql("insert into t1(v) values ('from env - '||$1)", x+2)

async def main():
    Config("test.toml")
    #await with_transaction()

    cnt = await sql("select count(*) from t1", ONE)
    print(cnt)

    env = DB_ENV(a=2)
    x = await env.sql("select $a * $b", ONE, b=5)
    print(x)  # 10

    t = await env.table("t1")
    x = await t.count()
    print(cnt == x, x) # True, record_count

    await t.seek(1) # seek to row 1 (numbers from 0)
    print("---- forward")
    # list forward
    while not t.EOF:
        print(t.position, t.row)
        await t.next()

    print("---- iterator")
    # forward by iterator
    async for row in t:
        print(t.position, row)
        if t.position == 4:
            break

    print("---- backward")
    # list backward
    await t.last()
    while not t.EOF:
        print(t.row)
        if t.BOF:
            break
        await t.prior()
    print("----")
    await t.filter([t.row.id == 4, t.row.id == 2]) # id == 2 or id == 4
    print("FILTER", t.row) # first filtred record

    # 4 records as tuple
    x = await t(TUPLE, PAGE(limit=4))
    print(x)

    # filtered records as named tuple
    x = await t(OBJECT, [t.row.id == 4, t.row.id == 2])
    print(x)

    await t.first()
    x = "record updated"
    if t.row.v.value == x:
        x = "another update"
    t.row.v.value = x  # change the value of v in the current record
    await env.commit() # commit changes without context

    await t.seek(id=7)
    print(t.row)

if __name__ == '__main__':
    run_async(main())