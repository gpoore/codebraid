---
title: Codebraid with GAP (Groups, Algorithms, Programming - a System
  for Computational Discrete Algebra)
---

## Inline code

### Run

Inline code with `.cb-run` gives raw stdout.

::: example
::: exampleMarkup
    `Print(1 + 2);`{.gap .cb-run session=firsttest}
:::

::: exampleOutput
3
:::
:::

### Expression and inline notebook

Inline code with `.cb-expr` evaluates an expression and then inserts the
raw output into the document, where it is interpreted as Markdown.
Inline code with `.cb-nb` (`nb` is short for `notebook`) is similar,
except output is shown verbatim. Notice that since these are
expressions, a trailing semicolon must not be used.

::: example
::: exampleMarkup
    `StringFormatted("*{}*", Sum([1..10]))`{.gap .cb-expr}
:::

::: exampleOutput
*55*
:::
:::

::: example
::: exampleMarkup
    `StringFormatted("*{}*", Sum([1..10]))`{.gap .cb-nb}
:::

::: exampleOutput
`*55*`{.expr}
:::
:::

### Stderr

In the event of an error, inline code automatically shows stderr by
default. This code is executed in its own session, `inline_error`, so
that it does not impact other examples.

::: example
::: exampleMarkup
    `1 + "a"`{.gap .cb-run session=inline_error}
:::

::: exampleOutput
`` Error, no method found! For debugging hints type ?Recovery from NoMethodFound Error, no 1st choice method found for `CallFuncList' on 2 arguments ``{.stderr
.error}
:::
:::

### Source errors

A message is also displayed for errors in the Markdown source. This
usually includes the name of the document source and the approximate
line number.

::: example
::: exampleMarkup
    `Print(1 + 2);`{.gp .cb-run session=inline_source_error}
:::

::: exampleOutput
`SYS CONFIG ERROR in "gap.cbmd" near line 43: Language definition for "gp" does not exist`{.error
.sysConfigError}
:::
:::

### Code

Inline code with `.cb-code` simply displays the code. Nothing is
executed.

::: example
::: exampleMarkup
    `Print("Hello from GAP!");`{.gap .cb-code}
:::

::: exampleOutput
`Print("Hello from GAP!");`{.gap}
:::
:::

The output is identical to that of

    `Print("Hello from GAP!");`{.gap}

so `.cb-code` is only really useful when it is combined with other
Codebraid features. For example, it is possible to give code with
`.cb-code` a `name`, and then copy it by `name` into a separate location
where it is executed. See [Copying code and output](#copying).

## Block code

### Run

Code blocks with `.cb-run` give raw stdout. There is continuity between
code blocks so long as they are in the same session; variables persist.

::: example
::: exampleMarkup
    ```{.gap .cb-run session=hello}
    x := "Hello from *GAP!*";
    ```
:::
:::

::: example
::: exampleMarkup
    ```{.gap .cb-run session=hello}
    Print(x);
    ```
:::

::: exampleOutput
Hello from *GAP!*
:::
:::

### Stderr

Code blocks show stderr automatically by default.

::: example
::: exampleMarkup
    ```{.gap .cb-nb session=block_error}
    x := 12;
    y := x + "x";
    ```
:::

::: exampleOutput
``` {.gap .numberLines startFrom="1"}
x := 12;
y := x + "x";
```

``` {.stderr .error}
Error, no method found! For debugging hints type ?Recovery from NoMethodFound
Error, no 1st choice method found for `+' on 2 arguments
```
:::
:::

### Source errors

A message is also displayed for errors in the Markdown source. This
usually includes the name of the document source and the approximate
line number.

::: example
::: exampleMarkup
    ```{.gap .cb-ruuun session=block_source_error}
    print(1 + 2);
    ```
:::

::: exampleOutput
``` {.error .sourceError}
SOURCE ERROR in "gap.cbmd" near line 96:
Unknown or unsupported Codebraid command "cb-ruuun"

SOURCE ERROR in "gap.cbmd" near line 96:
Missing valid Codebraid command
```
:::
:::

### Code

Code blocks with `.cb-code` simply display the code. Nothing is
executed.

::: example
::: exampleMarkup
    ```{.gap .cb-code}
    Print("Hello from GAP!");
    ```
:::

::: exampleOutput
``` {.gap .numberLines startFrom="1"}
Print("Hello from GAP!");
```
:::
:::

