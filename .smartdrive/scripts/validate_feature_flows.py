#!/usr/bin/env python3
"""Enforcement script: Validate FEATURE_FLOWS.md tag consistency and coverage.

This script enforces the binding WHAT contract in FEATURE_FLOWS.md:
- CLI Surface Mapping rows must map 1:1 to FEATURE headings.
- Tag blocks ([BUG:*] / [CHANGE:*]) must follow the canonical schema.
- Tag IDs must be unique across the entire file.
- Lifecycle rules: TRIAGED+ requires Roadmap; VERIFIED requires Verification.
- Feature sections must have required sub-sections with valid status values.
- Best-effort HOW-leak detection outside tag blocks.

Exit codes:
    0 - Validation passed
    2 - Validation errors found
    1 - Unexpected error

Usage:
    python scripts/validate_feature_flows.py
    python scripts/validate_feature_flows.py --path FEATURE_FLOWS.md
    python scripts/validate_feature_flows.py --allow-how-leak
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

STATUSES: Tuple[str, ...] = (
    "NEW",
    "TRIAGED",
    "IN_PROGRESS",
    "FIXED_UNVERIFIED",
    "VERIFIED",
    "DEFERRED",
)

OS_VALUES: Tuple[str, ...] = ("Windows", "Linux", "macOS", "Multi", "Unknown")
MODE_VALUES: Tuple[str, ...] = (
    "PW_ONLY",
    "PW_KEYFILE",
    "PW_GPG_KEYFILE",
    "GPG_PW_ONLY",
    "Multi",
    "Unknown",
)

SECURITY_IMPACT_VALUES: Tuple[str, ...] = ("NONE", "LOW", "MED", "HIGH", "CRITICAL")

# Valid status values for Known Issues / Open Change Requests / Verification Status
VALID_SECTION_STATUS: Tuple[str, ...] = ("NONE (verified)", "UNKNOWN (not yet audited)")

TAG_START_RE = re.compile(r"^\[(BUG|CHANGE):(P[0-3])\s+id=([A-Z]{3}-\d{8}-\d{3})\]$")
FEATURE_HEADING_RE = re.compile(r"^##\s+(FEATURE:\s+.+?)\s*$")


@dataclass(frozen=True)
class ValidationError:
    message: str
    line: Optional[int] = None


def _norm(s: str) -> str:
    return s.strip()


def _is_nonempty_list_value(lines: Sequence[str]) -> bool:
    for line in lines:
        if line.strip() and not line.strip().startswith("#"):
            return True
    return False


def _extract_markdown_table_rows(lines: Sequence[str], start_index: int) -> List[Tuple[int, List[str]]]:
    """Return (line_number, [col1, col2, ...]) rows for a markdown table.

    Assumes the header row and separator row exist; returns subsequent data rows.
    """
    rows: List[Tuple[int, List[str]]] = []
    for i in range(start_index, len(lines)):
        line = lines[i]
        if not line.strip():
            break
        if not line.lstrip().startswith("|"):
            break
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append((i + 1, cols))
    return rows


def find_section_start(lines: Sequence[str], heading: str) -> Optional[int]:
    for i, line in enumerate(lines):
        if line.strip() == heading:
            return i
    return None


def parse_feature_headings(lines: Sequence[str]) -> List[Tuple[int, str]]:
    headings: List[Tuple[int, str]] = []
    for i, line in enumerate(lines, start=1):
        m = FEATURE_HEADING_RE.match(line)
        if m:
            headings.append((i, m.group(1).strip()))
    return headings


def _parse_surface_mapping(
    lines: Sequence[str], section_heading: str, mapping_name: str, *, required: bool = True
) -> Tuple[List[ValidationError], Dict[str, Tuple[int, str]]]:
    """Parse a surface mapping table (CLI or GUI).

    Returns (errors, mapping) where mapping is {path: (line_num, feature)}.
    If required=False and section is missing, returns empty mapping with no errors.
    """
    errors: List[ValidationError] = []

    start = find_section_start(lines, section_heading)
    if start is None:
        if required:
            errors.append(ValidationError(f"Missing section: '{section_heading}'."))
        return errors, {}

    # Find first table row after heading
    table_start = None
    for i in range(start + 1, len(lines)):
        if lines[i].lstrip().startswith("|"):
            table_start = i
            break
        if lines[i].startswith("## "):
            break

    if table_start is None:
        errors.append(ValidationError(f"{mapping_name} mapping table not found under '{section_heading}'.", start + 1))
        return errors, {}

    rows = _extract_markdown_table_rows(lines, table_start)
    if len(rows) < 2:
        errors.append(
            ValidationError(
                f"{mapping_name} mapping table is too short (missing header/separator/data rows).", table_start + 1
            )
        )
        return errors, {}

    # First row is header, second is separator
    data_rows = rows[2:]

    mapping: Dict[str, Tuple[int, str]] = {}
    for line_num, cols in data_rows:
        if len(cols) < 2:
            errors.append(ValidationError(f"{mapping_name} mapping row must have at least 2 columns.", line_num))
            continue
        menu_path = cols[0].strip()
        feature = cols[1].strip()
        if not menu_path or not feature:
            errors.append(ValidationError(f"{mapping_name} mapping row has empty path or Feature Heading.", line_num))
            continue
        if menu_path in mapping:
            prev_line, _ = mapping[menu_path]
            errors.append(ValidationError(f"Duplicate path in {mapping_name} mapping: {menu_path}", line_num))
            errors.append(ValidationError(f"Previous occurrence of path: {menu_path}", prev_line))
            continue
        mapping[menu_path] = (line_num, feature)

    # Validate no duplicate feature targets within this mapping
    seen_feature_targets: Dict[str, int] = {}
    for menu_path, (line_num, feature) in mapping.items():
        if feature in seen_feature_targets:
            errors.append(
                ValidationError(f"Feature Heading mapped by multiple {mapping_name} rows: {feature}", line_num)
            )
            errors.append(ValidationError(f"Previous mapping to {feature}", seen_feature_targets[feature]))
        else:
            seen_feature_targets[feature] = line_num

    return errors, mapping


def parse_cli_mapping(lines: Sequence[str]) -> Tuple[List[ValidationError], Dict[str, Tuple[int, str]]]:
    return _parse_surface_mapping(lines, "## CLI Surface Mapping (Binding)", "CLI", required=True)


def parse_gui_mapping(lines: Sequence[str]) -> Tuple[List[ValidationError], Dict[str, Tuple[int, str]]]:
    # GUI mapping is optional - only required if there are GUI-only features
    return _parse_surface_mapping(lines, "## GUI Surface Mapping (Binding)", "GUI", required=False)


def iter_tag_blocks(lines: Sequence[str]) -> Iterable[Tuple[int, str, str, str, List[Tuple[int, str]]]]:
    """Yield tag blocks.

    Returns tuples:
      (start_line, tag_type, priority, tag_id, block_lines)

    where block_lines are (line_num, line_text) including the start line.
    """
    in_code_fence = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            i += 1
            continue

        if in_code_fence:
            i += 1
            continue

        m = TAG_START_RE.match(stripped)
        if not m:
            i += 1
            continue

        tag_type, priority, tag_id = m.group(1), m.group(2), m.group(3)
        start_line = i + 1
        block: List[Tuple[int, str]] = [(start_line, line.rstrip("\n"))]

        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            nxt_stripped = nxt.strip()

            if nxt_stripped.startswith("```"):
                # code fence starts; treat as terminator for tag blocks
                break
            if TAG_START_RE.match(nxt_stripped):
                break
            if nxt.startswith("## "):
                break
            if nxt.strip() == "---":
                break

            block.append((j + 1, nxt.rstrip("\n")))
            j += 1

        yield start_line, tag_type, priority, tag_id, block
        i = j


def _parse_field_value(block_lines: Sequence[Tuple[int, str]], field_prefix: str) -> Optional[Tuple[int, str]]:
    prefix = field_prefix + ":"
    for line_num, line in block_lines:
        if line.startswith(prefix):
            return line_num, line[len(prefix) :].strip()
    return None


def _collect_section_lines(block_lines: Sequence[Tuple[int, str]], header: str) -> Optional[List[str]]:
    """Collect indented lines following a header like 'Repro:' or 'Roadmap:'."""
    found_index = None
    for idx, (_line_num, line) in enumerate(block_lines):
        if line.strip() == f"{header}:":
            found_index = idx
            break
    if found_index is None:
        return None

    collected: List[str] = []
    for _line_num, line in block_lines[found_index + 1 :]:
        if re.match(r"^[A-Za-z][A-Za-z ]{1,40}:\s*", line):
            break
        if line.strip() == "":
            continue
        collected.append(line)
    return collected


def validate_tag_blocks(lines: Sequence[str], feature_headings: Set[str]) -> List[ValidationError]:
    errors: List[ValidationError] = []
    seen_ids: Dict[str, int] = {}

    for start_line, tag_type, priority, tag_id, block in iter_tag_blocks(lines):
        # ID prefix must match tag type
        if tag_type == "BUG" and not tag_id.startswith("BUG-"):
            errors.append(ValidationError(f"BUG tag id must start with 'BUG-': {tag_id}", start_line))
        if tag_type == "CHANGE" and not tag_id.startswith("CHG-"):
            errors.append(ValidationError(f"CHANGE tag id must start with 'CHG-': {tag_id}", start_line))

        if tag_id in seen_ids:
            errors.append(ValidationError(f"Duplicate tag id: {tag_id}", start_line))
            errors.append(ValidationError(f"Previous occurrence of tag id: {tag_id}", seen_ids[tag_id]))
        else:
            seen_ids[tag_id] = start_line

        status = _parse_field_value(block, "Status")
        if not status:
            errors.append(ValidationError("Missing required field: Status", start_line))
            status_value = None
        else:
            status_value = status[1]
            if status_value not in STATUSES:
                errors.append(ValidationError(f"Invalid Status: {status_value}", status[0]))

        feature = _parse_field_value(block, "Feature")
        if not feature:
            errors.append(ValidationError("Missing required field: Feature", start_line))
        else:
            feature_value = feature[1]
            if feature_value not in feature_headings:
                errors.append(
                    ValidationError(
                        f"Feature reference does not match any FEATURE heading exactly: {feature_value}",
                        feature[0],
                    )
                )

        os_field = _parse_field_value(block, "OS")
        if not os_field:
            errors.append(ValidationError("Missing required field: OS", start_line))
        else:
            if os_field[1] not in OS_VALUES:
                errors.append(ValidationError(f"Invalid OS: {os_field[1]}", os_field[0]))

        mode_field = _parse_field_value(block, "Mode")
        if not mode_field:
            errors.append(ValidationError("Missing required field: Mode", start_line))
        else:
            if mode_field[1] not in MODE_VALUES:
                errors.append(ValidationError(f"Invalid Mode: {mode_field[1]}", mode_field[0]))

        if tag_type == "BUG":
            for required in ("Repro", "Observed", "Expected", "Evidence", "Notes", "Roadmap", "Verification"):
                section_lines = _collect_section_lines(block, required)
                if section_lines is None:
                    errors.append(ValidationError(f"Missing required section: {required}:", start_line))

            security = _parse_field_value(block, "Security impact")
            if not security:
                errors.append(ValidationError("Missing required field: Security impact", start_line))
            else:
                if security[1] not in SECURITY_IMPACT_VALUES:
                    errors.append(ValidationError(f"Invalid Security impact: {security[1]}", security[0]))

        elif tag_type == "CHANGE":
            for required in (
                "Request",
                "Constraints",
                "Evidence",
                "Roadmap",
                "Verification",
            ):
                section_lines = _collect_section_lines(block, required)
                if section_lines is None:
                    errors.append(ValidationError(f"Missing required section: {required}:", start_line))

        # Lifecycle rules
        if status_value in {"TRIAGED", "IN_PROGRESS", "FIXED_UNVERIFIED", "VERIFIED", "DEFERRED"}:
            roadmap_lines = _collect_section_lines(block, "Roadmap") or []
            if not _is_nonempty_list_value(roadmap_lines):
                errors.append(ValidationError("Status TRIAGED+ requires non-empty Roadmap section.", start_line))

        if status_value == "VERIFIED":
            verification_lines = _collect_section_lines(block, "Verification") or []
            if not _is_nonempty_list_value(verification_lines):
                errors.append(ValidationError("Status VERIFIED requires non-empty Verification section.", start_line))

    return errors


def validate_feature_section_structure(
    lines: Sequence[str], feature_headings_list: List[Tuple[int, str]]
) -> List[ValidationError]:
    """Validate that each FEATURE section has required sub-sections with valid status.

    Required sub-sections:
    - Known Issues (or valid status)
    - Open Change Requests (or valid status)
    - Verification Status (with valid value)
    """
    errors: List[ValidationError] = []

    # Find the line ranges for each feature section
    heading_lines = [ln for (ln, _h) in feature_headings_list]

    for idx, (start_line, heading) in enumerate(feature_headings_list):
        # Determine end of this feature section
        if idx + 1 < len(feature_headings_list):
            end_line = feature_headings_list[idx + 1][0] - 1
        else:
            end_line = len(lines)

        section_lines = lines[start_line - 1 : end_line]
        section_text = "\n".join(section_lines)

        # Check for required sub-sections
        has_known_issues = False
        has_change_requests = False
        has_verification_status = False

        for i, line in enumerate(section_lines):
            stripped = line.strip()

            # Known Issues section
            if stripped.startswith("### Known Issues"):
                has_known_issues = True
                # Check if next non-empty line is a valid status or a BUG tag
                for j in range(i + 1, len(section_lines)):
                    next_line = section_lines[j].strip()
                    if not next_line:
                        continue
                    if next_line.startswith("###") or next_line.startswith("## ") or next_line == "---":
                        break
                    if next_line.startswith("[BUG:"):
                        break  # Has a bug tag, valid
                    if next_line in VALID_SECTION_STATUS:
                        break  # Has valid status
                    if next_line == "None currently recorded.":
                        errors.append(
                            ValidationError(
                                f"'{heading}' Known Issues uses forbidden 'None currently recorded.' "
                                f"Use 'NONE (verified)' or 'UNKNOWN (not yet audited)'",
                                start_line + i,
                            )
                        )
                    break

            # Open Change Requests section
            if stripped.startswith("### Open Change Requests"):
                has_change_requests = True
                for j in range(i + 1, len(section_lines)):
                    next_line = section_lines[j].strip()
                    if not next_line:
                        continue
                    if next_line.startswith("###") or next_line.startswith("## ") or next_line == "---":
                        break
                    if next_line.startswith("[CHANGE:"):
                        break  # Has a change tag, valid
                    if next_line in VALID_SECTION_STATUS:
                        break  # Has valid status
                    if next_line == "None currently recorded.":
                        errors.append(
                            ValidationError(
                                f"'{heading}' Open Change Requests uses forbidden 'None currently recorded.' "
                                f"Use 'NONE (verified)' or 'UNKNOWN (not yet audited)'",
                                start_line + i,
                            )
                        )
                    break

            # Verification Status section
            if stripped.startswith("### Verification Status"):
                has_verification_status = True
                for j in range(i + 1, len(section_lines)):
                    next_line = section_lines[j].strip()
                    if not next_line:
                        continue
                    if next_line.startswith("###") or next_line.startswith("## ") or next_line == "---":
                        break
                    if next_line in VALID_SECTION_STATUS:
                        break  # Valid
                    errors.append(
                        ValidationError(
                            f"'{heading}' Verification Status has invalid value: '{next_line}'. "
                            f"Use 'NONE (verified)' or 'UNKNOWN (not yet audited)'",
                            start_line + i,
                        )
                    )
                    break

        # Report missing required sub-sections
        if not has_known_issues:
            errors.append(ValidationError(f"'{heading}' missing required sub-section: '### Known Issues'", start_line))
        if not has_change_requests:
            errors.append(
                ValidationError(f"'{heading}' missing required sub-section: '### Open Change Requests'", start_line)
            )
        if not has_verification_status:
            errors.append(
                ValidationError(f"'{heading}' missing required sub-section: '### Verification Status'", start_line)
            )

    return errors


def validate_how_leaks(lines: Sequence[str], *, allow_how_leak: bool) -> List[ValidationError]:
    if allow_how_leak:
        return []

    errors: List[ValidationError] = []

    in_code_fence = False
    in_tag_block = False

    suspicious_patterns: List[Tuple[re.Pattern[str], str]] = [
        (re.compile(r"\bdef\s+[A-Za-z_]\w*\s*\("), "Python function definition"),
        (re.compile(r"\bclass\s+[A-Za-z_]\w*\s*[:\(]"), "Python class definition"),
        (re.compile(r"\bfrom\s+\S+\s+import\b"), "Python import"),
        (re.compile(r"\bimport\s+\S+"), "Python import"),
        (re.compile(r"\b__file__\b"), "__file__ reference"),
        (re.compile(r"\bPath\s*\("), "Path(…) reference"),
        (re.compile(r"\bcore/"), "core/ path (HOW leakage)"),
        (re.compile(r"\bscripts/"), "scripts/ path (HOW leakage)"),
        (re.compile(r"\.py\b"), ".py filename (HOW leakage)"),
        (re.compile(r"\bline\s+\d+\b", re.IGNORECASE), "line-number reference"),
    ]

    allowed_exact_lines: Set[str] = {
        "python scripts/validate_feature_flows.py",
    }

    for i, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n")
        stripped = line.strip()

        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            continue

        if in_code_fence:
            continue

        if TAG_START_RE.match(stripped):
            in_tag_block = True
            continue

        if in_tag_block:
            if stripped == "---" or stripped.startswith("## "):
                in_tag_block = False
            else:
                continue

        if stripped in allowed_exact_lines:
            continue

        for pattern, description in suspicious_patterns:
            if pattern.search(line):
                errors.append(ValidationError(f"Possible HOW leakage ({description}): {stripped}", i))
                break

    return errors


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate FEATURE_FLOWS.md contract.")
    parser.add_argument(
        "--path",
        default="FEATURE_FLOWS.md",
        help="Path to FEATURE_FLOWS.md (default: FEATURE_FLOWS.md)",
    )
    parser.add_argument(
        "--allow-how-leak",
        action="store_true",
        help="Allow best-effort HOW-leak patterns outside tag blocks.",
    )

    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        script_path = Path(__file__).resolve()
        repo_root = script_path.parent.parent
        feature_flows_path = (repo_root / args.path).resolve() if not Path(args.path).is_absolute() else Path(args.path)

        if not feature_flows_path.exists():
            print(f"ERROR: File not found: {feature_flows_path}", file=sys.stderr)
            return 2

        content = feature_flows_path.read_text(encoding="utf-8")
        lines = content.splitlines()

        errors: List[ValidationError] = []

        feature_headings_list = parse_feature_headings(lines)
        feature_headings = [h for (_ln, h) in feature_headings_list]

        # Headings must be unique
        seen: Dict[str, int] = {}
        for ln, h in feature_headings_list:
            if h in seen:
                errors.append(ValidationError(f"Duplicate FEATURE heading: {h}", ln))
                errors.append(ValidationError(f"Previous occurrence of FEATURE heading: {h}", seen[h]))
            else:
                seen[h] = ln

        mapping_errors, cli_mapping = parse_cli_mapping(lines)
        errors.extend(mapping_errors)

        gui_mapping_errors, gui_mapping = parse_gui_mapping(lines)
        errors.extend(gui_mapping_errors)

        # Combine all mapped features from CLI and GUI
        cli_mapped_features = set(feature for (_ln, feature) in cli_mapping.values()) if cli_mapping else set()
        gui_mapped_features = set(feature for (_ln, feature) in gui_mapping.values()) if gui_mapping else set()
        all_mapped_features = cli_mapped_features | gui_mapped_features

        # Validate CLI mapping references
        if cli_mapping:
            for menu_path, (ln, feature) in cli_mapping.items():
                if feature not in feature_headings:
                    errors.append(
                        ValidationError(
                            f"CLI mapping references missing FEATURE heading: {feature} (menu: {menu_path})",
                            ln,
                        )
                    )

        # Validate GUI mapping references
        if gui_mapping:
            for gui_path, (ln, feature) in gui_mapping.items():
                if feature not in feature_headings:
                    errors.append(
                        ValidationError(
                            f"GUI mapping references missing FEATURE heading: {feature} (path: {gui_path})",
                            ln,
                        )
                    )

        # Ensure no feature is mapped in both CLI and GUI
        overlap = cli_mapped_features & gui_mapped_features
        if overlap:
            for h in sorted(overlap):
                errors.append(
                    ValidationError(
                        f"FEATURE heading mapped in both CLI and GUI mappings (must be in exactly one): {h}"
                    )
                )

        # Ensure all features are mapped in either CLI or GUI (complete coverage)
        if all_mapped_features != set(feature_headings):
            missing_in_mapping = sorted(set(feature_headings) - all_mapped_features)
            extra_in_mapping = sorted(all_mapped_features - set(feature_headings))
            for h in missing_in_mapping:
                errors.append(ValidationError(f"FEATURE heading not present in CLI or GUI mapping: {h}"))
            for h in extra_in_mapping:
                errors.append(ValidationError(f"Surface mapping references non-existent FEATURE heading: {h}"))

        errors.extend(validate_tag_blocks(lines, set(feature_headings)))
        errors.extend(validate_feature_section_structure(lines, feature_headings_list))
        errors.extend(validate_how_leaks(lines, allow_how_leak=args.allow_how_leak))

        if errors:
            for err in errors:
                if err.line is not None:
                    print(f"ERROR:{err.line}: {err.message}", file=sys.stderr)
                else:
                    print(f"ERROR: {err.message}", file=sys.stderr)
            print(f"Validation failed: {len(errors)} error(s).", file=sys.stderr)
            return 2

        print("Validation passed.")
        return 0

    except Exception as exc:
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
