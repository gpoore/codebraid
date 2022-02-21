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
import datetime
import time
import textwrap
from typing import Callable, Deque, Dict, Iterable, List, Optional
from .terminal import stderr_term
from .code_chunks import CodeChunk, CodeKey
from .code_collections import Code, Session, Source
from . import util




class Progress(object):
    '''
    Centralized tracking of Codebraid progress, from parsing original document
    source files to executing code to postprocessing.  This makes possible a
    terminal progress display with customizable levels of detail.  It also
    makes possible arbitrary tasks that use code output immediately after it
    becomes available.
    '''
    def __init__(self):
        self._last_error_counts: Dict[CodeKey, int] = {}
        self._error_count: int = 0
        self._last_warning_counts: Dict[CodeKey, int] = {}
        self._warning_count: int = 0

        self._session_total_chunks_count: int = 0
        self._session_exec_chunks_count: int = 0
        self._session_exec_completed_chunks_count: int = 0
        self._session_exec_last_completed_chunk_count: Dict[CodeKey, int] = collections.defaultdict(int)

        self._current_task: Optional[str] = None
        self._current_subtask: Optional[str] = None
        self._last_task: Optional[str] = None
        self._last_subtask: Optional[str] = None
        self._last_progress_time: float = time.monotonic()
        if self.term.isatty:
            ellipsis_sequence = ['   ', '.  ', '.. ', '...']
        else:
            ellipsis_sequence = ['   ']
        self._progress_ellipsis_deque: Deque = collections.deque(ellipsis_sequence)
        self._in_live_output: bool = False
        self._last_live_output: Optional[str] = None
        self._last_live_output_stream: Optional[str] = None
        self._live_output_backlog: List[str] = []


    term = stderr_term


    _first_textwrappers = util.KeyDefaultDict(
        lambda columns: textwrap.TextWrapper(width=columns, initial_indent='  * ', subsequent_indent=' '*4)
    )
    _subsequent_textwrappers = util.KeyDefaultDict(
        lambda columns: textwrap.TextWrapper(width=columns, initial_indent=' '*4, subsequent_indent=' '*4)
    )


    def _register_codes(self, codes: Iterable[Code]):
        for code in codes:
            self._last_error_counts[code.key] = code.status.error_count
            self._error_count += code.status.error_count
            self._last_warning_counts[code.key] = code.status.warning_count
            self._warning_count += code.status.warning_count

    def register_sources(self, sources: Iterable[Source]):
        self._register_codes(sources)

    def register_sessions(self, sessions: Iterable[Session]):
        self._register_codes(sessions)
        self._session_total_chunks_count = sum(len(s.code_chunks) for s in sessions)
        self._session_exec_chunks_count = self._session_total_chunks_count


    def _code_messages_to_summary_list(self, code: Code, *, msg_type: str, columns: int) -> List[str]:
        first_textwrapper = self._first_textwrappers[columns]
        subsequent_textwrapper = self._subsequent_textwrappers[columns]
        if msg_type == 'errors':
            fmt_msg_type = self.term.fmt_error
        elif msg_type == 'warnings':
            fmt_msg_type = self.term.fmt_warning
        else:
            raise ValueError
        summary_list = []
        for msg in getattr(code, msg_type):
            if msg.is_refed:
                continue
            if summary_list:
                summary_list.append('')
            for line in first_textwrapper.wrap(f'"{code.code_chunks[0].origin_name}":'):
                summary_list.append(fmt_msg_type(line))
            for line in msg.message:
                summary_list.extend(subsequent_textwrapper.wrap(line))
        for cc in code.code_chunks:
            for msg in getattr(cc, msg_type):
                if msg.is_refed:
                    continue
                if summary_list:
                    summary_list.append('')
                for line in first_textwrapper.wrap(f'"{cc.origin_name}", line {cc.origin_start_line_number}:'):
                    summary_list.append(fmt_msg_type(line))
                for line in msg.message:
                    summary_list.extend(subsequent_textwrapper.wrap(line))
        return summary_list

    def _summarize_code_messages(self, code: Code, *, columns: int) -> str:
        summary_list = []
        if code.status.has_errors:
            summary_list.append(self.term.fmt_error('Errors:'))
            summary_list.extend(self._code_messages_to_summary_list(code, msg_type='errors', columns=columns))
        if code.status.has_warnings:
            summary_list.append(self.term.fmt_warning('Warnings:'))
            summary_list.extend(self._code_messages_to_summary_list(code, msg_type='warnings', columns=columns))
        summary_list.append('')
        return '\n'.join(summary_list)


    def _update_progress(self):
        '''
        Update terminal progress summary, which includes current task, current
        error and warnings counts, and code execution progress.
        '''
        if self._current_task is None:
            return
        if self._last_live_output is not None and not self._last_live_output.endswith('\n'):
            return
        time_now = time.monotonic()
        if (not self._in_live_output and
                self._current_task == self._last_task and self._current_subtask == self._last_subtask and
                time_now - self._last_progress_time < 1.0):
            return
        error_status = f'Errors: {self._error_count}'
        if self._error_count > 0:
            error_status_fmted = self.term.fmt_error(error_status)
        else:
            error_status_fmted = self.term.fmt_ok(error_status)
        warning_status = f'Warnings: {self._warning_count}'
        if self._warning_count > 0:
            warning_status_fmted = self.term.fmt_warning(warning_status)
        else:
            warning_status_fmted = self.term.fmt_ok(warning_status)
        if self._current_task == self._last_task:
            self._progress_ellipsis_deque.rotate(-1)
        else:
            while self._progress_ellipsis_deque[0] != '   ':
                self._progress_ellipsis_deque.rotate(-1)
        ellipsis = self._progress_ellipsis_deque[0]
        if self._current_subtask is None:
            task_w_subtask = self._current_task
            if self._current_task != 'Complete':
                task_w_subtask_fmted = self._current_task
            elif self._error_count > 0:
                task_w_subtask_fmted = self.term.fmt_error(self._current_task)
            elif self._warning_count > 0:
                task_w_subtask_fmted = self.term.fmt_warning(self._current_task)
            else:
                task_w_subtask_fmted = self.term.fmt_ok(self._current_task)
        else:
            task_w_subtask = f'{self._current_task}: {self._current_subtask}'
            task_w_subtask_fmted = task_w_subtask
        general_status = f'{task_w_subtask}{ellipsis} {error_status}  {warning_status}'
        general_status_fmted = f'{task_w_subtask_fmted}{ellipsis} {error_status_fmted}  {warning_status_fmted}'
        if self._current_task == 'Exec' and self._current_subtask == 'run':
            exec_status = f'  code chunk {self._session_exec_completed_chunks_count}/{self._session_exec_chunks_count}'
            bar_width = self.term.columns() - len(general_status) - len(exec_status) - 3
            finished_ratio = self._session_exec_completed_chunks_count / self._session_exec_chunks_count
            finished = round(finished_ratio*bar_width)
            unfinished = bar_width - finished
            bar = f''' [{'#'*finished}{'.'*unfinished}]'''
            filler = ''
        else:
            exec_status = ''
            bar = ''
            filler = ' '*(self.term.columns() - len(general_status))
        if self.term.isatty:
            progress_text = f'\r{general_status_fmted}{exec_status}{bar}{filler}'
        else:
            progress_text = f'PROGRESS: {general_status_fmted}{exec_status}{bar}\n'
        self._last_task = self._current_task
        self._last_subtask = self._current_subtask
        self._last_progress_time = time_now
        print(progress_text, file=self.term.stream, end='', flush=True)


    async def ticktock(self):
        '''
        Update terminal progress summary at 1 second intervals.
        '''
        if self.term.isatty:
            while True:
                try:
                    await asyncio.sleep(1)
                    self._update_progress()
                except asyncio.CancelledError:
                    break


    def _print_live_heading(self, code: Code, *, notification_type: str, title: str,
                            columns: int, flush: bool, clearline: bool,
                            content_sep: bool=True, chunk: Optional[CodeChunk]=None):
        output_list = []
        if clearline:
            output_list.append(self.term.clearline(columns))
        output_list.append(self.term.fmt_delim('='*columns))
        datetime_now = datetime.datetime.now()
        timestamp = f'[{datetime_now.hour:02d}:{datetime_now.minute:02d}:{datetime_now.second:02d}]'
        sep = ' '*(columns-len(notification_type)-2-len(title)-len(timestamp))
        output_list.append(self.term.fmt_notify(f'{notification_type}: {title}{sep}{timestamp}'))
        if chunk is None:
            chunk_progress = ''
            chunk_traceback = ''
        else:
            chunk_progress = f', code chunk {chunk.index+1}/{len(code.code_chunks)}'
            chunk_traceback = f'\n"{chunk.origin_name}", line {chunk.origin_start_line_number}'
        output_list.append(self.term.fmt_notify(f'{code.lang}, {code.type} "{code.name or "<default>"}"{chunk_progress}{chunk_traceback}'))
        if content_sep:
            output_list.append(self.term.fmt_delim('.'*columns))
        print('\n'.join(output_list), file=self.term.stream, flush=flush)

    def _print_live_closing(self, code: Code, *, notification_type: str, title: str,
                            columns: int, flush: bool, clearline: bool, chunk: Optional[CodeChunk]=None):
        output_list = []
        if self._last_live_output is not None and not self._last_live_output.endswith('\n'):
            output_list.append('\n')
        if clearline:
            output_list.append(self.term.clearline(columns))
        output_list.append(self.term.fmt_delim('-'*columns))
        output_list.append('\n')
        print(''.join(output_list), file=self.term.stream, flush=flush)

    def _print_live_notification(self, code: Code, *, notification_type: str, title: str,
                                 columns: Optional[int]=None, text: Optional[str]=None):
        if columns is None:
            columns = self.term.columns()
        self._print_live_heading(code, notification_type=notification_type, title=title,
                                 columns=columns, flush=False, clearline=self.term.isatty,
                                 content_sep=text is not None)
        if text is not None:
            if text.endswith('\n'):
                print(text, file=self.term.stream, end='')
            else:
                print(text, file=self.term.stream)
        self._print_live_closing(code, notification_type=notification_type, title=title,
                                 columns=columns, flush=True, clearline=False)

    def _print_live_output(self, output: str, *, stream: str, fmter: Optional[Callable[[str], str]]=None):
        if self._last_live_output is not None and not self._last_live_output.endswith('\n'):
            if stream == self._last_live_output_stream:
                if fmter is None:
                    print(output, file=self.term.stream, end='', flush=True)
                else:
                    print(fmter(output), file=self.term.stream, end='', flush=True)
                self._last_live_output = output
                self._last_live_output_stream = stream
            elif stream == 'stderr':
                if '\r' in output and ('\n' not in output or output.find('\r') < output.find('\n')):
                    print('\n', file=self.term.stream, end='')
                if fmter is None:
                    print(output, file=self.term.stream, end='', flush=True)
                else:
                    print(fmter(output), file=self.term.stream, end='', flush=True)
                self._last_live_output = output
                self._last_live_output_stream = stream
            else:
                self._live_output_backlog.append((output, stream, fmter))
            return
        if self.term.isatty:
            print(self.term.clearline(), file=self.term.stream, end='')
        if not self._live_output_backlog:
            if fmter is None:
                print(output, file=self.term.stream, end='', flush=True)
            else:
                print(fmter(output), file=self.term.stream, end='', flush=True)
            self._last_live_output = output
            self._last_live_output_stream = stream
            return
        new_backlog = []
        for backlog_output, backlog_stream, backlog_fmter in self._live_output_backlog:
            if self._last_live_output.endswith('\n') or backlog_stream == self._last_live_output_stream:
                if backlog_fmter is None:
                    print(backlog_output, file=self.term.stream, end='')
                else:
                    print(backlog_fmter(backlog_output), file=self.term.stream, end='')
                self._last_live_output = backlog_output
                self._last_live_output_stream = backlog_stream
            else:
                new_backlog.append((backlog_output, backlog_stream, backlog_fmter))
        self._live_output_backlog = new_backlog
        if self._last_live_output.endswith('\n'):
            if fmter is None:
                print(output, file=self.term.stream, end='')
            else:
                print(fmter(output), file=self.term.stream, end='')
            self._last_live_output = output
            self._last_live_output_stream = stream
        elif stream == 'stderr':
            if '\r' in output and ('\n' not in output or output.find('\r') < output.find('\n')):
                print('\n', file=self.term.stream, end='')
            if fmter is None:
                print(output, file=self.term.stream, end='')
            else:
                print(fmter(output), file=self.term.stream, end='')
            self._last_live_output = output
            self._last_live_output_stream = stream
        else:
            self._live_output_backlog.append((output, stream, fmter))
        self.term.stream.flush()


    def _update_message_count(self, code: Code):
        self._error_count += code.status.error_count - self._last_error_counts[code.key]
        self._last_error_counts[code.key] = code.status.error_count
        self._warning_count += code.status.warning_count - self._last_warning_counts[code.key]
        self._last_warning_counts[code.key] = code.status.warning_count


    def parse_start(self):
        self._current_task = 'Parse'
        self._current_subtask = None
        self._update_progress()

    def parse_end(self):
        pass

    def process_start(self):
        self._current_task = 'Process'
        self._current_subtask = None
        self._update_progress()

    def process_end(self):
        pass

    def exec_start(self):
        self._current_task = 'Exec'
        self._current_subtask = None
        self._update_progress()

    def exec_end(self):
        pass

    def postprocess_start(self):
        self._current_task = 'Postprocess'
        self._current_subtask = None
        self._update_progress()

    def postprocess_end(self):
        pass

    def convert_start(self):
        self._current_task = 'Convert'
        self._current_subtask = None
        self._update_progress()

    def convert_end(self):
        pass

    def complete(self):
        self._current_task = 'Complete'
        self._update_progress()


    def session_load_cache(self, session: Session):
        self._update_message_count(session)
        self._session_exec_chunks_count -= len(session.code_chunks)
        if session.live_output:
            self._in_live_output = True
            self._print_live_notification(session, notification_type='SESSION', title='LOADED CACHE')
        self._update_progress()


    def session_exec_stage_start(self, session: Session, *, stage: str):
        self._current_subtask = stage
        if session.live_output:
            self._in_live_output = True
            self._print_live_notification(session, notification_type='SESSION', title=f'START {stage.upper()}')
        self._update_progress()

    def session_exec_stage_output(self, session: Session, *, output: str):
        if session.live_output:
            self._print_live_output(output, stream='stdout')

    def session_exec_stage_end(self, session: Session, *, stage: str):
        self._update_message_count(session)
        self._update_progress()


    def _finished(self, code: Code):
        self._update_message_count(code)
        if code.live_output and (code.status.has_errors or code.status.has_warnings):
            columns = self.term.columns()
            self._print_live_notification(code, notification_type=f'{code.type.upper()}', title='SUMMARY',
                                          columns=columns, text=self._summarize_code_messages(code, columns=columns))
        self._update_progress()
        self._in_live_output = False

    def source_finished(self, source: Source):
        self._finished(source)

    def session_finished(self, session: Session):
        if session.did_exec:
            # If session exec is interrupted by errors, code chunk count may
            # be off because per-chunk progress wasn't registered
            delta = len(session.code_chunks) - self._session_exec_last_completed_chunk_count[session.key]
            self._session_exec_completed_chunks_count += delta
        self._finished(session)


    def chunk_start(self, session: Session, *, chunk: CodeChunk):
        if session.live_output:
            self._print_live_heading(session, chunk=chunk, notification_type='CODE CHUNK', title='LIVE OUTPUT',
                                     columns=self.term.columns(), flush=True, clearline=self.term.isatty)
        self._update_progress()

    def chunk_end(self, session: Session, *, chunk: CodeChunk):
        self._update_message_count(session)
        self._session_exec_completed_chunks_count += 1 + (chunk.output_index - chunk.index)
        self._session_exec_last_completed_chunk_count[session.key] = chunk.output_index + 1
        if session.live_output:
            self._print_live_closing(session, chunk=chunk, notification_type='CODE CHUNK', title='LIVE OUTPUT',
                                     columns=self.term.columns(), flush=True, clearline=self.term.isatty)
            self._last_live_output = None
            self._last_live_output_stream = None
        self._update_progress()


    def chunk_stdout(self, session: Session, *, chunk: Optional[CodeChunk], output: str):
        if session.live_output:
            self._print_live_output(output, stream='stdout')

    def chunk_stderr(self, session: Session, *, chunk: Optional[CodeChunk], output: str):
        if session.live_output:
            self._print_live_output(output, stream='stderr', fmter=self.term.fmt_error)

    def chunk_rich_output_text(self, session: Session, *, chunk: CodeChunk, output: str):
        if session.live_output:
            output_lines = util.splitlines_lf(output)
            columns = self.term.columns()
            output_list = ['RICH OUTPUT:']
            output_list.extend(self._first_textwrappers[columns].wrap(output_lines[0]))
            for line in output_lines[1:]:
                output_list.extend(self._subsequent_textwrappers[columns].wrap(line))
            output_list.append('')
            self._print_live_output('\n'.join(output_list), stream='rich_output', fmter=self.term.fmt_notify)

    def chunk_rich_output_files(self, session: Session, *, chunk: CodeChunk, files: Iterable[str]):
        if session.live_output:
            output_list = ['RICH OUTPUT FILES:\n']
            for file in files:
                output_list.append(f'  * {file}\n')
            self._print_live_output(''.join(output_list), stream='rich_output_files', fmter=self.term.fmt_notify)

    def chunk_expr(self, session: Session, *, chunk: CodeChunk, output: str):
        if session.live_output:
            output_list = ['EXPR:']
            output_list.extend(self._first_textwrappers[self.term.columns()].wrap(output))
            self._print_live_output('\n'.join(output_list), stream='expr', fmter=self.term.fmt_notify)

    def chunk_repl(self, session: Session, *, chunk: CodeChunk, output: str):
        if session.live_output:
            self._print_live_output(output, stream='repl')
