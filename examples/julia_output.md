---
title: Codebraid with Julia
---

## Inline code

### Run

Inline code with `.cb-run` gives raw stdout.

::: example
::: exampleMarkup
    `println(1 + 2)`{.julia .cb-run}
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
    `"\$\\sin(30^\\circ) = $(sind(30))\$"`{.julia .cb-expr}
:::

::: exampleOutput
$\sin(30^\circ) = 0.5$
:::
:::

::: example
::: exampleMarkup
    `"\$e^{\\pi/4} = $(exp(pi/4))\$"`{.julia .cb-expr}
:::

::: exampleOutput
$e^{\pi/4} = 2.1932800507380152$
:::
:::

::: example
::: exampleMarkup
    `"\$e^{\\pi/4} = $(exp(pi/4))\$"`{.julia .cb-nb}
:::

::: exampleOutput
`$e^{\pi/4} = 2.1932800507380152$`{.expr}
:::
:::

### Stderr

In the event of an error, inline code automatically shows stderr by
default. This code is executed in its own session, `inline_error`, so
that it does not impact other examples.

::: example
::: exampleMarkup
    `1 + "a"`{.julia .cb-run session=inline_error}
:::

::: exampleOutput
`ERROR: LoadError: MethodError: no method matching +(::Int64, ::String) Closest candidates are:   +(::Any, ::Any, !Matched::Any, !Matched::Any...) at ~\AppData\Local\Programs\Julia\share\julia\base\operators.jl:655   +(::T, !Matched::T) where T<:Union{Int128, Int16, Int32, Int64, Int8, UInt128, UInt16, UInt32, UInt64, UInt8} at ~\AppData\Local\Programs\Julia\share\julia\base\int.jl:87   +(::Integer, !Matched::Ptr) at ~\AppData\Local\Programs\Julia\share\julia\base\pointer.jl:161   ... Stacktrace:  [1] top-level scope    @ <string>:1 in expression starting at <string>:1`{.stderr
.error}
:::
:::

### Source errors

A message is also displayed for errors in the Markdown source. This
usually includes the name of the document source and the approximate
line number.

::: example
::: exampleMarkup
    `println(1 + 2)`{.jlia .cb-run session=inline_source_error}
:::

::: exampleOutput
`SYS CONFIG ERROR in "julia.cbmd" near line 45: Language definition for "jlia" does not exist`{.error
.sysConfigError}
:::
:::

## Block code

### Run

Code blocks with `.cb-run` give raw stdout. There is continuity between
code blocks so long as they are in the same session; variables persist.

::: example
::: exampleMarkup
    ```{.julia .cb-run session=hello}
    x = "Hello from *Julia!*"
    ```
:::
:::

::: example
::: exampleMarkup
    ```{.julia .cb-run session=hello}
    println(x)
    ```
:::

::: exampleOutput
Hello from *Julia!*
:::
:::

### Notebook

Code blocks with `.cb-nb` show the code and also the verbatim stdout.

::: example
::: exampleMarkup
    ```{.julia .cb-nb session=random}
    using Random
    using Statistics
    Random.seed!(1)
    rnums = rand(1:100, 10)
    println("Random numbers: $(rnums)")
    println("Median: $(median(rnums))")
    println("Mean: $(mean(rnums))")
    ```
:::

::: exampleOutput
``` {.julia .numberLines startFrom="1"}
using Random
using Statistics
Random.seed!(1)
rnums = rand(1:100, 10)
println("Random numbers: $(rnums)")
println("Median: $(median(rnums))")
println("Mean: $(mean(rnums))")
```

``` stdout
Random numbers: [8, 35, 70, 63, 92, 20, 78, 79, 68, 17]
Median: 65.5
Mean: 53.0
```
:::
:::

### Stderr

Code blocks automatically show stderr by default.

::: example
::: exampleMarkup
    ```{.julia .cb-nb .line_numbers session=block_error}
    var = 123
    println(var)
    flush(stdout)
    var += "a"
    ```
:::

::: exampleOutput
``` {.julia .numberLines startFrom="1"}
var = 123
println(var)
flush(stdout)
var += "a"
```

``` stdout
123
```

``` {.stderr .error}
ERROR: LoadError: MethodError: no method matching +(::Int64, ::String)
Closest candidates are:
  +(::Any, ::Any, !Matched::Any, !Matched::Any...) at ~\AppData\Local\Programs\Julia\share\julia\base\operators.jl:655
  +(::T, !Matched::T) where T<:Union{Int128, Int16, Int32, Int64, Int8, UInt128, UInt16, UInt32, UInt64, UInt8} at ~\AppData\Local\Programs\Julia\share\julia\base\int.jl:87
  +(::Integer, !Matched::Ptr) at ~\AppData\Local\Programs\Julia\share\julia\base\pointer.jl:161
  ...
Stacktrace:
 [1] top-level scope
   @ source.jl:4
in expression starting at source.jl:4
```
:::
:::

### Source errors

A message is also displayed for errors in the Markdown source. This
usually includes the name of the document source and the approximate
line number.

::: example
::: exampleMarkup
    ```{.julia .cb-ruuun session=block_source_error}
    println(1 + 2)
    ```
:::

::: exampleOutput
``` {.error .sourceError}
SOURCE ERROR in "julia.cbmd" near line 101:
Unknown or unsupported Codebraid command "cb-ruuun"

SOURCE ERROR in "julia.cbmd" near line 101:
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
    ```{.julia .cb-run show=code+stdout+stderr:verbatim_or_empty}
    x = 1 + 2
    ```
:::

::: exampleOutput
``` {.julia .numberLines startFrom="1"}
x = 1 + 2
```

``` stderr
 
```
:::
:::

It is also possible to selectively hide output from a code chunk.

::: example
::: exampleMarkup
    ```{.julia .cb-nb hide=stdout}
    println(x)
    ```
:::

::: exampleOutput
``` {.julia .numberLines startFrom="2"}
println(x)
```
:::
:::

`hide` takes any combination of `code`, `stderr`, and `stdout`, or
simply `all`.
