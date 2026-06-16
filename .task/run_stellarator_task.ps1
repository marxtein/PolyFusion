$ErrorActionPreference = "Continue"
$taskDir = "E:\work\digitalfusion-release\.task"
$promptFile = Join-Path $taskDir "stellarator_task_prompt.txt"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = Join-Path $taskDir "output_$timestamp.log"

# Log header
"=== Claude Code Stellarator Task ===" | Out-File -FilePath $logFile -Encoding UTF8
"Started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Out-File -FilePath $logFile -Encoding UTF8 -Append
"Log file: $logFile" | Out-File -FilePath $logFile -Encoding UTF8 -Append
"====================================" | Out-File -FilePath $logFile -Encoding UTF8 -Append

# Set working directory
Set-Location "E:\work\digitalfusion-release"
$env:PYTHONPATH = "E:\work\digitalfusion-release"

# Read prompt
$prompt = Get-Content $promptFile -Raw

# Run Claude Code with full autonomy
# --permission-mode bypassPermissions: auto-accept all tool calls
# --add-dir: grant access to both repos
# -p: non-interactive print mode
"Launching claude -p ..." | Out-File -FilePath $logFile -Encoding UTF8 -Append

$prompt | & claude -p `
    --permission-mode bypassPermissions `
    --add-dir "E:\work\digitalfusion-release" `
    --add-dir "E:\work\digitalfusion-compare\pyQSC" `
    --output-format text `
    2>&1 | Out-File -FilePath $logFile -Encoding UTF8 -Append

"Completed: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Out-File -FilePath $logFile -Encoding UTF8 -Append
