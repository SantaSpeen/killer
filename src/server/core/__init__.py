import argparse
import logging
import os
import platform
import sys
from datetime import datetime

from loguru import logger

from .config import Config
from .datastore import Host, HostDatabase

aparser = argparse.ArgumentParser(description="Killer server")
aparser.add_argument("-c", "--config", type=str, default="/etc/killer/config.json", help="Path to config file")
args = aparser.parse_args()

config = Config(args.config)

# configure logging
logger.remove()
system = platform.system()
if system == "Linux":
    # Logging
    if config.log.stdout.enabled:
        logger.add(**config.stdout_log)
    if config.log.file.enabled:
        f, f_args = config.file_log
        if f.exists():
            ftime = os.path.getmtime(f)
            index = 1
            while True:
                rename_path = f.parent / f"killer-{datetime.fromtimestamp(ftime).strftime('%Y-%m-%d')}-{index}.log"
                if not rename_path.exists():
                    break
                index += 1
            os.rename(f, rename_path)
        logger.add(f, **f_args)
else:
    logger.add(sys.stdout, level="DEBUG", backtrace=False, diagnose=False, enqueue=True,
               format="\r<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | {message}")
    logger.add("debug.log", level="DEBUG", rotation="10 MB", retention="30 day")

class InterceptHandler(logging.Handler):
    def emit(self, record):
        logger_opt = logger.opt(depth=6, exception=record.exc_info)
        logger_opt.log(record.levelno, record.getMessage())

logger.success("Starting")
