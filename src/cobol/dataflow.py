"""Analyze file I/O and shared data dependencies in COBOL programs."""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set
from enum import Enum


class FileAccessMode(Enum):
    """COBOL file access modes."""
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    I_O = "I-O"
    EXTEND = "EXTEND"
    RANDOM = "RANDOM"
    SEQUENTIAL = "SEQUENTIAL"
    DYNAMIC = "DYNAMIC"


class FileOrganization(Enum):
    """COBOL file organizations."""
    SEQUENTIAL = "SEQUENTIAL"
    INDEXED = "INDEXED"
    RELATIVE = "RELATIVE"
    LINE_SEQUENTIAL = "LINE SEQUENTIAL"


@dataclass
class FileDefinition:
    """Represents a file definition from FILE SECTION."""
    fd_name: str                  # FD name (e.g., CUSTOMER-FILE)
    assign_name: str              # ASSIGN TO name (e.g., CUSTMAST)
    organization: Optional[FileOrganization] = None
    access_mode: Optional[FileAccessMode] = None
    record_key: Optional[str] = None          # RECORD KEY for INDEXED
    alternate_keys: List[str] = None          # ALTERNATE RECORD KEY
    file_status: Optional[str] = None         # FILE STATUS variable
    block_size: Optional[int] = None          # BLOCK CONTAINS
    record_size: Optional[str] = None         # RECORD CONTAINS
    label_records: Optional[str] = None       # LABEL RECORDS
    data_records: List[str] = None            # DATA RECORDS ARE

    def __post_init__(self):
        if self.alternate_keys is None:
            self.alternate_keys = []
        if self.data_records is None:
            self.data_records = []


@dataclass
class FileOperation:
    """Represents a file I/O operation in PROCEDURE DIVISION."""
    operation: str                # OPEN, CLOSE, READ, WRITE, REWRITE, DELETE, START
    file_name: str                # FD name or file-name
    paragraph: str                # Paragraph where operation occurs
    line_number: int = 0
    details: str = ""             # Additional context (KEY IS, AT END, etc.)
    access_mode_implied: Optional[FileAccessMode] = None  # Inferred from operation


def extract_file_definitions(file_section: str, select_assign_map: Dict[str, Dict] = None) -> List[FileDefinition]:
    """
    Extract file definitions from FILE SECTION.

    Parses:
    - FD entries
    - SELECT/ASSIGN clauses (from ENVIRONMENT DIVISION if available)
    - ORGANIZATION, ACCESS MODE, RECORD KEY, etc.
    """
    files = []

    # For now, parse FD entries from FILE SECTION
    # FD pattern: FD filename [clauses...]
    # Match until next FD, SD, 01-level, or end of section
    fd_pattern = re.compile(
        r'FD\s+([A-Z0-9-]+)\s*(.*?)(?=\n\s*(?:FD|SD)\s|\n\s*01\s|\Z)',
        re.IGNORECASE | re.DOTALL
    )

    for match in fd_pattern.finditer(file_section):
        fd_name = match.group(1).strip()
        fd_clauses = match.group(2).strip()

        # Trim at first 01-level or next section
        lines = fd_clauses.split('\n')
        trimmed_lines = []
        for line in lines:
            if re.match(r'^\s*01\s+', line):
                break
            trimmed_lines.append(line)
        fd_clauses = '\n'.join(trimmed_lines)

        # Extract clauses from FD
        assign_match = re.search(r'ASSIGN\s+TO\s+([A-Z0-9-]+)', fd_clauses, re.IGNORECASE)
        org_match = re.search(r'ORGANIZATION\s+IS\s+(\w+)', fd_clauses, re.IGNORECASE)
        access_match = re.search(r'ACCESS\s+MODE\s+IS\s+(\w+)', fd_clauses, re.IGNORECASE)
        rec_key_match = re.search(r'RECORD\s+KEY\s+IS\s+([A-Z0-9-]+)', fd_clauses, re.IGNORECASE)
        alt_key_matches = re.findall(r'ALTERNATE\s+RECORD\s+KEY\s+IS\s+([A-Z0-9-]+)', fd_clauses, re.IGNORECASE)
        file_status_match = re.search(r'FILE\s+STATUS\s+IS\s+([A-Z0-9-]+)', fd_clauses, re.IGNORECASE)
        block_match = re.search(r'BLOCK\s+CONTAINS\s+(\d+)', fd_clauses, re.IGNORECASE)
        record_match = re.search(r'RECORD\s+CONTAINS\s+([\d\-]+)', fd_clauses, re.IGNORECASE)
        label_match = re.search(r'LABEL\s+RECORDS?\s+(?:ARE\s+)?(\S+)', fd_clauses, re.IGNORECASE)
        data_rec_match = re.search(r'DATA\s+RECORDS?\s+(?:ARE\s+)?([A-Z0-9-\s,]+)', fd_clauses, re.IGNORECASE)

        data_records = []
        if data_rec_match:
            data_records = [r.strip() for r in data_rec_match.group(1).split(',')]

        # Override with SELECT/ASSIGN info if available
        select_info = select_assign_map.get(fd_name, {}) if select_assign_map else {}

        file_def = FileDefinition(
            fd_name=fd_name,
            assign_name=select_info.get('assign', assign_match.group(1) if assign_match else fd_name),
            organization=FileOrganization(select_info.get('organization', org_match.group(1).strip().replace(' ', '_')) if org_match else select_info.get('organization')) if select_info.get('organization') or org_match else None,
            access_mode=FileAccessMode(select_info.get('access_mode', access_match.group(1).strip()) if access_match else select_info.get('access_mode')) if select_info.get('access_mode') or access_match else None,
            record_key=select_info.get('record_key', rec_key_match.group(1) if rec_key_match else None),
            alternate_keys=alt_key_matches,
            file_status=select_info.get('file_status', file_status_match.group(1) if file_status_match else None),
            block_size=int(block_match.group(1)) if block_match else None,
            record_size=record_match.group(1) if record_match else None,
            label_records=label_match.group(1) if label_match else None,
            data_records=data_records
        )
        files.append(file_def)

    return files


