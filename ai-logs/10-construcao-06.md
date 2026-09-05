# Sessão de construção 06

> Exportado por `scripts/exportar_ai_logs.py`, com redação de segredo,
> caminho absoluto e PII **na escrita**. 28 turnos; o `jsonl` de
> origem tinha 174 KB, majoritariamente saída de
> ferramenta, truncada em 1200 caracteres por bloco.

### Mateus

Review this change for security vulnerabilities.

Changed files (you may Read these and any other file in the repo):
  - app/agent/agente.py
  - scripts/conversa_manual.py

Unified diff (only + lines are new):

=== DIFF: app/agent/agente.py ===
@@ -0,0 +1,88 @@
+"""Montagem do agente Agno.
+
+Multiprovider pela **model-string** do Agno (`anthropic:...`, `ollama:qwen2.5:7b`).
+A forma-classe é usada só onde a string não expõe o necessário — que aqui é o prompt
+caching da Anthropic, que **só existe nesse provider**.
+
+O padrão de caching, confirmado na documentação oficial e contra a biblioteca
+instalada (Agno 3.0.6): `cache_system_prompt=True` mais `system_prompt_blocks`
+recebendo um **callable**, avaliado a cada requisição, devolvendo o bloco volátil com
+`cache=False`. O prefixo antes dele fica estável e quente.
+
+Nunca concatenar conteúdo volátil no system message: zera o cache silenciosamente —
+nada quebra, o custo sobe e ninguém vê.
+"""
+
+from __future__ import annotations
+
+from dataclasses import dataclass
+
+from agno.agent import Agent
+
+from app.agent.catalogo import carregar_catalogo
+from app.agent.prompt import construir_bloco_volatil, construir_system
+from app.agent.tools import ContextoDoTurno, make_qualify_lead, make_quote_plan
+from app.config import get_settings
+from app.contracts.conversa import LeadProfile
+from app.persistence import repo
+
+_catalogo: str | None = None
+
+
+def catalogo_do_processo() -> str:
+    """Buscado uma vez no boot. `GET /planos` é estável e não muda durante a execução;
+    e o catálogo entra no prefixo cacheável."""
+    global _catalogo
+    if _catalogo is None:
+        _catalogo = carregar_catalogo()
+    return _catalogo
+
+
+@dataclass
+class Turno:
+    texto: str
+    metrics: object | None = None
+
+
+def _perfil(ctx: ContextoDoTurno) -> LeadProfile:
+    c = repo.obter_conversa(ctx.sessao, ctx.conversation_id)
+    return LeadProfile(idade=c.idade, veiculo_ano=c.veiculo_ano, cep=c.cep,
+                       data_inicio=c.data_inicio, plano_id=c.plano_id)
+
+
+def construir_agente(ctx: ContextoDoTurno, adaptador=None, historico=None) -> Agent:
+    cfg = get_settings()
+    system = construir_system(catalogo_do_processo())
+    tools = [make_qualify_lead(ctx), make_quote_plan(ctx, adaptador)]
+
+    if cfg.llm_model.startswith("anthropic:"):
+        from agno.models.anthropic import Claude, SystemPromptBlock
+
+        def blocos_volateis() -> list[SystemPromptBlock]:
+            """Avaliado a cada requisição, DEPOIS do prefixo estável. `cache=False`
+            é o que mantém o prefixo anterior quente."""
+            return [SystemPromptBlock(text=construir_bloco_volatil(_perfil(ctx)),
+                                      cache=False)]
+
+        modelo = Claude(
+            id=cfg.llm_model.split(":", 1)[1],
+            cache_system_prompt=True,
+            system_prompt_blocks=blocos_volateis,
+        )
+    else:
+        # Ollama e os demais: a model-string basta. Prompt caching não existe fora da
+        # Anthropic, e o bloco volátil vai anexado à instrução.
+        modelo = cfg.llm_model
+
+    instrucoes = system
+    if not cfg.llm_model.startswith("anthropic:"):
+        instrucoes = f"{system}\n\n{construir_bloco_volatil(_perfil(ctx))}"
+
+    return Agent(
+        model=modelo,
+        instructions=instrucoes,
+        tools=tools,
+        markdown=False,
+        add_history_to_context=True,
+        num_history_runs=20,
+    )


