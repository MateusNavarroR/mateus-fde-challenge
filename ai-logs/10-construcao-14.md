# Sessão de construção 14

> Exportado por `scripts/exportar_ai_logs.py`, com redação de segredo,
> caminho absoluto e PII **na escrita**. 27 turnos; o `jsonl` de
> origem tinha 382 KB, majoritariamente saída de
> ferramenta, truncada em 1200 caracteres por bloco.

### Mateus

Review this change for security vulnerabilities.

Changed files (you may Read these and any other file in the repo):
  - app/agent/agente.py
  - app/agent/tools.py
  - app/agent/turno.py
  - app/auth.py
  - app/contracts/conversa.py
  - app/handoff/gatilhos.py
  - app/main.py
  - app/persistence/models.py
  - db/migrations/0003_handoff_trigger.sql
  - tests/nucleo/test_handoff.py

Unified diff (only + lines are new):

=== DIFF: app/agent/agente.py ===
@@ -22,7 +22,12 @@ from agno.db.postgres import PostgresDb
 
 from app.agent.catalogo import carregar_catalogo
 from app.agent.prompt import construir_bloco_volatil, construir_system
-from app.agent.tools import ContextoDoTurno, make_qualify_lead, make_quote_plan
+from app.agent.tools import (
+    ContextoDoTurno,
+    make_escalate_to_human,
+    make_qualify_lead,
+    make_quote_plan,
+)
 from app.config import get_settings
 from app.contracts.conversa import LeadProfile
 from app.persistence import repo
@@ -63,7 +68,11 @@ def _perfil(ctx: ContextoDoTurno) -> LeadProfile:
 def construir_agente(ctx: ContextoDoTurno) -> Agent:
     cfg = get_settings()
     system = construir_system(catalogo_do_processo())
-    tools = [make_qualify_lead(ctx), make_quote_plan(ctx)]
+    tools = [
+        make_qualify_lead(ctx),
+        make_quote_plan(ctx),
+        make_escalate_to_human(ctx),
+    ]
 
     if cfg.llm_model.startswith("anthropic:"):
         from agno.models.anthropic import Claude, SystemPromptBlock


=== DIFF: app/agent/tools.py ===
@@ -112,6 +112,16 @@ class ContextoDoTurno:
     #: A tool já falou com o lead neste turno ⇒ o texto do modelo é descartado.
     ja_enviou: bool = False
 
