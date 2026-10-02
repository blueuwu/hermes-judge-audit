In /app, rename billing.totals.calc_total to compute_total. Update every use of it in the
code, tests and docs/API.md. Keep calc_total importable from billing.totals as a deprecated
alias that emits a DeprecationWarning and returns the same result. Add an entry for the
rename under "Unreleased" in CHANGELOG.md. `python3 -m unittest discover -s tests` must
still pass.
