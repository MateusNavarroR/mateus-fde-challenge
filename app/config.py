"""Os limiares da política, num lugar só.

Cada número aqui tem uma medição por trás, citada no comentário. Espalhá-los pelo
código é como se perde a capacidade de explicar por que o timeout é 12 s — e é
justamente essa explicação que o desafio avalia.

Fonte das medições: `docs/API-COTACAO.md` e `docs/POLITICA-RESILIENCIA.md`.
"""

from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="APP_", env_file=".env", extra="ignore"
    )

    # ─── infraestrutura ──────────────────────────────────────────────────────
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/autoseguro"
    quote_api_url: str = "http://localhost:8000"

    #: Model-string do Agno. Só `anthropic:` e `ollama:` são validados por smoke test;
    #: os demais funcionam pela mesma string mas NÃO foram testados (CLAUDE.md 15).
    llm_model: str = "anthropic:claude-opus-5"

    #: Opcional e exigido quando definido (CLAUDE.md 14c). Ausente por padrão para que
    #: o caminho de um comando não mude; presente, dá ao passe de segurança uma
    #: resposta em código em vez de "risco aceito" em prosa.
    #:
    #: **Vazio é ausente.** Ver o validador abaixo — no shell e no compose não existe
    #: diferença entre "não defini" e `ADMIN_TOKEN=`, e tratar as duas coisas
    #: diferente foi o que quebrou o caminho padrão.
    admin_token: str | None = None

    #: ⚠️ `APP_ENV` não mora aqui — é lido direto por `app/main.py` e `app/auth.py`,
    #: porque as duas decisões que ele governa acontecem antes de `Settings` existir.
    #: O padrão é **`prod`**, e `dev` é opt-in: ele abre `/docs`, `/redoc` e
    #: `/openapi.json` e tira a flag `Secure` do cookie de sessão. Era o contrário, e
    #: "a imagem define prod" é a racionalização que o passe de `insecure-defaults`
    #: recusa — quem rodasse `uvicorn` fora da imagem ficava exposto em silêncio.

    # ─── cliente da /quote ───────────────────────────────────────────────────
    quote_connect_timeout_s: float = 2.0

    #: MAIOR que QUOTE_SLOW_SECONDS (8 s). Medido: 10% das chamadas dormem 8,004 s e
    #: devolvem 200 correto. Um timeout de 5 s destrói o sucesso; 12 s o salva, com
    #: margem para a rede e para SLOW_SECONDS ser configurável. (API-COTACAO §3.2)
    quote_read_timeout_s: float = 12.0

    #: Tentativas são sorteios independentes — medido 0,720 contra 0,729 teórico em
    #: p=0,9. Com p=0,20: 3 tentativas → 0,8% residual. A 4ª compra 0,64 pp e custa
    #: mais um ciclo que pode ser de 12 s. (API-COTACAO §3.4)
    quote_max_attempts: int = 3

    #: Não há `Retry-After` no 5xx do legado — o backoff é 100% nosso. (§3.1)
    quote_backoff_base_s: float = 0.25
    quote_backoff_teto_s: float = 2.0

    #: O handler da /quote é síncrono, então roda no threadpool do AnyIO (limite 40).
    #: Medido: 60 lentas simultâneas → 40 em ~8,8 s e 20 enfileiradas para ~16,6 s,
    #: acima do nosso read timeout. Sem limitar, o dimensionamento do timeout deixa
    #: de valer exatamente quando há mais leads. (§3.3)
    quote_max_concorrencia: int = 8

    # ─── circuit breaker ─────────────────────────────────────────────────────
    #: Com p=0,20, cinco falhas seguidas por acaso têm probabilidade de 0,032% — o
    #: breaker praticamente não abre por azar. Só `transient` e `timeout` contam.
    breaker_limiar: int = 5
    breaker_cooldown_s: float = 20.0

    # ─── espera conversacional ───────────────────────────────────────────────
    #: Relógio do LEAD: conta da chegada da mensagem dele, não de quando a tool
    #: começou. Disparado de dentro da tool de cotação.
    aviso_espera_s: float = 6.0
    reforco_espera_s: float = 20.0

    #: **Piso** do atraso do aviso, e ele não é cosmético.
    #:
    #: O relógio é o do lead, então quando o modelo leva mais de 6 s para chegar à
    #: tool o prazo já venceu e o atraso calculado é 0 — um `Timer(0)` que corre com
    #: a chamada HTTP. Medido gerando o transcript do caminho feliz: a `/quote`
    #: respondeu em 31 ms e o lead recebeu "tô buscando o valor" 0,1 s ANTES do
    #: preço. É exatamente o «só um instante» seguido da resposta que a decisão 1
    #: rejeita — e o motivo pelo qual o aviso não é um watchdog na camada de conversa.
    #:
    #: 1,0 s cobre com folga o caminho rápido (10–40 ms) e o ciclo de falha rápida
    #: com retry (~250 ms por tentativa, ~0,8 s no total), que a decisão 1 também
    #: manda não avisar. Uma chamada lenta de verdade (8 s, ou os 12 s do timeout)
    #: continua avisando — 1 s depois de a tool começar, quando o lead já esperou os
    #: 6 s e a demora já é fato, não previsão.
    piso_aviso_s: float = 1.0

    #: Fora do caminho da cotação, na camada de conversa. Limiar mais alto porque a
    #: demora do modelo é anômala, não projetada: 6,5 s ainda é latência plausível e
    #: avisar ali produziria "só um instante" seguido da resposta 0,2 s depois.
    aviso_sem_cotacao_s: float = 10.0

    @field_validator("admin_token", mode="after")
    @classmethod
    def _vazio_e_ausente(cls, v: str | None) -> str | None:
        """`ADMIN_TOKEN=` (vazio) significa **não configurado**, e não "token vazio".

        Sem isto, o `docker-compose.yml` — que passa `${ADMIN_TOKEN:-}` e portanto
        injeta string vazia quando a variável não existe — ligava a exigência de
        token com um token vazio. Medido no caminho padrão de um comando:

        - `GET /api/handoffs` sem cabeçalho → **200**, porque `exigir_admin` compara
          `"" == ""` e considera o token válido;
        - `WS /api/events` sem query → **403**, porque ali a comparação era contra
          `None` e o ausente não vira `""`;
        - `WS /api/events?token=` → **101**.

        Ou seja: uma proteção que quebrava o tempo real do admin e não protegia nada,
        já que `?token=` vazio abria. A normalização é na origem porque o defeito não
        era de nenhum dos dois consumidores — era do valor.
        """
        return v.strip() or None if v is not None else None

    @property
    def admin_exigido(self) -> bool:
        return self.admin_token is not None


_settings: Settings | None = None


def get_settings() -> Settings:
    """Instância única. Não é cache de performance: é para que um teste que
    sobrescreve um limiar não veja outro módulo lendo o valor antigo."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
