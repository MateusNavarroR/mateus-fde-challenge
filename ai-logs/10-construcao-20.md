# Sessão de construção 20

> Exportado por `scripts/exportar_ai_logs.py`, com redação de segredo,
> caminho absoluto e PII **na escrita**. 18 turnos; o `jsonl` de
> origem tinha 267 KB, majoritariamente saída de
> ferramenta, truncada em 1200 caracteres por bloco.

### Mateus

Review this change for security vulnerabilities.

Changed files (you may Read these and any other file in the repo):
  - Dockerfile
  - app/agent/tools.py
  - app/agent/turno.py
  - app/config.py
  - app/persistence/models.py
  - app/persistence/repo.py
  - app/quote/job.py
  - db/migrations/0004_tentativas_extracao.sql
  - scripts/transcript.py
  - tests/nucleo/test_espera.py
  - tests/nucleo/test_handoff.py
  - tests/nucleo/test_recusa.py
  - tests/nucleo/test_transcripts.py

Unified diff (only + lines are new):

=== DIFF: Dockerfile ===
@@ -27,6 +27,10 @@ COPY app/ ./app/
 COPY config/ ./config/
 COPY db/ ./db/
 COPY qa/ ./qa/
+# `scripts/` entra na imagem porque o comando de reprodução do transcript
+# (entregável nº 4) roda DENTRO do contêiner: é lá que estão as dependências e o
+# acesso à `quote-api` e ao Postgres pela rede do compose.
+COPY scripts/ ./scripts/
 COPY --from=web /web/dist ./web/dist
 
 ENV PATH="/srv/.venv/bin:$PATH" \


=== DIFF: app/agent/tools.py ===
@@ -116,9 +116,13 @@ class ContextoDoTurno:
     #: A tool já falou com o lead neste turno ⇒ o texto do modelo é descartado.
     ja_enviou: bool = False
 
-    #: Contadores que os gatilhos de handoff leem. Por CAMPO, não global: falhar uma
-    #: vez no CEP e uma na idade não é "falhou duas vezes".
-    tentativas_extracao: dict[str, int] = field(default_factory=dict)
+    #: `quote_id` já produzido NESTE turno. Uma segunda chamada a `quote_plan` no
+    #: mesmo turno é recusada a partir daqui — ver o guarda em `make_quote_plan`.
+    quote_do_turno: str | None = None
+
+    #: Contador que o gatilho de objeção de preço lê. `tentativas_extracao` NÃO mora
+    #: aqui: ela conta ao longo da conversa e vem do banco (`repo`), como as mídias e
+    #: as violações de guardrail. Um contador de turno reiniciaria a cada mensagem.
     objecoes_de_preco: int = 0
 
 
@@ -174,10 +178,11 @@ def make_qualify_lead(ctx: ContextoDoTurno) -> Callable[..., str]:
             if getattr(perfil, campo) is not None and ctx.texto_do_lead:
                 perfil.origem.setdefault(campo, mascarar(ctx.texto_do_lead))
 
+        # UMA vez por rejeição. A linha estava duplicada, e o efeito era o gatilho
+        # `extracao_falhou` disparar na PRIMEIRA falha — encaminhando por engano um
+        # lead que só precisava ser reperguntado.
         for campo in rejeitados:
             perfil.tentativas_extracao[campo] = perfil.tentativas_extracao.get(campo, 0) + 1
-            ctx.tentativas_extracao[campo] = ctx.tentativas_extracao.get(campo, 0) + 1
-            ctx.tentativas_extracao[campo] = ctx.tentativas_extracao.get(campo, 0) + 1
 
         _gravar_perfil(ctx, perfil)
 
@@ -205,9 +210,17 @@ def _normalizar(campo: str, valor):
 
 
 def _perfil_de(conv) -> LeadProfile:
+    """Reconstrói o perfil a partir da conversa.
+
+    `tentativas_extracao` entra aqui porque o gatilho `extracao_falhou` conta ao
+    longo da CONVERSA, não do turno: sem carregá-lo, o dicionário voltava vazio a
+    cada turno e "a segunda falha no mesmo campo" só podia acontecer dentro de um
+    turno só — o que é o modelo se atrapalhando, não o lead sendo ilegível.
+    """
     return LeadProfile(
         idade=conv.idade, veiculo_ano=conv.veiculo_ano, cep=conv.cep,
         data_inicio=conv.data_inicio, plano_id=conv.plano_id,
+        tentativas_extracao=dict(conv.tentativas_extracao or {}),
     )
 
 
@@ -215,6 +228,8 @@ def _gravar_perfil(ctx: ContextoDoTurno, perfil: LeadProfile) -> None:
     conv = repo.obter_conversa(ctx.sessao, ctx.conversation_id)
     for campo in CAMPOS_QUALIFICACAO:
         setattr(conv, campo, getattr(perfil, campo))
+    # Reatribuído, não mutado: o SQLAlchemy não detecta mutação in-place em JSONB.
+    conv.tentativas_extracao = dict(perfil.tentativas_extracao)
     if conv.state == "novo":
         conv.state = "qualificando"
     ctx.sessao.flush()
@@ -284,9 +299,38 @@ def make_quote_plan(ctx: ContextoDoTurno) -> Callable[..., str]:
                 return (f"dados_invalidos: o {campo} que você passou ({valor}) não bate "
                         f"com o que foi registrado ({registrado}). Confirme com o lead.")
 
+        # Uma cotação por turno. Medido gerando o transcript do caminho feliz: o
+        # modelo chamou `quote_plan` DUAS vezes na mesma volta, e o resultado foi
+        # dois jobs, dois avisos de espera idênticos em sequência para o lead, e uma
+        # linha em `quotes` que ficou `pending` para sempre — rastro inconsistente
+        # justamente na tabela que responde pelo critério nº 4.
+        #
+        # Recusar é seguro: se o lead mudar de plano, a nova cotação sai no próximo
+        # turno. O texto explica para o modelo o que fazer, em vez de só negar.
+        if ctx.quote_do_turno is not None:
+            return (f"já cotado neste turno: {ctx.quote_do_turno}. A mensagem com o "
+                    "resultado JÁ FOI ENVIADA ao lead pelo sistema. Não cote de novo "
+                    "e não repita o valor — encerre o turno.")
+
         conv.state = "cotando"
         ctx.sessao.flush()
 
+        # ⚠️ DEFINIDA ANTES de `executar_job`, e isso não é estilo.
+        #
+        # O `avisar=` abaixo é um closure sobre este nome, e quem o executa é uma
+        # `threading.Timer` — em OUTRA thread, 6 s depois. Com a definição embaixo da
+        # chamada, o timer disparava sobre um nome ainda não vinculado e morria com
+        # `NameError: cannot access free variable 'enviar'`. Numa thread de timer a
+        # exceção não sobe para lugar nenhum: o turno seguia normal, o preço chegava
+        # no fim, e o aviso de espera simplesmente NUNCA saía.
+        #
+        # Achado gerando o transcript do cenário degradado — a suíte passava porque
+        # os testes de espera montam o `avisar` diretamente, sem esta função.
+        def enviar(texto: str, quote_id: str | None = None) -> None:
+            ctx.ja_enviou = True
+            if ctx.enviar is not None:
+                ctx.enviar(texto, quote_id)
+
         q = executar_job(
             ctx.sessao, ctx.conversation_id, req,
             chegada_do_lead=ctx.chegada_do_lead,
@@ -295,13 +339,9 @@ def make_quote_plan(ctx: ContextoDoTurno) -> Callable[..., str]:
             # durante a geração do modelo.
             avisar=(lambda t: enviar(t)) if ctx.enviar else None,
         )
+        ctx.quote_do_turno = q.id
         ctx.sessao.commit()
 
-        def enviar(texto: str, quote_id: str | None = None) -> None:
-            ctx.ja_enviou = True
-            if ctx.enviar is not None:
-                ctx.enviar(texto, quote_id)
-
         if q.status == str(QuoteJobStatus.OK):
             enviar(render_de_payload(q.payload), quote_id=q.id)
             conv.state = "cotado"


