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
import typing; from typing import Optional, Union




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
            if not all(hasattr(cls, attr) and
                       isinstance(getattr(cls, attr), set) and
                       getattr(cls, attr) and
                       all(isinstance(x, str) for x in getattr(cls, attr))
                       for attr in ['from_formats', 'to_formats']):
                raise TypeError
            if not all(hasattr(cls, method) for method in ['_extract_code_chunks',
                                                           '_process_code_chunks',
                                                           'convert']):
                raise TypeError
        super().__init__(name, bases, dct)




class Converter(object):
    '''
    Base class for converters.
    '''
    __metaclass__ = MetaConverter

    def __init__(self,
                 string: Optional[str]=None,
                 path: Optional[Union[str, pathlib.Path]]=None,
                 expanduser: bool=False,
                 expandvars: bool=False,
                 from_format: Optional[str]=None):
        if path is not None and string is None:
            if isinstance(path, str):
                path = pathlib.Path(path)
            elif not isinstance(path, pathlib.Path):
                raise TypeError
            self.name = path.as_posix()
            if not all(isinstance(x, bool) for x in (expanduser, expandvars)):
                raise TypeError
            if expandvars:
                path = pathlib.Path(os.path.expandvars(path))
            if expanduser:
                path = path.expanduser()
            self.path = path
            self.string = path.read_text(encoding='utf_8_sig')
            if from_format is None:
                try:
                    from_format = self._extension_to_format_dict[path.suffix]
                except KeyError:
                    raise ValueError
            if from_format not in self.from_formats:
                raise ValueError
            self.from_format = from_format
        elif string is not None and path is None:
            if not all(x is False for x in (expanduser, expandvars)):
                if not all(isinstance(x, bool) for x in (expanduser, expandvars)):
                    raise TypeError
                raise ValueError
            self.name = '<string>'
            self.path = None
            self.string = string
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

    _extension_to_format_dict = {'.md': 'markdown', '.markdown': 'markdown',
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

