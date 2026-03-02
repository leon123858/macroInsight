"""
elf_reader.py — Read PROBE_ global variable values from a compiled object file.

Supports two backends, selected based on the compiler executable:
  - llvm-objdump  (for clang / any LLVM-based compiler)
  - fromelf       (for armclang / ARM Compiler 6)

The reader locates each PROBE_xxx symbol in the object's data/rodata section
and interprets the 8 bytes at that offset as a little-endian int64.
"""

import os
import re
import struct
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional


# Sentinel written by the probe template when the macro is not a
# compile-time integer constant.
PROBE_SENTINEL = -9999


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def read_probe_values(obj_path: str,
                      probe_names: List[str],
                      compiler_exec: str = "clang") -> Dict[str, Optional[int]]:
    """
    Read PROBE_<name> symbol values from *obj_path*.

    Returns a dict mapping each probe name (without the PROBE_ prefix) to its
    integer value, or None if it could not be determined.
    Entries whose value equals PROBE_SENTINEL are mapped to None, meaning
    "macro exists but is not a compile-time constant".
    """
    compiler_lower = Path(compiler_exec).stem.lower()

    # Determine which backend to use
    if "armclang" in compiler_lower or "armcc" in compiler_lower:
        raw = _read_with_fromelf(obj_path, compiler_exec)
    else:
        raw = _read_with_llvm_objdump(obj_path, compiler_exec)

    if raw is None:
        print(f"[elf_reader] WARNING: Could not read {obj_path}", file=sys.stderr)
        return {name: None for name in probe_names}

    result: Dict[str, Optional[int]] = {}
    for name in probe_names:
        symbol = f"PROBE_{name}"
        val = raw.get(symbol)
        if val is None:
            result[name] = None
        elif val == PROBE_SENTINEL:
            result[name] = None   # not a compile-time constant
        else:
            result[name] = val

    return result


# ---------------------------------------------------------------------------
# Backend: llvm-objdump
# ---------------------------------------------------------------------------

def _find_llvm_objdump(compiler_exec: str) -> str:
    """
    Locate llvm-objdump relative to the given compiler executable,
    or fall back to PATH.
    """
    compiler_path = Path(compiler_exec)
    if compiler_path.is_absolute() or os.sep in compiler_exec:
        candidates = [
            compiler_path.parent / "llvm-objdump.exe",
            compiler_path.parent / "llvm-objdump",
        ]
        for c in candidates:
            if c.exists():
                return str(c)

    # Fall back to PATH
    return "llvm-objdump"


