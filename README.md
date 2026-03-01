# MacroInsight

A robust tool designed to automatically extract statically evaluated C/C++ macro values to assist IDEs like **Source Insight** with conditional compilation.

## The Problem
Source Insight is a powerful IDE, but to correctly process conditional compilation paths, it needs all relevant macros to be explicitly registered. In large C/C++ embedded projects, there can be thousands of macros used for conditional compilation flags (`#if`, `#ifdef`, etc.), making manual registration impractical. 

Furthermore, simply adding probe variables to print all macros requires compiling and linking the code. Exposing thousands of variables will easily exceed memory constraints and cause linker code-space errors in embedded systems.

## The Solution
This tool automates the extraction of macro values directly from the codebase without touching the linking phase. It leverages Clang's `-fsyntax-only` AST dumping capabilities to extract the values of macros, which can then be fed into Source Insight.

1. **Injection**: `macro_extractor.py` parses a given `.c`/`.cpp` file and injects `long long PROBE_NAME = ...` for every macro.
   It uses `__builtin_choose_expr(__builtin_constant_p(MACRO), (long long)(MACRO), -9999LL)` so that non-constant macros explicitly fallback to `-9999` without producing compile errors.
2. **Parser**: `ast_parser.py` calls Clang with `-fsyntax-only`, meaning Clang just validates the syntax and generates the Abstract Syntax Tree (AST), but skips Code Generation and Linking entirely! It inherently solves any space/linker restrictions.
3. It directly evaluates the JSON AST branch outputs (handling constant binary math, unary operators, bits shifts, etc.).

## Usage

You must have `uv`, `clang`, and python installed.

```bash
.\batch.ps1 -RepoDir "<path_to_source_code>" -Output "<path_to_output>"
```

Sample

```bash
.\batch.ps1 -RepoDir ".\sample" -Output ".\sample\macros.json"
```
