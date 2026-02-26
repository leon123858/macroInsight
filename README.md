# MacroInsight

A robust tool to exactly extract statically evaluated C/C++ macro values avoiding linker restrictions and compilation overhead.

## The Problem
In large C embedded projects, you often need the evaluated value of macros. But adding variables to print them requires compiling and linking code. If your project has thousands of macros, declaring `long long` probe variables for all of them will exceed memory constraints causing linker code-space errors.

## The Solution
This tool leverages Clang's `-fsyntax-only` AST dumping capabilities along with `#pragma` and `__builtin_choose_expr` to guarantee that code space is **never touched or linked**. 

1. **Injection**: `macro_extractor.py` parses a given `.c` file and injects `long long PROBE_NAME = ...` for every macro.
   It uses `__builtin_choose_expr(__builtin_constant_p(MACRO), (long long)(MACRO), -9999LL)` so that non-constant macros explicitly fallback to `-9999` without producing compile errors.
2. **Parser**: `ast_parser.py` calls Clang with `-fsyntax-only`, meaning Clang just validates the syntax and generates the Abstract Syntax Tree (AST), but skips Code Generation and Linking entirely! It inherently solves any space/linker restrictions.
3. It directly evaluates the JSON AST branch outputs (handling constant binary math, unary operators, bits shifts, etc.).

## Usage

You must have `uv`, `clang`, and python installed.

To process a single file:
```bash
uv run main.py <path_to_source.c>
```

### With `compile_commands.json`
If your project uses CMake, you can generate a `compile_commands.json` which has the exact `-I` include paths and `-D` defines your project requires.

You can then pass those flags explicitly using `--flags` or `-f`.
For example, if you parsed `compile_commands.json` to extract `flags = ["-I/src/include", "-DDEBUG=1"]`, you can run:
```bash
uv run main.py src/target.c -f "-I/src/include" "-DDEBUG=1"
```

The output will be saved to `macros_output.json`.
