# IQ Lab
Research harness for IQ Option PRACTICE trading. Python package `iqlab/`, MCP server
`iq-lab` (`.mcp.json`), trading loop skill `.claude/skills/iq-trader`.
- Tests: `python -m pytest -q tests`
- Never place trades on a REAL balance. Never change strategy params without a
  proposal approved by the user (`python -m iqlab rules approve <v>`).