+    #: Contadores que os gatilhos de handoff leem. Por CAMPO, não global: falhar uma
+    #: vez no CEP e uma na idade não é "falhou duas vezes".
+    tentativas_extracao: dict[str, int] = field(default_factory=dict)
+    objecoes_de_preco: int = 0
+
+    #: Contadores que os gatilhos de handoff leem. Por CAMPO, não global: falhar uma
+    #: vez no CEP e uma na idade não é "falhou duas vezes".
+    tentativas_extracao: dict[str, int] = field(default_factory=dict)
+    objecoes_de_preco: int = 0
+
 
 def make_qualify_lead(ctx: ContextoDoTurno) -> Callable[..., str]:
     def qualify_lead(
@@ -167,6 +177,8 @@ def make_qualify_lead(ctx: ContextoDoTurno) -> Callable[..., str]:
 
         for campo in rejeitados:
             perfil.tentativas_extracao[campo] = perfil.tentativas_extracao.get(campo, 0) + 1
+            ctx.tentativas_extracao[campo] = ctx.tentativas_extracao.get(campo, 0) + 1
+            ctx.tentativas_extracao[campo] = ctx.tentativas_extracao.get(campo, 0) + 1
 
         _gravar_perfil(ctx, perfil)
 
@@ -311,9 +323,13 @@ def make_quote_plan(ctx: ContextoDoTurno) -> Callable[..., str]:
 
         # `failed`: o handoff é criado pela fatia 5; aqui a mensagem já sai.
         enviar(textos.compor_handoff("cotacao_indisponivel"))
-        ctx.handoffs.append({"trigger": "cotacao_indisponivel",
-                             "reason": "job de cotação terminou failed",
-                             "quote_id": q.id})
+        from app.contracts.conversa import HandoffTrigger
+
+        ctx.handoffs.append({
+            "trigger": HandoffTrigger.COTACAO_INDISPONIVEL,
+            "reason": "a cotação não respondeu depois de esgotadas as tentativas",
+            "quote_id": q.id, "disparado_por": "regra", "assunto": None,
+        })
         return ("indisponivel. O lead JÁ FOI avisado e um atendente foi acionado. "
                 "Encerre o turno.")
 
@@ -326,3 +342,50 @@ def _campo_do_erro(e: Exception) -> str:
     if isinstance(e, DataAmbigua):
         return "data_inicio"
     return "desconhecido"
+
+
+# ─── escalate_to_human: write-back ───────────────────────────────────────────
+
+
+def make_escalate_to_human(ctx: ContextoDoTurno) -> Callable[..., str]:
+    """Padrão **write-back**: a tool só registra a intenção; quem executa é o backend.
+
+    Isso mantém o comportamento testável e impede o modelo de causar efeito colateral
+    direto. E é o que faz um gatilho determinístico — breaker aberto, job `failed` —
+    produzir **exatamente o mesmo sinal** que uma decisão do modelo, distinguidos só
+    por `disparado_por`.
+    """
+
+    def escalate_to_human(trigger: str, reason: str, summary: str = "") -> str:
+        """Passa a conversa para um atendente humano.
+
+        Use quando o lead pedir uma pessoa, quando o assunto for sensível (sinistro,
+        jurídico, saúde, reclamação formal), ou quando você não conseguir ajudar.
+
+        Args:
+            trigger: um de `assunto_sensivel`, `lead_pediu_atendente`,
+                `objecao_fora_da_alcada`, `midia_sem_texto`, `extracao_falhou`.
+            reason: por que, em uma frase, para o atendente.
+            summary: resumo curto da conversa até aqui.
+
+        Returns:
+            str: confirmação interna. **Não repasse ao lead** — a mensagem de
+            encaminhamento já foi enviada pelo sistema. Encerre o turno.
+        """
+        from app.contracts.conversa import HandoffTrigger
+
+        try:
+            t = HandoffTrigger(trigger)
+        except ValueError:
+            return (f"trigger inválido: {trigger!r}. Use um de "
+                    f"{', '.join(str(x) for x in HandoffTrigger)}.")
+
+        ctx.handoffs.append({
+            "trigger": t, "reason": reason or "decisão do agente",
+            "summary": summary.strip() or None, "disparado_por": "modelo",
+            "assunto": None,
+        })
+        return ("encaminhado. A mensagem JÁ FOI ENVIADA ao lead pelo sistema. "
+                "Não repita nem prometa prazo — encerre o turno.")
+
+    return escalate_to_human


=== DIFF: app/agent/turno.py ===
@@ -77,6 +77,18 @@ async def responder(
             await _entregar(m, autor)
             _confirmar(m)
 
+        conv = repo.obter_conversa(s, conversation_id)
+        if conv is not None and conv.state == "encaminhado":
+            # `encaminhado` é terminal: o agente parou de responder. A mensagem do
+            # lead fica persistida — ela é do operador, não nossa para responder.
+            return
+
+        conv = repo.obter_conversa(s, conversation_id)
+        if conv is not None and conv.state == "encaminhado":
+            # `encaminhado` é TERMINAL: o agente parou de responder. A mensagem do
+            # lead fica persistida — ela é do operador, não nossa para responder.
+            return
+
         ctx = ContextoDoTurno(
             sessao=s,
             conversation_id=conversation_id,
@@ -98,6 +110,9 @@ async def responder(
 
         _gravar_uso(s, conversation_id, r)
 
+        if await _encaminhar(s, conversation_id, ctx, texto, enviar_async):
+            return
+
         if ctx.ja_enviou:
             # A tool já disse tudo o que o lead precisava. O texto do modelo vai fora.
             return
@@ -113,6 +128,115 @@ async def responder(
             log.warning("guardrail: %s", e.motivo)
 
 
+async def _encaminhar(s, conversation_id: str, ctx, texto: str, enviar_async) -> bool:
+    """Avalia os sete gatilhos e, se algum casar, encaminha.
+
+    As duas origens convergem aqui: o que o **modelo** pediu por `escalate_to_human`
+    (write-back em `ctx.handoffs`) e o que a **regra** detectou no turno. Elas
+    produzem o mesmo sinal, e `disparado_por` é a única diferença.
+    """
+    from app import textos
+    from app.contracts.conversa import HandoffTrigger
+    from app.handoff import gatilhos
+
+    perfil = repo.obter_conversa(s, conversation_id)
+    contexto = gatilhos.Contexto(
+        texto_do_lead=texto,
+        cotacao_falhou=any(
+            h.get("trigger") is HandoffTrigger.COTACAO_INDISPONIVEL for h in ctx.handoffs
+        ),
+        tentativas_extracao=ctx.tentativas_extracao,
+        objecoes_de_preco=ctx.objecoes_de_preco,
+    )
+    avaliado = gatilhos.avaliar(contexto)
+
+    # O pedido do modelo entra na disputa com a mesma precedência das regras.
+    do_modelo = next((h for h in ctx.handoffs if h.get("disparado_por") == "modelo"), None)
+
+    if avaliado is None and do_modelo is None:
+        return False
+
+    if avaliado is not None:
+        trigger, motivo, secundarios = avaliado
+        origem = "regra"
+        quote_id = next((h.get("quote_id") for h in ctx.handoffs if h.get("quote_id")), None)
+        resumo = None
+    else:
+        trigger, motivo = do_modelo["trigger"], do_modelo["reason"]
+        secundarios, origem = [], "modelo"
+        quote_id, resumo = do_modelo.get("quote_id"), do_modelo.get("summary")
+
+    gatilhos.registrar(
+        s, conversation_id, trigger, motivo,
+        secundarios=secundarios, summary=resumo, quote_id=quote_id,
+        disparado_por=origem,
+    )
+    s.commit()
+
+    # A mensagem de indisponibilidade já saiu de dentro da tool; repeti-la seria
+    # dizer duas vezes a mesma coisa.
+    if trigger is not HandoffTrigger.COTACAO_INDISPONIVEL:
+        await enviar_async(
+            textos.compor_handoff(str(trigger),
+                                  assunto=gatilhos.assunto_do_texto(texto))
+        )
+    return True
+
+
+async def _encaminhar(s, conversation_id: str, ctx, texto: str, enviar_async) -> bool:
+    """Avalia os sete gatilhos e, se algum casar, encaminha.
+
+    As duas origens convergem aqui: o que o **modelo** pediu por `escalate_to_human`
+    (write-back em `ctx.handoffs`) e o que a **regra** detectou no turno. Elas
+    produzem o mesmo sinal, e `disparado_por` é a única diferença — que é
+    exatamente o ponto do padrão write-back.
+    """
+    from app import textos
+    from app.contracts.conversa import HandoffTrigger
+    from app.handoff import gatilhos
+
+    contexto = gatilhos.Contexto(
+        texto_do_lead=texto,
+        cotacao_falhou=any(
+            h.get("trigger") is HandoffTrigger.COTACAO_INDISPONIVEL for h in ctx.handoffs
+        ),
+        tentativas_extracao=ctx.tentativas_extracao,
+        objecoes_de_preco=ctx.objecoes_de_preco,
+    )
+    avaliado = gatilhos.avaliar(contexto)
+    do_modelo = next((h for h in ctx.handoffs if h.get("disparado_por") == "modelo"), None)
+
+    if avaliado is None and do_modelo is None:
+        return False
+
+    if avaliado is not None:
+        trigger, motivo, secundarios = avaliado
+        origem = "regra"
+        quote_id = next((h.get("quote_id") for h in ctx.handoffs if h.get("quote_id")), None)
+        resumo = None
+    else:
+        trigger = do_modelo["trigger"]
+        motivo, secundarios, origem = do_modelo["reason"], [], "modelo"
+        quote_id, resumo = do_modelo.get("quote_id"), do_modelo.get("summary")
+
+    gatilhos.registrar(
+        s, conversation_id, trigger, motivo,
+        secundarios=secundarios, summary=resumo, quote_id=quote_id,
+        disparado_por=origem,
+    )
+    s.commit()
+
+    # A mensagem de indisponibilidade já saiu de dentro da tool de cotação;
+    # repeti-la aqui seria dizer duas vezes a mesma coisa ao lead.
+    if trigger is not HandoffTrigger.COTACAO_INDISPONIVEL:
+        await enviar_async(
+            textos.compor_handoff(str(trigger), assunto=gatilhos.assunto_do_texto(texto))
+        )
+    else:
+        await enviar_async(textos.DESPEDIDA)
+    return True
+
+
 def _gravar_uso(s, conversation_id: str, r) -> None:
     """Custo e uso por turno. Substitui o Langfuse: fica na própria base."""
     from app.persistence.uso import gravar_turn_usage


=== DIFF: app/auth.py ===
@@ -0,0 +1,346 @@
+"""A autenticação da área de operação — sessão em cookie, senha nunca em texto puro.
+
+**O problema.** `ADMIN_TOKEN` (CLAUDE.md 14c) é um mecanismo de máquina: um segredo
+único, colado num cabeçalho. Serve a `curl` e a CI, e é péssimo para uma pessoa —
+quem abre `/admin` no navegador não tem onde digitar um cabeçalho, e a solução que
+existia era guardar o token no `localStorage`, que é exatamente onde um XSS o lê.
+
+Esta camada acrescenta o mecanismo de **gente**: usuário e senha, sessão em cookie
+`httpOnly`. Ela **não substitui** o token — os dois convivem, e a ordem está em
+`exigir_admin`.
+
+**Cinco restrições, e todas nascem de o repositório ser público** (CLAUDE.md 13):
+
+1. *Nenhuma credencial no código.* Nem constante, nem default de `Settings`, nem
+   fixture, nem exemplo copiável. `ADMIN_USER` e `ADMIN_PASSWORD` vêm do ambiente e
+   **não têm valor padrão**. Um default aqui seria um achado autoinfligido no
+   `insecure-defaults@trailofbits` — num critério que é justamente sobre cuidado com
+   dados.
+2. *Sem as duas variáveis, o login não existe e `/admin` abre direto*, como antes.
+   Isso preserva o item 14: o caminho de um comando não muda, e quem sobe o compose
+   vê tudo sem procurar senha. A proteção efetiva no caminho padrão continua sendo o
+   bind em `127.0.0.1` (14b), que não depende de autenticação nenhuma.
+3. *A senha nunca é comparada nem guardada em texto puro.* No boot ela é derivada com
+   `hashlib.scrypt` e um salt aleatório do processo, e o texto puro é **apagado do
+   `os.environ`** logo em seguida — para que nem um `/debug` acidental, nem um
+   subprocesso herdado, nem um dump de ambiente o encontrem.
+4. *Comparação em tempo constante*, com `hmac.compare_digest`, e para **os dois**
+   campos. Comparar o usuário com `==` vazaria, por tempo, se aquele nome existe.
+5. *A sessão vive num cookie `httpOnly`, `SameSite=Strict`, `Secure` fora de dev.*
+   Nada em `localStorage`: o ponto de trocar o token pela senha era tirar o segredo
+   do alcance do JavaScript da página.
+
+**A sessão não tem armazenamento.** O cookie carrega `usuario|expiração` assinado por
+HMAC com uma chave derivada do próprio hash da senha. Consequências desejadas: trocar
+a senha invalida toda sessão viva, e reiniciar o processo também — o custo é um login
+depois do `docker compose restart`, e o benefício é não haver tabela de sessão para
+crescer, vazar ou dessincronizar.
+
+Sem dependência nova: `hashlib`, `hmac` e `secrets` são da biblioteca padrão.
+"""
+
+from __future__ import annotations
+
+import base64
+import hashlib
+import hmac
+import logging
+import os
+import secrets
+import time
+from dataclasses import dataclass
+
+from fastapi import Cookie, FastAPI, Header, HTTPException, Response
+from pydantic import BaseModel, Field
+
+log = logging.getLogger("autoseguro")
+
+#: Nome do cookie de sessão. Prefixo do projeto para não colidir com outra coisa
+#: servida do mesmo host em desenvolvimento.
+COOKIE_SESSAO = "autoseguro_sessao"
+
+#: Oito horas: um turno. Mais que isso é uma sessão que sobrevive à pessoa sair da
+#: mesa; muito menos é login no meio de uma investigação de handoff.
+VALIDADE_S = 8 * 60 * 60
+
+#: Parâmetros do `scrypt`. N=2^14 com r=8 usa ~16 MiB e leva dezenas de milissegundos
+#: — caro o bastante para uma tentativa por vez ser lenta em força bruta, barato o
+#: bastante para não ser ele o DoS. São os valores de referência do RFC 7914.
+_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}
+
+#: As três rotas desta camada. Elas ficam **fora** do OpenAPI congelado de propósito,
+#: e a lista existe para que essa exceção seja nominal e fechada — é o que
+#: `tests/nucleo/test_auth.py` verifica, para que `include_in_schema=False` não vire
+#: uma porta por onde superfície não documentada entra em silêncio.
+ROTAS_FORA_DO_CONTRATO = (
+    ("/api/auth/estado", "GET"),
+    ("/api/auth/login", "POST"),
+    ("/api/auth/logout", "POST"),
+)
+
+#: Mensagem única para usuário inexistente e senha errada. Distinguir os dois casos
+#: entrega ao atacante metade do trabalho — e não ajuda em nada quem só errou.
+FALHA = "usuário ou senha inválidos"
+
+
+def _dev() -> bool:
+    """`Secure` no cookie exige HTTPS; em desenvolvimento o serviço é HTTP puro e um
+    cookie `Secure` simplesmente não voltaria — o login pareceria quebrado."""
+    return os.getenv("APP_ENV", "dev") == "dev"
+
+
+@dataclass(frozen=True)
+class Credencial:
+    """O que sobra da senha depois do boot: nunca ela mesma."""
+
+    usuario: str
+    salt: bytes
+    digest: bytes
+
+    def confere(self, usuario: str, senha: str) -> bool:
+        """Tempo constante nos dois campos, e **sem curto-circuito**.
+
+        Um `and` entre as duas comparações deixaria de derivar o hash quando o usuário
+        não bate, e a diferença de tempo (dezenas de milissegundos do `scrypt`) diria
+        ao atacante que aquele nome existe. Por isso as duas linhas são avaliadas
+        sempre, e só depois combinadas.
+        """
+        nome_ok = hmac.compare_digest(usuario.encode("utf-8"), self.usuario.encode("utf-8"))
+        senha_ok = hmac.compare_digest(_derivar(senha, self.salt), self.digest)
+        return nome_ok & senha_ok
+
+    @property
+    def chave_de_sessao(self) -> bytes:
+        """Chave HMAC da assinatura do cookie, derivada do hash — **nunca** da senha.
+
+        Vem do digest com um rótulo de domínio, então: nada que assine um cookie pode
+        ser reusado para conferir uma senha, e trocar a senha muda a chave, o que
+        invalida toda sessão viva sem precisar de uma lista de revogação.
+        """
+        return hashlib.sha256(b"autoseguro/sessao/v1|" + self.salt + self.digest).digest()
+
+
+def _derivar(senha: str, salt: bytes) -> bytes:
+    return hashlib.scrypt(senha.encode("utf-8"), salt=salt, **_SCRYPT)
+
+
+_credencial: Credencial | None = None
+_lida = False
+
+
+def redefinir_credenciais() -> Credencial | None:
+    """Lê o ambiente, deriva o hash e **apaga a senha em texto puro do processo**.
+
+    Chamada uma vez no boot e explicitamente pelos testes. Devolve `None` — o modo
+    aberto — quando qualquer uma das duas variáveis está ausente ou vazia: exigir
+    usuário sem senha, ou senha sem usuário, seria uma meia-autenticação pior que
+    nenhuma, porque pareceria protegida.
+    """
+    global _credencial, _lida
+
+    usuario = (os.getenv("ADMIN_USER") or "").strip()
+    senha = os.getenv("ADMIN_PASSWORD") or ""
+
+    _lida = True
+    if not usuario or not senha:
+        _credencial = None
+        return None
+
+    salt = secrets.token_bytes(16)
+    _credencial = Credencial(usuario=usuario, salt=salt, digest=_derivar(senha, salt))
+
+    # A partir daqui a senha não existe mais neste processo. `del` no environ também
+    # a remove do ambiente herdado por qualquer subprocesso.
+    os.environ.pop("ADMIN_PASSWORD", None)
+    os.environ.pop("APP_ADMIN_PASSWORD", None)
+    del senha
+
+    return _credencial
+
+
+def credencial() -> Credencial | None:
+    """A credencial ativa, ou `None` quando o login não está configurado."""
+    if not _lida:
+        redefinir_credenciais()
+    return _credencial
+
+
+def login_configurado() -> bool:
+    return credencial() is not None
+
+
+# ─── a sessão assinada ───────────────────────────────────────────────────────
+
+
+def _b64(dados: bytes) -> str:
+    return base64.urlsafe_b64encode(dados).decode("ascii").rstrip("=")
+
+
+def _desb64(texto: str) -> bytes:
+    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))
+
+
+def emitir_sessao(cred: Credencial, agora: float | None = None) -> str:
+    exp = int((agora if agora is not None else time.time()) + VALIDADE_S)
+    corpo = f"{cred.usuario}|{exp}".encode("utf-8")
+    assinatura = hmac.new(cred.chave_de_sessao, corpo, hashlib.sha256).digest()
+    return f"{_b64(corpo)}.{_b64(assinatura)}"
+
+
+def sessao_valida(token: str | None, agora: float | None = None) -> bool:
+    """Verifica assinatura **antes** de olhar o conteúdo, e nunca levanta.
+
+    Um cookie é entrada de rede: qualquer coisa pode chegar aqui, e o caminho de
+    rejeição precisa ser o mesmo para lixo, para assinatura errada e para expirado.
+    """
+    cred = credencial()
+    if cred is None or not token:
+        return False
+    try:
+        parte_corpo, _, parte_sig = token.partition(".")
+        if not parte_sig:
+            return False
+        corpo = _desb64(parte_corpo)
+        esperada = hmac.new(cred.chave_de_sessao, corpo, hashlib.sha256).digest()
+        if not hmac.compare_digest(_desb64(parte_sig), esperada):
+            return False
+        usuario, _, exp = corpo.decode("utf-8").rpartition("|")
+        if usuario != cred.usuario:
+            return False
+        return int(exp) > (agora if agora is not None else time.time())
+    except Exception:  # noqa: BLE001 - entrada de rede: rejeita, não explode
+        return False
+
+
+def _gravar_cookie(resposta: Response, token: str) -> None:
+    resposta.set_cookie(
+        COOKIE_SESSAO,
+        token,
+        max_age=VALIDADE_S,
+        httponly=True,
+        samesite="strict",
+        secure=not _dev(),
+        path="/",
+    )
+
+
+# ─── a porta ─────────────────────────────────────────────────────────────────
+
+
+def exigir_admin(
+    autoseguro_sessao: str | None = Cookie(default=None),
+    x_admin_token: str | None = Header(default=None),
+) -> None:
+    """A dependência das rotas de operação. **Três modos, nesta ordem:**
+
+    1. `ADMIN_USER` + `ADMIN_PASSWORD` definidos ⇒ exige sessão válida (ou, para
+       máquina, o `ADMIN_TOKEN` quando este também estiver definido);
+    2. só `ADMIN_TOKEN` definido ⇒ o comportamento de sempre (CLAUDE.md 14c);
+    3. nenhum dos dois ⇒ aberto, e o boot avisa no log.
+
+    O token continua valendo com o login ligado porque ele é o caminho de CI e de
+    `curl`: tirá-lo quebraria automação para não ganhar nada — quem tem o token já
+    teria acesso pelos dois caminhos de qualquer forma.
+    """
+    from app.config import get_settings
+
+    cfg = get_settings()
+    token_ok = cfg.admin_exigido and hmac.compare_digest(
+        (x_admin_token or "").encode("utf-8"), (cfg.admin_token or "").encode("utf-8")
+    )
+
+    if login_configurado():
+        if sessao_valida(autoseguro_sessao) or token_ok:
+            return
+        raise HTTPException(status_code=401, detail="sessão de operação ausente ou expirada")
+
+    if cfg.admin_exigido and not token_ok:
+        raise HTTPException(status_code=401, detail="token de admin inválido ou ausente")
+
+
+# ─── as rotas ────────────────────────────────────────────────────────────────
+
+
+class Entrada(BaseModel):
+    usuario: str = Field(max_length=200)
+    senha: str = Field(max_length=1024)
+
+
+class EstadoAuth(BaseModel):
+    """O que a tela precisa saber antes de decidir se mostra o login.
+
+    Nunca inclui o nome do usuário configurado: quem ainda não entrou não tem por que
+    receber metade da credencial de presente.
+    """
+
+    exigido: bool
+    autenticado: bool
+
+
+def registrar_autenticacao(app: FastAPI) -> None:
+    """Monta as três rotas.
+
+    **`include_in_schema=False` é deliberado**, pelo mesmo motivo de `GET /`: o
+    `docs/openapi.yaml` foi congelado na Fase 0 como o contrato do produto, e
+    `tests/nucleo/test_contrato_openapi.py` o defende nos dois sentidos. Estas rotas
+    não são produto — são o mecanismo pelo qual um humano alcança o produto, e
+    reabrir o congelado para acomodá-las trocaria uma decisão escrita por um conserto
+    de teste.
+
+    Para que a exclusão não vire uma porta aberta, ela é **nominal e fechada**:
+    `ROTAS_FORA_DO_CONTRATO` lista exatamente estas três, e `tests/nucleo/test_auth.py`
+    falha se aparecer uma quarta rota escondida do schema.
+    """
+
+    @app.get("/api/auth/estado", include_in_schema=False, response_model=EstadoAuth)
+    def estado(autoseguro_sessao: str | None = Cookie(default=None)) -> EstadoAuth:
+        return EstadoAuth(
+            exigido=login_configurado(),
+            autenticado=(not login_configurado()) or sessao_valida(autoseguro_sessao),
+        )
+
+    @app.post("/api/auth/login", include_in_schema=False, status_code=204)
+    def login(corpo: Entrada, resposta: Response) -> Response:
+        cred = credencial()
+        if cred is None:
+            # Sem login configurado não há o que autenticar — e responder 200 aqui
+            # faria a tela acreditar numa sessão que não existe.
+            raise HTTPException(status_code=404, detail="esta instalação não exige login")
+
+        if not cred.confere(corpo.usuario, corpo.senha):
+            # Só o nome entra no log, e ainda assim truncado. A senha não é logada em
+            # lugar nenhum, nem em `debug`, nem no corpo da resposta — é o que
+            # `test_auth.py` verifica, porque "não logar senha" é uma promessa que
+            # ninguém quebra de propósito e todo mundo quebra por descuido.
+            log.warning("tentativa de login recusada para %r", corpo.usuario[:32])
+            raise HTTPException(status_code=401, detail=FALHA)
+
+        _gravar_cookie(resposta, emitir_sessao(cred))
+        resposta.status_code = 204
+        return resposta
+
+    @app.post("/api/auth/logout", include_in_schema=False, status_code=204)
+    def logout(resposta: Response) -> Response:
+        # Os mesmos atributos da gravação: um `delete_cookie` com `path` ou `samesite`
+        # diferentes deixa o cookie original vivo no navegador.
+        resposta.delete_cookie(
+            COOKIE_SESSAO, path="/", httponly=True, samesite="strict", secure=not _dev()
+        )
+        resposta.status_code = 204
+        return resposta
+
+
+def aviso_de_boot() -> str | None:
+    """A frase que o `lifespan` registra. `None` quando há alguma proteção ativa."""
+    from app.config import get_settings
+
+    if login_configurado():
+        return None
+    if get_settings().admin_exigido:
+        return None
+    return (
+        "Sem ADMIN_USER/ADMIN_PASSWORD e sem ADMIN_TOKEN: /api/* está sem "
+        "autenticação. A proteção efetiva é o bind em 127.0.0.1 do "
+        "docker-compose.yml. Defina ADMIN_USER e ADMIN_PASSWORD para exigir login, "
+        "ou ADMIN_TOKEN para exigir o cabeçalho X-Admin-Token."
+    )


=== DIFF: app/contracts/conversa.py ===
@@ -158,22 +158,36 @@ class ConversationState(StrEnum):
 
 
 class HandoffTrigger(StrEnum):
-    """Gatilhos de handoff, como dados e não como `if` espalhado.
+    """Os sete gatilhos de handoff, como dados e não como `if` espalhado.
 
-    ⚠️ **Conjunto provisório.** A tabela definitiva — quais gatilhos, qual precedência
-    e o que o bot diz em cada um — é uma das quatro decisões abertas do usuário
-    (`docs/DECISOES-ABERTAS.md`). Este enum existe para que as outras frentes tenham
-    contra o que compilar; ele é substituído pela decisão fechada.
+    **A ordem da declaração É a precedência.** Quando dois disparam no mesmo turno,
+    o primeiro vence e os demais são gravados como secundários — a fila mostra um
+    gatilho, o operador vê o quadro completo.
+
+    O critério é **o custo de o agente errar ali**: custo alto encaminha na hora e
+    sem tentar; custo baixo tenta e encaminha na segunda vez.
+
+    ⚠️ `COTACAO_RECUSADA` **foi removido**. Ele existia na Fase 0, antes de a decisão
+    3 fechar, e é justamente o que `DECISOES-FECHADAS.md` §3 lista sob "não são
+    gatilhos": recusa não cria handoff, porque um humano releria a mesma regra fixa
+    em `plans.json` e daria o mesmo "não". Encaminhar 30% do tráfego para isso
+    encheria a fila com casos sem saída.
     """
 
+    #: custo alto — encaminha imediato, sem tentar responder
+    ASSUNTO_SENSIVEL = "assunto_sensivel"
+    #: custo alto — encerra e registra
+    GUARDRAIL = "guardrail"
+    #: pedido explícito
     LEAD_PEDIU = "lead_pediu_atendente"
+    #: custo alto — o job de cotação terminou `failed`
     COTACAO_INDISPONIVEL = "cotacao_indisponivel"
-    COTACAO_RECUSADA = "cotacao_recusada"
+    #: custo médio — 2ª falha de extração no MESMO campo
     EXTRACAO_FALHOU = "extracao_falhou"
-    ASSUNTO_SENSIVEL = "assunto_sensivel"
+    #: custo baixo — o lead REPETE a objeção de preço
     OBJECAO_FORA_DA_ALCADA = "objecao_fora_da_alcada"
+    #: custo baixo — o lead INSISTE em mídia depois de pedirmos texto
     MIDIA_SEM_TEXTO = "midia_sem_texto"
-    GUARDRAIL = "guardrail"
 
 
 class HandoffStatus(StrEnum):


=== DIFF: app/handoff/gatilhos.py ===
@@ -0,0 +1,166 @@
+"""Os sete gatilhos de handoff — como dados, não como `if` espalhado.
+
+É isso que torna o critério "explícito e defensável", que é o texto do enunciado. O
+que reprova não é ser generoso ou econômico com a fila: é o gatilho implícito, que
+ninguém consegue enumerar nem testar.
+
+**O critério é o custo de o agente errar ali.** Custo alto encaminha na hora e sem
+tentar responder; custo baixo tenta e encaminha na segunda vez. Não é "quantos casos
+cobrir" — é onde o erro é caro.
+
+**Precedência = ordem da declaração.** Primeiro que casa vence; os demais que casaram
+no mesmo turno viram `gatilhos_secundarios`. A fila mostra um gatilho — o que mantém
+a regra testável, uma linha por gatilho — sem que o operador perca o quadro completo.
+
+**Não são gatilhos**, e cada ausência é uma decisão:
+
+- **recusa 422** — 30% do tráfego. Um humano releria a mesma regra fixa em
+  `plans.json` e daria o mesmo "não";
+- **falha isolada da `/quote` que o retry resolveu** — 20% dos jobs; encaminhar aí
+  encheria a fila com o que se resolve sozinho em 96% dos casos;
+- **primeira objeção de preço** e **primeira mídia** — o agente tenta uma vez.
+"""
+
+from __future__ import annotations
+
+import re
+import uuid
+from dataclasses import dataclass
+
+from sqlalchemy.orm import Session
+
+from app.contracts.conversa import HandoffTrigger
+from app.persistence.models import Conversation, Handoff
+
+#: Assuntos que separam o prefixo de texto: sinistro e saúde pedem empatia, jurídico
+#: e reclamação pedem neutralidade. "Sinto muito" numa notificação extrajudicial soa
+#: como admissão; a ausência dele depois de "bati o carro" soa como frieza.
+_SINISTRO = re.compile(
+    r"\b(bati|batida|colidi|colis[ãa]o|acidente|sinistro|capot|roubaram|furtaram|"
+    r"levaram meu carro|atropel|ferid|machuc|hospital|ambul[âa]ncia|m[ée]dic)\w*",
+    re.IGNORECASE,
+)
+_JURIDICO = re.compile(
+    r"\b(advogad|processo|processar|judicial|extrajudicial|procon|reclama[çc][ãa]o|"
+    r"intima[çc][ãa]o|not[ií]fica[çc][ãa]o|ju[ií]z|tribunal|indeniza[çc][ãa]o)\w*",
+    re.IGNORECASE,
+)
+_PEDIU_ATENDENTE = re.compile(
+    r"\b(atendente|humano|pessoa de verdade|falar com algu[ée]m|uma pessoa|"
+    r"supervisor|ger[êe]nte|prefiro falar com)\b",
+    re.IGNORECASE,
+)
+_OBJECAO_PRECO = re.compile(
+    r"\b(caro|salgad|abusiv|apertad|n[ãa]o cabe no bolso|fora do or[çc]amento|"
+    r"desconto|mais barato|baratinho|pesou)\w*",
+    re.IGNORECASE,
+)
+
+
+@dataclass(frozen=True)
+class Contexto:
+    """O que os gatilhos leem. Nada aqui vem de argumento de tool."""
+
+    texto_do_lead: str = ""
+    tipo_da_mensagem: str = "text"
+    #: O job de cotação terminou `failed` neste turno.
+    cotacao_falhou: bool = False
+    #: Violações de guardrail acumuladas nesta conversa.
+    violacoes_guardrail: int = 0
+    #: Quantas vezes cada campo já foi rejeitado na extração.
+    tentativas_extracao: dict[str, int] | None = None
+    #: Quantas vezes o lead já objetou preço, incluindo agora.
+    objecoes_de_preco: int = 0
+    #: Quantas mensagens de mídia o lead mandou depois de pedirmos texto.
+    midias_apos_pedido: int = 0
+
+
+def _assunto_sensivel(c: Contexto) -> str | None:
+    if _SINISTRO.search(c.texto_do_lead):
+        return "sinistro"
+    if _JURIDICO.search(c.texto_do_lead):
+        return "juridico"
+    return None
+
+
+#: A ordem desta lista É a precedência. Mudar a ordem muda o comportamento, e é por
+#: isso que ela é dado e não uma cadeia de `if`.
+REGRAS: list[tuple[HandoffTrigger, str]] = [
+    (HandoffTrigger.ASSUNTO_SENSIVEL, "assunto que exige uma pessoa: sinistro, saúde, jurídico ou reclamação"),
+    (HandoffTrigger.GUARDRAIL, "violação de guardrail repetida na conversa"),
+    (HandoffTrigger.LEAD_PEDIU, "o lead pediu para falar com uma pessoa"),
+    (HandoffTrigger.COTACAO_INDISPONIVEL, "a cotação não respondeu depois de esgotadas as tentativas"),
+    (HandoffTrigger.EXTRACAO_FALHOU, "não consegui ler o mesmo campo duas vezes"),
+    (HandoffTrigger.OBJECAO_FORA_DA_ALCADA, "o lead repetiu a objeção de preço"),
+    (HandoffTrigger.MIDIA_SEM_TEXTO, "o lead insistiu em mídia depois de pedirmos por texto"),
+]
+
+
+def casa(trigger: HandoffTrigger, c: Contexto) -> bool:
+    """Uma função por gatilho, para que cada um tenha um teste seu."""
+    if trigger is HandoffTrigger.ASSUNTO_SENSIVEL:
+        return _assunto_sensivel(c) is not None
+    if trigger is HandoffTrigger.GUARDRAIL:
+        # A primeira violação descarta a mensagem e conta; a segunda encaminha.
+        return c.violacoes_guardrail >= 2
+    if trigger is HandoffTrigger.LEAD_PEDIU:
+        return bool(_PEDIU_ATENDENTE.search(c.texto_do_lead))
+    if trigger is HandoffTrigger.COTACAO_INDISPONIVEL:
+        return c.cotacao_falhou
+    if trigger is HandoffTrigger.EXTRACAO_FALHOU:
+        # Por CAMPO, não global: falhar uma vez no CEP e uma na idade não é
+        # "falhou duas vezes".
+        return any(n >= 2 for n in (c.tentativas_extracao or {}).values())
+    if trigger is HandoffTrigger.OBJECAO_FORA_DA_ALCADA:
+        return c.objecoes_de_preco >= 2 and bool(_OBJECAO_PRECO.search(c.texto_do_lead))
+    if trigger is HandoffTrigger.MIDIA_SEM_TEXTO:
+        return c.tipo_da_mensagem != "text" and c.midias_apos_pedido >= 2
+    return False
+
+
+def avaliar(c: Contexto) -> tuple[HandoffTrigger, str, list[HandoffTrigger]] | None:
+    """Devolve `(gatilho, motivo, secundários)` ou `None`.
+
+    O primeiro que casa vence. Os demais não se perdem: viram secundários.
+    """
+    casaram = [(t, motivo) for t, motivo in REGRAS if casa(t, c)]
+    if not casaram:
+        return None
+    principal, motivo = casaram[0]
+    return principal, motivo, [t for t, _ in casaram[1:]]
+
+
+def registrar(
+    s: Session,
+    conversation_id: str,
+    trigger: HandoffTrigger,
+    reason: str,
+    *,
+    secundarios: list[HandoffTrigger] | None = None,
+    summary: str | None = None,
+    quote_id: str | None = None,
+    disparado_por: str = "regra",
+) -> Handoff:
+    """Cria o handoff e move a conversa para `encaminhado`, que é terminal."""
+    h = Handoff(
+        id=f"ho_{uuid.uuid4().hex[:16]}",
+        conversation_id=conversation_id,
+        trigger=str(trigger),
+        reason=reason,
+        summary=summary,
+        disparado_por=disparado_por,
+        quote_id=quote_id,
+        status="pendente",
+        gatilhos_secundarios=[str(t) for t in (secundarios or [])],
+    )
+    s.add(h)
+    conv = s.get(Conversation, conversation_id)
+    if conv is not None:
+        conv.state = "encaminhado"
+    s.flush()
+    return h
+
+
+def assunto_do_texto(texto: str) -> str | None:
+    """Qual prefixo de texto usar no `assunto_sensivel`."""
+    return _assunto_sensivel(Contexto(texto_do_lead=texto))


=== DIFF: app/main.py ===
@@ -9,9 +9,11 @@ Três decisões de exposição, todas de `CLAUDE.md` 14b/14c:
 
 - o compose publica em `127.0.0.1`, nunca em `0.0.0.0`. É o controle que de fato
   protege, e independe de autenticação;
-- `ADMIN_TOKEN` é opcional: definido ⇒ exigido; ausente ⇒ sobe e avisa no log. Existe
-  para que o achado do passe de segurança tenha resposta em código, desligada por
-  padrão, em vez de "risco aceito" em prosa;
+- a autenticação é opcional e vive em `app/auth.py`: `ADMIN_USER`/`ADMIN_PASSWORD`
+  ligam o login com sessão em cookie, `ADMIN_TOKEN` liga o cabeçalho para máquina, e
+  sem nenhum dos dois o serviço sobe e avisa no log. Existe para que o achado do
+  passe de segurança tenha resposta em código, desligada por padrão, em vez de
+  "risco aceito" em prosa;
 - `/docs`, `/redoc` e `/openapi.json` ficam **desligados** fora de desenvolvimento. O
   legado do desafio os expõe abertos; este serviço não repete esse default.
 """
@@ -22,11 +24,12 @@ import logging
 import os
 from contextlib import asynccontextmanager
 
-from fastapi import Depends, FastAPI, Header, HTTPException, Response
+from fastapi import Depends, FastAPI, Response
 from fastapi.responses import JSONResponse
 from sqlalchemy.orm import Session
 
 from app.api import consultas
+from app.auth import aviso_de_boot, exigir_admin, redefinir_credenciais, registrar_autenticacao
 from app.api.schemas import (
     Conversation,
     ConversationDetail,
@@ -36,7 +39,6 @@ from app.api.schemas import (
     QuoteHealth,
     Usage,
 )
-from app.config import get_settings
 from app.persistence import repo
 from app.persistence.db import sessao_factory
 
@@ -53,13 +55,12 @@ async def lifespan(app: FastAPI):
     # tem que doer aqui, não no meio de uma conversa.
     bootstrap()
 
-    s = get_settings()
-    if not s.admin_exigido:
-        log.warning(
-            "ADMIN_TOKEN não definido: /api/* está sem autenticação. "
-            "A proteção efetiva é o bind em 127.0.0.1 do docker-compose.yml. "
-            "Defina ADMIN_TOKEN para exigir o cabeçalho X-Admin-Token."
-        )
+    # Deriva o hash da senha e apaga o texto puro do processo. Antes do primeiro
+    # request, para que nenhuma rota veja o ambiente com a senha ainda nele.
+    redefinir_credenciais()
+    aviso = aviso_de_boot()
+    if aviso:
+        log.warning(aviso)
     yield
 
 
@@ -83,11 +84,9 @@ def sessao() -> Session:
         s.close()
 
 
-def exigir_admin(x_admin_token: str | None = Header(default=None)) -> None:
-    """Exigido **apenas** quando `ADMIN_TOKEN` está definido."""
-    cfg = get_settings()
-    if cfg.admin_exigido and x_admin_token != cfg.admin_token:
-        raise HTTPException(status_code=401, detail="token de admin inválido ou ausente")
+# `exigir_admin` mora em `app/auth.py` — a decisão de "quem pode ler a operação" é
+# de lá, e aqui só se declara a dependência. As três rotas de login são montadas no
+# fim do arquivo, junto dos WebSockets, pelo mesmo motivo: são montagem, não contrato.
 
 
 # ─── saúde ───────────────────────────────────────────────────────────────────
@@ -207,6 +206,7 @@ def atualizar_handoff(handoff_id: str, corpo: dict, s: Session = Depends(sessao)
 from app.channels.web import registrar_websockets  # noqa: E402
 
 registrar_websockets(app)
+registrar_autenticacao(app)
 
 
 @app.get("/", include_in_schema=False)


=== DIFF: app/persistence/models.py ===
@@ -177,6 +177,10 @@ class Handoff(Base):
     status: Mapped[str] = mapped_column(
         _enum("handoff_status", "pendente", "assumido", "resolvido"), default="pendente"
     )
+    #: Os demais gatilhos que casaram no mesmo turno (migração 0003).
+    gatilhos_secundarios: Mapped[list[str]] = mapped_column(
+        ARRAY(Text), default=list, server_default="{}"
+    )
     criado_em: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True),
                                                    server_default=func.now())
     assumido_em: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True),
@@ -210,5 +214,3 @@ class TurnUsage(Base):
                                                    server_default=func.now())
 
 
