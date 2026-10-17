"""Machine keys are stored as SHA-256 and checked in constant time; argon2 still verifies."""

from argon2 import PasswordHasher

from agentfox.platform.identity.keyhash import check_key, hash_key

RAW = "nom_api_" + "A" * 40


def test_round_trip_and_mismatch():
    stored = hash_key(RAW)
    assert stored.startswith("sha256$") and RAW not in stored
    assert check_key(stored, RAW) == (True, None)
    assert check_key(stored, RAW + "x") == (False, None)


def test_a_legacy_argon2_hash_verifies_and_upgrades():
    legacy = PasswordHasher().hash(RAW)
    assert check_key(legacy, RAW) == (True, hash_key(RAW))
    assert check_key(legacy, "nope") == (False, None)
    assert check_key("garbage", RAW) == (False, None)
