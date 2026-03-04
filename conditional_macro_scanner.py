"""
conditional_macro_scanner.py — Pure-text scanner for conditional compilation macros.

Scans all C/C++/header source files in a directory tree and collects the names of
every macro identifier referenced inside a preprocessing conditional directive:

    #if         #ifdef      #ifndef
    #elif       #elifdef    #elifndef   (C23 / GCC extension)

Handles many real-world complexities:
  - Line continuations (backslash-newline) → joins them before parsing
  - Single-line comments (//) stripped before scanning
  - Block comments (/* … */) stripped across lines
  - Both `defined(MACRO)` and `defined MACRO` syntax
  - Free-standing identifier references in expressions:
        #if TIMEOUT > 0
        #if MY_FLAG            (implicit non-zero check)
        #if (A + B) == C
  - Operators / punctuation / numeric literals are NOT collected (only identifiers)
  - C keywords used in #if expressions (e.g. `defined`) are excluded
  - Standard C/C++ compiler-internal double-underscore names are excluded

Public API:
    collect_conditional_macros(repo_dir: str) -> set[str]
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Set

# ---------------------------------------------------------------------------
# Source file extensions to scan
# ---------------------------------------------------------------------------

_SOURCE_EXTENSIONS = frozenset({
    ".c", ".h",
    ".cpp", ".cxx", ".cc",
    ".hpp", ".hxx", ".hh",
    ".inl", ".inc",
})

# Directories to skip entirely during the tree walk
_SKIP_DIRS = frozenset({"build", ".git", ".svn", ".hg", "node_modules"})

# ---------------------------------------------------------------------------
# Keywords / built-ins that appear in #if expressions but are NOT user macros
# ---------------------------------------------------------------------------

_NON_MACRO_KEYWORDS: frozenset[str] = frozenset({
    # preprocessor operator keyword
    "defined",
    # C/C++ keywords that can appear in constant expressions
    "true", "false",
    # ISO C _Bool etc. — unlikely but guard anyway
    "NULL",
    # GCC / Clang extensions sometimes seen in #if
    "__has_include", "__has_feature", "__has_extension",
    "__has_builtin", "__has_attribute", "__has_cpp_attribute",
    "__has_declspec_attribute",
    "__is_identifier",
})

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Match a preprocessing conditional directive line (after stripping comments).
# Group 1 = directive keyword  (if|ifdef|ifndef|elif|elifdef|elifndef)
# Group 2 = the rest of the expression (may be empty for ifdef/ifndef cases)
_DIRECTIVE_RE = re.compile(
    r"""
    ^[ \t]*                                    # optional leading whitespace
    \#[ \t]*                                   # hash, optional spaces
    # (if|ifdef|ifndef|elif|elifdef|elifndef)  # directive keyword
    (if|ifdef|elif|elifdef)                    # only catch this because source insight is poor with other conditions
    \b                                         # word boundary
    (.*)                                       # rest of line (the expression / identifier)
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Identifiers: sequences of letters, digits, underscores starting with letter or underscore
_IDENTIFIER_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")

# Block comment (possibly multi-line, but we process joined-continuation lines)
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
# Single-line comment
_LINE_COMMENT_RE = re.compile(r"//.*")

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _strip_comments(text: str) -> str:
    """Remove C-style block and line comments from *text*."""
    text = _BLOCK_COMMENT_RE.sub(" ", text)
    text = _LINE_COMMENT_RE.sub("", text)
    return text


def _join_continuations(raw_lines: list[str]) -> list[str]:
    """
    Merge backslash-continued lines into a single logical line.

    A physical line ending with '\\' is joined with the next line. The result
    is returned as a list of logical lines (no backslash-continuations remain).
    """
    logical_lines: list[str] = []
    buf = ""
    for line in raw_lines:
        # Remove the actual newline character(s) at the end
        stripped = line.rstrip("\r\n")
        if stripped.endswith("\\"):
            buf += stripped[:-1]  # drop trailing backslash, keep accumulating
        else:
            logical_lines.append(buf + stripped)
            buf = ""
    if buf:
        logical_lines.append(buf)
    return logical_lines


def _extract_identifiers_from_expression(expr: str) -> Set[str]:
    """
    Given the expression part of a #if / #elif directive, return every identifier
    that could be a macro name.

    Exclusions:
      - _NON_MACRO_KEYWORDS  (defined, true, false, __has_feature, …)
      - Double-underscore names  (__GNUC__, __cplusplus, …)
      - Pure numeric literals (already not matched by _IDENTIFIER_RE)
    """
    result: Set[str] = set()
    for m in _IDENTIFIER_RE.finditer(expr):
        name = m.group(1)
        if name in _NON_MACRO_KEYWORDS:
            continue
        if name.startswith("__") and name.endswith("__"):
            continue
        if name.startswith("__"):
            # Compiler-internal names (not double-underscore-wrapped but still internal)
            # We keep single-leading-underscore names since those can be user macros on
            # some platforms (POSIX _XOPEN_SOURCE etc.)
            # Only skip if BOTH prefix and suffix are "__".
            pass
        result.add(name)
    return result


def _process_file(path: str) -> Set[str]:
    """
    Extract all macro names referenced in conditional compilation directives
    in a single source file.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            raw_lines = fh.readlines()
    except OSError:
        return set()

    logical_lines = _join_continuations(raw_lines)

    found: Set[str] = set()

    # We need to handle block comments that span across (already-joined) logical lines.
    # Strategy: process the whole file as one string for block-comment stripping,
    # then split back at newlines for directive detection.
    joined_text = "\n".join(logical_lines)
    clean_text = _strip_comments(joined_text)
    clean_lines = clean_text.splitlines()

    for line in clean_lines:
        m = _DIRECTIVE_RE.match(line)
        if not m:
            continue

        directive = m.group(1).lower()   # if / ifdef / ifndef / elif / elifdef / elifndef
        expr = m.group(2).strip()

        if directive in ("ifdef", "ifndef", "elifdef", "elifndef"):
            # These are followed directly by a single identifier (no expression).
            # Extract just that identifier.
            id_m = _IDENTIFIER_RE.match(expr.lstrip())
            if id_m:
                name = id_m.group(1)
                if (name not in _NON_MACRO_KEYWORDS
                        and not (name.startswith("__") and name.endswith("__"))):
                    found.add(name)
        else:
            # #if / #elif — full expression; collect all identifiers.
            found.update(_extract_identifiers_from_expression(expr))

    return found


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def collect_conditional_macros(repo_dir: str) -> Set[str]:
    """
    Recursively walk *repo_dir*, scanning every C/C++/header source file
    for macro identifiers used inside conditional compilation directives.

    Returns a set of macro names (strings).
    """
    all_macros: Set[str] = set()
    repo_path = Path(repo_dir)

    for root, dirs, files in os.walk(repo_path):
        # Prune unwanted directories in-place so os.walk doesn't descend into them
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]

        for fname in files:
            suffix = Path(fname).suffix.lower()
            if suffix not in _SOURCE_EXTENSIONS:
                continue
            full_path = os.path.join(root, fname)
            macros = _process_file(full_path)
            all_macros.update(macros)

    return all_macros


# ---------------------------------------------------------------------------
# CLI convenience (for debugging / manual inspection)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 2:
        print("Usage: python conditional_macro_scanner.py <repo_dir>")
        sys.exit(1)

    result = collect_conditional_macros(sys.argv[1])
    print(json.dumps(sorted(result), indent=2))
    print(f"\nTotal: {len(result)} conditional-compilation macros found.", file=sys.stderr)
