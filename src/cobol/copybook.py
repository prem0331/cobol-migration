"""Resolve COPY statements in COBOL source code."""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class CopyStatement:
    """Represents a COPY statement found in COBOL source."""
    copy_name: str
    replacing: List[Tuple[str, str]] = None  # List of (old, new) pairs
    line_number: int = 0
    original_text: str = ""

    def __post_init__(self):
        if self.replacing is None:
            self.replacing = []


def extract_copy_statements(source: str) -> List[CopyStatement]:
    """
    Extract all COPY statements from COBOL source.

    Handles:
    - COPY copybook-name
    - COPY copybook-name REPLACING old BY new
    - COPY copybook-name REPLACING ==old== BY ==new==
    - Nested COPY (handled by resolver)
    """
    statements = []
    lines = source.split('\n')

    for i, line in enumerate(lines):
        line_num = i + 1

        # Skip if line too short
        if len(line) < 7:
            continue

        # Check column 7 (0-indexed: 6) for comment indicator
        if line[6] == '*':
            continue
        if line.strip().startswith('*>'):
            continue

        # Get the statement area (columns 8-72 in standard COBOL, or 8+ in free format)
        # COBOL statements start at column 8 (0-indexed: 7)
        stmt_area = line[7:] if len(line) > 7 else ''

        # Match COPY statement in statement area
        match = re.search(
            r'^COPY\s+([A-Z0-9-]+)(?:\s+REPLACING\s+(.*?))?(?:\s*\.)?$',
            stmt_area.strip(),
            re.IGNORECASE
        )

        if match:
            copy_name = match.group(1).strip()
            replacing_text = match.group(2)

            replacing = []
            if replacing_text:
                # Parse REPLACING clauses
                # Format: old BY new or ==old== BY ==new==
                # Also handle: CUST- BY CLIENT- (without == delimiters)
                repl_matches = re.finditer(
                    r'(==?([^=]+)==?|([A-Z0-9-]+))\s+BY\s+(==?([^=]+)==?|([A-Z0-9-]+))',
                    replacing_text,
                    re.IGNORECASE
                )
                for repl in repl_matches:
                    # Group 2 is for ==old== format, group 3 is for plain format
                    old = (repl.group(2) or repl.group(3) or '').strip()
                    # Group 5 is for ==new== format, group 6 is for plain format
                    new = (repl.group(5) or repl.group(6) or '').strip()
                    if old and new:
                        replacing.append((old, new))

            statements.append(CopyStatement(
                copy_name=copy_name,
                replacing=replacing,
                line_number=line_num,
                original_text=stmt_area.strip()
            ))

    return statements


def resolve_copy_statement(
    copy_stmt: CopyStatement,
    copybook_content: str,
    copybook_map: Dict[str, str]
) -> str:
    """
    Resolve a single COPY statement by inlining the copybook content.

    Args:
        copy_stmt: The COPY statement to resolve
        copybook_content: Content of the copybook
        copybook_map: Map of all copybooks (for nested COPY)

    Returns:
        Resolved content with REPLACING applied
    """
    content, _ = resolve_copy_statement_with_tracking(copy_stmt, copybook_content, copybook_map)
    return content


def resolve_all_copies(
    source: str,
    copybook_map: Dict[str, str],
    unresolved_handler: str = 'comment'
) -> Tuple[str, List[CopyStatement]]:
    """
    Resolve all COPY statements in source code.

    Args:
        source: COBOL source code
        copybook_map: Dictionary mapping copybook name -> content
        unresolved_handler: How to handle unresolved copybooks
            - 'comment': Replace with comment (default)
            - 'keep': Keep original COPY statement
            - 'error': Raise exception

    Returns:
        Tuple of (resolved_source, list_of_all_copy_statements)
    """
    all_statements = []
    lines = source.split('\n')
    resolved_lines = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Check for COPY statement
        match = re.search(
            r'COPY\s+([A-Z0-9-]+)(?:\s+REPLACING\s+(.*?))?(?:\s*\.)?$',
            stripped,
            re.IGNORECASE
        )

        if match:
            copy_name = match.group(1).strip().upper()
            replacing_text = match.group(2)

            # Parse REPLACING
            replacing = []
            if replacing_text:
                repl_matches = re.finditer(
                    r'(==?([^=]+)==?|([A-Z0-9-]+))\s+BY\s+(==?([^=]+)==?|([A-Z0-9-]+))',
                    replacing_text,
                    re.IGNORECASE
                )
                for repl in repl_matches:
                    # Group 2 is for ==old== format, group 3 is for plain format
                    old = (repl.group(2) or repl.group(3) or '').strip()
                    # Group 5 is for ==new== format, group 6 is for plain format
                    new = (repl.group(5) or repl.group(6) or '').strip()
                    if old and new:
                        replacing.append((old, new))

            stmt = CopyStatement(
                copy_name=copy_name,
                replacing=replacing,
                line_number=i + 1,
                original_text=line
            )
            all_statements.append(stmt)

            # Resolve copybook
            if copy_name in copybook_map:
                copybook_content = copybook_map[copy_name]
                resolved_content, nested_stmts = resolve_copy_statement_with_tracking(
                    stmt, copybook_content, copybook_map
                )
                all_statements.extend(nested_stmts)

                # Split resolved content into lines and add
                for resolved_line in resolved_content.split('\n'):
                    resolved_lines.append(resolved_line)
            else:
                # Copybook not found
                if unresolved_handler == 'comment':
                    resolved_lines.append(f"*> UNRESOLVED COPY {copy_name}: {line.strip()}")
                elif unresolved_handler == 'keep':
                    resolved_lines.append(line)
                elif unresolved_handler == 'error':
                    raise ValueError(f"Copybook not found: {copy_name} at line {i + 1}")

            i += 1
        else:
            resolved_lines.append(line)
            i += 1

    resolved_source = '\n'.join(resolved_lines)
    return resolved_source, all_statements