-# `gatilhos_secundarios` chega na migração 0003, com a fatia 5.
-_ = ARRAY  # mantém o import explícito para quando a coluna for mapeada


=== DIFF: db/migrations/0003_handoff_trigger.sql ===
@@ -0,0 +1,43 @@
+-- 0003_handoff_trigger.sql — o conjunto fechado de gatilhos
+--
+-- A Fase 0 marcou `HandoffTrigger` como provisório e a coluna ficou `TEXT` livre.
+-- A decisão 3 fechou sete gatilhos, e aqui o banco passa a recusar um que não exista.
+--
+-- `cotacao_recusada` **não** está na lista, e não é esquecimento: recusa não cria
+-- handoff (docs/DECISOES-FECHADAS.md §2). Um humano releria a mesma regra fixa em
+-- plans.json e daria o mesmo "não"; encaminhar 30% do tráfego para isso encheria a
+-- fila com casos sem saída.
+
+BEGIN;
+
+-- Quando dois gatilhos casam no mesmo turno, o de maior precedência vence e os
+-- demais ficam aqui. A fila mostra UM gatilho — o que mantém a regra testável, uma
+-- linha por gatilho — sem que o operador perca o quadro ao assumir.
+ALTER TABLE handoffs
+    ADD COLUMN gatilhos_secundarios TEXT[] NOT NULL DEFAULT '{}';
+
+ALTER TABLE handoffs
+    ADD CONSTRAINT handoffs_trigger_conhecido CHECK (
+        trigger IN (
+            'assunto_sensivel',
+            'guardrail',
+            'lead_pediu_atendente',
+            'cotacao_indisponivel',
+            'extracao_falhou',
+            'objecao_fora_da_alcada',
+            'midia_sem_texto'
+        )
+    );
+
+-- O mesmo conjunto vale para os secundários: um gatilho inventado não entra por
+-- nenhuma das duas portas.
+ALTER TABLE handoffs
+    ADD CONSTRAINT handoffs_secundarios_conhecidos CHECK (
+        gatilhos_secundarios <@ ARRAY[
+            'assunto_sensivel', 'guardrail', 'lead_pediu_atendente',
+            'cotacao_indisponivel', 'extracao_falhou',
+            'objecao_fora_da_alcada', 'midia_sem_texto'
+        ]::TEXT[]
+    );
+
+COMMIT;


