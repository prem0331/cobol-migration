"""Parse COBOL data definitions and procedure logic into structured data."""

import re
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class PicType(Enum):
    """COBOL PICTURE clause types."""
    ALPHANUMERIC = "X"
    NUMERIC = "9"
    ALPHABETIC = "A"
    EDITED_NUMERIC = "EDITED"
    COMPUTATIONAL = "COMP"
    COMP_3 = "COMP-3"
    POINTER = "POINTER"


@dataclass
class DataField:
    """Represents a COBOL data field definition."""
    name: str
    level: int
    picture: Optional[str] = None
    usage: Optional[str] = None
    value: Optional[str] = None
    occurs: Optional[int] = None
    redefines: Optional[str] = None
    parent: Optional[str] = None
    children: list = field(default_factory=list)
    condition_names: list = field(default_factory=list)  # 88-level items

    @property
    def is_group(self) -> bool:
        return self.picture is None and len(self.children) > 0

    @property
    def is_elementary(self) -> bool:
        return self.picture is not None

    def python_type(self) -> str:
        """Map COBOL picture to Python type."""
        if not self.picture:
            return "Any"

        pic = self.picture.upper()

        # Handle computational types
        if self.usage and 'COMP' in self.usage.upper():
            if 'COMP-3' in self.usage.upper() or 'PACKED' in self.usage.upper():
                return "Decimal"
            return "int"

        # Count numeric digits
        if '9' in pic:
            if 'V' in pic or '.' in pic:
                return "Decimal"
            return "int"

        if 'X' in pic or 'A' in pic:
            return "str"

        return "str"


@dataclass
class BusinessRule:
    """Represents a business rule extracted from PROCEDURE DIVISION."""
    name: str
    rule_type: str  # "validation", "calculation", "lookup", "conditional", "io"
    description: str
    source_paragraph: str
    conditions: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    variables_used: list = field(default_factory=list)


@dataclass
class IOOperation:
    """Represents an I/O operation in COBOL."""
    operation: str  # "READ", "WRITE", "DISPLAY", "ACCEPT", "OPEN", "CLOSE"
    target: str
    paragraph: str
    details: str = ""


@dataclass
class ParsedCobol:
    """Complete parsed representation of a COBOL program."""
    program_name: str
    data_fields: list = field(default_factory=list)
    business_logic: list = field(default_factory=list)
    io_operations: list = field(default_factory=list)
    paragraphs: list = field(default_factory=list)
    condition_names: dict = field(default_factory=dict)  # 88-level mappings


def parse_cobol_file(sections: 'CobolSections') -> ParsedCobol:
    """
    Parse extracted COBOL sections into structured data.

    This is a regex-based parser for basic COBOL constructs.
    """
    result = ParsedCobol(program_name=sections.program_id or "UNKNOWN")

    # Parse WORKING-STORAGE SECTION
    if sections.working_storage:
        result.data_fields = parse_working_storage(sections.working_storage)
        result.condition_names = extract_condition_names(result.data_fields)

    # Parse PROCEDURE DIVISION
    if sections.procedure_division:
        result.paragraphs = extract_paragraphs(sections.procedure_division)
        result.business_logic = extract_business_rules(
            sections.procedure_division,
            result.paragraphs,
            result.data_fields
        )
        result.io_operations = extract_io_operations(
            sections.procedure_division,
            result.paragraphs
        )

    return result


def parse_working_storage(source: str) -> list:
    """Parse WORKING-STORAGE SECTION into DataField objects."""
    fields = []
    lines = source.split('\n')

    current_parent = None
    parent_stack = []  # Stack of (level, field) for nested structures

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Skip section headers
        if line.upper().endswith('SECTION') or line.upper().endswith('DIVISION'):
            continue

        # Parse level number and field name
        # Format: [level] [name] [PIC...] [VALUE...] [OCCURS...] [REDEFINES...]
        # COBOL lines end with period, so strip it from name
        match = re.match(r'^(\d{1,2})\s+([A-Z0-9-]+)\.?(?:\s+(.*))?$', line, re.IGNORECASE)
        if not match:
            continue

        level = int(match.group(1))
        name = match.group(2).strip().rstrip('.')
        remainder = match.group(3) or ""

        # Handle 88-level (condition names)
        if level == 88:
            # Find parent field to attach condition
            for field in reversed(fields):
                if field.level < 88:
                    field.condition_names.append({
                        'name': name,
                        'value': extract_value(remainder)
                    })
                    break
            continue

        # Handle FILLER
        if name.upper() == 'FILLER':
            name = f"FILLER_{len([f for f in fields if f.name.startswith('FILLER')])}"

        # Extract clauses
        picture = extract_picture(remainder)
        usage = extract_usage(remainder)
        value = extract_value(remainder)
        occurs = extract_occurs(remainder)
        redefines = extract_redefines(remainder)

        field = DataField(
            name=name,
            level=level,
            picture=picture,
            usage=usage,
            value=value,
            occurs=occurs,
            redefines=redefines
        )

        # Manage parent-child hierarchy
        if level == 1:
            current_parent = field
            parent_stack = [(level, field)]
        else:
            # Find parent (last field with lower level)
            while parent_stack and parent_stack[-1][0] >= level:
                parent_stack.pop()

            if parent_stack:
                parent = parent_stack[-1][1]
                field.parent = parent.name
                parent.children.append(field)

            parent_stack.append((level, field))

        fields.append(field)

    return fields