def resolve_copy_statement_with_tracking(
    copy_stmt: CopyStatement,
    copybook_content: str,
    copybook_map: Dict[str, str]
) -> Tuple[str, List[CopyStatement]]:
    """
    Resolve a single COPY statement and track nested COPY statements.

    Args:
        copy_stmt: The COPY statement to resolve
        copybook_content: Content of the copybook
        copybook_map: Map of all copybooks (for nested COPY)

    Returns:
        Tuple of (resolved_content, list_of_nested_copy_statements)
    """
    content = copybook_content
    nested_statements = []

    # Apply REPLACING if specified
    for old, new in copy_stmt.replacing:
        # Replace whole words only
        pattern = r'\b' + re.escape(old) + r'\b'
        content = re.sub(pattern, new, content)

    # Check for nested COPY statements
    nested_copies = extract_copy_statements(content)
    for nested in nested_copies:
        if nested.copy_name.upper() in copybook_map:
            nested_content, deeper_nested = resolve_copy_statement_with_tracking(
                nested,
                copybook_map[nested.copy_name.upper()],
                copybook_map
            )
            nested_statements.append(nested)
            nested_statements.extend(deeper_nested)
            # Replace the COPY line with resolved content
            content = content.replace(nested.original_text, nested_content)
        else:
            # Nested copybook not found - leave as comment for visibility
            content = content.replace(
                nested.original_text,
                f"*> UNRESOLVED COPY: {nested.original_text}"
            )
            nested_statements.append(nested)

    return content, nested_statements


def load_copybook_map(copybook_paths) -> Dict[str, str]:
    """
    Load all copybooks from search paths into a map.

    Args:
        copybook_paths: List of directories to search, or a single directory path string

    Returns:
        Dictionary mapping uppercase copybook name -> content
    """
    copybook_map = {}

    # Handle both string and list input
    if isinstance(copybook_paths, str):
        copybook_paths = [copybook_paths]

    for search_path in copybook_paths:
        path = Path(search_path)
        if not path.exists():
            continue

        # Use walk instead of rglob to handle permission errors gracefully
        try:
            for file_path in path.rglob('*'):
                try:
                    if not file_path.is_file():
                        continue
                    if file_path.suffix.lower() not in ['.cpy', '.copy']:
                        continue
                    name = file_path.stem.upper()
                    if name not in copybook_map:
                        try:
                            content = file_path.read_text(encoding='utf-8', errors='replace')
                            copybook_map[name] = content
                        except Exception:
                            pass
                except (PermissionError, OSError):
                    # Skip files we can't read
                    continue
        except (PermissionError, OSError):
            # Skip directories we can't traverse
            continue

    return copybook_map


def resolve_cobol_source(
    source: str,
    copybook_paths: List[str],
    unresolved_handler: str = 'comment'
) -> Tuple[str, List[CopyStatement]]:
    """
    Convenience function to resolve all COPY statements in a COBOL source.

    Args:
        source: COBOL source code
        copybook_paths: List of directories to search for copybooks
        unresolved_handler: How to handle unresolved copybooks

    Returns:
        Tuple of (resolved_source, list_of_copy_statements)
    """
    copybook_map = load_copybook_map(copybook_paths)
    return resolve_all_copies(source, copybook_map, unresolved_handler)


# Import Path for convenience
from pathlib import Path