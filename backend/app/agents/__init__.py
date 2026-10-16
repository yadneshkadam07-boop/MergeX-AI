"""LangGraph multi-agent orchestration.

``graph`` wires stack detection into three rule groups that run in parallel,
then joins them at the synthesiser. ``state`` is the shared state object and
its reducers.

Only the synthesiser touches a language model, and only to attach prose to
findings that already exist. Every other node is deterministic.
"""
