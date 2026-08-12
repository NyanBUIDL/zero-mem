"""Dependency-free parser for the intentionally tiny corpus config contract.

Only one top-level setting is supported:

    corpus_root: <string path>

This is not a general YAML parser.  It accepts scalar paths, including paths
with spaces, with ordinary whitespace and comments.  Mappings, sequences,
implicit YAML types, tags, anchors, aliases, duplicate keys, and extra
configuration keys are rejected explicitly.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Final, Optional

CORPUS_ROOT_ENV_VAR: Final[str] = "ZERO_MEM_CORPUS_ROOT"
CONFIG_FILE_RELATIVE_PATH: Final[str] = "config/corpus.yaml"
CONFIG_FILE_CORPUS_ROOT_KEY: Final[str] = "corpus_root"


class CorpusConfigError(ValueError):
    """A present corpus configuration is malformed or unsupported."""


def _without_comment(line: str) -> str:
    """Remove an unquoted YAML-style comment without changing quoted values."""
    quote: Optional[str] = None
    escaped = False
    for index, character in enumerate(line):
        if quote == '"' and escaped:
            escaped = False
            continue
        if quote == '"' and character == "\\":
            escaped = True
            continue
        if character in ("'", '"'):
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
            continue
        if character == "#" and quote is None:
            if index == 0 or line[index - 1].isspace():
                return line[:index]
    if quote is not None:
        raise CorpusConfigError("corpus_config: unterminated_quote")
    return line


def _parse_scalar(value: str) -> str:
    """Parse one closed string scalar; never coerce YAML implicit types."""
    value = value.strip()
    if not value:
        raise CorpusConfigError("corpus_config: empty_corpus_root")

    if value[0] in ("'", '"'):
        quote = value[0]
        if len(value) < 2 or value[-1] != quote:
            raise CorpusConfigError("corpus_config: malformed_scalar")
        if quote == "'":
            parsed = value[1:-1].replace("''", "'")
        else:
            try:
                parsed = json.loads(value)
            except (TypeError, ValueError):
                raise CorpusConfigError("corpus_config: malformed_scalar") from None
        if not isinstance(parsed, str) or not parsed.strip():
            raise CorpusConfigError("corpus_config: corpus_root_must_be_string")
        return parsed

    # These forms introduce YAML structures or non-string/interpretive values.
    if value[0] in "[{!&*|>" or value == "-" or value.startswith("- "):
        raise CorpusConfigError("corpus_config: unsupported_scalar")
    lowered = value.lower()
    if lowered in {"null", "~", "true", "false", ".nan", ".inf", "-.inf"}:
        raise CorpusConfigError("corpus_config: corpus_root_must_be_string")
    if value[0].isdigit() or (value[0] in "+-" and len(value) > 1 and value[1].isdigit()):
        raise CorpusConfigError("corpus_config: corpus_root_must_be_string")
    return value


def parse_corpus_config(text: str) -> str:
    """Parse exactly one supported top-level ``corpus_root`` scalar."""
    parsed: Optional[str] = None
    seen_key = False

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = _without_comment(raw_line).strip()
        if not line:
            continue
        if line.startswith("-") or line.startswith("{") or line.startswith("["):
            raise CorpusConfigError(f"corpus_config: unsupported_structure:{line_number}")

        separator = None
        quote: Optional[str] = None
        escaped = False
        for index, character in enumerate(line):
            if quote == '"' and escaped:
                escaped = False
                continue
            if quote == '"' and character == "\\":
                escaped = True
                continue
            if character in ("'", '"'):
                if quote is None:
                    quote = character
                elif quote == character:
                    quote = None
                continue
            if character == ":" and quote is None:
                separator = index
                break
        if separator is None:
            raise CorpusConfigError(f"corpus_config: malformed_line:{line_number}")

        key = line[:separator].strip()
        if key != CONFIG_FILE_CORPUS_ROOT_KEY:
            raise CorpusConfigError(f"corpus_config: unsupported_key:{line_number}")
        if seen_key:
            raise CorpusConfigError("corpus_config: duplicate_corpus_root")
        seen_key = True
        parsed = _parse_scalar(line[separator + 1 :])

    if not seen_key or parsed is None:
        raise CorpusConfigError("corpus_config: missing_corpus_root")
    return parsed


def _config_root(config_path: Path) -> Optional[Path]:
    """Return None only when the optional config file is genuinely absent."""
    try:
        if not config_path.exists():
            return None
        if not config_path.is_file():
            raise CorpusConfigError("corpus_config: not_a_file")
        text = config_path.read_text(encoding="utf-8")
    except CorpusConfigError:
        raise
    except (OSError, UnicodeError):
        raise CorpusConfigError("corpus_config: read_failed") from None
    return Path(parse_corpus_config(text)).expanduser().resolve()


def resolve_root(
    explicit: Optional[Path],
    *,
    env_name: str = CORPUS_ROOT_ENV_VAR,
    config_path: Optional[Path] = None,
) -> Optional[Path]:
    """Resolve explicit -> environment -> optional config, with no defaults."""
    if explicit is not None:
        value = str(explicit).strip()
        if value:
            return Path(value).expanduser().resolve()
    env_value = os.environ.get(env_name)
    if env_value:
        env_value = env_value.strip()
        if env_value:
            return Path(env_value).expanduser().resolve()
    if config_path is not None:
        return _config_root(config_path)
    return None


__all__ = [
    "CorpusConfigError",
    "CORPUS_ROOT_ENV_VAR",
    "CONFIG_FILE_RELATIVE_PATH",
    "CONFIG_FILE_CORPUS_ROOT_KEY",
    "parse_corpus_config",
    "resolve_root",
]
