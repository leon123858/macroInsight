# MacroInsight

A robust tool designed to automatically extract statically evaluated C/C++ macro values to assist IDEs like **Source Insight** with conditional compilation.

## The Problem
Source Insight is a powerful IDE, but to correctly process conditional compilation paths, it needs all relevant macros to be explicitly registered. In large C/C++ embedded projects, there can be thousands of macros used for conditional compilation flags (`#if`, `#ifdef`, etc.), making manual registration impractical. 

Furthermore, simply adding probe variables to print all macros requires compiling and linking the code. Exposing thousands of variables will easily exceed memory constraints and cause linker code-space errors in embedded systems.

## The Solution
This tool automatically extracts macro values directly from the codebase, bypassing the linking phase.

It uses -dM to retrieve the macros from the file, then compiles a new file that includes a probe generated from those macros.

Finally, it dumps the updated macro values into the previously compiled object file.

## Usage

You must have `uv`, `clang`, and python installed.

```bash
.\batch.ps1 -RepoDir "<path_to_source_code>" -Output "<path_to_output>"
```

Sample

```bash
.\batch.ps1 -RepoDir ".\sample" -Output ".\sample\macros.json"
```
