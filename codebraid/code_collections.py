# -*- coding: utf-8 -*-
#
# Copyright (c) 2021-2022, Geoffrey M. Poore
# All rights reserved.
#
# Licensed under the BSD 3-Clause License:
# http://opensource.org/licenses/BSD-3-Clause
#


from __future__ import annotations


import hashlib
import json
import pathlib
import shlex
from typing import Dict, List, NamedTuple, Optional, Union
from . import language
from . import message
from .code_chunks import CodeChunk, CodeKey




class CodeLineOrigin(NamedTuple):
    '''
    Track origin of line of code with code chuck and (user code) line number.
    This is mainly for synchronizing error and warning messages for code that
    is executed.
    '''
    chunk: Optional[CodeChunk]
    line_number: int




class CodeCollection(object):
    '''
    Base class for sessions and sources.  Never instantiated.
    '''
    def __init__(self, code_key: CodeKey, *, code_defaults: Optional[Dict[str, Union[bool, str]]]):
        if type(self) is CodeCollection:
            raise NotImplementedError
        self.key: CodeKey = code_key
        self.lang: Optional[str] = code_key.lang
        self.name: Optional[str] = code_key.name
        self.origin_name: Optional[str] = code_key.origin_name

        self.code_chunks: List[CodeChunk] = []
        self._code_start_line_number: int = 1
        self.code_chunk_origins: set[str] = set()
        self.code_chunk_placeholder_langs = set()

        self.status: message.CodeStatus = message.CodeStatus()
        self.errors: message.ErrorMessageList = message.ErrorMessageList(status=self.status)
        self.warnings: message.WarningMessageList = message.WarningMessageList(status=self.status)
        self.files: List[str] = []

        if code_defaults is not None:
            for k, v in code_defaults.items():
                if hasattr(self, k):
                    setattr(self, k, v)
                elif k not in self._optional_attrs:
                    raise AttributeError

    type: str = 'code'
    _optional_attrs = set(['live_output'])




class Source(CodeCollection):
    '''
    An ordered collection of code chunks that is typically displayed but never
    executed.  May be exported as a single file of source code.
    '''
    def __init__(self, code_key: CodeKey, *,
                 code_defaults: Optional[Dict[str, Union[bool, str]]]=None,
                 source_defaults: Optional[Dict[str, Union[bool, str]]]=None):
        super().__init__(code_key, code_defaults=code_defaults)
        if source_defaults is not None:
            for k, v in source_defaults.items():
                if hasattr(self, k):
                    setattr(self, k, v)
                else:
                    raise AttributeError

    type: str = 'source'


    def append(self, code_chunk: CodeChunk):
        '''
        Append a code chunk to internal code chunk list.  Check code chunk
        options for validity and update chunk summary data.
        '''
        code_chunk.code_collection = self
        code_chunk.index = len(self.code_chunks)
        code_chunk.errors.register_status(self.status)
        code_chunk.warnings.register_status(self.status)
        first_chunk_options = code_chunk.options['first_chunk_options']
        if first_chunk_options:
            invalid_options = ', '.join(f'"{k}"' for k in first_chunk_options)
            first_chunk_options.clear()
            msg = f'Some options are only valid for a session, not for a source: {invalid_options}'
            code_chunk.errors.append(message.SourceError(msg))
        self.code_chunks.append(code_chunk)
        self.code_chunk_origins.add(code_chunk.origin_name)
        if 'placeholder_lang' in code_chunk.options:
            self.code_chunk_placeholder_langs.add(code_chunk.options['placeholder_lang'])


    def finalize(self):
        '''
        Perform tasks that must wait until all code chunks are present.
        '''
        for cc in self.code_chunks:
            if not cc.inline:
                cc.finalize_line_numbers(self._code_start_line_number)
                # Only named sources have sequential line numbering between
                # code chunks
                if self.name is not None:
                    self._code_start_line_number += len(cc.code_lines)




