"""Montagem do agente Agno.

Multiprovider pela **model-string** do Agno (`anthropic:...`, `ollama:qwen2.5:7b`).
A forma-classe é usada só onde a string não expõe o necessário — que aqui é o prompt
caching da Anthropic, que **só existe nesse provider**.

O padrão de caching, confirmado na documentação oficial e contra a biblioteca
instalada (Agno 3.0.6): `cache_system_prompt=True` mais `system_prompt_blocks`
recebendo um **callable**, avaliado a cada requisição, devolvendo o bloco volátil com
`cache=False`. O prefixo antes dele fica estável e quente.

Nunca concatenar conteúdo volátil no system message: zera o cache silenciosamente —
nada quebra, o custo sobe e ninguém vê.
"""

from __future__ import annotations

from dataclasses import dataclass

from agno.agent import Agent
from agno.db.postgres import PostgresDb

from app.agent.catalogo import carregar_catalogo
from app.agent.prompt import construir_bloco_volatil, construir_system
from app.agent.tools import ContextoDoTurno, make_qualify_lead, make_quote_plan
from app.config import get_settings
from app.contracts.conversa import LeadProfile
from app.persistence import repo

_catalogo: str | None = None


def catalogo_do_processo() -> str:
    """Buscado uma vez no boot. `GET /planos` é estável e não muda durante a execução;
    e o catálogo entra no prefixo cacheável."""
    global _catalogo
    if _catalogo is None:
        _catalogo = carregar_catalogo()
    return _catalogo


_db: PostgresDb | None = None


def _db_do_processo() -> PostgresDb:
    """O Agno guarda a sessão no mesmo Postgres da aplicação, em tabelas próprias.

    Elas são criadas pelo próprio Agno e **não** entram nas nossas migrações — o
    esquema delas é dele, e versioná-lo criaria um segundo dono para o mesmo objeto.
    """
    global _db
    if _db is None:
        _db = PostgresDb(db_url=get_settings().database_url)
    return _db


def _perfil(ctx: ContextoDoTurno) -> LeadProfile:
    c = repo.obter_conversa(ctx.sessao, ctx.conversation_id)
    return LeadProfile(idade=c.idade, veiculo_ano=c.veiculo_ano, cep=c.cep,
                       data_inicio=c.data_inicio, plano_id=c.plano_id)


def construir_agente(ctx: ContextoDoTurno, adaptador=None, historico=None) -> Agent:
    cfg = get_settings()
    system = construir_system(catalogo_do_processo())
    tools = [make_qualify_lead(ctx), make_quote_plan(ctx, adaptador)]

    if cfg.llm_model.startswith("anthropic:"):
        from agno.models.anthropic import Claude, SystemPromptBlock

        def blocos_volateis() -> list[SystemPromptBlock]:
            """Avaliado a cada requisição, DEPOIS do prefixo estável. `cache=False`
            é o que mantém o prefixo anterior quente."""
            return [SystemPromptBlock(text=construir_bloco_volatil(_perfil(ctx)),
                                      cache=False)]

        modelo = Claude(
            id=cfg.llm_model.split(":", 1)[1],
            cache_system_prompt=True,
            system_prompt_blocks=blocos_volateis,
        )
    else:
        # Ollama e os demais: a model-string basta. Prompt caching não existe fora da
        # Anthropic, e o bloco volátil vai anexado à instrução.
        modelo = cfg.llm_model

    instrucoes = system
    if not cfg.llm_model.startswith("anthropic:"):
        instrucoes = f"{system}\n\n{construir_bloco_volatil(_perfil(ctx))}"

    return Agent(
        model=modelo,
        instructions=instrucoes,
        tools=tools,
        markdown=False,
        # SEM `db`, `add_history_to_context=True` não faz nada — o Agno avisa e segue,
        # e cada turno nasce sem passado. O sintoma não é um erro: é um agente que
        # repergunta a idade que o lead acabou de dar, para sempre.
        #
        # A sessão do Agno é indexada pelo NOSSO `conversation_id`, no MESMO Postgres
        # da aplicação. Assim não há um segundo lugar guardando o histórico.
        db=_db_do_processo(),
        session_id=ctx.conversation_id,
        add_history_to_context=True,
        num_history_runs=20,
    )
