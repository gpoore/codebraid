# -*- coding: utf-8 -*-
#
# Copyright (c) 2018, Geoffrey M. Poore
# All rights reserved.
#
# Licensed under the BSD 3-Clause License:
# http://opensource.org/licenses/BSD-3-Clause
#


import json
import os
import pathlib
import platform
import re
import subprocess
from typing import Optional, Union
from .base import Converter
from .. import err




class PandocError(err.CodebraidError):
    pass




class PandocCodeChunk(object):
    pass




class PandocConverter(Converter):
    '''
    Converter based on Pandoc (https://pandoc.org/).

    Pandoc is used to parse input into a JSON-based AST.  Code nodes in the
    AST are located, processed, and then replaced with raw nodes.  Next, the
    AST is converted back into the original input format (or possibly another
    format), and reparsed into a new AST.  This allows raw code output to be
    interpreted as markup.  Finally, the new AST is converted into the output
    format.
    '''
    def __init__(self, *,
                 pandoc_path: Optional[Union[str, pathlib.Path]]=None,
                 from_format_extensions: Optional[str]=None,
                 expanduser: bool=False,
                 expandvars: bool=False,
                 **kwargs):
        if pandoc_path is None:
            pandoc_path = pathlib.Path('pandoc')
        else:
            if isinstance(pandoc_path, str):
                pandoc_path = pathlib.Path(pandoc_path)
            elif not isinstance(pandoc_path, pathlib.Path):
                raise TypeError
            if expandvars:
                pandoc_path = pathlib.Path(os.path.expandvars(pandoc_path))
            if expanduser:
                pandoc_path = pandoc_path.expanduser()
            if not pandoc_path.exists():
                raise ValueError
        self.pandoc_path = pandoc_path
        if from_format_extensions is not None and not isinstance(from_format_extensions, str):
            raise TypeError
        self.from_format_extensions = from_format_extensions
        super().__init__(**kwargs, expanduser=expanduser, expandvars=expandvars)


    from_formats = set(['markdown'])
    to_formats = set(['json', 'markdown', 'html', 'latex'])
    multi_source_formats = set(['markdown'])


    # Node sets are based on pandocfilters
    # https://github.com/jgm/pandocfilters/blob/master/pandocfilters.py
    _block_node_types = set(['Plain', 'Para', 'CodeBlock', 'RawBlock',
                             'BlockQuote', 'OrderedList', 'BulletList',
                             'DefinitionList', 'Header', 'HorizontalRule',
                             'Table', 'Div', 'Null'])
    # Block nodes that appear in `--trace` output and are leaf nodes as far as
    # that is concerned (these nodes may contain block nodes, but those
    # internal nodes don't appear in the trace output).  This should
    # technically contain Null nodes as well (trace nodes with the empty
    # string as their name), but algorithms are simpler if those are omitted.
    # Nulls are passed through like internal nodes rather than requiring
    # additional processing like leaf nodes.
    _trace_leaf_block_node_types = _block_node_types - set(['BlockQuote',
                                                            'OrderedList',
                                                            'BulletList',
                                                            'DefinitionList',
                                                            'Div'])
    # Block nodes that appear in `--trace` output that initiate chunk-based
    # line counting (for lists, this is on a per-item basis)
    _trace_chunk_block_node_types = set(t for t in _block_node_types if t.endswith('Quote') or t.endswith('List'))
    _code_node_types = set(['CodeBlock', 'Code'])
    _raw_node_types = set(['RawBlock', 'RawInline'])


    def _run_pandoc(self, *,
                    from_format: str,
                    to_format: str,
                    from_format_extensions: Optional[str]=None,
                    to_format_extensions: Optional[str]=None,
                    input: Optional[str]=None,
                    input_path: Optional[pathlib.Path]=None,
                    input_name: Optional[str]=None,
                    output_path: Optional[pathlib.Path]=None,
                    overwrite: bool=False,
                    standalone: bool=False,
                    trace: bool=False):
        '''
        Convert between formats using Pandoc.

        Communication with Pandoc is accomplished via pipes.
        '''
        # Allow from_format == 'json' for intermediate AST transforms
        if from_format not in self.from_formats and from_format != 'json':
            raise ValueError
        if to_format not in self.to_formats:
            raise ValueError
        if from_format_extensions is None:
            from_format_extensions = ''
        if to_format_extensions is None:
            to_format_extensions = ''
        if input and input_path:
            raise TypeError
        if output_path is not None and not overwrite and output_path.exists():
            raise RuntimeError

        cmd_template_list = ['{pandoc}', '--from', '{from}', '--to', '{to}']
        if standalone:
            cmd_template_list.append('--standalone')
        if trace:
            cmd_template_list.append('--trace')
        if output_path:
            cmd_template_list.extend(['--output', '{output}'])
        if input_path:
            cmd_template_list.append('{input_path}')
        template_dict = {'pandoc': self.pandoc_path,
                         'from': from_format + from_format_extensions,
                         'to': to_format + to_format_extensions,
                         'output': output_path, 'input_path': input_path}
        cmd_list = [x.format(**template_dict) for x in cmd_template_list]

        if platform.system() == 'Windows':
            # Prevent console from appearing for an instant
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
        else:
            startupinfo = None

        try:
            proc = subprocess.run(cmd_list,
                                  input=input,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT,
                                  encoding='utf8',
                                  startupinfo=startupinfo, check=True)
        except subprocess.CalledProcessError as e:
            if input_name is None:
                msg = 'Failed to run Pandoc:\n{0}'.format(e)
            else:
                msg = 'Failed to run Pandoc on source {0} :\n{1}'.format(input_name, e)
            raise PandocError(msg)
        return proc.stdout


    def _get_walk_closures(block_node_types=_block_node_types,
                           trace_chunk_block_node_types=_trace_chunk_block_node_types,
                           trace_leaf_block_node_types=_trace_leaf_block_node_types,
                           dict=dict, enumerate=enumerate, isinstance=isinstance, list=list):
        '''
        Define recursive closures that walk the AST in various ways.  These
        later become static methods for the class.  Recursive functions can't
        be defined directly as static methods.  Performance is maximized by
        eliminating all non-local functions, and minimizing recursive function
        calls via walk functions that are only ever called on lists.
        '''

        def walk_node_list(node_list):
            '''
            Walk all AST nodes in a list, recursively descending to walk all
            child nodes as well.  The walk function is written so that it is
            only ever called on lists.  This is an optimization:  it reduces
            recursion depth and the number of times the walk function is
            called.  As a result, the function is never called on `Str` nodes
            and other leaf nodes, which will typically make up the vast
            majority of nodes.  It might be slightly faster for some node
            types to use a dict mapping node type to a boolean describing
            whether the node type contains lists, thus avoiding the final
            `isinstance()`.  However, the current approach is optimal for
            nodes like `Space` that have no content at all.  Since these are
            typically very common, the overall approach should at least on
            average be very close to optimal.

            Return nodes plus their parent lists with indices.
            '''
            for index, obj in enumerate(node_list):
                if isinstance(obj, list):
                    yield from walk_node_list(obj)
                elif isinstance(obj, dict):
                    yield (obj, node_list, index)
                    if 'c' in obj and isinstance(obj['c'], list):
                        yield from walk_node_list(obj['c'])

        def walk_node_list_trace_blocks_with_context(node, node_type,
                                                     node_list, node_list_parent_list, node_list_parent_parent_list,
                                                     parent_chunk_node, parent_chunk_node_list):
            '''
            Walk all AST block nodes in a list, recursively descending to walk
            all child block nodes as well, with the exception of nodes that do
            not appear in trace output (those within tables).  Return each
            node along with its node type, parent node, parent node type, and
            current parent node list and index.  If the current parent list is
            itself nested in one or more lists, also return the lists up to
            two levels up.  The nearest ancestor node with chunk-based line
            counting (parent chunk node) and the nearest node list within it
            (parent chunk node list) are returned as well.  All of this
            contextual information provides what is needed to parse `--trace`
            output.
            '''
            for index, obj in enumerate(node_list):
                if isinstance(obj, list):
                    if parent_chunk_node is node:
                        parent_chunk_node_list = obj
                    yield from walk_node_list_trace_blocks_with_context(node, node_type,
                                                                        obj, node_list, node_list_parent_list,
                                                                        parent_chunk_node, parent_chunk_node_list)
                elif isinstance(obj, dict):
                    child_node_type = obj['t']
                    if child_node_type in block_node_types:
                        yield (obj, child_node_type,
                               node, node_type, node_list, index, node_list_parent_list, node_list_parent_parent_list,
                               parent_chunk_node, parent_chunk_node_list)
                        if child_node_type not in trace_leaf_block_node_types:
                            if child_node_type in trace_chunk_block_node_types:
                                yield from walk_node_list_trace_blocks_with_context(obj, child_node_type,
                                                                                    obj['c'], None, None,
                                                                                    obj, obj['c'])
                            else:
                                yield from walk_node_list_trace_blocks_with_context(obj, child_node_type,
                                                                                    obj['c'], None, None,
                                                                                    parent_chunk_node, parent_chunk_node_list)

        return (walk_node_list, walk_node_list_trace_blocks_with_context)

    _walk_node_list, _walk_node_list_trace_blocks_with_context = (staticmethod(x) for x in _get_walk_closures())

    def _walk_ast(self, ast):
        yield from self._walk_node_list(ast['blocks'])


    @staticmethod
    def _get_traceback_span_node(source_name, line_number):
        '''
        Create an empty span node containing source name and line number as
        attributes.  This is used to attach source info to an AST location,
        and then track that location through AST transformations and
        conversions.
        '''
        span_node = {'t': 'Span',
                     'c': [
                              [
                                  '',  # id
                                  ['codebraid--trace'],  # classes
                                  [['codebraid_trace', '{0}:{1}'.format(source_name, line_number)]]  # kv pairs
                              ],
                              []
                          ]
                    }
        return span_node

    @staticmethod
    def _freeze_raw_node(node, source_name, line_number,
                         type_translation_dict={'RawBlock': 'CodeBlock', 'RawInline': 'Code'}):
        '''
        Convert a raw node into a special code node.  This prevents the
        raw node from being prematurely interpreted/discarded during
        intermediate AST transformations.
        '''
        node['t'] = type_translation_dict[node['t']]
        raw_format, raw_content = node['c']
        if raw_format in ('markdown', 'tex', 'latex', 'beamer'):
            # Patch markdown writer to guarantees that the raw
            # block won't merge with a following block.
            # https://github.com/jgm/pandoc/issues/4629
            raw_content += '\n'
        node['c'] = [
                        [
                            '',  # id
                            ['codebraid--frozen-raw'],  # classes
                            [['format', raw_format], ['codebraid_trace', '{0}:{1}'.format(source_name, line_number)]]  # kv pairs
                        ],
                        raw_content
                    ]

    @staticmethod
    def _thaw_raw_node(node, source_name, line_number,
                       type_translation_dict={'CodeBlock': 'RawBlock', 'Code': 'RawInline'}):
        '''
        Convert a special code node back into its original form as a raw node.
        '''
        node['t'] = type_translation_dict[node['t']]
        for k, v in node['c'][0][2]:
            if k == 'format':
                raw_format = k
                break
        raw_content = node['c'][1]
        node['c'] = [raw_format, raw_content]


    def _convert_source_string_to_ast(self, *, source_string, source_name,
                                      id=id, int=int, next=next):
        '''
        Convert source string into a Pandoc AST and perform a number of
        operations on the AST.
          * Parse `--trace` output so that source line numbers can be assigned
            to arbitrary nodes.
          * Locate all code nodes for further processing.
          * Convert all raw nodes into specially marked code nodes.  This
            allows them to pass through later Pandoc conversions without
            being lost or being interpreted before the final conversion.
            These special code nodes are converted back into raw nodes in the
            final AST before the final format conversion.
        '''
        stdout_lines = self._run_pandoc(input=source_string,
                                        input_name=source_name,
                                        from_format=self.from_format,
                                        from_format_extensions=self.from_format_extensions,
                                        to_format='json',
                                        trace=True).splitlines()
        ast = json.loads(stdout_lines.pop())
        if not (isinstance(ast, dict) and
                'pandoc-api-version' in ast and
                ast['pandoc-api-version'][:2] == [1, 17]):
            raise PandocError('Incompatible Pandoc API version')
        trace = []
        left_trace_type_slice_index = len('[trace] Parsed [')
        right_trace_chunk_slice_index = len(' of chunk')
        for trace_line in stdout_lines:
            trace_node_type = trace_line[left_trace_type_slice_index:].split(' ', 1)[0].rstrip(']')
            if trace_line.endswith('chunk'):
                trace_in_chunk = True
                trace_line_number = int(trace_line.split('at line ', 1)[1][:-right_trace_chunk_slice_index])
            else:
                trace_in_chunk = False
                trace_line_number = int(trace_line.split('at line ', 1)[1])
            trace.append((trace_node_type, trace_line_number, trace_in_chunk))
        # Processing the trace involves looking ahead to the next trace leaf
        # node.  The final lookahead will go past the end of the trace,
        # so a sentinel is needed.
        trace.append((None, None, None))
        del stdout_lines

        source_string_lines = source_string.splitlines()
        current_line_number = 1
        ast_root_node_list = ast['blocks']
        block_node_types = self._block_node_types
        walk_node_list = self._walk_node_list
        trace_leaf_block_node_types = self._trace_leaf_block_node_types
        get_traceback_span_node = self._get_traceback_span_node
        freeze_raw_node = self._freeze_raw_node
        code_chunks = self._code_chunks
        parent_chunk_node_list_stack = []
        chunk_node_list_start_line_numbers = {}
        last_trace_iter = iter(trace)
        last_trace_node_type, last_trace_line_number, last_trace_in_chunk = ('Root', 1, False)
        current_trace_iter = iter(trace)
        current_trace_node_type, current_trace_line_number, current_trace_in_chunk = next(current_trace_iter)
        # The trace information for a given node provides information about
        # the line on which the next node begins, rather than information
        # about the current node.  So the `current_*` variables are a
        # lookahead corresponding to the current node, but all calculations
        # depend on the `last_*` variables.  At the beginning, deal with Null
        # nodes (empty string) and internal nodes that contain them to reach
        # the first leaf node (if any).
        while current_trace_node_type not in trace_leaf_block_node_types and current_trace_node_type is not None:
            last_trace_node_type, last_trace_line_number, last_trace_in_chunk = next(last_trace_iter)
            current_trace_node_type, current_trace_line_number, current_trace_in_chunk = next(current_trace_iter)
            if not last_trace_in_chunk:
                current_line_number = last_trace_line_number
            elif last_trace_node_type == '':
                current_line_number += last_trace_line_number - 1

        for walk_tuple in self._walk_node_list_trace_blocks_with_context(ast, 'Root',
                                                                         ast_root_node_list, None, None,
                                                                         ast, ast_root_node_list):
            (node, node_type,
                parent_node, parent_node_type, parent_node_list, parent_node_list_index, parent_node_list_parent_list, parent_node_list_parent_parent_list,
                parent_chunk_node, parent_chunk_node_list) = walk_tuple
            if parent_node_type == 'DefinitionList':
                # Definition lists need special treatment for two reasons.
                # First, terms being defined are not block nodes, so they
                # don't appear in trace output.  Line numbers must be adjusted
                # for this.  Second, the final chunk line number for each
                # definition is 1 larger than the equivalent for other chunk
                # blocks.  This must be corrected so that the same line number
                # formulas can be used for everything.
                #
                # parent_node_list contains nodes that make up a definition.
                # parent_node_list_parent_list is a list of definitions.
                # parent_node_list_parent_parent_list contains a term in index
                # 0 followed by a list of definitions in index 1.
                if parent_node_list[0] is node:
                    if parent_node_list_parent_list[0] is not parent_node_list:
                        # If not the first definition, correct overshoot.
                        current_line_number -= 1
                    else:
                        # Adjust for first definition.
                        if parent_node['c'][0] is not parent_node_list_parent_parent_list:
                            # If not the first term, correct overshoot.
                            current_line_number -= 1
                        # Add traceback span to term's inline node list
                        parent_node_list_parent_parent_list[0].insert(0, get_traceback_span_node(source_name, current_line_number))
                        # Deal with code and raw nodes in the term's node
                        # list.  Unlike the Para and Plain case later on,
                        # there is no possibility of having SoftBreak nodes,
                        # so processing is simpler.
                        for inline_walk_tuple in walk_node_list(parent_node_list_parent_parent_list[0]):
                            inline_node, inline_parent_node_list, inline_parent_node_list_index = inline_walk_tuple
                            inline_node_type = inline_node['t']
                            if inline_node_type == 'Code':
                                if 'codebraid' in inline_node['c'][0][1]:  # classes
                                    code_chunk = PandocCodeChunk(inline_node, source_name, current_line_number, inline_parent_node_list, inline_parent_node_list_index)
                                    code_chunks.append(code_chunk)
                            elif inline_node_type == 'RawInline':
                                freeze_raw_node(inline_node, source_name, current_line_number)
                        # Determine line number for start of first definition
                        current_line_number += 1
                        if source_string_lines[current_line_number-1].strip() == '':
                            current_line_number += 1
            elif (parent_node_type == 'Div' and
                    parent_node_list[0] is node and
                    source_string_lines[current_line_number-1].lstrip().startswith(':::')):
                # If this is the beginning of the div, and this is a pandoc
                # markdown fenced div rather than an HTML div, go to the next
                # line, where the content actually begins
                current_line_number += 1
            # The AST is walked in top-down order, but the trace gives nodes
            # in bottom-up order.  The top-down order in walking the AST
            # easily allows starting line numbers to be assigned to internal
            # nodes.  When internal nodes are encountered in the trace, this
            # information needs to be accessed to calculate line numbers in
            # chunks.  Internal node starting line numbers are stored by
            # `id()` in the dict `chunk_node_list_start_line_numbers`.  These
            # are accessed later in processing the trace by keeping a stack of
            # `parent_chunk_node_list`.
            if id(parent_chunk_node_list) not in chunk_node_list_start_line_numbers:
                chunk_node_list_start_line_numbers[id(parent_chunk_node_list)] = current_line_number
            if node_type not in trace_leaf_block_node_types:
                parent_chunk_node_list_stack.append(parent_chunk_node_list)
                continue
            if node_type != current_trace_node_type:
                if node_type == 'Plain' and current_trace_node_type == 'Para':
                    # Nodes that appear as Para in the trace can become Plain
                    # once parsing proceeds and they are inserted into the
                    # AST.  This can happen for example in BulletList.
                    pass
                elif node_type == 'RawBlock' and node['c'][0] == 'html':
                    # When the markdown extension markdown_in_html_blocks is
                    # enabled (default for pandoc markdown), text that is
                    # wrapped in block-level html tags will result in a Para
                    # or Plain node that is preceded and followed by one
                    # RawBlock per block-level tag.  However, only the
                    # following RawBlock(s) will appear in the trace.
                    #
                    # Trying to correct line numbers to account for this in
                    # the general case might be difficult, but it is simple
                    # for the case of tags on lines by themselves.  There is
                    # no need to handle the case of empty lines between the
                    # opening tag and the text, because that will result in
                    # Null nodes that will automatically adjust line numbers.
                    if source_string_lines[current_line_number-1].strip() == node['c'][1]:
                        current_line_number += 1
                    continue
                else:
                    raise PandocError('Parsing trace failed')
            if node_type in ('Plain', 'Para'):
                if node['c']:
                    node['c'].insert(0, get_traceback_span_node(source_name, current_line_number))
                    # Find inline code nodes and determine their line numbers.
                    # Incrementing `current_line_number` here won't throw off
                    # the overall line numbering if there are errors in the
                    # numbering calculations, because `current_line_number` is
                    # reset after each Plain or Para node based on the trace.
                    for inline_walk_tuple in walk_node_list(node['c']):
                        inline_node, inline_parent_node_list, inline_parent_node_list_index = inline_walk_tuple
                        inline_node_type = inline_node['t']
                        if inline_node_type == 'SoftBreak':
                            current_line_number += 1
                        elif inline_node_type == 'Code':
                            if 'codebraid' in inline_node['c'][0][1]:  # classes
                                code_chunk = PandocCodeChunk(inline_node, source_name, current_line_number, inline_parent_node_list, inline_parent_node_list_index)
                                code_chunks.append(code_chunk)
                            # For the unlikely case of a code span that is
                            # broken over multiple lines, make a basic attempt
                            # at correcting the line numbering.  This won't
                            # detect a broken span in all cases since that
                            # would require full parsing (for example, there
                            # could be multiple code spans with similar or
                            # identical content), but it will work in the vast
                            # majority of cases.  It's possible that the
                            # current line number is off so that the code
                            # can't be found.  In that case, don't change the
                            # numbering.
                            code_content = inline_node['c'][1]
                            if ' ' in code_content:
                                line = source_string_lines[current_line_number-1]
                                if code_content not in line:
                                    lookahead_line_number = current_line_number
                                    while True:
                                        lookahead_line_number += 1
                                        try:
                                            next_line = source_string_lines[lookahead_line_number-1]
                                        except IndexError:
                                            break
                                        if next_line.strip() == '':
                                            break
                                        line += ' ' + next_line.lstrip()
                                        if code_content in line:
                                            current_line_number = lookahead_line_number
                                            break
                        elif inline_node_type == 'RawInline':
                            freeze_raw_node(inline_node, source_name, current_line_number)
            elif node_type == 'CodeBlock':
                if 'codebraid' in node[0][1]:  # classes
                    code_chunk = PandocCodeChunk(node, source_name, current_line_number, parent_node_list, parent_node_list_index)
                    code_chunks.append(code_chunk)
            elif node_type == 'RawBlock':
                freeze_raw_node(node, source_name, current_line_number)
            last_trace_node_type, last_trace_line_number, last_trace_in_chunk = next(last_trace_iter)
            current_trace_node_type, current_trace_line_number, current_trace_in_chunk = next(current_trace_iter)
            if current_trace_node_type not in trace_leaf_block_node_types:
                while current_trace_node_type not in trace_leaf_block_node_types and current_trace_node_type is not None:
                    if not last_trace_in_chunk:
                        current_line_number = last_trace_line_number
                    else:
                        if current_trace_node_type != '':
                            parent_chunk_node_list = parent_chunk_node_list_stack.pop()
                        current_line_number = chunk_node_list_start_line_numbers[id(parent_chunk_node_list)] + last_trace_line_number - 1
                    last_trace_node_type, last_trace_line_number, last_trace_in_chunk = next(last_trace_iter)
                    current_trace_node_type, current_trace_line_number, current_trace_in_chunk = next(current_trace_iter)
            if not last_trace_in_chunk:
                current_line_number = last_trace_line_number
            else:
                current_line_number = chunk_node_list_start_line_numbers[id(parent_chunk_node_list)] + last_trace_line_number - 1

        return ast


    def _extract_code_chunks(self):
        ast = self._convert_source_string_to_ast(source_string=self.strings[0], source_name='name')
        for node, *_ in self._walk_ast(ast):
            node_type = node['t']
            if node_type in self._code_node_types:
                pass
                #print(node)
                #ode['c'][1] = str(eval(node['c'][1]))

        self._ast = ast

    def _process_code_chunks(self):
        ...

    def convert(self, *, to_format):
        if to_format not in self.to_formats:
            raise ValueError
        stdout = self._run_pandoc(input=json.dumps(self._ast),
                                  from_format='json',
                                  to_format=to_format,
                                  standalone=True)
        return stdout