=== DIFF: scripts/conversa_manual.py ===
@@ -0,0 +1,81 @@
+"""Uma conversa do começo ao fim, para LER — não para testar.
+
+O objetivo é aposentar a maior incerteza que resta: o desenho do agente. Ele tem o
+texto descartado em três dos quatro desfechos da tool, não vê número nenhum, e o
+catálogo no system prompt não tem preço nem franquia. Isso é deliberado — e ninguém
+nunca viu esse agente conversar.
+
+O que se procura ao ler: ele soa como atendimento ou como formulário? Ele fica mudo
+depois da cotação, porque tudo que escreveria foi descartado?
+
+Uso:
+    APP_QUOTE_API_URL=http://localhost:8001 \
+    ANTHROPIC_API_KEY=... uv run python scripts/conversa_manual.py
+"""
+
+from __future__ import annotations
+
+import os
+import sys
+import time
+
+sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
+
+from app.agent.agente import construir_agente  # noqa: E402
+from app.agent.tools import ContextoDoTurno  # noqa: E402
+from app.persistence import repo  # noqa: E402
+from app.persistence.db import sessao_factory  # noqa: E402
+
+#: As falas são do molde do dataset: linguagem torta, dados fora de ordem. As duas
+#: últimas cobrem o que o lead do dataset NUNCA informa — plano e data de início —,
+#: que é justamente o que a qualificação exige.
+FALAS = [
+    "Oi, queria fazer um seguro pro meu carro",
+    "e um Onix 2019",
+    "tenho 28 anos, cep [CEP]",
+    "qual a diferença dos planos?",
+    "quero o completo mesmo",
+    "pode começar dia 17 de outubro",
+]
+
+
+class CanalConsole:
+    def __init__(self, t0: float) -> None:
+        self.t0 = t0
+
+    async def send(self, conversation_id, text, *, message_id, quote_id=None,
+                   autor="agente", **kw):
+        marca = f"[+{time.monotonic() - self.t0:5.1f}s]"
+        print(f"{marca} sistema │ {text}\n")
+        return "console"
+
+
+def main() -> None:
+    t0 = time.monotonic()
+    canal = CanalConsole(t0)
+    fabrica = sessao_factory()
+    with fabrica() as s:
+        conv = repo.criar_conversa(s, channel="console", external_ref="manual")
+        s.commit()
+        ctx = ContextoDoTurno(sessao=s, conversation_id=conv.id)
+        agente = construir_agente(ctx, canal)
+
+        for fala in FALAS:
+            ctx.texto_do_lead = fala
+            print(f"[+{time.monotonic() - t0:5.1f}s] LEAD    │ {fala}\n")
+            r = agente.run(fala)
+            texto = (r.content or "").strip()
+            print(f"[+{time.monotonic() - t0:5.1f}s] agente  │ "
+                  f"{texto if texto else '(silêncio)'}\n")
+            m = getattr(r, "metrics", None)
+            if m:
+                print(f"          ↳ in={m.input_tokens} out={m.output_tokens} "
+                      f"cache_read={m.cache_read_tokens} "
+                      f"cache_write={m.cache_write_tokens}\n")
+
+        c = repo.obter_conversa(s, conv.id)
+        print(f"── estado final: {c.state} · conversa {conv.id}")
+
+
+if __name__ == "__main__":
+    main()


Investigate per the method in your instructions, then return the findings list.

### Claude

→ **Read**  `{"file_path": "/"}`

### Mateus

```
EISDIR: illegal operation on a directory, read '/'
```

### Claude

→ **Bash**  `{"command": "pwd && ls", "description": "Show current dir and list"}`

### Mateus

```
<repo>
ai-logs
app
CLAUDE.md
config
db
docker-compose.yml
docs
pyproject.toml
qa
README.md
scripts
tests
uv.lock
web
```

### Claude

→ **Read**  `{"file_path": "<repo>/app/agent/agente.py"}`

### Mateus

```
1	"""Montagem do agente Agno.
2	
3	Multiprovider pela **model-string** do Agno (`anthropic:...`, `ollama:qwen2.5:7b`).
4	A forma-classe é usada só onde a string não expõe o necessário — que aqui é o prompt
5	caching da Anthropic, que **só existe nesse provider**.
6	
7	O padrão de caching, confirmado na documentação oficial e contra a biblioteca
8	instalada (Agno 3.0.6): `cache_system_prompt=True` mais `system_prompt_blocks`
9	recebendo um **callable**, avaliado a cada requisição, devolvendo o bloco volátil com
10	`cache=False`. O prefixo antes dele fica estável e quente.
11	
12	Nunca concatenar conteúdo volátil no system message: zera o cache silenciosamente —
13	nada quebra, o custo sobe e ninguém vê.
14	"""
15	
16	from __future__ import annotations
17	
18	from dataclasses import dataclass
19	
20	from agno.agent import Agent
21	
22	from app.agent.catalogo import carregar_catalogo
23	from app.agent.prompt import construir_bloco_volatil, construir_system
24	from app.agent.tools import ContextoDoTurno, make_qualify_lead, make_quote_plan
25	from app.config import get_settings
26	from app.contracts.conversa import LeadProfile
27	from app.persistence import repo
28	
29	_catalogo: str | 
… [+2198 caracteres]
```

