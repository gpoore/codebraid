# -*- coding: utf-8 -*-
#
# Copyright (c) 2019-2022, Geoffrey M. Poore
# All rights reserved.
#
# Licensed under the BSD 3-Clause License:
# http://opensource.org/licenses/BSD-3-Clause
#


from __future__ import annotations


import asyncio
import atexit
import collections
import json
import pathlib
import sys
import time
import zipfile
from typing import Callable, Dict, List, Optional, Set
from .. import err
from .. import message
from .. import util
from ..code_chunks import CodeChunk, CodeKey
from ..code_collections import Session, Source
from ..progress import Progress
from ..version import __version__ as codebraid_version
from . import exec_builtin
from . import exec_jupyter




class CodeProcessor(object):
    '''
    Process code chunks.  This can involve executing code, copying code and/or
    output between code chunks, and creating source files.
    '''
    def __init__(self,
                 *,
                 code_chunks: List[CodeChunk],
                 cross_origin_sessions: bool,
                 no_cache: bool,
                 cache_path: pathlib.Path,
                 cache_key: str,
                 origin_paths_for_cache: Optional[List[pathlib.Path]],
                 code_defaults: Optional[Dict],
                 session_defaults: Optional[Dict],
                 only_code_output: bool,
                 progress: Progress):
        self.code_chunks = code_chunks
        self.cross_origin_sessions = cross_origin_sessions
        self.no_cache = no_cache
        self.cache_path = cache_path
        self.cache_key = cache_key
        self.origin_paths_for_cache = origin_paths_for_cache
        self._origin_paths_for_cache_as_strings: Optional[List[str]]
        if origin_paths_for_cache is None:
            self._origin_paths_for_cache_as_strings = None
        else:
            self._origin_paths_for_cache_as_strings = [p.as_posix() for p in origin_paths_for_cache]
        self.code_defaults = code_defaults
        self.session_defaults = session_defaults
        self._only_code_output = only_code_output
        self._progress = progress

        self._old_cache_index: Optional[Dict] = None
        self._cache_key_path = cache_path / cache_key
        self._cache_index_path = cache_path / cache_key / f'{cache_key}_index.zip'
        self._cache_lock_path = cache_path / cache_key / f'{cache_key}.lock'

        self._sessions: Dict[CodeKey, Session] = util.KeyDefaultDict(
            lambda x: Session(x, code_defaults=self.code_defaults, session_defaults=self.session_defaults)
        )
        self._session_hash_root_sets: Dict[str, Set] = collections.defaultdict(set)
        self._cached_sessions: Set[Session] = set()
        self._named_code_chunks: Dict[str, CodeChunk] = {}

        self._sources: Dict[CodeKey, Source] = util.KeyDefaultDict(lambda x: Source(x))

        # Use `atexit` to improve the odds of cleanup in the event of an
        # unexpected exit.  `cleanup()` ends by invoking
        # `atexit.unregister(self.cleanup)`.
        atexit.register(self.cleanup)


    @property
    def exit_code(self) -> int:
        code = 0b00000000
        if any(s.status.prevent_exec for s in self._sessions.values()):
            code ^= 0b00000100
        if (any(s.status.has_errors and not s.status.prevent_exec for s in self._sessions.values()) or
                any(s.status.has_errors for s in self._sources.values())):
            code ^= 0b00001000
        if any(s.status.has_warnings for s in self._sessions.values()):
            code ^= 0b00010000
        # Once there are warnings related to document build, add condition:
        #   code ^= 0b0010000
        return code


    def process(self):
        '''
        Set additional code chunk attributes that are inconvenient or
        impossible to determine until all code chunks are assembled.  Group
        code chunks into sessions and sources.
        '''
        self._index_named_code_chunks()
        self._resolve_code_copying()
        self._prep_cache()
        self._create_sessions_and_sources()
        if self._only_code_output and self._cached_sessions:
            # Resolve output copying as early as possible
            self._resolve_output_copying(from_cache=True)


    def exec(self):
        '''
        Execute code, update code, and copy code output.
        '''
        builtin_sessions = []
        jupyter_sessions = []
        for session in self._sessions.values():
            if not session.needs_exec:
                continue
            if session.jupyter_kernel is None:
                builtin_sessions.append(session)
            else:
                jupyter_sessions.append(session)
        # Use `atexit` to improve the odds of updating the cache index in the
        # event of an unexpected exit.  Any session caches that are
        # successfully updated can be used in the future, regardless of
        # whether an index is created.  However, if an index is not created,
        # there is no guarantee that unused cache files will be deleted.
        if builtin_sessions or jupyter_sessions:
            atexit.register(self._update_cache_index)
            if sys.platform == 'win32':
                # For Windows, need different event loops depending on whether
                # code execution uses the built-in system (asyncio subprocess)
                # or a Jupyter kernel:  https://bugs.python.org/issue37373.
                original_loop_policy = asyncio.get_event_loop_policy()
                if builtin_sessions:
                    if not isinstance(original_loop_policy, asyncio.windows_events.WindowsProactorEventLoopPolicy):
                        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
                    asyncio.run(self._exec_sessions(builtin_sessions=builtin_sessions))
                    asyncio.set_event_loop_policy(original_loop_policy)
                if jupyter_sessions:
                    if not isinstance(original_loop_policy, asyncio.windows_events.WindowsSelectorEventLoopPolicy):
                        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
                    asyncio.run(self._exec_sessions(jupyter_sessions=jupyter_sessions))
                    asyncio.set_event_loop_policy(original_loop_policy)
            else:
                asyncio.run(self._exec_sessions(builtin_sessions=builtin_sessions, jupyter_sessions=jupyter_sessions))
            self._update_cache_index()
            atexit.unregister(self._update_cache_index)
        self._resolve_output_copying()

    async def _exec_sessions(self, *,
                             builtin_sessions: Optional[List[Session]]=None,
                             jupyter_sessions: Optional[List[Session]]=None):
        ticktock = asyncio.create_task(self._progress.ticktock())
        max_concurrent_jobs = asyncio.Semaphore(1)
        coroutines = []
        if builtin_sessions is not None:
            coroutines.extend(
                [self._exec_session(exec_builtin.exec, session, max_concurrent_jobs) for session in builtin_sessions]
            )
        if jupyter_sessions is not None:
            coroutines.extend(
                [self._exec_session(exec_jupyter.exec, session, max_concurrent_jobs) for session in jupyter_sessions]
            )
        await asyncio.gather(*coroutines)
        ticktock.cancel()


    async def _exec_session(self, exec_func: Callable, session: Session, max_concurrent_jobs: asyncio.Semaphore):
        async with max_concurrent_jobs:
            await exec_func(session, cache_key_path=self._cache_key_path, progress=self._progress)
        self._update_session_cache(session)


    def _index_named_code_chunks(self):
        '''
        Index named code chunks, and mark code chunks with duplicate names.
        '''
        named_code_chunks = self._named_code_chunks
        for cc in self.code_chunks:
            cc_name = cc.options.get('name')
            if cc_name is not None:
                if cc_name not in named_code_chunks:
                    named_code_chunks[cc_name] = cc
                    continue
                other_cc = named_code_chunks[cc_name]
                src = other_cc.origin_name
                lineno = other_cc.origin_start_line_number
                msg = (f'Code chunk names must be unique; "{cc_name}" is already used in "{src}" near line {lineno}')
                cc.errors.append(message.SourceError(msg))


    def _resolve_code_copying(self):
        '''
        For code chunks with copying, handle the code copying.  The output
        copying for commands like "paste" must be handled separately later,
        after code is executed.
        '''
        named_chunks = self._named_code_chunks
        unresolved_chunks = []
        for cc in self.code_chunks:
            copy_chunk_names = cc.options.get('copy')
            if copy_chunk_names is not None:
                copy_chunks = [named_chunks.get(name) for name in copy_chunk_names]
                if any(x is None for x in copy_chunks):
                    unknown_names = ', '.join(f'"{name}"'
                                              for name, copied_cc in zip(copy_chunk_names, copy_chunks)
                                              if copied_cc is None)
                    cc.errors.append(message.SourceError(f'Unknown name(s) for copying: {unknown_names}'))
                    continue
                cc.copy_chunks.extend(copy_chunks)
                unresolved_chunks.append(cc)
        still_unresolved_chunks = []
        while True:
            for cc in unresolved_chunks:
                if any(copied_cc.errors.prevent_exec for copied_cc in cc.copy_chunks):
                    traceback_list = []
                    for copied_cc in cc.copy_chunks:
                        if copied_cc.errors.prevent_exec:
                            name = copied_cc.options['name']
                            src = copied_cc.origin_name
                            lineno = copied_cc.origin_start_line_number
                            traceback_list.append(f'  * "{name}" ("{src}" near line {lineno})')
                    traceback = '\n'.join(traceback_list)
                    msg = f'Code chunk(s) have error(s) that prevent copying:\n{traceback}'
                    cc.errors.append(message.SourceError(msg))
                elif any(not copied_cc.code_lines for copied_cc in cc.copy_chunks):
                    still_unresolved_chunks.append(cc)
                else:
                    cc.copy_code()
            if not still_unresolved_chunks:
                break
            if len(still_unresolved_chunks) == len(unresolved_chunks):
                # Locate circular copying dependencies.  The case of a code
                # chunk trying to copy itself directly is already handled
                # during code chunk creation.
                for cc in still_unresolved_chunks:
                    copy_path_list = [cc]
                    copy_path_set = set(copy_path_list)
                    copy_state = [cc.copy_chunks.copy()]
                    while copy_state:
                        try:
                            last_cc = copy_state[-1].pop()
                        except IndexError:
                            copy_state.pop()
                            continue
                        while len(copy_path_list) > len(copy_state):
                            copy_path_set.remove(copy_path_list.pop())
                        copy_path_list.append(last_cc)
                        if last_cc in copy_path_set:
                            start_circular_name = copy_path_list[1].options['name']
                            traceback_list = []
                            for copied_cc in copy_path_list[1:]:
                                name = copied_cc.options['name']
                                src = copied_cc.origin_name
                                lineno = copied_cc.origin_start_line_number
                                if copied_cc is last_cc:
                                    traceback_list.append(f' => "{name}" ("{src}" near line {lineno})')
                                else:
                                    traceback_list.append(f' -> "{name}" ("{src}" near line {lineno})')
                            traceback = '\n'.join(traceback_list)
                            msg = f'Circular dependency in copying "{start_circular_name}":\n{traceback}'
                            cc.errors.append(message.SourceError(msg))
                            break
                        copy_path_set.add(last_cc)
                        if 'copy' in last_cc.options:
                            copy_state.append(last_cc.copy_chunks.copy())
                still_unresolved_chunks = [cc for cc in still_unresolved_chunks if not cc.errors.prevent_exec]
            unresolved_chunks = still_unresolved_chunks
            still_unresolved_chunks = []

    def _resolve_output_copying(self, *, from_cache: bool=False):
        '''
        For code chunks with copying, handle the output copying.  The output
        copying for commands like "paste" must be handled after code is
        executed, while any code copying must be handled before so that it is
        available for execution.
        '''
        # There is no need to check for undefined names or circular
        # dependencies; that's already been handled in
        # `_resolve_code_copying()`.  Still need to check for errors that
        # prevent copying, since there can be runtime source errors or other
        # errors related to output.  Code chunks with
        # `.needs_to_copy == False` are copying code-only code chunks and thus
        # have no output for copying.
        unresolved_chunks = [cc for cc in self.code_chunks
                             if cc.command == 'paste' and not cc.errors.prevent_exec and cc.needs_to_copy]
        still_unresolved_chunks = []
        while True:
            for cc in unresolved_chunks:
                if any(copied_cc.errors.prevent_exec for copied_cc in cc.copy_chunks):
                    traceback_list = []
                    for copied_cc in cc.copy_chunks:
                        if copied_cc.errors.prevent_exec:
                            name = copied_cc.options['name']
                            src = copied_cc.origin_name
                            lineno = copied_cc.origin_start_line_number
                            traceback_list.append(f'  * "{name}" ("{src}" near line {lineno})')
                    traceback = '\n'.join(traceback_list)
                    msg = f'Code chunk(s) have error(s) that prevent copying:\n{traceback}'
                    cc.errors.append(message.SourceError(msg))
                    self._progress.source_chunk_complete(cc.source, chunk=cc)
                    if all(not cc.needs_to_copy or cc.errors.prevent_exec for cc in cc.source.code_chunks):
                        self._progress.source_finished(cc.source)
                elif any(copied_cc.needs_to_copy for copied_cc in cc.copy_chunks):
                    still_unresolved_chunks.append(cc)
                else:
                    cc.copy_output()
                    self._progress.source_chunk_complete(cc.source, chunk=cc)
                    if all(not cc.needs_to_copy or cc.errors.prevent_exec for cc in cc.source.code_chunks):
                        self._progress.source_finished(cc.source)
            if not still_unresolved_chunks or (from_cache and len(unresolved_chunks) == len(still_unresolved_chunks)):
                break
            unresolved_chunks = still_unresolved_chunks
            still_unresolved_chunks = []


    def _create_sessions_and_sources(self):
        '''
        Assemble code chunks into sessions and sources.
        '''
        placeholder_lang_num = 0
        for cc in self.code_chunks:
            if cc.execute:
                code_collection_name = cc.options['session']
                code_collection_type = 'session'
            else:
                code_collection_name = cc.options['source']
                code_collection_type = 'source'
            if self.cross_origin_sessions:
                origin_name = None
            else:
                origin_name = cc.origin_name
            cc.key = CodeKey(cc.options['lang'], code_collection_name, code_collection_type, origin_name)
            if cc.options['inherited_lang']:
                cc.options['placeholder_lang'] = f'{placeholder_lang_num}'
                placeholder_lang_num += 1
            if cc.execute:
                self._sessions[cc.key].append(cc)
            else:
                self._sources[cc.key].append(cc)
        for session in self._sessions.values():
            session.finalize()
            if session.status.prevent_exec:
                session.needs_exec = False
            else:
                self._session_hash_root_sets[session.hash_root].add(session)
                if self._load_session_cache(session):
                    session.needs_exec = False
        for source in self._sources.values():
            source.finalize()

        # Need to register collections before reporting any progress
        self._progress.register_code_collections(sessions=self._sessions.values(), sources=self._sources.values())
        for session in self._sessions.values():
            if session.status.prevent_exec:
                self._progress.session_errors_prevent_exec(session)
                for cc in session.code_chunks:
                    self._progress.session_chunk_complete_no_exec(session, chunk=cc)
                self._progress.session_finished(session)
            elif session in self._cached_sessions:
                self._progress.session_load_cache(session)
                for cc in session.code_chunks:
                    self._progress.session_chunk_complete_no_exec(session, chunk=cc)
                self._progress.session_finished(session)
        for source in self._sources.values():
            for cc in source.code_chunks:
                if not cc.needs_to_copy or cc.errors.prevent_exec:
                    self._progress.source_chunk_complete(source, chunk=cc)
            if all(not cc.needs_to_copy or cc.errors.prevent_exec for cc in source.code_chunks):
                self._progress.source_finished(source)


    def _prep_cache(self):
        '''
        Prepare the cache.

        A document's cache is located at `<cache_path>/<cache_key>/`.  If the
        document is read from stdin, <cache_key> is a constant.  If the
        document is read from file(s), <cache_key> is derived from a hash of
        the absolute source path(s).  Thus, the cache typically depends on
        source locations.  To provide some cross-device, cross-platform cache
        compatibility, source paths always use `~` to represent the user's
        home directory, even under Windows.

        Each session has a corresponding file in the document cache.  This
        file contains cacheable errors, cacheable warnings, and cacheable
        output (primarily text-based) such as stdout, sterr, and rich output.
        This data is stored in compressed JSON format.  For rich output,
        additional files such as images are also created.  While each session
        typically has its own separate file in the document cache, sessions
        can share a file in the rare case that their identifying hashes have
        identical starting sequences (`.hash_root`).

        The file `<cache_key>_index.zip` is used for managing the cache.  It
        includes all document source path(s) and a complete list of all cache
        files created (including itself).

        The cache is compatible with multiple documents being built
        simultaneously within a single `<cache_path>`, since the cache for
        each build will be located in its own subdirectory.  However, for a
        given document, only one build at a time is possible.  A lock file
        `<cache_path>/<cache_key>.lock` is used to enforce this.

        Notice that in cleaning outdated or invalid cache material, there is
        never wholesale directory removal.  Only files created directly by
        Codebraid are deleted.  Users should never manually create files in
        the cache, but if that happens those files should not be deleted
        unless they overwrite existing cache files.
        '''
        # Even when `no_cache == True`, need cache dir to store temp files
        # during build, such as rich output images
        self._cache_key_path.mkdir(parents=True, exist_ok=True)
        max_lock_wait = 5
        lock_check_interval = 0.1
        lock_time = 0
        while True:
            try:
                self._cache_lock_path.touch(exist_ok=False)
            except FileExistsError:
                if lock_time > max_lock_wait:
                    raise err.CodebraidError(
                        f'The cache for this document is locked.  This can happen if multiple processes attempt to '
                        f'build the document at the same time.  If Codebraid was forced to exit or encountered a '
                        f'severe error during the last run, it is also possible that the cache was corrupted.  In '
                        f'that case, the cache lock file "{self._cache_lock_path}" may need to be deleted manually.')
                time.sleep(lock_check_interval)
                lock_time += lock_check_interval
            else:
                break

        try:
            with zipfile.ZipFile(str(self._cache_index_path)) as zf:
                with zf.open('index.json') as f:
                    cache_index = json.load(f)
        except (FileNotFoundError, KeyError, json.JSONDecodeError):
            pass
        else:
            # These checks include handling source hash collisions and
            # corrupted caches.  The checks assume that if the key
            # 'codebraid_version' is present, then this is a valid Codebraid
            # index.
            if (self.no_cache or
                    not isinstance(cache_index, dict) or
                    cache_index.get('codebraid_version') != codebraid_version or
                    cache_index['origins'] != self._origin_paths_for_cache_as_strings or
                    not all((self._cache_key_path / f).is_file() for f in cache_index['files'])):
                if isinstance(cache_index, dict) and 'codebraid_version' in cache_index:
                    for f in cache_index['files']:
                        try:
                            (self._cache_key_path / f).unlink()
                        except FileNotFoundError:
                            pass
                else:
                    try:
                        self._cache_index_path.unlink()
                    except FileNotFoundError:
                        pass
            else:
                self._old_cache_index = cache_index


    def _load_session_cache(self, session: Session) -> bool:
        '''
        Load cached output for a session, if it exists.

        There's no need to check that all cache files are present in the case
        of rich output that results in additional files, because that is done
        during cache prep when the cache index is loaded.
        '''
        if self.no_cache or session.status.prevent_exec:
            return False
        if session in self._cached_sessions:
            return True
        session_cache_path = self._cache_key_path / f'{session.hash_root}.zip'
        try:
            with zipfile.ZipFile(str(session_cache_path)) as zf:
                with zf.open('cache.json') as f:
                    saved_cache = json.load(f)
        except (FileNotFoundError, KeyError, json.decoder.JSONDecodeError):
            return False
        if (not isinstance(saved_cache, dict) or
                'codebraid_version' not in saved_cache or
                saved_cache['codebraid_version'] != codebraid_version):
            return False
        try:
            session_cache = saved_cache['cache'][session.hash]
        except KeyError:
            return False
        for msg_name, msg_dict in session_cache['session_errors']:
            session.errors.append(message.message_name_to_class_map[msg_name](**msg_dict))
        for msg_name, msg_dict in session_cache['session_warnings']:
            session.warnings.append(message.message_name_to_class_map[msg_name](**msg_dict))
        session.files = session_cache['session_files']
        for index, chunk_cache in session_cache['code_chunks'].items():
            # `int(index)` because keys from JSON cache are strings
            chunk = session.code_chunks[int(index)]
            errors = chunk_cache.pop('errors', None)
            if errors is not None:
                for msg_name, msg_dict in errors:
                    chunk.errors.append(message.message_name_to_class_map[msg_name](**msg_dict))
            warnings = chunk_cache.pop('warnings', None)
            if warnings is not None:
                for msg_name, msg_dict in warnings:
                    chunk.warnings.append(message.message_name_to_class_map[msg_name](**msg_dict))
            for output_name, output in chunk_cache.items():
                setattr(chunk, output_name, output)
        self._cached_sessions.add(session)
        return True


    def _update_session_cache(self, update_session: Session):
        '''
        Update cache for a session.

        Notice that individual cache files contain output from multiple
        sessions in the rare case that the session hashes have identical
        starting sequences (`.hash_root`).  In that case, a cache file may be
        overwritten multiple times during a document build as additional
        sessions are executed.  While this is not maximally efficient from a
        file system perspective, it will be rare and it ensures that code
        output is preserved if at all possible in the event of an unexpected
        exit.
        '''
        if self.no_cache or update_session.status.prevent_caching:
            return
        hash_root_cache = {
            'codebraid_version': codebraid_version,
            'cache': {},
        }
        for session in self._session_hash_root_sets[update_session.hash_root]:
            if session.status.prevent_caching:
                continue
            session_code_chunks_cache = {}
            for index, chunk in enumerate(session.code_chunks):
                chunk_cache = {}
                if chunk.errors:
                    errors_cache = [(x.type, x.as_dict()) for x in chunk.errors if x.is_cacheable]
                    if errors_cache:
                        chunk_cache['errors'] = errors_cache
                if chunk.warnings:
                    warnings_cache = [(x.type, x.as_dict()) for x in chunk.warnings if x.is_cacheable]
                    if warnings_cache:
                        chunk_cache['warnings'] = warnings_cache
                for output_name in ('stdout_lines', 'stderr_lines', 'repl_lines', 'expr_lines', 'rich_output'):
                    output = getattr(chunk, output_name)
                    if output is not None:
                        chunk_cache[output_name] = output
                if chunk_cache:
                    # `str(index)` because keys for JSON cache are strings
                    session_code_chunks_cache[str(index)] = chunk_cache
            hash_root_cache['cache'][session.hash] = {
                'session_errors': [(x.type, x.as_dict()) for x in session.errors if x.is_cacheable],
                'session_warnings': [(x.type, x.as_dict()) for x in session.warnings if x.is_cacheable],
                'session_files': session.files,
                'code_chunks': session_code_chunks_cache,
            }
        hash_root_cache_path = self._cache_key_path / f'{update_session.hash_root}.zip'
        with zipfile.ZipFile(str(hash_root_cache_path), 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('cache.json', json.dumps(hash_root_cache))
        self._cached_sessions.add(update_session)


    def _update_cache_index(self):
        if self.no_cache:
            return
        used_cache_files = set()
        used_cache_files.add(f'{self.cache_key}_index.zip')
        for session in self._cached_sessions:
            used_cache_files.add(f'{session.hash_root}.zip')
            used_cache_files.update(session.files)
        if self._old_cache_index is not None:
            unused_cache_files = set(self._old_cache_index['files']) - used_cache_files
            for f in unused_cache_files:
                try:
                    (self._cache_key_path / f).unlink()
                except FileNotFoundError:
                    pass
        new_cache_index = {
            'codebraid_version': codebraid_version,
            'origins': self._origin_paths_for_cache_as_strings,
            'files': list(used_cache_files),
        }
        with zipfile.ZipFile(str(self._cache_index_path), 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('index.json', json.dumps(new_cache_index))


    def cleanup(self):
        try:
            self._cache_lock_path.unlink()
        except FileNotFoundError:
            pass
        if self.no_cache:
            for session in self._sessions.values():
                for f in session.files:
                    try:
                        (self._cache_key_path / f).unlink()
                    except FileNotFoundError:
                        pass
            try:
                self._cache_key_path.rmdir()
            except Exception:
                pass
            else:
                try:
                    self.cache_path.rmdir()
                except Exception:
                    pass
        atexit.unregister(self.cleanup)
