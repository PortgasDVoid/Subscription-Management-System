import pytest
from app.auth import (password_problems, hash_password, verify_password, make_token, decode_token, normalise_email, new_reset_token, hash_token)


@pytest.mark.parametrize("pw,ok", [("Abcdefg1!", True), ("Abcdefgh!", True), ("Abcdefg!", False),   # exactly 8 chars is rejected
                                   ("abcdefghi!", False), ("ABCDEFGHI!", False), ("Abcdefghi1", False), ("", False)])
def test_password_policy(pw, ok):
    assert (password_problems(pw) == []) is ok


def test_hash_round_trip_and_wrong_password():
    h = hash_password("Str0ng!Passw0rd")
    assert verify_password("Str0ng!Passw0rd", h) and not verify_password("wrong", h)


def test_legacy_scrypt_hash_still_verifies():
    import hashlib, os
    salt = os.urandom(16)
    stored = "scrypt$" + salt.hex() + "$" + hashlib.scrypt(b"Pass!word1", salt=salt, n=2**14, r=8, p=1).hex()
    assert verify_password("Pass!word1", stored)


def test_token_round_trip_and_tamper():
    t = make_token(7, "staff")
    assert decode_token(t)["sub"] == 7
    head, body, sig = t.split(".")
    assert decode_token(f"{head}.{body}x.{sig}") is None
    assert decode_token(make_token(1, "admin", ttl=-5)) is None
    assert decode_token("garbage") is None


def test_email_normalised_and_validated():
    assert normalise_email("  Jo@Example.COM ") == "jo@example.com"
    with pytest.raises(ValueError): normalise_email("nope")


def test_reset_token_stored_hashed():
    raw, hashed = new_reset_token()
    assert raw != hashed and hash_token(raw) == hashed
