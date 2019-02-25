# Change Log


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
