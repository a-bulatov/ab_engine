from _imports import *
"""
--чтобы тест отработал, выполнить в БД postgresql:
do $$
begin
    create table if not exists config(
      id smallint primary key,
      parent_id smallint references config(id),
      k varchar(50) not null,
      v varchar,
      constraint uk_name_in_level unique (parent_id, k)
    );
    insert into config(id, parent_id, k, v)
    values
    (1, null, 'defaults', null),
    (2, 1, 'database', 'main'),
    (3, null, 'database', null),
    (4, 3, 'main', 'postgresql://localhost:5432/postgres?user=postgres&password=postgres'),
    (5, 3, 'lite', 'sqlite://:memory:')
    --,(6, 3, 'mysql', 'mysql://localhost:3306/mysql?user=root&password=root')
    on conflict(id) do nothing;
end;
$$
"""

async def test():
    cfg=Config()
    cfg.log(cfg.database)
    x = await sql("select version()", ONE) # для БД по умолчанию (defaults) можно не передавать DB
    print("Postgres version:", x)
    x = await sql("select sqlite_version()", ONE, DB("lite"))
    print("SQLite version:", x)
    #x = await sql("select version()", ONE, DB("mysql"))
    #print("MySql version:", x)

if __name__ == '__main__':
    # при использовании конфигурации из БД важно вызвать Config перед стартом основного цикла
    Config('postgresql://localhost:5432/postgres?user=postgres&password=postgres{"query":"select k, v, id, parent_id from config"}')
    run_async(test())