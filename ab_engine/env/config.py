from typing import Optional
from datetime import datetime
from json import dumps, loads
from json5 import loads as json5_load
from yaml import safe_load as yaml_load
from toml import loads as toml_load
from pathlib import Path
from os import environ as ENV
import logging as LOG
from enum import Enum
from .timer import TimerList
from ..class_tools import classproperty
from ..error import raise_error, error_msg
import asyncio


class LogLevel(Enum):
    CRITICAL = LOG.CRITICAL
    FATAL = LOG.FATAL
    ERROR = LOG.ERROR
    WARNING = LOG.WARNING
    WARN = LOG.WARN
    INFO = LOG.INFO
    DEBUG = LOG.DEBUG
    SQL = LOG.DEBUG - 5
    NOTSET = LOG.NOTSET
    OFF = -1


class LogRecord(LOG.LogRecord):
    ext_data = {}
    # доп параметры в логер
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if len(args) > 1:
            self.sys_level = {
                LOG.CRITICAL: 2,
                LOG.FATAL: 2,
                LOG.ERROR: 3,
                LOG.WARNING: 4,
                LOG.INFO: 6,
                LOG.DEBUG: 7,
            }.get(args[1], 7)
        else:
            self.sys_level = 6
        for x in LogRecord.ext_data:
            setattr(self, x, LogRecord.ext_data[x])

def typed_val(key, values: dict):
    v = values.get(key)
    if v is None:
        return None
    elif "(" in key:
        key, t = key.split("(", 1)
        if not t.endswith(")"):
            return v
        match t.upper():
            case 'INT)':
                return int(v), key
            case 'STR)':
                return str(v), key
            case 'FLOAT)':
                return float(t), key
            case _:
                return v
    return v, key


def from_env(key:str, key_map:dict):
    ret = {key_map[x]: ENV[x] for x in key_map if x in ENV}
    if key and "." in key:
        eval_key = key.split(".")
        eval_key = [f"['{x}']" for x in eval_key]
        eval_key = "x" + "".join(eval_key)
    else:
        eval_key = f"x['{key}']"
    node = eval(eval_key, {"x": Config._settings}) if key else Config._settings[key]
    node.update(ret)

__CONF__ = None


