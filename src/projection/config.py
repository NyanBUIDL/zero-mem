"""M9.1 — explicit projection configuration and vault-root resolution.

The operator's vault path is RUNTIME CONFIGURATION, never a product constant.
No username, no home directory, no ``~/Obsidian`` guess, and no repository-local
default appears anywhere in this module. Product code RECEIVES a vault root; it
never discovers one (plan-m9.md §2.1).

Resolution order (deterministic, explicit-only — plan-m9.md §2.2), mirroring the
explicit-value-then-environment discipline already used by
``BridgeConfig._resolve_identity``:

1. explicit constructor/function argument (always wins; this is what tests use);
2. environment variable ``ZERO_MEM_OBSIDIAN_VAULT`` (absolute path);
3. project-local ``config/projection.yaml``, key ``vault_root``;
4. nothing configured -> ``None`` -> projection UNAVAILABLE.

No other source is consulted. The vault root is never derived from ``cwd``, the
repository name, ``$HOME``, session text, ``HERMES_PROJECT_ID``, or any memory
content — a memory-controlled string must never be able to choose a write root.

Unconfigured is a NORMAL, SAFE, SILENT state (§2.4): no directory is created
anywhere, no exception escapes, and nothing else in Zero-Mem changes behaviour.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Mapping, Optional, Tuple

from .contracts import (
    DEFAULT_PROJECTION_SENSITIVITY_CEILING,
    NoteType,
    ProjectionConfigError,
    ProjectionResult,
    validate_note_type,
    validate_sensitivity_ceiling,
)
from .paths import OBSIDIAN_CONFIG_DIR, resolve_managed_root

#: The ONE environment variable that may supply a vault root.
VAULT_ROOT_ENV_VAR: Final[str] = "ZERO_MEM_OBSIDIAN_VAULT"

#: Project-local optional config file, joining the existing ``config/`` convention.
CONFIG_FILE_RELATIVE_PATH: Final[str] = "config/projection.yaml"

#: Key read from that file. It is the only key this module honours.
CONFIG_FILE_VAULT_KEY: Final[str] = "vault_root"

#: Default managed subtree name beneath the configured vault (§6.1, Q2/Q3).
DEFAULT_MANAGED_DIR_NAME: Final[str] = "Zero-Mem"

#: Stable reason code for the unconfigured state.
REASON_VAULT_NOT_CONFIGURED: Final[str] = "vault_not_configured"

#: Repository root, derived from THIS module's own location. Used only to refuse
#: a vault root that points at the repository itself; never as a fallback value.
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Minimal, dependency-free config-file reader
# ---------------------------------------------------------------------------

def _read_config_file(path: Path) -> Optional[str]:
    """Read ``vault_root`` from the optional project-local config file.

    A deliberately minimal, stdlib-only reader for a flat ``key: value`` file:
    no new third-party dependency is introduced for one scalar (plan-m9.md
    §26.2 "no new dependency"). Supported syntax is exactly:

    * blank lines and whole-line ``#`` comments;
    * top-level ``key: value`` pairs with optional single/double quotes.

    Anything else — indentation, a list item, a nested block — is a structure
    this reader does not understand, so it fails closed rather than guessing.
    An absent file is normal and returns ``None``.
    """
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        raise ProjectionConfigError("config_file_unreadable") from None

    value: Optional[str] = None
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[:1].isspace() or line.lstrip().startswith("-"):
            raise ProjectionConfigError("config_file_unsupported_structure")
        key, separator, remainder = line.partition(":")
        if not separator:
            raise ProjectionConfigError("config_file_unsupported_structure")
        if key.strip() != CONFIG_FILE_VAULT_KEY:
            # Unknown keys are ignored, never interpreted. A future key must be
            # honoured deliberately, not absorbed by accident.
            continue
        candidate = remainder.strip()
        if len(candidate) >= 2 and candidate[0] == candidate[-1] and candidate[0] in "\"'":
            candidate = candidate[1:-1]
        value = candidate or None
    return value


# ---------------------------------------------------------------------------
# Vault-root resolution and validation
# ---------------------------------------------------------------------------

def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProjectionConfigError("vault_root_not_a_string")
    stripped = value.strip()
    return stripped or None


def resolve_vault_root(
    explicit: Optional[str | Path] = None,
    *,
    env: Optional[Mapping[str, str]] = None,
    config_file: Optional[Path] = None,
) -> Optional[Path]:
    """Resolve the configured vault root, or ``None`` when nothing is configured.

    Precedence is exactly §2.2. Returning ``None`` is a legitimate outcome; it
    never falls back to ``cwd``, ``$HOME``, a temporary directory, the
    repository, or an invented ``~/Obsidian``.
    """
    if explicit is not None:
        candidate = _clean(str(explicit) if isinstance(explicit, Path) else explicit)
        if candidate is not None:
            return Path(candidate)

    environment = os.environ if env is None else env
    candidate = _clean(environment.get(VAULT_ROOT_ENV_VAR))
    if candidate is not None:
        return Path(candidate)

    path = _REPO_ROOT / CONFIG_FILE_RELATIVE_PATH if config_file is None else config_file
    candidate = _clean(_read_config_file(path))
    if candidate is not None:
        return Path(candidate)

    return None


def validate_vault_root(vault_root: Path) -> Path:
    """Validate a candidate vault root, failing closed with a sanitized reason.

    Requirements (§2.3): absolute; not a ``~`` form; exists; is a directory; is
    not a symlink; is writable; is not the user's home directory; is not the
    repository root; is not an ``.obsidian`` directory.

    Errors name the failed condition only. The offending path is never echoed,
    so an operator's directory layout cannot leak into logs or test output.
    """
    if not isinstance(vault_root, Path):
        raise ProjectionConfigError("vault_root_not_a_path")
    text = str(vault_root)
    if not text:
        raise ProjectionConfigError("vault_root_empty")
    if "\x00" in text:
        raise ProjectionConfigError("vault_root_contains_nul")
    if text.startswith("~"):
        # A tilde form is a home GUESS, not an explicit operator path.
        raise ProjectionConfigError("vault_root_not_absolute")
    if not vault_root.is_absolute():
        raise ProjectionConfigError("vault_root_not_absolute")
    if vault_root.is_symlink():
        raise ProjectionConfigError("vault_root_is_symlink")
    if not vault_root.exists():
        raise ProjectionConfigError("vault_root_missing")
    if not vault_root.is_dir():
        raise ProjectionConfigError("vault_root_not_a_directory")

    real_root = Path(os.path.realpath(vault_root))
    if real_root == Path(os.path.realpath(_REPO_ROOT)):
        raise ProjectionConfigError("vault_root_is_repository_root")
    home = os.environ.get("HOME")
    if home and real_root == Path(os.path.realpath(home)):
        # Rejection guard only: the home directory is never a source of a vault
        # root here, it is merely refused as a target.
        raise ProjectionConfigError("vault_root_is_home_directory")
    if real_root.name == OBSIDIAN_CONFIG_DIR:
        raise ProjectionConfigError("vault_root_is_obsidian_config")
    if not os.access(vault_root, os.W_OK | os.X_OK):
        raise ProjectionConfigError("vault_root_not_writable")
    return vault_root


# ---------------------------------------------------------------------------
# ProjectionConfig
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProjectionConfig:
    """Validated projection configuration. Constructing one writes nothing.

    ``managed_root`` is derived (never supplied) and is the ONLY surface M9 may
    ever write to. The vault root itself, ``.obsidian/``, and every unrelated
    human path stay read-never-write.

    ``retire_mode`` is deliberately absent: retirement is owned by M9.4/M9.5, and
    a policy knob that nothing enforces would be a misleading contract at M9.1.
    """

    vault_root: Path
    managed_dir_name: str = DEFAULT_MANAGED_DIR_NAME
    sensitivity_ceiling: str = DEFAULT_PROJECTION_SENSITIVITY_CEILING
    note_types: Tuple[NoteType, ...] = tuple(NoteType)
    dry_run: bool = False
    managed_root: Path = field(init=False)

    def __post_init__(self) -> None:
        root = self.vault_root
        if isinstance(root, str):
            root = Path(root)
        validated = validate_vault_root(root)
        object.__setattr__(self, "vault_root", validated)

        if not isinstance(self.managed_dir_name, str) or not self.managed_dir_name.strip():
            raise ProjectionConfigError("managed_dir_name_invalid")
        try:
            managed_root = resolve_managed_root(validated, self.managed_dir_name)
        except ProjectionConfigError:
            raise
        except Exception as exc:  # ProjectionPathError and defensive fallbacks
            reason = getattr(exc, "reason", "managed_root_invalid")
            raise ProjectionConfigError(reason) from None
        object.__setattr__(self, "managed_root", managed_root)

        object.__setattr__(
            self,
            "sensitivity_ceiling",
            _validated_ceiling(self.sensitivity_ceiling),
        )

        if isinstance(self.note_types, (str, bytes)):
            raise ProjectionConfigError("note_types_invalid")
        try:
            resolved = tuple(validate_note_type(item) for item in self.note_types)
        except Exception:
            raise ProjectionConfigError("note_types_invalid") from None
        if not resolved:
            raise ProjectionConfigError("note_types_empty")
        # Deterministic, de-duplicated order independent of caller iteration.
        ordered = tuple(
            note_type for note_type in NoteType if note_type in set(resolved)
        )
        object.__setattr__(self, "note_types", ordered)

        if not isinstance(self.dry_run, bool):
            raise ProjectionConfigError("dry_run_invalid")

    def to_dict(self) -> dict[str, Any]:
        """Sanitized descriptor. Absolute operator paths are NEVER included."""
        return {
            "managed_dir_name": self.managed_dir_name,
            "sensitivity_ceiling": self.sensitivity_ceiling,
            "note_types": [note_type.value for note_type in self.note_types],
            "dry_run": self.dry_run,
            "projection_configured": True,
        }


def _validated_ceiling(value: Any) -> str:
    try:
        return validate_sensitivity_ceiling(value)
    except Exception:
        raise ProjectionConfigError("sensitivity_ceiling_invalid") from None


def load_projection_config(
    explicit_vault_root: Optional[str | Path] = None,
    *,
    env: Optional[Mapping[str, str]] = None,
    config_file: Optional[Path] = None,
    managed_dir_name: str = DEFAULT_MANAGED_DIR_NAME,
    sensitivity_ceiling: str = DEFAULT_PROJECTION_SENSITIVITY_CEILING,
    note_types: Optional[Tuple[NoteType, ...]] = None,
    dry_run: bool = False,
) -> Optional[ProjectionConfig]:
    """Resolve + validate configuration, or return ``None`` when unconfigured.

    ``None`` means "projection is unavailable" and is a normal state. An invalid
    configured value still raises ``ProjectionConfigError`` — a misconfiguration
    must be visible, whereas an absent configuration must be silent.
    """
    vault_root = resolve_vault_root(explicit_vault_root, env=env, config_file=config_file)
    if vault_root is None:
        return None
    return ProjectionConfig(
        vault_root=vault_root,
        managed_dir_name=managed_dir_name,
        sensitivity_ceiling=sensitivity_ceiling,
        note_types=tuple(NoteType) if note_types is None else note_types,
        dry_run=dry_run,
    )


def unavailable_result(reason: str = REASON_VAULT_NOT_CONFIGURED) -> ProjectionResult:
    """The safe silent outcome for an unconfigured vault.

    Creates nothing, anywhere: no ``cwd`` directory, no ``$HOME`` directory, no
    temp directory, no repository directory, no guessed ``~/Obsidian``.
    """
    return ProjectionResult.unavailable(reason)


__all__ = [
    "VAULT_ROOT_ENV_VAR",
    "CONFIG_FILE_RELATIVE_PATH",
    "CONFIG_FILE_VAULT_KEY",
    "DEFAULT_MANAGED_DIR_NAME",
    "REASON_VAULT_NOT_CONFIGURED",
    "ProjectionConfig",
    "resolve_vault_root",
    "validate_vault_root",
    "load_projection_config",
    "unavailable_result",
]
