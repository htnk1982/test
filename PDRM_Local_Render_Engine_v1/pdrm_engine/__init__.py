"""PDRM Local Render Engine v1 core.

The engine is intentionally conservative: musical preservation and output
validity outrank requested loudness. Round 9 remains hard-locked.
"""

__version__ = "1.0.0-mvp0"
CORE_API_VERSION = 1
MAX_ROUND_ALLOWED = 8
