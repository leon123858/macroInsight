param(
    [string]$RepoUrl = "https://github.com/madler/zlib.git",
    [string]$RepoDir = ".\sample\zlib",
    [string]$Output = ".\macros_output.json"
)

$CompileCommands = Join-Path $RepoDir "build\compile_commands.json"

if (-not (Test-Path $RepoDir)) {
    Write-Host "Cloning $RepoUrl into $RepoDir..."
    git clone --depth 1 --shallow-submodules --recurse-submodules $RepoUrl $RepoDir
}

if (-not (Test-Path $CompileCommands)) {
    Write-Host "Generating compile_commands.json via CMake..."
    $BuildDir = Join-Path $RepoDir "build"
    # We must use a generator that supports compile_commands.json, e.g., NMake or Ninja, or just Visual Studio which we did manually before. 
    # Actually Visual Studio generator DOES support compile_commands.json since CMake 3.27+, but maybe to be safe, just use default.
    cmake -S $RepoDir -B $BuildDir -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
    if ($LASTEXITCODE -ne 0) {
        Write-Error "CMake failed to configure."
        exit $LASTEXITCODE
    }
}

if (Test-Path $Output) {
    Remove-Item $Output
}

if (-not (Test-Path $CompileCommands)) {
    Write-Host "compile_commands.json missing, synthesizing list of C files..."
    $files = Get-ChildItem -Path $RepoDir -Recurse -Filter "*.c" | Where-Object { $_.FullName -notmatch "\\build\\" }
    $commands = @()
    foreach ($f in $files) {
        $commands += @{
            file      = $f.FullName
            directory = $RepoDir
            command   = "clang -I$RepoDir"
        }
    }
}
else {
    Write-Host "Reading compile commands from $CompileCommands"
    $commands = Get-Content $CompileCommands -Raw | ConvertFrom-Json
}

$count = 0

foreach ($cmd in $commands) {
    if (-not ($cmd.file.EndsWith(".c") -or $cmd.file.EndsWith(".cpp") -or $cmd.file.EndsWith(".cxx"))) {
        continue
    }

    $file = $cmd.file
    if (-not [System.IO.Path]::IsPathRooted($file)) {
        $file = Join-Path $cmd.directory $file
    }

    $extractFlags = @()
    if ($cmd.command) {
        $parts = $cmd.command -split '\s+'
        foreach ($part in $parts) {
            # In Clang, include paths and defines start with -I or -D
            if ($part.StartsWith("-I") -or $part.StartsWith("-D")) {
                $extractFlags += $part
            }
        }
    }
    elseif ($cmd.arguments) {
        foreach ($arg in $cmd.arguments) {
            if ($arg.StartsWith("-I") -or $arg.StartsWith("-D")) {
                $extractFlags += $arg
            }
        }
    }

    Write-Host "Processing: $file"
    
    $pyArgs = @("run", "main.py", $file, "-o", $Output)
    if ($extractFlags.Count -gt 0) {
        $pyArgs += "-f"
        $pyArgs += $extractFlags
    }

    & uv @pyArgs
    $count++
}

Write-Host "Processed $count files via batch script."