### Claude

→ **Read**  `{"file_path": "<repo>/scripts/conversa_manual.py"}`

### Mateus

```
1	"""Uma conversa do começo ao fim, para LER — não para testar.
2	
3	O objetivo é aposentar a maior incerteza que resta: o desenho do agente. Ele tem o
4	texto descartado em três dos quatro desfechos da tool, não vê número nenhum, e o
5	catálogo no system prompt não tem preço nem franquia. Isso é deliberado — e ninguém
6	nunca viu esse agente conversar.
7	
8	O que se procura ao ler: ele soa como atendimento ou como formulário? Ele fica mudo
9	depois da cotação, porque tudo que escreveria foi descartado?
10	
11	Uso:
12	    APP_QUOTE_API_URL=http://localhost:8001 \
13	    ANTHROPIC_API_KEY=... uv run python scripts/conversa_manual.py
14	"""
15	
16	from __future__ import annotations
17	
18	import os
19	import sys
20	import time
21	
22	sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
23	
24	from app.agent.agente import construir_agente  # noqa: E402
25	from app.agent.tools import ContextoDoTurno  # noqa: E402
26	from app.persistence import repo  # noqa: E402
27	from app.persistence.db import sessao_factory  # noqa: E402
28	
29	#: As falas são do molde do dataset: linguagem torta, dados fora de ordem. As duas
30	#: últimas cobrem o que o lead do dataset NU
… [+1900 caracteres]
```

### Claude

→ **Bash**  `{"command": "ls <repo>/app/agent/", "description": "List app/agent directory"}`

### Mateus

```
agente.py
catalogo.py
guardrail.py
__init__.py
prompt.py
__pycache__
runner.py
tools.py
turno.py
```

### Claude

→ **Read**  `{"file_path": "<repo>/app/agent/prompt.py"}`

### Mateus

```
1	"""System prompt: a parte estática, que é cacheável, e a volátil, que não é.
2	
3	A separação é **requisito do cache**, não estilo. Conteúdo volátil concatenado no system
4	message zera o cache silenciosamente: nada quebra, o custo sobe e ninguém vê. Por isso
5	existe um teste que assere o modo de falha (`test_volatil_no_system_zera_o_cache`).
6	
7	O padrão, confirmado na documentação do Agno: `cache_system_prompt=True` mais
8	`system_prompt_blocks` recebendo um **callable**, avaliado a cada requisição, que
9	devolve o bloco volátil com `cache=False`. O prefixo antes dele fica estável e quente.
10	
11	O few-shot é **só de tom, objeção e ordem de qualificação** — nunca de cotação. 100% das
12	cotações do dataset são matematicamente impossíveis, nenhuma cita carência e a frase de
13	cobertura é sempre a do Essencial: usá-las como exemplo ensinaria os três erros mais
14	graves possíveis nesta entrega.
15	"""
16	
17	from __future__ import annotations
18	
19	import datetime as dt
20	
21	from app.contracts.conversa import LeadProfile
22	
23	PAPEL = """Você é atendente de vendas da AutoSeguro, uma seguradora de veículos, e \
24	conversa com o lead pelo WhatsApp. Fale português do Brasil
… [+3186 caracteres]
```

### Claude

→ **Read**  `{"file_path": "<repo>/app/agent/tools.py"}`

### Mateus

```
1	"""As tools do agente — a fronteira entre o que o modelo decide e o que o sistema
2	garante.
3	
4	Os **nomes e as assinaturas são contrato**: as asserções do `ReliabilityEval` da frente
5	de Dados dependem deles, e mudá-los quebra a avaliação sem quebrar nenhum teste.
6	
7	    qualify_lead(idade, veiculo_ano, cep, data_inicio, plano_id) -> str
8	    quote_plan(plano_id, idade, veiculo_ano, cep, data_inicio) -> str   (fatia 3)
9	    escalate_to_human(trigger, reason, summary) -> str                  (fatia 5)
10	
11	Padrão **write-back**: a tool registra a decisão; quem executa é o backend. Isso mantém
12	o comportamento testável e impede o modelo de causar efeito colateral direto.
13	
14	O contexto confiável — qual conversa, qual sessão de banco — vem do **envelope**, por
15	closure, nunca dos argumentos que o modelo escreveu.
16	"""
17	
18	from __future__ import annotations
19	
20	import datetime as dt
21	import re
22	from collections.abc import Callable
23	from dataclasses import dataclass, field
24	
25	from pydantic import ValidationError
26	from sqlalchemy.orm import Session
27	
28	from app.contracts.conversa import CAMPOS_QUALIFICACAO, LeadProfile
29	from app.contracts.quote
… [+13280 caracteres]
```