=== DIFF: tests/nucleo/test_handoff.py ===
@@ -0,0 +1,253 @@
+"""Os sete gatilhos de handoff.
+
+O critério declarado é *"explícito e defensável"*. O que reprova não é ser generoso
+ou econômico com a fila — é o gatilho implícito, que ninguém consegue enumerar nem
+testar. Por isso: **um teste por gatilho**, e um bloco igualmente importante para o
+que **não** é gatilho.
+"""
+
+import pytest
+from sqlalchemy.exc import IntegrityError
+from sqlalchemy import text
+
+from app import textos
+from app.contracts.conversa import HandoffTrigger
+from app.handoff import gatilhos
+from app.handoff.gatilhos import Contexto
+from app.persistence import repo
+from app.persistence.models import Handoff
+
+pytestmark = pytest.mark.db
+
+
+# ─── um teste por gatilho ────────────────────────────────────────────────────
+
+CASOS = [
+    (HandoffTrigger.ASSUNTO_SENSIVEL,
+     Contexto(texto_do_lead="bati o carro ontem e queria abrir sinistro"), "alto"),
+    (HandoffTrigger.GUARDRAIL,
+     Contexto(violacoes_guardrail=2), "alto"),
+    (HandoffTrigger.LEAD_PEDIU,
+     Contexto(texto_do_lead="prefiro falar com uma pessoa"), "—"),
+    (HandoffTrigger.COTACAO_INDISPONIVEL,
+     Contexto(cotacao_falhou=True), "alto"),
+    (HandoffTrigger.EXTRACAO_FALHOU,
+     Contexto(tentativas_extracao={"cep": 2}), "médio"),
+    (HandoffTrigger.OBJECAO_FORA_DA_ALCADA,
+     Contexto(texto_do_lead="continua caro demais", objecoes_de_preco=2), "baixo"),
+    (HandoffTrigger.MIDIA_SEM_TEXTO,
+     Contexto(tipo_da_mensagem="audio", midias_apos_pedido=2), "baixo"),
+]
+
+
+@pytest.mark.parametrize("trigger,contexto,custo", CASOS, ids=[c[0].value for c in CASOS])
+def test_um_teste_por_gatilho(trigger, contexto, custo):
+    assert gatilhos.casa(trigger, contexto), f"{trigger} (custo do erro: {custo})"
+    assert gatilhos.avaliar(contexto)[0] is trigger
+
+
+def test_os_sete_gatilhos_tem_regra():
+    """Se alguém acrescentar um membro ao enum e esquecer a regra, o gatilho existiria
+    no contrato e nunca dispararia."""
+    assert {t for t, _ in gatilhos.REGRAS} == set(HandoffTrigger)
+    assert len(gatilhos.REGRAS) == 7
+
+
+# ─── o que NÃO é gatilho — vale tanto quanto ─────────────────────────────────
+
+
+@pytest.mark.parametrize(
+    "contexto,porque",
+    [
+        (Contexto(texto_do_lead="achei caro", objecoes_de_preco=1),
+         "primeira objeção: o agente responde e insiste"),
+        (Contexto(tipo_da_mensagem="audio", midias_apos_pedido=1),
+         "primeira mídia: o agente pede por texto"),
+        (Contexto(tentativas_extracao={"cep": 1, "idade": 1}),
+         "falhar uma vez em DOIS campos não é falhar duas vezes no mesmo"),
+        (Contexto(violacoes_guardrail=1),
+         "a primeira violação descarta a mensagem e conta; a segunda encaminha"),
+        (Contexto(texto_do_lead="quero cotar um seguro pro meu Onix"),
+         "conversa normal"),
+        (Contexto(texto_do_lead="o sistema deu erro na cotação, tenta de novo"),
+         "5xx que o retry resolveu — encaminhar aqui encheria a fila com o que se "
+         "resolve sozinho em 96% dos casos"),
+    ],
+)
+def test_o_que_nao_e_gatilho(contexto, porque):
+    assert gatilhos.avaliar(contexto) is None, porque
+
+
+def test_recusa_nao_e_gatilho_nem_existe_no_enum():
+    """30% do tráfego. Um humano releria a mesma regra fixa em plans.json e daria o
+    mesmo "não"; encaminhar isso encheria a fila com casos sem saída."""
+    assert not hasattr(HandoffTrigger, "COTACAO_RECUSADA")
+    assert "cotacao_recusada" not in {str(t) for t in HandoffTrigger}
+
+
+# ─── precedência ─────────────────────────────────────────────────────────────
+
+
+def test_assunto_sensivel_vence_lead_pediu():
+    c = Contexto(texto_do_lead="bati o carro, quero falar com alguém")
+    trigger, _, secundarios = gatilhos.avaliar(c)
+    assert trigger is HandoffTrigger.ASSUNTO_SENSIVEL
+    assert HandoffTrigger.LEAD_PEDIU in secundarios      # não se perde
+
+
+def test_a_ordem_da_declaracao_e_a_precedencia():
+    """A precedência é dado, não uma cadeia de `if`. Mudar a ordem da lista muda o
+    comportamento — e é isso que a torna auditável."""
+    ordem = [t for t, _ in gatilhos.REGRAS]
+    assert ordem[0] is HandoffTrigger.ASSUNTO_SENSIVEL
+    assert ordem.index(HandoffTrigger.COTACAO_INDISPONIVEL) < ordem.index(
+        HandoffTrigger.OBJECAO_FORA_DA_ALCADA
+    )
+
+
+def test_secundarios_saem_na_ordem_de_precedencia():
+    c = Contexto(texto_do_lead="bati o carro, quero falar com alguém",
+                 cotacao_falhou=True)
+    _, _, secundarios = gatilhos.avaliar(c)
+    assert secundarios == [HandoffTrigger.LEAD_PEDIU, HandoffTrigger.COTACAO_INDISPONIVEL]
+
+
+# ─── o prefixo de texto do assunto sensível ──────────────────────────────────
+
+
+@pytest.mark.parametrize(
+    "texto,esperado",
+    [
+        ("bati o carro ontem", "sinistro"),
+        ("levaram meu carro no fim de semana", "sinistro"),
+        ("fiquei ferido no acidente", "sinistro"),
+        ("meu advogado vai entrar com processo", "juridico"),
+        ("abri reclamação no Procon", "juridico"),
+        ("quero cotar um seguro", None),
+    ],
+)
+def test_o_assunto_escolhe_o_prefixo(texto, esperado):
+    """Dois textos e não um: "sinto muito" numa notificação extrajudicial soa como
+    admissão, e a ausência dele depois de "bati o carro" soa como frieza."""
+    assert gatilhos.assunto_do_texto(texto) == esperado
+
+
+@pytest.mark.parametrize(
+    "trigger,assunto,esperado",
+    [
+        ("cotacao_indisponivel", None, textos.INDISPONIBILIDADE + "\n\n" + textos.DESPEDIDA),
+        ("assunto_sensivel", "sinistro", textos.SENSIVEL_SINISTRO + "\n\n" + textos.DESPEDIDA),
+        ("assunto_sensivel", "juridico", textos.SENSIVEL_JURIDICO + "\n\n" + textos.DESPEDIDA),
+        ("lead_pediu_atendente", None, textos.DESPEDIDA),
+        ("objecao_fora_da_alcada", None, textos.DESPEDIDA),
+    ],
+)
+def test_composicao_prefixo_mais_despedida(trigger, assunto, esperado):
+    assert textos.compor_handoff(trigger, assunto=assunto) == esperado
+
+
+# ─── persistência ────────────────────────────────────────────────────────────
+
+
+def test_registrar_cria_o_handoff_e_encerra_a_conversa(sessao, conversa):
+    h = gatilhos.registrar(sessao, conversa.id, HandoffTrigger.LEAD_PEDIU,
+                           "o lead pediu uma pessoa")
+    assert h.status == "pendente" and h.disparado_por == "regra"
+    # `encaminhado` é terminal — é a saída de todos os gatilhos.
+    assert repo.obter_conversa(sessao, conversa.id).state == "encaminhado"
+
+
+def test_secundarios_sao_persistidos(sessao, conversa):
+    h = gatilhos.registrar(
+        sessao, conversa.id, HandoffTrigger.ASSUNTO_SENSIVEL, "sinistro",
+        secundarios=[HandoffTrigger.LEAD_PEDIU],
+    )
+    sessao.commit()
+    assert h.gatilhos_secundarios == ["lead_pediu_atendente"]
+
+
+def test_gatilho_inventado_e_recusado_pelo_banco(sessao, conversa):
+    """A migração 0003 fecha o conjunto. Enum e SQL divergirem é o tipo de coisa que
+    só explode em produção."""
+    with pytest.raises(IntegrityError):
+        sessao.execute(text(
+            "INSERT INTO handoffs (id, conversation_id, trigger, reason) "
+            "VALUES ('h_x', :c, 'inventado', 'x')"
+        ), {"c": conversa.id})
+    sessao.rollback()
+
+
+def test_o_enum_bate_com_o_check_do_banco(sessao):
+    """Se alguém acrescentar um gatilho no Python e esquecer o SQL, ou o inverso,
+    isto falha aqui — em vez de o INSERT explodir depois."""
+    definicao = sessao.execute(text(
+        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
+        "WHERE conname = 'handoffs_trigger_conhecido'"
+    )).scalar_one()
+    for t in HandoffTrigger:
+        assert f"'{t.value}'" in definicao, t
+    assert "cotacao_recusada" not in definicao
+
+
+def test_disparado_por_distingue_regra_de_modelo(sessao, conversa):
+    """Um gatilho determinístico e uma decisão do modelo produzem o MESMO sinal — e a
+    fila distingue os dois. É o ponto do padrão write-back."""
+    a = gatilhos.registrar(sessao, conversa.id, HandoffTrigger.COTACAO_INDISPONIVEL,
+                           "job failed", disparado_por="regra")
+    outra = repo.criar_conversa(sessao, channel="console", external_ref="outra-h")
+    b = gatilhos.registrar(sessao, outra.id, HandoffTrigger.LEAD_PEDIU,
+                           "pediu", disparado_por="modelo")
+    assert type(a) is type(b)
+    assert a.disparado_por != b.disparado_por
+
+
+# ─── `encaminhado` é terminal de verdade ─────────────────────────────────────
+
+
+async def test_agente_para_de_responder_apos_o_handoff(sessao, conversa):
+    """O estado é terminal: o agente avisa que um atendente vai assumir e para.
+
+    A mensagem do lead continua sendo persistida — ela é do operador agora, não
+    nossa para responder.
+    """
+    from app.agent import turno
+
+    gatilhos.registrar(sessao, conversa.id, HandoffTrigger.LEAD_PEDIU, "pediu")
+    sessao.commit()
+
+    class CanalMudo:
+        def __init__(self):
+            self.enviadas = []
+
+        async def send(self, *a, **kw):
+            self.enviadas.append(kw)
+            return "x"
+
+    canal = CanalMudo()
+    await turno.responder(conversa.id, "oi? tem alguém?", canal)
+    assert canal.enviadas == []
+
+
+def test_o_relogio_de_demora_desliga_em_encaminhado():
+    """Senão o lead que escreve depois do handoff recebe "só um instante" a cada
+    10 s, para sempre."""
+    import asyncio
+
+    from app.conversa import Conversa
+
+    async def agente(_t):
+        await asyncio.sleep(0.05)
+        return "resposta"
+
+    saidas = []
+
+    async def entregar(t, autor):
+        saidas.append(t)
+
+    async def rodar():
+        c = Conversa(conversation_id="c1", agente=agente, entregar=entregar)
+        c.encaminhar()
+        await c.receber("oi")
+
+    asyncio.run(rodar())
+    assert textos.AVISO_SEM_COTACAO not in saidas