=== DIFF: app/agent/turno.py ===
@@ -152,7 +152,7 @@ async def _encaminhar(s, conversation_id: str, ctx, texto: str, enviar_async) ->
         cotacao_falhou=any(
             h.get("trigger") is HandoffTrigger.COTACAO_INDISPONIVEL for h in ctx.handoffs
         ),
-        tentativas_extracao=ctx.tentativas_extracao,
+        tentativas_extracao=repo.tentativas_de_extracao(s, conversation_id),
         objecoes_de_preco=ctx.objecoes_de_preco,
         violacoes_guardrail=repo.violacoes_de_guardrail(s, conversation_id),
         # Do BANCO, incluindo a mensagem deste turno, que já foi gravada.
@@ -183,12 +183,14 @@ async def _encaminhar(s, conversation_id: str, ctx, texto: str, enviar_async) ->
 
     # A mensagem de indisponibilidade já saiu de dentro da tool de cotação;
     # repeti-la aqui seria dizer duas vezes a mesma coisa ao lead.
+    # A mensagem de indisponibilidade já saiu de dentro da tool de cotação, e
+    # `compor_handoff("cotacao_indisponivel")` JÁ TERMINA com a despedida. Mandar
+    # `DESPEDIDA` aqui repetia a mesma frase, palavra por palavra, duas mensagens
+    # seguidas — visível no transcript do cenário degradado.
     if trigger is not HandoffTrigger.COTACAO_INDISPONIVEL:
         await enviar_async(
             textos.compor_handoff(str(trigger), assunto=gatilhos.assunto_do_texto(texto))
         )
-    else:
-        await enviar_async(textos.DESPEDIDA)
     return True
 
 


=== DIFF: app/config.py ===
@@ -65,6 +65,22 @@ class Settings(BaseSettings):
     aviso_espera_s: float = 6.0
     reforco_espera_s: float = 20.0
 
+    #: **Piso** do atraso do aviso, e ele não é cosmético.
+    #:
+    #: O relógio é o do lead, então quando o modelo leva mais de 6 s para chegar à
+    #: tool o prazo já venceu e o atraso calculado é 0 — um `Timer(0)` que corre com
+    #: a chamada HTTP. Medido gerando o transcript do caminho feliz: a `/quote`
+    #: respondeu em 31 ms e o lead recebeu "tô buscando o valor" 0,1 s ANTES do
+    #: preço. É exatamente o «só um instante» seguido da resposta que a decisão 1
+    #: rejeita — e o motivo pelo qual o aviso não é um watchdog na camada de conversa.
+    #:
+    #: 1,0 s cobre com folga o caminho rápido (10–40 ms) e o ciclo de falha rápida
+    #: com retry (~250 ms por tentativa, ~0,8 s no total), que a decisão 1 também
+    #: manda não avisar. Uma chamada lenta de verdade (8 s, ou os 12 s do timeout)
+    #: continua avisando — 1 s depois de a tool começar, quando o lead já esperou os
+    #: 6 s e a demora já é fato, não previsão.
+    piso_aviso_s: float = 1.0
+
     #: Fora do caminho da cotação, na camada de conversa. Limiar mais alto porque a
     #: demora do modelo é anômala, não projetada: 6,5 s ainda é latência plausível e
     #: avisar ali produziria "só um instante" seguido da resposta 0,2 s depois.


=== DIFF: app/persistence/models.py ===
@@ -58,6 +58,13 @@ class Conversation(Base):
     data_inicio: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
     plano_id: Mapped[str | None] = mapped_column(Text, nullable=True)
 
+    #: `{campo: n}` — quantas vezes cada campo foi rejeitado na extração, acumulado
+    #: na CONVERSA. O gatilho `extracao_falhou` dispara a partir de 2 no mesmo campo,
+    #: e sem persistir isto a contagem reiniciava a cada turno (migração 0004).
+    tentativas_extracao: Mapped[dict] = mapped_column(
+        JSONB, default=dict, server_default="{}"
+    )
+
     criado_em: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True),
                                                    server_default=func.now())
     atualizado_em: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True),


