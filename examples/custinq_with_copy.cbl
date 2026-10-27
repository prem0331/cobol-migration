IDENTIFICATION DIVISION.
       PROGRAM-ID. CUSTINQ.

       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SOURCE-COMPUTER. IBM-ZOS.
       OBJECT-COMPUTER. IBM-ZOS.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY CUSTOMER-REC.

       01  TRANSACTION-RECORD.
           05  TXN-ID            PIC 9(10).
           05  TXN-AMOUNT        PIC 9(7)V99.
           05  TXN-TYPE          PIC X.
               88  TXN-DEBIT     VALUE 'D'.
               88  TXN-CREDIT    VALUE 'C'.
           05  TXN-DATE          PIC 9(8).
           05  TXN-DESC          PIC X(40).

       01  WS-RESPONSE-MESSAGE  PIC X(80).
       01  WS-ERROR-FLAG        PIC X.
           88  WS-NO-ERROR      VALUE 'N'.
           88  WS-HAS-ERROR     VALUE 'Y'.

       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "=== CUSTOMER INQUIRY SYSTEM ===".
           DISPLAY "Enter Customer ID (6 digits): ".
           ACCEPT CUST-ID.
           PERFORM VALIDATE-CUST-ID.
           IF WS-HAS-ERROR
               DISPLAY WS-RESPONSE-MESSAGE
               GO TO END-PROGRAM
           END-IF.
           PERFORM LOOKUP-CUSTOMER.
           IF ACTIVE
               PERFORM DISPLAY-CUSTOMER
           ELSE
               IF INACTIVE
                   MOVE "Customer account is inactive" TO WS-RESPONSE-MESSAGE
               ELSE
                   IF SUSPENDED
                       MOVE "Customer account is suspended" TO WS-RESPONSE-MESSAGE
                   ELSE
                       MOVE "Customer not found" TO WS-RESPONSE-MESSAGE
                   END-IF
               END-IF
               DISPLAY WS-RESPONSE-MESSAGE
           END-IF.
           PERFORM CHECK-CREDIT-AVAILABLE.
       END-PROGRAM.
           STOP RUN.

       VALIDATE-CUST-ID.
           IF CUST-ID NOT NUMERIC
               MOVE "Error: Customer ID must be numeric" TO WS-RESPONSE-MESSAGE
               SET WS-HAS-ERROR TO TRUE
           ELSE
               IF CUST-ID = ZEROS
                   MOVE "Error: Customer ID cannot be zero" TO WS-RESPONSE-MESSAGE
                   SET WS-HAS-ERROR TO TRUE
               ELSE
                   SET WS-NO-ERROR TO TRUE
               END-IF
           END-IF.

       LOOKUP-CUSTOMER.
           * Simulated database lookup - in reality this would READ a file
           IF CUST-ID = 123456
               MOVE "JOHN DOE" TO CUST-NAME
               MOVE 12345.67 TO CUST-BALANCE
               MOVE "A" TO CUST-STATUS
               MOVE 50000.00 TO CUST-CREDIT-LIMIT
               MOVE 20200115 TO CUST-OPEN-DATE
               MOVE 20240115 TO CUST-LAST-TXN-DATE
           ELSE
               IF CUST-ID = 789012
                   MOVE "JANE SMITH" TO CUST-NAME
                   MOVE 5000.00 TO CUST-BALANCE
                   MOVE "I" TO CUST-STATUS
                   MOVE 10000.00 TO CUST-CREDIT-LIMIT
                   MOVE 20210620 TO CUST-OPEN-DATE
                   MOVE 20231101 TO CUST-LAST-TXN-DATE
               ELSE
                   MOVE "UNKNOWN" TO CUST-NAME
                   MOVE 0.00 TO CUST-BALANCE
                   MOVE " " TO CUST-STATUS
                   MOVE 0.00 TO CUST-CREDIT-LIMIT
                   MOVE 0 TO CUST-OPEN-DATE
                   MOVE 0 TO CUST-LAST-TXN-DATE
               END-IF
           END-IF.

       DISPLAY-CUSTOMER.
           DISPLAY " ".
           DISPLAY "Customer ID:    " CUST-ID.
           DISPLAY "Name:           " CUST-NAME.
           DISPLAY "Balance:        $" CUST-BALANCE.
           DISPLAY "Status:         " CUST-STATUS.
           DISPLAY "Credit Limit:   $" CUST-CREDIT-LIMIT.
           DISPLAY "Open Date:      " CUST-OPEN-DATE.
           DISPLAY "Last Txn Date:  " CUST-LAST-TXN-DATE.
           DISPLAY " ".

       CHECK-CREDIT-AVAILABLE.
           IF CUST-BALANCE < CUST-CREDIT-LIMIT
               COMPUTE WS-AVAILABLE = CUST-CREDIT-LIMIT - CUST-BALANCE
               DISPLAY "Available Credit: $" WS-AVAILABLE
           ELSE
               DISPLAY "Credit limit exceeded!"
           END-IF.

       PROCESS-TRANSACTION.
           DISPLAY "Enter Transaction Amount: ".
           ACCEPT TXN-AMOUNT.
           DISPLAY "Enter Transaction Type (D/C): ".
           ACCEPT TXN-TYPE.
           IF TXN-DEBIT
               IF TXN-AMOUNT > CUST-BALANCE
                   DISPLAY "Insufficient funds for debit"
               ELSE
                   SUBTRACT TXN-AMOUNT FROM CUST-BALANCE
                   DISPLAY "Debit processed. New balance: $" CUST-BALANCE
               END-IF
           ELSE
               IF TXN-CREDIT
                   ADD TXN-AMOUNT TO CUST-BALANCE
                   DISPLAY "Credit processed. New balance: $" CUST-BALANCE
               ELSE
                   DISPLAY "Invalid transaction type"
               END-IF
           END-IF.