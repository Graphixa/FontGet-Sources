#!/usr/bin/env python3
"""Canonical SPDX-style license ids for FontGet source JSON."""

from __future__ import annotations

import re
from typing import Dict

# Keys are lowercase, whitespace-collapsed forms of upstream license strings.
_ALIASES: Dict[str, str] = {
    "ofl": "OFL-1.1",
    "ofl-1.1": "OFL-1.1",
    "sil open font license 1.1": "OFL-1.1",
    "sil ofl": "OFL-1.1",
    "sil_ofl": "OFL-1.1",
    "apache2": "Apache-2.0",
    "apache-2.0": "Apache-2.0",
    "apache license 2.0": "Apache-2.0",
    "ufl": "Ubuntu-font-1.0",
    "ubuntu-font-1.0": "Ubuntu-font-1.0",
    "mit": "MIT",
    "itf ffl": "ITF-FFL",
    "itf-ffl": "ITF-FFL",
    "itf_ffl": "ITF-FFL",
    "ofl-1.1-rfn": "OFL-1.1-RFN",
    "ofl-1.1-no-rfn": "OFL-1.1-no-RFN",
}

_EXPR_SPLIT = re.compile(r"\s+(and|or)\s+", re.IGNORECASE)


def _normalize_key(raw: str) -> str:
    s = raw.strip().rstrip(".").lower()
    return re.sub(r"\s+", " ", s)


def _alias_one(token: str) -> str:
    key = _normalize_key(token)
    if not key:
        return token.strip()
    if key in _ALIASES:
        return _ALIASES[key]
    return token.strip()


def canonical_license(raw: str) -> str:
    """Map an upstream license string to a shared SPDX-style id."""
    if not raw or not str(raw).strip():
        return "Unknown"

    text = str(raw).strip()
    parts = _EXPR_SPLIT.split(text)
    if len(parts) == 1:
        return _alias_one(parts[0])

    out: list[str] = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            out.append(part.upper())
        else:
            out.append(_alias_one(part))
    return " ".join(out)


def _self_check() -> None:
    assert canonical_license("OFL") == "OFL-1.1"
    assert canonical_license("APACHE2") == "Apache-2.0"
    assert canonical_license("UFL") == "Ubuntu-font-1.0"
    assert canonical_license("SIL Open Font License 1.1") == "OFL-1.1"
    assert canonical_license("OFL-1.1-RFN") == "OFL-1.1-RFN"
    assert canonical_license("OFL-1.1-no-RFN") == "OFL-1.1-no-RFN"
    assert canonical_license("mit") == "MIT"
    assert canonical_license("sil_ofl") == "OFL-1.1"
    assert (
        canonical_license("OFL-1.1-no-RFN or LGPL-2.1-only")
        == "OFL-1.1-no-RFN OR LGPL-2.1-only"
    )
    assert canonical_license("ITF FFL") == "ITF-FFL"
    assert canonical_license("") == "Unknown"
    print("license_ids self-check OK")


if __name__ == "__main__":
    _self_check()
