---
title: Codebraid with Jupyter kernels
---

Using Codebraid with Jupyter kernels rather than the built-in code
execution system is as simple as adding a Codebraid setting to the
document YAML metadata. For example, this document begins with the
following metadata:

    ---
    title: "Codebraid with Jupyter kernels"
    codebraid:
      jupyter: true
    ---

In this case, Codebraid automatically selects a kernel based on code
language. It is also possible to select a specific kernel. For example,

    ---
    codebraid:
      jupyter:
        kernel: python3
    ---

This would set a default kernel for the entire document. The kernel can
be overridden for an individual session by setting
`jupyter_kernel=<kernel>` on the first code chunk of a session.

## [Matplotlib](https://matplotlib.org/)

Plots are included automatically.

::: example
::: exampleMarkup
    ```{.python .cb-nb}
    %matplotlib inline
    import matplotlib.pyplot as plt
    import numpy as np
    x = np.linspace(0, 2*np.pi, 1001)
    x_tick_values = np.linspace(0, 2*np.pi, 5)
    x_tick_labels = ['0', r'$\pi/2$', r'$\pi$', r'$3\pi/2$', r'$2\pi$']
    plt.plot(x, np.cos(x), label=r'$\cos(x)$')
    plt.plot(x, np.sin(x), label=r'$\sin(x)$')
    plt.xticks(x_tick_values, x_tick_labels)
    plt.legend(prop={'size': 12})
    plt.grid()
    ```
:::

::: exampleOutput
``` {.python .numberLines startFrom="1"}
%matplotlib inline
import matplotlib.pyplot as plt
import numpy as np
x = np.linspace(0, 2*np.pi, 1001)
x_tick_values = np.linspace(0, 2*np.pi, 5)
x_tick_labels = ['0', r'$\pi/2$', r'$\pi$', r'$3\pi/2$', r'$2\pi$']
plt.plot(x, np.cos(x), label=r'$\cos(x)$')
plt.plot(x, np.sin(x), label=r'$\sin(x)$')
plt.xticks(x_tick_values, x_tick_labels)
plt.legend(prop={'size': 12})
plt.grid()
```

![](_codebraid/af3e4fc27886525a/python3--001-01.png){.richOutput}
:::
:::

If there are errors or warnings, they are shown as well. Copying this
code into a Jupyter notebook yields the same output.

::: example
::: exampleMarkup
    ```{.python .cb-nb}
    plt.plot(x, np.sin(x)/x, label=r'$\sin(x)/x$')
    plt.plot(x, np.cos(np.sin(x)), label=r'$\cos(\sin(x))$')
    plt.xticks(x_tick_values, x_tick_labels)
    plt.legend(prop={'size': 12})
    plt.grid()
    ```
:::

::: exampleOutput
``` {.python .numberLines startFrom="12"}
plt.plot(x, np.sin(x)/x, label=r'$\sin(x)/x$')
plt.plot(x, np.cos(np.sin(x)), label=r'$\cos(\sin(x))$')
plt.xticks(x_tick_values, x_tick_labels)
plt.legend(prop={'size': 12})
plt.grid()
```

``` stderr
~\AppData\Local\Temp\ipykernel_9628\293500280.py:1: RuntimeWarning: invalid value encountered in true_divide
  plt.plot(x, np.sin(x)/x, label=r'$\sin(x)/x$')
```

![](_codebraid/af3e4fc27886525a/python3--002-01.png){.richOutput}
:::
:::

## [SymPy](https://www.sympy.org/)

SymPy equations are displayed as well. This example runs in a separate
session from the plots above. Multiple Jupyter kernels can be used
within a single document, and multiple independent sessions are possible
per kernel.

::: example
::: exampleMarkup
    ```{.python .cb-nb session=sympy name=sympy1}
    from sympy import *
    init_printing(use_latex='mathjax')
    x = Symbol('x')
    eqn = E**(-x**2)
    int_eqn = Integral(eqn, (x, -oo, oo))
    int_eqn
    ```
:::

::: exampleOutput
``` {.python .numberLines startFrom="1"}
from sympy import *
init_printing(use_latex='mathjax')
x = Symbol('x')
eqn = E**(-x**2)
int_eqn = Integral(eqn, (x, -oo, oo))
int_eqn
```

$\displaystyle \int\limits_{-\infty}^{\infty} e^{- x^{2}}\, dx$
:::
:::

::: example
::: exampleMarkup
    ```{.python .cb-nb session=sympy name=sympy2}
    int_eqn.doit()
    ```
:::

::: exampleOutput
``` {.python .numberLines startFrom="7"}
int_eqn.doit()
```

$\displaystyle \sqrt{\pi}$
:::
:::

A Jupyter kernel can provide multiple formats for representing an
object. SymPy typically provides a LaTeX representation, a plain-text
representation, and a PNG representation. By default, Codebraid chooses
display formats in this order of precedence: LaTeX, Markdown, PNG, JPG,
plain. (This can be customized; see `rich_output` in the documentation
for details.) So Codebraid displays the SymPy math in LaTeX form. For
this to render as nicely as possible in the browser, Pandoc should be
run with one of the flags for rendering math in HTML, such as
`--mathjax`. For this document, Pandoc was used with `--webtex` to
convert LaTeX into PNG during the document build process.

`cb-paste` works with rich output like plots and LaTeX, just like it
normally does with code, stdout, and stderr.

::: example
::: exampleMarkup
    ```{.cb-paste copy=sympy1+sympy2 show=rich_output}
    ```
:::

::: exampleOutput
$\displaystyle \int\limits_{-\infty}^{\infty} e^{- x^{2}}\, dx$

$\displaystyle \sqrt{\pi}$
:::
:::

## Customizing output

When working with `rich_output` formats that have a `text/*` mime type,
such as LaTeX and Markdown, it is possible to display the rendered
output or show the markup. For example, using
`show=rich_output:latex:raw` displays the raw (rendered) LaTeX, while
`show=rich_output:latex:verbatim` displays the LaTeX markup verbatim.

::: example
::: exampleMarkup
    ```{.cb-paste copy=sympy1 show=rich_output:latex:raw}
    ```
:::

::: exampleOutput
$\displaystyle \int\limits_{-\infty}^{\infty} e^{- x^{2}}\, dx$
:::
:::

::: example
::: exampleMarkup
    ```{.cb-paste copy=sympy1 show=rich_output:latex:verbatim}
    ```
:::

::: exampleOutput
``` latex
$\displaystyle \int\limits_{-\infty}^{\infty} e^{- x^{2}}\, dx$
```
:::
:::
