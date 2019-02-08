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
        self.inline_expression_formatter = definition['inline_expression_formatter']
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
    Process code chunks.  This can involve executing code, extracting code
    from files for inclusion, or a combination of the two.
    '''
    def __init__(self, *, converter):
        self.code_chunks = converter.code_chunks
        self.code_options = converter.code_options
        self.cross_source_sessions = converter.cross_source_sessions
        self.cache_path = converter.cache_path

        raw_language_index = pkgutil.get_data('codebraid', 'languages/index.bespon')
        if raw_language_index is None:
            raise err.CodebraidError('Failed to find "codebraid/languages/index.bespon"')
        language_index = bespon.loads(raw_language_index)
        language_definitions = {}
        required_langs = set(cc.options['lang'] for cc in self.code_chunks if cc.command != 'code')
        for lang in required_langs:
            try:
                lang_def_fname = language_index[lang]
            except KeyError:
                raise err.CodebraidError('Language definition for "{0}" does not exist, or is not indexed'.format(lang))
            raw_lang_def = pkgutil.get_data('codebraid', 'languages/{0}'.format(lang_def_fname))
            if raw_lang_def is None:
                raise err.CodebraidError('Language definition for "{0}" does not exist'.format(lang))
            lang_def = bespon.loads(raw_lang_def)
            language_definitions[lang] = Language(lang, lang_def[lang])
        self._language_definitions = language_definitions

        session_chunk_lists = collections.defaultdict(list)
        if self.cross_source_sessions:
            for cc in self.code_chunks:
                if cc.command == 'run':
                    session_chunk_lists[(cc.options['lang'], cc.options['session'])].append(cc)
        else:
            for cc in self.code_chunks:
                if cc.command == 'run':
                    session_chunk_lists[(cc.options['lang'], cc.options['session'], cc.source_name)].append(cc)
        # Now that sessions are sorted, assign line numbers for first_number=next
        for session_chunk_list in session_chunk_lists.values():
            code_start_line_number = 1
            for cc in session_chunk_list:
                if not cc.inline:
                    cc.code_start_line_number = code_start_line_number
                    code_start_line_number += cc.code.count('\n')
        self.session_chunk_lists = session_chunk_lists

        # Cached stdout and stderr, plus any other relevant data.  Each
        # session has a key based on a BLAKE2b hash of its code plus the
        # length in bytes of the code when encoded with UTF8.
        self._cache = {}
        # Used files from the cache.  By default, these will be in
        # `<doc directory>/_codebraid` and will have names of the form
        # `<first 16 chars of hex session hash>.zip`.  They contain
        # `cache.json`, which is a dict mapping session keys to dicts that
        # contain lists of stdout and stderr, among other things.  While
        # each cache file will typically contain only a single session, it is
        # possible for a file to contain multiple sessions since the cache
        # file name is based on a truncated session hash.
        self._used_cache_files = set()
        # All session hash roots (<first 16 chars of hex session hash>) that
        # correspond to sessions with new or updated caches.
        self._updated_cache_hash_roots = []


    def process(self):
        '''
        Execute code and update cache.
        '''
        for key, session_chunk_list in self.session_chunk_lists.items():
            lang, session = key[:2]
            self._run(lang, session, session_chunk_list)
        self._update_cache()


    def _run(self, lang, session, session_chunk_list):
        h = hashlib.blake2b()
        code_len = 0
        for cc in session_chunk_list:
            code_bytes = cc.code.encode('utf8')
            h.update(code_bytes)
            code_len += len(code_bytes)
            # Hash needs to depend on code plus how it's divided into chunks.
            # Updating hash based on its current value at the end of each
            # chunk accomplishes this.
            h.update(h.digest())
        session_blake2b = h.hexdigest()
        session_hash = '{0}_{1}'.format(session_blake2b, code_len)
        session_hash_root = session_hash[:16]

        cache = self._cache.get(session_hash, None)
        if cache is None and self.cache_path is not None:
            session_cache_path = self.cache_path / '{0}.zip'.format(session_hash_root)
            if session_cache_path.is_file():
                with zipfile.ZipFile(str(session_cache_path)) as zf:
                    with zf.open('cache.json') as f:
                        self._cache.update(json.load(f))
                cache = self._cache.get(session_hash, None)
                self._used_cache_files.add(session_stream_cache_path.name)

        if cache is None:
            lang_def = self._language_definitions[lang]
            delim = 'Codebraid(hash="{0}")'.format(session_blake2b)
            run_code_list = []
            run_code_line_number = 1
            user_code_line_number = 1
            run_code_to_user_code_dict = {}
            chunk_wrapper_lines_before, chunk_wrapper_lines_after = [x.count('\n') for x in lang_def.chunk_wrapper.split('{code}')]

            run_code_list.append(lang_def.source_start.encode('utf8'))
            run_code_line_number += lang_def.source_start.count('\n')
            for cc in session_chunk_list:
                run_code_line_number += chunk_wrapper_lines_before
                for _ in range(cc.code.count('\n')):
                    run_code_to_user_code_dict[run_code_line_number] = user_code_line_number
                    user_code_line_number += 1
                    run_code_line_number += 1
                run_code_list.append(lang_def.chunk_wrapper.format(stdoutdelim=delim, stderrdelim=delim, code=cc.code).encode('utf8'))
                run_code_line_number += chunk_wrapper_lines_after
            run_code_list.append(lang_def.source_end.encode('utf8'))

            with tempfile.TemporaryDirectory() as tempdir:
                source_path = pathlib.Path(tempdir) / 'source.{0}'.format(lang_def.extension)
                with open(str(source_path), 'wb') as f:
                    for x in run_code_list:
                        f.write(x)
                pre_procs = []
                post_procs = []
                proc_error = False
                for cmd in lang_def.pre_run_commands:
                    if proc_error:
                        break
                    pre_proc = subprocess.run(shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                cmd = lang_def.run_command.format(executable=lang_def.executable, source=source_path.absolute().as_posix())
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
        if self.cache_path is not None:
            for cache_path in self.cache_path.glob('*.zip'):
                if cache_path.name not in self._used_cache_files:
                    cache_path.unlink()
            for hash_root in self._updated_cache_hash_roots:
                cache_path = self.cache_path / '{0}.zip'.format(hash_root)
                with zipfile.ZipFile(str(cache_path), 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                    data = {k: v for k, v in self._cache.items() if k.startswith(hash_root)}
                    zf.writestr('cache.json', json.dumps(data))
