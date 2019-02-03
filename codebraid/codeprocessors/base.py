# -*- coding: utf-8 -*-
#
# Copyright (c) 2019, Geoffrey M. Poore
# All rights reserved.
#
# Licensed under the BSD 3-Clause License:
# http://opensource.org/licenses/BSD-3-Clause
#


import bespon
import collections
import hashlib
import json
import os
import pathlib
import pkgutil
import subprocess
import shlex
import tempfile
import zipfile
from .. import err


class Language(object):
    '''
    Process language definition and insert default values.
    '''
    def __init__(self, name, definition):
        self.name = name
        self.language = definition.pop('language', name)
        self.executable = definition.pop('executable', name)
        self.extension = definition['extension']
        pre_run_commands = definition.pop('pre_run_commands', [])
        if not isinstance(pre_run_commands, list):
            pre_run_commands = [pre_run_commands]
        self.pre_run_commands = pre_run_commands
        self.run_command = definition.pop('run_command', '{executable} {source}')
        post_run_commands = definition.pop('post_run_commands', [])
        if not isinstance(post_run_commands, list):
            post_run_commands = [post_run_commands]
        self.post_run_commands = post_run_commands
        self.source_start = definition.pop('source_start', '')
        self.source_end = definition.pop('source_end', '')
        self.chunk_wrapper = definition['chunk_wrapper']
        self.inline_formatter = definition['inline_formatter']
        error_patterns = definition['error_patterns']
        if not isinstance(error_patterns, list):
            error_patterns = [error_patterns]
        self.error_patterns = error_patterns
        warning_patterns = definition['warning_patterns']
        if not isinstance(warning_patterns, list):
            warning_patterns = [warning_patterns]
        self.warning_patterns = warning_patterns
        line_number_patterns = definition['line_number_patterns']
        if not isinstance(line_number_patterns, list):
            line_number_patterns = [line_number_patterns]
        self.line_number_patterns = line_number_patterns




