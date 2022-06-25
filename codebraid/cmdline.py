# -*- coding: utf-8 -*-
#
# Copyright (c) 2019-2022, Geoffrey M. Poore
# All rights reserved.
#
# Licensed under the BSD 3-Clause License:
# http://opensource.org/licenses/BSD-3-Clause
#


from __future__ import annotations


import argparse
import io
import json
import pathlib
import sys
from . import converters
from . import util
from .version import __version__ as version




def main():
    class ArgumentParser(argparse.ArgumentParser):
        '''
        Custom argument parser that lists "[<PANDOC OPTIONS>]" in help,
        instead of either leaving them off altogether due to
        argparse.SUPPRESS, or listing them all and making help unnecessarily
        verbose.
        '''
        def print_help(self):
            original_stdout = sys.stdout
            try:
                temp_stdout = io.StringIO()
                sys.stdout = temp_stdout
                super().print_help()
                help_text = temp_stdout.getvalue()
            finally:
                sys.stdout = original_stdout
            try:
                before, after = help_text.split('[FILE', 1)
            except ValueError:
                print(help_text)
            else:
                indent = before.rsplit('\n', 1)[1]
                help_text = before + '[<PANDOC OPTIONS>]\n' + indent + '[FILE' + after
                help_text += '  [<PANDOC OPTIONS>]\n'
                help_text += indent + 'See output of "pandoc --help"\n'
                print(help_text)

    parser = ArgumentParser(prog='codebraid', allow_abbrev=False)
    parser.set_defaults(func=lambda x: parser.print_help())
    parser.add_argument('--version', action='version', version='Codebraid {0}'.format(version))
    subparsers = parser.add_subparsers(dest='subparser_name')

    parser_pandoc = subparsers.add_parser('pandoc',
                                          help='Execute code embedded in a document format supported by Pandoc (requires Pandoc >= 2.4)')
    parser_pandoc.set_defaults(func=pandoc)
    parser_pandoc.add_argument('-f', '--from', '-r', '--read', dest='from_format',
                               help='From format (may include Pandoc format extensions: format+ext1-ext2)')
    parser_pandoc.add_argument('-t', '--to', '-w', '--write', dest='to_format',
                               help='To format (may include Pandoc format extensions: format+ext1-ext2)')
    parser_pandoc.add_argument('-o', '--output',
                               help='File for saving output (otherwise it is written to stdout)')
    parser_pandoc.add_argument('--overwrite',
                               help='Overwrite existing files',
                               action='store_true')
    parser_pandoc.add_argument('-s', '--standalone', action='store_true',
                               help=argparse.SUPPRESS)
    parser_pandoc.add_argument('--file-scope', action='store_true', dest='pandoc_file_scope',
                               help=argparse.SUPPRESS)
    parser_pandoc.add_argument('--no-cache', action='store_true',
                               help='Do not cache code output so that code is always executed during each build '
                                    '(a cache directory may still be created for use with temporary files)')
    parser_pandoc.add_argument('--cache-dir',
                               help='Location for caching code output (default is "_codebraid" in document directory)')
    parser_pandoc.add_argument('--live-output', action='store_true',
                               help='Show code output (stdout and stderr) live in the terminal during code execution. '
                                    'For Jupyter kernels, also show  errors and a summary of rich output. '
                                    'Output still appears in the document as normal. '
                                    'Individual sessions can override this by setting live_output=false in the document.')
    parser_pandoc.add_argument('--no-execute', action='store_true',
                               help='Disable code execution.  Only load code output from cache, if it exists.')
    parser_pandoc.add_argument('--only-code-output', metavar='FORMAT',
                               help='Write code output to stdout in the specified format. '
                                    'Cached output is written immediately. '
                                    'Output from execution is written as soon as it becomes available. '
                                    'No document is created. '
                                    'Options --to and --output are only used (if at all) to inform code output formatting.')
    parser_pandoc.add_argument('--stdin-json-header', action='store_true',
                               help='Treat the first line of stdin as a header in JSON format containing data about stdin such as file origin.')
    parser_pandoc.add_argument('files', nargs='*', metavar='FILE',
                               help="Files (multiple files are allowed for formats supported by Pandoc)")
    for opts_or_long_opt, narg in PANDOC_OPTIONS.items():
        if isinstance(opts_or_long_opt, tuple):
            short_opt, long_opt = opts_or_long_opt
        else:
            short_opt, long_opt = (None, opts_or_long_opt)
        if narg == 0:
            if short_opt is None:
                parser_pandoc.add_argument(long_opt, action='store_true', dest=long_opt,
                                           help=argparse.SUPPRESS)
            else:
                parser_pandoc.add_argument(short_opt, long_opt, action='store_true', dest=long_opt,
                                           help=argparse.SUPPRESS)
        elif narg == 1:
            if short_opt is None:
                parser_pandoc.add_argument(long_opt, dest=long_opt, action='append',
                                           help=argparse.SUPPRESS)
            else:
                parser_pandoc.add_argument(short_opt, long_opt, dest=long_opt, action='append',
                                           help=argparse.SUPPRESS)
        elif narg == '?':
            if short_opt is None:
                parser_pandoc.add_argument(long_opt, nargs='?', const=True, default=None, dest=long_opt,
                                           help=argparse.SUPPRESS)
            else:
                parser_pandoc.add_argument(short_opt, long_opt, nargs='?', const=True, default=None, dest=long_opt,
                                           help=argparse.SUPPRESS)
        else:
            raise ValueError

    args = parser.parse_args()
    args.func(args)




