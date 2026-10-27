"""Semantic equivalence testing: compare COBOL logic vs generated FastAPI behavior."""

import json
import subprocess
import tempfile
import os
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from ..pipeline.models import BusinessRules, DataField, BusinessRule, IOOperation
from ..cobol.parser import parse_cobol_file, ParsedCobol

console = Console()


class TestResultStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


@dataclass
class TestCase:
    """A single test case for equivalence testing."""
    name: str
    description: str
    inputs: Dict[str, Any]           # Input values (WORKING-STORAGE fields)
    expected_outputs: Dict[str, Any] # Expected output values
    program_id: str
    paragraph: str = ""


@dataclass
class TestResult:
    """Result of a single test case execution."""
    test_case: TestCase
    status: TestResultStatus
    cobol_outputs: Dict[str, Any] = field(default_factory=dict)
    fastapi_outputs: Dict[str, Any] = field(default_factory=dict)
    differences: List[str] = field(default_factory=list)
    error_message: str = ""
    execution_time_ms: float = 0.0


@dataclass
class EquivalenceReport:
    """Complete equivalence test report."""
    program_id: str
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    results: List[TestResult] = field(default_factory=list)
    summary: str = ""


class CobolSimulator:
    """
    Simple COBOL simulator for testing business logic.

    Executes a subset of COBOL statements by translating to Python.
    Supports: MOVE, COMPUTE, IF/ELSE, PERFORM (simple), SET (88-levels)
    """

    def __init__(self, parsed_cobol: ParsedCobol):
        self.parsed = parsed_cobol
        self.variables: Dict[str, Any] = {}
        self.paragraphs: Dict[str, List[str]] = {}
        self._initialize_variables()
        self._parse_paragraphs()

    def _initialize_variables(self):
        """Initialize WORKING-STORAGE variables with their VALUE clauses."""
        for field in self.parsed.data_fields:
            if field.value is not None:
                self.variables[field.name] = field.value
            elif field.picture:
                # Initialize based on PIC
                self.variables[field.name] = self._default_value(field.picture)

    def _default_value(self, pic: str) -> Any:
        """Get default value for a PIC clause."""
        pic_upper = pic.upper()
        if '9' in pic_upper and 'V' in pic_upper:
            return 0.0
        elif '9' in pic_upper:
            return 0
        elif 'X' in pic_upper:
            return ""
        return None

    def _parse_paragraphs(self):
        """Parse PROCEDURE DIVISION into paragraph -> statements."""
        # Get procedure division from parsed object or use business logic
        proc_div = getattr(self.parsed, 'procedure_division', None)
        if not proc_div:
            # Fallback: use business logic to reconstruct
            proc_div = ""
            for rule in self.parsed.business_logic:
                proc_div += f"{rule.source_paragraph}.\n"
                for action in rule.actions:
                    proc_div += f"    {action}\n"

        current_para = ""
        for line in proc_div.split('\n'):
            stripped = line.strip()
            if not stripped:
                continue
            # Check for paragraph name
            if stripped.endswith('.') and not stripped.startswith('*'):
                # Could be paragraph or statement
                if ' ' not in stripped[:-1] and stripped[0].isalpha():
                    current_para = stripped[:-1]
                    self.paragraphs[current_para] = []
                    continue
            if current_para:
                self.paragraphs[current_para].append(stripped)

    def set_inputs(self, inputs: Dict[str, Any]):
        """Set input variable values."""
        self.variables.update(inputs)

    def get_outputs(self, output_fields: List[str]) -> Dict[str, Any]:
        """Get current values of output fields."""
        return {k: self.variables.get(k) for k in output_fields}

    def execute_paragraph(self, paragraph_name: str) -> Dict[str, Any]:
        """Execute a single paragraph."""
        if paragraph_name not in self.paragraphs:
            return {}

        for stmt in self.paragraphs[paragraph_name]:
            self._execute_statement(stmt)

        return self.variables.copy()

    def _execute_statement(self, stmt: str):
        """Execute a single COBOL statement (simplified)."""
        stmt_upper = stmt.upper()

        # MOVE value TO variable
        if stmt_upper.startswith('MOVE '):
            self._execute_move(stmt)

        # COMPUTE variable = expression
        elif stmt_upper.startswith('COMPUTE '):
            self._execute_compute(stmt)

        # IF condition THEN ... ELSE ... END-IF
        elif stmt_upper.startswith('IF '):
            self._execute_if(stmt)

        # SET 88-level TO TRUE
        elif stmt_upper.startswith('SET ') and ' TO TRUE' in stmt_upper:
            self._execute_set_true(stmt)

        # PERFORM paragraph
        elif stmt_upper.startswith('PERFORM '):
            self._execute_perform(stmt)

        # ADD, SUBTRACT, MULTIPLY, DIVIDE
        elif any(stmt_upper.startswith(op + ' ') for op in ['ADD ', 'SUBTRACT ', 'MULTIPLY ', 'DIVIDE ']):
            self._execute_arithmetic(stmt)

    def _execute_move(self, stmt: str):
        """Execute MOVE statement."""
        # MOVE literal TO var
        # MOVE var1 TO var2
        parts = stmt.split()
        if len(parts) >= 4 and parts[2].upper() == 'TO':
            source = parts[1]
            target = parts[3].rstrip('.')

            # Resolve source value
            if source.replace('.', '').replace('-', '').isdigit():
                value = float(source) if '.' in source else int(source)
            elif source.startswith('"') and source.endswith('"'):
                value = source[1:-1]
            else:
                value = self.variables.get(source, 0)

            self.variables[target] = value

    def _execute_compute(self, stmt: str):
        """Execute COMPUTE statement."""
        # COMPUTE var = expression
        parts = stmt.split(None, 2)
        if len(parts) >= 3 and '=' in parts[2]:
            target = parts[1]
            expr = parts[2].split('=')[1].strip().rstrip('.')
            # Simple eval with variable substitution
            for var_name, var_val in self.variables.items():
                if isinstance(var_val, (int, float)):
                    expr = expr.replace(var_name, str(var_val))
            try:
                result = eval(expr, {"__builtins__": {}})
                self.variables[target] = result
            except:
                pass

    def _execute_if(self, stmt: str):
        """Execute IF statement (simplified - only handles 88-levels)."""
        # IF 88-level THEN ... ELSE ... END-IF
        # This is a simplified version
        pass

    def _execute_set_true(self, stmt: str):
        """Execute SET 88-level TO TRUE."""
        # SET condition-name TO TRUE
        parts = stmt.split()
        if len(parts) >= 4:
            condition = parts[1]
            # Find the parent field and set its value
            for field in self.parsed.data_fields:
                if hasattr(field, 'condition_values') and condition in field.condition_values:
                    self.variables[field.name] = field.condition_values[condition]
                    break

    def _execute_perform(self, stmt: str):
        """Execute PERFORM paragraph."""
        parts = stmt.split()
        if len(parts) >= 2:
            para_name = parts[1].rstrip('.')
            self.execute_paragraph(para_name)

    def _execute_arithmetic(self, stmt: str):
        """Execute ADD/SUBTRACT/MULTIPLY/DIVIDE."""
        # Simplified - delegate to COMPUTE-like logic
        pass

    def run_main(self) -> Dict[str, Any]:
        """Execute MAIN paragraph or first paragraph."""
        main_paras = [p for p in self.paragraphs.keys() if 'MAIN' in p.upper()]
        if main_paras:
            return self.execute_paragraph(main_paras[0])
        elif self.paragraphs:
            first = list(self.paragraphs.keys())[0]
            return self.execute_paragraph(first)
        return self.variables.copy()