The output is essentially identical to that of a normal code block; the
only differences are some default display options, like line numbering.
Thus `.cb-code` is primarily useful when it is combined with other
Codebraid features. For example, it is possible to give code with
`.cb-code` a `name`, and then copy it by `name` into a separate location
where it is executed. See [Copying code and output](#copying).

## Other options

By default, stdout and stderr are only shown if they are non-empty. In
some situations, it may be useful to represent empty output visually as
confirmation that there indeed was none.

::: example
::: exampleMarkup
    ```{.gap .cb-run show=code+stdout+stderr:verbatim_or_empty}
    x := 1 + 2;;
    ```
:::

::: exampleOutput
``` {.gap .numberLines startFrom="1"}
x := 1 + 2;;
```

``` stderr
 
```
:::
:::

It is also possible to selectively hide output from a code chunk.

::: example
::: exampleMarkup
    ```{.gap .cb-nb hide=stdout}
    Print(x);
    ```
:::

::: exampleOutput
``` {.gap .numberLines startFrom="2"}
Print(x);
```
:::
:::

`hide` takes any combination of `code`, `stderr`, and `stdout`, or
simply `all`.

## Advanced features {#advanced}

### Copying code and output {#copying}

Code chunks can be named using the `name` keyword, which takes an
identifier-style name. Then the `copy` keyword can be used in other code
chunks to copy a named chunk or a combination of named chunks. When
`copy` is used with `cb-run`, `cb-expr`, or `cb-nb`, the code is copied
and then executed as if it had been entered directly. When `copy` is
used with `cb-code`, the code is copied and displayed, but nothing is
executed. When `copy` is used with the special command `cb-paste`, both
the code and output are copied but nothing is executed. This is useful
in executing code and then showing snippets of the code and/or output in
different parts of a document.

`copy` works with named code chunks anywhere in a document; a named code
chunk does not have to appear in a document before the location where it
is copied. A code chunk that copies another code chunk can itself have a
`name`, and then itself be copied.

The next two code chunks are named.

::: example
::: exampleMarkup
    ```{.gap .cb-run name=part1 session=copy_source}
    rnums := List([1..10], x -> Random([1..x]));;
    ```
:::
:::

::: example
::: exampleMarkup
    ```{.gap .cb-run name=part2 session=copy_source}
    PrintFormatted("Random numbers: {}", rnums);
    ```
:::

::: exampleOutput
Random numbers: \[ 1, 2, 1, 3, 3, 2, 3, 3, 5, 5 \]
:::
:::

Now the code and output of the previous two code chunks are copied and
combined. Because the content for this code block is copied from other
code chunks, the code block itself should be empty, or may alternately
contain a space or underscore as a placeholder.

::: example
::: exampleMarkup
    ```{.gap .cb-paste copy=part1+part2 show=code+stdout}
    ```
:::

::: exampleOutput
``` {.gap .numberLines startFrom="1"}
rnums := List([1..10], x -> Random([1..x]));;
PrintFormatted("Random numbers: {}", rnums);
```

``` stdout
Random numbers: [ 1, 2, 1, 3, 3, 2, 3, 3, 5, 5 ]
```
:::
:::

It would also be possible to copy and re-execute the code.

::: example
::: exampleMarkup
    ```{.gap .cb-run copy=part1+part2 session=copied show=code+stdout:raw}
    ```
:::

::: exampleOutput
``` {.gap .numberLines startFrom="1"}
rnums := List([1..10], x -> Random([1..x]));;
PrintFormatted("Random numbers: {}", rnums);
```

Random numbers: \[ 1, 2, 1, 3, 3, 2, 3, 3, 5, 5 \]
:::
:::

Another option is to display code, and then copy and execute it later.

::: example
::: exampleMarkup
    ```{.gap .cb-code name=hello}
    Print("Hello from GAP!");
    ```
:::

::: exampleOutput
``` {.gap .numberLines startFrom="1"}
Print("Hello from GAP!");
```
:::
:::

::: example
::: exampleMarkup
    ```{.gap .cb-nb copy=hello}
    ```
:::

::: exampleOutput
``` {.gap .numberLines startFrom="3"}
Print("Hello from GAP!");
```

``` stdout
Hello from GAP!
```
:::
:::

### Including external files

External files can be included for display or execution using
`include_file`. The default encoding is UTF-8; other encodings can be
selected with `include_encoding`. Instead of including the entire file,
it is possible to include only a selected range of lines with
`include_lines`. It is also possible to include part of a file that
matches a regular expression with `include_regex`, as shown in the
example. Other options for controlling what is included based on
starting or ending literal strings or regular expressions can be found
in the documentation.

::: example
::: exampleMarkup
    ```{.html .cb-code include_file=gap.html include_regex="<header.*?/header>"}
    ```
:::

::: exampleOutput
``` {.html .numberLines startFrom="1"}
<header id="title-block-header">
<h1 class="title">Codebraid with GAP (Groups, Algorithms, Programming -
a System for Computational Discrete Algebra)</h1>
</header>
```
:::
:::

When `include_file` is used with `cb-code`, the included code is simply
displayed. When `include_file` is used with `cb-run` or another command
that executes code, the included code is executed just as if it had been
entered directly.
