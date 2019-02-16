# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019, Geoffrey M. Poore
# All rights reserved.
#
# Licensed under the BSD 3-Clause License:
# http://opensource.org/licenses/BSD-3-Clause
#


import sys
if sys.version_info < (3, 5):
    sys.exit('Codebraid requires Python 3.5+')
import os
import pathlib
from setuptools import setup




# Extract the version from version.py, using functions in fmtversion.py
fmtversion_path = pathlib.Path(__file__).parent / 'codebraid' / 'fmtversion.py'
exec(compile(fmtversion_path.read_text(encoding='utf8'), 'codebraid/fmtversion.py', 'exec'))
version_path = pathlib.Path(__file__).parent / 'codebraid' / 'version.py'
version = get_version_from_version_py_str(version_path.read_text(encoding='utf8'))

readme_path = pathlib.Path(__file__).parent / 'README.md'
long_description = readme_path.read_text(encoding='utf8')


setup(name='codebraid',
      version=version,
      py_modules=[],
      packages=[
          'codebraid',
          'codebraid.converters',
          'codebraid.codeprocessors'
      ],
      package_data = {
          'codebraid': ['languages/*.bespon']
      },
      description='Live code in Pandoc Markdown',
      long_description=long_description,
      long_description_content_type='text/markdown',
      author='Geoffrey M. Poore',
      author_email='gpoore@gmail.com',
      url='http://github.com/gpoore/codebraid',
      license='BSD',
      keywords=['dynamic documents', 'reproducible research', 'notebook',
                'markdown', 'pandoc', 'LaTeX'],
      python_requires='>=3.5',
      install_requires=[
          'bespon>=0.3',
      ],
      # https://pypi.python.org/pypi?:action=list_classifiers
      classifiers=[
          'Development Status :: 4 - Beta',
          'Environment :: Console',
          'Intended Audience :: Developers',
          'Intended Audience :: Education',
          'Intended Audience :: Science/Research',
          'License :: OSI Approved :: BSD License',
          'Operating System :: OS Independent',
          'Programming Language :: Python :: 3.5',
          'Programming Language :: Python :: 3.6',
          'Programming Language :: Python :: 3.7',
          'Topic :: Documentation',
          'Topic :: Education',
          'Topic :: Software Development',
          'Topic :: Software Development :: Build Tools',
          'Topic :: Software Development :: Documentation',
          'Topic :: Text Processing',
          'Topic :: Text Processing :: Markup',
      ],
      entry_points = {
          'console_scripts': ['codebraid = codebraid.cmdline:main'],
      },
)
