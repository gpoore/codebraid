# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019, Geoffrey M. Poore
# All rights reserved.
#
# Licensed under the BSD 3-Clause License:
# http://opensource.org/licenses/BSD-3-Clause
#


import os
import collections
import json
import pathlib
import typing; from typing import List, Optional, Sequence, Union
import zipfile
from .. import err
from .. import codeprocessors




# Option processing functions
#
# These check options for validity and then store them.  There are no type
# conversions.  Any desired type conversions should be performed in
# format-specific subclasses of CodeChunk, which can take into account the
# data types that the format allows for options.  Duplicate or invalid options
# related to presentation result in warnings, while duplicate or invalid
# options related to code execution result in errors.
def _cb_option_unknown(code_chunk, key, value, options):
    code_chunk.source_errors.append('Unknown option "{0}" for code chunk'.format(key))

def _cb_option_bool(code_chunk, key, value, options):
    if isinstance(value, bool):
        options[key] = value
    else:
        code_chunk.source_warnings.append('Invalid "{0}" value "{1}" in code chunk'.format(key, value))

def _cb_option_str(code_chunk, key, value, options):
    if isinstance(value, str):
        options[key] = value
    else:
        code_chunk.source_warnings.append('Invalid "{0}" value "{1}" in code chunk'.format(key, value))

def _cb_option_first_number(code_chunk, key, value, options):
    if (isinstance(value, int) and value > 0) or (isinstance(value, str) and value == 'next'):
        options[key] = value
    else:
        code_chunk.source_warnings.append('Invalid "{0}" value "{1}" in code chunk'.format(key, value))

def _cb_option_hide(code_chunk, key, value, options):
    if not isinstance(value, str):
        code_chunk.source_warnings.append('Invalid "{0}" value "{1}" in code chunk'.format(key, value))
        return
    if value == 'all':
        options['show'] = collections.OrderedDict()
    else:
        hide_values = value.replace(' ', '').split('+')
        if not all(v in ('code', 'stdout', 'stderr', 'expr') for v in hide_values):
            code_chunk.source_warnings.append('Invalid "{0}" value "{1}" in code chunk'.format(key, value))
            return
        if 'expr' in hide_values and code_chunk.command != 'expr' and not (code_chunk.command == 'nb' and code_chunk.inline):
            code_chunk.source_warnings.append('Invalid "{0}" value "{1}" in code chunk'.format(key, value))
            return
        for v in hide_values:
            options['show'].pop(v, None)
    options[key] = hide_values

def _cb_option_label(code_chunk, key, value, options):
    if 'label' in options:
        code_chunk.source_warnings.append('Duplicate option "{0}" (label/name) for code chunk'.format(key))
    elif isinstance(value, str):
        options['label'] = value
    else:
        code_chunk.source_warnings.append('Invalid "{0}" value "{1}" in code chunk'.format(key, value))

def _cb_option_show(code_chunk, key, value, options):
    if not isinstance(value, str):
        code_chunk.source_warnings.append('Invalid "{0}" value "{1}" in code chunk'.format(key, value))
        return
    if value == 'none' or value is None:
        options[key] = collections.OrderedDict()
    else:
        value_processed = collections.OrderedDict()
        for output_and_format in value.replace(' ', '').split('+'):
            if ':' not in output_and_format:
                output = output_and_format
                format = None
            else:
                output, format = output_and_format.split(':', 1)
            if output in value_processed:
                code_chunk.source_warnings.append('Option "{0}" value "{1}" contains duplicate "{2}" in code chunk'.format(key, value, output))
                continue
            if output == 'code':
                if format is None:
                    format = 'verbatim'
                elif format != 'verbatim':
                    code_chunk.source_warnings.append('Invalid "{0}" value "{1}" in code chunk'.format(key, value))
                    continue
            elif output in ('stdout', 'stderr'):
                if format is None:
                    format = 'verbatim'
                elif format not in ('verbatim', 'verbatim_or_empty', 'raw'):
                    code_chunk.source_warnings.append('Invalid "{0}" value "{1}" in code chunk'.format(key, value))
                    continue
            elif output == 'expr':
                if not (code_chunk.command == 'expr' or (code_chunk.command == 'nb' and code_chunk.inline)):
                    code_chunk.source_warnings.append('Invalid "{0}" value "{1}" in code chunk (not expr chunk)'.format(key, value))
                    continue
                if format is None:
                    format = 'raw'
                elif format not in ('verbatim', 'verbatim_or_empty', 'raw'):
                    code_chunk.source_warnings.append('Invalid "{0}" value "{1}" in code chunk'.format(key, value))
                    continue
            else:
                code_chunk.source_warnings.append('Invalid "{0}" value "{1}" in code chunk'.format(key, value))
                continue
            value_processed[output] = format
        options[key] = value_processed


