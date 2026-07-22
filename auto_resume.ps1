# auto_resume.ps1 - Wait for quota refresh then resume Claude Code
# Usage:
#   powershell -ExecutionPolicy Bypass -File notes\auto_resume.ps1 -Message "continue"
#   powershell -ExecutionPolicy Bypass -File notes\auto_resume.ps1 -Messages "msg1","msg2"
#   powershell -ExecutionPolicy Bypass -File notes\auto_resume.ps1 -MessagesFile notes\messages.txt

#   powershell -ExecutionPolicy Bypass -File notes\auto_resume.ps1 -SessionId "904f8ee4-5981-423b-9cd8-354b3a71cb8a" -RefreshTime "15:07" -MessagesFile notes\claude3.txt
#   powershell -ExecutionPolicy Bypass -File notes\auto_resume.ps1 -SessionId "ba7fd91a-73d5-46a5-81a0-9fcfe5d47f90" -RefreshTime "15:05" -MessagesFile notes\claude3.txt -IntervalSeconds 1200

param(
    [string]$SessionId = "",
    [string]$RefreshTime = "12:30",
    [string]$Message = "",
    [string[]]$Messages = @(),
    [string]$MessagesFile = "",
    [int]$IntervalSeconds = 5
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding  = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$allMessages = @()

if ($MessagesFile) {
    if (-not (Test-Path $MessagesFile)) {
        Write-Host "[ERROR] MessagesFile not found: $MessagesFile" -ForegroundColor Red
        exit 1
    }
    $rawLines = Get-Content $MessagesFile -Encoding UTF8
    $buffer = ""
    foreach ($line in $rawLines) {
        if ($line.Trim() -eq "") {
            if ($buffer.Trim() -ne "") {
                $allMessages += $buffer.Trim()
                $buffer = ""
            }
            continue
        }
        if ($line.Trim().StartsWith("#")) {
            continue
        }
        if ($buffer -ne "") {
            $buffer = $buffer + [char]10 + $line
        } else {
            $buffer = $line
        }
    }
    if ($buffer.Trim() -ne "") {
        $allMessages += $buffer.Trim()
    }
    Write-Host "[INFO] Loaded $($allMessages.Count) messages from $MessagesFile"
}
elseif ($Messages.Count -gt 0) {
    $allMessages = $Messages
}
elseif ($Message) {
    $allMessages = @($Message)
}
else {
    Write-Host "[ERROR] No messages. Use -Message, -Messages, or -MessagesFile" -ForegroundColor Red
    exit 1
}

if ($allMessages.Count -eq 0) {
    Write-Host "[ERROR] No valid messages found" -ForegroundColor Red
    exit 1
}

Write-Host "========================================"
Write-Host " Claude Code Auto Resume"
Write-Host "========================================"
Write-Host ""
Write-Host "[INFO] Now: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "[INFO] Target: $RefreshTime"
Write-Host "[INFO] Messages: $($allMessages.Count) block(s)"
for ($i = 0; $i -lt $allMessages.Count; $i++) {
    $preview = ($allMessages[$i] -replace "`n", " ")
    if ($preview.Length -gt 70) { $preview = $preview.Substring(0, 70) + "..." }
    Write-Host "[INFO]   [$($i+1)] $preview"
}

if ($SessionId) {
    Write-Host "[INFO] Session: $SessionId"
} else {
    Write-Host "[INFO] Session: latest (--continue)"
}

$target = Get-Date $RefreshTime
if ($target -lt (Get-Date)) {
    $target = $target.AddDays(1)
    Write-Host "[INFO] Target passed, will wait until tomorrow $RefreshTime"
}

$waitSeconds = [int]($target - (Get-Date)).TotalSeconds
Write-Host "[INFO] Waiting $waitSeconds seconds ($([math]::Round($waitSeconds/3600, 1)) hours)"
Write-Host ""

while ($true) {
    $remaining = [int]($target - (Get-Date)).TotalSeconds
    if ($remaining -le 0) { break }
    $h = [math]::Floor($remaining / 3600)
    $m = [math]::Floor(($remaining % 3600) / 60)
    $s = $remaining % 60
    Write-Host ("`r[WAIT] {0}h {1}m {2}s remaining " -f $h, $m, $s) -NoNewline
    Start-Sleep -Seconds 10
}

Write-Host ""
Write-Host ""
Write-Host "[OK] Time is up! Launching Claude Code..."
Write-Host ""

for ($i = 0; $i -lt $allMessages.Count; $i++) {
    $msg = $allMessages[$i]
    $msgNum = $i + 1
    $msgTotal = $allMessages.Count

    $tempFile = [System.IO.Path]::GetTempFileName()
    [System.IO.File]::WriteAllText($tempFile, $msg, [System.Text.Encoding]::UTF8)
    $msgContent = Get-Content $tempFile -Raw -Encoding UTF8
    Remove-Item $tempFile -Force

    if ($i -eq 0) {
        if ($SessionId) {
            Write-Host "[SEND $msgNum/$msgTotal] Starting session $SessionId ..."
            $msgContent | claude --resume $SessionId --print
        } else {
            Write-Host "[SEND $msgNum/$msgTotal] Starting new session (--continue) ..."
            $msgContent | claude --continue --print
        }
    } else {
        Write-Host "[SEND $msgNum/$msgTotal] Resuming session ..."
        if ($SessionId) {
            $msgContent | claude --resume $SessionId --print
        } else {
            $msgContent | claude --continue --print
        }
    }

    Write-Host "[DONE $msgNum/$msgTotal] Response complete."
    Write-Host ""

    if ($i -lt ($allMessages.Count - 1)) {
        Write-Host "[WAIT] Sleeping $IntervalSeconds seconds before next message..."
        Start-Sleep -Seconds $IntervalSeconds
    }
}

Write-Host ""
Write-Host "========================================"
Write-Host " All $($allMessages.Count) messages sent."
Write-Host "========================================"
