"""The operations CLI must at least load and run its offline commands (it is not imported by the app itself)."""
import base64
import sys

from app import cli


def test_vapid_keys_prints_a_usable_pair(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["app.cli", "vapid-keys"])
    cli.main()
    lines = dict(line.split("=", 1) for line in capsys.readouterr().out.strip().splitlines())
    pad = lambda v: v + "=" * (-len(v) % 4)  # noqa: E731
    assert len(base64.urlsafe_b64decode(pad(lines["VAPID_PUBLIC_KEY"]))) == 65   # uncompressed P-256 point
    assert len(base64.urlsafe_b64decode(pad(lines["VAPID_PRIVATE_KEY"]))) == 32
