"""Migration planning for COBOL to FastAPI migration."""

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Any
from enum import Enum
from pydantic import BaseModel, Field

from .system_graph import DependencyGraph, EdgeType, ProgramNode, FileNode, CopybookNode


class MigrationStrategy(str, Enum):
    """Strategy for grouping programs into services."""
    INDEPENDENT = "independent"      # Each program -> separate service
    GROUPED = "grouped"              # Group tightly coupled programs
    HYBRID = "hybrid"                # Mix of both


class ServiceBoundary(BaseModel):
    """Represents a service boundary in the migration plan."""
    name: str
    programs: List[str] = Field(default_factory=list)
    shared_copybooks: List[str] = Field(default_factory=list)
    shared_files: List[str] = Field(default_factory=list)
    internal_calls: List[str] = Field(default_factory=list)    # CALLs within the boundary
    external_calls: List[str] = Field(default_factory=list)    # CALLs crossing boundary
    external_file_access: List[str] = Field(default_factory=list)  # File access crossing boundary
    rationale: str = ""


class SharedModel(BaseModel):
    """A shared Pydantic model from a shared copybook."""
    name: str
    source_copybooks: List[str] = Field(default_factory=list)
    fields: List[Dict[str, Any]] = Field(default_factory=list)
    used_by_programs: List[str] = Field(default_factory=list)
    used_by_services: List[str] = Field(default_factory=list)


class ServiceContract(BaseModel):
    """API contract between services."""
    source_service: str
    target_service: str
    endpoint: str
    method: str = "POST"
    request_model: str = ""
    response_model: str = ""
    description: str = ""


class MigrationGroup(BaseModel):
    """A group of programs to be migrated together."""
    name: str
    programs: List[str] = Field(default_factory=list)
    shared_copybooks: List[str] = Field(default_factory=list)
    shared_files: List[str] = Field(default_factory=list)
    recommended_strategy: str = ""
    service_boundary: Optional[ServiceBoundary] = None
    api_contracts: List[ServiceContract] = Field(default_factory=list)


class MigrationPlan(BaseModel):
    """Complete migration plan."""
    groups: List[MigrationGroup] = Field(default_factory=list)
    shared_models: List[SharedModel] = Field(default_factory=list)
    service_contracts: List[ServiceContract] = Field(default_factory=list)
    unresolved: List[str] = Field(default_factory=list)  # Unresolved dynamic calls, missing copybooks, etc.
    strategy: MigrationStrategy = MigrationStrategy.GROUPED
    metadata: Dict[str, Any] = Field(default_factory=dict)


def analyze_coupling(graph: DependencyGraph) -> Dict[str, Any]:
    """
    Analyze coupling between programs in the graph.

    Returns:
        Dictionary with coupling metrics
    """
    coupling = {
        "call_coupling": {},      # program -> {called_by: count, calls: count}
        "copy_coupling": {},      # program -> {shared_copybooks: count}
        "file_coupling": {},      # program -> {shared_files: count}
        "coupling_scores": {},    # program -> overall coupling score
    }

    # Call coupling
    for prog_name, prog_node in graph.programs.items():
        calls_count = len(prog_node.calls)
        called_by_count = len(graph.get_programs_calling(prog_name))
        coupling["call_coupling"][prog_name] = {
            "calls": calls_count,
            "called_by": called_by_count,
            "total": calls_count + called_by_count,
        }

    # Copy coupling (shared copybooks)
    copybook_usage = {}
    for cb_name, cb_node in graph.copybooks.items():
        for prog in cb_node.used_by:
            if prog not in copybook_usage:
                copybook_usage[prog] = set()
            copybook_usage[prog].add(cb_name)

    for prog_name in graph.programs:
        shared_cbs = copybook_usage.get(prog_name, set())
        coupling["copy_coupling"][prog_name] = {
            "shared_copybooks": len(shared_cbs),
            "copybooks": list(shared_cbs),
        }

    # File coupling (shared files)
    file_usage = {}
    for file_name, file_node in graph.files.items():
        for prog in file_node.used_by:
            if prog not in file_usage:
                file_usage[prog] = set()
            file_usage[prog].add(file_name)

    for prog_name in graph.programs:
        shared_files = file_usage.get(prog_name, set())
        coupling["file_coupling"][prog_name] = {
            "shared_files": len(shared_files),
            "files": list(shared_files),
        }

    # Overall coupling score (weighted)
    for prog_name in graph.programs:
        call_score = coupling["call_coupling"][prog_name]["total"] * 2.0
        copy_score = coupling["copy_coupling"][prog_name]["shared_copybooks"] * 1.5
        file_score = coupling["file_coupling"][prog_name]["shared_files"] * 2.0
        coupling["coupling_scores"][prog_name] = call_score + copy_score + file_score

    return coupling


