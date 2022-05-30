# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2022, Geoffrey M. Poore
# All rights reserved.
#
# Licensed under the BSD 3-Clause License:
# http://opensource.org/licenses/BSD-3-Clause
#


from __future__ import annotations


import collections
import collections.abc
import hashlib
import io
import json
import os
import pathlib
from typing import Dict, Optional, Sequence, Union
import zipfile
from .. import codeprocessors
from ..progress import Progress




class MetaConverter(type):
    '''
    Metaclass for converters.  Allows converters to register themselves
    by name and by compatible formats.
    '''
    def __init__(cls, name, bases, dct):
        if not hasattr(cls, '_registry'):
            # Base Converter class
            cls._registry = {}
        else:
            # Subclass
            cls._registry[name.lower()] = cls
            if not all(attr is None or
                       (isinstance(attr, set) and attr and all(isinstance(x, str) for x in attr))
                       for attr in [cls.from_formats, cls.multi_origin_formats, cls.to_formats]):
                raise TypeError
            if (cls.from_formats is not None and cls.multi_origin_formats is not None and
                    cls.multi_origin_formats - cls.from_formats):
                raise ValueError
        super().__init__(name, bases, dct)




class Converter(object):
    '''
    Base class for converters.
    '''
    __metaclass__ = MetaConverter

    def __init__(self, *,
                 strings: Optional[Union[str, Sequence[str]]]=None,
                 paths: Optional[Union[str, Sequence[str], pathlib.Path, Sequence[pathlib.Path]]]=None,
                 no_cache: Optional[bool]=False,
                 cache_path: Optional[Union[str, pathlib.Path]]=None,
                 cross_origin_sessions: bool=True,
                 expanduser: bool=False,
                 expandvars: bool=False,
                 from_format: Optional[str]=None,
                 code_defaults: Optional[Dict[str, Union[bool, str]]]=None,
                 session_defaults: Optional[Dict[str, Union[bool, str]]]=None,
                 no_execute: bool=False,
                 only_code_output: Optional[str]=None,
                 synctex: bool=False):

        if not all(isinstance(x, bool) for x in (cross_origin_sessions, expanduser, expandvars)):
            raise TypeError
        self.cross_origin_sessions = cross_origin_sessions
        self.expanduser = expanduser
        self.expandvars = expandvars
        self.code_defaults = code_defaults
        self.session_defaults = session_defaults

        if paths is not None and strings is None:
            if isinstance(paths, str):
                paths = [pathlib.Path(paths)]
            elif isinstance(paths, pathlib.Path):
                paths = [paths]
            elif isinstance(paths, collections.abc.Sequence) and paths:
                if all(isinstance(x, str) for x in paths):
                    paths = [pathlib.Path(x) for x in paths]
                elif not all(isinstance(x, pathlib.Path) for x in paths):
                    raise TypeError
            else:
                raise TypeError
            self.raw_origin_paths = paths
            # Names are based on paths BEFORE any expansion
            origin_names = [p.as_posix() for p in paths]
            if not all(isinstance(x, bool) for x in (expanduser, expandvars)):
                raise TypeError
            if expandvars:
                paths = [pathlib.Path(os.path.expandvars(str(p))) for p in paths]
            if expanduser:
                paths = [p.expanduser() for p in paths]
            self.expanded_origin_paths = collections.OrderedDict(zip(origin_names, paths))
            origin_strings = []
            for p in paths:
                try:
                    origin_string = p.read_text(encoding='utf_8_sig')
                except Exception as e:
                    if not p.is_file():
                        raise ValueError('File "{0}" does not exist'.format(p))
                    raise ValueError('Failed to read file "{0}":\n  {1}'.format(p, e))
                if not origin_string:
                    origin_string = '\n'
                origin_strings.append(origin_string)
            self.origins = collections.OrderedDict(zip(origin_names, origin_strings))
            if self.from_formats is not None:
                if from_format is None:
                    try:
                        origin_formats = set([self._file_extension_to_format_dict[p.suffix] for p in paths])
                    except KeyError:
                        raise TypeError('Cannot determine document format from file extensions, or unsupported format')
                    from_format = origin_formats.pop()
                    if origin_formats:
                        raise TypeError('Cannot determine unambiguous document format from file extensions')
                if from_format not in self.from_formats:
                    raise ValueError('Unsupported document format {0}'.format(from_format))
            self.from_format = from_format
        elif strings is not None and paths is None:
            if not all(x is False for x in (expanduser, expandvars)):
                if not all(isinstance(x, bool) for x in (expanduser, expandvars)):
                    raise TypeError
                raise ValueError
            if isinstance(strings, str):
                strings = [strings]
            elif not (isinstance(strings, collections.abc.Sequence) and
                      strings and all(isinstance(x, str) for x in strings)):
                raise TypeError
            # Normalize newlines, as if read from file with universal newlines
            origin_strings = [io.StringIO(s, newline=None).read() or '\n' for s in strings]
            if len(strings) == 1:
                origin_names = ['<string>']
            else:
                origin_names = ['<string({0})>'.format(n+1) for n in range(len(strings))]
            self.origins = collections.OrderedDict(zip(origin_names, origin_strings))
            self.raw_origin_paths = None
            self.expanded_origin_paths = None
            if from_format is None:
                raise TypeError('Document format is required')
            if self.from_formats is not None and from_format not in self.from_formats:
                raise ValueError('Unsupported document format {0}'.format(from_format))
            self.from_format = from_format
        else:
            raise TypeError
        if len(self.origins) > 1 and from_format not in self.multi_origin_formats:
            raise TypeError('Multiple source files are not supported for format {0}'.format(from_format))

        if not isinstance(no_cache, bool):
            raise TypeError
        self.no_cache = no_cache
        if cache_path is None:
            cache_path = pathlib.Path('_codebraid')
        elif isinstance(cache_path, str):
            cache_path = pathlib.Path(cache_path)
        elif not isinstance(cache_path, pathlib.Path):
            raise TypeError
        if expandvars:
            cache_path = pathlib.Path(os.path.expandvars(cache_path.as_posix()))
        if expanduser:
            cache_path = cache_path.expanduser()
        self.cache_path = cache_path
        cache_key_hasher = hashlib.blake2b()
        if self.expanded_origin_paths is None:
            origin_paths_for_cache = None
            cache_key_hasher.update(b'<string>')
        else:
            origin_paths_for_cache = []
            for p in self.expanded_origin_paths.values():
                try:
                    p_final = pathlib.Path('~') / p.absolute().relative_to(pathlib.Path.home())
                except ValueError:
                    p_final = p.absolute()
                origin_paths_for_cache.append(p_final)
                cache_key_hasher.update(p_final.as_posix().encode('utf8'))
                cache_key_hasher.update(cache_key_hasher.digest())
        self.origin_paths_for_cache = origin_paths_for_cache
        self.cache_key = cache_key_hasher.hexdigest()[:16]

        if not isinstance(no_execute, bool):
            raise TypeError
        self.no_execute = no_execute

        if only_code_output is None:
            pass
        elif not isinstance(only_code_output, str):
            raise TypeError
        elif only_code_output not in ('codebraid_preview',):
            raise ValueError
        self.only_code_output = only_code_output

        self._io_map = False
        if not isinstance(synctex, bool):
            raise TypeError
        self.synctex = synctex
        if synctex:
            self._io_map = True

        self._progress = Progress(self.only_code_output)

        self.code_chunks = []
        self.code_processor: Optional[codeprocessors.CodeProcessor] = None


    def __enter__(self):
        self.code_braid()
        return self

    def __exit__(self, exception_type, exception_value, exception_traceback):
        self.cleanup()


    @property
    def exit_code(self):
        if self.code_processor is not None:
            return self.code_processor.exit_code
        return 0


    from_formats = None
    to_formats = None
    multi_origin_formats = None

    _file_extension_to_format_dict = {'.md': 'markdown', '.markdown': 'markdown',
                                      '.tex': 'latex', '.ltx': 'latex'}

    def code_braid(self):
        self.extract_code_chunks()
        self.process_code_chunks()
        if self.no_execute:
            pass
        else:
            self.exec_code_chunks()

    def extract_code_chunks(self):
        self._progress.parse_start()
        self._extract_code_chunks()
        self._progress.parse_end()

    def _extract_code_chunks(self):
        raise NotImplementedError

    def process_code_chunks(self):
        self._progress.process_start()
        self._process_code_chunks()
        self._progress.process_end()

    def _process_code_chunks(self):
        self.code_processor = codeprocessors.CodeProcessor(
            code_chunks=self.code_chunks,
            cross_origin_sessions=self.cross_origin_sessions,
            no_cache=self.no_cache,
            cache_path=self.cache_path,
            cache_key=self.cache_key,
            origin_paths_for_cache=self.origin_paths_for_cache,
            code_defaults=self.code_defaults,
            session_defaults=self.session_defaults,
            progress=self._progress,
            only_code_output=self.only_code_output,
        )
        self.code_processor.process()

    def exec_code_chunks(self):
        self._progress.exec_start()
        self.code_processor.exec()
        self._progress.exec_end()

    def convert(self, *, to_format, **kwargs):
        self._progress.convert_start()
        self._convert(to_format=to_format, **kwargs)
        self._progress.convert_end()

    def _convert(self, *, to_format):
        raise NotImplementedError

    def cleanup(self):
        if self.code_processor is not None:
            self.code_processor.cleanup()
        self._progress.complete()

    def _save_synctex_data(self, data):
        zip_path = self.cache_path / 'synctex.zip'
        with zipfile.ZipFile(str(zip_path), 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('synctex.json', json.dumps(data))
