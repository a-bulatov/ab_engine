from typing import Optional, Callable
from os import sep as file_sep
from .fnc import *
from ..error import raise_error
from ..env import Config, DB_ENV
from sys import argv as sys_argv
from pathlib import Path


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
    if module.startswith(f".{file_sep}") or module.startswith(f"..{file_sep}"):
        module = _resolve_path(module)
    else:
        cfg = Config()
        if cfg.hasattr("defaults"):
            paths = cfg.defaults.get("plugin_path")
        else:
            paths = None
        if not paths:
            raise_error("REG_BAD_PLUG_DIR_DFLT", name=name, defs=defs)
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
    raise_error("REG_PLUG_NOT_FOUND", module=module, function=function if function else name)


def register(name:Optional[str|Callable]=None,defs=None, help=None) -> Callable:
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
        PythonFnc(name.__name__, name, help or defs)
        return name
    elif callable(defs):
        PythonFnc(name, defs, help)
        return defs
    elif defs is None:
        return wrapper
    elif isinstance(defs, Path):
        PluginFnc(name, defs, help)
    elif name and (isinstance(defs, tuple) or (isinstance(defs, str) and any(x.isspace() for x in defs))):
        SqlFnc(name, defs, help)
    elif name and isinstance(defs, str) and not (defs.startswith("/") or defs.startswith("~")):
        _load_by_default_path(name, defs, help)
    elif name and isinstance(defs, str):
        module, function = _split_module_fnc(defs)
        PluginFnc(name, module, help, function)
    else:
        raise_error("BAD_FN_PARAMS", name=name, defs=defs)
    return dummy


async def call_rpc(name_of_rpc_method_for_call, current_rpc_environment_for_call=None, **kwargs):
    """
    Выполняет вызов RPC
    :param current_rpc_environment_for_call: окружение, в котором будет выполняться метод
    :param name_of_rpc_method_for_call: имя метода
    :param kwargs: параметры
    :return: результат выполнения метода
    """
    if current_rpc_environment_for_call is None:
        current_rpc_environment_for_call = DB_ENV()
        local = True
    else:
        local = False
    if isinstance(name_of_rpc_method_for_call, str):
        f = Fnc.search(name_of_rpc_method_for_call)
        if f is None:
            raise_error("FN_NOT_FOUND", method=name_of_rpc_method_for_call)
    elif not isinstance(name_of_rpc_method_for_call, Fnc):
        raise_error("BAD_RPC_METHOD")
    else:
        f = name_of_rpc_method_for_call
    try:
        ret = await f(current_rpc_environment_for_call, **kwargs)
        if local and current_rpc_environment_for_call.in_transaction:
            await current_rpc_environment_for_call.commit()
        return ret
    except Exception as e:
        if current_rpc_environment_for_call.in_transaction:
            await current_rpc_environment_for_call.rollback()
        raise e