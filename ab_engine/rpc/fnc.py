from abc import ABC, abstractmethod
from inspect import iscoroutinefunction
from inspect import getdoc
from importlib.machinery import SourceFileLoader
from pathlib import Path

class Fnc(ABC):

    registry = {}

    def __init__(self, name, help):
        if name in Fnc.registry:
            raise RuntimeError(f"Funcion '{name}' is already registered")
        if isinstance(help, str):
            help = help.strip()
            if not help:
                help = None
        self._help = help
        Fnc.registry[name] = self

    @abstractmethod
    async def __call__(self, env, **kwargs):
        ...

    @classmethod
    def search(cls, name):
        f = Fnc.registry.get(name)
        return f

    @property
    def help(self):
        return self._help


class PythonFnc(Fnc):

    def __init__(self, name, f, help=None):
        """
        врапер для функции python
        :param name: имя функции для вызова RPC
        :param f: ссылка на функцию или корутину
        :param help: документация. если не задана, то будет взята из комментария к функции
        """
        if not help:
            help = getdoc(f)
        if iscoroutinefunction(f):
            async def wrapper_env(env, **kwargs):
                nonlocal f
                return await f(env, **kwargs)
            async def wrapper(env, **kwargs):
                nonlocal f
                return await f(**kwargs)
        else:
            async def wrapper_env(env, **kwargs):
                nonlocal f
                return f(env, **kwargs)
            async def wrapper(env, **kwargs):
                nonlocal f
                return f(**kwargs)
        if "env" in f.__code__.co_varnames:
            self.__f = wrapper_env
        else:
            self.__f = wrapper
        super().__init__(name, help)

    async def __call__(self, env, **kwargs):
        return await self.__f(env, **kwargs)


class PluginFnc(PythonFnc):

    modules = {}

    def __init__(self, name, module_path, help=None, fnc_name=None, module_name=None):
        """
        врапер для функции python, вызываемой из плагина
        :param name: имя функции для вызова RPC
        :param module_path: путь к модулю, содержащему функцию
        :param help: документация. если не задана, то будет взята из комментария к функции
        :param fnc_name: имя функции ыв модуле. если не задано, будет использовано name
        :param module_name: имя модуля в списке модулей (чтобы не грузить модуль повторно) если не задано - будет взято из пути
        """
        module_path = Path(module_path)
        if not fnc_name:
            fnc_name = name
        if not module_name:
            module_name = module_path.name
            if module_name.endswith(".py"):
                module_name = module_name[:-3]
        m = PluginFnc.modules.get(module_name)
        if not m:
            m = SourceFileLoader(module_name, str(module_path)).load_module()
            PluginFnc.modules[module_name] = m
        if not hasattr(m, fnc_name):
            raise RuntimeError(f"Funcion '{fnc_name}' is not found in module '{module_name}'")
        f = getattr(m, fnc_name)
        super().__init__(name, f, help)


class SqlFnc(Fnc):

    def __init__(self, name, query, help=None):
        """
        врапер для sql-запроса, вызываемого как функция
        :param name: имя функции для вызова RPC
        :param query: запрос
        :param help: документация
        """
        if callable(query):
            if not help:
                help = getdoc(query)
            query = query()
        if isinstance(query, str):
            self.__query = query
            self.__args = ()
        elif isinstance(query, tuple):
            self.__query = query[0]
            self.__args = query[1:]
        super().__init__(name, help)

    async def __call__(self, env, **kwargs):
        ret = await env.sql(self.__query, *self.__args, **kwargs)
        return ret