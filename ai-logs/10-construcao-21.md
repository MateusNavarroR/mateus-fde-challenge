# Sessão de construção 21

> Exportado por `scripts/exportar_ai_logs.py`, com redação de segredo,
> caminho absoluto e PII **na escrita**. 26 turnos; o `jsonl` de
> origem tinha 310 KB, majoritariamente saída de
> ferramenta, truncada em 1200 caracteres por bloco.

### Mateus

Review this change for security vulnerabilities.

Changed files (you may Read these and any other file in the repo):
  - app/agent/turno.py
  - app/channels/web.py
  - app/config.py
  - app/main.py
  - tests/nucleo/test_auth.py
  - tests/nucleo/test_handoff.py
  - tests/web/unit/chat-estado-inicial.test.tsx
  - tests/web/unit/estados.test.tsx
  - tests/web/unit/pagina-chat.test.tsx
  - web/src/admin/PaginaConversas.tsx
  - web/src/chat/BlocoCotacao.tsx
  - web/src/chat/PaginaChat.tsx
  - web/src/chat/markdown.tsx

Unified diff (only + lines are new):

=== DIFF: app/agent/turno.py ===
@@ -107,7 +107,18 @@ async def responder(
                 )
             return
 
+        # O COMMIT é parte do gravar, e não uma formalidade.
+        #
+        # `gravar_turn_usage` faz `flush`, não `commit`. Todo caminho de saída daqui
+        # para baixo que NÃO envia mensagem própria — `ja_enviou`, saída vazia — sai
+        # da sessão sem commitar, e o `flush` volta atrás no rollback do
+        # `with fabrica() as s`. Efeito medido na vistoria: uma conversa de 2 turnos
+        # tinha 1 linha em `turn_usage`, e a que faltava era a do turno da COTAÇÃO.
+        #
+        # Ou seja, o painel de custo perdia exatamente os turnos com tool call — os
+        # mais caros — e o número de C7 saía sistematicamente subestimado.
         _gravar_uso(s, conversation_id, r)
+        s.commit()
 
         if await _encaminhar(s, conversation_id, ctx, texto, enviar_async):
             return
@@ -174,13 +185,23 @@ async def _encaminhar(s, conversation_id: str, ctx, texto: str, enviar_async) ->
         motivo, secundarios, origem = do_modelo["reason"], [], "modelo"
         quote_id, resumo = do_modelo.get("quote_id"), do_modelo.get("summary")
 
