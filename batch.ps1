param(
    [string]$RepoDir = ".\sample",
    [string]$Output = "",
    [ValidateSet("json", "xml")]
    [string]$OutputFormat = "json",
    [string]$Clang = "clang",
    [switch]$CompileFallback,
    [string]$CProjectConfig = ""
)

# Default output filename depends on the chosen format
if ($Output -eq "") {
    $Output = ".\macros_output.$OutputFormat"
}

function Assert-Command {
    param([string]$CommandName, [string]$Context)
    if (-not (Get-Command $CommandName -ErrorAction SilentlyContinue)) {
        Write-Error "Environment Check Failed: '$CommandName' was not found in PATH."
        if ($Context) { Write-Host $Context -ForegroundColor Yellow }
        exit 1
    }
}

Write-Host "Verifying environment dependencies..." -ForegroundColor Cyan

# 1. 決定使用 uv run python 還是純 python
$pythonExec = @()
if (Get-Command "uv" -ErrorAction SilentlyContinue) {
    Write-Host "Checking Python via uv..."
    $pythonVersion = & uv run python --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "uv is installed but failed to run python. Please ensure uv is correctly initialized."
        exit 1
    }
    Write-Host "Found: $pythonVersion" -ForegroundColor Green
    $pythonExec = @("uv", "run", "python")
}
else {
    Write-Host "'uv' not found. Falling back to global python..." -ForegroundColor Yellow
    Assert-Command "python" "Please install Python and add it to your PATH."
    $pythonVersion = & python --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Python failed to run."
        exit 1
    }
    Write-Host "Found: $pythonVersion" -ForegroundColor Green
    $pythonExec = @("python")
}

# 2. 檢查自定義 Clang 執行檔 (Macro 解析核心)
Assert-Command $Clang "The specified clang executable '$Clang' is required to parse the C AST. Please install it and add it to your PATH."
$clangVersion = & $Clang --version 2>&1 | Select-Object -First 1
Write-Host "Found Compiler: $clangVersion" -ForegroundColor Green

# 3. 檢查 CMake (產生 compile_commands.json 用)
Assert-Command "cmake" "CMake is required to generate compile commands. Please install CMake and add it to your PATH."
$cmakeVersion = & cmake --version 2>&1 | Select-Object -First 1
Write-Host "Found: $cmakeVersion" -ForegroundColor Green

Write-Host "`nEnvironment checks passed. Running MacroInsight...`n" -ForegroundColor Cyan

# ── Auto-generate CMakeLists.txt from .cproject ──────────────────────────────
$cmakeListsPath = Join-Path $RepoDir "CMakeLists.txt"
$cprojectPath = Join-Path $RepoDir ".cproject"

if (-not (Test-Path $cmakeListsPath) -and ($CProjectConfig -ne "")) {
    Write-Host "No CMakeLists.txt found in '$RepoDir'." -ForegroundColor Yellow

    if (Test-Path $cprojectPath) {
        Write-Host "Found .cproject - generating CMakeLists.txt via cproject_to_cmake.py ..." -ForegroundColor Cyan

        # cmake_template.txt 與本腳本放在同一目錄
        $templatePath = Join-Path $PSScriptRoot "cmake_template.txt"

        $genArgs = @(
            "cproject_to_cmake.py",
            "--cproject", $cprojectPath,
            "--template", $templatePath,
            "--output", $cmakeListsPath
        )
        if ($CProjectConfig -ne "") {
            $genArgs += @("--config", $CProjectConfig)
        }

        $genCmd = $pythonExec + $genArgs
        & $genCmd[0] $genCmd[1..($genCmd.Length - 1)]

        if ($LASTEXITCODE -ne 0) {
            Write-Error "cproject_to_cmake.py failed. Cannot continue without CMakeLists.txt."
            exit $LASTEXITCODE
        }

        Write-Host "CMakeLists.txt generated successfully.`n" -ForegroundColor Green
    }
    else {
        Write-Warning "No .cproject found either. main.py will proceed without CMakeLists.txt."
    }
}
# ─────────────────────────────────────────────────────────────────────────────

$pyArgs = @("main.py", "--repo-dir", $RepoDir, "--output", $Output, "--output-format", $OutputFormat, "--clang", $Clang)
if ($CompileFallback) {
    $pyArgs += "--compile-fallback"
}
$fullCmd = $pythonExec + $pyArgs

# 執行 python 陣列指令
& $fullCmd[0] $fullCmd[1..($fullCmd.Length - 1)]

if ($LASTEXITCODE -eq 0) {
    Write-Host "`nMacroInsight completed successfully." -ForegroundColor Green
}
else {
    Write-Error "`nMacroInsight failed."
    exit $LASTEXITCODE
}
