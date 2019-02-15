---
title: "Codebraid with Python"
---


## Inline code


### Run

Inline code with `.cb.run` gives raw stdout.

```{.example}
`print(1 + 2)`{.python .cb.run}
```

:::{.output}
`print(1 + 2)`{.python .cb.run}
:::


### Expression and inline notebook

Inline code with `.cb.expr` and `.cb.nb` (`nb` is short for `notebook`)
evaluate an expression and then insert the raw output into the document, where
it is interpreted as Markdown.

```{.example}
`"*{}*".format("emphasis")`{.python .cb.expr}

`"**{}**".format("strong")`{.python .cb.nb}
```

:::{.output}
`"*{}*".format("emphasis")`{.python .cb.expr}

`"**{}**".format("strong")`{.python .cb.nb}
:::


### Stderr

In the event of an error, inline code automatically shows stderr by default.
This code is executed in its own session, `inline_error`, so that it does
not impact other examples.

```{.example}
`1 + 'a'`{.python .cb.run session=inline_error}
```

:::{.output}
`1 + 'a'`{.python .cb.run session=inline_error}
:::


### Source errors

A message is also displayed for errors in the Markdown source.  This usually
includes the name of the document source and the approximate line number.

```{.example}
`print(1 + 2)`{.pythn .cb.run session=inline_source_error}
```

:::{.output}
`print(1 + 2)`{.pythn .cb.run session=inline_source_error}
:::



## Block code


### Run

Code blocks with `.cb.run` give raw stdout.  There is continuity between code
blocks so long as they are in the same session; variables persist.

``````{.example}
```{.python .cb.run session=hello}
x = 'Hello from *Python!*'
```

```{.python .cb.run session=hello}
print(x)
```
``````

:::{.output}
```{.python .cb.run session=hello}
x = 'Hello from *Python!*'
```

```{.python .cb.run session=hello}
print(x)
```
:::


### Notebook

Code blocks with `.cb.nb` show the code and also the verbatim stdout.

``````{.example}
```{.python .cb.nb session=random}
import random
random.seed(2)
rnums = [random.randrange(100) for n in range(10)]
print(rnums)
print(sorted(rnums))
print((min(rnums), max(rnums)))
```
``````

:::{.output}
```{.python .cb.nb session=random}
import random
random.seed(2)
rnums = [random.randrange(100) for n in range(10)]
print(rnums)
print(sorted(rnums))
print((min(rnums), max(rnums)))
```
:::

While there is not yet support for automatically including plots, including
them manually is straightforward.

Note that this example uses the `show` keyword argument for the code block
so that the output is interpreted as raw Markdown rather than displayed
verbatim (the default for `.cb.nb`).

``````{.example}
```{.python .cb.nb session=plot show=code+stdout:raw}
import numpy as np
import matplotlib.pyplot as plt
x = np.linspace(0, 6, 600)
plt.figure(figsize=(4,2.5))
plt.grid(linestyle='dashed')
plt.plot(x, np.sin(x))
plt.xlabel('$x$')
plt.ylabel('$y=\\sin(x)$')
plt.savefig('plot.png', transparent=True, bbox_inches='tight')
print('![The function $y=\\sin(x)$](plot.png)')
```
``````

:::{.output}
```{.python .cb.nb session=plot show=code+stdout:raw}
import numpy as np
import matplotlib.pyplot as plt
x = np.linspace(0, 6, 600)
plt.figure(figsize=(4,2.5))
plt.grid(linestyle='dashed')
plt.plot(x, np.sin(x))
plt.xlabel('$x$')
plt.ylabel('$y=\\sin(x)$')
plt.savefig('plot.png', transparent=True, bbox_inches='tight')
print('![The function $y=\\sin(x)$](plot.png)')
```
:::


### Stderr

Code blocks automatically show stderr by default.

``````{.example}
```{.python .cb.nb .line_numbers session=block_error}
var = 123
print(var, flush=True)
var += 'a'
```
``````

:::{.output}
```{.python .cb.nb .line_numbers session=block_error}
var = 123
print(var, flush=True)
var += 'a'
```
:::


### Source errors

A message is also displayed for errors in the Markdown source.  This usually
includes the name of the document source and the approximate line number.

``````{.example}
```{.python .cb.ruuun session=block_source_error}
print(1 + 2)
```
``````

:::{.output}
```{.python .cb.ruuun session=block_source_error}
print(1 + 2)
```
:::


## Other options

By default, stdout and stderr are only shown if they are non-empty.  In some
situations, it may be useful to visually represent empty output as
confirmation that there indeed was none.

``````{.example}
```{.python .cb.run show=code+stdout:verbatim_or_empty+stderr:verbatim_or_empty}
x = 1 + 2
```
``````

:::{.output}
```{.python .cb.run show=code+stdout:verbatim_or_empty+stderr:verbatim_or_empty}
x = 1 + 2
```
:::

It is also possible to selectively hide output from a code chunk.

``````{.example}
```{.python .cb.nb hide=stdout}
print('stdout')
```
``````

:::{.output}
```{.python .cb.nb hide=stdout}
print('stdout')
```
:::

`hide` takes any combination of `code`, `stderr`, and `stdout`, or simply
`all`.
