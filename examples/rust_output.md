---
title: Codebraid with Rust
---

## Introduction

Codebraid with Rust is slightly different than using some other
languages. With a language like Python or Julia, it makes sense that you
can just run the code in code blocks or inline code. But with Rust, what
about `main()`?

By default, all executed code is inserted into a `main()` template like
this:

``` rust
#![allow(unused)]
fn main() {
    use std::fmt::Write as FmtWrite;
    use std::io::Write as IoWrite;
    <code>
}
```

The template allows you to start running code without explicitly
defining `main()`. In some situations, though, it will be useful to
define `main()` explicitly or otherwise have complete control over what
is executed. For those situations, see [Advanced features](#advanced).

## Inline code

### Run

Inline code with `.cb.run` gives raw stdout.

::: example
::: exampleMarkup
    `println!("{}", 1 + 2);`{.rust .cb.run}
:::

::: exampleOutput
3
:::
:::

### Expression and inline notebook

Inline code with `.cb.expr` evaluates an expression and then inserts the
raw output into the document, where it is interpreted as Markdown.
Inline code with `.cb.nb` (`nb` is short for `notebook`) is similar,
except output is shown verbatim. Notice that since these are
expressions, a trailing semicolon must not be used. This is only
compatible with expressions that return Rust types implementing the
`Display` trait.

::: example
::: exampleMarkup
    `format!("*{}*", (1..1000).sum::<i32>())`{.rust .cb.expr}
:::

::: exampleOutput
*499500*
:::
:::

::: example
::: exampleMarkup
    `(1..1000).map(|x| x*x).sum::<i32>()`{.rust .cb.nb}
:::

::: exampleOutput
`332833500`{.expr}
:::
:::

If you need to work with an expression that returns a type without the
`Display` trait, simply use `format!` with the `Debug` trait (`"{:?}"`,
or `"{:#?}"` for pretty-print) to convert to a string manually. Since
the string implements `Display`, everything works:

::: example
::: exampleMarkup
    `format!("{:?}", ())`{.rust .cb.expr}
:::

::: exampleOutput
()
:::
:::

### Stderr

In the event of a compilation error, inline code automatically shows
stderr by default. This code is compiled in its own session,
`inline_error`, so that it does not impact other examples.

::: example
::: exampleMarkup
    `1 + "a";`{.rust .cb.run session=inline_error}
:::

::: exampleOutput
`` error[E0277]: cannot add `&str` to `{integer}`  --> <string>:1:7   | 1 |     1 + "a";   |       ^ no implementation for `{integer} + &str`   |   = help: the trait `Add<&str>` is not implemented for `{integer}`  error: aborting due to previous error  For more information about this error, try `rustc --explain E0277`. ``{.stderr
.error}
:::
:::

### Source errors

A message is also displayed for errors in the Markdown source. This
usually includes the name of the document source and the approximate
line number.

::: example
::: exampleMarkup
    `println!("{}", 1 + 2);`{.rus .cb.run session=inline_source_error}
:::

::: exampleOutput
`SYS CONFIG ERROR in "rust.cbmd" near line 73: Language definition for "rus" does not exist`{.error
.sysConfigError}
:::
:::

## Block code

### Run

Code blocks with `.cb.run` give raw stdout. There is continuity between
code blocks so long as they are in the same session; variables persist.

::: example
::: exampleMarkup
    ```{.rust .cb.run session=hello}
    let x = "Hello from *Rust!*";
    ```
:::
:::

::: example
::: exampleMarkup
    ```{.rust .cb.run session=hello}
    println!("{}", x);
    ```
:::

::: exampleOutput
Hello from *Rust!*
:::
:::

### Notebook

Code blocks with `.cb.nb` show the code and also the verbatim stdout.

::: example
::: exampleMarkup
    ```{.rust .cb.nb session=loop}
    fn pows_of_two(start: u32, end: u32) {
        let n: i32 = 2;
        for x in start..end {
            if x == end - 1 {
                println!("{}", n.pow(x));
            }
            else {
                print!("{}, ", n.pow(x));
            }
        }
    }
    pows_of_two(1, 9);
    pows_of_two(1, 17);
    ```
:::

::: exampleOutput
``` {.rust .numberLines startFrom="1"}
fn pows_of_two(start: u32, end: u32) {
    let n: i32 = 2;
    for x in start..end {
        if x == end - 1 {
            println!("{}", n.pow(x));
        }
        else {
            print!("{}, ", n.pow(x));
        }
    }
}
pows_of_two(1, 9);
pows_of_two(1, 17);
```

``` stdout
2, 4, 8, 16, 32, 64, 128, 256
2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536
```
:::
:::

### Stderr

Code blocks automatically show compilation errors by default. Errors are
synchronized with code blocks so that they appear next to the correct
code blocks.

The first code block in this session is valid, so no compilation error
is shown.

::: example
::: exampleMarkup
    ```{.rust .cb.nb session=block_error}
    let number = 123;
    let letter = "a";
    ```
:::

::: exampleOutput
``` {.rust .numberLines startFrom="1"}
let number = 123;
let letter = "a";
```
:::
:::

The next code block in this sesssion produces a compilation error. The
error message appears automatically, with line numbers that correctly
correspond to the code. This last point is important. Remember that by
default, Codebraid inserts Rust code into an implicit `main()` function,
so the line numbers of what is compiled typically do not correspond to
those of the code entered by the user.

::: example
::: exampleMarkup
    ```{.rust .cb.nb session=block_error}
    number += 1;
    number += letter;
    ```
:::

::: exampleOutput
``` {.rust .numberLines startFrom="3"}
number += 1;
number += letter;
```

``` {.stderr .error}
error[E0277]: cannot add-assign `&str` to `{integer}`
  --> source.rs:4:12
   |
 4 |     number += letter;
   |            ^^ no implementation for `{integer} += &str`
   |
   = help: the trait `AddAssign<&str>` is not implemented for `{integer}`

error: aborting due to previous error

For more information about this error, try `rustc --explain E0277`.
```
:::
:::

### Source errors

A message is also displayed for errors in the Markdown source. This
usually includes the name of the document source and the approximate
line number.

::: example
::: exampleMarkup
    ```{.rust .cb.ruuun session=block_source_error}
    println!("{}", 1 + 2);
    ```
:::

::: exampleOutput
``` {.error .sourceError}
SOURCE ERROR in "rust.cbmd" near line 151:
Unknown or unsupported Codebraid command "cb.ruuun"

SOURCE ERROR in "rust.cbmd" near line 151:
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
    ```{.rust .cb.run show=code+stdout+stderr:verbatim_or_empty}
    let x = 1 + 2;
    ```
:::

::: exampleOutput
``` {.rust .numberLines startFrom="1"}
let x = 1 + 2;
```

``` stderr
 
```
:::
:::

It is also possible to selectively hide output from a code chunk.

::: example
::: exampleMarkup
    ```{.rust .cb.nb hide=stdout}
    println!("{}", x);
    ```
:::

::: exampleOutput
``` {.rust .numberLines startFrom="2"}
println!("{}", x);
```
:::
:::

`hide` takes any combination of `code`, `stderr`, and `stdout`, or
simply `all`.

## Advanced features {#advanced}

### `outside_main`

By default, all executed code is inserted into a `main()` template. It
is possible to create your own `main()` or functions outside `main()`
using the code chunk keyword `outside_main`. If a session *starts* with
one or more code chunks with `outside_main=true`, these are used instead
of the beginning of the `main()` template. Similarly, if a session
*ends* with one or more code chunks with `outside_main=true`, these are
used instead of the end of the `main()` template. If there are any code
chunks in between that lack `outside_main` (that is, default
`outside_main=false`), then these will have their stdout collected on a
per-chunk basis like normal. Having code chunks that lack `outside_main`
is not required; if there are none, the total accumulated stdout for a
session belongs to the last code chunk in the session and can be
controlled by modifying the `show` settings for that chunk.

For example, it is possible to overwrite the `main()` template with a
single, self-contained code block. This is useful when the code is short
enough that splitting it up into separate chunks, each with its
associated stdout, is not necessary.

::: example
::: exampleMarkup
    ```{.rust .cb.nb outside_main=true session=no_main_template_single_chunk}
    fn main() {
        use std::fmt::Write as FmtWrite;
        use std::io::Write as IoWrite;
        println!("Hello from Rust!");
    }
    ```
:::

::: exampleOutput
``` {.rust .numberLines startFrom="1"}
fn main() {
    use std::fmt::Write as FmtWrite;
    use std::io::Write as IoWrite;
    println!("Hello from Rust!");
}
```

``` stdout
Hello from Rust!
```
:::
:::

Here is the same example, but broken up into multiple code chunks so
that the stdout is more closely associated with the code that produced
it.

::: example
::: exampleMarkup
    ```{.rust .cb.nb outside_main=true session=no_main_template}
    fn main() {
        use std::fmt::Write as FmtWrite;
        use std::io::Write as IoWrite;
    ```
:::

::: exampleOutput
``` {.rust .numberLines startFrom="1"}
fn main() {
    use std::fmt::Write as FmtWrite;
    use std::io::Write as IoWrite;
```
:::
:::

::: example
::: exampleMarkup
    ```{.rust .cb.nb session=no_main_template}
        println!("Hello from Rust!");
    ```
:::

::: exampleOutput
``` {.rust .numberLines startFrom="4"}
    println!("Hello from Rust!");
```

``` stdout
Hello from Rust!
```
:::
:::

::: example
::: exampleMarkup
    ```{.rust .cb.nb outside_main=true session=no_main_template}
    }
    ```
:::

::: exampleOutput
``` {.rust .numberLines startFrom="5"}
}
```
:::
:::

### `complete`

By default, a code chunk must contain a complete unit of code. A
function definition, loop, or expression cannot be split between
multiple chunks (with the exception of code chunks with
`outside_main=True`). The code chunk keyword `complete` allows code
chunks that do not contain a complete unit of code.

::: example
::: exampleMarkup
    ```{.rust .cb.nb session=split complete=false}
    fn pows_of_two(start: u32, end: u32) {
        let n: i32 = 2;
        for x in start..end {
    ```
:::

::: exampleOutput
``` {.rust .numberLines startFrom="1"}
fn pows_of_two(start: u32, end: u32) {
    let n: i32 = 2;
    for x in start..end {
```
:::
:::

::: example
::: exampleMarkup
    ```{.rust .cb.nb session=split}
            if x == end - 1 {
                println!("{}", n.pow(x));
            }
            else {
                print!("{}, ", n.pow(x));
            }
        }
    }
    pows_of_two(1, 9);
    ```
:::

::: exampleOutput
``` {.rust .numberLines startFrom="4"}
        if x == end - 1 {
            println!("{}", n.pow(x));
        }
        else {
            print!("{}, ", n.pow(x));
        }
    }
}
pows_of_two(1, 9);
```

``` stdout
2, 4, 8, 16, 32, 64, 128, 256
```
:::
:::
