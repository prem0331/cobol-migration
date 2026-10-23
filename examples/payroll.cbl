IDENTIFICATION DIVISION.
       PROGRAM-ID. PAYROLL.

       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SOURCE-COMPUTER. IBM-ZOS.
       OBJECT-COMPUTER. IBM-ZOS.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  EMPLOYEE-RECORD.
           05  EMP-ID           PIC 9(6).
           05  EMP-NAME         PIC X(30).
           05  EMP-DEPT         PIC X(20).
           05  EMP-PAY-GRADE    PIC X.
               88  GRADE-A      VALUE 'A'.
               88  GRADE-B      VALUE 'B'.
               88  GRADE-C      VALUE 'C'.
           05  EMP-BASE-SALARY  PIC 9(7)V99.
           05  EMP-HIRE-DATE    PIC 9(8).
           05  EMP-STATUS       PIC X.
               88  EMP-ACTIVE   VALUE 'A'.
               88  EMP-TERM     VALUE 'T'.
               88  EMP-LOA      VALUE 'L'.

       01  PAYROLL-RECORD.
           05  PAY-EMP-ID       PIC 9(6).
           05  PAY-PERIOD       PIC 9(6).       *> YYYYMM
           05  PAY-GROSS        PIC 9(7)V99.
           05  PAY-TAX          PIC 9(7)V99.
           05  PAY-NET          PIC 9(7)V99.
           05  PAY-TYPE         PIC X.
               88  REGULAR      VALUE 'R'.
               88  OVERTIME     VALUE 'O'.
               88  BONUS        VALUE 'B'.
           05  PAY-HOURS        PIC 9(4)V99.
           05  PAY-RATE         PIC 9(5)V99.

       01  WS-RESPONSE-MSG    PIC X(80).
       01  WS-ERROR-FLAG      PIC X.
           88  WS-NO-ERR       VALUE 'N'.
           88  WS-HAS-ERR      VALUE 'Y'.
       01  WS-TAX-RATE        PIC 9V99.
       01  WS-OVERTIME-RATE   PIC 9V99.

       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "=== PAYROLL PROCESSING SYSTEM ===".
           DISPLAY "Enter Employee ID (6 digits): ".
           ACCEPT EMP-ID.
           PERFORM VALIDATE-EMP-ID.
           IF WS-HAS-ERR
               DISPLAY WS-RESPONSE-MSG
               GO TO END-PROGRAM
           END-IF.
           PERFORM LOOKUP-EMPLOYEE.
           IF EMP-ACTIVE
               DISPLAY "Employee: " EMP-NAME " Dept: " EMP-DEPT
               DISPLAY "Pay Grade: " EMP-PAY-GRADE " Base Salary: " EMP-BASE-SALARY
               PERFORM CALCULATE-PAYROLL
               DISPLAY "Gross Pay: " PAY-GROSS " Tax: " PAY-TAX " Net Pay: " PAY-NET
           ELSE
               IF EMP-TERM
                   MOVE "Employee terminated - payroll not processed" TO WS-RESPONSE-MSG
               ELSE
                   IF EMP-LOA
                       MOVE "Employee on leave - payroll suspended" TO WS-RESPONSE-MSG
                   ELSE
                       MOVE "Employee not active" TO WS-RESPONSE-MSG
                   END-IF
               END-IF
               DISPLAY WS-RESPONSE-MSG
           END-IF.
           STOP RUN.

       END-PROGRAM.

       VALIDATE-EMP-ID.
           IF EMP-ID NOT NUMERIC
               MOVE "Error: Employee ID must be numeric" TO WS-RESPONSE-MSG
               SET WS-HAS-ERR TO TRUE
           ELSE
               IF EMP-ID = ZEROS
                   MOVE "Error: Employee ID cannot be zero" TO WS-RESPONSE-MSG
                   SET WS-HAS-ERR TO TRUE
               ELSE
                   SET WS-NO-ERR TO TRUE
               END-IF
           END-IF.

       LOOKUP-EMPLOYEE.
           * Simulated database lookup based on employee ID
           IF EMP-ID = 100001
               MOVE "JOHN ANDERSON" TO EMP-NAME
               MOVE "ENGINEERING" TO EMP-DEPT
               MOVE "A" TO EMP-PAY-GRADE
               MOVE 125000.00 TO EMP-BASE-SALARY
               MOVE 20200115 TO EMP-HIRE-DATE
               MOVE "A" TO EMP-STATUS
           ELSE
               IF EMP-ID = 100002
                   MOVE "MARY CHEN" TO EMP-NAME
                   MOVE "MARKETING" TO EMP-DEPT
                   MOVE "B" TO EMP-PAY-GRADE
                   MOVE 85000.00 TO EMP-BASE-SALARY
                   MOVE 20210322 TO EMP-HIRE-DATE
                   MOVE "A" TO EMP-STATUS
               ELSE
                   IF EMP-ID = 100003
                       MOVE "ROBERT KIM" TO EMP-NAME
                       MOVE "SALES" TO EMP-DEPT
                       MOVE "C" TO EMP-PAY-GRADE
                       MOVE 65000.00 TO EMP-BASE-SALARY
                       MOVE 20220710 TO EMP-HIRE-DATE
                       MOVE "T" TO EMP-STATUS
                   ELSE
                       MOVE "UNKNOWN" TO EMP-NAME
                       MOVE " " TO EMP-DEPT
                       MOVE " " TO EMP-PAY-GRADE
                       MOVE 0 TO EMP-BASE-SALARY
                       MOVE 0 TO EMP-HIRE-DATE
                       MOVE " " TO EMP-STATUS
                   END-IF
               END-IF
           END-IF.

       CALCULATE-PAYROLL.
           MOVE EMP-BASE-SALARY TO PAY-GROSS.
           MOVE PAY-EMP-ID TO EMP-ID.
           MOVE 202412 TO PAY-PERIOD.

           * Determine tax rate by pay grade
           IF GRADE-A
               MOVE 0.32 TO WS-TAX-RATE
           ELSE
               IF GRADE-B
                   MOVE 0.24 TO WS-TAX-RATE
               ELSE
                   IF GRADE-C
                       MOVE 0.18 TO WS-TAX-RATE
                   ELSE
                       MOVE 0.20 TO WS-TAX-RATE
                   END-IF
               END-IF
           END-IF.

           COMPUTE PAY-TAX = PAY-GROSS * WS-TAX-RATE.
           COMPUTE PAY-NET = PAY-GROSS - PAY-TAX.

           * Overtime calculation for hourly (Grade C)
           IF GRADE-C
               MOVE 1.5 TO WS-OVERTIME-RATE
               COMPUTE PAY-GROSS = PAY-GROSS + (PAY-HOURS * PAY-RATE * WS-OVERTIME-RATE)
               COMPUTE PAY-TAX = PAY-GROSS * WS-TAX-RATE
               COMPUTE PAY-NET = PAY-GROSS - PAY-TAX
               MOVE 'O' TO PAY-TYPE
           ELSE
               MOVE 'R' TO PAY-TYPE
           END-IF.

           * Bonus for long-tenure employees (5+ years)
           IF (202412 - EMP-HIRE-DATE) > 50000
               COMPUTE PAY-GROSS = PAY-GROSS * 1.10
               COMPUTE PAY-TAX = PAY-GROSS * WS-TAX-RATE
               COMPUTE PAY-NET = PAY-GROSS - PAY-TAX
               MOVE 'B' TO PAY-TYPE
           END-IF.

       PROCESS-PAYROLL-RUN.
           DISPLAY "Enter Pay Period (YYYYMM): ".
           ACCEPT PAY-PERIOD.
           DISPLAY "Enter Pay Type (R=Regular, O=Overtime, B=Bonus): ".
           ACCEPT PAY-TYPE.
           DISPLAY "Enter Hours (if overtime): ".
           ACCEPT PAY-HOURS.
           DISPLAY "Enter Rate (if overtime): ".
           ACCEPT PAY-RATE.
           PERFORM VALIDATE-PAYROLL-INPUT.
           IF WS-HAS-ERR
               DISPLAY WS-RESPONSE-MSG
               GO TO END-PROCESS
           END-IF.
           PERFORM LOOKUP-EMPLOYEE.
           IF NOT EMP-ACTIVE
               MOVE "Cannot process payroll for inactive employee" TO WS-RESPONSE-MSG
               SET WS-HAS-ERR TO TRUE
           ELSE
               PERFORM CALCULATE-PAYROLL
               MOVE "Payroll processed successfully" TO WS-RESPONSE-MSG
           END-IF.
           DISPLAY WS-RESPONSE-MSG.
       END-PROCESS.

       VALIDATE-PAYROLL-INPUT.
           IF PAY-PERIOD NOT NUMERIC OR PAY-PERIOD = ZEROS
               MOVE "Error: Pay period must be valid YYYYMM" TO WS-RESPONSE-MSG
               SET WS-HAS-ERR TO TRUE
           ELSE
               IF PAY-HOURS NOT NUMERIC OR PAY-HOURS < 0
                   MOVE "Error: Hours must be non-negative" TO WS-RESPONSE-MSG
                   SET WS-HAS-ERR TO TRUE
               ELSE
                   SET WS-NO-ERR TO TRUE
               END-IF
           END-IF.