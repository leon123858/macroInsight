param(
    [string]$RepoDir = ".\sample",
    [string]$Output = ".\macros_output.json"
)

Write-Host "Running MacroInsight via Python..."
& uv run main.py --repo-dir $RepoDir --output $Output

if ($LASTEXITCODE -eq 0) {
    Write-Host "MacroInsight completed successfully."
}
else {
    Write-Error "MacroInsight failed."
    exit $LASTEXITCODE
}
