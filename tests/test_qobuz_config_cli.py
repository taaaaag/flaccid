from typer.testing import CliRunner

from flaccid.cli import app


def test_flaccid_qobuz_auto_auth_success(monkeypatch):
    runner = CliRunner()

    # Patch requests.post used by flaccid.commands.config
    import types

    from flaccid.commands import config as cfg

    class SimpleResp:
        def __init__(self, json_data=None, status_code=200):
            self._json = json_data or {}
            self.status_code = status_code

        def json(self):
            return self._json

        def raise_for_status(self):
            if self.status_code >= 400:
                raise Exception("HTTP error")

    def fake_post(url, data=None, timeout=None, headers=None):
        if url.endswith("/user/login"):
            return SimpleResp({"user_auth_token": "token-abc"})
        return SimpleResp()

    monkeypatch.setattr(cfg, "requests", types.SimpleNamespace(post=fake_post))

    # Provide all options to avoid interactive prompts
    res = runner.invoke(
        app,
        [
            "config",
            "auto-qobuz",
            "--email",
            "user@example.com",
            "--password",
            "secret",
            "--app-id",
            "798273057",
        ],
    )
    assert res.exit_code == 0, res.output
    assert "Qobuz authentication successful" in res.output
