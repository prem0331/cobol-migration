"""Tests for file I/O and data flow analysis."""

import pytest
from src.cobol.dataflow import (
    extract_file_definitions,
    extract_file_operations,
    analyze_file_sharing,
    extract_select_assign_from_env,
    build_data_dependency_graph,
    FileDefinition,
    FileOperation,
    FileAccessMode,
    FileOrganization,
)


SAMPLE_FILE_SECTION = """       FILE SECTION.
       FD  CUSTOMER-FILE
           LABEL RECORDS STANDARD
           BLOCK CONTAINS 20 RECORDS
           RECORD CONTAINS 80 CHARACTERS
           DATA RECORDS ARE CUSTOMER-RECORD.
       01  CUSTOMER-RECORD.
           05  CUST-ID           PIC 9(6).
           05  CUST-NAME         PIC X(30).

       FD  TRANSACTION-FILE
           ASSIGN TO TXNMAST
           ORGANIZATION IS INDEXED
           ACCESS MODE IS RANDOM
           RECORD KEY IS TXN-ID
           FILE STATUS IS WS-FILE-STATUS.
       01  TRANSACTION-RECORD.
           05  TXN-ID            PIC 9(10).
           05  TXN-AMOUNT        PIC 9(7)V99.
"""

SAMPLE_ENV_DIVISION = """       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUSTOMER-FILE
               ASSIGN TO CUSTMAST
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-CUST-STATUS.

           SELECT TRANSACTION-FILE
               ASSIGN TO TXNMAST
               ORGANIZATION IS INDEXED
               ACCESS MODE IS RANDOM
               RECORD KEY IS TXN-ID
               ALTERNATE RECORD KEY IS TXN-DATE
               FILE STATUS IS WS-TXN-STATUS.
"""

SAMPLE_PROC_DIVISION = """       PROCEDURE DIVISION.
       OPEN-INPUT.
           OPEN INPUT CUSTOMER-FILE.
           OPEN I-O TRANSACTION-FILE.

       READ-CUSTOMER.
           READ CUSTOMER-FILE INTO WS-CUSTOMER-REC
               AT END SET WS-EOF TO TRUE.

       WRITE-TRANSACTION.
           WRITE TRANSACTION-RECORD FROM WS-TXN-REC
               INVALID KEY DISPLAY "Duplicate key".

       REWRITE-CUSTOMER.
           REWRITE CUSTOMER-RECORD FROM WS-CUST-UPDATE
               INVALID KEY DISPLAY "Rewrite failed".

       DELETE-TRANSACTION.
           DELETE TRANSACTION-FILE
               INVALID KEY DISPLAY "Delete failed".

       START-TRANSACTION.
           START TRANSACTION-FILE KEY IS EQUAL TO WS-TXN-ID
               INVALID KEY DISPLAY "Not found".

       CLOSE-FILES.
           CLOSE CUSTOMER-FILE TRANSACTION-FILE.
           STOP RUN.
"""

