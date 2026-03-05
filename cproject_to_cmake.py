#!/usr/bin/env python3
"""
cproject_to_cmake.py

從 Eclipse CDT 的 .cproject 檔案中，提取指定 configurationName 底下的：
  - Define macros (-D)
  - Include paths (-I)
  - Exclude paths (sourceEntries excluding)

再套用 cmake_template.txt 模板，產生 CMakeLists.txt。

Usage:
    python cproject_to_cmake.py \
        --cproject .cproject.sample \
        --template cmake_template.txt \
        --config FW_XXX \
        --output CMakeLists.txt
"""

import argparse
import sys
import re
import logging
from pathlib import Path
from xml.etree import ElementTree as ET


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------

def _unescape_value(value: str) -> str:
    """還原 XML entity（主要是 &quot; → "）並移除外層引號。"""
    value = value.replace("&quot;", '"').replace("&amp;", "&")
    # 移除 Eclipse 用 &quot; 包住的路徑兩側引號
    value = value.strip('"')
    return value


def _get_configuration_node(root: ET.Element, config_name: str) -> ET.Element:
    """
    在整個 XML 樹中尋找 name 屬性符合 config_name 的 <configuration> 節點。
    Eclipse .cproject 可能有多個 cconfiguration，每個下面又有一個 configuration。
    """
    # 尋找 cdtBuildSystem storageModule 底下的 configuration
    for storage in root.iter("storageModule"):
        if storage.get("moduleId") == "cdtBuildSystem":
            for cfg in storage.iter("configuration"):
                if cfg.get("name") == config_name:
                    return cfg
    return None


# ---------------------------------------------------------------------------
# Extract functions
# ---------------------------------------------------------------------------

def extract_defines(cfg_node: ET.Element) -> list[str]:
    """
    提取 C Compiler 的 Define macro (-D) option。
    superClass 含 "option.defmac" 且 valueType="definedSymbols"。
    """
    defines = []
    for option in cfg_node.iter("option"):
        super_class = option.get("superClass", "")
        value_type  = option.get("valueType", "")
        # 只取 C compiler 的 defmac，排除 assembler / linker 的版本
        # （superClass 包含 "c.compiler" 或 "tool.c.compiler"）
        if "option.defmac" in super_class and value_type == "definedSymbols":
            # 確認它屬於 C compiler tool（不是 assembler）
            tool_ancestor = _find_ancestor_tool(cfg_node, option)
            if tool_ancestor is not None:
                tool_name = tool_ancestor.get("name", "")
                # 排除 assembler 與 linker
                if "Assembler" in tool_name or "Linker" in tool_name or "Librarian" in tool_name:
                    continue
            for list_opt in option.findall("listOptionValue"):
                val = list_opt.get("value", "")
                if val:
                    defines.append(_unescape_value(val))
    return defines


def extract_includes(cfg_node: ET.Element) -> list[str]:
    """
    提取 Include path (-I) option。
    superClass 含 "option.incpath"，valueType="includePath"。
    """
    includes = []
    for option in cfg_node.iter("option"):
        super_class = option.get("superClass", "")
        value_type  = option.get("valueType", "")
        if "option.incpath" in super_class and value_type == "includePath":
            for list_opt in option.findall("listOptionValue"):
                val = list_opt.get("value", "")
                if val:
                    includes.append(_unescape_value(val))
    return includes


def extract_excludes(cfg_node: ET.Element) -> list[str]:
    """
    提取 sourceEntries 中的 excluding 屬性（以 | 分隔的路徑列表）。
    """
    excludes = []
    for entry in cfg_node.iter("entry"):
        excl = entry.get("excluding", "")
        if excl:
            parts = [p.strip() for p in excl.split("|") if p.strip()]
            excludes.extend(parts)
    return excludes


def _find_ancestor_tool(root: ET.Element, target: ET.Element):
    """
    在 root 子樹中找到包含 target 的直接 <tool> 父節點。
    ElementTree 不支援 parent map，需要自己建立。
    """
    parent_map = {child: parent for parent in root.iter() for child in parent}

    node = target
    while node in parent_map:
        node = parent_map[node]
        if node.tag == "tool":
            return node
    return None


