"""Extract CALL statements and build call graphs from COBOL programs."""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set
from pathlib import Path


@dataclass
class CallStatement:
    """Represents a CALL statement in COBOL."""
    target_program: str          # Program name being called (or variable for dynamic)
    using_params: List[str]      # Parameters in USING clause
    giving_param: Optional[str] = None  # RETURNING/GIVING parameter
    is_dynamic: bool = False     # True if CALL variable-name
    paragraph: str = ""          # Paragraph where call appears
    line_number: int = 0         # Line number in source
    original_text: str = ""      # Original CALL statement text


def extract_calls(proc_division: str, paragraphs: List[str] = None) -> List[CallStatement]:
    """
    Extract all CALL statements from PROCEDURE DIVISION.

    Args:
        proc_division: PROCEDURE DIVISION source code
        paragraphs: Optional list of paragraph names (for context)

    Returns:
        List of CallStatement objects
    """
    calls = []
    lines = proc_division.split('\n')

    current_paragraph = ""
    para_pattern = re.compile(r'^([A-Z][A-Z0-9-]*)\s*\.$', re.IGNORECASE)

    for i, line in enumerate(lines):
        line_num = i + 1
        stripped = line.strip()

        # Skip empty lines and comments
        if not stripped:
            continue
        if len(stripped) >= 7 and stripped[6] == '*':
            continue
        if stripped.startswith('*>'):
            continue

        # Track current paragraph
        para_match = para_pattern.match(stripped)
        if para_match:
            current_paragraph = para_match.group(1)
            continue

        # Match CALL statements
        # CALL "program-name" [USING param1 param2 ...] [RETURNING result]
        # CALL 'program-name' [USING param1 param2 ...] [RETURNING result]
        # CALL WS-PROG-NAME [USING ...] (dynamic call)
        call_match = re.search(
            r'CALL\s+(?:"([^"]+)"|\'([^\']+)\'|([A-Z0-9-]+))'
            r'(?:\s+USING\s+(.*?))?'
            r'(?:\s+(?:RETURNING|GIVING)\s+(\S+))?'
            r'(?:\s*\.)?$',
            stripped,
            re.IGNORECASE
        )

        if call_match:
            # Group 1: literal program name "PROGNAME" (double quotes)
            # Group 2: literal program name 'PROGNAME' (single quotes)
            # Group 3: variable name for dynamic call (no quotes)
            double_quoted = call_match.group(1)
            single_quoted = call_match.group(2)
            variable_target = call_match.group(3)
            using_text = call_match.group(4)
            giving = call_match.group(5)

            if double_quoted:
                target = double_quoted
                is_dynamic = False
            elif single_quoted:
                target = single_quoted
                is_dynamic = False
            else:
                target = variable_target
                is_dynamic = True

            # Parse USING parameters
            using_params = []
            if using_text:
                # Split by spaces, but handle potential subscripts
                params = re.split(r'\s+', using_text.strip())
                using_params = [p.strip().rstrip('.') for p in params if p.strip()]

            # Clean giving parameter
            if giving:
                giving = giving.strip().rstrip('.')

            calls.append(CallStatement(
                target_program=target,
                using_params=using_params,
                giving_param=giving,
                is_dynamic=is_dynamic,
                paragraph=current_paragraph,
                line_number=line_num,
                original_text=stripped
            ))

    return calls


def extract_calls_with_context(proc_division: str) -> Dict[str, List[CallStatement]]:
    """
    Extract CALL statements grouped by paragraph.

    Returns:
        Dictionary mapping paragraph name -> list of CallStatement
    """
    calls = extract_calls(proc_division)
    grouped = {}

    for call in calls:
        para = call.paragraph or "UNKNOWN"
        if para not in grouped:
            grouped[para] = []
        grouped[para].append(call)

    return grouped


def build_call_graph(programs: Dict[str, str], copybook_paths: List[str] = None) -> Dict:
    """
    Build a call graph from multiple COBOL programs.

    Args:
        programs: Dict mapping program_name -> source code
        copybook_paths: Paths to search for copybooks (for resolution)

    Returns:
        Dictionary with 'nodes' and 'edges' for the call graph
    """
    from .extractor import extract_cobol_sections_with_copybooks

    nodes = {}
    edges = []
    unresolved_calls = []

    for prog_name, source in programs.items():
        # Extract sections (with copybook resolution if paths provided)
        if copybook_paths:
            sections = extract_cobol_sections_with_copybooks(source, copybook_paths)
        else:
            from .extractor import extract_cobol_sections
            sections = extract_cobol_sections(source)

        calls = extract_calls(sections.procedure_division)

        nodes[prog_name] = {
            'program_id': prog_name,
            'source_file': '',  # Would be populated by caller
            'calls': []
        }

        for call in calls:
            edge = {
                'source': prog_name,
                'target': call.target_program,
                'type': 'DYNAMIC_CALL' if call.is_dynamic else 'STATIC_CALL',
                'paragraph': call.paragraph,
                'line_number': call.line_number,
                'using_params': call.using_params,
                'giving_param': call.giving_param,
                'original_text': call.original_text
            }
            edges.append(edge)
            nodes[prog_name]['calls'].append(call.target_program)

            if call.is_dynamic:
                unresolved_calls.append({
                    'source_program': prog_name,
                    'variable': call.target_program,
                    'paragraph': call.paragraph,
                    'line_number': call.line_number
                })

    return {
        'nodes': nodes,
        'edges': edges,
        'unresolved_dynamic_calls': unresolved_calls
    }


def find_entry_points(call_graph: Dict) -> List[str]:
    """Find programs that are not called by any other program (entry points)."""
    called = set()
    for edge in call_graph['edges']:
        called.add(edge['target'])

    entry_points = []
    for node_name in call_graph['nodes']:
        if node_name not in called:
            entry_points.append(node_name)

    return entry_points


def find_leaf_programs(call_graph: Dict) -> List[str]:
    """Find programs that don't call any other program."""
    callers = set()
    for edge in call_graph['edges']:
        callers.add(edge['source'])

    leaf_programs = []
    for node_name, node_data in call_graph['nodes'].items():
        if node_name not in callers and not node_data['calls']:
            leaf_programs.append(node_name)

    return leaf_programs


def find_circular_calls(call_graph: Dict) -> List[List[str]]:
    """Detect circular call dependencies using DFS."""
    from collections import defaultdict

    graph = defaultdict(list)
    for edge in call_graph['edges']:
        if not edge.get('is_dynamic', False):  # Only static calls for cycle detection
            graph[edge['source']].append(edge['target'])

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

    for node in call_graph['nodes']:
        if node not in visited:
            dfs(node)

    return cycles


def serialize_call_graph(call_graph: Dict, output_path: str) -> None:
    """Serialize call graph to JSON file."""
    import json

    serializable = {
        'nodes': call_graph['nodes'],
        'edges': call_graph['edges'],
        'unresolved_dynamic_calls': call_graph.get('unresolved_dynamic_calls', []),
        'entry_points': find_entry_points(call_graph),
        'leaf_programs': find_leaf_programs(call_graph),
        'circular_dependencies': find_circular_calls(call_graph)
    }

    with open(output_path, 'w') as f:
        json.dump(serializable, f, indent=2)


def load_call_graph(input_path: str) -> Dict:
    """Load call graph from JSON file."""
    import json

    with open(input_path, 'r') as f:
        return json.load(f)