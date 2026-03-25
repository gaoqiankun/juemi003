# ruff: noqa
import importlib
import logging

__modules__ = {}


def register(name):
    def decorator(cls):
        if name in __modules__:
            raise ValueError(
                f"Module {name} already exists! Names of extensions conflict!"
            )
        else:
            __modules__[name] = cls
        return cls

    return decorator


def find(name):
    if name in __modules__:
        return __modules__[name]
    else:
        try:
            module_string = ".".join(name.split(".")[:-1])
            cls_name = name.split(".")[-1]
            module = importlib.import_module(module_string, package=None)
            return getattr(module, cls_name)
        except Exception:
            raise ValueError(f"Module {name} not found!")


###  grammar sugar for logging utilities  ###
logger = logging.getLogger("pytorch_lightning")
try:
    from pytorch_lightning.utilities.rank_zero import (
        rank_zero_debug,
        rank_zero_info,
        rank_zero_only,
    )
except ModuleNotFoundError:
    def rank_zero_debug(*args, **kwargs):
        logger.debug(*args, **kwargs)

    def rank_zero_info(*args, **kwargs):
        logger.info(*args, **kwargs)

    def rank_zero_only(fn):
        return fn

debug = rank_zero_debug
info = rank_zero_info


@rank_zero_only
def warn(*args, **kwargs):
    logger.warn(*args, **kwargs)


from . import models
