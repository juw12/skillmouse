# Optional: start SkillMouse automatically at login + add a Start Menu entry.
# Run:  powershell -ExecutionPolicy Bypass -File install-autostart.ps1
# Undo: powershell -ExecutionPolicy Bypass -File install-autostart.ps1 -Remove
param([switch]$Remove)

$script  = Join-Path $PSScriptRoot "skillmouse.py"
$pythonw = (Get-Command pythonw.exe -ErrorAction Stop).Source
$targets = @(
    (Join-Path ([Environment]::GetFolderPath("Startup")) "SkillMouse.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Programs")) "SkillMouse.lnk")
)

foreach ($link in $targets) {
    if ($Remove) {
        Remove-Item $link -ErrorAction SilentlyContinue
        Write-Host "Removed $link"
        continue
    }
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($link)
    $shortcut.TargetPath = $pythonw
    $shortcut.Arguments = "`"$script`""
    $shortcut.WorkingDirectory = $PSScriptRoot
    $shortcut.Description = "SkillMouse - Claude/Codex skills with any model"
    $shortcut.Save()
    Write-Host "Created $link"
}
