* CUSTOMER-REC.cpy - Shared customer record definition
       * Copybook for customer data structures

       01  CUSTOMER-RECORD.
           05  CUST-ID            PIC 9(6).
           05  CUST-NAME          PIC X(30).
           05  CUST-BALANCE       PIC 9(7)V99.
           05  CUST-STATUS        PIC X.
               88  CUST-ACTIVE      VALUE 'A'.
               88  CUST-INACTIVE    VALUE 'I'.
               88  CUST-SUSPENDED   VALUE 'S'.
           05  CUST-CREDIT-LIMIT  PIC 9(7)V99.
           05  CUST-OPEN-DATE     PIC 9(8).
           05  CUST-LAST-TXN-DATE PIC 9(8).

       01  VALIDATION-RESULT.
           05  VALID-FLAG         PIC X.
               88  VALID-OK         VALUE 'Y'.
               88  VALID-ERROR      VALUE 'N'.
           05  ERROR-MSG          PIC X(80).
           05  ERROR-CODE         PIC 9(3).