$ErrorActionPreference = 'Stop'
$mutex = New-Object Threading.Mutex($false, 'Local\YouTubeTelegramBotRunner')
$owned = $false
try {
    try { $owned = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $owned = $true }
    if (-not $owned) { Write-Host 'The bot is already running. Use the existing window.'; Start-Sleep -Seconds 3; exit 0 }
    Set-Location $PSScriptRoot
    $runtime = Get-Content (Join-Path $PSScriptRoot 'runtime.json') -Raw | ConvertFrom-Json
    $env:PATH = ($runtime.paths -join ';') + ';' + $env:PATH
    Write-Host 'YouTube Bot is starting. Keep this window open.' -ForegroundColor Cyan
    Write-Host 'Send /start to your Telegram bot. Press Ctrl+C to stop.'
    Write-Host 'Internet access to Telegram and YouTube is required.'
    & (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'bot.py')
    if ($LASTEXITCODE -ne 0) { throw 'Bot stopped with an error. Check your connection and token (Change Token shortcut).' }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    Read-Host 'Press Enter to close'
} finally {
    if ($owned) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
