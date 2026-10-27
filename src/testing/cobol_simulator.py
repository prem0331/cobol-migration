"""Simple COBOL subset interpreter for semantic equivalence testing."""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Callable
from enum import Enum


class StatementType(Enum):
    MOVE = "MOVE"
    COMPUTE = "COMPUTE"
    IF = "IF"
    ELSE = "ELSE"
    END_IF = "END-IF"
    PERFORM = "PERFORM"
    SET = "SET"
    ADD = "ADD"
    SUBTRACT = "SUBTRACT"
    MULTIPLY = "MULTIPLY"
    DIVIDE = "DIVIDE"
    DISPLAY = "DISPLAY"
    ACCEPT = "ACCEPT"
    STOP_RUN = "STOP RUN"
    GOBACK = "GOBACK"
    CALL = "CALL"
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    READ = "READ"
    WRITE = "WRITE"
    REWRITE = "REWRITE"
    DELETE = "DELETE"
    START = "START"
    UNKNOWN = "UNKNOWN"


@dataclass
class CobolVariable:
    """Represents a COBOL variable with PIC clause."""
    name: str
    pic: str
    value: Any = None
    condition_values: Dict[str, Any] = field(default_factory=dict)  # 88-levels
    redefines: Optional[str] = None
    occurs: int = 0
    level: int = 0


@dataclass
class ParsedStatement:
    """A parsed COBOL statement."""
    type: StatementType
    raw: str
    operands: List[str] = field(default_factory=list)
    target: str = ""
    condition: str = ""
    paragraph: str = ""