=== DIFF: app/persistence/repo.py ===
@@ -188,6 +188,18 @@ def gravar_mensagem(
     return m
 
 
+def tentativas_de_extracao(s: Session, conversation_id: str) -> dict[str, int]:
+    """`{campo: n}` acumulado na conversa. Insumo de `EXTRACAO_FALHOU`.
+
+    A terceira das contagens derivadas do banco, com `midias_do_lead` e
+    `violacoes_de_guardrail`, e pelo mesmo motivo: um contador que vive só no envelope
+    do turno reinicia a cada mensagem, e "a segunda falha no mesmo campo" deixa de
+    poder acontecer entre turnos — que é exatamente o caso que a regra descreve.
+    """
+    conv = s.get(Conversation, conversation_id)
+    return dict(conv.tentativas_extracao or {}) if conv is not None else {}
+
+
 def registrar_descarte(s: Session, conversation_id: str, conteudo: str) -> Message:
     """Grava a mensagem que o guardrail **impediu de sair**, com status `discarded`.
 


=== DIFF: app/quote/job.py ===
@@ -224,7 +224,12 @@ class _Avisos:
         )
         # O relógio é o do LEAD: se ele já esperou 3 s antes de a tool começar, o
         # aviso sai 3 s depois daqui, não 6.
+        # O piso é o que impede o aviso de correr com a resposta. Ver
+        # `Settings.piso_aviso_s` — só o AVISO tem piso: o reforço é encadeado a
+        # partir do aviso, então quando ele existe a demora já está estabelecida.
         atraso = max(0.0, limiar - (time.monotonic() - self.t0))
+        if nome == "aviso":
+            atraso = max(atraso, self.cfg.piso_aviso_s)
         t = threading.Timer(atraso, self._disparar, args=(nome, texto))
         t.daemon = True
         t.start()


=== DIFF: db/migrations/0004_tentativas_extracao.sql ===
@@ -0,0 +1,34 @@
+-- 0004_tentativas_extracao.sql — o contador que o gatilho de extração lê
+--
+-- `EXTRACAO_FALHOU` é definido como "**2ª** falha de extração no MESMO campo"
+-- (docs/DECISOES-FECHADAS.md §3, custo médio: tenta uma vez, encaminha na segunda).
+-- Ele não fazia isso.
+--
+-- Duas causas, e as duas medidas gerando o transcript do cenário degradado:
+--
+-- 1. o contador do turno era incrementado DUAS vezes por rejeição — uma linha
+--    duplicada —, então a primeira falha já marcava 2 e o gatilho disparava nela;
+-- 2. `LeadProfile.tentativas_extracao` nunca era persistido: `_perfil_de()`
+--    reconstrói o perfil das colunas da conversa, e o dicionário voltava vazio a
+--    cada turno. Ou seja, mesmo sem a duplicação o contador nunca teria chegado a 2
+--    por dois turnos — só por duas chamadas de tool dentro do MESMO turno, que é o
+--    modelo se atrapalhando, e não o lead sendo ilegível.
+--
+-- O efeito somado é o pior possível para o critério nº 3: um lead cujo primeiro
+-- campo o modelo mandou torto ia para a fila humana na hora, sem nunca ser
+-- reperguntado. Encaminhar por bug nosso é o caso que CLAUDE.md 9 nomeia.
+--
+-- Persistir na conversa é o que torna a contagem derivável do banco, como
+-- `midias_do_lead` e `violacoes_de_guardrail` — e, como elas, auditável a partir do
+-- transcript em vez de depender de um número que o chamador passa.
+
+BEGIN;
+
+ALTER TABLE conversations
+    ADD COLUMN tentativas_extracao JSONB NOT NULL DEFAULT '{}'::jsonb;
+
+COMMENT ON COLUMN conversations.tentativas_extracao IS
+    'Quantas vezes cada campo foi rejeitado na extração, acumulado na conversa. '
+    'Insumo do gatilho extracao_falhou, que dispara a partir de 2 no mesmo campo.';
+
+COMMIT;


=== DIFF: scripts/transcript.py ===
@@ -0,0 +1,306 @@
+"""Gera o log de execução completa — entregável nº 4 do enunciado.
+
+Dois cenários, e o segundo é o que o enunciado chama de *"o ponto que mais separa"*:
+
+- **`feliz`**: a `/quote` responde na primeira tentativa. Mostra a qualificação dos
+  cinco campos, o bloco de cotação renderizado por template — com carência, franquia
+  e pro-rata — e o estado final `cotado`.
+- **`degradado`**: a `/quote` estoura o timeout nas três tentativas. Mostra o aviso
+  aos 6 s, o reforço aos 20 s e o encaminhamento aos ~37 s, que é o **pior caso da
+  política** e a razão de a cotação ser um job com estado em vez de uma espera dentro
+  do turno.
+
+**Por que pelo console e não pelo navegador.** O transcript precisa ser um artefato de
+texto, comparável entre execuções e legível num diff. O `ConsoleAdapter` já marca tempo
+relativo por linha, que é o que transforma "a política funciona" em número.
+
+**O caminho é o de produção.** Este script chama `turno.responder`, o mesmo que o canal
+web chama — não uma versão simplificada. Um transcript gerado por um laço próprio
+provaria o laço próprio. Por isso ele exercita persistência, guardrail, política de
+espera e a avaliação dos sete gatilhos de handoff, e não só o modelo.
+
+**O conteúdo do lead sai MASCARADO**, porque é o que fica gravado: a linha do CEP
+aparece como `cep [CEP]`. Não é limitação do transcript, é o produto — não existe
+versão crua do lado do servidor. De quebra, é o que permite ao artefato viver em
+`artifacts/`, que a varredura de PII do portão de segurança lê inteira (CLAUDE.md 13a).
+
+Reprodução: cada arquivo gerado carrega no cabeçalho o comando exato que o produz.
+Um cenário da `/quote` é a tripla **(seed, processo reiniciado, sequência exata de
+requisições)** — a seed sozinha não basta, porque o RNG do legado é um fluxo global e
+contínuo do processo.
+"""
+
+from __future__ import annotations
+
+import argparse
+import asyncio
+import datetime as dt
+import os
+import sys
+import time
+
+sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
+
+from app.bootstrap import bootstrap  # noqa: E402
+from app.channels.console import ConsoleAdapter, LinhaTranscript  # noqa: E402
+from app.persistence import repo  # noqa: E402
+from app.persistence.db import sessao_factory  # noqa: E402
+from app.persistence.models import Handoff, Quote, QuoteAttempt  # noqa: E402
+
+# ─── as falas ────────────────────────────────────────────────────────────────
+#
+# Do molde do dataset: linguagem torta, dados fora de ordem, um campo por vez e uma
+# pergunta no meio. As duas últimas cobrem o que o lead do dataset NUNCA informa —
+# plano e data de início —, que é justamente o que a qualificação exige.
+#
+# A data de início é dia 17 de propósito: dia ≠ 1 é a única forma de o bloco
+# `primeiro_pagamento_pro_rata` existir na resposta da `/quote`.
+
+FALAS = [
+    "Oi, queria fazer um seguro pro meu carro",
+    "e um Onix 2019",
+    "tenho 28 anos, cep [CEP]",
+    "qual a diferença dos planos?",
+    "quero o completo mesmo",
+    "pode começar dia 17 de outubro",
+]
+
+CENARIOS = {
+    "feliz": {
+        "titulo": "Caminho feliz — do «oi» à cotação",
+        "env": "QUOTE_FAILURE_RATE=0 QUOTE_SLOW_RATE=0",
+        "porque": (
+            "A `/quote` responde na primeira tentativa. É o cenário que prova o "
+            "critério nº 1: o agente atende de ponta a ponta e entrega o preço."
+        ),
+    },
+    "degradado": {
+        "titulo": "Caminho degradado — a `/quote` não responde",
+        "env": "QUOTE_SLOW_RATE=1 QUOTE_SLOW_SECONDS=13 QUOTE_FAILURE_RATE=0",
+        "porque": (
+            "`SLOW_SECONDS=13` é **maior** que o nosso read timeout de 12 s, então as "
+            "três tentativas estouram e o job termina `failed`. É o pior caso da "
+            "política, forçado de propósito: no tráfego real ele acontece em ~0,8 % "
+            "dos jobs, e esperar por ele para gerar o artefato seria esperar por acaso."
+            "\n\n"
+            "**Como ler os Δ.** O aviso tem limiar de 6 s e o reforço de 20 s, contados "
+            "da chegada da mensagem do lead. O aviso costuma aparecer um pouco depois "
+            "dos 6 s, e a aritmética é esta: quem agenda os dois timers é a **tool de "
+            "cotação**, e o modelo leva alguns segundos para chegar até ela. Quando o "
+            "job começa depois dos 6 s, o prazo já venceu e o aviso sai na hora — é "
+            "por isso que ele acompanha o início do job, e não o relógio.\n\n"
+            "O disparo é de dentro da tool de propósito: um watchdog na camada de "
+            "conversa dispararia **durante** a geração do modelo e produziria «só um "
+            "instante» seguido da resposta 0,2 s depois. Para a demora que não é da "
+            "cotação existe um segundo relógio, aos 10 s, na camada de conversa."
+        ),
+    },
+}
+
+
+def cabecalho(cenario: str, conversation_id: str) -> str:
+    c = CENARIOS[cenario]
+    return f"""# {c['titulo']}
+
+> Gerado por `scripts/transcript.py`. **Entregável nº 4** do enunciado: log de uma
+> execução completa, do início ao fim.
+
+## Como reproduzir
+
+```bash
+{c['env']} docker compose up -d --build --wait
+docker compose exec -T app python scripts/transcript.py --cenario {cenario} \\
+  > artifacts/transcript-{cenario}.md
+```
+
+O redirecionamento é do lado de fora de propósito: o contêiner é efêmero e montar um
+volume só para isto acrescentaria uma linha ao `docker-compose.yml` que não serve ao
+produto. O artefato nasce onde vai viver.
+
+O `docker compose up` acima **reinicia o processo da `/quote`** com essas variáveis, e
+é isso que torna o cenário reproduzível: o RNG do legado é um fluxo global e contínuo
+do processo, então a tripla que define um cenário é *(seed, processo reiniciado,
+sequência exata de requisições)* — a seed sozinha não basta.
+
+{c['porque']}
+
+- Conversa: `{conversation_id}`
+- Gerado em: {dt.datetime.now(dt.UTC).isoformat(timespec='seconds')}
+- `[+Xs]` é o tempo desde o início da conversa; `Δ` é o tempo desde a mensagem do
+  lead naquele turno — é a coluna que a política de espera governa.
+
+## Transcript
+
+```
+"""
+
+
+class Coletor(ConsoleAdapter):
+    """`ConsoleAdapter` que também guarda o Δ do turno.
+
+    A coluna Δ existe porque a política de espera conta a partir da chegada da
+    mensagem do LEAD (`aviso_espera_s`, `reforco_espera_s`), e não do início da
+    conversa. Sem ela, "aviso aos 6 s" fica invisível no meio de uma conversa que já
+    dura 40 s — e é justamente esse número que o critério nº 2 pede para ver.
+    """
+
+    def __init__(self) -> None:
+        super().__init__(transcript=True)
+        self.t_turno: float = 0.0
+        self.deltas: list[float | None] = []
+
+    def abrir_turno(self) -> None:
+        self.t_turno = self._decorrido()
+
+    def anotar(self, autor: str, conteudo: str, *, do_turno: bool) -> None:
+        agora = self._decorrido()
+        self.linhas.append(LinhaTranscript(agora, autor, conteudo))
+        self.deltas.append(agora - self.t_turno if do_turno else None)
+
+    async def send(self, conversation_id, text, *, message_id, quote_id=None,
+                   autor="agente", **kw) -> str:
+        self.anotar(autor, text, do_turno=True)
+        self.enviadas.append({"text": text, "quote_id": quote_id, "autor": autor})
+        return f"console:{message_id}"
+
+    async def typing(self, conversation_id, *, ativo: bool) -> None:
+        return None
+
+    def render(self) -> str:
+        largura = max((len(l.autor) for l in self.linhas), default=7)
+        saida = []
+        for linha, delta in zip(self.linhas, self.deltas, strict=True):
+            marca = f"[{linha.segundos:+6.1f}s]"
+            d = f"  Δ{delta:+5.1f}s" if delta is not None else " " * 9
+            # Continuações alinhadas: um bloco de cotação tem várias linhas, e sem
+            # isto a segunda em diante encosta na margem e some do lado do autor.
+            corpo = linha.conteudo.replace("\n", "\n" + " " * (len(marca) + 9 + largura + 4))
+            saida.append(f"{marca}{d}  {linha.autor:<{largura}}  {corpo}")
+        return "\n".join(saida)
+
+
+def rodape(s, conversation_id: str) -> str:
+    """O que ficou GRAVADO. Um transcript sem isto é uma tela; com isto é rastro.
+
+    É a evidência do critério nº 4 (*cada mensagem e cotação com id e status*) e do
+    nº 3 (*critério de handoff explícito*): o desfecho não é o texto que saiu, é a
+    linha do banco que sobrou.
+    """
+    conv = repo.obter_conversa(s, conversation_id)
+    partes = ["```", "", "## O que ficou gravado", "",
+              f"**Estado final da conversa:** `{conv.state}`", ""]
+
+    msgs = repo.mensagens(s, conversation_id)
+    partes += ["### Mensagens", "",
+               "| index | autor | tipo | status | quote_id |",
+               "|---|---|---|---|---|"]
+    for m in msgs:
+        partes.append(
+            f"| {m.index} | `{m.autor}` | `{m.tipo}` | `{m.status}` | "
+            f"{'`' + m.quote_id + '`' if m.quote_id else '—'} |"
+        )
+
+    quotes = s.query(Quote).filter_by(conversation_id=conversation_id).all()
+    if quotes:
+        partes += ["", "### Cotações", "",
+                   "| quote_id | status | prêmio | outcome | latência |",
+                   "|---|---|---|---|---|"]
+        for q in quotes:
+            premio = f"R$ {q.premio_mensal}" if q.premio_mensal is not None else "—"
+            partes.append(
+                f"| `{q.id}` | `{q.status}` | {premio} | "
+                f"`{q.erro_outcome or '—'}` | {q.total_latency_ms or 0} ms |"
+            )
+        for q in quotes:
+            tentativas = (s.query(QuoteAttempt).filter_by(quote_id=q.id)
+                          .order_by(QuoteAttempt.attempt).all())
+            if not tentativas:
+                continue
+            partes += ["", f"#### Tentativas de `{q.id}`", "",
+                       "| # | HTTP | outcome | latência |", "|---|---|---|---|"]
+            for a in tentativas:
+                partes.append(
+                    f"| {a.attempt} | {a.http_status or '— (sem resposta)'} | "
+                    f"`{a.outcome}` | {a.latency_ms} ms |"
+                )
+
+    handoffs = s.query(Handoff).filter_by(conversation_id=conversation_id).all()
+    if handoffs:
+        partes += ["", "### Handoff", ""]
+        for h in handoffs:
+            partes += [f"- gatilho `{h.trigger}`, disparado por **{h.disparado_por}**",
+                       f"  - motivo: {h.reason}"]
+            if h.gatilhos_secundarios:
+                partes.append(f"  - secundários: {h.gatilhos_secundarios}")
+    else:
+        partes += ["", "### Handoff", "",
+                   "Nenhum. O agente resolveu sozinho — que é o desfecho pretendido "
+                   "deste cenário."]
+
+    return "\n".join(partes) + "\n"
+
+
+async def executar(cenario: str, saida: str) -> int:
+    from app.agent.turno import responder
+
+    canal = Coletor()
+    fabrica = sessao_factory()
+
+    with fabrica() as s:
+        conv = repo.criar_conversa(
+            s, channel="console",
+            # Único por execução: `conversations` tem UNIQUE (channel, external_ref),
+            # e uma execução anterior abortada bloquearia a próxima.
+            external_ref=f"transcript-{cenario}-{int(time.time())}",
+        )
+        s.commit()
+        conversation_id = conv.id
+
+    canal.marcar_inicio()
+
+    for fala in FALAS:
+        canal.abrir_turno()
+        chegada = time.monotonic()
+        with fabrica() as s:
+            estado = repo.obter_conversa(s, conversation_id).state
+            if estado == "encaminhado":
+                # Terminal de verdade: o agente parou. Continuar o roteiro produziria
+                # linhas de lead sem resposta e daria a impressão de que ele travou.
+                canal.anotar("—", f"(conversa em `{estado}`: o roteiro para aqui)",
+                             do_turno=False)
+                break
+            m = repo.gravar_mensagem(s, conversation_id, autor="lead",
+                                     conteudo=fala, status="received")
+            s.commit()
+            # A versão MASCARADA, que é a que fica gravada. Ver o docstring do módulo.
+            canal.anotar("lead", m.conteudo, do_turno=False)
+
+        await responder(conversation_id, fala, canal, chegada_do_lead=chegada)
+
+    with fabrica() as s:
+        corpo = cabecalho(cenario, conversation_id) + canal.render() + "\n"
+        corpo += rodape(s, conversation_id)
+
+    if saida == "-":
+        sys.stdout.write(corpo)
+    else:
+        os.makedirs(os.path.dirname(saida) or ".", exist_ok=True)
+        with open(saida, "w", encoding="utf-8") as f:
+            f.write(corpo)
+    print(f"→ {len(canal.linhas)} linhas", file=sys.stderr)
+    return 0
+
+
+def main() -> int:
+    p = argparse.ArgumentParser(description=__doc__)
+    p.add_argument("--cenario", choices=sorted(CENARIOS), required=True)
+    # Padrão: stdout. Ver o cabeçalho gerado — o artefato é redirecionado no host.
+    p.add_argument("--saida", default="-")
+    args = p.parse_args()
+
+    bootstrap()
+    return asyncio.run(executar(args.cenario, args.saida))
+
+
+if __name__ == "__main__":
+    raise SystemExit(main())


