"""Os limiares da política vivem num lugar só.

Espalhá-los pelo código é como se perde a capacidade de explicar por que o timeout é
12 s. Este teste trava cada número contra a medição que o justifica.
"""

from app.config import Settings


def test_defaults_sao_os_da_politica():
    s = Settings(_env_file=None)
    # > SLOW_SECONDS=8: a chamada lenta devolve 200 correto (API-COTACAO §3.2)
    assert s.quote_read_timeout_s == 12.0
    assert s.quote_connect_timeout_s == 2.0
    # 0,20³ = 0,8% de falha residual; a 4ª tentativa compra 0,64 pp (§3.4)
    assert s.quote_max_attempts == 3
    # o legado serializa acima de 40 lentas simultâneas (§3.3)
    assert s.quote_max_concorrencia == 8
    assert s.quote_backoff_base_s == 0.25
    assert s.quote_backoff_teto_s == 2.0
    # relógio do LEAD, caminho da cotação
    assert s.aviso_espera_s == 6.0
    assert s.reforco_espera_s == 20.0
    # fora do caminho da cotação: a demora do modelo é anômala, não projetada
    assert s.aviso_sem_cotacao_s == 10.0
    assert s.breaker_limiar == 5
    assert s.breaker_cooldown_s == 20.0


def test_limiar_sem_cotacao_e_maior_que_o_da_cotacao():
    """6,5 s de modelo é latência plausível; 10 s é sintoma. Se alguém
    'uniformizar' os dois, o agente passa a se desculpar por nada."""
    s = Settings(_env_file=None)
    assert s.aviso_sem_cotacao_s > s.aviso_espera_s


def test_timeout_maior_que_a_lentidao_simulada():
    """A invariante que o número 12 existe para cumprir."""
    s = Settings(_env_file=None)
    assert s.quote_read_timeout_s > 8.0


def test_nenhum_default_carrega_segredo():
    s = Settings(_env_file=None)
    assert s.admin_token is None          # opcional, ausente por padrão (CLAUDE.md 14c)
    dump = s.model_dump()
    for chave, valor in dump.items():
        if isinstance(valor, str):
            assert not valor.startswith("sk-"), chave


def test_admin_token_e_opcional_mas_exigido_quando_definido(monkeypatch):
    assert Settings(_env_file=None).admin_exigido is False
    monkeypatch.setenv("APP_ADMIN_TOKEN", "qualquer-coisa")
    assert Settings(_env_file=None).admin_exigido is True


def test_pode_ser_sobrescrito_por_ambiente(monkeypatch):
    monkeypatch.setenv("APP_QUOTE_MAX_ATTEMPTS", "1")
    assert Settings(_env_file=None).quote_max_attempts == 1
