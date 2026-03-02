"""
core.py — Orchestrates the probe-compile-read pipeline for a single source file.

Pipeline:
  1. inject_probes()       → write probe.c with PROBE_xxx global variables
  2. compile probe.c       → produce probe.obj using the original compile command
     2a. If compile fails, parse stderr for error lines, remove offending probes, retry
  3. read_probe_values()   → extract values from probe.obj via llvm-objdump / fromelf
  4. cleanup               → delete probe.c, probe.obj
"""

import os
import re
import sys
import subprocess
import shlex
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from macro_extractor import inject_probes
from elf_reader import read_probe_values


# ---------------------------------------------------------------------------
# Command building
# ---------------------------------------------------------------------------

def build_probe_compile_cmd(original_cmd: str,
                             original_file: str,
                             probe_c_path: str,
                             probe_obj_path: str,
                             directory: str) -> Optional[List[str]]:
    """
    Build a compile command for probe.c from the original compile_commands entry.

    Transforms the original command by:
      - Keeping all flags unchanged (so -D, -I, -march, --target, … are preserved)
      - Replacing the input file (original_file) with probe_c_path
      - Replacing the -o output with probe_obj_path
      - Ensuring -c is present (compile only, no link)
      - Removing flags that interfere: -fsyntax-only, -ast-dump*, -MF/-MT/-MD, -Werror
      - Adding -O1 so constant folding writes values into the data section
    
    Returns the command as a list of strings, or None if parsing failed.
    """
    try:
        parts = shlex.split(original_cmd)
    except ValueError as e:
        print(f"[core] shlex failed: {e}", file=sys.stderr)
        parts = original_cmd.split()

    # Expand @response files in-place
    parts = _expand_response_files(parts, directory)

    # Flags to remove entirely (single token)
    REMOVE_FLAGS = {
        "-fsyntax-only", "-ast-dump", "-Werror",
        "-save-temps", "-save-temps=obj",
    }
    # Flags whose NEXT token should also be removed (-o <file>, -MF <depfile>, etc.)
    REMOVE_WITH_NEXT = {"-MF", "-MT", "-MQ"}
    # Flags whose prefix should be removed (e.g. -Xclang -ast-dump-filter=...)
    REMOVE_XCLANG_VALUES = {"-ast-dump", "-ast-dump-filter", "-ast-dump=json", "-gcodeview"}

    new_parts: List[str] = []
    i = 0
    has_c_flag = False
    input_replaced = False
    output_replaced = False

    while i < len(parts):
        part = parts[i]

        # Skip flags we want to remove
        if part in REMOVE_FLAGS:
            i += 1
            continue

        if part in REMOVE_WITH_NEXT:
            i += 2
            continue

        # Handle -Xclang <value> pairs
        if part == "-Xclang" and i + 1 < len(parts):
            next_val = parts[i + 1]
            if any(next_val.startswith(bad) for bad in REMOVE_XCLANG_VALUES):
                i += 2
                continue
            # keep the pair
            new_parts.append(part)
            i += 1
            new_parts.append(parts[i])
            i += 1
            continue

        # Skip flags that start with removed prefixes
        if any(part.startswith(bad) for bad in ["-ast-dump", "-Xclang-ast"]):
            i += 1
            continue

        # Replace output
        if part == "-o" and i + 1 < len(parts):
            new_parts.extend(["-o", probe_obj_path])
            output_replaced = True
            i += 2
            continue

        if part.startswith("-o") and len(part) > 2:
            new_parts.append(f"-o{probe_obj_path}")
            output_replaced = True
            i += 1
            continue

        # -c flag
        if part == "-c":
            has_c_flag = True
            new_parts.append(part)
            i += 1
            continue

        # Replace input file (last non-flag positional argument matching original)
        orig_norm = os.path.normcase(os.path.abspath(original_file))
        part_norm = os.path.normcase(os.path.abspath(os.path.join(directory, part))) if not part.startswith("-") else ""
        if not input_replaced and part_norm and part_norm == orig_norm:
            new_parts.append(probe_c_path)
            input_replaced = True
            i += 1
            continue

        new_parts.append(part)
        i += 1

    # Ensure -c is present
    if not has_c_flag:
        new_parts.append("-c")

    # Ensure output is set
    if not output_replaced:
        new_parts.extend(["-o", probe_obj_path])

    # Add -O1 for constant folding (after the compiler name but before other flags)
    # Insert it as a trailing flag if not already present
    if "-O1" not in new_parts and "-O2" not in new_parts and "-O3" not in new_parts and "-Os" not in new_parts:
        # Insert after the first element (compiler) 
        new_parts.insert(1, "-O1")

    return new_parts