_cb_option_processors = collections.defaultdict(lambda: _cb_option_unknown,
                                                {'hide': _cb_option_hide,
                                                 'example': _cb_option_bool,
                                                 'first_number': _cb_option_first_number,
                                                 'label': _cb_option_label,
                                                 'lang': _cb_option_str,
                                                 'line_numbers': _cb_option_bool,
                                                 'session': _cb_option_str,
                                                 'show': _cb_option_show})

ODict = collections.OrderedDict
_cb_default_show_options = collections.defaultdict(lambda: ODict(),
                                                   {('expr', True): ODict([('expr', 'raw'),
                                                                           ('stderr', 'verbatim')]),
                                                    ('nb', True):   ODict([('expr', 'raw'),
                                                                           ('stderr', 'verbatim')]),
                                                    ('nb', False):  ODict([('code', 'verbatim'),
                                                                           ('stdout', 'verbatim'),
                                                                           ('stderr', 'verbatim')]),
                                                    ('run', True):  ODict([('stdout', 'raw'),
                                                                           ('stderr', 'verbatim')]),
                                                    ('run', False): ODict([('stdout', 'raw'),
                                                                           ('stderr', 'verbatim')])})

_cb_default_block_options = {'example': False,
                             'first_number': 'next',
                             'lang': None,
                             'line_numbers': True,
                             'session': None}
_cb_default_inline_options = {'example': False,
                              'lang': None,
                              'session': None}




