"""Tests for COBOL parser and extractor."""

import pytest
from src.cobol.extractor import extract_cobol_sections, clean_cobol_source
from src.cobol.parser import parse_cobol_file, ParsedCobol


SAMPLE_COBOL = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  CUSTOMER-RECORD.
           05  CUST-ID        PIC 9(6).
           05  CUST-NAME      PIC X(30).
           05  CUST-BALANCE   PIC 9(7)V99.
           05  CUST-STATUS    PIC X.
               88  ACTIVE     VALUE 'A'.
               88  INACTIVE   VALUE 'I'.

       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "Hello".
           ACCEPT CUST-ID.
           PERFORM LOOKUP-CUSTOMER.
           IF ACTIVE
               DISPLAY "Active customer"
           ELSE
               DISPLAY "Inactive"
           END-IF.
           STOP RUN.

       LOOKUP-CUSTOMER.
           MOVE "TEST" TO CUST-NAME.
           MOVE 100.00 TO CUST-BALANCE.
           MOVE "A" TO CUST-STATUS.
"""


def test_extract_program_id():
    """Test PROGRAM-ID extraction."""
    sections = extract_cobol_sections(SAMPLE_COBOL)
    assert sections.program_id == "TESTPROG"


def test_extract_working_storage():
    """Test WORKING-STORAGE extraction."""
    sections = extract_cobol_sections(SAMPLE_COBOL)
    assert "CUSTOMER-RECORD" in sections.working_storage
    assert "CUST-ID" in sections.working_storage
    assert "PIC 9(6)" in sections.working_storage
    assert "88  ACTIVE" in sections.working_storage


def test_extract_procedure_division():
    """Test PROCEDURE DIVISION extraction."""
    sections = extract_cobol_sections(SAMPLE_COBOL)
    assert "MAIN-PARA" in sections.procedure_division
    assert "LOOKUP-CUSTOMER" in sections.procedure_division
    assert "DISPLAY" in sections.procedure_division
    assert "PERFORM" in sections.procedure_division


def test_clean_cobol_source():
    """Test comment removal."""
    # COBOL fixed format: column 7 is * for full-line comments
    cobol_with_comments = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
      * This is a comment line
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  FIELD-1  PIC X(10).  *> Inline comment
"""
    cleaned = clean_cobol_source(cobol_with_comments)
    assert "This is a comment line" not in cleaned
    assert "Inline comment" not in cleaned
    assert "PROGRAM-ID. TESTPROG" in cleaned
    assert "FIELD-1" in cleaned


def test_parse_working_storage():
    """Test parsing WORKING-STORAGE into structured data."""
    sections = extract_cobol_sections(SAMPLE_COBOL)
    parsed = parse_cobol_file(sections)

    assert parsed.program_name == "TESTPROG"
    assert len(parsed.data_fields) > 0

    # Find CUSTOMER-RECORD (level 01)
    customer_record = next((f for f in parsed.data_fields if f.name == "CUSTOMER-RECORD"), None)
    assert customer_record is not None
    assert customer_record.level == 1
    assert customer_record.is_group

    # Find CUST-ID (level 05)
    cust_id = next((f for f in parsed.data_fields if f.name == "CUST-ID"), None)
    assert cust_id is not None
    assert cust_id.level == 5
    assert cust_id.picture == "9(6)"
    assert cust_id.python_type() == "int"

    # Find CUST-BALANCE
    cust_balance = next((f for f in parsed.data_fields if f.name == "CUST-BALANCE"), None)
    assert cust_balance is not None
    assert cust_balance.picture == "9(7)V99"
    assert cust_balance.python_type() == "Decimal"

    # Find condition names
    assert "ACTIVE" in parsed.condition_names
    assert parsed.condition_names["ACTIVE"]["field"] == "CUST-STATUS"
    assert parsed.condition_names["ACTIVE"]["value"] == "'A'"


def test_extract_paragraphs():
    """Test paragraph extraction from PROCEDURE DIVISION."""
    sections = extract_cobol_sections(SAMPLE_COBOL)
    parsed = parse_cobol_file(sections)

    assert "MAIN-PARA" in parsed.paragraphs
    assert "LOOKUP-CUSTOMER" in parsed.paragraphs


def test_extract_business_rules():
    """Test business rule extraction."""
    sections = extract_cobol_sections(SAMPLE_COBOL)
    parsed = parse_cobol_file(sections)

    assert len(parsed.business_logic) > 0

    # Check MAIN-PARA rule
    main_rule = next((r for r in parsed.business_logic if r.name == "MAIN-PARA"), None)
    assert main_rule is not None
    assert main_rule.rule_type in ["conditional", "workflow", "io"]

    # Check LOOKUP-CUSTOMER rule
    lookup_rule = next((r for r in parsed.business_logic if r.name == "LOOKUP-CUSTOMER"), None)
    assert lookup_rule is not None
    assert len(lookup_rule.actions) > 0


def test_extract_io_operations():
    """Test I/O operation extraction."""
    sections = extract_cobol_sections(SAMPLE_COBOL)
    parsed = parse_cobol_file(sections)

    # Should find DISPLAY and ACCEPT
    display_ops = [op for op in parsed.io_operations if op.operation == "DISPLAY"]
    accept_ops = [op for op in parsed.io_operations if op.operation == "ACCEPT"]

    assert len(display_ops) > 0
    assert len(accept_ops) > 0


def test_nested_structure():
    """Test parsing nested group items."""
    nested_cobol = """       PROGRAM-ID. NESTED.
       WORKING-STORAGE SECTION.
       01  ORDER-RECORD.
           05  ORDER-HEADER.
               10  ORDER-ID   PIC 9(8).
               10  ORDER-DATE PIC 9(8).
           05  ORDER-ITEMS OCCURS 10 TIMES.
               10  ITEM-ID    PIC 9(6).
               10  ITEM-QTY   PIC 9(4).
               10  ITEM-PRICE PIC 9(5)V99.
       PROCEDURE DIVISION.
       MAIN.
           STOP RUN.
"""
    sections = extract_cobol_sections(nested_cobol)
    parsed = parse_cobol_file(sections)

    order_record = next((f for f in parsed.data_fields if f.name == "ORDER-RECORD"), None)
    assert order_record is not None
    assert len(order_record.children) == 2

    order_header = next((f for f in order_record.children if f.name == "ORDER-HEADER"), None)
    assert order_header is not None
    assert len(order_header.children) == 2

    order_items = next((f for f in order_record.children if f.name == "ORDER-ITEMS"), None)
    assert order_items is not None
    assert order_items.occurs == 10


def test_redefines():
    """Test REDEFINES clause parsing."""
    redefines_cobol = """       PROGRAM-ID. REDEFTST.
       WORKING-STORAGE SECTION.
       01  RECORD-1.
           05  FIELD-A PIC X(10).
       01  RECORD-2 REDEFINES RECORD-1.
           05  FIELD-B PIC 9(10).
       PROCEDURE DIVISION.
       MAIN.
           STOP RUN.
"""
    sections = extract_cobol_sections(redefines_cobol)
    parsed = parse_cobol_file(sections)

    record2 = next((f for f in parsed.data_fields if f.name == "RECORD-2"), None)
    assert record2 is not None
    assert record2.redefines == "RECORD-1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])