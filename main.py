import os
import argparse
import json
import subprocess
import shlex
import sys
from pathlib import Path

from core import process_file

def generate_compile_commands(repo_dir, build_dir):
    compile_commands_path = os.path.join(build_dir, "compile_commands.json")
    if not os.path.exists(compile_commands_path):
        print("Generating compile_commands.json via CMake...")
        # Attempt to run cmake to generate compile_commands.json
        cmd = ["cmake", "-G", "Unix Makefiles", "-S", repo_dir, "-B", build_dir, "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"]
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"CMake failed to configure. Error: {e}", file=sys.stderr)
            return None
    return compile_commands_path

def fallback_find_c_files(repo_dir, clang_exec="clang", compile_fallback=False):
    assert compile_fallback, "compile_commands.json missing and compile_fallback is not enabled. Halting to avoid inaccurate extraction."
    print("WARNING: compile_commands.json not found!", file=sys.stderr)
    print("WARNING: Falling back to naive recursive C file search.", file=sys.stderr)
    print("WARNING: This means critical compiler flags, predefined macros (-D), and include paths (-I) will be missing.", file=sys.stderr)
    print("WARNING: Macro extraction results may be incomplete or inaccurate!", file=sys.stderr)
    commands = []
    # Find all .c, .cpp, .cxx files excluding the 'build' directory
    repo_path = Path(repo_dir)
    for ext in ("*.c", "*.cpp", "*.cxx", "*.cc"):
        for f in repo_path.rglob(ext):
            if "build" not in f.parts:
                commands.append({
                    "file": str(f.absolute()),
                    "directory": repo_dir,
                    "command": f"{clang_exec} -I{repo_dir}"
                })
    return commands

def extract_flags_from_command(command_str):
    flags = []
    try:
        parts = shlex.split(command_str)
    except ValueError as e:
        print(f"Warning: shlex failed to parse command string: {e}")
        parts = command_str.split()
        
    i = 0
    while i < len(parts):
        part = parts[i]
        
        # Match standalone -I or -D 
        if part in ("-I", "-D", "-isystem", "-include"):
            flags.append(part)
            if i + 1 < len(parts):
                i += 1
                flags.append(parts[i])
        # Match concatenated -I... or -D...
        elif part.startswith(("-I", "-D", "-isystem", "-include")):
            flags.append(part)
        
        i += 1
        
    return flags

def extract_flags_from_arguments(arguments_list):
    flags = []
    i = 0
    while i < len(arguments_list):
        arg = arguments_list[i]
        
        if arg in ("-I", "-D", "-isystem", "-include"):
            flags.append(arg)
            if i + 1 < len(arguments_list):
                i += 1
                flags.append(arguments_list[i])
        elif arg.startswith(("-I", "-D", "-isystem", "-include")):
            flags.append(arg)
            
        i += 1
    return flags

def main():
    parser = argparse.ArgumentParser(description="Extract compiler macro values using Clang AST (Batch Mode).")
    parser.add_argument("--repo-dir", "-r", help="Repository directory containing source code", default=".\\sample")
    parser.add_argument("--output", "-o", help="Output JSON file", default=".\\macros_output.json")
    parser.add_argument("--clang", "-c", help="Clang executable to use", default="clang")
    parser.add_argument("--compile-fallback", action="store_true", help="Allow fallback to recursive C file search if compile_commands.json is missing")
    
    args = parser.parse_args()
    
    repo_dir = os.path.abspath(args.repo_dir)
    build_dir = os.path.join(repo_dir, "build")
    output_file = os.path.abspath(args.output)
    clang_exec = args.clang
    compile_fallback = args.compile_fallback
    
    compile_commands_path = os.path.join(build_dir, "compile_commands.json")
    
    if not os.path.exists(compile_commands_path):
        generated_path = generate_compile_commands(repo_dir, build_dir)
        if generated_path and os.path.exists(generated_path):
            compile_commands_path = generated_path
            
    if os.path.exists(output_file):
        try:
            os.remove(output_file)
        except OSError as e:
            print(f"Warning: Could not remove existing output file: {e}")

    commands = []
    if not os.path.exists(compile_commands_path):
        commands = fallback_find_c_files(repo_dir, clang_exec, compile_fallback)
    else:
        print(f"Reading compile commands from {compile_commands_path}")
        try:
            with open(compile_commands_path, "r", encoding="utf-8") as f:
                commands = json.load(f)
        except Exception as e:
            print(f"Error reading compile_commands.json: {e}", file=sys.stderr)
            sys.exit(1)
            
    all_macros = {}
    count = 0
    
    for cmd in commands:
        file_path = cmd.get("file", "")
        if not file_path.endswith((".c", ".cpp", ".cxx", ".cc")):
            continue
            
        if not os.path.isabs(file_path):
            directory = cmd.get("directory", repo_dir)
            file_path = os.path.join(directory, file_path)
            
        extract_flags = []
        if "command" in cmd:
            extract_flags = extract_flags_from_command(cmd["command"])
        elif "arguments" in cmd:
            extract_flags = extract_flags_from_arguments(cmd["arguments"])
            
        # Extract initial constant definitions directly from the compile -D flags
        # so they are correctly accounted for out-of-the-box before compiling AST.
        i = 0
        while i < len(extract_flags):
            flag = extract_flags[i]
            macro_def = None
            if flag == "-D" and i + 1 < len(extract_flags):
                macro_def = extract_flags[i+1]
                i += 1
            elif flag.startswith("-D"):
                macro_def = flag[2:]
                
            if macro_def:
                # Format is usually NAME=VALUE or NAME
                if "=" in macro_def:
                    name, value = macro_def.split("=", 1)
                    try:
                        # Attempt to parse integer values since AST evaluates to int
                        all_macros[name] = int(value, 0)
                    except ValueError:
                        all_macros[name] = value
                else:
                    all_macros[macro_def] = 1 # -DNAME implicitly defines NAME as 1
            i += 1
            
        macros = process_file(file_path, extract_flags, all_macros, clang_exec)
        if macros:
            all_macros.update(macros)
        count += 1
        
    print(f"Processed {count} files.")
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_macros, f, indent=4)
        
    print(f"Extracted {len(all_macros)} macros. Saved to {output_file}")


if __name__ == "__main__":
    main()
