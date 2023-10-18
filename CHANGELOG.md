# Change Log


# v0.11.0 (2023-10-17)

* Added support for Pandoc option `--embed-resources`.

* Python 3.11 compatibility:  set `PYDEVD_DISABLE_FILE_VALIDATION=1` at
  beginning of command-line application to prevent debugger frozen modules
  warning.

* Switched packaging to `pyproject.toml`.

* Added support for [GAP](https://www.gap-system.org/) (#51).



# v0.10.3 (2023-01-19)

* Fixed bug in Pandoc version checking for Pandoc 3.0 compatibility.



# v0.10.2 (2022-08-30)

* Sessions that result in errors are now re-executed during subsequent builds
  regardless of whether the session code is modified.  Previously,
  re-execution was only triggered by code modification.  This addresses
  situations such as import errors due to missing libraries (#57).

* Markup and code can now be displayed `raw`.  Previously, only `verbatim` was
  permitted.

* Fixed a bug that caused Jupyter kernels to be used if there were any
  Jupyter settings in the YAML metadata, including `jupyter: false`.



# v0.10.1 (2022-07-11)

* Fixed a bug that prevented multi-file documents from working with input
  formats other than Pandoc's Markdown (`markdown`).



# v0.10.0 (2022-07-11)

* Added support for specifying document-wide settings in the YAML metadata.
  Codebraid settings must be under either a `codebraid` or `codebraid_` key in
  the metadata.  Pandoc will ignore `codebraid_` so it will not be available
  to filters; this distinction should not typically be important.

  To use Jupyter kernels automatically for all sessions, simply set
  `jupyter: true`.  For example,

  ```
  ---
  codebraid:
    jupyter: true
  ---
  ```

  It is also possible to set a default kernel and/or default timeout.  For example,

  ```
  ---
  codebraid:
    jupyter:
      kernel: python3
      timeout: 120
  ---
  ```

  A Jupyter kernel and/or timeout can still be set in the first code chunk
  for a given session, and will override the document-wide default.

  It is also possible to set `live_output: <bool>` in the metadata.
  Additional metadata settings will be added in future releases.

* When a selected Jupyter kernel is ambiguous (for example, `python` on a
  machine with multiple Python kernels), there is no longer an error message
  by default.  Instead, if all potential matches have kernel names that
  include a version number, and if only a single kernel has a version number
  higher than the rest, then the kernel with the highest version number is
  used.  Only version numbers of the form `major`, `major.minor`, and
  `major.minor.patch` are considered in doing the comparison.  Any
  alpha/beta/dev or similar status is ignored.

* Fixed an encoding bug that prevented `svg` rich output from being displayed.
  Added `svg` to the collection of rich output formats that are automatically displayed (#53).

* stdout and stderr from Jupyter kernel processes are no longer included in
  Codebraid's stdout and stderr.  Some kernels such as IJulia write messages
  to output streams during startup.  This was causing error messages in
  Codebraid Preview and incorrect documents when Codebraid outputs to stdout.

* Fixed a bug that prevented Jupyter kernels from being used when the kernel
  name, kernel display name, and kernel language were not all different from
  each other.

* Setting `jupyter_timeout` without `jupyter_kernel` on the first code chunk
  in a session now causes the session to execute with the default kernel for
  the session's language.  Previously, `jupyter_timeout` was ignored without
  `jupyter_kernel`.

* Sessions that do not specify execution information (language, executable,
  Jupyter kernel, etc.) now result in an error message rather than causing
  `codebraid` to exit with an error.

* Fixed `--only-code-output` bugs that affected Codebraid Preview.
  `.cb-paste` did not work due to a hashing bug.  LaTeX rich output appeared
  verbatim instead of being interpreted.  Verbatim textual rich output did not
  have the correct language class.  Code chunks with a missing language or
  inherited language could have incorrect output when interspersed.

* Code chunks with a named session but an invalid command are now treated as
  session rather than source chunks.  This provides better error messages and
  prevents execution of the named session since it involves errors.

* Code chunks in sessions and sources with significant errors are now given
  consecutive line numbers, instead of all starting with a line number of 1.



## v0.9.0 (2022-06-25)

* Added option `--stdin-json-header`, which treats the first line of stdin as
  a header in JSON format containing data about stdin such as file origin.
  This allows Codebraid Preview to transmit multiple, concatenated files via
  stdin while still getting correct file names and line numbers in error and
  warning messages, rather than a file name like `<string>` and a number based
  on concatenated file length.  It also allows Codebraid Preview and normal
  Codebraid processing to share the same cache, since Codebraid can associate
  the cache with specific file paths rather than just generic stdin.

* Fixed a caching bug.  Errors due to missing executables (built-in code
  execution system), missing Jupyter kernels, ambiguous Jupyter kernel names,
  and some Jupyter configuration issues were only reported during an initial
  Codebraid run.  During subsequent runs with unmodified code and settings,
  errors were not reported and there was no attempt to re-execute sessions to
  check for newly available executables/Jupyter kernels/libraries.

* When a Jupyter kernel name is ambiguous (for example, `python` on a machine
  with multiple Python kernels), the error message now lists all potentially
  compatible kernels instead of just stating that a kernel could not be found.

* Improved `--only-code-output`.  It now sends an `index` message that lists
  all code collections being processed and includes information about language
  inheritance through `copy`.  Code chunk `output` messages now include
  execution progress information for chunks being executed.  Fixed a bug that
  could cause a `KeyError` for some sessions containing only a single code
  chunk.  Fixed a bug that caused the first code chunk in a code collection to
  be resent unnecessarily at the end of code collection processing.

* Refactored line number calculations.  Fixed a bug that could produce
  incorrect line numbers for code from `copy`.  Fixed a bug with
  `--only-code-output` that duplicated line number settings for the first code
  chunk in a code collection when checking the code chunk for modifications at
  the end of code collection processing.

* Fixed a bug that skipped progress notifications for sessions with errors
  that prevent code execution.  This prevented `--only-code-output` from
  sending information about these sessions and prevented summaries with
  `--live-output`.

* Fixed a bug that prevented a progress notification for session completion
  with the built-in code execution system.

* Improved progress tracking for sources.



## v0.8.0 (2022-06-11)

* Improved process for setting the default Python executable used by the
  built-in code execution system.  For `.python` code chunks in a session that
  does not set `executable` to a custom value, Python's `sys.executable` is
  now used as the default Python executable if it is set and if it is
  equivalent to either `python` or `python3` on PATH.  This will typically
  guarantee that the Python interpreter running `codebraid` is identical to
  the default for built-in code execution.  The default Python executable is
  now set using an absolute path when possible, to avoid name resolution
  issues under Windows with Python environments.

* Fixed a bug that stripped a trailing empty line from code blocks.

* Fixed a bug that caused an incorrect `attr_hash` in `--only-code-output`
  when a code chunk has key-value attributes.



## v0.7.0 (2022-06-04)

* Added `--only-code-output` option, which writes code output in JSON Lines
  format to stdout as soon as it is available, and does not create a document.
  This is intended for use with Codebraid Preview, so that document previews
  can be updated during code execution.

* Added command-line option `--no-execute` that disables code execution and
  only uses available cached output.

* Added first-chunk setting `executable_opts` for passing command-line options
  to the executable that compiles/runs code (#52).

* Setting `executable` to an executable relative to the working directory (for
  example, `./exec.sh`) now functions correctly.  Previously, `pathlib.Path()`
  was used to track executables, but it strips a leading `./`.

* Added first-chunk setting `args` for passing command-line arguments to
  executed code.



## v0.6.0 (2022-02-22)

* Python 3.7 is now the minimum supported version.

* Added support for Codebraid Preview extension for VS Code, which provides an
  HTML preview with scroll sync and document export (#37).  As part of this,
  added support for Pandoc's `commonmark_x` as an input format.
  `commonmark_x` is CommonMark Markdown plus Pandoc extensions that give it
  most of the capabilities of Pandoc Markdown.  `commonmark_x` does not
  support the full Pandoc Markdown syntax for classes, so it requires
  Codebraid commands in the form `.cb-<command>` instead of `.cb.<command>`
  (for example, `.cb-run` instead of `.cb.run`).  `.cb-<command>` is now
  supported for Pandoc Markdown as well and should be preferred going forward
  for maximum compatibility across Pandoc variants of Markdown.
  `.cb.<command>` continues to be supported for Pandoc Markdown.

* Added fine-grained progress tracking and display of progress.  When
  `codebraid` runs in a terminal, there is now a color-coded summary of errors
  and warnings plus a progress bar.  In a terminal, `live_output` now displays
  color-coded output from executed code in real time, including a summary of
  rich output.  `live_output` now displays a summary of errors and warnings
  for all output loaded from cache.

  `live_output` is now compatible with Jupyter kernels (#21).

  Added command-line option `--live-output`.  This changes the default
  `live_output` value for all sessions to `true` (#21).

* Completely reimplemented error and warning handling to support new
  `live_output` features and to provide better display of errors and stderr
  within documents.  All errors and warnings related to code execution are now
  cached.

  At the end of document build, `codebraid` now exits with a non-zero exit
  code if there are errors or warnings (#24).  This is triggered by using
  invalid settings or by executing code that causes errors or warnings.  It is
  also triggered by loading cached output from code that caused errors or
  warnings when it was originally executed (error and warning state is
  cached).  Exit codes are between 4 and 60 inclusive.  The bits in the exit
  code are assigned value as follow:
  ```
  0b00<doc_warn><exec_warn><doc_error><exec_error>00
  ```
  Nonzero values for `<doc_warn>` and `<exec_warn>` indicate the presence of
  warnings from document build and from code execution, respectively.
  `<doc_error>` represents an error in document build that was not so severe
  that build was canceled with exit code 1, such as invalid settings related
  to displaying code output.  `<exec_error>` represents an error from code
  execution.  An exit code of 1 still indicates that `codebraid` itself exited
  unexpectedly or otherwise failed to complete document build.

* Reimplemented built-in code execution system and Jupyter kernel support as
  async.  This makes possible new progress tracking and `live_output`
  features.

  The built-in code execution system now provides more robust error handling
  and error synchronization.

  Jupyter kernels now require `jupyter_client` >= 6.1.0 for async
  functionality.  Version 6.1.12 or 7.1+ is recommended.  The new async
  Jupyter support should resolve errors with `jupyter_client` > 6.1.12 (#46).

* When setting `jupyter_kernel` for a session, lowercased kernel display names
  and kernel language names are now used as aliases in finding the correct
  kernel.  Aliases are used only when they have a single possible
  interpretation given the kernels installed.  For example, `python` can be
  used to select the `python3` kernel if no `python2` kernel is installed.

* Pandoc command-line options `--katex`, `--mathjax`, and `--webtex` now work
  correctly with an optional URL.  For example, for `--katex` Pandoc allows
  `--katex[=URL]`.

* Caching is now more robust to crashes or program interruption.  The output
  for each session is now cached immediately after execution, rather than waiting until all sessions have finished.

* Synchronization of code with source line numbers uses a new algorithm that
  eliminates sync failure in the form of `StopIteration` errors (#36, #38,
  #44).  Synchronization will now be faster and will not raise errors, but
  may also be less accurate occasionally.

* In stderr output, the user home directory is now sanitized to `~`.  This is
  also done in error messages from Jupyter kernels.

* Updated installation requirements: `bespon` version 0.6.



## v0.5.0 (2021-02-28)

* The built-in code execution system now uses PATH to locate executables under
  Windows.  Previously PATH was ignored under Windows due to the
  implementation details of Python's `subprocess.Popen()` (#41).

* Added support for Pandoc command-line options `-C` and `--citeproc` (#42).

* `rich_output` formats with a `text/*` mime type can now be displayed `raw`,
  `verbatim`, or `verbatim_or_empty`.  For example,
  `show=rich_output:latex:raw` and `show=rich_output:latex:verbatim`.

* When a code chunk produces multiple outputs, it is now impossible for these
  to accidentally merge into a single output that does not represent the
  intended Markdown.  Raw output no longer merges with adjacent output.
  Adjacent inline code outputs no longer merge into a single, potentially
  invalid, code output.

* Most example documents now come with both HTML and Markdown output.  This is
  convenient for seeing how a Markdown-to-Markdown conversion process works.
  It also significantly simplifies Codebraid testing for new releases, which
  uses the example documents.  The HTML output changes whenever Pandoc updates
  its HTML templates.  Markdown output should be much more stable.

* `codebraid` now reads from stdin (#33).

* Added preliminary support for the Python REPL (`python_repl`) via Python's
  `code` module.  Added `cb.repl` command.

* Synchronization of code with source line numbers is now simpler and more
  robust to prevent `StopIteration` errors (#36).

* Check for compatible Pandoc version now works correctly with Pandoc 2.10+.

* Added `live_output` option for the first code chunk in a session.  This
  shows code output (stdout and stderr) live in the terminal during code
  execution (#21).

* "Includes" are now skipped during internal, intermediate file
  transformations, which prevents duplicated "includes" and associated errors
  (#20).  This applies to `header-includes`, `include-before`,
  `include-after`, `--include-in-header`, `--include-before-body`, and
  `--include-after-body`.  Roundtrip conversion from Pandoc Markdown to Pandoc
  Markdown now skips all "includes" and also ignores `toc`/`table-of-contents`
  and `--toc`/`--table-of-contents`.  This allows Codebraid to be used as a
  preprocessor and saves YAML metadata settings for a subsequent conversion
  from Pandoc Markdown to another format.

* Added option `jupyter_timeout` for the first code chunk in a session (#30).

* Fixed Pandoc 2.8+ compatibility by using `-raw_attribute` in intermediate
  Markdown.  Code output in raw format (interpreted as Markdown) is no longer
  lost when converting to document formats other than Markdown (#26).

* Added support for SageMath (#5).

* All document transformations now use `--preserve-tabs`, so code indentation
  is maintained without change and tabs no longer cause errors in syncing code
  to input line numbers (#18).

* Added support for remaining unsupported Pandoc command-line options,
  including `--defaults` (#14).

* Julia now uses `--project=@.` (#10).

* Documentation now includes details of code execution and how this can result
  in different output compared to interactive sessions (#11).

* AST walking code no longer assumes that all dict nodes represent types and
  have a "t" (type) key.  Dict nodes without a "t" key are now skipped.  This
  fixes a bug with citations of the form `[@cite]` (#12).



## v0.4.0 (2019-07-10)

* Added support for Jupyter kernels with the `jupyter_kernel` option, which
  can be used with the first code chunk in a session to specify a kernel.
  Multiple Jupyter kernels can be used within a single document, and multiple
  sessions are possible per kernel.  Added associated `rich_output` display
  options.  Rich output such as plots is displayed automatically.

* A single cache location can now be shared by multiple documents.  When
  multiple documents are built in a single directory with the default cache
  settings, they no longer remove each other's cached output.

* Inline `cb.nb` is no longer the same as `cb.expr`.  Inline `cb.nb` now shows
  output verbatim when used with Codebraid's built-in code execution system,
  and shows rich output or a verbatim text representation when used with
  Jupyter kernels.  This makes inline and block `cb.nb` behavior more
  parallel.

* Added `executable` option, which can be used with the first code chunk in a
  session.  This overrides the default executable called by the built-in code
  execution system.

* Added `include_file` and associated options.  This allows code from an
  external file to be included for execution and/or display.

* Added JavaScript support.

* Pandoc options like `--syntax-definition` can now be used multiple times.

* Fixed a bug that prevented `--webtex`, `--mathjax`, and `--katex` from
  working with Pandoc.  They now work when a URL is not specified, but do not
  yet work when a URL is given.

* When a `paste` code chunk is copied, now everything is copied, not just what
  is actually displayed by the `paste` chunk.  Improved and simplified copying
  logic.

* Added `copied_markup` option for `show` and `hide`.  This is used with
  `copy` to show the Markdown source of copied code chunks.

* Added keyword argument `hide_markup_keys` for code chunks.  This allows
  specified keys in code chunk attributes to be hidden in the Markdown source
  displayed with `markup` and `copied_markup`.

* Code chunk options `line_anchors` and `line_numbers` are now properly
  converted to boolean values.

* Improved option processing.



## v0.3.0 (2019-05-19)

* Added Bash support.

* Added `cb.code` command that simply displays code and executes nothing.

* Added `cb.paste` command that allows code and/or output to be copied from
  other code chunks.

* Added `markup` option for `show` and `hide`.  This displays the Markdown
  source for inline code or a code block.

* Added support for naming code chunks with the `name` keyword.  Added support
  for copying named code chunks into other code chunks with the `copy`
  keyword.

* Runtime source errors (code is improperly divided into code chunks, such as
  `complete=true` when it is not) are now handled like any other source
  errors, rather than as a special instance of stderr.  As part of this, the
  errors now have their own entry in the cache.

* `FileNotFoundError` for subprocesses now returns `FailedProcess` with
  correct attribute values.

* Fixed compatibility with languages that do not define an inline expression
  formatter.

* Fixed stderr syncing bug for languages that have multiple line number
  patterns.

* Fixed compatibility with Pandoc commands in which output format is inferred
  from output file name.  Better output when `codebraid` is run with no
  arguments (#3).

* Code that interferes with Codebraid's templates is now detected and results
  in error messages.

* Session names are now restricted to identifier-style strings.

* In language definitions, field `tempsuffix` is renamed to `temp_suffix`.

* Raw output from code blocks no longer merges with a following paragraph or
  other block.

* Improved newline handling.  All text is processed in universal newlines
  mode. Only `\n` is treated as a newline for line splitting.  This avoids
  edge cases from `str.splitlines()`.

* `outside_main` is now properly checked for compatibility with other options.

* More efficient AST processing.



## v0.2.0 (2019-02-25)

* Added Julia, Rust, and R support.

* Added boolean keyword argument `complete` for code chunks.  This allows code
  chunks that contain incomplete units of code, such as part of a function
  definition or part of a loop.  Any stdout from a chunk with `complete=false`
  will appear with the next chunk with `complete=true` (the default value).

* Session hashes are now more robust by including session names and chunk
  `complete` status.  This prevents the collision of sessions with identical
  code but different processing for code output.

* Added boolean keyword argument `example` for code chunks.  This displays the
  Markdown source along with the output, putting both inside a single div with
  class `example` and putting them individually in divs with classes
  `exampleMarkup` and `exampleOutput`, respectively.

* Added boolean keyword argument `outside_main` for code chunks.  Code chunks
  with `outside_main=true` at the beginning of a session will overwrite the
  beginning of the Codebraid source template, while code chunks with
  `outside_main=true` at the end of a session will overwrite the end of the
  source template.  This is primarily for compiled languages like Rust, so
  that the implicit `main()` function defined in the default source template
  can be overwritten.

* In language definitions, `source_start` and `source_end` are now combined
  into a single `source_template`.  Delimiter fields are renamed to
  `stdout_delim` and `stderr_delim` (added underscore to parallel future,
  optional delimiters).

* There is no longer any attempt to sync `RawInline` HTML precisely with the
  document source, since this can fail in some cases with HTML comments.
  `RawBlock` HTML was already not synced precisely due to similar issues.

* More robust stdout and stderr parsing.



## v0.1.0 (2019-02-15)

* Initial release.
