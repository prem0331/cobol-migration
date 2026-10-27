IDENTIFICATION DIVISION.
       PROGRAM-ID. REPORT-MAIN.
       AUTHOR. INTEGRATION TEST.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT REPORT-FILE
               ASSIGN TO RPTMAST
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-RPT-STATUS.

       DATA DIVISION.
       FILE SECTION.
       FD REPORT-FILE.
       01  REPORT-RECORD.
           05  RPT-ID       PIC 9(6).
           05  RPT-TYPE     PIC X(10).
           05  RPT-AMOUNT   PIC 9(7)V99.
           05  RPT-DATE     PIC 9(8).

       WORKING-STORAGE SECTION.
       01  WS-RPT-STATUS        PIC XX.
       01  WS-REPORT-COUNTER    PIC 9(4) VALUE ZERO.

       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "=== INDEPENDENT REPORT PROGRAM ===".
           OPEN OUTPUT REPORT-FILE.
           IF WS-RPT-STATUS NOT = "00"
               DISPLAY "Error opening report file"
               GO TO END-PROGRAM
           END-IF.

           MOVE 123456 TO RPT-ID.
           MOVE "SUMMARY" TO RPT-TYPE.
           MOVE 9999.99 TO RPT-AMOUNT.
           MOVE 20240115 TO RPT-DATE.
           WRITE REPORT-RECORD.
           ADD 1 TO WS-REPORT-COUNTER.

           MOVE 789012 TO RPT-ID.
           MOVE "DETAIL" TO RPT-TYPE.
           MOVE 1234.56 TO RPT-AMOUNT.
           MOVE 20240116 TO RPT-DATE.
           WRITE REPORT-RECORD.
           ADD 1 TO WS-REPORT-COUNTER.

           CLOSE REPORT-FILE.
           DISPLAY "Report generated: " WS-REPORT-COUNTER " records".

       END-PROGRAM.
           STOP RUN.