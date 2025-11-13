from _imports import *


def timer_test(name, prev_time):
    cfg = Config()
    cfg.log(f"timer test {name} {prev_time}")
    if name == "A":
        if cfg.timers["B"].started:
            cfg.log("STOP timer B")
            cfg.timers["B"].stop()
        else:
            cfg.log("START timer B")
            cfg.timers["B"].start()


async def timers():
    Config("test.toml")
    Config().timers["A"].init(timer_test, "minute", immediately_start=False)
    Config().timers["B"].init(timer_test)
    Config().timers["A"].start(immediately_start=False)
    while True:
        await sleep(1)


if __name__ == '__main__':
    run_async(timers())