Investigate per the method in your instructions, then return the findings list.

### Claude

→ **Read**  `{"file_path": "/home/<usuario>/repo/app/auth.py"}`

### Mateus

```
File does not exist. Note: your current working directory is <repo>.
```

### Claude

→ **Read**  `{"file_path": "<repo>/app/auth.py"}`

### Mateus

```
1	"""A autenticação da área de operação — sessão em cookie, senha nunca em texto puro.
2	
3	**O problema.** `ADMIN_TOKEN` (CLAUDE.md 14c) é um mecanismo de máquina: um segredo
4	único, colado num cabeçalho. Serve a `curl` e a CI, e é péssimo para uma pessoa —
5	quem abre `/admin` no navegador não tem onde digitar um cabeçalho, e a solução que
6	existia era guardar o token no `localStorage`, que é exatamente onde um XSS o lê.
7	
8	Esta camada acrescenta o mecanismo de **gente**: usuário e senha, sessão em cookie
9	`httpOnly`. Ela **não substitui** o token — os dois convivem, e a ordem está em
10	`exigir_admin`.
11	
12	**Cinco restrições, e todas nascem de o repositório ser público** (CLAUDE.md 13):
13	
14	1. *Nenhuma credencial no código.* Nem constante, nem default de `Settings`, nem
15	   fixture, nem exemplo copiável. `ADMIN_USER` e `ADMIN_PASSWORD` vêm do ambiente e
16	   **não têm valor padrão**. Um default aqui seria um achado autoinfligido no
17	   `insecure-defaults@trailofbits` — num critério que é justamente sobre cuidado com
18	   dados.
19	2. *Sem as duas variáveis, o login não existe e `/admin` abre direto*, como antes.
20	   Isso preserva o item 14: o caminho de um com
… [+14109 caracteres]
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
… [+9303 caracteres]
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
12	- a autenticação é opcional e vive em `app/auth.py`: `ADMIN_USER`/`ADMIN_PASSWORD`
13	  ligam o login com sessão em cookie, `ADMIN_TOKEN` liga o cabeçalho para máquina, e
14	  sem nenhum dos dois o serviço sobe e avisa no log. Existe para que o achado do
15	  passe de segurança tenha resposta em código, desligada por padrão, em vez de
16	  "risco aceito" em prosa;
17	- `/docs`, `/redoc` e `/openapi.json` ficam **desligados** fora de desenvolvimento. O
18	  legado do desafio os expõe abertos; este serviço não repete esse default.
19	"""
20	
21	from __future__ import annotations
22	
23	import logging
24	import os
25	from contextlib import asynccontextmanager
26
… [+7655 caracteres]
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
… [+16674 caracteres]
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
… [+7248 caracteres]
```