def pandoc(args):
    # Stay consistent with Pandoc's requirement of UTF-8
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf_8_sig')

    other_pandoc_args = []
    if vars(args).get('--defaults') is not None:
        if args.from_format is None:
            sys.exit('Must specify input format ("--from" or "--read") when using default options ("--defaults")')
        if args.to_format is None:
            sys.exit('Must specify output format ("--to" or "--write") when using default options ("--defaults")')
        if args.output is None:
            sys.exit('Must specify output file ("--output") when using default options ("--defaults"); for stdout, use "-o -"')
    if args.output == '-':
        args.output = None
    for k, v in vars(args).items():
        if isinstance(k, str) and k.startswith('--') and v not in (None, False):
            if isinstance(v, list):
                for v_i in v:
                    other_pandoc_args.append(k)
                    other_pandoc_args.append(v_i)
            elif k in ('--katex', '--mathjax', '--webtex') and not isinstance(v, bool):
                other_pandoc_args.append(f'{k}={v}')
            else:
                other_pandoc_args.append(k)
                if not isinstance(v, bool):
                    other_pandoc_args.append(v)

    if not args.files or (len(args.files) == 1 and args.files[0] == '-'):
        paths = None
        string_origins = None
        try:
            strings = sys.stdin.read()
        except UnicodeDecodeError as e:
            sys.exit(f'Input must be UTF-8:\n{e}')
        if args.stdin_json_header:
            stdin_lines = util.splitlines_lf(strings)
            if not stdin_lines:
                sys.exit('Missing data for --stdin-json-header')
            if len(stdin_lines) == 1:
                stdin_lines.append('')
            json_header_str = stdin_lines[0]
            try:
                json_header = json.loads(json_header_str)
            except Exception as e:
                sys.exit(f'Invalid data for --stdin-json-header:\n{e}')
            if not isinstance(json_header, dict):
                sys.exit(f'Invalid data for --stdin-json-header: expected dict')
            json_header_origins = json_header.get('origins')
            if json_header_origins is not None:
                if not isinstance(json_header_origins, list):
                    sys.exit('Invalid data for --stdin-json-header field "string_origins"')
                start_line = 1
                strings = []
                string_origins = []
                for entry in json_header_origins:
                    origin_name = entry['path']
                    origin_length = entry['lines']
                    string_origins.append(origin_name)
                    strings.append('\n'.join(stdin_lines[start_line:start_line+origin_length]))
                    start_line += origin_length
            else:
                strings = '\n'.join(stdin_lines[1:])
    else:
        paths = args.files
        strings = None
        string_origins = None

    code_defaults = {}
    session_defaults = {}
    if args.live_output:
        session_defaults['live_output'] = args.live_output

    preview = False
    other_pandoc_args_at_load = None
    for n, arg in enumerate(other_pandoc_args):
        if n > 0 and 'pandoc-sourcepos-sync' in arg and other_pandoc_args[n-1] in ('-L', '--lua-filter'):
            other_pandoc_args_at_load = other_pandoc_args[n-1:n+1]
            other_pandoc_args = other_pandoc_args[:n-1] + other_pandoc_args[n+1:]
            preview = True
            break

    if args.output in (None, '-'):
        output_path = None
    else:
        output_path = pathlib.Path(args.output).expanduser()
        if not args.overwrite and output_path.is_file():
            # There is also a check for this in `converter.convert()`, but should
            # fail early.
            sys.exit(f'File "{args.output}" already exists (to replace it, add option "--overwrite")')
    with converters.PandocConverter(
        paths=paths,
        strings=strings,
        string_origins=string_origins,
        from_format=args.from_format,
        pandoc_file_scope=args.pandoc_file_scope,
        no_cache=args.no_cache,
        cache_path=args.cache_dir,
        code_defaults=code_defaults,
        session_defaults=session_defaults,
        other_pandoc_args_at_load=other_pandoc_args_at_load,
        no_execute=args.no_execute,
        only_code_output=args.only_code_output,
    ) as converter:
        if not args.only_code_output:
            converter.convert(
                to_format=args.to_format,
                standalone=args.standalone,
                output_path=output_path,
                overwrite=args.overwrite,
                other_pandoc_args=other_pandoc_args
            )
        exit_code = converter.exit_code

    sys.exit(exit_code)


