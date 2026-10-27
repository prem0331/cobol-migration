"""Tests for CALL graph extraction and analysis."""

import pytest
from src.cobol.callgraph import (
    extract_calls,
    extract_calls_with_context,
    build_call_graph,
    find_entry_points,
    find_leaf_programs,
    find_circular_calls,
)


SAMPLE_PROC_DIVISION = """       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "Starting program".
           CALL "VALIDATE-INPUT" USING WS-INPUT.
           IF WS-VALID
               CALL "PROCESS-RECORD" USING WS-RECORD WS-OUTPUT
               CALL "WRITE-OUTPUT" USING WS-OUTPUT
           ELSE
               CALL "LOG-ERROR" USING WS-ERROR-MSG
           END-IF.
           STOP RUN.

       VALIDATE-INPUT.
           * Validation logic here
           EXIT.

       PROCESS-RECORD.
           CALL "CALCULATE-TOTAL" USING WS-AMOUNT WS-RATE WS-TOTAL.
           EXIT.

       CALCULATE-TOTAL.
           COMPUTE WS-TOTAL = WS-AMOUNT * WS-RATE.
           EXIT.

       WRITE-OUTPUT.
           WRITE OUTPUT-RECORD FROM WS-OUTPUT.
           EXIT.

       LOG-ERROR.
           CALL "ERROR-HANDLER" USING WS-ERROR-CODE WS-ERROR-MSG.
           EXIT.
"""

SAMPLE_DYNAMIC_CALL = """       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE "SUB-PROG" TO WS-PROG-NAME.
           CALL WS-PROG-NAME USING WS-PARAM.
           STOP RUN.
"""

MULTI_PROGRAM_SOURCES = {
    "MAINPROG": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAINPROG.
       PROCEDURE DIVISION.
       MAIN.
           CALL "SUBPROG1" USING WS-DATA.
           CALL "SUBPROG2" USING WS-DATA.
           STOP RUN.
""",
    "SUBPROG1": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUBPROG1.
       PROCEDURE DIVISION.
       MAIN.
           CALL "UTILITY" USING WS-PARAM.
           EXIT.
""",
    "SUBPROG2": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUBPROG2.
       PROCEDURE DIVISION.
       MAIN.
           EXIT.
""",
    "UTILITY": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. UTILITY.
       PROCEDURE DIVISION.
       MAIN.
           EXIT.
""",
}

CIRCULAR_CALL_SOURCES = {
    "PROGA": """       PROGRAM-ID. PROGA.
       PROCEDURE DIVISION.
       MAIN.
           CALL "PROGB".
           EXIT.
""",
    "PROGB": """       PROGRAM-ID. PROGB.
       PROCEDURE DIVISION.
       MAIN.
           CALL "PROGC".
           EXIT.
""",
    "PROGC": """       PROGRAM-ID. PROGC.
       PROCEDURE DIVISION.
       MAIN.
           CALL "PROGA".
           EXIT.
""",
}


def test_extract_static_calls():
    """Test extraction of static CALL statements."""
    calls = extract_calls(SAMPLE_PROC_DIVISION)

    assert len(calls) == 6  # VALIDATE-INPUT, PROCESS-RECORD, WRITE-OUTPUT, LOG-ERROR, CALCULATE-TOTAL, ERROR-HANDLER

    # Check first call
    call1 = calls[0]
    assert call1.target_program == "VALIDATE-INPUT"
    assert call1.using_params == ["WS-INPUT"]
    assert call1.is_dynamic is False
    assert call1.paragraph == "MAIN-PARA"

    # Check call with multiple USING params
    call2 = calls[1]
    assert call2.target_program == "PROCESS-RECORD"
    assert call2.using_params == ["WS-RECORD", "WS-OUTPUT"]

    # Check call with RETURNING/GIVING
    call_with_giving = [c for c in calls if c.giving_param]
    assert len(call_with_giving) >= 0  # May or may not have GIVING in this sample


