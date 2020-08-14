# -*- coding: utf-8 -*-
#
# Copyright (c) 2019, Geoffrey M. Poore
# All rights reserved.
#
# Licensed under the BSD 3-Clause License:
# http://opensource.org/licenses/BSD-3-Clause
#


import atexit
import bespon
import collections
import hashlib
import io
import json
import locale
import pathlib
import pkgutil
import queue
import re
import subprocess
import shlex
import shutil
import sys
import threading
import tempfile
import textwrap
import time
import zipfile
from .. import err
from .. import util
from ..version import __version__ as codebraid_version




class FailedProcess(object):
    '''
    Represent a failed `subprocess.run()` with an object analogous to
    CompletedProcess.  This allows FileNotFoundError to be handled just like
    other errors that do produce a CompletedProcess.
    '''
    def __init__(self, args, stderr=None, stdout=None):
        self.returncode = 1
        self.args = args
        self.stderr = stderr
        self.stdout = stdout




class Language(object):
    '''
    Process language definition and insert default values.
    '''
    def __init__(self, name, definition, definition_bytes):
        self.name = name
        # The language definition config file will be hashed as part of
        # creating the cache.  Make sure that this won't depend on platform.
        self.definition_bytes = definition_bytes.replace(b'\r\n', b'\n')
        try:
            self.language = definition.pop('language', name)
            executable = definition.pop('executable', None)
            if executable is None:
                if name not in ('python', 'python_repl'):
                    executable = name
                else:
                    # Windows can have python3, and Arch Linux uses python,
                    # so use python3 if it exists and otherwise python
                    executable = 'python3' if shutil.which('python3') else 'python'
            self.executable = executable
            self.extension = definition.pop('extension')
            self.pre_run_encoding = definition.pop('pre_run_encoding', None)
            pre_run_commands = definition.pop('pre_run_commands', [])
            if not isinstance(pre_run_commands, list):
                pre_run_commands = [pre_run_commands]
            self.pre_run_commands = pre_run_commands
            self.compile_encoding = definition.pop('compile_encoding', None)
            compile_commands = definition.pop('compile_commands', [])
            if not isinstance(compile_commands, list):
                compile_commands = [compile_commands]
            self.compile_commands = compile_commands
            self.run_encoding = definition.pop('run_encoding', None)
            self.run_command = definition.pop('run_command', '{executable} {source}')
            self.post_run_encoding = definition.pop('post_run_encoding', None)
            post_run_commands = definition.pop('post_run_commands', [])
            if not isinstance(post_run_commands, list):
                post_run_commands = [post_run_commands]
            self.post_run_commands = post_run_commands
            self.repl = definition.pop('repl', False)
            if not self.repl:
                self.source_template = definition.pop('source_template', '{code}\n')
                self.chunk_wrapper = definition.pop('chunk_wrapper')
                self.inline_expression_formatter = definition.pop('inline_expression_formatter', None)
            else:
                self.repl_template = definition.pop('repl_template')
            error_patterns = definition.pop('error_patterns', ['error', 'Error', 'ERROR'])
            if not isinstance(error_patterns, list):
                error_patterns = [error_patterns]
            self.error_patterns = error_patterns
            warning_patterns = definition.pop('warning_patterns', ['warning', 'Warning', 'WARNING'])
            if not isinstance(warning_patterns, list):
                warning_patterns = [warning_patterns]
            self.warning_patterns = warning_patterns
            line_number_patterns = definition.pop('line_number_patterns', [':{number}', 'line {number}'])
            if not isinstance(line_number_patterns, list):
                line_number_patterns = [line_number_patterns]
            self.line_number_patterns = line_number_patterns
            self.line_number_regex = definition.pop('line_number_regex', None)
        except KeyError as e:
            raise err.CodebraidError('Missing key(s) in language definition for "{0}":\n  {1}'.format(name, e.args[0]))
        if definition:
            raise err.CodebraidError('Unknown key(s) in language definition for "{0}":\n  {1}'.format(name, ', '.join("{0}".format(k) for k in definition)))

        re_patterns = []
        for lnp in line_number_patterns:
           re_patterns.append(r'(\d+)'.join(re.escape(x) for x in lnp.split('{number}')))
        self.line_number_pattern_re = re.compile('(?:{0})'.format('|'.join(re_patterns)))
        if self.line_number_regex is None:
            self.line_number_regex_re = None
        else:
            self.line_number_regex_re = re.compile(self.line_number_regex, re.MULTILINE)




class Session(object):
    '''
    Code chunks comprising a session.
    '''
    def __init__(self, session_key):
        self.code_processor = session_key[0]
        self.lang = session_key[1]
        self.name = session_key[2]
        if self.name is None:
            self._name_escaped = 'none'
        else:
            self._name_escaped = '"{0}"'.format(self.name)
        if len(session_key) == 3:
            self.source_name = None
        else:
            self.source_name = session_key[3]
        self.lang_def = None
        self.executable = None
        self.jupyter_kernel = None
        self.jupyter_timeout = None

        self.code_options = None
        self.code_chunks = []
        self.errors = False
        self.warnings = False
        self._code_start_line_number = 1
        self.source_error_chunks = []
        self.source_warning_chunks = []
        self.pre_run_errors = False
        self.pre_run_error_lines = None
        # Compile and run errors are treated as a single category separate
        # from pre/post errors.  This is because they can potentially be
        # synchronized with the source.
        self.compile_errors = False
        self.run_errors = False
        self.run_error_chunks = []
        self.decode_error = False
        self.run_warnings = False
        self.run_warning_chunks = []
        self.post_run_errors = False
        self.post_run_error_lines = None


    def append(self, code_chunk):
        '''
        Append a code chunk to internal code chunk list.
        '''
        code_chunk.session_obj = self
        code_chunk.session_index = len(self.code_chunks)
        if code_chunk.session_index == 0:
            jupyter_kernel = code_chunk.options['first_chunk_options'].get('jupyter_kernel')
            if jupyter_kernel is not None:
                self.repl = False
                self.jupyter_kernel = jupyter_kernel
                self.jupyter_timeout = code_chunk.options['first_chunk_options'].get('jupyter_timeout')
            else:
                self.lang_def = self.code_processor.language_definitions[self.lang]
                if self.lang_def is None:
                    self.executable = None
                    self.repl = None
                else:
                    self.executable = code_chunk.options['first_chunk_options'].get('executable')
                    self.repl = self.lang_def.repl
        elif code_chunk.options['first_chunk_options']:
            invalid_options = ', '.join('"{0}"'.format(k) for k in code_chunk.options['first_chunk_options'])
            del code_chunk.options['first_chunk_options']
            code_chunk.source_errors.append('Some options are only valid for the first code chunk in a session: {0}'.format(invalid_options))

        self.code_chunks.append(code_chunk)


    def finalize(self):
        '''
        Perform tasks that must wait until all code chunks are present,
        such as hashing.
        '''
        if self.code_chunks[0].options['outside_main']:
            from_outside_main_switches = 0
        else:
            from_outside_main_switches = 1
        to_outside_main_switches = 0
        incomplete_ccs = []
        last_cc = None
        for cc in self.code_chunks:
            if self.repl and cc.command != 'repl':
                cc.source_errors.append('Code executed in REPL mode must use the "repl" command')
            if cc.is_expr and self.lang_def is not None and self.lang_def.inline_expression_formatter is None:
                cc.source_errors.append('Inline expressions are not supported for {0}'.format(self.lang_def.name))
            if last_cc is not None and last_cc.options['outside_main'] != cc.options['outside_main']:
                if last_cc.options['outside_main']:
                    from_outside_main_switches += 1
                    if from_outside_main_switches > 1:
                        cc.source_errors.append('Invalid "outside_main" value; cannot switch back yet again')
                    for icc in incomplete_ccs:
                        # When switching from `outside_main`, all accumulated
                        # output belongs to the last code chunk `outside_main`
                        icc.session_output_index = last_cc.session_index
                    incomplete_ccs = []
                else:
                    if not last_cc.options['complete']:
                        last_cc.source_errors.append('The last code chunk before switching to "outside_main" must have "complete" value "true"')
                        if not self.source_error_chunks or self.source_error_chunks[-1] is not last_cc:
                            self.source_error_chunks.append(last_cc)
                            self.errors = True
                    to_outside_main_switches += 1
                    if to_outside_main_switches > 1:
                        cc.source_errors.append('Invalid "outside_main" value; cannot switch back yet again')
            if cc.options['complete']:
                cc.session_output_index = cc.session_index
                if incomplete_ccs:
                    for icc in incomplete_ccs:
                        icc.session_output_index = cc.session_index
                    incomplete_ccs = []
            else:
                incomplete_ccs.append(cc)
            if cc.source_errors:
                self.source_error_chunks.append(cc)
                self.errors = True
            if cc.source_warnings:
                self.source_warning_chunks.append(cc)
                self.warnings = True
            last_cc = cc
        if incomplete_ccs:
            # Last code chunk gets all accumulated output.  Last code chunk
            # could have `complete=false` or be `outside_main`.
            for icc in incomplete_ccs:
                icc.session_output_index = last_cc.session_index
        if self.errors:
            # Hashing and line numbers are only needed if code will indeed be
            # executed.  It is impossible to determine these in the case of
            # errors like copy errors which leave code for one or more chunks
            # undefined.
            return

        if sys.version_info < (3, 6):
            hasher = hashlib.sha512()
        else:
            hasher = hashlib.blake2b()
        code_len = 0
        # Hash needs to depend on the language definition
        if self.lang_def is not None:
            hasher.update(self.lang_def.definition_bytes)
        hasher.update(hasher.digest())
        # Hash needs to depend on session name to avoid the possibility of
        # collisions.  Some options can cause sessions with identical code to
        # produce output that is processed differently.  `complete` is an
        # example (though it is explicitly incorporated into the hash).
        hasher.update('{{session={0}}}'.format(self._name_escaped).encode('utf8'))
        hasher.update(hasher.digest())
        for cc in self.code_chunks:
            if not cc.inline:
                cc.code_start_line_number = self._code_start_line_number
                self._code_start_line_number += len(cc.code_lines)
            # Hash needs to depend on some code chunk details.  `command`
            # determines some wrapper code, while `inline` affects line count
            # and error sync currently, and might also affect code in the
            # future.
            cc_options = '{{command="{0}", inline={1}, complete={2}}}'.format(cc.command,
                                                                              str(cc.inline).lower(),
                                                                              str(cc.options['complete']).lower())
            hasher.update(cc_options.encode('utf8'))
            hasher.update(hasher.digest())
            code_bytes = cc.code.encode('utf8')
            hasher.update(code_bytes)
            code_len += len(code_bytes)
            # Hash needs to depend on code plus how it's divided into chunks.
            # Updating hash based on its current value at the end of each
            # chunk accomplishes this.
            hasher.update(hasher.digest())
        self.hash = '{0}_{1}'.format(hasher.hexdigest(), code_len)
        self.hash_root = self.temp_suffix = hasher.hexdigest()[:16]