=== DIFF: tests/nucleo/test_espera.py ===
@@ -22,6 +22,8 @@ from app.quote import client
 from app.quote.breaker import resetar_breaker
 from app.quote.job import executar_job
 
+from tests.fixtures.pii import cep_de
+
 pytestmark = [pytest.mark.db, pytest.mark.live, pytest.mark.serial]
 
 LIMPA = os.getenv("QUOTE_API_LIMPA", "http://localhost:8001")
@@ -29,7 +31,7 @@ FALHA = os.getenv("QUOTE_API_FALHA", "http://localhost:8002")
 LENTA = os.getenv("QUOTE_API_LENTA", "http://localhost:8003")
 
 REQ = QuoteRequest(plano_id="completo", idade=28, veiculo_ano=2019,
-                   cep="[CEP]", data_inicio=dt.date(2026, 10, 17))
+                   cep=cep_de("07"), data_inicio=dt.date(2026, 10, 17))
 
 
 @pytest.fixture(autouse=True)
@@ -92,8 +94,14 @@ def test_aviso_sai_na_espera_longa(sessao, conversa, monkeypatch):
 
 
 def test_aviso_e_reforco_na_ordem(sessao, conversa, monkeypatch):
+    # O piso entra comprimido junto com os limiares: quem encolhe o relógio tem
+    # de encolher a política inteira, senão o teste mede uma mistura dos dois.
     _cfg(monkeypatch, FALHA, aviso_espera_s=0.05, reforco_espera_s=0.10,
-         quote_backoff_teto_s=0.2)
+         piso_aviso_s=0.01)
+    # Backoff FIXO: `calcular_backoff` é `uniform(0, teto)`, então o mínimo é zero e
+    # o job de falha rápida pode terminar em ~10 ms — antes do reforço. O teste
+    # falhava em ~1 execução a cada 4 medindo o jitter, e não a sequência de avisos.
+    monkeypatch.setattr(client, "calcular_backoff", lambda _n: 0.15)
     col = Coletor()
     executar_job(sessao, conversa.id, REQ, avisar=col)
     assert col.textos == [textos.AVISO_ESPERA, textos.REFORCO]
