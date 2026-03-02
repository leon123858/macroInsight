import os
from macro_extractor import inject_probes
from ast_parser import dump_ast_and_extract

def process_file(source_file, compile_flags=None, known_macros=None, clang_exec="clang", system_arch=64):
    print(f"Processing: {source_file}")
    base, ext = os.path.splitext(source_file)
    probe_file = f"{base}.probe{ext}"
    
    # Collect -D command-line macro definitions (name → value or 1) so inject_probes
    # can add them to the probe list. Their values may reference other macros, so they
    # must go through AST evaluation rather than being trusted as literal strings.
    cmdline_macros = {}
    if compile_flags:
        i = 0
        while i < len(compile_flags):
            flag = compile_flags[i]
            macro_def = None
            if flag == "-D" and i + 1 < len(compile_flags):
                macro_def = compile_flags[i + 1]
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
    
    try:
        # Step 1: Inject probes
        inject_probes(source_file, probe_file, compile_flags, known_macros, clang_exec, cmdline_macros=cmdline_macros)
        
        # Step 2: Extract via Clang AST
        macros = dump_ast_and_extract(probe_file, compile_flags, clang_exec, system_arch)
        
        # Step 3: Self-verify extracted macros
        with open(probe_file, "r", encoding="utf-8") as f:
            content = f.read()
        import re
        probe_pattern = re.compile(r"long long PROBE_([A-Za-z0-9_]+) =")
        expected_macros = set(probe_pattern.findall(content))
        
        missing_macros = expected_macros - set(macros.keys())
        if missing_macros:
            error_msg = f"Validation failed! {len(missing_macros)} macros were not successfully extracted in {source_file}.\n"
            for m in list(missing_macros)[:10]:
                error_msg += f"  - Missing: {m}\n"
            if len(missing_macros) > 10:
                error_msg += f"  - ... and {len(missing_macros) - 10} more.\n"
            assert False, error_msg
                
        return macros
    finally:
        # Step 4: Cleanup probe file
        if os.path.exists(probe_file):
            print(f"Cleaning up {probe_file}")
            os.remove(probe_file)