def extract_picture(text: str) -> Optional[str]:
    """Extract PICTURE clause."""
    match = re.search(r'PIC(?:TURE)?\s+([A-Z0-9()V.,+-]+)', text, re.IGNORECASE)
    if match:
        return match.group(1).rstrip('.')
    return None


def extract_usage(text: str) -> Optional[str]:
    """Extract USAGE clause."""
    match = re.search(r'USAGE\s+(?:IS\s+)?(COMP(?:-3)?|COMPUTATIONAL(?:-3)?|PACKED-DECIMAL|BINARY|POINTER|DISPLAY)', text, re.IGNORECASE)
    return match.group(1) if match else None


def extract_value(text: str) -> Optional[str]:
    """Extract VALUE clause."""
    # Handle quoted strings and unquoted values
    match = re.search(r'VALUE\s+(?:IS\s+)?((?:\'[^\']*\'|"[^"]*"|\S+))', text, re.IGNORECASE)
    if match:
        val = match.group(1).strip()
        # Remove trailing period if present
        val = val.rstrip('.')
        return val
    return None


def extract_occurs(text: str) -> Optional[int]:
    """Extract OCCURS clause."""
    match = re.search(r'OCCURS\s+(\d+)', text, re.IGNORECASE)
    return int(match.group(1)) if match else None


def extract_redefines(text: str) -> Optional[str]:
    """Extract REDEFINES clause."""
    match = re.search(r'REDEFINES\s+([A-Z0-9-]+)', text, re.IGNORECASE)
    return match.group(1) if match else None


def extract_condition_names(fields: list) -> dict:
    """Extract 88-level condition names mapping."""
    conditions = {}
    for field in fields:
        for cond in field.condition_names:
            conditions[cond['name']] = {
                'field': field.name,
                'value': cond['value']
            }
    return conditions


def extract_paragraphs(source: str) -> list:
    """Extract paragraph names from PROCEDURE DIVISION."""
    paragraphs = []

    # Paragraph names: start at column 8 (after 7 chars), end with .
    # Format: PARAGRAPH-NAME.
    lines = source.split('\n')

    for line in lines:
        # Paragraph definition (starts at margin, ends with period, no verb)
        match = re.match(r'^([A-Z][A-Z0-9-]*)\s*\.$', line.strip(), re.IGNORECASE)
        if match:
            name = match.group(1)
            # Filter out known COBOL verbs
            verbs = {'IF', 'ELSE', 'END-IF', 'PERFORM', 'MOVE', 'COMPUTE', 'ADD', 'SUBTRACT',
                     'MULTIPLY', 'DIVIDE', 'DISPLAY', 'ACCEPT', 'READ', 'WRITE', 'OPEN',
                     'CLOSE', 'GO', 'STOP', 'EXIT', 'CONTINUE', 'CALL', 'RETURN'}
            if name.upper() not in verbs:
                paragraphs.append(name)

    return paragraphs


def extract_business_rules(proc_source: str, paragraphs: list, data_fields: list) -> list:
    """Extract business rules from PROCEDURE DIVISION."""
    rules = []
    field_names = [f.name for f in data_fields]

    # Split into paragraphs for analysis
    para_blocks = split_into_paragraphs(proc_source)

    for para_name, para_content in para_blocks.items():
        # Determine rule type based on content
        rule_type = classify_rule(para_content)

        # Extract conditions (IF statements)
        conditions = extract_conditions(para_content)

        # Extract actions (MOVE, COMPUTE, PERFORM, etc.)
        actions = extract_actions(para_content)

        # Extract variables used
        vars_used = extract_variables_used(para_content, field_names)

        if rule_type != "unknown" or conditions or actions:
            rules.append(BusinessRule(
                name=para_name,
                rule_type=rule_type,
                description=para_content[:200],
                source_paragraph=para_name,
                conditions=conditions,
                actions=actions,
                variables_used=vars_used
            ))

    return rules


def split_into_paragraphs(source: str) -> dict:
    """Split PROCEDURE DIVISION into paragraph blocks."""
    paragraphs = {}
    lines = source.split('\n')
    current_para = None
    current_content = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Check if this line starts a new paragraph
        match = re.match(r'^([A-Z][A-Z0-9-]*)\s*\.$', stripped, re.IGNORECASE)
        if match:
            # Save previous paragraph
            if current_para:
                paragraphs[current_para] = '\n'.join(current_content)
            current_para = match.group(1)
            current_content = []
        else:
            current_content.append(stripped)

    # Save last paragraph
    if current_para:
        paragraphs[current_para] = '\n'.join(current_content)

    return paragraphs


