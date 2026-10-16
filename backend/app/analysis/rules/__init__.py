"""Deterministic rule engines, one module per category.

Each module exposes a ``run_*_rules`` function taking the extracted facts and
returning :class:`app.analysis.findings.Finding` objects. No module here calls
a language model: a finding's existence never depends on one.
"""