-    gatilhos.registrar(
+    handoff = gatilhos.registrar(
         s, conversation_id, trigger, motivo,
         secundarios=secundarios, summary=resumo, quote_id=quote_id,
         disparado_por=origem,
     )
     s.commit()
 
+    # É este push que faz a fila do admin ganhar o caso SEM recarregar — que é o que
+    # a tela de handoffs promete por escrito. Antes, `publicar_evento` não era
+    # chamada em lugar nenhum: o cliente assinava, o servidor aceitava a conexão, e
+    # nada nunca era enviado.
+    from app.channels.web import publicar_evento
+
+    await publicar_evento("handoff.created", {
+        "id": handoff.id, "conversation_id": conversation_id, "trigger": str(trigger),
+    })
+
     # A mensagem de indisponibilidade já saiu de dentro da tool de cotação;
     # repeti-la aqui seria dizer duas vezes a mesma coisa ao lead.
     # A mensagem de indisponibilidade já saiu de dentro da tool de cotação, e


=== DIFF: app/channels/web.py ===
@@ -31,6 +31,7 @@ tentando".
 from __future__ import annotations
 
 import asyncio
+import hmac
 import json
 import logging
 from collections.abc import AsyncIterator
@@ -92,6 +93,16 @@ _TIPOS = frozenset({"text", "image", "audio", "document"})
 #: Conexões de administração, para o push de `/api/events`.
 _admin: set[WebSocket] = set()
 
+#: O laço do servidor, capturado no boot. Uma rota síncrona roda no threadpool do
+#: AnyIO e não tem laço próprio: `get_event_loop()` de lá devolveria outro laço, ou
+#: nada. Guardar o certo no startup é a única forma de o push sair de uma rota `def`.
+_laco: asyncio.AbstractEventLoop | None = None
+
+
+def registrar_laco(laco: asyncio.AbstractEventLoop) -> None:
+    global _laco
+    _laco = laco
+
 
 async def publicar_evento(tipo: str, dados: dict) -> None:
     """`handoff.created`, `handoff.updated`, `quote.attempt`.
@@ -110,6 +121,25 @@ async def publicar_evento(tipo: str, dados: dict) -> None:
         _admin.discard(ws)
 
 
+def publicar_sync(tipo: str, dados: dict) -> None:
+    """`publicar_evento` a partir de uma rota **síncrona**.
+
+    As rotas de operação são `def`, então correm no threadpool do AnyIO e não têm
+    laço de eventos próprio. `run_coroutine_threadsafe` marshala para o laço do
+    servidor; sem esperar o resultado, porque um push perdido nunca pode atrasar ou
+    derrubar a resposta HTTP que o operador está esperando.
+
+    Falhar aqui é silencioso de propósito: o push é conveniência, e a tela recarrega
+    do endpoint de qualquer forma.
+    """
+    if _laco is None:  # sem servidor rodando: teste de unidade, script
+        return
+    try:
+        asyncio.run_coroutine_threadsafe(publicar_evento(tipo, dados), _laco)
+    except Exception:  # noqa: BLE001  # pragma: no cover
+        log.debug("push perdido; a tela recarrega do endpoint")
+
+
 def registrar_websockets(app: FastAPI) -> None:
     @app.websocket("/api/chat/{conversation_id}")
     async def chat(ws: WebSocket, conversation_id: str) -> None:
@@ -162,7 +192,13 @@ def registrar_websockets(app: FastAPI) -> None:
         cfg = get_settings()
         # O navegador não põe cabeçalho no handshake do WebSocket: quando
         # ADMIN_TOKEN está definido, o token vem por query string.
-        if cfg.admin_exigido and ws.query_params.get("token") != cfg.admin_token:
+        # A MESMA comparação que `exigir_admin` faz no REST: ausente coage para `""`
+        # e o confronto é em tempo constante. Antes, o REST coagia e o WS não, então
+        # a mesma requisição sem token era aceita numa porta e recusada na outra.
+        apresentado = ws.query_params.get("token") or ""
+        if cfg.admin_exigido and not hmac.compare_digest(
+            apresentado.encode("utf-8"), (cfg.admin_token or "").encode("utf-8")
+        ):
             await ws.close(code=4401)
             return
         await ws.accept()


=== DIFF: app/config.py ===
@@ -9,6 +9,7 @@ Fonte das medições: `docs/API-COTACAO.md` e `docs/POLITICA-RESILIENCIA.md`.
 
 from __future__ import annotations
 
+from pydantic import field_validator
 from pydantic_settings import BaseSettings, SettingsConfigDict
 
 
@@ -28,6 +29,10 @@ class Settings(BaseSettings):
     #: Opcional e exigido quando definido (CLAUDE.md 14c). Ausente por padrão para que
     #: o caminho de um comando não mude; presente, dá ao passe de segurança uma
     #: resposta em código em vez de "risco aceito" em prosa.
+    #:
+    #: **Vazio é ausente.** Ver o validador abaixo — no shell e no compose não existe
+    #: diferença entre "não defini" e `ADMIN_TOKEN=`, e tratar as duas coisas
+    #: diferente foi o que quebrou o caminho padrão.
     admin_token: str | None = None
 
     # ─── cliente da /quote ───────────────────────────────────────────────────
@@ -86,6 +91,27 @@ class Settings(BaseSettings):
     #: avisar ali produziria "só um instante" seguido da resposta 0,2 s depois.
     aviso_sem_cotacao_s: float = 10.0
 
+    @field_validator("admin_token", mode="after")
+    @classmethod
+    def _vazio_e_ausente(cls, v: str | None) -> str | None:
+        """`ADMIN_TOKEN=` (vazio) significa **não configurado**, e não "token vazio".
+
+        Sem isto, o `docker-compose.yml` — que passa `${ADMIN_TOKEN:-}` e portanto
+        injeta string vazia quando a variável não existe — ligava a exigência de
+        token com um token vazio. Medido no caminho padrão de um comando:
+
+        - `GET /api/handoffs` sem cabeçalho → **200**, porque `exigir_admin` compara
+          `"" == ""` e considera o token válido;
+        - `WS /api/events` sem query → **403**, porque ali a comparação era contra
+          `None` e o ausente não vira `""`;
+        - `WS /api/events?token=` → **101**.
+
+        Ou seja: uma proteção que quebrava o tempo real do admin e não protegia nada,
+        já que `?token=` vazio abria. A normalização é na origem porque o defeito não
+        era de nenhum dos dois consumidores — era do valor.
+        """
+        return v.strip() or None if v is not None else None
+
     @property
     def admin_exigido(self) -> bool:
         return self.admin_token is not None


=== DIFF: app/main.py ===
@@ -60,6 +60,14 @@ async def lifespan(app: FastAPI):
     # Deriva o hash da senha e apaga o texto puro do processo. Antes do primeiro
     # request, para que nenhuma rota veja o ambiente com a senha ainda nele.
     redefinir_credenciais()
+
+    # O laço do servidor, para que uma rota síncrona consiga empurrar evento.
+    import asyncio as _asyncio
+
+    from app.channels import web as _web
+
+    _web.registrar_laco(_asyncio.get_running_loop())
+
     aviso = aviso_de_boot()
     if aviso:
         log.warning(aviso)
@@ -199,8 +207,14 @@ def listar_handoffs(status: str | None = None, limit: int = 50,
 def atualizar_handoff(handoff_id: str, corpo: dict, s: Session = Depends(sessao),
                       _: None = Depends(exigir_admin)):
     from app.api.montagem import transicionar_handoff
-
-    return transicionar_handoff(s, handoff_id, corpo.get("status"))
+    from app.channels.web import publicar_sync
+
+    resultado = transicionar_handoff(s, handoff_id, corpo.get("status"))
+    # Sem isto a fila e a badge de pendentes de QUALQUER outro operador continuam
+    # mostrando o item como pendente até alguém recarregar a página — dois
+    # operadores assumindo o mesmo caso é o resultado.
+    publicar_sync("handoff.updated", {"id": handoff_id})
+    return resultado
 
 
 # ─── websockets ──────────────────────────────────────────────────────────────


=== DIFF: tests/nucleo/test_auth.py ===
@@ -481,3 +481,149 @@ def test_as_rotas_escondidas_do_schema_sao_exatamente_as_declaradas():
         "rota fora do OpenAPI congelado sem decisão escrita — acrescente-a ao "
         "contrato ou a esta lista, com o motivo"
     )
+
+
+# ─── ADMIN_TOKEN vazio é ADMIN_TOKEN ausente ─────────────────────────────────
+#
+# Achado na vistoria de navegação, no caminho padrão de um comando. O
+# `docker-compose.yml` passa `${ADMIN_TOKEN:-}`, que injeta STRING VAZIA quando a
+# variável não existe. `admin_exigido` testava `is not None`, então a exigência
+# ligava com um token vazio — e as duas superfícies discordavam sobre o que isso
+# significa, porque uma coage o ausente para `""` e a outra comparava contra `None`.
+#
+# O resultado medido no navegador: pílula vermelha "sem conexão em tempo real" em
+# toda tela do admin numa instalação saudável, socket reconectando para sempre, e
+# nenhuma proteção real — `?token=` vazio abria.
+
+
+@pytest.mark.parametrize("bruto", ["", "   ", "\t"])
+def test_token_vazio_no_ambiente_nao_liga_a_exigencia(bruto):
+    """É o compose que produz este valor, não uma configuração exótica."""
+    from app.config import Settings
+
+    cfg = Settings(admin_token=bruto)
+    assert cfg.admin_token is None
+    assert cfg.admin_exigido is False
+
+
+def test_token_de_verdade_continua_ligando_a_exigencia():
+    """O negativo: normalizar vazio não pode desligar a proteção de quem a quer."""
+    from app.config import Settings
+
+    cfg = Settings(admin_token="[REDIGIDO]")
+    assert cfg.admin_token == "s3gr3d0", "espaços da borda saem; o valor fica"
+    assert cfg.admin_exigido is True
+
+
+def test_rest_e_websocket_concordam_sobre_o_mesmo_token(cliente, monkeypatch):
+    """A regra que faltava: a MESMA requisição não pode passar numa porta e ser
+    recusada na outra.
+
+    Medido antes da correção, com o token vazio do compose: `GET /api/handoffs` →
+    200 e `WS /api/events` → 403. Um teste por superfície nunca acharia isso; só um
+    teste que compara as duas.
+    """
+    from app.config import get_settings
+
+    cfg = get_settings()
+
+    # ⚠️ O valor CRU, sem `or None`. Escrever `token or None` aqui converteria `""`
+    # em `None` no próprio teste e o faria pular exatamente o caso que ele existe
+    # para cobrir — foi assim que ele nasceu, e passava com o bug presente.
+    for token, esperado_aberto in (("", True), ("s3gr3d0", False)):
+        monkeypatch.setattr(cfg, "admin_token", token)
+
+        rest = cliente.get("/api/handoffs")
+        rest_aberto = rest.status_code != 401
+
+        try:
+            with cliente.websocket_connect("/api/events"):
+                ws_aberto = True
+        except Exception:  # noqa: BLE001
+            ws_aberto = False
+
+        assert rest_aberto == ws_aberto == esperado_aberto, (
+            f"token={token!r}: REST aberto={rest_aberto}, WS aberto={ws_aberto}, "
+            f"esperado={esperado_aberto}"
+        )
+
+
+def test_um_token_vazio_apresentado_nao_abre_o_websocket(cliente, monkeypatch):
+    """`?token=` vazio abria o socket quando a exigência estava ligada com token
+    vazio. Com um token de verdade configurado, apresentar vazio tem de fechar."""
+    from app.config import get_settings
+
+    monkeypatch.setattr(get_settings(), "admin_token", "s3gr3d0")
+    with pytest.raises(Exception):
+        with cliente.websocket_connect("/api/events?token="):
+            pass
+
+
+# ─── o canal de tempo real tinha assinante e não tinha produtor ──────────────
+
+
+def test_publicar_evento_e_de_fato_chamado_pelo_backend():
+    """`publicar_evento` não era chamada em lugar NENHUM do código.
+
+    O cliente assinava `/api/events`, o servidor aceitava a conexão, e nada era
+    enviado — para sempre. A tela de handoffs anunciava por escrito *"a fila entra em
+    tempo real, sem recarregar a página"*, e a fila nunca entrava.
+
+    Um `grep` é o teste certo aqui: o defeito não era um caminho errado, era a
+    AUSÊNCIA de qualquer chamada. Um teste de comportamento cobriria um produtor de
+    cada vez; este falha no dia em que o último for removido.
+    """
+    raiz = Path(__file__).resolve().parents[2]
+    # `app/channels/web.py` fica FORA da varredura: é onde as duas funções moram, e
+    # `publicar_sync` chama `publicar_evento` internamente. Incluí-lo faria o teste
+    # passar provando que a função chama a si mesma — foi assim que ele nasceu, e
+    # sobreviveu à mutação que removia todos os produtores de verdade.
+    definicao = raiz / "app" / "channels" / "web.py"
+    chamadas = [
+        f"{p.relative_to(raiz)}:{n}"
+        for p in (raiz / "app").rglob("*.py")
+        if p != definicao
+        for n, linha in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
+        if ("publicar_evento(" in linha or "publicar_sync(" in linha)
+        and "def " not in linha
+        and "import" not in linha
+    ]
+    assert chamadas, (
+        "nenhum produtor de evento no backend: o push de `/api/events` volta a ser "
+        "uma conexão que nunca recebe nada"
+    )
+
+
+def test_assumir_um_handoff_empurra_para_o_socket(cliente, monkeypatch):
+    """O caminho ponta a ponta: um operador assume, e o socket de QUALQUER outro
+    recebe — que é o que impede dois operadores de pegarem o mesmo caso.
+
+    Também é o que faz a badge de pendentes deste mesmo cliente descer de 7 para 6
+    sem F5: ela mora no `LayoutAdmin`, longe da página que faz a ação, e escuta o
+    push.
+    """
+    import app.main as main
+    from app.channels import web
+
+    empurrados: list[tuple[str, dict]] = []
+    monkeypatch.setattr(web, "publicar_sync",
+                        lambda tipo, dados: empurrados.append((tipo, dados)))
+    monkeypatch.setattr(
+        "app.api.montagem.transicionar_handoff",
+        lambda s, hid, status: {"id": hid, "status": status},
+    )
+    monkeypatch.setattr(main, "sessao", lambda: None, raising=False)
+
+    # O `transicionar_handoff` de mentira não satisfaz o `response_model`, e a
+    # validação da RESPOSTA acontece depois do push. Isto é aceitável aqui porque o
+    # comportamento sob teste é o push: montar um `HandoffOut` completo faria o teste
+    # passar a exercitar `montar_handoffs`, que tem os seus próprios testes.
+    try:
+        cliente.patch("/api/handoffs/ho_1", json={"status": "assumido"})
+    except Exception:  # noqa: BLE001
+        pass
+
+    assert ("handoff.updated", {"id": "ho_1"}) in empurrados, (
+        "assumir um handoff não empurrou nada: a fila e a badge de outro operador "
+        "seguem mostrando o caso como pendente até alguém recarregar"
+    )


=== DIFF: tests/nucleo/test_handoff.py ===
@@ -571,3 +571,69 @@ def test_uma_cotacao_por_turno(sessao, conversa, monkeypatch):
     )
     assert "já cotado neste turno" in resposta
     assert "q_ja_existe" in resposta
+
+
+# ─── o custo do turno sobrevive ao fim do turno ──────────────────────────────
+
+
+async def test_turno_em_que_a_tool_responde_grava_o_custo(sessao, conversa, monkeypatch):
+    """Achado na vistoria: uma conversa de 2 turnos tinha 1 linha em `turn_usage`, e
+    a que faltava era a do turno da COTAÇÃO.
+
+    `gravar_turn_usage` faz `flush`, não `commit`. O caminho `ja_enviou → return`
+    saía da sessão sem commitar e o rollback levava a linha junto. O turno sem tool
+    sobrevivia só porque `enviar_async` commitava depois, por acidente.
+
+    Um teste de `gravar_turn_usage` isolado passaria com o bug presente: ele grava
+    certo. Quem perdia era o TURNO. Por isso a asserção é depois de `responder`, com
+    sessão nova — que é o que prova que a linha atravessou o commit.
+    """
+    from app.agent import runner, turno
+    from app.persistence.db import sessao_factory
+    from app.persistence.models import TurnUsage
+
+    class Metrics:
+        input_tokens, output_tokens = 1234, 567
+        cache_read_tokens, cache_write_tokens = 890, 0
+        duration = 1.5
+
+    class AgenteComTool:
+        """Imita o turno de cotação: a tool fala com o lead e o texto do modelo é
+        descartado — que é o caminho em que a linha sumia."""
+
+        def run(self, _texto):
+            ctx.ja_enviou = True
+            return type("R", (), {"content": "texto que será descartado",
+                                  "metrics": Metrics()})()
+
+    ctx = None
+    original = turno.ContextoDoTurno if hasattr(turno, "ContextoDoTurno") else None
+
+    def construir(c):
+        nonlocal ctx
+        ctx = c
+        return AgenteComTool()
+
+    monkeypatch.setattr(turno, "construir_agente", construir)
+
+    class Canal:
+        name = "web"
+
+        async def send(self, *a, **kw):
+            return "x"
+
+        async def typing(self, *a, **kw):
+            return None
+
+    await runner.processar_turno_web(conversa.id, "quanto fica?", Canal())
+
+    # Sessão NOVA: é ela que distingue "flushado" de "commitado".
+    with sessao_factory()() as outra:
+        linhas = outra.query(TurnUsage).filter_by(conversation_id=conversa.id).all()
+
+    assert len(linhas) == 1, (
+        "o turno em que a tool respondeu não gravou custo — é o turno com tool "
+        "call, o mais caro, e o painel o perdia"
+    )
+    assert linhas[0].tokens_in == 1234
+    assert linhas[0].cache_read == 890


=== DIFF: tests/web/unit/chat-estado-inicial.test.tsx ===
@@ -7,7 +7,7 @@
  * exatamente como `MIDIA_SEM_TEXTO` ficou inalcançável em produção com o teste
  * verde. Por isso a asserção é feita sobre a TELA montada.
  */
-import { render, screen, waitFor } from "@testing-library/react";
+import { render, screen, waitFor, within } from "@testing-library/react";
 import userEvent from "@testing-library/user-event";
 import { afterEach, beforeEach, expect, it, vi } from "vitest";
 import { WebSocketFalso } from "../fakes/websocket-falso";
@@ -134,3 +134,30 @@ it("uma mensagem de texto NÃO ganha rótulo de anexo", async () => {
   await screen.findByText(/atendente da equipe/i);
   expect(screen.queryByTestId("marca-anexo")).toBeNull();
 });
+
+
+it("a conversa travada oferece a saída JUNTO do campo, não só no topo", async () => {
+  // Achado na vistoria: entrando pela capa — que promete "fale com o agente e peça
+  // uma cotação" — dá para cair numa conversa `encaminhado` de sessão anterior, com
+  // o campo morto. A saída existia, a três centímetros dali e sem relação visual com
+  // o problema. A pergunta 2 da vistoria não falhava (não era beco sem saída), mas a
+  // promessa da capa não batia com o destino.
+  abrirSessao.mockResolvedValue({
+    id: "c1",
+    detalhe: { id: "c1", state: "encaminhado", perfil: {}, quotes: [], handoffs: [],
+               messages: MENSAGENS },
+  });
+  reiniciarSessao.mockResolvedValue("c2");
+
+  const usuario = userEvent.setup();
+  render(<PaginaChat />);
+
+  const aviso = await screen.findByText(/o campo abaixo está travado/i);
+  const acao = within(aviso).getByRole("button", { name: /conversa nova/i });
+
+  await usuario.click(acao);
+
+  await waitFor(() => {
+    expect(screen.getByRole("textbox", { name: /sua mensagem/i })).toBeEnabled();
+  });
+});


=== DIFF: tests/web/unit/estados.test.tsx ===
@@ -1,4 +1,5 @@
 import { render, screen, within } from "@testing-library/react";
+import userEvent from "@testing-library/user-event";
 import { expect, it } from "vitest";
 import { Admin } from "../../../web/src/admin/Admin";
 import { montarBackendFalso } from "../fakes/backend-falso";
@@ -40,3 +41,24 @@ it.each([
   // Piso, não teto: o jsdom não faz layout. O Playwright confere no navegador.
   expect(raiz.scrollWidth).toBeLessThanOrEqual(raiz.clientWidth);
 });
+
+it("filtro sem resultado NÃO diz que o banco está vazio", async () => {
+  // Achado na vistoria: com 14 conversas no banco e o filtro em `fechado`, a tela
+  // dizia "o banco está no ar e vazio" e mandava abrir o /chat para criar uma
+  // conversa. O próximo passo certo era limpar o filtro, e a tela apontava para o
+  // lado oposto — a pergunta 3 da vistoria ("algum estado vazio deixa de explicar o
+  // que fazer?") falhando.
+  const usuario = userEvent.setup();
+  montarBackendFalso({ tudoVazio: true });
+  render(<Admin rota="/admin/conversas" />);
+
+  const vazio = await screen.findByTestId("estado-vazio");
+  expect(vazio).toHaveTextContent(/banco está no ar e vazio/i);
+
+  await usuario.selectOptions(screen.getByLabelText(/estado/i), "fechado");
+
+  const filtrado = await screen.findByTestId("estado-vazio");
+  expect(filtrado).toHaveTextContent(/fechado/);
+  expect(filtrado).toHaveTextContent(/filtro/i);
+  expect(filtrado).not.toHaveTextContent(/banco está no ar e vazio/i);
+});


=== DIFF: tests/web/unit/pagina-chat.test.tsx ===
@@ -101,6 +101,17 @@ it("o bloco da cotação preserva o texto do renderer e não formata número", a
   expect(cotacao).toHaveAttribute("data-quote-id", "q1");
   expect(cotacao).toHaveTextContent("R$ 392,25/mês");
   expect(cotacao).toHaveTextContent(/30 dias/);
+
+  // A ênfase do template é estilo WhatsApp (`*assim*`), porque o canal imita o
+  // WhatsApp. Achado na vistoria: o bloco renderizava a linha crua e o lead lia
+  // `*Completo — R$ 392,25/mês*` COM os asteriscos — na linha mais importante do
+  // produto. Este teste passava porque `toHaveTextContent` ignora os marcadores.
+  expect(cotacao.textContent).not.toMatch(/\*/);
+  expect(cotacao.querySelector("em")).toHaveTextContent("Completo — R$ 392,25/mês");
+
+  // E o número segue sem ser reformatado: o valor é byte a byte o do renderer.
+  expect(cotacao).toHaveTextContent("392,25");
+  expect(cotacao).not.toHaveTextContent("392.25");
   // Bloco com cotação vinculada não é marcado como bug.
   expect(screen.queryByTestId("marca-bug")).toBeNull();
 });


=== DIFF: web/src/admin/PaginaConversas.tsx ===
@@ -79,11 +79,28 @@ export function PaginaConversas() {
         </span>
       </div>
 
+      {/*
+        Dois vazios diferentes, e confundi-los foi um achado da vistoria: com 14
+        conversas no banco e o filtro em `fechado`, a tela dizia "o banco está no ar e
+        VAZIO" e mandava abrir o `/chat` para criar uma. O próximo passo certo era
+        limpar o filtro, e a tela apontava para o lado oposto.
+
+        "Nenhum resultado" e "nenhum dado" pedem ações contrárias. Quem está filtrando
+        sabe que filtrou; o que ele não sabe é que o filtro é a causa.
+      */}
       {linhas.length === 0 && !carregando ? (
-        <Vazio titulo="Nenhuma conversa ainda">
-          O banco está no ar e vazio. Abra <code>/chat</code>, mande uma mensagem, e ela
-          aparece aqui com id, estado e o desfecho da cotação.
-        </Vazio>
+        estado ? (
+          <Vazio titulo={`Nenhuma conversa em «${estado}»`}>
+            O filtro está ativo e nada casou com ele. Volte para{" "}
+            <strong>todos</strong> para ver a lista inteira — pode haver conversas em
+            outros estados.
+          </Vazio>
+        ) : (
+          <Vazio titulo="Nenhuma conversa ainda">
+            O banco está no ar e vazio. Abra <code>/chat</code>, mande uma mensagem, e
+            ela aparece aqui com id, estado e o desfecho da cotação.
+          </Vazio>
+        )
       ) : (
         <table className="tabela" role="table">
           <thead>


=== DIFF: web/src/chat/BlocoCotacao.tsx ===
@@ -1,3 +1,4 @@
+import { Inline } from "./markdown";
 import type { Mensagem } from "./useConversa";
 
 /**
@@ -7,9 +8,14 @@ import type { Mensagem } from "./useConversa";
  * valor monetário. Formatar moeda aqui abriria uma segunda origem de preço — e o
  * invariante é que o preço nunca vem de outro lugar que não a `/quote`.
  *
- * A tela faz só duas coisas: preserva as quebras de linha e destaca a linha da
- * carência, que já vem marcada do template. A carência é a ressalva que gera
- * reclamação depois se passar batida, então ela tem tratamento próprio.
+ * A tela faz três coisas: preserva as quebras de linha, destaca a linha da carência
+ * — que já vem marcada do template, e é a ressalva que gera reclamação depois se
+ * passar batida — e converte os marcadores de ênfase do template.
+ *
+ * A ênfase é estilo WhatsApp (`*assim*`), porque o canal imita o WhatsApp. Antes de
+ * passar pelo `Inline`, o lead lia `*Completo — R$ 392,25/mês*` com os asteriscos, na
+ * primeira linha do bloco. `Inline` converte marcador em elemento e não toca em
+ * dígito nem em moeda, então a regra acima continua valendo.
  */
 export function BlocoCotacao({ mensagem }: { mensagem: Mensagem }) {
   const linhas = mensagem.conteudo.split("\n");
@@ -31,7 +37,7 @@ export function BlocoCotacao({ mensagem }: { mensagem: Mensagem }) {
         return (
           // A ordem das linhas é fixa e vem do template: o índice é a identidade.
           <p key={`${mensagem.id}-${i}`} className={classe}>
-            {linha}
+            <Inline linha={linha} />
           </p>
         );
       })}


=== DIFF: web/src/chat/PaginaChat.tsx ===
@@ -177,10 +177,30 @@ export function PaginaChat({ conversationId }: { conversationId?: string }) {
       </main>
 
       <footer className="chat__rodape">
+        {/*
+          A saída fica AQUI, junto do campo travado, e não só no botão do topo.
+
+          Achado na vistoria: entrando pela capa — que promete "fale com o agente e
+          peça uma cotação" — dá para cair numa conversa `encaminhado` de uma sessão
+          anterior, com o campo morto. A tela explicava o porquê e a saída existia,
+          mas a três centímetros dali e sem relação visual com o problema.
+
+          Não é caso de apagar o histórico ao carregar: a retomada é deliberada, e um
+          F5 no meio de uma janela de 37 s não pode destruir a conversa. O que faltava
+          era a ação estar onde a pessoa está olhando quando descobre que não pode
+          escrever.
+        */}
         {estado.entradaBloqueada ? (
           <p className="chat__travado">
             Já passei sua conversa pra um atendente da equipe. A equipe assume daqui — por
-            isso o campo abaixo está travado.
+            isso o campo abaixo está travado.{" "}
+            <button
+              type="button"
+              className="chat__travado-acao"
+              onClick={trocarDeConversa}
+            >
+              Começar uma conversa nova
+            </button>
           </p>
         ) : null}
         <form


=== DIFF: web/src/chat/markdown.tsx ===
@@ -47,7 +47,17 @@ function fatiar(linha: string): Trecho[] {
   return trechos;
 }
 
-function Inline({ linha }: { linha: string }): ReactNode {
+/**
+ * Exportado para o `BlocoCotacao`: o bloco de cotação vem do template em
+ * `quote/renderer.py`, que usa ênfase estilo WhatsApp (`*assim*`) porque o canal
+ * imita o WhatsApp. Sem passar por aqui, o lead lia `*Completo — R$ 392,25/mês*`
+ * com os asteriscos — na linha mais importante do produto.
+ *
+ * Reusar isto **não** viola o "este componente não formata número nenhum": `Inline`
+ * converte marcador de ênfase em elemento e não toca em dígito, separador nem
+ * símbolo de moeda.
+ */
+export function Inline({ linha }: { linha: string }): ReactNode {
   return fatiar(linha).map((t, i) => {
     if (t.tipo === "negrito") return <strong key={i}>{t.valor}</strong>;
     if (t.tipo === "italico") return <em key={i}>{t.valor}</em>;


Investigate per the method in your instructions, then return the findings list.

### Claude

→ **Read**  `{"file_path": "/"}`

### Mateus

```
EISDIR: illegal operation on a directory, read '/'
```

### Claude

→ **Bash**  `{"command": "pwd && ls", "description": "Find working directory"}`

### Mateus

```
<repo>
ai-logs
app
artifacts
CLAUDE.md
config
db
docker-compose.yml
Dockerfile
docs
node_modules
pyproject.toml
qa
quote-service
README.md
scripts
tests
uv.lock
web
```

### Claude

→ **Read**  `{"file_path": "<repo>/app/channels/web.py"}`

### Mateus

```
1	"""Adaptador `web` da porta `ChannelAdapter`, sobre WebSocket.
2	
3	**O problema que ele resolve:** a tool de cotação bloqueia até o job resolver — até
4	~37 s no pior caso — e fala durante a espera. Aviso aos 6 s, reforço aos ~20 s, e o
5	bloco da cotação quando resolve. São **três mensagens separadas que aparecem enquanto
6	o turno não terminou**.
7	
8	O WebSocket não é request/response, então não há acoplamento a desfazer: quem chama
9	`send()` no meio do turno é a tool, e o frame sai na hora.
10	
11	Ordem dos frames num turno degradado:
12	
13	    1. MessageEvent  autor=lead      eco com o id e o `index` canônicos
14	    2. TypingEvent   ativo=true      ao adquirir o lock do turno
15	    3. MessageEvent  autor=sistema   aviso, aos 6 s          ← da tool
16	    4. MessageEvent  autor=sistema   reforço, aos ~20 s      ← da tool
17	    5. MessageEvent  autor=sistema   bloco da cotação        ← da tool, com quote_id
18	    6. MessageEvent  autor=agente    só quando há texto do modelo
19	    7. StateEvent                    na mudança de estado
20	    8. TypingEvent   ativo=false     ao liberar o lock
21	
22	O indicador de digitando **permanece** entre 2 e 8, inclusive enquanto 3,
… [+8019 caracteres]
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
… [+10651 caracteres]
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
… [+9032 caracteres]
```

### Claude

→ **Read**  `{"file_path": "<repo>/web/src/chat/markdown.tsx"}`

### Mateus

```
1	import type { ReactNode } from "react";
2	
3	/**
4	 * Um subconjunto seguro de Markdown, renderizado como elementos React.
5	 *
6	 * O agente escreve `**Essencial**`, listas com `-` e listas numeradas — é assim que
7	 * ele explica os planos, e sem renderizar isso o lead lê asteriscos.
8	 *
9	 * **Por que um renderizador próprio e não uma biblioteca.** Duas razões, e a segunda
10	 * é a que decide:
11	 *
12	 * 1. O que o agente produz é um subconjunto pequeno e conhecido: negrito, itálico,
13	 *    código, listas e parágrafos. Uma biblioteca completa traria tabelas, HTML
14	 *    embutido, links e imagens — superfície que ninguém pediu.
15	 * 2. **Nada aqui passa por `dangerouslySetInnerHTML`.** O texto renderizado vem em
16	 *    parte do modelo e em parte do próprio lead, e os dois são conteúdo não
17	 *    confiável. Construir nós React em vez de HTML significa que uma tentativa de
18	 *    injeção sai como texto — que é exatamente o que se quer, e é o mesmo princípio
19	 *    que trata a mensagem do lead como dado e nunca como instrução.
20	 *
21	 * O que NÃO é suportado, de propósito: links, imagens, HTML embutido, tabelas e
22	 * títulos. Se o agente algum dia produzir isso
… [+4400 caracteres]
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
12	from pydantic import field_validator
13	from pydantic_settings import BaseSettings, SettingsConfigDict
14	
15	
16	class Settings(BaseSettings):
17	    model_config = SettingsConfigDict(
18	        env_prefix="APP_", env_file=".env", extra="ignore"
19	    )
20	
21	    # ─── infraestrutura ──────────────────────────────────────────────────────
22	    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/autoseguro"
23	    quote_api_url: str = "http://localhost:8000"
24	
25	    #: Model-string do Agno. Só `anthropic:` e `ollama:` são validados por smoke test;
26	    #: os demais funcionam pela mesma string mas NÃO foram testados (CLAUDE.md 15).
27	    llm_model: str = "anthropic:claude-opus-5"
28	
29	    #: Opcional e exigido quando definido (CLAUDE.md 14c). Ausente por pad
… [+5270 caracteres]
```

### Claude

→ **Read**  `{"file_path": "<repo>/web/src/chat/PaginaChat.tsx"}`

### Mateus

```
1	import { Casca } from "../ui/Casca";
2	import { useEffect, useRef, useState } from "react";
3	import type {
4	  ConversationDetail,
5	  EstadoConversa,
6	  Message,
7	  TipoMensagem,
8	} from "../api/tipos";
9	import { Bolha } from "./Bolha";
10	import { BlocoCotacao } from "./BlocoCotacao";
11	import { Digitando } from "./Digitando";
12	import { abrirSessao, reiniciarSessao } from "./sessao";
13	import { useConversa } from "./useConversa";
14	
15	const ESTADO_LEGIVEL: Record<string, string> = {
16	  novo: "conversa aberta",
17	  qualificando: "coletando dados",
18	  cotando: "cotação em andamento",
19	  cotado: "cotação entregue",
20	  fechado: "conversa encerrada",
21	  encaminhado: "com a equipe",
22	};
23	
24	/**
25	 * A tela é um **cliente burro** de um fluxo de eventos. Ela não decide nada
26	 * sobre a conversa: recebe `MessageEvent`, `TypingEvent` e `StateEvent`, mantém
27	 * um mapa `id → Message` e renderiza ordenado por `index`.
28	 *
29	 * Não existe cronômetro aqui. Os 6 s e os 20 s da política de degradação são do
30	 * backend — se a tela tivesse um `setTimeout(6000)`, existiriam duas cópias da
31	 * política e elas divergiriam na primeira mudança de limiar.
32	 */
… [+9352 caracteres]
```

### Claude

→ **Read**  `{"file_path": "<repo>/web/src/admin/PaginaConversas.tsx"}`

### Mateus

```
1	import { useCallback, useId, useState } from "react";
2	import { api } from "../api/cliente";
3	import { ESTADOS_CONVERSA } from "../api/tipos";
4	import type { ConversationSummary, PaginaConversas as Pagina, StatusJob } from "../api/tipos";
5	import { Erro } from "../ui/Erro";
6	import { Vazio } from "../ui/Vazio";
7	import { instante } from "../ui/formatar";
8	import { useRecurso } from "../ui/useRecurso";
9	
10	/**
11	 * `refused` e `failed` precisam ser distinguíveis à primeira vista.
12	 *
13	 * Recusa é desfecho de **negócio** e não gera handoff; `failed` é
14	 * indisponibilidade e gera. Empilhar os dois no mesmo cinza apagaria a decisão
15	 * mais importante do produto — por isso cores diferentes, não dois tons.
16	 */
17	const SELO_COTACAO: Record<StatusJob, { texto: string; classe: string }> = {
18	  pending: { texto: "cotando", classe: "selo selo--espera" },
19	  ok: { texto: "cotada", classe: "selo selo--ok" },
20	  refused: { texto: "recusada", classe: "selo selo--recusa" },
21	  failed: { texto: "falhou", classe: "selo selo--falha" },
22	};
23	
24	export function PaginaConversas() {
25	  const idFiltro = useId();
26	  const [estado, setEstado] = useState<string>("")
… [+5621 caracteres]
```

### Claude

→ **Read**  `{"file_path": "<repo>/web/src/chat/BlocoCotacao.tsx"}`

### Mateus

```
1	import { Inline } from "./markdown";
2	import type { Mensagem } from "./useConversa";
3	
4	/**
5	 * **Este componente não formata número nenhum.**
6	 *
7	 * O bloco chega pronto do `quote/renderer.py`, que é a origem única do texto com
8	 * valor monetário. Formatar moeda aqui abriria uma segunda origem de preço — e o
9	 * invariante é que o preço nunca vem de outro lugar que não a `/quote`.
10	 *
11	 * A tela faz três coisas: preserva as quebras de linha, destaca a linha da carência
12	 * — que já vem marcada do template, e é a ressalva que gera reclamação depois se
13	 * passar batida — e converte os marcadores de ênfase do template.
14	 *
15	 * A ênfase é estilo WhatsApp (`*assim*`), porque o canal imita o WhatsApp. Antes de
16	 * passar pelo `Inline`, o lead lia `*Completo — R$ 392,25/mês*` com os asteriscos, na
17	 * primeira linha do bloco. `Inline` converte marcador em elemento e não toca em
18	 * dígito nem em moeda, então a regra acima continua valendo.
19	 */
20	export function BlocoCotacao({ mensagem }: { mensagem: Mensagem }) {
21	  const linhas = mensagem.conteudo.split("\n");
22	
23	  return (
24	    <div
25	      className="cotacao"
26	      data-testid="bloco-cota
… [+815 caracteres]
```

### Claude

Looking at all changed files, let me verify a couple of remaining traces before concluding.

### Claude

→ **Grep**  `{"pattern": "publicar_evento|publicar_sync", "path": "<repo>/app", "output_mode": "content", "-n": true}`

### Mateus

```
app/main.py:210:    from app.channels.web import publicar_sync
app/main.py:216:    publicar_sync("handoff.updated", {"id": handoff_id})
app/agent/turno.py:196:    # a tela de handoffs promete por escrito. Antes, `publicar_evento` não era
app/agent/turno.py:199:    from app.channels.web import publicar_evento
app/agent/turno.py:201:    await publicar_evento("handoff.created", {
app/channels/web.py:107:async def publicar_evento(tipo: str, dados: dict) -> None:
app/channels/web.py:124:def publicar_sync(tipo: str, dados: dict) -> None:
app/channels/web.py:125:    """`publicar_evento` a partir de uma rota **síncrona**.
app/channels/web.py:138:        asyncio.run_coroutine_threadsafe(publicar_evento(tipo, dados), _laco)
```
