# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019, Geoffrey M. Poore
# All rights reserved.
#
# Licensed under the BSD 3-Clause License:
# http://opensource.org/licenses/BSD-3-Clause
#


import collections
import json
import os
import pathlib
import platform
import re
import subprocess
import sys
import tempfile
from typing import Dict, Optional, Sequence, Union
import warnings
from .base import Converter, CodeChunk
from .. import err




class PandocError(err.CodebraidError):
    pass




# Option processing functions
#
# Duplicate or invalid options related to presentation result in warnings,
# while duplicate or invalid options related to code execution result in
# errors.
#
# Code chunk classes
def _pandoc_class_lang_or_unknown(code_chunk, class_index, class_name, options):
    if 'lang' in options:
        if class_name.startswith('cb.'):
            code_chunk.source_errors.append('Unknown or unsupported Codebraid command "{0}"'.format(class_name))
        else:
            code_chunk.source_errors.append('Unknown non-Codebraid class')
    elif class_index > 0:
        if class_name.startswith('cb.'):
            code_chunk.source_errors.append('Unknown or unsupported Codebraid command "{0}"'.format(class_name))
        else:
            code_chunk.source_errors.append('The language/format "{0}" must be the first class for code chunk'.format(class_name))
    else:
        options['lang'] = class_name

def _pandoc_class_codebraid_command(code_chunk, class_index, class_name, options):
    if 'codebraid_command' in options:
        code_chunk.source_errors.append('Only one Codebraid command can be applied per code chunk')
    else:
        options['codebraid_command'] = class_name.split('.', 1)[1]

def _pandoc_class_line_anchors(code_chunk, class_index, class_name, options):
    if 'lineAnchors' in options:
        code_chunk.source_warnings.append('Duplicate line anchor class for code chunk')
    else:
        options['lineAnchors'] = True

def _pandoc_class_line_numbers(code_chunk, class_index, class_name, options):
    if 'line_numbers' in options:
        code_chunk.source_warnings.append('Duplicate line numbering class for code chunk')
    else:
        options['line_numbers'] = True

_pandoc_class_processors = collections.defaultdict(lambda: _pandoc_class_lang_or_unknown,
                                                   {'cb.run': _pandoc_class_codebraid_command,
                                                    'cb.expr': _pandoc_class_codebraid_command,
                                                    'cb.nb': _pandoc_class_codebraid_command,
                                                    'cb.paste': _pandoc_class_codebraid_command,
                                                    'lineAnchors': _pandoc_class_line_anchors,
                                                    'line-anchors': _pandoc_class_line_anchors,
                                                    'line_anchors': _pandoc_class_line_anchors,
                                                    'line_numbers': _pandoc_class_line_numbers,
                                                    'numberLines': _pandoc_class_line_numbers,
                                                    'number-lines': _pandoc_class_line_numbers,
                                                    'number_lines': _pandoc_class_line_numbers})

# Code chunk key-value attributes
def _pandoc_kv_generic(code_chunk, key, value, options):
    if key in options:
        code_chunk.source_errors.append('Duplicate "{0}" attribute for code chunk'.format(key))
    else:
        options[key] = value

def _pandoc_kv_bool(code_chunk, key, value, options):
    if key in options:
        code_chunk.source_errors.append('Duplicate "{0}" attribute for code chunk'.format(key))
    elif value not in ('true', 'false'):
        code_chunk.source_errors.append('Attribute "{0}" must be true or false for code chunk'.format(key))
    else:
        options[key] = value == 'true'

def _pandoc_kv_first_number(code_chunk, key, value, options):
    if 'first_number' in options:
        code_chunk.source_warnings.append('Duplicate first line number attribute for code chunk')
    else:
        try:
            value = int(value)
        except ValueError:
            pass
        options['first_number'] = value

def _pandoc_kv_name(code_chunk, key, value, options,
                     pandoc_id_re=re.compile(r'(?!\d|_)(?:\w+|[-:.]+)+')):
    if key in options:
        code_chunk.source_errors.append('Duplicate "{0}" attribute for code chunk'.format(key))
    elif not pandoc_id_re.match(value):
        # Identifier regex approximation for Pandoc/Readers/Markdown.hs
        code_chunk.source_errors.append('Code chunk "name" attribute must be valid Pandoc identifier: <letter>(<alphanum>|"-_:.")*')
    else:
        options['name'] = value

def _pandoc_kv_line_anchors(code_chunk, key, value, options):
    if 'lineAnchors' in options:
        code_chunk.source_warnings.append('Duplicate line anchor attribute for code chunk')
    elif value not in ('true', 'false'):
        code_chunk.source_warnings.append('Attribute "{0}" must be true or false for code chunk'.format(key))
    else:
        options['lineAnchors'] = value

def _pandoc_kv_line_numbers(code_chunk, key, value, options):
    if 'line_numbers' in options:
        code_chunk.source_warnings.append('Duplicate line numbering attribute for code chunk')
    elif value not in ('true', 'false'):
        code_chunk.source_warnings.append('Attribute "{0}" must be true or false for code chunk'.format(key))
    else:
        options['line_numbers'] = value

_pandoc_kv_processors = collections.defaultdict(lambda: _pandoc_kv_generic,
                                                {'complete': _pandoc_kv_bool,
                                                 'copy': _pandoc_kv_generic,
                                                 'example': _pandoc_kv_bool,
                                                 'first_number': _pandoc_kv_first_number,
                                                 'startFrom': _pandoc_kv_first_number,
                                                 'start-from': _pandoc_kv_first_number,
                                                 'start_from': _pandoc_kv_first_number,
                                                 'name': _pandoc_kv_name,
                                                 'lineAnchors': _pandoc_kv_line_anchors,
                                                 'line-anchors': _pandoc_kv_line_anchors,
                                                 'line_anchors': _pandoc_kv_line_anchors,
                                                 'line_numbers': _pandoc_kv_line_numbers,
                                                 'numberLines': _pandoc_kv_line_numbers,
                                                 'number-lines': _pandoc_kv_line_numbers,
                                                 'number_lines': _pandoc_kv_line_numbers,
                                                 'outside_main': _pandoc_kv_bool})




