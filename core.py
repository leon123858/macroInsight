import os
from macro_extractor import inject_probes
from ast_parser import dump_ast_and_extract

def process_file(source_file, compile_flags=None, known_macros=None):
    print(f"Processing: {source_file}")
    base, ext = os.path.splitext(source_file)
    probe_file = f"{base}.probe{ext}"
    
    try:
        # Step 1: Inject probes
        inject_probes(source_file, probe_file, compile_flags, known_macros)
        
        # Step 2: Extract via Clang AST
        macros = dump_ast_and_extract(probe_file, compile_flags)
        
        return macros
    finally:
        # Step 3: Cleanup probe file
        if os.path.exists(probe_file):
            print(f"Cleaning up {probe_file}")
            os.remove(probe_file)