@@ -102,7 +110,12 @@ def test_aviso_e_reforco_na_ordem(sessao, conversa, monkeypatch):
 def test_cada_aviso_sai_uma_vez_so(sessao, conversa, monkeypatch):
     """Três tentativas com o limiar baixo poderiam repetir o aviso a cada laço."""
     _cfg(monkeypatch, FALHA, aviso_espera_s=0.01, reforco_espera_s=0.02,
-         quote_backoff_teto_s=0.2)
+         piso_aviso_s=0.005)
+    # Backoff FIXO: `calcular_backoff` é `uniform(0, teto)`, então o mínimo é zero e
+    # o job de falha rápida pode terminar em ~10 ms — antes do reforço. O teste
+    # falhava em ~1 execução a cada 4 medindo o jitter, e não a sequência de avisos.
+    monkeypatch.setattr(client, "calcular_backoff", lambda _n: 0.15)
+
     col = Coletor()
     executar_job(sessao, conversa.id, REQ, avisar=col)
     assert col.textos.count(textos.AVISO_ESPERA) == 1
@@ -111,13 +124,27 @@ def test_cada_aviso_sai_uma_vez_so(sessao, conversa, monkeypatch):
 
 def test_relogio_e_o_do_lead_nao_o_da_tool(sessao, conversa, monkeypatch):
     """O turno gasta a latência do modelo ANTES da tool. Contando do início da tool,
-    o lead ficaria 8 s no escuro antes do aviso."""
-    _cfg(monkeypatch, LIMPA, aviso_espera_s=2.0, reforco_espera_s=99.0)
+    o lead ficaria 8 s no escuro antes do aviso.
+
+    ⚠️ Este teste usava a instância LIMPA e afirmava que uma cotação de
+    milissegundos, com o prazo do lead já vencido, deveria avisar. Isso é o
+    contrário da decisão 1: o aviso sairia 0,1 s antes do preço. A propriedade que
+    ele quer provar — que o relógio é o do lead — é real, e se prova com a instância
+    LENTA, onde a espera existe de fato: o lead escreveu 5 s atrás, o limiar é 6 s,
+    então o aviso sai ~1 s depois de a tool começar, e não 6 s depois.
+    """
+    _cfg(monkeypatch, LENTA, aviso_espera_s=6.0, reforco_espera_s=99.0,
+         piso_aviso_s=0.2)
     col = Coletor()
-    # o lead escreveu 3 s atrás; a /quote limpa responde em milissegundos
     executar_job(sessao, conversa.id, REQ,
-                 chegada_do_lead=time.monotonic() - 3.0, avisar=col)
+                 chegada_do_lead=time.monotonic() - 5.0, avisar=col)
+
     assert textos.AVISO_ESPERA in col.textos
+    quando = next(t for t, txt in col.msgs if txt == textos.AVISO_ESPERA)
+    assert quando < 3.0, (
+        f"o aviso saiu {quando:.1f}s depois do início da tool. Se o relógio fosse o "
+        "da tool, sairia aos 6,0 s — os 5 s que o lead já esperou seriam ignorados."
+    )
 
 
 def test_sucesso_rapido_nao_avisa(sessao, conversa, monkeypatch):
@@ -131,9 +158,125 @@ def test_a_sequencia_degradada_completa(sessao, conversa, monkeypatch):
     """O que o avaliador vai ler no transcript degradado: aviso, reforço, e o job
     terminando `failed` — nunca um preço inventado."""
     _cfg(monkeypatch, FALHA, aviso_espera_s=0.05, reforco_espera_s=0.10,
-         quote_backoff_teto_s=0.2)
+         piso_aviso_s=0.01)
+    # Backoff FIXO: `calcular_backoff` é `uniform(0, teto)`, então o mínimo é zero e
+    # o job de falha rápida pode terminar em ~10 ms — antes do reforço. O teste
+    # falhava em ~1 execução a cada 4 medindo o jitter, e não a sequência de avisos.
+    monkeypatch.setattr(client, "calcular_backoff", lambda _n: 0.15)
     col = Coletor()
     q = executar_job(sessao, conversa.id, REQ, avisar=col)
     assert q.status == "failed"
     assert col.textos == [textos.AVISO_ESPERA, textos.REFORCO]
     assert not any("R$" in t for t in col.textos)
+
+
+# ─── e agora pelo caminho de produção, que é onde estava quebrado ────────────
+
+
+def test_o_aviso_sai_PELA_TOOL_e_nao_so_pelo_job(sessao, conversa, monkeypatch):
+    """Todo teste acima passa `avisar=` direto para `executar_job`. Nenhum atravessa
+    `quote_plan` — e era exatamente ali que a fiação estava quebrada.
+
+    `make_quote_plan` montava `avisar=(lambda t: enviar(t))` **antes** de `def
+    enviar`. O closure via um nome não vinculado, e quem o executa é uma
+    `threading.Timer`: a `NameError` morria na thread do timer, sem subir para lugar
+    nenhum. O turno seguia normal, o preço chegava no fim, e o aviso de espera nunca
+    saía — em produção, em 100 % das cotações lentas.
+
+    A suíte inteira ficou verde durante isso. Achado gerando o transcript.
+    """
+    from app.agent.tools import ContextoDoTurno, make_quote_plan
+
+    _cfg(monkeypatch, LENTA, aviso_espera_s=1.0, reforco_espera_s=99.0)
+
+    recebidas: list[str] = []
+    ctx = ContextoDoTurno(
+        sessao=sessao,
+        conversation_id=conversa.id,
+        enviar=lambda texto, quote_id=None, autor="sistema": recebidas.append(texto),
+        chegada_do_lead=time.monotonic(),
+    )
+    # O perfil precisa bater com o argumento: a tool faz checagem cruzada.
+    conversa.idade, conversa.veiculo_ano = 28, 2019
+    sessao.flush()
+
+    make_quote_plan(ctx)(
+        plano_id="completo", idade=28, veiculo_ano=2019,
+        cep=cep_de("07"), data_inicio="2026-10-17",
+    )
+
+    assert textos.AVISO_ESPERA in recebidas, (
+        "o aviso de espera não chegou ao canal pelo caminho da tool. "
+        f"Saiu: {recebidas}"
+    )
+
+
+def test_o_aviso_vem_ANTES_do_preco(sessao, conversa, monkeypatch):
+    """A ordem é o ponto: um aviso de espera entregue depois do preço é pior do que
+    nenhum — ele avisa sobre uma espera que já acabou."""
+    from app.agent.tools import ContextoDoTurno, make_quote_plan
+
+    _cfg(monkeypatch, LENTA, aviso_espera_s=1.0, reforco_espera_s=99.0)
+
+    recebidas: list[str] = []
+    ctx = ContextoDoTurno(
+        sessao=sessao,
+        conversation_id=conversa.id,
+        enviar=lambda texto, quote_id=None, autor="sistema": recebidas.append(texto),
+        chegada_do_lead=time.monotonic(),
+    )
+    conversa.idade, conversa.veiculo_ano = 28, 2019
+    sessao.flush()
+
+    make_quote_plan(ctx)(
+        plano_id="completo", idade=28, veiculo_ano=2019,
+        cep=cep_de("07"), data_inicio="2026-10-17",
+    )
+
+    assert len(recebidas) == 2, recebidas
+    assert recebidas[0] == textos.AVISO_ESPERA
+    assert "R$" in recebidas[1], "a segunda mensagem tem que ser o bloco de cotação"
+
+
+def test_cotacao_rapida_nunca_avisa_mesmo_com_o_prazo_ja_vencido(
+    sessao, conversa, monkeypatch
+):
+    """O aviso não pode correr com a resposta.
+
+    Medido gerando o transcript do caminho feliz: o modelo levou 6,5 s para chegar à
+    tool, o prazo do relógio do lead já tinha vencido, o atraso calculado deu 0 e o
+    `Timer(0)` disparou 0,1 s ANTES de a `/quote` responder em 31 ms. O lead leu «tô
+    buscando o valor» e, na linha seguinte, o preço.
+
+    É o «só um instante» seguido da resposta que a decisão 1 rejeita — e o motivo de
+    o aviso não ser um watchdog na camada de conversa. O piso resolve por construção.
+    """
+    col = Coletor()
+    # Prazo VENCIDO: o lead já esperou 30 s antes de a tool começar.
+    _cfg(monkeypatch, LIMPA, aviso_espera_s=6.0, reforco_espera_s=20.0,
+         piso_aviso_s=1.0)
+
+    executar_job(sessao, conversa.id, REQ,
+                 chegada_do_lead=time.monotonic() - 30.0, avisar=col)
+
+    assert col.textos == [], (
+        "a /quote respondeu em milissegundos; nenhum aviso podia ter saído. "
+        f"Saiu: {col.textos}"
+    )
+
+
+def test_o_piso_nao_engole_o_aviso_de_uma_espera_de_verdade(
+    sessao, conversa, monkeypatch
+):
+    """O negativo: um piso alto demais mataria a política inteira em silêncio."""
+    col = Coletor()
+    _cfg(monkeypatch, LENTA, aviso_espera_s=6.0, reforco_espera_s=99.0,
+         piso_aviso_s=1.0)
+
+    executar_job(sessao, conversa.id, REQ,
+                 chegada_do_lead=time.monotonic() - 30.0, avisar=col)
+
+    assert textos.AVISO_ESPERA in col.textos
+    # E saiu DEPOIS do piso, não na hora.
+    quando = next(t for t, txt in col.msgs if txt == textos.AVISO_ESPERA)
+    assert quando >= 0.9, f"o aviso saiu em {quando:.2f}s, antes do piso de 1,0 s"


=== DIFF: tests/nucleo/test_handoff.py ===
@@ -449,3 +449,125 @@ def test_a_fronteira_cobre_todos_os_sete_gatilhos():
     assert _DO_MODELO < {str(t) for t in HandoffTrigger}
     contados = {str(t) for t in HandoffTrigger} - _DO_MODELO
     assert len(contados) == 5
+
+
+# ─── `extracao_falhou` conta ao longo da CONVERSA, e conta uma vez ───────────
+
+
+def test_uma_falha_de_extracao_nao_encaminha(sessao, conversa):
+    """Medido gerando o transcript: o gatilho disparava na PRIMEIRA falha.
+
+    Duas causas somadas — o incremento estava duplicado, e o contador nunca era
+    persistido. O efeito é o pior possível para o critério nº 3: um lead cujo campo o
+    modelo mandou torto ia para a fila humana na hora, sem nunca ser reperguntado.
+    Encaminhar por bug nosso é o caso que CLAUDE.md 9 nomeia.
+    """
+    from app.agent.tools import ContextoDoTurno, make_qualify_lead
+    from app.persistence import repo as _repo
+
+    ctx = ContextoDoTurno(sessao=sessao, conversation_id=conversa.id)
+    qualificar = make_qualify_lead(ctx)
+
+    qualificar(data_inicio="dia de são nunca")
+    sessao.commit()
+
+    assert _repo.tentativas_de_extracao(sessao, conversa.id) == {"data_inicio": 1}
+    assert not gatilhos.casa(
+        HandoffTrigger.EXTRACAO_FALHOU,
+        Contexto(tentativas_extracao=_repo.tentativas_de_extracao(sessao, conversa.id)),
+    )
+
+
+def test_a_contagem_de_extracao_atravessa_turnos(sessao, conversa):
+    """A regra diz "2ª falha no MESMO campo", sem dizer "no mesmo turno".
+
+    Antes, `tentativas_extracao` vivia no envelope do turno e `_perfil_de()` a
+    descartava ao reconstruir o perfil das colunas — então a contagem reiniciava a
+    cada mensagem e a segunda falha só podia acontecer dentro de um turno só, que é o
+    modelo se atrapalhando, e não o lead sendo ilegível.
+    """
+    from app.agent.tools import ContextoDoTurno, make_qualify_lead
+    from app.persistence import repo as _repo
+
+    for _ in range(2):
+        # Um ContextoDoTurno NOVO a cada volta: é o que o turno faz de verdade.
+        ctx = ContextoDoTurno(sessao=sessao, conversation_id=conversa.id)
+        make_qualify_lead(ctx)(data_inicio="quando der")
+        sessao.commit()
+
+    contagem = _repo.tentativas_de_extracao(sessao, conversa.id)
+    assert contagem == {"data_inicio": 2}
+    assert gatilhos.casa(HandoffTrigger.EXTRACAO_FALHOU,
+                         Contexto(tentativas_extracao=contagem))
+
+
+def test_falhas_em_campos_diferentes_nao_somam(sessao, conversa):
+    """O negativo que dá sentido ao positivo: a contagem é POR CAMPO.
+
+    Errar uma vez a data e uma vez o CEP não é "falhou duas vezes" — são dois campos
+    para reperguntar, e reperguntar é barato.
+    """
+    from app.agent.tools import ContextoDoTurno, make_qualify_lead
+    from app.persistence import repo as _repo
+
+    ctx = ContextoDoTurno(sessao=sessao, conversation_id=conversa.id)
+    make_qualify_lead(ctx)(data_inicio="sei lá", plano_id="turbo")
+    sessao.commit()
+
+    contagem = _repo.tentativas_de_extracao(sessao, conversa.id)
+    assert sorted(contagem) == ["data_inicio", "plano_id"]
+    assert all(n == 1 for n in contagem.values())
+    assert not gatilhos.casa(HandoffTrigger.EXTRACAO_FALHOU,
+                             Contexto(tentativas_extracao=contagem))
+
+
+def test_indisponibilidade_nao_repete_a_despedida(sessao, conversa, monkeypatch):
+    """`compor_handoff("cotacao_indisponivel")` já TERMINA com a despedida.
+
+    `_encaminhar` mandava `DESPEDIDA` de novo, e o lead lia a mesma frase, palavra
+    por palavra, em duas mensagens seguidas. Visível no transcript do cenário
+    degradado — e invisível na suíte, porque nenhum teste comparava as mensagens
+    entre si.
+    """
+    from app.agent import turno
+    from app.agent.tools import ContextoDoTurno
+
+    enviadas: list[str] = []
+
+    async def enviar_async(texto, autor="sistema"):
+        enviadas.append(texto)
+
+    ctx = ContextoDoTurno(sessao=sessao, conversation_id=conversa.id)
+    ctx.handoffs.append({
+        "trigger": HandoffTrigger.COTACAO_INDISPONIVEL,
+        "reason": "a cotação não respondeu", "quote_id": None,
+        "disparado_por": "regra", "assunto": None,
+    })
+
+    import asyncio
+    asyncio.run(turno._encaminhar(sessao, conversa.id, ctx, "e aí?", enviar_async))
+
+    assert enviadas == [], (
+        "a mensagem de indisponibilidade sai de dentro da tool; `_encaminhar` não "
+        f"pode mandar nada por cima. Mandou: {enviadas}"
+    )
+    assert textos.DESPEDIDA in textos.compor_handoff("cotacao_indisponivel")
+
+
+def test_uma_cotacao_por_turno(sessao, conversa, monkeypatch):
+    """O modelo chamou `quote_plan` duas vezes no mesmo turno, gerando o transcript.
+
+    O estrago tem três partes: dois jobs contra a `/quote`, dois avisos de espera
+    idênticos em sequência para o lead, e uma linha em `quotes` que ficou `pending`
+    para sempre — rastro inconsistente na tabela que responde pelo critério nº 4.
+    """
+    from app.agent.tools import ContextoDoTurno, make_quote_plan
+
+    ctx = ContextoDoTurno(sessao=sessao, conversation_id=conversa.id)
+    ctx.quote_do_turno = "q_ja_existe"
+
+    resposta = make_quote_plan(ctx)(
+        plano_id="completo", idade=30, veiculo_ano=2020,
+    )
+    assert "já cotado neste turno" in resposta
+    assert "q_ja_existe" in resposta


=== DIFF: tests/nucleo/test_recusa.py ===
@@ -24,6 +24,8 @@ from app import textos
 from app.agent.tools import ContextoDoTurno, make_qualify_lead, make_quote_plan
 from app.contracts.quote import MotivoRecusa, QuoteRequest
 from app.persistence import repo
+
+from tests.fixtures.pii import cep_de
 from app.persistence.models import Handoff, Message, Quote, QuoteAttempt
 from app.quote import client
 from app.quote.breaker import breaker_global, resetar_breaker
@@ -239,8 +241,16 @@ def test_reenquadramento_acontece_em_dois_turnos(ctx, sessao, conversa, canal):
     assert repo.obter_conversa(sessao, conversa.id).state != "encaminhado"
 
     # Turno 2, com o outro veículo: cota normalmente.
-    ctx.ja_enviou = False
-    r = make_quote_plan(ctx)("completo", 35, 2021, "[CEP]", "2026-10-17")
+    #
+    # ⚠️ Um `ContextoDoTurno` NOVO, e não o mesmo com `ja_enviou` zerado. O envelope
+    # é por turno — `responder` constrói um a cada mensagem —, e é ele que carrega a
+    # trava de uma cotação por turno. Reaproveitar o objeto simulava um segundo turno
+    # que não existe em lugar nenhum do código de produção, e esta linha passou a
+    # falhar quando a trava entrou: era o teste que estava frouxo, não a trava.
+    #
+    # Que o reenquadramento leve dois turnos é a decisão §2, não um efeito colateral.
+    ctx2 = ContextoDoTurno(sessao=sessao, conversation_id=conversa.id, enviar=canal)
+    r = make_quote_plan(ctx2)("completo", 35, 2021, cep_de("01"), "2026-10-17")
     assert "cotado" in r
     assert sessao.query(Quote).filter(Quote.status == "ok").count() == 1
 


=== DIFF: tests/nucleo/test_transcripts.py ===
@@ -0,0 +1,208 @@
+"""Os dois transcripts de `artifacts/` são o **entregável nº 4** do enunciado.
+
+Um artefato gerado uma vez e nunca mais conferido apodrece em silêncio: o código muda,
+o texto de espera muda, um limiar muda, e o arquivo continua no repositório afirmando
+um comportamento que já não existe. Este arquivo é o que impede isso.
+
+Ele **não** regenera os transcripts — regenerar exige a `/quote` de pé, o modelo vivo e
+uns dois minutos de relógio. Ele lê o que está commitado e confere que continua sendo
+verdade sobre o código atual: que os textos são os mesmos de `app/textos.py`, que a
+sequência de espera respeita os limiares de `Settings`, e que o desfecho gravado é
+coerente com o cenário anunciado no cabeçalho.
+
+Quando um destes falha, o conserto é regenerar o artefato com o comando que o próprio
+cabeçalho carrega — não editar a asserção.
+"""
+
+from __future__ import annotations
+
+import re
+from pathlib import Path
+
+import pytest
+
+from app import textos
+from app.config import get_settings
+
+RAIZ = Path(__file__).resolve().parents[2]
+FELIZ = RAIZ / "artifacts" / "transcript-feliz.md"
+DEGRADADO = RAIZ / "artifacts" / "transcript-degradado.md"
+
+#: `[  +6.0s]  Δ +6.0s  sistema  texto`
+LINHA = re.compile(r"^\[\s*([+-][\d.]+)s\]\s+(?:Δ\s*([+-][\d.]+)s)?\s+(\S+)\s+(.*)$")
+
+
+def _linhas(caminho: Path) -> list[tuple[float, float | None, str, str]]:
+    saida = []
+    for bruta in caminho.read_text(encoding="utf-8").splitlines():
+        m = LINHA.match(bruta)
+        if m:
+            saida.append((float(m[1]), float(m[2]) if m[2] else None, m[3], m[4]))
+    return saida
+
+
+@pytest.fixture(params=[FELIZ, DEGRADADO], ids=["feliz", "degradado"])
+def transcript(request) -> Path:
+    if not request.param.exists():
+        pytest.fail(
+            f"{request.param.relative_to(RAIZ)} não existe. É o entregável nº 4 do "
+            "enunciado; gere com `scripts/transcript.py` (o comando está no cabeçalho "
+            "do arquivo irmão)."
+        )
+    return request.param
+
+
+# ─── o que vale para os dois ─────────────────────────────────────────────────
+
+
+def test_o_cabecalho_carrega_o_comando_que_reproduz(transcript):
+    """Um artefato sem o comando que o gera é uma captura de tela em markdown."""
+    texto = transcript.read_text(encoding="utf-8")
+    assert "## Como reproduzir" in texto
+    assert "docker compose up -d --build --wait" in texto
+    assert "scripts/transcript.py --cenario" in texto
+
+
+def test_nenhum_valor_monetario_sai_sem_cotacao_vinculada(transcript):
+    """O guardrail, lido do artefato em vez do banco.
+
+    Toda linha com dinheiro tem de ser do `sistema` — o autor dos textos de template.
+    Uma linha do `agente` com `R$` seria o modelo escrevendo preço, que é a coisa que
+    o projeto inteiro existe para impedir.
+    """
+    for _, _, autor, conteudo in _linhas(transcript):
+        if re.search(r"R\$\s*[\d.,]+", conteudo):
+            assert autor in {"sistema", "lead"}, (
+                f"valor monetário numa linha do `{autor}`: {conteudo[:80]!r}"
+            )
+
+
+def test_nenhuma_PII_crua_no_artefato(transcript):
+    """`artifacts/` é varrido inteiro pelo portão de segurança (CLAUDE.md 13a).
+
+    A conversa passa um CEP; ele tem de aparecer mascarado, porque é o que fica
+    gravado. Se um dia o mascaramento sair do caminho, é aqui que aparece.
+    """
+    from app.privacy.mascarar import mascarar
+
+    texto = transcript.read_text(encoding="utf-8")
+    assert texto == mascarar(texto), "há PII crua no artefato"
+    assert "[CEP]" in texto, (
+        "o roteiro passa um CEP e ele deveria aparecer mascarado. Sem isto, ou o "
+        "roteiro mudou ou o mascaramento parou de acontecer."
+    )
+
+
+# ─── o caminho feliz ─────────────────────────────────────────────────────────
+
+
+def test_o_feliz_entrega_a_cotacao_e_termina_cotado():
+    texto = FELIZ.read_text(encoding="utf-8")
+    assert "**Estado final da conversa:** `cotado`" in texto
+    assert "Nenhum." in texto.split("### Handoff")[-1], "o feliz não pode ter handoff"
+
+
+def test_o_feliz_cita_carencia_franquia_e_pro_rata():
+    """Os três itens que a decisão 23 obriga no bloco, e que somem com facilidade.
+
+    A carência de 30 dias é a mais fácil de perder: ela vem em 100 % das respostas
+    200 e omiti-la é vender cobertura que ainda não vale.
+    """
+    texto = FELIZ.read_text(encoding="utf-8")
+    assert "30 dias" in texto and "Roubo e furto" in texto
+    assert "Franquia de R$" in texto
+    assert "proporcional" in texto, "o pro-rata do dia 17 tem de aparecer"
+
+
+def test_o_feliz_nao_avisa_espera_por_uma_cotacao_rapida():
+    """O «só um instante» seguido da resposta — decisão 1, e o defeito que o piso
+    de `piso_aviso_s` corrigiu. Se voltar, volta aqui."""
+    textos_ditos = [c for _, _, _, c in _linhas(FELIZ)]
+    assert textos.AVISO_ESPERA not in textos_ditos
+    assert textos.REFORCO not in textos_ditos
+
+
+def test_o_feliz_tem_exatamente_uma_cotacao():
+    """Duas linhas em `quotes` para um turno significa que o modelo chamou a tool
+    duas vezes — e uma delas fica `pending` para sempre, sujando a tabela que
+    responde pelo critério nº 4."""
+    corpo = FELIZ.read_text(encoding="utf-8").split("### Cotações")[1]
+    ids = re.findall(r"\| `(q_[0-9a-f]+)` \|", corpo.split("####")[0])
+    assert len(ids) == 1, f"esperava uma cotação, achei {ids}"
+    assert "`pending`" not in corpo
+
+
+# ─── o caminho degradado ─────────────────────────────────────────────────────
+
+
+def test_o_degradado_esgota_as_tentativas_e_nao_inventa_preco():
+    texto = DEGRADADO.read_text(encoding="utf-8")
+    assert "**Estado final da conversa:** `encaminhado`" in texto
+    assert "`failed`" in texto
+    assert "cotacao_indisponivel" in texto
+    assert "disparado por **regra**" in texto
+
+    cfg = get_settings()
+    tentativas = re.findall(r"^\| (\d) \| — \(sem resposta\) \| `timeout` \|",
+                            texto, re.MULTILINE)
+    assert len(tentativas) == cfg.quote_max_attempts, (
+        f"o artefato mostra {len(tentativas)} tentativas e a política diz "
+        f"{cfg.quote_max_attempts}"
+    )
+    assert "R$" not in texto.split("## O que ficou gravado")[0], (
+        "nenhum valor podia aparecer: nenhuma tentativa devolveu preço"
+    )
+
+
+def test_o_degradado_mostra_aviso_reforco_e_encaminhamento_na_ordem():
+    """A sequência que o enunciado chama de «o ponto que mais separa».
+
+    A asserção é sobre a ORDEM e sobre os textos literais de `app/textos.py`: um
+    transcript que mostrasse o reforço antes do aviso, ou um texto parafraseado pelo
+    modelo, estaria descrevendo outro produto.
+    """
+    ditos = [(d, c) for _, d, _, c in _linhas(DEGRADADO) if d is not None]
+    esperados = [textos.AVISO_ESPERA, textos.REFORCO]
+
+    achados = [(d, c) for d, c in ditos if c in esperados]
+    assert [c for _, c in achados] == esperados, (
+        f"esperava aviso e depois reforço; achei {[c[:40] for _, c in achados]}"
+    )
+
+    encaminhamento = next(d for d, c in ditos if textos.INDISPONIBILIDADE in c)
+    assert achados[0][0] < achados[1][0] < encaminhamento
+
+
+def test_o_degradado_respeita_os_limiares_configurados():
+    """Os Δ do artefato contra `Settings`, e não contra números escritos à mão.
+
+    O aviso pode sair DEPOIS do limiar — quem agenda os timers é a tool, e o modelo
+    leva alguns segundos para chegar até ela. O que não pode é sair antes: isso
+    significaria avisar sobre uma espera que o lead ainda não teve.
+    """
+    cfg = get_settings()
+    ditos = {c: d for _, d, _, c in _linhas(DEGRADADO) if d is not None}
+
+    assert ditos[textos.AVISO_ESPERA] >= cfg.aviso_espera_s - 0.1
+    assert ditos[textos.REFORCO] >= cfg.reforco_espera_s - 0.1
+
+    # O pior caso da política: 3 × read timeout, mais backoff, mais o tempo que o
+    # modelo levou até a tool. É a aritmética que justifica a cotação ser um job.
+    piso = cfg.quote_max_attempts * cfg.quote_read_timeout_s
+    encaminhamento = next(d for _, d, _, c in _linhas(DEGRADADO)
+                          if d is not None and textos.INDISPONIBILIDADE in c)
+    assert encaminhamento >= piso, (
+        f"o encaminhamento saiu em {encaminhamento:.1f}s, antes de as "
+        f"{cfg.quote_max_attempts} tentativas de {cfg.quote_read_timeout_s}s caberem"
+    )
+
+
+def test_os_textos_do_artefato_sao_os_de_TEXTOS_md():
+    """Byte a byte, e é o ponto: o valor do artefato é ser prova, não ilustração.
+
+    Se o texto do aviso mudar em `docs/TEXTOS.md` e o transcript não for regerado, o
+    entregável passa a mostrar um produto que não existe mais.
+    """
+    corpo = DEGRADADO.read_text(encoding="utf-8")
+    for nome in ("AVISO_ESPERA", "REFORCO", "INDISPONIBILIDADE", "DESPEDIDA"):
+        assert getattr(textos, nome) in corpo, f"{nome} divergiu do artefato"


Investigate per the method in your instructions, then return the findings list.

### Claude

→ **Bash**  `{"command": "find /home -maxdepth 4 -name \"tools.py\" -path \"*/agent/*\" 2>/dev/null; find /root -maxdepth 4 -name \"tools.py\" -path \"*/agent/*\" 2>/dev/null; find / -maxdepth 5 -name \"tools.py\" -path \"*/agent/*\" 2>/dev/null | head -5", "description": "Find repo location"}`

### Mateus

```
This Bash command contains multiple operations. The following part requires approval: find /home -maxdepth 4 -name "tools.py" -path "*/agent/*" ; find /root -maxdepth 4 -name "tools.py" -path "*/agent/*" ; find / -maxdepth 5 -name "tools.py" -path "*/agent/*"
```

### Claude

→ **Glob**  `{"pattern": "**/app/agent/tools.py"}`

### Mateus

```
app/agent/tools.py
```

### Claude

→ **Read**  `{"file_path": "/mnt/user-data/repo/app/agent/tools.py"}`

### Mateus

```
File does not exist. Note: your current working directory is <repo>.
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
… [+20785 caracteres]
```

### Claude

→ **Read**  `{"file_path": "<repo>/app/quote/job.py"}`

### Mateus

```
1	"""A cotação como **job com estado**.
2	
3	Não é preferência de design; é aritmética. O pior caso da política de retry é
4	~37 s — três tentativas de 12 s mais backoff — e isso não cabe dentro de um turno de
5	conversa. Ou o agente fala antes de ter o preço, ou fica mudo por meio minuto.
6	
7	O job grava **toda** tentativa, inclusive as que falham — que é justamente quando a
8	linha do tempo importa. É `quote_attempts` que responde, sem log nenhum: "tentamos 3
9	vezes, a 1ª deu 503 em 40 ms, a 2ª estourou o timeout aos 12 s, a 3ª voltou 200 aos
10	8,01 s".
11	
12	**O laço de retry.** Só `transient` e `timeout` retentam — 3 tentativas levam a 0,8% de
13	falha residual, e a 4ª compraria 0,64 ponto percentual por mais um ciclo que pode ser
14	de 12 s. `400` e `422`, nas duas formas, **nunca** retentam: retentá-los mascara defeito
15	e queima tempo.
16	
17	**A espera é visível.** O relógio é o do lead — conta da chegada da mensagem dele, não
18	de quando a tool começou —, e o disparo é daqui, não de um watchdog genérico na camada
19	de conversa, que dispararia durante a geração do modelo.
20	
21	**O breaker é consultado antes da primeira tentativa.** Com o circuito aberto o job
22	na
… [+9587 caracteres]
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
… [+7797 caracteres]
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
… [+9741 caracteres]
```

### Claude

Based on my review of the diff and the relevant surrounding code (tools.py, turno.py, job.py, models.py), this change is primarily business-logic hardening with no exploitable security defects:

- **`quote_do_turno` guard** in `make_quote_plan` — the interpolated `q.id` is server-generated (`uuid.uuid4().hex`), not attacker-controlled.
- **`tentativas_extracao` JSONB column** — the keys written come from a fixed set (`CAMPOS_QUALIFICACAO` / `rejeitados`), not free-form user input; the dict is passed to SQLAlchemy JSONB (parameterized), no injection surface.
- **`enviar` closure ordering fix** — pure correctness fix for `NameError`; no new sink is introduced.
- **`piso_aviso_s` config + `max(atraso, piso)`** — a floor on a Timer delay, no state-decision impact.
- **Removal of duplicate `DESPEDIDA`** in `_encaminhar` — removes a redundant message; nothing security-relevant.
- **`repo.tentativas_de_extracao`** — reads a JSONB column keyed by fixed field names via SQLAlchemy `Session.get`, no dynamic SQL.
- **Migration 0004** — adds a JSONB column with NOT NULL DEFAULT `'{}'`; hardcoded DDL, no template injection.
- **`scripts/transcript.py`** — CLI tool executed manually inside the container; `--saida` and `--cenario` are operator inputs (argparse `choices`), not a network entrypoint; PII stays masked via existing `mascarar`.
- **Dockerfile** — copies `scripts/` (only `transcript.py`) into the image; the script itself contains no exec/eval/subprocess sinks and no exposed endpoints.
- **Tests** — test-only changes, correctly excluded.

No source→sink path with a missing mitigation was identified.

### Claude

→ **StructuredOutput**  `{"findings": []}`

### Mateus

```
Structured output provided successfully
```