PANDOC_OPTIONS  = {
    '--data-dir': 1,
    '--base-header-level': 1,
    '--strip-empty-paragraphs': 0,
    '--indented-code-classes': 1,
    ('-F', '--filter'): 1,
    ('-L', '--lua-filter'): 1,
    '--shift-heading-level-by': 1,
    ('-p', '--preserve-tabs'): 0,
    '--tab-stop': 1,
    '--track-changes': 1,
    '--extract-media': 1,
    '--template': 1,
    ('-M', '--metadata'): 1,
    '--metadata-file': 1,
    ('-d', '--defaults'): 1,
    ('-V', '--variable'): 1,
    '--dpi': 1,
    '--eol': 1,
    '--wrap': 1,
    '--columns': 1,
    '--strip-comments': 0,
    '--toc': 0,
    '--table-of-contents': 0,
    '--toc-depth': 1,
    '--no-highlight': 0,
    '--highlight-style': 1,
    '--syntax-definition': 1,
    ('-H', '--include-in-header'): 1,
    ('-B', '--include-before-body'): 1,
    ('-A', '--include-after-body'): 1,
    '--resource-path': 1,
    '--request-header': 1,
    '--abbreviations': 1,
    '--self-contained': 0,
    '--html-q-tags': 0,
    '--ascii': 0,
    '--reference-links': 0,
    '--reference-location': 1,
    '--atx-headers': 0,
    '--top-level-division': 1,
    ('-N', '--number-sections'): 0,
    '--number-offset': 1,
    '--listings': 0,
    ('-i', '--incremental'): 0,
    '--slide-level': 1,
    '--section-divs': 0,
    '--default-image-extension': 1,
    '--email-obfuscation': 1,
    '--id-prefix': 1,
    ('-T', '--title-prefix'): 1,
    ('-c', '--css'): 1,
    '--reference-doc': 1,
    '--epub-subdirectory': 1,
    '--epub-cover-image': 1,
    '--epub-metadata': 1,
    '--epub-embed-font': 1,
    '--epub-chapter-level': 1,
    '--pdf-engine': 1,
    '--pdf-engine-opt': 1,
    '--ipynb-output': 1,
    ('-C', '--citeproc'): 0,
    '--bibliography': 1,
    '--csl': 1,
    '--citation-abbreviations': 1,
    '--natbib': 0,
    '--biblatex': 0,
    '--mathml': 0,
    '--webtex': '?',
    '--mathjax': '?',
    '--katex': '?',
    '--gladtex': 0,
    '--trace': 0,
    '--dump-args': 0,
    '--ignore-args': 0,
    '--verbose': 0,
    '--quiet': 0,
    '--fail-if-warnings': 0,
    '--log': 1,
    '--bash-completion': 0,
}
