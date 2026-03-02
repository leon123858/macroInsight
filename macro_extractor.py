import re
import os
import subprocess

def inject_probes(source_path, target_path=None, compile_flags=None, known_macros=None, clang_exec="clang", cmdline_macros=None):
    """
    Runs `clang -E -dM` (or custom clang) to get all defined macros, filters for parameterless macros,
    and appends a global variable probe for each at the end of the source file.
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

    # Run clang -E -dM to extract all macros including those from headers
    cmd = [clang_exec, "-E", "-dM"] + compile_flags + [source_path]
    print(f"Running Preprocessor: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        macro_output = result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error running clang preprocessor: {e.stderr}")
        # We can still proceed even if there are preprocessor warnings/errors
        macro_output = e.stdout if e.stdout else ""

    # `#define MACRO_NAME value`
    # We enforce a space after the name to avoid capturing `MACRO_NAME(x)`
    # We allow the value to be empty (e.g., define guards like `#define MACRO_NAME`)
    define_pattern = re.compile(r'^[ \t]*#[ \t]*define[ \t]+([A-Za-z_][A-Za-z0-9_]*)(?:[ \t]+(.*))?$', re.MULTILINE)
    
    # Build unified list of (name, value_str) from both preprocessor output and -D command-line macros.
    # cmdline_macros entries are appended after so they can override/supplement the preprocessor list.
    macro_pairs = [(m.group(1), m.group(2)) for m in define_pattern.finditer(macro_output)]
    # NOTE: clang -E -dM already includes macros passed via -D in its output, so we must
    # deduplicate to avoid generating two PROBE_ declarations for the same macro name
    # (which would cause a redefinition compile error in the probe file).
    seen_names = {name for name, _ in macro_pairs}
    for name, value in cmdline_macros.items():
        if name not in seen_names:
            macro_pairs.append((name, str(value) if value != 1 else None))
            seen_names.add(name)

    probes = []
    for macro_name, macro_value in macro_pairs:
        # Skip internal compiler macros starting with __ to speed things up
        if macro_name.startswith("__") and macro_name.endswith("__"):
            continue
            
        # Skip macros we already extracted previously to greatly improve performance
        if macro_name in known_macros:
            continue
            
        if not macro_value or not macro_value.strip():
            probe_code = f"long long PROBE_{macro_name} = 1LL;\n"
        else:
            probe_code = f"""
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wint-conversion"
#pragma clang diagnostic ignored "-Wpointer-to-int-cast"
long long PROBE_{macro_name} = __builtin_choose_expr(__builtin_constant_p({macro_name}), (long long)({macro_name}), -9999LL);
#pragma clang diagnostic pop
"""
        probes.append(probe_code)

    # Append probes to the end of the original code
    final_code = original_code + "\n\n/* --- MACRO PROBES --- */\n" + "".join(probes)

    with open(target_path, 'w', encoding='utf-8') as f:
        f.write(final_code)
        
    return target_path

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        inject_probes(sys.argv[1])
    else:
        print("Usage: python macro_extractor.py <source.c>")
