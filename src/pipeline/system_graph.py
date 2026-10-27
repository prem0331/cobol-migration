"""Unified system dependency graph for COBOL programs."""

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Any
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class EdgeType(str, Enum):
    """Types of dependencies in the graph."""
    CALL = "CALL"                    # Program CALLs another program
    DYNAMIC_CALL = "DYNAMIC_CALL"    # Program CALLs variable (dynamic)
    COPY = "COPY"                    # Program COPYs a copybook
    SHARED_FILE = "SHARED_FILE"      # Programs share a file (by ASSIGN name) - used by >1 program
    USES_FILE = "USES_FILE"          # Program uses a file (by ASSIGN name) - used by 1 program only
    SQL_TABLE = "SQL_TABLE"          # Program accesses SQL table (FROM/JOIN/INTO/UPDATE)
    CICS_LINK = "CICS_LINK"          # EXEC CICS LINK PROGRAM
    CICS_XCTL = "CICS_XCTL"          # EXEC CICS XCTL PROGRAM
    CICS_SEND = "CICS_SEND"          # EXEC CICS SEND MAP
    CICS_RECEIVE = "CICS_RECEIVE"    # EXEC CICS RECEIVE MAP
    FILE_OPEN = "FILE_OPEN"          # OPEN statement with mode
    FILE_READ = "FILE_READ"          # READ statement
    FILE_WRITE = "FILE_WRITE"        # WRITE statement
    FILE_REWRITE = "FILE_REWRITE"    # REWRITE statement
    FILE_DELETE = "FILE_DELETE"      # DELETE statement
    FILE_START = "FILE_START"        # START statement
    FILE_CLOSE = "FILE_CLOSE"        # CLOSE statement
    FILE_UNLOCK = "FILE_UNLOCK"      # UNLOCK statement


class ProgramNode(BaseModel):
    """A COBOL program node."""
    name: str
    source_file: str = ""
    program_id: str = ""
    calls: List[str] = Field(default_factory=list)       # Programs this program CALLs
    copies: List[str] = Field(default_factory=list)      # Copybooks this program COPYs
    files: List[str] = Field(default_factory=list)       # Files this program uses (ASSIGN names)
    unresolved_dynamic_calls: List[Dict[str, Any]] = Field(default_factory=list)


class CopybookNode(BaseModel):
    """A copybook node."""
    name: str
    source_file: str = ""
    used_by: List[str] = Field(default_factory=list)     # Programs that COPY this


class FileNode(BaseModel):
    """A file/database node."""
    assign_name: str
    fd_names: List[str] = Field(default_factory=list)    # Logical FD names across programs
    used_by: List[str] = Field(default_factory=list)     # Programs that use this file
    organization: Optional[str] = None
    access_mode: Optional[str] = None
    record_key: Optional[str] = None


class DependencyEdge(BaseModel):
    """An edge in the dependency graph."""
    source: str
    target: str
    type: EdgeType
    evidence: str = ""          # Source location/line number
    details: Dict[str, Any] = Field(default_factory=dict)  # Additional context


