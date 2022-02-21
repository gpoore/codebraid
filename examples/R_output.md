---
title: Codebraid with R
---

## Introduction

R code is executed with `Rscript`. The `methods` library is loaded
automatically by default as part of the template into which user code is
inserted. A null graphics device, `pdf(file=NULL)`, is created by
default to avoid the automatic, unintentional creation of plot files
with default names. Saving plots requires explicit graphics commands.

## Inline code

### Run

Inline code with `.cb-run` gives raw stdout.

::: example
::: exampleMarkup
    `cat(1 + 2)`{.R .cb-run}
:::

::: exampleOutput
3
:::
:::

### Expression and inline notebook

Inline code with `.cb-expr` evaluates an expression and then inserts the
raw output into the document, where it is interpreted as Markdown.
Inline code with `.cb-nb` (`nb` is short for `notebook`) is similar,
except output is shown verbatim. Expressions are converted to strings
via `toString()`.

::: example
::: exampleMarkup
    `paste("$2^8 = ", 2^8, "$", sep="")`{.R .cb-expr}
:::

::: exampleOutput
$2^8 = 256$
:::
:::

::: example
::: exampleMarkup
    `(x <- 1:20)[x %% 3 == 0]`{.R .cb-nb}
:::

::: exampleOutput
`3, 6, 9, 12, 15, 18`{.expr}
:::
:::

### Stderr

In the event of an error, inline code automatically shows stderr by
default. This code is executed in its own session, `inline_error`, so
that it does not impact other examples.

::: example
::: exampleMarkup
    `1 + "a"`{.R .cb-run session=inline_error}
:::

::: exampleOutput
`Error in 1 + "a" : non-numeric argument to binary operator Execution halted`{.stderr
.error}
:::
:::

### Source errors

A message is also displayed for errors in the Markdown source. This
usually includes the name of the document source and the approximate
line number.

::: example
::: exampleMarkup
    `cat(1 + 2)`{.R .cb-rn session=inline_source_error}
:::

::: exampleOutput
`SOURCE ERROR in "R.cbmd" near line 52: Unknown or unsupported Codebraid command "cb-rn"  SOURCE ERROR in "R.cbmd" near line 52: Missing valid Codebraid command`{.error
.sourceError}
:::
:::

## Block code

### Run

Code blocks with `.cb-run` give raw stdout. There is continuity between
code blocks so long as they are in the same session; variables persist.

::: example
::: exampleMarkup
    ```{.R .cb-run session=hello}
    x <- "Hello from *R!*"
    ```
:::
:::

::: example
::: exampleMarkup
    ```{.R .cb-run session=hello}
    cat(x)
    ```
:::

::: exampleOutput
Hello from *R!*
:::
:::

### Notebook

Code blocks with `.cb-nb` show the code and also the verbatim stdout.

::: example
::: exampleMarkup
    ```{.R .cb-nb session=random}
    set.seed(1)
    random_ints <- floor(runif(10, min=0, max=101))
    cat("Random integers: ", random_ints, "\n\n")
    summary(random_ints)
    ```
:::

::: exampleOutput
``` {.R .numberLines startFrom="1"}
set.seed(1)
random_ints <- floor(runif(10, min=0, max=101))
cat("Random integers: ", random_ints, "\n\n")
summary(random_ints)
```

``` stdout
Random integers:  26 37 57 91 20 90 95 66 63 6 

   Min. 1st Qu.  Median    Mean 3rd Qu.    Max. 
   6.00   28.75   60.00   55.10   84.00   95.00 
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
    ```{.R .cb-nb session=plot show=code+stdout:raw+stderr}
    png("plot.png", width=500, height=350, bg="transparent")
    x <- seq(0, 6, 0.01)
    y <- sin(x)
    plot(x, y, type="l", col="blue", lwd=3, xlab="x", ylab="y(x) = sin(x)")
    invisible(dev.off())
    markdown <- paste("![The function $y=\\sin(x)$]",
        "(plot.png)",
        "{width=100% max-width=500px}", sep="")
    cat(markdown)
    ```
:::

::: exampleOutput
``` {.R .numberLines startFrom="1"}
png("plot.png", width=500, height=350, bg="transparent")
x <- seq(0, 6, 0.01)
y <- sin(x)
plot(x, y, type="l", col="blue", lwd=3, xlab="x", ylab="y(x) = sin(x)")
invisible(dev.off())
markdown <- paste("![The function $y=\\sin(x)$]",
    "(plot.png)",
    "{width=100% max-width=500px}", sep="")
cat(markdown)
```

![The function $y=\sin(x)$](plot.png){width="100%" max-width="500px"}
:::
:::

### Stderr

Code blocks show stderr automatically by default.

::: example
::: exampleMarkup
    ```{.R .cb-nb session=block_error}
    var <- 123
    cat(var)
    flush(stdout())
    var <- var + "a"
    ```
:::

::: exampleOutput
``` {.R .numberLines startFrom="1"}
var <- 123
cat(var)
flush(stdout())
var <- var + "a"
```

``` stdout
123
```

``` {.stderr .error}
Error in var + "a" : non-numeric argument to binary operator
Execution halted
```
:::
:::

### Source errors

A message is also displayed for errors in the Markdown source. This
usually includes the name of the document source and the approximate
line number.

::: example
::: exampleMarkup
    ```{.R .cb-ruuun session=block_source_error}
    cat(1 + 2)
    ```
:::

::: exampleOutput
``` {.error .sourceError}
SOURCE ERROR in "R.cbmd" near line 124:
Unknown or unsupported Codebraid command "cb-ruuun"

SOURCE ERROR in "R.cbmd" near line 124:
Missing valid Codebraid command
```
:::
:::

## Other options

By default, stdout and stderr are only shown if they are non-empty. In
some situations, it may be useful to represent empty output visually as
confirmation that there indeed was none.

::: example
::: exampleMarkup
    ```{.R .cb-run show=code+stdout+stderr:verbatim_or_empty}
    x <- 1 + 2
    ```
:::

::: exampleOutput
``` {.R .numberLines startFrom="1"}
x <- 1 + 2
```

``` stderr
 
```
:::
:::

It is also possible to selectively hide output from a code chunk.

::: example
::: exampleMarkup
    ```{.R .cb-nb hide=stdout}
    cat(x)
    ```
:::

::: exampleOutput
``` {.R .numberLines startFrom="2"}
cat(x)
```
:::
:::

`hide` takes any combination of `code`, `stderr`, and `stdout`, or
simply `all`.
