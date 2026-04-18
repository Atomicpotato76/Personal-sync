$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = "C:\Users\skyhu\AppData\Local\Programs\Python\Python310\python.exe"
$serverScript = Join-Path $projectRoot "router_server.py"
$logsDir = Join-Path $projectRoot "logs"
$stdoutLog = Join-Path $logsDir "router_server.stdout.log"
$stderrLog = Join-Path $logsDir "router_server.stderr.log"

New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
Set-Location $projectRoot

# Avoid duplicate scheduler launches if the server is already running.
$existing = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match "^python(w)?\.exe$" -and $_.CommandLine -like "*router_server.py*"
}
if ($existing) {
    exit 0
}

if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found: $pythonExe"
}

Add-Content -Path $stdoutLog -Value ("[{0}] Starting router_server.py" -f (Get-Date -Format s))
& $pythonExe $serverScript 1>> $stdoutLog 2>> $stderrLog