### Claude

→ **Read**  `{"file_path": "<repo>/app/persistence/models.py"}`

### Mateus

```
1	"""Espelho SQLAlchemy das migrações.
2	
3	**O SQL é a fonte.** Este módulo não redefine o esquema, não cria tabela e não declara
4	`CHECK` — os invariantes que importam (prêmio só existe quando o job é `ok`, timeout
5	não tem status HTTP, handoff resolvido tem data) são impostos pelo banco, em
6	`db/migrations/0001_inicial.sql`. Duplicá-los aqui criaria dois lugares para divergir.
7	
8	Os tipos `ENUM` são referenciados com `create_type=False` pelo mesmo motivo.
9	"""
10	
11	from __future__ import annotations
12	
13	import datetime as dt
14	from decimal import Decimal
15	
16	from sqlalchemy import (
17	    ARRAY,
18	    Boolean,
19	    Date,
20	    DateTime,
21	    Enum,
22	    ForeignKey,
23	    Integer,
24	    Numeric,
25	    SmallInteger,
26	    String,
27	    Text,
28	    func,
29	)
30	from sqlalchemy.dialects.postgresql import JSONB
31	from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
32	
33	
34	class Base(DeclarativeBase):
35	    pass
36	
37	
38	def _enum(nome: str, *valores: str) -> Enum:
39	    return Enum(*valores, name=nome, create_type=False, native_enum=True)
40	
41	
42	class Conversation(Base):
43	    __tablename__ = "conversations"
44	
4
… [+9352 caracteres]
```

