"""Tests for the crunchbase_lite funding scraper.

Regression guard: the subprocess call must not be pinned to any hardcoded
checkout path and must use the current interpreter, so it works for any user,
install location, and working directory.
"""

import sys
from unittest.mock import MagicMock, patch

from supersearch.scrapers import crunchbase_lite


def test_fetch_funding_uses_current_interpreter_and_no_hardcoded_cwd(tmp_path, monkeypatch):
    # Run from a directory that is NOT the canonical checkout.
    monkeypatch.chdir(tmp_path)

    fake = MagicMock()
    fake.stdout = "Acme raised $12 million Series B; valuation $80 million; 250 employees"
    with patch.object(crunchbase_lite.subprocess, "run", return_value=fake) as run:
        out = crunchbase_lite.fetch_funding("Acme")

    args, kwargs = run.call_args
    cmd = args[0]
    # Same interpreter/env — not a bare "python3".
    assert cmd[0] == sys.executable
    assert cmd[1:3] == ["-m", "supersearch"]
    # No hardcoded cwd override; inherits the caller's directory.
    assert "cwd" not in kwargs
    # The query arg carries no absolute path — only the company + keywords.
    assert cmd[3].startswith("Acme ")

    # Parsing still works end-to-end on the mocked output.
    assert out["company"] == "Acme"
    assert out["valuation"] == "$80.0M"
    assert out["employees"] == 250
    assert "Series B" in out["funding_rounds"]


def test_fetch_funding_returns_empty_shell_on_subprocess_error():
    with patch.object(crunchbase_lite.subprocess, "run", side_effect=OSError("boom")):
        out = crunchbase_lite.fetch_funding("Acme")
    assert out["company"] == "Acme"
    assert out["funding_rounds"] == []
    assert out["valuation"] is None
