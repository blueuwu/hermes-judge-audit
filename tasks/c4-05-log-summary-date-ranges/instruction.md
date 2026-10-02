You are given multiple log files stored in /app/logs. Each log file name follows the
pattern YYYY-MM-DD_<source>.log (e.g., 2025-08-10_db.log), indicating the date of the logs
and their source. Each log line contains an event with a severity level. Analyze all logs
and count how many times each severity appears within the following date ranges: today
(the current date), the last 7 days (including today), the last 30 days (including
today), the current month to date (from the 1st of the current month up to and including
today), and the total over all log files regardless of date.

The severity levels to count are exactly ERROR, WARNING and INFO. Write /app/summary.csv
with the header period,severity,count followed by one row per period and severity, in
this order: periods today, last_7_days, last_30_days, month_to_date, total; within each,
ERROR, WARNING, INFO. The current date is 2025-08-12; use it as the reference date for all
calculations. `python3 /app/check_summary.py` checks the layout.