### Claude

→ **Read**  `{"file_path": "<repo>/app/handoff/gatilhos.py"}`

### Mateus

```
1	"""Os sete gatilhos de handoff — como dados, não como `if` espalhado.
2	
3	É isso que torna o critério "explícito e defensável", que é o texto do enunciado. O
4	que reprova não é ser generoso ou econômico com a fila: é o gatilho implícito, que
5	ninguém consegue enumerar nem testar.
6	
7	**O critério é o custo de o agente errar ali.** Custo alto encaminha na hora e sem
8	tentar responder; custo baixo tenta e encaminha na segunda vez. Não é "quantos casos
9	cobrir" — é onde o erro é caro.
10	
11	**Precedência = ordem da declaração.** Primeiro que casa vence; os demais que casaram
12	no mesmo turno viram `gatilhos_secundarios`. A fila mostra um gatilho — o que mantém
13	a regra testável, uma linha por gatilho — sem que o operador perca o quadro completo.
14	
15	**Não são gatilhos**, e cada ausência é uma decisão:
16	
17	- **recusa 422** — 30% do tráfego. Um humano releria a mesma regra fixa em
18	  `plans.json` e daria o mesmo "não";
19	- **falha isolada da `/quote` que o retry resolveu** — 20% dos jobs; encaminhar aí
20	  encheria a fila com o que se resolve sozinho em 96% dos casos;
21	- **primeira objeção de preço** e **primeira mídia** — o agente tenta uma vez.
22	"""
23	
24	fr
… [+6001 caracteres]
```

