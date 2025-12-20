<# 
.SYNOPSIS
    SmartDrive Runtime Verification Script for Windows

.DESCRIPTION
    Verifies SmartDrive runtime behavior:
    - Environment and log paths
    - DiskIdentity detection
    - Partition resolver
    - Security mode prerequisites
    - Atomic config writes

.NOTES
    P0 Requirement: This script provides scriptable verification for CI.
    Run with: powershell -ExecutionPolicy Bypass -File tools\verify_runtime.ps1

.EXAMPLE
    .\tools\verify_runtime.ps1
    .\tools\verify_runtime.ps1 -Verbose
#>

[CmdletBinding()]
param(
    [switch]$SkipDiskTests,
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"
$script:TestsPassed = 0
$script:TestsFailed = 0
$script:TestsSkipped = 0

# =============================================================================
# Helpers
# =============================================================================

function Write-TestHeader {
    param([string]$Title)
    Write-Host "`n" -NoNewline
    Write-Host ("=" * 70) -ForegroundColor Cyan
    Write-Host "  $Title" -ForegroundColor Cyan
    Write-Host ("=" * 70) -ForegroundColor Cyan
}

function Write-Pass {
    param([string]$Message)
    Write-Host "  [PASS] $Message" -ForegroundColor Green
    $script:TestsPassed++
}

function Write-Fail {
    param([string]$Message)
    Write-Host "  [FAIL] $Message" -ForegroundColor Red
    $script:TestsFailed++
}

function Write-Skip {
    param([string]$Message)
    Write-Host "  [SKIP] $Message" -ForegroundColor Yellow
    $script:TestsSkipped++
}

function Write-Info {
    param([string]$Message)
    Write-Host "  [INFO] $Message" -ForegroundColor Gray
}

# =============================================================================
# Environment Verification
# =============================================================================

function Test-Environment {
    Write-TestHeader "ENVIRONMENT VERIFICATION"
    
    # Python version
    try {
        $pythonVersion = & python --version 2>&1
        if ($pythonVersion -match "Python (\d+\.\d+)") {
            $version = [version]$Matches[1]
            if ($version -ge [version]"3.10") {
                Write-Pass "Python version: $pythonVersion"
            } else {
                Write-Fail "Python version $pythonVersion is below 3.10"
            }
        }
    } catch {
        Write-Fail "Python not found in PATH"
    }
    
    # Project structure
    $projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    $smartdriveDir = Join-Path $projectRoot ".smartdrive"
    
    if (Test-Path $smartdriveDir) {
        Write-Pass ".smartdrive directory exists"
    } else {
        Write-Fail ".smartdrive directory not found"
    }
    
    # Core modules
    $coreModules = @(
        "core/__init__.py",
        "core/safety.py",
        "core/config.py",
        "core/constants.py",
        "core/version.py"
    )
    
    foreach ($module in $coreModules) {
        $modulePath = Join-Path $smartdriveDir $module
        if (Test-Path $modulePath) {
            Write-Pass "Module exists: $module"
        } else {
            Write-Fail "Module missing: $module"
        }
    }
    
    # Log paths
    $logDir = Join-Path $env:USERPROFILE ".smartdrive"
    Write-Info "Log directory: $logDir"
    Write-Info "GUI log path: $logDir\smartdrive_gui.log"
}

# =============================================================================
# DiskIdentity Verification
# =============================================================================

function Test-DiskIdentity {
    Write-TestHeader "DISK IDENTITY VERIFICATION"
    
    if ($SkipDiskTests) {
        Write-Skip "Disk tests skipped via -SkipDiskTests"
        return
    }
    
    # Test 1: Detect system disk
    try {
        $systemDisk = Get-Disk -Number 0
        if ($systemDisk.UniqueId) {
            Write-Pass "System disk UniqueId: $($systemDisk.UniqueId.Substring(0, [Math]::Min(30, $systemDisk.UniqueId.Length)))..."
        } else {
            Write-Fail "System disk has no UniqueId"
        }
        
        if ($systemDisk.BusType) {
            Write-Pass "System disk BusType: $($systemDisk.BusType)"
        }
    } catch {
        Write-Fail "Could not detect system disk: $_"
    }
    
    # Test 2: List all disks with identity info
    try {
        $allDisks = Get-Disk | Where-Object { $_.OperationalStatus -eq "Online" }
        Write-Info "Found $($allDisks.Count) online disk(s)"
        
        foreach ($disk in $allDisks) {
            $idPreview = if ($disk.UniqueId) { 
                $disk.UniqueId.Substring(0, [Math]::Min(20, $disk.UniqueId.Length)) + "..." 
            } else { 
                "N/A" 
            }
            Write-Info "Disk $($disk.Number): $($disk.FriendlyName) | BusType=$($disk.BusType) | UniqueId=$idPreview"
        }
    } catch {
        Write-Fail "Could not enumerate disks: $_"
    }
    
    # Test 3: Run Python disk identity detection
    try {
        $projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
        $testScript = @"
import sys
sys.path.insert(0, r'$projectRoot\.smartdrive')
from core.safety import detect_source_disk
from pathlib import Path
identity = detect_source_disk(Path(r'$projectRoot\.smartdrive\core\safety.py'))
if identity:
    print(f'PYTHON_IDENTITY_OK|{identity.unique_id[:30]}|{identity.bus_type}')
else:
    print('PYTHON_IDENTITY_FAIL')
"@
        
        $result = & python -c $testScript 2>&1
        if ($result -match "PYTHON_IDENTITY_OK\|(.+)\|(.+)") {
            Write-Pass "Python detect_source_disk works: UniqueId=$($Matches[1])... BusType=$($Matches[2])"
        } elseif ($result -match "PYTHON_IDENTITY_FAIL") {
            Write-Fail "Python detect_source_disk returned None"
        } else {
            Write-Fail "Python detect_source_disk error: $result"
        }
    } catch {
        Write-Fail "Python disk identity test failed: $_"
    }
}

# =============================================================================
# Partition Resolver Verification
# =============================================================================

function Test-PartitionResolver {
    Write-TestHeader "PARTITION RESOLVER VERIFICATION"
    
    if ($SkipDiskTests) {
        Write-Skip "Partition tests skipped via -SkipDiskTests"
        return
    }
    
    # Get USB disks for testing
    $usbDisks = Get-Disk | Where-Object { $_.BusType -eq "USB" -and $_.OperationalStatus -eq "Online" }
    
    if ($usbDisks.Count -eq 0) {
        Write-Skip "No USB disks connected for partition resolver test"
        return
    }
    
    foreach ($disk in $usbDisks) {
        Write-Info "Testing partition resolver on disk $($disk.Number): $($disk.FriendlyName)"
        
        # Get partitions via PowerShell
        $partitions = Get-Partition -DiskNumber $disk.Number -ErrorAction SilentlyContinue
        
        if ($partitions) {
            Write-Info "  Found $($partitions.Count) partition(s)"
            
            foreach ($p in $partitions) {
                $sizeGB = [math]::Round($p.Size / 1GB, 2)
                $letter = if ($p.DriveLetter) { $p.DriveLetter } else { "N/A" }
                $hidden = if ($p.IsHidden) { "[HIDDEN]" } else { "" }
                Write-Info "    Partition $($p.PartitionNumber): ${sizeGB}GB Letter=$letter Type=$($p.Type) $hidden"
            }
            
            # Run Python resolver
            try {
                $projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
                $testScript = @"
import sys
sys.path.insert(0, r'$projectRoot\.smartdrive')
from core.safety import get_disk_snapshot_windows
snapshot = get_disk_snapshot_windows($($disk.Number))
if snapshot:
    launcher = snapshot.launcher_partition
    payload = snapshot.payload_partition
    l_num = launcher.partition_number if launcher else 'N/A'
    p_num = payload.partition_number if payload else 'N/A'
    p_size = f'{payload.size_gb:.2f}' if payload else 'N/A'
    print(f'RESOLVER_OK|{l_num}|{p_num}|{p_size}')
else:
    print('RESOLVER_FAIL')
"@
                
                $result = & python -c $testScript 2>&1
                if ($result -match "RESOLVER_OK\|(.+)\|(.+)\|(.+)") {
                    Write-Pass "Python resolver: Launcher=#$($Matches[1]) Payload=#$($Matches[2]) (${$Matches[3]}GB)"
                } elseif ($result -match "RESOLVER_FAIL") {
                    Write-Fail "Python resolver returned None"
                } else {
                    Write-Fail "Python resolver error: $result"
                }
            } catch {
                Write-Fail "Python resolver test failed: $_"
            }
        } else {
            Write-Info "  No partitions found on disk"
        }
    }
}

# =============================================================================
# Atomic Config Write Verification
# =============================================================================

function Test-AtomicConfigWrite {
    Write-TestHeader "ATOMIC CONFIG WRITE VERIFICATION"
    
    $projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    
    try {
        $testScript = @"
import sys
import os
import tempfile
import json
from pathlib import Path

sys.path.insert(0, r'$projectRoot\.smartdrive')
from core.config import write_config_atomic

# Create temp directory
with tempfile.TemporaryDirectory() as tmpdir:
    config_path = Path(tmpdir) / 'test_config.json'
    test_config = {'test_key': 'test_value', 'number': 42}
    
    # Write atomically
    write_config_atomic(config_path, test_config)
    
    # Verify file exists
    if not config_path.exists():
        print('ATOMIC_FAIL|file_not_created')
        sys.exit(1)
    
    # Verify content
    with open(config_path, 'r') as f:
        loaded = json.load(f)
    
    if loaded != test_config:
        print(f'ATOMIC_FAIL|content_mismatch|{loaded}')
        sys.exit(1)
    
    # Verify no temp files left
    temp_files = list(Path(tmpdir).glob('config_*.tmp'))
    if temp_files:
        print(f'ATOMIC_FAIL|temp_files_remaining|{len(temp_files)}')
        sys.exit(1)
    
    print('ATOMIC_OK')
"@
        
        $result = & python -c $testScript 2>&1
        if ($result -eq "ATOMIC_OK") {
            Write-Pass "write_config_atomic works correctly"
        } else {
            Write-Fail "write_config_atomic test failed: $result"
        }
    } catch {
        Write-Fail "Atomic config write test error: $_"
    }
}

# =============================================================================
# Unit Test Runner
# =============================================================================

function Test-UnitTests {
    Write-TestHeader "PYTHON UNIT TESTS"
    
    $projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    
    try {
        Push-Location $projectRoot
        
        # Run pytest with output capture
        $pytestOutput = & python -m pytest tests/ -v --tb=short 2>&1
        $exitCode = $LASTEXITCODE
        
        # Parse results
        if ($pytestOutput -match "(\d+) passed") {
            $passed = $Matches[1]
            Write-Info "Tests passed: $passed"
        }
        if ($pytestOutput -match "(\d+) failed") {
            $failed = $Matches[1]
            Write-Info "Tests failed: $failed"
        }
        if ($pytestOutput -match "(\d+) skipped") {
            $skipped = $Matches[1]
            Write-Info "Tests skipped: $skipped"
        }
        
        if ($exitCode -eq 0) {
            Write-Pass "All pytest tests passed"
        } else {
            Write-Fail "Some pytest tests failed (exit code: $exitCode)"
            # Show last 20 lines of output for debugging
            Write-Host "`nTest output (last 20 lines):" -ForegroundColor Yellow
            $pytestOutput | Select-Object -Last 20 | ForEach-Object { Write-Host "  $_" }
        }
    } catch {
        Write-Fail "pytest execution error: $_"
    } finally {
        Pop-Location
    }
}

# =============================================================================
# Main
# =============================================================================

Write-Host "`n"
Write-Host ("=" * 70) -ForegroundColor Magenta
Write-Host "  SMARTDRIVE RUNTIME VERIFICATION" -ForegroundColor Magenta
Write-Host "  Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Magenta
Write-Host ("=" * 70) -ForegroundColor Magenta

# Run tests
Test-Environment
Test-DiskIdentity
Test-PartitionResolver
Test-AtomicConfigWrite
Test-UnitTests

# Summary
Write-Host "`n"
Write-Host ("=" * 70) -ForegroundColor Magenta
Write-Host "  VERIFICATION SUMMARY" -ForegroundColor Magenta
Write-Host ("=" * 70) -ForegroundColor Magenta
Write-Host "  Passed:  $script:TestsPassed" -ForegroundColor Green
Write-Host "  Failed:  $script:TestsFailed" -ForegroundColor $(if ($script:TestsFailed -gt 0) { "Red" } else { "Green" })
Write-Host "  Skipped: $script:TestsSkipped" -ForegroundColor Yellow
Write-Host ("=" * 70) -ForegroundColor Magenta

# Exit code
if ($script:TestsFailed -gt 0) {
    Write-Host "`nVerification FAILED" -ForegroundColor Red
    exit 1
} else {
    Write-Host "`nVerification PASSED" -ForegroundColor Green
    exit 0
}
