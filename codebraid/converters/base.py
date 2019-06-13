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
import re
import textwrap
import typing; from typing import List, Optional, Sequence, Union
import zipfile
from .. import codeprocessors
from .. import err
from .. import util




class Include(dict):
    '''
    Store code chunk options related to including a file or other external
    resource.  Also perform the include and modify the code chunk as
    necessary.
    '''
    def __init__(self, code_chunk, include_options):
        # Start by creating fallback values for attributes
        self.code_lines = None

        self.code_chunk = code_chunk
        if not isinstance(include_options, dict):
            code_chunk.source_errors.append('Invalid "include" value "{0}"'.format(include_options))
            return

        if not all(k in self.keywords for k in include_options):
            unknown_keys = ', '.join("{0}".format(k) for k in include_options if k not in self.keywords)
            code_chunk.source_errors.append('Unknown "include" keywords: {0}'.format(unknown_keys))
        if not all(isinstance(v, str) and v for v in include_options.values()):
            invalid_value_keys = ', '.join("{0}".format(k) for k, v in include_options.items() if not isinstance(v, str) or not v)
            code_chunk.source_errors.append('Invalid values for "include" keywords: {0}'.format(invalid_value_keys))

        start_keywords = tuple(k for k in include_options if k in self._start_keywords)
        end_keywords = tuple(k for k in include_options if k in self._end_keywords)
        range_keywords = tuple(k for k in include_options if k in self._range_keywords)
        if ((range_keywords and (start_keywords or end_keywords)) or
                len(range_keywords) > 1 or len(start_keywords) > 1 or len(end_keywords) > 1):
            conflicting_keys = ', '.join("{0}".format(k) for k in include_options if k in self._selection_keywords)
            code_chunk.source_errors.append('Too many keywords for selecting part of an "include" file: {0}'.format(conflicting_keys))

        file = include_options.get('file', None)
        encoding = include_options.get('encoding', 'utf8')
        if file is None:
            code_chunk.source_errors.append('Missing "include" keyword "file"')

        if code_chunk.source_errors:
            return

        file_path = pathlib.Path(file).expanduser()
        try:
            text = file_path.read_text(encoding=encoding)
        except FileNotFoundError:
            code_chunk.source_errors.append('Cannot include nonexistent file "{0}"'.format(file))
        except LookupError:
            code_chunk.source_errors.append('Unknown encoding "{0}"'.format(encoding))
        except PermissionError:
            code_chunk.source_errors.append('Insufficient permissions to access file "{0}"'.format(file))
        except UnicodeDecodeError:
            code_chunk.source_errors.append('Cannot decode file "{0}" with encoding "{1}"'.format(file, encoding))
        if code_chunk.source_errors:
            return

        selection_keywords = start_keywords + end_keywords + range_keywords
        if selection_keywords:
            for kw in selection_keywords:
                text = getattr(self, '_option_'+kw)(include_options[kw], text)
                if code_chunk.source_errors:
                    return
        code_lines = util.splitlines_lf(text)
        self.code_lines = code_lines
        self.update(include_options)


    keywords = set(['file', 'encoding', 'lines', 'regex',
                    'start_string', 'start_regex', 'after_string', 'after_regex',
                    'before_string', 'before_regex', 'end_string', 'end_regex'])
    _start_keywords = set(['start_string', 'start_regex', 'after_string', 'after_regex'])
    _end_keywords = set(['before_string', 'before_regex', 'end_string', 'end_regex'])
    _range_keywords = set(['lines', 'regex'])
    _selection_keywords = _start_keywords | _end_keywords | _range_keywords


    def _option_lines(self, value, text,
                      pattern_re=re.compile(r'{n}(?:-(?:{n})?)?(?:,{n}(?:-(?:{n})?)?)*\Z'.format(n='[1-9][0-9]*'))):
        value = value.replace(' ', '')
        if not pattern_re.match(value):
            self.code_chunk.source_errors.append('Invalid value for "include" option "lines"')
            return
        max_line_number = text.count('\n')
        if text[-1:] != '\n':
            max_line_number += 1
        include_line_indices = set()
        for line_range in value.split(','):
            if '-' not in line_range:
                include_line_indices.add(int(line_range)-1)
            else:
                start, end = line_range.split('-')
                start = int(start) - 1
                end = int(end) if end else max_line_number
                include_line_indices.update(range(start, end))
        text_lines = util.splitlines_lf(text)
        return '\n'.join(text_lines[n] for n in sorted(include_line_indices))


    def _option_regex(self, value, text):
        try:
            pattern_re = re.compile(value, re.MULTILINE | re.DOTALL)
        except re.error:
            self.code_chunk.source_errors.append('Invalid regex pattern for "include" option "regex"')
            return
        match = pattern_re.search(text)
        if match is None:
            self.code_chunk.source_errors.append('The pattern given by "include" option "regex" was not found')
            return
        return match.group()


    def _option_start_string(self, value, text):
        index = text.find(value)
        if index < 0:
            self.code_chunk.source_errors.append('The pattern given by "include" option "start_string" was not found')
            return
        return text[index:]


    def _option_start_regex(self, value, text):
        try:
            pattern_re = re.compile(value, re.MULTILINE | re.DOTALL)
        except re.error:
            self.code_chunk.source_errors.append('Invalid regex pattern for "include" option "start_regex"')
            return
        match = pattern_re.search(text)
        if match is None:
            self.code_chunk.source_errors.append('The pattern given by "include" option "start_regex" was not found')
            return
        return text[match.start():]


    def _option_after_string(self, value, text):
        index = text.find(value)
        if index < 0:
            self.code_chunk.source_errors.append('The pattern given by "include" option "after_string" was not found')
            return
        return text[index+len(value):]


    def _option_after_regex(self, value, text):
        try:
            pattern_re = re.compile(value, re.MULTILINE | re.DOTALL)
        except re.error:
            self.code_chunk.source_errors.append('Invalid regex pattern for "include" option "after_regex"')
            return
        match = pattern_re.search(text)
        if match is None:
            self.code_chunk.source_errors.append('The pattern given by "include" option "after_regex" was not found')
            return
        return text[match.end():]


    def _option_before_string(self, value, text):
        index = text.find(value)
        if index < 0:
            self.code_chunk.source_errors.append('The pattern given by "include" option "before_string" was not found')
            return
        return text[:index]


    def _option_before_regex(self, value, text):
        try:
            pattern_re = re.compile(value, re.MULTILINE | re.DOTALL)
        except re.error:
            self.code_chunk.source_errors.append('Invalid regex pattern for "include" option "before_regex"')
            return
        match = pattern_re.search(text)
        if match is None:
            self.code_chunk.source_errors.append('The pattern given by "include" option "before_regex" was not found')
            return
        return text[:match.start()]


    def _option_end_string(self, value, text):
        index = text.find(value)
        if index < 0:
            self.code_chunk.source_errors.append('The pattern given by "include" option "end_string" was not found')
            return
        return text[:index+len(value)]


    def _option_end_regex(self, value, text):
        try:
            pattern_re = re.compile(value, re.MULTILINE | re.DOTALL)
        except re.error:
            self.code_chunk.source_errors.append('Invalid regex pattern for "include" option "end_regex"')
            return
        match = pattern_re.search(text)
        if match is None:
            self.code_chunk.source_errors.append('The pattern given by "include" option "end_regex" was not found')
            return
        return text[:match.end()]