### Claude

→ **Grep**  `{"pattern": "admin_exigido|admin_token|ADMIN_TOKEN|ADMIN_USER|ADMIN_PASSWORD", "path": "<repo>", "output_mode": "content", "-n": true}`

### Mateus

```
CLAUDE.md:84:14c. **`ADMIN_TOKEN` é opcional e exigido quando definido.** Sem ele a aplicação sobe,
.env.example:21:ADMIN_USER=
.env.example:22:ADMIN_PASSWORD=
.env.example:27:ADMIN_TOKEN=
docker-compose.yml:4:# ADMIN_TOKEN é opcional — sem ele a aplicação sobe e avisa no log.
docker-compose.yml:63:      APP_ADMIN_TOKEN: "${ADMIN_TOKEN:-}"
docs/DECISOES-FECHADAS.md:388:**Exposição: `127.0.0.1` mais `ADMIN_TOKEN` opcional.** O controle que de fato importa é
app/main.py:12:- a autenticação é opcional e vive em `app/auth.py`: `ADMIN_USER`/`ADMIN_PASSWORD`
app/main.py:13:  ligam o login com sessão em cookie, `ADMIN_TOKEN` liga o cabeçalho para máquina, e
docs/planos/07-chat.md:850:5. **`ADMIN_TOKEN`, quando definido, precisa de um caminho para o WebSocket.** O
docs/planos/01-espinha.md:327:      ambiente, **sem default**. `ADMIN_TOKEN` opcional, ausente por padrão.
app/config.py:31:    admin_token: str | None = None
app/config.py:74:    def admin_exigido(self) -> bool:
app/config.py:75:        return self.admin_token is not None
app/bootstrap.py:32:SEM_PREFIXO = ("ANTHROPIC_API_KEY", "OLLAMA_API_KEY", "ADMIN_TOKEN")
app/bootstrap.py:37:#: faz `APP_ADMIN_TOKEN: ${ADMIN_TOKEN:-}` e resol
… [+6607 caracteres]
```

### Claude

→ **Grep**  `{"pattern": "def compor_handoff", "path": "<repo>", "output_mode": "content", "-n": true, "-A": 30}`

### Mateus

```
app/textos.py:99:def compor_handoff(trigger: str, *, assunto: str | None = None) -> str:
app/textos.py-100-    """O handoff é sempre **um prefixo opcional mais a despedida**.
app/textos.py-101-
app/textos.py-102-    Tabela de quatro linhas, determinística — o que mantém o descarte do texto do
app/textos.py-103-    modelo sem exceção em todo caminho de encaminhamento.
app/textos.py-104-    """
app/textos.py-105-    if trigger == "cotacao_indisponivel":
app/textos.py-106-        return f"{INDISPONIBILIDADE}\n\n{DESPEDIDA}"
app/textos.py-107-    if trigger == "assunto_sensivel":
app/textos.py-108-        prefixo = SENSIVEL_SINISTRO if assunto in ("sinistro", "saude") else SENSIVEL_JURIDICO
app/textos.py-109-        return f"{prefixo}\n\n{DESPEDIDA}"
app/textos.py-110-    return DESPEDIDA
```

### Claude

→ **Read**  `{"file_path": "<repo>/app/channels/web.py", "offset": 140, "limit": 40}`

### Mateus

```
140	                if msg.get("type") != "message":
141	                    continue
142	
143	                texto = msg.get("text", "")
144	                from app.agent.runner import processar_turno_web
145	
146	                await processar_turno_web(conversation_id, texto, adaptador)
147	
148	        except WebSocketDisconnect:
149	            return
150	
151	    @app.websocket("/api/events")
152	    async def eventos(ws: WebSocket) -> None:
153	        cfg = get_settings()
154	        # O navegador não põe cabeçalho no handshake do WebSocket: quando
155	        # ADMIN_TOKEN está definido, o token vem por query string.
156	        if cfg.admin_exigido and ws.query_params.get("token") != cfg.admin_token:
157	            await ws.close(code=4401)
158	            return
159	        await ws.accept()
160	        _admin.add(ws)
161	        try:
162	            while True:
163	                await asyncio.sleep(30)
164	                await ws.send_text(json.dumps({"type": "ping"}))
165	        except Exception:  # noqa: BLE001
166	            pass
167	        finally:
168	            _admin.discard(ws)
169	
```

### Claude

→ **Grep**  `{"pattern": "_admin|send_text|broadcast", "path": "<repo>/app/channels/web.py", "output_mode": "content", "-n": true}`

### Mateus

```
67:        await self.ws.send_text(json.dumps(frame, ensure_ascii=False))
76:            await self.ws.send_text(json.dumps({"type": "typing", "ativo": ativo}))
81:        await self.ws.send_text(json.dumps({"type": "state", "state": state}))
89:_admin: set[WebSocket] = set()
100:    for ws in _admin:
102:            await ws.send_text(frame)
106:        _admin.discard(ws)
160:        _admin.add(ws)
164:                await ws.send_text(json.dumps({"type": "ping"}))
168:            _admin.discard(ws)
```

### Claude

→ **Grep**  `{"pattern": "APP_ADMIN_PASSWORD|ESPELHADAS", "path": "<repo>", "output_mode": "content", "-n": true}`

### Mateus

```
app/bootstrap.py:40:ESPELHADAS = {"ADMIN_TOKEN": "[REDIGIDO]"}
app/bootstrap.py:68:            espelho = ESPELHADAS.get(chave)
app/auth.py:155:    os.environ.pop("APP_ADMIN_PASSWORD", None)
```