def _expand_response_files(parts: List[str], directory: str) -> List[str]:
    """Recursively expand @response_file tokens in a command list."""
    expanded = []
    for part in parts:
        if part.startswith("@"):
            rsp_path = part[1:]
            if not os.path.isabs(rsp_path):
                rsp_path = os.path.join(directory, rsp_path)
            if os.path.exists(rsp_path):
                try:
                    with open(rsp_path, "r", encoding="utf-8") as f:
                        rsp_content = f.read()
                    rsp_args = shlex.split(rsp_content)
                    expanded.extend(_expand_response_files(rsp_args, directory))
                except Exception as e:
                    print(f"[core] Warning: Could not read response file {rsp_path}: {e}", file=sys.stderr)
                    expanded.append(part)
            else:
                print(f"[core] Warning: Response file not found: {rsp_path}", file=sys.stderr)
                expanded.append(part)
        else:
            expanded.append(part)
    return expanded


# ---------------------------------------------------------------------------
# Compilation with error-based probe removal
# ---------------------------------------------------------------------------

def _parse_probe_error_lines(stderr_text: str, probe_c_path: str) -> List[int]:
    """
    Extract line numbers from compiler error messages that reference probe_c_path.
    Returns a sorted list of 1-indexed line numbers with errors.
    """
    error_lines = []
    # Patterns: "file.c:LINE:COL: error:" or "file.c(LINE): error"
    patterns = [
        re.compile(r'(?i)' + re.escape(os.path.basename(probe_c_path)) + r':(\d+):\d+:\s+(?:fatal )?error:'),
        re.compile(r'(?i)' + re.escape(probe_c_path.replace('\\', '/')) + r':(\d+):\d+:\s+(?:fatal )?error:'),
        re.compile(r'(?i)' + re.escape(probe_c_path) + r':(\d+):\d+:\s+(?:fatal )?error:'),
    ]
    for pattern in patterns:
        for m in pattern.finditer(stderr_text):
            error_lines.append(int(m.group(1)))
    return sorted(set(error_lines))