class Config:
    _settings = None

    def __new__(cls, *args, **kwargs):
        global __CONF__
        if not __CONF__:
            __CONF__ = super().__new__(cls)
        return __CONF__

    @classproperty
    def initialized(cls):
        return cls._settings is not None

    def __init__(self, path: Optional[str | list[str] | dict] = None, env_map: Optional[dict] = None, can_include: Optional[list]=None) -> None:
        if Config.initialized:
            return

        Config._settings, env = {}, None

        def load(fn):
            if "://" in fn:
                x = asyncio.run(self._config_from_db(fn))
                return x
            with Path(fn).open() as f:
                data = f.readlines()
            data = ''.join(data)
            match Path(fn).suffix.lower():
                case ".json" | ".json5":
                    return json5_load(data)
                case ".yaml" | ".yml":
                    return yaml_load(data)
                case ".toml":
                    return toml_load(data)
                case _:
                    raise_error("BAD_FORMAT", format_name=fn)

        self._log_level = LogLevel.INFO
        if path is None:
            raise_error("BAD_CONFIG_PATH")
        elif isinstance(path, dict):
            Config._settings = path
        elif isinstance(path, str):
            Config._settings = load(path)
        elif isinstance(path, list):
            Config._settings = load(path.pop(0))
            for fn in path:
                data = load(fn)
                for x in data:
                    item = data[x]
                    dest = Config._settings.get(x)
                    if isinstance(dest, dict):
                        dest.update(item)
                    else:
                        data[x] = item

        if not Config._settings:
            Config._settings = {}
        if env_map:
            for x in env_map:
                from_env(x, env_map[x])
        if can_include:
            for x in can_include:
                f = Config._settings.get(x)
                if isinstance(f, str):
                    Config._settings[x] = load(f)
        if "logging" in Config._settings:
            self._logger = ...
            if self.logger:
                self.log(error_msg("INFO_LOG_START").message)
            del Config._settings["logging"]
        else:
            self._logger = None

        if "timers" in Config._settings:
            self._timers = TimerList()
            f = Config._settings["timers"]
            for x in f:
                self._timers.add(x, interval=f[x])
            del Config._settings["timers"]
        else:
            self._timers = None
        if "defaults" not in Config._settings:
            Config._settings["defaults"] = {}
        x = Config._settings.get("database")
        if isinstance(x, dict):
            Config._settings["defaults"]["database"] = tuple(x.keys())[0]

    @staticmethod
    def _cast(value, to_type):
        if value is None:
            return None
        elif to_type == "I":
            return int(value)
        elif to_type == "F":
            return float(value)
        elif to_type == "B" and value:
            return True
        elif to_type == "B":
            return False
        else:
            return str(value)

    async def _config_from_db(self, connection: str) -> dict:
        """
        считывает настройки из БД
        в параметрах соединения можно задать (внутри фигурных скобок, одной строкой без переносов, маленькими буквами)
        query - запрос для получения настроек, в запросе должны быть указаны поля в следующем порядке:
          1 - поле ключа
          2 - поле значения
          3 - идентификатор записи
          4 - идентификатор родительской записи
        также возможен вариант, когда
          4 - тип значенгия
          5 - идентификатор родительской записи
          в этом случае конфигуратор понимает следующие типы:
            I - int
            F - float
            S - str
            B - bool
          преобразование типа происходит в функции Config._cast(value, to_type) т.е. наследники Config могут обрабатывать
          другие типы.

        если в запросе указано where, то это условие будет добавлено во все запросы
        при построении конфигурации.

        по умолчанию запрос:
        select k, v, id, parent_id from config

        соответственно самый простой вариант таблицы:
        create table config(
            id serial not null primary key,
            parent_id integer references config(id),
            k varchar(150) not null,
            v varchar,
            constraint config_level_uk unique (parent_id, k)
        )
        """
        query = "select k, v, id, parent_id from config"
        if connection.endswith("}"):
            connection, params = connection.split("{", 1)
            params = loads(f"{{{params}")
            if x := params.get("query"):
                del params["query"]
                query = x
            if params:
                connection += dumps(params)
        if " where" in query:
            query, ext_where = query.rsplit(" where", 1)
            ext_where = f"\nand {ext_where}"
        else:
            ext_where = ""
        query, env = query.rsplit(" from ", 1)
        query, parent_id = query.rsplit(",", 1)
        parent_id = parent_id.strip()
        query += f", {parent_id} from {env}"
        try:
            from .db_context import DB_ENV, TUPLE
        except Exception as e:
            from db_context import DB_ENV, TUPLE
        env = DB_ENV(connection)

        async def load_level(where: str) -> dict:
            nonlocal env, query, parent_id, ext_where
            lst = await env.sql(query + "\nwhere " + where + ext_where, TUPLE)
            ret = {}
            with_tp = lst and len(lst[0]) >= 5
            for x in lst:
                childs = await load_level(f"{parent_id}={x[2]}")
                if childs:
                    ret[x[0]] = childs
                elif with_tp:
                    ret[x[0]] = self._cast(x[1], x[3])
                else:
                    ret[x[0]] = x[1]
            return ret

        ret = await load_level(f"{parent_id} is null")
        await env.commit()
        return ret

    def __getattr__(self, item):
        if not(item in Config._settings):
            raise_error("ATTR_NOT_FOUND", name=item)
        return Config._settings[item]

    @property
    def timers(self) -> TimerList:
        """
        Возвращает таймеры, перечисленные в секции timers
        таймер должен быть проинициализирован:
          init(callback, interval_type = TimerInterval.SECOND, interval: int = 0, immediately_start=True)
            calback       - обработчик таймера, может быть как async, так и синхронным
            interval_type - тип интервала (единица времени) MILLISECOND, SECOND, MINUTE, HOUR, DAY по умолчанию SECOND
            interval      - количество единиц времени, если задан, то перекроет считанное из конфига
            immediately_start - означает, что calback будет запущен сразу после инициализации, иначе через интервал
        например:
          cfg.init(callback, interval_type = TimerInterval.MINUTE):
        callbac должен быть функцией вида:
          def callback(name, prev_time):
              ...
          или:
          async def callback(name, prev_time):
              ...
          в параметр name передается в имя таймера, в prev_time предыдущее время запуска, первый раз prev_time = None
        дополнительные методы:
          start() - запускает таймер, если он остановлен или запущен с immediately_start=False
          stop()  - останавливает таймер. остановленный таймер можно зпустить методом start()
        :return: ab_engine.env.timer.Timer
        """
        return self._timers

    @staticmethod
    def hasattr(item):
        return item in Config._settings

    @staticmethod
    def _parse_log_level(level)->LogLevel:
        if isinstance(level, str):
            level = LogLevel[level.upper()]
        elif isinstance(level, int):
            level = LogLevel(level)
        elif isinstance(level, LogLevel):
            ...
        else:
            ValueError("Не понятен уровень лога")
        if level == LogLevel.SQL:
            level = LogLevel.DEBUG
        return level

    @property
    def log_level(self) -> LogLevel:
        return self._log_level

    @property
    def logger(self) -> LOG.Logger:
        if self._logger is not ...:
            return self._logger
        if not "level" in self.logging:
            self.logging["level"] = "info"
        if self.logging["level"].upper() == "SQL":
            self._log_level = LogLevel.SQL
        else:
            self._log_level = self._parse_log_level(self.logging["level"])
        self._logger = None
        if self._logger == LogLevel.OFF:
            return None
        LogRecord.ext_data = self.logging.get("ext_data", {})
        LOG.setLogRecordFactory(LogRecord)

        defs = {
            # '<%(sys_level)s>[%(service)s][%(asctime)s][%(levelname)s][%(filename)s:%(lineno)s]: %(message)s'),
            "format": self.logging.get("format", '[%(asctime)s][%(levelname)s][%(filename)s:%(lineno)s]: %(message)s'),
            "datefmt": self.logging.get("datefmt", '%m.%d.%Y %H:%M:%S'),
            "level": LOG.DEBUG if self._log_level.value == 5 else self._log_level.value
        }
        if not "handler" in self.logging:
            # Handler не задан ----------------------------------------------------------------------------------------
            for x in ("filename", "filemode"):
                v = self.logging.get(x)
                if v:
                    if x == "filename":
                        Path(v).parents[0].mkdir(parents=True, exist_ok=True)
                    defs[x] = v

            LOG.basicConfig(**defs)
            self._logger = LOG.getLogger()  # =logging.root
            return self._logger

        # Handler задан -----------------------------------------------------------------------------------------------
        lst = []

        def get_childs(cla):
            nonlocal lst
            lst.append(cla)
            for x in cla.__subclasses__():
                get_childs(x)

        hndl = self.logging["handler"]["class"]
        for x in LOG.Handler.__subclasses__():
            if x.__name__ == self.logging["handler"]:
                hndl = x
                break

        if isinstance(hndl, str):
            import logging.handlers

            get_childs(logging.Handler)

            for x in lst:
                if x.__name__ == hndl:
                    hndl = x
                    break
            if isinstance(hndl, str):
                raise_error("BAD_LOG_HANDLER", handler=self.logging['handler'])

        self._logger = logging.getLogger(self._name)

        params = {}
        for x in self.logging["handler"]:
            if x in ("class", "property"):
                continue
            v, x = typed_val(x, self.logging["handler"])

            if v is not None:
                if x == "filename":
                    Path(v).parents[0].mkdir(parents=True, exist_ok=True)
                params[x] = v
        def get_log_filename(filename):
            # Получаем директорию, где расположены логи
            log_directory = Path(filename).parent
            x = datetime.now().strftime("%Y%m%d")
            # Сформировали имя нового лог-файла
            filename = f"{log_directory / x}"
            x = f"{filename}.log"
            if not Path(x).exists():
                return x
            # Найдём минимальный индекс файла на текущий момент.
            index = 0
            f = f"{filename}.{index}.log"
            while Path(f).exists():
                index += 1
                f = f"{filename}.{index}.log"
            return f

        if self.logging["handler"]["class"] == "TimedRotatingFileHandler":
            x = params.get('filename')
            if x is None:
                raise_error("NA_FILE_NAME")
            Path(x).parents[0].mkdir(parents=True, exist_ok=True)
            with open(x, 'a'):
                ...
            hndl = hndl(**params)
            hndl.namer = get_log_filename
        else:
            hndl = hndl(**params)

        if "property" in self.logging["handler"]:
            for x in self.logging["handler"]["property"]:
                v, x = typed_val(x, self.logging["handler"]["property"])

                if v is not None:
                    if x == "filename":
                        Path(v).parents[0].mkdir(parents=True, exist_ok=True)
                    setattr(hndl, x, v)

        formatter = LOG.Formatter(
            defs["format"],
            defs["datefmt"]
        )
        hndl.setFormatter(formatter)

        self._logger.addHandler(hndl)
        return self._logger

    def log(self, msg, level:LogLevel | str | int=LogLevel.INFO, *args, **kwargs):
        """
        запись в лог
        :param msg: сообщение об ошибке. может быть экземпляром Exception
        :param level: уровень сообщения, для msg = Exception автомаптически вставляется ERROR. Может быть передан как строка
        :param args:  --/- зарезервировано для дальнейшего использования
        :param kwargs:-/
        """
        if self._log_level == LogLevel.OFF:
            return
        try:
            log_to = self.logger
        except Exception as e:
            log_to = None

        if isinstance(msg, Exception):
            level = LogLevel.ERROR
        else:
            level = self._parse_log_level(level)
            msg = str(msg)
        if level.value < self.log_level.value:
            return

        if not log_to:
            print(level.name, msg, flush=True)
            return

        try:
            params = {
                "name": log_to.name,
                "level": level.value,
                "fn": "",
                "lno": 0,
                "args": args,
                "exc_info": None,
                "func": "",
                "extra": None,
                "sinfo": None
            }
            if self._log_level.value <= LogLevel.DEBUG.value or isinstance(msg, Exception):
                if 'stacklevel' not in kwargs:
                    lvl = 2
                    info = log_to.findCaller(stacklevel=lvl)
                    p = str(Path(__file__).parent.parent)
                    while info[0].startswith(p):
                         lvl += 1
                         x = log_to.findCaller(stacklevel=lvl)
                         if '/venv/' in x[0]:
                             break
                         elif not x[0].startswith(p):
                             info = x
                             break
                         else:
                             info = x
                else:
                    info = log_to.findCaller(stacklevel=kwargs.get('stacklevel', 2))

                if isinstance(msg, Exception):
                    params["fn"] = info[0]
                else:
                    x = info[0].rsplit("/", 2)
                    del x[0]
                    params["fn"] = '/'.join(x)
                params["func"] = info[2]
                params["lno"] = info[1]

            if "timer" in kwargs:
                n = kwargs["timer"]
                x = self.__log_timers.get(n)
                if x:
                    x = datetime.now() - x
                    msg = f'{msg} [ {x} ]'
                self.__log_timers[n] = datetime.now()

            params["msg"] = f"{msg}"
            info = log_to.makeRecord(**params)
            log_to.handle(info)
        except Exception as e:
            # Больше вывести некуда - выводим на стандартный вывод
            print(level, msg, flush=True)
            print("LOGGER ERROR: ", str(e), flush=True)

    def db_connection(self, connection:str="")->str:
        if not Config.hasattr("database"):
            raise_error("NA_DB_IN_CONFIG")
        db = self.database
        if isinstance(db, str) and connection=="":
            return db
        if isinstance(db, dict):
            dflt = self.defaults if self.hasattr("defaults") else {}
            db = db.get(connection, db.get(dflt.get("database", "main")))
        if not db:
            raise_error("NA_DB", connection=connection)
        return db