"""Carregamento de ambiente e falha alta por credencial ausente.

O modo de falha que isto previne é o pior tipo: o arquivo existe, a variável existe, e
o SDK não a vê — porque o `pydantic-settings` não exporta para `os.environ`. O sintoma
seria uma exceção de autenticação no meio de outra coisa.
"""

import os

import pytest

from app.bootstrap import CredencialAusente, carregar_env, exigir_credenciais


def test_carrega_variavel_sem_prefixo(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=valor-de-teste\nAPP_LLM_MODEL=x\n")
    assert carregar_env(env) == ["ANTHROPIC_API_KEY"]
    assert os.environ["ANTHROPIC_API_KEY"] == "valor-de-teste"


def test_nunca_sobrescreve_o_ambiente_real(tmp_path, monkeypatch):
    """Quem exportou no shell mandou mais que o arquivo."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "do-shell")
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=do-arquivo\n")
    carregar_env(env)
    assert os.environ["ANTHROPIC_API_KEY"] == "do-shell"


def test_nao_carrega_o_que_pertence_ao_settings(tmp_path, monkeypatch):
    """`APP_*` é do pydantic-settings; duplicar aqui criaria dois caminhos para o
    mesmo valor, e um deles ficaria para trás."""
    monkeypatch.delenv("APP_DATABASE_URL", raising=False)
    env = tmp_path / ".env"
    env.write_text("APP_DATABASE_URL=postgres://x\n")
    assert carregar_env(env) == []
    assert "APP_DATABASE_URL" not in os.environ


def test_env_ausente_nao_quebra(tmp_path):
    assert carregar_env(tmp_path / "nao-existe") == []


def test_valor_vazio_e_ignorado(tmp_path, monkeypatch):
    """`.env.example` tem `ADMIN_TOKEN=` vazio; carregá-lo faria `admin_exigido`
    virar verdadeiro com token vazio, que é pior que não ter."""
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    env = tmp_path / ".env"
    env.write_text("ADMIN_TOKEN=\n")
    assert carregar_env(env) == []


def test_falha_alto_quando_anthropic_sem_chave(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(CredencialAusente) as e:
        exigir_credenciais("anthropic:claude-opus-5")
    msg = str(e.value)
    # A mensagem diz exatamente o que fazer, incluindo a saída sem chave.
    assert "ANTHROPIC_API_KEY" in msg
    assert ".env" in msg
    assert "ollama:qwen2.5:7b" in msg


def test_ollama_nao_exige_chave(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    exigir_credenciais("ollama:qwen2.5:7b")   # não levanta


def test_anthropic_com_chave_passa(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "presente")
    exigir_credenciais("anthropic:claude-opus-5")


def test_a_mensagem_nao_vaza_o_valor_da_chave(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(CredencialAusente) as e:
        exigir_credenciais("anthropic:claude-opus-5")
    assert "sk-" not in str(e.value)
