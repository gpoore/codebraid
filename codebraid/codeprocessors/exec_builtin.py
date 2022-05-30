# -*- coding: utf-8 -*-
#
# Copyright (c) 2021-2022, Geoffrey M. Poore
# All rights reserved.
#
# Licensed under the BSD 3-Clause License:
# http://opensource.org/licenses/BSD-3-Clause
#


from __future__ import annotations


import asyncio
import collections
import io
import pathlib
import platform
import re
import shlex
import shutil
import subprocess
import tempfile
from typing import Optional
from .. import util
from .. import message
from ..code_collections import Session, CodeLineOrigin
from ..code_chunks import CodeChunk
from ..progress import Progress




async def exec(session: Session, *, cache_key_path: pathlib.Path, progress: Progress) -> None:
    '''
    Execute code from a session with the built-in code execution system,
    attach textual output to the code chunks within the session, and save rich
    output files.
    '''
    session.did_exec = True

    with tempfile.TemporaryDirectory() as temp_dir_str:
        temp_dir_path = pathlib.Path(temp_dir_str)
        if not session.lang_def.interpreter_script:
            origin_path = temp_dir_path / f'source_{session.hash_root}.{session.lang_def.extension}'
            origin_path.write_text(session.run_code, encoding='utf8')
        for stage, command_or_commands in session.lang_def.exec_stages.items():
            if session.status.prevent_exec:
                break
            progress.session_exec_stage_start(session, stage=stage)
            if isinstance(command_or_commands, str):
                commands = [command_or_commands]
            else:
                commands = command_or_commands
            for command in commands:
                if session.status.prevent_exec:
                    break
                subproc = SessionSubprocess(session, stage, command, temp_dir_path, progress)
                await subproc.start()
                await subproc.wait()
            progress.session_exec_stage_end(session, stage=stage)


