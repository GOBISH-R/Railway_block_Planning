"""Ingestion from maintenance-management systems (TMS / SMMS / TDMS).

Nothing here is imported by blockplan_service or blockplan_api unless
BLOCKPLAN_DATA_SOURCE asks for a feed. The frozen CSVs remain the default.

`contract.py` defines what THIS system accepts. It is not a reproduction of any
real system's schema -- see its docstring before describing it as one.
"""