MULTI_PROGRAM_SOURCES = {
    "CUSTINQ": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CUSTINQ.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUSTOMER-FILE ASSIGN TO CUSTMAST.
       DATA DIVISION.
       FILE SECTION.
       FD CUSTOMER-FILE ASSIGN TO CUSTMAST.
       01 CUSTOMER-RECORD PIC X(80).
       PROCEDURE DIVISION.
       MAIN.
           OPEN INPUT CUSTOMER-FILE.
           READ CUSTOMER-FILE.
           CLOSE CUSTOMER-FILE.
           STOP RUN.
""",
    "TRANSACT": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TRANSACT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUSTOMER-FILE ASSIGN TO CUSTMAST.
           SELECT TRANSACTION-FILE ASSIGN TO TXNMAST.
       DATA DIVISION.
       FILE SECTION.
       FD CUSTOMER-FILE ASSIGN TO CUSTMAST.
       01 CUSTOMER-RECORD PIC X(80).
       FD TRANSACTION-FILE ASSIGN TO TXNMAST.
       01 TRANSACTION-RECORD PIC X(100).
       PROCEDURE DIVISION.
       MAIN.
           OPEN I-O CUSTOMER-FILE.
           OPEN OUTPUT TRANSACTION-FILE.
           READ CUSTOMER-FILE.
           WRITE TRANSACTION-RECORD.
           CLOSE CUSTOMER-FILE TRANSACTION-FILE.
           STOP RUN.
""",
    "REPORT": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. REPORT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TRANSACTION-FILE ASSIGN TO TXNMAST.
       DATA DIVISION.
       FILE SECTION.
       FD TRANSACTION-FILE ASSIGN TO TXNMAST.
       01 TRANSACTION-RECORD PIC X(100).
       PROCEDURE DIVISION.
       MAIN.
           OPEN INPUT TRANSACTION-FILE.
           READ TRANSACTION-FILE.
           CLOSE TRANSACTION-FILE.
           STOP RUN.
""",
}


def test_extract_file_definitions():
    """Test extracting file definitions from FILE SECTION."""
    files = extract_file_definitions(SAMPLE_FILE_SECTION)

    assert len(files) == 2

    # Check CUSTOMER-FILE
    cust_file = next(f for f in files if f.fd_name == "CUSTOMER-FILE")
    assert cust_file.fd_name == "CUSTOMER-FILE"
    assert cust_file.label_records == "STANDARD"
    assert cust_file.block_size == 20
    assert cust_file.record_size == "80"  # Parser extracts just the number
    assert "CUSTOMER-RECORD" in cust_file.data_records

    # Check TRANSACTION-FILE
    txn_file = next(f for f in files if f.fd_name == "TRANSACTION-FILE")
    assert txn_file.fd_name == "TRANSACTION-FILE"
    assert txn_file.assign_name == "TXNMAST"
    assert txn_file.organization == FileOrganization.INDEXED
    assert txn_file.access_mode == FileAccessMode.RANDOM


def test_extract_select_assign():
    """Test extracting SELECT/ASSIGN from ENVIRONMENT DIVISION."""
    select_map = extract_select_assign_from_env(SAMPLE_ENV_DIVISION)

    assert "CUSTOMER-FILE" in select_map
    assert select_map["CUSTOMER-FILE"]["assign"] == "CUSTMAST"
    assert select_map["CUSTOMER-FILE"]["organization"] == "SEQUENTIAL"
    assert select_map["CUSTOMER-FILE"]["access_mode"] == "SEQUENTIAL"

    assert "TRANSACTION-FILE" in select_map
    assert select_map["TRANSACTION-FILE"]["assign"] == "TXNMAST"
    assert select_map["TRANSACTION-FILE"]["organization"] == "INDEXED"
    assert select_map["TRANSACTION-FILE"]["record_key"] == "TXN-ID"
    assert select_map["TRANSACTION-FILE"]["alternate_key"] == "TXN-DATE"


def test_extract_file_operations():
    """Test extracting file operations from PROCEDURE DIVISION."""
    ops = extract_file_operations(SAMPLE_PROC_DIVISION)

    # Should find: OPEN INPUT, OPEN I-O, READ, WRITE, REWRITE, DELETE, START, CLOSE
    assert len(ops) >= 7

    # Check OPEN operations
    open_ops = [o for o in ops if o.operation == "OPEN"]
    assert len(open_ops) == 2
    assert open_ops[0].file_name == "CUSTOMER-FILE"
    assert open_ops[0].access_mode_implied == FileAccessMode.INPUT
    assert open_ops[1].file_name == "TRANSACTION-FILE"
    assert open_ops[1].access_mode_implied == FileAccessMode.I_O

    # Check READ
    read_ops = [o for o in ops if o.operation == "READ"]
    assert len(read_ops) >= 1
    assert read_ops[0].file_name == "CUSTOMER-FILE"

    # Check WRITE
    write_ops = [o for o in ops if o.operation == "WRITE"]
    assert len(write_ops) >= 1
    assert write_ops[0].file_name == "TRANSACTION-RECORD"

    # Check CLOSE
    close_ops = [o for o in ops if o.operation == "CLOSE"]
    assert len(close_ops) >= 1


def test_analyze_file_sharing():
    """Test analyzing shared files between programs."""
    programs = {
        "CUSTINQ": [
            FileDefinition(fd_name="CUSTOMER-FILE", assign_name="CUSTMAST"),
        ],
        "TRANSACT": [
            FileDefinition(fd_name="CUSTOMER-FILE", assign_name="CUSTMAST"),
            FileDefinition(fd_name="TRANSACTION-FILE", assign_name="TXNMAST"),
        ],
        "REPORT": [
            FileDefinition(fd_name="TRANSACTION-FILE", assign_name="TXNMAST"),
        ],
    }

    shared = analyze_file_sharing(programs)

    assert "CUSTMAST" in shared
    assert set(shared["CUSTMAST"]) == {"CUSTINQ", "TRANSACT"}

    assert "TXNMAST" in shared
    assert set(shared["TXNMAST"]) == {"TRANSACT", "REPORT"}


def test_build_data_dependency_graph():
    """Test building full data dependency graph."""
    graph = build_data_dependency_graph(MULTI_PROGRAM_SOURCES)

    assert "program_files" in graph
    assert "shared_files" in graph

    # Check shared files
    shared = graph["shared_files"]
    assert "CUSTMAST" in shared
    assert set(shared["CUSTMAST"]) == {"CUSTINQ", "TRANSACT"}

    assert "TXNMAST" in shared
    assert set(shared["TXNMAST"]) == {"TRANSACT", "REPORT"}


def test_file_access_mode_enum():
    """Test FileAccessMode enum values."""
    assert FileAccessMode.INPUT.value == "INPUT"
    assert FileAccessMode.OUTPUT.value == "OUTPUT"
    assert FileAccessMode.I_O.value == "I-O"
    assert FileAccessMode.EXTEND.value == "EXTEND"


def test_file_organization_enum():
    """Test FileOrganization enum values."""
    assert FileOrganization.SEQUENTIAL.value == "SEQUENTIAL"
    assert FileOrganization.INDEXED.value == "INDEXED"
    assert FileOrganization.RELATIVE.value == "RELATIVE"
    assert FileOrganization.LINE_SEQUENTIAL.value == "LINE SEQUENTIAL"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])