class Options(dict):
    '''
    Store code chunk options.  Also modify the code chunk as necessary based
    on the options.

    Option processing methods check options for validity and process them, but
    do not perform any type conversions.  Any desired type conversions must be
    performed in format-specific subclasses of CodeChunk, which can take into
    account the data types that a given document format allows for options.
    Subclasses must also handle duplicate options, since at this point options
    must have been reduced to a dict.

    The effect of all options is independent of their order.  When two options
    would have an order-dependent effect, only one of them is permitted at a
    time.

    Invalid options related to presentation result in warnings, while invalid
    options related to code execution result in errors.  When possible, option
    processing proceeds even after an error, to give a more complete error
    message.  There are two approaches to handling errors:  Stop all code
    execution, or stop all code execution related to the error.  The latter
    approach is currently taken.  Processing as many options as possible makes
    it easier to determine which code execution is related to an error.  For
    example, if the session option is processed for a code chunk with an
    error, then only that session can be disabled, instead of the entire
    language related to the error.
    '''
    def __init__(self, code_chunk, custom_options):
        self.code_chunk = code_chunk
        if code_chunk.inline:
            self.update(self._default_inline_options)
        else:
            self.update(self._default_block_options)
        if code_chunk.execute:
            self['session'] = None
        else:
            self['source'] = None
        self['first_chunk_options'] = {}
        if any(k not in self.keywords for k in custom_options):
            unknown_keys = ', '.join('"{0}"'.format(k) for k in custom_options if k not in self.keywords)
            # Raise an error for unknown options.  There is no way to tell
            # whether an execution or presentation option was intended, so
            # take the safer approach.
            code_chunk.source_errors.append('Unknown keywords: {0}'.format(unknown_keys))
            # Treat received `custom_options` as immutable
            custom_options = {k: v for k, v in custom_options.items() if k in self.keywords}
        self.custom_options = custom_options

        for k, v in custom_options.items():
            if k not in self._after_copy_keywords:
                getattr(self, '_option_'+k)(k, v)

        if not code_chunk.source_errors and 'copy' not in self:
            # Only handle 'show' and 'hide' if there are no errors so far and
            # there is not a pending 'copy', which for some commands might
            # change `.is_expr` or the defaults for 'show'.  If there are
            # errors, 'show' and 'hide' are never used.
            if code_chunk.inline:
                self['show'] = self._default_inline_show[code_chunk.command].copy()
            else:
                self['show'] = self._default_block_show[code_chunk.command].copy()
            for k, v in custom_options.items():
                if k in self._after_copy_keywords:
                    getattr(self, '_option_'+k)(k, v)


    def finalize_after_copy(self, *, lang, show):
        '''
        Complete any option processing that must wait until after copying.
        For the paste command, 'show' can be inherited.  For paste and code,
        `.is_expr` can be inherited.  'lang' can also be inherited.
        '''
        code_chunk = self.code_chunk
        custom_options = self.custom_options
        if self['lang'] is None:
            self['lang'] = lang
        if code_chunk.inline:
            if code_chunk.command == 'paste' and 'show' not in custom_options:
                self['show'] = show.copy()  # Inherit
            else:
                self['show'] = self._default_inline_show[code_chunk.command].copy()
        else:
            if code_chunk.command == 'paste' and 'show' not in custom_options:
                self['show'] = show.copy()  # Inherit
            else:
                self['show'] = self._default_block_show[code_chunk.command].copy()

        for key in self._after_copy_keywords:
            if key in custom_options:
                getattr(self, '_option_'+key)(key, custom_options[key])


    _base_keywords = set(['complete', 'copy', 'example', 'hide', 'hide_markup_keys', 'include',
                          'lang', 'name', 'outside_main', 'session', 'source', 'show'])
    _layout_keywords = set(['{0}_{1}'.format(dsp, kw) if dsp else kw
                            for dsp in ('', 'markup', 'copied_markup', 'code', 'stdout', 'stderr')
                            for kw in ('first_number', 'line_numbers', 'rewrap_lines', 'rewrap_width', 'expand_tabs', 'tab_size')])
    _first_chunk_execute_keywords = set(['executable', 'jupyter_kernel'])
    _first_chunk_save_keywords = set(['save', 'save_as'])
    _first_chunk_keywords = _first_chunk_execute_keywords | _first_chunk_save_keywords

    keywords = _base_keywords | _layout_keywords | _first_chunk_keywords

    _after_copy_keywords = set(['hide', 'show'])


    # Default values for show and session/source are inserted later based on
    # command and inline status
    _default_inline_options = {'complete': True,
                               'example': False,
                               'lang': None,
                               'outside_main': False}
    _default_block_options = _default_inline_options.copy()
    _default_block_options.update({'code_first_number': 'next',
                                   'code_line_numbers': True})

    # The defaultdict handles unknown commands that are represented as None
    _default_inline_show = collections.defaultdict(lambda: ODict(),  # Unknown -> show nothing
                                                   {'code':  ODict([('code', 'verbatim')]),
                                                    'expr':  ODict([('expr', 'raw'),
                                                                    ('stderr', 'verbatim')]),
                                                    # expr and rich_output don't clash, because expr is only present
                                                    # with the built-in code execution system, while rich_output
                                                    # requires a Jupyter kernel.  If the built-in system gains
                                                    # rich_output capabilities or there are other related changes,
                                                    # this may need refactoring.
                                                    'nb':    ODict([('expr', 'raw'),
                                                                    ('rich_output', 'latex|markdown|png|jpg|plain'.split('|')),
                                                                    ('stderr', 'verbatim')]),
                                                    'paste': ODict(),
                                                    'run':   ODict([('stdout', 'raw'),
                                                                    ('stderr', 'verbatim')])})
    _default_block_show = collections.defaultdict(lambda: ODict(),  # Unknown -> show nothing
                                                  {'code': ODict([('code', 'verbatim')]),
                                                   'nb':   ODict([('code', 'verbatim'),
                                                                  ('stdout', 'verbatim'),
                                                                  ('stderr', 'verbatim'),
                                                                  ('rich_output', 'latex|markdown|png|jpg|plain'.split('|'))]),
                                                   'paste': ODict(),
                                                   'run':  ODict([('stdout', 'raw'),
                                                                  ('stderr', 'verbatim'),
                                                                  ('rich_output', 'latex|markdown|png|jpg|plain'.split('|'))])})


    def _option_bool_warning(self, key, value):
        if not isinstance(value, bool):
            self.code_chunk.source_warnings.append('Invalid "{0}" value "{1}"'.format(key, value))
        else:
            self[key] = value

    def _option_bool_error(self, key, value):
        if not isinstance(value, bool):
            self.code_chunk.source_errors.append('Invalid "{0}" value "{1}"'.format(key, value))
        else:
            self[key] = value

    def _option_str_warning(self, key, value):
        if not isinstance(value, str):
            self.code_chunk.source_warnings.append('Invalid "{0}" value "{1}"'.format(key, value))
        else:
            self[key] = value

    def _option_str_error(self, key, value):
        if not isinstance(value, str):
            self.code_chunk.source_errors.append('Invalid "{0}" value "{1}"'.format(key, value))
        else:
            self[key] = value

    def _option_positive_int_warning(self, key, value):
        if not isinstance(value, int) or value <= 0:
            self.code_chunk.source_warnings.append('Invalid "{0}" value "{1}"'.format(key, value))
        else:
            self[key] = value

    def _option_positive_int_error(self, key, value):
        if not isinstance(value, int) or value <= 0:
            self.code_chunk.source_errors.append('Invalid "{0}" value "{1}"'.format(key, value))
        else:
            self[key] = value

    def _option_first_chunk_bool_error(self, key, value):
        if not isinstance(value, bool):
            self.code_chunk.source_errors.append('Invalid "{0}" value "{1}"'.format(key, value))
        else:
            self['first_chunk_options'][key] = value

    def _option_first_chunk_string_error(self, key, value):
        if not isinstance(value, str):
            self.code_chunk.source_errors.append('Invalid "{0}" value "{1}"'.format(key, value))
        else:
            first_chunk_options = self['first_chunk_options']
            if (key in self._first_chunk_execute_keywords and
                    any(k in first_chunk_options for k in self._first_chunk_execute_keywords)):
                conflicting_options = ', '.join('"{0}"'.format(k) for k in self._first_chunk_execute_keywords if k in first_chunk_options)
                self.code_chunk.source_errors.append('Conflicting options: {0}'.format(conflicting_options))
            else:
                first_chunk_options[key] = value

    _option_executable = _option_first_chunk_string_error
    _option_jupyter_kernel = _option_first_chunk_string_error
    _option_save = _option_first_chunk_bool_error
    _option_save_as = _option_first_chunk_string_error

    _option_example = _option_bool_warning
    _option_lang = _option_str_error


    def _option_complete(self, key, value):
        if not isinstance(value, bool):
            self.code_chunk.source_errors.append('Invalid "{0}" value "{1}"'.format(key, value))
        elif not self.code_chunk.execute:
            self.code_chunk.source_errors.append('Option "complete" is only compatible with executed code chunks')
        elif self.code_chunk.is_expr and not value:
            self.code_chunk.source_errors.append('Option "complete" value "false" is incompatible with expr command')
        elif self['outside_main']:
            # Technically, this is only required for complete=true, but
            # prohibiting it in all cases is more consistent
            self.code_chunk.source_errors.append('Option "complete" is incompatible with "outside_main" value "true"')
        else:
            self[key] = value


    def _option_copy(self, key, value):
        if not isinstance(value, str):
            self.code_chunk.source_errors.append('Invalid "{0}" value "{1}"'.format(key, value))
        elif 'include' in self:
            self.code_chunk.source_errors.append('Option "copy" is incompatible with "include"')
        else:
            # Since non-identifier code chunk names can't be defined, there's
            # no need to check for identifier-style names here
            self[key] = [x.strip() for x in value.split('+')]


    def _option_expand_tabs(self, key, value):
        if key == 'expand_tabs':
            key = 'code_expand_tabs'
        self._option_bool_warning(key, value)

    _option_markup_expand_tabs = _option_expand_tabs
    _option_copied_markup_expand_tabs = _option_expand_tabs
    _option_code_expand_tabs = _option_expand_tabs
    _option_stdout_expand_tabs = _option_expand_tabs
    _option_stderr_expand_tabs = _option_expand_tabs


    def _option_first_number(self, key, value):
        if not ((isinstance(value, int) and value > 0) or (isinstance(value, str) and value == 'next')):
            self.code_chunk.source_warnings.append('Invalid "{0}" value "{1}"'.format(key, value))
        else:
            if key == 'first_number':
                key = 'code_first_number'
            self[key] = value

    _option_markup_first_number = _option_first_number
    _option_copied_markup_first_number = _option_first_number
    _option_code_first_number = _option_first_number
    _option_stdout_first_number = _option_first_number
    _option_stderr_first_number = _option_first_number


    def _option_rewrap_lines(self, key, value):
        if key == 'rewrap_lines':
            key = 'code_rewrap_lines'
        self._option_bool_warning(key, value)

    _option_markup_rewrap_lines = _option_rewrap_lines
    _option_copied_markup_rewrap_lines = _option_rewrap_lines
    _option_code_rewrap_lines = _option_rewrap_lines
    _option_stdout_rewrap_lines = _option_rewrap_lines
    _option_stderr_rewrap_lines = _option_rewrap_lines


    def _option_rewrap_width(self, key, value):
        if key == 'rewrap_width':
            key = 'code_rewrap_width'
        self._option_positive_int_warning(key, value)

    _option_markup_rewrap_width = _option_rewrap_width
    _option_copied_markup_rewrap_width = _option_rewrap_width
    _option_code_rewrap_width = _option_rewrap_width
    _option_stdout_rewrap_width = _option_rewrap_width
    _option_stderr_rewrap_width = _option_rewrap_width


    def _option_hide(self, key, value,
                     display_values=set(['markup', 'copied_markup', 'code', 'stdout', 'stderr', 'expr', 'rich_output'])):
        # 'hide' may be processed during `finalize_after_copy()` to allow for
        # 'show' and `.is_expr` inheritance.
        if not isinstance(value, str):
            self.code_chunk.source_warnings.append('Invalid "{0}" value "{1}"'.format(key, value))
        elif 'show' in self.custom_options:
            # 'hide' checks for 'show' conflict, so 'show' does not.  Check
            # in `custom_options` since there's a default 'show' in `self`.
            self.code_chunk.source_warnings.append('Option "hide" cannot be used with "show"')
        elif value == 'all':
            self['show'] = ODict()
        else:
            hide_values = value.replace(' ', '').split('+')
            if not all(v in display_values for v in hide_values):
                self.code_chunk.source_warnings.append('Invalid "{0}" value "{1}"'.format(key, value))
            else:
                for v in hide_values:
                    self['show'].pop(v, None)


    def _option_hide_markup_keys(self, key, value):
        if not isinstance(value, str):
            self.code_chunk.source_warnings.append('Invalid "{0}" value "{1}"'.format(key, value))
        else:
            # No need to check keys for validity; this is a display option.
            hide_keys = set(value.replace(' ', '').split('+'))
            hide_keys.add('hide_markup_keys')
            self[key] = hide_keys


    def _option_include(self, key, value):
        # Include() does its own value check, so this isn't technically needed
        if not isinstance(value, dict):
            self.code_chunk.source_errors.append('Invalid "{0}" value "{1}"'.format(key, value))
        elif 'copy' in self:
            self.code_chunk.source_errors.append('Option "include" is incompatible with "copy"')
        else:
            include = Include(self.code_chunk, value)
            if include.code_lines is not None:
                self[key] = include


    def _option_line_numbers(self, key, value):
        if not isinstance(value, bool):
            self.code_chunk.source_warnings.append('Invalid "{0}" value "{1}"'.format(key, value))
        else:
            if key == 'line_numbers':
                key = 'code_line_numbers'
            self[key] = value

    _option_markup_line_numbers = _option_line_numbers
    _option_copied_markup_line_numbers = _option_line_numbers
    _option_code_line_numbers = _option_line_numbers
    _option_stdout_line_numbers = _option_line_numbers
    _option_stderr_line_numbers = _option_line_numbers


    def _option_name(self, key, value):
        if not isinstance(value, str):
            self.code_chunk.source_warnings.append('Invalid "{0}" value "{1}"'.format(key, value))
        elif not value.isidentifier():
            self.code_chunk.source_warnings.append('Option "{0}" has invalid, non-identifier value "{1}"'.format(key, value))
        else:
            self[key] = value


    def _option_outside_main(self, key, value):
        if not isinstance(value, bool):
            self.code_chunk.source_errors.append('Invalid "{0}" value "{1}"'.format(key, value))
        elif not self.code_chunk.execute:
            self.code_chunk.source_errors.append('Option "outside_main" is only compatible with executed code chunks')
        elif self.code_chunk.is_expr and value:
            self.code_chunk.source_errors.append('Option "outside_main" value "true" is incompatible with expr command')
        elif value and 'complete' in self.custom_options:
            self.code_chunk.source_errors.append('Option "outside_main" value "true" is incompatible with "complete"')
        else:
            self['complete'] = False
            self[key] = value


    def _option_source(self, key, value):
        if not isinstance(value, str):
            self.code_chunk.source_errors.append('Invalid "{0}" value "{1}"'.format(key, value))
        elif self.code_chunk.execute and self.code_chunk.command is not None:
            # Always preserve sources for unknown commands, so that these
            # sources can be marked as having potential errors later
            self.code_chunk.source_errors.append('Option "source" is only compatible with non-executed code chunks; otherwise, use "session"')
        elif not value.isidentifier():
            self.code_chunk.source_errors.append('Option "{0}" has invalid, non-identifier value "{1}"'.format(key, value))
        else:
            self[key] = value


    def _option_session(self, key, value):
        if not isinstance(value, str):
            self.code_chunk.source_errors.append('Invalid "{0}" value "{1}"'.format(key, value))
        elif not self.code_chunk.execute and self.code_chunk.command is not None:
            # Always preserve sessions for unknown commands, so that these
            # sessions can be marked as having potential errors later
            self.code_chunk.source_errors.append('Option "session" is only compatible with executed code chunks; otherwise, use "source"')
        elif not value.isidentifier():
            self.code_chunk.source_errors.append('Option "{0}" has invalid, non-identifier value "{1}"'.format(key, value))
        else:
            self[key] = value


    mime_map = {'latex': 'text/latex',
                'html': 'text/html',
                'markdown': 'text/markdown',
                'plain': 'text/plain',
                'png': 'image/png',
                'jpg': 'image/jpeg',
                'jpeg': 'image/jpeg',
                'svg': 'image/svg+xml',
                'pdf': 'application/pdf'}

    def _option_show(self, key, value):
        # 'show' may be processed during `finalize_after_copy()` to allow for
        # 'show' and `.is_expr` inheritance.  'hide' checks for 'show'
        # conflict, so 'show' does not.
        if not (isinstance(value, str) or value is None):
            self.code_chunk.source_warnings.append('Invalid "{0}" value "{1}"'.format(key, value))
        elif value in ('none', None):
            self[key] = ODict()
        else:
            value_processed = ODict()
            for output_and_format in value.replace(' ', '').split('+'):
                if ':' not in output_and_format:
                    output = output_and_format
                    format = None
                else:
                    output, format = output_and_format.split(':', 1)
                if output in value_processed:
                    self.code_chunk.source_warnings.append('Option "{0}" value "{1}" contains duplicate "{2}"'.format(key, value, output))
                    continue
                if output in ('markup', 'copied_markup', 'code'):
                    if format is None:
                        format = 'verbatim'
                    elif format != 'verbatim':
                        self.code_chunk.source_warnings.append('Invalid "{0}" sub-value "{1}"'.format(key, output_and_format))
                        continue
                    if output == 'copied_markup' and 'copy' not in self.custom_options:
                        self.code_chunk.source_warnings.append('Invalid "{0}" sub-value "{1}"; can only be used with "copy"'.format(key, output_and_format))
                        continue
                elif output in ('stdout', 'stderr'):
                    if format is None:
                        format = 'verbatim'
                    elif format not in ('verbatim', 'verbatim_or_empty', 'raw'):
                        self.code_chunk.source_warnings.append('Invalid "{0}" sub-value "{1}"'.format(key, output_and_format))
                        continue
                elif output == 'expr':
                    if not self.code_chunk.is_expr:
                        self.code_chunk.source_warnings.append('Invalid "{0}" sub-value "{1}"'.format(key, output_and_format))
                        continue
                    if format is None:
                        format = 'raw'
                    elif format not in ('verbatim', 'verbatim_or_empty', 'raw'):
                        self.code_chunk.source_warnings.append('Invalid "{0}" sub-value "{1}"'.format(key, output_and_format))
                        continue
                elif output == 'rich_output':
                    if format is None:
                        format = 'latex|markdown|png|jpg|plain'.split('|')
                    else:
                        format = format.split('|')
                        if not all(fmt in self.mime_map for fmt in format):
                            self.code_chunk.source_warnings.append('Invalid "{0}" sub-value "{1}"'.format(key, output_and_format))
                            continue
                else:
                    self.code_chunk.source_warnings.append('Invalid "{0}" sub-value "{1}"'.format(key, output_and_format))
                    continue
                value_processed[output] = format
            self[key] = value_processed


    def _option_tab_size(self, key, value):
        if key == 'tab_size':
            key = 'code_tab_size'
        self._option_positive_int_warning(key, value)

    _option_markup_tab_size = _option_tab_size
    _option_copied_markup_tab_size = _option_tab_size
    _option_code_tab_size = _option_tab_size
    _option_stdout_tab_size = _option_tab_size
    _option_stderr_tab_size = _option_tab_size




