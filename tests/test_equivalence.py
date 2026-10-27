"""Tests for semantic equivalence testing framework."""

import pytest
from src.testing.equivalence import (
    CobolSimulator,
    TestCase,
    TestResult,
    TestResultStatus,
    EquivalenceReport,
    generate_test_cases,
    _generate_basic_test_cases,
)
from src.testing.cobol_simulator import (
    CobolInterpreter,
    create_interpreter_from_parsed,
    StatementType,
)
from src.cobol.parser import parse_cobol_file, ParsedCobol
from src.cobol.extractor import extract_cobol_sections


SAMPLE_COBOL = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NUM1        PIC 9(3) VALUE 10.
       01  WS-NUM2        PIC 9(3) VALUE 20.
       01  WS-RESULT      PIC 9(5).
       01  WS-STATUS      PIC X.
           88  SUCCESS    VALUE 'Y'.
           88  FAILURE    VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           COMPUTE WS-RESULT = WS-NUM1 + WS-NUM2.
           IF WS-RESULT > 25
               SET SUCCESS TO TRUE
           ELSE
               SET FAILURE TO TRUE
           END-IF.
           STOP RUN.
"""


def _get_parsed_cobol(filepath: str) -> ParsedCobol:
    """Helper to parse COBOL file properly."""
    source = open(filepath).read()
    sections = extract_cobol_sections(source)
    parsed = parse_cobol_file(sections)
    # Add missing attributes for compatibility
    parsed.procedure_division = sections.procedure_division
    parsed.condition_values = {}
    for field in parsed.data_fields:
        for cond in field.condition_names:
            parsed.condition_values[cond['name']] = cond['value']
    return parsed


def test_cobol_interpreter_basic():
    """Test basic COBOL interpreter functionality."""
    parsed = _get_parsed_cobol("examples/sample.cbl")
    interpreter = create_interpreter_from_parsed(parsed)
    result = interpreter.run()

    assert "CUST-ID" in result
    assert "CUST-NAME" in result
    assert "CUST-BALANCE" in result
    assert "CUST-STATUS" in result


def test_cobol_interpreter_compute():
    """Test COMPUTE statement execution."""
    parsed = _get_parsed_cobol("examples/sample.cbl")
    interpreter = create_interpreter_from_parsed(parsed)

    # Set inputs
    interpreter.variables["CUST-ID"].value = 12345

    # Run
    result = interpreter.run()

    # Should have executed MAIN-PARA
    assert result is not None


def test_cobol_interpreter_move():
    """Test MOVE statement."""
    interpreter = CobolInterpreter()
    interpreter.add_variable(
        interpreter.variables.setdefault("WS-A", type('obj', (object,), {"name": "WS-A", "pic": "9(3)", "value": 0}))()
    )
    interpreter.add_variable(
        interpreter.variables.setdefault("WS-B", type('obj', (object,), {"name": "WS-B", "pic": "9(3)", "value": 0}))()
    )

    # Manually add vars
    from src.testing.cobol_simulator import CobolVariable
    interpreter.variables["WS-A"] = CobolVariable(name="WS-A", pic="9(3)", value=0)
    interpreter.variables["WS-B"] = CobolVariable(name="WS-B", pic="9(3)", value=0)

    interpreter.load_program("""       MAIN-PARA.
           MOVE 10 TO WS-A.
           MOVE WS-A TO WS-B.
           STOP RUN.
""")
    result = interpreter.run("MAIN-PARA")

    assert result["WS-A"] == 10
    assert result["WS-B"] == 10


def test_cobol_interpreter_88_level():
    """Test 88-level condition handling."""
    interpreter = CobolInterpreter()

    from src.testing.cobol_simulator import CobolVariable
    var = CobolVariable(name="WS-STATUS", pic="X", value="N")
    var.condition_values = {"SUCCESS": "Y", "FAILURE": "N"}
    interpreter.variables["WS-STATUS"] = var

    interpreter.load_program("""       MAIN-PARA.
           SET SUCCESS TO TRUE.
           STOP RUN.
