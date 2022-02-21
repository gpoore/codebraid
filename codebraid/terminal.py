# -*- coding: utf-8 -*-
#
# Copyright (c) 2021-2022, Geoffrey M. Poore
# All rights reserved.
#
# Licensed under the BSD 3-Clause License:
# http://opensource.org/licenses/BSD-3-Clause
#


from __future__ import annotations


import io
import os
import platform
import sys
from typing import Callable, Optional, TextIO


class Terminal(object):
    '''
    Utils for working with terminal to create output messages.
    '''
    def __init__(self, stream: TextIO):
        if not isinstance(stream, io.TextIOWrapper):
            raise TypeError
        if stream not in (sys.stdout, sys.stderr):
            raise ValueError

        self.stream: io.TextIOWrapper = stream

        self.isatty: bool = False
        self.columns: Callable[[], int] = self._columns_default
        self.supports_ansi_escape_codes: bool = False
        self.clearline: Callable[[Optional[int]], str] = self._clearline_plain
        self.fmt_ok: Callable[[str], str] = self._fmt_ok_plain
        self.fmt_ok_heading: Callable[[str], str] = self._fmt_ok_heading_plain
        self.fmt_error: Callable[[str], str] = self._fmt_error_plain
        self.fmt_error_heading: Callable[[str], str] = self._fmt_error_heading_plain
        self.fmt_warning: Callable[[str], str] = self._fmt_warning_plain
        self.fmt_warning_heading: Callable[[str], str] = self._fmt_warning_heading_plain
        self.fmt_notify: Callable[[str], str] = self._fmt_notify_plain
        self.fmt_notify_heading: Callable[[str], str] = self._fmt_notify_heading_plain
        self.fmt_delim: Callable[[str], str] = self._fmt_delim_plain

        if not stream.isatty():
            return

        get_terminal_size = os.get_terminal_size
        fileno = stream.fileno()
        if platform.system() == 'Windows' or platform.system().startswith('CYGWIN_NT'):
            # https://bugs.python.org/issue28654
            try:
                get_terminal_size(fileno)
            except OSError:
                return
            self.isatty = True
            if 'ALACRITTY_LOG' in os.environ or 'WT_SESSION' in os.environ:
                # Alacritty or Windows Terminal (https://github.com/microsoft/terminal/issues/1040)
                self.columns = lambda: get_terminal_size(fileno).columns
                self.supports_ansi_escape_codes = True
            else:
                # Many Windows terminal programs interpret a line consisting
                # of <columns> characters followed by a newline as two lines,
                # one line consisting of <columns> characters and one line
                # that is empty (from the newline).  For some but not all of
                # these, it is possible to use `\b\n` to avoid this.  The
                # simplest workaround is to treat the number of columns as one
                # less than the actual value.
                self.columns = lambda: get_terminal_size(fileno).columns - 1
                if os.environ.get('CONEMUANSI') == 'ON' or os.environ.get('TERM_PROGRAM') == 'mintty':
                    # ConEmu or Cmder; or Cygwin, Git for Windows BASH, MSYS, etc.
                    self.supports_ansi_escape_codes = True
            if self.supports_ansi_escape_codes:
                self.clearline = self._clearline_ansi_term
            else:
                self.clearline = self._clearline_win_term
        else:
            self.isatty = True
            self.columns = lambda: get_terminal_size(fileno).columns
            self.supports_ansi_escape_codes = True
            self.clearline = self._clearline_ansi_term
        if self.supports_ansi_escape_codes:
            self.fmt_ok = self._fmt_ok_ansi_color
            self.fmt_ok_heading = self._fmt_ok_heading_ansi_color
            self.fmt_error = self._fmt_error_ansi_color
            self.fmt_error_heading = self._fmt_error_heading_ansi_color
            self.fmt_warning = self._fmt_warning_ansi_color
            self.fmt_warning_heading = self._fmt_warning_heading_ansi_color
            self.fmt_notify = self._fmt_notify_ansi_color
            self.fmt_notify_heading = self._fmt_notify_heading_ansi_color
            self.fmt_delim = self._fmt_delim_ansi_color


    @staticmethod
    def _columns_default():
        return 80


    def _clearline_plain(self, columns: Optional[int]=None) -> str:
        return '\n'

    def _clearline_ansi_term(self, columns: Optional[int]=None) -> str:
        return '\x1b[2K\r'

    def _clearline_win_term(self, columns: Optional[int]=None) -> str:
        if columns is None:
            columns = self.columns()
        return '\r' + ' '*columns + '\r'


    @staticmethod
    def _fmt_ok_plain(string: str) -> str:
        return string

    @staticmethod
    def _fmt_ok_ansi_color(string: str) -> str:
        return f'\x1b[92m{string}\x1b[0m'

    @staticmethod
    def _fmt_ok_heading_plain(string: str) -> str:
        return string

    @staticmethod
    def _fmt_ok_heading_ansi_color(string: str) -> str:
        return f'\x1b[92;1m{string}\x1b[0m'


    @staticmethod
    def _fmt_error_plain(string: str) -> str:
        return string

    @staticmethod
    def _fmt_error_ansi_color(string: str) -> str:
        return f'\x1b[91m{string}\x1b[0m'

    @staticmethod
    def _fmt_error_heading_plain(string: str) -> str:
        return string

    @staticmethod
    def _fmt_error_heading_ansi_color(string: str) -> str:
        return f'\x1b[91;1m{string}\x1b[0m'


    @staticmethod
    def _fmt_warning_plain(string: str) -> str:
        return string

    @staticmethod
    def _fmt_warning_ansi_color(string: str) -> str:
        return f'\x1b[93m{string}\x1b[0m'

    @staticmethod
    def _fmt_warning_heading_plain(string: str) -> str:
        return string

    @staticmethod
    def _fmt_warning_heading_ansi_color(string: str) -> str:
        return f'\x1b[93;1m{string}\x1b[0m'


    @staticmethod
    def _fmt_notify_plain(string: str) -> str:
        return string

    @staticmethod
    def _fmt_notify_ansi_color(string: str) -> str:
        return f'\x1b[96m{string}\x1b[0m'

    @staticmethod
    def _fmt_notify_heading_plain(string: str) -> str:
        return string

    @staticmethod
    def _fmt_notify_heading_ansi_color(string: str) -> str:
        return f'\x1b[96;1m{string}\x1b[0m'


    @staticmethod
    def _fmt_delim_plain(string: str) -> str:
        return string

    @staticmethod
    def _fmt_delim_ansi_color(string: str) -> str:
        return f'\x1b[94m{string}\x1b[0m'


stdout_term = Terminal(sys.stdout)
stderr_term = Terminal(sys.stderr)
