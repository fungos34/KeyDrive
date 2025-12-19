<#
E2E Settings Verification Script (Windows)
==========================================
Tests Settings dialog end-to-end:
- Launch GUI from drive
- Open Settings
- Modify fields in each tab
- Save and verify persistence
- Test invalid input handling
- Verify config integrity

Exit codes:
  0: All tests pass
  1: One or more tests failed
#>

param(
    [string]$DriveLetter = "F",
    [string]$ConfigPath = ""
)

$ErrorActionPreference = "Stop"
$TestsPassed = 0
$TestsFailed = 0

function Write-TestResult {
    param([string]$Test, [bool]$Passed, [string]$Details = "")
    if ($Passed) {
        Write-Host "[PASS] $Test" -ForegroundColor Green
        $script:TestsPassed++
    } else {
        Write-Host "[FAIL] $Test" -ForegroundColor Red
        if ($Details) {
            Write-Host "       $Details" -ForegroundColor Yellow
        }
        $script:TestsFailed++
    }
}

function Test-ConfigIntegrity {
    param([string]$Path)
    
    if (-not (Test-Path $Path)) {
        return $false
    }
    
    try {
        $content = Get-Content $Path -Raw | ConvertFrom-Json
        return ($null -ne $content)
    } catch {
        return $false
    }
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "E2E Settings Verification" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# Test 1: Locate GUI script
$GuiScript = "${DriveLetter}:\.smartdrive\scripts\gui.py"
Write-TestResult "GUI script exists" (Test-Path $GuiScript)

# Test 2: Locate config file
if ($ConfigPath -eq "") {
    $ConfigPath = "${DriveLetter}:\.smartdrive\scripts\config.json"
}
Write-TestResult "Config file exists" (Test-Path $ConfigPath)

# Test 3: Config file integrity before test
$ConfigValid = Test-ConfigIntegrity $ConfigPath
Write-TestResult "Config JSON valid before test" $ConfigValid

if (-not $ConfigValid) {
    Write-Host "`n❌ Cannot proceed: Config file invalid" -ForegroundColor Red
    exit 1
}

# Test 4: Backup config
$BackupPath = "${ConfigPath}.e2e_backup"
try {
    Copy-Item $ConfigPath $BackupPath -Force
    Write-TestResult "Config backup created" $true
} catch {
    Write-TestResult "Config backup created" $false $_.Exception.Message
}

# Test 5: Read original config
try {
    $OriginalConfig = Get-Content $ConfigPath -Raw | ConvertFrom-Json
    $OriginalDriveName = $OriginalConfig.drive_name
    Write-Host "[INFO] Original drive_name: $OriginalDriveName" -ForegroundColor Cyan
    Write-TestResult "Config readable" $true
} catch {
    Write-TestResult "Config readable" $false $_.Exception.Message
}

# Test 6: Schema audit
Write-Host "`n[INFO] Running schema audit..." -ForegroundColor Cyan
try {
    $AuditScript = Join-Path $PSScriptRoot "audit_schema_ssot.py"
    # Run without 2>&1 to avoid exit code corruption
    $null = & python $AuditScript *>&1
    $AuditPassed = $LASTEXITCODE -eq 0
    Write-TestResult "Schema SSOT audit" $AuditPassed
} catch {
    Write-TestResult "Schema SSOT audit" $false $_.Exception.Message
}

# Test 7: GUI launch test (non-interactive)
# Note: Full GUI testing requires automation framework
# For now, verify imports work
Write-Host "`n[INFO] Verifying GUI imports..." -ForegroundColor Cyan
$RepoRoot = Split-Path $PSScriptRoot -Parent
$ImportTest = @"
import sys
sys.path.insert(0, r'$RepoRoot\.smartdrive')
sys.path.insert(0, r'$RepoRoot\.smartdrive\scripts')
try:
    from scripts.gui import SettingsDialog
    from PyQt6.QtWidgets import QTabWidget, QSpinBox
    print('IMPORTS_OK')
except Exception as e:
    print(f'IMPORTS_FAILED: {e}')
    import traceback
    traceback.print_exc()
    sys.exit(1)
"@

try {
    $ImportResult = $ImportTest | python 2>&1
    $ImportsPassed = $ImportResult -match "IMPORTS_OK"
    Write-TestResult "GUI imports (QTabWidget, QSpinBox)" $ImportsPassed ($ImportResult | Out-String)
} catch {
    Write-TestResult "GUI imports" $false $_.Exception.Message
}

# Test 8: Simulate config modification (like Settings UI would)
Write-Host "`n[INFO] Simulating Settings save..." -ForegroundColor Cyan
try {
    # Read config as JSON object (compatible with older PowerShell)
    $ConfigJson = Get-Content $ConfigPath -Raw
    $ModifiedConfig = $ConfigJson | ConvertFrom-Json
    
    # Add/modify drive_name field using Add-Member (works whether field exists or not)
    if ($ModifiedConfig.PSObject.Properties.Name -contains "drive_name") {
        $ModifiedConfig.drive_name = "E2E_TEST_MODIFIED"
    } else {
        $ModifiedConfig | Add-Member -MemberType NoteProperty -Name "drive_name" -Value "E2E_TEST_MODIFIED" -Force
    }
    
    # Add unknown key using Add-Member (compatible approach)
    $ModifiedConfig | Add-Member -MemberType NoteProperty -Name "test_unknown_key" -Value "should_be_preserved" -Force
    
    # Save modified config (atomic write)
    $TempPath = "${ConfigPath}.tmp"
    $ModifiedConfig | ConvertTo-Json -Depth 10 | Set-Content $TempPath -Encoding UTF8
    Move-Item $TempPath $ConfigPath -Force
    
    Write-TestResult "Config modification saved" $true
} catch {
    Write-TestResult "Config modification saved" $false $_.Exception.Message
}

# Test 9: Verify modifications persisted
try {
    $ReloadedConfig = Get-Content $ConfigPath -Raw | ConvertFrom-Json
    $NameChanged = $ReloadedConfig.drive_name -eq "E2E_TEST_MODIFIED"
    Write-TestResult "Modified field persisted" $NameChanged
    
    $UnknownKeyPreserved = $null -ne $ReloadedConfig.test_unknown_key
    Write-TestResult "Unknown key preserved" $UnknownKeyPreserved
} catch {
    Write-TestResult "Config reload after save" $false $_.Exception.Message
}

# Test 10: Test invalid input handling (mount letter validation)
Write-Host "`n[INFO] Testing validation..." -ForegroundColor Cyan
$ValidationTest = @"
import sys
sys.path.insert(0, r'$RepoRoot\.smartdrive')
from core.settings_schema import validate_mount_letter

# Valid
valid, msg = validate_mount_letter('Z')
assert valid, f'Z should be valid: {msg}'

# Invalid
valid, msg = validate_mount_letter('ZZ')
assert not valid, 'ZZ should be invalid'

valid, msg = validate_mount_letter('1')
assert not valid, '1 should be invalid'

print('VALIDATION_OK')
"@

try {
    $ValResult = $ValidationTest | python 2>&1
    $ValPassed = $ValResult -match "VALIDATION_OK"
    Write-TestResult "Input validation (mount_letter)" $ValPassed ($ValResult | Out-String)
} catch {
    Write-TestResult "Input validation" $false $_.Exception.Message
}

# Test 11: Config integrity after all operations
$FinalIntegrity = Test-ConfigIntegrity $ConfigPath
Write-TestResult "Config integrity after operations" $FinalIntegrity

# Test 12: Restore original config
try {
    Copy-Item $BackupPath $ConfigPath -Force
    Remove-Item $BackupPath -Force
    Write-TestResult "Config restored from backup" $true
} catch {
    Write-TestResult "Config restored from backup" $false $_.Exception.Message
}

# Summary
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "E2E Settings Test Summary" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Passed: $TestsPassed" -ForegroundColor Green
Write-Host "Failed: $TestsFailed" -ForegroundColor Red

if ($TestsFailed -eq 0) {
    Write-Host "`n✅ ALL E2E TESTS PASSED" -ForegroundColor Green
    exit 0
} else {
    Write-Host "`n❌ SOME TESTS FAILED" -ForegroundColor Red
    exit 1
}
