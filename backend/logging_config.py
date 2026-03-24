import logging
import sys

def setup_logging():
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    # Access log via uvicorn goes to journalctl automatically
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
