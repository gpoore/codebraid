---
title: Codebraid with JavaScript
---

## Inline code

### Run

Inline code with `.cb-run` gives raw stdout. While the language can be
specified with `.javascript`, `.js` works as well.

::: example
::: exampleMarkup
    `console.log(1 + 2);`{.js .cb-run}
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
    `` `\$2^8 = ${2**8}\$` ``{.js .cb-expr}
:::

::: exampleOutput
$2^8 = 256$
:::
:::

::: example
::: exampleMarkup
    `4*16`{.js .cb-nb}
:::

::: exampleOutput
`64`{.expr}
:::
:::

### Stderr

In the event of an error, inline code automatically shows stderr by
default. This code is executed in its own session, `inline_error`, so
that it does not impact other examples.

::: example
::: exampleMarkup
    `console.logs(1 + 2);`{.js .cb-run session=inline_error}
:::

::: exampleOutput
`<string>:1 console.logs(1 + 2);         ^  TypeError: console.logs is not a function     at Object.<anonymous> (<string>:1:9)     at Module._compile (node:internal/modules/cjs/loader:1101:14)     at Object.Module._extensions..js (node:internal/modules/cjs/loader:1153:10)     at Module.load (node:internal/modules/cjs/loader:981:32)     at Function.Module._load (node:internal/modules/cjs/loader:822:12)     at Function.executeUserEntryPoint [as runMain] (node:internal/modules/run_main:81:12)     at node:internal/main/run_main_module:17:47`{.stderr
.error}
:::
:::

## Block code

### Run

Code blocks with `.cb-run` give raw stdout. There is continuity between
code blocks so long as they are in the same session; variables persist.

::: example
::: exampleMarkup
    ```{.js .cb-run}
    message = "Hello from *JavaScript!*";
    ```
:::
:::

::: example
::: exampleMarkup
    ```{.js .cb-run}
    console.log(message);
    ```
:::

::: exampleOutput
Hello from *JavaScript!*
:::
:::

### Notebook

Code blocks with `.cb-nb` show the code and also the verbatim stdout.

::: example
::: exampleMarkup
    ```{.js .cb-nb session=notebook}
    function pows_of_two(start, end) {
        n = 2;
        x = start;
        while (x < end) {
            process.stdout.write(String(2**x) + ", ");
            x += 1;
        }
        console.log(2**end);
    }
    pows_of_two(1, 9);
    pows_of_two(1, 15);
    ```
:::

::: exampleOutput
``` {.js .numberLines startFrom="1"}
function pows_of_two(start, end) {
    n = 2;
    x = start;
    while (x < end) {
        process.stdout.write(String(2**x) + ", ");
        x += 1;
    }
    console.log(2**end);
}
pows_of_two(1, 9);
pows_of_two(1, 15);
```

``` stdout
2, 4, 8, 16, 32, 64, 128, 256, 512
2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768
```
:::
:::

### Stderr

Code blocks show stderr automatically by default.

::: example
::: exampleMarkup
    ```{.js .cb-nb session=block_error}
    x = 1 + ;
    ```
:::

::: exampleOutput
``` {.js .numberLines startFrom="1"}
x = 1 + ;
```

``` {.stderr .error}
source.js:1
x = 1 + ;
        ^

SyntaxError: Unexpected token ';'
    at Object.compileFunction (node:vm:352:18)
    at wrapSafe (node:internal/modules/cjs/loader:1031:15)
    at Module._compile (node:internal/modules/cjs/loader:1065:27)
    at Object.Module._extensions..js (node:internal/modules/cjs/loader:1153:10)
    at Module.load (node:internal/modules/cjs/loader:981:32)
    at Function.Module._load (node:internal/modules/cjs/loader:822:12)
    at Function.executeUserEntryPoint [as runMain] (node:internal/modules/run_main:81:12)
    at node:internal/main/run_main_module:17:47
```
:::
:::