### Claude

→ **Read**  `{"file_path": "<repo>/app/agent/catalogo.py"}`

### Mateus

```
1	"""O catálogo de planos, buscado no boot.
2	
3	`fetch_plans` **não é tool.** `GET /planos` é estável — não passa pelo sorteio de falha
4	(30/30 respondem 200 mesmo com `FAILURE_RATE=1.0`) e não muda durante a execução.
5	Buscar no boot elimina um round trip por conversa e põe o catálogo no prefixo cacheável
6	do system prompt.
7	
8	**O catálogo entra sem nenhum valor monetário**, e é este o motivo mais forte. Se
9	`base_mensal` estivesse no prompt, o modelo poderia dizer "o Essencial começa em
10	R$ 119,90" — verdadeiro, e ainda assim um preço escrito pelo modelo. O guardrail
11	precisaria então de uma lista de exceções, e é ali que guardrail morre.
12	
13	Sem número no contexto, a regra é uma linha sem ressalva: zero token monetário em texto
14	de autor `agente`.
15	
16	O custo é uma pergunta que o agente não responde de cabeça — "qual a franquia do
17	Completo?" vira "isso eu te falo junto com o valor". Que é, por acaso, melhor prática de
18	vendas do que soltar a franquia antes do preço.
19	"""
20	
21	from __future__ import annotations
22	
23	import time
24	from dataclasses import dataclass
25	
26	import httpx
27	
28	from app.config import get_settings
29	
30	
31	class Catalog
… [+2758 caracteres]
```

### Claude

→ **Read**  `{"file_path": "<repo>/app/config.py"}`

### Mateus

```
1	"""Os limiares da política, num lugar só.
2	
3	Cada número aqui tem uma medição por trás, citada no comentário. Espalhá-los pelo
4	código é como se perde a capacidade de explicar por que o timeout é 12 s — e é
5	justamente essa explicação que o desafio avalia.
6	
7	Fonte das medições: `docs/API-COTACAO.md` e `docs/POLITICA-RESILIENCIA.md`.
8	"""
9	
10	from __future__ import annotations
11	
12	from pydantic_settings import BaseSettings, SettingsConfigDict
13	
14	
15	class Settings(BaseSettings):
16	    model_config = SettingsConfigDict(
17	        env_prefix="APP_", env_file=".env", extra="ignore"
18	    )
19	
20	    # ─── infraestrutura ──────────────────────────────────────────────────────
21	    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/autoseguro"
22	    quote_api_url: str = "http://localhost:8000"
23	
24	    #: Model-string do Agno. Só `anthropic:` e `ollama:` são validados por smoke test;
25	    #: os demais funcionam pela mesma string mas NÃO foram testados (CLAUDE.md 15).
26	    llm_model: str = "anthropic:claude-opus-5"
27	
28	    #: Opcional e exigido quando definido (CLAUDE.md 14c). Ausente por padrão para que
29	    #: o caminho de um c
… [+2806 caracteres]
```

### Claude

→ **Read**  `{"file_path": "<repo>/app/contracts/conversa.py"}`

### Mateus

```
1	"""Contratos da conversa — lead, turno, estado e sinal de handoff.
2	
3	Congelado na Fase 0. Ver `app/contracts/quote.py` para o motivo de os contratos
4	viverem num pacote próprio.
5	"""
6	
7	from __future__ import annotations
8	
9	import datetime as dt
10	from enum import StrEnum
11	from typing import Annotated, Literal
12	
13	from pydantic import BaseModel, ConfigDict, Field
14	
15	from app.contracts.quote import PlanoId, QuoteRequest
16	
17	# ─────────────────────────────────────────────────────────────────────────────
18	# Perfil do lead
19	# ─────────────────────────────────────────────────────────────────────────────
20	
21	#: Os cinco campos da qualificação, na ordem em que são perguntados.
22	#: Cada um está aqui porque muda o resultado ou destrava um campo da resposta:
23	#: idade e ano do veículo definem multiplicador *e* aceitação; CEP vale até 30% de
24	#: agravo; data de início destrava o pro-rata; plano define a base.
25	CAMPOS_QUALIFICACAO: tuple[str, ...] = (
26	    "idade",
27	    "veiculo_ano",
28	    "cep",
29	    "data_inicio",
30	    "plano_id",
31	)
32	
33	
34	class LeadProfile(BaseModel):
35	    """O que sabemos do lead. Todo campo é opcional porque a conv
… [+6456 caracteres]
```