def classify_rule(content: str) -> str:
    """Classify the type of business rule based on content."""
    content_upper = content.upper()

    if any(kw in content_upper for kw in ['READ', 'WRITE', 'REWRITE', 'DELETE', 'START']):
        return "io"
    elif any(kw in content_upper for kw in ['DISPLAY', 'ACCEPT']):
        return "io"
    elif any(kw in content_upper for kw in ['COMPUTE', 'ADD', 'SUBTRACT', 'MULTIPLY', 'DIVIDE']):
        return "calculation"
    elif any(kw in content_upper for kw in ['IF', 'EVALUATE', 'WHEN']):
        return "conditional"
    elif any(kw in content_upper for kw in ['PERFORM', 'CALL']):
        return "workflow"
    elif any(kw in content_upper for kw in ['MOVE', 'SET', 'INITIALIZE']):
        return "data_transfer"

    return "unknown"


def extract_conditions(content: str) -> list:
    """Extract IF conditions from content."""
    conditions = []

    # Simple IF pattern matching
    if_matches = re.finditer(
        r'IF\s+(.+?)\s+(?:THEN\s+)?(.*?)(?:ELSE\s+(.*?))?(?:END-IF|\.)',
        content,
        re.IGNORECASE | re.DOTALL
    )

    for match in if_matches:
        condition = match.group(1).strip()
        then_part = match.group(2).strip() if match.group(2) else ""
        else_part = match.group(3).strip() if match.group(3) else ""
        conditions.append({
            "condition": condition,
            "then": then_part,
            "else": else_part
        })

    return conditions


def extract_actions(content: str) -> list:
    """Extract action statements from content."""
    actions = []

    # MOVE statements
    for match in re.finditer(r'MOVE\s+(.+?)\s+TO\s+(.+?)(?:\s|\.|$)', content, re.IGNORECASE):
        actions.append({
            "type": "MOVE",
            "from": match.group(1).strip(),
            "to": match.group(2).strip()
        })

    # COMPUTE statements
    for match in re.finditer(r'COMPUTE\s+(.+?)\s*=\s*(.+?)(?:\s|\.|$)', content, re.IGNORECASE):
        actions.append({
            "type": "COMPUTE",
            "target": match.group(1).strip(),
            "expression": match.group(2).strip()
        })

    # PERFORM statements
    for match in re.finditer(r'PERFORM\s+([A-Z0-9-]+)', content, re.IGNORECASE):
        actions.append({
            "type": "PERFORM",
            "paragraph": match.group(1).strip()
        })

    return actions


def extract_variables_used(content: str, known_fields: list) -> list:
    """Extract variable names used in the content."""
    used = set()
    content_upper = content.upper()

    for field in known_fields:
        # Match whole word
        pattern = r'\b' + re.escape(field.upper()) + r'\b'
        if re.search(pattern, content_upper):
            used.add(field)

    return list(used)


def extract_io_operations(proc_source: str, paragraphs: list) -> list:
    """Extract I/O operations from PROCEDURE DIVISION."""
    operations = []

    para_blocks = split_into_paragraphs(proc_source)

    for para_name, para_content in para_blocks.items():
        # READ operations
        for match in re.finditer(r'READ\s+([A-Z0-9-]+)', para_content, re.IGNORECASE):
            operations.append(IOOperation(
                operation="READ",
                target=match.group(1),
                paragraph=para_name,
                details=para_content[:100]
            ))

        # WRITE operations
        for match in re.finditer(r'WRITE\s+([A-Z0-9-]+)', para_content, re.IGNORECASE):
            operations.append(IOOperation(
                operation="WRITE",
                target=match.group(1),
                paragraph=para_name,
                details=para_content[:100]
            ))

        # DISPLAY operations
        for match in re.finditer(r'DISPLAY\s+(.+?)(?:\s|\.|$)', para_content, re.IGNORECASE):
            operations.append(IOOperation(
                operation="DISPLAY",
                target=match.group(1).strip(),
                paragraph=para_name,
                details=para_content[:100]
            ))

        # ACCEPT operations
        for match in re.finditer(r'ACCEPT\s+([A-Z0-9-]+)', para_content, re.IGNORECASE):
            operations.append(IOOperation(
                operation="ACCEPT",
                target=match.group(1),
                paragraph=para_name,
                details=para_content[:100]
            ))

        # OPEN/CLOSE
        for match in re.finditer(r'(OPEN|CLOSE)\s+(.+?)(?:\s|\.|$)', para_content, re.IGNORECASE):
            operations.append(IOOperation(
                operation=match.group(1).upper(),
                target=match.group(2).strip(),
                paragraph=para_name,
                details=para_content[:100]
            ))

    return operations