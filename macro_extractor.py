"""
macro_extractor.py — Discover all macros in a source file and generate a probe .c file.

The probe file contains one global variable per macro:
  - If the macro has NO value (e.g. include guards): emit `= 1LL`
  - If the macro value can plausibly be a constant expression: emit the
    __builtin_constant_p ternary guard so that non-constant macros write
    the sentinel -9999LL instead of causing a compile error
  - If the macro value is obviously a non-expression (C keyword, statement
    fragment, string literal, etc.): skip it silently
"""

import re
import os
import subprocess
import logging

# Sentinel value written when a macro is not a compile-time integer constant.
# elf_reader.py interprets this as None (not evaluable).
PROBE_SENTINEL = -9999

# Probe template for macros that may or may not be constants at compile time.
# __builtin_constant_p is supported by both clang and armclang.
PROBE_TEMPLATE_MAYBE = (
    "const volatile long long PROBE_{name} = "
    "__builtin_constant_p((long long)({name})) ? "
    "(long long)({name}) : -9999LL;\n"
)

# Probe template for macros with no value (e.g. include guards "#define FOO").
# These are trivially known to map to 1.
PROBE_TEMPLATE_EMPTY = "const volatile long long PROBE_{name} = 1LL;\n"

# C keywords that, when they appear as the START of a macro value, indicate
# the macro expands to a statement or type fragment — not a castable expression.
_STMT_KEYWORDS = frozenset({
    # Control flow statements — not expressions
    "do", "while", "for", "if", "else", "switch", "case", "default",
    "break", "continue", "return", "goto",
    # Type / declaration keywords — not castable as (long long)
    "struct", "union", "enum", "typedef",
    "void",
    "int", "float", "double", "char", "long", "short",
    "unsigned", "signed", "bool", "_Bool",
    "__int8", "__int16", "__int32", "__int64",
    "_Float16", "_Float32", "_Float64",
    # Storage-class / qualifier keywords used as standalone macro values
    "extern", "static", "register", "auto", "inline", "const", "volatile",
    # Compiler extensions
    "sizeof", "alignof", "_Alignof",
    "__attribute__", "__declspec", "__asm", "asm",
    "__extension__", "__typeof__", "typeof",
})

def _macro_value_is_skippable(value: str) -> bool:
    """
    Return True if the macro value cannot be used as a cast-able expression.
    This is a best-effort heuristic to avoid common compile errors in the probe file.
    """
    v = value.strip()
    if not v:
        return False  # empty → handled by PROBE_TEMPLATE_EMPTY

    # String literals — cast to long long would fail
    if v.startswith('"'):
        return True

    # Check leading token against known non-expression keywords
    # Extract first identifier-like token from the value
    first_token_m = re.match(r'([A-Za-z_][A-Za-z0-9_]*)', v)
    if first_token_m:
        first_token = first_token_m.group(1)
        if first_token in _STMT_KEYWORDS:
            return True

    # Compound statement fragments: starts with '{' or '}'
    if v.startswith(('{', '}')):
        return True

    # Preprocessor tokens like '#' at start (e.g. #pragma fragments embedded in macros)
    if v.startswith('#'):
        return True

    return False


def inject_probes(source_path, target_path=None, compile_flags=None, known_macros=None,
                  clang_exec="clang", cmdline_macros=None):
    """
    Run the compiler preprocessor (-E -dM) to discover all macros, then write
    a probe .c file with one PROBE_xxx global variable per macro.

    Macros are skipped if:
      - They are double-underscore built-in macros (__FOO__)
      - They are already in known_macros
      - Their value is a non-expression fragment (statement keywords, string literals, etc.)
      - They are function-like macros (with parameter list — filtered by the define regex)
    """
    if target_path is None:
        target_path = source_path + ".probe.c"
    if compile_flags is None:
        compile_flags = []
    if known_macros is None:
        known_macros = {}
    if cmdline_macros is None:
        cmdline_macros = {}

    # Read original source code
    with open(source_path, 'r', encoding='utf-8') as f:
        original_code = f.read()

    # Run compiler -E -dM to discover all macros (including those from headers).
    # This is the authoritative source — it reflects the exact macro environment
    # that the compile command would set up.
    cmd = [clang_exec, "-E", "-dM"] + compile_flags + [source_path]
    logging.getLogger("macro_extractor").info(f"Running Preprocessor: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        macro_output = result.stdout
    except subprocess.CalledProcessError as e:
        logging.getLogger("macro_extractor").error(f"Error running preprocessor: {e.stderr}")
        macro_output = e.stdout if e.stdout else ""

    # Match "#define NAME [value]" — note NO parenthesis after NAME so function-like
    # macros (NAME(x)) are excluded because -E -dM emits them as "NAME(x) body".
    define_pattern = re.compile(
        r'^[ \t]*#[ \t]*define[ \t]+([A-Za-z_][A-Za-z0-9_]*)(?:[ \t]+(.*))?$',
        re.MULTILINE,
    )

    macro_pairs = [(m.group(1), m.group(2)) for m in define_pattern.finditer(macro_output)]

    # Add command-line macros not already captured by the preprocessor output
    seen_names = {name for name, _ in macro_pairs}
    for name, value in cmdline_macros.items():
        if name not in seen_names:
            macro_pairs.append((name, str(value) if value != 1 else None))
            seen_names.add(name)

    probes = []
    injected_names = []  # names actually written, in order, after all filtering
    for macro_name, macro_value in macro_pairs:
        # Skip internal compiler macros
        if macro_name.startswith("__"):
            continue

        # Skip already-known macros (avoid re-processing across source files)
        if macro_name in known_macros:
            continue

        # Normalise the macro value
        value_str = macro_value.strip() if macro_value else ""

        if not value_str:
            # Include guard / flag macro with no value → trivially 1
            probes.append(PROBE_TEMPLATE_EMPTY.format(name=macro_name))
            injected_names.append(macro_name)
            continue

        # Skip values that cannot be cast to long long at compile time
        if _macro_value_is_skippable(value_str):
            continue

        # Use the __builtin_constant_p guard for everything else.
        probes.append(PROBE_TEMPLATE_MAYBE.format(name=macro_name))
        injected_names.append(macro_name)

    final_code = original_code + "\n\n/* --- MACRO PROBES --- */\n" + "".join(probes)

    with open(target_path, 'w', encoding='utf-8') as f:
        f.write(final_code)

    return target_path, injected_names


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        inject_probes(sys.argv[1])
    else:
        logging.getLogger("macro_extractor").info("Usage: python macro_extractor.py <source.c>")
