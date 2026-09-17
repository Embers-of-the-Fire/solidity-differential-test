"""AI-in-the-loop differential bug hunter for solc vs solang.

Wraps the solidity-diff oracle in a generate -> run -> triage -> minimize
-> dedup loop driven by an OpenAI-compatible LLM endpoint.
"""

__version__ = "0.1.0"