class SessionSubprocess(object):
    def __init__(self, session: Session, stage: str, command: str, temp_dir_path: pathlib.Path, progress: Progress):
        self.session = session
        self.stage = stage
        self.encoding = getattr(session.lang_def, f'{stage}_encoding')
        self.has_interpreter_script = session.lang_def.interpreter_script is not None
        template_dict = {
            'executable': session.executable,
            'extension': session.lang_def.extension,
            'run_delim_start': session.run_delim_start,
            'run_delim_hash': session.run_delim_hash,
        }
        if not self.has_interpreter_script:
            origin_name = f'source_{session.hash_root}'
            origin_path = temp_dir_path / f'{origin_name}.{session.lang_def.extension}'
            template_dict.update({
                'source_name': origin_name,
                'source_dir': temp_dir_path.as_posix(),
                'source': origin_path.as_posix(),
                'source_without_extension': (temp_dir_path / origin_name).as_posix(),
            })
        else:
            template_dict.update({
                'run_script': session.lang_def.interpreter_script.as_posix(),
                'buffering': 'line',
            })
        program_with_args: list[str] = []
        for s in shlex.split(command):
            if s == '{executable_opts}':
                if session.executable_opts:
                    program_with_args.extend(session.executable_opts)
                continue
            if s == '{args}':
                if session.args:
                    program_with_args.extend(session.args)
                continue
            program_with_args.append(s.format(**template_dict))
        if platform.system() == 'Windows':
            # Modify args since subprocess.Popen() ignores PATH
            #   * https://bugs.python.org/issue8557
            #   * https://bugs.python.org/issue15451
            program = shutil.which(program_with_args[0]) or program_with_args[0]
        else:
            program = program_with_args[0]
        self.program = program
        self.args = program_with_args[1:]
        self.stage = stage
        self.progress = progress
        self.input = session.run_code if self.has_interpreter_script else None
        self.stderr_is_stdout = (stage != 'run')

        self._stdout_buffer: list[bytes] = []
        self._stderr_buffer: list[bytes] = []
        self._delim_error: bool = False
        self._sync_chunk_start_delims_state: dict[int, int] = collections.defaultdict(int)
        self._sync_chunk_end_delims_state: dict[int, int] = collections.defaultdict(int)
        self._sync_chunk_start_delims_waiting: int = 0
        self._sync_chunk_end_delims_waiting: int = 0
        self._sync_stream_end_waiting: int = 0

        if not self.has_interpreter_script:
            origin_path_re_pattern = re.escape(origin_path.as_posix()).replace('/', r'[\\/]')
            origin_name_re_pattern = re.escape(origin_path.name)
            self.origin_path_re = re.compile(f'{origin_path_re_pattern}|{origin_name_re_pattern}', re.IGNORECASE)
            self.origin_path_replacement = f'source.{session.lang_def.extension}'
            self.origin_path_inline_replacement = '<string>'
            self.line_number_pattern_re = session.lang_def.line_number_pattern_re
            self.line_number_regex_re = session.lang_def.line_number_regex_re
        self.error_patterns = session.lang_def.error_patterns
        self.warning_patterns = session.lang_def.warning_patterns
        home_path_re_pattern = re.escape(pathlib.Path('~').expanduser().as_posix()).replace('/', r'[\\/]')
        self.home_path_re = re.compile(home_path_re_pattern, re.IGNORECASE)

    @property
    def returncode(self):
        return self.proc.returncode

    @property
    def is_terminated(self):
        return self.proc.returncode is not None


    async def start(self):
        self.proc = None
        try:
            self.proc = await asyncio.create_subprocess_exec(
                self.program, *self.args,
                stdin=subprocess.PIPE if self.input else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT if self.stderr_is_stdout else subprocess.PIPE
            )
        except FileNotFoundError:
            self.session.errors.append(message.SysConfigError(f'Could not find executable "{self.program}"'))
            return
        if self.stage != 'run':
            await asyncio.gather(self._read_output())
        else:
            await asyncio.gather(self._write_input(), self._read_run('stdout'), self._read_run('stderr'))

    async def wait(self):
        if self.proc is None:
            return
        await self.proc.wait()
        for error in self.session.errors:
            if isinstance(error, message.ExecError):
                error.exit_code = self.proc.returncode
        for cc in self.session.code_chunks:
            for error in cc.errors:
                if isinstance(error, message.ExecError):
                    error.exit_code = self.proc.returncode
        return self.proc.returncode


    def _decode(self, output: bytes, *, output_type: Optional[str]=None, code_chunk: Optional[CodeChunk]=None):
        # Decode bytes using `io` to get the same newline behavior as reading
        # from a file.  Only raise decoding errors for the run stage, since
        # that is the only stage that produces output in the document.  At
        # some point, it may be worth adding a warning for decoding errors for
        # other stages.
        if self.stage != 'run':
            return io.TextIOWrapper(io.BytesIO(output), encoding=self.encoding, errors='backslashreplace').read()
        try:
            decoded = io.TextIOWrapper(io.BytesIO(output), encoding=self.encoding).read()
        except UnicodeDecodeError as e:
            self.session.decode_error_count += 1
            if self.session.decode_error_count <= self.session.max_tracked_decode_error_count:
                error = message.DecodeError(
                    f'Error decoding {output_type or "output"} as "{self.encoding}" (invalid bytes shown in \\xNN format):\n{e}'
                )
                if code_chunk is not None:
                    code_chunk.errors.append(error)
                else:
                    self.session.errors.append(error)
            decoded = io.TextIOWrapper(io.BytesIO(output), encoding=self.encoding, errors='backslashreplace').read()
        return decoded


    async def _write_input(self):
        if not self.input:
            return
        for line in io.BytesIO(self.input.encode(self.encoding)):
            self.proc.stdin.write(line)
            await self.proc.stdin.drain()
        self.proc.stdin.close()
        await self.proc.stdin.wait_closed()


    async def _read_output(self):
        while True:
            out = await self.proc.stdout.read(4096)
            if out:
                self._stdout_buffer.append(out)
            else:
                break
        stdout = self._decode(b''.join(self._stdout_buffer))
        if self.stage == 'compile':
            stdout = self._sync_stderr_or_compile_output(
                stdout, code_chunk=None, session_output_lines=self.session.compile_lines
            )
            self.session.compile_lines.extend(util.splitlines_lf(stdout))
        elif self.stage == 'pre_run':
            self.session.pre_run_output_lines.extend(util.splitlines_lf(stdout))
            self.session.errors.append(message.PreRunError(self.session.pre_run_output_lines))
        elif self.stage == 'post_run':
            self.session.post_run_output_lines.extend(util.splitlines_lf(stdout))
            self.session.errors.append(message.PostRunError(self.session.post_run_output_lines))
        else:
            raise ValueError
        self.progress.session_exec_stage_output(self.session, output=stdout)

    def _parse_delim(self, delim_line: str):
        start = delim_line.find('(')
        end = delim_line.rfind(')')
        if start == -1 or end == -1:
            raise ValueError
        try:
            kv_pairs = [x.strip() for x in delim_line[start+1:end].split(',') if x]
            k_v_dict = {}
            for kv in kv_pairs:
                k, v = kv.split('=')
                k_v_dict[k] = v
            for k in ('chunk', 'output_chunk'):
                k_v_dict[k] = int(k_v_dict[k])
        except Exception:
            raise ValueError
        if k_v_dict['hash'] != self.session.run_delim_hash:
            raise ValueError
        return k_v_dict

    def _process_code_chunk_output(self, output: bytes, *, code_chunk: CodeChunk, output_type: str):
        if not output:
            return
        output_str = self._decode(output, output_type=output_type, code_chunk=code_chunk)
        if output_type == 'stderr':
            output_str = self._sync_stderr_or_compile_output(output_str, code_chunk=code_chunk)
        getattr(self.progress, f'session_chunk_{output_type}')(self.session, chunk=code_chunk, output=output_str)
        getattr(code_chunk, f'{output_type}_lines').extend(util.splitlines_lf(output_str))

    def _run_line_number_to_origin(self, run_line_number: int) -> CodeLineOrigin | tuple[None, None]:
        line_origin = self.session.run_code_to_origins.get(run_line_number, None)
        while line_origin is None and run_line_number > 0:
            run_line_number -= 1
            origin = self.session.run_code_to_origins.get(run_line_number, None)
        if line_origin is None:
            return (None, None)
        return line_origin

    def _sync_stderr_or_compile_output(self, output: str, *,
                                       code_chunk: Optional[CodeChunk],
                                       session_output_lines: Optional[list[str]]=None) -> str:
        if not ((code_chunk is not None and session_output_lines is None) or
                (code_chunk is None and session_output_lines is not None)):
            raise TypeError

        if (self.has_interpreter_script or self.origin_path_re.search(output) is None and
                (self.line_number_regex_re is None or self.line_number_regex_re.search(output) is None)):
            output = self.home_path_re.sub('~', output)
            for error_pattern in self.error_patterns:
                if error_pattern in output:
                    if code_chunk is not None:
                        if not code_chunk.errors.has_stderr:
                            code_chunk.errors.append(message.StderrRunError(code_chunk.stderr_lines))
                    elif not self.session.errors.has_ref(session_output_lines):
                        self.session.errors.append(message.StderrRunError(session_output_lines))
                    return output
            for warning_pattern in self.warning_patterns:
                if warning_pattern in output:
                    if code_chunk is not None:
                        if not code_chunk.warnings.has_stderr:
                            code_chunk.warnings.append(message.StderrRunWarning(code_chunk.stderr_lines))
                    elif not self.session.warnings.has_ref(session_output_lines):
                        self.session.warnings.append(message.StderrRunWarning(session_output_lines))
                    return output
            return output

        # For each line containing the origin (source) path, replace the path
        # with a generic file name.  Sync line numbers with the line numbers
        # from user code (existing line numbers include template code).  In
        # the event of line numbers that can't be synchronized, wrap numbers
        # in square brackets `[<number>]`.
        max_synced_code_chunk = None
        if not self.line_number_pattern_re:
            if code_chunk is not None and code_chunk.inline:
                output = self.origin_path_re.sub(self.origin_path_inline_replacement, output)
            else:
                output = self.origin_path_re.sub(self.origin_path_replacement, output)
        else:
            output_lines_indices_with_origin_path = set()
            def process_match(match: re.Match):
                line_number = output.count('\n', 0, match.start())
                output_lines_indices_with_origin_path.add(line_number)
                return self.origin_path_replacement
            output = self.origin_path_re.sub(process_match, output)
            output_lines = util.splitlines_lf(output)
            if output.endswith('\n'):
                output_lines.append('')
            for index in output_lines_indices_with_origin_path:
                line = output_lines[index]
                current_code_chunk = None
                line_list = []
                last_end = 0
                for line_number_match in self.line_number_pattern_re.finditer(line):
                    for group_index in range(1, line_number_match.lastindex+1):
                        if line_number_match.group(group_index) is not None:
                            line_list.append(line[last_end:line_number_match.start(group_index)])
                            synced_code_chunk, synced_line_number = self._run_line_number_to_origin(int(line_number_match.group(group_index)))
                            if synced_code_chunk is None:
                                current_code_chunk = None
                                line_list.append(f'[{line_number_match.group(group_index)}]')
                            else:
                                current_code_chunk = synced_code_chunk
                                if max_synced_code_chunk is None or max_synced_code_chunk.index > synced_code_chunk.index:
                                    max_synced_code_chunk = synced_code_chunk
                                line_list.append(f'{synced_line_number}')
                            line_list.append(line[line_number_match.end(group_index):line_number_match.end()])
                            last_end = line_number_match.end()
                            break
                line_list.append(line[last_end:])
                line = ''.join(line_list)
                if current_code_chunk is not None and current_code_chunk.inline:
                    # Inline replacements must be performed last, so that
                    # patterns like `.ext:{number}` will work.  Otherwise,
                    # this has become `<string>:{number}` and matching fails.
                    line = line.replace(self.origin_path_replacement, self.origin_path_inline_replacement)
                output_lines[index] = line
            output = '\n'.join(output_lines)
        if self.line_number_regex_re:
            output_list = []
            last_end = 0
            for line_number_match in self.line_number_regex_re.finditer(output):
                for group_index in range(1, line_number_match.lastindex+1):
                    if line_number_match.group(group_index) is not None:
                        output_list.append(output[last_end:line_number_match.start(group_index)])
                        _, synced_line_number = self._run_line_number_to_origin(int(line_number_match.group(group_index)))
                        if synced_line_number is None:
                            output_list.append(f'[{line_number_match.group(group_index)}]')
                        else:
                            output_list.append(f'{synced_line_number:{line_number_match.end(group_index)-line_number_match.start(group_index)}d}')
                        output_list.append(output[line_number_match.end(group_index):line_number_match.end()])
                        last_end = line_number_match.end()
                        break
            output_list.append(output[last_end:])
            output = ''.join(output_list)
        # Wait to sanitize home dir until after normalizing temp paths
        output = self.home_path_re.sub('~', output)
        for error_pattern in self.error_patterns:
            if error_pattern in output:
                if code_chunk is not None:
                    if not code_chunk.errors.has_stderr:
                        code_chunk.errors.append(message.StderrRunError(code_chunk.stderr_lines))
                else:
                    if not self.session.errors.has_ref(session_output_lines):
                        self.session.errors.append(message.StderrRunError(session_output_lines))
                    if max_synced_code_chunk is not None and not max_synced_code_chunk.errors.has_ref(session_output_lines):
                        max_synced_code_chunk.errors.append(message.StderrRunErrorRef(session_output_lines))
                        self.session.errors.update_refed(session_output_lines)
                return output
        for warning_pattern in self.warning_patterns:
            if warning_pattern in output:
                if code_chunk is not None:
                    if not code_chunk.warnings.has_stderr:
                        code_chunk.warnings.append(message.StderrRunWarning(code_chunk.stderr_lines))
                else:
                    if not self.session.warnings.has_ref(session_output_lines):
                        self.session.warnings.append(message.StderrRunWarning(session_output_lines))
                    if max_synced_code_chunk is not None and not max_synced_code_chunk.warnings.has_ref(session_output_lines):
                        max_synced_code_chunk.warnings.append(message.StderrRunWarningRef(session_output_lines))
                return output
        return output


    async def _sync_chunk_start_delims(self, code_chunk: CodeChunk):
        self._sync_chunk_start_delims_state[code_chunk.index] += 1
        if self._sync_chunk_start_delims_state[code_chunk.index] == 2:
            self.progress.session_chunk_start(self.session, chunk=code_chunk)
            return
        self._sync_chunk_start_delims_waiting += 1
        while self._sync_chunk_start_delims_state[code_chunk.index] < 2:
            if self._delim_error:
                break
            if self._sync_chunk_start_delims_waiting > 1:
                code_chunk.errors.append(message.RuntimeSourceError(
                    'Synchronization of code output with document failed.  Possible modification of stdout or stderr?'
                ))
                self._delim_error = True
                break
            await asyncio.sleep(0)
        self._sync_chunk_start_delims_waiting -= 1

    async def _sync_chunk_end_delims(self, code_chunk: CodeChunk):
        self._sync_chunk_end_delims_state[code_chunk.index] += 1
        if self._sync_chunk_end_delims_state[code_chunk.index] == 2:
            self.progress.session_chunk_end(self.session, chunk=code_chunk)
            return
        self._sync_chunk_end_delims_waiting += 1
        while self._sync_chunk_end_delims_state[code_chunk.index] < 2:
            if self._delim_error:
                break
            if self._sync_chunk_end_delims_waiting > 1:
                code_chunk.errors.append(message.RuntimeSourceError(
                    'Synchronization of code output with document failed.  Possible modification of stdout or stderr?'
                ))
                self._delim_error = True
                break
            await asyncio.sleep(0)
        self._sync_chunk_end_delims_waiting -= 1

    async def _sync_stream_end(self, stream_type: str):
        # Add sleep for stdout to make order of stream resolution reproducible
        self._sync_stream_end_waiting += 1
        if self._sync_stream_end_waiting == 2:
            if stream_type == 'stdout':
                await asyncio.sleep(0)
            return
        while self._sync_stream_end_waiting < 2:
            await asyncio.sleep(0)
        self._sync_stream_end_waiting = 0
        if stream_type == 'stdout':
            await asyncio.sleep(0)


    async def _read_run(self, stream_type: str):
        # Currently, progress is line buffered.

        session = self.session
        encoding = self.encoding
        run_delim_start_search_pattern = self.session.run_delim_start_search_pattern.encode(encoding)
        lf = '\n'.encode(encoding)
        lflf = 2 * lf
        cr = '\r'.encode(encoding)
        crlf = cr + lf
        crflcrlf = 2 * crlf
        # Assume encoding with len(cr) == len(lf)
        len_cr_or_lf = len(lf)
        if stream_type == 'stdout':
            stream = self.proc.stdout
            buffer = self._stdout_buffer
        elif stream_type == 'stderr':
            stream = self.proc.stderr
            buffer = self._stderr_buffer
        else:
            raise ValueError

        if session.code_chunks[0].options['outside_main']:
            first_code_chunk = session.code_chunks[0]
            code_chunk = session.code_chunks[first_code_chunk.output_index]
            await self._sync_chunk_start_delims(first_code_chunk)
        else:
            code_chunk = None
        output_type = stream_type

        while True:
            output = await stream.read(4096)
            if self._delim_error:
                if output:
                    continue
                break
            if not output:
                if buffer:
                    remaining_output = b''.join(buffer)
                    buffer.clear()
                    if code_chunk is not None:
                        if code_chunk.options['outside_main'] and code_chunk is session.code_chunks[-1]:
                            self._process_code_chunk_output(remaining_output, code_chunk=code_chunk, output_type=output_type)
                            await self._sync_chunk_end_delims(code_chunk)
                        else:
                            self._process_code_chunk_output(remaining_output, code_chunk=code_chunk, output_type=output_type)
                            await self._sync_chunk_end_delims(code_chunk)
                            self._delim_error = True
                            if not code_chunk.errors.has_stderr:
                                code_chunk.errors.append(message.RuntimeSourceError(
                                    'Code chunk is not a complete unit of code or exited before expected.'
                                ))
                    elif stream_type == 'stderr':
                        if (all(v == 0 for v in session.expected_stderr_start_delim_chunks.values()) and
                                all(v == 0 for v in session.expected_stderr_end_delim_chunks.values())):
                            session_lines = session.template_end_stderr_lines
                        else:
                            session_lines = session.other_stderr_lines
                        synced_output = self._sync_stderr_or_compile_output(
                            self._decode(remaining_output, output_type='stderr', code_chunk=None),
                            code_chunk=None,
                            session_output_lines=session_lines
                        )
                        session_lines.extend(util.splitlines_lf(synced_output))
                elif code_chunk is not None:
                    await self._sync_chunk_end_delims(code_chunk)
                await self._sync_stream_end(stream_type)

                # Only report a single error as a result of missing
                # delimiter(s), for the first code chunk with a missing
                # delimiter.
                if not self._delim_error and not session.status.prevent_exec:
                    for code_chunk_index, count in getattr(session, f'expected_{stream_type}_start_delim_chunks').items():
                        if count != 0:
                            session.code_chunks[code_chunk_index].errors.append(message.RuntimeSourceError(
                                "A previous code chunk interfered with this chunk's execution.  "
                                'Incorrect "outside_main" or "complete" settings, or incomplete preceding unit of code.'
                            ))
                            break
                if not self._delim_error and not session.status.prevent_exec:
                    for code_chunk_index, count in getattr(session, f'expected_{stream_type}_end_delim_chunks').items():
                        if count != 0:
                            session.code_chunks[code_chunk_index].errors.append(message.RuntimeSourceError(
                                'Code chunk is not a complete unit of code or exited before expected.'
                            ))
                            break
                break
            buffer.append(output)
            if lf not in output and cr not in output:
                continue
            unprocessed_output = b''.join(buffer)
            buffer.clear()
            delim_start_index = unprocessed_output.find(run_delim_start_search_pattern)
            if delim_start_index == -1:
                if code_chunk is not None:
                    # Leave a trailing `\r` since it might be followed by
                    # `\n`.  Leave a trailing `\n` since it might be from
                    # delim rather that user.
                    last_lf_index = unprocessed_output.rfind(lf)
                    last_cr_index = unprocessed_output.rfind(cr, 0, len(unprocessed_output) - len_cr_or_lf)
                    break_index = max(last_lf_index, last_cr_index)
                    if break_index != -1:
                        output_before_break = unprocessed_output[:break_index+len_cr_or_lf]
                        unprocessed_output = unprocessed_output[break_index+len_cr_or_lf:]
                        if output_before_break:
                            self._process_code_chunk_output(output_before_break, code_chunk=code_chunk, output_type=output_type)
            else:
                while delim_start_index != -1:
                    output_before_delim = unprocessed_output[:delim_start_index]
                    if output_before_delim == lf or output_before_delim == crlf:
                        output_before_delim = b''
                    elif output_before_delim.endswith(lflf):
                        output_before_delim = output_before_delim[:-len_cr_or_lf]
                    elif output_before_delim.endswith(crflcrlf):
                        output_before_delim = output_before_delim[:-2*len_cr_or_lf]
                    if output_before_delim:
                        if code_chunk is not None:
                            self._process_code_chunk_output(output_before_delim, code_chunk=code_chunk, output_type=output_type)
                    delim_end_index = unprocessed_output.find(lf, delim_start_index)
                    if delim_end_index == -1:
                        break
                    delim = unprocessed_output[delim_start_index:delim_end_index+len_cr_or_lf]
                    unprocessed_output = unprocessed_output[delim_end_index+len_cr_or_lf:]
                    try:
                        delim_dict = self._parse_delim(delim.decode(encoding))
                    except Exception:
                        if code_chunk is not None:
                            self._process_code_chunk_output(delim, code_chunk=code_chunk, output_type=output_type)
                        delim_start_index = -1
                    else:
                        if delim_dict['delim'] == 'start':
                            delim_output_type = delim_dict['output']
                            if delim_output_type == stream_type:
                                expected_start_delim_chunks = getattr(session, f'expected_{stream_type}_start_delim_chunks')
                                expected_start_delim_chunks[delim_dict['chunk']] -= 1
                                if output_type != stream_type or code_chunk is not None or expected_start_delim_chunks[delim_dict['chunk']] != 0:
                                    self._delim_error = True
                                    session.code_chunks[delim_dict['chunk']].errors.append(message.RuntimeSourceError(
                                        "A previous code chunk interfered with this chunk's execution.  "
                                        'Incorrect "outside_main" or "complete" settings, or incomplete preceding unit of code.'
                                    ))
                                    break
                                code_chunk = session.code_chunks[delim_dict['output_chunk']]
                                await self._sync_chunk_start_delims(session.code_chunks[delim_dict['chunk']])
                            else:
                                if output_type != stream_type or code_chunk is None:
                                    self._delim_error = True
                                    session.code_chunks[delim_dict['chunk']].errors.append(message.RuntimeSourceError(
                                        'Code chunk is not a complete unit of code or is invalid.'
                                    ))
                                    break
                                output_type = delim_output_type
                        elif delim_dict['delim'] == 'end':
                            delim_output_type = delim_dict['output']
                            if delim_output_type == stream_type:
                                expected_end_delim_chunks = getattr(session, f'expected_{stream_type}_end_delim_chunks')
                                expected_end_delim_chunks[delim_dict['chunk']] -= 1
                                if output_type != stream_type or code_chunk is None or code_chunk.output_index != delim_dict['output_chunk'] or expected_end_delim_chunks[delim_dict['chunk']] != 0:
                                    self._delim_error = True
                                    session.code_chunks[delim_dict['chunk']].errors.append(message.RuntimeSourceError(
                                        'Code chunk is not a complete unit of code or is invalid.'
                                    ))
                                    break
                                code_chunk = None
                                await self._sync_chunk_end_delims(session.code_chunks[delim_dict['chunk']])
                            else:
                                if output_type != delim_output_type or code_chunk is None:
                                    self._delim_error = True
                                    session.code_chunks[delim_dict['chunk']].errors.append(message.RuntimeSourceError(
                                        'Code chunk is not a complete unit of code or is invalid.'
                                    ))
                                    break
                                output_type = stream_type
                        else:
                            raise ValueError
                        delim_start_index = unprocessed_output.find(run_delim_start_search_pattern)
            if unprocessed_output:
                buffer.append(unprocessed_output)
