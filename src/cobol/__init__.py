"""COBOL parsing utilities for the migration pipeline."""

from .extractor import (
    extract_cobol_sections,
    extract_cobol_sections_with_copybooks,
    CobolSections,
    clean_cobol_source,
)
from .parser import parse_cobol_file, ParsedCobol
from .discovery import (
    find_cobol_files,
    find_copybooks,
    discover_all,
    filter_cobol_programs,
    CobolFile,
    Copybook,
)
from .copybook import (
    resolve_cobol_source,
    extract_copy_statements,
    load_copybook_map,
    CopyStatement,
)
from .callgraph import (
    extract_calls,
    extract_calls_with_context,
    build_call_graph,
    find_entry_points,
    find_leaf_programs,
    find_circular_calls,
    serialize_call_graph,
    load_call_graph,
    CallStatement,
)

__all__ = [
    "extract_cobol_sections",
    "extract_cobol_sections_with_copybooks",
    "CobolSections",
    "clean_cobol_source",
    "parse_cobol_file",
    "ParsedCobol",
    "find_cobol_files",
    "find_copybooks",
    "discover_all",
    "filter_cobol_programs",
    "CobolFile",
    "Copybook",
    "resolve_cobol_source",
    "extract_copy_statements",
    "load_copybook_map",
    "CopyStatement",
    "extract_calls",
    "extract_calls_with_context",
    "build_call_graph",
    "find_entry_points",
    "find_leaf_programs",
    "find_circular_calls",
    "serialize_call_graph",
    "load_call_graph",
    "CallStatement",
]