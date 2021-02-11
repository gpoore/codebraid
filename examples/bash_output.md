---
title: Codebraid with Bash
---

## Inline code

### Run

Inline code with `.cb.run` gives raw stdout.

::: {.example}
::: {.exampleMarkup}
    `echo $((1 + 2))`{.bash .cb.run}
:::

::: {.exampleOutput}
3
:::
:::

### Expression and inline notebook

Inline code with `.cb.expr` evaluates an expression and then inserts the
raw output into the document, where it is interpreted as Markdown.
Inline code with `.cb.nb` (`nb` is short for `notebook`) is similar,
except output is shown verbatim. Expressions are evaluated via
`$(<expr>)`.

::: {.example}
::: {.exampleMarkup}
    `(4 * 16)`{.bash .cb.expr}
:::

::: {.exampleOutput}
64
:::
:::

::: {.example}
::: {.exampleMarkup}
    `ls | grep "bash\.cbmd"`{.bash .cb.nb}
:::

::: {.exampleOutput}
`bash.cbmd`{.expr}
:::
:::

### Stderr

In the event of an error, inline code automatically shows stderr by
default. This code is executed in its own session, `inline_error`, so
that it does not impact other examples.

::: {.example}
::: {.exampleMarkup}
    `echooo $((1 + 2))`{.bash .cb.run session=inline_error}
:::

::: {.exampleOutput}
`<string>: line 1: echooo: command not found`{.stderr}
:::
:::

## Block code

### Run

Code blocks with `.cb.run` give raw stdout. There is continuity between
code blocks so long as they are in the same session; variables persist.

::: {.example}
::: {.exampleMarkup}
    ```{.bash .cb.run}
    message="Hello from *Bash!*"
    ```
:::
:::

::: {.example}
::: {.exampleMarkup}
    ```{.bash .cb.run}
    echo "$message"
    ```
:::

::: {.exampleOutput}
Hello from *Bash!*
:::
:::

### Notebook

Code blocks with `.cb.nb` show the code and also the verbatim stdout.

::: {.example}
::: {.exampleMarkup}
    ```{.bash .cb.nb session=notebook}
    ls | grep "bash"
    ```
:::

::: {.exampleOutput}
``` {.bash .numberLines startFrom="1"}
ls | grep "bash"
```

``` {.stdout}
bash.cbmd
bash.html
build_bash.sh
```
:::
:::

::: {.example}
::: {.exampleMarkup}
    ```{.bash .cb.nb session=notebook}
    which python3 && which python
    ```
:::

::: {.exampleOutput}
``` {.bash .numberLines startFrom="2"}
which python3 && which python
```

``` {.stdout}
/usr/bin/python3
```
:::
:::

### Stderr

Code blocks show stderr automatically by default.

::: {.example}
::: {.exampleMarkup}
    ```{.bash .cb.nb session=block_error}
    set -u
    var="$((1 + 2))"
    echo "$varrr"
    ```
:::

::: {.exampleOutput}
``` {.bash .numberLines startFrom="1"}
set -u
var="$((1 + 2))"
echo "$varrr"
```

``` {.stderr}
source.sh: line 3: varrr: unbound variable
```
:::
:::
