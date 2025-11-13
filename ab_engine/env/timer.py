from enum import Enum
from datetime import datetime, timedelta
from inspect import iscoroutinefunction
from ..error import raise_error
import asyncio

class TimerInterval(Enum):
    MILLISECOND = 1
    SECOND = 1000 * MILLISECOND
    MINUTE = 60 * SECOND
    HOUR = 60 * MINUTE
    DAY = 24 * HOUR

class Timer:

    def __init__(self, interval: int = 10, interval_type = TimerInterval.SECOND, name:str=""):
        self._last_tm = None
        self._task = None
        self._callback = None
        self._interval_type = interval_type
        self._interval = abs(interval)
        self._name = name

    async def _do_task(self):
        chk = self._interval_type.value * self._interval
        t = (chk / 4) // 1000
        chk = timedelta(milliseconds=chk)
        if self._last_tm:
            if iscoroutinefunction(self._callback):
                await self._callback(self.name, None)
            else:
                self._callback(self.name, None)
        else:
            self._last_tm = datetime.now()
        while self._task is not None:
            await asyncio.sleep(t)
            if (datetime.now() - self._last_tm) < chk:
                continue
            if self._task is None:
                break
            try:
                if iscoroutinefunction(self._callback):
                    await self._callback(self.name, self._last_tm)
                else:
                    self._callback(self.name, self._last_tm)
            except Exception as e:
                ...
            finally:
                self._last_tm = datetime.now()

    @property
    def name(self):
        return self._name

    def init(self, callback, interval_type = TimerInterval.SECOND, interval: int = 0, immediately_start=True):
        if isinstance(interval_type, str):
            interval_type = TimerInterval[interval_type.upper()]
        if self._task:
            self._task = None
        if interval:
            self._interval = interval
        if interval_type:
            self._interval_type = interval_type
        self._callback = callback
        if immediately_start:
            self.start()

    def start(self, immediately_start=True):
        if self._callback is None:
            raise_error("TMR_WO_CALLBACK", name = self._name)
        if self._task:
            raise_error("TMR_ARDY_STARTED", name = self._name)
        if immediately_start:
            self._last_tm = datetime.now()
        else:
            self._last_tm = None
        self._task = asyncio.create_task(self._do_task())

    def stop(self):
        if self._task is None:
            raise_error("TMR_ARDY_STOPPED", name = self._name)
        self._task = None

    @property
    def started(self):
        return self._task is not None


class TimerList:

    def __init__(self):
        self._timers = {}

    def add(self, name:str, interval: int = 10, interval_type = TimerInterval.SECOND, callback=None, immediately_start=True):
        if name in self._timers:
            raise_error("TMR_ARDY_EXISTS", name=name)
        self._timers[name] = Timer(interval=interval, interval_type=interval_type, name=name)
        if callback:
            self._timers[name].init(callback=callback, immediately_start=immediately_start)

    def __getitem__(self, item)->Timer:
        if not item in self._timers:
            raise_error("TMR_NOT_EXISTS", name=item)
        return self._timers[item]