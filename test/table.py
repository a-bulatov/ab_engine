from _imports import *

async def test():
    Config("test.toml")
    env = DB_ENV()
    tbl = await env.table("test", if_not_exists=[
        """
        create table test(
            id serial primary key,
            val varchar
        )""",
        """
        insert into test(val)
        select format('Запись № %s', generate_series)
        from generate_series(1, 100)
        """
    ])

    # выбрать записи с id==2 или id==5
    x = await tbl([
        tbl.row.id == 2,
        tbl.row.id == 5
    ])
    print(x)
    print("------------")

    # тоже выбрать записи с id==2 или id==5
    where = (tbl.row.id == 2) | (tbl.row.id == 5)
    print(where)
    x = await tbl(where)
    print(x)
    print("------------")

    # выбрать записи с val=="Запись № 7"
    x = await tbl(tbl.row.val=="Запись № 7", OBJECT)
    print(x)

    # обход всех записей курсора
    async for row in tbl:
        print(row.id.value, tbl.position) # вывод значения поля id и номер строки
    print("------------")

    # установить курсор на строку с номером 30
    await tbl.seek(30)
    for x in range(5):
        await tbl.prior() # передвинуть курмор на строку назад
        print(tbl.row) # вывод всех значений всех полей строки

    await tbl.first() # установить курсор на первую запись
    for x in range(5):
        print(tbl.row)
        await tbl.next() # перейти на следующую строку
    print("------------")
    await tbl.seek(3)
    print(tbl.row)
    # поменять значение поля val в строке 3
    tbl.row.val.value = "Новое значение" if tbl.row.val.value=="Запись № 4" else "Запись № 4"
    print(tbl.row)
    await env.commit() # сохранить изменения


if __name__ == '__main__':
    raise error("DB_ALRDY_DEF")
    run_async(test())