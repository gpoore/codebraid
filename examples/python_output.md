---
title: Codebraid with Python
---

## Inline code

### Run

Inline code with `.cb-run` gives raw stdout.

::: example
::: exampleMarkup
    `print(1 + 2)`{.python .cb-run}
:::

::: exampleOutput
3
:::
:::

### Expression and inline notebook

Inline code with `.cb-expr` evaluates an expression and then inserts the
raw output into the document, where it is interpreted as Markdown.
Inline code with `.cb-nb` (`nb` is short for `notebook`) is similar,
except output is shown verbatim.

::: example
::: exampleMarkup
    `"...".join(["*emphasis*", "**strong**", "~~strikeout~~"])`{.python .cb-expr}
:::

::: exampleOutput
*emphasis*...**strong**...~~strikeout~~
:::
:::

::: example
::: exampleMarkup
    `"$2^8 = {}$".format(2**8)`{.python .cb-nb}
:::

::: exampleOutput
`$2^8 = 256$`{.expr}
:::
:::

### Stderr

In the event of an error, inline code automatically shows stderr by
default. This code is executed in its own session, `inline_error`, so
that it does not impact other examples.

::: example
::: exampleMarkup
    `1 + "a"`{.python .cb-run session=inline_error}
:::

::: exampleOutput
`Traceback (most recent call last):   File "<string>", line 1, in <module>     1 + "a"     ~~^~~~~ TypeError: unsupported operand type(s) for +: 'int' and 'str'`{.stderr
.error}
:::
:::

### Source errors

A message is also displayed for errors in the Markdown source. This
usually includes the name of the document source and the approximate
line number.

::: example
::: exampleMarkup
    `print(1 + 2)`{.pythn .cb-run session=inline_source_error}
:::

::: exampleOutput
`SYS CONFIG ERROR in "python.cbmd" near line 42: Language definition for "pythn" does not exist`{.error
.sysConfigError}
:::
:::

### Code

Inline code with `.cb-code` simply displays the code. Nothing is
executed.

::: example
::: exampleMarkup
    `print("Hello from Python!")`{.python .cb-code}
:::

::: exampleOutput
`print("Hello from Python!")`{.python}
:::
:::

The output is identical to that of

    `print("Hello from Python!")`{.python}

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
    ```{.python .cb-run session=hello}
    x = 'Hello from *Python!*'
    ```
:::
:::

::: example
::: exampleMarkup
    ```{.python .cb-run session=hello}
    print(x)
    ```
:::

::: exampleOutput
Hello from *Python!*
:::
:::

### Notebook

Code blocks with `.cb-nb` show the code and also the verbatim stdout.

::: example
::: exampleMarkup
    ```{.python .cb-nb session=random}
    import random
    random.seed(2)
    rnums = [random.randrange(100) for n in range(10)]
    print("Random numbers: {}".format(rnums))
    print("Sorted numbers: {}".format(sorted(rnums)))
    print("Range: {}".format([min(rnums), max(rnums)]))
    ```
:::

::: exampleOutput
``` {.python .numberLines startFrom="1"}
import random
random.seed(2)
rnums = [random.randrange(100) for n in range(10)]
print("Random numbers: {}".format(rnums))
print("Sorted numbers: {}".format(sorted(rnums)))
print("Range: {}".format([min(rnums), max(rnums)]))
```

``` stdout
Random numbers: [7, 11, 10, 46, 21, 94, 85, 39, 32, 77]
Sorted numbers: [7, 10, 11, 21, 32, 39, 46, 77, 85, 94]
Range: [7, 94]
```
:::
:::

While there is not yet support for automatically including plots when
using the built-in code execution system, including them manually is
straightforward. (Plots *are* included automatically when using the
`jupyter_kernel` option. See the documentation and Jupyter example
document.)

Note that this example uses the `show` keyword argument for the code
block so that the output is interpreted as raw Markdown rather than
displayed verbatim (the default for `.cb-nb`).

::: example
::: exampleMarkup
    ```{.python .cb-nb session=plot show=code+stdout:raw+stderr}
    import numpy as np
    import matplotlib.pyplot as plt
    x = np.linspace(0, 6, 600)
    plt.figure(figsize=(4,2.5))
    plt.grid(linestyle='dashed')
    plt.plot(x, np.sin(x))
    plt.xlabel('$x$')
    plt.ylabel('$y=\\sin(x)$')
    plt.savefig('plot.png', transparent=True, bbox_inches='tight')
    markdown = '''
    ![The function $y=\\sin(x)$](plot.png){width=100% max-width=400px}
    '''
    print(markdown)
    ```
:::

::: exampleOutput
``` {.python .numberLines startFrom="1"}
import numpy as np
import matplotlib.pyplot as plt
x = np.linspace(0, 6, 600)
plt.figure(figsize=(4,2.5))
plt.grid(linestyle='dashed')
plt.plot(x, np.sin(x))
plt.xlabel('$x$')
plt.ylabel('$y=\\sin(x)$')
plt.savefig('plot.png', transparent=True, bbox_inches='tight')
markdown = '''
![The function $y=\\sin(x)$](plot.png){width=100% max-width=400px}
'''
print(markdown)
```

