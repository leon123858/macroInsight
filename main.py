import os
import argparse
import json
import logging
import subprocess
import sys
import xml.etree.ElementTree as ET
from xml.dom import minidom
from pathlib import Path

from core import process_file
from conditional_macro_scanner import collect_conditional_macros


class SilenceFilter(logging.Filter):
    def filter(self, record):
        return record.name == "Bar"


def setup_logging(silence: bool):
    log_format = "[%(name)s] %(message)s"
    logging.basicConfig(level=logging.INFO, format=log_format)
    
    if silence:
        for handler in logging.root.handlers:
            handler.addFilter(SilenceFilter())


def load_env_config():
    """Load environment variables from local configuration files to temporarily override."""
    config_file = "env.json"
    if os.path.exists(config_file):
        logging.getLogger("main").info(f"Loading environment variables from {config_file}")
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k, v in data.items():
                    os.environ[k] = str(v)
        except Exception as e:
            logging.getLogger("main").error(f"Error loading {config_file}: {e}")
         
def generate_compile_commands(repo_dir, build_dir):
    compile_commands_path = os.path.join(build_dir, "compile_commands.json")
    if not os.path.exists(compile_commands_path):
        logging.getLogger("main").info("Generating compile_commands.json via CMake...")
        cmd = ["cmake", "-G", "Unix Makefiles", "-S", repo_dir, "-B", build_dir,
               "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"]
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            logging.getLogger("main").error(f"CMake failed: {e}")
            return None
    return compile_commands_path


def fallback_find_c_files(repo_dir, clang_exec="clang", compile_fallback=False):
    assert compile_fallback, (
        "compile_commands.json missing and --compile-fallback is not enabled. "
        "Halting to avoid inaccurate extraction."
    )
    logging.getLogger("main").warning("compile_commands.json not found!")
    logging.getLogger("main").warning("Falling back to naive recursive C file search.")
    logging.getLogger("main").warning("Macro extraction results may be incomplete or inaccurate!")
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


def save_output(data: dict, output_file: str, fmt: str) -> None:
    """Write *data* to *output_file* in the requested format (json or xml)."""
    if fmt == "xml":
        root = ET.Element("SourceInsightParseConditions", {
            "AppVer": "4.00.0089",
            "AppVerMinReader": "4.00.0019",
        })
        parse_conditions = ET.SubElement(root, "ParseConditions")
        defines = ET.SubElement(parse_conditions, "Defines")
        for key, value in data.items():
            if isinstance(value, bool):
                val_str = "1" if value else "0"
            elif value is None:
                val_str = ""
            else:
                val_str = str(value)
            if val_str != "":
                ET.SubElement(defines, "define", {"id": str(key), "value": val_str})
        xml_bytes = ET.tostring(root, encoding="utf-8")
        pretty_xml = minidom.parseString(xml_bytes).toprettyxml(indent="  ")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(pretty_xml)
    else:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)


