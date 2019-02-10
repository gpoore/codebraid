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
import locale
import os
import pathlib
import pkgutil
import platform
import subprocess
import shlex
import tempfile
import zipfile
from .. import err
from .. import util




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
        self.pre_run_encoding = definition.pop('pre_run_encoding', None)
        self.run_command = definition.pop('run_command', '{executable} {source}')
        self.run_encoding = definition.pop('run_encoding', None)
        post_run_commands = definition.pop('post_run_commands', [])
        if not isinstance(post_run_commands, list):
            post_run_commands = [post_run_commands]
        self.post_run_commands = post_run_commands
        self.post_run_encoding = definition.pop('post_run_encoding', None)
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




class Session(object):
    '''
    Code chunks comprising a session.
    '''
    def __init__(self, session_key):
        self.lang = session_key[0]
        self.name = session_key[1]
        if len(session_key) == 2:
            self.source_name = None
        else:
            self.source_name = session_key[2]

        self.code_options = None
        self.code_chunks = []
        self.errors = False
        self.warnings = False
        self._code_start_line_number = 1
        self.source_error_chunks = []
        self.source_warning_chunks = []
        self.pre_run_error = False
        self.pre_run_error_lines = None
        self.run_error = False
        self.run_error_lines = None
        self.post_run_error = False
        self.post_run_error_lines = None


    def append(self, code_chunk):
        '''
        Append a code chunk to internal code chunk list.
        '''
        if not code_chunk.inline:
            code_chunk.code_start_line_number = self._code_start_line_number
            self._code_start_line_number += len(code_chunk.code_lines)
        if code_chunk.source_errors:
            self.source_error_chunks.append(code_chunk)
            self.errors = True
        if code_chunk.source_warnings:
            self.source_warning_chunks.append(code_chunk)
            self.warnings = True
        self.code_chunks.append(code_chunk)


    def finalize(self, lang_def, lang_def_bytes):
        '''
        Perform tasks that must wait until all code chunks are present,
        such as hashing.
        '''
        h = hashlib.blake2b()
        code_len = 0
        # Hash needs to depend on the language definition
        h.update(lang_def_bytes)
        h.update(h.digest())
        for cc in self.code_chunks:
            code_bytes = cc.code.encode('utf8')
            h.update(code_bytes)
            code_len += len(code_bytes)
            # Hash needs to depend on code plus how it's divided into chunks.
            # Updating hash based on its current value at the end of each
            # chunk accomplishes this.
            h.update(h.digest())
        session_blake2b = h.hexdigest()
        self.hash = '{0}_{1}'.format(session_blake2b, code_len)
        self.hash_root = session_blake2b[:16]
        self.tempsuffix = session_blake2b[:16]
        self.lang_def = lang_def
        self.lang_def_bytes = lang_def_bytes




