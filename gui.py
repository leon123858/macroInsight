import os
import sys
import argparse
import threading
import logging
import json
import webview
from flask import Flask, request, jsonify, render_template

from main import load_env_config, generate_compile_commands, fallback_find_c_files, save_output, setup_logging
from core import process_file
from conditional_macro_scanner import collect_conditional_macros

app = Flask(__name__)
log = logging.getLogger("gui")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/config", methods=["POST"])
def api_config():
    data = request.json
    repo_dir = os.path.abspath(data.get("repo_dir", ".\\sample"))
    output_fmt = data.get("output_format", "json")
    clang_exec = data.get("clang", "clang")
    compile_fallback = data.get("compile_fallback", False)
    file_list = data.get("file_list", None)
    
    # Do initial setup
    load_env_config()
    
    build_dir = os.path.join(repo_dir, "build")
    compile_commands_path = os.path.join(build_dir, "compile_commands.json")
    
    if not os.path.exists(compile_commands_path):
        cmake_lists_path = os.path.join(repo_dir, "CMakeLists.txt")
        cproject_path = os.path.join(repo_dir, ".cproject")
        
        if not os.path.exists(cmake_lists_path) and os.path.exists(cproject_path):
            log.info(f"CMakeLists.txt not found. Generating from {cproject_path} ...")
            try:
                import xml.etree.ElementTree as ET
                from cproject_to_cmake import (
                    list_configurations, 
                    _get_configuration_node, 
                    extract_defines, 
                    extract_includes, 
                    extract_excludes, 
                    render_template
                )
                tree = ET.parse(cproject_path)
                root = tree.getroot()
                
                cproject_config = data.get("cproject_config")
                if not cproject_config:
                    all_configs = list_configurations(root)
                    if all_configs:
                        cproject_config = all_configs[0]
                
                if cproject_config:
                    cfg_node = _get_configuration_node(root, cproject_config)
                    if cfg_node is not None:
                        defines = extract_defines(cfg_node)
                        includes = extract_includes(cfg_node)
                        excludes = extract_excludes(cfg_node)
                        
                        template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cmake_template.txt")
                        if os.path.exists(template_path):
                            with open(template_path, "r", encoding="utf-8") as f:
                                template_content = f.read()
                            
                            output_content = render_template(template_content, defines, includes, excludes)
                            with open(cmake_lists_path, "w", encoding="utf-8") as f:
                                f.write(output_content)
                            log.info(f"Generated CMakeLists.txt using .cproject configuration: {cproject_config}")
                        else:
                            log.warning(f"Template file not found: {template_path}")
                    else:
                        log.warning(f"Configuration node '{cproject_config}' not found in .cproject")
            except Exception as e:
                log.error(f"Error generating CMakeLists.txt from .cproject: {e}")

        generated_path = generate_compile_commands(repo_dir, build_dir)
        if generated_path and os.path.exists(generated_path):
            compile_commands_path = generated_path

    commands = []
    if not os.path.exists(compile_commands_path):
        try:
            commands = fallback_find_c_files(repo_dir, clang_exec, compile_fallback)
        except Exception as e:
            return jsonify({"error": str(e)}), 400
    else:
        try:
            with open(compile_commands_path, "r", encoding="utf-8") as f:
                commands = json.load(f)
        except Exception as e:
            return jsonify({"error": f"Error reading compile_commands.json: {e}"}), 400
            
    if file_list:
        try:
            with open(file_list, "w", encoding="utf-8") as fl:
                for cmd in commands:
                    fpath = cmd.get("file", "")
                    if fpath:
                        directory = cmd.get("directory", repo_dir)
                        if not os.path.isabs(fpath):
                            fpath = os.path.join(directory, fpath)
                        fpath = os.path.abspath(fpath)
                        fl.write(f'"{fpath}"\n')
        except Exception as e:
            log.error(f"Error writing file list: {e}")

    # filter commands to only those we care about (C/C++ files)
    valid_commands = []
    for cmd in commands:
        file_path = cmd.get("file", "")
        if file_path.endswith((".c", ".cpp", ".cxx", ".cc")):
            # ensure absolute
            directory = cmd.get("directory", repo_dir)
            if not os.path.isabs(file_path):
                file_path = os.path.join(directory, file_path)
            cmd["file"] = os.path.abspath(file_path)
            valid_commands.append(cmd)

    return jsonify({
        "commands": valid_commands,
        "repo_dir": repo_dir,
        "clang_exec": clang_exec
    })