def main():
    load_env_config()
    parser = argparse.ArgumentParser(
        description="Extract compiler macro values by compiling a probe file and reading the ELF/COFF object."
    )
    parser.add_argument("--repo-dir", "-r", help="Repository directory containing source code",
                        default=".\\sample")
    parser.add_argument("--output", "-o", help="Output file path", default=None)
    parser.add_argument(
        "--output-format", "-f",
        choices=["json", "xml"],
        default="json",
        help="Output format: json (default) or xml (Source Insight ParseConditions)",
    )
    parser.add_argument("--clang", "-c",
                        choices=["clang", "armclang"],
                        help="Compiler executable to use (clang → llvm-objdump, armclang → fromelf)",
                        default="clang")
    parser.add_argument("--compile-fallback", action="store_true",
                        help="Allow fallback to recursive C file search if compile_commands.json is missing")
    parser.add_argument(
        "--no-conditional-macro",
        dest="conditional_macro",
        action="store_false",
        default=True,
        help="Disable the conditional-macro filter; include ALL evaluated macros in output "
             "(by default only macros referenced in #if/#ifdef/#ifndef/#elif/etc. are kept)",
    )
    parser.add_argument(
        "--jobs", "-j",
        type=int,
        default=None,
        help="Number of concurrent threads to use for parsing (default: automatic based on CPU cores)",
    )
    parser.add_argument(
        "--file-list",
        help="Output compilation target file paths to a text file (each enclosed in quotes)",
        default=None,
    )
    parser.add_argument(
        "--silence",
        action="store_true",
        help="Silence all outputs except for the [Bar] tag",
    )

    args = parser.parse_args()
    
    setup_logging(args.silence)

    repo_dir = os.path.abspath(args.repo_dir)
    build_dir = os.path.join(repo_dir, "build")
    output_fmt = args.output_format
    ext = ".xml" if output_fmt == "xml" else ".json"
    default_output = f".\\macros_output{ext}"
    output_file = os.path.abspath(args.output if args.output is not None else default_output)
    clang_exec = args.clang
    compile_fallback = args.compile_fallback

    compile_commands_path = os.path.join(build_dir, "compile_commands.json")

    logging.getLogger("Bar").info("Init Cmd List")
    if not os.path.exists(compile_commands_path):
        generated_path = generate_compile_commands(repo_dir, build_dir)
        if generated_path and os.path.exists(generated_path):
            compile_commands_path = generated_path

    if os.path.exists(output_file):
        try:
            os.remove(output_file)
        except OSError as e:
            logging.getLogger("main").warning(f"Could not remove existing output file: {e}")

    commands = []
    if not os.path.exists(compile_commands_path):
        commands = fallback_find_c_files(repo_dir, clang_exec, compile_fallback)
    else:
        logging.getLogger("main").info(f"Reading compile commands from {compile_commands_path}")
        try:
            with open(compile_commands_path, "r", encoding="utf-8") as f:
                commands = json.load(f)
        except Exception as e:
            logging.getLogger("main").error(f"Error reading compile_commands.json: {e}")
            sys.exit(1)

    if args.file_list:
        try:
            with open(args.file_list, "w", encoding="utf-8") as fl:
                for cmd in commands:
                    fpath = cmd.get("file", "")
                    if fpath:
                        directory = cmd.get("directory", repo_dir)
                        if not os.path.isabs(fpath):
                            fpath = os.path.join(directory, fpath)
                        fpath = os.path.abspath(fpath)
                        fl.write(f'"{fpath}"\n')
            logging.getLogger("main").info(f"File list saved to {args.file_list}")
        except Exception as e:
            logging.getLogger("main").error(f"Error writing file list to {args.file_list}: {e}")

    all_macros = {}
    count = 0

    import threading
    import concurrent.futures

    all_macros_lock = threading.Lock()

    def worker(cmd):
        file_path = cmd.get("file", "")
        if not file_path.endswith((".c", ".cpp", ".cxx", ".cc")):
            return None

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
            logging.getLogger("main").warning(f"Warning: no command/arguments for {file_path}, skipping.")
            return None

        macros = process_file(
            source_file=file_path,
            original_cmd=original_cmd,
            directory=directory,
            known_macros=all_macros,
            clang_exec=clang_exec,
        )
        return macros

    logging.getLogger("core").info(f"Starting parallel processing with {'automatic' if args.jobs is None else args.jobs} workers...")
    logging.getLogger("Bar").info(f"total job count: {len(commands)}")
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {executor.submit(worker, cmd): cmd for cmd in commands}
        for future in concurrent.futures.as_completed(futures):
            try:
                macros = future.result()
                if macros is not None:
                    with all_macros_lock:
                        if macros:
                            all_macros.update(macros)
                        count += 1
                        logging.getLogger("Bar").info(f"processed {count} files.")
            except Exception as e:
                logging.getLogger("core").error(f"Error processing file: {e}")

    logging.getLogger("core").info(f"Processed {count} files.")

    # --conditional-macro filter (enabled by default)
    if args.conditional_macro:
        logging.getLogger("conditional-macro").info("Scanning source files for conditional-compilation macros...")
        conditional_names = collect_conditional_macros(repo_dir)
        logging.getLogger("conditional-macro").info(f"Found {len(conditional_names)} unique macro names in #if/#ifdef/etc. directives.")
        before = len(all_macros)
        all_macros = {k: v for k, v in all_macros.items() if k in conditional_names}
        logging.getLogger("conditional-macro").info(f"Kept {len(all_macros)}/{before} macros (use --no-conditional-macro to disable this filter).")

    save_output(all_macros, output_file, output_fmt)

    evaluable = sum(1 for v in all_macros.values() if v is not None)
    logging.getLogger("Bar").info(f"Extracted {len(all_macros)} macros ({evaluable} with static values). Saved to {output_file} [{output_fmt}]")


if __name__ == "__main__":
    main()
