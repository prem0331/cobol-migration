*> Product Record Copybook
      *> Shared between INVMGT and ORDER programs
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