class PandocCodeChunk(CodeChunk):
    def __init__(self,
                 node: dict,
                 parent_node_list: list,
                 parent_node_list_index: int,
                 source_name: str,
                 source_start_line_number: int,
                 inline_parent_node: Optional[dict]=None):
        super().__pre_init__()

        self.node = node
        self.parent_node_list = parent_node_list
        self.parent_node_list_index = parent_node_list_index

        node_id, node_classes, node_kvpairs = node['c'][0]
        self.node_id = node_id
        self.node_classes = node_classes
        self.node_kvpairs = node_kvpairs
        code = node['c'][1]
        options = {}

        # Preprocess options
        if node_id:
            options['name'] = node_id
        inline = node['t'] == 'Code'
        for n, c in enumerate(node_classes):
            self._class_processors[c](self, n, c, options)
        for k, v in node_kvpairs:
            self._kv_processors[k](self, k, v, options)
        codebraid_command = options.pop('codebraid_command', None)

        # Process options
        super().__init__(codebraid_command, code, options, source_name, source_start_line_number=source_start_line_number, inline=inline)

        # Work with processed options -- now use `self.options`
        if inline:
            if (self.options['example'] and (inline_parent_node is None or
                    'codebraid_pseudonode' in inline_parent_node or len(parent_node_list) > 1)):
                self.source_errors.insert(0, 'Option "example" is only allowed for inline code that is in a paragraph by itself')
                self.options['example'] = False
            self.inline_parent_node = inline_parent_node
        pandoc_id = self.options.get('name', '')
        pandoc_classes = []
        pandoc_kvpairs = []
        if 'lang' in options:
            pandoc_classes.insert(0, options['lang'])
        if self.options.pop('lineAnchors', False):
            pandoc_classes.append('lineAnchors')
        if self.options.get('line_numbers', False):
            pandoc_classes.append('numberLines')
        # Can't handle `startFrom` yet here, because if it is `next`, then
        # the value depends on which other code chunks end up in the session.
        # Starting line number is determined when output is generated.

        self.pandoc_id = pandoc_id
        self.pandoc_classes = pandoc_classes
        self.pandoc_kvpairs = pandoc_kvpairs
        self._output_nodes = None
        self._as_markdown = None


    _class_processors = _pandoc_class_processors
    _kv_processors = _pandoc_kv_processors

    # This may need additional refinement in future depending on allowed values
    _unquoted_kv_value_re = re.compile(r'[A-Za-z$_+\-][A-Za-z0-9$_+\-:]*')


    @property
    def output_nodes(self):
        '''
        A list of nodes representing output, or representing source errors if
        those prevented execution.
        '''
        if self._output_nodes is not None:
            return self._output_nodes
        nodes = []
        if self.source_errors:
            message = 'SOURCE ERROR in "{0}" near line {1}:'.format(self.source_name, self.source_start_line_number)
            if self.inline:
                nodes.append({'t': 'Code', 'c': [['', ['sourceError'], []], message + ' ' + ' '.join(self.source_errors)]})
            else:
                nodes.append({'t': 'CodeBlock', 'c': [['', ['sourceError'], []], message + '\n' + '\n'.join(self.source_errors)]})
            self._output_nodes = nodes
            return nodes
        if not self.inline and self.options['line_numbers']:
            # Line numbers can't be precalculated since they are determined by
            # how a session is assembled across potentially multiple sources
            first_number = self.options['first_number']
            if first_number == 'next':
                first_number = str(self.code_start_line_number)
            else:
                first_number = str(first_number)
            self.pandoc_kvpairs.append(['startFrom', first_number])
        t_code = 'Code' if self.inline else 'CodeBlock'
        t_raw = 'RawInline' if self.inline else 'RawBlock'
        for output, format in self.options['show'].items():
            if output == 'code':
                if self.inline:
                    code = self.code_lines[0]
                else:
                    code = '\n'.join(self.code_lines)
                nodes.append({'t': t_code, 'c': [[self.pandoc_id, self.pandoc_classes, self.pandoc_kvpairs], code]})
            elif output == 'expr':
                if format == 'verbatim':
                    if self.expr_lines is not None:
                        nodes.append({'t': t_code, 'c': [['', ['expr'], []], ' '.join(self.expr_lines)]})
                elif format == 'verbatim_or_empty':
                    if self.expr_lines is not None:
                        nodes.append({'t': t_code, 'c': [['', ['expr'], []], ' '.join(self.expr_lines)]})
                    else:
                        nodes.append({'t': t_code, 'c': [['', ['expr'], []], '\xa0']})
                elif format == 'raw':
                    if self.expr_lines is not None:
                        nodes.append({'t': t_raw, 'c': ['markdown', ' '.join(self.expr_lines)]})
                else:
                    raise ValueError
            elif output == 'stdout':
                if format == 'verbatim':
                    if self.stdout_lines is not None:
                        if self.inline:
                            nodes.append({'t': t_code, 'c': [['', ['stdout'], []], ' '.join(self.stdout_lines)]})
                        else:
                            nodes.append({'t': t_code, 'c': [['', ['stdout'], []], '\n'.join(self.stdout_lines)]})
                elif format == 'verbatim_or_empty':
                    if self.stderr_lines is not None:
                        if self.inline:
                            nodes.append({'t': t_code, 'c': [['', ['stdout'], []], ' '.join(self.stdout_lines)]})
                        else:
                            nodes.append({'t': t_code, 'c': [['', ['stdout'], []], '\n'.join(self.stdout_lines)]})
                    else:
                        if self.inline:
                            nodes.append({'t': t_code, 'c': [['', ['stdout'], []], '\xa0']})
                        else:
                            nodes.append({'t': t_code, 'c': [['', ['stdout'], []], '\xa0\n']})
                elif format == 'raw':
                    if self.stdout_lines is not None:
                        if self.inline:
                            nodes.append({'t': t_raw, 'c': ['markdown', ' '.join(self.stdout_lines)]})
                        else:
                            nodes.append({'t': t_raw, 'c': ['markdown', '\n'.join(self.stdout_lines)]})
                else:
                    raise ValueError
            elif output == 'stderr':
                if format == 'verbatim':
                    if self.stderr_lines is not None:
                        if self.inline:
                            nodes.append({'t': t_code, 'c': [['', ['stderr'], []], ' '.join(self.stderr_lines)]})
                        else:
                            nodes.append({'t': t_code, 'c': [['', ['stderr'], []], '\n'.join(self.stderr_lines)]})
                elif format == 'verbatim_or_empty':
                    if self.stderr_lines is not None:
                        if self.inline:
                            nodes.append({'t': t_code, 'c': [['', ['stderr'], []], ' '.join(self.stderr_lines)]})
                        else:
                            nodes.append({'t': t_code, 'c': [['', ['stderr'], []], '\n'.join(self.stderr_lines)]})
                    else:
                        if self.inline:
                            nodes.append({'t': t_code, 'c': [['', ['stderr'], []], '\xa0']})
                        else:
                            nodes.append({'t': t_code, 'c': [['', ['stderr'], []], '\xa0\n']})
                elif format == 'raw':
                    if self.stderr_lines is not None:
                        if self.inline:
                            nodes.append({'t': t_raw, 'c': ['markdown', ' '.join(self.stderr_lines)]})
                        else:
                            nodes.append({'t': t_raw, 'c': ['markdown', '\n'.join(self.stderr_lines)]})
                else:
                    raise ValueError
            else:
                raise ValueError
        self._output_nodes = nodes
        return nodes


    @property
    def as_markdown(self):
        '''
        Generate an approximation of the Markdown source that created the
        node.  This is used in creating examples that show Markdown source
        plus output.
        '''
        if self._as_markdown is not None:
            return self._as_markdown
        attr_list = []
        if self.node_id:
            attr_list.append('#{0}'.format(self.node_id))
        for c in self.node_classes:
            attr_list.append('.{0}'.format(c))
        for k, v in self.node_kvpairs:
            if k != 'example':
                if not self._unquoted_kv_value_re.match(v):
                    v = '"{0}"'.format(v.replace('\\', '\\\\').replace('"', '\\"'))
                attr_list.append('{0}={1}'.format(k, v))
        if self.placeholder_code is not None:
            code = self.placeholder_code
        else:
            code = self.code
        if self.inline:
            code_strip = code.strip(' ')
            if code_strip.startswith('`'):
                code = ' ' + code
            if code_strip.endswith('`'):
                code = code + ' '
            delim = '`'
            while delim in code:
                delim += '`'
            md = '{delim}{code}{delim}{{{attr}}}'.format(delim=delim, code=code, attr=' '.join(attr_list))
        elif self.placeholder_code is None or self.placeholder_code:
            delim = '```'
            while delim in code:
                delim += '```'
            md = '{delim}{{{attr}}}\n{code}\n{delim}'.format(delim=delim, attr=' '.join(attr_list), code=code)
        else:
            md = '```{{{attr}}}\n```'.format(attr=' '.join(attr_list))
        self._as_markdown = md
        return md


    def update_parent_node(self):
        '''
        Update parent node with output.
        '''
        if not self.options['example']:
            index = self.parent_node_list_index
            self.parent_node_list[index:index+1] = self.output_nodes
            return
        markup_node = {'t': 'CodeBlock', 'c': [['', [], []], self.as_markdown]}
        example_div_contents = [{'t': 'Div', 'c': [['', ['exampleMarkup'], []], [markup_node]]}]
        output_nodes = self.output_nodes
        if output_nodes:
            if self.inline:
                # `output_nodes` are all inline, but will be inserted into a
                # div, so need a block-level wrapper
                output_nodes = [{'t': 'Para', 'c': output_nodes}]
            example_div_contents.append({'t': 'Div', 'c': [['', ['exampleOutput'], []], output_nodes]})
        example_div_node = {'t': 'Div', 'c': [['', ['example'], []], example_div_contents]}
        if self.inline:
            # An inline node can't be replaced with a div directly.  Instead,
            # its block-level parent node is redefined.  The validity of this
            # operation is checked during initialization.
            parent_para_plain_node = self.inline_parent_node
            parent_para_plain_node['t'] = 'Div'
            parent_para_plain_node['c'] = example_div_node['c']
        else:
            index = self.parent_node_list_index
            self.parent_node_list[index] = example_div_node





