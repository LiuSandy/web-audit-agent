"""Equivalent verbosity gates for the original Adze logger."""

import logging

isVerbose = False


def setVerbose(verbose: bool) -> None:
    global isVerbose
    isVerbose = verbose


class _NamespaceLogger:
    def __init__(self, namespace: str) -> None:
        self.base = logging.getLogger(namespace)
        self.base.setLevel(logging.INFO)
        self.base.propagate = False
        if not self.base.handlers:
            self.base.addHandler(logging.StreamHandler())

    def log(self, *args: object) -> None:
        if isVerbose:
            self.base.info(" ".join(map(str, args)))

    def info(self, *args: object) -> None:
        if isVerbose:
            self.base.info(" ".join(map(str, args)))

    def warn(self, *args: object) -> None:
        self.base.warning(" ".join(map(str, args)))

    def error(self, *args: object) -> None:
        self.base.error(" ".join(map(str, args)))

    def success(self, *args: object) -> None:
        self.base.info(" ".join(map(str, args)))


def createLogger(namespace: str) -> _NamespaceLogger:
    return _NamespaceLogger(namespace)


logger = createLogger("global")
