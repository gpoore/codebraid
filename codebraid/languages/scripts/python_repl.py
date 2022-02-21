# -*- coding: utf-8 -*-
#
# Copyright (c) 2021-2022, Geoffrey M. Poore
# All rights reserved.
#
# Licensed under the BSD 3-Clause License:
# http://opensource.org/licenses/BSD-3-Clause
#

'''
Python REPL emulation for Codebraid.  Reads code interspersed with delimiters
from stdin.  Writes code plus output interspersed with delimiters to stdout.
'''


import code
import io
import sys


# Prevent apport systems in some Linux distributions from breaking
# exception handling
sys.excepthook = sys.__excepthook__

# A sequence of ASCII characters at the start of any line that is a
# Codebraid delimiter line.
delim_start = sys.argv[1]
# The unique hash (hex) that identifies the code being executed.  This is
# present in any delimiter line and is used to avoid `delim_start` causing
# false positives in identifying delimiter lines.
hash = sys.argv[2]
# Optional buffering mode.
buffering = sys.argv[3] if len(sys.argv) > 3 else 'line'


sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf8')
if buffering == 'line':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf8', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf8', line_buffering=True)
elif buffering == 'unbuffered':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf8', write_through=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf8', write_through=True)
elif buffering == 'buffered':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf8')
else:
    raise ValueError

def parse_delim(delim_line: str):
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
    if k_v_dict['hash'] != hash:
        raise ValueError
    return k_v_dict




class Console(code.InteractiveConsole):
    def __init__(self):
        super().__init__(filename='<stdin>')
        self._line_iter = (line.rstrip('\n') for line in sys.stdin)
        self._cached_line = None
        self._last_line = None

    def raw_input(self, prompt):
        line = self._cached_line
        self._cached_line = None
        while True:
            if line is None:
                try:
                    line = next(self._line_iter)
                except StopIteration:
                    raise EOFError
            if line.startswith(delim_start):
                try:
                    delim_dict = parse_delim(line)
                except Exception:
                    break
                if prompt == sys.ps2:
                    if (delim_dict['delim'] == 'end' and delim_dict['output'] == 'repl' and
                            delim_dict['chunk'] == delim_dict['output_chunk'] and self._last_line):
                        self._cached_line = line
                        line = ''
                        break
                    raise EOFError
                if delim_dict['output'] == 'repl':
                    print(f'\n{line}')
                elif delim_dict['output'] == 'stdout':
                    print(f'\n{line}', flush=True)
                elif delim_dict['output'] == 'stderr':
                    print(f'\n{line}', file=sys.stderr, flush=True)
                else:
                    raise ValueError
                line = None
                continue
            break
        self._last_line = line
        if line:
            print(f'{prompt}{line}')
        else:
            print(prompt.rstrip())
        return line

    def write(self, text):
        print(text, end='')


console = Console()
console.interact(banner='', exitmsg='')
