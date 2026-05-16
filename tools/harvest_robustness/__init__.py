"""Harvest Robustness Harness — orchestrates ad-hoc analysis scripts for
basket-recycle (harvest-oriented) strategies and collates outputs into a
single report.

Parallels tools/robustness/ for normal strategies. The key design difference:
this is a THIN HARNESS over existing analysis scripts in tmp/, not a
rewrite. Each section of the report is produced by an external script
declared in sections.yaml. Add new modules by appending to sections.yaml
or dropping a Python module into this package and registering it.

Plug-in protocol — see README.md.
"""

__version__ = "1.0.0"
