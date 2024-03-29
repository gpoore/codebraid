# -*- coding: utf-8 -*-
#
# Copyright (c) 2021-2022, Geoffrey M. Poore
# All rights reserved.
#
# Licensed under the BSD 3-Clause License:
# http://opensource.org/licenses/BSD-3-Clause
#


from __future__ import annotations


import base64
import collections
import pathlib
import queue
import re
import subprocess
import time
try:
    import jupyter_client
except ImportError:
    jupyter_client = None
from .. import util
from .. import message
from ..code_collections import Session
from ..progress import Progress


_ansi_color_escape_code_re = re.compile('\x1b.*?m')
_version_number_re = re.compile(r'(?P<major>\d+)(?:\.(?P<minor>\d+)(?:\.(?P<patch>\d+))?)?')

kernel_name_aliases: dict[str, str] = {}
kernel_name_collisions: dict[str, set[str]] = collections.defaultdict(set)
if jupyter_client is not None:
    for k, v in jupyter_client.kernelspec.KernelSpecManager().get_all_specs().items():
        for alias in [k.lower(), v['spec']['display_name'].lower(), v['spec']['language'].lower()]:
            if alias in kernel_name_aliases:
                kernel_name_collisions[alias].add(k)
            else:
                kernel_name_aliases[alias] = k
    for alias in kernel_name_collisions:
        kernel_name_collisions[alias].add(kernel_name_aliases[alias])
        if len(kernel_name_collisions[alias]) > 1:
            name_to_version_map = {}
            for k in kernel_name_collisions[alias]:
                match = _version_number_re.search(k)
                if match is None:
                    name_to_version_map[k] = None
                else:
                    major = int(match.group('major'))
                    minor = int(match.group('minor')) if match.group('minor') is not None else 0
                    patch = int(match.group('patch')) if match.group('patch') is not None else 0
                    name_to_version_map[k] = (major, minor, patch)
            if not all(v is not None for v in name_to_version_map.values()):
                del kernel_name_aliases[alias]
            else:
                last_version = None
                for k, v in name_to_version_map.items():
                    if last_version is None or v > last_version:
                        kernel_name_aliases[alias] = k
                        last_version = v
                    elif v == last_version:
                        del kernel_name_aliases[alias]
                        break


mime_type_to_file_extension_map: dict[str, str] = {
    'image/png': 'png',
    'image/jpeg': 'jpg',
    'image/svg+xml': 'svg',
    'application/pdf': 'pdf',
}


_home_path_re_pattern = re.escape(pathlib.Path('~').expanduser().as_posix()).replace('/', r'[\\/]')
_home_path_re = re.compile(_home_path_re_pattern, re.IGNORECASE)


