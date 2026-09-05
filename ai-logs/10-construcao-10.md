# Sessão de construção 10

> Exportado por `scripts/exportar_ai_logs.py`, com redação de segredo,
> caminho absoluto e PII **na escrita**. 32 turnos; o `jsonl` de
> origem tinha 172 KB, majoritariamente saída de
> ferramenta, truncada em 1200 caracteres por bloco.

### Mateus

Review this change for security vulnerabilities.

Changed files (you may Read these and any other file in the repo):
  - app/agent/turno.py
  - app/bootstrap.py
  - tests/nucleo/test_bootstrap.py

Unified diff (only + lines are new):

=== DIFF: app/agent/turno.py ===
@@ -36,27 +36,47 @@ async def responder(
     fabrica = sessao_factory()
 
     with fabrica() as s:
-        def enviar(conteudo: str, quote_id: str | None = None, autor: str = "sistema") -> None:
-            """Grava e entrega, **bloqueando** até o frame sair.
 
-            Chamado de dentro da thread do agente. `run_coroutine_threadsafe(...).result()`
-            é o que garante a ordem: agendar sem esperar deixaria o aviso de espera
-            chegar depois do preço.
-            """
+        def _persistir(conteudo: str, quote_id: str | None, autor: str):
             m = repo.gravar_mensagem(
                 s, conversation_id, autor=autor, conteudo=conteudo,
                 status="pending", quote_id=quote_id,
             )
             s.commit()
-            asyncio.run_coroutine_threadsafe(
-                adaptador.send(conversation_id, m.conteudo, message_id=m.id,
-                               quote_id=m.quote_id, autor=autor, index=m.index,
-                               status="sent"),
-                laco,
-            ).result(timeout=30)
+            return m
+
+        def _confirmar(m) -> None:
             repo.atualizar_status_mensagem(s, m.id, "sent")
             s.commit()
 
+        async def _entregar(m, autor: str) -> None:
+            await adaptador.send(conversation_id, m.conteudo, message_id=m.id,
+                                 quote_id=m.quote_id, autor=autor,
+                                 index=m.index, status="sent")
+
+        def enviar(conteudo: str, quote_id: str | None = None,
+                   autor: str = "sistema") -> None:
+            """Grava e entrega, **bloqueando** até o frame sair.
+
+            Chamado de dentro da thread do agente. `run_coroutine_threadsafe(...)
+            .result()` é o que garante a ordem: agendar sem esperar deixaria o aviso
+            de espera chegar depois do preço.
+
+            ⚠️ **Só pode ser chamado fora da thread do laço.** Chamá-lo de dentro dela
+            agenda no laço que está bloqueado esperando o resultado — deadlock, e o
+            sintoma é um `TimeoutError` a 30 s de distância da causa. O caminho de
+            erro abaixo usa `await` direto por isso.
+            """
+            m = _persistir(conteudo, quote_id, autor)
+            asyncio.run_coroutine_threadsafe(_entregar(m, autor), laco).result(timeout=45)
+            _confirmar(m)
+
+        async def enviar_async(conteudo: str, autor: str = "sistema") -> None:
+            """A versão para quando já se está no laço."""
+            m = _persistir(conteudo, None, autor)
+            await _entregar(m, autor)
+            _confirmar(m)
+
         ctx = ContextoDoTurno(
             sessao=s,
             conversation_id=conversation_id,
@@ -70,10 +90,10 @@ async def responder(
             r = await asyncio.to_thread(agente.run, texto)
         except Exception:  # noqa: BLE001
             log.exception("turno falhou")
-            enviar(
-                "Tive um problema aqui do meu lado. Já vou chamar alguém da equipe.",
-                autor="sistema",
-            )
+            if not ctx.ja_enviou:
+                await enviar_async(
+                    "Tive um problema aqui do meu lado. Já vou chamar alguém da equipe."
+                )
             return
 
         _gravar_uso(s, conversation_id, r)
@@ -86,7 +106,7 @@ async def responder(
         if not saida:
             return
         try:
-            enviar(saida, autor="agente")
+            await enviar_async(saida, autor="agente")
         except GuardrailViolado as e:
             # Violação não é corrigida pelo modelo — isso vira laço. A mensagem é
             # descartada e a violação conta.


=== DIFF: app/bootstrap.py ===
@@ -31,6 +31,14 @@ RAIZ = Path(__file__).resolve().parent.parent
 #: Variáveis que o SDK ou o legado leem direto do ambiente, sem passar por `Settings`.
 SEM_PREFIXO = ("ANTHROPIC_API_KEY", "OLLAMA_API_KEY", "ADMIN_TOKEN")
 
+#: Nomes que o `.env` usa sem prefixo e que o `Settings` espera com `APP_`.
+#:
+#: A mesma armadilha da chave da Anthropic, num segundo lugar: o `docker-compose.yml`
+#: faz `APP_ADMIN_TOKEN: ${ADMIN_TOKEN:-}` e resolve sozinho, então o caminho que
+#: quebra é o local — e quebra em silêncio, com o `/admin` subindo sem autenticação
+#: apesar de o token estar no arquivo.
+ESPELHADAS = {"ADMIN_TOKEN": "[REDIGIDO]"}
+
 
 class CredencialAusente(RuntimeError):
     """Erra no boot, não no meio da conversa."""
@@ -57,6 +65,10 @@ def carregar_env(caminho: Path | None = None) -> list[str]:
         if chave in SEM_PREFIXO or chave.startswith("QUOTE_"):
             os.environ[chave] = valor
             carregadas.append(chave)
+            espelho = ESPELHADAS.get(chave)
+            if espelho and espelho not in os.environ:
+                os.environ[espelho] = valor
+                carregadas.append(espelho)
     return carregadas
 
 


=== DIFF: tests/nucleo/test_bootstrap.py ===
@@ -78,3 +78,23 @@ def test_a_mensagem_nao_vaza_o_valor_da_chave(monkeypatch):
     with pytest.raises(CredencialAusente) as e:
         exigir_credenciais("anthropic:claude-opus-5")
     assert "sk-" not in str(e.value)
+
+
+def test_admin_token_chega_ao_settings(tmp_path, monkeypatch):
+    """A mesma armadilha da chave da Anthropic, num segundo lugar.
+
+    O `.env` declara `ADMIN_TOKEN`; o `Settings` espera `APP_ADMIN_TOKEN`. O
+    `docker-compose.yml` faz a ponte (`APP_ADMIN_TOKEN: ${ADMIN_TOKEN:-}`), então o
+    caminho que quebra é o local — e quebra **em silêncio**: o `/admin` sobe sem
+    autenticação apesar de o token estar no arquivo.
+    """
+    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
+    monkeypatch.delenv("APP_ADMIN_TOKEN", raising=False)
+    env = tmp_path / ".env"
+    env.write_text("ADMIN_TOKEN=[REDIGIDO]\n")
+    carregar_env(env)
+    assert os.environ["APP_ADMIN_TOKEN"] == "segredo-de-teste"
+
+    from app.config import Settings
+
+    assert Settings(_env_file=None).admin_exigido is True


Investigate per the method in your instructions, then return the findings list.

### Claude

→ **Read**  `{"file_path": "/app/agent/turno.py"}`

### Mateus

```
File does not exist. Note: your current working directory is <repo>.
```

### Claude

→ **Read**  `{"file_path": "/app/bootstrap.py"}`

### Claude

→ **Read**  `{"file_path": "/tests/nucleo/test_bootstrap.py"}`

### Mateus

```
File does not exist. Note: your current working directory is <repo>.
```

### Mateus

```
File does not exist. Note: your current working directory is <repo>.
```

### Claude

→ **Read**  `{"file_path": "<repo>/app/agent/turno.py"}`

### Mateus

```
1	"""Um turno do agente, ponta a ponta.
2	
3	Monta o contexto confiável, constrói o agente Agno com as tools ligadas, roda, e
4	aplica a **regra de descarte**: quando a tool já falou com o lead — cotação, recusa ou
5	indisponibilidade —, o texto do modelo naquele turno é jogado fora.
6	
7	O motivo do descarte: tudo que o lead precisava ouvir já foi dito deterministicamente,
8	e o que o modelo acrescentar é texto não verificado sobre uma cotação. Vale nos três
9	desfechos, **sem exceção** — inclusive na recusa, onde o risco não é preço alucinado e
10	sim promessa falsa ("vou ver com o setor de exceções").
11	
12	O agente roda numa **thread**, porque as tools do Agno são síncronas e uma delas
13	bloqueia por até ~37 s esperando a `/quote`. Rodá-lo no laço de eventos travaria o
14	WebSocket inteiro — inclusive as mensagens de espera que a própria tool precisa enviar.
15	"""
16	
17	from __future__ import annotations
18	
19	import asyncio
20	import logging
21	import time
22	
23	from app.agent.agente import construir_agente
24	from app.agent.guardrail import GuardrailViolado
25	from app.agent.tools import ContextoDoTurno
26	from app.persistence import repo
27	from app.persistence.db impo
… [+3926 caracteres]
```

### Claude

→ **Read**  `{"file_path": "<repo>/app/bootstrap.py"}`

### Mateus

```
1	"""Carregamento de ambiente e validação de credencial — explícito e testável.
2	
3	**O problema que isto resolve.** O `pydantic-settings` lê o `.env` para preencher os
4	campos de `Settings`, com o prefixo `APP_`, mas **não exporta nada para `os.environ`**.
5	O SDK da Anthropic, por outro lado, lê `ANTHROPIC_API_KEY` direto do ambiente do
6	processo. Resultado: rodando local, a chave existe no arquivo e **não chega ao SDK**.
7	
8	O `docker compose` não tem esse problema — ele interpola `${ANTHROPIC_API_KEY}` do
9	`.env` do diretório sozinho. Então o caminho que quebra é justamente o do
10	desenvolvimento, e ele quebra tarde: uma exceção de autenticação no meio de outra
11	coisa, e quinze minutos procurando no lugar errado.
12	
13	Duas funções, e as duas são chamadas em **todo** ponto de entrada:
14	
15	- `carregar_env()` põe no `os.environ` as variáveis sem prefixo que o `.env` declara,
16	  sem nunca sobrescrever o que já veio do ambiente real;
17	- `exigir_credenciais()` **falha alto no boot** se o provider configurado precisa de
18	  credencial e ela não está lá, com uma mensagem que diz exatamente o que fazer.
19	
20	Mesmo princípio do catálogo: falhar no boot com mensagem cl
… [+3659 caracteres]
```

### Claude

→ **Read**  `{"file_path": "<repo>/tests/nucleo/test_bootstrap.py"}`

### Mateus

```
1	"""Carregamento de ambiente e falha alta por credencial ausente.
2	
3	O modo de falha que isto previne é o pior tipo: o arquivo existe, a variável existe, e
4	o SDK não a vê — porque o `pydantic-settings` não exporta para `os.environ`. O sintoma
5	seria uma exceção de autenticação no meio de outra coisa.
6	"""
7	
8	import os
9	
10	import pytest
11	
12	from app.bootstrap import CredencialAusente, carregar_env, exigir_credenciais
13	
14	
15	def test_carrega_variavel_sem_prefixo(tmp_path, monkeypatch):
16	    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
17	    env = tmp_path / ".env"
18	    env.write_text("ANTHROPIC_API_KEY=[REDIGIDO]\nAPP_LLM_MODEL=x\n")
19	    assert carregar_env(env) == ["ANTHROPIC_API_KEY"]
20	    assert os.environ["ANTHROPIC_API_KEY"] == "valor-de-teste"
21	
22	
23	def test_nunca_sobrescreve_o_ambiente_real(tmp_path, monkeypatch):
24	    """Quem exportou no shell mandou mais que o arquivo."""
25	    monkeypatch.setenv("ANTHROPIC_API_KEY", "do-shell")
26	    env = tmp_path / ".env"
27	    env.write_text("ANTHROPIC_API_KEY=[REDIGIDO]\n")
28	    carregar_env(env)
29	    assert os.environ["ANTHROPIC_API_KEY"] == "do-shell"
30	
31	
32	def test_nao_carr
… [+2890 caracteres]
```

### Claude

→ **Grep**  `{"pattern": "ctx\\.enviar|\\.enviar\\(|enviar_async", "output_mode": "content", "-n": true}`

### Mateus

```
scripts/conversa_manual.py:75:        ctx.enviar = enviar
app/agent/turno.py:74:        async def enviar_async(conteudo: str, autor: str = "sistema") -> None:
app/agent/turno.py:94:                await enviar_async(
app/agent/turno.py:109:            await enviar_async(saida, autor="agente")
web/src/chat/useConversa.ts:206:    enviarRef.current = (texto: string) => sessao.enviar({ type: "message", text: texto });
app/agent/tools.py:285:            avisar=(lambda t: enviar(t)) if ctx.enviar else None,
app/agent/tools.py:291:            if ctx.enviar is not None:
app/agent/tools.py:292:                ctx.enviar(texto, quote_id)
```

### Claude

→ **Grep**  `{"pattern": "ja_enviou", "output_mode": "content", "-n": true}`

### Mateus

```
scripts/conversa_manual.py:82:            ctx.ja_enviou = False
scripts/conversa_manual.py:86:            if ctx.ja_enviou:
app/agent/turno.py:93:            if not ctx.ja_enviou:
app/agent/turno.py:101:        if ctx.ja_enviou:
app/agent/tools.py:113:    ja_enviou: bool = False
app/agent/tools.py:290:            ctx.ja_enviou = True
tests/nucleo/test_cotacao.py:129:    assert ctx.ja_enviou is False
tests/nucleo/test_cotacao.py:131:    assert ctx.ja_enviou is True
tests/nucleo/test_cotacao.py:137:    assert ctx.ja_enviou is True
```

### Claude

→ **Grep**  `{"pattern": "admin_exigido|ADMIN_TOKEN|admin_token", "output_mode": "content", "-n": true, "-i": true}`

### Mateus

```
docker-compose.yml:4:# ADMIN_TOKEN é opcional — sem ele a aplicação sobe e avisa no log.
docker-compose.yml:63:      APP_ADMIN_TOKEN: "${ADMIN_TOKEN:-}"
.env.example:7:ADMIN_TOKEN=
CLAUDE.md:84:14c. **`ADMIN_TOKEN` é opcional e exigido quando definido.** Sem ele a aplicação sobe,
docs/DECISOES-FECHADAS.md:388:**Exposição: `127.0.0.1` mais `ADMIN_TOKEN` opcional.** O controle que de fato importa é
app/bootstrap.py:32:SEM_PREFIXO = ("ANTHROPIC_API_KEY", "OLLAMA_API_KEY", "ADMIN_TOKEN")
app/bootstrap.py:37:#: faz `APP_ADMIN_TOKEN: ${ADMIN_TOKEN:-}` e resolve sozinho, então o caminho que
app/bootstrap.py:40:ESPELHADAS = {"ADMIN_TOKEN": "[REDIGIDO]"}
app/channels/web.py:155:        # ADMIN_TOKEN está definido, o token vem por query string.
app/channels/web.py:156:        if cfg.admin_exigido and ws.query_params.get("token") != cfg.admin_token:
app/config.py:31:    admin_token: str | None = None
app/config.py:74:    def admin_exigido(self) -> bool:
app/config.py:75:        return self.admin_token is not None
docs/planos/07-chat.md:850:5. **`ADMIN_TOKEN`, quando definido, precisa de um caminho para o WebSocket.** O
app/main.py:12:- `ADMIN_TOKEN` é opcional: definido ⇒ exigido; ausent
… [+3918 caracteres]
```

### Claude

→ **Read**  `{"file_path": "<repo>/app/agent/tools.py", "offset": 270, "limit": 40}`

### Mateus

```
270	        for campo, valor in (("idade", req.idade), ("veiculo_ano", req.veiculo_ano)):
271	            registrado = getattr(conv, campo)
272	            if registrado is not None and registrado != valor:
273	                return (f"dados_invalidos: o {campo} que você passou ({valor}) não bate "
274	                        f"com o que foi registrado ({registrado}). Confirme com o lead.")
275	
276	        conv.state = "cotando"
277	        ctx.sessao.flush()
278	
279	        q = executar_job(
280	            ctx.sessao, ctx.conversation_id, req,
281	            chegada_do_lead=ctx.chegada_do_lead,
282	            # O aviso e o reforço saem por aqui, de dentro da tool, com o relógio do
283	            # lead — nunca por um watchdog na camada de conversa, que dispararia
284	            # durante a geração do modelo.
285	            avisar=(lambda t: enviar(t)) if ctx.enviar else None,
286	        )
287	        ctx.sessao.commit()
288	
289	        def enviar(texto: str, quote_id: str | None = None) -> None:
290	            ctx.ja_enviou = True
291	            if ctx.enviar is not None:
292	                ctx.enviar(texto, quote_id)
293	
294	        if q.status == str(QuoteJobStatu
… [+840 caracteres]
```

### Claude

→ **Read**  `{"file_path": "<repo>/app/agent/tools.py", "offset": 100, "limit": 30}`

### Mateus

```
100	
101	    #: `(texto, quote_id) -> None`, **síncrono**. Quem monta o contexto decide como a
102	    #: mensagem chega ao canal: o console imprime, o web empurra pelo socket. A tool
103	    #: é síncrona (é o Agno que a chama), então marshalar para o laço de eventos é
104	    #: responsabilidade de quem constrói — e agendar sem esperar quebraria a ordem
105	    #: das mensagens no socket.
106	    enviar: Callable[[str, str | None], None] | None = None
107	
108	    #: `time.monotonic()` de quando a mensagem do lead chegou. É o **relógio do lead**:
109	    #: contar do início da tool faria o aviso sair depois de ele já ter esperado 8 s.
110	    chegada_do_lead: float | None = None
111	
112	    #: A tool já falou com o lead neste turno ⇒ o texto do modelo é descartado.
113	    ja_enviou: bool = False
114	
115	
116	def make_qualify_lead(ctx: ContextoDoTurno) -> Callable[..., str]:
117	    def qualify_lead(
118	        idade: int | None = None,
119	        veiculo_ano: int | None = None,
120	        cep: str | None = None,
121	        data_inicio: str | None = None,
122	        plano_id: str | None = None,
123	    ) -> str:
124	        """Registra os dados de qualificação do lead que 
… [+193 caracteres]
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

→ **Read**  `{"file_path": "<repo>/app/main.py"}`

### Mateus

```
1	"""A superfície HTTP.
2	
3	Implementa as nove rotas de `docs/openapi.yaml`, congelado na Fase 0. O que garante
4	que ele não vire documentação mentindo é `tests/nucleo/test_contrato_openapi.py`, que
5	compara nos **dois sentidos** — e é o segundo sentido, "toda rota gerada existe no
6	congelado", que pega superfície não documentada.
7	
8	Três decisões de exposição, todas de `CLAUDE.md` 14b/14c:
9	
10	- o compose publica em `127.0.0.1`, nunca em `0.0.0.0`. É o controle que de fato
11	  protege, e independe de autenticação;
12	- `ADMIN_TOKEN` é opcional: definido ⇒ exigido; ausente ⇒ sobe e avisa no log. Existe
13	  para que o achado do passe de segurança tenha resposta em código, desligada por
14	  padrão, em vez de "risco aceito" em prosa;
15	- `/docs`, `/redoc` e `/openapi.json` ficam **desligados** fora de desenvolvimento. O
16	  legado do desafio os expõe abertos; este serviço não repete esse default.
17	"""
18	
19	from __future__ import annotations
20	
21	import logging
22	import os
23	from contextlib import asynccontextmanager
24	
25	from fastapi import Depends, FastAPI, Header, HTTPException, Response
26	from fastapi.responses import JSONResponse
27	from sqlalchemy.orm impo
… [+7562 caracteres]
```

### Claude

→ **Grep**  `{"pattern": "carregar_env\\(", "output_mode": "content", "-n": true}`

### Mateus

```
app/bootstrap.py:15:- `carregar_env()` põe no `os.environ` as variáveis sem prefixo que o `.env` declara,
app/bootstrap.py:47:def carregar_env(caminho: Path | None = None) -> list[str]:
app/bootstrap.py:93:            "direto do ambiente. Por isso este processo chama carregar_env() no "
app/bootstrap.py:95:            "chave, ou carregar_env() não foi chamado.\n"
app/bootstrap.py:104:    carregar_env()
tests/nucleo/test_bootstrap.py:34:    assert carregar_env(env) == ["ANTHROPIC_API_KEY"]
tests/nucleo/test_bootstrap.py:43:    carregar_env(env)
tests/nucleo/test_bootstrap.py:53:    assert carregar_env(env) == []
tests/nucleo/test_bootstrap.py:58:    assert carregar_env(tmp_path / "nao-existe") == []
tests/nucleo/test_bootstrap.py:67:    assert carregar_env(env) == []
tests/nucleo/test_bootstrap.py:110:    carregar_env(env)
```

### Claude

Based on my review of the three touched files and their callers:

**app/agent/turno.py** — Refactor of the `enviar` closure into `_persistir`/`_confirmar`/`_entregar` primitives, plus a new `enviar_async` used on the async-loop paths (exception apology and model output). The deadlock warning it documents is real, and the change actually fixes it (the exception handler and model-output paths formerly used the thread-only `enviar`, which would have deadlocked when called from the loop thread). No new sinks, no new taint sources; the session `s` is still only touched from the tool thread in `_persistir`/`_confirmar` and never concurrently from the loop.

**app/bootstrap.py** — The `ESPELHADAS` mirror closes an actual auth-bypass: previously an `ADMIN_TOKEN` set in `.env` was not seen by `Settings`, so `admin_exigido` returned False and `/api/*` (protected via `exigir_admin`) came up unauthenticated. The mirror respects existing `os.environ` (won't override), only runs when the source key is in `SEM_PREFIXO`, and value-empty lines are still filtered by the pre-existing guard at line 63. Precedence logic is consistent with the rest of the file.

**tests/nucleo/test_bootstrap.py** — Test-only addition. Correctly resets both env vars before the assertion.

No injection sinks, no SSRF, no auth bypass, no dangerous deserialization, no PII/credential logging changes, no parser differentials, no cross-loop concurrent session access, no fail-open regressions. The changes are net security-positive.

### Claude

→ **StructuredOutput**  `{"findings": []}`

### Mateus

```
Structured output provided successfully
```
