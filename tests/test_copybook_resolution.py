"""Tests for copybook resolution and file discovery."""

import pytest
import tempfile
import os
from pathlib import Path

from src.cobol.copybook import (
    extract_copy_statements,
    resolve_copy_statement,
    resolve_all_copies,
    load_copybook_map,
    resolve_cobol_source,
    CopyStatement,
)
from src.cobol.discovery import (
    find_cobol_files,
    find_copybooks,
    discover_all,
    filter_cobol_programs,
    extract_program_id,
)
from src.cobol.extractor import extract_cobol_sections_with_copybooks


# Test copybook content
SAMPLE_COPYBOOK = """       01  CUSTOMER-RECORD.
           05  CUST-ID           PIC 9(6).
           05  CUST-NAME         PIC X(30).
           05  CUST-BALANCE      PIC 9(7)V99.
           05  CUST-STATUS       PIC X.
               88  ACTIVE        VALUE 'A'.
               88  INACTIVE      VALUE 'I'.
"""

COBOL_WITH_COPY = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY CUSTOMER-REC.

       01  TRANSACTION-RECORD.
           05  TXN-ID            PIC 9(10).
           05  TXN-AMOUNT        PIC 9(7)V99.

       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "Hello".
           STOP RUN.
"""

COBOL_WITH_REPLACING = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY CUSTOMER-REC REPLACING CUST- BY CLIENT-.

       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""

COBOL_NESTED_COPY = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY OUTER-COPY.

       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""

OUTER_COPYBOOK = """       01  OUTER-RECORD.
           05  OUTER-FIELD       PIC X(10).
           COPY INNER-COPY.
"""

INNER_COPYBOOK = """       05  INNER-FIELD       PIC 9(5).
"""


def test_extract_copy_statements_basic():
    """Test extracting basic COPY statements."""
    statements = extract_copy_statements(COBOL_WITH_COPY)

    assert len(statements) == 1
    assert statements[0].copy_name == "CUSTOMER-REC"
    assert statements[0].replacing == []


def test_extract_copy_statements_with_replacing():
    """Test extracting COPY with REPLACING."""
    statements = extract_copy_statements(COBOL_WITH_REPLACING)

    assert len(statements) == 1
    assert statements[0].copy_name == "CUSTOMER-REC"
    assert len(statements[0].replacing) == 1
    assert statements[0].replacing[0] == ("CUST-", "CLIENT-")


def test_resolve_copy_statement():
    """Test resolving a single COPY statement."""
    stmt = CopyStatement(
        copy_name="CUSTOMER-REC",
        replacing=[],
        line_number=5,
        original_text="       COPY CUSTOMER-REC."
    )

    resolved = resolve_copy_statement(stmt, SAMPLE_COPYBOOK, {})

    assert "CUSTOMER-RECORD" in resolved
    assert "CUST-ID" in resolved
    assert "PIC 9(6)" in resolved


def test_resolve_copy_statement_with_replacing():
    """Test resolving COPY with REPLACING."""
    stmt = CopyStatement(
        copy_name="CUSTOMER-REC",
        replacing=[("CUST-", "CLIENT-")],
        line_number=5,
        original_text="       COPY CUSTOMER-REC REPLACING CUST- BY CLIENT-."
    )

    resolved = resolve_copy_statement(stmt, SAMPLE_COPYBOOK, {})

    assert "CLIENT-ID" in resolved
    assert "CLIENT-NAME" in resolved
    assert "CLIENT-BALANCE" in resolved
    assert "CUST-ID" not in resolved  # Should be replaced


def test_resolve_all_copies():
    """Test resolving all COPY statements in source."""
    copybook_map = {"CUSTOMER-REC": SAMPLE_COPYBOOK}

    resolved, statements = resolve_all_copies(COBOL_WITH_COPY, copybook_map)

    assert "CUSTOMER-RECORD" in resolved
    assert "CUST-ID" in resolved
    assert len(statements) == 1


def test_resolve_cobol_source():
    """Test the convenience function."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create copybook
        copybook_path = Path(tmpdir) / "CUSTOMER-REC.cpy"
        copybook_path.write_text(SAMPLE_COPYBOOK)

        resolved, statements = resolve_cobol_source(COBOL_WITH_COPY, [tmpdir])

        assert "CUSTOMER-RECORD" in resolved
        assert "CUST-ID" in resolved


def test_nested_copy_resolution():
    """Test resolving nested COPY statements."""
    copybook_map = {
        "OUTER-COPY": OUTER_COPYBOOK,
        "INNER-COPY": INNER_COPYBOOK,
    }

    resolved, statements = resolve_all_copies(COBOL_NESTED_COPY, copybook_map)

    assert "OUTER-RECORD" in resolved
    assert "OUTER-FIELD" in resolved
    assert "INNER-FIELD" in resolved
    # Should have both copy statements tracked
    copy_names = [s.copy_name for s in statements]
    assert "OUTER-COPY" in copy_names
    assert "INNER-COPY" in copy_names


