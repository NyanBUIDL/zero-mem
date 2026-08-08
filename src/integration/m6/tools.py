"""M6.1 — allowlisted tool registry and fixed resource-type mapping.

Only READ tools exist. No SQL/JSONL/write/grant-admin tools are defined or
reachable. ``resource_type`` is tool-fixed: a caller cannot downgrade or
substitute a less restrictive resource type to retrieve a different resource.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .contracts import Operation, ResourceType

# Tools that are explicitly FORBIDDEN on the M6 read surface. Listed here as a
# guard so future code cannot accidentally register them.
FORBIDDEN_TOOL_NAMES = frozenset({
    "execute_sql", "raw_sql", "sqlite_query", "database_query",
    "read_jsonl", "raw_jsonl", "read_file_arbitrary",
    "write_memory", "create_memory", "update_memory", "delete_memory",
    "create_grant", "revoke_grant", "supersede_grant", "grant_admin",
    "project_write", "requirement_write", "decision_write",
})


@dataclass(frozen=True)
class ToolSpec:
    name: str
    resource_type: ResourceType          # fixed by the tool; caller cannot override
    operation: Operation = Operation.READ
    description: str = ""
    accepts_search: bool = False        # memory_search / memory_query only
    accepts_relation: bool = False      # memory_get_related only
    accepts_source_event: bool = False  # M4 include_source_event path


# Approved tool namespace (exact names from the committed M6 plan).
TOOL_REGISTRY: dict[str, ToolSpec] = {
    # M3-oriented
    "memory_query": ToolSpec(
        "memory_query", ResourceType.EVENT, description="Structured event retrieval.",
        accepts_search=False),
    "memory_search": ToolSpec(
        "memory_search", ResourceType.EVENT, description="Authorized M3 FTS search.",
        accepts_search=True),
    "memory_get_event": ToolSpec(
        "memory_get_event", ResourceType.EVENT, description="Single event by id."),
    "memory_get_related": ToolSpec(
        "memory_get_related", ResourceType.RELATION, description="Hardened relation expansion.",
        accepts_relation=True),
    # M4-oriented
    "project_get_charter": ToolSpec(
        "project_get_charter", ResourceType.CHARTER, description="Project charter."),
    "project_list_requirements": ToolSpec(
        "project_list_requirements", ResourceType.REQUIREMENT,
        description="List requirements.", accepts_source_event=True),
    "project_list_decisions": ToolSpec(
        "project_list_decisions", ResourceType.DECISION, description="List decisions."),
    "project_get_state": ToolSpec(
        "project_get_state", ResourceType.PROJECT_STATE, description="Current project state."),
    "project_list_verifications": ToolSpec(
        "project_list_verifications", ResourceType.VERIFICATION, description="Verification records."),
    "project_list_artifacts": ToolSpec(
        "project_list_artifacts", ResourceType.ARTIFACT,
        description="Artifact metadata only (no file contents)."),
}


def get_tool(name: str) -> Optional[ToolSpec]:
    if name in FORBIDDEN_TOOL_NAMES:
        return None
    return TOOL_REGISTRY.get(name)


def list_tool_names() -> List[str]:
    return sorted(TOOL_REGISTRY.keys())


def is_forbidden_tool(name: str) -> bool:
    return name in FORBIDDEN_TOOL_NAMES


def resource_type_of(name: str) -> Optional[ResourceType]:
    spec = get_tool(name)
    return spec.resource_type if spec else None
