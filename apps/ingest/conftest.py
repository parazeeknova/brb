"""Test env: layer .env.development < .env so integration tests see local infra.

Never overrides real environment (CI sets its own).
"""

from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_ROOT / ".env.development", override=False)
load_dotenv(_ROOT / ".env", override=False)
