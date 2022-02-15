import logging
import sys
from datetime import datetime
from logging import Handler
from pathlib import Path
from typing import Optional

import coloredlogs
import yaloader
from baselooper import Module, ModuleConfig, State


class LogHandler(Module):
    def __init__(self, time_stamp: Optional[datetime], **kwargs):
        super().__init__(**kwargs)
        self.time_stamp = time_stamp
        self.handler: Optional[Handler] = None

    def set_handler(self, handler: Handler):
        if self.handler is None:
            self.handler = handler
            logging.getLogger().addHandler(self.handler)

    def teardown(self, state: State) -> None:
        if self.handler is not None:
            self.handler.close()
            logging.getLogger().removeHandler(self.handler)
        self.handler = None


class LogHandlerConfig(ModuleConfig):
    time_stamp: Optional[datetime] = datetime.utcnow().replace(microsecond=0)


class FileLogBase(LogHandler):
    def __init__(self, log_dir: Path, **kwargs):
        super().__init__(**kwargs)
        self.log_dir = log_dir if self.time_stamp is None else log_dir.joinpath(str(self.time_stamp))
        self.log_dir.mkdir(parents=True, exist_ok=True)


class FileLogBaseConfig(LogHandlerConfig):
    log_dir: Path


class TextFileLog(FileLogBase):
    def __init__(self, level: int = logging.WARNING, **kwargs):
        super().__init__(**kwargs)
        handler = logging.FileHandler(self.log_dir.joinpath("log"))
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter(
            fmt='%(asctime)s %(name)s %(levelname)s %(message)s',
            datefmt=coloredlogs.DEFAULT_DATE_FORMAT
        ))
        self.set_handler(handler)


@yaloader.loads(TextFileLog)
class TextFileLogConfig(FileLogBaseConfig):
    pass


class ConsoleLog(LogHandler):
    def __init__(self, level: int = logging.WARNING, **kwargs):
        super().__init__(**kwargs)
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(level)
        handler.setFormatter(coloredlogs.ColoredFormatter(
            fmt='%(asctime)s %(name)s %(levelname)s %(message)s',
            datefmt=coloredlogs.DEFAULT_DATE_FORMAT
        ))

        self.set_handler(handler)


@yaloader.loads(ConsoleLog)
class ConsoleLogConfig(LogHandlerConfig):
    level: int = logging.WARNING
