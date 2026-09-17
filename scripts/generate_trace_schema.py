# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Regenerate the checked-in canonical trace schema from the Result adapter."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rampart.core.serialization import ResultRecord


def main() -> None:
    """Write the schema or fail when the committed contract has drifted.

    Raises:
        SystemExit: If --check finds a missing or outdated schema.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = Path(__file__).resolve().parents[1] / "schemas" / "trace.v1.schema.json"
    content = json.dumps(ResultRecord.json_schema(), indent=2, sort_keys=True) + "\n"
    if args.check:
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            parser.exit(
                status=1,
                message=(
                    "Trace schema is outdated; run scripts/generate_trace_schema.py\n"
                ),
            )
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
