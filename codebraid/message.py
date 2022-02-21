# -*- coding: utf-8 -*-
#
# Copyright (c) 2021-2022, Geoffrey M. Poore
# All rights reserved.
#
# Licensed under the BSD 3-Clause License:
# http://opensource.org/licenses/BSD-3-Clause
#


from __future__ import annotations


from typing import Dict, List, Optional, Type, Union
from . import util


message_name_to_class_map: Dict[str, 'BaseMessage'] = {}


class MetaMessage(type):
    '''
    Metaclass for message class.  Check class attributes and create a mapping
    from class names (strings) to classes that is used in caching.
    '''
    def __new__(cls, name, parents, attr_dict):
        attr_dict['type'] = name
        display_name_list = []
        for c in name:
            if ord('A') <= ord(c) <= ord('Z') and display_name_list:
                display_name_list.append(' ')
            display_name_list.append(c)
        attr_dict['display_name'] = ''.join(display_name_list)
        attr_dict['is_stderr'] = 'Stderr' in name
        attr_dict['is_ref'] = name.endswith('Ref')
        new_class = super().__new__(cls, name, parents, attr_dict)
        if hasattr(new_class, 'category'):
            if not isinstance(new_class.category, str):
                raise TypeError
            for attr in cls._checked_attrs:
                if not hasattr(new_class, attr) or not isinstance(getattr(new_class, attr), bool):
                    raise TypeError
            if 'Error' in name:
                if not new_class.prevent_exec and 'CanExec' not in name:
                    raise ValueError
            elif 'Warning' in name:
                if new_class.prevent_caching or new_class.prevent_exec:
                    raise ValueError
            else:
                raise ValueError
            if new_class.prevent_caching and new_class.is_cacheable:
                raise ValueError
            if not new_class.is_cacheable:
                if 'Source' not in name and 'SysConfig' not in name:
                    raise ValueError
        message_name_to_class_map[name] = new_class
        return new_class
    _checked_attrs = ('prevent_caching', 'is_cacheable', 'prevent_exec')


class BaseMessage(object, metaclass=MetaMessage):
    '''
    Base class for all error and warning messages.

    Cannot be instantiated.
    '''
    def __init__(self, message: Optional[Union[str, List[str]]], is_refed: bool=False):
        if not hasattr(self, 'category'):
            raise NotImplementedError
        if isinstance(message, str):
            message = util.splitlines_lf(message)
        self.message: Optional[List[str]] = message
        self.is_refed: bool = is_refed

    # General category to which message belongs.
    category: str
    # Whether this particular message is cacheable when caching is not
    # prevented.  Messages that are not cacheable must be regenerated each
    # time during document processing.  Messages that are cacheable typically
    # relate to (attempted) code execution.
    is_cacheable: bool
    # Whether this message prevents all caching of messages and code output.
    # For simplicity, errors that are detected before attempting code
    # execution prevent caching, since it is typically trivial to regenerate
    # such errors each time during document processing.  Errors that are due
    # to unmonitored factors like system configuration also prevent caching,
    # since the only way to determine if they have been resolved is to try
    # executing code again.
    prevent_caching: bool
    # Whether this message is severe enough to completely prevent any
    # subsequent code execution.
    prevent_exec: bool
    # Whether this message is simply a copy of information present in stderr.
    is_stderr: bool
    # Whether this message is a reference to another message.  For example, a
    # code chunk can have a stderr message that references a session-level
    # stderr message.
    is_ref: bool
    # Name of class as a string.  Used in caching.
    type: str
    # Name of class as string with spaces inserted.
    display_name: str

    def as_dict(self):
        return {
            'message': self.message,
            'is_refed': self.is_refed,
        }


class BaseError(BaseMessage):
    '''
    Base class for all error messages.
    '''

class SourceError(BaseError):
    '''
    Error in source, such as a typo or invalid value, that might affect code
    execution.
    '''
    category = 'source'
    is_cacheable = False
    prevent_caching = True
    prevent_exec = True

class CanExecSourceError(SourceError):
    '''
    Error in source, such as a typo or invalid value, that cannot affect code
    execution.
    '''
    prevent_caching = False
    prevent_exec = False

class RuntimeSourceError(BaseError):
    '''
    Error in source that can only be detected at runtime.

    For example, a code chunk with `complete=true` that is actually not
    complete.
    '''
    category = 'runtime_source'
    is_cacheable = True
    prevent_caching = False
    prevent_exec = True

class SysConfigError(BaseError):
    '''
    Error in system configuration.

    For example, attempting to use a Jupyter kernel without having
    `jupyter_client` installed, or trying to run a program that is not in
    PATH.

    This error is not cached since the system configuration is not monitored,
    so it might change by the next attempt and allow success.
    '''
    category: str = 'sys_config'
    is_cacheable = False
    prevent_caching = True
    prevent_exec = True

class ExecError(BaseError):
    '''
    Error during the compile, pre-run, run, or post-run stage of code
    execution.

    Typically, the message will consist of stderr for the run stage, and the
    combined stdout and stderr for other stages.
    '''
    def __init__(self, message: Optional[Union[str, List[str]]], *,
                 is_refed: bool=False, exit_code: Optional[int]=None):
        super().__init__(message, is_refed=is_refed)
        self.exit_code: Optional[int] = exit_code
    is_cacheable = True
    prevent_caching = False
    prevent_exec = True
    def as_dict(self):
        error_as_dict = super().as_dict()
        error_as_dict['exit_code'] = self.exit_code
        return error_as_dict

