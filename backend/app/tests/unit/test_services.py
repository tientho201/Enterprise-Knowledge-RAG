from app.core.security import create_access_token, decode_token, hash_password, verify_password


def test_password_hash_and_verify():
    password = "securepassword123"
    hashed = hash_password(password)
    assert hashed != password
    assert verify_password(password, hashed)
    assert not verify_password("wrongpassword", hashed)


def test_create_and_decode_token():
    user_id = "test-user-id"
    token = create_access_token(user_id)
    payload = decode_token(token)
    assert payload is not None
    assert payload["sub"] == user_id
    assert payload["type"] == "access"


def test_decode_invalid_token():
    payload = decode_token("invalid.token.here")
    assert payload is None


def test_decode_tampered_token():
    token = create_access_token("user-123")
    tampered = token[:-5] + "xxxxx"
    payload = decode_token(tampered)
    assert payload is None