@app.route("/api/cproject-configs", methods=["POST"])
def api_cproject_configs():
    data = request.json
    repo_dir = os.path.abspath(data.get("repo_dir", ".\\sample"))
    cproject_path = os.path.join(repo_dir, ".cproject")
    
    if not os.path.exists(cproject_path):
        return jsonify({"configs": []})
        
    try:
        import xml.etree.ElementTree as ET
        from cproject_to_cmake import list_configurations
        tree = ET.parse(cproject_path)
        root = tree.getroot()
        configs = list_configurations(root)
        return jsonify({"configs": configs})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/process", methods=["POST"])
def api_process():
    data = request.json
    cmd = data.get("command")
    repo_dir = data.get("repo_dir")
    clang_exec = data.get("clang_exec", "clang")
    
    file_path = cmd.get("file", "")
    directory = cmd.get("directory", repo_dir)
    
    if "command" in cmd:
        original_cmd = cmd["command"]
    elif "arguments" in cmd:
        import shlex
        original_cmd = shlex.join(cmd["arguments"])
    else:
        return jsonify({"macros": {}})

    try:
        macros = process_file(
            source_file=file_path,
            original_cmd=original_cmd,
            directory=directory,
            known_macros={},
            clang_exec=clang_exec,
        )
        return jsonify({"macros": macros or {}})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/cleanup", methods=["POST"])
def api_cleanup():
    data = request.json
    all_macros = data.get("macros", {})
    repo_dir = data.get("repo_dir")
    output_file = data.get("output_file")
    output_fmt = data.get("output_format", "json")
    conditional_macro = data.get("conditional_macro", True)

    if conditional_macro:
        conditional_names = collect_conditional_macros(repo_dir)
        all_macros = {k: v for k, v in all_macros.items() if k in conditional_names}

    if not output_file:
        ext = ".xml" if output_fmt == "xml" else ".json"
        output_file = os.path.abspath(f".\\macros_output{ext}")

    save_output(all_macros, output_file, output_fmt)
    
    evaluable = sum(1 for v in all_macros.values() if v is not None)
    return jsonify({
        "status": "success",
        "total_extracted": len(all_macros),
        "evaluable": evaluable,
        "output_file": output_file
    })

@app.route("/api/hard-cleanup", methods=["POST"])
def api_hard_cleanup():
    import shutil
    data = request.json
    repo_dir = data.get("repo_dir")
    preview = data.get("preview", False)
    
    if not repo_dir:
        return jsonify({"error": "No repo_dir provided"}), 400
        
    build_dir = os.path.join(repo_dir, "build")
    cmake_lists = os.path.join(repo_dir, "CMakeLists.txt")
    cproject_path = os.path.join(repo_dir, ".cproject")
    
    targets = []
    
    # Target CMakeLists.txt only if .cproject exists
    if os.path.exists(cmake_lists) and os.path.exists(cproject_path):
        targets.append(cmake_lists)
        
    if os.path.exists(build_dir):
        targets.append(build_dir)
        
    if preview:
        return jsonify({"status": "success", "targets": targets})
        
    deleted = []
    errors = []
    
    for target in targets:
        try:
            if os.path.isdir(target):
                shutil.rmtree(target)
            else:
                os.remove(target)
            deleted.append(target)
            log.info(f"Deleted {target}")
        except Exception as e:
            errors.append(f"Could not remove {target}: {e}")
            log.error(f"Could not remove {target}: {e}")
            
    if errors:
        return jsonify({
            "status": "partial_success", 
            "deleted": deleted, 
            "error": "Some files could not be deleted",
            "details": "\n".join(errors)
        }), 500
        
    return jsonify({
        "status": "success",
        "deleted": deleted
    })

def start_server():
    app.run(host="127.0.0.1", port=5000, debug=False)

if __name__ == "__main__":
    setup_logging(False)
    t = threading.Thread(target=start_server)
    t.daemon = True
    t.start()
    
    # 啟用 debug=True，這樣在視窗內按 F12 (或右鍵選單) 就可以打開開發者工具 (DevTools)
    webview.create_window("MacroInsight GUI", "http://127.0.0.1:5000", width=1024, height=768)
    webview.start(debug=True)