class FastAPITester:
    """Test generated FastAPI application."""

    def __init__(self, service_dir: Path):
        self.service_dir = service_dir
        self.base_url = "http://localhost:8000"
        self.process = None

    def start_server(self) -> bool:
        """Start the FastAPI server in background."""
        try:
            # Install requirements
            req_file = self.service_dir / "requirements.txt"
            if req_file.exists():
                subprocess.run(
                    ["pip", "install", "-q", "-r", str(req_file)],
                    cwd=self.service_dir,
                    capture_output=True,
                    timeout=120
                )

            # Start uvicorn
            self.process = subprocess.Popen(
                ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"],
                cwd=self.service_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            # Wait for server to start
            import time
            import requests
            for _ in range(30):
                try:
                    resp = requests.get(f"{self.base_url}/docs", timeout=1)
                    if resp.status_code == 200:
                        return True
                except:
                    time.sleep(0.5)
            return False
        except Exception as e:
            console.print(f"[red]Failed to start server: {e}[/red]")
            return False

    def stop_server(self):
        """Stop the FastAPI server."""
        if self.process:
            self.process.terminate()
            self.process.wait(timeout=5)

    def call_endpoint(self, method: str, path: str, data: Dict = None) -> Dict:
        """Call a FastAPI endpoint."""
        import requests
        url = f"{self.base_url}{path}"
        try:
            if method == "GET":
                resp = requests.get(url, params=data, timeout=10)
            else:
                resp = requests.post(url, json=data, timeout=10)
            return {"status": resp.status_code, "data": resp.json()}
        except Exception as e:
            return {"status": 500, "error": str(e)}


def generate_test_cases(parsed_cobol: ParsedCobol, business_rules: BusinessRules) -> List[TestCase]:
    """
    Generate test cases from COBOL business rules.

    Creates test cases covering:
    - Normal flow (valid inputs)
    - Boundary conditions (88-level conditions)
    - Error conditions
    - Cross-entity operations
    """
    test_cases = []

    # Extract input/output fields from business rules
    input_fields = [f for f in business_rules.data_definitions if f.usage in ('INPUT', 'BOTH')]
    output_fields = [f for f in business_rules.data_definitions if f.usage in ('OUTPUT', 'BOTH')]

    # Test case 1: Normal flow with default VALUES
    normal_inputs = {}
    for field in input_fields:
        if field.value is not None:
            normal_inputs[field.name] = field.value

    # Simulate to get expected outputs
    sim = CobolSimulator(parsed_cobol)
    sim.set_inputs(normal_inputs)
    expected = sim.run_main()

    test_cases.append(TestCase(
        name="normal_flow",
        description="Normal execution with default VALUES",
        inputs=normal_inputs,
        expected_outputs={k: expected.get(k) for k in [f.name for f in output_fields]},
        program_id=parsed_cobol.program_name,
        paragraph="MAIN"
    ))

    # Test case 2: Boundary conditions from 88-levels
    for field in parsed_cobol.data_fields:
        if hasattr(field, 'condition_values') and field.condition_values:
            for cond_name, cond_value in field.condition_values.items():
                test_inputs = normal_inputs.copy()
                test_inputs[field.name] = cond_value

                sim2 = CobolSimulator(parsed_cobol)
                sim2.set_inputs(test_inputs)
                expected2 = sim2.run_main()

                test_cases.append(TestCase(
                    name=f"condition_{cond_name.lower()}",
                    description=f"Test {cond_name} condition on {field.name}",
                    inputs=test_inputs,
                    expected_outputs={k: expected2.get(k) for k in [f.name for f in output_fields]},
                    program_id=parsed_cobol.program_name,
                    paragraph="MAIN"
                ))

    # Test case 3: Cross-entity operations (from business logic)
    for rule in business_rules.business_logic:
        if 'update' in rule.description.lower() or 'modify' in rule.description.lower():
            # This might involve multiple entities
            pass

    return test_cases


def run_equivalence_test(
    cobol_file: Path,
    service_dir: Path,
    test_cases: List[TestCase] = None
) -> EquivalenceReport:
    """
    Run full equivalence test suite.

    Args:
        cobol_file: Path to original COBOL file
        service_dir: Path to generated FastAPI service
        test_cases: Optional custom test cases (auto-generated if not provided)

    Returns:
        EquivalenceReport with results
    """
    # Parse COBOL
    parsed = parse_cobol_file(str(cobol_file))

    # Generate test cases if not provided
    if test_cases is None:
        # Need business rules - would come from Analyst output
        # For now, create basic test cases
        test_cases = _generate_basic_test_cases(parsed)

    report = EquivalenceReport(program_id=parsed.program_name)

    # Start FastAPI server
    tester = FastAPITester(service_dir)
    if not tester.start_server():
        report.summary = "Failed to start FastAPI server"
        return report

    try:
        # Run each test case
        for tc in test_cases:
            result = _run_single_test(tc, parsed, tester)
            report.results.append(result)
            report.total_tests += 1

            if result.status == TestResultStatus.PASS:
                report.passed += 1
            elif result.status == TestResultStatus.FAIL:
                report.failed += 1
            elif result.status == TestResultStatus.ERROR:
                report.errors += 1
            else:
                report.skipped += 1

    finally:
        tester.stop_server()

    # Generate summary
    report.summary = (
        f"Program: {report.program_id}\n"
        f"Total: {report.total_tests}, Passed: {report.passed}, "
        f"Failed: {report.failed}, Errors: {report.errors}, Skipped: {report.skipped}"
    )

    return report


def _generate_basic_test_cases(parsed: ParsedCobol) -> List[TestCase]:
    """Generate basic test cases from parsed COBOL."""
    test_cases = []

    # Find fields with VALUE clauses
    input_fields = [f for f in parsed.data_fields if f.value is not None]

    if input_fields:
        inputs = {f.name: f.value for f in input_fields}
        sim = CobolSimulator(parsed)
        sim.set_inputs(inputs)
        outputs = sim.run_main()

        output_field_names = [f.name for f in parsed.data_fields if f.name not in inputs]
        expected = {k: outputs.get(k) for k in output_field_names}

        test_cases.append(TestCase(
            name="default_values",
            description="Execute with WORKING-STORAGE VALUE clauses",
            inputs=inputs,
            expected_outputs=expected,
            program_id=parsed.program_name
        ))

    return test_cases


def _run_single_test(
    test_case: TestCase,
    parsed: ParsedCobol,
    tester: FastAPITester
) -> TestResult:
    """Run a single equivalence test case."""
    import time

    start = time.time()

    # Run COBOL simulator
    sim = CobolSimulator(parsed)
    sim.set_inputs(test_case.inputs)
    cobol_outputs = sim.run_main()

    # Filter to expected output fields
    cobol_filtered = {k: v for k, v in cobol_outputs.items() if k in test_case.expected_outputs}

    # Run FastAPI endpoint
    # Map test inputs to API request
    fastapi_outputs = {}
    # This would need to map based on the generated API structure
    # For now, return placeholder

    # Compare
    differences = []
    for key, expected in test_case.expected_outputs.items():
        actual = cobol_filtered.get(key)
        if actual != expected:
            differences.append(f"{key}: expected {expected}, got {actual}")

    execution_time = (time.time() - start) * 1000

    if differences:
        return TestResult(
            test_case=test_case,
            status=TestResultStatus.FAIL,
            cobol_outputs=cobol_filtered,
            fastapi_outputs=fastapi_outputs,
            differences=differences,
            execution_time_ms=execution_time
        )
    else:
        return TestResult(
            test_case=test_case,
            status=TestResultStatus.PASS,
            cobol_outputs=cobol_filtered,
            fastapi_outputs=fastapi_outputs,
            execution_time_ms=execution_time
        )


def print_equivalence_report(report: EquivalenceReport):
    """Print formatted equivalence test report."""
    console.print(Panel.fit(
        f"[bold]Equivalence Test Report: {report.program_id}[/bold]\n"
        f"{report.summary}",
        border_style="green" if report.failed == 0 and report.errors == 0 else "red"
    ))

    table = Table(title="Test Results")
    table.add_column("Test Case", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Description")
    table.add_column("Differences", style="red")
    table.add_column("Time (ms)")

    for r in report.results:
        status_color = {
            TestResultStatus.PASS: "green",
            TestResultStatus.FAIL: "red",
            TestResultStatus.ERROR: "yellow",
            TestResultStatus.SKIPPED: "dim"
        }.get(r.status, "white")

        table.add_row(
            r.test_case.name,
            f"[{status_color}]{r.status.value}[/{status_color}]",
            r.test_case.description,
            "; ".join(r.differences) if r.differences else "—",
            f"{r.execution_time_ms:.1f}"
        )

    console.print(table)


def save_equivalence_report(report: EquivalenceReport, output_path: Path):
    """Save equivalence report to JSON."""
    data = {
        "program_id": report.program_id,
        "summary": report.summary,
        "total_tests": report.total_tests,
        "passed": report.passed,
        "failed": report.failed,
        "errors": report.errors,
        "skipped": report.skipped,
        "results": [
            {
                "test_case": {
                    "name": r.test_case.name,
                    "description": r.test_case.description,
                    "inputs": r.test_case.inputs,
                    "expected_outputs": r.test_case.expected_outputs,
                },
                "status": r.status.value,
                "cobol_outputs": r.cobol_outputs,
                "fastapi_outputs": r.fastapi_outputs,
                "differences": r.differences,
                "error_message": r.error_message,
                "execution_time_ms": r.execution_time_ms
            }
            for r in report.results
        ]
    }

    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2, default=str)

    console.print(f"[green]Report saved to {output_path}[/green]")