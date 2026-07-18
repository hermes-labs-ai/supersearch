"""Tests for antidetect helpers (UA pool, header randomization, jitter, retry)."""

from unittest.mock import MagicMock, patch


from supersearch import antidetect


def test_user_agent_pool_has_at_least_20_entries():
    # The spec calls for 20+ real browser UAs.
    assert len(antidetect.USER_AGENTS) >= 20


def test_user_agent_pool_has_no_python_requests_strings():
    # `python-requests/X.X.X` instantly flags as automated. Pool must be clean.
    for ua in antidetect.USER_AGENTS:
        assert "python-requests" not in ua.lower()
        assert "curl/" not in ua.lower()


def test_random_user_agent_is_from_pool():
    for _ in range(20):
        ua = antidetect.random_user_agent()
        assert ua in antidetect.USER_AGENTS


def test_random_headers_includes_required_fields():
    h = antidetect.random_headers()
    for key in ("User-Agent", "Accept", "Accept-Language", "Accept-Encoding"):
        assert key in h
        assert h[key]


def test_random_headers_referer_optional():
    no_ref = antidetect.random_headers()
    assert "Referer" not in no_ref
    with_ref = antidetect.random_headers(referer="https://example.com")
    assert with_ref["Referer"] == "https://example.com"
    # Sec-Fetch-Site changes shape with referer
    assert with_ref["Sec-Fetch-Site"] == "cross-site"
    assert no_ref["Sec-Fetch-Site"] == "none"


def test_random_headers_actually_varies():
    # Across 50 calls we should see at least a couple of distinct UAs.
    uas = {antidetect.random_headers()["User-Agent"] for _ in range(50)}
    assert len(uas) >= 3


def test_jitter_sleeps_within_window(monkeypatch):
    slept = []
    monkeypatch.setattr(antidetect.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(antidetect.random, "uniform", lambda a, b: (a + b) / 2)
    antidetect.jitter(0.5, 1.5)
    assert slept == [1.0]


def test_jitter_zero_window_is_noop(monkeypatch):
    # Both <= 0 should not call sleep at all
    called = []
    monkeypatch.setattr(antidetect.time, "sleep", lambda s: called.append(s))
    antidetect.jitter(0.0, 0.0)
    assert called == []


def test_jitter_negative_min_clamped(monkeypatch):
    # Negative lower bound must be clamped to 0
    slept = []
    monkeypatch.setattr(antidetect.time, "sleep", lambda s: slept.append(s))
    captured = {}

    def fake_uniform(a, b):
        captured["lo"] = a
        captured["hi"] = b
        return a
    monkeypatch.setattr(antidetect.random, "uniform", fake_uniform)
    antidetect.jitter(-1.0, 0.5)
    assert captured["lo"] == 0.0
    assert captured["hi"] == 0.5


# --- request_with_retry --------------------------------------------------

def _resp(status: int = 200):
    r = MagicMock(status_code=status)
    r.raise_for_status = MagicMock()
    return r


def test_request_with_retry_returns_first_response_on_200(monkeypatch):
    monkeypatch.setattr(antidetect, "jitter", lambda *a, **kw: None)
    with patch("requests.request", return_value=_resp(200)) as mock_req:
        out = antidetect.request_with_retry("https://x/y", timeout=1)
    assert out.status_code == 200
    assert mock_req.call_count == 1


def test_request_with_retry_retries_on_throttle(monkeypatch):
    # First response is 429 (throttled), second is 200
    monkeypatch.setattr(antidetect, "jitter", lambda *a, **kw: None)
    responses = [_resp(429), _resp(200)]
    with patch("requests.request", side_effect=responses) as mock_req:
        out = antidetect.request_with_retry("https://x/y", timeout=1)
    assert out.status_code == 200
    assert mock_req.call_count == 2


def test_request_with_retry_rotates_ua_on_retry(monkeypatch):
    monkeypatch.setattr(antidetect, "jitter", lambda *a, **kw: None)
    captured_uas: list[str] = []

    def fake_request(method, url, **kwargs):
        captured_uas.append(kwargs["headers"]["User-Agent"])
        # first 403, then 200
        if len(captured_uas) == 1:
            return _resp(403)
        return _resp(200)

    # Force the UA pool to alternate so retry uses a different UA.
    ua_cycle = iter(["UA-ONE", "UA-TWO", "UA-THREE"])
    monkeypatch.setattr(antidetect, "random_user_agent", lambda: next(ua_cycle))

    with patch("requests.request", side_effect=fake_request):
        antidetect.request_with_retry("https://x/y", timeout=1)

    assert captured_uas[0] != captured_uas[1]


def test_request_with_retry_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(antidetect, "jitter", lambda *a, **kw: None)
    with patch("requests.request", return_value=_resp(503)) as mock_req:
        out = antidetect.request_with_retry("https://x/y", timeout=1, max_retries=1)
    # 1 initial + 1 retry = 2 calls; final status still 503 (caller decides)
    assert mock_req.call_count == 2
    assert out.status_code == 503


def test_throttle_status_set_includes_common_codes():
    assert 429 in antidetect.THROTTLE_STATUS
    assert 403 in antidetect.THROTTLE_STATUS
    assert 503 in antidetect.THROTTLE_STATUS
    assert 200 not in antidetect.THROTTLE_STATUS
    assert 404 not in antidetect.THROTTLE_STATUS
