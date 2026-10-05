# AI Story & Video Studio - PowerShell Launcher

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ScriptDir ".venv\Scripts\python.exe"

if (Test-Path $VenvPython) {
    $PythonExe = $VenvPython
} else {
    $PythonExe = "python"
}

Write-Host "====================================================================" -ForegroundColor Green
Write-Host "           STARTING AI STORY & VIDEO STUDIO WEB APP" -ForegroundColor Green
Write-Host "====================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Using Python: $PythonExe" -ForegroundColor Yellow
Write-Host "Launching Server on http://127.0.0.1:5000..." -ForegroundColor Cyan
Write-Host ""

Start-Process "http://127.0.0.1:5000"

& $PythonExe "$ScriptDir\studio\app.py"
