import subprocess
import json
import sys

# Create a clean ascii file
with open("test.c", "w", encoding="ascii") as f:
    f.write("long long foo = __builtin_choose_expr(__builtin_constant_p(0), (long long)(0), -9999LL);\n")

# Run clang
res = subprocess.run(["clang", "-Xclang", "-ast-dump=json", "-fsyntax-only", "test.c"], capture_output=True, text=True)
if res.returncode != 0:
    print("clang failed:", res.stderr)
    sys.exit(1)

# Dump it
ast = json.loads(res.stdout)

def visit(node):
    if not isinstance(node, dict): return
    if node.get("kind") == "ChooseExpr":
        print(json.dumps(node, indent=2))
        return
    for c in node.get("inner", []):
        visit(c)

visit(ast)