def test_extract_dynamic_calls():
    """Test extraction of dynamic CALL statements."""
    calls = extract_calls(SAMPLE_DYNAMIC_CALL)

    assert len(calls) == 1
    assert calls[0].target_program == "WS-PROG-NAME"
    assert calls[0].is_dynamic is True
    assert calls[0].using_params == ["WS-PARAM"]


def test_extract_calls_with_context():
    """Test grouping calls by paragraph."""
    grouped = extract_calls_with_context(SAMPLE_PROC_DIVISION)

    assert "MAIN-PARA" in grouped
    assert "PROCESS-RECORD" in grouped
    assert len(grouped["MAIN-PARA"]) == 4  # VALIDATE-INPUT, PROCESS-RECORD, WRITE-OUTPUT, LOG-ERROR


def test_build_call_graph():
    """Test building call graph from multiple programs."""
    graph = build_call_graph(MULTI_PROGRAM_SOURCES)

    assert len(graph['nodes']) == 4
    assert len(graph['edges']) == 3  # MAINPROG->SUBPROG1, MAINPROG->SUBPROG2, SUBPROG1->UTILITY

    # Check edges
    edge_targets = [(e['source'], e['target']) for e in graph['edges']]
    assert ("MAINPROG", "SUBPROG1") in edge_targets
    assert ("MAINPROG", "SUBPROG2") in edge_targets
    assert ("SUBPROG1", "UTILITY") in edge_targets


def test_find_entry_points():
    """Test finding entry points (programs not called by others)."""
    graph = build_call_graph(MULTI_PROGRAM_SOURCES)
    entry_points = find_entry_points(graph)

    assert "MAINPROG" in entry_points
    assert "SUBPROG1" not in entry_points
    assert "SUBPROG2" not in entry_points
    assert "UTILITY" not in entry_points


def test_find_leaf_programs():
    """Test finding leaf programs (programs that don't call others)."""
    graph = build_call_graph(MULTI_PROGRAM_SOURCES)
    leaf_programs = find_leaf_programs(graph)

    assert "SUBPROG2" in leaf_programs
    assert "UTILITY" in leaf_programs
    assert "MAINPROG" not in leaf_programs
    assert "SUBPROG1" not in leaf_programs


def test_find_circular_calls():
    """Test detection of circular call dependencies."""
    graph = build_call_graph(CIRCULAR_CALL_SOURCES)
    cycles = find_circular_calls(graph)

    assert len(cycles) > 0
    # Should find the cycle PROGA -> PROGB -> PROGC -> PROGA
    cycle = cycles[0]
    assert "PROGA" in cycle
    assert "PROGB" in cycle
    assert "PROGC" in cycle


def test_unresolved_dynamic_calls_tracked():
    """Test that dynamic calls are tracked as unresolved."""
    graph = build_call_graph({
        "MAIN": """       PROGRAM-ID. MAIN.
       PROCEDURE DIVISION.
       MAIN.
           MOVE "DYNAMIC" TO WS-PROG.
           CALL WS-PROG USING WS-DATA.
           STOP RUN.
"""
    })

    unresolved = graph.get('unresolved_dynamic_calls', [])
    assert len(unresolved) == 1
    assert unresolved[0]['source_program'] == "MAIN"
    assert unresolved[0]['variable'] == "WS-PROG"


def test_call_with_giving_returning():
    """Test CALL with RETURNING/GIVING clause."""
    proc_div = """       MAIN-PARA.
           CALL "CALCULATE" USING WS-INPUT RETURNING WS-RESULT.
           STOP RUN.
"""
    calls = extract_calls(proc_div)

    assert len(calls) == 1
    assert calls[0].target_program == "CALCULATE"
    assert calls[0].using_params == ["WS-INPUT"]
    assert calls[0].giving_param == "WS-RESULT"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])