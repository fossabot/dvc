import errno
import logging
import os
from collections import defaultdict

import dpath.util
from voluptuous import Any

from dvc.exceptions import DvcException
from dvc.hash_info import HashInfo
from dvc.utils.serialize import LOADERS, ParseError

from .base import Dependency

logger = logging.getLogger(__name__)


class MissingParamsError(DvcException):
    pass


class MissingParamsFile(DvcException):
    pass


class ParamsIsADirectoryError(DvcException):
    pass


class BadParamFileError(DvcException):
    pass


class ParamsDependency(Dependency):
    PARAM_PARAMS = "params"
    PARAM_SCHEMA = {PARAM_PARAMS: Any(dict, list, None)}
    DEFAULT_PARAMS_FILE = "params.yaml"

    def __init__(self, stage, path, params=None, repo=None):
        info = {}
        self.params = params or []
        if params:
            if isinstance(params, list):
                self.params = params
            else:
                assert isinstance(params, dict)
                self.params = list(params.keys())
                info = {self.PARAM_PARAMS: params}

        super().__init__(
            stage,
            path
            or os.path.join(stage.repo.root_dir, self.DEFAULT_PARAMS_FILE),
            info=info,
            repo=repo,
        )

    def dumpd(self):
        ret = super().dumpd()
        if not self.hash_info:
            ret[self.PARAM_PARAMS] = self.params
        return ret

    def fill_values(self, values=None):
        """Load params values dynamically."""
        if not values:
            return
        info = {}
        for param in self.params:
            if param in values:
                info[param] = values[param]
        self.hash_info = HashInfo(self.PARAM_PARAMS, info)

    def workspace_status(self):
        status = super().workspace_status()

        if status.get(str(self)) == "deleted":
            return status

        status = defaultdict(dict)
        info = self.hash_info.value if self.hash_info else {}
        actual = self.read_params()
        for param in self.params:
            if param not in actual.keys():
                st = "deleted"
            elif param not in info:
                st = "new"
            elif actual[param] != info[param]:
                st = "modified"
            else:
                assert actual[param] == info[param]
                continue

            status[str(self)][param] = st

        return status

    def status(self):
        return self.workspace_status()

    def validate_filepath(self):
        if not self.exists:
            raise FileNotFoundError(
                errno.ENOENT, os.strerror(errno.ENOENT), str(self)
            )
        if self.isdir():
            raise IsADirectoryError(
                errno.EISDIR, os.strerror(errno.EISDIR), str(self)
            )

    def read_file(self):
        _, ext = os.path.splitext(self.fs_path)
        loader = LOADERS[ext]

        try:
            self.validate_filepath()
        except FileNotFoundError as exc:
            raise MissingParamsFile(
                f"Parameters file '{self}' does not exist"
            ) from exc
        except IsADirectoryError as exc:
            raise ParamsIsADirectoryError(
                f"'{self}' is a directory, expected a parameters file"
            ) from exc

        try:
            return loader(self.fs_path, fs=self.repo.fs)
        except ParseError as exc:
            raise BadParamFileError(
                f"Unable to read parameters from '{self}'"
            ) from exc

    def _read(self):
        try:
            return self.read_file()
        except MissingParamsFile:
            return {}

    def read_params_d(self, **kwargs):
        config = self._read()

        ret = {}
        for param in self.params:
            dpath.util.merge(
                ret,
                dpath.util.search(config, param, separator="."),
                separator=".",
            )
        return ret

    def read_params(self):
        config = self._read()

        ret = {}
        for param in self.params:
            try:
                ret[param] = dpath.util.get(config, param, separator=".")
            except KeyError:
                pass
        return ret

    def get_hash(self):
        info = self.read_params()

        missing_params = set(self.params) - set(info.keys())
        if missing_params:
            raise MissingParamsError(
                "Parameters '{}' are missing from '{}'.".format(
                    ", ".join(missing_params), self
                )
            )

        return HashInfo(self.PARAM_PARAMS, info)

    def save(self):
        if not self.exists:
            raise self.DoesNotExistError(self)

        if not self.isfile and not self.isdir:
            raise self.IsNotFileOrDirError(self)

        if self.is_empty:
            logger.warning(f"'{self}' is empty.")

        self.ignore()

        if self.metric or self.plot:
            self.verify_metric()

        self.hash_info = self.get_hash()
