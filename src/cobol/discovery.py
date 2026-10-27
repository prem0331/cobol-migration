"""Discover COBOL files and copybooks in a directory tree."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set


@dataclass
class CobolFile:
    """Represents a discovered COBOL source file."""
    path: str
    program_id: Optional[str] = None
    size: int = 0
    modified: float = 0.0


@dataclass
class Copybook:
    """Represents a discovered copybook."""
    name: str
    path: str
    size: int = 0
    modified: float = 0.0


def find_cobol_files(root_dir: str, extensions: Optional[List[str]] = None) -> List[CobolFile]:
    """
    Recursively find all COBOL source files in a directory.

    Args:
        root_dir: Root directory to search
        extensions: File extensions to consider (default: .cbl, .cob, .cobol)

    Returns:
        List of CobolFile objects
    """
    if extensions is None:
        extensions = ['.cbl', '.cob', '.cobol', '.cpy', '.copy']

    cobol_files = []
    root = Path(root_dir)

    if not root.exists():
        return cobol_files

    for ext in extensions:
        for file_path in root.rglob(f'*{ext}'):
            if file_path.is_file():
                stat = file_path.stat()
                cobol_files.append(CobolFile(
                    path=str(file_path),
                    size=stat.st_size,
                    modified=stat.st_mtime
                ))

    return cobol_files


def extract_program_id(source: str) -> Optional[str]:
    """Extract PROGRAM-ID from COBOL source."""
    # Match PROGRAM-ID. PROGNAME or PROGRAM-ID PROGNAME
    match = re.search(r'PROGRAM-ID\s*\.?\s*([A-Z0-9-]+)', source, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def find_copybooks(search_paths: List[str], extensions: Optional[List[str]] = None) -> Dict[str, Copybook]:
    """
    Find all copybooks in the given search paths.

    Args:
        search_paths: List of directories to search for copybooks
        extensions: File extensions for copybooks

    Returns:
        Dictionary mapping copybook name (uppercase) to Copybook object
    """
    if extensions is None:
        extensions = ['.cpy', '.copy', '.cbl', '.cob']

    copybooks = {}

    for search_path in search_paths:
        path = Path(search_path)
        if not path.exists():
            continue

        for ext in extensions:
            for file_path in path.rglob(f'*{ext}'):
                if file_path.is_file():
                    # Use stem as copybook name (without extension)
                    name = file_path.stem.upper()
                    stat = file_path.stat()

                    # Only keep first found (or could warn about duplicates)
                    if name not in copybooks:
                        copybooks[name] = Copybook(
                            name=name,
                            path=str(file_path),
                            size=stat.st_size,
                            modified=stat.st_mtime
                        )

    return copybooks


def read_copybook_content(copybook: Copybook) -> str:
    """Read copybook content with encoding fallback."""
    encodings = ['utf-8', 'cp1252', 'latin-1', 'iso-8859-1']

    for encoding in encodings:
        try:
            return Path(copybook.path).read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue

    # Last resort: read as binary and decode with replacement
    return Path(copybook.path).read_text(encoding='utf-8', errors='replace')


def discover_all(root_dir: str, copybook_paths: Optional[List[str]] = None) -> Dict:
    """
    Discover all COBOL files and copybooks in a project.

    Args:
        root_dir: Root directory for COBOL source files
        copybook_paths: Additional directories to search for copybooks

    Returns:
        Dictionary with 'files' (List[CobolFile]) and 'copybooks' (Dict[str, Copybook])
    """
    # Find COBOL files
    cobol_files = find_cobol_files(root_dir)

    # Extract program IDs
    for cf in cobol_files:
        try:
            source = Path(cf.path).read_text(encoding='utf-8', errors='replace')
            cf.program_id = extract_program_id(source)
        except Exception:
            pass

    # Find copybooks
    if copybook_paths is None:
        copybook_paths = [os.path.join(root_dir, 'copybooks'),
                          os.path.join(root_dir, 'cobol', 'copybooks'),
                          os.path.join(root_dir, 'cpy')]

    # Also check same directory as source files
    for cf in cobol_files:
        copybook_paths.append(os.path.dirname(cf.path))

    # Deduplicate paths
    copybook_paths = list(dict.fromkeys(copybook_paths))

    copybooks = find_copybooks(copybook_paths)

    return {
        'files': cobol_files,
        'copybooks': copybooks,
        'copybook_paths': copybook_paths
    }


def filter_cobol_programs(files: List[CobolFile],
                          exclude_copybooks: bool = True) -> List[CobolFile]:
    """
    Filter to only main COBOL programs (exclude copybooks).

    Args:
        files: List of discovered files
        exclude_copybooks: If True, exclude files that look like copybooks

    Returns:
        Filtered list of program files
    """
    if not exclude_copybooks:
        return files

    programs = []
    for f in files:
        # Heuristic: copybooks often don't have PROGRAM-ID
        # or are in copybooks/ directory
        path_lower = f.path.lower()
        if 'copybook' in path_lower or f.path.endswith(('.cpy', '.copy')):
            # Could be a copybook, check for PROGRAM-ID
            if f.program_id is None:
                continue
        programs.append(f)

    return programs