def extract_file_operations(proc_division: str, paragraphs: List[str] = None) -> List[FileOperation]:
    """
    Extract file I/O operations from PROCEDURE DIVISION.

    Operations: OPEN, CLOSE, READ, WRITE, REWRITE, DELETE, START, UNLOCK
    """
    operations = []
    lines = proc_division.split('\n')

    current_paragraph = ""
    para_pattern = re.compile(r'^([A-Z][A-Z0-9-]*)\s*\.$', re.IGNORECASE)

    for i, line in enumerate(lines):
        line_num = i + 1
        stripped = line.strip()

        if not stripped:
            continue
        if len(stripped) >= 7 and stripped[6] == '*':
            continue
        if stripped.startswith('*>'):
            continue

        # Track paragraph
        para_match = para_pattern.match(stripped)
        if para_match:
            current_paragraph = para_match.group(1)
            continue

        # Match file operations
        # OPEN INPUT/OUTPUT/I-O/EXTEND file-name...
        open_match = re.search(
            r'OPEN\s+(INPUT|OUTPUT|I-O|EXTEND)\s+(.+?)(?:\s*\.)?$',
            stripped,
            re.IGNORECASE
        )
        if open_match:
            mode = FileAccessMode(open_match.group(1).upper())
            files = [f.strip() for f in open_match.group(2).split()]
            for f in files:
                operations.append(FileOperation(
                    operation="OPEN",
                    file_name=f,
                    paragraph=current_paragraph,
                    line_number=line_num,
                    access_mode_implied=mode,
                    details=f"Mode: {mode.value}"
                ))
            continue

        # CLOSE file-name...
        close_match = re.search(
            r'CLOSE\s+(.+?)(?:\s*\.)?$',
            stripped,
            re.IGNORECASE
        )
        if close_match:
            files = [f.strip() for f in close_match.group(1).split()]
            for f in files:
                operations.append(FileOperation(
                    operation="CLOSE",
                    file_name=f,
                    paragraph=current_paragraph,
                    line_number=line_num,
                    details=close_match.group(1)
                ))
            continue

        # READ file-name [NEXT/RECORD] [INTO ws] [KEY IS...] [AT END...]
        read_match = re.search(
            r'READ\s+([A-Z0-9-]+)'
            r'(?:\s+(?:NEXT|PREVIOUS))?'
            r'(?:\s+RECORD)?'
            r'(?:\s+INTO\s+(\S+))?'
            r'(?:\s+KEY\s+IS\s+(\S+))?'
            r'(?:\s+AT\s+END.*)?',
            stripped,
            re.IGNORECASE
        )
        if read_match:
            operations.append(FileOperation(
                operation="READ",
                file_name=read_match.group(1),
                paragraph=current_paragraph,
                line_number=line_num,
                access_mode_implied=FileAccessMode.INPUT,
                details=stripped
            ))
            continue

        # WRITE record-name [FROM ws] [INVALID KEY...]
        # Note: WRITE uses record name, but we track it as file operation
        write_match = re.search(
            r'WRITE\s+([A-Z0-9-]+)'
            r'(?:\s+FROM\s+(\S+))?'
            r'(?:\s+INVALID\s+KEY.*)?',
            stripped,
            re.IGNORECASE
        )
        if write_match:
            operations.append(FileOperation(
                operation="WRITE",
                file_name=write_match.group(1),  # This is the record name
                paragraph=current_paragraph,
                line_number=line_num,
                access_mode_implied=FileAccessMode.OUTPUT,
                details=stripped
            ))
            continue

        # REWRITE record-name [FROM ws] [INVALID KEY...]
        rewrite_match = re.search(
            r'REWRITE\s+([A-Z0-9-]+)'
            r'(?:\s+FROM\s+(\S+))?'
            r'(?:\s+INVALID\s+KEY.*)?',
            stripped,
            re.IGNORECASE
        )
        if rewrite_match:
            operations.append(FileOperation(
                operation="REWRITE",
                file_name=rewrite_match.group(1),  # This is the record name
                paragraph=current_paragraph,
                line_number=line_num,
                access_mode_implied=FileAccessMode.I_O,
                details=stripped
            ))
            continue

        # DELETE file-name [INVALID KEY...]
        delete_match = re.search(
            r'DELETE\s+([A-Z0-9-]+)'
            r'(?:\s+INVALID\s+KEY.*)?',
            stripped,
            re.IGNORECASE
        )
        if delete_match:
            file_name = delete_match.group(1)
            # Filter out keywords that are not file names
            if file_name.upper() not in ['ERROR', 'DISPLAY', 'NOT', 'END', 'KEY', 'INVALID']:
                operations.append(FileOperation(
                    operation="DELETE",
                    file_name=file_name,
                    paragraph=current_paragraph,
                    line_number=line_num,
                    access_mode_implied=FileAccessMode.I_O,
                    details=stripped
                ))
            continue

        # START file-name [KEY IS...] [INVALID KEY...]
        start_match = re.search(
            r'START\s+([A-Z0-9-]+)'
            r'(?:\s+KEY\s+(?:IS\s+)?(?:EQUAL\s+TO|NOT\s+EQUAL\s+TO|GREATER\s+THAN|NOT\s+GREATER\s+THAN|LESS\s+THAN|NOT\s+LESS\s+THAN)\s+(\S+))?'
            r'(?:\s+INVALID\s+KEY.*)?',
            stripped,
            re.IGNORECASE
        )
        if start_match:
            file_name = start_match.group(1)
            # Filter out keywords that are not file names
            if file_name.upper() not in ['ERROR', 'DISPLAY', 'NOT', 'END', 'KEY', 'INVALID']:
                operations.append(FileOperation(
                    operation="START",
                    file_name=file_name,
                    paragraph=current_paragraph,
                    line_number=line_num,
                    access_mode_implied=FileAccessMode.I_O,
                    details=stripped
                ))
            continue

        # UNLOCK file-name
        unlock_match = re.search(
            r'UNLOCK\s+([A-Z0-9-]+)',
            stripped,
            re.IGNORECASE
        )
        if unlock_match:
            operations.append(FileOperation(
                operation="UNLOCK",
                file_name=unlock_match.group(1),
                paragraph=current_paragraph,
                line_number=line_num,
                details=stripped
            ))

    return operations


