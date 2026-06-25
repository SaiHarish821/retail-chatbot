"""
Retail AI Assistant – Agents Re-exporter (Backwards Compatibility Wrapper)

This module preserves backwards compatibility with existing startup routers,
endpoints, and test tools that expect AgentRouter to be exported from agents.py.
All implementation logic has been refactored into:
  - prompts.py (system messages and prompts)
  - validation.py (sanitization and verification)
  - tools.py (database search algorithms and geocoding)
  - router.py (the core AgentRouter orchestration class)
"""

from .router import AgentRouter