async def exec(session: Session, *, cache_key_path: pathlib.Path, progress: Progress) -> None:
    '''
    Execute code from a session with a Jupyter kernel, attach textual output
    to the code chunks within the session, and save rich output files.
    '''
    # https://jupyter-client.readthedocs.io/en/stable/api/client.html
    # https://jupyter-client.readthedocs.io/en/stable/messaging.html#messages-on-the-iopub-pub-sub-channel

    session.did_exec = True
    progress.session_exec_stage_start(session, stage='run')

    if jupyter_client is None:
        msg = 'Cannot import "jupyter_client" Python module; install it and try again'
        session.errors.append(message.SysConfigError(msg))
        progress.session_exec_stage_end(session, stage='run')
        progress.session_finished(session)
        return

    if jupyter_client.version_info < (6, 1):
        # Require async support
        msg = f'jupyter_client >= 6.1.0 is required; version {jupyter_client.__version__} is installed'
        session.errors.append(message.SysConfigError(msg))
        progress.session_exec_stage_end(session, stage='run')
        progress.session_finished(session)
        return

    kernel_name = kernel_name_aliases.get(session.jupyter_kernel.lower())
    if kernel_name is None:
        if session.jupyter_kernel in kernel_name_collisions:
            msg = (
                f'''Jupyter kernel "{session.jupyter_kernel}" is ambiguous; '''
                f'''could refer to {', '.join(f'"{k}"' for k in kernel_name_collisions[session.jupyter_kernel])}'''
            )
        else:
            msg = f'No Jupyter kernel was found for "{session.jupyter_kernel}"'
        session.errors.append(message.SysConfigError(msg))
        progress.session_exec_stage_end(session, stage='run')
        progress.session_finished(session)
        return

    kernel_manager = jupyter_client.AsyncKernelManager(kernel_name=kernel_name)
    try:
        await kernel_manager.start_kernel(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except jupyter_client.kernelspec.NoSuchKernel:
        msg = f'No Jupyter kernel was found for "{session.jupyter_kernel}"'
        session.errors.append(message.SysConfigError(msg))
        progress.session_exec_stage_end(session, stage='run')
        progress.session_finished(session)
        return
    except FileNotFoundError:
        msg = f'Jupyter kernel for "{session.jupyter_kernel}" has been deleted or corrupted'
        session.errors.append(message.SysConfigError(msg))
        progress.session_exec_stage_end(session, stage='run')
        progress.session_finished(session)
        return
    except Exception as e:
        msg = f'Failed to start Jupyter kernel for "{session.jupyter_kernel}":\n{e}'
        session.errors.append(message.SysConfigError(msg))
        progress.session_exec_stage_end(session, stage='run')
        progress.session_finished(session)
        return

    kernel_client = kernel_manager.client()
    kernel_client.start_channels()
    try:
        await kernel_client.wait_for_ready()
    except RuntimeError as e:
        kernel_client.stop_channels()
        await kernel_manager.shutdown_kernel()
        msg = f'Jupyter kernel timed out during setup:\n{e}'
        session.errors.append(message.RunConfigError(msg))
        progress.session_exec_stage_end(session, stage='run')
        progress.session_finished(session)
        return

    try:
        kernel_has_errors = False
        incomplete_cc_stack = []
        for cc in session.code_chunks:
            if kernel_has_errors:
                break
            if cc.output_index != cc.index:
                # If incomplete code, accumulate until complete
                incomplete_cc_stack.append(cc)
                continue
            if not incomplete_cc_stack:
                progress.session_chunk_start_exec(session, chunk=cc)
                cc_jupyter_id = kernel_client.execute(cc.code_str)
            else:
                incomplete_cc_stack.append(cc)
                progress.session_chunk_start_exec(session, chunk=incomplete_cc_stack[0])
                cc_jupyter_id = kernel_client.execute('\n'.join(icc.code_str for icc in incomplete_cc_stack))
            deadline = time.monotonic() + session.jupyter_timeout
            while True:
                try:
                    kernel_msg = await kernel_client.get_iopub_msg(timeout=max(0, deadline - time.monotonic()))
                except queue.Empty:
                    kernel_msg = (f'Jupyter kernel "{kernel_name}" timed out during execution '
                                  f'(jupyter_timeout = {session.jupyter_timeout} s)')
                    cc.errors.append(message.RunConfigError(kernel_msg))
                    kernel_has_errors = True
                    break
                if kernel_msg['parent_header'].get('msg_id') != cc_jupyter_id:
                    continue
                kernel_msg_type = kernel_msg['msg_type']
                kernel_msg_content = kernel_msg['content']
                if kernel_msg_type == 'status' and kernel_msg_content['execution_state'] == 'idle':
                    break
                if kernel_msg_type in ('display_data', 'execute_result'):
                    # Rich output
                    if cc.rich_output is None:
                        cc.rich_output = []
                    rich_output_files = {}
                    rich_output = {'files': rich_output_files, 'data': kernel_msg_content['data']}
                    for mime_type, data in kernel_msg_content['data'].items():
                        file_extension = mime_type_to_file_extension_map.get(mime_type)
                        if file_extension is None:
                            continue
                        if 'name' not in cc.options:
                            file_name = f'''{kernel_name}-{session.name or ''}-{cc.output_index+1:03d}-{len(cc.rich_output)+1:02d}.{file_extension}'''
                        else:
                            file_name = f'''{cc.options['name']}-{len(cc.rich_output)+1}.{file_extension}'''
                        session.files.append(file_name)
                        ro_path = cache_key_path / file_name
                        if file_extension == 'svg':
                            ro_path.write_text(data, encoding='utf8')
                        else:
                            ro_path.write_bytes(base64.b64decode(data))
                        rich_output_files[mime_type] = ro_path.as_posix()
                    cc.rich_output.append(rich_output)
                    rich_output_text = kernel_msg_content['data'].get('text/plain')
                    if rich_output_text:
                        progress.session_chunk_rich_output_text(session, chunk=cc, output=rich_output_text)
                    if rich_output_files:
                        progress.session_chunk_rich_output_files(session, chunk=cc, files=rich_output_files.values())
                elif kernel_msg_type == 'stream':
                    if kernel_msg_content['name'] == 'stdout':
                        cc.stdout_lines.extend(util.splitlines_lf(kernel_msg_content['text']))
                        progress.session_chunk_stdout(session, chunk=cc, output=kernel_msg_content['text'])
                    elif kernel_msg_content['name'] == 'stderr':
                        cc.stderr_lines.extend(util.splitlines_lf(_home_path_re.sub('~', kernel_msg_content['text'])))
                        progress.session_chunk_stderr(session, chunk=cc, output=kernel_msg_content['text'])
                elif kernel_msg_type == 'error':
                    kernel_msg_text = _ansi_color_escape_code_re.sub('', '\n'.join(kernel_msg_content['traceback']))
                    kernel_msg_text = _home_path_re.sub('~', kernel_msg_text)
                    # This is currently treated as a `StderrRunError` and
                    # stored in `stderr_lines`.  For some kernels, it may
                    # make more sense to use `RunError` or further refine the
                    # error system.
                    cc.stderr_lines.extend(util.splitlines_lf(kernel_msg_text))
                    cc.errors.append(message.StderrRunError(cc.stderr_lines))
                    kernel_has_errors = True
                    progress.session_chunk_stderr(session, chunk=cc, output=kernel_msg_text)
            if not incomplete_cc_stack:
                progress.session_chunk_end_exec(session, chunk=cc)
            else:
                progress.session_chunk_end_exec(session, chunk=incomplete_cc_stack[-1])
                incomplete_cc_stack = []
    finally:
        kernel_client.stop_channels()
        await kernel_manager.shutdown_kernel()

    progress.session_exec_stage_end(session, stage='run')
    progress.session_finished(session)
