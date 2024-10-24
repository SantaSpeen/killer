import glob
import logging
import os
import platform
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from loguru import logger

# configure logging
logger.remove()
system = platform.system()
if system == "Linux":
    # Logging
    log_dir = Path("/var/log/")
    log_file = log_dir / "killer-client.log"
    os.makedirs(log_dir, exist_ok=True)
    if os.path.exists(log_file):
        ftime = os.path.getmtime(log_file)
        index = 1
        while True:
            zip_path = log_dir / f"dhcp-{datetime.fromtimestamp(ftime).strftime('%Y-%m-%d')}-{index}.zip"
            if not os.path.exists(zip_path):
                break
            index += 1
        with zipfile.ZipFile(zip_path, "w") as zipf:
            logs_files = glob.glob(f"{log_dir}/killer-client*.log")
            for file in logs_files:
                if os.path.exists(file):
                    zipf.write(file, os.path.basename(file))
                    os.remove(file)
    logger.add(sys.stdout, level=0, backtrace=False, diagnose=False, enqueue=True, colorize=False, format="| {level: <8} | {message}")
    logger.add(log_file, level=0, rotation="10 MB", retention="30 day")
    # Configurations
    os.makedirs("/etc/killer/", exist_ok=True)
else:
    logger.add(sys.stdout, level=0, backtrace=False, diagnose=False, enqueue=True,
               format="\r<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | {message}")
    logger.add("debug.log", level=0, rotation="10 MB", retention="30 day")

class InterceptHandler(logging.Handler):
    def emit(self, record):
        logger_opt = logger.opt(depth=6, exception=record.exc_info)
        logger_opt.log(record.levelno, record.getMessage())
