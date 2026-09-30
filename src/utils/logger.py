"""Equivalent verbosity gates for the original Adze logger."""

import logging

is_verbose = False


def set_verbose(verbose: bool) -> None:
    global is_verbose
    is_verbose = verbose


class _NamespaceLogger:
    def __init__(self, namespace: str) -> None:
        self.base = logging.getLogger(namespace)
        self.base.setLevel(logging.INFO)
        self.base.propagate = False
        if not self.base.handlers:
            self.base.addHandler(logging.StreamHandler())

    def log(self, *args: object) -> None:
        if is_verbose:
            self.base.info(" ".join(map(str, args)))

    def info(self, *args: object) -> None:
        if is_verbose:
            self.base.info(" ".join(map(str, args)))

    def warn(self, *args: object) -> None:
        self.base.warning(" ".join(map(str, args)))

    def error(self, *args: object) -> None:
        self.base.error(" ".join(map(str, args)))

    def success(self, *args: object) -> None:
        self.base.info(" ".join(map(str, args)))


def create_logger(namespace: str) -> _NamespaceLogger:
    return _NamespaceLogger(namespace)


logger = create_logger("global")