class CodeProcessor(object):
    '''
    Process code chunks
    '''
    def __init__(self, *, code_chunks, code_options):
        raw_language_index = pkgutil.get_data('codebraid', 'languages/index.bespon')
        if raw_language_index is None:
            raise err.CodebraidError('Failed to find "codebraid/languages/index.bespon"')
        language_index = bespon.loads(raw_language_index)
        language_definitions = {}
        for lang in set(cc.options['lang'] for cc in code_chunks):
            try:
                lang_def_file = language_index[lang]
            except KeyError:
                raise err.CodebraidError('Language definition for "{0}" does not exist, or is not indexed'.format(lang))
            raw_lang_def = pkgutil.get_data('codebraid', 'languages/{0}'.format(lang_def_file))
            if raw_lang_def is None:
                raise err.CodebraidError('Language definition for "{0}" does not exist'.format(lang))
            lang_def = bespon.loads(raw_lang_def)
            language_definitions[lang] = Language(lang, lang_def[lang])
        self._language_definitions = language_definitions

        session_chunk_lists = collections.defaultdict(list)
        for cc in code_chunks:
            if cc.command == 'run':
                session_chunk_lists[(cc.source_name, cc.options['lang'], cc.options['session'])].append(cc)
        self._session_chunk_lists = session_chunk_lists

        cache_path = pathlib.Path('_codebraid', 'cache')
        if not cache_path.is_dir():
            cache_path.mkdir(parents=True)
        self._cache_path = cache_path
        self._cache = {}
        self._used_cache_files = set()
        self._updated_cache_hash_roots = []

        self._process()


    def _process(self):
        for key, session_chunk_list in self._session_chunk_lists.items():
            source_name, lang, session = key
            self._run(source_name, lang, session, session_chunk_list)
        self._update_cache()


    def _run(self, source_name, lang, session, session_chunk_list):
        h = hashlib.blake2b()
        for cc in session_chunk_list:
            h.update(cc.code.encode('utf8'))
            # Hash needs to depend on code plus how it's divided into chunks
            h.update(h.digest())
        session_hash = h.hexdigest()
        session_hash_root = session_hash[:32]
        self._used_cache_files.add('{0}.zip'.format(session_hash_root))
        if session_hash in self._cache:
            cache = self._cache[session_hash]
        else:
            session_cache_path = self._cache_path / '{0}.zip'.format(session_hash_root)
            if session_cache_path.exists():
                with zipfile.ZipFile(str(session_cache_path)) as zf:
                    with zf.open('cache.json') as f:
                        self._cache.update(json.load(f))
                cache = self._cache[session_hash]
            else:
                cache = None

        if cache is None:
            lang_def = self._language_definitions[lang]
            delim = 'Codebraid(hash="{0}")'.format(session_hash)
            source_list = []
            source_line_number = 0
            code_line_number = 0
            source_to_code_map = {}
            chunk_wrapper_lines_before, chunk_wrapper_lines_after = lang_def.chunk_wrapper.split('{code}')
            chunk_wrapper_lines_before = chunk_wrapper_lines_before.count('\n')
            chunk_wrapper_lines_after = chunk_wrapper_lines_after.count('\n')

            source_list.append(lang_def.source_start.encode('utf8'))
            source_line_number += lang_def.source_start.count('\n')
            for cc in session_chunk_list:
                source_line_number += chunk_wrapper_lines_before
                for _ in range(cc.code.count('\n')):
                    code_line_number += 1
                    source_line_number += 1
                    source_to_code_map[source_line_number] = code_line_number
                source_list.append(lang_def.chunk_wrapper.format(stdoutdelim=delim, stderrdelim=delim, code=cc.code).encode('utf8'))
                source_line_number += chunk_wrapper_lines_after
            source_list.append(lang_def.source_end.encode('utf8'))
            with tempfile.TemporaryDirectory() as tempdir:
                source_path = pathlib.Path(tempdir) / 'source.{0}'.format(lang_def.extension)
                source_path_abs = source_path.absolute()
                with open(str(source_path), 'wb') as f:
                    for x in source_list:
                        f.write(x)
                for cmd in lang_def.pre_run_commands:
                    subprocess.run(shlex.split(cmd))
                cmd = lang_def.run_command.format(executable=lang_def.executable, source=source_path_abs.as_posix())
                proc = subprocess.run(shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                for cmd in lang_def.post_run_commands:
                    subprocess.run(shlex.split(cmd))
            stdout_list = []
            stdout_buffer = None
            for line in proc.stdout.decode('utf8').splitlines():
                if delim in line:
                    if stdout_buffer is not None:
                        if stdout_buffer:
                            stdout_buffer[-1] += '\n'
                            stdout_list.append('\n'.join(stdout_buffer))
                        else:
                            stdout_list.append(None)
                    stdout_buffer = []
                elif stdout_buffer is not None:
                    stdout_buffer.append(line)
            if stdout_buffer:
                stdout_buffer[-1] += '\n'
                stdout_list.append('\n'.join(stdout_buffer))
            else:
                stdout_list.append(None)
            stdout_list.extend([None]*(len(session_chunk_list)-len(stdout_list)))
            stderr_list = []
            stderr_buffer = None
            for line in proc.stderr.decode('utf8').splitlines():
                if delim in line:
                    if stderr_buffer is not None:
                        if stderr_buffer:
                            stderr_buffer[-1] += '\n'
                            stderr_list.append('\n'.join(stderr_buffer))
                        else:
                            stderr_list.append(None)
                    stderr_buffer = []
                elif stderr_buffer is not None:
                    stderr_buffer.append(line)
            if stderr_buffer:
                stderr_buffer[-1] += '\n'
                stderr_list.append('\n'.join(stderr_buffer))
            else:
                stderr_list.append(None)
            stderr_list.extend([None]*(len(session_chunk_list)-len(stdout_list)))

            cache = {'stdout': stdout_list, 'stderr': stderr_list}
            self._cache[session_hash] = cache
            self._updated_cache_hash_roots.append(session_hash_root)

        for cc, stdout, stderr in zip(session_chunk_list, cache['stdout'], cache['stderr']):
            cc.stdout = stdout
            cc.stderr = stderr


    def _update_cache(self):
        for fname in os.listdir(self._cache_path):
            if fname not in self._used_cache_files:
                pathlib.Path(self._cache_path / fname).unlink()
        for hash_root in self._updated_cache_hash_roots:
            hash_root_cache_path = self._cache_path / '{0}.zip'.format(hash_root)
            with zipfile.ZipFile(str(hash_root_cache_path), 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                data = {k: v for k, v in self._cache.items() if k.startswith(hash_root)}
                zf.writestr('cache.json', json.dumps(data))
