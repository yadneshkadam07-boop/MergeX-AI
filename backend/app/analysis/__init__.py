"""The deterministic analysis engine.

``taxonomy`` defines every rule by stable ID. ``rules/`` holds one engine per
category. ``findings`` is the output type, ``scoring`` turns findings into a
health score, and ``engine`` runs the whole pipeline.

Nothing in this package calls a language model. A finding's existence,
severity, location and evidence are decided here; Phase 4 adds explanations
on top and can be absent entirely without changing any result.
"""
