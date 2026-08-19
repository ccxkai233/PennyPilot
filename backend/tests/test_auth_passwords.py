from app.auth import hash_password, verify_password


def test_password_hash_round_trip():
    password = "correct horse battery staple"
    hashed = hash_password(password)

    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("wrong password", hashed) is False