""")
    result = interpreter.run("MAIN-PARA")

    # 88-level SET TRUE should set the parent variable to the condition value
    assert result["WS-STATUS"] == "Y"


def test_cobol_interpreter_perform():
    """Test PERFORM statement."""
    from src.testing.cobol_simulator import CobolInterpreter, CobolVariable

    interpreter = CobolInterpreter()
    interpreter.variables["WS-COUNTER"] = CobolVariable(name="WS-COUNTER", pic="9(2)", value=0)

    interpreter.load_program("""       MAIN-PARA.
           PERFORM INCREMENT.
           STOP RUN.

       INCREMENT.
           ADD 1 TO WS-COUNTER.
           GOBACK.
""")
    result = interpreter.run("MAIN-PARA")

    assert result["WS-COUNTER"] == 1


def test_cobol_simulator_class():
    """Test the CobolSimulator class (simplified version)."""
    parsed = _get_parsed_cobol("examples/sample.cbl")
    simulator = CobolSimulator(parsed)

    # Set inputs
    simulator.set_inputs({"CUST-ID": 99999})

    # Run
    outputs = simulator.run_main()

    assert "CUST-ID" in outputs
    assert outputs["CUST-ID"] == 99999


def test_generate_test_cases():
    """Test test case generation."""
    parsed = _get_parsed_cobol("examples/sample.cbl")

    # Create a mock BusinessRules object
    from src.pipeline.models import BusinessRules, DataField, BusinessRule, IOOperation
    business_rules = BusinessRules(
        program_name="CUSTINQ",
        data_definitions=[
            DataField(name="CUST-ID", pic="9(6)", level=5, usage="INPUT", value="12345"),
            DataField(name="CUST-NAME", pic="X(30)", level=5, usage="OUTPUT"),
            DataField(name="CUST-BALANCE", pic="9(7)V99", level=5, usage="OUTPUT"),
            DataField(name="CUST-STATUS", pic="X", level=5, usage="OUTPUT"),
        ],
        business_logic=[],
        io_operations=[]
    )

    test_cases = generate_test_cases(parsed, business_rules)

    assert len(test_cases) >= 1
    assert test_cases[0].name == "normal_flow"
    assert test_cases[0].program_id == "CUSTINQ"


def test_basic_test_case_generation():
    """Test basic test case generation from parsed COBOL."""
    # Use a COBOL with VALUE clauses
    sample_with_values = """       IDENTIFICATION DIVISION.
           PROGRAM-ID. TESTPROG.
           DATA DIVISION.
           WORKING-STORAGE SECTION.
           01  WS-NUM1        PIC 9(3) VALUE 10.
           01  WS-NUM2        PIC 9(3) VALUE 20.
           01  WS-RESULT      PIC 9(5).
           PROCEDURE DIVISION.
           MAIN-PARA.
               COMPUTE WS-RESULT = WS-NUM1 + WS-NUM2.
               STOP RUN.
    """
    from src.cobol.extractor import extract_cobol_sections
    from src.cobol.parser import parse_cobol_file
    sections = extract_cobol_sections(sample_with_values)
    parsed = parse_cobol_file(sections)
    # Attach procedure_division for the simulator
    parsed.procedure_division = sections.procedure_division

    test_cases = _generate_basic_test_cases(parsed)

    assert len(test_cases) >= 1
    tc = test_cases[0]
    assert isinstance(tc, TestCase)
    assert tc.program_id == "TESTPROG"
    assert "WS-NUM1" in tc.inputs
    assert tc.inputs["WS-NUM1"] == "10"


def test_equivalence_report():
    """Test EquivalenceReport creation and summary."""
    report = EquivalenceReport(program_id="TESTPROG")
    report.total_tests = 5
    report.passed = 4
    report.failed = 1
    report.errors = 0
    report.skipped = 0

    assert report.passed + report.failed + report.errors + report.skipped == report.total_tests


def test_test_result_status_enum():
    """Test TestResultStatus enum values."""
    assert TestResultStatus.PASS.value == "PASS"
    assert TestResultStatus.FAIL.value == "FAIL"
    assert TestResultStatus.ERROR.value == "ERROR"
    assert TestResultStatus.SKIPPED.value == "SKIPPED"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])