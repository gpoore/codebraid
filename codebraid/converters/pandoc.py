# -*- coding: utf-8 -*-
#
# Copyright (c) 2018, Geoffrey M. Poore
# All rights reserved.
#
# Licensed under the BSD 3-Clause License:
# http://opensource.org/licenses/BSD-3-Clause
#


import json
import pathlib
import platform
import re
import subprocess
from typing import Optional, Union
from .base import Converter
from .. import err




class PandocError(err.CodebraidError):
    pass




class PandocConverter(Converter):
    '''
    Converter based on Pandoc (https://pandoc.org/).

    Pandoc is used to parse input into a JSON-based AST.  Code nodes in the
    AST are located, processed, and then replaced with raw nodes.  Next, the
    AST is converted back into the original input format (or another document
    format), and reparsed into a new AST.  This allows code output to be
    interpreted with the input document format, making possible things like
    references that could be difficult to handle by parsing code output in
    isolation.  Finally, the new AST is converted into the output format.
    '''
    def __init__(self,
                 pandoc_path: Optional[Union[str, pathlib.Path]]=None,
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
        super().__init__(**kwargs, expanduser=expanduser, expandvars=expandvars)


    from_formats = set(['json', 'markdown'])
    to_formats = set(['json', 'markdown', 'html', 'latex', ])


    # Node sets are based on pandocfilters
    # https://github.com/jgm/pandocfilters/blob/master/pandocfilters.py
    _block_node_types = set(['Plain', 'Para', 'CodeBlock', 'RawBlock',
                             'BlockQuote', 'OrderedList', 'BulletList',
                             'DefinitionList', 'Header', 'HorizontalRule',
                             'Table', 'Div', 'Null'])
    # Block nodes that appear in `--trace` output and are leaf nodes as far as
    # that is concerned (these nodes may contain block nodes, but those
    # internal nodes don't appear in the trace output)
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


    _whitespace_lines_re = re.compile('(?:[\x20\t]*\r?\n)*')


    def _run_pandoc(self, *,
                    from_format: str,
                    to_format: str,
                    input: Optional[str]=None,
                    input_path: Optional[pathlib.Path]=None,
                    output_path: Optional[pathlib.Path]=None,
                    standalone: bool=False,
                    trace: bool=False):
        '''
        Convert between formats using Pandoc.

        Communication with Pandoc is accomplished via pipes.
        '''
        if from_format not in self.from_formats:
            raise ValueError
        if to_format not in self.to_formats:
            raise ValueError

        if from_format == 'markdown':
            # Because line number tracebacks depend on parsing `--trace`
            # output, some HTML features of pandoc markdown must be disabled
            # to guarantee reliable results.  Since pandoc markdown supports
            # fenced divs and bracketed spans, disabling the parsing of the
            # HTML versions shouldn't be a significant limitation.
            from_format += '-markdown_in_html_blocks-native_divs-native_spans'

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
                         'from': from_format, 'to': to_format,
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
            raise PandocError('Failed to run Pandoc:\n{0}'.format(e))
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
            average be very close to optimal.  Return nodes plus their
            parent lists with indices.
            '''
            for index, obj in enumerate(node_list):
                if isinstance(obj, list):
                    yield from walk_node_list(obj)
                elif isinstance(obj, dict):
                    yield (obj, node_list, index)
                    if 'c' in obj:
                        if isinstance(obj['c'], list):
                            yield from walk_node_list(obj['c'])

        def walk_node_list_trace_blocks_with_context(node, node_type,
                                                     node_list, node_list_parent_list, node_list_parent_parent_list,
                                                     parent_chunk_node, parent_chunk_node_list):
            '''
            Walk all AST block nodes in a list, recursively descending to walk
            all child block nodes as well, with the exception of nodes that do
            not appear in trace output (those within tables).  Return each
            node along with its node type, parent node, parent node type, and
            current parent node list.  If the current parent list is itself
            nested in one or more lists, also return the lists up to two
            levels up.  The nearest ancestor node with chunk-based line
            counting (parent chunk node) and the nearest node list within it
            (parent chunk node list) are returned as well.  All of this
            contextual information provides what is needed to parse `--trace`
            output.
            '''
            for obj in node_list:
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
                               node, node_type, node_list, node_list_parent_list, node_list_parent_parent_list,
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
    def _get_traceback_span_node(line_number,
                                 id=None, classes=None, attribute=None,
                                 str=str):
        '''
        Create an empty span node containing a line number as an attribute.
        This is used to attach a source file line number to an AST location,
        and then track that location through AST transformations and
        conversions.
        '''
        if id is None:
            id = ''
        if classes is None:
            classes = ['codebraid', 'codebraid--code-line']
        if attribute is None:
            attribute = 'data-line'
        span_node = {'t': 'Span',
                     'c': [
                              [
                                  id,
                                  classes,
                                  [[attribute, str(line_number)]]
                              ],
                              []
                          ]
                    }
        return span_node


    def _convert_source_string_to_ast(self, id=id, int=int, next=next, str=str):
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
        stdout = self._run_pandoc(input=self.string,
                                  from_format=self.from_format,
                                  to_format='json',
                                  trace=True)
        stdout_lines = stdout.splitlines()

        ast = json.loads(stdout_lines[-1])
        if 'pandoc-api-version' not in ast or ast['pandoc-api-version'][:2] != [1, 17]:
            raise PandocError('Incompatible Pandoc API version')

        string_lines = self.string.splitlines(True)
        first_line_number = self._whitespace_lines_re.match(self.string).group().count('\n') + 1
        current_line_number = first_line_number
        left_trace_slice_index = len('[trace] Parsed [')
        right_trace_chunk_slice_index = len(' of chunk')
        ast_root_node_list = ast['blocks']
        ast_trace_blocks_with_context_walker = self._walk_node_list_trace_blocks_with_context(ast, 'Root',
                                                                                              ast_root_node_list, None, None,
                                                                                              ast, ast_root_node_list)
        trace_leaf_block_node_types = self._trace_leaf_block_node_types
        get_traceback_span_node = self._get_traceback_span_node
        chunk_node_list_stack = []
        chunk_node_list_start_line_numbers = {}

        for trace_line in stdout_lines[:-1]:
            trace_node_type = trace_line[left_trace_slice_index:].split(' ', 1)[0].rstrip(']')
            if trace_node_type == '' and current_line_number > first_line_number:
                current_line_number += 1
                continue
            if trace_node_type not in trace_leaf_block_node_types:
                if trace_line.endswith('chunk'):
                    trace_chunk_line_number = int(trace_line.split('line ', 1)[1][:-right_trace_chunk_slice_index])
                    current_line_number = chunk_node_list_start_line_numbers[id(chunk_node_list_stack.pop())] + trace_chunk_line_number - 1
                else:
                    trace_line_number = int(trace_line.split('line ', 1)[1])
                    current_line_number = trace_line_number
                continue
            (node, node_type,
                parent_node, parent_node_type, parent_node_list, parent_node_list_parent_list, parent_node_list_parent_parent_list,
                parent_chunk_node, parent_chunk_node_list) = next(ast_trace_blocks_with_context_walker)
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
                        # First definition
                        if parent_node['c'][0] is not parent_node_list_parent_parent_list:
                            # If not the first term, correct overshoot.
                            current_line_number -= 1
                        # Add traceback span to term
                        parent_node_list_parent_parent_list[0].insert(0, get_traceback_span_node(current_line_number))
                        # Determine line number for start of first definition
                        current_line_number += 1
                        if string_lines[current_line_number-1].isspace():
                            current_line_number += 1
            elif (parent_node_type == 'Div' and
                    parent_node_list[0] is node and
                    string_lines[current_line_number-1].lstrip().startswith(':::')):
                # If this is the beginning of the div, and this is a pandoc
                # markdown fenced div rather than an HTML div, go to the next
                # line, where the content actually begins
                current_line_number += 1
            if id(parent_chunk_node_list) not in chunk_node_list_start_line_numbers:
                chunk_node_list_start_line_numbers[id(parent_chunk_node_list)] = current_line_number
            if node_type not in trace_leaf_block_node_types:
                while node_type not in trace_leaf_block_node_types:
                    if parent_chunk_node is not ast:
                        chunk_node_list_stack.append(parent_chunk_node_list)
                    (node, node_type,
                        parent_node, parent_node_type, parent_node_list, parent_node_list_parent_list, parent_node_list_parent_parent_list,
                        parent_chunk_node, parent_chunk_node_list) = next(ast_trace_blocks_with_context_walker)
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
                                # First definition
                                if parent_node['c'][0] is not parent_node_list_parent_parent_list:
                                    # If not the first term, correct overshoot.
                                    current_line_number -= 1
                                # Add traceback span to term
                                parent_node_list_parent_parent_list[0].insert(0, get_traceback_span_node(current_line_number))
                                # Determine line number for start of first definition
                                current_line_number += 1
                                if string_lines[current_line_number-1].isspace():
                                    current_line_number += 1
                    elif (parent_node_type == 'Div' and
                            parent_node_list[0] is node and
                            string_lines[current_line_number-1].lstrip().startswith(':::')):
                        # If this is the beginning of the div, and this is a pandoc
                        # markdown fenced div rather than an HTML div, go to the next
                        # line, where the content actually begins
                        current_line_number += 1
                    if id(parent_chunk_node_list) not in chunk_node_list_start_line_numbers:
                        chunk_node_list_start_line_numbers[id(parent_chunk_node_list)] = current_line_number
            if node_type in ('Plain', 'Para'):
                if node['c']:
                    node['c'].insert(0, get_traceback_span_node(current_line_number))
            if trace_line.endswith('chunk'):
                trace_chunk_line_number = int(trace_line.split('line ', 1)[1][:-right_trace_chunk_slice_index])
                current_line_number = chunk_node_list_start_line_numbers[id(parent_chunk_node_list)] + trace_chunk_line_number - 1
            else:
                trace_line_number = int(trace_line.split('line ', 1)[1])
                current_line_number = trace_line_number

        return ast


    def _extract_code_chunks(self):
        ast = self._convert_source_string_to_ast()
        for node, *_ in self._walk_ast(ast):
            node_type = node['t']
            if node_type in self._code_node_types:
                node['c'][1] = str(eval(node['c'][1]))

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
