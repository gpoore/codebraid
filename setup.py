# -*- coding: utf-8 -*-
#
# Copyright (c) 2018, Geoffrey M. Poore
# All rights reserved.
#
# Licensed under the BSD 3-Clause License:
# http://opensource.org/licenses/BSD-3-Clause
#


import sys
if sys.version_info < (3, 6):
    sys.exit('Codebraid requires Python 3.6+')
import os
import pathlib


try:
    from setuptools import setup
    setup_package_dependent_keywords = dict(
        entry_points = {
            #'console_scripts': ['codebraid = codebraid.cmdline:main'],
        },
    )
except ImportError:
    from distutils.core import setup
    setup_package_dependent_keywords = dict(
        #scripts = ['bin/codebraid'],
    )


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
      packages=['codebraid'],
      description='Execute code embedded in markdown and LaTeX documents',
      long_description=long_description,
      long_description_content_type='text/markdown',
      author='Geoffrey M. Poore',
      author_email='gpoore@gmail.com',
      url='http://github.com/gpoore/codebraid',
      license='BSD',
      keywords=['dynamic documents', 'reproducible research',
                'markdown', 'pandoc', 'LaTeX', 'Jupyter'],
      python_requires='~=3.6',
      # https://pypi.python.org/pypi?:action=list_classifiers
      classifiers=[
          'Development Status :: 4 - Beta',
          'Environment :: Console',
          'Framework :: Jupyter',
          'Intended Audience :: Developers',
          'Intended Audience :: Education',
          'Intended Audience :: Science/Research',
          'License :: OSI Approved :: BSD License',
          'Operating System :: OS Independent',
          'Programming Language :: Python',
          'Programming Language :: Python :: 3 :: Only',
          'Programming Language :: Python :: 3.6',
          'Topic :: Documentation',
          'Topic :: Education',
          'Topic :: Software Development',
          'Topic :: Software Development :: Build Tools',
          'Topic :: Software Development :: Documentation',
          'Topic :: Text Processing',
          'Topic :: Text Processing :: Markup',
      ],
      **setup_package_dependent_keywords
)
