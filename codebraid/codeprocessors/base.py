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
import io
import json
import locale
import pathlib
import pkgutil
import re
import subprocess
import shlex
import shutil
import sys
import tempfile
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
                if name != 'python':
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
            self.source_template = definition.pop('source_template', '{code}\n')
            self.chunk_wrapper = definition.pop('chunk_wrapper')
            self.inline_expression_formatter = definition.pop('inline_expression_formatter', None)
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
            self._name_escaped = '"{0}"'.format(self.name.replace('\\', '\\\\').replace('"', '\\"'))
        if len(session_key) == 3:
            self.source_name = None
        else:
            self.source_name = session_key[3]
        self.lang_def = self.code_processor.language_definitions[self.lang]
        self._hash_function = self.code_processor.cache_config.get('hash_function', None)

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
            if cc.is_expr and self.lang_def.inline_expression_formatter is None:
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

        if self._hash_function is None:
            hasher = hashlib.blake2b()
        elif self._hash_function == 'sha512':
            hasher = hashlib.sha512()
        else:
            raise ValueError
        code_len = 0
        # Hash needs to depend on the language definition
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
    def __init__(self, *, code_chunks, code_options, cross_source_sessions, cache_path):
        self.code_chunks = code_chunks
        self.code_options = code_options
        self.cross_source_sessions = cross_source_sessions
        self.cache_path = cache_path

        self._load_cache_config_prep_cache()
        self._load_language_definitions()
        self._index_named_code_chunks()
        self._resolve_code_copying()
        self._create_sessions()


    def _load_cache_config_prep_cache(self):
        '''
        Load existing cache configuration, or generate default config.
        '''
        cache_config = {}
        if self.cache_path is not None:
            cache_config_path = self.cache_path / 'config.zip'
            if cache_config_path.is_file():
                with zipfile.ZipFile(str(cache_config_path)) as zf:
                    with zf.open('config.json') as f:
                        if sys.version_info < (3, 6):
                            cache_config = json.loads(f.read().decode('utf8'))
                        else:
                            cache_config = json.load(f)
        if not cache_config and sys.version_info < (3, 6):
            cache_config['hash_function'] = 'sha512'
        self.cache_config = cache_config

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


    def _load_language_definitions(self):
        '''
        Load language definitions, and mark any code chunks that lack
        necessary definitions.
        '''
        raw_language_index = pkgutil.get_data('codebraid', 'languages/index.bespon')
        if raw_language_index is None:
            raise err.CodebraidError('Failed to find "codebraid/languages/index.bespon"')
        language_index = bespon.loads(raw_language_index)
        language_definitions = collections.defaultdict(lambda: None)
        required_langs = set(cc.options['lang'] for cc in self.code_chunks if cc.execute)
        for lang in required_langs:
            try:
                lang_def_fname = language_index[lang]
            except KeyError:
                for cc in self.code_chunks:
                    if cc.options['lang'] == lang and cc.execute:
                        cc.source_errors.append('Language definition for "{0}" does not exist, or is not indexed'.format(lang))
                continue
            lang_def_bytes = pkgutil.get_data('codebraid', 'languages/{0}'.format(lang_def_fname))
            if lang_def_bytes is None:
                for cc in self.code_chunks:
                    if cc.options['lang'] == lang and cc.execute:
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
                elif any(x.code is None for x in cc.copy_chunks):
                    still_unresolved_chunks.append(cc)
                else:
                    cc.copy_code()
            if not still_unresolved_chunks:
                break
            if len(still_unresolved_chunks) == len(unresolved_chunks):
                for cc in still_unresolved_chunks:
                    unresolved_names = ', '.join('"{0}"'.format(name) for name, x in zip(cc.options['copy'], cc.copy_chunks) if x.code is None)
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
        unresolved_chunks = [cc for cc in self.code_chunks if cc.command == 'paste' and not cc.source_errors]
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
                if self.cross_source_sessions:
                    key = (self, cc.options['lang'], cc.options['session'])
                else:
                    key = (self, cc.options['lang'], cc.options['session'], cc.source_name)
                sessions[key].append(cc)
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
                    self._run(session)
                self._process_session(session)
        self._resolve_output_copying()
        self._update_cache()


    def _load_cache(self, session):
        '''
        Load cached output, if it exists.
        '''
        if self.cache_path is not None and session.hash not in self._cache:
            session_cache_path = self.cache_path / '{0}.zip'.format(session.hash_root)
            if session_cache_path.is_file():
                # It may be worth modifying this in future to handle
                # some failure modes or do more validation on loaded data.
                with zipfile.ZipFile(str(session_cache_path)) as zf:
                    with zf.open('cache.json') as f:
                        if sys.version_info < (3, 6):
                            saved_cache = json.loads(f.read().decode('utf8'))
                        else:
                            saved_cache = json.load(f)
                if saved_cache['codebraid_version'] == codebraid_version:
                    self._cache.update(saved_cache)
                self._used_cache_files.add(session_cache_path.name)


    def _subproc(self, cmd, tmpdir_path, hash,
                 pipes=True, stderr_is_stdout=False):
        '''
        Wrapper around `subprocess.run()` that provides a single location for
        customizing handling.
        '''
        # Note that `shlex.split()` only works correctly on posix paths.  If
        # it is ever necessary to switch to non-posix paths under Windows, the
        # backslashes will require extra escaping.
        args = shlex.split(cmd)
        failed_proc_stderr = 'COMMAND FAILED (missing program or file): {0}'.format(cmd).encode('utf8')
        if pipes:
            if stderr_is_stdout:
                try:
                    proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                except FileNotFoundError:
                    proc = FailedProcess(args, stdout=failed_proc_stderr)
            else:
                try:
                    proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                except FileNotFoundError:
                    proc = FailedProcess(args, stdout=b'', stderr=failed_proc_stderr)
        else:
            # When stdout and stderr are stored in files rather than accessed
            # through pipes, the files are named using a session-derived hash
            # as a precaution against code accessing them and against
            # collisions.
            stdout_path = tmpdir_path / '{0}.stdout'.format(hash)
            stderr_path = tmpdir_path / '{0}.stderr'.format(hash)
            if stderr_is_stdout:
                with open(str(stdout_path), 'wb') as fout:
                    try:
                        proc = subprocess.run(args, stdout=fout, stderr=subprocess.STDOUT)
                    except FileNotFoundError:
                        proc = FailedProcess(args, stdout=failed_proc_stderr)
                if not isinstance(proc, FailedProcess):
                    proc.stdout = stdout_path.read_bytes()
            else:
                with open(str(stdout_path), 'wb') as fout:
                    with open(str(stderr_path), 'wb') as ferr:
                        try:
                            proc = subprocess.run(args, stdout=fout, stderr=ferr)
                        except FileNotFoundError:
                            proc = FailedProcess(args, stdout=b'', stderr=failed_proc_stderr)
                if not isinstance(proc, FailedProcess):
                    proc.stdout = stdout_path.read_bytes()
                    proc.stderr = stderr_path.read_bytes()
        return proc


    def _run(self, session):
        stdstream_delim_start = 'CodebraidStd'
        stdstream_delim = r'{0}(hash="{1}", chunk={{0}})'.format(stdstream_delim_start, session.hash[:64])
        stdstream_delim_escaped = stdstream_delim.replace('"', '\\"')
        stdstream_delim_start_hash = stdstream_delim.split(',', 1)[0]
        expression_delim_start = 'CodebraidExpr'
        expression_delim = r'{0}(hash="{1}")'.format(expression_delim_start, session.hash[64:])
        expression_delim_escaped = expression_delim.replace('"', '\\"')
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
            delim = stdstream_delim_escaped.format(cc.session_output_index)
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
                    expr_code = session.lang_def.inline_expression_formatter.format(stdout_delim=expression_delim_escaped,
                                                                                    stderr_delim=expression_delim_escaped,
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
            source_path.write_text(''.join(run_code_list), encoding='utf8')

            # All paths use `.as_posix()` for `shlex.split()` compatibility
            template_dict = {'executable': session.lang_def.executable,
                             'extension': session.lang_def.extension,
                             'source': source_path.as_posix(),
                             'source_dir': source_dir_path.as_posix(),
                             'source_without_extension': (source_dir_path / source_name).as_posix()}

            for cmd_template in session.lang_def.pre_run_commands:
                if error:
                    break
                pre_proc = self._subproc(cmd_template.format(**template_dict), source_dir_path, session.hash_root, stderr_is_stdout=True)
                if pre_proc.returncode != 0:
                    error = True
                    session.pre_run_errors = True
                    encoding = session.lang_def.pre_run_encoding or locale.getpreferredencoding(False)
                    stdout_str = io.TextIOWrapper(io.BytesIO(pre_proc.stdout), encoding=encoding, errors='backslashreplace').read()
                    session.pre_run_error_lines = util.splitlines_lf(stdout_str)

            for cmd_template in session.lang_def.compile_commands:
                if error:
                    break
                comp_proc = self._subproc(cmd_template.format(**template_dict), source_dir_path, session.hash_root, stderr_is_stdout=True)
                if comp_proc.returncode != 0:
                    error = True
                    session.compile_errors = True
                    encoding = session.lang_def.compile_encoding or locale.getpreferredencoding(False)
                    stdout_lines = []
                    stdout_str = io.TextIOWrapper(io.BytesIO(comp_proc.stdout), encoding=encoding, errors='backslashreplace').read()
                    stderr_lines = util.splitlines_lf(stdout_str)

            if not error:
                cmd_template = session.lang_def.run_command
                run_proc = self._subproc(cmd_template.format(**template_dict), source_dir_path, session.hash_root)
                if run_proc.returncode != 0:
                    error = True
                    session.run_errors = True
                encoding = session.lang_def.run_encoding or locale.getpreferredencoding(False)
                try:
                    stdout_str = io.TextIOWrapper(io.BytesIO(run_proc.stdout), encoding=encoding).read()
                    stderr_str = io.TextIOWrapper(io.BytesIO(run_proc.stderr), encoding=encoding).read()
                except UnicodeDecodeError:
                    session.decode_error = True
                    stdout_str = io.TextIOWrapper(io.BytesIO(run_proc.stdout), encoding=encoding, errors='backslashreplace').read()
                    stderr_str = io.TextIOWrapper(io.BytesIO(run_proc.stderr), encoding=encoding, errors='backslashreplace').read()
                stdout_lines = util.splitlines_lf(stdout_str)
                stderr_lines = util.splitlines_lf(stderr_str)

            for cmd_template in session.lang_def.post_run_commands:
                if error:
                    break
                post_proc = self._subproc(cmd_template.format(**template_dict), source_dir_path, session.hash_root, stderr_is_stdout=True)
                if post_proc.returncode != 0:
                    error = True
                    session.post_run_errors = True
                    encoding = session.lang_def.post_run_encoding or locale.getpreferredencoding(False)
                    stdout_str = io.TextIOWrapper(io.BytesIO(post_proc.stdout), encoding=encoding, errors='backslashreplace').read()
                    session.post_run_error_lines = util.splitlines_lf(stdout_str)

        session.error = error

        if session.pre_run_errors:
            chunk_stdout_dict = {}
            chunk_stderr_dict = {0: ['PRE-RUN ERROR:', *session.pre_run_error_lines]}
            chunk_expr_dict = {}
            chunk_source_error_dict = {}
        elif session.post_run_errors:
            chunk_stdout_dict = {}
            chunk_stderr_dict = {0: ['POST-RUN ERROR:', *session.post_run_error_lines]}
            chunk_expr_dict = {}
            chunk_source_error_dict = {}
        else:
            # Ensure that there's at least one delimiter to serve as a
            # sentinel, even if the code never ran due to something like a
            # syntax error or compilation error
            sentinel_delim = stdstream_delim.format(-1)
            stdout_lines.append('')
            stdout_lines.append(sentinel_delim)
            stderr_lines.append('')
            stderr_lines.append(sentinel_delim)
            expected_stdstream_delims.append(-1)
            chunk_stdout_dict = {}
            chunk_stderr_dict = {}
            chunk_expr_dict = {}
            chunk_source_error_dict = {}
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
                    next_session_output_index = int(line.split('chunk=', 1)[1].split(')', 1)[0])
                    if index > 0:
                        chunk_end_index = index - 1
                        if stdout_lines[chunk_end_index]:
                            chunk_end_index = index
                    if chunk_end_index > chunk_start_index:
                        if session_output_index >= 0 and session.code_chunks[session_output_index].is_expr:
                            combined_lines = stdout_lines[chunk_start_index:chunk_end_index]
                            for combined_index, combined_line in enumerate(combined_lines):
                                if combined_line.startswith(expression_delim_start) and combined_line.startswith(expression_delim):
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
                    next_session_output_index = int(line.split('chunk=', 1)[1].split(')', 1)[0])
                    if next_session_output_index == session_output_index and next_session_output_index >= 0:
                        # A code chunk that is not actually complete was run
                        # with the default `complete=true`, and this resulted
                        # in a delimiter being printed multiple times.  Since
                        # this error can only be detected at runtime, it is
                        # stored specially rather than being reported as a
                        # normal source error.  This guarantees that the code
                        # won't run again until this is fixed.
                        error_cc = session.code_chunks[session_output_index]
                        message_lines = ['RUNTIME SOURCE ERROR in "{0}" near line {1}:'.format(error_cc.source_name,
                                                                                               error_cc.source_start_line_number),
                                         'This ran with "complete" value "true" but is not a complete unit of code.']
                        session.errors = True
                        session.run_errors = True
                        chunk_stdout_dict = {}
                        chunk_stderr_dict = {}
                        chunk_expr_dict = {}
                        chunk_source_error_dict = {error_cc.session_output_index: message_lines}
                        break
                    if next_session_output_index != next(expected_stdstream_delims_iter, None):
                        # A code chunk that is not actually complete was run
                        # with the default `complete=true`, or a code chunk
                        # with `outside_main` ended in an incomplete state.
                        # This prevented a delimiter from being printed.
                        if next_session_output_index > 0:
                            error_cc = session.code_chunks[session_output_index]
                        else:
                            error_cc = session.code_chunks[session.code_chunks[0].session_output_index]
                        message_lines = ['RUNTIME SOURCE ERROR in "{0}" near line {1}:'.format(error_cc.source_name,
                                                                                        error_cc.source_start_line_number)]
                        if error_cc.options['complete']:
                            message_lines.append('This ran with "complete" value "true" but is not a complete unit of code.')
                        elif error_cc.options['outside_main']:
                            message_lines.append('This marked the end of "outside_main" but is not a complete unit of code.')
                        else:
                            # Fallback; previous cases should cover everything
                            message_lines.append('This is not a complete unit of code.')
                        message_lines.append('It interfered with the following code chunk.')
                        session.errors = True
                        session.run_errors = True
                        chunk_stdout_dict = {}
                        chunk_stderr_dict = {}
                        chunk_expr_dict = {}
                        chunk_source_error_dict = {error_cc.session_output_index: message_lines}
                        break
                    if index > 0:
                        chunk_end_index = index - 1
                        if stderr_lines[chunk_end_index]:
                            chunk_end_index = index
                    if chunk_end_index > chunk_start_index:
                        cc_stderr_lines = stderr_lines[chunk_start_index:chunk_end_index]
                        if session_output_index >= 0 and session.code_chunks[session_output_index].is_expr:
                            for combined_index, combined_line in enumerate(cc_stderr_lines):
                                if combined_line.startswith(expression_delim_start) and combined_line.startswith(expression_delim):
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

        cache = {'stdout_lines': chunk_stdout_dict,
                 'stderr_lines': chunk_stderr_dict,
                 'expr_lines': chunk_expr_dict,
                 'source_error_lines': chunk_source_error_dict}
        self._cache[session.hash] = cache
        self._updated_cache_hash_roots.append(session.hash_root)


    def _process_session(self, session):
        cache = self._cache[session.hash]
        # `int()` handles keys from json cache
        for index, lines in cache['stdout_lines'].items():
            session.code_chunks[int(index)].stdout_lines = lines
        for index, lines in cache['stderr_lines'].items():
            session.code_chunks[int(index)].stderr_lines = lines
        for index, lines in cache['expr_lines'].items():
            session.code_chunks[int(index)].expr_lines = lines
        for index, lines in cache['source_error_lines'].items():
            session.code_chunk[int(index)].source_errors.extend(lines)


    def _update_cache(self):
        if self.cache_path is not None:
            for cache_zip_path in self.cache_path.glob('*.zip'):
                if cache_zip_path.name not in self._used_cache_files:
                    cache_zip_path.unlink()
            for hash_root in self._updated_cache_hash_roots:
                cache_zip_path = self.cache_path / '{0}.zip'.format(hash_root)
                with zipfile.ZipFile(str(cache_zip_path), 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                    data = {k: v for k, v in self._cache.items() if k.startswith(hash_root)}
                    data['codebraid_version'] = codebraid_version
                    zf.writestr('cache.json', json.dumps(data))
            if self.cache_config:
                cache_config_path = self.cache_path / 'config.zip'
                with zipfile.ZipFile(str(cache_config_path), 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr('config.json', json.dumps(self.cache_config))
