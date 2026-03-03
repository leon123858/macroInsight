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
    hex_cmd = [objdump, "-s", obj_path]
    try:
        hex_result = subprocess.run(hex_cmd, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[elf_reader] llvm-objdump -s failed: {e}", file=sys.stderr)
        return None

    section_bytes = _parse_hex_dump(hex_result.stdout)

    section_convert_cmd = [objdump, "-h", obj_path]
    try:
        section_convert_result = subprocess.run(section_convert_cmd, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[elf_reader] llvm-objdump -h failed: {e}", file=sys.stderr)
        return None
    
    # print(section_convert_result.stdout)
    # Sections:
    # Idx Name          Size     VMA              Type
    #   0 .text         00005e7c 0000000000000000 TEXT
    #   1 .data         00000018 0000000000000000 DATA
    pattern = r"^\s*(\d+)\s+([\.\w]+)"
    matches = re.findall(pattern, section_convert_result.stdout, re.MULTILINE)
    section_map = {}
    for idx, name in matches:
        if name not in section_map:
            section_map[name] = [f"sec{int(idx)+1}"]
        else:
            section_map[name].append(f"sec{int(idx)+1}")

    # ── Step 3: extract values ──────────────────────────────────────────────
    result: Dict[str, int] = {}
    for sym_name, info in symbols.items():
        section = info.get("section")
        offset = info.get("offset")
        if section is None or offset is None:
            continue
        
        keys = list(section_map.keys())
        targetIdx = (-1, -1)
        for i in range(0, len(keys)):
            for j in range(0, len(section_map.get(keys[i]))):
                if section_map.get(keys[i])[j] == section:
                    targetIdx = (i, j)
                    break
        if targetIdx == (-1, -1):
            assert False, f"Section '{section}' not found in hex dump."
        section_name, section_name_cnt = targetIdx
        data = section_bytes[keys[section_name]][section_name_cnt]
        assert data is not None, f"Section '{section}' not found in hex dump."
        # for i in range(0, len(data), 16):
        #     _chunk = data[i:i+16]
        #     _offset = f"{i:08x}"
        #     _hex_values = " ".join(f"{b:02x}" for b in _chunk)
        #     _hex_values = _hex_values.ljust(16 * 3)
        #     _ascii_values = "".join(chr(b) if 32 <= b <= 126 else "." for b in _chunk)
        #     print(f"{_offset}  {_hex_values}  |{_ascii_values}|")

        try:
            raw_bytes = data[offset: offset + 8]
            assert len(raw_bytes) == 8, f"Not enough bytes for {sym_name} at offset {offset:#x}"
            value = int.from_bytes(raw_bytes, byteorder='little', signed=True)
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


def _parse_hex_dump(text: str) -> Dict[str, List[bytearray]]:
    """
    Parse the output of `llvm-objdump -s` into a dict of section_name → bytes.

    Each section block looks like:
      Contents of section .rodata:
       0000 01000000 000000xx ...    <ascii>
    """
    section_bytes: Dict[str, List[bytearray]] = {}
    current_section: Optional[str] = None
    current_data: Optional[bytearray] = None
    for line in text.splitlines():
        # Section header
        hdr = re.match(r"Contents of section ([^:]+):", line)
        if hdr:
            if current_section is not None and current_data is not None:
                if current_section in section_bytes:
                    section_bytes[current_section].append(current_data)
                else:
                    section_bytes[current_section] = [current_data]
            current_section = hdr.group(1).strip()
            current_data = bytearray()
            continue

        # Hex data line: " <offset_hex> <hex_pairs...>  <ascii>"
        if current_section is not None:
            data_m = re.match(r'\s+[0-9a-fA-F]+\s+((?:[0-9a-fA-F]{8}\s+)+)', line)
            if data_m:
                hex_part = data_m.group(1)
                # print("$$$", hex_part)
                for chunk in hex_part.split():
                    if len(chunk) % 2 != 0:
                        chunk = chunk + '0'
                    try:
                        current_data += bytes.fromhex(chunk)
                    except ValueError:
                        assert False, f"Invalid hex chunk: {chunk}"

    if current_section is not None and current_data is not None:
        if current_section in section_bytes:
            section_bytes[current_section].append(current_data)
        else:
            section_bytes[current_section] = [current_data]

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
    use fromelf dump raw data ib object file
    """
    fromelf = _find_fromelf(compiler_exec)
    # Data dump
    dump_cmd = [fromelf, "--text", "-d", obj_path]
    try:
        dump_result = subprocess.run(dump_cmd, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[elf_reader] fromelf --text -d failed: {e}", file=sys.stderr)
        return None

    section_bytes = _parse_fromelf_dump(dump_result.stdout)
    
    result: Dict[str, int] = {}
    for section_name, r_data in section_bytes.items():
        value = int.from_bytes(r_data, byteorder='little')
        strs  = section_name.split(".")
        if len(strs) < 3:
            continue
        if strs[1] == "rodata" and strs[2].startswith("PROBE_"):
            result[strs[2]] = value

    return result


def _parse_fromelf_dump(text: str) -> Dict[str, bytearray]:
    """Parse `fromelf --text -d` output into section_name → bytes."""
    section_bytes: Dict[str, bytearray] = {}
    current_section: Optional[str] = None
    current_data: Optional[bytearray] = None

    for line in text.splitlines():
        sec_m = re.match(r'\*\*\s+Section\s+#\d+\s+\'([^\']+)\'', line)
        if sec_m:
            current_section = sec_m.group(1)
            current_data = bytearray()
            continue

        if current_section is not None:
            data_m = re.search(r"0x[0-9a-fA-F]+:\s*((?:[0-9a-fA-F]{2}\s*)+)", line)
            if data_m:
                for byte_str in data_m.group(1).split():
                    try:
                        current_data.append(int(byte_str, 16))
                    except ValueError:
                        pass
                section_bytes[current_section] = current_data
                current_section = None
                
    return section_bytes