class Session(CodeCollection):
    '''
    Code chunks comprising a session.
    '''
    def __init__(self, code_key: CodeKey, *,
                 code_defaults: Optional[Dict[str, Union[bool, str]]]=None,
                 session_defaults: Optional[Dict[str, Union[bool, str]]]=None):
        super().__init__(code_key, code_defaults=code_defaults)

        self.lang_def: Optional[language.Language] = None
        self.executable: Optional[str] = None
        self.executable_opts: Optional[list[str]] = None
        self.args: Optional[list[str]] = None
        self.live_output: Optional[bool] = None
        self.repl: Optional[bool] = None
        self.jupyter_kernel: Optional[str] = None
        self.jupyter_timeout: Optional[int] = None

        if session_defaults is not None:
            for k, v in session_defaults.items():
                if hasattr(self, k):
                    setattr(self, k, v)
                else:
                    raise AttributeError

        self.needs_exec: bool = True
        self.did_exec: bool = False
        self.is_finalized: bool = False

        self.decode_error_count: int = 0
        self.max_tracked_decode_error_count: int = 10

        # Output that isn't directly associated with individual code chunks.
        # This can come from the start or end of the run code template, or
        # from other sources like Python syntax errors that are generated
        # before code ever runs or compilation output from Rust.
        self.compile_lines: list[str] = []
        self.pre_run_output_lines: list[str] = []
        self.template_start_stdout_lines: list[str] = []
        self.template_start_stderr_lines: list[str] = []
        self.template_end_stdout_lines: list[str] = []
        self.template_end_stderr_lines: list[str] = []
        self.other_stdout_lines: list[str] = []
        self.other_stderr_lines: list[str] = []
        self.post_run_output_lines: list[str] = []

        self._run_code: Optional[str] = None
        self.run_delim_start: str = '#Codebraid'
        self.run_delim_start_search_pattern: str= f'{self.run_delim_start}('
        self.run_code_to_origins: Optional[dict[int, CodeLineOrigin]] = None
        self.expected_stdout_start_delim_chunks: Optional[dict[int, int]] = None
        self.expected_stderr_start_delim_chunks: Optional[dict[int, int]] = None
        self.expected_stdout_end_delim_chunks: Optional[dict[int, int]] = None
        self.expected_stderr_end_delim_chunks: Optional[dict[int, int]] = None

    type: str = 'session'

    _default_jupyter_timeout = 60


    def append(self, code_chunk: CodeChunk):
        '''
        Append a code chunk to internal code chunk list.  Check code chunk
        options for validity and update chunk summary data.
        '''
        code_chunk.code_collection = self
        code_chunk.index = len(self.code_chunks)
        code_chunk.errors.register_status(self.status)
        code_chunk.warnings.register_status(self.status)
        first_chunk_options = code_chunk.options['first_chunk_options']
        if code_chunk.index == 0:
            jupyter_kernel = first_chunk_options.get('jupyter_kernel')
            if jupyter_kernel is not None:
                self.repl = False
                self.jupyter_kernel = jupyter_kernel
                self.jupyter_timeout = first_chunk_options.get('jupyter_timeout', self._default_jupyter_timeout)
            else:
                self.lang_def = language.languages[self.lang]
                if self.lang_def is None:
                    msg = f'Language definition for "{self.lang}" does not exist'
                    self.errors.append(message.SysConfigError(msg))
                else:
                    try:
                        raw_executable = first_chunk_options['executable']
                    except KeyError:
                        executable = self.lang_def.executable
                    else:
                        executable = pathlib.Path(raw_executable).expanduser().as_posix()
                        if raw_executable.startswith('./') or raw_executable.startswith('.\\'):
                            executable = f'./{executable}'
                    self.executable = executable
                    try:
                        raw_executable_opts = first_chunk_options['executable_opts']
                    except KeyError:
                        executable_opts = self.lang_def.executable_opts
                    else:
                        executable_opts = shlex.split(raw_executable_opts)
                    self.executable_opts = executable_opts
                    try:
                        raw_args = first_chunk_options['args']
                    except KeyError:
                        args = self.lang_def.args
                    else:
                        args = shlex.split(raw_args)
                    self.args = args
                    self.repl = self.lang_def.repl
            live_output = first_chunk_options.get('live_output')
            if live_output is not None:
                self.live_output = live_output
        elif first_chunk_options:
            invalid_options = ', '.join(f'"{k}"' for k in first_chunk_options)
            first_chunk_options.clear()
            msg = f'Some options are only valid for the first code chunk in a session: {invalid_options}'
            code_chunk.errors.append(message.SourceError(msg))
        self.code_chunks.append(code_chunk)
        self.code_chunk_origins.add(code_chunk.origin_name)
        if 'placeholder_lang' in code_chunk.options:
            self.code_chunk_placeholder_langs.add(code_chunk.options['placeholder_lang'])


    def finalize(self):
        '''
        Perform tasks that must wait until all code chunks are present,
        such as hashing.
        '''
        if self.code_chunks[0].options['outside_main']:
            from_outside_main_switches = 0
        else:
            from_outside_main_switches = 1
        to_outside_main_switches = 0
        incomplete_ccs = []
        last_cc = None
        for cc in self.code_chunks:
            if self.repl and cc.command != 'repl':
                msg = 'Code executed in REPL mode must use the "repl" command'
                cc.errors.append(message.SourceError(msg))
            if cc.is_expr and self.lang_def is not None and self.lang_def.inline_expression_formatter is None:
                msg = f'Inline expressions are not supported for {self.lang_def.name}'
                cc.errors.append(message.SourceError(msg))
            if last_cc is not None and last_cc.options['outside_main'] != cc.options['outside_main']:
                if last_cc.options['outside_main']:
                    from_outside_main_switches += 1
                    if from_outside_main_switches > 1:
                        msg = 'Invalid "outside_main" value; cannot switch back yet again'
                        cc.errors.append(message.SourceError(msg))
                    for icc in incomplete_ccs:
                        # When switching from `outside_main`, all accumulated
                        # output belongs to the last code chunk `outside_main`
                        icc.output_index = last_cc.index
                    incomplete_ccs = []
                else:
                    if not last_cc.options['complete']:
                        msg = 'Final code chunk before switching to "outside_main" must have "complete" value "true"'
                        last_cc.errors.append(message.SourceError(msg))
                    to_outside_main_switches += 1
                    if to_outside_main_switches > 1:
                        msg = 'Invalid "outside_main" value; cannot switch back yet again'
                        cc.errors.append(message.SourceError(msg))
            if cc.options['complete']:
                cc.output_index = cc.index
                if incomplete_ccs:
                    for icc in incomplete_ccs:
                        icc.output_index = cc.index
                    incomplete_ccs = []
            else:
                incomplete_ccs.append(cc)
            last_cc = cc
        if incomplete_ccs:
            if last_cc.options['outside_main']:
                # Last code chunk gets all accumulated output
                for icc in incomplete_ccs:
                    icc.output_index = last_cc.index
            else:
                msg = 'Final code chunk cannot have "complete" value "false"'
                last_cc.errors.append(message.SourceError(msg))
        for cc in self.code_chunks:
            if not cc.inline:
                cc.finalize_line_numbers(self._code_start_line_number)
                self._code_start_line_number += len(cc.code_lines)
        if self.status.prevent_exec:
            # Hashes and line numbers are only needed if code will indeed be
            # executed.  It is impossible to determine these in the case of
            # errors like copy errors which leave code for one or more chunks
            # undefined.
            return

        # The overall hash for a session has the form
        # `<blake2b(session)>_<len(code)>`.  Code is hashed as well as options
        # that affect code execution.  The hashing process needs to use some
        # sort of delimiter between code chunks and between code and its
        # options.  `hasher.digest()` is used for this purpose.  `len(code)`
        # is included in the overall hash as an extra guard against
        # collisions.
        hasher = hashlib.blake2b()
        code_len = 0
        # Hash needs to depend on session to avoid collisions.  Hash needs to
        # depend on options that determine how code is executed.
        if self.executable:
            hashed_options = {
                'session': self.name,
                'executable': self.executable,
                'executable_opts': self.executable_opts,
                'args': self.args,
            }
        elif self.jupyter_kernel:
            hashed_options = {
                'session': self.name,
                'jupyter_kernel': self.jupyter_kernel,
                'jupyter_timeout': self.jupyter_timeout,
            }
        else:
            raise TypeError
        hasher.update(json.dumps(hashed_options).encode('utf8'))
        hasher.update(hasher.digest())
        # Hash needs to depend on the language definition
        if self.lang_def is not None:
            hasher.update(self.lang_def.definition_bytes)
        hasher.update(hasher.digest())
        for cc in self.code_chunks:
            # Hash needs to depend on some code chunk options.  `command`
            # determines some wrapper code.  `inline` affects line count
            # and error sync currently, and might also affect code in the
            # future.  `complete` determines how code is executed as a
            # byproduct of modifying where output appears.
            cc_options = {
                'command': cc.command,
                'inline': cc.inline,
                'complete': cc.options['complete'],
            }
            hasher.update(json.dumps(cc_options).encode('utf8'))
            hasher.update(hasher.digest())
            code_bytes = cc.code_str.encode('utf8')
            hasher.update(code_bytes)
            hasher.update(hasher.digest())
            code_len += len(cc.code_str) + 1  # +1 for omitted trailing newline
        self.hash = f'{hasher.hexdigest()}_{code_len}'
        self.hash_root = self.temp_suffix = hasher.hexdigest()[:16]
        self.run_delim_hash = hasher.hexdigest()[:64]

        self.is_finalized = True


    @property
    def run_code(self) -> str:
        if self._run_code is not None:
            return self._run_code

        if (self.jupyter_kernel is not None or not self.is_finalized or self.status.has_errors):
            raise AttributeError

        # Delim templates for streams
        delim_start = self.run_delim_start
        start_delim_args = f'delim=start, chunk={{chunk}}, output_chunk={{output_chunk}}, hash={self.run_delim_hash},'
        end_delim_args =   f'delim=end, chunk={{chunk}}, output_chunk={{output_chunk}}, hash={self.run_delim_hash},'
        stdout_start_delim_template = f'{delim_start}(output=stdout, {start_delim_args})'
        stdout_end_delim_template =   f'{delim_start}(output=stdout, {end_delim_args})'
        stderr_start_delim_template = f'{delim_start}(output=stderr, {start_delim_args})'
        stderr_end_delim_template =   f'{delim_start}(output=stderr, {end_delim_args})'
        expr_start_delim_template =   f'{delim_start}(output=expr, {start_delim_args})'
        expr_end_delim_template =     f'{delim_start}(output=expr, {end_delim_args})'
        repl_start_delim_template =   f'{delim_start}(output=repl, {start_delim_args})'
        repl_end_delim_template =     f'{delim_start}(output=repl, {end_delim_args})'
        rich_output_start_delim_template = f'{delim_start}(output=rich_output, format={{format}}, {start_delim_args})'
        rich_output_end_delim_template =   f'{delim_start}(output=rich_output, format={{format}}, {end_delim_args})'

        # List of code to execute, plus bookkeeping for tracing errors back to
        # their origin
        run_code_list: list[str] = []
        run_code_line_number: int = 1
        user_code_line_number: int = 1
        self.run_code_to_origins = {}
        self.expected_stdout_start_delim_chunks = {}
        self.expected_stderr_start_delim_chunks = {}
        self.expected_stdout_end_delim_chunks = {}
        self.expected_stderr_end_delim_chunks = {}

        # Assemble code to execute while keeping track of where each line
        # originates
        if not self.code_chunks[0].options['outside_main']:
            run_code_list.append(self.lang_def.run_template_before_code)
            run_code_line_number += self.lang_def.run_template_before_code_n_lines
        last_cc = None
        for cc in self.code_chunks:
            if ((last_cc is not None and last_cc.options['complete']) or
                    (last_cc is not None and last_cc.options['outside_main'] and not cc.options['outside_main'])):
                run_code_list.append(
                    self.lang_def.chunk_wrapper_after_code.format(
                        stdout_end_delim=stdout_end_delim_template.format(chunk=last_cc.index, output_chunk=last_cc.output_index),
                        stderr_end_delim=stderr_end_delim_template.format(chunk=last_cc.index, output_chunk=last_cc.output_index),
                        repl_end_delim=repl_end_delim_template.format(chunk=last_cc.index, output_chunk=last_cc.output_index),
                    )
                )
                run_code_line_number += self.lang_def.chunk_wrapper_after_code_n_lines
                self.expected_stdout_end_delim_chunks[last_cc.index] = 1
                self.expected_stderr_end_delim_chunks[last_cc.index] = 1
            if ((last_cc is None and not cc.options['outside_main']) or
                    (last_cc is not None and last_cc.options['complete']) or
                    (last_cc is not None and last_cc.options['outside_main'] != cc.options['outside_main'])):
                run_code_list.append(
                    self.lang_def.chunk_wrapper_before_code.format(
                        stdout_start_delim=stdout_start_delim_template.format(chunk=cc.index, output_chunk=cc.output_index),
                        stderr_start_delim=stderr_start_delim_template.format(chunk=cc.index, output_chunk=cc.output_index),
                        repl_start_delim=repl_start_delim_template.format(chunk=cc.index, output_chunk=cc.output_index),
                    )
                )
                run_code_line_number += self.lang_def.chunk_wrapper_before_code_n_lines
                self.expected_stdout_start_delim_chunks[cc.index] = 1
                self.expected_stderr_start_delim_chunks[cc.index] = 1
            if cc.inline:
                # Only block code contributes toward line numbers
                if cc.is_expr:
                    expr_start_delim = expr_start_delim_template.format(chunk=cc.index, output_chunk=cc.output_index)
                    expr_end_delim = expr_end_delim_template.format(chunk=cc.index, output_chunk=cc.output_index)
                    expr_code = self.lang_def.inline_expression_formatter.format(
                        expr_start_delim=expr_start_delim,
                        expr_end_delim=expr_end_delim,
                        temp_suffix=self.temp_suffix,
                        code=cc.code_str,
                    )
                    if not self.lang_def.chunk_wrapper_code_indent:
                        run_code_list.append(expr_code)
                    else:
                        run_code_list.append(
                            expr_code.replace('\n', '\n'+self.lang_def.chunk_wrapper_code_indent,
                                              self.lang_def.inline_expression_formatter_n_lines-1)
                        )
                    line_number = run_code_line_number + self.lang_def.inline_expression_formatter_before_code_n_lines
                    self.run_code_to_origins[line_number] = CodeLineOrigin(chunk=cc, line_number=1)
                    run_code_line_number += self.lang_def.inline_expression_formatter_n_lines
                else:
                    run_code_list.append(f'{self.lang_def.chunk_wrapper_code_indent}{cc.code_str}\n')
                    self.run_code_to_origins[run_code_line_number] = CodeLineOrigin(chunk=cc, line_number=1)
                    run_code_line_number += 1
            else:
                for line in cc.code_lines:
                    run_code_list.append(f'{self.lang_def.chunk_wrapper_code_indent}{line}\n')
                    self.run_code_to_origins[run_code_line_number] = CodeLineOrigin(chunk=cc, line_number=user_code_line_number)
                    user_code_line_number += 1
                    run_code_line_number += 1
            last_cc = cc
        if self.code_chunks[-1].options['complete']:
            run_code_list.append(
                self.lang_def.chunk_wrapper_after_code.format(
                    stdout_end_delim=stdout_end_delim_template.format(chunk=last_cc.index, output_chunk=last_cc.output_index),
                    stderr_end_delim=stderr_end_delim_template.format(chunk=last_cc.index, output_chunk=last_cc.output_index),
                    repl_end_delim=repl_end_delim_template.format(chunk=last_cc.index, output_chunk=last_cc.output_index),
                )
            )
            self.expected_stdout_end_delim_chunks[last_cc.index] = 1
            self.expected_stderr_end_delim_chunks[last_cc.index] = 1
        if not self.code_chunks[-1].options['outside_main']:
            run_code_list.append(self.lang_def.run_template_after_code)
        self._run_code = ''.join(run_code_list)
        return self._run_code
