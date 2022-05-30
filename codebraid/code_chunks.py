# -*- coding: utf-8 -*-
#
# Copyright (c) 2021-2022, Geoffrey M. Poore
# All rights reserved.
#
# Licensed under the BSD 3-Clause License:
# http://opensource.org/licenses/BSD-3-Clause
#


from __future__ import annotations


import collections
from collections import OrderedDict as ODict
import pathlib
import re
import textwrap
import typing
from typing import List, NamedTuple, Optional, Union
from . import message
from . import util
if typing.TYPE_CHECKING:
    from .code_collections import CodeCollection




class CodeKey(NamedTuple):
    '''
    Collection of attributes uniquely identifying a session or source.
    '''
    lang: Optional[str]
    name: Optional[str]
    type: str
    origin_name: Optional[str]


class Include(dict):
    '''
    Store code chunk options related to including a file or other external
    resource.  Also perform the include and modify the code chunk as
    necessary.
    '''
    def __init__(self, code_chunk, include_options):
        # Start by creating fallback values for attributes
        self.code_lines = []

        self.code_chunk = code_chunk
        if not isinstance(include_options, dict):
            code_chunk.errors.append(message.SourceError('Invalid "include" value "{0}"'.format(include_options)))
            return

        if not all(k in self.keywords for k in include_options):
            unknown_keys = ', '.join("{0}".format(k) for k in include_options if k not in self.keywords)
            code_chunk.errors.append(message.SourceError('Unknown "include" keywords: {0}'.format(unknown_keys)))
        if not all(isinstance(v, str) and v for v in include_options.values()):
            invalid_value_keys = ', '.join("{0}".format(k) for k, v in include_options.items() if not isinstance(v, str) or not v)
            code_chunk.errors.append(message.SourceError('Invalid values for "include" keywords: {0}'.format(invalid_value_keys)))

        start_keywords = tuple(k for k in include_options if k in self._start_keywords)
        end_keywords = tuple(k for k in include_options if k in self._end_keywords)
        range_keywords = tuple(k for k in include_options if k in self._range_keywords)
        if ((range_keywords and (start_keywords or end_keywords)) or
                len(range_keywords) > 1 or len(start_keywords) > 1 or len(end_keywords) > 1):
            conflicting_keys = ', '.join("{0}".format(k) for k in include_options if k in self._selection_keywords)
            code_chunk.errors.append(message.SourceError('Too many keywords for selecting part of an "include" file: {0}'.format(conflicting_keys)))

        file = include_options.get('file', None)
        encoding = include_options.get('encoding', 'utf8')
        if file is None:
            code_chunk.errors.append(message.SourceError('Missing "include" keyword "file"'))

        if code_chunk.errors:
            return

        file_path = pathlib.Path(file).expanduser()
        try:
            text = file_path.read_text(encoding=encoding)
        except FileNotFoundError:
            code_chunk.errors.append(message.SourceError('Cannot include nonexistent file "{0}"'.format(file)))
        except PermissionError:
            code_chunk.errors.append(message.SourceError('Insufficient permissions to access file "{0}"'.format(file)))
        except LookupError:
            code_chunk.errors.append(message.SourceError('Unknown encoding "{0}"'.format(encoding)))
        except UnicodeDecodeError:
            code_chunk.errors.append(message.SourceError('Cannot decode file "{0}" with encoding "{1}"'.format(file, encoding)))
        if code_chunk.errors:
            return

        selection_keywords = start_keywords + end_keywords + range_keywords
        if selection_keywords:
            for kw in selection_keywords:
                text = getattr(self, '_option_'+kw)(include_options[kw], text)
                if code_chunk.errors:
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
            self.code_chunk.errors.append(message.SourceError('Invalid value for "include" option "lines"'))
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
            self.code_chunk.errors.append(message.SourceError('Invalid regex pattern for "include" option "regex"'))
            return
        match = pattern_re.search(text)
        if match is None:
            self.code_chunk.errors.append(message.SourceError('The pattern given by "include" option "regex" was not found'))
            return
        return match.group()


    def _option_start_string(self, value, text):
        index = text.find(value)
        if index < 0:
            self.code_chunk.errors.append(message.SourceError('The pattern given by "include" option "start_string" was not found'))
            return
        return text[index:]


    def _option_start_regex(self, value, text):
        try:
            pattern_re = re.compile(value, re.MULTILINE | re.DOTALL)
        except re.error:
            self.code_chunk.errors.append(message.SourceError('Invalid regex pattern for "include" option "start_regex"'))
            return
        match = pattern_re.search(text)
        if match is None:
            self.code_chunk.errors.append(message.SourceError('The pattern given by "include" option "start_regex" was not found'))
            return
        return text[match.start():]


    def _option_after_string(self, value, text):
        index = text.find(value)
        if index < 0:
            self.code_chunk.errors.append(message.SourceError('The pattern given by "include" option "after_string" was not found'))
            return
        return text[index+len(value):]


    def _option_after_regex(self, value, text):
        try:
            pattern_re = re.compile(value, re.MULTILINE | re.DOTALL)
        except re.error:
            self.code_chunk.errors.append(message.SourceError('Invalid regex pattern for "include" option "after_regex"'))
            return
        match = pattern_re.search(text)
        if match is None:
            self.code_chunk.errors.append(message.SourceError('The pattern given by "include" option "after_regex" was not found'))
            return
        return text[match.end():]


    def _option_before_string(self, value, text):
        index = text.find(value)
        if index < 0:
            self.code_chunk.errors.append(message.SourceError('The pattern given by "include" option "before_string" was not found'))
            return
        return text[:index]


    def _option_before_regex(self, value, text):
        try:
            pattern_re = re.compile(value, re.MULTILINE | re.DOTALL)
        except re.error:
            self.code_chunk.errors.append(message.SourceError('Invalid regex pattern for "include" option "before_regex"'))
            return
        match = pattern_re.search(text)
        if match is None:
            self.code_chunk.errors.append(message.SourceError('The pattern given by "include" option "before_regex" was not found'))
            return
        return text[:match.start()]


    def _option_end_string(self, value, text):
        index = text.find(value)
        if index < 0:
            self.code_chunk.errors.append(message.SourceError('The pattern given by "include" option "end_string" was not found'))
            return
        return text[:index+len(value)]


    def _option_end_regex(self, value, text):
        try:
            pattern_re = re.compile(value, re.MULTILINE | re.DOTALL)
        except re.error:
            self.code_chunk.errors.append(message.SourceError('Invalid regex pattern for "include" option "end_regex"'))
            return
        match = pattern_re.search(text)
        if match is None:
            self.code_chunk.errors.append(message.SourceError('The pattern given by "include" option "end_regex" was not found'))
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

    Invalid options related to presentation produce errors that do not prevent
    code execution.  Otherwise, errors prevent execution.  When possible,
    option processing proceeds even after an error, to give a more complete
    error message.
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
            code_chunk.errors.append(message.SourceError('Unknown keywords: {0}'.format(unknown_keys)))
            # Treat received `custom_options` as immutable
            custom_options = {k: v for k, v in custom_options.items() if k in self.keywords}
        self.custom_options = custom_options

        for k, v in custom_options.items():
            if k not in self._after_copy_keywords:
                getattr(self, '_option_'+k)(k, v)

        if not code_chunk.errors and 'copy' not in self:
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


    def finalize_after_copy(self):
        '''
        Complete any option processing that must wait until after copying.
        For the paste command, 'show' can be inherited.  For paste and code,
        `.is_expr` can be inherited.  'lang' can also be inherited.
        '''
        code_chunk = self.code_chunk
        custom_options = self.custom_options
        if self['lang'] is None:
            self['inherited_lang'] = True
            self['lang'] = code_chunk.copy_chunks[0].options['lang']
        if code_chunk.inline:
            if code_chunk.command == 'paste' and 'show' not in custom_options:
                self['show'] = code_chunk.copy_chunks[0].options['show'].copy()  # Inherit
            else:
                self['show'] = self._default_inline_show[code_chunk.command].copy()
        else:
            if code_chunk.command == 'paste' and 'show' not in custom_options:
                self['show'] = code_chunk.copy_chunks[0].options['show'].copy()  # Inherit
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
    _first_chunk_other_keywords = set(['executable_opts', 'args', 'jupyter_timeout', 'live_output'])
    _first_chunk_keywords = _first_chunk_execute_keywords | _first_chunk_save_keywords | _first_chunk_other_keywords

    keywords = _base_keywords | _layout_keywords | _first_chunk_keywords

    _after_copy_keywords = set(['hide', 'show'])


    # Default values for show and session/source are inserted later based on
    # command and inline status
    _default_inline_options = {'complete': True,
                               'example': False,
                               'lang': None,
                               'inherited_lang': False,
                               'outside_main': False}
    _default_block_options = _default_inline_options.copy()
    _default_block_options.update({'code_first_number': 'next',
                                   'code_line_numbers': True})

    # The defaultdict handles unknown commands that are represented as None
    _default_rich_output = 'latex|markdown|png|jpg|plain'.split('|')
    _default_inline_show = collections.defaultdict(lambda: ODict(),  # Unknown -> show nothing
                                                   {'code':  ODict([('code', 'verbatim')]),
                                                    'expr':  ODict([('expr', 'raw'),
                                                                    ('stderr', 'verbatim')]),
                                                    # expr and rich_output don't clash, because expr is only present
                                                    # with the built-in code execution system, while rich_output
                                                    # requires a Jupyter kernel.  If the built-in system gains
                                                    # rich_output capabilities or there are other related changes,
                                                    # this may need refactoring.
                                                    'nb':    ODict([('expr', 'verbatim'),
                                                                    ('rich_output', _default_rich_output),
                                                                    ('stderr', 'verbatim')]),
                                                    'paste': ODict(),
                                                    'run':   ODict([('stdout', 'raw'),
                                                                    ('stderr', 'verbatim'),
                                                                    ('rich_output', _default_rich_output)])})
    _default_block_show = collections.defaultdict(lambda: ODict(),  # Unknown -> show nothing
                                                  {'code': ODict([('code', 'verbatim')]),
                                                   'nb':   ODict([('code', 'verbatim'),
                                                                  ('stdout', 'verbatim'),
                                                                  ('stderr', 'verbatim'),
                                                                  ('rich_output', _default_rich_output)]),
                                                   'paste': ODict(),
                                                   'repl': ODict([('repl', 'verbatim')]),
                                                   'run':  ODict([('stdout', 'raw'),
                                                                  ('stderr', 'verbatim'),
                                                                  ('rich_output', _default_rich_output)])})


    def _option_bool_can_exec_error(self, key, value):
        if not isinstance(value, bool):
            self.code_chunk.errors.append(message.CanExecSourceError(f'Invalid "{key}" value "{value}"'))
        else:
            self[key] = value

    def _option_bool_error(self, key, value):
        if not isinstance(value, bool):
            self.code_chunk.errors.append(message.SourceError(f'Invalid "{key}" value "{value}"'))
        else:
            self[key] = value

    def _option_str_can_exec_error(self, key, value):
        if not isinstance(value, str):
            self.code_chunk.errors.append(message.CanExecSourceError(f'Invalid "{key}" value "{value}"'))
        else:
            self[key] = value

    def _option_str_error(self, key, value):
        if not isinstance(value, str):
            self.code_chunk.errors.append(message.SourceError(f'Invalid "{key}" value "{value}"'))
        else:
            self[key] = value

    def _option_positive_int_can_exec_error(self, key, value):
        if not isinstance(value, int) or value <= 0:
            self.code_chunk.errors.append(message.CanExecSourceError(f'Invalid "{key}" value "{value}"'))
        else:
            self[key] = value

    def _option_positive_int_error(self, key, value):
        if not isinstance(value, int) or value <= 0:
            self.code_chunk.errors.append(message.SourceError(f'Invalid "{key}" value "{value}"'))
        else:
            self[key] = value

    def _option_first_chunk_bool_error(self, key, value):
        if not isinstance(value, bool):
            self.code_chunk.errors.append(message.SourceError(f'Invalid "{key}" value "{value}"'))
        else:
            self['first_chunk_options'][key] = value

    def _option_first_chunk_string_error(self, key, value):
        if not isinstance(value, str):
            self.code_chunk.errors.append(message.SourceError(f'Invalid "{key}" value "{value}"'))
        else:
            first_chunk_options = self['first_chunk_options']
            if (key in self._first_chunk_execute_keywords and
                    any(k in first_chunk_options for k in self._first_chunk_execute_keywords)):
                conflicting_options = ', '.join('"{0}"'.format(k) for k in self._first_chunk_execute_keywords if k in first_chunk_options)
                self.code_chunk.errors.append(message.SourceError('Conflicting options: {0}'.format(conflicting_options)))
            else:
                first_chunk_options[key] = value

    def _option_first_chunk_int_error(self, key, value):
        if not isinstance(value, int):
            self.code_chunk.errors.append(message.SourceError(f'Invalid "{key}" value "{value}"'))
        else:
            self['first_chunk_options'][key] = value

    _option_executable = _option_first_chunk_string_error
    _option_executable_opts = _option_first_chunk_string_error
    _option_args = _option_first_chunk_string_error
    _option_jupyter_kernel = _option_first_chunk_string_error
    _option_jupyter_timeout = _option_first_chunk_int_error
    _option_save = _option_first_chunk_bool_error
    _option_save_as = _option_first_chunk_string_error
    _option_live_output = _option_first_chunk_bool_error

    _option_example = _option_bool_can_exec_error
    _option_lang = _option_str_error


    def _option_complete(self, key, value):
        if not isinstance(value, bool):
            self.code_chunk.errors.append(message.SourceError(f'Invalid "{key}" value "{value}"'))
        elif not self.code_chunk.execute:
            self.code_chunk.errors.append(message.SourceError('Option "complete" is only compatible with executed code chunks'))
        elif self.code_chunk.command == 'repl':
            self.code_chunk.errors.append(message.SourceError('Option "complete" is not compatible with "repl" command'))
        elif self.code_chunk.is_expr and not value:
            self.code_chunk.errors.append(message.SourceError('Option "complete" value "false" is incompatible with expr command'))
        elif self['outside_main']:
            # Technically, this is only required for complete=true, but
            # prohibiting it in all cases is more consistent
            self.code_chunk.errors.append(message.SourceError('Option "complete" is incompatible with "outside_main" value "true"'))
        else:
            self[key] = value


    def _option_copy(self, key, value):
        if not isinstance(value, str):
            self.code_chunk.errors.append(message.SourceError(f'Invalid "{key}" value "{value}"'))
        elif 'include' in self:
            self.code_chunk.errors.append(message.SourceError('Option "copy" is incompatible with "include"'))
        else:
            values = [x.strip() for x in value.split('+')]
            if not all(v.isidentifier() for v in values):
                invalid_values = ', '.join(f'"{v}"' for v in values if not v.isidentifier())
                self.code_chunk.errors.append(message.SourceError(f'Option "{key}" has invalid, non-identifier value(s) {invalid_values}'))
            elif self.get('name') in values:
                self.code_chunk.errors.append(message.SourceError('Code chunk cannot copy itself'))
            else:
                self[key] = values


    def _option_expand_tabs(self, key, value):
        if key == 'expand_tabs':
            key = 'code_expand_tabs'
        self._option_bool_can_exec_error(key, value)

    _option_markup_expand_tabs = _option_expand_tabs
    _option_copied_markup_expand_tabs = _option_expand_tabs
    _option_code_expand_tabs = _option_expand_tabs
    _option_stdout_expand_tabs = _option_expand_tabs
    _option_stderr_expand_tabs = _option_expand_tabs


    def _option_first_number(self, key, value):
        if not ((isinstance(value, int) and value > 0) or (isinstance(value, str) and value == 'next')):
            self.code_chunk.errors.append(message.CanExecSourceError(f'Invalid "{key}" value "{value}"'))
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
        self._option_bool_can_exec_error(key, value)

    _option_markup_rewrap_lines = _option_rewrap_lines
    _option_copied_markup_rewrap_lines = _option_rewrap_lines
    _option_code_rewrap_lines = _option_rewrap_lines
    _option_stdout_rewrap_lines = _option_rewrap_lines
    _option_stderr_rewrap_lines = _option_rewrap_lines


    def _option_rewrap_width(self, key, value):
        if key == 'rewrap_width':
            key = 'code_rewrap_width'
        self._option_positive_int_can_exec_error(key, value)

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
            self.code_chunk.errors.append(message.CanExecSourceError(f'Invalid "{key}" value "{value}"'))
        elif 'show' in self.custom_options:
            # 'hide' checks for 'show' conflict, so 'show' does not.  Check
            # in `custom_options` since there's a default 'show' in `self`.
            self.code_chunk.errors.append(message.CanExecSourceError('Option "hide" cannot be used with "show"'))
        elif value == 'all':
            self['show'] = ODict()
        else:
            hide_values = value.replace(' ', '').split('+')
            if not all(v in display_values for v in hide_values):
                self.code_chunk.errors.append(message.CanExecSourceError(f'Invalid "{key}" value "{value}"'))
            else:
                for v in hide_values:
                    self['show'].pop(v, None)


    def _option_hide_markup_keys(self, key, value):
        if not isinstance(value, str):
            self.code_chunk.errors.append(message.CanExecSourceError(f'Invalid "{key}" value "{value}"'))
        else:
            # No need to check keys for validity; this is a display option.
            hide_keys = set(value.replace(' ', '').split('+'))
            hide_keys.add('hide_markup_keys')
            self[key] = hide_keys


    def _option_include(self, key, value):
        # Include() does its own value check, so this isn't technically needed
        if not isinstance(value, dict):
            self.code_chunk.errors.append(message.SourceError(f'Invalid "{key}" value "{value}"'))
        elif 'copy' in self:
            self.code_chunk.errors.append(message.SourceError('Option "include" is incompatible with "copy"'))
        else:
            include = Include(self.code_chunk, value)
            if include.code_lines:
                self[key] = include


    def _option_line_numbers(self, key, value):
        if not isinstance(value, bool):
            self.code_chunk.errors.append(message.CanExecSourceError(f'Invalid "{key}" value "{value}"'))
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
            self.code_chunk.errors.append(message.CanExecSourceError(f'Invalid "{key}" value "{value}"'))
        elif not value.isidentifier():
            self.code_chunk.errors.append(message.CanExecSourceError('Option "{0}" has invalid, non-identifier value "{1}"'.format(key, value)))
        elif 'copy' in self and key in self['copy']:
            self.code_chunk.errors.append(message.SourceError('Code chunk cannot copy itself'))
        else:
            self[key] = value


    def _option_outside_main(self, key, value):
        if not isinstance(value, bool):
            self.code_chunk.errors.append(message.SourceError(f'Invalid "{key}" value "{value}"'))
        elif not self.code_chunk.execute:
            self.code_chunk.errors.append(message.SourceError('Option "outside_main" is only compatible with executed code chunks'))
        elif self.code_chunk.command == 'repl':
            self.code_chunk.errors.append(message.SourceError('Option "outside_main" is not compatible with "repl" command'))
        elif self.code_chunk.is_expr and value:
            self.code_chunk.errors.append(message.SourceError('Option "outside_main" value "true" is incompatible with expr command'))
        elif value and 'complete' in self.custom_options:
            self.code_chunk.errors.append(message.SourceError('Option "outside_main" value "true" is incompatible with "complete"'))
        else:
            self['complete'] = None
            self[key] = value


    def _option_source(self, key, value):
        if not isinstance(value, str):
            self.code_chunk.errors.append(message.SourceError(f'Invalid "{key}" value "{value}"'))
        elif self.code_chunk.execute and self.code_chunk.command is not None:
            # Always preserve sources for unknown commands, so that these
            # sources can be marked as having potential errors later
            self.code_chunk.errors.append(message.SourceError('Option "source" is only compatible with non-executed code chunks; otherwise, use "session"'))
        elif not value.isidentifier():
            self.code_chunk.errors.append(message.SourceError('Option "{0}" has invalid, non-identifier value "{1}"'.format(key, value)))
        else:
            self[key] = value


    def _option_session(self, key, value):
        if not isinstance(value, str):
            self.code_chunk.errors.append(message.SourceError(f'Invalid "{key}" value "{value}"'))
        elif not self.code_chunk.execute and self.code_chunk.command is not None:
            # Always preserve sessions for unknown commands, so that these
            # sessions can be marked as having potential errors later
            self.code_chunk.errors.append(message.SourceError('Option "session" is only compatible with executed code chunks; otherwise, use "source"'))
        elif not value.isidentifier():
            self.code_chunk.errors.append(message.SourceError('Option "{0}" has invalid, non-identifier value "{1}"'.format(key, value)))
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

    mime_map_with_text_display = {}
    rich_text_default_display = {}
    for k, v in mime_map.items():
        mime_map_with_text_display[k] = v
        if v.startswith('text/'):
            mime_map_with_text_display[k+':raw'] = v
            mime_map_with_text_display[k+':verbatim'] = v
            mime_map_with_text_display[k+':verbatim_or_empty'] = v
            if k == 'plain':
                rich_text_default_display[k] = 'verbatim'
            else:
                rich_text_default_display[k] = 'raw'


    def _option_show(self, key, value):
        # 'show' may be processed during `finalize_after_copy()` to allow for
        # 'show' and `.is_expr` inheritance.  'hide' checks for 'show'
        # conflict, so 'show' does not.
        if not (isinstance(value, str) or value is None):
            self.code_chunk.errors.append(message.CanExecSourceError(f'Invalid "{key}" value "{value}"'))
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
                    self.code_chunk.errors.append(message.CanExecSourceError('Option "{0}" value "{1}" contains duplicate "{2}"'.format(key, value, output)))
                    continue
                if output in ('markup', 'copied_markup', 'code', 'repl'):
                    if format is None:
                        format = 'verbatim'
                    elif format != 'verbatim':
                        self.code_chunk.errors.append(message.CanExecSourceError('Invalid "{0}" sub-value "{1}"'.format(key, output_and_format)))
                        continue
                    if output == 'copied_markup' and 'copy' not in self.custom_options:
                        self.code_chunk.errors.append(message.CanExecSourceError('Invalid "{0}" sub-value "{1}"; can only be used with "copy"'.format(key, output_and_format)))
                        continue
                elif output in ('stdout', 'stderr'):
                    if format is None:
                        format = 'verbatim'
                    elif format not in ('verbatim', 'verbatim_or_empty', 'raw'):
                        self.code_chunk.errors.append(message.CanExecSourceError('Invalid "{0}" sub-value "{1}"'.format(key, output_and_format)))
                        continue
                elif output == 'expr':
                    if not self.code_chunk.is_expr:
                        self.code_chunk.errors.append(message.CanExecSourceError('Invalid "{0}" sub-value "{1}"'.format(key, output_and_format)))
                        continue
                    if format is None:
                        format = 'raw'
                    elif format not in ('verbatim', 'verbatim_or_empty', 'raw'):
                        self.code_chunk.errors.append(message.CanExecSourceError('Invalid "{0}" sub-value "{1}"'.format(key, output_and_format)))
                        continue
                elif output == 'rich_output':
                    if format is None:
                        format = self._default_rich_output
                    else:
                        format = format.split('|')
                        if not all(fmt in self.mime_map_with_text_display for fmt in format):
                            self.code_chunk.errors.append(message.CanExecSourceError('Invalid "{0}" sub-value "{1}"'.format(key, output_and_format)))
                            continue
                else:
                    self.code_chunk.errors.append(message.CanExecSourceError('Invalid "{0}" sub-value "{1}"'.format(key, output_and_format)))
                    continue
                value_processed[output] = format
            self[key] = value_processed


    def _option_tab_size(self, key, value):
        if key == 'tab_size':
            key = 'code_tab_size'
        self._option_positive_int_can_exec_error(key, value)

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
                 *,
                 origin_name: Optional[str]=None,
                 origin_start_line_number: Optional[int]=None,
                 inline: Optional[bool]=None):
        self.errors: message.ErrorMessageList
        self.warnings: message.WarningMessageList
        self.__pre_init__()

        self.key: Optional[CodeKey]  # Set during session/source creation

        if command not in self.commands:
            if command is None:
                self.errors.append(message.SourceError('Missing valid Codebraid command'))
            else:
                self.errors.append(message.SourceError('Unknown Codebraid command "{0}"'.format(command)))
            self.command = None
        else:
            self.command = command
        if command == 'expr' and not inline:
            self.errors.append(message.SourceError('Codebraid command "{0}" is only allowed inline'.format(command)))
        if command == 'repl' and inline:
            self.errors.append(message.SourceError('Codebraid command "{0}" is not supported inline'.format(command)))
        self.execute = self._default_execute[command]
        if command == 'expr' or (inline and command == 'nb'):
            self.is_expr = True
        else:
            # For the paste command, or code with 'copy', this value can
            # change later due to inheritance
            self.is_expr = False
        self.origin_name = origin_name
        self.origin_start_line_number = origin_start_line_number
        self.inline = inline

        # Check for len(code_lines) > 1 for inline later
        self._code_str = None
        if isinstance(code, list):
            code_lines = code
        else:
            code_lines = util.splitlines_lf(code) or ['']
        if 'copy' not in custom_options and 'include' not in custom_options:
            if inline and len(code_lines) > 1:
                self.errors.append(message.SourceError('Inline code cannot be longer that 1 line'))
            self.code_lines = code_lines
            self.placeholder_code_lines = []
        else:
            if inline:
                if len(code_lines) > 1 or code_lines[0] not in ('', ' ', '_'):
                    self.errors.append(message.SourceError('Invalid placeholder code for copy or include (need space or underscore)'))
            elif len(code_lines) > 1 or code_lines[0].rstrip(' ') not in ('', '_'):
                self.errors.append(message.SourceError('Invalid placeholder code for copy or include (need empty, space, or underscore)'))
            # Copying or including code could result in more than one line of
            # code in an inline context.  That is only an issue if the code is
            # actually displayed.  This is checked later when code is
            # included/copied.
            self.placeholder_code_lines = code_lines
            self.code_lines = []

        self.options = Options(self, custom_options)

        if 'include' in self.options and not self.errors:
            # Copy over include only if no source errors -- otherwise it isn't
            # used and 'show' may not exist
            include = self.options['include']
            if inline and 'code' in self.options['show'] and len(include.code_lines) > 1:
                self.errors.append(message.SourceError('Cannot include and then display multiple lines of code in an inline context'))
            else:
                self.code_lines = include.code_lines

        if command == 'paste':
            if 'copy' not in custom_options:
                self.errors.append(message.SourceError('Command "paste" cannot be used without specifying a target via "copy"'))
            self.needs_to_copy = True
        else:
            self.needs_to_copy = False
        if 'copy' in self.options:
            self.copy_chunks = []

        self.code_collection: Optional[CodeCollection] = None
        self.index: Optional[int] = None
        self.output_index = None
        self.stdout_lines = []
        self.stderr_lines = []
        self.repl_lines = []
        self.rich_output = None
        self.expr_lines = []
        self.markup_start_line_number = 1
        self.code_start_line_number = 1
        self.stdout_start_line_number = 1
        self.stderr_start_line_number = 1

    @property
    def session(self):
        if self.execute:
            return self.code_collection
        raise TypeError

    @property
    def source(self):
        if not self.execute:
            return self.code_collection
        raise TypeError


    def __pre_init__(self):
        '''
        Create lists of errors and warnings.  Subclasses may need to record
        errors or warnings during preprocessing, before they are ready
        to call `super().__init__()`
        '''
        if not hasattr(self, 'errors'):
            self.errors = message.ErrorMessageList()
        elif not isinstance(self.errors, message.ErrorMessageList):
            raise TypeError
        if not hasattr(self, 'warnings'):
            self.warnings = message.WarningMessageList()
        elif not isinstance(self.warnings, message.WarningMessageList):
            raise TypeError


    commands = set(['code', 'expr', 'nb', 'paste', 'repl', 'run'])

    _default_execute = collections.defaultdict(lambda: False,  # Unknown command -> do not run
                                               {k: True for k in ('expr', 'nb', 'repl', 'run')})


    @property
    def code_str(self):
        code_str = self._code_str
        if code_str is not None:
            return code_str
        code = '\n'.join(self.code_lines)
        self._code_str = code
        return code


    @property
    def attr_hash(self):
        raise NotImplementedError

    @property
    def code_hash(self):
        raise NotImplementedError

    def only_code_output(self, format):
        raise NotImplementedError


    def finalize_after_copy(self):
        '''
        Finalize options.  This can be redefined by subclasses so that they
        can modify themselves based on inherited 'lang' or 'show'.
        '''
        self.options.finalize_after_copy()


    def copy_code(self):
        '''
        Copy code for 'copy' option.  Code is copied before execution, which
        is more flexible.  Output (stdout, stderr, expr, etc.) must be copied
        separately after execution.

        This should only be invoked for a code chunk with no errors that would
        prevent execution, with copy targets that all exist and have no errors
        that would prevent execution.
        '''
        copy_chunks = self.copy_chunks
        if any(cc.is_expr for cc in copy_chunks):
            if len(copy_chunks) > 1:
                invalid_cc_names = ', '.join(cc.options['name'] for cc in copy_chunks if cc.is_expr)
                self.errors.append(message.SourceError('Cannot copy multiple code chunks when some are expressions: {0}'.format(invalid_cc_names)))
            if self.command in ('paste', 'code'):
                # Some commands inherit expression status.  The code command
                # inherits so that subsequent copying doesn't result in
                # incorrectly concatenated expressions.  Since the code
                # command never has output, this has no display side effects.
                self.is_expr = True
                self.expr_lines = []
            elif not self.is_expr:
                self.errors.append(message.SourceError('A non-expression command cannot copy an expression code chunk'))
        elif self.is_expr:
            self.errors.append(message.SourceError('An expression command cannot copy a non-expression code chunk'))
        if self.errors:
            return
        # Finalization must come after any potential `.is_expr` modifications
        self.finalize_after_copy()
        if self.inline and 'code' in self.options['show'] and (len(copy_chunks) > 1 or len(copy_chunks[0].code_lines) > 1):
            self.errors.append(message.SourceError('Cannot copy and then display multiple lines of code in an inline context'))
            return
        if len(copy_chunks) == 1:
            self.code_lines = copy_chunks[0].code_lines
        else:
            self.code_lines = [line for x in copy_chunks for line in x.code_lines]
        if self.command == 'paste':
            if all(cc.command == 'code' for cc in copy_chunks):
                # When possible, simplify the copying resolution process
                self.needs_to_copy = False
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
                    self.errors.append(message.SourceError('Can only copy a single paste code chunk; cannot combine multiple paste chunks'))
                else:
                    self.errors.append(message.SourceError('Cannot copy a mixture of paste and other code chunks'))
        elif any(cc.execute for cc in copy_chunks):
            if not all(cc.execute for cc in copy_chunks):
                self.errors.append(message.SourceError('Copying output of multiple code chunks requires that all or none are executed'))
            elif len(copy_chunks) > 1:
                if len(set(cc.session for cc in copy_chunks)) > 1:
                    self.errors.append(message.SourceError('Cannot copy output from code chunks in multiple sessions'))
                elif any(ccx.index != ccy.index-1 for ccx, ccy in zip(copy_chunks[:-1], copy_chunks[1:])):
                    if any(ccx is ccy for ccx, ccy in zip(copy_chunks[:-1], copy_chunks[1:])):
                        self.errors.append(message.SourceError('Cannot copy output of a single code chunk multiple times'))
                    elif any(ccx.index > ccy.index for ccx, ccy in zip(copy_chunks[:-1], copy_chunks[1:])):
                        self.errors.append(message.SourceError('Cannot copy output of code chunks out of order'))
                    else:
                        self.errors.append(message.SourceError('Cannot copy output of code chunks when some chunks in a sequence are omitted'))
        else:
            raise ValueError
        if self.errors:
            # If errors, discard what has already been copied
            self.code_lines = []
            return
        if len(copy_chunks) == 1:
            self.stdout_lines = copy_chunks[0].stdout_lines
            self.stderr_lines = copy_chunks[0].stderr_lines
            self.repl_lines = copy_chunks[0].repl_lines
            self.rich_output = copy_chunks[0].rich_output
        else:
            self.stdout_lines = [line for x in copy_chunks if x.stdout_lines for line in x.stdout_lines]
            self.stderr_lines = [line for x in copy_chunks if x.stderr_lines for line in x.stderr_lines]
            self.repl_lines = [line for x in copy_chunks if x.repl_lines for line in x.repl_lines]
            self.rich_output = [ro for x in copy_chunks if x.rich_output for ro in x.rich_output]
        if self.is_expr:
            # expr compatibility has already been checked in `copy_code()`
            self.expr_lines = copy_chunks[0].expr_lines
        self.stdout_start_line_number = copy_chunks[0].stdout_start_line_number
        self.stderr_start_line_number = copy_chunks[0].stderr_start_line_number
        self.needs_to_copy = False


    @property
    def as_markup_lines(self):
        raise NotImplementedError

    @property
    def as_example_markup_lines(self):
        raise NotImplementedError

    def layout_output(self, output_type, output_format, lines=None):
        '''
        Layout all forms of output, except for rich output that is not
        text/plain, by performing operations such as line rewrapping and tab
        expansion.  If `lines` is supplied, it is used.  Otherwise, the
        default lines (if any) are accessed for the specified output type.
        '''
        if lines is not None:
            if not lines and output_format == 'verbatim_or_empty':
                lines = ['\xa0']
            pass
        elif output_type == 'code':
            lines = self.code_lines
        elif output_type == 'repl':
            lines = self.repl_lines
        elif output_type in ('expr', 'stdout', 'stderr'):
            lines = getattr(self, output_type+'_lines')
            if not lines and output_format == 'verbatim_or_empty':
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
