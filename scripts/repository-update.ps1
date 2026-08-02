param([switch]$Auto)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$settingsPath = Join-Path $root 'data\ai_workbench\repository_update.json'

if (-not $Auto) { exit 0 }
if (-not (Test-Path -LiteralPath $settingsPath)) { exit 0 }
try { $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json } catch { exit 0 }
if (-not $settings.auto_update_enabled) { exit 0 }

$origin = (& git -C $root remote get-url origin 2>$null).Trim()
if ($origin -notmatch '(^https://([^@/]+@)?github\.com/Kicgut/AiToolbox-You\.git$)|(^git@github\.com:Kicgut/AiToolbox-You\.git$)') { exit 0 }
if ((& git -C $root branch --show-current).Trim() -ne 'main') { exit 0 }
if ((& git -C $root status --porcelain)) { exit 0 }

& git -C $root fetch --quiet origin main
if ([int](& git -C $root rev-list --count HEAD..origin/main) -gt 0) {
  & git -C $root pull --ff-only origin main
}
