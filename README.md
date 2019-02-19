# Codebraid – live code in Pandoc Markdown

Codebraid is a Python command-line program that enables executable code in
[Pandoc](http://pandoc.org/) Markdown documents.  Using Codebraid can be as
simple as adding a class to your code blocks, and then running `codebraid`
rather than `pandoc` to convert your document from Markdown to another format.
`codebraid` supports almost all of `pandoc`'s options and passes them to
`pandoc` internally.

Codebraid currently can run **Python 3.5+** and **Julia**.  Support for R,
Rust, and several other languages is nearly ready for release.

**Development:**  https://github.com/gpoore/codebraid

View example HTML output, or see the Markdown source or raw HTML:

  * [Python example](http://htmlpreview.github.com/?https://github.com/gpoore/codebraid/blob/master/examples/python.html)
    [[Pandoc Markdown source](https://github.com/gpoore/codebraid/blob/master/examples/python.cbmd)]
    [[raw HTML](https://github.com/gpoore/codebraid/blob/master/examples/python.html)]
  * [Julia example](http://htmlpreview.github.com/?https://github.com/gpoore/codebraid/blob/master/examples/julia.html)
    [[Pandoc Markdown source](https://github.com/gpoore/codebraid/blob/master/examples/julia.cbmd)]
    [[raw HTML](https://github.com/gpoore/codebraid/blob/master/examples/julia.html)]


## Simple example

Markdown source `test.md`:

``````markdown
```{.python .cb.run}
print('Hello from Python!')
print('$2^8 = {}$'.format(2**8))
```
``````

Run `codebraid` (to save the output, add something like `-o test_out.md`, and
add `--overwrite` if it already exists):

```shell
codebraid pandoc -f markdown -t markdown test.md
```

Output:

```markdown
Hello from Python! $2^8 = 256$
```

## Installation and requirements

**Installation:**  `pip3 install codebraid` or `pip install codebraid`

Manual installation:  `python3 setup.py install` (or on some Windows
installations and Arch Linux, `python setup.py install`)

**Requirements:**

  * [Pandoc](http://pandoc.org/) 2.4+
  * Python 3.5+ with `setuptools` and [`bespon`](https://bespon.org) 0.3
    (`bespon` installation is typically managed by `setup.py`)

By default, the `python3` executable will be used to execute code.  If it does
not exist, `python` will be tried to account for Windows and Arch Linux.
Future releases will allow specifying the executable on systems with multiple
Python 3 installations.


## Converting a document

Simply run `codebraid pandoc <normal pandoc options>`.  Note that
`--overwrite` is required for existing files.


## Caching

By default, code output is cached, and code is only re-executed when it is
modified.  The default cache location is a `_codebraid` directory in the
directory with your markdown document.  This can be modified using
`--cache-dir`.  Sharing a single cache location between multiple documents is
not yet supported.

If you are working with external data that changes, you should run `codebraid`
with `--no-cache` to prevent the cache from becoming out of sync with your
data.  Future releases will allow external dependencies to be specified so
that caching will work correctly in these situations.


## Code options

### Classes

Code is made executable by adding a Codebraid class to its
[Pandoc attributes](http://pandoc.org/MANUAL.html#fenced-code-blocks).
For example, `` `code`{.python}` `` becomes
`` `code`{.python .cb.run}` ``.

* `.cb.expr` — Evaluate an expression and interpret the result as Markdown.
  Only works with inline code.

* `.cb.run` — Run code and interpret any printed content (stdout) as Markdown.
  Also insert stderr verbatim (as code) if it exists.

* `.cb.nb` — Notebook mode.  For inline code, this is equivalent to
  `.cb.expr`.  For code blocks, this inserts the code verbatim, followed by
  the stdout verbatim.  If stderr exists, it is also inserted verbatim.

### Keyword arguments

Pandoc code attribute syntax allows keyword arguments of the form `key=value`,
with spaces (*not* commas) separating subsequent keys.  `value` can be
unquoted if it contains only letters and some symbols; otherwise, double
quotation marks `"value"` are required.  For example,
```
{.python key1=value1 key2=value2}
```
Codebraid adds support for additional keyword arguments.  In some cases,
multiple keywords can be used for the same option.  This is primarily for
Pandoc compatibility.

* `session`={string} — By default, all code for a given language is executed
  in a single, shared session so that data and variables persist between code
  chunks.  This allows code to be separated into multiple independent
  sessions.

* `hide`={`expr`, `code`, `stdout`, `stderr`, `all`} — Hide some or all of the
  elements that are displayed by default.  Elements can be combined.  For
  example, `hide=stdout+stderr`.  Note that `expr` only applies to `.cb.expr`
  or `.cb.nb` with inline code, since only these evaluate an expression.

* `show`={`expr`, `code`, `stdout`, `stderr`, `none`} — Override the elements
  that are displayed by default.  `expr` only applies to `.cb.expr` or
  `.cb.nb` with inline code, since only these evaluate an expression.
  Elements can be combined.  For example, `show=code+stdout`.  Each element
  displayed can optionally specify a format from `raw`, `verbatim`, or
  `verbatim_or_empty`.  For example, `show=code:verbatim+stdout:raw`.

    - `raw` means interpreted as Markdown.
    - `verbatim` produces inline code or a code block, depending on context.
      Nothing is produced if there is no content (for example, nothing in
      stdout.)
    - `verbatim_or_empty` produces inline code containing a single
      non-breaking space or a code block containing a single empty line in the
      event that there is no content.  It is useful when a placeholder is
      desired, or a visual confirmation that there is indeed no output.

  `expr` defaults to `raw` if a format is not specified.  All others default
  to `verbatim`.

* `line_numbers`/`numberLines`/`number-lines`/`number_lines`={`true`, `false`}
  — Number code lines in code blocks.

* `first_number`/`startFrom`/`start-from`/`start_from`={integer or `next`} —
  Specify the first line number for code when line numbers are displayed.
  `next` means continue from the last code in the current session.