class CobolInterpreter:
    """
    Interprets a subset of COBOL PROCEDURE DIVISION statements.

    Supported statements:
    - MOVE (literal/variable TO variable)
    - COMPUTE (variable = arithmetic expression)
    - IF/ELSE/END-IF (with 88-level conditions)
    - PERFORM (paragraph, inline, or with VARYING/UNTIL)
    - SET (88-level TO TRUE/FALSE)
    - ADD, SUBTRACT, MULTIPLY, DIVIDE
    - DISPLAY, ACCEPT
    - STOP RUN, GOBACK
    - CALL (stub - records call for analysis)
    - File I/O: OPEN, CLOSE, READ, WRITE, REWRITE, DELETE, START (stubs)
    """

    def __init__(self, variables: Dict[str, CobolVariable] = None):
        self.variables = variables or {}
        self.paragraphs: Dict[str, List[ParsedStatement]] = {}
        self.current_paragraph = ""
        self.call_stack: List[str] = []
        self.performed_paragraphs: List[str] = []
        self.output_buffer: List[str] = []
        self.input_provider: Optional[Callable[[str], str]] = None
        self.file_handlers: Dict[str, Any] = {}  # Stub for file I/O
        self.call_log: List[Dict] = []

    def add_variable(self, var: CobolVariable):
        """Add a variable to the environment."""
        self.variables[var.name] = var

    def load_program(self, procedure_division: str):
        """Parse PROCEDURE DIVISION into paragraphs."""
        self.paragraphs = {}
        self.current_paragraph = ""
        lines = procedure_division.split('\n')

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith('*'):
                continue

            # Check for paragraph name (ends with . and no spaces before .)
            # But exclude known statements that end with .
            is_statement = stripped.upper() in ('STOP RUN.', 'GOBACK.', 'EXIT.', 'GO TO.', 'CONTINUE.')
            if not is_statement and re.match(r'^[A-Z][A-Z0-9-]*\s*\.$', stripped, re.IGNORECASE):
                self.current_paragraph = stripped[:-1].strip()
                self.paragraphs[self.current_paragraph] = []
                continue

            if self.current_paragraph:
                stmt = self._parse_statement(stripped)
                stmt.paragraph = self.current_paragraph
                self.paragraphs[self.current_paragraph].append(stmt)

    def _parse_statement(self, line: str) -> ParsedStatement:
        """Parse a single COBOL statement."""
        line_upper = line.upper()

        # Determine statement type
        for stmt_type in StatementType:
            if line_upper.startswith(stmt_type.value + ' ') or line_upper == stmt_type.value:
                break
        else:
            stmt_type = StatementType.UNKNOWN

        # Parse operands based on type
        operands = []
        target = ""
        condition = ""

        if stmt_type == StatementType.MOVE:
            # MOVE source TO target
            match = re.search(r'MOVE\s+(.+?)\s+TO\s+(.+?)(?:\s*\.)?$', line, re.IGNORECASE)
            if match:
                operands = [match.group(1).strip(), match.group(2).strip()]
                target = match.group(2).strip()

        elif stmt_type == StatementType.COMPUTE:
            # COMPUTE target = expression
            match = re.search(r'COMPUTE\s+(\S+)\s*=\s*(.+?)(?:\s*\.)?$', line, re.IGNORECASE)
            if match:
                target = match.group(1).strip()
                operands = [match.group(2).strip()]

        elif stmt_type == StatementType.IF:
            # IF condition
            match = re.search(r'IF\s+(.+?)(?:\s+THEN)?(?:\s*\.)?$', line, re.IGNORECASE)
            if match:
                condition = match.group(1).strip()

        elif stmt_type == StatementType.SET:
            # SET condition TO TRUE/FALSE
            match = re.search(r'SET\s+(\S+)\s+TO\s+(TRUE|FALSE)', line, re.IGNORECASE)
            if match:
                target = match.group(1).strip()
                operands = [match.group(2).strip()]

        elif stmt_type == StatementType.PERFORM:
            # PERFORM paragraph [VARYING...] [UNTIL...]
            match = re.search(r'PERFORM\s+(\S+)', line, re.IGNORECASE)
            if match:
                target = match.group(1).strip().rstrip('.')

        elif stmt_type == StatementType.CALL:
            # CALL "program" [USING ...] [RETURNING ...]
            match = re.search(r'CALL\s+("([^"]+)"|(\S+))', line, re.IGNORECASE)
            if match:
                target = match.group(2) or match.group(3)

        elif stmt_type in (StatementType.ADD, StatementType.SUBTRACT,
                          StatementType.MULTIPLY, StatementType.DIVIDE):
            # Arithmetic statements
            operands = line.split()[1:]

        return ParsedStatement(
            type=stmt_type,
            raw=line,
            operands=operands,
            target=target,
            condition=condition
        )

    def execute_paragraph(self, paragraph_name: str) -> Dict[str, Any]:
        """Execute a paragraph by name."""
        if paragraph_name not in self.paragraphs:
            return self._get_variable_values()

        self.call_stack.append(paragraph_name)
        try:
            for stmt in self.paragraphs[paragraph_name]:
                self._execute_statement(stmt)
        finally:
            self.call_stack.pop()

        return self._get_variable_values()

    def _execute_statement(self, stmt: ParsedStatement):
        """Execute a single parsed statement."""
        if stmt.type == StatementType.MOVE:
            self._execute_move(stmt)
        elif stmt.type == StatementType.COMPUTE:
            self._execute_compute(stmt)
        elif stmt.type == StatementType.IF:
            self._execute_if(stmt)
        elif stmt.type == StatementType.SET:
            self._execute_set(stmt)
        elif stmt.type == StatementType.PERFORM:
            self._execute_perform(stmt)
        elif stmt.type in (StatementType.ADD, StatementType.SUBTRACT,
                          StatementType.MULTIPLY, StatementType.DIVIDE):
            self._execute_arithmetic(stmt)
        elif stmt.type == StatementType.DISPLAY:
            self._execute_display(stmt)
        elif stmt.type == StatementType.ACCEPT:
            self._execute_accept(stmt)
        elif stmt.type == StatementType.CALL:
            self._execute_call(stmt)
        elif stmt.type in (StatementType.OPEN, StatementType.CLOSE,
                          StatementType.READ, StatementType.WRITE,
                          StatementType.REWRITE, StatementType.DELETE, StatementType.START):
            self._execute_file_io(stmt)
        elif stmt.type in (StatementType.STOP_RUN, StatementType.GOBACK):
            pass  # Just return

    def _execute_move(self, stmt: ParsedStatement):
        """Execute MOVE statement."""
        if len(stmt.operands) >= 2:
            source = stmt.operands[0]
            target = stmt.operands[1]

            # Resolve source value
            value = self._resolve_value(source)

            # Handle target (could be multiple: MOVE a TO b c d)
            targets = [target] if ' ' not in target else target.split()
            for t in targets:
                self._set_variable(t.strip(), value)

    def _execute_compute(self, stmt: ParsedStatement):
        """Execute COMPUTE statement."""
        if stmt.target and stmt.operands:
            expr = stmt.operands[0]
            # Substitute variables in expression
            expr = self._substitute_variables(expr)
            try:
                result = eval(expr, {"__builtins__": {}}, {})
                self._set_variable(stmt.target, result)
            except Exception as e:
                print(f"COMPUTE error: {e}")

    def _execute_if(self, stmt: ParsedStatement):
        """Execute IF statement (simplified)."""
        # This is a placeholder - full IF/ELSE/END-IF requires
        # parsing the full block structure
        condition_result = self._evaluate_condition(stmt.condition)
        # In a real implementation, we'd track IF/ELSE blocks
        pass

    def _execute_set(self, stmt: ParsedStatement):
        """Execute SET statement for 88-level conditions."""
        if stmt.target and stmt.operands:
            # Find the variable that has this condition name
            target_var = None
            for var in self.variables.values():
                if stmt.target in var.condition_values:
                    target_var = var
                    break
            if target_var and target_var.condition_values:
                cond_value = target_var.condition_values.get(stmt.target)
                if cond_value is not None and stmt.operands[0].upper() == 'TRUE':
                    self._set_variable(target_var.name, cond_value)
                # FALSE would need a default value

    def _execute_perform(self, stmt: ParsedStatement):
        """Execute PERFORM statement."""
        if stmt.target:
            self.execute_paragraph(stmt.target)

    def _execute_arithmetic(self, stmt: ParsedStatement):
        """Execute ADD/SUBTRACT/MULTIPLY/DIVIDE."""
        # Handle ADD var TO target
        # ADD value TO target [GIVING result]
        # For now, handle simple ADD X TO Y
        stmt_upper = stmt.raw.upper()
        if stmt_upper.startswith('ADD '):
            # ADD 1 TO WS-COUNTER
            match = re.search(r'ADD\s+(.+?)\s+TO\s+(\S+)(?:\s+GIVING\s+(\S+))?(?:\s*\.?)?$', stmt.raw, re.IGNORECASE)
            if match:
                source = match.group(1).strip()
                target = match.group(2).strip().rstrip('.')
                giving = match.group(3).strip().rstrip('.') if match.group(3) else None

                value = self._resolve_value(source)
                target_val = self.variables.get(target, CobolVariable(name=target, pic="", value=0)).value

                if giving:
                    self._set_variable(giving, target_val + value)
                else:
                    self._set_variable(target, target_val + value)

    def _execute_display(self, stmt: ParsedStatement):
        """Execute DISPLAY statement."""
        self.output_buffer.append(stmt.raw)

    def _execute_accept(self, stmt: ParsedStatement):
        """Execute ACCEPT statement."""
        if self.input_provider:
            # Would prompt for input
            pass

    def _execute_call(self, stmt: ParsedStatement):
        """Execute CALL statement - records for analysis."""
        self.call_log.append({
            "program": stmt.target,
            "paragraph": stmt.paragraph,
            "using": stmt.operands
        })

    def _execute_file_io(self, stmt: ParsedStatement):
        """Execute file I/O statements (stubs)."""
        # These would need actual file handlers
        pass

    def _resolve_value(self, source: str) -> Any:
        """Resolve a source value (literal or variable)."""
        source = source.strip()

        # Numeric literal
        if re.match(r'^[-+]?\d+(\.\d+)?$', source):
            return float(source) if '.' in source else int(source)

        # String literal
        if source.startswith('"') and source.endswith('"'):
            return source[1:-1]
        if source.startswith("'") and source.endswith("'"):
            return source[1:-1]

        # Variable reference
        return self.variables.get(source, CobolVariable(name=source, pic="", value=0)).value

    def _substitute_variables(self, expr: str) -> str:
        """Substitute variable names with values in expression."""
        for name, var in self.variables.items():
            if var.value is not None:
                # Use word boundaries to avoid partial matches
                expr = re.sub(rf'\b{name}\b', str(var.value), expr)
        return expr

    def _evaluate_condition(self, condition: str) -> bool:
        """Evaluate a COBOL condition (88-level, relational, etc.)."""
        condition = condition.strip().upper()

        # 88-level condition
        for var in self.variables.values():
            if condition in var.condition_values:
                return var.value == var.condition_values[condition]

        # Relational condition (simplified)
        # Would need full parser for complex conditions
        return False

    def _set_variable(self, name: str, value: Any):
        """Set a variable value, handling PIC formatting."""
        if name in self.variables:
            var = self.variables[name]
            # Format based on PIC
            if 'V' in var.pic.upper():
                var.value = float(value)
            elif '9' in var.pic.upper():
                var.value = int(value)
            else:
                var.value = value
        else:
            # Create implicit variable
            self.variables[name] = CobolVariable(name=name, pic="", value=value)

    def _get_variable_values(self) -> Dict[str, Any]:
        """Get all variable values."""
        return {name: var.value for name, var in self.variables.items()}

    def run(self, start_paragraph: str = None) -> Dict[str, Any]:
        """Run the program starting from a paragraph."""
        if start_paragraph is None:
            # Find MAIN paragraph
            for name in self.paragraphs:
                if 'MAIN' in name.upper():
                    start_paragraph = name
                    break
            if start_paragraph is None and self.paragraphs:
                start_paragraph = list(self.paragraphs.keys())[0]

        if start_paragraph:
            return self.execute_paragraph(start_paragraph)
        return self._get_variable_values()


def create_interpreter_from_parsed(parsed) -> CobolInterpreter:
    """Create interpreter from ParsedCobol object."""
    interpreter = CobolInterpreter()

    # Add variables from WORKING-STORAGE
    for field in parsed.data_fields:
        var = CobolVariable(
            name=field.name,
            pic=field.picture or "",
            value=field.value,
            level=field.level,
            occurs=field.occurs or 0,
            redefines=field.redefines
        )
        # Add 88-level conditions
        if hasattr(field, 'condition_values') and field.condition_values:
            var.condition_values = field.condition_values
        interpreter.add_variable(var)

    # Load PROCEDURE DIVISION
    interpreter.load_program(parsed.procedure_division)

    return interpreter


if __name__ == "__main__":
    # Simple test
    from ..cobol.parser import parse_cobol_file

    parsed = parse_cobol_file("examples/sample.cbl")
    interpreter = create_interpreter_from_parsed(parsed)
    result = interpreter.run()
    print("Variables after execution:", result)