# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2022, Geoffrey M. Poore
# All rights reserved.
#
# Licensed under the BSD 3-Clause License:
# http://opensource.org/licenses/BSD-3-Clause
#


from __future__ import annotations




class CodebraidError(Exception):
    pass


class SourceError(CodebraidError):
    '''
    Raise error related to a particular line in a particular source.
    '''
    def __init__(self, message, origin_name=None, origin_start_line_number=None):
        if origin_name is not None and origin_start_line_number is not None:
            message = 'In "{0}" near line {1}:\n  {2}'.format(origin_name, origin_start_line_number, message)
        elif origin_name is not None:
            message = 'In "{0}":\n  {1}'.format(origin_name, message)
        super().__init__(message)


class SourceTraceback(object):
    '''
    Store information about an issue at a particular line in a particular
    source so that an error or warning can be raised later or alternatively a
    full report can be assembled.  This is useful in reporting all errors and
    warnings related to a given source, rather than just reporting the first
    error and then stopping.
    '''
    def __init__(self, message, origin_name=None, origin_start_line_number=None):
        self.message = message
        self.origin_name = origin_name
        self.origin_start_line_number = origin_start_line_number