def _read_with_llvm_objdump(obj_path: str, compiler_exec: str) -> Optional[Dict[str, int]]:
    """
    Use llvm-objdump to read PROBE_ symbol values from an ELF/COFF object.

    Strategy:
      1. `llvm-objdump -t` → symbol table (name, section, offset, size)
      2. `llvm-objdump -s` → hex dump of data-like sections
      3. Parse offsets and extract 8-byte little-endian int64 for each symbol.
    """
    objdump = _find_llvm_objdump(compiler_exec)

    # ── Step 1: symbol table ────────────────────────────────────────────────
    sym_cmd = [objdump, "-t", obj_path]
    try:
        sym_result = subprocess.run(sym_cmd, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[elf_reader] llvm-objdump -t failed: {e}", file=sys.stderr)
        return None

    # Parse ELF symbol table lines. Two common formats:
    #   ELF:  <addr_hex> <flags> <section> <size_hex> <name>
    #   COFF: [<idx>] <value_hex> <section_number> <type> <class> <name>
    symbols: Dict[str, dict] = {}
    for line in sym_result.stdout.splitlines():
        # Try to match a PROBE_ symbol line in any common format
        m = re.search(r'PROBE_[A-Za-z0-9_]+', line)
        if not m:
            continue
        sym_name = m.group(0)
        _parse_symbol_line(line, sym_name, symbols)

    if not symbols:
        print("[elf_reader] No PROBE_ symbols found in symbol table.", file=sys.stderr)
        return {}

    # ── Step 2: hex dump ────────────────────────────────────────────────────
    # Collect section names referenced by PROBE_ symbols
    sections_needed = {info["section"] for info in symbols.values() if info.get("section")}

    # Always try a set of likely section names for data/rodata
    default_sections = [".data", ".rodata", ".data.rel.ro", ".rdata", ".rodata.cst8"]
    sections_to_dump = list(sections_needed | set(default_sections))

    hex_cmd = [objdump, "-s", obj_path]
    try:
        hex_result = subprocess.run(hex_cmd, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[elf_reader] llvm-objdump -s failed: {e}", file=sys.stderr)
        return None

    section_bytes = _parse_hex_dump(hex_result.stdout)

    # ── Step 3: extract values ──────────────────────────────────────────────
    result: Dict[str, int] = {}
    for sym_name, info in symbols.items():
        section = info.get("section")
        offset = info.get("offset")
        if section is None or offset is None:
            continue

        data = section_bytes.get(section)
        if data is None:
            # Try known aliases
            for alt in [".rdata", ".rodata", ".data.rel.ro"]:
                data = section_bytes.get(alt)
                if data:
                    break

        if data is None:
            print(f"[elf_reader] Section '{section}' not found in hex dump.", file=sys.stderr)
            continue

        try:
            raw_bytes = data[offset: offset + 8]
            if len(raw_bytes) < 8:
                print(f"[elf_reader] Not enough bytes for {sym_name} at offset {offset:#x}", file=sys.stderr)
                continue
            value = struct.unpack_from("<q", raw_bytes)[0]   # little-endian int64
            result[sym_name] = value
        except Exception as ex:
            print(f"[elf_reader] Error extracting {sym_name}: {ex}", file=sys.stderr)

    return result


def _parse_symbol_line(line: str, sym_name: str, symbols: dict):
    """
    Try to parse a symbol table line from llvm-objdump -t output.

    ELF format example:
      0000000000000000 g     O .rodata        0000000000000008 PROBE_TEST_MACRO

    COFF format example:
      [  2] (sec  3)(fl 0x00)(ty   0)(scl   3) (nx 0) 0x00000000 PROBE_TEST_MACRO
    """
    # ELF pattern: <hex_addr> <flags> <section> <hex_size> <name>
    elf_m = re.match(
        r'([0-9a-fA-F]+)\s+\S+\s+(\S+)\s+([0-9a-fA-F]+)\s+(\S+)', line
    )
    if elf_m and elf_m.group(4) == sym_name:
        symbols[sym_name] = {
            "offset": int(elf_m.group(1), 16),
            "section": elf_m.group(2),
            "size": int(elf_m.group(3), 16),
        }
        return

    # COFF pattern: [...] (sec N) ... 0x<offset> <name>
    coff_m = re.search(r'\(sec\s+(\d+)\).*?0x([0-9a-fA-F]+)\s+' + re.escape(sym_name), line)
    if coff_m:
        symbols[sym_name] = {
            "offset": int(coff_m.group(2), 16),
            "section": f"sec{coff_m.group(1)}",   # resolve later from section map
            "size": 8,
        }
        return

    # Fallback: just note the name with unknown location
    symbols.setdefault(sym_name, {})


def _parse_hex_dump(text: str) -> Dict[str, bytearray]:
    """
    Parse the output of `llvm-objdump -s` into a dict of section_name → bytes.

    Each section block looks like:
      Contents of section .rodata:
       0000 01000000 000000xx ...    <ascii>
    """
    section_bytes: Dict[str, bytearray] = {}
    current_section: Optional[str] = None
    current_data: Optional[bytearray] = None

    for line in text.splitlines():
        # Section header
        hdr = re.match(r"Contents of section ([^:]+):", line)
        if hdr:
            if current_section is not None and current_data is not None:
                section_bytes[current_section] = current_data
            current_section = hdr.group(1).strip()
            current_data = bytearray()
            continue

        # Hex data line: " <offset_hex> <hex_pairs...>  <ascii>"
        if current_data is not None:
            data_m = re.match(r'\s+[0-9a-fA-F]+\s+((?:[0-9a-fA-F]{2,8}\s+)+)', line)
            if data_m:
                hex_part = data_m.group(1)
                for chunk in hex_part.split():
                    try:
                        current_data += bytes.fromhex(chunk)
                    except ValueError:
                        pass

    if current_section is not None and current_data is not None:
        section_bytes[current_section] = current_data

    return section_bytes


# ---------------------------------------------------------------------------
# Backend: fromelf (ARM Compiler 6 / armclang)
# ---------------------------------------------------------------------------

def _find_fromelf(compiler_exec: str) -> str:
    """Locate fromelf relative to armclang, or fall back to PATH."""
    compiler_path = Path(compiler_exec)
    if compiler_path.is_absolute() or os.sep in compiler_exec:
        candidates = [
            compiler_path.parent / "fromelf.exe",
            compiler_path.parent / "fromelf",
        ]
        for c in candidates:
            if c.exists():
                return str(c)
    return "fromelf"


def _read_with_fromelf(obj_path: str, compiler_exec: str) -> Optional[Dict[str, int]]:
    """
    Use `fromelf --text -s` to read the symbol table, then `--text -d` for
    a data section dump, and extract PROBE_ values.
    """
    fromelf = _find_fromelf(compiler_exec)

    # Symbol table
    sym_cmd = [fromelf, "--text", "-s", obj_path]
    try:
        sym_result = subprocess.run(sym_cmd, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[elf_reader] fromelf failed: {e}", file=sys.stderr)
        return None

    # Parse fromelf symbol table — format varies, look for PROBE_ entries
    # Typical line: "   PROBE_MYMACRO    0x00000000   Data   8   .data"
    symbols: Dict[str, dict] = {}
    for line in sym_result.stdout.splitlines():
        m = re.search(r'(PROBE_[A-Za-z0-9_]+)\s+(0x[0-9a-fA-F]+)\s+\S+\s+(\d+)\s+(\S+)', line)
        if m:
            symbols[m.group(1)] = {
                "offset": int(m.group(2), 16),
                "size": int(m.group(3)),
                "section": m.group(4),
            }

    if not symbols:
        print("[elf_reader] fromelf: No PROBE_ symbols found.", file=sys.stderr)
        return {}

    # Data dump
    dump_cmd = [fromelf, "--text", "-d", obj_path]
    try:
        dump_result = subprocess.run(dump_cmd, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[elf_reader] fromelf --text -d failed: {e}", file=sys.stderr)
        return None

    section_bytes = _parse_fromelf_dump(dump_result.stdout)

    result: Dict[str, int] = {}
    for sym_name, info in symbols.items():
        section = info.get("section")
        offset = info.get("offset", 0)
        data = section_bytes.get(section) if section else None
        if data is None:
            for sec_data_key, sec_data_val in section_bytes.items():
                data = sec_data_val
                break  # take first available section as fallback

        if data is None:
            continue
        try:
            raw_bytes = data[offset: offset + 8]
            if len(raw_bytes) < 8:
                continue
            # ARM targets are typically little-endian; adjust if big-endian needed
            value = struct.unpack_from("<q", raw_bytes)[0]
            result[sym_name] = value
        except Exception as ex:
            print(f"[elf_reader] fromelf: Error extracting {sym_name}: {ex}", file=sys.stderr)

    return result


def _parse_fromelf_dump(text: str) -> Dict[str, bytearray]:
    """Parse `fromelf --text -d` output into section_name → bytes."""
    section_bytes: Dict[str, bytearray] = {}
    current_section: Optional[str] = None
    current_data: Optional[bytearray] = None

    for line in text.splitlines():
        sec_m = re.match(r'\*\*\s+Section\s+#\d+\s+\'([^\']+)\'', line)
        if sec_m:
            if current_section and current_data is not None:
                section_bytes[current_section] = current_data
            current_section = sec_m.group(1)
            current_data = bytearray()
            continue

        if current_data is not None:
            data_m = re.match(r'\s*[0-9a-fA-F]+:\s+((?:[0-9a-fA-F]{2}\s+)+)', line)
            if data_m:
                for byte_str in data_m.group(1).split():
                    try:
                        current_data.append(int(byte_str, 16))
                    except ValueError:
                        pass

    if current_section and current_data is not None:
        section_bytes[current_section] = current_data

    return section_bytes
