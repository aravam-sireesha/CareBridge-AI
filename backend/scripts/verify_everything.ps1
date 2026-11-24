# Runs every check that does NOT need your real database, then prints one PASS/FAIL table.
# From the project folder that contains both "backend" and "frontend":   .\backend\scripts\verify_everything.ps1
# (Activate the backend virtual environment first.)   The database and GPS checks are in MANUAL_VERIFICATION.md.
$ErrorActionPreference = "Continue"
$backend  = Join-Path $PSScriptRoot ".."
$frontend = Join-Path $PSScriptRoot "..\..\frontend"
$results  = @()
function Step([string]$name, [string]$dir, [string]$command) {
    Write-Host "`n=== $name ===" -ForegroundColor Cyan
    Push-Location $dir
    try { Invoke-Expression $command; $ok = ($LASTEXITCODE -eq 0) } catch { $ok = $false; Write-Host $_ -ForegroundColor Red }
    Pop-Location
    $script:results += [pscustomobject]@{ Step = $name; Result = $(if ($ok) { "PASS" } else { "FAIL" }) }
}
Step "Backend: static consistency check"       $backend  "python scripts\static_check.py"
Step "Backend: migration tests (SQLite)"        $backend  "python -m pytest tests\test_migrations_sqlite.py -q"
Step "Backend: pure-logic tests"                $backend  "python -m pytest tests\test_geo.py tests\test_otp.py tests\test_delivery_flow.py tests\test_matching_center.py tests\test_kb_ingest.py tests\test_tracking.py tests\test_availability.py tests\test_sms.py -q"
Step "Backend: API tests for the new features"  $backend  "python -m pytest tests\test_locations.py tests\test_otp_api.py tests\test_deliveries_api.py tests\test_kb_upload_api.py tests\test_email_verification_api.py -q"
Step "Backend: the whole test suite"            $backend  "python -m pytest -q"
Step "Frontend: install packages"               $frontend "npm install"
Step "Frontend: tests"                          $frontend "npm test"
Step "Frontend: production build"               $frontend "npm run build"
Write-Host "`n==== SUMMARY ====" -ForegroundColor Cyan
$results | Format-Table -AutoSize
if ($results.Result -contains "FAIL") { Write-Host "Something failed. Send the output of the FAIL step(s) back so it can be fixed." -ForegroundColor Yellow; exit 1 }
Write-Host "All checks passed. Now do the database and GPS checks in MANUAL_VERIFICATION.md." -ForegroundColor Green
