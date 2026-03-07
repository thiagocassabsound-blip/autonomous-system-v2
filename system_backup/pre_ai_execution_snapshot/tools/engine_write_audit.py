"""
tools/engine_write_audit.py — Engine Write Audit Scanner

Scans the engines/ directory for direct state writes that bypass the Orchestrator.
Run from the project root:
    py tools/engine_write_audit.py
"""
import re
import sys
import os
import io
from pathlib import Path

# Force UTF-8 stdout on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Patterns that indicate a potentially forbidden direct write
WRITE_PATTERNS = [
    (r'self\.state\.set\s*\(',       "state.set() — direct write"),
    (r'self\.state\.delete\s*\(',    "state.delete() — direct write"),
    (r'state_manager\.set\s*\(',     "state_manager.set() — direct write"),
    (r'state_manager\.delete\s*\(', "state_manager.delete() — direct write"),
    (r'_state\[',                    "_state[] — internal dict access"),
    (r'_locked\s*=\s*False',         "_locked = False — unauthorized unlock attempt"),
]

# Patterns that are EXPECTED / OK (orchestrator internals + domain engines with own _state)
ALLOW_LIST_FILES = {
    "core/orchestrator.py",
    "core/state_manager.py",
    "core/state_machine.py",
    "core/snapshot_manager.py",
    "core/version_manager.py",
    "core/cycle_manager.py",
    "core/telemetry_engine.py",
    "core/global_state.py",
    "core/finance_engine.py",
    "core/product_life_engine.py",
    "core/market_loop_engine.py",
    "core/pricing_engine.py",
    "core/version_manager.py",
    "core/security_layer.py",
    "core/commercial_engine.py",
    "core/uptime_engine.py",
    "core/strategic_memory_engine.py",
    "core/dashboard_service.py",
    "core/strategic_opportunity_engine.py",
    "core/opportunity_confluence_engine.py",
    "core/feedback_incentive_engine.py",
    "core/user_enrichment_engine.py",
    "core/macro_exposure_governance_engine.py",
    "infrastructure/db.py",
    "infrastructure/finance_persistence.py",
    "infrastructure/product_lifecycle_persistence.py",
    "infrastructure/market_loop_persistence.py",
    "infrastructure/pricing_persistence.py",
    "infrastructure/version_persistence.py",
    "infrastructure/security_persistence.py",
    "infrastructure/commercial_persistence.py",
    "infrastructure/uptime_persistence.py",
    "infrastructure/strategic_memory_persistence.py",
    "infrastructure/opportunity_radar_persistence.py",
    "infrastructure/opportunity_confluence_persistence.py",
    "infrastructure/feedback_incentive_persistence.py",
    "infrastructure/user_enrichment_persistence.py",
    "infrastructure/macro_exposure_persistence.py",
}

SCAN_DIRS = ["engines", "core", "api", "dashboard", "infrastructure"]


def scan(root: Path) -> list[dict]:
    findings = []

    for scan_dir in SCAN_DIRS:
        target = root / scan_dir
        if not target.exists():
            continue

        for filepath in sorted(target.rglob("*.py")):
            rel = filepath.relative_to(root).as_posix()

            # Allow-list: these files are expected to touch internals
            if rel in ALLOW_LIST_FILES:
                continue

            lines = filepath.read_text(encoding="utf-8").splitlines()
            for lineno, line in enumerate(lines, start=1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                for pattern, label in WRITE_PATTERNS:
                    if re.search(pattern, line):
                        findings.append({
                            "file":    rel,
                            "line":    lineno,
                            "type":    label,
                            "content": stripped[:120],
                        })
                        break  # one match per line

    return findings


def main() -> None:
    root = Path(__file__).resolve().parent.parent

    print("\n" + "=" * 60)
    print("  ENGINE WRITE AUDIT")
    print(f"  Root: {root}")
    print("=" * 60)

    findings = scan(root)

    if not findings:
        print("\n  ✅ CLEAN — No direct state writes found outside core.\n")
        sys.exit(0)

    print(f"\n  ⚠️  Found {len(findings)} potential violation(s):\n")
    for f in findings:
        print(f"  [{f['file']}:{f['line']}]")
        print(f"    Type   : {f['type']}")
        print(f"    Code   : {f['content']}")
        print()

    sys.exit(1)


if __name__ == "__main__":
    main()
