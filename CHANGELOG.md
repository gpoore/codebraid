# Change Log

## v0.5.0 (dev)

* `codebraid` now reads from `stdin` (#33).
* Added preliminary support for the Python REPL (`python_repl`) via Python's
  `code` module.  Added `cb.repl` command.
* Synchronization of code with source line numbers is now simpler and more
  robust to prevent `StopIteration` errors (#36).
* Check for compatible Pandoc version now works correctly with Pandoc 2.10.
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
