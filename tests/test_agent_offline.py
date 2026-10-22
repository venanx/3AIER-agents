import json
from types import SimpleNamespace
from unittest.mock import Mock

import agent


def test_tools_and_context_without_model():
    assert agent.somar(1234, 5678) == {"resultado": 6912}
    assert json.loads(agent.executar_ferramenta("somar", {"a": 2, "b": 3})) == {"resultado": 5}
    assert "erro" in json.loads(agent.executar_ferramenta("unknown", {}))
    assert "erro" in json.loads(agent.executar_ferramenta("somar", {}))
    assert "# Memória" in agent.carregar_contexto()


def test_response_uses_mock_client(monkeypatch):
    client = Mock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[], content="offline"))])
    monkeypatch.setattr(agent, "get_cliente", lambda: client)
    history = [{"role": "user", "content": "hello"}]
    assert agent.responder(history) == "offline"
    assert history[-1] == {"role": "assistant", "content": "offline"}
    client.chat.completions.create.assert_called_once()
