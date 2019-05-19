# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019, Geoffrey M. Poore
# All rights reserved.
#
# Licensed under the BSD 3-Clause License:
# http://opensource.org/licenses/BSD-3-Clause
#


import collections
from collections import OrderedDict as ODict
import io
import json
import os
import pathlib
import typing; from typing import List, Optional, Sequence, Union
import zipfile
from .. import codeprocessors
from .. import err
from .. import util




def _get_option_processors():
    '''
    Create dict mapping code chunk options to processing functions.

    These functions check options for validity and then store them.  There are
    no type conversions.  Any desired type conversions should be performed in
    format-specific subclasses of CodeChunk, which can take into account the
    data types that the format allows for options.  Duplicate or invalid
    options related to presentation result in warnings, while duplicate or
    invalid options related to code execution result in errors.
    '''

    def option_unknown(code_chunk, options, key, value):
        '''
        Raise an error for unknown options.  There is no way to tell whether an
        execution or presentation option was intended, so take the safer approach.
        '''
        code_chunk.source_errors.append('Unknown option "{0}" for code chunk'.format(key))

    def option_bool_warning(code_chunk, options, key, value):
        if isinstance(value, bool):
            options[key] = value
        else:
            code_chunk.source_warnings.append('Invalid "{0}" value "{1}" in code chunk'.format(key, value))

    def option_bool_error(code_chunk, options, key, value):
        if isinstance(value, bool):
            options[key] = value
        else:
            code_chunk.source_errors.append('Invalid "{0}" value "{1}" in code chunk'.format(key, value))

    def option_str_warning(code_chunk, options, key, value):
        if isinstance(value, str):
            options[key] = value
        else:
            code_chunk.source_warnings.append('Invalid "{0}" value "{1}" in code chunk'.format(key, value))

    def option_str_error(code_chunk, options, key, value):
        if isinstance(value, str):
            options[key] = value
        else:
            code_chunk.source_errors.append('Invalid "{0}" value "{1}" in code chunk'.format(key, value))

    def option_copy(code_chunk, options, key, value):
        if 'include' in options:
            code_chunk.source_errors.append('Options "copy" and "include" in code chunk are mutually exclusive')
        elif isinstance(value, str):
            # No need to check whether names are valid identifier-style strings,
            # since that's done when they are defined
            options[key] = [x.strip() for x in value.split('+')]
        else:
            # This is an error, because no functionality is possible
            code_chunk.source_errors.append('Invalid "{0}" value "{1}" in code chunk'.format(key, value))

    def option_first_number(code_chunk, options, key, value):
        if (isinstance(value, int) and value > 0) or (isinstance(value, str) and value == 'next'):
            options[key] = value
        else:
            code_chunk.source_warnings.append('Invalid "{0}" value "{1}" in code chunk'.format(key, value))

    def option_hide(code_chunk, options, key, value):
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
            if 'expr' in hide_values and not code_chunk.is_expr and code_chunk.command != 'paste':
                code_chunk.source_warnings.append('Invalid "{0}" value "{1}" in code chunk'.format(key, value))
                return
            for v in hide_values:
                options['show'].pop(v, None)

    def option_include(code_chunk, options, key, value):
        if 'copy' in options:
            code_chunk.source_errors.append('Options "copy" and "include" in code chunk are mutually exclusive')
        elif isinstance(value, str):
            options[key] = value
        else:
            # This is an error, because no functionality is possible
            code_chunk.source_errors.append('Invalid "{0}" value "{1}" in code chunk'.format(key, value))

    def option_name(code_chunk, options, key, value):
        if isinstance(value, str):
            if value.isidentifier():
                options[key] = value
            else:
                code_chunk.source_warnings.append('Option "{0}" has invalid, non-identifier value "{1}"'.format(key, value))
        else:
            code_chunk.source_warnings.append('Invalid "{0}" value "{1}" in code chunk'.format(key, value))

    def option_session(code_chunk, options, key, value):
        if isinstance(value, str):
            if value.isidentifier():
                options[key] = value
            else:
                code_chunk.source_errors.append('Option "{0}" has invalid, non-identifier value "{1}"'.format(key, value))
        else:
            code_chunk.source_errors.append('Invalid "{0}" value "{1}" in code chunk'.format(key, value))

    def option_show(code_chunk, options, key, value):
        if not isinstance(value, str):
            if value is None:
                options[key] = collections.OrderedDict()
            else:
                code_chunk.source_warnings.append('Invalid "{0}" value "{1}" in code chunk'.format(key, value))
        elif value == 'none':
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
                    if not code_chunk.is_expr and code_chunk.command != 'paste':
                        code_chunk.source_warnings.append('Invalid "{0}" value "{1}" in code chunk'.format(key, value))
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

    return collections.defaultdict(lambda: option_unknown,  # Unknown option -> error
                                   {'complete': option_bool_error,
                                    'copy': option_copy,
                                    'hide': option_hide,
                                    'example': option_bool_warning,
                                    'first_number': option_first_number,
                                    'name': option_name,
                                    'lang': option_str_error,
                                    'line_numbers': option_bool_warning,
                                    'outside_main': option_bool_error,
                                    'session': option_session,
                                    'show': option_show})




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

        if command not in self.commands:
            if command is None:
                self.source_errors.append('Missing valid Codebraid command')
            else:
                self.source_errors.append('Unknown Codebraid command "{0}"'.format(command))
        if command == 'expr' and not inline:
            self.source_errors.append('Codebraid command "{0}" is only allowed inline'.format(command))
        self.command = command
        self.execute = self._default_execute[command]

        if isinstance(code, list):
            code_lines = code
            if inline:
                code = code_lines[0]  # Check for len(code_lines) > 1 later
            else:
                code = '\n'.join(code_lines)
        else:
            code_lines = util.splitlines_lf(code) or ['']
            if inline:
                code = code_lines[0]  # Check for len(code_lines) > 1 later
            elif code[-1:] == '\n':
                code = code[:-1]

        if 'copy' not in options and 'include' not in options:
            if inline and len(code_lines) > 1:
                self.source_errors.append('Inline code cannot be longer that 1 line')
            self.code = code
            self.code_lines = code_lines
            self.placeholder_code = None
        else:
            if inline:
                if code not in (' ', '_'):
                    self.source_errors.append('Invalid placeholder code for copy or include (need space or underscore)')
            elif code.rstrip(' ') not in ('', '_'):
                self.source_errors.append('Invalid placeholder code for copy or include (need empty, space, or underscore)')
            self.placeholder_code = code
            self.code = None
            self.code_lines = None
        if command == 'expr' or (inline and command == 'nb'):
            self.is_expr = True
        else:
            self.is_expr = False

        self.source_name = source_name
        self.source_start_line_number = source_start_line_number
        self.inline = inline

        # No need to check for duplicate options, since `options` is a dict.
        # That must be handled in subclasses or source parsing code.
        if inline:
            final_options = self._default_inline_options.copy()
            final_options['show'] = self._default_inline_show[command].copy()
        else:
            final_options = self._default_block_options.copy()
            final_options['show'] = self._default_block_show[command].copy()
        for k, v in options.items():
            self._option_processors[k](self, final_options, k, v)
        if command == 'paste':
            if 'copy' not in options:
                self.source_errors.append('Command "paste" cannot be used without specifying a target via "copy"')
            if 'show' not in options and 'hide' not in options:
                final_options['show'] = None  # Will inherit if not specified
            for k in ('complete', 'outside_main', 'session'):
                if k in options:
                    self.source_warnings.append('Option "{0}" has no effect with command "paste"')
                    options[k] = None
            self.has_output = False
        elif command == 'code':
            for k in ('complete', 'outside_main', 'session'):
                if k in options:
                    self.source_warnings.append('Option "{0}" has no effect with command "code"')
                    options[k] = None
            self.has_output = True
        else:
            if not final_options['complete'] and self.is_expr:
                self.source_errors.append('Option "complete" value "false" is incompatible with inline expressions')
            if final_options['outside_main']:
                if self.is_expr:
                    self.source_errors.append('"outside_main" value "true" is incompatible with expr command')
                if 'complete' in options:
                    self.source_errors.append('Option "complete" cannot be specified with "outside_main" value "true"; it is inferred automatically')
                final_options['complete'] = False
            self.has_output = True
        self.options = final_options
        if 'copy' in self.options:
            self.copy_chunks = []

        self.session_obj = None
        self.session_index = None
        self.session_output_index = None
        self.stdout_lines = None
        self.stderr_lines = None
        if self.is_expr:
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


    commands = set(['code', 'expr', 'nb', 'run', 'paste'])

    _default_execute = collections.defaultdict(lambda: False,  # Unknown command -> do not run
                                               {k: True for k in ('expr', 'nb', 'run')})

    # Default value for 'show' is inserted before use, based on command+inline
    _default_block_options = {'complete': True,
                              'example': False,
                              'first_number': 'next',
                              'lang': None,
                              'line_numbers': True,
                              'outside_main': False,
                              'session': None}
    _default_inline_options = {'complete': True,
                               'example': False,
                               'lang': None,
                               'outside_main': False,
                               'session': None}

    _default_block_show = collections.defaultdict(lambda: ODict(),  # Unknown -> show nothing
                                                  {'code': ODict([('code', 'verbatim')]),
                                                   'nb':   ODict([('code', 'verbatim'),
                                                                  ('stdout', 'verbatim'),
                                                                  ('stderr', 'verbatim')]),
                                                   'run':  ODict([('stdout', 'raw'),
                                                                  ('stderr', 'verbatim')])})
    _default_inline_show = collections.defaultdict(lambda: ODict(),  # Unknown -> show nothing
                                                   {'code':  ODict([('code', 'verbatim')]),
                                                    'expr':  ODict([('expr', 'raw'),
                                                                    ('stderr', 'verbatim')]),
                                                    'nb':    ODict([('expr', 'raw'),
                                                                    ('stderr', 'verbatim')]),
                                                    'run':   ODict([('stdout', 'raw'),
                                                                    ('stderr', 'verbatim')])})

    _option_processors = _get_option_processors()


    def copy_code(self):
        if 'copy' not in self.options:
            raise TypeError
        copy_chunks = self.copy_chunks
        if self.options['lang'] is None:
            self.options['lang'] = copy_chunks[0].options['lang']
        if self.options['show'] is None:
            self.options['show'] = copy_chunks[0].options['show'].copy()
        if not any(x.execute for x in copy_chunks) or all(k == 'code' for k in self.options['show']):
            self.has_output = True
        if any(x.is_expr for x in copy_chunks):
            if len(copy_chunks) > 1:
                invalid_cc_names = ', '.join(x.options['name'] for x in copy_chunks if x.is_expr)
                message = 'Cannot copy multiple code chunks when one or more code chunks are expressions: {0}'.format(invalid_cc_names)
                self.source_errors.append(message)
            if self.command in ('paste', 'code'):
                # Some commands inherit expression status.  The code command
                # inherits so that subsequent copying doesn't result in
                # incorrectly concatenated expressions.  Since the code
                # command never has output, this has no display side effects.
                self.is_expr = True
            elif not self.is_expr:
                self.source_errors.append('A non-expression command cannot copy an expression code chunk')
        elif self.is_expr:
            self.source_errors.append('An expression command cannot copy a non-expression code chunk')
        if self.inline and 'code' in self.options['show'] and (len(copy_chunks) > 1 or len(copy_chunks[0].code_lines) > 1):
            self.source_errors.append('Cannot copy and then display multiple lines of code in an inline context')
        if self.source_errors:
            return
        if len(copy_chunks) == 1:
            self.code_lines = copy_chunks[0].code_lines
            self.code = copy_chunks[0].code
        else:
            self.code_lines = [line for x in copy_chunks for line in x.code_lines]
            self.code = '\n'.join(x.code for x in copy_chunks)
        if self.command == 'paste':
            self.code_start_line_number = copy_chunks[0].code_start_line_number


    def copy_output(self):
        if self.command != 'paste':
            raise TypeError
        copy_chunks = self.copy_chunks
        if not self.is_expr and 'expr' in self.options['show']:
            # Make sure 'show' is compatible with inherited expression status.
            # Can't do this during option processing because that is before
            # inheritance.
            del self.options['show']['expr']
            self.source_warnings.append('Invalid "show" value "expr" in paste code chunk')
        if len(copy_chunks) > 1:
            if len(set(x.session_obj for x in copy_chunks)) > 1:
                self.source_errors.append('Cannot copy and concatenate output from code chunks in different sessions')
            if any(x.session_index >= y.session_index for x, y in zip(copy_chunks[:-1], copy_chunks[1:])):
                self.source_errors.append('Cannot copy output of code chunks out of order, or copy a single code chunk multiple times')
        if self.source_errors:
            self.code_lines = None
            self.code = None
            return
        if self.is_expr:
            # For this case, already checked that len(copy_chunks) == 1
            self.expr_lines = copy_chunks[0].expr_lines
        if len(copy_chunks) == 1:
            self.stdout_lines = copy_chunks[0].stdout_lines
            self.stderr_lines = copy_chunks[0].stderr_lines
        else:
            self.stdout_lines = [line for x in copy_chunks if x.stdout_lines is not None for line in x.stdout_lines] or None
            self.stderr_lines = [line for x in copy_chunks if x.stderr_lines is not None for line in x.stderr_lines] or None
        self.has_output = True




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
                       for attr in [cls.from_formats, cls.multi_source_formats, cls.to_formats]):
                raise TypeError
            if (cls.from_formats is not None and cls.multi_source_formats is not None and
                    cls.multi_source_formats - cls.from_formats):
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
            if self.from_formats is not None:
                if from_format is None:
                    try:
                        source_formats = set([self._file_extension_to_format_dict[p.suffix] for p in paths])
                    except KeyError:
                        raise TypeError('Cannot determine document format from file extensions, or unsupported format')
                    from_format = source_formats.pop()
                    if source_formats:
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
            self.source_strings = [io.StringIO(s, newline=None).read() or '\n' for s in strings]
            if len(strings) == 1:
                self.source_names = ['<string>']
            else:
                self.source_names = ['<string({0})>'.format(n+1) for n in range(len(strings))]
            self.raw_source_paths = None
            self.expanded_source_paths = None
            if from_format is None:
                raise TypeError('Document format is required')
            if self.from_formats is not None and from_format not in self.from_formats:
                raise ValueError('Unsupported document format {0}'.format(from_format))
            self.from_format = from_format
        else:
            raise TypeError
        if len(self.source_strings) > 1 and from_format not in self.multi_source_formats:
            raise TypeError('Multiple sources are not supported for format {0}'.format(from_format))
        if not isinstance(no_cache, bool):
            raise TypeError
        self.no_cache = no_cache
        if isinstance(cache_path, str):
            cache_path = pathlib.Path(cache_path)
        elif not isinstance(cache_path, pathlib.Path) and cache_path is not None:
            raise TypeError
        if no_cache:
            cache_path = None
        elif cache_path is None:
            if paths is not None:
                cache_path = self.expanded_source_paths[0].parent / '_codebraid'
        else:
            if expandvars:
                cache_path = pathlib.Path(os.path.expandvars(str(cache_path.as_posix())))
            if expanduser:
                cache_path = cache_path.expanduser()
        if cache_path is not None and not cache_path.is_dir():
            cache_path.mkdir(parents=True)
        self.cache_path = cache_path
        self._io_map = False
        if not isinstance(synctex, bool):
            raise TypeError
        if synctex and cache_path is None:
            raise TypeError('Cache path must be specified')
        self.synctex = synctex
        if synctex:
            self._io_map = True

        self.code_chunks = []
        self.code_options = {}


    from_formats = None
    to_formats = None
    multi_source_formats = None

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