class CompileError(ExecError):
    category: str = 'compile'

class PreRunError(ExecError):
    category: str = 'pre-run'

class RunError(ExecError):
    category: str = 'run'

class StderrRunError(RunError):
    # Run error that is also present in stderr
    pass

class StderrRunErrorRef(RunError):
    # Reference from code chunk to session run error that is also present in
    # stderr
    pass

class RunConfigError(ExecError):
    category: str = 'run_config'

class PostRunError(ExecError):
    category: str = 'post-run'

class DecodeError(BaseError):
    '''
    Error in decoding code output.
    '''
    category: str = 'encoding'
    is_cacheable = True
    prevent_caching = False
    prevent_exec = True


class BaseWarning(BaseMessage):
    '''
    Base class for all warning messages.

    Warnings cannot be sufficiently severe to impact caching or code
    execution; only errors can do that.
    '''
    prevent_caching = False
    prevent_exec = False

class SourceWarning(BaseWarning):
    '''
    Warning about source.
    '''
    category: str = 'source'
    is_cacheable = False

class ExecWarning(BaseWarning):
    '''
    Warning during the compile, pre-run, run, or post-run stage of code
    execution.

    Typically, the message will consist of stderr for the run stage, and the
    combined stdout and stderr for other stages.
    '''

class RunWarning(ExecWarning):
    category: str = 'run'
    is_cacheable = True

class StderrRunWarning(RunWarning):
    # Run warning that is also present in stderr
    pass

class StderrRunWarningRef(RunWarning):
    # Reference from code chunk to session run warning that is also present in
    # stderr
    pass

class CodeStatus(object):
    '''
    Status of code belonging to a Session or Source.
    '''
    def __init__(self):
        # Attributes summarize the overall attributes of
        self.prevent_caching: bool = False
        self.prevent_exec: bool = False
        self.error_count: int = 0
        self.warning_count: int = 0
        self.has_stderr: bool = False
        self.has_non_stderr: bool = False

    @property
    def has_errors(self) -> bool:
        return self.error_count > 0

    @property
    def has_warnings(self) -> bool:
        return self.warning_count > 0


class MessageList(list):
    '''
    Base class for list of Message objects that also tracks some properties of
    the collection.

    Cannot be instantiated.
    '''
    def __init__(self, *, status=None):
        if not hasattr(self, '_contents_base_class'):
            raise NotImplementedError
        # Attributes summarize the attributes of objects in list
        self.prevent_caching: bool = False
        self.prevent_exec: bool = False
        self.has_stderr: bool = False
        self.has_non_stderr: bool = False
        self._refed_list_ids: set[int] = set()
        self._list_id_to_msg: dict[int, BaseMessage] = {}

        self._status: Optional[CodeStatus] = status
        super().__init__()

    _contents_base_class: Union[Type[BaseError], Type[BaseWarning]]

    def append(self, msg: BaseMessage):
        # Prevent accidental mixing of error and warning objects
        if not isinstance(msg, self._contents_base_class):
            raise TypeError
        # Message list ids should be unique.  It may be worth adding a check
        # for duplicates at some point, depending on the final implementation
        # of stderr sync, etc.
        self._list_id_to_msg[id(msg.message)] = msg
        if not self.prevent_caching:
            self.prevent_caching = msg.prevent_caching
        if not self.prevent_exec:
            self.prevent_exec = msg.prevent_exec
        if not self.has_stderr:
            self.has_stderr = msg.is_stderr
        if not self.has_non_stderr:
            self.has_non_stderr = not msg.is_stderr
        if self._status is not None:
            if not self._status.prevent_caching:
                self._status.prevent_caching = msg.prevent_caching
            if not self._status.prevent_exec:
                self._status.prevent_exec = msg.prevent_exec
            if not self._status.has_stderr:
                self._status.has_stderr = msg.is_stderr
            if not self._status.has_non_stderr:
                self._status.has_non_stderr = not msg.is_stderr
        super().append(msg)

    def extend(self, msgs: List[BaseMessage]):
        for msg in msgs:
            self.append(msg)

    def register_status(self, status: CodeStatus):
        '''
        Update `status` if there are already messages, and set `_status` for
        future updating.
        '''
        if self._status is not None:
            raise RuntimeError
        if self:
            if self._contents_base_class is BaseError:
                for msg in self:
                    if not msg.is_ref:
                        status.error_count += 1
            elif self._contents_base_class is BaseWarning:
                for msg in self:
                    if not msg.is_ref:
                        status.warning_count += 1
            else:
                raise TypeError
            if not status.prevent_caching:
                status.prevent_caching = self.prevent_caching
            if not status.prevent_exec:
                status.prevent_exec = self.prevent_exec
        self._status = status

    def update_refed(self, message_list):
        self._list_id_to_msg[id(message_list)].is_refed = True

    def has_ref(self, message_or_message_list: BaseMessage | list[str]):
        if isinstance(message_or_message_list, list):
            return id(message_or_message_list) in self._list_id_to_msg
        if isinstance(message_or_message_list, BaseMessage):
            return id(message_or_message_list.message) in self._list_id_to_msg
        raise TypeError

class ErrorMessageList(MessageList):
    _contents_base_class = BaseError
    def append(self, msg: BaseError):
        if self._status is not None and not msg.is_ref:
            self._status.error_count += 1
        super().append(msg)

class WarningMessageList(MessageList):
    _contents_base_class = BaseWarning
    def append(self, msg: BaseWarning):
        if self._status is not None and not msg.is_ref:
            self._status.warning_count += 1
        super().append(msg)