![The function $y=\sin(x)$](plot.png){width="100%" max-width="400px"}
:::
:::

### Stderr

Code blocks show stderr automatically by default.

::: example
::: exampleMarkup
    ```{.python .cb-nb session=block_error}
    var = 123
    print(var, flush=True)
    var += "a"
    ```
:::

::: exampleOutput
``` {.python .numberLines startFrom="1"}
var = 123
print(var, flush=True)
var += "a"
```

``` stdout
123
```

``` {.stderr .error}
Traceback (most recent call last):
  File "source.py", line 3, in <module>
    var += "a"
TypeError: unsupported operand type(s) for +=: 'int' and 'str'
```
:::
:::

### Source errors

A message is also displayed for errors in the Markdown source. This
usually includes the name of the document source and the approximate
line number.

::: example
::: exampleMarkup
    ```{.python .cb-ruuun session=block_source_error}
    print(1 + 2)
    ```
:::

::: exampleOutput
``` {.error .sourceError}
SOURCE ERROR in "python.cbmd" near line 135:
Unknown or unsupported Codebraid command "cb-ruuun"

SOURCE ERROR in "python.cbmd" near line 135:
Missing valid Codebraid command
```
:::
:::

### Code

Code blocks with `.cb-code` simply display the code. Nothing is
executed.

::: example
::: exampleMarkup
    ```{.python .cb-code}
    print("Hello from Python!")
    ```
:::

::: exampleOutput
``` {.python .numberLines startFrom="1"}
print("Hello from Python!")
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
    ```{.python .cb-run show=code+stdout+stderr:verbatim_or_empty}
    x = 1 + 2
    ```
:::

::: exampleOutput
``` {.python .numberLines startFrom="1"}
x = 1 + 2
```

``` stderr
 
```
:::
:::

It is also possible to selectively hide output from a code chunk.

::: example
::: exampleMarkup
    ```{.python .cb-nb hide=stdout}
    print(x)
    ```
:::

::: exampleOutput
``` {.python .numberLines startFrom="2"}
print(x)
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
    ```{.python .cb-run name=part1 session=copy_source}
    import random
    random.seed(2)
    rnums = [random.randrange(100) for n in range(10)]
    ```
:::
:::

::: example
::: exampleMarkup
    ```{.python .cb-run name=part2 session=copy_source}
    print("Random numbers: {}".format(rnums))
    ```
:::

::: exampleOutput
Random numbers: \[7, 11, 10, 46, 21, 94, 85, 39, 32, 77\]
:::
:::

Now the code and output of the previous two code chunks are copied and
combined. Because the content for this code block is copied from other
code chunks, the code block itself should be empty, or may alternately
contain a space or underscore as a placeholder.

::: example
::: exampleMarkup
    ```{.python .cb-paste copy=part1+part2 show=code+stdout}
    ```
:::

::: exampleOutput
``` {.python .numberLines startFrom="1"}
import random
random.seed(2)
rnums = [random.randrange(100) for n in range(10)]
print("Random numbers: {}".format(rnums))
```

``` stdout
Random numbers: [7, 11, 10, 46, 21, 94, 85, 39, 32, 77]
```
:::
:::

It would also be possible to copy and re-execute the code.

::: example
::: exampleMarkup
    ```{.python .cb-run copy=part1+part2 session=copied show=code+stdout:raw}
    ```
:::

::: exampleOutput
``` {.python .numberLines startFrom="1"}
import random
random.seed(2)
rnums = [random.randrange(100) for n in range(10)]
print("Random numbers: {}".format(rnums))
```

Random numbers: \[7, 11, 10, 46, 21, 94, 85, 39, 32, 77\]
:::
:::

Another option is to display code, and then copy and execute it later.

::: example
::: exampleMarkup
    ```{.python .cb-code name=hello}
    print("Hello from Python!")
    ```
:::

::: exampleOutput
``` {.python .numberLines startFrom="1"}
print("Hello from Python!")
```
:::
:::

::: example
::: exampleMarkup
    ```{.python .cb-nb copy=hello}
    ```
:::

::: exampleOutput
``` {.python .numberLines startFrom="3"}
print("Hello from Python!")
```

``` stdout
Hello from Python!
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
    ```{.html .cb-code include_file=python.html include_regex="<header.*?/header>"}
    ```
:::

::: exampleOutput
``` {.html .numberLines startFrom="1"}
<header id="title-block-header">
<h1 class="title">Codebraid with Python</h1>
</header>
```
:::
:::

When `include_file` is used with `cb-code`, the included code is simply
displayed. When `include_file` is used with `cb-run` or another command
that executes code, the included code is executed just as if it had been
entered directly.
