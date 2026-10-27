* TRANSACTION-REC.cpy - Transaction record with nested COPY
* Tests nested COPY resolution

       COPY CUSTOMER-REC REPLACING CUSTOMER-RECORD BY CUST-INFO
                                    VALIDATION-RESULT BY TRANS-VALIDATION.

       01  TRANSACTION-RECORD.
           05  TXN-ID             PIC 9(10).
           05  TXN-CUST-ID        PIC 9(6).
           05  TXN-AMOUNT         PIC 9(7)V99.
           05  TXN-TYPE           PIC X.
               88  TXN-DEBIT        VALUE 'D'.
               88  TXN-CREDIT       VALUE 'C'.
           05  TXN-DATE           PIC 9(8).
           05  TXN-DESC           PIC X(40).