from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_validator_module(smartdrive_root: Path):
    # Validator is now at .smartdrive/scripts/validate_feature_flows.py
    script_path = smartdrive_root / "scripts" / "validate_feature_flows.py"
    spec = importlib.util.spec_from_file_location("validate_feature_flows", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def test_valid_minimal_doc_passes(tmp_path: Path):
    # tests/unit/test_*.py -> tests/unit -> tests -> .smartdrive
    smartdrive_root = Path(__file__).resolve().parents[2]
    validator = _load_validator_module(smartdrive_root)

    doc = """# FEATURE FLOWS (WHAT Contract)

## CLI Surface Mapping (Binding)

| Menu Path | Feature Heading |
|---|---|
| Main → Mount | FEATURE: MOUNT |

## Feature Flows

## FEATURE: MOUNT

[OBSERVED] Minimal.

### Known Issues

UNKNOWN (not yet audited)

### Open Change Requests

UNKNOWN (not yet audited)

### Verification Status

UNKNOWN (not yet audited)
"""

    feature_file = tmp_path / "FEATURE_FLOWS.md"
    feature_file.write_text(doc, encoding="utf-8")

    assert validator.main(["--path", str(feature_file), "--allow-how-leak"]) == 0


def test_invalid_tag_feature_reference_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    # tests/unit/test_*.py -> tests/unit -> tests -> .smartdrive
    smartdrive_root = Path(__file__).resolve().parents[2]
    validator = _load_validator_module(smartdrive_root)

    doc = """# FEATURE FLOWS (WHAT Contract)

## CLI Surface Mapping (Binding)

| Menu Path | Feature Heading |
|---|---|
| Main → Mount | FEATURE: MOUNT |

## Feature Flows

## FEATURE: MOUNT

[BUG:P0 id=BUG-20251218-001]
Status: NEW
Feature: FEATURE: DOES NOT EXIST
OS: Windows
Mode: PW_ONLY
Repro:
  1. a
Observed:
  - b
Expected:
  - c
Evidence:
  - none
Security impact: NONE
Notes:
  - n
Roadmap:
  -
Verification:
  -

### Known Issues

UNKNOWN (not yet audited)

### Open Change Requests

UNKNOWN (not yet audited)

### Verification Status

UNKNOWN (not yet audited)
"""

    feature_file = tmp_path / "FEATURE_FLOWS.md"
    feature_file.write_text(doc, encoding="utf-8")

    code = validator.main(["--path", str(feature_file), "--allow-how-leak"])
    assert code == 2

    captured = capsys.readouterr()
    assert "Feature reference does not match" in (captured.err + captured.out)
