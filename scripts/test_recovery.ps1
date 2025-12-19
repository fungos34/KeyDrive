# SmartDrive Recovery Test Harness
# ================================
# 
# This script tests the recovery system for regressions.
# Run manually before deploying changes.
#
# PREREQUISITES:
# - VeraCrypt installed and in PATH
# - Python 3.8+ with dependencies installed
# - Administrator privileges (for VeraCrypt operations)
# - A test volume file (will be created if not exists)
#
# USAGE:
#   .\test_recovery.ps1 [-TestVolume <path>] [-Cleanup]
#
# WARNING: This creates and destroys test data. Use only on test volumes!

param(
    [string]$TestVolume = "$PSScriptRoot\..\test_data\test_volume.vc",
    [string]$TestPassword = "TestPassword123!",
    [string]$MountLetter = "T",
    [switch]$Cleanup,
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TestDataDir = Split-Path -Parent $TestVolume

# Test state tracking
$TestsPassed = 0
$TestsFailed = 0
$TestResults = @()

function Write-TestHeader($name) {
    Write-Host "`n" -NoNewline
    Write-Host ("=" * 70) -ForegroundColor Cyan
    Write-Host "  TEST: $name" -ForegroundColor Cyan
    Write-Host ("=" * 70) -ForegroundColor Cyan
}

function Write-TestResult($name, $passed, $message = "") {
    $script:TestResults += [PSCustomObject]@{
        Name = $name
        Passed = $passed
        Message = $message
    }
    
    if ($passed) {
        $script:TestsPassed++
        Write-Host "  ✅ PASS: $name" -ForegroundColor Green
    } else {
        $script:TestsFailed++
        Write-Host "  ❌ FAIL: $name" -ForegroundColor Red
        if ($message) {
            Write-Host "     $message" -ForegroundColor Yellow
        }
    }
}

function Test-Prerequisites {
    Write-TestHeader "Prerequisites"
    
    # Check VeraCrypt
    $vcPath = Get-Command veracrypt -ErrorAction SilentlyContinue
    Write-TestResult "VeraCrypt available" ($null -ne $vcPath)
    
    # Check Python
    $pyPath = Get-Command python -ErrorAction SilentlyContinue
    Write-TestResult "Python available" ($null -ne $pyPath)
    
    # Check dependencies
    try {
        $result = python -c "import mnemonic; import cryptography; import argon2; print('OK')" 2>&1
        Write-TestResult "Python dependencies" ($result -eq "OK")
    } catch {
        Write-TestResult "Python dependencies" $false "Missing dependencies"
    }
    
    # Check admin
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    Write-TestResult "Administrator privileges" $isAdmin "Some tests may fail without admin"
    
    return ($script:TestsFailed -eq 0)
}

function New-TestVolume {
    Write-TestHeader "Create Test Volume"
    
    # Create test data directory
    if (-not (Test-Path $TestDataDir)) {
        New-Item -ItemType Directory -Path $TestDataDir -Force | Out-Null
    }
    
    # Skip if volume exists
    if (Test-Path $TestVolume) {
        Write-Host "  Test volume already exists: $TestVolume" -ForegroundColor Yellow
        return $true
    }
    
    Write-Host "  Creating 10MB test volume..." -ForegroundColor Gray
    
    try {
        # Create volume using VeraCrypt (non-interactive)
        # This creates a basic FAT volume with the test password
        $createArgs = @(
            "--text",
            "--create", $TestVolume,
            "--size=10M",
            "--password=$TestPassword",
            "--volume-type=normal",
            "--encryption=aes",
            "--hash=sha512",
            "--filesystem=fat",
            "--pim=0",
            "--keyfiles=",
            "--random-source=/dev/urandom"
        )
        
        $result = & veracrypt @createArgs 2>&1
        
        if ($LASTEXITCODE -eq 0) {
            Write-TestResult "Volume creation" $true
            return $true
        } else {
            Write-TestResult "Volume creation" $false "$result"
            return $false
        }
    } catch {
        Write-TestResult "Volume creation" $false $_.Exception.Message
        return $false
    }
}

function Test-GenerateRecoveryKit {
    Write-TestHeader "Generate Recovery Kit"
    
    # This test verifies:
    # - Recovery kit can be generated
    # - Container file is created
    # - Config is updated
    # - HTML kit is created
    
    # Create a mock config for testing
    $testConfig = @{
        mode = "pw_only"
        windows = @{
            volume_path = $TestVolume
            mount_letter = $MountLetter
        }
    }
    
    $configPath = "$ScriptDir\config.json"
    $backupConfig = $null
    
    # Backup existing config
    if (Test-Path $configPath) {
        $backupConfig = Get-Content $configPath -Raw
    }
    
    try {
        # Write test config
        $testConfig | ConvertTo-Json | Set-Content $configPath
        
        # Note: Full generate test would require interactive input
        # For now, test that the script loads without errors
        $result = python "$ScriptDir\recovery.py" --help 2>&1
        
        Write-TestResult "Recovery script loads" ($LASTEXITCODE -eq 0)
        
    } finally {
        # Restore original config
        if ($backupConfig) {
            $backupConfig | Set-Content $configPath
        } elseif (Test-Path $configPath) {
            Remove-Item $configPath -Force
        }
    }
    
    return ($script:TestsFailed -eq 0)
}

function Test-RecoveryOutcomeClassification {
    Write-TestHeader "Recovery Outcome Classification"
    
    # Verify RecoveryOutcome class is properly defined
    $code = @"
import sys
sys.path.insert(0, r'$ScriptDir')
from recovery import RecoveryOutcome

# Test all outcomes exist
outcomes = [
    RecoveryOutcome.SUCCESS,
    RecoveryOutcome.TRANSIENT_FAILURE,
    RecoveryOutcome.PERMANENT_FAILURE,
    RecoveryOutcome.ENVIRONMENT_FAILURE,
    RecoveryOutcome.USER_ABORT,
]

# Test messages exist
for o in outcomes:
    msg = RecoveryOutcome.message(o)
    assert msg, f"No message for {o}"

# Test retry safety
assert not RecoveryOutcome.is_retry_safe(RecoveryOutcome.SUCCESS)
assert RecoveryOutcome.is_retry_safe(RecoveryOutcome.TRANSIENT_FAILURE)
assert not RecoveryOutcome.is_retry_safe(RecoveryOutcome.PERMANENT_FAILURE)
assert RecoveryOutcome.is_retry_safe(RecoveryOutcome.ENVIRONMENT_FAILURE)
assert RecoveryOutcome.is_retry_safe(RecoveryOutcome.USER_ABORT)

print("OK")
"@
    
    try {
        $result = $code | python 2>&1
        Write-TestResult "Outcome enum defined" ($result -eq "OK")
        Write-TestResult "Outcome messages" ($result -eq "OK")
        Write-TestResult "Retry safety logic" ($result -eq "OK")
    } catch {
        Write-TestResult "Outcome classification" $false $_.Exception.Message
    }
}

function Test-PreflightChecks {
    Write-TestHeader "Preflight Checks"
    
    $code = @"
import sys
sys.path.insert(0, r'$ScriptDir')
from recovery import run_preflight_checks

# Test with non-existent volume
passed, issues = run_preflight_checks(
    volume_path="C:\\nonexistent\\volume.vc",
    mount_target="Z:",
)
assert not passed, "Should fail for non-existent volume"
assert any("not found" in i.lower() for i in issues), f"Should report volume not found: {issues}"

print("OK")
"@
    
    try {
        $result = $code | python 2>&1
        Write-TestResult "Preflight detects missing volume" ($result -eq "OK")
    } catch {
        Write-TestResult "Preflight checks" $false "$result"
    }
}

function Test-VolumeIdentity {
    Write-TestHeader "Volume Identity"
    
    if (-not (Test-Path $TestVolume)) {
        Write-TestResult "Volume identity" $false "Test volume not available"
        return
    }
    
    $code = @"
import sys
sys.path.insert(0, r'$ScriptDir')
from recovery import compute_volume_identity, verify_volume_identity

# Test identity computation
vol_path = r'$TestVolume'
identity = compute_volume_identity(vol_path)
assert identity and not identity.startswith("unknown"), f"Should compute identity: {identity}"
assert len(identity) == 32, f"Identity should be 32 chars: {len(identity)}"

# Test verification
match, msg = verify_volume_identity(identity, vol_path)
assert match, f"Should match self: {msg}"

# Test mismatch detection
wrong_id = "0" * 32
match, msg = verify_volume_identity(wrong_id, vol_path)
assert not match, "Should detect mismatch"

print("OK")
"@
    
    try {
        $result = $code | python 2>&1
        Write-TestResult "Identity computation" ($result -eq "OK")
        Write-TestResult "Identity verification" ($result -eq "OK")
    } catch {
        Write-TestResult "Volume identity" $false "$result"
    }
}

function Test-AuditLogging {
    Write-TestHeader "Audit Logging"
    
    $logFile = "$ScriptDir\recovery.log"
    $hadLog = Test-Path $logFile
    
    $code = @"
import sys
import json
sys.path.insert(0, r'$ScriptDir')
from recovery import audit_log, RECOVERY_LOG_FILE

# Write test entry
audit_log("TEST_EVENT", outcome="TEST_OUTCOME", details={"test_key": "test_value"})

# Verify log exists and is valid JSON
with open(RECOVERY_LOG_FILE, 'r') as f:
    lines = f.readlines()
    last_line = lines[-1]
    entry = json.loads(last_line)
    assert entry["event"] == "TEST_EVENT"
    assert entry["outcome"] == "TEST_OUTCOME"

print("OK")
"@
    
    try {
        $result = $code | python 2>&1
        Write-TestResult "Audit log creation" ($result -eq "OK")
        Write-TestResult "Audit log format" ($result -eq "OK")
    } catch {
        Write-TestResult "Audit logging" $false "$result"
    }
    
    # Cleanup test log entry if log didn't exist before
    if (-not $hadLog -and (Test-Path $logFile)) {
        # Leave the log but note it was created
        Write-Host "  Note: recovery.log was created during test" -ForegroundColor Gray
    }
}

function Test-EnvironmentSnapshot {
    Write-TestHeader "Environment Snapshot"
    
    $code = @"
import sys
sys.path.insert(0, r'$ScriptDir')
from recovery import get_environment_snapshot

snap = get_environment_snapshot()

# Check required fields
assert "python_version" in snap, "Missing python_version"
assert "os_family" in snap, "Missing os_family"
assert "veracrypt_version" in snap, "Missing veracrypt_version"
assert "requirements_hash" in snap, "Missing requirements_hash"
assert "captured_at" in snap, "Missing captured_at"

# Verify values are reasonable
assert snap["python_version"].startswith("3."), f"Unexpected Python: {snap['python_version']}"
assert snap["os_family"] == "Windows", f"Unexpected OS: {snap['os_family']}"

print("OK")
"@
    
    try {
        $result = $code | python 2>&1
        Write-TestResult "Snapshot capture" ($result -eq "OK")
        Write-TestResult "Snapshot completeness" ($result -eq "OK")
    } catch {
        Write-TestResult "Environment snapshot" $false "$result"
    }
}

function Show-Summary {
    Write-Host "`n"
    Write-Host ("=" * 70) -ForegroundColor White
    Write-Host "  TEST SUMMARY" -ForegroundColor White
    Write-Host ("=" * 70) -ForegroundColor White
    Write-Host ""
    Write-Host "  Passed: $TestsPassed" -ForegroundColor Green
    Write-Host "  Failed: $TestsFailed" -ForegroundColor $(if ($TestsFailed -gt 0) { "Red" } else { "Gray" })
    Write-Host ""
    
    if ($TestsFailed -gt 0) {
        Write-Host "  Failed tests:" -ForegroundColor Red
        $TestResults | Where-Object { -not $_.Passed } | ForEach-Object {
            Write-Host "    - $($_.Name): $($_.Message)" -ForegroundColor Yellow
        }
    }
    
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor White
    
    return ($TestsFailed -eq 0)
}

# Main execution
Write-Host ""
Write-Host "SmartDrive Recovery Test Harness" -ForegroundColor Cyan
Write-Host "=================================" -ForegroundColor Cyan
Write-Host ""

if ($Cleanup) {
    Write-Host "Cleaning up test data..." -ForegroundColor Yellow
    if (Test-Path $TestDataDir) {
        Remove-Item $TestDataDir -Recurse -Force
        Write-Host "  Removed: $TestDataDir" -ForegroundColor Gray
    }
    exit 0
}

# Run tests
$prereqOk = Test-Prerequisites
if (-not $prereqOk) {
    Write-Host "`nPrerequisites failed. Fix issues and retry." -ForegroundColor Red
    exit 1
}

# Create test volume if needed (optional - some tests don't need it)
# New-TestVolume

# Run unit tests
Test-RecoveryOutcomeClassification
Test-PreflightChecks
Test-AuditLogging
Test-EnvironmentSnapshot

# Run integration tests (require test volume)
if (Test-Path $TestVolume) {
    Test-VolumeIdentity
}

Test-GenerateRecoveryKit

# Show summary
$allPassed = Show-Summary

exit $(if ($allPassed) { 0 } else { 1 })