def analyze_file_sharing(programs: Dict[str, List[FileDefinition]]) -> Dict[str, List[str]]:
    """
    Analyze which programs share the same files (by ASSIGN name).

    Args:
        programs: Dict mapping program_name -> list of FileDefinition

    Returns:
        Dict mapping assign_name -> list of program_names that use it
    """
    file_usage = {}

    for prog_name, files in programs.items():
        for f in files:
            assign = f.assign_name
            if assign not in file_usage:
                file_usage[assign] = []
            if prog_name not in file_usage[assign]:
                file_usage[assign].append(prog_name)

    # Filter to only shared files (used by >1 program)
    shared = {assign: progs for assign, progs in file_usage.items() if len(progs) > 1}
    return shared


def extract_select_assign_from_env(env_division: str) -> Dict[str, Dict]:
    """
    Extract SELECT/ASSIGN clauses from ENVIRONMENT DIVISION.

    Returns:
        Dict mapping logical file name -> {assign, organization, access_mode, ...}
    """
    select_map = {}

    # Match each SELECT clause - find SELECT ... (until next SELECT or end)
    # Use a simpler approach: find all SELECT statements
    select_pattern = re.compile(
        r'SELECT\s+([A-Z0-9-]+)\s+ASSIGN\s+TO\s+([A-Z0-9-]+)'
        r'(?:\s+ORGANIZATION\s+IS\s+(\w+))?'
        r'(?:\s+ACCESS\s+MODE\s+IS\s+(\w+))?'
        r'(?:\s+RECORD\s+KEY\s+IS\s+([A-Z0-9-]+))?'
        r'(?:\s+ALTERNATE\s+RECORD\s+KEY\s+IS\s+([A-Z0-9-]+))?'
        r'(?:\s+FILE\s+STATUS\s+IS\s+([A-Z0-9-]+))?',
        re.IGNORECASE
    )

    for match in select_pattern.finditer(env_division):
        logical_name = match.group(1).strip()
        select_map[logical_name] = {
            'assign': match.group(2).strip() if match.group(2) else logical_name,
            'organization': match.group(3).strip().replace(' ', '_') if match.group(3) else None,
            'access_mode': match.group(4).strip() if match.group(4) else None,
            'record_key': match.group(5).strip() if match.group(5) else None,
            'alternate_key': match.group(6).strip() if match.group(6) else None,
            'file_status': match.group(7).strip() if match.group(7) else None,
        }

    return select_map