### Claude

→ **Read**  `{"file_path": "<repo>/app/agent/runner.py"}`

### Mateus

```
1	"""Execução de um turno.
2	
3	Nesta fatia o runner ainda é a espinha: ele orquestra persistência e canal. O agente
4	Agno com tools entra na fatia 3, junto com a cotação.
5	"""
6	
7	from __future__ import annotations
8	
9	from app.persistence import repo
10	from app.persistence.db import sessao_factory
11	
12	
13	async def processar_turno_web(conversation_id: str, texto: str, adaptador) -> None:
14	    """Um turno vindo do canal web.
15	
16	    A mensagem do lead é **ecoada** de volta com o id e o `index` canônicos: sem isso
17	    o cliente não tem como reconciliar a bolha otimista, e passa a exibir um status
18	    que ele mesmo inventou.
19	    """
20	    fabrica = sessao_factory()
21	    with fabrica() as s:
22	        m = repo.gravar_mensagem(
23	            s, conversation_id, autor="lead", conteudo=texto, status="received"
24	        )
25	        s.commit()
26	        await adaptador.send(conversation_id, m.conteudo, message_id=m.id,
27	                             autor="lead", index=m.index, status=m.status)
28	
29	    await adaptador.typing(conversation_id, ativo=True)
30	    try:
31	        from app.agent.turno import responder
32	
33	        await responder(conversati
… [+108 caracteres]
```

### Claude

→ **Read**  `{"file_path": "<repo>/app/agent/turno.py"}`

### Mateus

```
1	"""O turno do agente. Substituído pelo agente Agno na fatia 3."""
2	
3	from __future__ import annotations
4	
5	from app.persistence import repo
6	from app.persistence.db import sessao_factory
7	
8	
9	async def responder(conversation_id: str, texto: str, adaptador) -> None:
10	    fabrica = sessao_factory()
11	    resposta = "Recebi! Ainda estou sendo montado — a cotação chega na próxima fatia."
12	    with fabrica() as s:
13	        m = repo.gravar_mensagem(
14	            s, conversation_id, autor="agente", conteudo=resposta, status="pending"
15	        )
16	        s.commit()
17	        await adaptador.send(conversation_id, m.conteudo, message_id=m.id,
18	                             autor="agente", index=m.index, status="sent")
19	        repo.atualizar_status_mensagem(s, m.id, "sent")
20	        s.commit()
21	
```

### Claude

Based on my review of the two changed files plus the imported context (prompt.py, tools.py, catalogo.py, config.py, contracts/conversa.py, runner.py, turno.py), I traced every new sink to its source:

**Data flow analysis:**
- `agente.py`: `_perfil(ctx)` reads from DB using a trusted `conversation_id` from the closure; the volatile block only uses type-validated structured fields (int/int/8-digit-regex/date/literal), no free-text lead input reaches the system prompt. Non-anthropic path freezes the volatile block at agent-construction — that's a correctness bug for reused agents, not a security one, since `qualify_lead` still re-reads from DB.
- `cfg.llm_model` comes from env (`APP_LLM_MODEL`); `.split(":", 1)[1]` isn't an injection sink.
- `catalogo_do_processo` module-level cache holds only public product catalog (no PII, no per-tenant data) — benign race at boot, no cross-tenant leak.
- `conversa_manual.py`: hardcoded FALAS, a `sys.path.insert` (standard script boilerplate), console `send` that just prints. No sink is attacker-influenceable; the script is developer-run.
- No shell/exec, no SQL raw, no filesystem sinks, no SSRF vector in these files, no deserialization, no template injection.
- The closure over `ctx` in `blocos_volateis` correctly re-reads perfil per request via the mutable ctx pattern; there's no cross-conversation leak in the sole call site (`conversa_manual.py`) because `ctx` is scoped to a single `conv.id`.

No security vulnerabilities found in the diff.

### Claude

→ **StructuredOutput**  `{"findings": []}`

### Mateus

```
Structured output provided successfully
```
