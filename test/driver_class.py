import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from ab_engine.db import sql, ONE, DB
from ab_engine.db.option import DRIVER_CLASSES
from ab_engine.db.driver_postgresql import Driver
import asyncio

class MyPgDriver(Driver):

    async def begin(self):
        await super().begin()
        print("BEGIN TRANSACTION", flush=True)

    async def rollback(self):
        await super().rollback()
        print("END TRANSACTION", flush=True)

DRIVER_CLASSES["postgresql"] = MyPgDriver

async def main():
    x = await sql("select version();", ONE, DB("postgresql://localhost:5432/postgres?user=postgres&password=postgres"))
    print(x)
    await DB.garbage_collect()

if __name__ == '__main__':
    asyncio.run(main())