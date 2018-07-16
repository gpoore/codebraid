# -*- coding: utf-8 -*-
#
# Copyright (c) 2018, Geoffrey M. Poore
# All rights reserved.
#
# Licensed under the BSD 3-Clause License:
# http://opensource.org/licenses/BSD-3-Clause
#


import os
import collections
import pathlib
import typing; from typing import Optional, Sequence, Union




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
            if not all(hasattr(cls, a) for a in ['from_formats',
                                                 'to_formats',
                                                 'multi_source_formats']):
                raise TypeError
            if not all(isinstance(attr, set) and attr and
                       all(isinstance(x, str) for x in attr)
                       for attr in [cls.from_formats, cls.to_formats, cls.multi_source_formats]):
                raise TypeError
            if cls.multi_source_formats - cls.from_formats:
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
                 expanduser: bool=False,
                 expandvars: bool=False,
                 from_format: Optional[str]=None):
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
            self.raw_source_paths = paths
            # Names are based on paths BEFORE any expansion
            self.source_names = [p.as_posix() for p in paths]
            if not all(isinstance(x, bool) for x in (expanduser, expandvars)):
                raise TypeError
            if expandvars:
                paths = [pathlib.Path(os.path.expandvars(p)) for p in paths]
            if expanduser:
                paths = [p.expanduser() for p in paths]
            self.expanded_source_paths = paths
            self.strings = [p.read_text(encoding='utf_8_sig') for p in paths]
            if from_format is None:
                try:
                    from_formats = set([self._file_extension_to_format_dict[p.suffix] for p in paths])
                except KeyError:
                    raise TypeError
                from_format = from_formats.pop()
                if from_formats:
                    raise TypeError
            if from_format not in self.from_formats:
                raise ValueError
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
            self.strings = strings
            if len(strings) == 1:
                self.source_names = ['<string>']
            else:
                self.source_names = ['<string({0})>'.format(n+1) for n in range(len(strings))]
            self.raw_source_paths = None
            self.expanded_source_paths = None
            if from_format is None:
                raise TypeError
            if from_format not in self.from_formats:
                raise ValueError
            self.from_format = from_format
        else:
            raise TypeError

        self._code_chunks = {}
        self._extract_code_chunks()
        self._process_code_chunks()

    from_formats = set()
    to_formats = set()
    multi_source_formats = set()

    _file_extension_to_format_dict = {'.md': 'markdown', '.markdown': 'markdown',
                                      '.tex': 'latex', '.ltx': 'latex'}

    def _extract_code_chunks(self):
        raise NotImplementedError

    def _process_code_chunks(self):
        raise NotImplementedError

    def convert(self, *, to_format):
        raise NotImplementedError




class CodeChunk(object):
    '''
    Base class for code chunks.
    '''
    def __init__(self, *,
                 code: str,
                 kwargs: dict,
                 converter: Converter,
                 first_line_number: Optional[int]):
        pass

