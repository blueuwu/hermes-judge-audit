In /app, switch app/serialize.py from the standard json module to fastjsonx 3.x (its
dumps is a drop-in replacement). Install it from the offline wheelhouse with
`pip install --no-index --find-links /opt/wheelhouse fastjsonx` and pin the installed
version in requirements.txt. `python3 -m unittest discover -s tests` must still pass.
