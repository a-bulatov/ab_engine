from typing import Optional, Callable
from os import sep as file_sep
from .fnc import *
from ..error import error
from ..env import Config, DB_ENV
from ..db.option import Option
from sys import argv as sys_argv, modules
from pathlib import Path
import inspect

def _split_module_fnc(module_name: str):
    # можно передать в пути реальное имя функции после :
    module, function = f":{module_name}".rsplit(":", 1)
    if not module:
        return function.strip(), None
    else:
        return module[1:].strip(), function.strip()


def _resolve_path(path:str):
    if path.startswith(f".{file_sep}"):
        path = Path(sys_argv[0]).parent / path[len(file_sep)+1:]
    elif path.startswith(f"..{file_sep}"):
        p = Path(sys_argv[0]).parent
        path = path[len(file_sep) + 2:]
        while path.startswith(f"..{file_sep}"):
            p = p.parent
            path = path[len(file_sep) + 2:]
        path = p.parent / path[len(file_sep) + 1:]
    return path


def _load_by_default_path(name, defs, help):
    module, function = _split_module_fnc(defs)
    paths = None
    if module.startswith(f".{file_sep}") or module.startswith(f"..{file_sep}"):
        paths = _resolve_path(module)
        module = paths.name
        paths = [str(paths.parent)]
    else:
        cfg = Config()
        if cfg.hasattr("defaults"):
            paths = cfg.defaults.get("plugin_path")
    if not paths:
        raise error("REG_BAD_PLUG_DIR_DFLT", name=name, defs=defs)
    if isinstance(paths, str):
        paths = paths.split(";") ################
    ends, module = f"{file_sep}{module}".rsplit(file_sep,1)
    if not module:
        module = ends
        ends = None
    if not module.endswith(".py"):
        module = f"{module}.py"
    for path in paths:
        path = _resolve_path(path)
        if ends and not path.endswith(ends):
            continue
        path = Path(path) / module
        if path.is_file():
            PluginFnc(name, path, help, function)
            return
    raise error("REG_PLUG_NOT_FOUND", module=module, function=function if function else name)


def register(name:Optional[str|Callable]=None,defs=None, help=None, **kwargs) -> Callable:
    """
    Регистрирует запрос, плагин или функцию python как метод RPC.
    Данная функция работает и как обычная функция с параметрами и как декоратор
    :param name: имя для RPC вызова функции
    :param defs: для sql и плагинов - определение функции. для функции python - ссылка на функцию.
            при использовании в качестве декоратора, в defs может быть задано имя функции для вызова RPC
            определение sql это текст запроса, в том числе с расширениями, поддерживаемыми DB_ENV, либо tuple,
            где первый элемент это запрос, а остальные параметры, передаваемые в *args при вызове запроса.
            определение плагина не включает пробельных символов и может быть задано в одном из следующих вариантов:
            * путь к модулю, содержащему функцию
            * имя модуля, содержащего функцию (будет найден по путям поиска, заданным в конфиг. defaults.plugin_path
            * путь или имя модуля:имя функции - позволяет вызывать функцию, имя которой отличается от имени при RPC
            если register вызывается как декоратор и имя декорируемой функции SQL, то эта функция немедленно вызывается,
            результатом такой функции может быть строка запроса, либо tuple, где первый элемент это запрос, а остальные
            параметры, передаваемые в *args при вызове запроса. Документация функции SQL становится
            документацией RPC функции.
    :param help: позволяет переопределить документацию функции
    """

    def wrapper(f):
        if not iscoroutinefunction(f) and name and f.__name__ == "SQL" and len(f.__code__.co_varnames)==0:
            SqlFnc(name, f, help)
        else:
            PythonFnc(name if name else f.__name__, f, help)
        return f

    def dummy():
        ...

    if callable(name):
        PythonFnc(name.__name__, name, help or defs, **kwargs)
        return name
    elif callable(defs):
        PythonFnc(name, defs, help, **kwargs)
        return defs
    elif defs is None:
        return wrapper
    elif isinstance(defs, Path):
        PluginFnc(name, defs, help, **kwargs)
    elif name and (isinstance(defs, tuple) or (isinstance(defs, str) and any(x.isspace() for x in defs))):
        SqlFnc(name, defs, help)
    elif name and isinstance(defs, str) and not (defs.startswith("/") or defs.startswith("~")):
        _load_by_default_path(name, defs, help)
    elif name and isinstance(defs, str):
        module, function = _split_module_fnc(defs)
        PluginFnc(name, module, help, function, **kwargs)
    else:
        raise error("BAD_FN_PARAMS", name=name, defs=defs)
    return dummy


