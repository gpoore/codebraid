# -*- coding: utf-8 -*-
#
# Copyright (c) 2019, Geoffrey M. Poore
# All rights reserved.
#
# Licensed under the BSD 3-Clause License:
# http://opensource.org/licenses/BSD-3-Clause
#


import collections
import random




class KeyDefaultDict(collections.defaultdict):
    '''
    Default dict that passes missing keys to the factory function, rather than
    calling the factory function with no arguments.
    '''
    def __missing__(self, key):
        if self.default_factory is None:
            raise KeyError(key)
        else:
            self[key] = self.default_factory(key)
            return self[key]


def random_ascii_lower_alpha(n):
    '''
    Create a random string of length n consisting of lowercase ASCII
    letters.  Useful for creating more robust tempfile names when working in
    `tempfile.TemporaryDirectory()`.
    '''
    return ''.join(chr(num) for num in (random.randrange(97, 122+1) for _ in range(n)))


def splitlines_lf(string):
    r'''
    Like `str.splitlines()`, but only splits on `\n`.  This should be used
    on strings that have had `\r\n?` normalized to `\n`.  It avoids the
    `str.splitlines()` behavior of splitting on additional code points
    like `\v` and `\f`.
    '''
    lines = string.split('\n')
    if string == '' or string[-1] == '\n':
        lines.pop()
    return lines
