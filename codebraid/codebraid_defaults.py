# -*- coding: utf-8 -*-
#
# Copyright (c) 2022, Geoffrey M. Poore
# All rights reserved.
#
# Licensed under the BSD 3-Clause License:
# http://opensource.org/licenses/BSD-3-Clause
#


from __future__ import annotations


import re
from typing import Callable
YAML = None
yaml = None
try:
    from ruamel.yaml import YAML
except ImportError:
    try:
        from ruamel_yaml import YAML
    except ImportError:
        pass
if YAML is not None:
    yaml = YAML(typ='safe', pure=True)
from . import err


_yaml_metadata_re = re.compile(r'^---[ \t]*\n(.+?)\n(?:---|\.\.\.)[ \t]*\n', re.DOTALL)


_codebraid_defaults_schema: dict[str, tuple[Callable[[str], bool], str]] = {
    'jupyter': (
        lambda x: (
            isinstance(x, bool) or
            (isinstance(x, dict) and all(k in ('kernel', 'timeout') for k in x) and
                isinstance(x.get('kernel', ''), str) and isinstance(x.get('timeout', 0), int))
        ),
        'bool, or dict containing "kernel" (string) and/or "timeout" (int)'
    ),
    'live_output': (lambda x: isinstance(x, bool), 'bool'),
}
_codebraid_defaults_fallback = {
}
for k, v in _codebraid_defaults_fallback.items():
    if k not in _codebraid_defaults_schema or not _codebraid_defaults_schema[k][0](v):
        raise err.CodebraidError('Invalid defaults fallback')


class CodebraidDefaults(dict):
    def __init__(self):
        super().__init__(_codebraid_defaults_fallback)
        self._key_is_set = set()


    def update(self, data: dict):
        for k, v in data.items():
            self.__setitem__(k, v)


    def __setitem__(self, key, value):
        if key in self._key_is_set:
            return
        try:
            schema_func, value_doc = _codebraid_defaults_schema[key]
        except KeyError:
            raise err.CodebraidError(f'Unknown key "{key}"')
        if not schema_func(value):
            raise err.CodebraidError(f'Incorrect value for key "{key}" (expected {value_doc})')
        super().__setitem__(key, value)
        self._key_is_set.add(key)


    def update_from_yaml_metadata(self, first_origin_string: str):
        if not first_origin_string.startswith('---'):
            return
        match = _yaml_metadata_re.match(first_origin_string)
        if not match or 'codebraid' not in match.group(1):
            return
        if yaml is None:
            raise err.YAMLMetadataError(
                'Cannot load YAML metadata: ruamel.yaml (or ruamel_yaml for conda) is not installed'
            )
        try:
            metadata = yaml.load(match.group(1))
        except Exception as e:
            raise err.YAMLMetadataError(f'Invalid YAML metadata:\n{e}')
        codebraid_keys = ('codebraid', 'codebraid_')
        codebraid_metadata = None
        for key in codebraid_keys:
            data = metadata.get(key)
            if data:
                if codebraid_metadata is not None:
                    raise err.YAMLMetadataError(
                        'Invalid YAML metadata: only a single Codebraid key is permitted '
                        f'''({', '.join(f'"{x}"' for x in codebraid_keys)})'''
                    )
                codebraid_metadata = data
        if codebraid_metadata is None:
            return
        if not isinstance(codebraid_metadata, dict):
            raise err.YAMLMetadataError('Invalid YAML metadata: Codebraid key should map to a dict')
        try:
            self.update(codebraid_metadata)
        except err.CodebraidError as e:
            raise err.YAMLMetadataError(f'Invalid YAML metadata:\n{e}')


    def get_keypath(self, keypath: str, default=None):
        keypath_elems = keypath.split('.')
        obj = self
        for elem in keypath_elems[:-1]:
            try:
                obj = obj[elem]
            except KeyError:
                return default
            if not isinstance(obj, dict):
                return default
        try:
            obj = obj[keypath_elems[-1]]
        except KeyError:
            return default
        return obj
