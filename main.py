import os
import argparse
import json
from macro_extractor import inject_probes
from ast_parser import dump_ast_and_extract

def process_file(source_file, compile_flags=None, known_macros=None):
    print(f"Processing: {source_file}")
    probe_file = source_file.replace(".c", ".probe.c")
    if source_file == probe_file:
        probe_file += ".probe.c"
    
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

def main():
    parser = argparse.ArgumentParser(description="Extract compiler macro values using Clang AST.")
    parser.add_argument("files", nargs="+", help="C source files to process")
    parser.add_argument("--flags", "-f", nargs=argparse.REMAINDER, help="Compilation flags for Clang", default=[])
    parser.add_argument("--output", "-o", help="Output JSON file", default="macros_output.json")
    
    args = parser.parse_args()
    
    all_macros = {}
    if os.path.exists(args.output):
        try:
            with open(args.output, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    all_macros = json.loads(content)
        except Exception as e:
            print(f"Warning: Could not read existing output: {e}")
    
    for file in args.files:
        if os.path.isfile(file):
            macros = process_file(file, args.flags, all_macros)
            if macros:
                all_macros.update(macros)
        else:
            print(f"File not found: {file}")
            
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(all_macros, f, indent=4)
        
    print(f"Extracted {len(all_macros)} macros. Saved to {args.output}")

if __name__ == "__main__":
    main()
