*> Customer Record Copybook
      *> Shared between CUSTINQ and TRANSACTION programs
       01  CUSTOMER-RECORD.
           05  CUST-ID           PIC 9(6).
           05  CUST-NAME         PIC X(30).
           05  CUST-BALANCE      PIC 9(7)V99.
           05  CUST-STATUS       PIC X.
               88  ACTIVE        VALUE 'A'.
               88  INACTIVE      VALUE 'I'.
               88  SUSPENDED     VALUE 'S'.
           05  CUST-CREDIT-LIMIT PIC 9(7)V99.
           05  CUST-OPEN-DATE    PIC 9(8).
           05  CUST-LAST-TXN-DATE PIC 9(8).