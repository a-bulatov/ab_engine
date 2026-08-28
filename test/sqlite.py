import asyncio
from ab_engine.db import sql, DB, COMMIT, Table

async def main():
    db = DB('sqlite:///tmp/test.db')
    await sql('drop table if exists t', db, COMMIT)
    # однострочный CREATE TABLE — типичный случай
    await sql('create table t(id integer primary key, val varchar)', db, COMMIT)
    t = await Table.create('t', db)
    print(t.field_names)

asyncio.run(main())