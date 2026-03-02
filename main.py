import os
import argparse
import json
import subprocess
import sys
from pathlib import Path

from core import process_file


def generate_compile_commands(repo_dir, build_dir):
    compile_commands_path = os.path.join(build_dir, "compile_commands.json")
    if not os.path.exists(compile_commands_path):
        print("Generating compile_commands.json via CMake...")
        cmd = ["cmake", "-G", "Unix Makefiles", "-S", repo_dir, "-B", build_dir,
               "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"]
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"CMake failed: {e}", file=sys.stderr)
            return None
    return compile_commands_path


def fallback_find_c_files(repo_dir, clang_exec="clang", compile_fallback=False):
    assert compile_fallback, (
        "compile_commands.json missing and --compile-fallback is not enabled. "
        "Halting to avoid inaccurate extraction."
    )
    print("WARNING: compile_commands.json not found!", file=sys.stderr)
    print("WARNING: Falling back to naive recursive C file search.", file=sys.stderr)
    print("WARNING: Macro extraction results may be incomplete or inaccurate!", file=sys.stderr)
    commands = []
    repo_path = Path(repo_dir)
    for ext in ("*.c", "*.cpp", "*.cxx", "*.cc"):
        for f in repo_path.rglob(ext):
            if "build" not in f.parts:
                abs_f = str(f.absolute())
                commands.append({
                    "file": abs_f,
                    "directory": repo_dir,
                    # Minimal fallback command — no -I, no -D; results will be imprecise
                    "command": f"{clang_exec} -c {abs_f}",
                })
    return commands


def main():
    parser = argparse.ArgumentParser(
        description="Extract compiler macro values by compiling a probe file and reading the ELF/COFF object."
    )
    parser.add_argument("--repo-dir", "-r", help="Repository directory containing source code",
                        default=".\\sample")
    parser.add_argument("--output", "-o", help="Output JSON file", default=".\\macros_output.json")
    parser.add_argument("--clang", "-c",
                        help="Compiler executable to use (clang → llvm-objdump, armclang → fromelf)",
                        default="clang")
    parser.add_argument("--compile-fallback", action="store_true",
                        help="Allow fallback to recursive C file search if compile_commands.json is missing")

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

        directory = cmd.get("directory", repo_dir)
        if not os.path.isabs(file_path):
            file_path = os.path.join(directory, file_path)

        # Build the original command string.
        # Prefer "command" (shell string); fall back to reconstructing from "arguments" list.
        if "command" in cmd:
            original_cmd = cmd["command"]
        elif "arguments" in cmd:
            import shlex
            original_cmd = shlex.join(cmd["arguments"])
        else:
            print(f"Warning: no command/arguments for {file_path}, skipping.", file=sys.stderr)
            continue

        macros = process_file(
            source_file=file_path,
            original_cmd=original_cmd,
            directory=directory,
            known_macros=all_macros,
            clang_exec=clang_exec,
        )
        if macros:
            all_macros.update(macros)
        count += 1

    print(f"Processed {count} files.")

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_macros, f, indent=4)

    evaluable = sum(1 for v in all_macros.values() if v is not None)
    print(f"Extracted {len(all_macros)} macros ({evaluable} with static values). Saved to {output_file}")


if __name__ == "__main__":
    main()
