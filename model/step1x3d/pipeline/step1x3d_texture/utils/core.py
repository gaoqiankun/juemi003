# ruff: noqa
import importlib

###  grammar sugar for logging utilities  ###
import logging

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


def find(cls_string):
    module_string = ".".join(cls_string.split(".")[:-1])
    cls_name = cls_string.split(".")[-1]
    module = importlib.import_module(module_string, package=None)
    cls = getattr(module, cls_name)
    return cls


debug = rank_zero_debug
info = rank_zero_info


@rank_zero_only
def warn(*args, **kwargs):
    logger.warn(*args, **kwargs)
