"""Grant specifications: what a peer may read (ADR-V170-05, section 6). Pure validation, no I/O."""
from __future__ import annotations

from typing import Any, Optional

from ..memory import MEMORY_TYPES, PEER_SPACE_PREFIX
from ..provisioning import valid_id
from . import ShareError
from .util import parse_duration

DEFAULT_GRANT_SECONDS = 30 * 86400
MAX_GRANT_SECONDS = 365 * 86400
_KEYS = {"space", "projects", "types", "ref_prefixes", "expires_in"}


def _bad(message: str) -> ShareError:
    return ShareError("invalid_grant", message)


def validate_grant_spec(spec: Any) -> dict:
    """Closed, normalized grant spec: ``{space, projects, types, ref_prefixes, expires_in}`` (``expires_in`` seconds or ``None``)."""
    if not isinstance(spec, dict) or set(spec) - _KEYS:
        raise _bad("unknown grant field")
    space = spec.get("space")
    projects = list(spec.get("projects") or [])
    types = list(spec.get("types") or [])
    prefixes = list(spec.get("ref_prefixes") or [])
    expires_in = spec.get("expires_in", DEFAULT_GRANT_SECONDS)
    if space is not None:
        if not valid_id(space):
            raise _bad("the space id may use letters, digits and . _ - (max 64)")
        if space.startswith(PEER_SPACE_PREFIX):
            raise _bad("peer-imported (quarantine) spaces can never be shared onward")
    if len(projects) > 20 or any(not valid_id(p) for p in projects):
        raise _bad("project ids may use letters, digits and . _ - (max 64, at most 20)")
    if space is None and not projects:
        raise _bad("a grant needs a knowledge space (--space) or a project (--project); private memory cannot be shared")
    if len(types) > len(MEMORY_TYPES) or any(t not in MEMORY_TYPES for t in types):
        raise _bad("--type must be one of: " + ", ".join(MEMORY_TYPES))
    if len(prefixes) > 20 or any(
            not isinstance(p, str) or not 7 <= len(p) <= 200 or not (p.startswith("mem://") or p.startswith("file://"))
            or any(ord(c) < 32 or ord(c) == 127 for c in p) for p in prefixes):
        raise _bad("--ref-prefix must start with mem:// or file:// (at most 200 characters, at most 20)")
    if expires_in is not None and (not isinstance(expires_in, int) or isinstance(expires_in, bool)
                                   or not 60 <= expires_in <= MAX_GRANT_SECONDS):
        raise _bad("a grant expires between 1 minute and 365 days (or never)")
    return {"space": space, "projects": sorted(dict.fromkeys(projects)), "types": sorted(dict.fromkeys(types)),
            "ref_prefixes": sorted(dict.fromkeys(prefixes)), "expires_in": expires_in}


def expires_arg(text: Optional[str]) -> Optional[int]:
    """``--expires`` value -> seconds (``never`` -> ``None``; omitted -> the 30 day default)."""
    if text is None:
        return DEFAULT_GRANT_SECONDS
    if str(text).strip().lower() == "never":
        return None
    return parse_duration(text, minimum=60, maximum=MAX_GRANT_SECONDS)


def parse_grant_arg(text: str) -> dict:
    """``space=ks-shared,type=fact|file,project=a|b,prefix=mem://fact/,expires=30d`` -> a validated spec."""
    spec: dict = {"projects": [], "types": [], "ref_prefixes": []}
    expires: Optional[str] = None
    for part in str(text).split(","):
        key, sep, value = part.partition("=")
        key, value = key.strip().lower(), value.strip()
        if not sep or not value:
            raise _bad("a grant is key=value pairs separated by commas: space=ks-shared,type=fact|file,expires=30d")
        values = [v for v in value.split("|") if v] if key != "prefix" else [value]
        if key == "space":
            spec["space"] = value
        elif key == "project":
            spec["projects"] += values
        elif key == "type":
            spec["types"] += values
        elif key == "prefix":
            spec["ref_prefixes"] += values
        elif key == "expires":
            expires = value
        else:
            raise _bad(f"unknown grant key {key!r} (space, project, type, prefix, expires)")
    spec["expires_in"] = expires_arg(expires)
    return validate_grant_spec(spec)
