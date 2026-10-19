import logging
import sys
from logging.handlers import RotatingFileHandler

from .paths import log_dir

FORMAT = "%(asctime)s %(levelname)-7s %(message)s"


def setup_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    fh = RotatingFileHandler(log_dir() / "ocrdms.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(logging.Formatter(FORMAT))
    root.addHandler(fh)
    if sys.stderr:  # in der fensterlosen EXE gibt es kein stderr
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter(FORMAT, "%H:%M:%S"))
        root.addHandler(sh)
    for noisy in ("urllib3", "requests"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
