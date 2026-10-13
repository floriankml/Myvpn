import pytest

from dvpn.config import Settings
from dvpn.ratelimit import RateLimiter
from dvpn.security import generate_password, generate_psk, is_valid_wg_key


def test_rate_limiter_window():
    rl = RateLimiter(2, 10)
    assert rl.hit("a", 0) and rl.hit("a", 1)
    assert not rl.hit("a", 2)
    assert rl.hit("b", 2)
    assert rl.hit("a", 10.5)  # Fenster abgelaufen


def test_rate_limiter_memory_bound():
    rl = RateLimiter(1, 10, max_keys=10)
    for i in range(100):
        rl.hit(str(i), 0)
    assert len(rl._hits) <= 10


def test_psk_and_password_generation():
    assert is_valid_wg_key(generate_psk())
    assert len({generate_psk() for _ in range(50)}) == 50
    pw = generate_password()
    assert len(pw) == 23 and pw.count("-") == 3


@pytest.mark.parametrize("kwargs", [
    {"subnet_v4": "8.8.8.0/24"},
    {"subnet_v4": "10.8.0.0/30"},
    {"subnet_v4": "10.8.0.1/24"},
    {"subnet_v6": "10.8.0.0/24"},
    {"ipv6_egress": True, "subnet_v6": ""},
])
def test_invalid_settings(kwargs):
    with pytest.raises(ValueError):
        Settings(**kwargs)


def test_ipv6_ula_derivation():
    s = Settings(subnet_v6="fd12:3456:789a::/64")
    assert str(s.server_v6) == "fd12:3456:789a::1"
    assert s.dns_servers == ["10.8.0.1", "fd12:3456:789a::1"]