def find_connected_components(graph: DependencyGraph, edge_types: List[EdgeType] = None) -> List[Set[str]]:
    """
    Find connected components in the graph based on specified edge types.

    Args:
        graph: Dependency graph
        edge_types: Edge types to consider (default: CALL + SHARED_FILE)

    Returns:
        List of sets of program names (connected components)
    """
    if edge_types is None:
        edge_types = [EdgeType.CALL, EdgeType.SHARED_FILE]

    # Build adjacency list
    from collections import defaultdict
    adj = defaultdict(set)

    for edge in graph.edges:
        if edge.type in edge_types:
            adj[edge.source].add(edge.target)
            adj[edge.target].add(edge.source)

    # Find connected components using DFS
    visited = set()
    components = []

    def dfs(node, component):
        visited.add(node)
        component.add(node)
        for neighbor in adj[node]:
            if neighbor not in visited and neighbor in graph.programs:
                dfs(neighbor, component)

    for prog_name in graph.programs:
        if prog_name not in visited:
            component = set()
            dfs(prog_name, component)
            components.append(component)

    return components


def recommend_groups(
    graph: DependencyGraph,
    strategy: MigrationStrategy = MigrationStrategy.GROUPED,
    max_group_size: int = 5
) -> List[MigrationGroup]:
    """
    Recommend migration groups based on dependency graph and strategy.

    Args:
        graph: Dependency graph
        strategy: Migration strategy
        max_group_size: Maximum programs per group (for GROUPED strategy)

    Returns:
        List of MigrationGroup objects
    """
    coupling = analyze_coupling(graph)

    if strategy == MigrationStrategy.INDEPENDENT:
        # Each program gets its own group
        groups = []
        for prog_name in graph.programs:
            groups.append(MigrationGroup(
                name=f"service-{prog_name.lower()}",
                programs=[prog_name],
                recommended_strategy="independent",
            ))
        return groups

    elif strategy == MigrationStrategy.GROUPED:
        # Group by connected components (CALL + SHARED_FILE edges)
        components = find_connected_components(graph)

        groups = []
        for i, component in enumerate(components):
            prog_names = sorted(list(component))

            # If component too large, split by coupling
            if len(prog_names) > max_group_size:
                # Sort by coupling score and split
                prog_names.sort(key=lambda p: -coupling["coupling_scores"].get(p, 0))
                for j in range(0, len(prog_names), max_group_size):
                    chunk = prog_names[j:j + max_group_size]
                    groups.append(_create_group_from_programs(graph, chunk, f"group-{i}-{j//max_group_size}"))
            else:
                groups.append(_create_group_from_programs(graph, prog_names, f"group-{i}"))

        return groups

    elif strategy == MigrationStrategy.HYBRID:
        # Hybrid: group tightly coupled, separate loosely coupled
        components = find_connected_components(graph, [EdgeType.CALL, EdgeType.SHARED_FILE])

        groups = []
        for i, component in enumerate(components):
            prog_names = sorted(list(component))

            # Check internal coupling
            internal_coupling = sum(coupling["coupling_scores"].get(p, 0) for p in prog_names)

            # If highly coupled, keep together; otherwise split
            if internal_coupling > 10 and len(prog_names) <= max_group_size:
                groups.append(_create_group_from_programs(graph, prog_names, f"service-{i}"))
            else:
                # Split into individual services
                for prog in prog_names:
                    groups.append(_create_group_from_programs(graph, [prog], f"service-{prog.lower()}"))

        return groups

    return []


def _create_group_from_programs(
    graph: DependencyGraph,
    prog_names: List[str],
    group_name: str
) -> MigrationGroup:
    """Create a MigrationGroup from a list of program names."""
    shared_copybooks = set()
    shared_files = set()
    internal_calls = []
    external_calls = []
    external_file_access = []

    # Find shared copybooks
    for prog_name in prog_names:
        prog_node = graph.programs[prog_name]
        for cb in prog_node.copies:
            cb_node = graph.copybooks.get(cb)
            if cb_node and len(cb_node.used_by) > 1:
                shared_copybooks.add(cb)

    # Find shared files
    for prog_name in prog_names:
        prog_node = graph.programs[prog_name]
        for f in prog_node.files:
            file_node = graph.files.get(f)
            if file_node and len(file_node.used_by) > 1:
                shared_files.add(f)

    # Find internal and external calls
    for prog_name in prog_names:
        prog_node = graph.programs[prog_name]
        for call_target in prog_node.calls:
            if call_target in prog_names:
                internal_calls.append(f"{prog_name} -> {call_target}")
            else:
                external_calls.append(f"{prog_name} -> {call_target}")

    # Find external file access
    for prog_name in prog_names:
        prog_node = graph.programs[prog_name]
        for f in prog_node.files:
            file_node = graph.files.get(f)
            if file_node:
                other_users = [u for u in file_node.used_by if u not in prog_names]
                if other_users:
                    external_file_access.append(f"{prog_name} -> {f} (also used by {', '.join(other_users)})")

    # Determine rationale
    if len(prog_names) == 1:
        rationale = f"Single program: {prog_names[0]}"
    else:
        rationale = f"Group of {len(prog_names)} programs sharing {len(shared_copybooks)} copybooks and {len(shared_files)} files"

    service_boundary = ServiceBoundary(
        name=group_name,
        programs=prog_names,
        shared_copybooks=list(shared_copybooks),
        shared_files=list(shared_files),
        internal_calls=internal_calls,
        external_calls=external_calls,
        external_file_access=external_file_access,
        rationale=rationale,
    )

    return MigrationGroup(
        name=group_name,
        programs=prog_names,
        shared_copybooks=list(shared_copybooks),
        shared_files=list(shared_files),
        recommended_strategy="grouped" if len(prog_names) > 1 else "independent",
        service_boundary=service_boundary,
    )


