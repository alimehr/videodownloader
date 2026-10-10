$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$form = New-Object Windows.Forms.Form
$form.Text = 'YouTube Bot - Telegram Token'
$form.Size = New-Object Drawing.Size(540, 240)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$label = New-Object Windows.Forms.Label
$label.Text = 'Paste your BotFather token below. It is saved only on this PC.'
$label.Location = New-Object Drawing.Point(20, 20)
$label.Size = New-Object Drawing.Size(490, 40)
$inputBox = New-Object Windows.Forms.TextBox
$inputBox.Location = New-Object Drawing.Point(20, 65)
$inputBox.Size = New-Object Drawing.Size(480, 28)
$inputBox.UseSystemPasswordChar = $true
$show = New-Object Windows.Forms.CheckBox
$show.Text = 'Show token'
$show.Location = New-Object Drawing.Point(20, 105)
$show.Add_CheckedChanged({ $inputBox.UseSystemPasswordChar = -not $show.Checked })
$save = New-Object Windows.Forms.Button
$save.Text = 'Save'
$save.Location = New-Object Drawing.Point(395, 145)
$save.Add_Click({
    if ($inputBox.Text.Trim() -notmatch '^\d{5,20}:[A-Za-z0-9_-]{20,100}$') {
        [Windows.Forms.MessageBox]::Show('This does not look like a BotFather token. Paste the full token.', 'Check token') | Out-Null
        return
    }
    $form.DialogResult = [Windows.Forms.DialogResult]::OK
    $form.Close()
})
$form.Controls.AddRange(@($label, $inputBox, $show, $save))
$form.AcceptButton = $save
if ($form.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { throw 'Token setup cancelled. Run Install again when ready.' }
$token = $inputBox.Text.Trim()
$envFile = Join-Path $PSScriptRoot '.env'
# Preserve other configuration when changing the token.
$lines = @()
if (Test-Path $envFile) {
    $lines = @(Get-Content $envFile | Where-Object { $_ -notmatch '^\s*BOT_TOKEN\s*=' })
} else { $lines = @('ALLOWED_USER_IDS=', 'DATA_DIR=data') }
$lines = @("BOT_TOKEN=$token") + $lines
[IO.File]::WriteAllLines($envFile, $lines, (New-Object Text.UTF8Encoding($false)))
# Restrict token file access to the current Windows user, SYSTEM, and administrators.
$acl = New-Object Security.AccessControl.FileSecurity
$acl.SetAccessRuleProtection($true, $false)
foreach ($sid in @([Security.Principal.WindowsIdentity]::GetCurrent().User, (New-Object Security.Principal.SecurityIdentifier('S-1-5-18')), (New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')))) {
    $rule = New-Object Security.AccessControl.FileSystemAccessRule($sid, 'FullControl', 'Allow')
    $acl.AddAccessRule($rule)
}
Set-Acl -Path $envFile -AclObject $acl
$inputBox.Clear()
$form.Dispose()
$token = $null
Write-Host 'Token saved. Its validity will be checked when the bot connects.' -ForegroundColor Green
