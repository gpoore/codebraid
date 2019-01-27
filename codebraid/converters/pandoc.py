# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019, Geoffrey M. Poore
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
import warnings
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
                 from_format_pandoc_extensions: Optional[str]=None,
                 expanduser: bool=False,
                 expandvars: bool=False,
                 **kwargs):
        super().__init__(**kwargs, expanduser=expanduser, expandvars=expandvars)
        if pandoc_path is None:
            pandoc_path = pathlib.Path('pandoc')
        else:
            pandoc_path = pathlib.Path(pandoc_path)
            if expandvars:
                pandoc_path = pathlib.Path(os.path.expandvars(pandoc_path))
            if expanduser:
                pandoc_path = pandoc_path.expanduser()
        try:
            proc = subprocess.run([pandoc_path, '--version'], capture_output=True)
        except FileNotFoundError:
            raise RuntimeError('Pandoc path "{0}" does not exist'.format(pandoc_path))
        pandoc_version_match = re.search(rb'\d+\.\d+', proc.stdout)
        if not pandoc_version_match:
            raise RuntimeError('Could not determine Pandoc version from "{0} --version"; faulty Pandoc installation?'.format(pandoc_path))
        elif float(pandoc_version_match.group()) < 2.4:
            raise RuntimeError('Pandoc at "{0}" is version {1}, but >= 2.4 is required'.format(pandoc_path, float(pandoc_version_match.group())))
        self.pandoc_path = pandoc_path
        if (from_format_pandoc_extensions is not None and
                not isinstance(from_format_pandoc_extensions, str)):
            raise TypeError
        self.from_format_pandoc_extensions = from_format_pandoc_extensions


    from_formats = set(['json', 'markdown'])
    to_formats = set(['json', 'markdown', 'html', 'latex'])
    multi_source_formats = set(['markdown'])


    # Node sets are based on pandocfilters
    # https://github.com/jgm/pandocfilters/blob/master/pandocfilters.py
    _null_block_node_type = set([''])
    _plain_or_para_block_node_types = set(['Plain', 'Para'])
    _block_node_types = set(['Plain', 'Para', 'CodeBlock', 'RawBlock',
                             'BlockQuote', 'OrderedList', 'BulletList',
                             'DefinitionList', 'Header', 'HorizontalRule',
                             'Table', 'Div']) | _null_block_node_type
    # Block nodes that appear in `--trace` output and are internal block
    # nodes.  Note that this does NOT include Table.
    _trace_internal_block_node_types = set(['BlockQuote', 'OrderedList',
                                            'BulletList', 'DefinitionList',
                                            'Div'])
    # Block nodes that appear in `--trace` output and are leaf block nodes as
    # far as that is concerned (these nodes may contain block nodes, but those
    # nodes don't appear in the trace output).  Sets are provided with and
    # without the Null node (trace node with the empty string as its name).
    # Nulls contain no nodes of any type (block or inline) and so are
    # technically leaf block nodes, but they are similar to internal block
    # nodes because they require no additional processing like a normal leaf
    # block node.
    _trace_leaf_block_node_types_with_null = _block_node_types - _trace_internal_block_node_types
    _trace_leaf_block_node_types_without_null = _trace_leaf_block_node_types_with_null - _null_block_node_type
    # Block nodes that appear in `--trace` output that initiate chunk-based
    # line counting (for lists, this is on a per-item basis)
    _trace_chunk_block_node_types = set(t for t in _block_node_types if t.endswith('Quote') or t.endswith('List'))
    # Nodes that may require special processing
    _code_node_types = set(['CodeBlock', 'Code'])
    _raw_node_types = set(['RawBlock', 'RawInline'])


    def _run_pandoc(self, *,
                    from_format: str,
                    to_format: str,
                    from_format_pandoc_extensions: Optional[str]=None,
                    to_format_pandoc_extensions: Optional[str]=None,
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
        if from_format not in self.from_formats:
            raise ValueError
        if to_format not in self.to_formats:
            raise ValueError
        if from_format_pandoc_extensions is None:
            from_format_pandoc_extensions = ''
        if to_format_pandoc_extensions is None:
            to_format_pandoc_extensions = ''
        if input and input_path:
            raise TypeError
        if output_path is not None and not overwrite and output_path.exists():
            raise RuntimeError('Output path {0} exists, but overwrite=False'.format(output_path))

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
                         'from': from_format + from_format_pandoc_extensions,
                         'to': to_format + to_format_pandoc_extensions,
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
            if input_path is not None and input_name is None:
                input_name = input_path
            if input_name is None:
                msg = 'Failed to run Pandoc:\n{0}'.format(e)
            else:
                msg = 'Failed to run Pandoc on source {0}:\n{1}'.format(input_name, e)
            raise PandocError(msg)
        return proc.stdout


    def _get_walk_closures(block_node_types=_block_node_types,
                           trace_chunk_block_node_types=_trace_chunk_block_node_types,
                           trace_leaf_block_node_types_without_null=_trace_leaf_block_node_types_without_null,
                           dict=dict, enumerate=enumerate, isinstance=isinstance, list=list):
        '''
        Define recursive closures that walk the AST in various ways.  These
        ultimately become static methods for the class.  Recursive functions
        can't be defined directly as static methods, hence the current
        approach.  Performance is maximized by eliminating all non-local
        functions, and minimizing recursive function calls via walk functions
        that are only ever called on lists.
        '''

        def walk_node_list(node_list):
            '''
            Walk all AST nodes in a list, recursively descending to walk all
            child nodes as well.  The walk function is written so that it is
            only ever called on lists, reducing recursion depth and reducing
            the number of times the walk function is called.  Thus, it is
            never called on `Str` nodes and other leaf nodes, which will
            typically make up the vast majority of nodes.

            Returns nodes plus their parent lists with indices.
            '''
            for index, obj in enumerate(node_list):
                if isinstance(obj, list):
                    yield from walk_node_list(obj)
                elif isinstance(obj, dict):
                    yield (obj, node_list, index)
                    obj_contents = obj.get('c', None)
                    if obj_contents is not None and isinstance(obj_contents, list):
                        yield from walk_node_list(obj_contents)

        def walk_node_list_trace_blocks_with_context(node, node_type, node_depth,
                                                     node_list, node_list_parent_list, node_list_parent_parent_list,
                                                     parent_chunk_node, parent_chunk_node_list):
            '''
            Walk all AST block nodes in a list, recursively descending to walk
            all child block nodes as well, with the exception of nodes that do
            not appear in trace output (those within tables).  Retain enough
            contextual information for parsing `--trace` output.

            Returns each node along with its node type, node depth, parent
            node, parent node type, and current parent node list and index.
            If the current parent list is itself nested in one or more lists,
            these are returned up to two levels up.  The nearest ancestor node
            with chunk-based line counting (parent chunk node) and the nearest
            node list within it (parent chunk node list) are returned as well.

            Node depth is defined as the number of nodes between a node and
            the Root node.  For example, nodes in the Root node list are at a
            depth of 0.  This definition simplifies later operations.  For
            example, it allows a list representing the AST node path to a node
            to omit Root, with node depth corresponding to list index.  As a
            result of this definition, the effective depth of Root is -1.
            '''
            for index, obj in enumerate(node_list):
                if isinstance(obj, list):
                    if parent_chunk_node is node:
                        parent_chunk_node_list = obj
                    yield from walk_node_list_trace_blocks_with_context(node, node_type, node_depth,
                                                                        obj, node_list, node_list_parent_list,
                                                                        parent_chunk_node, parent_chunk_node_list)
                elif isinstance(obj, dict):
                    child_node_type = obj['t']
                    if child_node_type in block_node_types:
                        yield (obj, child_node_type, node_depth+1,
                               node, node_type, node_list, index,
                               node_list_parent_list, node_list_parent_parent_list,
                               parent_chunk_node, parent_chunk_node_list)
                        if child_node_type not in trace_leaf_block_node_types_with_null:
                            if child_node_type in trace_chunk_block_node_types:
                                yield from walk_node_list_trace_blocks_with_context(obj, child_node_type, node_depth+1,
                                                                                    obj['c'], None, None,
                                                                                    obj, obj['c'])
                            else:
                                yield from walk_node_list_trace_blocks_with_context(obj, child_node_type, node_depth+1,
                                                                                    obj['c'], None, None,
                                                                                    parent_chunk_node, parent_chunk_node_list)
        return (walk_node_list, walk_node_list_trace_blocks_with_context)

    _walk_node_list, _walk_node_list_trace_blocks_with_context = (staticmethod(x) for x in _get_walk_closures())

    def _walk_ast(self, ast):
        '''
        Walk all nodes in AST.
        '''
        ast_root_node_list = ast['blocks']
        yield from self._walk_node_list(ast_root_node_list)

    def _walk_ast_trace_blocks_with_context(self, ast):
        '''
        Walk all AST block nodes, with the exception of nodes that do not
        appear in trace output (those within tables).

        The AST does not contain an actual Root node; there is only a
        Root-level node list.  As a result, the AST dict itself is treated as
        the Root node for the purpose of starting the walk.  Because node
        depth is defined as the number of nodes between the current node and
        Root, Root has an effective depth of -1 to get the walk algorithm
        started correctly.
        '''
        ast_root_node_list = ast['blocks']
        yield from self._walk_node_list_trace_blocks_with_context(ast, 'Root', -1,
                                                                  ast_root_node_list, None, None,
                                                                  ast, ast_root_node_list)


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
                                  ['codebraid--temp'],  # classes
                                  [['trace', '{0}:{1}'.format(source_name, line_number)]]  # kv pairs
                              ],
                              []  # contents
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
        node['c'] = [
                        [
                            '',  # id
                            ['codebraid--temp'],  # classes
                            [['format', raw_format], ['trace', '{0}:{1}'.format(source_name, line_number)]]  # kv pairs
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


    # Regex for footnotes.  While they shouldn't be indented, the Pandoc
    # parser does recognize them as long as the indentation is less than 4
    # spaces.  The restrictions on the footnote identifier are minimal.
    # https://pandoc.org/MANUAL.html#footnotes
    # https://github.com/jgm/pandoc/blob/master/src/Text/Pandoc/Readers/Markdown.hs
    _footnote_re = re.compile(r' {0,3}\[\^[^ \t]+?\]:')


    def _convert_source_string_to_ast(self, *, source_string, source_name,
                                      any=any, id=id, int=int, len=len,
                                      next=next, reversed=reversed):
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
        # Convert source string to trace plus AST with Pandoc
        stdout_lines = self._run_pandoc(input=source_string,
                                        input_name=source_name,
                                        from_format=self.from_format,
                                        from_format_pandoc_extensions=self.from_format_pandoc_extensions,
                                        to_format='json',
                                        trace=True).splitlines()
        try:
            ast = json.loads(stdout_lines.pop())
        except Exception:
            raise PandocError('Incompatible Pandoc version; failed to load AST')
        if not (isinstance(ast, dict) and
                'pandoc-api-version' in ast and 'blocks' in ast):
            raise PandocError('Incompatible Pandoc API version')
        if ast['pandoc-api-version'][0:2] != [1, 17]):
            warnings.warn('Pandoc API is {0}, but Codebraid is designed for 1.17; this might cause issues depending on what has changed'.format(ast['pandoc-api-version'][0:2]))
        ast_root_node_list = ast['blocks']

        # Will need to index source by line number later
        source_string_lines = source_string.splitlines()

        # Process trace into a list of tuples of the form
        # (<node type>, <raw node format>, <line number>, <in chunk>)
        left_trace_type_slice_index = len('[trace] Parsed [')
        right_trace_chunk_slice_index = len(' of chunk')
        footnote_re = self._footnote_re
        initial_trace = ('', None, 1, False)
        traces = [initial_trace]
        in_footnote = False
        trace = initial_trace
        try:
            for trace_line in stdout_lines:
                last_trace_node_type, last_trace_node_format, last_trace_line_number, last_trace_in_chunk = trace
                trace_line = trace_line[left_trace_type_slice_index:]
                trace_node_type, trace_line = trace_line.split(' ', 1)
                trace_node_type = trace_node_type.rstrip(']')
                if trace_node_type != 'RawBlock':
                    trace_node_format = None
                else:
                    trace_line = trace_line.split('(Format "', 1)[1]
                    trace_node_format, trace_line = trace_line.split('")', 1)
                    trace_node_format = trace_node_format.lower()
                if trace_line.endswith('chunk'):
                    trace_in_chunk = True
                    trace_line_number = int(trace_line.split('at line ', 1)[1][:-right_trace_chunk_slice_index])
                else:
                    trace_in_chunk = False
                    trace_line_number = int(trace_line.split('at line ', 1)[1])
                trace = (trace_node_type, trace_node_format, trace_line_number, trace_in_chunk)
                # Filter out footnote traces.  Since footnotes must be at root
                # level in the AST, line numbers are guaranteed to be correct
                # for their start location (no chunk numbering involved), so
                # this will always detect and skip them correctly.  There
                # shouldn't be any indentation before the `[^<identifier>]:`,
                # but a regex is used to cover all cases that the parser will
                # accept.  A footnote is always followed by a Null at root
                # level.
                if (trace_in_chunk and not last_trace_in_chunk and
                        footnote_re.match(string_lines[last_trace_line_number-1])):
                    in_footnote = True
                    continue
                if in_footnote:
                    if trace_in_chunk:
                        continue
                    in_footnote = False
                traces.append(trace)
        except Exception as e:
            raise PandocError('Incompatible Pandoc version or trace; cannot parse trace format:\n{0}'.format(e))
        # The trace always goes beyond the actual length of the source.  Add
        # empty lines to prevent index errors/avoid correcting the trace.
        # The final trace values are discarded, so this has no effect on
        # determining line numbers.
        source_string_lines.extend(['']*(trace_line_number-len(source_string_lines)))

        # Walk AST and trace simultaneously to associate trace line numbers
        # with AST nodes
        code_chunks = self._code_chunks
        line_number = 1
        lookahead_traces_iter = iter(traces)
        lookahead_trace_tuple = next(lookahead_traces_iter)  # == initial_trace
        traces_iter = iter(traces)
        trace_tuple = next(traces_iter)
        trace_node_type, trace_node_format, trace_line_number, trace_in_chunk = trace_tuple
        plain_or_para_block_node_types = self._plain_or_para_block_node_types
        block_node_types = self._block_node_types
        trace_leaf_block_node_types_without_null = self._trace_leaf_block_node_types_without_null
        trace_leaf_block_node_types_with_null = self._trace_leaf_block_node_types_with_null
        walk_node_list = self._walk_node_list
        get_traceback_span_node = self._get_traceback_span_node
        freeze_raw_node = self._freeze_raw_node
        ast_trace_nodes_iter = self._walk_ast_trace_blocks_with_context(ast)
        chunk_node_list_start_line_numbers = {id(ast_root_node_list): 1}
        parent_chunk_node_list_stack = []
        untraced_html_node_stack = []
        untraced_html_parent_chunk_node_list_stack = []
        out_of_order_html_node = False
        left_strip_chars = '\t *+->|:'
        left_strip_chars_less_colon = left_strip_chars.replace(':', '')

        while True:
            # Look ahead to find the next leaf node in the trace.  This is
            # useful in handling leaf nodes in the AST that do not appear in
            # the trace.  The Pandoc markdown extension
            # markdown_in_html_blocks can produce markdown nodes preceded and
            # followed by HTML RawBlocks, but only the following RawBlock
            # appears in the trace, so the preceding block must be skipped
            # (with a basic attempt at correcting line numbers).  A similar
            # approach is used to deal with HTML RawBlocks that appear out of
            # order in the trace (at the end of the current chunk, rather than
            # where they appear relative to other leaf nodes; for example,
            # `<hr/>`).
            try:
                (last_lookahead_trace_node_type, last_lookahead_trace_node_format,
                    last_lookahead_trace_line_number, last_lookahead_trace_in_chunk) = lookahead_trace_tuple
                lookahead_trace_tuple = next(lookahead_traces_iter)
                (lookahead_trace_node_type, lookahead_trace_node_format,
                    lookahead_trace_line_number, lookahead_trace_in_chunk) = lookahead_trace_tuple
            except StopIteration:
                break
            if lookahead_trace_node_type not in trace_leaf_block_node_types_without_null:
                try:
                    while lookahead_trace_node_type not in trace_leaf_block_node_types_without_null:
                        (last_lookahead_trace_node_type, last_lookahead_trace_node_format,
                            last_lookahead_trace_line_number, last_lookahead_trace_in_chunk) = lookahead_trace_tuple
                        lookahead_trace_tuple = next(lookahead_traces_iter)
                        (lookahead_trace_node_type, lookahead_trace_node_format,
                            lookahead_trace_line_number, lookahead_trace_in_chunk) = lookahead_trace_tuple
                except StopIteration:
                    break

            # Get the next leaf node in the AST while creating a list of
            # internal nodes whose order corresponds to that in which they
            # will appear in the trace.  StopIteration checks are needed
            # because some HTML RawBlocks appear in the trace out of order,
            # after nodes they actually precede.  When these nodes are
            # encountered in the AST, they are skipped (with a basic attempt
            # at correcting line numbers).  When these nodes appear in the
            # trace, there isn't a corresponding leaf node in the AST since it
            # has already been skipped, so looking for a corresponding node in
            # the AST can result in StopIteration.
            if out_of_order_html_node:
                # If a prior trace node was an out-of-order HTML RawBlock,
                # keep advancing through the trace until it catches up with
                # the current AST location.  Note that the node types being
                # different isn't necessarily an issue, because node type can
                # change between being reported in the trace and inserted in
                # the AST.
                if node_type != lookahead_trace_node_type:
                    if (lookahead_trace_node_type == 'RawBlock' and
                            lookahead_trace_node_format == 'html'):
                        continue
                    elif (node_type not in plain_or_para_block_node_types or
                            lookahead_trace_node_type not in plain_or_para_block_node_types):
                        # If unexpected type mismatch, give up
                        break
                out_of_order_html_node = False
            else:
                # Get the next AST leaf node
                try:
                    (node, node_type, node_depth,
                        parent_node, parent_node_type, parent_node_list, parent_node_list_index,
                        parent_node_list_parent_list, parent_node_list_parent_parent_list,
                        parent_chunk_node, parent_chunk_node_list) = next(ast_trace_nodes_iter)
                except StopIteration:
                    break
                if (node_type not in trace_leaf_block_node_types_without_null or
                        (node_type != lookahead_trace_node_type and
                            node_type == 'RawBlock' and node['c'][0].lower() == 'html')):
                    # Skip internal nodes, and skip HTML RawBlocks that only
                    # appear in the AST or appear out-of-order in the trace
                    # (while maintaining a list of these nodes for making a
                    # basic attempt at correcting line numbers)
                    try:
                        while True:
                            if node_type not in trace_leaf_block_node_types_without_null:
                                parent_chunk_node_list_stack.insert(node_depth, parent_chunk_node_list)
                                (node, node_type, node_depth,
                                    parent_node, parent_node_type, parent_node_list, parent_node_list_index,
                                    parent_node_list_parent_list, parent_node_list_parent_parent_list,
                                    parent_chunk_node, parent_chunk_node_list) = next(ast_trace_nodes_iter)
                            elif (node_type != lookahead_trace_node_type and
                                    node_type == 'RawBlock' and node['c'][0].lower() == 'html'):
                                untraced_html_node_stack.append(node)
                                untraced_html_parent_chunk_node_list_stack.append(parent_chunk_node_list)
                                (node, node_type, node_depth,
                                    parent_node, parent_node_type, parent_node_list, parent_node_list_index,
                                    parent_node_list_parent_list, parent_node_list_parent_parent_list,
                                    parent_chunk_node, parent_chunk_node_list) = next(ast_trace_nodes_iter)
                            else:
                                break
                    except StopIteration:
                        break
                if node_type != lookahead_trace_node_type:
                    if (lookahead_trace_node_type == 'RawBlock' and
                            lookahead_trace_node_format == 'html'):
                        out_of_order_html_node = True
                        continue
                    elif (node_type not in plain_or_para_block_node_types or
                            lookahead_trace_node_type not in plain_or_para_block_node_types):
                        # If unexpected type mismatch, give up
                        break

            # Get the next leaf node in the trace again, this time while
            # calculating line numbers.  No StopIteration checks are needed;
            # the previous lookahead in the trace guarantees node existence.
            if parent_chunk_node_list is ast_root_node_list:
                # Right below root level in AST.  traces_iter needs to catch
                # up with lookahead_traces_iter, but all needed information is
                # already available in the lookahead variables.
                new_node_lists = False
                trace_tuple = next(traces_iter)
                if trace_tuple is not lookahead_trace_tuple:
                    while trace_tuple is not lookahead_trace_tuple:
                        trace_tuple = next(traces_iter)
                accurate_node_line_number = True
                accurate_ancestor_line_number = True
                line_number = last_lookahead_trace_line_number
                if parent_chunk_node_list_stack:
                    parent_chunk_node_list_stack = []
            elif id(parent_chunk_node_list) in chunk_node_list_start_line_numbers:
                # Continue in the AST at a level that has already been
                # visited.  While this is in the same chunk block node as one
                # or more previous leaf nodes, it isn't necessarily within the
                # same block node (for example, Div doesn't start a chunk).
                # Because this AST level has already been visited, and is not
                # Root, getting to it will not involve going to a lower chunk
                # level or passing through Root.  Since Null nodes or nodes
                # containing only Nulls can be skipped, they can't cause line
                # number errors in this case.
                #
                # The line number is only incremented if that can be done
                # accurately.  Otherwise it remains at the last known good
                # value.
                new_node_lists = False
                trace_tuple = next(traces_iter)
                if trace_tuple is not lookahead_trace_tuple:
                    while trace_tuple is not lookahead_trace_tuple:
                        trace_node_type = trace_tuple[0]
                        if trace_node_type not in trace_leaf_block_node_types_with_null:
                            parent_chunk_node_list_stack.pop()
                        trace_tuple = next(traces_iter)
                chunk_offset = chunk_node_list_start_line_numbers[id(parent_chunk_node_list)]
                if chunk_offset is None:
                    accurate_node_line_number = False
                else:
                    accurate_node_line_number = True
                    accurate_ancestor_line_number = True
                    line_number = chunk_offset + last_lookahead_trace_line_number - 1
            else:
                # Visiting deeper levels in the AST for the first time.
                # Traveling to the leaf node may involve passing through Root.
                new_node_lists = True
                null_count = 0
                last_null_offset = 0
                null_backtrack = False
                (last_trace_node_type, last_trace_node_format,
                    last_trace_line_number, last_trace_in_chunk) = trace_tuple
                trace_tuple = next(traces_iter)
                if trace_tuple is not lookahead_trace_tuple:
                    while trace_tuple is not lookahead_trace_tuple:
                        if last_trace_node_type not in trace_leaf_block_node_types_with_null:
                            current_trace_parent_chunk_node_list = parent_chunk_node_list_stack.pop()
                            if not last_trace_in_chunk:
                                line_number = trace_line_number
                                null_count = 0
                                last_null_offset = 0
                                null_backtrack = False
                            elif id(current_trace_parent_chunk_node_list) in chunk_node_list_start_line_numbers:
                                chunk_offset = chunk_node_list_start_line_numbers[id(current_trace_parent_chunk_node_list)]
                                if chunk_offset is not None:
                                    line_number = chunk_offset + last_trace_line_number - 1
                                    null_count = 0
                                    last_null_offset = 0
                                    null_backtrack = False
                            elif null_count > 0:
                                null_backtrack = True
                        elif last_trace_node_type == '':
                            if not last_trace_in_chunk:
                                line_number = last_trace_line_number
                                null_count = 0
                                last_null_offset = 0
                                null_backtrack = False
                            else:
                                null_count += 1
                                last_null_offset = last_trace_line_number - 1
                        # Leaf nodes are possible here, but require no special
                        # handling.  There could be an out-of-order HTML
                        # RawBlock, which should be ignored since it would be
                        # at the end of the chunk and thus followed in the
                        # trace by an internal node that would reset line
                        # numbering.
                        (last_trace_node_type, last_trace_node_format,
                            last_trace_line_number, last_trace_in_chunk) = trace_tuple
                        trace_tuple = next(traces_iter)
                if any(chunk_node_list_start_line_numbers.get(id(node_list), ()) is None
                        for node_list in parent_chunk_node_list_stack):
                    # At least one ancestor has inaccurate line numbering
                    accurate_node_line_number = False
                elif untraced_html_node_stack:
                    accurate_node_line_number = True
                    if any(node_list is not parent_chunk_node_list
                            for node_list in untraced_html_parent_chunk_node_list_stack)):
                        # There are untraced HTML nodes at one or more AST
                        # levels above the current one
                        accurate_ancestor_line_number = False
                    else:
                        accurate_ancestor_line_number = True
                elif null_count <= 1:
                    # No Nulls to worry about, or only a single one
                    accurate_node_line_number = True
                    accurate_ancestor_line_number = True
                elif (not null_backtrack and
                        id(parent_chunk_node_list_stack[-1]) in chunk_node_list_start_line_numbers):
                    # Multiple Nulls, but all at the same level, so the last
                    # Null gives the desired value
                    accurate_node_line_number = True
                    accurate_ancestor_line_number = True
                else:
                    # Ancestors are accurate, but multiple Nulls at multiple
                    # levels
                    accurate_node_line_number = True
                    accurate_ancestor_line_number = False

            if not accurate_node_line_number:
                # If line numbering can't be accurate, record that and reset
                # for the next loop
                if new_node_lists:
                    for node_list in reversed(parent_chunk_node_list_stack):
                        if id(node_list) in chunk_node_list_start_line_numbers:
                            break
                        chunk_node_list_start_line_numbers[id(node_list)] = None
                    chunk_node_list_start_line_numbers[id(parent_chunk_node_list)] = None
                if untraced_html_node_stack:
                    untraced_html_node_stack = []
                    untraced_html_parent_chunk_node_list_stack = []
            else:
                # If line numbering can be accurate, attempt various
                # corrections
                uncorrected_line_number = line_number
                if untraced_html_node_stack:
                    # For node lists that have already had their starting line
                    # number determined, there's no need to check for empty
                    # lines between or after HTML RawBlocks, because those
                    # would introduce Nulls, which would automatically cause
                    # any preceding HTML RawBlocks to be irrelevant in
                    # calculating line numbers.  For node lists that still do
                    # need to have their starting line number determined,
                    # empty lines may occur anywhere if there are Nulls.
                    for html_node in untraced_html_node_stack:
                        line_stripped = source_string_lines[line_number-1].lstrip(left_strip_chars).rstrip()
                        if new_node_lists and null_count > 0 and line_stripped == '':
                            while line_stripped == '':
                                line_number += 1
                                line_stripped = source_string_lines[line_number-1].lstrip(left_strip_chars).rstrip()
                        html = html_node['c'][1]
                        if html == line_stripped or (html in line_stripped and line_stripped.split(html, 1)[1] == ''):
                            line_number += 1
                    if new_node_lists and null_count > 0:
                        line_stripped = source_string_lines[line_number-1].lstrip(left_strip_chars).rstrip()
                        if new_node_lists and null_count > 0 and line_stripped == '':
                            while line_stripped == '':
                                line_number += 1
                                line_stripped = source_string_lines[line_number-1].lstrip(left_strip_chars).rstrip()
                    untraced_html_node_stack = []
                    untraced_html_parent_chunk_node_list_stack = []
                elif new_node_lists and null_count > 0:
                    if null_count == 1:
                        line_number += last_null_offset
                    else:
                        line_stripped = source_string_lines[line_number-1].lstrip(left_strip_chars).rstrip()
                        if line_stripped == '':
                            while line_stripped == '':
                                line_number += 1
                                line_stripped = source_string_lines[line_number-1].lstrip(left_strip_chars).rstrip()

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
                            line_number -= 1
                        else:
                            # Adjust for first definition.
                            if parent_node['c'][0] is not parent_node_list_parent_parent_list:
                                # If not the first term, correct overshoot.
                                line_number -= 1
                            # Add traceback span to term's inline node list
                            parent_node_list_parent_parent_list[0].insert(0, get_traceback_span_node(source_name, line_number))
                            # Deal with code and raw nodes in the term's node
                            # list.  Unlike the Para and Plain case later on,
                            # there is no possibility of having SoftBreak nodes,
                            # so processing is simpler.
                            for inline_walk_tuple in walk_node_list(parent_node_list_parent_parent_list[0]):
                                inline_node, inline_parent_node_list, inline_parent_node_list_index = inline_walk_tuple
                                inline_node_type = inline_node['t']
                                if inline_node_type == 'Code':
                                    if 'codebraid' in inline_node['c'][0][1]:  # classes
                                        code_chunk = PandocCodeChunk(inline_node, source_name, line_number, inline_parent_node_list, inline_parent_node_list_index)
                                        code_chunks.append(code_chunk)
                                elif inline_node_type == 'RawInline':
                                    freeze_raw_node(inline_node, source_name, line_number)
                            # Determine line number for start of first definition
                            line_number += 1
                            if source_string_lines[line_number-1].strip() == '':
                                line_number += 1
                elif (parent_node_type == 'Div' and
                        parent_node_list[0] is node and
                        source_string_lines[line_number-1].lstrip().startswith(':::')):
                    # If this is the beginning of the div, and this is a pandoc
                    # markdown fenced div rather than an HTML div, go to the next
                    # line, where the content actually begins
                    line_number += 1






            # Check that node types are consistent
            if node_type != trace_node_type:
                if node_type == 'Plain' and trace_node_type == 'Para':
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

                    if not last_trace_in_chunk or chunk_offset is not None:
                        #
                    if source_string_lines[line_number-1].strip() == node['c'][1]:
                        line_number += 1
                    continue
                else:
                    raise PandocError('Parsing trace failed')
            if node_type in ('Plain', 'Para'):
                if node['c']:
                    node['c'].insert(0, get_traceback_span_node(source_name, line_number))
                    # Find inline code nodes and determine their line numbers.
                    # Incrementing `line_number` here won't throw off
                    # the overall line numbering if there are errors in the
                    # numbering calculations, because `line_number` is
                    # reset after each Plain or Para node based on the trace.
                    for inline_walk_tuple in walk_node_list(node['c']):
                        inline_node, inline_parent_node_list, inline_parent_node_list_index = inline_walk_tuple
                        inline_node_type = inline_node['t']
                        if inline_node_type == 'SoftBreak':
                            line_number += 1
                        elif inline_node_type == 'Code':
                            if 'codebraid' in inline_node['c'][0][1]:  # classes
                                code_chunk = PandocCodeChunk(inline_node, source_name, line_number, inline_parent_node_list, inline_parent_node_list_index)
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
                                line = source_string_lines[line_number-1]
                                if code_content not in line:
                                    lookahead_line_number = line_number
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
                                            line_number = lookahead_line_number
                                            break
                        elif inline_node_type == 'RawInline':
                            freeze_raw_node(inline_node, source_name, line_number)
            elif node_type == 'CodeBlock':
                if 'codebraid' in node[0][1]:  # classes
                    code_chunk = PandocCodeChunk(node, source_name, line_number, parent_node_list, parent_node_list_index)
                    code_chunks.append(code_chunk)
            elif node_type == 'RawBlock':
                freeze_raw_node(node, source_name, line_number)





        if trace_node_type is not None:
            raise PandocError('Parsing trace failed; unused trace for {0}'.format(trace_node_type))

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
