# -*- coding: utf-8 -*-
#
# Copyright (c) 2021-2022, Geoffrey M. Poore
# All rights reserved.
#
# Licensed under the BSD 3-Clause License:
# http://opensource.org/licenses/BSD-3-Clause
#


from __future__ import annotations


import json
import locale
import pathlib
import pkgutil
import platform
import re
import shlex
import shutil
import string
from typing import Optional

import bespon
from . import err
from . import version
from . import util
from .util import KeyDefaultDict




_string_formatter = string.Formatter()

def _check_template(template: str):
    '''
    Check a template string for validity.  Make sure all replacement fields
    are plain ASCII keywords without any format specifiers or conversion
    flags.
    '''
    for literal_text, field_name, format_spec, conversion in _string_formatter.parse(template):
        if field_name is None:
            continue
        if not isinstance(field_name, str):
            if isinstance(field_name, int):
                raise TypeError(f'Invalid field "{field_name}": need ASCII identifier, not integer')
            raise TypeError
        if not field_name.isidentifier() or not field_name.isascii():
            raise TypeError(f'Invalid field "{field_name}": need ASCII identifier')
        if format_spec:
            raise TypeError(
                f'Invalid field "{field_name}": need plain keyword without format specifier "{format_spec}"'
            )
        if conversion:
            raise TypeError(
                f'Invalid field "{field_name}": need plain keyword without conversion flag "{conversion}"'
            )

def _split_template(template: str, field: str) -> list[str]:
    '''
    Split template string at specified field name, removing field including
    `{}` delimiters.  Only supports templates with plain keywords, no format
    specifiers or conversion flags.
    '''
    split = []
    start = 0
    end = 0
    for literal_text, field_name, format_spec, conversion in _string_formatter.parse(template):
        if format_spec or conversion:
            raise TypeError('Template strings with format specifiers or conversion flags are not supported')
        end = template.find(literal_text, end) + len(literal_text)
        if field_name != field:
            if end == len(template):
                split.append(template[start:end])
                break
            continue
        split.append(template[start:end])
        end = template.find('}', end) + 1
        start = end
        if start == len(template):
            split.append('')
            break
    if len(split) == 1:
        raise ValueError(f'Field "{field}" was not found')
    return split