# ---------------------------------------------------------------------------
# Eclipse variable → CMake variable 轉換
# ---------------------------------------------------------------------------

_ECLIPSE_VAR_RE = re.compile(r"\$\{workspace_loc:/?\$?\{?ProjName\}?(/[^}]*)?\}")

def _eclipse_path_to_cmake(path: str) -> str:
    """
    把 Eclipse 路徑變數轉成 CMake 的 PROJECT_SOURCE_DIR 形式。

    例：
      ${workspace_loc:/${ProjName}/src_fw/common}  →  ${PROJECT_SOURCE_DIR}/src_fw/common
      ${workspace_loc:/${ProjName}/src_fw}          →  ${PROJECT_SOURCE_DIR}/src_fw
    """
    def replacer(m):
        sub = m.group(1) or ""
        return "${PROJECT_SOURCE_DIR}" + sub

    result = _ECLIPSE_VAR_RE.sub(replacer, path)
    # 若仍含 ${workspace_loc:...} 之類的無法辨識變數，原樣保留
    return result


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

def _build_defines_block(defines: list[str]) -> str:
    if not defines:
        return "add_definitions(\n    # (no defines extracted)\n)"
    lines = ["add_definitions("]
    for d in defines:
        lines.append(f"    -D{d}")
    lines.append(")")
    return "\n".join(lines)


def _build_includes_block(includes: list[str]) -> str:
    if not includes:
        return "include_directories(\n    # (no include paths extracted)\n)"
    lines = ["include_directories("]
    for inc in includes:
        cmake_inc = _eclipse_path_to_cmake(inc)
        lines.append(f'    "{cmake_inc}"')
    lines.append(")")
    return "\n".join(lines)


def _build_excludes_block(excludes: list[str], glob_root: str = "src_fw") -> str:
    """
    把排除路徑轉成 list(FILTER SOURCES EXCLUDE REGEX ...) 語句。
    每個排除路徑產生一行 FILTER 語句。
    """
    if not excludes:
        return "# (no exclude paths extracted)"
    lines = []
    for excl in excludes:
        # 正規化路徑分隔符
        excl_re = excl.replace("\\", "/").rstrip("/")
        lines.append(f'list(FILTER SOURCES EXCLUDE REGEX "{excl_re}/.*")')
    return "\n".join(lines)


PLACEHOLDER_DEFINES  = re.compile(r"add_definitions\([^)]*\)", re.DOTALL)
PLACEHOLDER_INCLUDES = re.compile(r"include_directories\([^)]*\)", re.DOTALL)
PLACEHOLDER_EXCLUDES = re.compile(r'list\(FILTER SOURCES EXCLUDE REGEX "[^"]*"\)')


def render_template(template: str, defines: list[str],
                    includes: list[str], excludes: list[str]) -> str:
    """
    將模板中的佔位區塊替換成從 .cproject 提取的內容。
    """
    result = template

    # 1. 替換 add_definitions(...)
    defines_block = _build_defines_block(defines)
    result, n = PLACEHOLDER_DEFINES.subn(defines_block, result, count=1)
    if n == 0:
        # 模板沒有 add_definitions，就在 include_directories 前插入
        result = defines_block + "\n\n" + result

    # 2. 替換 include_directories(...)
    includes_block = _build_includes_block(includes)
    result, n = PLACEHOLDER_INCLUDES.subn(includes_block, result, count=1)
    if n == 0:
        result = includes_block + "\n\n" + result

    # 3. 替換第一個 list(FILTER SOURCES EXCLUDE REGEX ...) 或附加到 file(GLOB_RECURSE ...) 後
    excludes_block = _build_excludes_block(excludes)
    result, n = PLACEHOLDER_EXCLUDES.subn(excludes_block, result, count=1)
    if n == 0:
        # 找 file(GLOB_RECURSE ...) 後面插入
        glob_re = re.compile(r'(file\(GLOB_RECURSE[^\)]*\))', re.DOTALL)
        m = glob_re.search(result)
        if m:
            end = m.end()
            result = result[:end] + "\n" + excludes_block + result[end:]
        else:
            result += "\n" + excludes_block

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="從 .cproject 提取設定並產生 CMakeLists.txt"
    )
    parser.add_argument(
        "--cproject", default=".cproject.sample",
        help="輸入的 .cproject 檔案路徑 (預設: .cproject.sample)"
    )
    parser.add_argument(
        "--template", default="cmake_template.txt",
        help="CMakeLists.txt 模板路徑 (預設: cmake_template.txt)"
    )
    parser.add_argument(
        "--config", default=None,
        help="目標 configurationName。若未指定，自動使用第一個找到的 configuration。"
    )
    parser.add_argument(
        "--output", default="CMakeLists.txt",
        help="輸出的 CMakeLists.txt 路徑 (預設: CMakeLists.txt)"
    )
    parser.add_argument(
        "--list-configs", action="store_true",
        help="列出所有可用的 configurationName 後退出"
    )
    return parser.parse_args()


