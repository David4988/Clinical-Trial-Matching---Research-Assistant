import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.repository.json_repo import JsonRepository  # noqa: E402
from app.service import ScreeningService  # noqa: E402


@pytest.fixture
def repo(tmp_path):
    """A throwaway store so tests never touch the demo data file."""
    return JsonRepository(tmp_path / "store.json")


@pytest.fixture
def service(repo):
    return ScreeningService(repository=repo)


#: Real credentials in the repo-root `.env.local` are loaded by `app.main`
#: at import time (see `main.py`'s `load_dotenv`). Without this fixture the
#: obligation end-to-end tests, which approve a proposal on the EMAIL
#: channel, make `comms/factory.py` hand back a REAL `GmailProvider` and
#: perform a REAL Gmail API send on every `pytest` run — verified against
#: the live mailbox during the final verification pass.
#:
#: Tests that genuinely exercise a configured provider set their own fake
#: values with `monkeypatch.setenv` (see `test_comms_gmail.py`,
#: `test_obligations_channel_selection.py`); those run *after* this fixture
#: and are unaffected. Clearing here only removes the accidental use of real
#: credentials, and weakens no assertion.
_EXTERNAL_CREDENTIAL_ENV = (
    "GMAIL_CLIENT_ID",
    "GMAIL_CLIENT_SECRET",
    "GMAIL_REFRESH_TOKEN",
    "GMAIL_SENDER",
    "META_ACCESS_TOKEN",
    "WHATSAPP_PHONE_NUMBER_ID",
    "WHATSAPP_APP_SECRET",
    "WHATSAPP_VERIFY_TOKEN",
)


@pytest.fixture(autouse=True)
def _no_real_external_credentials(monkeypatch):
    """Keeps the suite hermetic: no test may reach a real external provider."""
    for name in _EXTERNAL_CREDENTIAL_ENV:
        monkeypatch.delenv(name, raising=False)