def walk_node_list(node_list, enumerate=enumerate, isinstance=isinstance):
    '''
    Walk all AST nodes in a list, recursively descending to walk all
    child nodes as well.  The walk function is written so that it is
    only ever called on lists, reducing recursion depth and reducing
    the number of times the walk function is called.  Thus, it is
    never called on `Str` nodes and other leaf nodes, which will
    typically make up the vast majority of nodes.

    DefinitionLists are handled specially to wrap terms in fake Plain
    nodes, which are marked so that they can be identified later if necessary.
    This simplifies processing.

    Returns nodes plus their parent lists with indices.
    '''
    for index, obj in enumerate(node_list):
        if isinstance(obj, list):
            yield from walk_node_list(obj)
        elif isinstance(obj, dict):
            yield (obj, node_list, index)
            obj_contents = obj.get('c', None)
            if obj_contents is not None and isinstance(obj_contents, list):
                if obj['t'] != 'DefinitionList':
                    yield from walk_node_list(obj_contents)
                else:
                    for elem in obj_contents:
                        term, definition = elem
                        yield ({'t': 'Plain', 'c': term, 'codebraid_pseudonode': True}, elem, 0)
                        yield from walk_node_list(term)
                        yield from walk_node_list(definition)


def walk_node_list_less_note_contents(node_list, enumerate=enumerate, isinstance=isinstance):
    '''
    Like `walk_node_list()`, except that it will return a `Note` node
    but not iterate through it.  It can be useful to process `Note`
    contents separately since they are typically located in another
    part of the document and may contain block nodes.
    '''
    for index, obj in enumerate(node_list):
        if isinstance(obj, list):
            yield from walk_node_list_less_note_contents(obj)
        elif isinstance(obj, dict):
            yield (obj, node_list, index)
            if obj['t'] == 'Note':
                continue
            obj_contents = obj.get('c', None)
            if obj_contents is not None and isinstance(obj_contents, list):
                if obj['t'] != 'DefinitionList':
                    yield from walk_node_list_less_note_contents(obj_contents)
                else:
                    for elem in obj_contents:
                        term, definition = elem
                        yield ({'t': 'Plain', 'c': term, 'codebraid_pseudonode': True}, elem, 0)
                        yield from walk_node_list_less_note_contents(term)
                        yield from walk_node_list_less_note_contents(definition)




