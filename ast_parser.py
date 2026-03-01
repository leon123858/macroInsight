import subprocess
import json
import sys

def dump_ast_and_extract(source_file, compile_flags=None, clang_exec="clang"):
    """
    Runs Clang with -fsyntax-only and -ast-dump=json on the modified source file.
    Extracts the values of variables starting with PROBE_.
    """
    if compile_flags is None:
        compile_flags = []
        
    lang = "c++" if source_file.endswith((".cpp", ".cxx", ".cc")) else "c"
    cmd = [clang_exec, "-x", lang, "-fsyntax-only", "-Xclang", "-ast-dump=json"] + compile_flags + [source_file]
    print(f"Running AST Dump: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, errors='replace')
    
    try:
        ast_data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        print("Failed to decode Clang AST JSON. Output might be too large or malformed.", file=sys.stderr)
        raise e
        
    extracted_macros = {}
    
    def visit_node(node):
        if not isinstance(node, dict):
            return
            
        if node.get("kind") == "VarDecl":
            name = node.get("name", "")
            if name.startswith("PROBE_"):
                macro_name = name[len("PROBE_"):]
                
                extracted_val = extract_value_from_vardecl(node)
                if extracted_val is not None:
                    extracted_macros[macro_name] = extracted_val
                else:
                    print(f"DEBUG: Failed to extract {macro_name} from VarDecl")
                    
        if "inner" in node:
            for child in node["inner"]:
                visit_node(child)

    visit_node(ast_data)
    return extracted_macros


def extract_value_from_vardecl(node):
    """
    Extract the integer value from a VarDecl initialization.
    Handles ChooseExpr correctly by evaluating the condition.
    """
    choose_expr = find_node_of_kind(node, "ChooseExpr")
    
    if choose_expr:
        inner = choose_expr.get("inner", [])
        if len(inner) >= 3:
            cond_node = inner[0]
            true_branch = inner[1]
            false_branch = inner[2]
            
            cond_val = extract_literal_value(cond_node)
            if cond_val is not None and cond_val != 0:
                return extract_literal_value(true_branch)
            else:
                return extract_literal_value(false_branch)
    
    # Fallback to evaluating the initialization expression directly if ChooseExpr isn't present
    if "inner" in node:
        for child in node["inner"]:
            val = extract_literal_value(child)
            if val is not None:
                return val
                
    return extract_literal_value(node)


def find_node_of_kind(node, target_kind):
    if not isinstance(node, dict):
        return None
    if node.get("kind") == target_kind:
        return node
    if "inner" in node:
        for child in node["inner"]:
            res = find_node_of_kind(child, target_kind)
            if res:
                return res
    return None


def extract_literal_value(node):
    if not isinstance(node, dict):
        return None
        
    kind = node.get("kind")
    if kind == "IntegerLiteral":
        return int(node.get("value", 0))
    elif kind == "CharacterLiteral":
        return int(node.get("value", 0))
    elif kind == "ConstantExpr" and "value" in node:
        try:
            return int(node.get("value", 0))
        except ValueError:
            pass
    elif kind == "UnaryExprOrTypeTraitExpr":
        # e.g. sizeof
        name = node.get("name")
        if name == "sizeof":
            arg_type = node.get("argType", {}).get("qualType", "")
            # Basic fallback sizes for typical 64-bit systems
            # For complex structs or arrays, we'd need more logic, but this covers basic types and simple arrays
            # Let's extract array size if it matches e.g. 'int[10]'
            import re
            arr_match = re.match(r'(.+)\[(\d+)\]', arg_type)
            if arr_match:
                base_type = arr_match.group(1).strip()
                count = int(arr_match.group(2))
                sizes = {
                    "char": 1, "signed char": 1, "unsigned char": 1,
                    "short": 2, "unsigned short": 2,
                    "int": 4, "unsigned int": 4, "float": 4,
                    "long": 4, "unsigned long": 4, # Standard Windows long is 4 bytes
                    "long long": 8, "unsigned long long": 8, "double": 8,
                }
                if base_type in sizes:
                    return sizes[base_type] * count
            
            # Simple types
            sizes = {
                "char": 1, "signed char": 1, "unsigned char": 1,
                "short": 2, "unsigned short": 2,
                "int": 4, "unsigned int": 4, "float": 4,
                "long": 4, "unsigned long": 4,
                "long long": 8, "unsigned long long": 8, "double": 8,
            }
            if arg_type in sizes:
                return sizes[arg_type]
            if "*" in arg_type:
                return 8 # 64-bit pointer
            
        return None
    elif kind == "UnaryOperator":
        opcode = node.get("opcode")
        inner = node.get("inner", [])
        if inner:
            val = extract_literal_value(inner[0])
            if val is not None:
                if opcode == "-": return -val
                if opcode == "~": return ~val
                if opcode == "+": return val
                if opcode == "!": return 1 if val == 0 else 0
                return val
    elif kind == "BinaryOperator":
        opcode = node.get("opcode")
        inner = node.get("inner", [])
        if len(inner) >= 2:
            left = extract_literal_value(inner[0])
            right = extract_literal_value(inner[1])
            if left is not None and right is not None:
                if opcode == "+": return left + right
                if opcode == "-": return left - right
                if opcode == "*": return left * right
                if opcode == "/": return left // right if right != 0 else 0
                if opcode == "%": return left % right if right != 0 else 0
                if opcode == "|": return left | right
                if opcode == "&": return left & right
                if opcode == "^": return left ^ right
                if opcode == "<<": return left << right
                if opcode == ">>": return left >> right
                if opcode == "<": return 1 if left < right else 0
                if opcode == "<=": return 1 if left <= right else 0
                if opcode == ">": return 1 if left > right else 0
                if opcode == ">=": return 1 if left >= right else 0
                if opcode == "==": return 1 if left == right else 0
                if opcode == "!=": return 1 if left != right else 0
                if opcode == "&&": return 1 if (left != 0 and right != 0) else 0
                if opcode == "||": return 1 if (left != 0 or right != 0) else 0
    elif kind == "ConditionalOperator":
        inner = node.get("inner", [])
        if len(inner) >= 3:
            cond = extract_literal_value(inner[0])
            if cond is not None:
                if cond != 0:
                    return extract_literal_value(inner[1])
                else:
                    return extract_literal_value(inner[2])
                    
    # Fallback to first inner child for Cast nodes and Paren nodes (including BuiltinBitCastExpr)
    if kind in ["ParenExpr", "ImplicitCastExpr", "CStyleCastExpr", "BuiltinBitCastExpr"]:
        if "inner" in node:
            for child in node["inner"]:
                res = extract_literal_value(child)
                if res is not None:
                    return res
    return None

if __name__ == "__main__":
    if len(sys.argv) > 1:
        res = dump_ast_and_extract(sys.argv[1])
        print(json.dumps(res, indent=2))
    else:
        print("Usage: python ast_parser.py <source.probe.c>")