def generate_shared_models(graph: DependencyGraph, groups: List[MigrationGroup]) -> List[SharedModel]:
    """
    Generate shared Pydantic models from shared copybooks.

    Args:
        graph: Dependency graph
        groups: Migration groups

    Returns:
        List of SharedModel objects
    """
    shared_models = []

    # Find copybooks used by multiple groups
    copybook_to_groups = {}
    for group in groups:
        for prog_name in group.programs:
            prog_node = graph.programs[prog_name]
            for cb in prog_node.copies:
                cb_node = graph.copybooks.get(cb)
                if cb_node and len(cb_node.used_by) > 1:
                    if cb not in copybook_to_groups:
                        copybook_to_groups[cb] = set()
                    copybook_to_groups[cb].add(group.name)

    for cb_name, group_names in copybook_to_groups.items():
        if len(group_names) > 1:
            cb_node = graph.copybooks[cb_name]
            shared_models.append(SharedModel(
                name=cb_name.replace("-", "_").replace(".", "_").upper() + "Model",
                source_copybooks=[cb_name],
                used_by_programs=cb_node.used_by,
                used_by_services=list(group_names),
            ))

    return shared_models


def generate_service_contracts(graph: DependencyGraph, groups: List[MigrationGroup]) -> List[ServiceContract]:
    """
    Generate API contracts between services based on CALL edges.

    Args:
        graph: Dependency graph
        groups: Migration groups

    Returns:
        List of ServiceContract objects
    """
    contracts = []

    # Map program -> group
    prog_to_group = {}
    for group in groups:
        for prog in group.programs:
            prog_to_group[prog] = group.name

    # Find CALL edges crossing group boundaries
    for edge in graph.edges:
        if edge.type == EdgeType.CALL:
            source_group = prog_to_group.get(edge.source)
            target_group = prog_to_group.get(edge.target)

            if source_group and target_group and source_group != target_group:
                contracts.append(ServiceContract(
                    source_service=source_group,
                    target_service=target_group,
                    endpoint=f"/{edge.target.lower()}",
                    method="POST",
                    request_model=f"{edge.target}Request",
                    response_model=f"{edge.target}Response",
                    description=f"Call from {edge.source} to {edge.target} with params: {edge.details.get('using_params', [])}",
                ))

    return contracts


def create_migration_plan(
    graph: DependencyGraph,
    strategy: MigrationStrategy = MigrationStrategy.GROUPED,
    max_group_size: int = 5
) -> MigrationPlan:
    """
    Create a complete migration plan from a dependency graph.

    Args:
        graph: Dependency graph
        strategy: Migration strategy
        max_group_size: Maximum programs per group

    Returns:
        MigrationPlan object
    """
    # Recommend groups
    groups = recommend_groups(graph, strategy, max_group_size)

    # Generate shared models
    shared_models = generate_shared_models(graph, groups)

    # Generate service contracts
    service_contracts = generate_service_contracts(graph, groups)

    # Collect unresolved items
    unresolved = []
    for prog_name, prog_node in graph.programs.items():
        for dyn_call in prog_node.unresolved_dynamic_calls:
            unresolved.append(
                f"Dynamic CALL in {prog_name}: variable '{dyn_call['variable']}' "
                f"at {dyn_call['paragraph']}:{dyn_call['line_number']}"
            )

    # Check for missing copybooks (referenced but not found)
    for prog_name, prog_node in graph.programs.items():
        for cb in prog_node.copies:
            if cb not in graph.copybooks:
                unresolved.append(f"Missing copybook: {cb} referenced by {prog_name}")

    # Check for circular dependencies
    cycles = graph.find_circular_calls()
    for cycle in cycles:
        unresolved.append(f"Circular CALL dependency: {' -> '.join(cycle)}")

    return MigrationPlan(
        groups=groups,
        shared_models=shared_models,
        service_contracts=service_contracts,
        unresolved=unresolved,
        strategy=strategy,
        metadata={
            "total_programs": len(graph.programs),
            "total_groups": len(groups),
            "total_shared_models": len(shared_models),
            "total_contracts": len(service_contracts),
            "unresolved_count": len(unresolved),
        }
    )


def save_migration_plan(plan: MigrationPlan, output_path: str) -> None:
    """Save migration plan to JSON file."""
    with open(output_path, 'w') as f:
        json.dump(plan.model_dump(), f, indent=2)


def load_migration_plan(input_path: str) -> MigrationPlan:
    """Load migration plan from JSON file."""
    with open(input_path, 'r') as f:
        data = json.load(f)
    return MigrationPlan(**data)


import json  # For save/load functions