class CodeProcessor(object):
    '''
    Process code chunks.  This can involve executing code, extracting code
    from files for inclusion, or a combination of the two.
    '''
    def __init__(self, *, code_chunks, code_options, cross_source_sessions,
                 no_cache, cache_path, cache_key, cache_source_paths):
        self.code_chunks = code_chunks
        self.code_options = code_options
        self.cross_source_sessions = cross_source_sessions
        self.no_cache = no_cache
        self.cache_path = cache_path
        self.cache_key = cache_key
        self.cache_source_paths = cache_source_paths
        if cache_source_paths is None:
            self.cache_source_paths_as_strings = None
        else:
            self.cache_source_paths_as_strings = [p.as_posix() for p in cache_source_paths]

        self.cache_key_path = cache_path / cache_key
        self.cache_index_path = cache_path / cache_key / '{0}_index.zip'.format(cache_key)
        self.cache_lock_path = cache_path / cache_key / '{0}.lock'.format(cache_key)

        self._prep_cache()
        self._generate_keys_load_language_definitions()
        self._index_named_code_chunks()
        self._resolve_code_copying()
        self._create_sessions()


    def _prep_cache(self):
        '''
        Prepare the cache.

        A document's cache is located at `<cache_path>/<cache_key>/`, where
        <cache_key> is derived from a hash of the absolute source path(s).
        Thus, the cache depends on source locations.  To provide some
        cross-platform cache compatibility, source paths always use `~` to
        represent the user's home directory, even under Windows.  This is
        expanded via `pathlib.Path.expanduser()`.

        Each document cache contains per-session cache files that include
        stdout, sterr, expr, rich output, and runtime source errors.  When
        there is rich output, additional files such as images are also
        created.  The file `<cache_key>_index.zip` includes all source path(s)
        and a complete list of all cache files created (including itself).

        The cache is compatible with multiple documents being built
        simultaneously within a single `<cache_path>`, since the cache for
        each build will be located in its own subdirectory.  However, for a
        given document, only one build at a time is possible.  A lock file
        `<cache_key>.lock` is used to enforce this.

        Notice that in cleaning outdated or invalid cache material, there is
        never wholesale directory removal.  Only files created directly by
        Codebraid are deleted.  Users should never manually create files in
        the cache, but if that happens those files should not be deleted
        unless they overwrite existing cache files.
        '''
        self.cache_key_path.mkdir(parents=True, exist_ok=True)
        max_lock_wait = 2
        lock_check_interval = 0.1
        lock_time = 0
        while True:
            try:
                self.cache_lock_path.touch(exist_ok=False)
            except FileExistsError:
                if lock_time > max_lock_wait:
                    raise err.CodebraidError('This document is already being built with the specified cache '
                                             'or another process is cleaning the cache; the cache is locked')
                time.sleep(lock_check_interval)
                lock_time += lock_check_interval
            else:
                break
        def final_cache_cleanup():
            try:
                self.cache_lock_path.unlink()
            except FileNotFoundError:
                pass
            for p in (self.cache_key_path, self.cache_path):
                try:
                    p.rmdir()
                except OSError:
                    pass
        atexit.register(final_cache_cleanup)

        try:
            with zipfile.ZipFile(str(self.cache_index_path)) as zf:
                with zf.open('index.json') as f:
                    if sys.version_info < (3, 6):
                        cache_index = json.loads(f.read().decode('utf8'))
                    else:
                        cache_index = json.load(f)
        except (FileNotFoundError, KeyError, json.decoder.JSONDecodeError):
            cache_index = {}
        else:
            # These checks include handling source hash collisions and
            # corrupted caches
            if (self.no_cache or
                    not isinstance(cache_index, dict) or
                    cache_index.get('codebraid_version') != codebraid_version or
                    cache_index['sources'] != self.cache_source_paths_as_strings or
                    not all((self.cache_key_path / f).is_file() for f in cache_index['files'])):
                if isinstance(cache_index, dict) and 'files' in cache_index:
                    for f in cache_index['files']:
                        try:
                            (self.cache_key_path / f).unlink()
                        except FileNotFoundError:
                            pass
                else:
                    try:
                        self.cache_index_path.unlink()
                    except FileNotFoundError:
                        pass
                cache_index = {}
        if not cache_index:
            cache_index['codebraid_version'] = codebraid_version
            cache_index['sources'] = self.cache_source_paths_as_strings
            cache_index['files'] = []
        self.cache_index = cache_index

        # Cached stdout and stderr, plus any other relevant data.  Each
        # session has a key based on a BLAKE2b hash of its code plus the
        # length in bytes of the code when encoded with UTF8.  (SHA-512 is
        # used as a fallback for Python 3.5.)
        self._cache = {}
        # All session hash roots (<first 16 chars of hex session hash>) that
        # correspond to sessions with new or updated caches.
        self._updated_cache_hash_roots = set()


    def _generate_keys_load_language_definitions(self):
        '''
        Assign code chunk session/source keys.  Load language definitions, and
        mark any code chunks that lack necessary definitions.
        '''
        required_lang_keys = set()
        jupyter_lang_keys = set()
        for cc in self.code_chunks:
            if cc.execute:
                if self.cross_source_sessions:
                    key = (self, cc.options['lang'], cc.options['session'])
                else:
                    key = (self, cc.options['lang'], cc.options['session'], cc.source_name)
                if key not in required_lang_keys and key not in jupyter_lang_keys:
                    if 'jupyter_kernel' in cc.options['first_chunk_options']:
                        jupyter_lang_keys.add(key)
                    else:
                        required_lang_keys.add(key)
            elif self.cross_source_sessions:
                key = (self, cc.options['lang'], cc.options['source'])
            else:
                key = (self, cc.options['lang'], cc.options['source'], cc.source_name)
            cc.key = key

        raw_language_index = pkgutil.get_data('codebraid', 'languages/index.bespon')
        if raw_language_index is None:
            raise err.CodebraidError('Failed to find "codebraid/languages/index.bespon"')
        language_index = bespon.loads(raw_language_index)
        language_definitions = collections.defaultdict(lambda: None)
        required_langs = set(key[1] for key in required_lang_keys)
        for lang in required_langs:
            try:
                lang_def_fname = language_index[lang]
            except KeyError:
                for cc in self.code_chunks:
                    if cc.options['lang'] == lang and cc.execute and cc.key in required_lang_keys:
                        cc.source_errors.append('Language definition for "{0}" does not exist, or is not indexed'.format(lang))
                continue
            lang_def_bytes = pkgutil.get_data('codebraid', 'languages/{0}'.format(lang_def_fname))
            if lang_def_bytes is None:
                for cc in self.code_chunks:
                    if cc.options['lang'] == lang and cc.execute and cc.key in required_lang_keys:
                        cc.source_errors.append('Language definition for "{0}" does not exist'.format(lang))
            lang_def = bespon.loads(lang_def_bytes)
            language_definitions[lang] = Language(lang, lang_def[lang], lang_def_bytes)
        self.language_definitions = language_definitions


    def _index_named_code_chunks(self):
        '''
        Index named code chunks, and mark code chunks with duplicate names.
        '''
        named_code_chunks = {}
        for cc in self.code_chunks:
            cc_name = cc.options.get('name', None)
            if cc_name is not None:
                if cc_name not in named_code_chunks:
                    named_code_chunks[cc_name] = cc
                else:
                    message = 'Code chunk names must be unique; duplicate for code chunk in "{0}" near line "{1}"'
                    message = message.format(named_code_chunks[cc_name].source_name,
                                             named_code_chunks[cc_name].source_start_line_number)
                    cc.source_errors.append(message)
        self.named_code_chunks = named_code_chunks


    def _resolve_code_copying(self):
        '''
        For code chunks with copying, handle the code copying.  The output
        copying for commands like "paste" must be handled separately later,
        after code is executed.
        '''
        named_chunks = self.named_code_chunks
        unresolved_chunks = self.code_chunks
        still_unresolved_chunks = []
        for cc in unresolved_chunks:
            if 'copy' in cc.options:
                cc.copy_chunks = [named_chunks.get(name, None) for name in cc.options['copy']]
                if any(x is None for x in cc.copy_chunks):
                    unknown_names = ', '.join('"{0}"'.format(name) for name, x in zip(cc.options['copy'], cc.copy_chunks) if x is None)
                    message = 'Unknown name(s) for copying: {0}'.format(unknown_names)
                    cc.source_errors.append(message)
                if not cc.source_errors:
                    still_unresolved_chunks.append(cc)
        unresolved_chunks = still_unresolved_chunks
        still_unresolved_chunks = []
        while True:
            for cc in unresolved_chunks:
                if any(x.source_errors for x in cc.copy_chunks):
                    error_names = ', '.join('"{0}"'.format(name) for name, x in zip(cc.options['copy'], cc.copy_chunks) if x.source_errors)
                    message = 'Cannot copy code chunks with source errors: {0}'.format(error_names)
                    cc.source_errors.append(message)
                elif any(x.code_lines is None for x in cc.copy_chunks):
                    still_unresolved_chunks.append(cc)
                else:
                    cc.copy_code()
            if not still_unresolved_chunks:
                break
            if len(still_unresolved_chunks) == len(unresolved_chunks):
                for cc in still_unresolved_chunks:
                    unresolved_names = ', '.join('"{0}"'.format(name) for name, x in zip(cc.options['copy'], cc.copy_chunks) if x.code_lines is None)
                    if cc.options['name'] in cc.options['copy']:
                        message = 'Code chunk cannot copy itself: {0}'.format(unresolved_names)
                    else:
                        message = 'Could not resolve name(s) for copying (circular dependency?): {0}'.format(unresolved_names)
                    cc.source_errors.append(message)
                break
            unresolved_chunks = still_unresolved_chunks
            still_unresolved_chunks = []


    def _resolve_output_copying(self):
        '''
        For code chunks with copying, handle the output copying.  The output
        copying for commands like "paste" must be handled after code is
        executed, while any code copying must be handled before.
        '''
        # There is no need to check for undefined names or circular
        # dependencies because that's already been handled in
        # `_resolve_code_copying()`.  There can still be runtime source
        # errors, though, due to code that isn't properly divided into chunks.
        named_chunks = self.named_code_chunks
        unresolved_chunks = [cc for cc in self.code_chunks
                             if cc.command == 'paste' and not cc.source_errors and not cc.has_output]
        still_unresolved_chunks = []
        while True:
            for cc in unresolved_chunks:
                copy_ccs = [named_chunks.get(name, None) for name in cc.options['copy']]
                if any(x.source_errors for x in copy_ccs):
                    error_names = ', '.join('"{0}"'.format(name) for name, x in zip(cc.options['copy'], copy_ccs) if x.source_errors)
                    message = 'Cannot copy code chunks with source errors: {0}'.format(error_names)
                    cc.source_errors.append(message)
                elif any(not x.has_output for x in copy_ccs):
                    still_unresolved_chunks.append(cc)
                else:
                    cc.copy_output()
            if not still_unresolved_chunks:
                break
            unresolved_chunks = still_unresolved_chunks
            still_unresolved_chunks = []


    def _create_sessions(self):
        sessions = util.KeyDefaultDict(Session)
        for cc in self.code_chunks:
            if cc.execute:
                sessions[cc.key].append(cc)
            elif not cc.inline:
                # Code blocks not in sessions need starting line numbers
                cc.code_start_line_number = 1

        for session in sessions.values():
            session.finalize()

        self._sessions = sessions


    def process(self):
        '''
        Execute code and update cache.
        '''
        for session in self._sessions.values():
            if not session.errors:
                self._load_cache(session)
                if session.hash not in self._cache:
                    if session.jupyter_kernel is None:
                        self._run(session)
                    else:
                        self._run_jupyter(session)
                self._process_session(session)
        self._resolve_output_copying()
        self._update_cache()


    def _load_cache(self, session):
        '''
        Load cached output, if it exists.

        There's no need to check that all cache files are present in the case
        of rich output that results in additional files, because that is done
        during cache prep.
        '''
        if session.hash not in self._cache:
            session_cache_path = self.cache_key_path / '{0}.zip'.format(session.hash_root)
            try:
                with zipfile.ZipFile(str(session_cache_path)) as zf:
                    with zf.open('cache.json') as f:
                        if sys.version_info < (3, 6):
                            saved_cache = json.loads(f.read().decode('utf8'))
                        else:
                            saved_cache = json.load(f)
            except (FileNotFoundError, KeyError, json.decoder.JSONDecodeError):
                pass
            else:
                if saved_cache['codebraid_version'] == codebraid_version:
                    try:
                        self._cache[session.hash] = saved_cache['cache'][session.hash]
                    except KeyError:
                        pass


    def _subproc_default(self, *, session, stdin, stage, stage_num, stage_tot_num, cmd, encoding, stderr_is_stdout=False):
        '''
        Wrapper around `subprocess.run()` that provides a single location for
        customizing handling.
        '''
        # Note that `shlex.split()` only works correctly on posix paths.  If
        # it is ever necessary to switch to non-posix paths under Windows, the
        # backslashes will require extra escaping.
        args = shlex.split(cmd)
        failed_proc_stderr = 'COMMAND FAILED (missing program or file):\n  {0}'.format(cmd).encode('utf8')
        if stdin is None:
            stdin_bytes_or_none = None
        else:
            stdin_bytes_or_none = stdin.encode('utf8')
        if stderr_is_stdout:
            try:
                proc = subprocess.run(args, input=stdin_bytes_or_none, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            except FileNotFoundError:
                proc = FailedProcess(args, stdout=failed_proc_stderr)
        else:
            try:
                proc = subprocess.run(args, input=stdin_bytes_or_none, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except FileNotFoundError:
                proc = FailedProcess(args, stdout=b'', stderr=failed_proc_stderr)
        return proc


    def _subproc_live_output(self, *, session, stdin, stage, stage_num, stage_tot_num, cmd, encoding, stderr_is_stdout=False):
        '''
        Drop-in replacement for `_subproc_default()` for when stdout and
        stderr need to be both recorded and passed through (for example, for a
        progress bar).
        '''
        if stdin is not None:
            raise err.CodebraidError('"live_output" is currently not compatible with running a process that requires STDIN')
        args = shlex.split(cmd)
        failed_proc_stderr = 'COMMAND FAILED (missing program or file):\n  {0}'.format(cmd).encode('utf8')
        # Queue of bytes from stdout and stderr, plus string delims
        print_queue = queue.Queue()
        hash_bytes = session.hash[:64].encode('utf8')
        delim_border_n_chars = 60
        if stage == 'run':
            delim_text = 'run: {lang}, session {session}\n'
            delim_text = delim_text.format(lang=session.lang,
                                           session='"{0}"'.format(session.name) if session.name is not None else '<default>')
            chunk_delim_text = '''\
                run: {lang}, session {session}, chunk {{chunk}}/{total_chunks}
                "{{source}}", line {{line}}
                '''
            chunk_delim_text = textwrap.dedent(chunk_delim_text)
            chunk_delim_text = chunk_delim_text.format(lang=session.lang,
                                                       session='"{0}"'.format(session.name) if session.name is not None else '<default>',
                                                       total_chunks=len(session.code_chunks))
            chunk_start_delim = '\n' + '='*delim_border_n_chars + '\n' + chunk_delim_text + '-'*delim_border_n_chars + '\n'
        else:
            if stage_num == stage_tot_num:
                delim_text = '{stage}: {lang}, session {session}\n'
            else:
                delim_text = '{stage} ({num}/{tot}): {lang}, session {session}\n'
            delim_text = delim_text.format(stage=stage, num=stage_num, tot=stage_tot_num,
                                           lang=session.lang,
                                           session='"{0}"'.format(session.name) if session.name is not None else '<default>')
        stage_start_delim = '\n' + '#'*delim_border_n_chars + '\n' + delim_text + '#'*delim_border_n_chars + '\n'
        print(stage_start_delim, end='', file=sys.stderr, flush=True)

        def stream_reader(stream, buffer, is_stdout, is_stderr, stdout_lock=None, stderr_lock=None):
            '''
            Read bytes from a stream (stdout or stderr) and pass them on to a
            buffer (list) and print queue (queue.Queue).  Bytes are accumulated in
            a local buffer, and only passed on a line at a time.  This allows
            Codebraid delims to be filtered out.
            '''
            local_buffer = []
            while True:
                output = stream.read(1)
                if not output:
                    if local_buffer:
                        line = b''.join(local_buffer)
                        buffer.append(line)
                        print_queue.put(line)
                    break
                if output == b'\n':
                    if not local_buffer:
                        # Could be leading `\n` from Codebraid delim
                        local_buffer.append(output)
                        continue
                    local_buffer.append(output)
                    line = b''.join(local_buffer)
                    buffer.append(line)
                    local_buffer = []
                    # Codebraid delim starts with `\n`, but that will be used
                    # by whatever was printed just before it when a trailing
                    # newline has been omitted.
                    if (stage == 'run' and
                            (line.startswith(b'CodebraidStd') or line.startswith(b'\nCodebraidStd')) and
                            hash_bytes in line):
                        # When stdout_is_stderr == False, locks are used to
                        # ensure that stdout and stderr stay in sync.  Lock
                        # usage is based on the stdout delim always being
                        # printed immediately before the stderr delim.
                        if not is_stderr:
                            stdout_lock.acquire()
                            stderr_lock.release()
                        elif not is_stdout:
                            stderr_lock.acquire()
                            stdout_lock.release()
                        if is_stderr:
                            chunk_number = int(line.split(b'chunk=', 1)[1].split(b',', 1)[0])
                            cc = session.code_chunks[chunk_number]
                            print_queue.put(chunk_start_delim.format(source=cc.source_name,
                                                                     line=cc.source_start_line_number,
                                                                     chunk=cc.session_index+1))
                    else:
                        print_queue.put(line)
                    continue
                if output == b'\r':
                    local_buffer.append(output)
                    line = b''.join(local_buffer)
                    buffer.append(line)
                    print_queue.put(line)
                    local_buffer = []
                    continue
                local_buffer.append(output)

        if stderr_is_stdout:
            std_buffer = []
            try:
                popen = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                std_thread = threading.Thread(target=stream_reader,
                                              args=(popen.stdout, std_buffer, True, True))
                std_thread.daemon = True
                std_thread.start()
                while popen.poll() is None:
                    try:
                        line = print_queue.get(block=True, timeout=0.1)
                    except queue.Empty:
                        continue
                    if isinstance(line, bytes):
                        line = line.decode(encoding=encoding, errors='backslashreplace')
                    print(line, end='', file=sys.stderr, flush=True)
                std_thread.join()
                while True:
                    try:
                        line = print_queue.get(block=False)
                    except queue.Empty:
                        break
                    if isinstance(line, bytes):
                        line = line.decode(encoding=encoding, errors='backslashreplace')
                    print(line, end='', file=sys.stderr, flush=True)
                print('\n', end='', file=sys.stderr, flush=True)
                proc = subprocess.CompletedProcess(popen.args, popen.returncode, b''.join(std_buffer), b'')
            except FileNotFoundError:
                proc = FailedProcess(args, stdout=b'', stderr=failed_proc_stderr)
        else:
            stdout_lock = threading.Lock()
            stderr_lock = threading.Lock()
            stdout_buffer = []
            stderr_buffer = []
            try:
                popen = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                stdout_thread = threading.Thread(target=stream_reader,
                                                 args=(popen.stdout, stdout_buffer, True, False, stdout_lock, stderr_lock))
                stdout_thread.daemon = True
                stderr_thread = threading.Thread(target=stream_reader,
                                                 args=(popen.stderr, stderr_buffer, False, True, stdout_lock, stderr_lock))
                stderr_thread.daemon = True
                stdout_lock.acquire()
                stdout_thread.start()
                stderr_thread.start()
                while popen.poll() is None:
                    try:
                        line = print_queue.get(block=True, timeout=0.1)
                    except queue.Empty:
                        continue
                    if isinstance(line, bytes):
                        line = line.decode(encoding=encoding, errors='backslashreplace')
                    print(line, end='', file=sys.stderr, flush=True)
                stdout_thread.join()
                stderr_thread.join()
                while True:
                    try:
                        line = print_queue.get(block=False)
                    except queue.Empty:
                        break
                    if isinstance(line, bytes):
                        line = line.decode(encoding=encoding, errors='backslashreplace')
                    print(line, end='', file=sys.stderr, flush=True)
                print('\n', end='', file=sys.stderr, flush=True)
                proc = subprocess.CompletedProcess(popen.args, popen.returncode, b''.join(stdout_buffer), b''.join(stderr_buffer))
            except FileNotFoundError:
                proc = FailedProcess(args, stdout=b'', stderr=failed_proc_stderr)

        return proc


    def _run(self, session):
        stdstream_delim_start = 'CodebraidStd'
        stdstream_delim = r'{0}(hash="{1}", chunk={{chunk}}, output_chunk={{output_chunk}},)'.format(stdstream_delim_start, session.hash[:64])
        stdstream_delim_escaped = stdstream_delim.replace('"', '\\"')
        stdstream_delim_start_hash = stdstream_delim.split(',', 1)[0]
        expression_delim_start = 'CodebraidExpr'
        expression_delim = r'{0}(hash="{1}", chunk={{chunk}}, output_chunk={{output_chunk}},)'.format(expression_delim_start, session.hash[64:])
        expression_delim_escaped = expression_delim.replace('"', '\\"')
        expression_delim_start_hash = expression_delim.split(',', 1)[0]

        if session.repl:
            stdin_list = []
            expected_stdstream_delims = []
            run_code_to_user_code_dict = {}
            line_number = 1
            for cc in session.code_chunks:
                delim = stdstream_delim.format(chunk=cc.session_index, output_chunk=cc.session_output_index)
                stdin_list.append(delim)
                stdin_list.append('\n')
                expected_stdstream_delims.append(cc.session_output_index)
                stdin_list.append(cc.code)
                stdin_list.append('\n')
                for _ in range(len(cc.code_lines)):
                    run_code_to_user_code_dict[line_number] = (cc, line_number)
                    line_number += 1
            stdin = ''.join(stdin_list)
        else:
            stdin = None
            run_code_list = []
            run_code_line_number = 1
            user_code_line_number = 1
            # Map line numbers of code that is run to code chunks and to user code
            # line numbers.  Including code chunks helps with things like syntax
            # errors that prevent code from starting to run. In that case, the
            # code chunks before the one that produced an error won't have
            # anything in stderr that belongs to them.
            run_code_to_user_code_dict = {}
            source_template_before, source_template_after = session.lang_def.source_template.split('{code}')
            chunk_wrapper_before, chunk_wrapper_after = session.lang_def.chunk_wrapper.split('{code}')
            chunk_wrapper_before_n_lines = chunk_wrapper_before.count('\n')
            chunk_wrapper_after_n_lines = chunk_wrapper_after.count('\n')
            if session.lang_def.inline_expression_formatter is not None:
                inline_expression_formatter_n_lines = session.lang_def.inline_expression_formatter.count('\n')
                inline_expression_formatter_n_leading_lines = session.lang_def.inline_expression_formatter.split('{code}')[0].count('\n')

            if not session.code_chunks[0].options['outside_main']:
                run_code_list.append(source_template_before)
                run_code_line_number += source_template_before.count('\n')
            last_cc = None
            expected_stdstream_delims = []  # Track expected chunk numbers
            for cc in session.code_chunks:
                delim = stdstream_delim_escaped.format(chunk=cc.session_index, output_chunk=cc.session_output_index)
                if last_cc is None:
                    if not cc.options['outside_main']:
                        run_code_list.append(chunk_wrapper_before.format(stdout_delim=delim, stderr_delim=delim))
                        run_code_line_number += chunk_wrapper_before_n_lines
                        expected_stdstream_delims.append(cc.session_output_index)
                elif last_cc.options['complete']:
                    run_code_list.append(chunk_wrapper_after)
                    run_code_line_number += chunk_wrapper_after_n_lines
                    run_code_list.append(chunk_wrapper_before.format(stdout_delim=delim, stderr_delim=delim))
                    run_code_line_number += chunk_wrapper_before_n_lines
                    expected_stdstream_delims.append(cc.session_output_index)
                elif last_cc.options['outside_main'] and not cc.options['outside_main']:
                    run_code_list.append(chunk_wrapper_before.format(stdout_delim=delim, stderr_delim=delim))
                    run_code_line_number += chunk_wrapper_before_n_lines
                    expected_stdstream_delims.append(cc.session_output_index)
                if cc.inline:
                    # Only block code contributes toward line numbers.  No need to
                    # check expr compatibility with `complete`, etc.; that's
                    # handled in creating sessions.
                    if cc.is_expr:
                        expr_delim = expression_delim_escaped.format(chunk=cc.session_index, output_chunk=cc.session_output_index)
                        expr_code = session.lang_def.inline_expression_formatter.format(stdout_delim=expr_delim,
                                                                                        stderr_delim=expr_delim,
                                                                                        temp_suffix=session.temp_suffix,
                                                                                        code=cc.code)
                        run_code_list.append(expr_code)
                        run_code_to_user_code_dict[run_code_line_number+inline_expression_formatter_n_leading_lines] = (cc, 1)
                        run_code_line_number += inline_expression_formatter_n_lines
                    else:
                        run_code_list.append(cc.code)
                        run_code_list.append('\n')
                        run_code_to_user_code_dict[run_code_line_number] = (cc, 1)
                        run_code_line_number += 1
                else:
                    run_code_list.append(cc.code)
                    run_code_list.append('\n')
                    for _ in range(len(cc.code_lines)):
                        run_code_to_user_code_dict[run_code_line_number] = (cc, user_code_line_number)
                        user_code_line_number += 1
                        run_code_line_number += 1
                last_cc = cc
            if session.code_chunks[-1].options['complete']:
                run_code_list.append(chunk_wrapper_after)
            if not session.code_chunks[-1].options['outside_main']:
                run_code_list.append(source_template_after)

        error = False
        with tempfile.TemporaryDirectory() as tempdir:
            # tempdir is absolute pathname as str, which simplifies things
            source_dir_path = pathlib.Path(tempdir)
            source_name = 'source_{0}'.format(session.hash_root)
            source_path = source_dir_path / '{0}.{1}'.format(source_name, session.lang_def.extension)
            if session.repl:
                source_path.write_text(session.lang_def.repl_template)
            else:
                source_path.write_text(''.join(run_code_list), encoding='utf8')

            executable = session.code_chunks[0].options['first_chunk_options'].get('executable', session.lang_def.executable)
            # All paths use `.as_posix()` for `shlex.split()` compatibility
            template_dict = {
                'executable': executable,
                'extension': session.lang_def.extension,
                'source': source_path.as_posix(),
                'source_dir': source_dir_path.as_posix(),
                'source_without_extension': (source_dir_path / source_name).as_posix(),
                'delim_start': 'Codebraid',
                'hash': session.hash[:64],
            }

            live_output = session.code_chunks[0].options['first_chunk_options'].get('live_output', False)
            if live_output:
                subproc = self._subproc_live_output
            else:
                subproc = self._subproc_default

            for n, cmd_template in enumerate(session.lang_def.pre_run_commands):
                if error:
                    break
                encoding = session.lang_def.pre_run_encoding or locale.getpreferredencoding(False)
                pre_proc = subproc(session=session,
                                   stage='pre-run', stage_num=n+1, stage_tot_num=len(session.lang_def.pre_run_commands),
                                   cmd=cmd_template.format(**template_dict),
                                   encoding=encoding,
                                   stderr_is_stdout=True)
                if pre_proc.returncode != 0:
                    error = True
                    session.pre_run_errors = True
                    stdout_str = io.TextIOWrapper(io.BytesIO(pre_proc.stdout), encoding=encoding, errors='backslashreplace').read()
                    session.pre_run_error_lines = util.splitlines_lf(stdout_str)

            for n, cmd_template in enumerate(session.lang_def.compile_commands):
                if error:
                    break
                encoding = session.lang_def.compile_encoding or locale.getpreferredencoding(False)
                comp_proc = subproc(session=session,
                                    stage='compile', stage_num=n+1, stage_tot_num=len(session.lang_def.compile_commands),
                                    cmd=cmd_template.format(**template_dict),
                                    encoding=encoding,
                                    stderr_is_stdout=True)
                if comp_proc.returncode != 0:
                    error = True
                    session.compile_errors = True
                    stdout_lines = []
                    stdout_str = io.TextIOWrapper(io.BytesIO(comp_proc.stdout), encoding=encoding, errors='backslashreplace').read()
                    stderr_lines = util.splitlines_lf(stdout_str)

            if not error:
                cmd_template = session.lang_def.run_command
                encoding = session.lang_def.run_encoding or locale.getpreferredencoding(False)
                run_proc = subproc(session=session, stdin=stdin,
                                   stage='run', stage_num=1, stage_tot_num=1,
                                   cmd=cmd_template.format(**template_dict),
                                   encoding=encoding)
                if run_proc.returncode != 0:
                    error = True
                    session.run_errors = True
                try:
                    stdout_str = io.TextIOWrapper(io.BytesIO(run_proc.stdout), encoding=encoding).read()
                    stderr_str = io.TextIOWrapper(io.BytesIO(run_proc.stderr), encoding=encoding).read()
                except UnicodeDecodeError:
                    session.decode_error = True
                    stdout_str = io.TextIOWrapper(io.BytesIO(run_proc.stdout), encoding=encoding, errors='backslashreplace').read()
                    stderr_str = io.TextIOWrapper(io.BytesIO(run_proc.stderr), encoding=encoding, errors='backslashreplace').read()
                stdout_lines = util.splitlines_lf(stdout_str)
                stderr_lines = util.splitlines_lf(stderr_str)

            for n, cmd_template in enumerate(session.lang_def.post_run_commands):
                if error:
                    break
                encoding = session.lang_def.post_run_encoding or locale.getpreferredencoding(False)
                post_proc = subproc(session=session,
                                    stage='post-run', stage_num=n+1, stage_tot_num=len(session.lang_def.post_run_commands),
                                    cmd=cmd_template.format(**template_dict),
                                    encoding=encoding,
                                    stderr_is_stdout=True)
                if post_proc.returncode != 0:
                    error = True
                    session.post_run_errors = True
                    stdout_str = io.TextIOWrapper(io.BytesIO(post_proc.stdout), encoding=encoding, errors='backslashreplace').read()
                    session.post_run_error_lines = util.splitlines_lf(stdout_str)

        session.error = error

        if session.pre_run_errors:
            chunk_stdout_dict = {}
            chunk_stderr_dict = {0: ['PRE-RUN ERROR:', *session.pre_run_error_lines]}
            chunk_expr_dict = {}
            chunk_rich_output_dict = {}
            files_list = []
            chunk_runtime_source_error_dict = {}
        elif session.post_run_errors:
            chunk_stdout_dict = {}
            chunk_stderr_dict = {0: ['POST-RUN ERROR:', *session.post_run_error_lines]}
            chunk_expr_dict = {}
            chunk_rich_output_dict = {}
            files_list = []
            chunk_runtime_source_error_dict = {}
        else:
            # Ensure that there's at least one delimiter to serve as a
            # sentinel, even if the code never ran due to something like a
            # syntax error or compilation error
            sentinel_delim = stdstream_delim.format(chunk=-1,output_chunk=-1)
            stdout_lines.append('')
            stdout_lines.append(sentinel_delim)
            stderr_lines.append('')
            stderr_lines.append(sentinel_delim)
            expected_stdstream_delims.append(-1)
            chunk_stdout_dict = {}
            chunk_stderr_dict = {}
            chunk_expr_dict = {}
            chunk_rich_output_dict = {}
            files_list = []
            chunk_runtime_source_error_dict = {}
            # More source patterns may be needed in future to cover the
            # possibility of languages that make paths lowercase on
            # case-insensitive filesystems
            source_pattern_posix = source_path.as_posix()
            source_pattern_win = str(pathlib.PureWindowsPath(source_path))
            source_pattern_final = 'source.{0}'.format(session.lang_def.extension)
            source_pattern_final_inline = '<string>'
            error_patterns = session.lang_def.error_patterns
            warning_patterns = session.lang_def.warning_patterns
            line_number_pattern_re = session.lang_def.line_number_pattern_re
            line_number_regex_re = session.lang_def.line_number_regex_re

            session_output_index = -1
            chunk_start_index = 0
            chunk_end_index = 0
            for index, line in enumerate(stdout_lines):
                if line.startswith(stdstream_delim_start) and line.startswith(stdstream_delim_start_hash):
                    next_session_output_index = int(line.split('output_chunk=', 1)[1].split(',', 1)[0])
                    if index > 0:
                        chunk_end_index = index - 1
                        if stdout_lines[chunk_end_index]:
                            chunk_end_index = index
                    if chunk_end_index > chunk_start_index:
                        if session_output_index >= 0 and session.code_chunks[session_output_index].is_expr:
                            combined_lines = stdout_lines[chunk_start_index:chunk_end_index]
                            for combined_index, combined_line in enumerate(combined_lines):
                                if combined_line.startswith(expression_delim_start) and combined_line.startswith(expression_delim_start_hash):
                                    if combined_index + 1 < len(combined_lines):
                                        chunk_expr_dict[session_output_index] = combined_lines[combined_index+1:]
                                    if not combined_lines[combined_index-1]:
                                        combined_index -= 1
                                    if combined_index > 0:
                                        chunk_stdout_dict[session_output_index] = combined_lines[:combined_index]
                                    break
                        else:
                            chunk_stdout_dict[session_output_index] = stdout_lines[chunk_start_index:chunk_end_index]
                    chunk_start_index = index + 1
                    session_output_index = next_session_output_index
            if -1 in chunk_stdout_dict:
                # `session_output_index` covers the possibility that this is
                # output from the template or `outside_main` at the beginning,
                # and also the possibility that there were no delimiters.  If
                # the -1 is due to a delimiter-related error, that will be
                # detected and handled in stderr processing.
                cc_unclaimed_stdout_index = session.code_chunks[0].session_output_index
                if cc_unclaimed_stdout_index in chunk_stdout_dict:
                    chunk_stdout_dict[cc_unclaimed_stdout_index] = chunk_stdout_dict[-1] + chunk_stdout_dict[cc_unclaimed_stdout_index]
                else:
                    chunk_stdout_dict[cc_unclaimed_stdout_index] = chunk_stdout_dict[-1]
                del chunk_stdout_dict[-1]

            session_output_index = -1
            chunk_start_index = 0
            chunk_end_index = 0
            expected_stdstream_delims_iter = iter(expected_stdstream_delims)
            for index, line in enumerate(stderr_lines):
                if line.startswith(stdstream_delim_start) and line.startswith(stdstream_delim_start_hash):
                    next_session_output_index = int(line.split('output_chunk=', 1)[1].split(',', 1)[0])
                    if next_session_output_index == session_output_index and next_session_output_index >= 0:
                        # A code chunk that is not actually complete was run
                        # with the default `complete=true`, and this resulted
                        # in a delimiter being printed multiple times.  Since
                        # this error can only be detected at runtime, it is
                        # stored specially rather than being reported as a
                        # normal source error.  This guarantees that the code
                        # won't run again until this is fixed.
                        error_cc = session.code_chunks[session_output_index]
                        message_lines = ['This ran with "complete" value "true" but is not a complete unit of code.']
                        session.errors = True
                        session.run_errors = True
                        chunk_stdout_dict = {}
                        chunk_stderr_dict = {}
                        chunk_expr_dict = {}
                        chunk_runtime_source_error_dict = {error_cc.session_output_index: message_lines}
                        break
                    if not session.error and next_session_output_index != next(expected_stdstream_delims_iter, None):
                        # A code chunk that is not actually complete was run
                        # with the default `complete=true`, or a code chunk
                        # with `outside_main` ended in an incomplete state.
                        # This prevented a delimiter from being printed.
                        if next_session_output_index > 0:
                            error_cc = session.code_chunks[session_output_index]
                        else:
                            error_cc = session.code_chunks[session.code_chunks[0].session_output_index]
                        if error_cc.options['complete']:
                            message_lines = ['This ran with "complete" value "true" but is not a complete unit of code.']
                        elif error_cc.options['outside_main']:
                            message_lines = ['This marked the end of "outside_main" but is not a complete unit of code.']
                        else:
                            # Fallback; previous cases should cover everything
                            message_lines = ['This is not a complete unit of code.']
                        message_lines.append('It interfered with the following code chunk.')
                        session.errors = True
                        session.run_errors = True
                        chunk_stdout_dict = {}
                        chunk_stderr_dict = {}
                        chunk_expr_dict = {}
                        chunk_runtime_source_error_dict = {error_cc.session_output_index: message_lines}
                        break
                    if index > 0:
                        chunk_end_index = index - 1
                        if stderr_lines[chunk_end_index]:
                            chunk_end_index = index
                    if chunk_end_index > chunk_start_index:
                        cc_stderr_lines = stderr_lines[chunk_start_index:chunk_end_index]
                        if session_output_index >= 0 and session.code_chunks[session_output_index].is_expr:
                            for combined_index, combined_line in enumerate(cc_stderr_lines):
                                if combined_line.startswith(expression_delim_start) and combined_line.startswith(expression_delim_start_hash):
                                    if cc_stderr_lines[combined_index-1]:
                                        del cc_stderr_lines[combined_index]
                                    else:
                                        del cc_stderr_lines[combined_index-1:combined_index+1]
                                    break
                            if not cc_stderr_lines:
                                chunk_start_index = index + 1
                                session_output_index = next_session_output_index
                                continue
                        # Sync error and warning line numbers with those in
                        # user code, and replace source name.  This is
                        # somewhat complex because in cases like a syntax
                        # error, the code chunk that the iteration is
                        # currently on isn't the real code chunk (`actual_cc`)
                        # that the error belongs to.
                        actual_cc = None
                        if session_output_index < 0:
                            if session.compile_errors:
                                user_cc = session.code_chunks[0]
                            else:
                                user_cc = session.code_chunks[session.code_chunks[0].session_output_index]
                        else:
                            user_cc = session.code_chunks[session_output_index]
                        if not session.repl:
                            for cc_index, cc_line in enumerate(cc_stderr_lines):
                                if source_pattern_posix in cc_line or source_pattern_win in cc_line:
                                    match = line_number_pattern_re.search(cc_line)
                                    if match:
                                        for mg in match.groups():
                                            if mg is not None:
                                                run_number = int(mg)
                                                break
                                        try:
                                            user_cc, user_number = run_code_to_user_code_dict[run_number]
                                        except KeyError:
                                            lower_run_number = run_number - 1
                                            while lower_run_number > 0 and lower_run_number not in run_code_to_user_code_dict:
                                                lower_run_number -= 1
                                            if lower_run_number == 0:
                                                user_number = 1
                                                user_cc = session.code_chunks[0]
                                            else:
                                                user_cc, user_number = run_code_to_user_code_dict[lower_run_number]
                                        cc_line = cc_line.replace(match.group(0), match.group(0).replace(str(run_number), str(user_number)))
                                        if actual_cc is None:
                                            actual_cc = user_cc
                                    if user_cc.inline:
                                        cc_line = cc_line.replace(source_pattern_posix, source_pattern_final_inline)
                                        cc_line = cc_line.replace(source_pattern_win, source_pattern_final_inline)
                                    else:
                                        cc_line = cc_line.replace(source_pattern_posix, source_pattern_final)
                                        cc_line = cc_line.replace(source_pattern_win, source_pattern_final)
                                    cc_stderr_lines[cc_index] = cc_line
                        if actual_cc is None:
                            actual_cc = user_cc
                        # Replace other line numbers that are identified by
                        # regex instead of by being in the same line as the
                        # source name.  This works for syncing messages from a
                        # single chunk, but will need to be revised if it is
                        # ever necessary to sync messages across multiple
                        # chunks.
                        if line_number_regex_re is not None:
                            def replace_match(match):
                                for mg in match.groups():
                                    if mg is not None:
                                        run_number = int(mg)
                                        before, after = match.group(0).split(mg, 1)
                                        if before.strip(' \t'):
                                            template = '{0}'
                                        else:
                                            template = '{{:{0}d}}'.format(len(mg))
                                        break
                                try:
                                    _, user_number = run_code_to_user_code_dict[run_number]
                                except KeyError:
                                    lower_run_number = run_number - 1
                                    while lower_run_number > 0 and lower_run_number not in run_code_to_user_code_dict:
                                        lower_run_number -= 1
                                    if lower_run_number == 0:
                                        user_number = 1
                                    else:
                                        _, user_number = run_code_to_user_code_dict[lower_run_number]
                                return match.group(0).replace(str(run_number), template.format(user_number))
                            cc_stderr_lines = util.splitlines_lf(line_number_regex_re.sub(replace_match, '\n'.join(cc_stderr_lines)))
                        # Update session error and warning status
                        if not session.compile_errors:
                            for cc_line in cc_stderr_lines:
                                if any(x in cc_line for x in error_patterns):
                                    session.run_errors = True
                                    session.run_error_chunks.append(actual_cc)
                                    break
                                elif any(x in cc_line for x in warning_patterns):
                                    session.run_warnings = True
                                    if not (session.run_warning_chunks and session.run_warning_chunks[-1] is actual_cc):
                                        session.run_warning_chunks.append(actual_cc)
                        if actual_cc.session_index in chunk_stderr_dict:
                            chunk_stderr_dict[actual_cc.session_index].extend(cc_stderr_lines)
                        else:
                            chunk_stderr_dict[actual_cc.session_index] = cc_stderr_lines
                    chunk_start_index = index + 1
                    session_output_index = next_session_output_index
        if session.repl:
            cache = {
                'stdout_lines': {},
                'stderr_lines': chunk_stderr_dict,
                'repl_lines': chunk_stdout_dict,
                'expr_lines': chunk_expr_dict,
                'rich_output': chunk_rich_output_dict,
                'files': files_list,
                'runtime_source_error_lines': chunk_runtime_source_error_dict,
            }
        else:
            cache = {
                'stdout_lines': chunk_stdout_dict,
                'stderr_lines': chunk_stderr_dict,
                'repl_lines': {},
                'expr_lines': chunk_expr_dict,
                'rich_output': chunk_rich_output_dict,
                'files': files_list,
                'runtime_source_error_lines': chunk_runtime_source_error_dict,
            }
        self._cache[session.hash] = cache
        self._updated_cache_hash_roots.add(session.hash_root)


    def _run_jupyter(self, session):
        chunk_stdout_dict = collections.defaultdict(list)
        chunk_stderr_dict = collections.defaultdict(list)
        chunk_repl_dict = collections.defaultdict(list)
        chunk_expr_dict = collections.defaultdict(list)
        chunk_rich_output_dict = collections.defaultdict(list)
        files_list = []
        chunk_runtime_source_error_dict = collections.defaultdict(list)
        cache = {
            'stdout_lines': chunk_stdout_dict,
            'stderr_lines': chunk_stderr_dict,
            'repl_lines': chunk_repl_dict,
            'expr_lines': chunk_expr_dict,
            'rich_output': chunk_rich_output_dict,
            'files': files_list,
            'runtime_source_error_lines': chunk_runtime_source_error_dict,
        }
        self._updated_cache_hash_roots.add(session.hash_root)
        self._cache[session.hash] = cache

        import queue
        import base64

        # https://jupyter-client.readthedocs.io/en/stable/api/client.html
        # https://jupyter-client.readthedocs.io/en/stable/messaging.html#messages-on-the-iopub-pub-sub-channel
        kernel_name = session.jupyter_kernel
        try:
            import jupyter_client
        except ImportError:
            chunk_runtime_source_error_dict[0].append('Cannot import "jupyter_client" module'.format(kernel_name))
            return
        jupyter_manager = jupyter_client.KernelManager(kernel_name=kernel_name)
        try:
            jupyter_manager.start_kernel()
        except jupyter_client.kernelspec.NoSuchKernel:
            chunk_runtime_source_error_dict[0].append('No such Jupyter kernel "{0}"'.format(kernel_name))
            return
        except Exception as e:
            chunk_runtime_source_error_dict[0].append('Failed to start Jupyter kernel "{0}":\n"{1}"'.format(kernel_name, e))
            return
        jupyter_client = jupyter_manager.client()
        def shutdown_kernel():
            if jupyter_manager.has_kernel:
                jupyter_client.stop_channels()
                jupyter_manager.shutdown_kernel(now=True)
        atexit.register(shutdown_kernel)
        jupyter_client.start_channels()
        try:
            jupyter_client.wait_for_ready()
        except RuntimeError as e:
            jupyter_client.stop_channels()
            jupyter_manager.shutdown_kernel()
            chunk_runtime_source_error_dict[0].append('Jupyter kernel "{0}" timed out during startup:\n"{1}"'.format(kernel_name, e))
            return

        try:
            errors = False
            incomplete_cc_stack = []
            for cc in session.code_chunks:
                if errors:
                    break
                if cc.session_output_index != cc.session_index:
                    # If incomplete code, accumulate until complete
                    incomplete_cc_stack.append(cc)
                    continue
                if not incomplete_cc_stack:
                    cc_jupyter_id = jupyter_client.execute(cc.code)
                else:
                    incomplete_cc_stack.append(cc)
                    cc_jupyter_id = jupyter_client.execute('\n'.join(icc.code for icc in incomplete_cc_stack))
                    incomplete_cc_stack = []
                external_file_mime_types = set(['image/png', 'image/jpeg', 'image/svg+xml', 'application/pdf'])
                while True:
                    try:
                        msg = jupyter_client.iopub_channel.get_msg(timeout=session.jupyter_timeout or 60)
                    except queue.Empty:
                        chunk_runtime_source_error_dict[cc.session_output_index].append('Jupyter kernel "{0}" timed out during execution"'.format(kernel_name))
                        errors = True
                        break
                    if msg['parent_header'].get('msg_id') != cc_jupyter_id:
                        continue
                    msg_type = msg['msg_type']
                    msg_content = msg['content']
                    if msg_type in ('execute_result', 'display_data'):
                        # Rich output
                        rich_output_files = {}
                        rich_output = {'files': rich_output_files, 'data': msg_content['data']}
                        for mime_type, data in msg_content['data'].items():
                            if mime_type in external_file_mime_types:
                                file_extension = mime_type.split('/', 1)[1].split('+', 1)[0]
                                if file_extension == 'jpeg':
                                    file_extension = 'jpg'
                                if 'name' not in cc.options:
                                    file_name = '{0}-{1}-{2:03d}-{3:02d}.{4}'.format(kernel_name,
                                                                                     session.name or '',
                                                                                     cc.session_output_index+1,
                                                                                     len(chunk_rich_output_dict[cc.session_output_index])+1,
                                                                                     file_extension)
                                else:
                                    file_name = '{0}-{1:02d}.{2}'.format(cc.options['name'],
                                                                         len(chunk_rich_output_dict[cc.session_output_index])+1,
                                                                         file_extension)
                                files_list.append(file_name)
                                ro_path = self.cache_key_path / file_name
                                ro_path.write_bytes(base64.b64decode(data))
                                rich_output_files[mime_type] = ro_path.as_posix()
                        chunk_rich_output_dict[cc.session_output_index].append(rich_output)
                        continue
                    if msg_type == 'status' and msg_content['execution_state'] == 'idle':
                        break
                    if msg_type == 'error':
                        chunk_stderr_dict[cc.session_output_index].extend(util.splitlines_lf(re.sub('\x1b.*?m', '', '\n'.join(msg_content['traceback']))))
                        continue
                    if msg_type == 'stream':
                        if msg_content['name'] == 'stdout':
                            chunk_stdout_dict[cc.session_output_index].extend(util.splitlines_lf(msg_content['text']))
                        elif msg_content['name'] == 'stderr':
                            chunk_stderr_dict[cc.session_output_index].extend(util.splitlines_lf(msg_content['text']))
                        continue
        finally:
            jupyter_client.stop_channels()
            jupyter_manager.shutdown_kernel()


    def _process_session(self, session):
        cache = self._cache[session.hash]
        # `int()` handles keys from json cache
        for index, lines in cache['stdout_lines'].items():
            session.code_chunks[int(index)].stdout_lines = lines
        for index, lines in cache['stderr_lines'].items():
            session.code_chunks[int(index)].stderr_lines = lines
        for index, lines in cache['repl_lines'].items():
            session.code_chunks[int(index)].repl_lines = lines
        for index, lines in cache['expr_lines'].items():
            session.code_chunks[int(index)].expr_lines = lines
        if 'rich_output' in cache:
            for index, rich_output in cache['rich_output'].items():
                session.code_chunks[int(index)].rich_output = rich_output
        for index, lines in cache['runtime_source_error_lines'].items():
            cc = session.code_chunks[int(index)]
            cc.source_errors.extend(lines)
            cc.runtime_source_error = True


    def _update_cache(self):
        if self.no_cache:
            created_cache_files = set()
            for hash, value in self._cache.items():
                created_cache_files.update(value['files'])
            if created_cache_files:
                cache_key_path = self.cache_key_path
                def cleanup_created_cache_files():
                    for f in created_cache_files:
                        try:
                            (cache_key_path / f).unlink()
                        except FileNotFoundError:
                            pass
                atexit.register(cleanup_created_cache_files)
        else:
            used_cache_files = set()
            used_cache_files.add('{0}_index.zip'.format(self.cache_key))
            for hash, value in self._cache.items():
                used_cache_files.add('{0}.zip'.format(hash[:16]))
                used_cache_files.update(value['files'])
            for f in set(self.cache_index['files']) - used_cache_files:
                try:
                    (self.cache_key_path / f).unlink()
                except FileNotFoundError:
                    pass
            self.cache_index['files'] = list(used_cache_files)
            with zipfile.ZipFile(str(self.cache_index_path), 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr('index.json', json.dumps(self.cache_index))
            hash_root_to_hash_dict = collections.defaultdict(list)
            for hash in self._cache:
                hash_root_to_hash_dict[hash[:16]].append(hash)
            for hash_root in self._updated_cache_hash_roots:
                cache_zip_path = self.cache_key_path / '{0}.zip'.format(hash_root)
                with zipfile.ZipFile(str(cache_zip_path), 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                    data = {'codebraid_version': codebraid_version,
                            'cache': {}}
                    for hash in hash_root_to_hash_dict[hash_root]:
                        data['cache'][hash] = self._cache[hash]
                    zf.writestr('cache.json', json.dumps(data))
