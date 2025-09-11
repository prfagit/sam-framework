import os
from sam.utils.rate_limiter import RateLimiter


def test_rate_limiter_env_overrides(monkeypatch):
    monkeypatch.setenv("SAM_RL_MAX_KEYS", "1234")
    monkeypatch.setenv("SAM_RL_CLEANUP_INTERVAL", "7")

    rl = RateLimiter()
    assert rl.max_keys == 1234
    assert rl.cleanup_interval == 7

