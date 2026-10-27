IDENTIFICATION DIVISION.
       PROGRAM-ID. CUSTOMER-MAIN.
       AUTHOR. INTEGRATION TEST.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUSTOMER-FILE
               ASSIGN TO CUSTMAST
               ORGANIZATION IS INDEXED
               ACCESS MODE IS RANDOM
               RECORD KEY IS CUST-ID
               FILE STATUS IS WS-FILE-STATUS.

       DATA DIVISION.
       FILE SECTION.
       FD CUSTOMER-FILE.
           COPY CUSTOMER-REC.

       WORKING-STORAGE SECTION.
           COPY CUSTOMER-REC REPLACING CUSTOMER-RECORD BY WS-CUSTOMER-RECORD
                                        VALIDATION-RESULT BY WS-VALIDATION-RESULT.

       01  WS-FILE-STATUS        PIC XX.
       01  WS-INPUT-CUST-ID      PIC 9(6).
       01  WS-RESPONSE-MSG       PIC X(80).

       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "=== CUSTOMER MAIN PROGRAM ===".
           DISPLAY "Enter Customer ID: ".
           ACCEPT WS-INPUT-CUST-ID.
           MOVE WS-INPUT-CUST-ID TO CUST-ID OF WS-CUSTOMER-RECORD.

           * Call validation program
           CALL "VALIDATE-CUST" USING WS-CUSTOMER-RECORD WS-VALIDATION-RESULT.
           IF VALID-ERROR OF WS-VALIDATION-RESULT
               MOVE ERROR-MSG OF WS-VALIDATION-RESULT TO WS-RESPONSE-MSG
               DISPLAY "Validation Error: " WS-RESPONSE-MSG
               GO TO END-PROGRAM
           END-IF.

           * Call lookup program
           CALL "LOOKUP-CUST" USING WS-CUSTOMER-RECORD.
           IF WS-FILE-STATUS NOT = "00"
               MOVE "Customer lookup failed" TO WS-RESPONSE-MSG
               DISPLAY "Lookup Error: " WS-RESPONSE-MSG
               GO TO END-PROGRAM
           END-IF.

           * Display customer info
           DISPLAY "Customer Found:".
           DISPLAY "  ID: " CUST-ID OF WS-CUSTOMER-RECORD.
           DISPLAY "  Name: " CUST-NAME OF WS-CUSTOMER-RECORD.
           DISPLAY "  Balance: " CUST-BALANCE OF WS-CUSTOMER-RECORD.
           DISPLAY "  Status: " CUST-STATUS OF WS-CUSTOMER-RECORD.

       END-PROGRAM.
           STOP RUN.