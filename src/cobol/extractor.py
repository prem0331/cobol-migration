"""Extract key sections from COBOL source code using regex-based parsing."""

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CobolSections:
    """Extracted sections from a COBOL program."""
    program_id: Optional[str] = None
    working_storage: str = ""
    procedure_division: str = ""
    file_section: str = ""
    linkage_section: str = ""
    raw_source: str = ""

    def has_content(self) -> bool:
        """Check if any meaningful content was extracted."""
        return bool(self.working_storage or self.procedure_division)


def extract_cobol_sections(source: str) -> CobolSections:
    """
    Extract major COBOL divisions/sections from source code.

    Uses regex to find:
    - PROGRAM-ID
    - WORKING-STORAGE SECTION
    - PROCEDURE DIVISION
    - FILE SECTION
    - LINKAGE SECTION
    """
    sections = CobolSections(raw_source=source)

    # Normalize line endings and remove extra whitespace
    normalized = re.sub(r'\r\n', '\n', source)

    # Extract PROGRAM-ID
    program_id_match = re.search(
        r'PROGRAM-ID\s*\.\s*([A-Z0-9-]+)',
        normalized,
        re.IGNORECASE
    )
    if program_id_match:
        sections.program_id = program_id_match.group(1).strip()

    # Find division/section boundaries
    # COBOL divisions in order: IDENTIFICATION, ENVIRONMENT, DATA, PROCEDURE
    div_pattern = r'(IDENTIFICATION\s+DIVISION|ENVIRONMENT\s+DIVISION|DATA\s+DIVISION|PROCEDURE\s+DIVISION)'
    div_matches = list(re.finditer(div_pattern, normalized, re.IGNORECASE))

    # Find section boundaries within DATA DIVISION
    section_pattern = r'(WORKING-STORAGE\s+SECTION|FILE\s+SECTION|LINKAGE\s+SECTION|LOCAL-STORAGE\s+SECTION)'
    section_matches = list(re.finditer(section_pattern, normalized, re.IGNORECASE))

    # Extract WORKING-STORAGE SECTION
    ws_start = None
    ws_end = None
    for i, match in enumerate(section_matches):
        if 'WORKING-STORAGE' in match.group(1).upper():
            ws_start = match.end()
            # Find next section or PROCEDURE DIVISION
            if i + 1 < len(section_matches):
                ws_end = section_matches[i + 1].start()
            else:
                # Look for PROCEDURE DIVISION
                for div_match in div_matches:
                    if 'PROCEDURE' in div_match.group(1).upper() and div_match.start() > ws_start:
                        ws_end = div_match.start()
                        break
            break

    if ws_start and ws_end:
        sections.working_storage = normalized[ws_start:ws_end].strip()
    elif ws_start:
        sections.working_storage = normalized[ws_start:].strip()

    # Extract FILE SECTION
    fs_start = None
    fs_end = None
    for i, match in enumerate(section_matches):
        if 'FILE SECTION' in match.group(1).upper():
            fs_start = match.end()
            if i + 1 < len(section_matches):
                fs_end = section_matches[i + 1].start()
            else:
                for div_match in div_matches:
                    if 'PROCEDURE' in div_match.group(1).upper() and div_match.start() > fs_start:
                        fs_end = div_match.start()
                        break
            break

    if fs_start and fs_end:
        sections.file_section = normalized[fs_start:fs_end].strip()
    elif fs_start:
        sections.file_section = normalized[fs_start:].strip()

    # Extract LINKAGE SECTION
    ls_start = None
    ls_end = None
    for i, match in enumerate(section_matches):
        if 'LINKAGE' in match.group(1).upper():
            ls_start = match.end()
            if i + 1 < len(section_matches):
                ls_end = section_matches[i + 1].start()
            else:
                for div_match in div_matches:
                    if 'PROCEDURE' in div_match.group(1).upper() and div_match.start() > ls_start:
                        ls_end = div_match.start()
                        break
            break

    if ls_start and ls_end:
        sections.linkage_section = normalized[ls_start:ls_end].strip()
    elif ls_start:
        sections.linkage_section = normalized[ls_start:].strip()

    # Extract PROCEDURE DIVISION
    proc_start = None
    for div_match in div_matches:
        if 'PROCEDURE' in div_match.group(1).upper():
            proc_start = div_match.end()
            break

    if proc_start:
        sections.procedure_division = normalized[proc_start:].strip()

    return sections


def clean_cobol_source(source: str) -> str:
    """
    Clean COBOL source by removing comments and normalizing.

    COBOL comments:
    - * in column 7 (full line comment)
    - *> inline comment (after column 7)
    - Floating comment lines starting with *>
    """
    lines = source.split('\n')
    cleaned_lines = []

    for line in lines:
        # Skip full-line comments (column 7 is *)
        if len(line) >= 7 and line[6] == '*':
            continue

        # Remove inline comments (*>)
        inline_comment_pos = line.find('*>')
        if inline_comment_pos != -1:
            line = line[:inline_comment_pos]

        cleaned_lines.append(line.rstrip())

    return '\n'.join(cleaned_lines)