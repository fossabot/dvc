import os
from collections import defaultdict
from collections.abc import Mapping, MutableMapping, MutableSequence
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any, List, Optional, Sequence, Union

from funcy import identity

from dvc.utils.serialize import LOADERS


def _merge(into, update, overwrite):
    for key, val in update.items():
        if isinstance(into.get(key), Mapping) and isinstance(val, Mapping):
            _merge(into[key], val, overwrite)
        else:
            if key in into and not overwrite:
                raise ValueError(
                    f"Cannot overwrite as key {key} already exists in {into}"
                )
            into[key] = val


@dataclass
class Meta:
    source: Optional[str]
    dpaths: List[str] = field(default_factory=list)

    @staticmethod
    def update_path(meta: "Meta", path: Union[str, int]):
        dpaths = meta.dpaths[:] + [str(path)]
        return replace(meta, dpaths=dpaths)

    def __str__(self):
        string = self.source or "<local>:"
        string += self.path()
        return string

    def path(self):
        return ".".join(self.dpaths)


@dataclass
class Value:
    value: Any
    meta: Meta = field(compare=False, repr=False)

    def __repr__(self):
        return f"'{self}'"

    def __str__(self) -> str:
        return str(self.value)

    def get_sources(self):
        return {self.meta.source: self.meta.path()}


class String:
    """
    Wrapper around string, that can interpolate, and keep the
    original source of those interpolations.
    """

    def __init__(self, template, matches, context):

        from .interpolate import _resolve_value

        index, buf = 0, ""
        self.meta = defaultdict(set)
        for match in matches:
            start, end = match.span(0)
            val = _resolve_value(match, context)
            self._add_source(val)
            buf += template[index:start] + str(val)
            index = end
        value = buf + template[index:]
        self.value = value.replace(r"\${", "${")

    def __repr__(self) -> str:
        return str(self.value)

    def _add_source(self, val: Union[Value, "String"]):
        # string might have been built from multiple sources
        if isinstance(val, Value) and val.meta and val.meta.source:
            self.meta[val.meta.source].add(val.meta.path())
        if isinstance(val, String) and val.meta:
            for source, keys in self.meta.items():
                self.meta[source].update(keys)

    def get_sources(self):
        return self.meta


class Container:
    meta: Meta
    data: Union[list, dict]
    _key_transform = staticmethod(identity)

    def __init__(self, meta) -> None:
        self.meta = meta or Meta(source=None)

    def _convert(self, key, value):
        meta = Meta.update_path(self.meta, key)
        if value is None or isinstance(value, (int, float, str, bytes, bool)):
            return Value(value, meta=meta)
        elif isinstance(value, (CtxList, CtxDict, Value, String)):
            return value
        elif isinstance(value, (list, dict)):
            container = CtxDict if isinstance(value, dict) else CtxList
            return container(value, meta=meta)
        else:
            msg = "Unsupported value of type '{value}' in '{meta}'"
            raise TypeError(msg)

    def __repr__(self):
        return repr(self.data)

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = self._convert(key, value)

    def __delitem__(self, key):
        del self.data[key]

    def __len__(self):
        return len(self.data)

    def __iter__(self):
        return iter(self.data)

    def __eq__(self, o):
        return o.data == self.data

    def select(self, key: str):
        index, *rems = key.split(sep=".", maxsplit=1)
        index = index.strip()
        index = self._key_transform(index)
        try:
            d = self.data[index]
        except LookupError as exc:
            raise ValueError(
                f"Could not find '{index}' in {self.data}"
            ) from exc
        return d.select(rems[0]) if rems else d

    def get_sources(self):
        return {}


class CtxList(Container, MutableSequence):
    _key_transform = staticmethod(int)

    def __init__(self, values: Sequence, meta: Meta = None):
        super().__init__(meta=meta)
        self.data: list = []
        self.extend(values)

    def insert(self, index: int, value):
        self.data.insert(index, self._convert(index, value))

    def get_sources(self):
        return {self.meta.source: self.meta.path()}


class CtxDict(Container, MutableMapping):
    def __init__(self, mapping: Mapping = None, meta: Meta = None, **kwargs):
        super().__init__(meta=meta)

        self.data: dict = {}
        if mapping:
            self.update(mapping)
        self.update(kwargs)

    def __setitem__(self, key, value):
        if not isinstance(key, str):
            # limitation for the interpolation
            # ignore other kinds of keys
            return
        return super().__setitem__(key, value)

    def merge_update(self, *args, overwrite=True):
        for d in args:
            _merge(self.data, d, overwrite=overwrite)


class Context(CtxDict):
    def __init__(self, *args, **kwargs):
        """
        Top level mutable dict, with some helpers to create context and track
        """
        super().__init__(*args, **kwargs)
        self._track = False
        self._tracked_data = defaultdict(set)

    @contextmanager
    def track(self):
        self._track = True
        yield
        self._track = False

    def _track_data(self, node):
        if not self._track:
            return

        for source, keys in node.get_sources().items():
            if not source:
                continue
            params_file = self._tracked_data[source]
            keys = [keys] if isinstance(keys, str) else keys
            params_file.update(keys)

    @property
    def tracked(self):
        return [
            {file: list(keys)} for file, keys in self._tracked_data.items()
        ]

    def select(self, key: str):
        node = super().select(key)
        self._track_data(node)
        return node

    @classmethod
    def load_from(cls, tree, file: str) -> "Context":
        _, ext = os.path.splitext(file)
        loader = LOADERS[ext]

        meta = Meta(source=file)
        return cls(loader(file, tree=tree), meta=meta)

    @classmethod
    def clone(cls, ctx: "Context") -> "Context":
        """Clones given context."""
        return cls(deepcopy(ctx.data))