class Language(object):
    '''
    Process language definition and insert default values.
    '''
    def __init__(self, name: str, definition: dict):
        if not isinstance(name, str):
            raise TypeError
        self.name: str = name
        if name.endswith('_repl'):
            name_root = name.rsplit('_', 1)[0]
        else:
            name_root = name

        try:
            definition_str = json.dumps(definition)
        except TypeError:
            raise err.CodebraidError(f'Invalid language definition for "{name}"')
        self.definition_bytes: bytes = definition_str.encode('utf8')

        default_encoding = locale.getpreferredencoding(False)

        try:
            language = definition.pop('language', name_root)
            if not isinstance(language, str):
                raise TypeError
            self.language: str = language

            raw_executable = definition.pop('executable', None)
            if raw_executable is None:
                if name_root == 'python':
                    # Windows can have "python3", and Arch Linux uses
                    # "python", so use "python3" if it exists and otherwise
                    # "python"
                    which_python3 = shutil.which('python3')
                    if which_python3:
                        if (platform.system() == 'Windows' and
                                'AppData/Local/Microsoft/WindowsApps' in pathlib.Path(which_python3).as_posix()):
                            executable = 'python'
                        else:
                            executable = 'python3'
                    else:
                        executable = 'python'
                else:
                    executable = name_root
            elif isinstance(raw_executable, str):
                executable = pathlib.Path(raw_executable).expanduser().as_posix()
                if raw_executable.startswith('./') or raw_executable.startswith('.\\'):
                    executable = f'./{executable}'
            else:
                raise TypeError
            self.executable: str = executable

            raw_interpreter_script = definition.pop('run_script', None)
            if raw_interpreter_script is None:
                interpreter_script = None
            else:
                if not isinstance(raw_interpreter_script, str):
                    raise TypeError
                if any(x in raw_interpreter_script for x in ('..', '\\')):
                    # No relative or Windows-style paths
                    raise ValueError
                scripts_root_dir = pathlib.Path(__file__).parent.resolve() / 'languages' / 'scripts'
                interpreter_script = scripts_root_dir / raw_interpreter_script
                if not interpreter_script.is_file():
                    version_info = version.__version_info__
                    version_num = f'{version_info.major}.{version_info.minor}.{version_info.micro}'
                    scripts_root_dir = pathlib.Path(f'~/.codebraid/{version_num}/languages/scripts').expanduser()
                    interpreter_script = scripts_root_dir / raw_interpreter_script
                    if version_info.releaselevel != 'final' or not interpreter_script.is_file():
                        script_bytes = pkgutil.get_data('codebraid', f'languages/scripts/{raw_interpreter_script}')
                        if script_bytes is None:
                            raise err.CodebraidError(
                                f'Missing interpreter script in language definition for "{name}"'
                            )
                        interpreter_script.parent.mkdir(parents=True, exist_ok=True)
                        interpreter_script.write_bytes(script_bytes)
            self.interpreter_script: Optional[pathlib.Path] = interpreter_script

            raw_opts = definition.pop('executable_opts', None)
            if self.interpreter_script and raw_opts is not None:
                raise TypeError
            if raw_opts is None:
                opts = raw_opts
            elif isinstance(raw_opts, str):
                opts = shlex.split(raw_opts)
                if not opts:
                    raise TypeError
            elif isinstance(raw_opts, list) and raw_opts and all(isinstance(x, str) for x in raw_opts):
                opts = raw_opts
            else:
                raise TypeError
            self.executable_opts: Optional[list[str]] = opts

            raw_args = definition.pop('args', None)
            if self.interpreter_script and raw_args is not None:
                raise TypeError
            if raw_args is None:
                args = raw_args
            elif isinstance(raw_args, str):
                args = shlex.split(raw_args)
                if not args:
                    raise TypeError
            elif isinstance(raw_args, list) and raw_args and all(isinstance(x, str) for x in raw_args):
                args = raw_args
            else:
                raise TypeError
            self.args: Optional[list[str]] = args

            extension = definition.pop('extension', None)
            if not isinstance(extension, str):
                raise TypeError
            if extension.startswith('.'):
                raise ValueError
            self.extension: str = extension

            compile_encoding = definition.pop('compile_encoding', default_encoding)
            if compile_encoding is not None and not isinstance(compile_encoding, str):
                raise TypeError
            self.compile_encoding: Optional[str] = compile_encoding
            compile_commands = definition.pop('compile_commands', [])
            if isinstance(compile_commands, str):
                compile_commands = [compile_commands]
            elif not isinstance(compile_commands, list) or not all(isinstance(x, str) for x in compile_commands):
                raise TypeError
            self.compile_commands: list[str] = compile_commands

            pre_run_encoding = definition.pop('pre_run_encoding', default_encoding)
            if pre_run_encoding is not None and not isinstance(pre_run_encoding, str):
                raise TypeError
            self.pre_run_encoding: Optional[str] = pre_run_encoding
            pre_run_commands = definition.pop('pre_run_commands', [])
            if isinstance(pre_run_commands, str):
                pre_run_commands = [pre_run_commands]
            elif not isinstance(pre_run_commands, list) or not all(isinstance(x, str) for x in pre_run_commands):
                raise TypeError
            self.pre_run_commands: list[str] = pre_run_commands

            run_encoding = definition.pop('run_encoding', default_encoding)
            if run_encoding is not None and not isinstance(run_encoding, str):
                raise TypeError
            self.run_encoding: Optional[str] = run_encoding
            if not self.interpreter_script:
                run_command = definition.pop('run_command', '{executable} {executable_opts} {source} {args}')
            else:
                run_command = definition.pop('run_command', '{executable} {run_script} {run_delim_start} {run_delim_hash} {buffering}')
            if not isinstance(run_command, str):
                raise TypeError
            self.run_command: str = run_command

            post_run_encoding = definition.pop('post_run_encoding', default_encoding)
            if post_run_encoding is not None and not isinstance(post_run_encoding, str):
                raise TypeError
            self.post_run_encoding: Optional[str] = post_run_encoding
            post_run_commands = definition.pop('post_run_commands', [])
            if isinstance(post_run_commands, str):
                post_run_commands = [post_run_commands]
            elif not isinstance(post_run_commands, list) or not all(isinstance(x, str) for x in post_run_commands):
                raise TypeError
            self.post_run_commands: list[str] = post_run_commands

            repl = definition.pop('repl', name.endswith('_repl'))
            if not isinstance(repl, bool):
                raise TypeError
            self.repl: bool = repl

            run_template = definition.pop('run_template', '{code}\n')
            if not isinstance(run_template, str):
                raise TypeError
            if not run_template.endswith('\n'):
                raise ValueError('run_template must end with a newline ("\n")')
            _check_template(run_template)
            try:
                raw_run_template_before_code, raw_run_template_after_code = _split_template(run_template, 'code')
            except ValueError:
                raise ValueError('Run template must contain one and only one "{code}" field')
            raw_run_template_before_code_last_nl_index = raw_run_template_before_code.rfind('\n')
            if raw_run_template_before_code_last_nl_index < 0:
                run_template_before_code = ''
                run_template_before_code_last_line = raw_run_template_before_code
            else:
                run_template_before_code = raw_run_template_before_code[:raw_run_template_before_code_last_nl_index+1]
                run_template_before_code_last_line = raw_run_template_before_code[raw_run_template_before_code_last_nl_index+1:]
            raw_run_template_after_code_first_nl_index = raw_run_template_after_code.find('\n')
            if raw_run_template_after_code_first_nl_index < 0:
                # Technically, this duplicates the run_template.endswith('\n')
                # test from earlier.  Check anyway in case the earlier
                # test/restriction is ever relaxed.
                raise ValueError('Run template must end with a newline ("\n")')
            run_template_after_code = raw_run_template_after_code[raw_run_template_after_code_first_nl_index+1:]
            run_template_after_code_first_line = raw_run_template_after_code[:raw_run_template_after_code_first_nl_index]
            if run_template_before_code_last_line.strip(' \t') or run_template_after_code_first_line.strip(' \t'):
                raise ValueError('In run template, "{code}" field must be on a line by itself')
            run_template_code_indent = run_template_before_code_last_line
            self.run_template_before_code: str = run_template_before_code
            self.run_template_after_code: str = run_template_after_code
            self.run_template_before_code_n_lines: int = run_template_before_code.count('\n')
            self.run_template_after_code_n_lines: int = run_template_after_code.count('\n')

            if self.interpreter_script:
                if not self.repl:
                    chunk_wrapper_default = (
                        '{stdout_start_delim}\n'
                        '{stderr_start_delim}\n'
                        '{code}\n'
                        '{stdout_end_delim}\n'
                        '{stderr_end_delim}\n'
                    )
                else:
                    chunk_wrapper_default = (
                        '{stdout_start_delim}\n'
                        '{stderr_start_delim}\n'
                        '{repl_start_delim}\n'
                        '{code}\n'
                        '{repl_end_delim}\n'
                        '{stdout_end_delim}\n'
                        '{stderr_end_delim}\n'
                    )
                chunk_wrapper = definition.pop('chunk_wrapper', chunk_wrapper_default)
            else:
                chunk_wrapper = definition.pop('chunk_wrapper')
            if not isinstance(chunk_wrapper, str):
                raise TypeError
            if not chunk_wrapper.endswith('\n'):
                raise ValueError
            _check_template(chunk_wrapper)
            try:
                raw_chunk_wrapper_before_code, raw_chunk_wrapper_after_code = _split_template(chunk_wrapper, 'code')
            except ValueError:
                raise ValueError('Chunk wrapper template must contain one and only one "{code}" field')
            raw_chunk_wrapper_before_code_last_nl_index = raw_chunk_wrapper_before_code.rfind('\n')
            if raw_chunk_wrapper_before_code_last_nl_index < 0:
                raw_chunk_wrapper_before_code = ''
                raw_chunk_wrapper_before_code_last_line = raw_chunk_wrapper_before_code
            else:
                raw_chunk_wrapper_before_code = raw_chunk_wrapper_before_code[:raw_chunk_wrapper_before_code_last_nl_index+1]
                raw_chunk_wrapper_before_code_last_line = raw_chunk_wrapper_before_code[raw_chunk_wrapper_before_code_last_nl_index+1:]
            raw_chunk_wrapper_after_code_first_nl_index = raw_chunk_wrapper_after_code.find('\n')
            if raw_chunk_wrapper_after_code_first_nl_index < 0:
                # Technically, this duplicates the chunk_wrapper.endswith('\n')
                # test from earlier.  Check anyway in case the earlier
                # test/restriction is ever relaxed.
                raise ValueError('Chunk wrapper template must end with a newline ("\n")')
            raw_chunk_wrapper_after_code = raw_chunk_wrapper_after_code[raw_chunk_wrapper_after_code_first_nl_index+1:]
            raw_chunk_wrapper_after_code_first_line = raw_chunk_wrapper_after_code[:raw_chunk_wrapper_after_code_first_nl_index]
            if raw_chunk_wrapper_before_code_last_line.strip(' \t') or raw_chunk_wrapper_after_code_first_line.strip(' \t'):
                raise ValueError('In chunk wrapper template, "{code}" field must be on a line by itself')
            raw_chunk_wrapper_code_indent = raw_chunk_wrapper_before_code_last_line
            chunk_wrapper_code_indent = run_template_code_indent + raw_chunk_wrapper_code_indent
            self.chunk_wrapper_code_indent: str = chunk_wrapper_code_indent
            raw_chunk_wrapper_before_code_lines = util.splitlines_lf(raw_chunk_wrapper_before_code)
            raw_chunk_wrapper_after_code_lines = util.splitlines_lf(raw_chunk_wrapper_after_code)
            for lines in (raw_chunk_wrapper_before_code_lines, raw_chunk_wrapper_after_code_lines):
                if all(not line or line.startswith((' ', '\t')) for line in lines):
                    raise ValueError(
                        'Chunk wrapper template must not be indented; indentation is inherited from run template'
                    )
            self.chunk_wrapper_before_code: str = ''.join(f'{run_template_code_indent}{line}\n' for line in raw_chunk_wrapper_before_code_lines)
            self.chunk_wrapper_before_code_n_lines: int = len(raw_chunk_wrapper_before_code_lines)
            self.chunk_wrapper_after_code: str = ''.join(f'{run_template_code_indent}{line}\n' for line in raw_chunk_wrapper_after_code_lines)
            self.chunk_wrapper_after_code_n_lines: int = len(raw_chunk_wrapper_after_code_lines)

            raw_inline_expr_fmter = definition.pop('inline_expression_formatter', None)
            if raw_inline_expr_fmter is None:
                inline_expression_formatter = None
                inline_expr_fmter_before_code_n_lines = None
                inline_expr_fmter_n_lines = None
            else:
                if not isinstance(raw_inline_expr_fmter, str):
                    raise TypeError
                if not raw_inline_expr_fmter.endswith('\n'):
                    raise ValueError
                _check_template(raw_inline_expr_fmter)
                try:
                    raw_inline_expr_fmter_before_code, _ = _split_template(raw_inline_expr_fmter, 'code')
                except ValueError:
                    raise ValueError(
                        'Inline expression formatter template must contain one and only one "{code}" field'
                    )
                inline_expr_fmter_before_code_n_lines = raw_inline_expr_fmter_before_code.count('\n')
                raw_inline_expr_fmter_lines = util.splitlines_lf(raw_inline_expr_fmter)
                if all(not line or line.startswith((' ', '\t')) for line in raw_inline_expr_fmter_lines):
                    raise ValueError(
                        'Inline expression formatter template must not be indented; indentation is inherited from other templates'
                    )
                # Inline expression formatter has no indent to consider beyond
                # chunk wrapper indent, since code is only ever a single line.
                inline_expression_formatter = ''.join(f'{chunk_wrapper_code_indent}{line}\n' for line in raw_inline_expr_fmter_lines)
                inline_expr_fmter_n_lines = len(raw_inline_expr_fmter_lines)
            self.inline_expression_formatter: Optional[str] = inline_expression_formatter
            self.inline_expression_formatter_n_lines: Optional[int] = inline_expr_fmter_n_lines
            self.inline_expression_formatter_before_code_n_lines: Optional[int] = inline_expr_fmter_before_code_n_lines

            error_patterns = definition.pop('error_patterns', ['error', 'Error', 'ERROR'])
            if isinstance(error_patterns, str):
                error_patterns = [error_patterns]
            elif not (isinstance(error_patterns, list) and error_patterns and
                      all(isinstance(x, str) and x for x in error_patterns)):
                raise TypeError
            self.error_patterns: list[str] = error_patterns
            warning_patterns = definition.pop('warning_patterns', ['warning', 'Warning', 'WARNING'])
            if isinstance(warning_patterns, str):
                warning_patterns = [warning_patterns]
            elif not (isinstance(warning_patterns, list) and warning_patterns and
                      all(isinstance(x, str) and x for x in warning_patterns)):
                raise TypeError
            self.warning_patterns: list[str] = warning_patterns
            line_number_raw_patterns = definition.pop('line_number_patterns', [':{number}', 'line {number}'])
            if line_number_raw_patterns is None:
                pass
            elif isinstance(line_number_raw_patterns, str):
                line_number_raw_patterns = [line_number_raw_patterns]
            elif not (isinstance(line_number_raw_patterns, list) and line_number_raw_patterns and
                      all(isinstance(x, str) and x for x in line_number_raw_patterns)):
                raise TypeError
            self.line_number_raw_patterns: Optional[list[str]] = line_number_raw_patterns
            line_number_regex = definition.pop('line_number_regex', None)
            if line_number_regex is not None and not isinstance(line_number_regex, str):
                raise TypeError
            self.line_number_regex: Optional[str] = line_number_regex
            if line_number_raw_patterns is None and line_number_regex is None:
                raise TypeError
        except KeyError as e:
            raise err.CodebraidError(f'Missing key(s) in language definition for "{name}":\n{e}')
        except (TypeError, ValueError) as e:
            raise err.CodebraidError(f'Invalid data type or value in language definition for "{name}":\n{e}')
        if definition:
            unknown_keys = ', '.join(f'"{k}"' for k in definition)
            raise err.CodebraidError(f'Unknown key(s) in language definition for "{name}": {unknown_keys}')

        self.exec_stages = {}
        if self.compile_commands:
            self.exec_stages['compile'] = self.compile_commands
        if self.pre_run_commands:
            self.exec_stages['pre_run'] = self.pre_run_commands
        if self.run_command:
            self.exec_stages['run'] = self.run_command
        if self.post_run_commands:
            self.exec_stages['post_run'] = self.post_run_commands

        if line_number_raw_patterns:
            line_number_patterns = []
            for lnp in line_number_raw_patterns:
                try:
                    lnp_split = _split_template(lnp, 'number')
                except ValueError as e:
                    raise err.CodebraidError(f'Invalid line number pattern in language definition for "{name}":\n{e}')
                line_number_patterns.append(r'(\d+)'.join(re.escape(x) for x in lnp_split))
            line_number_pattern = '|'.join(line_number_patterns)
            try:
                line_number_pattern_re =  re.compile(line_number_pattern)
            except Exception as e:
                raise err.CodebraidError(f'Invalid line number pattern in language definition for "{name}":\n{e}')
        else:
            line_number_pattern = None
            line_number_pattern_re = None
        self.line_number_pattern: Optional[str] = line_number_pattern
        self.line_number_pattern_re: Optional[re.Pattern] = line_number_pattern_re
        if self.line_number_regex is None:
            line_number_regex_re = None
        else:
            try:
                line_number_regex_re = re.compile(self.line_number_regex, re.MULTILINE)
            except Exception as e:
                raise err.CodebraidError(f'Invalid line number regex in language definition for "{name}":\n{e}')
        self.line_number_regex_re: Optional[re.Pattern] = line_number_regex_re




templates_root = 'languages'
_raw_index = pkgutil.get_data('codebraid', f'{templates_root}/index.bespon')
if _raw_index is None:
    raise err.CodebraidError(f'Failed to find "codebraid/{templates_root}/index.bespon"')
index = bespon.loads(_raw_index)
del _raw_index


def _load_language(lang_name: str) -> Optional[Language]:
    '''
    Load and return language definition from if it exists, else return None.
    '''
    try:
        lang_def_filename = index[lang_name]
    except KeyError:
        return None
    lang_def_bytes = pkgutil.get_data('codebraid', f'{templates_root}/{lang_def_filename}')
    if lang_def_bytes is None:
        return None
    try:
        lang_def = bespon.loads(lang_def_bytes)
    except Exception as e:
        raise err.CodebraidError(
            f'Failed to load language definition for "{lang_name}" (invalid or corrupted definition?):\n{e}'
        )
    return Language(lang_name, lang_def[lang_name])
languages = KeyDefaultDict(_load_language)
del _load_language