def test_unresolved_copybook_handling():
    """Test handling of unresolved copybooks."""
    # Test comment handler (default)
    resolved, statements = resolve_all_copies(
        COBOL_WITH_COPY,
        {},  # Empty map - copybook not found
        unresolved_handler='comment'
    )
    assert "UNRESOLVED COPY" in resolved

    # Test keep handler
    resolved, _ = resolve_all_copies(
        COBOL_WITH_COPY,
        {},
        unresolved_handler='keep'
    )
    assert "COPY CUSTOMER-REC" in resolved


def test_discover_cobol_files():
    """Test file discovery."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test files
        (Path(tmpdir) / "prog1.cbl").write_text("PROGRAM-ID. PROG1.")
        (Path(tmpdir) / "prog2.cob").write_text("PROGRAM-ID. PROG2.")
        (Path(tmpdir) / "copybook.cpy").write_text("01 REC PIC X(10).")
        (Path(tmpdir) / "subdir").mkdir()
        (Path(tmpdir) / "subdir" / "prog3.cobol").write_text("PROGRAM-ID. PROG3.")

        files = find_cobol_files(tmpdir)

        assert len(files) == 4
        names = [Path(f.path).name for f in files]
        assert "prog1.cbl" in names
        assert "prog2.cob" in names
        assert "prog3.cobol" in names


def test_discover_copybooks():
    """Test copybook discovery."""
    with tempfile.TemporaryDirectory() as tmpdir:
        copybook_dir = Path(tmpdir) / "copybooks"
        copybook_dir.mkdir()

        (copybook_dir / "CUST-REC.cpy").write_text("01 CUST PIC X(10).")
        (copybook_dir / "PROD-REC.copy").write_text("01 PROD PIC X(10).")

        copybooks = find_copybooks([str(copybook_dir)])

        assert "CUST-REC" in copybooks
        assert "PROD-REC" in copybooks
        assert copybooks["CUST-REC"].path.endswith("CUST-REC.cpy")


def test_extract_program_id():
    """Test PROGRAM-ID extraction."""
    cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. MYPROG.
    """
    assert extract_program_id(cobol) == "MYPROG"

    # With period
    cobol2 = """       PROGRAM-ID. ANOTHER-PROG."""
    assert extract_program_id(cobol2) == "ANOTHER-PROG"


def test_discover_all():
    """Test full discovery."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create structure
        (Path(tmpdir) / "cobol").mkdir()
        (Path(tmpdir) / "cobol" / "prog1.cbl").write_text("PROGRAM-ID. PROG1.\nCOPY CUST-REC.")
        (Path(tmpdir) / "cobol" / "prog2.cbl").write_text("PROGRAM-ID. PROG2.")
        (Path(tmpdir) / "copybooks").mkdir()
        (Path(tmpdir) / "copybooks" / "CUST-REC.cpy").write_text("01 CUST PIC X(10).")

        result = discover_all(str(Path(tmpdir) / "cobol"), [str(Path(tmpdir) / "copybooks")])

        assert len(result['files']) == 2
        assert "CUST-REC" in result['copybooks']


def test_filter_cobol_programs():
    """Test filtering to only main programs."""
    from src.cobol.discovery import CobolFile

    files = [
        CobolFile(path="/src/prog1.cbl", program_id="PROG1"),
        CobolFile(path="/src/copybooks/cust.cpy", program_id=None),
        CobolFile(path="/src/prog2.cob", program_id="PROG2"),
    ]

    programs = filter_cobol_programs(files)
    assert len(programs) == 2
    assert all(f.program_id is not None for f in programs)


def test_extract_sections_with_copybooks():
    """Test full extraction with copybook resolution."""
    with tempfile.TemporaryDirectory() as tmpdir:
        copybook_dir = Path(tmpdir) / "copybooks"
        copybook_dir.mkdir()
        (copybook_dir / "CUSTOMER-REC.cpy").write_text(SAMPLE_COPYBOOK)

        sections = extract_cobol_sections_with_copybooks(
            COBOL_WITH_COPY,
            [str(copybook_dir)]
        )

        assert sections.program_id == "TESTPROG"
        assert "CUSTOMER-RECORD" in sections.working_storage
        assert "CUST-ID" in sections.working_storage
        assert "TRANSACTION-RECORD" in sections.working_storage
        assert len(sections.copy_statements) == 1
        assert sections.copy_statements[0].copy_name == "CUSTOMER-REC"


def test_extract_sections_with_replacing():
    """Test extraction with REPLACING clause."""
    with tempfile.TemporaryDirectory() as tmpdir:
        copybook_dir = Path(tmpdir) / "copybooks"
        copybook_dir.mkdir()
        (copybook_dir / "CUSTOMER-REC.cpy").write_text(SAMPLE_COPYBOOK)

        sections = extract_cobol_sections_with_copybooks(
            COBOL_WITH_REPLACING,
            [str(copybook_dir)]
        )

        assert "CLIENT-ID" in sections.working_storage
        assert "CLIENT-NAME" in sections.working_storage
        assert "CUST-ID" not in sections.working_storage


if __name__ == "__main__":
    pytest.main([__file__, "-v"])