class CodeChunk(object):
    '''
    Base class for code chunks.
    '''
    def __init__(self,
                 command: str,
                 code: Union[str, List[str]],
                 custom_options: dict,
                 source_name: str, *,
                 source_start_line_number: Optional[int]=None,
                 inline: Optional[bool]=None):
        self.__pre_init__()

        if command not in self.commands:
            if command is None:
                self.source_errors.append('Missing valid Codebraid command')
            else:
                self.source_errors.append('Unknown Codebraid command "{0}"'.format(command))
            self.command = None
        else:
            self.command = command
        if command == 'expr' and not inline:
            self.source_errors.append('Codebraid command "{0}" is only allowed inline'.format(command))
        self.execute = self._default_execute[command]
        if command == 'expr' or (inline and command == 'nb'):
            self.is_expr = True
        else:
            # For the paste command, or code with 'copy', this value can
            # change later due to inheritance
            self.is_expr = False
        self.source_name = source_name
        self.source_start_line_number = source_start_line_number
        self.inline = inline

        # Check for len(code_lines) > 1 for inline later
        self._code = None
        if isinstance(code, list):
            code_lines = code
        else:
            code_lines = util.splitlines_lf(code) or ['']
        if 'copy' not in custom_options and 'include' not in custom_options:
            if inline and len(code_lines) > 1:
                self.source_errors.append('Inline code cannot be longer that 1 line')
            self.code_lines = code_lines
            self.placeholder_code_lines = None
        else:
            if inline:
                if len(code_lines) > 1 or code_lines[0] not in ('', ' ', '_'):
                    self.source_errors.append('Invalid placeholder code for copy or include (need space or underscore)')
            elif len(code_lines) > 1 or code_lines[0].rstrip(' ') not in ('', '_'):
                self.source_errors.append('Invalid placeholder code for copy or include (need empty, space, or underscore)')
            # Copying or including code could result in more than one line of
            # code in an inline context.  That is only an issue if the code is
            # actually displayed.  This is checked later when code is
            # included/copied.
            self.placeholder_code_lines = code_lines
            self.code_lines = None

        self.options = Options(self, custom_options)

        if 'include' in self.options and not self.source_errors:
            # Copy over include only if no source errors -- otherwise it isn't
            # used and 'show' may not exist
            include = self.options['include']
            if inline and 'code' in self.options['show'] and len(include.code_lines) > 1:
                self.source_errors.append('Cannot include and then display multiple lines of code in an inline context')
            else:
                self.code_lines = include.code_lines

        if command == 'paste':
            if 'copy' not in custom_options:
                self.source_errors.append('Command "paste" cannot be used without specifying a target via "copy"')
            self.has_output = False
        else:
            self.has_output = True  # Whether need output from copying
        if 'copy' in self.options:
            self.copy_chunks = []

        if self.execute:
            self.session_obj = None
            self.session_index = None
            self.session_output_index = None
        else:
            self.source_obj = None
            self.source_index = None
        self.stdout_lines = None
        self.stderr_lines = None
        self.rich_output = None
        if self.is_expr:
            self.expr_lines = None
        self.markup_start_line_number = None
        self.code_start_line_number = None
        self.stdout_start_line_number = None
        self.stderr_start_line_number = None


    def __pre_init__(self):
        '''
        Create lists of errors and warnings.  Subclasses may need to register
        errors or warnings during preprocessing, before they are ready
        for `super().__init__()`
        '''
        if not hasattr(self, 'source_errors'):
            self.source_errors = []
            self.runtime_source_error = False
            self.source_warnings = []


    commands = set(['code', 'expr', 'nb', 'run', 'paste'])

    _default_execute = collections.defaultdict(lambda: False,  # Unknown command -> do not run
                                               {k: True for k in ('expr', 'nb', 'run')})


    @property
    def code(self):
        code = self._code
        if code is not None:
            return code
        code = '\n'.join(self.code_lines)
        self._code = code
        return code


    def copy_code(self):
        '''
        Copy code for 'copy' option.  Code is copied before execution, which
        is more flexible.  Output (stdout, stderr, expr) must be copied
        separately after execution.

        This should only be invoked for a code chunk with no source errors,
        with copy targets that all exist and have no source errors.
        '''
        copy_chunks = self.copy_chunks
        if any(cc.is_expr for cc in copy_chunks):
            if len(copy_chunks) > 1:
                invalid_cc_names = ', '.join(cc.options['name'] for cc in copy_chunks if cc.is_expr)
                self.source_errors.append('Cannot copy multiple code chunks when some are expressions: {0}'.format(invalid_cc_names))
            if self.command in ('paste', 'code'):
                # Some commands inherit expression status.  The code command
                # inherits so that subsequent copying doesn't result in
                # incorrectly concatenated expressions.  Since the code
                # command never has output, this has no display side effects.
                self.is_expr = True
                self.expr_lines = None
            elif not self.is_expr:
                self.source_errors.append('A non-expression command cannot copy an expression code chunk')
        elif self.is_expr:
            self.source_errors.append('An expression command cannot copy a non-expression code chunk')
        if self.source_errors:
            return
        # Finalizing options must come after any potential `.is_expr`
        # modifications
        self.options.finalize_after_copy(lang=copy_chunks[0].options['lang'],
                                         show=copy_chunks[0].options['show'])
        if self.inline and 'code' in self.options['show'] and (len(copy_chunks) > 1 or len(copy_chunks[0].code_lines) > 1):
            self.source_errors.append('Cannot copy and then display multiple lines of code in an inline context')
            return
        if len(copy_chunks) == 1:
            self.code_lines = copy_chunks[0].code_lines
        else:
            self.code_lines = [line for x in copy_chunks for line in x.code_lines]
        if self.command == 'paste':
            if all(cc.command == 'code' for cc in copy_chunks):
                # When possible, simplify the copying resolution process
                self.has_output = True
        self.code_start_line_number = copy_chunks[0].code_start_line_number


    def copy_output(self):
        '''
        Copy output (stdout, stderr, expr) for 'copy' option.  This must be
        copied separately from code, after execution.

        This should only be invoked for a code chunk with no source errors,
        with copy targets that all exist and have no source errors.
        '''
        if self.command != 'paste':
            raise TypeError
        copy_chunks = self.copy_chunks
        # The case of all code chunks being code commands has already been
        # handled in `copy_code()`
        if any(cc.command == 'paste' for cc in copy_chunks):
            if len(copy_chunks) > 1:
                if all(cc.command == 'paste' for cc in copy_chunks):
                    self.source_errors.append('Can only copy a single paste code chunk; cannot combine multiple paste chunks')
                else:
                    self.source_errors.append('Cannot copy a mixture of paste and other code chunks')
        elif any(cc.execute for cc in copy_chunks):
            if not all(cc.execute for cc in copy_chunks):
                self.source_errors.append('Copying output of multiple code chunks requires that all or none are executed')
            elif len(copy_chunks) > 1:
                if len(set(cc.session_obj for cc in copy_chunks)) > 1:
                    self.source_errors.append('Cannot copy output from code chunks in multiple sessions')
                elif any(ccx.session_index != ccy.session_index-1 for ccx, ccy in zip(copy_chunks[:-1], copy_chunks[1:])):
                    if any(ccx is ccy for ccx, ccy in zip(copy_chunks[:-1], copy_chunks[1:])):
                        self.source_errors.append('Cannot copy output of a single code chunk multiple times')
                    elif any(ccx.session_index > ccy.session_index for ccx, ccy in zip(copy_chunks[:-1], copy_chunks[1:])):
                        self.source_errors.append('Cannot copy output of code chunks out of order')
                    else:
                        self.source_errors.append('Cannot copy output of code chunks when some chunks in a sequence are omitted')
        else:
            raise ValueError
        if self.source_errors:
            # If errors, discard what has already been copied
            self.code_lines = None
            return
        if len(copy_chunks) == 1:
            self.stdout_lines = copy_chunks[0].stdout_lines
            self.stderr_lines = copy_chunks[0].stderr_lines
            self.rich_output = copy_chunks[0].rich_output
        else:
            self.stdout_lines = [line for x in copy_chunks if x.stdout_lines is not None for line in x.stdout_lines] or None
            self.stderr_lines = [line for x in copy_chunks if x.stderr_lines is not None for line in x.stderr_lines] or None
            self.rich_output = [ro for x in copy_chunks if x.rich_output is not None for ro in x.rich_output] or None
        if self.is_expr:
            # expr compatibilty has already been checked in `copy_code()`
            self.expr_lines = copy_chunks[0].expr_lines
        self.stdout_start_line_number = copy_chunks[0].stdout_start_line_number
        self.stderr_start_line_number = copy_chunks[0].stderr_start_line_number
        self.has_output = True


    def layout_output(self, output_type, output_format, lines=None):
        '''
        Layout all forms of output, except for rich output that is not
        text/plain, by performing operations such as line rewrapping and tab
        expansion.  If `lines` is supplied, it is used.  Otherwise, the
        default lines (if any) are accessed for the specified output type.
        '''
        if lines is not None:
            pass
        elif output_type == 'code':
            lines = self.code_lines
        elif output_type in ('expr', 'stdout', 'stderr'):
            lines = getattr(self, output_type+'_lines')
            if lines is None and output_format == 'verbatim_or_empty':
                lines = ['\xa0']
        elif output_type == 'markup':
            lines = self.as_markup_lines
        elif output_type == 'example_markup':
            lines = self.as_example_markup_lines
        elif output_type == 'copied_markup':
            if len(self.copy_chunks) == 1:
                lines = self.copy_chunks[0].as_markup_lines
            elif self.inline:
                lines = []
                for cc in self.copy_chunks:
                    lines.extend(cc.as_markup_lines)
            else:
                lines = []
                last_cc = self.copy_chunks[-1]
                for cc in self.copy_chunks:
                    lines.extend(cc.as_markup_lines)
                    if cc is not last_cc:
                        lines.append('')
        else:
            raise ValueError

        rewrap_lines = self.options.get(output_type+'_rewrap_lines', False)
        rewrap_width = self.options.get(output_type+'_rewrap_width', 78)
        expand_tabs = self.options.get(output_type+'_expand_tabs', False)
        tab_size = self.options.get(output_type+'_tab_size', 8)
        # This should be rewritten once rewrapping design is finalized, since
        # textwrap doesn't necessarily do everything as might be desired, and
        # the use of textwrap could be optimized if it continues to be used.
        # Nothing is done yet with tabs.
        if rewrap_lines:
            new_lines = []
            for line in lines:
                if not line:
                    new_lines.append(line)
                    continue
                line_stripped = line.lstrip(' \t')
                indent = line[:len(line)-len(line_stripped)]
                new_lines.extend(textwrap.wrap(line_stripped, width=rewrap_width-len(indent), initial_indent=indent, subsequent_indent=indent))
            lines = new_lines
        if self.inline:
            return ' '.join(lines)
        return '\n'.join(lines)




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