class DependencyGraph(BaseModel):
    """Complete dependency graph for a COBOL codebase."""
    programs: Dict[str, ProgramNode] = Field(default_factory=dict)
    copybooks: Dict[str, CopybookNode] = Field(default_factory=dict)
    files: Dict[str, FileNode] = Field(default_factory=dict)
    edges: List[DependencyEdge] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def add_program(self, node: ProgramNode) -> None:
        """Add a program node."""
        self.programs[node.name] = node

    def add_copybook(self, node: CopybookNode) -> None:
        """Add a copybook node."""
        self.copybooks[node.name] = node

    def add_file(self, node: FileNode) -> None:
        """Add a file node."""
        self.files[node.assign_name] = node

    def add_edge(self, edge: DependencyEdge) -> None:
        """Add a dependency edge."""
        self.edges.append(edge)

    def get_call_edges(self) -> List[DependencyEdge]:
        """Get all CALL edges."""
        return [e for e in self.edges if e.type == EdgeType.CALL]

    def get_copy_edges(self) -> List[DependencyEdge]:
        """Get all COPY edges."""
        return [e for e in self.edges if e.type == EdgeType.COPY]

    def get_file_edges(self) -> List[DependencyEdge]:
        """Get all SHARED_FILE edges."""
        return [e for e in self.edges if e.type == EdgeType.SHARED_FILE]

    def get_all_file_edges(self) -> List[DependencyEdge]:
        """Get all file edges (SHARED_FILE + USES_FILE)."""
        return [e for e in self.edges if e.type in [EdgeType.SHARED_FILE, EdgeType.USES_FILE]]

    def get_programs_calling(self, program_name: str) -> List[str]:
        """Get programs that call the given program."""
        callers = []
        for edge in self.get_call_edges():
            if edge.target == program_name:
                callers.append(edge.source)
        return callers

    def get_programs_called_by(self, program_name: str) -> List[str]:
        """Get programs called by the given program."""
        if program_name in self.programs:
            return self.programs[program_name].calls
        return []

    def get_entry_points(self) -> List[str]:
        """Find programs not called by any other program (entry points)."""
        called = {e.target for e in self.get_call_edges()}
        return [name for name in self.programs if name not in called]

    def get_leaf_programs(self) -> List[str]:
        """Find programs that don't call any other program."""
        callers = {e.source for e in self.get_call_edges()}
        return [name for name in self.programs if name not in callers and not self.programs[name].calls]

    def find_circular_calls(self) -> List[List[str]]:
        """Detect circular CALL dependencies using DFS."""
        from collections import defaultdict

        graph = defaultdict(list)
        for edge in self.get_call_edges():
            graph[edge.source].append(edge.target)

        visited = set()
        rec_stack = set()
        cycles = []
        path = []

        def dfs(node):
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in graph[node]:
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    # Found a cycle
                    cycle_start = path.index(neighbor)
                    cycles.append(path[cycle_start:] + [neighbor])
                    return True

            rec_stack.remove(node)
            path.pop()
            return False

        for node in self.programs:
            if node not in visited:
                dfs(node)

        return cycles

    def serialize(self, output_path: str) -> None:
        """Serialize graph to JSON file."""
        serializable = {
            "programs": {k: v.model_dump() for k, v in self.programs.items()},
            "copybooks": {k: v.model_dump() for k, v in self.copybooks.items()},
            "files": {k: v.model_dump() for k, v in self.files.items()},
            "edges": [e.model_dump() for e in self.edges],
            "metadata": self.metadata,
            "entry_points": self.get_entry_points(),
            "leaf_programs": self.get_leaf_programs(),
            "circular_dependencies": self.find_circular_calls(),
        }

        with open(output_path, 'w') as f:
            json.dump(serializable, f, indent=2)

    @classmethod
    def load(cls, input_path: str) -> "DependencyGraph":
        """Load graph from JSON file."""
        with open(input_path, 'r') as f:
            data = json.load(f)

        graph = cls(
            programs={k: ProgramNode(**v) for k, v in data.get("programs", {}).items()},
            copybooks={k: CopybookNode(**v) for k, v in data.get("copybooks", {}).items()},
            files={k: FileNode(**v) for k, v in data.get("files", {}).items()},
            edges=[DependencyEdge(**e) for e in data.get("edges", [])],
            metadata=data.get("metadata", {}),
        )
        return graph

    def to_mermaid(self) -> str:
        """
        Generate Mermaid diagram for the dependency graph.

        Returns:
            Mermaid diagram as string
        """
        lines = ["graph TB"]

        # Define subgraphs
        lines.append("    subgraph \"COBOL Programs\"")
        program_names = sorted(self.programs.keys())
        for i, prog_name in enumerate(program_names):
            safe_name = f"P{i}"
            lines.append(f"        {safe_name}[\"{prog_name}\"]")
        lines.append("    end")

        lines.append("    subgraph \"Copybooks\"")
        copybook_names = sorted(self.copybooks.keys())
        for i, cb_name in enumerate(copybook_names):
            safe_name = f"CB{i}"
            lines.append(f"        {safe_name}[\"{cb_name}\"]")
        lines.append("    end")

        lines.append("    subgraph \"Files/Datasets\"")
        file_names = sorted(self.files.keys())
        for i, file_name in enumerate(file_names):
            safe_name = f"F{i}"
            lines.append(f"        {safe_name}[\"{file_name}\"]")
        lines.append("    end")

        # COPY edges (deduplicate)
        copy_edges = set()
        for edge in self.get_copy_edges():
            if edge.source in self.programs and edge.target in self.copybooks:
                key = (edge.source, edge.target)
                if key not in copy_edges:
                    copy_edges.add(key)
                    prog_idx = program_names.index(edge.source)
                    cb_idx = copybook_names.index(edge.target)
                    lines.append(f"    P{prog_idx} -->|COPY| CB{cb_idx}")

        # CALL edges
        for edge in self.get_call_edges():
            if edge.source in self.programs and edge.target in self.programs:
                source_idx = program_names.index(edge.source)
                target_idx = program_names.index(edge.target)
                lines.append(f"    P{source_idx} -.->|CALL| P{target_idx}")

        # FILE edges (SHARED_FILE and USES_FILE)
        for edge in self.get_all_file_edges():
            if edge.source in self.programs and edge.target in self.files:
                prog_idx = program_names.index(edge.source)
                file_idx = file_names.index(edge.target)
                edge_label = "SHARED" if edge.type == EdgeType.SHARED_FILE else "USES"
                lines.append(f"    P{prog_idx} ---|{edge_label}| F{file_idx}")

        # SQL TABLE edges
        for edge in self.edges:
            if edge.type == EdgeType.SQL_TABLE:
                if edge.source in self.programs:
                    prog_idx = program_names.index(edge.source)
                    lines.append(f"    P{prog_idx} -.->|SQL:{edge.details.get('operation', '')}| {edge.target}")

        # CICS edges
        for edge in self.edges:
            if edge.type in [EdgeType.CICS_LINK, EdgeType.CICS_XCTL, EdgeType.CICS_SEND, EdgeType.CICS_RECEIVE]:
                if edge.source in self.programs:
                    prog_idx = program_names.index(edge.source)
                    label = edge.type.value.replace("CICS_", "")
                    lines.append(f"    P{prog_idx} -.->|CICS:{label}| {edge.target}")

        # File operation edges
        file_op_types = [EdgeType.FILE_OPEN, EdgeType.FILE_READ, EdgeType.FILE_WRITE,
                         EdgeType.FILE_REWRITE, EdgeType.FILE_DELETE, EdgeType.FILE_START,
                         EdgeType.FILE_CLOSE, EdgeType.FILE_UNLOCK]
        for edge in self.edges:
            if edge.type in file_op_types:
                if edge.source in self.programs:
                    prog_idx = program_names.index(edge.source)
                    label = edge.type.value.replace("FILE_", "")
                    lines.append(f"    P{prog_idx} -.->|FILE:{label}| {edge.target}")

        # Styling
        lines.append("    classDef programClass fill:#81c784,stroke:#388e3c,stroke-width:2px;")
        lines.append("    classDef copybookClass fill:#ffb74d,stroke:#f57c00,stroke-width:2px;")
        lines.append("    classDef fileClass fill:#64b5f6,stroke:#1976d2,stroke-width:2px;")
        lines.append("    classDef sqlClass fill:#ffccbc,stroke:#e65100,stroke-width:2px;")
        lines.append("    classDef cicsClass fill:#ce93d8,stroke:#7b1fa2,stroke-width:2px;")
        lines.append("    classDef fileOpClass fill:#b3e5fc,stroke:#0277bd,stroke-width:2px;")

        for i in range(len(program_names)):
            lines.append(f"    class P{i} programClass")
        for i in range(len(copybook_names)):
            lines.append(f"    class CB{i} copybookClass")
        for i in range(len(file_names)):
            lines.append(f"    class F{i} fileClass")

        return "\n".join(lines)

    def to_neo4j_cypher(self) -> str:
        """
        Generate Neo4j Cypher queries to create the dependency graph.

        Returns:
            Cypher queries as string
        """
        lines = []

        # Clear existing graph
        lines.append("MATCH (n) DETACH DELETE n;")
        lines.append("")

        # Create program nodes
        for prog_name, prog_node in self.programs.items():
            safe_name = prog_name.replace("-", "_").replace(".", "_")
            lines.append(f'CREATE (p:Program {{name: "{prog_name}", program_id: "{prog_node.program_id}"}});')

        # Create copybook nodes
        for cb_name, cb_node in self.copybooks.items():
            safe_name = cb_name.replace("-", "_").replace(".", "_")
            lines.append(f'CREATE (c:Copybook {{name: "{cb_name}", used_by: {cb_node.used_by}}});')

        # Create file nodes
        for file_name, file_node in self.files.items():
            safe_name = file_name.replace("-", "_").replace(".", "_")
            lines.append(f'CREATE (f:File {{assign_name: "{file_name}", organization: "{file_node.organization or ""}", access_mode: "{file_node.access_mode or ""}", record_key: "{file_node.record_key or ""}"}});')

        lines.append("")

        # Create CALL relationships (including external calls where target not in programs)
        for edge in self.get_call_edges():
            if edge.source in self.programs:
                source_safe = edge.source.replace("-", "_").replace(".", "_")
                target_safe = edge.target.replace("-", "_").replace(".", "_")
                # Parse evidence field (format: "PARAGRAPH:line")
                evidence_parts = edge.evidence.split(":")
                paragraph = evidence_parts[0] if evidence_parts else ""
                line_num = int(evidence_parts[1]) if len(evidence_parts) > 1 and evidence_parts[1].isdigit() else 0
                if edge.target in self.programs:
                    lines.append(f'MATCH (p1:Program {{name: "{edge.source}"}}), (p2:Program {{name: "{edge.target}"}}) CREATE (p1)-[:CALLS {{paragraph: "{paragraph}", line: {line_num}, using_params: {edge.details.get("using_params", [])}}}]->(p2);')
                else:
                    # External program - create target node if not exists, then relationship
                    lines.append(f'MERGE (p2:Program {{name: "{edge.target}"}}) ON CREATE SET p2.program_id = "{edge.target}", p2.external = true;')
                    lines.append(f'MATCH (p1:Program {{name: "{edge.source}"}}), (p2:Program {{name: "{edge.target}"}}) CREATE (p1)-[:CALLS {{paragraph: "{paragraph}", line: {line_num}, using_params: {edge.details.get("using_params", [])}}}]->(p2);')

        # Create COPY relationships (one per COPY statement to preserve REPLACING)
        for edge in self.get_copy_edges():
            if edge.source in self.programs and edge.target in self.copybooks:
                source_safe = edge.source.replace("-", "_").replace(".", "_")
                target_safe = edge.target.replace("-", "_").replace(".", "_")
                repl_str = str(edge.details.get("replacing", []))
                line_evidence = edge.evidence
                lines.append(f'MATCH (p:Program {{name: "{edge.source}"}}), (c:Copybook {{name: "{edge.target}"}}) CREATE (p)-[:COPIES {{replacing: "{repl_str}", line: "{line_evidence}"}}]->(c);')

        # Create FILE relationships (SHARED_FILE and USES_FILE)
        for edge in self.edges:
            if edge.type in [EdgeType.SHARED_FILE, EdgeType.USES_FILE]:
                if edge.source in self.programs and edge.target in self.files:
                    rel_type = "SHARED_FILE" if edge.type == EdgeType.SHARED_FILE else "USES_FILE"
                    lines.append(f'MATCH (p:Program {{name: "{edge.source}"}}), (f:File {{assign_name: "{edge.target}"}}) CREATE (p)-[:{rel_type} {{fd_name: "{edge.details.get("fd_name", "")}"}}]->(f);')

        # Create SQL TABLE relationships
        for edge in self.edges:
            if edge.type == EdgeType.SQL_TABLE:
                if edge.source in self.programs:
                    lines.append(f'MATCH (p:Program {{name: "{edge.source}"}}), (t:SqlTable {{name: "{edge.target}"}}) CREATE (p)-[:ACCESSES {{operation: "{edge.details.get("operation", "")}", line: {edge.evidence.split(":")[-1] if ":" in edge.evidence else 0}}}]->(t);')

        # Create CICS relationships
        for edge in self.edges:
            if edge.type in [EdgeType.CICS_LINK, EdgeType.CICS_XCTL, EdgeType.CICS_SEND, EdgeType.CICS_RECEIVE]:
                if edge.source in self.programs:
                    rel_type = edge.type.value
                    target_label = "Program" if edge.type in [EdgeType.CICS_LINK, EdgeType.CICS_XCTL] else "CicsMap"
                    target_name = edge.target
                    lines.append(f'MATCH (p:Program {{name: "{edge.source}"}}), (c:{target_label} {{name: "{target_name}"}}) CREATE (p)-[:{rel_type} {{line: {edge.evidence.split(":")[-1] if ":" in edge.evidence else 0}}}]->(c);')

        # Create FILE operation relationships
        for edge in self.edges:
            if edge.type in [EdgeType.FILE_OPEN, EdgeType.FILE_READ, EdgeType.FILE_WRITE,
                             EdgeType.FILE_REWRITE, EdgeType.FILE_DELETE, EdgeType.FILE_START,
                             EdgeType.FILE_CLOSE, EdgeType.FILE_UNLOCK]:
                if edge.source in self.programs and edge.target in self.files:
                    rel_type = edge.type.value
                    access_mode = edge.details.get("access_mode_implied")
                    lines.append(f'MATCH (p:Program {{name: "{edge.source}"}}), (f:File {{assign_name: "{edge.target}"}}) CREATE (p)-[:{rel_type} {{access_mode: "{access_mode}"}}]->(f);')

        return "\n".join(lines)


