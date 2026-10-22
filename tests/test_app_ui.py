from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

import agent


@pytest.mark.parametrize("channel", [None, "", "stable", "false", "canary", " Canary "])
def test_canary_identification_is_opt_in(monkeypatch, channel):
    if channel is None:
        monkeypatch.delenv("APP_RELEASE_CHANNEL", raising=False)
    else:
        monkeypatch.setenv("APP_RELEASE_CHANNEL", channel)
    monkeypatch.setattr(agent, "get_cliente", Mock())
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run()
    assert not app.exception
    assert app.title[0].value == "🤖 Agente base"
    markup = "\n".join(item.value for item in app.markdown)
    if channel and channel.strip().lower() == "canary":
        assert "Canary" in markup
        assert "versão de teste" in markup
        assert "background: #991b1b" in markup
        assert "color: #ffffff" in markup
        assert 'role="note"' in markup
    else:
        assert not markup
    app.button[0].click().run()
    assert not app.exception
    assert len(app.markdown) == (1 if channel and channel.strip().lower() == "canary" else 0)
