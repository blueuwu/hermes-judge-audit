You are given a COBOL program located at /app/src/program.cbl. This program reads input
data from /app/src/INPUT.DAT and modifies one or more .DAT files located in the /app/data/
directory. The COBOL program is designed to be run from the /app/ directory and should be
compiled and executed using GnuCOBOL 3 (installed as cobc).

Re-implement the functionality of program.cbl in Python as /app/program.py, which must
perform exactly the same operations: read the input from /app/src/INPUT.DAT and apply the
same logic to the .DAT files in /app/data/, so that the files it produces are identical to
those the COBOL program produces from the same input and initial files.
`python3 /app/check_example.py` checks one worked example.
