param(
    [string]$RepoDir = ".\sample",
    [string]$Output = ".\macros_output.json"
)

function Assert-Command {
    param([string]$CommandName, [string]$Context)
    if (-not (Get-Command $CommandName -ErrorAction SilentlyContinue)) {
        Write-Error "Environment Check Failed: '$CommandName' was not found in PATH."
        if ($Context) { Write-Host $Context -ForegroundColor Yellow }
        exit 1
    }
}

Write-Host "Verifying environment dependencies..." -ForegroundColor Cyan

# 1. 檢查 uv (Python 環境管理器)
Assert-Command "uv" "Please install 'uv' from https://github.com/astral-sh/uv."

# 2. 檢查 Python 版本 (透過 uv 確認可執行)
Write-Host "Checking Python via uv..."
$pythonVersion = & uv run python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "uv failed to run python. Please ensure uv is correctly initialized."
    exit 1
}
Write-Host "Found: $pythonVersion" -ForegroundColor Green

# 3. 檢查 Clang (Macro 解析核心)
Assert-Command "clang" "LLVM/Clang is required to parse the C AST. Please install LLVM and add it to your PATH."
$clangVersion = & clang --version 2>&1 | Select-Object -First 1
Write-Host "Found: $clangVersion" -ForegroundColor Green

# 4. 檢查 CMake (產生 compile_commands.json 用)
Assert-Command "cmake" "CMake is required to generate compile commands. Please install CMake and add it to your PATH."
$cmakeVersion = & cmake --version 2>&1 | Select-Object -First 1
Write-Host "Found: $cmakeVersion" -ForegroundColor Green

Write-Host "`nEnvironment checks passed. Running MacroInsight via Python...`n" -ForegroundColor Cyan
& uv run main.py --repo-dir $RepoDir --output $Output

if ($LASTEXITCODE -eq 0) {
    Write-Host "MacroInsight completed successfully."
}
else {
    Write-Error "MacroInsight failed."
    exit $LASTEXITCODE
}
