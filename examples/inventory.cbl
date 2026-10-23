IDENTIFICATION DIVISION.
       PROGRAM-ID. INVMGT.

       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SOURCE-COMPUTER. IBM-ZOS.
       OBJECT-COMPUTER. IBM-ZOS.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  PRODUCT-RECORD.
           05  PROD-ID           PIC 9(8).
           05  PROD-NAME         PIC X(40).
           05  PROD-CATEGORY     PIC X(20).
           05  PROD-PRICE        PIC 9(6)V99.
           05  PROD-QTY-ON-HAND  PIC 9(6).
           05  PROD-QTY-ALLOCATED PIC 9(6).
           05  PROD-REORDER-LEVEL PIC 9(5).
           05  PROD-STATUS       PIC X.
               88  ACTIVE        VALUE 'A'.
               88  DISCONTINUED  VALUE 'D'.
               88  BACKORDER     VALUE 'B'.
           05  PROD-LAST-RESTOCK  PIC 9(8).

       01  ORDER-RECORD.
           05  ORDER-ID          PIC 9(10).
           05  ORDER-PROD-ID     PIC 9(8).
           05  ORDER-QTY         PIC 9(5).
           05  ORDER-TYPE        PIC X.
               88  ORDER-SALE    VALUE 'S'.
               88  ORDER-RETURN  VALUE 'R'.
               88  ORDER-RECV    VALUE 'C'.
           05  ORDER-DATE        PIC 9(8).
           05  ORDER-CUST-ID     PIC 9(6).

       01  WS-RESPONSE-MESSAGE  PIC X(80).
       01  WS-ERROR-FLAG        PIC X.
           88  WS-NO-ERROR      VALUE 'N'.
           88  WS-HAS-ERROR     VALUE 'Y'.
       01  WS-AVAILABLE-QTY     PIC 9(6).

       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "=== INVENTORY MANAGEMENT SYSTEM ===".
           DISPLAY "Enter Product ID (8 digits): ".
           ACCEPT PROD-ID.
           PERFORM VALIDATE-PROD-ID.
           IF WS-HAS-ERROR
               DISPLAY WS-RESPONSE-MESSAGE
               GO TO END-PROGRAM
           END-IF.
           PERFORM LOOKUP-PRODUCT.
           IF ACTIVE
               PERFORM DISPLAY-PRODUCT
               PERFORM CHECK-REORDER-NEEDED
           ELSE
               IF DISCONTINUED
                   MOVE "Product is discontinued" TO WS-RESPONSE-MESSAGE
               ELSE
                   IF BACKORDER
                       MOVE "Product is on backorder" TO WS-RESPONSE-MESSAGE
                   ELSE
                       MOVE "Product not found" TO WS-RESPONSE-MESSAGE
                   END-IF
               END-IF
               DISPLAY WS-RESPONSE-MESSAGE
           END-IF.
           STOP RUN.

       END-PROGRAM.

       VALIDATE-PROD-ID.
           IF PROD-ID NOT NUMERIC
               MOVE "Error: Product ID must be numeric" TO WS-RESPONSE-MESSAGE
               SET WS-HAS-ERROR TO TRUE
           ELSE
               IF PROD-ID = ZEROS
                   MOVE "Error: Product ID cannot be zero" TO WS-RESPONSE-MESSAGE
                   SET WS-HAS-ERROR TO TRUE
               ELSE
                   SET WS-NO-ERROR TO TRUE
               END-IF
           END-IF.

       LOOKUP-PRODUCT.
           * Simulated database lookup
           IF PROD-ID = 10000001
               MOVE "WIRELESS MOUSE" TO PROD-NAME
               MOVE "ELECTRONICS" TO PROD-CATEGORY
               MOVE 2999 TO PROD-PRICE
               MOVE 150 TO PROD-QTY-ON-HAND
               MOVE 10 TO PROD-QTY-ALLOCATED
               MOVE 20 TO PROD-REORDER-LEVEL
               MOVE "A" TO PROD-STATUS
               MOVE 20240115 TO PROD-LAST-RESTOCK
           ELSE
               IF PROD-ID = 10000002
                   MOVE "MECHANICAL KEYBOARD" TO PROD-NAME
                   MOVE "ELECTRONICS" TO PROD-CATEGORY
                   MOVE 12999 TO PROD-PRICE
                   MOVE 5 TO PROD-QTY-ON-HAND
                   MOVE 0 TO PROD-QTY-ALLOCATED
                   MOVE 10 TO PROD-REORDER-LEVEL
                   MOVE "B" TO PROD-STATUS
                   MOVE 20231201 TO PROD-LAST-RESTOCK
               ELSE
                   MOVE "UNKNOWN" TO PROD-NAME
                   MOVE " " TO PROD-CATEGORY
                   MOVE 0 TO PROD-PRICE
                   MOVE 0 TO PROD-QTY-ON-HAND
                   MOVE 0 TO PROD-QTY-ALLOCATED
                   MOVE 0 TO PROD-REORDER-LEVEL
                   MOVE " " TO PROD-STATUS
                   MOVE 0 TO PROD-LAST-RESTOCK
               END-IF
           END-IF.

       DISPLAY-PRODUCT.
           DISPLAY " ".
           DISPLAY "Product ID:      " PROD-ID.
           DISPLAY "Name:            " PROD-NAME.
           DISPLAY "Category:        " PROD-CATEGORY.
           DISPLAY "Price:           $" PROD-PRICE.
           DISPLAY "Qty On Hand:     " PROD-QTY-ON-HAND.
           DISPLAY "Qty Allocated:   " PROD-QTY-ALLOCATED.
           DISPLAY "Reorder Level:   " PROD-REORDER-LEVEL.
           DISPLAY "Status:          " PROD-STATUS.
           DISPLAY "Last Restock:    " PROD-LAST-RESTOCK.
           DISPLAY " ".

       CHECK-REORDER-NEEDED.
           COMPUTE WS-AVAILABLE-QTY = PROD-QTY-ON-HAND - PROD-QTY-ALLOCATED.
           IF WS-AVAILABLE-QTY < PROD-REORDER-LEVEL
               DISPLAY "REORDER ALERT: Available qty " WS-AVAILABLE-QTY " below reorder level " PROD-REORDER-LEVEL
           ELSE
               DISPLAY "Stock OK: Available qty " WS-AVAILABLE-QTY
           END-IF.

       PROCESS-ORDER.
           DISPLAY "Enter Order Product ID: ".
           ACCEPT ORDER-PROD-ID.
           DISPLAY "Enter Order Quantity: ".
           ACCEPT ORDER-QTY.
           DISPLAY "Enter Order Type (S=Sale, R=Return, C=Receive): ".
           ACCEPT ORDER-TYPE.
           PERFORM VALIDATE-ORDER.
           IF WS-HAS-ERROR
               DISPLAY WS-RESPONSE-MESSAGE
               GO TO END-PROCESS
           END-IF.
           PERFORM LOOKUP-PRODUCT-FOR-ORDER.
           IF ORDER-SALE
               IF ORDER-QTY > WS-AVAILABLE-QTY
                   MOVE "Insufficient stock for sale" TO WS-RESPONSE-MESSAGE
                   SET WS-HAS-ERROR TO TRUE
               ELSE
                   SUBTRACT ORDER-QTY FROM PROD-QTY-ON-HAND
                   MOVE "Sale processed. New qty: " PROD-QTY-ON-HAND TO WS-RESPONSE-MESSAGE
               END-IF
           ELSE
               IF ORDER-RETURN
                   ADD ORDER-QTY TO PROD-QTY-ON-HAND
                   MOVE "Return processed. New qty: " PROD-QTY-ON-HAND TO WS-RESPONSE-MESSAGE
               ELSE
                   IF ORDER-RECV
                       ADD ORDER-QTY TO PROD-QTY-ON-HAND
                       MOVE "Receipt processed. New qty: " PROD-QTY-ON-HAND TO WS-RESPONSE-MESSAGE
                   ELSE
                       MOVE "Invalid order type" TO WS-RESPONSE-MESSAGE
                       SET WS-HAS-ERROR TO TRUE
                   END-IF
               END-IF
           END-IF.
           DISPLAY WS-RESPONSE-MESSAGE.
       END-PROCESS.

       VALIDATE-ORDER.
           IF ORDER-QTY NOT NUMERIC OR ORDER-QTY = ZEROS
               MOVE "Error: Order quantity must be positive" TO WS-RESPONSE-MESSAGE
               SET WS-HAS-ERROR TO TRUE
           ELSE
               SET WS-NO-ERROR TO TRUE
           END-IF.

       LOOKUP-PRODUCT-FOR-ORDER.
           * Same logic as LOOKUP-PRODUCT but for order processing
           IF ORDER-PROD-ID = 10000001
               MOVE "WIRELESS MOUSE" TO PROD-NAME
               MOVE "ELECTRONICS" TO PROD-CATEGORY
               MOVE 2999 TO PROD-PRICE
               MOVE 150 TO PROD-QTY-ON-HAND
               MOVE 10 TO PROD-QTY-ALLOCATED
               MOVE 20 TO PROD-REORDER-LEVEL
               MOVE "A" TO PROD-STATUS
               MOVE 20240115 TO PROD-LAST-RESTOCK
           ELSE
               IF ORDER-PROD-ID = 10000002
                   MOVE "MECHANICAL KEYBOARD" TO PROD-NAME
                   MOVE "ELECTRONICS" TO PROD-CATEGORY
                   MOVE 12999 TO PROD-PRICE
                   MOVE 5 TO PROD-QTY-ON-HAND
                   MOVE 0 TO PROD-QTY-ALLOCATED
                   MOVE 10 TO PROD-REORDER-LEVEL
                   MOVE "B" TO PROD-STATUS
                   MOVE 20231201 TO PROD-LAST-RESTOCK
               ELSE
                   MOVE "UNKNOWN" TO PROD-NAME
                   MOVE " " TO PROD-CATEGORY
                   MOVE 0 TO PROD-PRICE
                   MOVE 0 TO PROD-QTY-ON-HAND
                   MOVE 0 TO PROD-QTY-ALLOCATED
                   MOVE 0 TO PROD-REORDER-LEVEL
                   MOVE " " TO PROD-STATUS
                   MOVE 0 TO PROD-LAST-RESTOCK
               END-IF
           END-IF.