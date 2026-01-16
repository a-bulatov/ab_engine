from yaml import safe_load
from .class_tools import find_subclass
from collections import defaultdict
from pathlib import Path
from os import sep as pathsep
from collections import namedtuple

_ERRORS = {}

def load_errors(file_name):
    if pathsep in file_name:
        f = Path(file_name)
    else:
        f = Path(__file__).parent / file_name
    with f.open("r") as stream:
        data = stream.readlines()
    data = ''.join(data)
    data = safe_load(data)
    data = {x["code"]:x for x in data}
    _ERRORS.update(data)

class Error(Exception):

    def __init__(self, code, http_code:int, message:str):
        self._code = code
        self._http_code = http_code
        super().__init__(message)

    @property
    def code(self):
        return self._code

    @property
    def http_code(self)->int:
        return self._http_code

ErrorData = namedtuple("Error", ["code", "http_code", "message", "class_name"])

class BadError(Error):

    def __init__(self, code, http_code:int, not_found, *args, **kwargs):
        args = list(args)
        not_found = f"!!! UNKNOWN ERROR CLASS {not_found} !!!"
        if len(args) > 0:
            args[0] = f"{args[0]}\n{not_found}"
            args = tuple(args)
        else:
            args = (not_found,)
        super().__init__(code, http_code,*args, **kwargs)

def error_msg(code, *args, **kwargs)->ErrorData:
    global _ERRORS
    if not _ERRORS:
        load_errors("error.yaml")
    if isinstance(code, int):
        h_code = code
    else:
        code = str(code).upper()
        h_code = 501
    info = _ERRORS.get(code, {
        "http": 501,
        "msg": f"Unknown error\n{str(kwargs)}".replace("{", "/")
    })
    h_code = info.get("http", h_code)
    if msg:= info.get("msg"):
        msg = msg.format_map(defaultdict(lambda: "", kwargs))
    return ErrorData(code=code, http_code=h_code, message=msg, class_name=info.get("class"))


def error(code, *args, **kwargs):
    err = error_msg(code, *args, **kwargs)

    if err.class_name and err.class_name != "Error":
        cls = find_subclass(BaseException, err.class_name)
        if cls is None:
            raise BadError(code, err.http_code, err.message, err.class_name, *args, **kwargs)
    else:
        cls = Error
    if cls is None:
        return Error(code, err.http_code, err.message)
    elif find_subclass(Error, cls.__name__):
        return cls(code, err.http_code, err.message)
    return cls(err.message, *args)


def raise_error(code, *args, **kwargs):
    raise error(code, *args, **kwargs)