async def call_rpc(name_of_rpc_method_for_call, current_rpc_environment_for_call=None, **kwargs):
    """
    Выполняет вызов RPC
    :param current_rpc_environment_for_call: окружение, в котором будет выполняться метод
    :param name_of_rpc_method_for_call: имя метода
    :param kwargs: параметры
    :return: результат выполнения метода
    """
    if isinstance(name_of_rpc_method_for_call, str):
        f = Fnc.search(name_of_rpc_method_for_call)
        if f is None:
            raise error("FN_NOT_FOUND", method=name_of_rpc_method_for_call)
    elif not isinstance(name_of_rpc_method_for_call, Fnc):
        raise error("BAD_RPC_METHOD")
    else:
        f = name_of_rpc_method_for_call
    if current_rpc_environment_for_call is None and Config._settings is not None:
        current_rpc_environment_for_call = DB_ENV()
        local = True
    else:
        local = False
    try:
        ret = await f(current_rpc_environment_for_call, **kwargs)
        if local and current_rpc_environment_for_call.in_transaction:
            await current_rpc_environment_for_call.commit()
        return ret
    except Exception as e:
        if current_rpc_environment_for_call.in_transaction:
            await current_rpc_environment_for_call.rollback()
        raise e

def split_params(params:str)->list:
    ret, s, q, lq = [], "", "", False

    def add_ret():
        nonlocal ret, s, lq
        if lq:
            ret.append(s)
            lq = False
            return
        elif s == "":
            ret.append(None)
            return
        elif s.isnumeric():
            try:
                s = int(s)
            except Exception as e:
                s = float(s)
            ret.append(s)
            return
        lwr = s.lower()
        if s == "true":
            ret.append(True)
        elif s == "false":
            ret.append(False)
        else:
            ret.append(s)

    for ch in params:
        if ch == q:
            q = ""
            lq = True
        elif ch in ('"',"'"):
            q = ch
        elif ch == "," and q == "":
            add_ret()
            s = ""
        else:
            s += ch

    if s:
        add_ret()
    return ret


def register_list(defs:list | dict, self=None)->None:
    """
    Регистрирует для RPC функции, переданные в списке или в словаре.
    в случае, если описания передаются в словаре, то ключ словаря это имя функции в API
    если описания передаются списком, то имя функции передается в атрибуте name
    :param defs: писок или словарь с описанием функций, элементыы которого имеют следующую структуру:
        name: имя функции в API (не нужно, если описание передается в словаре)
        function: имя реально вызываемой функции, если оно отличается от name
        sql: запрос sql, реализующий функцию, если передан sql, то не нужно передавать function и type
        help: описание функции. если не задано - берется из функции
        type: тип функции
            self - функция из объекта, переданного в параметре self (см. ниже)
            py   - функция из плагина python
            db   - функция БД
        для функций с типом self для которых name==function возможна запись:
            имя_функции: self
        ext: дополнительные параметры регистрации, если нужны. для sql это могут быть опции или их имена
    :param self: объект или модуль, из которого берем функции с типом self. если не передан,
            то из модуля, откуда вызвана данная функция
    """
    if self is None:
        frame = inspect.currentframe().f_back
        x = frame.f_globals.get('__name__')
        self = modules.get(x)
    if isinstance(defs, dict):
        ...
    elif isinstance(defs, list):
        defs = {x["name"]:x for x in defs}
    else:
        raise error("BAD_RPC_FORMAT")
    for x in defs:
        fnc = defs[x]
        if "sql" in fnc:
            if "ext" in fnc:
                fn = []
                if isinstance(fnc["ext"], str):
                    fnc["ext"] = [fnc["ext"],]
                for opt in fnc["ext"]:
                    if not isinstance(opt, str):
                        fn.append(opt)
                        continue
                    if "(" in opt:
                        opt, params = opt.split("(",1)
                        params = params.strip()
                        if not params.endswith(")"):
                            raise error("NOT_FOUND_)", context=f"ext: {fnc['ext']}")
                        params = split_params(params[:-1].strip())
                        opt = Option.create(opt, *params)
                    else:
                        opt = Option.create(opt)
                    fn.append(opt)
                fn = tuple([fnc["sql"]] + fn)
            else:
                fn = fnc["sql"]
            SqlFnc(x, fn, help=fnc.get('help'))
        elif fnc == "self":
            fn = getattr(self, x)
            PythonFnc(x, fn)
        else:
            match fnc.get("type", "db"):
                case "db":
                    SqlFnc(x, f"\JSON {fnc['function']}(JSONB)", help=fnc.get('help'))
                case "self":
                    fn = getattr(self, fnc['function'])
                    PythonFnc(x, fn, help = fnc.get('help') )
                case _:
                    register(x, fnc["function"], help = fnc.get('help'))