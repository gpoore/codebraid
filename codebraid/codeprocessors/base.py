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
import re
import subprocess
import shlex
import sys
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
        re_patterns = []
        for lnp in line_number_patterns:
           re_patterns.append(r'(\d+)'.join(re.escape(x) for x in lnp.split('{number}')))
        self.line_number_re = re.compile('({0})'.format('|'.join(re_patterns)))





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
        self.run_errors = False
        self.run_error_chunks = []
        self.run_error_template_lines = None
        self.decode_error = False
        self.run_warnings = False
        self.run_warning_chunks = []
        self.run_warning_template_lines = None
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


    def finalize(self, *, lang_def, lang_def_bytes, hash_alg=None):
        '''
        Perform tasks that must wait until all code chunks are present,
        such as hashing.
        '''
        if hash_alg is None:
            h = hashlib.blake2b()
        elif hash_alg == 'sha512':
            h = hashlib.sha512()
        else:
            raise ValueError
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
        self.hash = '{0}_{1}'.format(h.hexdigest(), code_len)
        self.hash_root = self.tempsuffix = h.hexdigest()[:16]
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

        cache_config = {}
        if cache_path is not None:
            cache_config_path = cache_path / 'config.zip'
            if cache_config_path.is_file():
                with zipfile.ZipFile(str(cache_config_path)) as zf:
                    with zf.open('config.json') as f:
                        cache_config = json.load(f)
        if not cache_config and sys.version_info < (3, 6):
            cache_config['hash_algorithm'] = 'sha512'
        self.cache_config = cache_config

        raw_language_index = pkgutil.get_data('codebraid', 'languages/index.bespon')
        if raw_language_index is None:
            raise err.CodebraidError('Failed to find "codebraid/languages/index.bespon"')
        language_index = bespon.loads(raw_language_index)
        language_definitions = {}
        language_definitions_bytes = {}
        required_langs = set(cc.options['lang'] for cc in self.code_chunks if cc.command in ('run', 'expr'))
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
                if cc.command in ('run', 'expr'):
                    sessions_run[(cc.options['lang'], cc.options['session'])].append(cc)
        else:
            for cc in self.code_chunks:
                if cc.command in ('run', 'expr'):
                    sessions_run[(cc.options['lang'], cc.options['session'], cc.source_name)].append(cc)
        for session in sessions_run.values():
            session.finalize(lang_def=language_definitions[session.lang],
                             lang_def_bytes=language_definitions_bytes[session.lang],
                             hash_alg=cache_config.get('hash_algorithm', None))
        self._sessions_run = sessions_run

        # Cached stdout and stderr, plus any other relevant data.  Each
        # session has a key based on a BLAKE2b hash of its code plus the
        # length in bytes of the code when encoded with UTF8.  (SHA-512 is
        # used as a fallback for Python 3.5.)
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
                if cc.command == 'expr':
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
                                          stderr=subprocess.STDOUT,)
                if pre_proc.returncode != 0:
                    error = True
                    session.pre_run_error = True
                    encoding = session.lang_def.pre_run_encoding or locale.getpreferredencoding(False)
                    session.pre_run_error_lines = pre_proc.stdout.decode(encoding, errors='backslashreplace').splitlines()

            if not error:
                cmd_template = session.lang_def.run_command
                cmd = cmd_template.format(**template_dict)

                proc = subprocess.run(shlex.split(cmd),
                                      stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE)
                if proc.returncode != 0:
                    error = True
                    session.run_errors = True
                encoding = session.lang_def.run_encoding or locale.getpreferredencoding(False)
                try:
                    stdout_lines = proc.stdout.decode(encoding).splitlines()
                    stderr_lines = proc.stderr.decode(encoding).splitlines()
                except UnicodeDecodeError:
                    session.decode_error = True
                    stdout_lines = proc.stdout.decode(encoding, errors='backslashreplace').splitlines()
                    stderr_lines = proc.stderr.decode(encoding, errors='backslashreplace').splitlines()

            for cmd_template in session.lang_def.post_run_commands:
                if error:
                    break
                cmd = cmd_template.format(**template_dict)
                post_proc = subprocess.run(shlex.split(cmd),
                                           stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT)
                if post_proc.returncode != 0:
                    error = True
                    session.post_run_error = True
                    encoding = encoding=session.lang_def.post_run_encoding,
                    session.post_run_error_lines = post_proc.stdout.decode(errors='backslashreplace').splitlines()

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
            source_pattern_posix = source_path.as_posix()
            source_pattern_win = str(pathlib.PureWindowsPath(source_path))
            source_pattern_final = source_path.name
            error_patterns = session.lang_def.error_patterns
            warning_patterns = session.lang_def.warning_patterns
            line_number_re = session.lang_def.line_number_re
            for (std_lines, storage_list) in [(stdout_lines, chunk_stdout_list), (stderr_lines, chunk_stderr_list)]:
                chunk_start_index = -1
                for index, line in enumerate(std_lines):
                    if line.startswith(stdstream_delim_start) and line == stdstream_delim:
                        if chunk_start_index < 0:
                            # Handle possibility of errors or warnings from
                            # initial template code, or that occur before
                            # execution begins (for example, syntax errors).
                            # At least for basic language support, there
                            # typically won't be any final template code, so
                            # that case isn't handled currently.
                            if index > 1 and std_lines is stderr_lines:
                                chunk_end_index = index - 1
                                if std_lines[chunk_end_index]:
                                    chunk_end_index = index
                                leading_err_lines = std_lines[0:chunk_end_index]
                                if index == len(stderr_lines) - 1:
                                    # If the only delim is the one that was
                                    # inserted, the code never ran.  Normal
                                    # stderr processing will handle this
                                    # later.
                                    session.run_errors = True
                                    storage_list.append(leading_err_lines)
                                else:
                                    # Apparently the code ran, so this is
                                    # probably a template issue.
                                    for err_line in leading_err_lines:
                                        if any(x in err_line for x in error_patterns):
                                            session.run_errors = True
                                            session.run_error_template_lines = leading_err_lines
                                            break
                                        elif any(x in line for x in warning_patterns):
                                            session.run_warnings = True
                                            session.run_warning_template_lines = leading_err_lines
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
            for cc_n, (cc, cc_stdout_lines) in enumerate(zip(session.code_chunks, chunk_stdout_list)):
                # Process inline expressions by separating stdout from
                # expression value.
                if cc_stdout_lines is not None and cc.command == 'expr':
                    index = 0
                    for line in cc_stdout_lines:
                        if line.startswith(expression_delim_start) and line == expression_delim:
                            break
                        index += 1
                    if index < len(cc_stdout_lines):
                        if index < len(cc_stdout_lines) - 1:
                            cc.expr_lines = cc_stdout_lines[index+1:]
                        if cc_stdout_lines[index-1]:
                            del cc_stdout_lines[index:]
                        else:
                            del cc_stdout_lines[index-1:]
                        if not cc_stdout_lines:
                            chunk_stdout_list[cc_n] = None
            for cc_n, (cc, cc_stderr_lines) in enumerate(zip(session.code_chunks, chunk_stderr_list)):
                if cc_stderr_lines is not None:
                    # Process inline expressions.  Currently, this just
                    # amounts to deleting a stderr delimiter that separate
                    # stderr due to expression evaluation from stderr due to
                    # converting the expressiong to a string and printing it.
                    # The two varieties may be handled separately in future.
                    if cc.inline and cc.command == 'expr':
                        index = 0
                        for line in cc_stderr_lines:
                            if line.startswith(expression_delim_start) and line == expression_delim:
                                break
                            index += 1
                        if index < len(cc_stderr_lines):
                            if cc_stderr_lines[index-1]:
                                del cc_stderr_lines[index]
                            else:
                                del cc_stderr_lines[index-1:index+1]
                            if not cc_stderr_lines:
                                chunk_stderr_list[cc_n] = None
                    # Update session error and warning status
                    for line in cc_stderr_lines:
                        if any(x in line for x in error_patterns):
                            session.run_errors = True
                            session.run_error_chunks.append(cc)
                            break
                        elif any(x in line for x in warning_patterns):
                            session.run_warnings = True
                            if not (session.run_warning_chunks and session.run_warning_chunks[-1] is cc):
                                session.warning_chunks.append(cc)
                    # Sync error and warning line numbers with those in user
                    # code, and change path of code file
                    for index, line in enumerate(cc_stderr_lines):
                        check_line_for_number = False
                        if source_pattern_posix in line:
                            line = line.replace(source_pattern_posix, source_pattern_final)
                            check_line_for_number = True
                        elif source_pattern_win in line:
                            line = line.replace(source_pattern_win, source_pattern_final)
                            check_line_for_number = True
                        if check_line_for_number:
                            match = line_number_re.search(line)
                            if match:
                                for match_number in match.groups()[1:]:
                                    if match_number is not None:
                                        run_number = int(match_number)
                                try:
                                    user_number = run_code_to_user_code_dict[run_number]
                                except KeyError:
                                    while run_number >= 0 and run_number not in run_code_to_user_code_dict:
                                        run_number -= 1
                                    if run_number < 0:
                                        user_number = 0
                                    else:
                                        user_number = run_code_to_user_code_dict[run_num]
                                line = line.replace(match.group(0), match.group(0).replace(str(run_number), str(user_number)))
                            cc_stderr_lines[index] = line


        cache = {'stdout_lines': chunk_stdout_list, 'stderr_lines': chunk_stderr_list}
        self._cache[session.hash] = cache
        self._updated_cache_hash_roots.append(session.hash_root)
        return cache

    def _process_session(self, session, cache):
        for cc, cc_stdout_lines in zip(session.code_chunks, cache['stdout_lines']):
            cc.stdout_lines = cc_stdout_lines
        for cc, cc_stderr_lines in zip(session.code_chunks, cache['stderr_lines']):
            cc.stderr_lines = cc_stderr_lines


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
            if self.cache_config:
                cache_config_path = self.cache_path / 'config.zip'
                with zipfile.ZipFile(str(cache_config_path), 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr('cache.json', json.dumps(self.cache_config))