def extract_sql_tables(source: str) -> List[Dict]:
    """
    Extract SQL table references from EXEC SQL blocks.

    Returns:
        List of dicts with table_name, operation, line_number, context
    """
    tables = []
    lines = source.split('\n')

    in_exec_sql = False
    sql_buffer = []
    sql_start_line = 0

    for i, line in enumerate(lines):
        line_num = i + 1
        stripped = line.strip()

        # Skip comments
        if len(stripped) >= 7 and stripped[6] == '*':
            continue
        if stripped.startswith('*>'):
            continue

        # Check for EXEC SQL start
        if re.search(r'EXEC\s+SQL', stripped, re.IGNORECASE):
            in_exec_sql = True
            sql_start_line = line_num
            sql_buffer = [stripped]
            continue

        if in_exec_sql:
            sql_buffer.append(stripped)

            # Check for END-EXEC
            if re.search(r'END-EXEC', stripped, re.IGNORECASE):
                in_exec_sql = False
                sql_text = ' '.join(sql_buffer)
                # Analyze the SQL block
                extracted = _analyze_sql_block(sql_text, sql_start_line)
                tables.extend(extracted)

    return tables


def _analyze_sql_block(sql_text: str, line_number: int) -> List[Dict]:
    """Analyze a single EXEC SQL block for table references."""
    tables = []
    sql_upper = sql_text.upper()

    # Keywords that indicate table references
    table_keywords = [
        ('FROM', 'SELECT'),
        ('JOIN', 'SELECT'),
        ('INNER JOIN', 'SELECT'),
        ('LEFT JOIN', 'SELECT'),
        ('RIGHT JOIN', 'SELECT'),
        ('FULL JOIN', 'SELECT'),
        ('INTO', 'INSERT/SELECT'),
        ('UPDATE', 'UPDATE'),
        ('TABLE', 'DECLARE'),
        ('DELETE FROM', 'DELETE'),
        ('INTO', 'MERGE'),
    ]

    # Reserved SQL words to exclude
    reserved = {'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'FROM', 'WHERE', 'GROUP', 'ORDER', 'BY',
                'HAVING', 'AND', 'OR', 'NOT', 'IN', 'EXISTS', 'BETWEEN', 'LIKE', 'IS', 'NULL',
                'INNER', 'LEFT', 'RIGHT', 'FULL', 'OUTER', 'JOIN', 'ON', 'AS', 'TABLE', 'INTO',
                'VALUES', 'SET', 'KEY', 'PRIMARY', 'FOREIGN', 'REFERENCES', 'CONSTRAINT',
                'DCLGEN', 'OF', 'IN', 'A', 'THE', 'END', 'EXEC', 'SQL'}

    for keyword, operation in table_keywords:
        # Pattern to find table name after keyword
        pattern = rf'{keyword}\s+([A-Z0-9_\-]+)'
        matches = re.finditer(pattern, sql_upper, re.IGNORECASE)
        for match in matches:
            table_name = match.group(1)
            if table_name not in reserved and len(table_name) > 1:
                tables.append({
                    'table_name': table_name,
                    'operation': operation,
                    'line_number': line_number,
                    'context': sql_text[:200]
                })

    return tables


