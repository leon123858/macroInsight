import subprocess
import json
import sys

def dump_ast_and_extract(source_file, compile_flags=None):
    """
    Runs Clang with -fsyntax-only and -ast-dump=json on the modified source file.
    Extracts the values of variables starting with PROBE_.
    """
    if compile_flags is None:
        compile_flags = []
        
    lang = "c++" if source_file.endswith((".cpp", ".cxx", ".cc")) else "c"
    cmd = ["clang", "-x", lang, "-fsyntax-only", "-Xclang", "-ast-dump=json"] + compile_flags + [source_file]
    print(f"Running Clang: {' '.join(cmd)}")
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
    # Find ChooseExpr if it exists inside VarDecl's inner nodes
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
    
    # Fallback
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
    elif kind == "ConstantExpr" and "value" in node:
        try:
            return int(node.get("value", 0))
        except ValueError:
            pass
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
                    
    # Only fallback to first inner child for Cast nodes and Paren nodes
    if kind in ["ParenExpr", "ImplicitCastExpr", "CStyleCastExpr"]:
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