class CodeChunk(object):
    '''
    Base class for code chunks.
    '''
    def __init__(self,
                 command: str,
                 code: Union[str, List[str]],
                 options: dict,
                 source_name: str, *,
                 source_start_line_number: Optional[int]=None,
                 inline: Optional[bool]=None):
        self.__pre_init__()

        if command not in ('code', 'expr', 'nb', 'run'):
            if command is None:
                self.source_errors.append('Missing valid Codebraid command')
            else:
                self.source_errors.append('Unknown Codebraid command "{0}"'.format(command))
        if command == 'expr' and not inline:
            self.source_errors.append('Codebraid command "{0}" is only allowed inline'.format(command))

        self.command = command

        if isinstance(code, list):
            code_lines = code
        else:
            code_lines = code.splitlines()
        if len(code_lines) > 1 and inline:
            self.source_errors.append('Inline code cannot be longer that 1 line')
        self.code_lines = code_lines
        if inline:
            self.code = code_lines[0]
        else:
            self.code = '\n'.join(code_lines)

        self.source_name = source_name
        self.source_start_line_number = source_start_line_number
        self.inline = inline

        final_options = self._default_options[inline].copy()
        final_options['show'] = self._default_show[(command, inline)].copy()
        for k, v in options.items():
            self._option_processors[k](self, k, v, final_options)
        self.options = final_options

        self.session_index = None
        self.stdout_lines = None
        self.stderr_lines = None
        if command == 'expr' or (inline and command == 'nb'):
            self.expr_lines = None
        self.code_start_line_number = None


    def __pre_init__(self):
        '''
        Create lists of errors and warnings.  Subclasses may need to register
        errors or warnings during preprocessing, before they are ready
        for `super().__init__()`
        '''
        if not hasattr(self, 'source_errors'):
            self.source_errors = []
            self.source_warnings = []


    _default_options = {True: _cb_default_inline_options,
                        False: _cb_default_block_options}
    _default_show = _cb_default_show_options
    _option_processors = _cb_option_processors




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
                       for attr in [cls.from_formats, cls.to_formats]):
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
                 no_cache: Optional[bool]=False,
                 cache_path: Optional[Union[str, pathlib.Path]]=None,
                 cross_source_sessions: bool=True,
                 expanduser: bool=False,
                 expandvars: bool=False,
                 from_format: Optional[str]=None,
                 synctex: bool=False):
        if not all(isinstance(x, bool) for x in (cross_source_sessions, expanduser, expandvars)):
            raise TypeError
        self.cross_source_sessions = cross_source_sessions
        self.expanduser = expanduser
        self.expandvars = expandvars
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
                paths = [pathlib.Path(os.path.expandvars(str(p))) for p in paths]
            if expanduser:
                paths = [p.expanduser() for p in paths]
            self.expanded_source_paths = paths
            source_strings = []
            for p in paths:
                try:
                    source_string = p.read_text(encoding='utf_8_sig')
                except Exception as e:
                    if not p.is_file():
                        raise ValueError('File "{0}" does not exist'.format(p))
                    raise ValueError('Failed to read file "{0}":\n  {1}'.format(p, e))
                if not source_string:
                    source_string = '\n'
                source_strings.append(source_string)
            self.source_strings = source_strings
            if from_format is None:
                try:
                    from_formats = set([self._file_extension_to_format_dict[p.suffix] for p in paths])
                except KeyError:
                    raise TypeError('Cannot determine document format from file extensions, or unsupported format')
                from_format = from_formats.pop()
                if from_formats:
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
            self.source_strings = strings
            if len(strings) == 1:
                self.source_names = ['<string>']
            else:
                self.source_names = ['<string({0})>'.format(n+1) for n in range(len(strings))]
            self.raw_source_paths = None
            self.expanded_source_paths = None
            if from_format is None:
                raise TypeError('Document format is required')
            if from_format not in self.from_formats:
                raise ValueError('Unsupported document format {0}'.format(from_format))
            self.from_format = from_format
        else:
            raise TypeError
        if len(self.source_strings) > 1 and from_format not in self.multi_source_formats:
            raise TypeError('Multiple sources are not supported for format {0}'.format(from_format))
        if not isinstance(no_cache, bool):
            raise TypeError
        self.no_cache = no_cache
        if cache_path is None:
            if paths is not None:
                cache_path = self.expanded_source_paths[0].parent / '_codebraid'
        elif isinstance(cache_path, str):
            cache_path = pathlib.Path(cache_path)
        elif not isinstance(cache_path, pathlib.Path):
            raise TypeError
        if no_cache:
            cache_path = None
        elif cache_path is not None:
            if expandvars:
                cache_path = pathlib.Path(os.path.expandvars(str(cache_path.as_posix)))
            if expanduser:
                cache_path = cache_path.expanduser()
            if not cache_path.is_dir():
                cache_path.mkdir(parents=True)
        self.cache_path = cache_path
        self._io_map = False
        if not isinstance(synctex, bool):
            raise TypeError
        if synctex and cache_path is None:
            raise ValueError
        self.synctex = synctex
        if synctex:
            self._io_map = True

        self.code_chunks = []
        self.code_options = {}


    from_formats = set()
    to_formats = set()
    multi_source_formats = set()

    _file_extension_to_format_dict = {'.md': 'markdown', '.markdown': 'markdown',
                                      '.tex': 'latex', '.ltx': 'latex'}


    def code_braid(self):
        self._extract_code_chunks()
        self._process_code_chunks()
        self._postprocess_code_chunks()

    def _extract_code_chunks(self):
        raise NotImplementedError

    def _process_code_chunks(self):
        cp = codeprocessors.CodeProcessor(code_chunks=self.code_chunks,
                                          code_options=self.code_options,
                                          cross_source_sessions=self.cross_source_sessions,
                                          cache_path=self.cache_path)
        cp.process()

    def _postprocess_code_chunks(self):
        raise NotImplementedError

    def convert(self, *, to_format):
        raise NotImplementedError


    def _save_synctex_data(self, data):
        zip_path = self.cache_path / 'synctex.zip'
        with zipfile.ZipFile(str(zip_path), 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('synctex.json', json.dumps(data))
