import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, _, value = line.partition("=")
            if name.strip() not in _NEVER_IN_TESTS:
                os.environ.setdefault(name.strip(), value.strip())


# Tests must never spend real LLM credits: the key is not loaded, even if exported.
_NEVER_IN_TESTS = ("ANTHROPIC_API_KEY",)
_load_dotenv()
for _name in _NEVER_IN_TESTS:
    os.environ.pop(_name, None)
