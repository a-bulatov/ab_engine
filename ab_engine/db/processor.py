from .option import Option, DB, TIMEOUT, PAGE, CALLBACK, ITERATOR
from .driver import RowFactory
from ..error import raise_error

CONNECTION:str = ""

def set_connection(connection_string:str):
    global CONNECTION
    CONNECTION = connection_string

async def sql(query:str, *args, **kwargs):
    process = []
    db = callback = tm = row_factory = one_row = page = itr = None
    for n, arg in enumerate(args):
        if Option.is_option(arg):
            if not process:
                process.append(n)
            if one_row is None and arg.one_row is not None:
                one_row = arg
            elif one_row and arg.one_row is not None and one_row.one_row!=arg.one_row:
                raise_error("NEQ_ROWS", src1=one_row.__class__.__name__, src2=arg.__class__.__name__)
            if row_factory is None or row_factory.row_factory == RowFactory.ANY:
                row_factory = arg
            elif row_factory and arg.row_factory != RowFactory.ANY:
                raise_error("DEF_STR_FABRIC", src = row_factory.__class__.__name__)
            if arg.can_process:
                process.append(arg)
                continue
            if arg == DB:
                arg = DB()
            if isinstance(arg, DB) and db is None:
                db = arg
            elif isinstance(arg, CALLBACK) and callback is None:
                callback = arg
            elif isinstance(arg, DB):
                raise_error("DB_ALRDY_DEF")
            elif isinstance(arg, PAGE) and page is None:
                page = arg
            elif isinstance(arg, PAGE):
                raise_error("PAGE_ALRDY_DEF")
            elif isinstance(arg, TIMEOUT) and tm is None:
                tm = arg
            elif isinstance(arg, TIMEOUT):
                raise_error("TIMEOUT_ALRDY_DEF")
            elif arg == ITERATOR:
                itr = ITERATOR()
            elif isinstance(arg, ITERATOR):
                itr = arg
        elif process:
            raise_error("PMT_BEF_OPT")
    if process:
        args = args[:process.pop(0)]
    if db is None:
        db = DB(CONNECTION)
        in_self = True
    else:
        in_self = False
    await db.garbage_collect(False)
    one_row = one_row.one_row if one_row else False
    row_factory = row_factory.row_factory if row_factory and row_factory.row_factory != RowFactory.ANY else RowFactory.DICT
    if callback:
        kwargs["__PARAM_CALLBACK_GETTER"] = callback
    query = await db.connection.parse_query(query, *args, **kwargs)
    if page:
        query = await page(db.connection, query)
    if callback is not None:
        query = await callback(query)
    if itr:
        if page:
            raise_error("PAGE_ITERATOR")
        return itr(query, db, row_factory, process)
    try:
        if tm is None:
            ret = await db.connection.sql(query, one_row=one_row, row_factory=row_factory)
        else:
            ret = await tm(db.connection.sql(query, one_row=one_row, row_factory=row_factory))
        for f in process:
            ret, row_factory = await f.process(ret, db.connection, row_factory)
            if row_factory is not None:
                break
    except Exception as e:
        try:
            if db.connection.in_transaction:
                await db.connection.rollback()
        except Exception as e2:
            ...
        raise e
    if in_self and db.connection.in_transaction:
        await db.connection.commit()
    return ret