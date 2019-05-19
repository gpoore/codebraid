# Change Log

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