def list_configurations(root: ET.Element) -> list[str]:
    names = []
    for storage in root.iter("storageModule"):
        if storage.get("moduleId") == "cdtBuildSystem":
            for cfg in storage.iter("configuration"):
                name = cfg.get("name")
                if name:
                    names.append(name)
    return names


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args()

    # --- 讀取 .cproject ---
    cproject_path = Path(args.cproject)
    if not cproject_path.exists():
        logging.getLogger("cproject_to_cmake").error(f"[ERROR] 找不到 .cproject 檔案: {cproject_path}")
        sys.exit(1)

    try:
        tree = ET.parse(cproject_path)
        root = tree.getroot()
    except ET.ParseError as e:
        logging.getLogger("cproject_to_cmake").error(f"[ERROR] XML 解析失敗: {e}")
        sys.exit(1)

    # --- 列出所有 configurations ---
    all_configs = list_configurations(root)

    if args.list_configs:
        if all_configs:
            logging.getLogger("cproject_to_cmake").info("可用的 configurationName：")
            for c in all_configs:
                logging.getLogger("cproject_to_cmake").info(f"  - {c}")
        else:
            logging.getLogger("cproject_to_cmake").info("未找到任何 configuration。")
        return

    # --- 選擇目標 configuration ---
    config_name = args.config
    if config_name is None:
        if not all_configs:
            logging.getLogger("cproject_to_cmake").error("[ERROR] 找不到任何 configuration，請確認 .cproject 格式正確。")
            sys.exit(1)
        config_name = all_configs[0]
        logging.getLogger("cproject_to_cmake").info(f"[INFO] 未指定 --config，自動選擇第一個: \"{config_name}\"")
    
    cfg_node = _get_configuration_node(root, config_name)
    if cfg_node is None:
        logging.getLogger("cproject_to_cmake").error(f"[ERROR] 找不到 configurationName=\"{config_name}\"")
        logging.getLogger("cproject_to_cmake").error(f"        可用的有: {all_configs}")
        sys.exit(1)

    logging.getLogger("cproject_to_cmake").info(f"[INFO] 使用 configuration: \"{config_name}\"")

    # --- 提取資訊 ---
    defines  = extract_defines(cfg_node)
    includes = extract_includes(cfg_node)
    excludes = extract_excludes(cfg_node)

    logging.getLogger("cproject_to_cmake").info(f"[INFO] 找到 {len(defines)} 個 define macro: {defines}")
    logging.getLogger("cproject_to_cmake").info(f"[INFO] 找到 {len(includes)} 個 include path: {includes}")
    logging.getLogger("cproject_to_cmake").info(f"[INFO] 找到 {len(excludes)} 個 exclude path: {excludes}")

    # --- 讀取模板 ---
    template_path = Path(args.template)
    if not template_path.exists():
        logging.getLogger("cproject_to_cmake").error(f"[ERROR] 找不到模板檔案: {template_path}")
        sys.exit(1)

    template_content = template_path.read_text(encoding="utf-8")

    # --- 渲染並輸出 ---
    output_content = render_template(template_content, defines, includes, excludes)

    output_path = Path(args.output)
    output_path.write_text(output_content, encoding="utf-8")
    logging.getLogger("cproject_to_cmake").info(f"[INFO] 已產生: {output_path.resolve()}")


if __name__ == "__main__":
    main()