def _remove_probes_at_lines(probe_c_path: str, error_lines: List[int]) -> Tuple[List[str], int]:
    """
    Remove PROBE_ variable declarations that appear at or near the given error lines.
    Returns (removed_probe_names, count_removed).
    """
    with open(probe_c_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Walk backwards from each error line to find the start of the PROBE_ declaration
    probe_name_pattern = re.compile(r'\bPROBE_([A-Za-z0-9_]+)\b')
    removed_names = []
    lines_to_remove = set()

    for err_line in error_lines:
        idx = err_line - 1  # 0-indexed
        # Search in a small window around the error line
        for scan_idx in range(max(0, idx - 2), min(len(lines), idx + 3)):
            m = probe_name_pattern.search(lines[scan_idx])
            if m:
                removed_names.append(m.group(1))
                lines_to_remove.add(scan_idx)
                break

    if not lines_to_remove:
        return [], 0

    new_lines = [line for i, line in enumerate(lines) if i not in lines_to_remove]
    with open(probe_c_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    return removed_names, len(lines_to_remove)


def compile_probe(compile_cmd: List[str],
                  probe_c_path: str,
                  directory: str,
                  max_retries: int = 50) -> Tuple[bool, List[str]]:
    """
    Compile the probe file, automatically removing problematic PROBE_ declarations
    if the compilation fails.

    Returns (success, list_of_removed_macro_names).
    """
    removed_macros: List[str] = []

    for attempt in range(max_retries + 1):
        print(f"[core] Compiling probe (attempt {attempt + 1}): {' '.join(compile_cmd)}")
        result = subprocess.run(
            compile_cmd,
            capture_output=True,
            text=True,
            cwd=directory,
        )

        if result.returncode == 0:
            return True, removed_macros

        stderr = result.stderr
        print(f"[core] Compilation failed (exit {result.returncode})", file=sys.stderr)

        if attempt >= max_retries:
            print("[core] Max retries reached. Giving up on this probe file.", file=sys.stderr)
            print(f"[core] Last stderr:\n{stderr[:2000]}", file=sys.stderr)
            return False, removed_macros

        error_lines = _parse_probe_error_lines(stderr, probe_c_path)
        if not error_lines:
            # Can't identify problem lines — print stderr and bail
            print("[core] Cannot identify error lines in compiler output:", file=sys.stderr)
            print(stderr[:2000], file=sys.stderr)
            return False, removed_macros

        names, count = _remove_probes_at_lines(probe_c_path, error_lines)
        if count == 0:
            print("[core] Could not remove any probes based on error lines.", file=sys.stderr)
            return False, removed_macros

        removed_macros.extend(names)
        print(f"[core] Removed {count} problematic probe(s): {names}")

    return False, removed_macros


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def process_file(source_file: str,
                 original_cmd: str,
                 directory: str,
                 known_macros: Optional[Dict] = None,
                 clang_exec: str = "clang") -> Optional[Dict]:
    """
    Full pipeline for one source file:
      1. Run preprocessor to discover macros → generate probe.c
      2. Compile probe.c → probe.obj (using original compile command)
      3. Read PROBE_ values from probe.obj
      4. Cleanup temp files

    Returns a dict {macro_name: value_or_null} for all discovered macros.
    """
    print(f"Processing: {source_file}")
    base, ext = os.path.splitext(source_file)

    # Derive flags list for preprocessor (-E -dM only needs -D/-I/-isystem/etc.)
    preprocessor_flags = _extract_preprocessor_flags(original_cmd, directory)

    # Collect -D macro definitions from command line
    cmdline_macros = _extract_cmdline_macros(preprocessor_flags)

    probe_c_path = f"{base}.probe{ext}"
    # Use a fixed-name .obj in a temp dir to avoid cluttering the build dir
    probe_obj_path = probe_c_path.replace(ext, ".obj")

    try:
        # Step 1: inject probes — returns (path, list_of_injected_macro_names)
        _, injected_names = inject_probes(
            source_file,
            probe_c_path,
            preprocessor_flags,
            known_macros,
            clang_exec,
            cmdline_macros=cmdline_macros,
        )

        # injected_names is the authoritative list of macros written to probe.c,
        # already deduplicated and filtered by inject_probes.
        expected_probe_names = injected_names

        if not expected_probe_names:
            print(f"[core] No probes generated for {source_file}")
            return {}

        # Step 2: build and run compile command
        compile_cmd = build_probe_compile_cmd(
            original_cmd, source_file, probe_c_path, probe_obj_path, directory
        )
        if compile_cmd is None:
            print(f"[core] Could not build compile command for {source_file}", file=sys.stderr)
            return None

        success, removed_macro_names = compile_probe(compile_cmd, probe_c_path, directory)
        if not success:
            print(f"[core] Probe compilation failed for {source_file}", file=sys.stderr)
            assert False, "Probe compilation failed"

        # Update expected probe names (remove the ones that were dropped)
        remaining_probe_names = [n for n in expected_probe_names if n not in removed_macro_names]

        # Step 3: read values from obj
        macros = read_probe_values(probe_obj_path, remaining_probe_names, clang_exec)

        # Mark removed macros as None (they exist but are not statically evaluable)
        for name in removed_macro_names:
            macros[name] = None

        # ── Self-verification ──────────────────────────────────────────────
        # Every name that inject_probes wrote into probe.c should appear in the
        # returned dict (either as an integer value, or as None if it was removed
        # because it's not a compile-time constant).  A name that is completely
        # absent means the ELF reader failed to locate the symbol in the object
        # file — this is unexpected and indicates a bug or an unsupported section.
        all_expected = set(expected_probe_names)
        actually_returned = set(macros.keys())
        silently_missing = all_expected - actually_returned

        if silently_missing:
            print(
                f"[core] WARNING: {len(silently_missing)} probe(s) were expected but "
                f"not returned by the ELF reader for {source_file}:",
                file=sys.stderr,
            )
            for name in sorted(silently_missing):
                print(f"[core]   - MISSING: {name}", file=sys.stderr)
        # ──────────────────────────────────────────────────────────────────

        return macros


    finally:
        # Step 4: cleanup temp files
        for path in (probe_c_path, probe_obj_path):
            if os.path.exists(path):
                try:
                    os.remove(path)
                    print(f"[core] Cleaned up {path}")
                except OSError as e:
                    print(f"[core] Warning: Could not remove {path}: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_preprocessor_flags(command_str: str, directory: str) -> List[str]:
    """
    Extract flags relevant to 'clang -E -dM' from an original compile command.

    We want the preprocessor to see the SAME macro environment as the real compile,
    so we include ALL flags that influence predefined macros or include search paths:

    Category                      Examples
    ─────────────────────────────────────────────────────────────
    Macro definitions/undefs      -D, -U
    Include search paths          -I, -isystem, -isysroot,
                                  --sysroot, -include, -iprefix,
                                  -iwithprefix, -iquote
    Target triple                 --target=, -target
    Architecture / CPU            -march, -mcpu, -mfpu, -mtune,
                                  -mfloat-abi, -mabi, -mthumb, -marm,
                                  -m32, -m64, -mhard-float, -msoft-float
    Language standard             -std, -ansi, -x
    MS-compat / extensions        -fms-extensions, -fms-compatibility,
                                  -fms-compatibility-version,
                                  -fmsc-version, -fgnuc-version
    Feature flags affecting macros -fno-builtin, -fno-math-errno,
                                  -ffreestanding, -fno-exceptions,
                                  -fno-rtti, -fshort-wchar,
                                  -fshort-enums, -funsigned-char,
                                  -fsigned-char, -fno-signed-zeros
    ARM Thumb interwork            -mthumb-interwork
    ─────────────────────────────────────────────────────────────

    Flags that are NOT included (only affect code-gen / linking, not macros):
      -c, -o, -O*, -g*, -W*, -f{sanitize,coverage,...}, -save-temps, etc.
    """
    try:
        parts = shlex.split(command_str)
    except ValueError:
        parts = command_str.split()

    parts = _expand_response_files(parts, directory)

    # Flags that take a separate next token as their value
    FLAGS_WITH_NEXT = {
        "-D", "-U",
        "-I", "-isystem", "-isysroot", "-iprefix",
        "-iwithprefix", "-iwithprefixbefore",
        "-iquote", "-include", "-include-pch",
        "-target",                     # old-style target flag
        "-x",                          # language override
        "-std",
        "-arch",                       # macOS multi-arch (clang)
        "--sysroot",
        "-march", "-mcpu", "-mfpu", "-mtune",
        "-mfloat-abi", "-mabi",
        "-fms-compatibility-version",
        "-fmsc-version",
        "-fgnuc-version",
    }

    # Flag PREFIXES: the flag and its value are a single token (flag=value or flagVALUE)
    PREFIXES = (
        "-D", "-U",
        "-I", "-isystem", "-isysroot", "-iprefix",
        "-iwithprefix", "-iwithprefixbefore",
        "-iquote", "-include",
        "--target=",                   # --target=<triple>
        "-target=",
        "-x",
        "-std=",
        "--sysroot=",
        "-march=", "-mcpu=", "-mfpu=", "-mtune=",
        "-mfloat-abi=", "-mabi=",
        "-fms-compatibility-version=",
        "-fmsc-version=",
        "-fgnuc-version=",
    )

    # Standalone boolean flags that directly affect predefined macros
    STANDALONE = {
        "-mthumb", "-marm", "-mthumb-interwork",
        "-m32", "-m64",
        "-mhard-float", "-msoft-float",
        "-ansi",
        "-fms-extensions",
        "-fms-compatibility",
        "-fno-ms-extensions",
        "-ffreestanding",
        "-fno-builtin",
        "-fshort-wchar",
        "-fshort-enums",
        "-funsigned-char",
        "-fsigned-char",
        "-fno-signed-char",
        "-fno-exceptions",
        "-fno-rtti",
        "-fno-math-errno",
        "-fno-signed-zeros",
        "-fno-strict-aliasing",
    }

    flags = []
    i = 0
    while i < len(parts):
        part = parts[i]

        # Always skip: compiler executable (first positional) and input file (last .c/.cpp)
        # We skip the first positional by relying on the fact that compiler execs
        # start without '-' but we can't know the input file without extra logic.
        # Instead we simply never emit pure positional args (those without '-').

        if part in FLAGS_WITH_NEXT:
            flags.append(part)
            if i + 1 < len(parts):
                i += 1
                flags.append(parts[i])

        elif any(part.startswith(pfx) for pfx in PREFIXES):
            flags.append(part)

        elif part in STANDALONE:
            flags.append(part)

        # -Xclang pairs: some pass-through flags affect clang's internal state
        # We forward only safe ones (not -ast-dump, -gcodeview, etc.)
        elif part == "-Xclang" and i + 1 < len(parts):
            next_val = parts[i + 1]
            _SAFE_XCLANG = {"-fms-compatibility", "-fno-builtin"}
            if next_val in _SAFE_XCLANG:
                flags.extend([part, next_val])
            i += 1  # always consume the next token

        i += 1

    return flags



def _extract_cmdline_macros(flags: List[str]) -> Dict[str, object]:
    """Extract -D macro definitions from a flags list."""
    cmdline_macros = {}
    i = 0
    while i < len(flags):
        flag = flags[i]
        macro_def = None
        if flag == "-D" and i + 1 < len(flags):
            macro_def = flags[i + 1]
            i += 1
        elif flag.startswith("-D"):
            macro_def = flag[2:]
        if macro_def:
            if "=" in macro_def:
                name, value = macro_def.split("=", 1)
                cmdline_macros[name] = value
            else:
                cmdline_macros[macro_def] = 1
        i += 1
    return cmdline_macros
