import hashlib
import types

import flaccid.plugins.qobuz as qbz


def test_qobuz_sign_request_deterministic(monkeypatch):
    # Fix the timestamp for deterministic signature
    monkeypatch.setattr(qbz.time, "time", lambda: 1720000000)

    secret = "mysecret"
    endpoint = "track/getFileUrl"
    params = {
        "app_id": "123",
        "user_auth_token": "token",
        "track_id": "456",
        "format_id": 6,
        "intent": "stream",
    }

    ts, sig = qbz._sign_request(secret, endpoint, **params)
    assert ts == str(1720000000)

    # Recompute expected signature inline
    sorted_params = "".join(f"{k}{v}" for k, v in sorted(params.items()))
    base = f"{endpoint}{sorted_params}{ts}{secret}".encode("utf-8")
    assert sig == hashlib.md5(base).hexdigest()


def test_qobuz_generate_path_from_template():
    fields = {
        "albumartist": "An Artist",
        "album": "The Album",
        "date": "2021-01-01",
        "title": "A Song",
        "tracknumber": 1,
        "discnumber": 1,
        "disctotal": 2,
    }
    path = qbz._generate_path_from_template(fields, ".flac")
    # Expect directory with year in album folder and CD subdir since multi-disc
    assert path.startswith("An Artist/(2021) The Album/CD1/01. A Song")