def build_system_graph(
    programs: Dict[str, str],
    copybook_paths: List[str] = None
) -> DependencyGraph:
    """
    Build a complete system dependency graph from COBOL programs.

    Args:
        programs: Dict mapping program_name -> source code
        copybook_paths: Paths to search for copybooks

    Returns:
        DependencyGraph with all nodes and edges
    """
    from ..cobol.extractor import extract_cobol_sections_with_copybooks
    from ..cobol.callgraph import extract_calls, extract_calls_with_context
    from ..cobol.copybook import extract_copy_statements, resolve_cobol_source, load_copybook_map
    from ..cobol.dataflow import (
        extract_file_definitions,
        extract_select_assign_from_env,
        extract_file_operations,
        analyze_file_sharing,
        extract_sql_tables,
        extract_cics_calls,
        FileDefinition
    )

    graph = DependencyGraph()
    program_files = {}  # program_name -> list of FileDefinition

    # Load copybook map
    copybook_map = {}
    if copybook_paths:
        copybook_map.update(load_copybook_map(copybook_paths))

    # Process each program
    for prog_name, source in programs.items():
        # Extract sections with copybook resolution
        if copybook_paths:
            sections = extract_cobol_sections_with_copybooks(source, copybook_paths)
        else:
            from ..cobol.extractor import extract_cobol_sections
            sections = extract_cobol_sections(source)

        program_id = sections.program_id or prog_name

        # Extract CALL statements
        calls = extract_calls(sections.procedure_division)
        call_targets = [c.target_program for c in calls if not c.is_dynamic]
        unresolved_dynamic = [
            {
                "variable": c.target_program,
                "paragraph": c.paragraph,
                "line_number": c.line_number,
                "using_params": c.using_params,
            }
            for c in calls if c.is_dynamic
        ]

        # Extract COPY statements
        copy_statements = extract_copy_statements(source)
        copy_names = [c.copy_name for c in copy_statements]

        # Extract SELECT/ASSIGN from original source
        select_assign_map = extract_select_assign_from_env(source)

        # Extract file definitions
        file_defs = extract_file_definitions(sections.file_section, select_assign_map)
        assign_names = [f.assign_name for f in file_defs]
        program_files[prog_name] = file_defs

        # Create program node
        prog_node = ProgramNode(
            name=prog_name,
            program_id=program_id,
            calls=call_targets,
            copies=copy_names,
            files=assign_names,
            unresolved_dynamic_calls=unresolved_dynamic,
        )
        graph.add_program(prog_node)

        # Add CALL edges
        for call in calls:
            edge = DependencyEdge(
                source=prog_name,
                target=call.target_program,
                type=EdgeType.DYNAMIC_CALL if call.is_dynamic else EdgeType.CALL,
                evidence=f"{call.paragraph}:{call.line_number}",
                details={
                    "using_params": call.using_params,
                    "giving_param": call.giving_param,
                    "is_dynamic": call.is_dynamic,
                }
            )
            graph.add_edge(edge)

        # Add COPY edges
        for copy_stmt in copy_statements:
            edge = DependencyEdge(
                source=prog_name,
                target=copy_stmt.copy_name,
                type=EdgeType.COPY,
                evidence=f"line {copy_stmt.line_number}",
                details={
                    "replacing": copy_stmt.replacing,
                }
            )
            graph.add_edge(edge)

            # Track copybook usage
            if copy_stmt.copy_name not in graph.copybooks:
                graph.add_copybook(CopybookNode(
                    name=copy_stmt.copy_name,
                    used_by=[prog_name],
                ))
            else:
                if prog_name not in graph.copybooks[copy_stmt.copy_name].used_by:
                    graph.copybooks[copy_stmt.copy_name].used_by.append(prog_name)

        # Extract SQL table dependencies
        sql_tables = extract_sql_tables(source)
        for sql_table in sql_tables:
            table_name = sql_table['table_name']
            edge = DependencyEdge(
                source=prog_name,
                target=table_name,
                type=EdgeType.SQL_TABLE,
                evidence=f"line {sql_table['line_number']}",
                details={
                    "operation": sql_table['operation'],
                    "context": sql_table['context'][:200],
                }
            )
            graph.add_edge(edge)

        # Extract CICS dependencies
        cics_calls = extract_cics_calls(source)
        for cics in cics_calls:
            if cics['command'] == 'LINK' and cics.get('target_program'):
                edge = DependencyEdge(
                    source=prog_name,
                    target=cics['target_program'],
                    type=EdgeType.CICS_LINK,
                    evidence=f"line {cics['line_number']}",
                    details={
                        "context": cics['context'][:200],
                    }
                )
                graph.add_edge(edge)
            elif cics['command'] == 'XCTL' and cics.get('target_program'):
                edge = DependencyEdge(
                    source=prog_name,
                    target=cics['target_program'],
                    type=EdgeType.CICS_XCTL,
                    evidence=f"line {cics['line_number']}",
                    details={
                        "context": cics['context'][:200],
                    }
                )
                graph.add_edge(edge)
            elif cics['command'] == 'SEND' and cics.get('map_name'):
                edge = DependencyEdge(
                    source=prog_name,
                    target=cics['map_name'],
                    type=EdgeType.CICS_SEND,
                    evidence=f"line {cics['line_number']}",
                    details={
                        "context": cics['context'][:200],
                    }
                )
                graph.add_edge(edge)
            elif cics['command'] == 'RECEIVE' and cics.get('map_name'):
                edge = DependencyEdge(
                    source=prog_name,
                    target=cics['map_name'],
                    type=EdgeType.CICS_RECEIVE,
                    evidence=f"line {cics['line_number']}",
                    details={
                        "context": cics['context'][:200],
                    }
                )
                graph.add_edge(edge)

        # Extract detailed file operations
        file_operations = extract_file_operations(sections.procedure_division)
        for op in file_operations:
            edge_type_map = {
                'OPEN': EdgeType.FILE_OPEN,
                'READ': EdgeType.FILE_READ,
                'WRITE': EdgeType.FILE_WRITE,
                'REWRITE': EdgeType.FILE_REWRITE,
                'DELETE': EdgeType.FILE_DELETE,
                'START': EdgeType.FILE_START,
                'CLOSE': EdgeType.FILE_CLOSE,
                'UNLOCK': EdgeType.FILE_UNLOCK,
            }
            edge_type = edge_type_map.get(op.operation)
            if edge_type:
                edge = DependencyEdge(
                    source=prog_name,
                    target=op.file_name,
                    type=edge_type,
                    evidence=f"{op.paragraph}:{op.line_number}",
                    details={
                        "access_mode_implied": op.access_mode_implied.value if op.access_mode_implied else None,
                        "context": op.details,
                    }
                )
                graph.add_edge(edge)

    # Process ALL files (not just shared)
    all_files = {}
    for prog_name, files in program_files.items():
        for fd in files:
            assign_name = fd.assign_name
            if assign_name not in all_files:
                all_files[assign_name] = {
                    'fd_names': set(),
                    'used_by': set(),
                    'organization': fd.organization,
                    'access_mode': fd.access_mode,
                    'record_key': fd.record_key,
                }
            all_files[assign_name]['fd_names'].add(fd.fd_name)
            all_files[assign_name]['used_by'].add(prog_name)

    for assign_name, file_info in all_files.items():
        file_node = FileNode(
            assign_name=assign_name,
            fd_names=list(file_info['fd_names']),
            used_by=list(file_info['used_by']),
            organization=file_info['organization'].value if file_info['organization'] else None,
            access_mode=file_info['access_mode'].value if file_info['access_mode'] else None,
            record_key=file_info['record_key'],
        )
        graph.add_file(file_node)

        # Add FILE edges (SHARED_FILE for shared, USES_FILE for single)
        edge_type = EdgeType.SHARED_FILE if len(file_info['used_by']) > 1 else EdgeType.USES_FILE
        for prog_name in file_info['used_by']:
            fd_name = next((fd.fd_name for fd in program_files[prog_name] if fd.assign_name == assign_name), "")
            edge = DependencyEdge(
                source=prog_name,
                target=assign_name,
                type=edge_type,
                evidence="FILE SECTION / ENVIRONMENT DIVISION",
                details={
                    "fd_name": fd_name,
                }
            )
            graph.add_edge(edge)

    # Add metadata
    graph.metadata = {
        "total_programs": len(graph.programs),
        "total_copybooks": len(graph.copybooks),
        "total_files": len(graph.files),
        "total_edges": len(graph.edges),
        "entry_points": graph.get_entry_points(),
        "leaf_programs": graph.get_leaf_programs(),
        "circular_calls": graph.find_circular_calls(),
    }

    return graph