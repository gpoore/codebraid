# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019, Geoffrey M. Poore
# All rights reserved.
#
# Licensed under the BSD 3-Clause License:
# http://opensource.org/licenses/BSD-3-Clause
#


class CodebraidError(Exception):
    pass


class SourceError(CodebraidError):
    def __init__(self, message, source_name=None, start_line_number=None):
        if source_name is not None and start_line_number is not None:
            message = 'In "{0}" near line {1}:\n  {2}'.format(source_name, start_line_number, message)
        elif source_name is not None:
            message = 'In "{0}":\n  {1}'.format(source_name, message)
        super.__init__(message)