class CodeProcessor(object):
    '''
    Process code chunks.  This can involve executing code, extracting code
    from files for inclusion, or a combination of the two.
    '''
    def __init__(self, *, code_chunks, code_options, cross_source_sessions, cache_path):
        self.code_chunks = code_chunks
        self.code_options = code_options
        self.cross_source_sessions = cross_source_sessions
        self.cache_path = cache_path

        raw_language_index = pkgutil.get_data('codebraid', 'languages/index.bespon')
        if raw_language_index is None:
            raise err.CodebraidError('Failed to find "codebraid/languages/index.bespon"')
        language_index = bespon.loads(raw_language_index)
        language_definitions = {}
        language_definitions_bytes = {}
        required_langs = set(cc.options['lang'] for cc in self.code_chunks if cc.command == 'run')
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
            # The raw language definition will be hashed as part of creating
            # the cache.  Make sure that this won't depend on platform.
            language_definitions_bytes[lang] = raw_lang_def.replace(b'\r\n', b'\n')

        sessions_run = util.KeyDefaultDict(Session)
        if self.cross_source_sessions:
            for cc in self.code_chunks:
                if cc.command == 'run':
                    sessions_run[(cc.options['lang'], cc.options['session'])].append(cc)
        else:
            for cc in self.code_chunks:
                if cc.command == 'run':
                    sessions_run[(cc.options['lang'], cc.options['session'], cc.source_name)].append(cc)
        for session in sessions_run.values():
            session.finalize(language_definitions[session.lang], language_definitions_bytes[session.lang])
        self._sessions_run = sessions_run

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
        for session in self._sessions_run.values():
            if not session.errors:
                session_cache = self._load_cache(session)
                if session_cache is None:
                    session_cache = self._run(session)
                self._process_session(session, session_cache)
        self._update_cache()


    def _load_cache(self, session):
        '''
        Load cached output, if it exists.
        '''
        if self.cache_path is None:
            cache = None
        else:
            cache = self._cache.get(session.hash, None)
            if cache is None:
                session_cache_path = self.cache_path / '{0}.zip'.format(session.hash_root)
                if session_cache_path.is_file():
                    with zipfile.ZipFile(str(session_cache_path)) as zf:
                        with zf.open('cache.json') as f:
                            self._cache.update(json.load(f))
                    cache = self._cache.get(session.hash, None)
                    self._used_cache_files.add(session_cache_path.name)
        return cache


    def _run(self, session):
        stdstream_delim_start = 'CodebraidStd'
        stdstream_delim = '{0}(hash="{1}")'.format(stdstream_delim_start, session.hash[:64])
        expression_delim_start = 'CodebraidExpr'
        expression_delim = '{0}(hash="{1}")'.format(expression_delim_start, session.hash[64:])
        run_code_list = []
        run_code_line_number = 1
        user_code_line_number = 1
        run_code_to_user_code_dict = {}
        chunk_wrapper_n_lines_before, chunk_wrapper_n_lines_after = [x.count('\n') for x in session.lang_def.chunk_wrapper.split('{code}')]
        inline_expression_formatter_n_lines = session.lang_def.inline_expression_formatter.count('\n')

        run_code_list.append(session.lang_def.source_start.encode('utf8'))
        run_code_line_number += session.lang_def.source_start.count('\n')
        for cc in session.code_chunks:
            run_code_line_number += chunk_wrapper_n_lines_before
            if cc.inline:
                if 'expression' in cc.options['show']:
                    code = session.lang_def.inline_expression_formatter.format(stdoutdelim=expression_delim,
                                                                               stderrdelim=expression_delim,
                                                                               tempsuffix=session.tempsuffix,
                                                                               code=cc.code)
                    run_code_line_number += inline_expression_formatter_n_lines
                else:
                    code = cc.code
                run_code = session.lang_def.chunk_wrapper.format(stdoutdelim=stdstream_delim,
                                                                 stderrdelim=stdstream_delim,
                                                                 code=code)
            else:
                for _ in range(len(cc.code_lines)):
                    run_code_to_user_code_dict[run_code_line_number] = user_code_line_number
                    user_code_line_number += 1
                    run_code_line_number += 1
                run_code = session.lang_def.chunk_wrapper.format(stdoutdelim=stdstream_delim,
                                                                 stderrdelim=stdstream_delim,
                                                                 code=cc.code+'\n')
            run_code_list.append(run_code.encode('utf8'))
            run_code_line_number += chunk_wrapper_n_lines_after
        run_code_list.append(session.lang_def.source_end.encode('utf8'))

        error = False
        with tempfile.TemporaryDirectory() as tempdir:
            source_dir_path = pathlib.Path(tempdir)
            source_path = source_dir_path / 'source.{0}'.format(session.lang_def.extension)
            with open(str(source_path), 'wb') as f:
                for x in run_code_list:
                    f.write(x)

            template_dict = {'executable': session.lang_def.executable,
                             'extension': session.lang_def.extension,
                             'source': source_path.as_posix(),
                             'source_dir': source_dir_path.as_posix(),
                             'source_stem': source_dir_path.stem}

            for cmd_template in session.lang_def.pre_run_commands:
                if error:
                    break
                cmd = cmd_template.format(**template_dict)
                pre_proc = subprocess.run(shlex.split(cmd),
                                          stdout=subprocess.PIPE,
                                          stderr=subprocess.STDOUT,
                                          encoding=session.lang_def.pre_run_encoding,
                                          errors='backslashreplace')
                if pre_proc.returncode != 0:
                    error = True
                    session.pre_run_error = True
                    session.pre_run_error_lines = pre_proc.stdout.splitlines()

            if not error:
                cmd_template = session.lang_def.run_command
                cmd = cmd_template.format(**template_dict)

                proc = subprocess.run(shlex.split(cmd),
                                      stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE,
                                      encoding=session.lang_def.run_encoding,
                                      errors='backslashreplace')
                if proc.returncode != 0:
                    error = True
                    session.run_error = True
                stdout_lines = proc.stdout.splitlines()
                stderr_lines = proc.stderr.splitlines()

            for cmd_template in session.lang_def.post_run_commands:
                if error:
                    break
                cmd = cmd_template.format(**template_dict)
                post_proc = subprocess.run(shlex.split(cmd),
                                           stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT,
                                           encoding=session.lang_def.post_run_encoding,
                                           errors='backslashreplace')
                if post_proc.returncode != 0:
                    error = True
                    session.post_run_error = True
                    session.post_run_error_lines = post_proc.stdout.splitlines()

        if session.pre_run_error:
            chunk_stdout_list = [None]
            chunk_stderr_list = [session.pre_run_error_lines]
        elif session.post_run_error:
            chunk_stdout_list = [None]
            chunk_stderr_list = [session.post_run_error_lines]
        else:
            stdout_lines.append('')
            stdout_lines.append(stdstream_delim)
            stderr_lines.append('')
            stderr_lines.append(stdstream_delim)
            chunk_stdout_list = []
            chunk_stderr_list = []

            for (std_lines, storage_list) in [(stdout_lines, chunk_stdout_list), (stderr_lines, chunk_stderr_list)]:
                chunk_start_index = -1
                for index, line in enumerate(std_lines):
                    if line.startswith(stdstream_delim_start) and line == stdstream_delim:
                        if chunk_start_index < 0:
                            chunk_start_index = index + 1
                        else:
                            chunk_end_index = index - 1
                            if std_lines[chunk_end_index]:
                                chunk_end_index = index
                            if chunk_end_index > chunk_start_index:
                                storage_list.append(std_lines[chunk_start_index:chunk_end_index])
                            else:
                                storage_list.append(None)
                            chunk_start_index = index + 1

        cache = {'stdout_lines': chunk_stdout_list, 'stderr_lines': chunk_stderr_list}
        self._cache[session.hash] = cache
        self._updated_cache_hash_roots.append(session.hash_root)
        return cache

    def _process_session(self, session, cache):
        for cc, stdout_lines in zip(session.code_chunks, cache['stdout_lines']):
            cc.stdout_lines = stdout_lines
        for cc, stderr_lines in zip(session.code_chunks, cache['stderr_lines']):
            cc.stderr_lines = stderr_lines


    def _update_cache(self):
        if self.cache_path is not None:
            for cache_zip_path in self.cache_path.glob('*.zip'):
                if cache_zip_path.name not in self._used_cache_files:
                    cache_zip_path.unlink()
            for hash_root in self._updated_cache_hash_roots:
                cache_zip_path = self.cache_path / '{0}.zip'.format(hash_root)
                with zipfile.ZipFile(str(cache_zip_path), 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                    data = {k: v for k, v in self._cache.items() if k.startswith(hash_root)}
                    zf.writestr('cache.json', json.dumps(data))
