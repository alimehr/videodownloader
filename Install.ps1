$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$target = Join-Path $env:LOCALAPPDATA 'YouTubeTelegramBot'
function Refresh-Path {
    $env:PATH = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}
function Install-Package([string]$id) {
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        Start-Process 'ms-windows-store://pdp/?ProductId=9NBLGGH4NNS1'
        throw 'Windows App Installer (winget) is missing. Install/update it in the Store window, then run Install again.'
    }
    Write-Host "Installing $id ..." -ForegroundColor Cyan
    & winget.exe install --id $id --exact --source winget --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
    if ($LASTEXITCODE -ne 0) { throw "Installation of $id failed (code $LASTEXITCODE). Check internet access and run Install again." }
    Refresh-Path
}
function Find-Python {
    $candidates = @((Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'), (Join-Path $env:ProgramFiles 'Python312\python.exe'))
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command -and $command.Source -notlike '*\WindowsApps\*') { $candidates += $command.Source }
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            & $candidate -c 'import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] <= (3,14) else 1)' 2>$null
            if ($LASTEXITCODE -eq 0) { return $candidate }
        }
    }
    return $null
}
function Find-Tool([string]$name) {
    $command = Get-Command "$name.exe" -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    if ($name -eq 'node') {
        $node = Join-Path $env:ProgramFiles 'nodejs\node.exe'
        if (Test-Path $node) { return $node }
    }
    if ($name -in @('ffmpeg', 'ffprobe')) {
        $root = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
        if (Test-Path $root) {
            $found = Get-ChildItem $root -Filter 'Gyan.FFmpeg*' -Directory | ForEach-Object { Get-ChildItem $_.FullName -Filter "$name.exe" -Recurse -File } | Select-Object -First 1
            if ($found) { return $found.FullName }
        }
    }
    return $null
}
try {
    Write-Host 'YouTube Telegram Bot - Windows Setup' -ForegroundColor Cyan
    Write-Host 'This online installer installs missing Python, Node.js and FFmpeg dependencies.'
    Write-Host 'Windows may ask you to approve a dependency installer. No admin terminal is required.'
    if (-not [Environment]::Is64BitOperatingSystem) { throw '64-bit Windows is required.' }
    $guard = New-Object Threading.Mutex($false, 'Local\YouTubeTelegramBotRunner')
    $acquired = $false
    try { $acquired = $guard.WaitOne(0) } catch [Threading.AbandonedMutexException] { $acquired = $true }
    if (-not $acquired) { $guard.Dispose(); throw 'Close the running bot before installing/updating.' }
    Refresh-Path
    $python = Find-Python
    if (-not $python) { Install-Package 'Python.Python.3.12'; $python = Find-Python }
    if (-not $python) { throw 'Python was not found after installation. Restart Windows, then run Install again.' }
    $node = Find-Tool 'node'
    $nodeOK = $false
    if ($node) { & $node -e 'process.exit(parseInt(process.versions.node) >= 22 ? 0 : 1)'; $nodeOK = ($LASTEXITCODE -eq 0) }
    if (-not $nodeOK) { Install-Package 'OpenJS.NodeJS.LTS'; $node = Find-Tool 'node' }
    $ffmpeg = Find-Tool 'ffmpeg'
    $ffprobe = Find-Tool 'ffprobe'
    if (-not $ffmpeg -or -not $ffprobe) { Install-Package 'Gyan.FFmpeg'; $ffmpeg = Find-Tool 'ffmpeg'; $ffprobe = Find-Tool 'ffprobe' }
    if (-not $node -or -not $ffmpeg -or -not $ffprobe) { throw 'Dependencies could not be located. Restart Windows and run Install again.' }
    foreach ($tool in @($ffmpeg, $ffprobe)) {
        & $tool -version | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'FFmpeg verification failed.' }
    }
    & $node -e 'process.exit(parseInt(process.versions.node) >= 22 ? 0 : 1)'
    if ($LASTEXITCODE -ne 0) { throw 'Node.js 22 or newer is required.' }
    New-Item $target -ItemType Directory -Force | Out-Null
    foreach ($name in @('bot.py', 'requirements.txt', 'Run.ps1', 'Configure.ps1')) {
        Copy-Item (Join-Path $PSScriptRoot "app\$name") (Join-Path $target $name) -Force
    }
    $venv = Join-Path $target '.venv\Scripts\python.exe'
    if (-not (Test-Path $venv)) {
        & $python -m venv (Join-Path $target '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Could not create Python environment.' }
    }
    Write-Host 'Installing bot libraries ...' -ForegroundColor Cyan
    & $venv -m pip install --disable-pip-version-check -r (Join-Path $target 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Python library download failed. Check your connection and run Install again.' }
    & $venv -c 'import telegram, dotenv, yt_dlp'
    if ($LASTEXITCODE -ne 0) { throw 'Python dependencies could not be loaded.' }
    $runtime = @{ paths = @((Split-Path $node), (Split-Path $ffmpeg), (Split-Path $ffprobe)) }
    [IO.File]::WriteAllText((Join-Path $target 'runtime.json'), ($runtime | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
    & (Join-Path $target 'Configure.ps1')
    $shell = New-Object -ComObject WScript.Shell
    $desktop = [Environment]::GetFolderPath('Desktop')
    foreach ($item in @(@('YouTube Bot', 'Run.ps1'), @('YouTube Bot - Change Token', 'Configure.ps1'))) {
        $shortcut = $shell.CreateShortcut((Join-Path $desktop ($item[0] + '.lnk')))
        $shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $shortcut.Arguments = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $target $item[1]) + '"'
        $shortcut.WorkingDirectory = $target
        $shortcut.Save()
    }
    $guard.ReleaseMutex(); $guard.Dispose(); $acquired = $false
    Write-Host 'Installed! Starting your bot. Desktop shortcuts are ready.' -ForegroundColor Green
    Start-Process (Join-Path $desktop 'YouTube Bot.lnk')
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
} finally {
    if ($acquired) { $guard.ReleaseMutex(); $guard.Dispose() }
}
