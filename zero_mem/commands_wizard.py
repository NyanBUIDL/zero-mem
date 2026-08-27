"""Guided, fail-safe first-run onboarding for Zero-Mem."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


WIZARD_SCHEMA_VERSION = 1


class WizardError(RuntimeError):
    """Sanitized onboarding request or interaction failure."""


def _validate_request(
    *,
    project_id: str | None,
    profile_id: str | None,
    skip_hermes: bool,
    non_interactive: bool,
    as_json: bool,
) -> None:
    has_project = project_id is not None
    has_profile = profile_id is not None
    if has_project != has_profile:
        raise WizardError("project-id and profile-id must be provided together")
    if skip_hermes and has_project:
        raise WizardError("skip-hermes cannot be combined with Hermes identity")
    if non_interactive and not skip_hermes and not has_project:
        raise WizardError(
            "non-interactive mode requires --skip-hermes or both identity options"
        )
    if as_json and not non_interactive:
        raise WizardError("JSON output requires --non-interactive")


def _ask_yes_no(
    prompt: str,
    *,
    input_fn: Callable[[str], str],
) -> bool:
    for _attempt in range(3):
        try:
            answer = input_fn(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            raise WizardError(
                "interactive input unavailable; use --non-interactive --skip-hermes"
            ) from None
        if answer in {"", "n", "no"}:
            return False
        if answer in {"y", "yes"}:
            return True
    raise WizardError("expected yes or no")


def _read_identity(
    *,
    input_fn: Callable[[str], str],
) -> tuple[str, str]:
    try:
        project_id = input_fn("Hermes project ID: ")
        profile_id = input_fn("Hermes profile ID: ")
    except (EOFError, KeyboardInterrupt):
        raise WizardError("Hermes identity input was interrupted") from None
    return project_id, profile_id


def _require_configurable_hermes(info: dict[str, Any]) -> None:
    if info["master_error"]:
        raise WizardError(str(info["master_error"]))
    if not info["zero_mem_enabled"]:
        raise WizardError("Hermes integration is disabled by ZERO_MEM_ENABLED")
    if not info["hermes_found"]:
        raise WizardError("Hermes was not found; rerun with --skip-hermes")
    if not info["boundary_available"]:
        raise WizardError("Hermes boundary is unavailable in this installation")


def _plan(
    *,
    project_id: str | None,
    profile_id: str | None,
    skip_hermes: bool,
    non_interactive: bool,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
) -> tuple[str, str | None, str | None]:
    from .hermes_integration import (
        HermesIntegrationError,
        IntegrationConfig,
        inspect_integration,
    )

    info = inspect_integration()
    if info["config_error"]:
        raise WizardError("existing Hermes integration configuration is invalid")
    if project_id is not None and profile_id is not None:
        _require_configurable_hermes(info)
        try:
            IntegrationConfig(project_id=project_id, profile_id=profile_id)
        except HermesIntegrationError as exc:
            raise WizardError(str(exc)) from None
        return "CONFIGURE", project_id, profile_id
    if info["configured"]:
        return "PRESERVE", None, None
    if skip_hermes:
        return "SKIP", None, None
    if non_interactive:  # defensive; normally rejected before inspection
        raise WizardError("non-interactive Hermes choice is missing")
    if not info["hermes_found"]:
        output_fn("Hermes was not found. Zero-Mem will run in standalone mode.")
        return "NOT_FOUND", None, None

    output_fn("Hermes integration is optional and can be added later.")
    output_fn(
        "Project ID identifies the Hermes codebase/workspace; profile ID identifies "
        "the active Hermes profile and access identity."
    )
    output_fn(
        "Copy both IDs from Hermes configuration. Zero-Mem never guesses them and "
        "does not read Hermes secrets."
    )
    if not _ask_yes_no("Configure Hermes integration now? [y/N]: ", input_fn=input_fn):
        return "SKIP", None, None
    selected_project, selected_profile = _read_identity(input_fn=input_fn)
    _require_configurable_hermes(info)
    try:
        IntegrationConfig(
            project_id=selected_project,
            profile_id=selected_profile,
        )
    except HermesIntegrationError as exc:
        raise WizardError(str(exc)) from None
    return "CONFIGURE", selected_project, selected_profile


def run(
    *,
    project_id: str | None = None,
    profile_id: str | None = None,
    skip_hermes: bool = False,
    non_interactive: bool = False,
    as_json: bool = False,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> tuple[int, dict[str, Any]]:
    """Run setup, optional explicit Hermes configuration, then doctor."""

    _validate_request(
        project_id=project_id,
        profile_id=profile_id,
        skip_hermes=skip_hermes,
        non_interactive=non_interactive,
        as_json=as_json,
    )
    action, selected_project, selected_profile = _plan(
        project_id=project_id,
        profile_id=profile_id,
        skip_hermes=skip_hermes,
        non_interactive=non_interactive,
        input_fn=input_fn,
        output_fn=(lambda _message: None) if as_json else output_fn,
    )

    from .commands_setup import run as setup

    setup()
    if action == "CONFIGURE":
        from .hermes_integration import configure_integration

        configure_integration(
            project_id=selected_project,
            profile_id=selected_profile,
        )

    from .commands_doctor import collect

    doctor = collect()
    status = "READY" if doctor["overall"] == "READY" else "NOT_READY"
    hermes_status = {
        "CONFIGURE": "CONFIGURED",
        "PRESERVE": "PRESERVED",
        "SKIP": "SKIPPED",
        "NOT_FOUND": "NOT_FOUND",
    }[action]
    report = {
        "schema_version": WIZARD_SCHEMA_VERSION,
        "status": status,
        "setup": "READY",
        "hermes": hermes_status,
        "doctor": doctor["overall"],
        "next_steps": ["zero-mem doctor"],
    }
    return (0 if status == "READY" else 2), report


def render(report: dict[str, Any]) -> str:
    """Render a bounded, content-free human summary."""

    return "\n".join(
        (
            f"Zero-Mem onboarding: {report['status']}",
            f"Setup: {report['setup']}",
            f"Hermes: {report['hermes']}",
            f"Doctor: {report['doctor']}",
            f"Next: {report['next_steps'][0]}",
        )
    )


__all__ = ["WIZARD_SCHEMA_VERSION", "WizardError", "render", "run"]
