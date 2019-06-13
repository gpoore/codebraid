# -*- coding: utf-8 -*-
#
# Copyright (c) 2019, Geoffrey M. Poore
# All rights reserved.
#
# Licensed under the BSD 3-Clause License:
# http://opensource.org/licenses/BSD-3-Clause
#


import argparse
import sys
from . import converters
from .version import __version__ as version




def main():
    parser = argparse.ArgumentParser(prog='codebraid')
    parser.set_defaults(func=lambda x: parser.print_help())
    parser.add_argument('--version', action='version', version='Codebraid {0}'.format(version))
    subparsers = parser.add_subparsers(dest='subparser_name')

    parser_pandoc = subparsers.add_parser('pandoc',
                                          help='Execute code embedded in a document format supported by Pandoc (requires Pandoc >= 2.4)')
    parser_pandoc.set_defaults(func=pandoc)
    parser_pandoc.add_argument('-f', '--from', dest='from_format',
                               help='From format (may include Pandoc format extensions: format+ext1-ext2)')
    parser_pandoc.add_argument('-t', '--to', dest='to_format',
                               help='To format (may include Pandoc format extensions: format+ext1-ext2)')
    parser_pandoc.add_argument('-o', '--output',
                               help='File for saving output (otherwise it is written to stdout)')
    parser_pandoc.add_argument('--overwrite',
                               help='Overwrite existing files',
                               action='store_true')
    parser_pandoc.add_argument('-s', '--standalone', action='store_true',
                               help='Create Pandoc standalone document')
    parser_pandoc.add_argument('--file-scope', action='store_true', dest='pandoc_file_scope',
                               help='Pandoc parses multiple files individually before merging their output, instead of merging before parsing')
    parser_pandoc.add_argument('--no-cache', action='store_true',
                               help='Do not cache code output (all code will be executed on each run)')
    parser_pandoc.add_argument('--cache-dir',
                               help='Location for caching code output (default is "_codebraid" in document directory)')
    parser_pandoc.add_argument('files', nargs='+', metavar='FILE',
                               help="Files (multiple files are allowed for formats supported by Pandoc)")
    for opt, narg in PANDOC_OPTIONS.items():
        if narg == 0:
            parser_pandoc.add_argument(opt, action='store_true', dest=opt,
                                       help='Pandoc option; see Pandoc documentation')
        elif narg == 1:
            parser_pandoc.add_argument(opt, dest=opt, metavar='PANDOC',
                                       help='Pandoc option; see Pandoc documentation')
        elif narg == '?':
            parser_pandoc.add_argument(opt, nargs='?', const=True, default=None, dest=opt, metavar='PANDOC',
                                       help='Pandoc option; see Pandoc documentation')
        else:
            raise ValueError

    args = parser.parse_args()
    args.func(args)




def pandoc(args):
    other_pandoc_args = []
    for k, v in vars(args).items():
        if isinstance(k, str) and k.startswith('--') and v not in (None, False):
            other_pandoc_args.append(k)
            if not isinstance(v, bool):
                other_pandoc_args.append(v)

    converter = converters.PandocConverter(paths=args.files,
                                           from_format=args.from_format,
                                           pandoc_file_scope=args.pandoc_file_scope,
                                           no_cache=args.no_cache,
                                           cache_path=args.cache_dir)
    converter.code_braid()
    converter.convert(to_format=args.to_format, standalone=args.standalone,
                      output_path=args.output, overwrite=args.overwrite,
                      other_pandoc_args=other_pandoc_args)

PANDOC_OPTIONS  = {
    '--data-dir': 1,
    '--base-header-level': 1,
    '--strip-empty-paragraphs': 0,
    '--indented-code-classes': 1,
    '--filter': 1,
    '--lua-filter': 1,
    '--preserve-tabs': 0,
    '--tab-stop': 1,
    '--track-changes': 1,
    '--extract-media': 1,
    '--template': 1,
    '--metadata': 1,
    '--metadata-file': 1,
    '--variable': 1,
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
    '--include-in-header': 1,
    '--include-before-body': 1,
    '--include-after-body': 1,
    '--resource-path': 1,
    '--request-header': 1,
    '--self-contained': 0,
    '--html-q-tags': 0,
    '--ascii': 0,
    '--reference-links': 0,
    '--reference-location': 1,
    '--atx-headers': 0,
    '--top-level-division': 1,
    '--number-sections': 0,
    '--number-offset': 1,
    '--listings': 0,
    '--incremental': 0,
    '--slide-level': 1,
    '--section-divs': 0,
    '--default-image-extension': 1,
    '--email-obfuscation': 1,
    '--id-prefix': 1,
    '--title-prefix': 1,
    '--css': 1,
    '--reference-doc': 1,
    '--epub-subdirectory': 1,
    '--epub-cover-image': 1,
    '--epub-metadata': 1,
    '--epub-embed-font': 1,
    '--epub-chapter-level': 1,
    '--pdf-engine': 1,
    '--pdf-engine-opt': 1,
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
    '--abbreviations': 1,
    '--trace': 0,
    '--dump-args': 0,
    '--ignore-args': 0,
    '--verbose': 0,
    '--quiet': 0,
    '--fail-if-warnings': 0,
    '--log': 1,
    '--bash-completion': 0,
}
