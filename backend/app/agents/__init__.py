"""LangGraph multi-agent orchestration.

Phase 4: ``graph`` wires ``stack_agent`` -> {``api_contract_agent``,
``schema_agent``, ``security_agent``} in parallel -> ``synthesizer_agent``.
Agents coordinate deterministic engines; only the synthesizer calls Gemini.
"""
