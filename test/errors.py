from _imports import raise_error, load_errors

load_errors("./errors.yaml")

try:
    raise_error("ERROR", place="программе", name="в коде", what="страшное")
except Exception as e:
    print(type(e))
    print(e)
    print("CODE:", e.code)
    print("HTTP CODE:",e.http_code)

try:
    raise_error("OTHER_ERROR")
except Exception as e:
    print(type(e))
    print(e)