class PandocConverter(Converter):
    '''
    Converter based on Pandoc (https://pandoc.org/).

    Pandoc is used to parse input into a JSON-based AST.  Code nodes in the
    AST are located, processed, and then replaced.  Next, the AST is converted
    back into the original input format (or possibly another format), and
    reparsed into a new AST.  This allows raw code output to be interpreted as
    markup.  Finally, the new AST can be converted into the output format.
    '''
    def __init__(self, *,
                 pandoc_path: Optional[Union[str, pathlib.Path]]=None,
                 pandoc_file_scope: Optional[bool]=False,
                 from_format: Optional[str]=None,
                 scroll_sync: bool=False,
                 **kwargs):
        if from_format is not None and not isinstance(from_format, str):
            raise TypeError
        from_format, from_format_pandoc_extensions = self._split_format_extensions(from_format)
        if pandoc_path is None:
            pandoc_path = pathlib.Path('pandoc')
        else:
            pandoc_path = pathlib.Path(pandoc_path)
            if self.expandvars:
                pandoc_path = pathlib.Path(os.path.expandvars(pandoc_path))
            if self.expanduser:
                pandoc_path = pandoc_path.expanduser()
        try:
            proc = subprocess.run([str(pandoc_path), '--version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        except FileNotFoundError:
            raise RuntimeError('Pandoc path "{0}" does not exist'.format(pandoc_path))
        pandoc_version_match = re.search(rb'\d+\.\d+', proc.stdout)
        if not pandoc_version_match:
            raise RuntimeError('Could not determine Pandoc version from "{0} --version"; faulty Pandoc installation?'.format(pandoc_path))
        elif float(pandoc_version_match.group()) < 2.4:
            raise RuntimeError('Pandoc at "{0}" is version {1}, but >= 2.4 is required'.format(pandoc_path, float(pandoc_version_match.group())))
        self.pandoc_path = pandoc_path
        proc = subprocess.run([str(pandoc_path), '--list-output-formats'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        self.to_formats = set([x for x in (line.strip() for line in proc.stdout.decode('utf8').splitlines()) if x])
        super().__init__(from_format=from_format, **kwargs)


        if not isinstance(pandoc_file_scope, bool):
            raise TypeError
        if pandoc_file_scope and kwargs.get('cross_source_sessions') is None:
            self.cross_source_sessions = False
        self.pandoc_file_scope = pandoc_file_scope
        if self.from_format == 'markdown' and not pandoc_file_scope and len(self.source_strings) > 1:
            # If multiple files are being passed to Pandoc for concatenated
            # processing, ensure sufficient whitespace to prevent elements in
            # different files from merging, and insert a comment to prevent
            # indented elements from merging.  This means that the original
            # sources cannot be passed to Pandoc directly.
            for n, source_string in enumerate(self.source_strings):
                if source_string[-1] == '\n':
                    source_string += '\n<!--codebraid.eof-->\n\n'
                else:
                    source_string += '\n\n<!--codebraid.eof-->\n\n'
                self.source_strings[n] = source_string
            self.concat_source_string = ''.join(self.source_strings)

        self.from_format_pandoc_extensions = from_format_pandoc_extensions or ''

        if not isinstance(scroll_sync, bool):
            raise TypeError
        self.scroll_sync = scroll_sync
        if scroll_sync:
            raise NotImplementedError
            self._io_map = True

        self._asts = {}
        self._para_plain_source_name_node_line_number = []
        self._final_ast = None
        self._final_ast_bytes = None


    from_formats = set(['markdown'])
    to_formats = None
    multi_source_formats = set(['markdown'])


    def _split_format_extensions(self, format_extensions):
        '''
        Split a Pandoc `--from` or `--to` string of the form
        `format+extension1-extension2` into the format and extensions.
        '''
        if format_extensions is None:
            return (None, None)
        index = min([x for x in (format_extensions.find('+'), format_extensions.find('-')) if x >= 0], default=-1)
        if index >= 0:
            return (format_extensions[:index], format_extensions[index:])
        return (format_extensions, None)


    # Node sets are based on pandocfilters
    # https://github.com/jgm/pandocfilters/blob/master/pandocfilters.py
    _null_block_node_type = set([''])
    _block_node_types = set(['Plain', 'Para', 'CodeBlock', 'RawBlock',
                             'BlockQuote', 'OrderedList', 'BulletList',
                             'DefinitionList', 'Header', 'HorizontalRule',
                             'Table', 'Div']) | _null_block_node_type


    def _run_pandoc(self, *,
                    from_format: str,
                    to_format: str,
                    from_format_pandoc_extensions: Optional[str]=None,
                    to_format_pandoc_extensions: Optional[str]=None,
                    file_scope=False,
                    input: Optional[str]=None,
                    input_paths: Optional[Union[pathlib.Path, Sequence[pathlib.Path]]]=None,
                    input_name: Optional[str]=None,
                    output_path: Optional[pathlib.Path]=None,
                    overwrite: bool=False,
                    standalone: bool=False,
                    trace: bool=False,
                    decode_output: bool=True,
                    other_pandoc_args: Optional[Dict[str, str]]=None):
        '''
        Convert between formats using Pandoc.

        Communication with Pandoc is accomplished via pipes.
        '''
        if from_format not in self.from_formats and from_format != 'json':
            raise ValueError
        if to_format not in self.to_formats and to_format != 'json':
            raise ValueError
        if from_format_pandoc_extensions is None:
            from_format_pandoc_extensions = ''
        if to_format_pandoc_extensions is None:
            to_format_pandoc_extensions = ''
        if input and input_paths:
            raise TypeError
        if output_path is not None and not overwrite and output_path.exists():
            raise RuntimeError('Output path {0} exists, but overwrite=False'.format(output_path))

        cmd_list = [str(self.pandoc_path),
                    '--from', from_format + from_format_pandoc_extensions,
                    '--to', to_format + to_format_pandoc_extensions,
                    '--eol', 'lf']
        if standalone:
            cmd_list.append('--standalone')
        if trace:
            cmd_list.append('--trace')
        if file_scope:
            cmd_list.append('--file-scope')
        if output_path:
            cmd_list.extend(['--output', output_path.as_posix()])
        if other_pandoc_args:
            cmd_list.extend(other_pandoc_args)
        if input_paths is not None:
            if isinstance(input_paths, pathlib.Path):
                cmd_list.append(input_paths.as_posix())
            else:
                cmd_list.extend([p.as_posix() for p in input_paths])

        if platform.system() == 'Windows':
            # Prevent console from appearing for an instant
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        else:
            startupinfo = None

        try:
            proc = subprocess.run(cmd_list,
                                  input=input.encode('utf8') if input is not None else input,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE,
                                  startupinfo=startupinfo, check=True)
        except subprocess.CalledProcessError as e:
            if isinstance(input_paths, pathlib.Path) and input_name is None:
                input_name = input_paths.as_posix()
            if input_name is None:
                msg = 'Failed to run Pandoc:\n{0}'.format(e.stderr.decode('utf8'))
            else:
                msg = 'Failed to run Pandoc on source {0}:\n{1}'.format(input_name, e.stderr.decode('utf8'))
            raise PandocError(msg)
        if not decode_output:
            return (proc.stdout, proc.stderr)
        return (proc.stdout.decode('utf8'), proc.stderr.decode('utf8'))


    _walk_node_list = staticmethod(walk_node_list)
    _walk_node_list_less_note_contents = staticmethod(walk_node_list_less_note_contents)

    def _walk_ast(self, ast):
        '''
        Walk all nodes in AST.
        '''
        ast_root_node_list = ast['blocks']
        yield from self._walk_node_list(ast_root_node_list)

    def _walk_ast_less_note_contents(self, ast):
        '''
        Walk all nodes in AST, except those in Notes.
        '''
        ast_root_node_list = ast['blocks']
        yield from self._walk_node_list_less_note_contents(ast_root_node_list)


    @staticmethod
    def _io_map_span_node(source_name, line_number):
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
    def _io_map_span_node_to_raw_tracker(span_node):
        span_node['t'] = 'RawInline'
        span_node['c'] = [None, '\x02CodebraidTrace({0})\x03'.format(span_node['c'][0][2][0][1])]


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
                            [['format', raw_format]],  # kv pairs
                        ],
                        raw_content
                    ]

    @staticmethod
    def _freeze_raw_node_io_map(node, source_name, line_number,
                                type_translation_dict={'RawBlock': 'CodeBlock', 'RawInline': 'Code'}):
        '''
        Same as `_freeze_raw_node()`, but also store trace info.
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
    def _thaw_raw_node(node,
                       type_translation_dict={'CodeBlock': 'RawBlock', 'Code': 'RawInline'}):
        '''
        Convert a special code node back into its original form as a raw node.
        '''
        node['t'] = type_translation_dict[node['t']]
        node['c'] = [node['c'][0][2][0][1], node['c'][1]]

    @staticmethod
    def _thaw_raw_node_io_map(node,
                              type_translation_dict={'CodeBlock': 'RawBlock', 'Code': 'RawInline'}):
        '''
        Same as `_thaw_raw_node()`, but also return trace info.
        '''
        node['t'] = type_translation_dict[node['t']]
        for k, v in node['c'][0][2]:
            if k == 'format':
                raw_format = v
            else:
                trace = v
        node['c'] = [raw_format, '\x02CodebraidTrace({0})\x03'.format(trace) + node['c'][1]]


    # Regex for footnotes.  While they shouldn't be indented, the Pandoc
    # parser does recognize them as long as the indentation is less than 4
    # spaces.  The restrictions on the footnote identifier are minimal.
    # https://pandoc.org/MANUAL.html#footnotes
    # https://github.com/jgm/pandoc/blob/master/src/Text/Pandoc/Readers/Markdown.hs
    _footnote_re = re.compile(r' {0,3}\[\^[^ \t]+?\]:')


    def _load_and_process_initial_ast(self, *,
                                      source_string, single_source_name=None,
                                      any=any, int=int, len=len, next=next):
        '''
        Convert source string into a Pandoc AST and perform a number of
        operations on the AST.
          * Assign source line numbers to some nodes.  This is needed later
            for syncing error messages and is also needed for SyncTeX when the
            output is LaTeX.
          * Locate all code nodes for further processing.
          * Convert all raw nodes into specially marked code nodes.  This
            allows them to pass through later Pandoc conversions without
            being lost or being interpreted before the final conversion.
            These special code nodes are converted back into raw nodes in the
            final AST before the final format conversion.
        '''
        # Currently, a brute-force approach is used to determine line numbers:
        # walk the AST, and then search the source each time a Str node,
        # etc. is encountered, starting at the end of the last string that was
        # located.  This isn't guaranteed to give correct results in all
        # cases, since not all AST information like attributes is used in
        # searching, but it will usually give exact results.  Since syncing is
        # a usability feature, an occasional small loss of precision isn't
        # critical.  Pandoc's `--trace` output is used to simplify this
        # process.  The trace can be used to determine the exact start of
        # root-level nodes, so it periodically corrects any errors that have
        # accumulated.  It can also be used to locate and skip over footnotes
        # and link definitions.  These do not appear in the AST except in
        # processed form, so they would be a primary source of sync errors
        # otherwise.
        #
        # The original attempt at implementing line number syncing used only
        # the trace plus AST, with no string searching.  That might have had
        # much better performance had it worked.  Unfortunately, the data in
        # the trace is typically only sufficient to give approximate locations
        # at best.  The Pandoc markdown extension markdown_in_html_blocks can
        # produce markdown nodes preceded and followed by HTML RawBlocks, but
        # only the following RawBlock appears in the trace.  Similarly, HTML
        # RawBlocks can appear out of order in the trace (at the end of the
        # current chunk, rather than where they appear relative to other leaf
        # nodes; for example, `<hr/>`).  The trace data for DefinitionList
        # follows different rules (line numbers typically larger by 1),
        # presumably because of how Pandoc's parsing works.  Empty elements,
        # such as might occur in an incomplete bullet list, are difficult to
        # deal with.

        # Convert source string to trace plus AST with Pandoc
        from_format_pandoc_extensions = self.from_format_pandoc_extensions
        if self.from_format == 'markdown':
            from_format_pandoc_extensions += '-latex_macros-smart'
        pandoc_stdout_bytes, pandoc_stderr_bytes = self._run_pandoc(input=source_string,
                                                                    input_name=single_source_name,
                                                                    from_format=self.from_format,
                                                                    from_format_pandoc_extensions=from_format_pandoc_extensions,
                                                                    to_format='json',
                                                                    file_scope=self.pandoc_file_scope,
                                                                    trace=True,
                                                                    decode_output=False)
        try:
            if sys.version_info < (3, 6):
                ast = json.loads(pandoc_stdout_bytes.decode('utf8'))
            else:
                ast = json.loads(pandoc_stdout_bytes)
        except Exception as e:
            raise PandocError('Failed to load AST (incompatible Pandoc version?):\n{0}'.format(e))
        pandoc_stderr = pandoc_stderr_bytes.decode('utf8')
        if not (isinstance(ast, dict) and
                'pandoc-api-version' in ast and 'blocks' in ast):
            raise PandocError('Incompatible Pandoc API version')
        if ast['pandoc-api-version'][0:2] != [1, 17]:
            warnings.warn('Pandoc API is {0}.{1}, but Codebraid is designed for 1.17; this might cause issues'.format(*ast['pandoc-api-version'][0:2]))
        self._asts[single_source_name] = ast

        source_string_lines = source_string.splitlines()

        # Process trace to determine location of footnotes and link
        # definitions, and mark those line numbers as invalid
        invalid_line_numbers = set()
        left_trace_type_slice_index = len('[trace] Parsed [')
        right_trace_chunk_slice_index = len(' of chunk')
        footnote_re = self._footnote_re
        in_footnote = False
        trace = ('', 1, False)  # (<node type>, <line number>, <in chunk>)
        try:
            for trace_line in pandoc_stderr.splitlines():
                if trace_line.startswith('[WARNING]'):
                    print(trace_line, file=sys.stderr)
                    continue
                last_trace_node_type, last_trace_line_number, last_trace_in_chunk = trace
                trace_line = trace_line[left_trace_type_slice_index:]
                trace_node_type, trace_line = trace_line.split(' ', 1)
                trace_node_type = trace_node_type.rstrip(']')
                if trace_line.endswith('chunk'):
                    trace_in_chunk = True
                    trace_line_number = int(trace_line.split('at line ', 1)[1][:-right_trace_chunk_slice_index])
                else:
                    trace_in_chunk = False
                    trace_line_number = int(trace_line.split('at line ', 1)[1])
                trace = (trace_node_type, trace_line_number, trace_in_chunk)
                # Since footnotes must be at root level in the AST, line
                # numbers are guaranteed to be correct for their start
                # locations (no chunk numbering involved), so this will always
                # detect and skip them correctly.  There shouldn't be any
                # indentation before the `[^<identifier>]:`, but a regex is
                # used to cover all cases that the parser will accept.  A
                # footnote is always followed by a Null at root level.
                if (trace_in_chunk and not last_trace_in_chunk and
                        footnote_re.match(source_string_lines[last_trace_line_number-1])):
                    in_footnote = True
                    invalid_line_number = last_trace_line_number
                    continue
                if in_footnote:
                    if trace_in_chunk:
                        continue
                    in_footnote = False
                    while invalid_line_number < trace_line_number:
                        invalid_line_numbers.add(invalid_line_number)
                        invalid_line_number += 1
                # Link definitions must be at root level and produce Nulls.
                # Since they can contain much less text compared to footnotes,
                # it is unlikely that they will significantly affect line
                # numbers.  If more precision is needed later, something like
                # approach below could be used.  However, it would need to be
                # supplemented with a regex, like the footnote case, because
                # the conditions below are also met by some raw nodes.
                # ```
                # if not trace_node_type and not last_trace_in_chunk and not trace_in_chunk:
                #     invalid_line_number = last_trace_line_number
                #     while invalid_line_number < trace_line_number:
                #         invalid_line_numbers.add(invalid_line_number)
                #         invalid_line_number += 1
                # ```
        except Exception as e:
            raise PandocError('Incompatible Pandoc version or trace; cannot parse trace format:\n{0}'.format(e))

        # Iterator for source lines and line numbers that skips invalid lines
        if self.pandoc_file_scope or len(self.source_strings) == 1:
            source_name_line_and_number_iter = ((single_source_name, line, n+1) for (n, line) in enumerate(source_string_lines) if n+1 not in invalid_line_numbers)
        else:
            def make_source_name_line_and_number_iter():
                line_and_concat_line_number_iter = ((line, n+1) for (n, line) in enumerate(source_string_lines))
                for source_name, source_string in zip(self.source_names, self.source_strings):
                    for line_number in range(1, source_string.count('\n')+1):
                        line, concat_line_number = next(line_and_concat_line_number_iter)
                        if concat_line_number in invalid_line_numbers:
                            continue
                        yield (source_name, line, line_number)
            source_name_line_and_number_iter = make_source_name_line_and_number_iter()


        # Walk AST to associate line numbers with AST nodes
        para_plain_source_name_node_line_number = self._para_plain_source_name_node_line_number
        source_name, line, line_number = next(source_name_line_and_number_iter)
        line_index = 0
        block_node_types = self._block_node_types
        if self._io_map:
            freeze_raw_node = self._freeze_raw_node_io_map
        else:
            freeze_raw_node = self._freeze_raw_node
        for node_tuple in self._walk_ast_less_note_contents(ast):
            node, parent_node_list, parent_node_list_index = node_tuple
            node_type = node['t']
            if node_type == 'Str':
                node_contents = node['c']
                line_index = line.find(node_contents, line_index)
                if line_index >= 0:
                    line_index += len(node_contents)
                else:
                    source_name, line, line_number = next(source_name_line_and_number_iter)
                    line_index = line.find(node_contents)
                    if line_index < 0:
                        while line_index < 0:
                            source_name, line, line_number = next(source_name_line_and_number_iter)
                            line_index = line.find(node_contents)
                    line_index += len(node_contents)
                if para_plain_node is not None:
                    para_plain_source_name_node_line_number.append((source_name, para_plain_node, line_number))
                    para_plain_node = None
            elif node_type in ('Code', 'RawInline'):
                if node_type == 'Code' or node['c'][0].lower() != 'html':
                    # Long HTML comments can produce situations in which
                    # searching fails.  This is likely related to the HTML
                    # RawBlock issue.
                    node_contents = node['c'][1]
                    last_line_index = line_index
                    line_index = line.find(node_contents, line_index)
                    if line_index >= 0:
                        line_index += len(node_contents)
                    else:
                        line_index = last_line_index
                        for node_contents_elem in node_contents.split(' '):
                            line_index = line.find(node_contents_elem, line_index)
                            if line_index >= 0:
                                line_index += len(node_contents_elem)
                            else:
                                source_name, line, line_number = next(source_name_line_and_number_iter)
                                line_index = line.find(node_contents_elem)
                                if line_index < 0:
                                    while line_index < 0:
                                        source_name, line, line_number = next(source_name_line_and_number_iter)
                                        line_index = line.find(node_contents_elem)
                                line_index += len(node_contents_elem)
                if node_type == 'Code':
                    if any(c == 'cb' or c.startswith('cb.') for c in node['c'][0][1]):  # 'cb.*' in classes
                        code_chunk = PandocCodeChunk(node, parent_node_list, parent_node_list_index,
                                                     source_name, line_number, inline_parent_node=para_plain_node)
                        self.code_chunks.append(code_chunk)
                else:
                    freeze_raw_node(node, source_name, line_number)
                if para_plain_node is not None:
                    para_plain_source_name_node_line_number.append((source_name, para_plain_node, line_number))
                    para_plain_node = None
            elif node_type == 'CodeBlock':
                node_contents_lines = node['c'][1].splitlines()
                for node_contents_line in node_contents_lines:
                    if node_contents_line not in line:
                        # Move forward a line at a time until match
                        source_name, line, line_number = next(source_name_line_and_number_iter)
                        if node_contents_line not in line:
                            while node_contents_line not in line:
                                source_name, line, line_number = next(source_name_line_and_number_iter)
                    # Once there's a match, move forward one line per loop
                    source_name, line, line_number = next(source_name_line_and_number_iter)
                line_index = 0
                if any(c == 'cb' or c.startswith('cb.') for c in node['c'][0][1]):  # 'cb.*' in classes
                    code_chunk = PandocCodeChunk(node, parent_node_list, parent_node_list_index,
                                                 source_name, line_number - len(node_contents_lines))
                    self.code_chunks.append(code_chunk)
                para_plain_node = None
            elif node_type == 'RawBlock':
                # Since some RawBlocks can be inline in the sense that their
                # content does not begin on a new line (especially HTML, LaTeX
                # to a lesser extent), use `.find()` rather than `in` to
                # guarantee results.  The `len(node_contents_line) or 1`
                # guarantees that multiple empty `node_contents_line` won't
                # keep matching the same `line`.
                node_format, node_contents = node['c']
                node_format = node_format.lower()
                if node_format == 'html':
                    if node_contents == '<!--codebraid.eof-->':
                        node['t'] = 'Null'
                        del node['c']
                    else:
                        freeze_raw_node(node, source_name, line_number)
                else:
                    # While this almost always works for HTML, it does fail in
                    # at least some cases because the node contents do not
                    # necessarily correspond to the verbatim content of the
                    # document.  For example, try the invalid HTML
                    # `<hr/></hr/>`; the first tag becomes `<hr />` with
                    # an inserted space.
                    # https://github.com/jgm/pandoc/issues/5305
                    node_contents_lines = node_contents.splitlines()
                    for node_contents_line in node_contents_lines:
                        line_index = line.find(node_contents_line)
                        if line_index >= 0:
                            line_index += len(node_contents_line) or 1
                        else:
                            source_name, line, line_number = next(source_name_line_and_number_iter)
                            line_index = line.find(node_contents_line)
                            if line_index < 0:
                                while line_index < 0:
                                    source_name, line, line_number = next(source_name_line_and_number_iter)
                                    line_index = line.find(node_contents_line)
                            line_index += len(node_contents_line) or 1
                    freeze_raw_node(node, source_name, line_number - len(node_contents_lines) + 1)
                para_plain_node = None
            elif node_type == 'Note':
                note_para_plain_node = None
                for note_node_tuple in self._walk_node_list(node['c']):
                    note_node, note_parent_node_list, note_parent_node_list_index = note_node_tuple
                    note_node_type = node['t']
                    if note_node_type in ('Para', 'Plain'):
                        note_para_plain_node = note_node
                    elif note_node_type in ('Code', 'CodeBlock'):
                        if any(c == 'cb' or c.startswith('cb.') for c in node['c'][0][1]):  # 'cb.*' in classes
                            if note_node_type == 'Code':
                                code_chunk = PandocCodeChunk(note_node, note_parent_node_list, note_parent_node_list_index,
                                                            source_name, line_number, note_para_plain_node)
                            else:
                                code_chunk = PandocCodeChunk(note_node, note_parent_node_list, note_parent_node_list_index,
                                                            source_name, line_number)
                            self.code_chunks.append(code_chunk)
                        note_para_plain_node = None
                    elif note_node_type in ('RawInline', 'RawBlock'):
                        freeze_raw_node(note_node, source_name, line_number)
                        note_para_plain_node = None
                    else:
                        note_para_plain_node = None
            elif node_type in ('Para', 'Plain'):
                para_plain_node = node
            elif node_type in block_node_types:
                para_plain_node = None


    def _extract_code_chunks(self):
        if self.pandoc_file_scope or len(self.source_strings) == 1:
            for source_string, source_name in zip(self.source_strings, self.source_names):
                self._load_and_process_initial_ast(source_string=source_string, single_source_name=source_name)
        else:
            self._load_and_process_initial_ast(source_string=self.concat_source_string)


    def _postprocess_code_chunks(self):
        for code_chunk in reversed(self.code_chunks):
            # Substitute code output into AST in reversed order to preserve
            # indices
            code_chunk.update_parent_node()
        if self._io_map:
            # Insert tracking spans if needed
            io_map_span_node = self._io_map_span_node
            for source_name, node, line_number in self._para_plain_source_name_node_line_number:
                if node['t'] in ('Para', 'Plain'):
                    # When `example` is in use, a node can be converted into
                    # a different type
                    node['c'].insert(0, io_map_span_node(source_name, line_number))

        # Convert modified AST to markdown, then back, so that raw output
        # can be reinterpreted as markdown
        processed_markup = {}
        for source_name, ast in self._asts.items():
            processed_markup[source_name], _ = self._run_pandoc(input=json.dumps(ast),
                                                                from_format='json',
                                                                to_format='markdown',
                                                                to_format_pandoc_extensions=self.from_format_pandoc_extensions+'-latex_macros-smart',
                                                                standalone=True)

        if not self.pandoc_file_scope or len(self.source_strings) == 1:
            for markup in processed_markup.values():
                final_ast_bytes, pandoc_stderr_bytes = self._run_pandoc(input=markup,
                                                                        from_format='markdown',
                                                                        from_format_pandoc_extensions=self.from_format_pandoc_extensions,
                                                                        to_format='json',
                                                                        decode_output=False)
                if pandoc_stderr_bytes:
                    for line in pandoc_stderr_bytes.decode('utf8').splitlines():
                        print(line, file=sys.stderr)
        else:
            with tempfile.TemporaryDirectory() as tempdir:
                tempdir_path = pathlib.Path(tempdir)
                tempfile_paths = []
                for n, markup in enumerate(processed_markup.values()):
                    tempfile_path = tempdir_path / 'codebraid_intermediate_{0}.txt'.format(n)
                    tempfile_path.write_text(markup, encoding='utf8')
                    tempfile_paths.append(tempfile_path)
                final_ast_bytes, pandoc_stderr_bytes = self._run_pandoc(input_paths=tempfile_paths,
                                                                        from_format='markdown',
                                                                        from_format_pandoc_extensions=self.from_format_pandoc_extensions,
                                                                        to_format='json',
                                                                        decode_output=False)
                if pandoc_stderr_bytes:
                    for line in pandoc_stderr_bytes.decode('utf8').splitlines():
                        print(line, file=sys.stderr)
        if sys.version_info < (3, 6):
            final_ast = json.loads(final_ast_bytes.decode('utf8'))
        else:
            final_ast = json.loads(final_ast_bytes)
        self._final_ast_bytes = final_ast_bytes
        self._final_ast = final_ast

        if not self._io_map:
            thaw_raw_node = self._thaw_raw_node
            for node_tuple in self._walk_ast(final_ast):
                node, parent_node_list, parent_node_list_index = node_tuple
                node_type = node['t']
                if node_type in ('Code', 'CodeBlock') and 'codebraid--temp' in node['c'][0][1]:
                    thaw_raw_node(node)
        else:
            io_tracker_nodes = []
            io_map_span_node_to_raw_tracker = self._io_map_span_node_to_raw_tracker
            thaw_raw_node = self._thaw_raw_node_io_map
            for node_tuple in self._walk_ast(final_ast):
                node, parent_node_list, parent_node_list_index = node_tuple
                node_type = node['t']
                if node_type == 'Span' and 'codebraid--temp' in node['c'][0][1]:
                    io_map_span_node_to_raw_tracker(node)
                    io_tracker_nodes.append(node)
                if node_type in ('Code', 'CodeBlock') and 'codebraid--temp' in node['c'][0][1]:
                    thaw_raw_node(node)
            self._io_tracker_nodes = io_tracker_nodes


    def convert(self, *, to_format, output_path=None, overwrite=False,
                standalone=None, other_pandoc_args=None):
        if not isinstance(to_format, str):
            raise TypeError
        to_format, to_format_pandoc_extensions = self._split_format_extensions(to_format)
        if to_format not in self.to_formats:
            raise ValueError
        if not isinstance(standalone, bool):
            raise TypeError
        if output_path is not None:
            if not isinstance(output_path, pathlib.Path):
                if isinstance(output_path, str):
                    output_path = pathlib.Path(output_path)
                else:
                    raise TypeError

        if not isinstance(overwrite, bool):
            raise TypeError
        if output_path is not None and output_path.is_file() and not overwrite:
            raise RuntimeError('Output path {0} exists, but overwrite=False'.format(output_path))

        if not self._io_map:
            converted, _ = self._run_pandoc(input=json.dumps(self._final_ast),
                                            from_format='json',
                                            to_format=to_format,
                                            to_format_pandoc_extensions=to_format_pandoc_extensions,
                                            standalone=standalone,
                                            other_pandoc_args=other_pandoc_args)
        else:
            for node in self._io_tracker_nodes:
                node['c'][0] = to_format
            converted, _ = self._run_pandoc(input=json.dumps(self._final_ast),
                                            from_format='json',
                                            to_format=to_format,
                                            to_format_pandoc_extensions=to_format_pandoc_extensions,
                                            standalone=standalone,
                                            other_pandoc_args=other_pandoc_args)
            converted_lines = converted.splitlines()
            converted_to_source_dict = {}
            trace_re = re.compile(r'\x02CodebraidTrace\(.+?:\d+\)\x03')
            for index, line in enumerate(converted_lines):
                if '\x02' in line:
                    #  Tracking format:  '\x02CodebraidTrace({0})\x03'
                    line_split = line.split('\x02CodebraidTrace(', 1)
                    if len(line_split) == 1:
                        continue
                    line_before, trace_and_line_after = line_split
                    trace, line_after = trace_and_line_after.split(')\x03', 1)
                    line = line_before + line_after
                    converted_to_source_dict[str(index + 1)] = trace
                    if '\x02' in line:
                        line = trace_re.sub('', line)
                    converted_lines[index] = line
            converted_lines[-1] = converted_lines[-1] + '\n'
            converted = '\n'.join(converted_lines)
        if self.synctex:
            self._save_synctex_data(converted_to_source_dict)
        if output_path is not None:
            output_path.write_text(converted, encoding='utf8')
        else:
            print(converted, end='')
