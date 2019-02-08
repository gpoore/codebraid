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
import pathlib
import typing; from typing import Optional, Sequence, Union
from .. import err
from .. import codeprocessors




class CodeChunk(object):
    '''
    Base class for code chunks.
    '''
    def __init__(self,
                 command: str,
                 code: str,
                 options: dict,
                 source_name: str, *,
                 source_start_line_number: Optional[int]=None,
                 inline: Optional[bool]=None):
        if command not in ('code', 'run'):
            raise err.SourceError('Unknown Codebraid command "{0}"'.format(command), source_name, source_start_line_number)
        self.command = command
        code_lines = code.splitlines()
        if len(code_lines) > 1 and inline:
            raise err.SourceError('Inline code cannot be longer that 1 line', source_name, source_start_line_number)
        if not inline:
            # Inline code automatically won't contribute to line count
            code_lines[-1] += '\n'
        self.code = '\n'.join(code_lines)
        if inline:
            final_options = self._default_inline_options.copy()
        else:
            final_options = self._default_options.copy()
        for k, v in options.items():
            try:
                v_func = self._options_schema_process[k]
            except KeyError:
                raise err.SourceError('Unknown option "{0}"'.format(k), source_name, source_start_line_number)
            v_isvalid, v_processed = v_func(v, inline, final_options)
            if not v_isvalid:
                raise err.SourceError('Option "{0}" has incorrect value "{1}"'.format(k, v), source_name, source_start_line_number)
            if v_processed is not None:
                final_options[k] = v_processed
        self.options = final_options
        self.source_name = source_name
        self.source_start_line_number = source_start_line_number
        self.inline = inline

        self.stdout = None
        self.stderr = None
        if inline:
            self.expression = None
        self.code_start_line_number = None


    @staticmethod
    def _option_first_number_schema_process(x, inline, opts):
        if isinstance(x, int) and x > 0:
            return (True, x)
        elif isinstance(x, str):
            if x == 'next':
                return (True, x)
            try:
                x = int(x)
            except ValueError:
                return (False, x)
            return (True, x)
        return (False, x)

    @staticmethod
    def _option_hide_schema_process(x, inline, opts):
        if not isinstance(x, str):
            return (False, None)
        vals = x.replace(' ', '').split('+')
        if not all(val in ('code', 'stdout', 'stderr') for val in vals):
            return (False, None)
        for val in vals:
            opts['show'].pop(val, None)
        return (True, None)

    _show_notebook = collections.OrderedDict([('code', 'verbatim'),
                                              ('stdout', 'autoverbatim'),
                                              ('stderr', 'verbatim')])
    _show_inline_notebook = collections.OrderedDict([('expression', 'raw'),
                                                     ('stderr', 'verbatim')])

    def _option_show_schema_process(self, x, inline, opts):
        if not isinstance(x, str):
            return (False, x)
        if x == 'notebook':
            if inline:
                return (True, self._show_inline_notebook.copy())
            return (True, self._show_notebook.copy())
        v_processed = collections.OrderedDict()
        vals = x.replace(' ', '').split('+')
        for output_and_format in vals:
            if ':' not in output_and_format:
                output = output_and_format
                format = None
            else:
                output, format = output_and_format.split(':', 1)
            if output in v_processed:
                return (False, x)
            if output == 'code':
                if format is None:
                    format = 'verbatim'
                elif format != 'verbatim':
                    return (False, x)
            elif output == 'expression':
                if not inline:
                    return (False, x)
                if format is None:
                    format = 'raw'
                elif format not in ('verbatim', 'autoverbatim', 'raw'):
                    return (False, x)
            elif output in ('stdout', 'stderr'):
                if format not in (None, 'verbatim', 'autoverbatim', 'raw'):
                    return (False, x)
                if format is None:
                    format = 'verbatim'
            else:
                return (False, x)
            v_processed[output] = format
        return (True, v_processed)

    @staticmethod
    def _option_line_numbers_schema_process(x, inline, opts):
        if isinstance(x, bool):
            return (True, x)
        if x in ('true', 'false'):
            return (True, x == 'true')
        return (False, x)


    _options_schema_process = {'hide': _option_hide_schema_process,
                               'first_number': _option_first_number_schema_process,
                               'label': lambda x, inline, opts: (isinstance(x, str), x),
                               'lang': lambda x, inline, opts: (isinstance(x, str), x),
                               'line_numbers': _option_line_numbers_schema_process,
                               'session': lambda x, inline, opts: (isinstance(x, str), x),
                               'show': _option_show_schema_process}

    _default_options = {'first_number': 'next',
                        'line_numbers': True,
                        'session': None,
                        'show': _show_notebook}
    _default_inline_options = {'session': None, 'show': _show_inline_notebook}




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
                 cache_path: Optional[Union[str, pathlib.Path]]=None,
                 cross_source_sessions: bool=True,
                 expanduser: bool=False,
                 expandvars: bool=False,
                 from_format: Optional[str]=None):
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
                source_string = p.read_text(encoding='utf_8_sig')
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
        if cache_path is None:
            if paths is not None:
                cache_path = self.expanded_source_paths[0].parent() / '_codebraid'
        elif isinstance(cache_path, str):
            cache_path = pathlib.Path(cache_path)
        elif not isinstance(cache_path, pathlib.Path):
            raise TypeError
        if cache_path is not None:
            if expandvars:
                cache_path = pathlib.Path(os.path.expandvars(str(cache_path.as_posix)))
            if expanduser:
                cache_path = cache_path.expanduser()
        self.cache_path = cache_path

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
        codeprocessors.CodeProcessor(converter=self).process()

    def _postprocess_code_chunks(self):
        raise NotImplementedError

    def convert(self, *, to_format):
        raise NotImplementedError