def extract_cics_calls(source: str) -> List[Dict]:
    """
    Extract CICS commands from source.

    Returns:
        List of dicts with command type, target, line_number, context
    """
    cics_calls = []
    lines = source.split('\n')

    for i, line in enumerate(lines):
        line_num = i + 1
        stripped = line.strip()

        # Skip comments
        if len(stripped) >= 7 and stripped[6] == '*':
            continue
        if stripped.startswith('*>'):
            continue

        # EXEC CICS LINK PROGRAM('PROGNAME')
        link_match = re.search(
            r'EXEC\s+CICS\s+LINK\s+PROGRAM\s*\(\s*[\'"]([A-Z0-9\-]+)[\'"]\s*\)',
            stripped,
            re.IGNORECASE
        )
        if link_match:
            cics_calls.append({
                'command': 'LINK',
                'target_program': link_match.group(1),
                'line_number': line_num,
                'context': stripped
            })
            continue

        # EXEC CICS XCTL PROGRAM('PROGNAME')
        xctl_match = re.search(
            r'EXEC\s+CICS\s+XCTL\s+PROGRAM\s*\(\s*[\'"]([A-Z0-9\-]+)[\'"]\s*\)',
            stripped,
            re.IGNORECASE
        )
        if xctl_match:
            cics_calls.append({
                'command': 'XCTL',
                'target_program': xctl_match.group(1),
                'line_number': line_num,
                'context': stripped
            })
            continue

        # EXEC CICS SEND MAP('MAPNAME')
        send_match = re.search(
            r'EXEC\s+CICS\s+SEND\s+MAP\s*\(\s*[\'"]([A-Z0-9\-]+)[\'"]\s*\)',
            stripped,
            re.IGNORECASE
        )
        if send_match:
            cics_calls.append({
                'command': 'SEND',
                'map_name': send_match.group(1),
                'line_number': line_num,
                'context': stripped
            })
            continue

        # EXEC CICS RECEIVE MAP('MAPNAME')
        receive_match = re.search(
            r'EXEC\s+CICS\s+RECEIVE\s+MAP\s*\(\s*[\'"]([A-Z0-9\-]+)[\'"]\s*\)',
            stripped,
            re.IGNORECASE
        )
        if receive_match:
            cics_calls.append({
                'command': 'RECEIVE',
                'map_name': receive_match.group(1),
                'line_number': line_num,
                'context': stripped
            })
            continue

        # Other CICS commands - generic catch
        if re.search(r'EXEC\s+CICS', stripped, re.IGNORECASE):
            cics_calls.append({
                'command': 'OTHER',
                'target_program': None,
                'line_number': line_num,
                'context': stripped
            })

    return cics_calls


def build_data_dependency_graph(
    programs: Dict[str, str],
    copybook_paths: List[str] = None
) -> Dict:
    """
    Build a data dependency graph showing file sharing between programs.

    Args:
        programs: Dict mapping program_name -> source code
        copybook_paths: Paths for copybook resolution

    Returns:
        Dictionary with file dependencies
    """
    from .extractor import extract_cobol_sections, extract_cobol_sections_with_copybooks

    program_files = {}
    program_operations = {}

    for prog_name, source in programs.items():
        if copybook_paths:
            sections = extract_cobol_sections_with_copybooks(source, copybook_paths)
        else:
            sections = extract_cobol_sections(source)

        # Extract from FILE SECTION
        file_defs = extract_file_definitions(sections.file_section)
        program_files[prog_name] = file_defs

        # Extract from PROCEDURE DIVISION
        ops = extract_file_operations(sections.procedure_division)
        program_operations[prog_name] = ops

    # Analyze sharing
    shared_files = analyze_file_sharing(program_files)

    return {
        'program_files': {k: [f.__dict__ for f in v] for k, v in program_files.items()},
        'program_operations': {k: [o.__dict__ for o in v] for k, v in program_operations.items()},
        'shared_files': shared_files,
        'file_usage_detail': program_files  # Keep original objects for detail
    }