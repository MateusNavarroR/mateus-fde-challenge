# Sessão de construção 18

> Exportado por `scripts/exportar_ai_logs.py`, com redação de segredo,
> caminho absoluto e PII **na escrita**. 7 turnos; o `jsonl` de
> origem tinha 321 KB, majoritariamente saída de
> ferramenta, truncada em 1200 caracteres por bloco.

### Mateus

Review this change for security vulnerabilities.

Changed files (you may Read these and any other file in the repo):
  - web/src/api/cliente.ts
  - web/src/ui/Login.tsx
  - tests/dados/test_replay_resiliencia.py
  - tests/dados/test_replay_assercoes.py
  - tests/dados/test_replay_relatorio.py
  - tests/dados/test_replay_respondedor.py
  - quote-service/app/quote_logic.py
  - web/src/ui/useAutenticacao.ts
  - quote-service/app/main.py
  - quote-service/data/plans.json
  - web/src/App.tsx
  - app/main.py
  - qa/replay/captura.py
  - Dockerfile
  - qa/replay/assercoes.py
  - tests/nucleo/test_contrato_openapi.py
  - tests/dados/test_preco_contra_api.py
  - web/src/ui/Capa.tsx
  - docker-compose.yml
  - quote-service/pyproject.toml
  - web/src/admin/LayoutAdmin.tsx
  - quote-service/Dockerfile
  - tests/dados/test_replay_precos.py
  - tests/nucleo/test_compose.py
  - app/bootstrap.py
  - qa/replay/amostra.py
  - tests/nucleo/test_bootstrap.py
  - qa/replay/respondedor.py
  - tests/dados/test_replay_amostra.py
  - qa/replay/casos.py

Unified diff (only + lines are new):

=== DIFF: web/src/api/cliente.ts ===
@@ -8,6 +8,12 @@
  * `ADMIN_TOKEN` é **opcional e exigido quando definido** (CLAUDE.md 14c). Sem
  * token gravado, nenhum cabeçalho é enviado — mandar um cabeçalho vazio
  * transformaria um token opcional em token obrigatório mal configurado.
+ *
+ * A **sessão de login não passa por aqui**, e isso é o ponto: ela vive num cookie
+ * `httpOnly` que este código não consegue ler nem escrever. `credentials:
+ * "same-origin"` é o que o navegador precisa para anexá-lo — e é o único
+ * envolvimento do JavaScript com a credencial da operação. Nada de sessão em
+ * `localStorage`: se este arquivo pudesse ler o segredo, um XSS também poderia.
  */
 
 import type {
@@ -58,6 +64,31 @@ export const ROTAS = {
   eventos: () => "/api/events",
 } as const;
 
+/**
+ * As três rotas de autenticação, **fora do `openapi.yaml` congelado de propósito**.
+ *
+ * Elas ficam num objeto separado de `ROTAS` porque `ROTAS` é o inventário do
+ * contrato: `tests/web/unit/openapi-deriva.test.ts` afirma que toda rota ali existe
+ * na spec, e misturar as duas coisas obrigaria a relaxar essa afirmação — que é
+ * justamente o teste que pega superfície não documentada.
+ *
+ * O `openapi.yaml` foi congelado na Fase 0 como o contrato do produto. Login não é
+ * produto: é o mecanismo pelo qual um humano alcança o produto, e o backend as monta
+ * com `include_in_schema=False`, com inventário fechado em `tests/nucleo/test_auth.py`.
+ */
+export const ROTAS_AUTENTICACAO = {
+  estado: () => "/api/auth/estado",
+  entrar: () => "/api/auth/login",
+  sair: () => "/api/auth/logout",
+} as const;
+
+/** O que a UI precisa saber antes de decidir se mostra o login. */
+export type EstadoAuth = {
+  /** `false` quando a instalação não configurou ADMIN_USER/ADMIN_PASSWORD. */
+  exigido: boolean;
+  autenticado: boolean;
+};
+
 export type TipoErro =
   | "nao_autorizado"
   | "nao_encontrado"
@@ -126,7 +157,10 @@ const TEXTO_PADRAO: Record<TipoErro, string> = {
 async function executar<T>(url: string, init: RequestInit): Promise<T> {
   let resposta: Response;
   try {
-    resposta = await fetch(url, init);
+    // `same-origin` anexa o cookie de sessão. É o default do `fetch` moderno, mas
+    // explícito porque a autenticação inteira depende dele: um dia alguém troca o
+    // `fetch` por outro cliente e o default some junto.
+    resposta = await fetch(url, { credentials: "same-origin", ...init });
   } catch {
     // Backend fora do ar vira erro tipado, nunca uma tela em branco.
     throw new ErroApi("indisponivel", TEXTO_PADRAO.indisponivel, null, null);
@@ -137,8 +171,16 @@ async function executar<T>(url: string, init: RequestInit): Promise<T> {
     let message = TEXTO_PADRAO[tipo];
     let error: string | null = null;
     try {
-      const corpo = (await resposta.json()) as Partial<{ error: string; message: string }>;
+      const corpo = (await resposta.json()) as Partial<{
+        error: string;
+        message: string;
+        // As rotas do contrato devolvem `{error, message}`; o `HTTPException` do
+        // FastAPI devolve `{detail}`. Ler só o primeiro fazia toda recusa de login
+        // virar o texto genérico — e o texto genérico ainda falava de ADMIN_TOKEN.
+        detail: string;
+      }>;
       if (typeof corpo?.message === "string" && corpo.message.length > 0) message = corpo.message;
+      else if (typeof corpo?.detail === "string" && corpo.detail.length > 0) message = corpo.detail;
       if (typeof corpo?.error === "string") error = corpo.error;
     } catch {
       // 401 sem corpo é comum: um erro tipado, não um crash de parse.
@@ -184,4 +226,10 @@ export const api = {
     get<FilaHandoffs>(ROTAS.handoffs(params)),
   transicionarHandoff: (id: string, status: StatusHandoff) =>
     patch<Handoff>(ROTAS.handoff(id), { status }),
+
+  estadoAutenticacao: () => get<EstadoAuth>(ROTAS_AUTENTICACAO.estado()),
+  /** Resolve quando a sessão foi criada; rejeita com `ErroApi` quando não. */
+  entrar: (usuario: string, senha: string) =>
+    post<void>(ROTAS_AUTENTICACAO.entrar(), { usuario, senha }),
+  sair: () => post<void>(ROTAS_AUTENTICACAO.sair(), {}),
 };


=== DIFF: web/src/ui/Login.tsx ===
@@ -0,0 +1,151 @@
+import { useId, useState } from "react";
+import { ErroApi, api } from "../api/cliente";
+import { reconsultarAutenticacao } from "./useAutenticacao";
+
+/**
+ * A porta da 2ª via.
+ *
+ * **A ideia, e ela vem do domínio, não de um padrão de dashboard.** O sistema já
+ * chama suas duas áreas de *vias* de um mesmo documento: a 1ª é do cliente, a 2ª
+ * fica no arquivo. Pedir credencial para a 2ª via não é "fazer login num app" — é
+ * **requisitar acesso ao arquivo**, e o balcão pergunta quem está requisitando. Toda
+ * a tela é escrita nessa voz, e por isso ela se explica sem instrução de uso.
+ *
+ * **A folha é a mesma da capa**, deliberadamente: quem clicou na 2ª via não trocou
+ * de aplicação, encontrou um balcão. O que muda é uma coisa só, e ela é o elemento
+ * mais forte da tela — a **linha picotada** acima do formulário, onde a 1ª via foi
+ * destacada. É a única marca que diz, sem texto, "você está na segunda folha".
+ *
+ * **O que a tela NÃO faz, e cada omissão é uma decisão:**
+ *
+ * - *não tem carimbo girado.* O sistema visual reserva escala e rotação a um único
+ *   elemento na aplicação inteira, o disjuntor em `/admin/status`. Um segundo carimbo
+ *   aqui roubaria dele exatamente o que o torna achável em dois segundos;
+ * - *não tem "lembrar de mim".* A sessão já dura um turno e vive num cookie
+ *   `httpOnly`; a caixinha só serviria para dar a impressão de controle sobre algo
+ *   que o servidor decide;
+ * - *não tem "esqueci a senha".* Não há cadastro, e-mail nem recuperação: a
+ *   credencial é uma variável de ambiente de quem operou o `docker compose`. Um link
+ *   que não leva a lugar nenhum é pior que a ausência dele — a nota do rodapé diz a
+ *   verdade em uma linha;
+ * - *não diz se o usuário existe.* O backend devolve a mesma recusa para nome errado
+ *   e senha errada, e a tela repete essa recusa sem enfeitar.
+ *
+ * **Nada de senha sai daqui.** O campo é `type="password"`, `autoComplete` é
+ * `current-password` (o gerenciador do navegador é a resposta certa para "onde
+ * guardo isso"), o formulário é `POST` por `fetch` — nunca `GET`, que poria a senha
+ * na barra de endereços e no log do servidor — e o estado local é descartado no
+ * sucesso. A sessão volta num cookie que este código não consegue ler.
+ */
+export function Login({ destino = "/admin/conversas" }: { destino?: string }) {
+  const idUsuario = useId();
+  const idSenha = useId();
+
+  const [usuario, setUsuario] = useState("");
+  const [senha, setSenha] = useState("");
+  const [enviando, setEnviando] = useState(false);
+  const [recusa, setRecusa] = useState<string | null>(null);
+
+  async function enviar(e: React.FormEvent) {
+    e.preventDefault();
+    if (enviando) return;
+    setEnviando(true);
+    setRecusa(null);
+    try {
+      await api.entrar(usuario, senha);
+      // A senha some da memória do componente no instante em que deixa de ser
+      // necessária. Não impede um dump de heap, mas encurta a janela — e a linha
+      // custa nada.
+      setSenha("");
+      await reconsultarAutenticacao();
+      history.pushState(null, "", destino);
+      // O `App` escuta `popstate` para navegação de volta; um `pushState` não o
+      // dispara sozinho, então o evento é emitido aqui.
+      window.dispatchEvent(new PopStateEvent("popstate"));
+    } catch (erro: unknown) {
+      setSenha("");
+      setRecusa(
+        erro instanceof ErroApi && erro.status !== null
+          ? erro.message
+          : "Não consegui falar com o backend. Confira se o serviço está no ar.",
+      );
+    } finally {
+      setEnviando(false);
+    }
+  }
+
+  return (
+    <div className="capa">
+      <div className="capa__folha login">
+        <p className="capa__formulario">seguro auto · proposta</p>
+        <h1 className="capa__marca">AutoSeguro</h1>
+
+        {/* A linha por onde a 1ª via foi destacada. Decorativa para o leitor de
+            tela — o que ela comunica já está dito em texto logo abaixo. */}
+        <div className="login__picote" aria-hidden="true" />
+
+        <p className="capa__ordinal login__ordinal">2ª via · registro</p>
+        <h2 className="login__titulo">Requisição de acesso ao arquivo</h2>
+        <p className="capa__linha">
+          Esta instalação pede credencial para a área de operação. Ela é a{" "}
+          <code>ADMIN_USER</code> e a <code>ADMIN_PASSWORD</code> definidas no ambiente
+          de quem subiu o serviço.
+        </p>
+
+        <form className="login__form" onSubmit={enviar} noValidate>
+          <span className="campo">
+            <label className="rotulo" htmlFor={idUsuario}>
+              Usuário
+            </label>
+            <input
+              id={idUsuario}
+              name="usuario"
+              value={usuario}
+              autoComplete="username"
+              autoCapitalize="none"
+              autoCorrect="off"
+              spellCheck={false}
+              autoFocus
+              required
+              onChange={(e) => setUsuario(e.target.value)}
+            />
+          </span>
+
+          <span className="campo">
+            <label className="rotulo" htmlFor={idSenha}>
+              Senha
+            </label>
+            <input
+              id={idSenha}
+              name="senha"
+              type="password"
+              value={senha}
+              autoComplete="current-password"
+              required
+              onChange={(e) => setSenha(e.target.value)}
+            />
+          </span>
+
+          <button type="submit" className="botao login__entrar" disabled={enviando}>
+            {enviando ? "Conferindo…" : "Entrar"}
+          </button>
+        </form>
+
+        {/* `role="alert"` e não um texto qualquer: quem usa leitor de tela precisa
+            saber que a tentativa falhou sem ter de sair procurando. */}
+        {recusa !== null ? (
+          <p className="erro login__recusa" role="alert">
+            {recusa}
+          </p>
+        ) : null}
+
+        <p className="capa__rodape">
+          Não há cadastro nem recuperação de senha: a credencial vive no ambiente do
+          serviço. Sem <code>ADMIN_USER</code> e <code>ADMIN_PASSWORD</code> definidas,
+          esta tela não existe e a operação abre direto.{" "}
+          <a href="/chat">Voltar para a 1ª via</a>.
+        </p>
+      </div>
+    </div>
+  );
+}


=== DIFF: tests/dados/test_replay_resiliencia.py ===
@@ -0,0 +1,411 @@
+"""Rate limit, HTTP 402 e o laço do executor — testados sem banco e sem modelo.
+
+**Um replay que morre na conversa 18 e não diz que morreu é pior que um replay que não
+roda.** Este arquivo é o que torna essa frase verificável: ele monta um agente falso que
+levanta as exceções reais dos provedores, roda o laço do executor com um relógio que não
+dorme, e confere que o relatório sai — com o número de conversas completadas, o número
+de falhadas e o motivo de cada uma.
+
+O caminho exercitado é o de verdade em tudo que importa para a resiliência: a costura de
+`captura.py`, a detecção por delta no coletor (necessária porque `turno.responder`
+captura `Exception` de forma ampla e a falha nunca chega ao executor como exceção), a
+política de retentativa por classe e a parada no 402.
+"""
+
+from __future__ import annotations
+
+import asyncio
+
+import pytest
+
+from qa.replay import executor as exec_mod
+from qa.replay.assercoes import Desfecho
+from qa.replay.captura import Coletor, capturando, instrumentar
+from qa.replay.casos import CasoReplay, Fala, Gabarito
+from tests.fixtures.pii import cep_de
+from qa.dataset.elegibilidade import Elegibilidade
+from qa.replay.falhas import Backoff, ClasseDeFalha, classificar, de_excecao
+from qa.replay import amostra as amostragem
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# Classificação
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+class ErroDeProvedor(Exception):
+    """Imita o formato dos SDKs: `status_code` como atributo."""
+
+    def __init__(self, mensagem: str, status_code: int | None = None):
+        super().__init__(mensagem)
+        self.status_code = status_code
+
+
+@pytest.mark.parametrize(
+    "erro,esperado",
+    [
+        (ErroDeProvedor("nope", 402), ClasseDeFalha.PAGAMENTO),
+        (ErroDeProvedor("nope", 429), ClasseDeFalha.RATE_LIMIT),
+        (ErroDeProvedor("nope", 503), ClasseDeFalha.INDISPONIVEL),
+        (ErroDeProvedor("nope", 400), ClasseDeFalha.OUTRA),
+    ],
+)
+def test_classifica_pelo_status_quando_ele_existe(erro, esperado):
+    assert classificar(erro) is esperado
+
+
+@pytest.mark.parametrize(
+    "mensagem,esperado",
+    [
+        # A forma exata que o free tier do Ollama Cloud devolve em três dos quatro
+        # modelos — e o motivo de o 402 existir como classe própria.
+        ("402 Payment Required", ClasseDeFalha.PAGAMENTO),
+        ("insufficient credit for this model", ClasseDeFalha.PAGAMENTO),
+        ("429 Too Many Requests", ClasseDeFalha.RATE_LIMIT),
+        ("rate limit exceeded, retry later", ClasseDeFalha.RATE_LIMIT),
+        ("upstream 503 service unavailable", ClasseDeFalha.INDISPONIVEL),
+        ("Read timed out", ClasseDeFalha.INDISPONIVEL),
+        ("something else entirely", ClasseDeFalha.OUTRA),
+    ],
+)
+def test_classifica_pelo_texto_quando_nao_ha_status(mensagem, esperado):
+    """O erro atravessa o SDK do provedor e o wrapper do Agno, e cada um embrulha de um
+    jeito. Casar por tipo exigiria importar exceções de três bibliotecas e manter-se em
+    dia com as três."""
+    assert classificar(RuntimeError(mensagem)) is esperado
+
+
+def test_classifica_atraves_da_cadeia_de_causas():
+    """O Agno embrulha a exceção do SDK: o "402" fica um nível abaixo."""
+    try:
+        try:
+            raise ErroDeProvedor("Payment Required", 402)
+        except ErroDeProvedor as origem:
+            raise RuntimeError("model run failed") from origem
+    except RuntimeError as e:
+        assert classificar(e) is ClasseDeFalha.PAGAMENTO
+
+
+def test_so_o_402_e_fatal():
+    """429 melhora com espera; 402 não. Insistir num 402 só produz mais 402."""
+    assert de_excecao(ErroDeProvedor("x", 402)).fatal
+    assert not de_excecao(ErroDeProvedor("x", 429)).fatal
+    assert not de_excecao(ErroDeProvedor("x", 503)).fatal
+
+
+def test_mensagem_da_falha_e_truncada():
+    """Sem traceback e sem corpo de resposta inteiro: os dois podem ecoar o prompt."""
+    falha = de_excecao(RuntimeError("x" * 5000), limite=120)
+    assert len(falha.mensagem) == 120
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# Backoff
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+def test_backoff_cresce_e_respeita_o_teto():
+    dormidas: list[float] = []
+    b = Backoff(base_s=2.0, teto_s=10.0, seed=1, dormir=dormidas.append)
+    for tentativa in range(1, 8):
+        b.esperar(tentativa)
+    assert dormidas[0] < dormidas[2]
+    assert max(dormidas) <= 10.0
+    assert b.esperado_s == pytest.approx(sum(dormidas))
+
+
+def test_backoff_e_reproduzivel():
+    """Um jitter não reprodutível tornaria dois relatórios incomparáveis por um motivo
+    que não tem nada a ver com o agente."""
+    a = Backoff(seed=7, dormir=lambda _: None)
+    b = Backoff(seed=7, dormir=lambda _: None)
+    assert [a.espera(i) for i in range(1, 5)] == [b.espera(i) for i in range(1, 5)]
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# A costura de captura
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+class RunFalso:
+    """O mínimo que `ReliabilityEval` e o coletor leem de um `RunOutput`."""
+
+    def __init__(self, tools=()):
+        self.content = "ok"
+        self.messages = [
+            type("Msg", (), {"tool_calls": [
+                {"function": {"name": nome, "arguments": args}} for nome, args in tools
+            ]})()
+        ]
+
+
+class AgenteFalso:
+    """Roteiro por turno: uma exceção ou um `RunFalso`."""
+
+    def __init__(self, roteiro):
+        self.roteiro = list(roteiro)
+        self.chamadas = 0
+
+    def run(self, texto, **kwargs):
+        self.chamadas += 1
+        passo = self.roteiro.pop(0) if self.roteiro else RunFalso()
+        if isinstance(passo, BaseException):
+            raise passo
+        return passo
+
+
+def test_a_captura_registra_o_run_e_relanca_a_excecao():
+    """Relançar importa: engolir a exceção aqui faria a falha chegar ao relatório como
+    "conversa normal que respondeu estranho"."""
+    coletor = Coletor()
+    agente = instrumentar(AgenteFalso([RunFalso(), ErroDeProvedor("x", 402)]), coletor)
+    agente.run("oi")
+    with pytest.raises(ErroDeProvedor):
+        agente.run("de novo")
+    assert len(coletor.runs) == 1
+    assert coletor.falhas[-1].classe is ClasseDeFalha.PAGAMENTO
+
+
+def test_a_captura_le_nomes_e_argumentos_das_tools():
+    coletor = Coletor()
+    agente = instrumentar(
+        AgenteFalso([RunFalso(tools=[
+            ("qualify_lead", '{"idade": 35}'),
+            ("quote_plan", '{"plano_id": "completo", "idade": 35, "veiculo_ano": 2018}'),
+        ])]),
+        coletor,
+    )
+    agente.run("oi")
+    assert coletor.chamadas_de_tool() == ["qualify_lead", "quote_plan"]
+    assert coletor.argumentos_de("quote_plan")[0]["veiculo_ano"] == 2018
+
+
+def test_argumento_ilegivel_nao_derruba_o_coletor():
+    """O modelo às vezes emite JSON quebrado. Estourar aqui perderia a conversa inteira
+    por causa de uma vírgula."""
+    coletor = Coletor()
+    agente = instrumentar(AgenteFalso([RunFalso(tools=[("quote_plan", "{isso nao e json")])]), coletor)
+    agente.run("oi")
+    assert coletor.argumentos_de("quote_plan") == [{}]
+
+
+def test_a_costura_e_desfeita_mesmo_quando_o_corpo_levanta():
+    """Deixar a costura instalada depois de uma falha faria o próximo teste da mesma
+    sessão medir o coletor errado — o tipo de defeito que só aparece na ordem de
+    execução."""
+    from app.agent import turno
+
+    original = turno.construir_agente
+    with pytest.raises(ValueError):
+        with capturando(Coletor()):
+            raise ValueError("boom")
+    assert turno.construir_agente is original
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# O laço do executor
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+def _caso(cid="c1", falas=3, cotavel=True):
+    from app.contracts.quote import MotivoRecusa
+
+    return CasoReplay(
+        conversation_id=cid,
+        outcome="ganho",
+        falas=tuple(Fala(i, "text", f"fala {i}") for i in range(falas)),
+        gabarito=Gabarito(idade=35, veiculo_ano=2018, cep=cep_de("01", com_hifen=False)),
+        elegibilidade=Elegibilidade(
+            cotavel=cotavel, por_idade=not cotavel, por_veiculo=False,
+            motivo=None if cotavel else MotivoRecusa.IDADE_ACIMA,
+            ano_veiculo=2018, idade_veiculo=8,
+        ),
+    )
+
+
+class SessaoFalsa:
+    """O executor só precisa que a sessão exista e feche. Quem lê o banco é `observar`,
+    que os testes deste bloco substituem."""
+
+    def commit(self): ...
+    def close(self): ...
+    def expire_all(self): ...
+
+
+def _montar_executor(monkeypatch, roteiro, *, observacao=None, **kwargs):
+    """Um executor cujo `responder` imita o de produção no que importa aqui.
+
+    Ele constrói o agente pelo módulo `turno` — que é o que `capturando` embrulha — e
+    **captura a exceção**, como o `responder` real faz. É exatamente essa captura que
+    obriga o executor a detectar a falha por delta no coletor.
+    """
+    from app.agent import turno
+
+    agente = AgenteFalso(roteiro)
+    monkeypatch.setattr(turno, "construir_agente", lambda ctx: agente)
+
+    async def responder_falso(cid, texto, adaptador, chegada_do_lead=None):
+        construido = turno.construir_agente(None)
+        try:
+            construido.run(texto)
+        except Exception:  # noqa: BLE001 - é o que o `responder` de produção faz
+            pass
+        await adaptador.send(cid, "e qual plano você prefere?", message_id="m")
+
+    monkeypatch.setattr(
+        exec_mod, "observar",
+        lambda sessao, cid: observacao or exec_mod.Observacao(desfecho=Desfecho.OK),
+    )
+    import app.persistence.repo as repo
+
+    monkeypatch.setattr(
+        repo, "criar_conversa",
+        lambda s, **kw: type("C", (), {"id": "conv_x", "state": "cotado"})(),
+    )
+    monkeypatch.setattr(repo, "obter_conversa", lambda s, cid: None)
+
+    executor = exec_mod.Executor(
+        modo=exec_mod.Modo.DESFECHO,
+        sessao_factory=SessaoFalsa,
+        responder=responder_falso,
+        backoff=Backoff(seed=1, dormir=lambda _: None),
+        modelo="falso:teste",
+        **kwargs,
+    )
+    return executor, agente
+
+
+def _rodar(executor, casos):
+    estrat = amostragem._fechar(casos)
+    return asyncio.run(executor.executar(estrat))
+
+
+def test_rate_limit_e_retentado_e_a_execucao_continua(monkeypatch):
+    """429 é transitório por definição. Abortar por causa dele desperdiçaria as horas já
+    gastas numa execução longa e não interativa."""
+    roteiro = [ErroDeProvedor("429 rate limit", 429), RunFalso()]
+    executor, agente = _montar_executor(monkeypatch, roteiro)
+    rel = _rodar(executor, [_caso("c1", falas=1)])
+
+    # Uma chamada que falhou, a retentativa, e os dois turnos do respondedor — o
+    # `responder_falso` sempre pergunta o plano.
+    assert agente.chamadas == 2 + exec_mod.MAX_INJECOES_POR_FALA
+    assert rel.completadas == 1
+    assert rel.falhadas == 0
+    assert rel.segundos_de_espera > 0
+
+
+def test_rate_limit_persistente_marca_a_conversa_e_segue_para_a_proxima(monkeypatch):
+    executor, _ = _montar_executor(
+        monkeypatch, [ErroDeProvedor("429", 429)] * 40
+    )
+    rel = _rodar(executor, [_caso("c1", falas=1), _caso("c2", falas=1)])
+
+    assert rel.falhadas == 2
+    assert rel.completadas == 0
+    assert rel.falhas_por_classe == {"rate_limit": 2}
+    assert rel.interrompido_por is None  # não é fatal: a execução foi até o fim
+    assert rel.taxa_de_acerto is None
+
+
+def test_402_para_a_execucao_e_o_relatorio_diz_onde_parou(monkeypatch):
+    """A propriedade central do módulo: 17 conversas com o motivo, e não um traceback."""
+    executor, agente = _montar_executor(monkeypatch, [ErroDeProvedor("402", 402)] * 10)
+    rel = _rodar(executor, [_caso(f"c{i}", falas=1) for i in range(5)])
+
+    assert len(rel.resultados) == 1        # parou na primeira
+    assert rel.nao_alcancadas == 4         # e diz quantas não tentou
+    assert rel.falhas_por_classe == {"pagamento_402": 1}
+    assert "402" in (rel.interrompido_por or "")
+    assert agente.chamadas == 1            # não retentou: 402 não melhora com espera
+    assert not rel.aprovado
+
+
+def test_402_com_continuar_tenta_todas(monkeypatch):
+    """A flag existe, e o default é o contrário — insistir num 402 só produz mais 402."""
+    executor, _ = _montar_executor(
+        monkeypatch, [ErroDeProvedor("402", 402)] * 10, parar_no_402=False
+    )
+    rel = _rodar(executor, [_caso(f"c{i}", falas=1) for i in range(3)])
+    assert len(rel.resultados) == 3
+    assert rel.interrompido_por is None
+
+
+def test_o_relatorio_existe_mesmo_quando_a_execucao_morre_no_meio(monkeypatch):
+    executor, _ = _montar_executor(monkeypatch, [ErroDeProvedor("402", 402)])
+    rel = _rodar(executor, [_caso("c1", falas=2), _caso("c2", falas=2)])
+    assert rel.terminado_em is not None
+    assert rel.modo == "desfecho" and rel.modelo == "falso:teste"
+    assert rel.conversas_pedidas == 2
+
+
+def test_desfecho_esperado_sai_da_tabela_do_contrato(monkeypatch):
+    """Lead incotável: **`quote_plan` obrigatório**, desfecho `refused`,
+    `escalate_to_human` proibido. É a asserção que estava invertida na spec original."""
+    executor, _ = _montar_executor(
+        monkeypatch, [RunFalso(tools=[("quote_plan", "{}")])] * 5,
+        observacao=exec_mod.Observacao(
+            desfecho=Desfecho.REFUSED, motivo="idade_acima_do_limite"
+        ),
+    )
+    rel = _rodar(executor, [_caso("c1", falas=1, cotavel=False)])
+    linha = rel.resultados[0]
+
+    assert linha.desfecho_esperado == "refused"
+    assert linha.tools_faltando == []
+    assert linha.tools_proibidas_chamadas == []
+    assert linha.passou
+
+
+def test_escalate_num_lead_incotavel_reprova(monkeypatch):
+    """Recusa não cria handoff (DECISOES-FECHADAS §2)."""
+    executor, _ = _montar_executor(
+        monkeypatch,
+        [RunFalso(tools=[("quote_plan", "{}"), ("escalate_to_human", "{}")])] * 5,
+        observacao=exec_mod.Observacao(
+            desfecho=Desfecho.REFUSED, motivo="idade_acima_do_limite"
+        ),
+    )
+    rel = _rodar(executor, [_caso("c1", falas=1, cotavel=False)])
+    assert rel.resultados[0].tools_proibidas_chamadas == ["escalate_to_human"]
+    assert not rel.resultados[0].passou
+
+
+def test_quote_indisponivel_nao_e_veredito_sobre_o_agente(monkeypatch):
+    """A `/quote` falha em ~20% das chamadas. Encaminhar aí é o comportamento correto, e
+    contá-lo como erro faria a taxa de acerto oscilar com `FAILURE_RATE`."""
+    executor, _ = _montar_executor(
+        monkeypatch, [RunFalso(tools=[("quote_plan", "{}")])] * 5,
+        observacao=exec_mod.Observacao(
+            desfecho=Desfecho.ENCAMINHADO, trigger_handoff="cotacao_indisponivel"
+        ),
+    )
+    rel = _rodar(executor, [_caso("c1", falas=1)])
+    assert rel.completadas == 0
+    assert rel.falhas_por_classe == {"indisponivel": 1}
+
+
+def test_o_respondedor_e_consultado_no_modo_desfecho(monkeypatch):
+    """O `responder_falso` sempre pergunta o plano; o script tem que responder, e o
+    turno extra tem que aparecer na contagem."""
+    executor, agente = _montar_executor(monkeypatch, [RunFalso()] * 20)
+    rel = _rodar(executor, [_caso("c1", falas=1)])
+    assert rel.resultados[0].perguntas_do_agente >= 1
+    assert agente.chamadas > 1  # a fala do dataset mais a resposta roteirizada
+
+
+def test_o_respondedor_fica_desligado_no_modo_extracao(monkeypatch):
+    """`data_inicio` e `plano_id` não têm gabarito e não são medidos: injetar respostas
+    para eles gastaria inferência sem mudar a medição."""
+    executor, agente = _montar_executor(monkeypatch, [RunFalso()] * 20)
+    executor.modo = exec_mod.Modo.EXTRACAO
+    _rodar(executor, [_caso("c1", falas=3)])
+    assert agente.chamadas == 3  # exatamente as três falas do dataset
+
+
+def test_o_laco_nao_injeta_alem_do_limite(monkeypatch):
+    """Se o agente continuar perguntando depois de plano e data respondidos, insistir
+    vira laço — e o laço apareceria no relatório como custo, não como defeito."""
+    executor, agente = _montar_executor(monkeypatch, [RunFalso()] * 50)
+    _rodar(executor, [_caso("c1", falas=1)])
+    assert agente.chamadas <= 1 + exec_mod.MAX_INJECOES_POR_FALA


=== DIFF: tests/dados/test_replay_assercoes.py ===
@@ -0,0 +1,321 @@
+"""A tabela de asserções — incluindo a linha que estava invertida.
+
+A spec original dizia *"lead incotável chamou `escalate_to_human` e não chamou
+`quote_plan`"*. As duas metades estão erradas, e cada uma tem um teste aqui:
+
+- **recusa não cria handoff** (DECISOES-FECHADAS §2), então `escalate_to_human` num lead
+  incotável é o defeito;
+- **o agente não tem como saber que o lead é incotável** — o catálogo no system prompt
+  tem nomes e coberturas e nenhuma regra —, então `quote_plan` é obrigatório: quem
+  decide elegibilidade é a `/quote`, do mesmo jeito que quem decide preço.
+"""
+
+from __future__ import annotations
+
+import json
+
+import pytest
+
+from app.contracts.conversa import HandoffTrigger
+from app.contracts.quote import MotivoRecusa
+from qa.dataset.elegibilidade import Elegibilidade
+from qa.replay import assercoes
+from qa.replay.assercoes import Desfecho, ESCALATE, QUALIFY, QUOTE
+from qa.replay.casos import CasoReplay, Fala, Gabarito
+from tests.fixtures.pii import cep_de
+
+
+def _caso(*, cotavel=True, motivo=None, textos=("oi, quero cotar",), midia=False):
+    return CasoReplay(
+        conversation_id="c1",
+        outcome="ganho",
+        falas=tuple(
+            Fala(i, "audio" if (midia and i == 0) else "text", t)
+            for i, t in enumerate(textos)
+        ),
+        gabarito=Gabarito(idade=35, veiculo_ano=2018, cep=cep_de("01", com_hifen=False)),
+        elegibilidade=Elegibilidade(
+            cotavel=cotavel,
+            por_idade=motivo is MotivoRecusa.IDADE_ACIMA,
+            por_veiculo=motivo is MotivoRecusa.VEICULO_ANTIGO,
+            motivo=motivo, ano_veiculo=2018, idade_veiculo=8,
+        ),
+        _midias=1 if midia else 0,
+    )
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# A tabela
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+def test_lead_incotavel_deve_chamar_quote_plan():
+    """A metade invertida nº 1. **`quote_plan` é obrigatório** no lead incotável.
+
+    Não perguntamos ao modelo se o lead é elegível, do mesmo jeito que não perguntamos o
+    preço: o catálogo no system prompt não tem regra nenhuma, e quem decide é a `/quote`.
+    """
+    e = assercoes.esperado_para(_caso(cotavel=False, motivo=MotivoRecusa.IDADE_ACIMA))
+    assert e.tools_obrigatorias == (QUOTE,)
+    assert e.desfecho is Desfecho.REFUSED
+    assert e.motivo_recusa == "idade_acima_do_limite"
+
+
+def test_lead_incotavel_nao_deve_chamar_escalate():
+    """A metade invertida nº 2. Recusa **não** cria handoff (§2)."""
+    e = assercoes.esperado_para(_caso(cotavel=False, motivo=MotivoRecusa.VEICULO_ANTIGO))
+    assert e.tools_proibidas == (ESCALATE,)
+
+
+def test_lead_cotavel_deve_cotar_com_idade_e_ano_corretos():
+    e = assercoes.esperado_para(_caso())
+    assert e.desfecho is Desfecho.OK
+    assert e.tools_obrigatorias == (QUOTE,)
+    assert e.tools_proibidas == (ESCALATE,)
+    assert e.argumentos_de_quote == {
+        "idade": 35, "veiculo_ano": 2018, "cep": cep_de("01", com_hifen=False)
+    }
+
+
+def test_o_cep_fica_fora_do_casamento_exato_de_argumentos():
+    """O casamento do Agno é igualdade exata, e o argumento é o que o **modelo
+    escreveu** — na forma `01XXX-XXX`, com hífen, como o lead falou —, enquanto o
+    gabarito é normalizado
+    para 8 dígitos corridos. Exigir igualdade ali reprovaria uma extração correta por
+    causa de um hífen.
+
+    O CEP continua conferido nos dois lugares onde já está normalizado: `conversations.cep`
+    na extração e `quotes.req_cep` na conferência de preço.
+    """
+    caso = _caso()
+    eval_ = assercoes.montar_reliability(caso, assercoes.esperado_para(caso), [_Run()])
+    assert set(eval_.expected_tool_call_arguments[QUOTE]) == {"idade", "veiculo_ano"}
+
+
+def test_argumento_sem_gabarito_nao_e_exigido():
+    """Exigir um argumento que o dataset não tem reprovaria o agente pelo corpus."""
+    caso = _caso()
+    caso = CasoReplay(
+        conversation_id=caso.conversation_id, outcome=caso.outcome, falas=caso.falas,
+        gabarito=Gabarito(idade=None, veiculo_ano=2018, cep=None),
+        elegibilidade=caso.elegibilidade,
+    )
+    assert assercoes.esperado_para(caso).argumentos_de_quote == {"veiculo_ano": 2018}
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# A terceira linha: handoff legítimo vindo da fala do lead
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+@pytest.mark.parametrize(
+    "texto,trigger",
+    [
+        ("quero falar com um atendente", HandoffTrigger.LEAD_PEDIU),
+        ("bati o carro ontem, e agora?", HandoffTrigger.ASSUNTO_SENSIVEL),
+        ("vou entrar com processo no Procon", HandoffTrigger.ASSUNTO_SENSIVEL),
+    ],
+)
+def test_fala_do_lead_que_pede_handoff_muda_a_expectativa(texto, trigger):
+    """Parte do corpus traz gatilho legítimo na fala do lead. Cobrar `quote_plan` ali
+    mediria o agente contra o oposto do que a política manda."""
+    e = assercoes.esperado_para(_caso(textos=("oi", texto)))
+    assert e.desfecho is Desfecho.ENCAMINHADO
+    assert e.gatilho_esperado is trigger
+    assert e.tools_obrigatorias == ()
+    assert e.tools_proibidas == ()
+
+
+def test_o_classificador_de_gatilho_e_o_de_producao():
+    """Um segundo classificador divergiria do primeiro, e o replay passaria a reprovar o
+    agente por concordar com a própria política."""
+    import inspect
+
+    fonte = inspect.getsource(assercoes.gatilho_no_corpus)
+    assert "from app.handoff import gatilhos" in fonte
+    assert "gatilhos.casa(" in fonte
+
+
+def test_handoff_legitimo_vence_a_incotabilidade():
+    """Precedência: um lead incotável que pede um atendente é encaminhado, não recusado."""
+    caso = _caso(
+        cotavel=False, motivo=MotivoRecusa.IDADE_ACIMA,
+        textos=("oi", "prefiro falar com uma pessoa"),
+    )
+    assert assercoes.esperado_para(caso).desfecho is Desfecho.ENCAMINHADO
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# Conferência de tools
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+def test_conferir_tools_separa_faltando_de_proibida():
+    e = assercoes.esperado_para(_caso(cotavel=False, motivo=MotivoRecusa.IDADE_ACIMA))
+    assert assercoes.conferir_tools(e, [QUALIFY, QUOTE]) == ((), ())
+    assert assercoes.conferir_tools(e, [QUALIFY]) == ((QUOTE,), ())
+    assert assercoes.conferir_tools(e, [QUOTE, ESCALATE]) == ((), (ESCALATE,))
+
+
+def test_qualify_lead_e_permitido_e_nao_obrigatorio():
+    """É legítimo e não obrigatório. Reprovar por chamá-lo — que é o que
+    `allow_additional_tool_calls=False` faria — mediria a coisa errada."""
+    e = assercoes.esperado_para(_caso())
+    assert QUALIFY not in e.tools_obrigatorias
+    assert QUALIFY not in e.tools_proibidas
+
+
+def test_os_nomes_das_tools_sao_os_congelados_em_app_agent_tools():
+    """As assinaturas são contrato: mudá-las quebraria a avaliação sem quebrar nenhum
+    teste do agente. Este é o teste que faz quebrar."""
+    import app.agent.tools as tools
+
+    assert callable(tools.make_qualify_lead) and QUALIFY == "qualify_lead"
+    assert callable(tools.make_quote_plan) and QUOTE == "quote_plan"
+    assert callable(tools.make_escalate_to_human) and ESCALATE == "escalate_to_human"
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# A ponte com o ReliabilityEval do Agno
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+class _Msg:
+    def __init__(self, tool_calls):
+        self.tool_calls = tool_calls
+        self.from_history = False
+
+
+class _Run:
+    """Um `RunOutput` mínimo com as duas evidências que o `ReliabilityEval` lê.
+
+    `tools` (as execuções) é a que decide desde a 2.8.0; `messages` (os pedidos) fica
+    para anotar a chamada que nunca virou execução.
+    """
+
+    def __init__(self, *chamadas, com_erro=()):
+        from agno.models.response import ToolExecution
+
+        self.tools = [
+            ToolExecution(tool_name=n, tool_args=json.loads(a),
+                          tool_call_error=(n in com_erro) or None)
+            for n, a in chamadas
+        ]
+        self.messages = [
+            _Msg([{"function": {"name": n, "arguments": a}} for n, a in chamadas])
+        ]
+
+
+def test_agregar_junta_os_turnos_da_conversa():
+    """`ReliabilityEval` avalia **um** `RunOutput`, e a nossa unidade é a conversa: o
+    `quote_plan` acontece no turno 9 de 11, e avaliar turno a turno reprovaria os
+    outros dez por não terem cotado."""
+    agregado = assercoes.agregar([_Run(("qualify_lead", "{}")), _Run(("quote_plan", "{}"))])
+    assert len(agregado.messages) == 2
+
+
+def test_reliability_passa_quando_a_cotacao_aconteceu_com_os_argumentos_certos():
+    caso = _caso(cotavel=False, motivo=MotivoRecusa.IDADE_ACIMA)
+    e = assercoes.esperado_para(caso)
+    runs = [
+        _Run(("qualify_lead", '{"idade": 35}')),
+        _Run(("quote_plan", '{"plano_id": "completo", "idade": 35, "veiculo_ano": 2018}')),
+    ]
+    resultado = assercoes.montar_reliability(caso, e, runs).run(print_results=False)
+    assert resultado.eval_status == "PASSED"
+
+
+def test_reliability_reprova_quando_o_ano_do_veiculo_diverge_do_gabarito():
+    caso = _caso()
+    e = assercoes.esperado_para(caso)
+    runs = [_Run(("quote_plan", '{"plano_id": "completo", "idade": 35, "veiculo_ano": 2008}'))]
+    resultado = assercoes.montar_reliability(caso, e, runs).run(print_results=False)
+    assert resultado.eval_status == "FAILED"
+    assert "quote_plan" in resultado.failed_argument_checks
+
+
+def test_reliability_reprova_quando_nao_cotou():
+    caso = _caso(cotavel=False, motivo=MotivoRecusa.IDADE_ACIMA)
+    e = assercoes.esperado_para(caso)
+    resultado = assercoes.montar_reliability(caso, e, [_Run(("qualify_lead", "{}"))]).run(
+        print_results=False
+    )
+    assert resultado.eval_status == "FAILED"
+    assert "quote_plan" in resultado.missing_tool_calls
+
+
+def test_reliability_nao_e_montado_sem_tool_obrigatoria():
+    """Um eval sem expectativa produz um `PASSED` que não significa nada."""
+    caso = _caso(textos=("quero falar com um atendente",))
+    e = assercoes.esperado_para(caso)
+    assert assercoes.montar_reliability(caso, e, [_Run()]) is None
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# Mídia sem transcrição
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+@pytest.mark.parametrize(
+    "fala",
+    [
+        "não consigo ouvir áudio por aqui, me conta por escrito?",
+        "pode digitar o que tem no documento?",
+        "não abro imagem aqui, manda por texto",
+    ],
+)
+def test_pedir_por_texto_cumpre_a_politica_de_midia(fala):
+    assert assercoes.tratou_midia([fala], encaminhou=False)
+
+
+def test_encaminhar_tambem_cumpre():
+    assert assercoes.tratou_midia(["qualquer coisa"], encaminhou=True)
+
+
+def test_inventar_o_conteudo_nao_cumpre():
+    assert not assercoes.tratou_midia(
+        ["Entendi, seu Corolla 2018 está registrado."], encaminhou=False
+    )
+
+
+def test_conversa_com_midia_exige_pedido_de_texto():
+    assert assercoes.esperado_para(_caso(midia=True)).exige_pedido_de_texto
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# O juiz de modelo, e o seu limite
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+def test_o_juiz_so_avalia_tom_e_clareza_da_recusa():
+    """Preço é cálculo e tem gabarito fechado; elegibilidade tem gabarito em
+    `plans.json`. Perguntar qualquer um dos dois a um juiz trocaria uma conta exata por
+    uma opinião cara (CLAUDE.md 27)."""
+    criterio = assercoes.CRITERIO_RECUSA.lower()
+    assert "preço" not in criterio and "valor" not in criterio
+    assert "não promete exceção" in criterio
+    assert "trocar o condutor principal" in criterio
+
+
+def test_o_juiz_e_a_classe_certa_do_agno():
+    """A classe é `AgentAsJudgeEval`, não `AgentAsJudge` — o erro está avisado no
+    `docs/DECISOES-FECHADAS.md` §6."""
+    from agno.eval.agent_as_judge import AgentAsJudgeEval
+
+    juiz = assercoes.montar_juiz_da_recusa()
+    assert isinstance(juiz, AgentAsJudgeEval)
+    assert juiz.scoring_strategy == "numeric" and juiz.threshold == 8
+
+
+def test_execucao_que_errou_nao_satisfaz_a_expectativa():
+    """`quote_plan` que estourou dentro da tool não cotou.
+
+    Contá-la faria a asserção "o lead incotável foi recusado pela API" passar sem a API
+    ter sido consultada — que é exatamente o buraco que a 2.8.0 do Agno fechou ao trocar
+    a evidência do pedido pela execução.
+    """
+    caso = _caso(cotavel=False, motivo=MotivoRecusa.IDADE_ACIMA)
+    e = assercoes.esperado_para(caso)
+    runs = [_Run(("quote_plan", "{}"), com_erro=("quote_plan",))]
+    resultado = assercoes.montar_reliability(caso, e, runs).run(print_results=False)
+    assert resultado.eval_status == "FAILED"


=== DIFF: tests/dados/test_replay_relatorio.py ===
@@ -0,0 +1,266 @@
+"""O relatório: o parser, as contagens derivadas e a garantia de que nada cru sai.
+
+A propriedade que este arquivo protege é a mais simples de enunciar e a mais fácil de
+perder numa refatoração: **um numerador sem denominador é a forma mais educada de
+mentir.** Um replay que morre na conversa 18 e reporta "17 conversas, 100% de acerto"
+passa por bem-sucedido.
+"""
+
+from __future__ import annotations
+
+import json
+
+from app.privacy.mascarar import contem_pii
+from qa.replay.assercoes import Desfecho
+from qa.replay.falhas import ClasseDeFalha, Falha
+from qa.replay.relatorio import (
+    ExtracaoConferida,
+    Relatorio,
+    ResultadoConversa,
+    de_json,
+    estimativa_de_parede,
+    falha_para_dict,
+    render,
+)
+from tests.fixtures.pii import frase_do_lead
+
+
+def _ok(cid="c1", **kwargs):
+    base = dict(
+        conversation_id=cid, estrato="cotavel", outcome_dataset="ganho",
+        desfecho_esperado=str(Desfecho.OK), desfecho_obtido=str(Desfecho.OK),
+        preco_alcancavel=True, preco_exato=True, perguntas_do_agente=4,
+    )
+    base.update(kwargs)
+    return ResultadoConversa(**base)
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# Veredito por conversa
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+def test_conversa_que_bate_o_contrato_passa():
+    assert _ok().passou
+
+
+def test_tool_obrigatoria_faltando_reprova():
+    """Lead incotável que não chamou `quote_plan` não foi recusado pela API — foi
+    recusado pelo modelo, que é o defeito (DECISOES-FECHADAS §9)."""
+    assert not _ok(tools_faltando=["quote_plan"]).passou
+
+
+def test_escalate_em_conversa_de_recusa_reprova():
+    """Recusa **não** cria handoff (§2). Chamar `escalate_to_human` num lead incotável é
+    o defeito, não o acerto — é a asserção que estava invertida na spec original."""
+    assert not _ok(tools_proibidas_chamadas=["escalate_to_human"]).passou
+
+
+def test_recusa_pelo_motivo_errado_reprova():
+    """Nas 60 conversas recusadas pelos dois motivos, a API reporta a idade por
+    precedência do serviço. Um replay que só conferisse "recusou" passaria com o motivo
+    errado."""
+    linha = _ok(
+        desfecho_esperado=str(Desfecho.REFUSED), desfecho_obtido=str(Desfecho.REFUSED),
+        motivo_esperado="idade_acima_do_limite",
+        motivo_obtido="veiculo_acima_de_20_anos",
+    )
+    assert not linha.passou
+
+
+def test_preco_fora_do_conjunto_reprova():
+    assert not _ok(preco_exato=False).passou
+
+
+def test_midia_nao_tratada_reprova():
+    assert not _ok(tem_midia=True, midia_tratada=False).passou
+
+
+def test_falha_de_provedor_nao_conta_como_conversa_completa():
+    """402 é uma conta sem crédito, não um agente ruim. Somá-los produziria uma taxa de
+    acerto que cai quando o cartão vence."""
+    linha = _ok(falha=falha_para_dict(Falha(ClasseDeFalha.PAGAMENTO, "402")))
+    assert not linha.completou and not linha.passou
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# Contagens do relatório
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+def _relatorio(**kwargs) -> Relatorio:
+    base = dict(modo="desfecho", modelo="ollama:qwen2.5:7b", seed=1, conversas_pedidas=30)
+    base.update(kwargs)
+    return Relatorio(**base)
+
+
+def test_conversas_nao_alcancadas_sao_contadas_separadas_das_falhadas():
+    """São coisas diferentes: uma falhou porque foi tentada, a outra nunca foi tentada.
+    Somá-las esconderia onde a execução parou."""
+    rel = _relatorio(
+        resultados=[_ok("c1"), _ok("c2", falha=falha_para_dict(Falha(ClasseDeFalha.PAGAMENTO, "402")))],
+        interrompido_por="HTTP 402",
+    )
+    assert rel.completadas == 1
+    assert rel.falhadas == 1
+    assert rel.nao_alcancadas == 28
+    assert not rel.aprovado
+
+
+def test_taxa_de_acerto_e_sobre_as_completadas():
+    rel = _relatorio(
+        conversas_pedidas=3,
+        resultados=[
+            _ok("c1"),
+            _ok("c2", tools_faltando=["quote_plan"]),
+            _ok("c3", falha=falha_para_dict(Falha(ClasseDeFalha.RATE_LIMIT, "429"))),
+        ],
+    )
+    assert rel.completadas == 2
+    assert rel.aprovados == 1
+    assert rel.taxa_de_acerto == 0.5
+
+
+def test_taxa_e_none_quando_nada_completou():
+    """Zero acertos em zero conversas é indefinido. Imprimir "0%" convidaria a ler uma
+    execução que não rodou como uma execução que falhou tudo."""
+    rel = _relatorio(conversas_pedidas=1, resultados=[
+        _ok("c1", falha=falha_para_dict(Falha(ClasseDeFalha.PAGAMENTO, "402")))
+    ])
+    assert rel.taxa_de_acerto is None
+    assert "n/a" in render(rel)
+
+
+def test_falhas_sao_agrupadas_por_classe():
+    rel = _relatorio(resultados=[
+        _ok("c1", falha=falha_para_dict(Falha(ClasseDeFalha.PAGAMENTO, "402"))),
+        _ok("c2", falha=falha_para_dict(Falha(ClasseDeFalha.RATE_LIMIT, "429"))),
+        _ok("c3", falha=falha_para_dict(Falha(ClasseDeFalha.RATE_LIMIT, "429 de novo"))),
+    ])
+    assert rel.falhas_por_classe == {"pagamento_402": 1, "rate_limit": 2}
+
+
+def test_extracao_por_campo_ignora_campo_sem_gabarito():
+    """Campo sem gabarito não conta como erro do agente — contar rebaixaria a taxa por
+    culpa do corpus."""
+    rel = _relatorio(conversas_pedidas=2, resultados=[
+        _ok("c1", extracao=ExtracaoConferida(
+            esperado_idade=35, obtido_idade=35,
+            esperado_veiculo_ano=2018, obtido_veiculo_ano=2018, cep_correto=True)),
+        _ok("c2", extracao=ExtracaoConferida(
+            esperado_idade=None, obtido_idade=None,
+            esperado_veiculo_ano=2010, obtido_veiculo_ano=2001, cep_correto=None)),
+    ])
+    por_campo = rel.extracao_por_campo
+    assert por_campo["idade"] == {"comparaveis": 1, "acertos": 1}
+    assert por_campo["veiculo_ano"] == {"comparaveis": 2, "acertos": 1}
+    assert por_campo["cep"] == {"comparaveis": 1, "acertos": 1}
+
+
+def test_o_relatorio_mede_exatamente_tres_campos():
+    """Idade, `veiculo_ano` e CEP. Marca e modelo ficam fora por decisão registrada."""
+    rel = _relatorio(resultados=[_ok("c1")])
+    assert set(rel.extracao_por_campo) == {"idade", "veiculo_ano", "cep"}
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# O contador do respondedor reprovando a suíte
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+def test_incompreensao_acima_do_limiar_reprova_a_suite():
+    """E a mensagem tem que dizer que o motivo é o harness, não o agente."""
+    rel = _relatorio(conversas_pedidas=2, resultados=[
+        _ok("c1", perguntas_do_agente=10, nao_entendi=4),
+        _ok("c2", perguntas_do_agente=10, nao_entendi=0),
+    ])
+    assert rel.taxa_nao_entendi == 0.2 + 0.0  # 4 em 20
+    assert rel.respondedor_reprovou is False  # exatamente no limiar ainda passa
+
+    rel.resultados[1] = _ok("c2", perguntas_do_agente=10, nao_entendi=1)
+    assert rel.respondedor_reprovou is True
+    assert not rel.aprovado
+    assert "REPROVA: o harness" in render(rel)
+
+
+def test_sem_perguntas_a_taxa_e_zero_e_nao_divide_por_zero():
+    rel = _relatorio(resultados=[_ok("c1", perguntas_do_agente=0)])
+    assert rel.taxa_nao_entendi == 0.0
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# Serialização, parser e PII
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+def test_round_trip_preserva_as_linhas():
+    """A comparação entre duas execuções — antes e depois de uma mudança de prompt — é o
+    uso principal do artefato, e ela precisa que ele seja lido de volta."""
+    rel = _relatorio(conversas_pedidas=2, resultados=[
+        _ok("c1", extracao=ExtracaoConferida(esperado_idade=35, obtido_idade=35)),
+        _ok("c2", falha=falha_para_dict(Falha(ClasseDeFalha.RATE_LIMIT, "429"))),
+    ])
+    lido = de_json(json.dumps(rel.para_dict(), ensure_ascii=False))
+    assert [r.conversation_id for r in lido.resultados] == ["c1", "c2"]
+    assert lido.resultados[0].extracao.esperado_idade == 35
+    assert lido.resultados[1].falha["classe"] == "rate_limit"
+    assert lido.completadas == rel.completadas
+    assert lido.taxa_de_acerto == rel.taxa_de_acerto
+
+
+def test_o_resumo_e_derivado_e_nao_e_lido_de_volta():
+    """Reconstruí-lo das linhas impede um relatório editado à mão de afirmar 100% com
+    12 linhas vermelhas embaixo."""
+    rel = _relatorio(conversas_pedidas=1, resultados=[_ok("c1", tools_faltando=["quote_plan"])])
+    dados = rel.para_dict()
+    dados["resumo"]["taxa_de_acerto"] = 1.0
+    dados["resumo"]["aprovado"] = True
+    lido = de_json(json.dumps(dados))
+    assert lido.taxa_de_acerto == 0.0
+    assert not lido.aprovado
+
+
+def test_mensagem_de_erro_do_provedor_e_mascarada():
+    """O corpo de erro pode ecoar o prompt, e o prompt carrega a fala do lead.
+
+    A defesa não depende de o diretório de saída ser ignorado pelo Git: depende do
+    mascaramento.
+    """
+    fala, _ = frase_do_lead(seed=5)
+    assert contem_pii(fala)
+    linha = falha_para_dict(
+        Falha(ClasseDeFalha.OUTRA, f"400 Bad Request: prompt was {fala}")
+    )
+    assert not contem_pii(linha["mensagem"])
+
+
+def test_o_cep_nunca_aparece_no_relatorio_nem_certo_nem_errado():
+    """O CEP entra como **acerto ou erro**, nunca como valor: o relatório é um artefato
+    que alguém vai colar num README."""
+    campos = set(ExtracaoConferida.__dataclass_fields__)
+    assert "cep_correto" in campos
+    assert not any(c.endswith("_cep") or c == "cep" for c in campos)
+
+
+def test_relatorio_serializado_nao_contem_pii():
+    rel = _relatorio(resultados=[_ok("c1")])
+    assert not contem_pii(json.dumps(rel.para_dict(), ensure_ascii=False))
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# A estimativa de parede
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+def test_estimativa_reproduz_a_tabela_de_custo_de_relogio():
+    """DECISOES-FECHADAS §9: 203 inferências ≈ 10 min, 16.470 ≈ 14 h."""
+    assert estimativa_de_parede(203) == "~10 min"
+    assert estimativa_de_parede(991) == "~50 min"
+    assert estimativa_de_parede(16470) == "~13.7 h"
+
+
+def test_render_sempre_diz_o_denominador():
+    rel = _relatorio(conversas_pedidas=30, resultados=[_ok("c1")])
+    texto = render(rel)
+    assert "1/30 completadas" in texto
+    assert "não alcançadas" in texto


=== DIFF: tests/dados/test_replay_respondedor.py ===
@@ -0,0 +1,206 @@
+"""O respondedor roteirizado e o contador que torna a fragilidade visível.
+
+O contador é o teste mais importante do arquivo. Um casador de intenção por regex que
+para de casar não produz erro: produz uma suíte que passa medindo nada, e uma queda de
+desfechos que alguém debugaria no prompt por dois dias. O contador é o que transforma
+esse silêncio em vermelho — e é por isso que ele tem teste próprio, não só o casamento.
+"""
+
+from __future__ import annotations
+
+import pytest
+
+from qa.replay.respondedor import Intencao, RespondedorRoteirizado, classificar
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# Casamento por intenção
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+@pytest.mark.parametrize(
+    "fala,esperado",
+    [
+        ("Qual plano você prefere: essencial, completo ou premium?", Intencao.PLANO_ID),
+        ("me diga qual dos três te atende melhor", Intencao.PLANO_ID),
+        ("A partir de quando você quer que a cobertura comece?", Intencao.DATA_INICIO),
+        ("qual a data de início da vigência?", Intencao.DATA_INICIO),
+        ("Quantos anos você tem?", Intencao.IDADE),
+        ("qual o ano do carro?", Intencao.VEICULO_ANO),
+        ("me informe o CEP onde o carro dorme", Intencao.CEP),
+    ],
+)
+def test_classifica_as_cinco_intencoes(fala, esperado):
+    assert classificar(fala) is esperado
+
+
+@pytest.mark.parametrize(
+    "fala",
+    [
+        "",
+        "   ",
+        "Perfeito, já anotei aqui.",
+        "Obrigado pelas informações, vou calcular.",
+    ],
+)
+def test_fala_que_nao_pergunta_nada_nao_conta(fala):
+    """Nem responde, nem soma no contador. É o caso mais comum e o mais fácil de errar:
+    sem a guarda de "isto é uma pergunta?", metade das falas do agente viraria
+    incompreensão."""
+    assert classificar(fala) is Intencao.NENHUMA
+
+
+def test_bloco_de_cotacao_nao_e_lido_como_pergunta_de_plano():
+    """O bloco cita plano, franquia e carência. Sem a guarda, o respondedor responderia
+    a uma pergunta que ninguém fez — e injetaria um turno a mais por cotação."""
+    bloco = (
+        "Plano Completo: R$ 494,58 por mês. Franquia de R$ 3.000. "
+        "Roubo e furto têm carência de 30 dias a partir do início da vigência."
+    )
+    assert classificar(bloco) is Intencao.NENHUMA
+
+
+def test_pergunta_fora_dos_cinco_campos_e_desconhecida():
+    assert classificar("Você já teve algum sinistro nos últimos 5 anos?") is (
+        Intencao.DESCONHECIDA
+    )
+
+
+def test_plano_vence_data_quando_a_pergunta_junta_os_dois():
+    """Um lead real também responderia uma coisa de cada vez; a outra volta no turno
+    seguinte."""
+    fala = "Qual plano você quer e quando a cobertura deve começar?"
+    assert classificar(fala) is Intencao.PLANO_ID
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# As duas respostas
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+def test_responde_plano_com_um_dos_tres_do_catalogo():
+    r = RespondedorRoteirizado(conversation_id="conv-a")
+    resposta = r.responder("Qual plano você prefere?")
+    assert resposta is not None
+    assert r.plano_escolhido in {"essencial", "completo", "premium"}
+    assert r.plano_escolhido in resposta
+
+
+def test_responde_data_em_texto_livre_e_nunca_no_dia_1():
+    """Duas razões, e as duas estão no docstring de `data_escolhida`: ISO testaria o
+    caminho fácil de `normalizar_data`, e **dia 1 faz o `primeiro_pagamento_pro_rata`
+    sumir da resposta** (API-COTACAO §6.2) — o replay deixaria de exercitar o pro-rata."""
+    r = RespondedorRoteirizado(conversation_id="conv-a")
+    resposta = r.responder("Quando a cobertura deve começar?")
+    assert resposta is not None
+    assert "dia " in resposta and not resposta.startswith("20")
+    dia = int(r.data_escolhida.split()[1])
+    assert dia != 1
+
+
+def test_a_data_roteirizada_e_lida_pela_normalizacao_de_producao():
+    """Se `normalizar_data` não lê a nossa frase, o replay injeta um campo que a
+    qualificação rejeita — e mediria o nosso script, não o agente."""
+    import datetime as dt
+
+    from app.agent.tools import normalizar_data
+
+    r = RespondedorRoteirizado(conversation_id="conv-a")
+    data = normalizar_data(r.data_escolhida, hoje=dt.date(2026, 9, 4))
+    assert data > dt.date(2026, 9, 4)
+    assert data.day != 1
+
+
+def test_idade_ano_e_cep_sao_reconhecidos_e_nao_respondidos():
+    """Quem os responde são as falas do dataset. Reconhecê-los sem responder é o que
+    impede o contador de subir por perguntas que o corpus já cobre — senão ele mediria o
+    dataset, não o script."""
+    r = RespondedorRoteirizado(conversation_id="conv-a")
+    for fala in ("Quantos anos você tem?", "Qual o ano do carro?", "Qual o CEP?"):
+        assert r.responder(fala) is None
+    assert r.nao_entendi == 0
+    assert r.perguntas == 3
+
+
+def test_o_script_cobre_dois_buracos_e_so_dois():
+    """"Script cobrindo dois buracos conhecidos, não a conversa inteira" — a garantia
+    fica em teste para que ampliar o script seja uma decisão, não um deslize."""
+    r = RespondedorRoteirizado(conversation_id="conv-a")
+    r.responder("Qual plano?")
+    r.responder("Quando começa?")
+    assert set(r.respondeu) == {"plano_id", "data_inicio"}
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# O contador
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+def test_contador_sobe_so_para_pergunta_desconhecida():
+    r = RespondedorRoteirizado(conversation_id="conv-a")
+    r.responder("Qual plano você prefere?")
+    r.responder("Perfeito, anotado.")
+    r.responder("Você tem carta de bônus de outra seguradora?")
+    r.responder("Prefere pagar no cartão ou no boleto?")
+    assert r.nao_entendi == 2
+    assert len(r.nao_entendidas) == 2
+
+
+def test_perguntas_e_o_denominador_da_taxa():
+    """"não entendi" sozinho não diz nada: 3 em 4 é ruim, 3 em 200 é ruído."""
+    r = RespondedorRoteirizado(conversation_id="conv-a")
+    r.responder("Perfeito, anotado.")            # não é pergunta
+    r.responder("Qual plano?")                    # pergunta reconhecida
+    r.responder("Tem carta de bônus?")            # pergunta desconhecida
+    assert r.perguntas == 2
+    assert r.nao_entendi == 1
+
+
+def test_pedidos_repetidos_ficam_visiveis():
+    """O agente pedindo o mesmo campo cinco vezes é sinal de que a nossa resposta não
+    está sendo lida — e isso tem que aparecer no relatório, não sumir na média."""
+    r = RespondedorRoteirizado(conversation_id="conv-a")
+    for _ in range(5):
+        r.responder("Qual plano você prefere?")
+    assert r.pedidos["plano_id"] == 5
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# Determinismo
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+def test_mesma_conversa_recebe_sempre_o_mesmo_plano_e_a_mesma_data():
+    a = RespondedorRoteirizado(conversation_id="conv-xyz")
+    b = RespondedorRoteirizado(conversation_id="conv-xyz")
+    assert (a.plano_escolhido, a.data_escolhida) == (b.plano_escolhido, b.data_escolhida)
+
+
+def test_conversas_diferentes_exercitam_os_tres_planos():
+    """Fixar um único plano exercitaria um terço da tabela de preço."""
+    planos = {
+        RespondedorRoteirizado(conversation_id=f"conv-{i}").plano_escolhido
+        for i in range(50)
+    }
+    assert planos == {"essencial", "completo", "premium"}
+
+
+def test_a_semente_nao_depende_de_pythonhashseed():
+    """`hash()` de `str` é aleatorizado por processo: usá-lo faria a mesma conversa
+    receber planos diferentes em execuções diferentes, e a comparação entre duas
+    execuções do replay deixaria de valer."""
+    import subprocess
+    import sys
+
+    codigo = (
+        "from qa.replay.respondedor import _semente; print(_semente('conv-estavel'))"
+    )
+    saidas = {
+        subprocess.run(
+            [sys.executable, "-c", codigo], capture_output=True, text=True,
+            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin", "PYTHONPATH": "."},
+            check=True,
+        ).stdout.strip()
+        for seed in ("0", "1", "12345")
+    }
+    assert len(saidas) == 1


=== DIFF: quote-service/app/quote_logic.py ===
@@ -0,0 +1,101 @@
+"""Logica de cotacao. Le plans.json e aplica as regras (faixa etaria, idade do
+veiculo, regiao, carencia, pro-rata de entrada no meio do mes)."""
+from __future__ import annotations
+import json, datetime as dt
+from pathlib import Path
+from calendar import monthrange
+
+_PLANS_PATH = Path(__file__).resolve().parent.parent / "data" / "plans.json"
+
+
+def load_plans() -> dict:
+    return json.loads(_PLANS_PATH.read_text(encoding="utf-8"))
+
+
+class CotacaoRecusada(Exception):
+    def __init__(self, motivo: str):
+        self.motivo = motivo
+        super().__init__(motivo)
+
+
+def _faixa_etaria_mult(regras: dict, idade: int) -> float:
+    for f in regras["faixa_etaria"]:
+        if f["idade_min"] <= idade <= f["idade_max"]:
+            if f.get("recusar"):
+                raise CotacaoRecusada(f["motivo"])
+            return f["multiplicador"]
+    raise CotacaoRecusada("Idade fora das faixas aceitas.")
+
+
+def _idade_veiculo_mult(regras: dict, ano_veiculo: int, hoje: dt.date) -> float:
+    anos = hoje.year - ano_veiculo
+    for f in regras["idade_veiculo"]:
+        if f["anos_min"] <= anos <= f["anos_max"]:
+            if f.get("recusar"):
+                raise CotacaoRecusada(f["motivo"])
+            return f["multiplicador"]
+    raise CotacaoRecusada("Idade do veiculo fora das faixas aceitas.")
+
+
+def _regiao_mult(regras: dict, cep: str | None) -> float:
+    if not cep:
+        return 1.0
+    pref = cep.replace("-", "").strip()[:2]
+    r = regras["regiao_cep"]
+    return r["multiplicador"] if pref in r["prefixos_alto_risco"] else 1.0
+
+
+def _pro_rata_primeiro_mes(base_mensal: float, inicio: dt.date) -> dict:
+    """Primeiro mes proporcional aos dias restantes (inclui o dia de inicio)."""
+    dias_mes = monthrange(inicio.year, inicio.month)[1]
+    dias_restantes = dias_mes - inicio.day + 1
+    valor = round(base_mensal * dias_restantes / dias_mes, 2)
+    return {"dias_no_mes": dias_mes, "dias_cobrados": dias_restantes, "valor_primeiro_pagamento": valor}
+
+
+def cotar(payload: dict) -> dict:
+    """Recebe dados do lead/veiculo e devolve a cotacao calculada.
+    Campos esperados: plano_id, idade (int), veiculo_ano (int),
+    cep (str, opcional), data_inicio (YYYY-MM-DD, opcional)."""
+    plans = load_plans()
+    regras = plans["regras"]
+    hoje = dt.date.today()
+
+    plano_id = (payload.get("plano_id") or "essencial").lower()
+    plano = next((p for p in plans["planos"] if p["id"] == plano_id), None)
+    if plano is None:
+        raise CotacaoRecusada(f"Plano '{plano_id}' inexistente. Opcoes: "
+                              + ", ".join(p["id"] for p in plans["planos"]))
+
+    idade = int(payload["idade"])
+    ano = int(payload["veiculo_ano"])
+    cep = payload.get("cep")
+
+    m_idade = _faixa_etaria_mult(regras, idade)
+    m_veic = _idade_veiculo_mult(regras, ano, hoje)
+    m_regiao = _regiao_mult(regras, cep)
+
+    premio = round(plano["base_mensal"] * m_idade * m_veic * m_regiao, 2)
+
+    car = regras["carencia"]
+    resp = {
+        "plano_id": plano["id"],
+        "plano_nome": plano["nome"],
+        "premio_mensal": premio,
+        "franquia": plano["franquia"],
+        "coberturas": plano["coberturas"],
+        "multiplicadores": {"faixa_etaria": m_idade, "idade_veiculo": m_veic, "regiao": m_regiao},
+        "carencia": {
+            "coberturas": [c for c in plano["coberturas"] if c in car["coberturas_com_carencia"]],
+            "dias": car["dias"],
+            "observacao": car["_obs"],
+        },
+        "moeda": plans["moeda"],
+    }
+
+    di = payload.get("data_inicio")
+    if di:
+        inicio = dt.date.fromisoformat(di)
+        if inicio.day != 1:
+            resp["primeiro_pagamento_pro_rata"] = _pro_rata_primeiro_mes(premio, inicio)
+    return resp


=== DIFF: web/src/ui/useAutenticacao.ts ===
@@ -0,0 +1,95 @@
+import { useCallback, useEffect, useState } from "react";
+import { api, type EstadoAuth } from "../api/cliente";
+
+/**
+ * O estado de autenticação, **compartilhado entre telas** e consultado uma vez.
+ *
+ * Por que um singleton de módulo e não um `useRecurso` por componente: três lugares
+ * precisam da mesma resposta ao mesmo tempo — a capa (para saber para onde aponta a
+ * 2ª via), o roteador (para decidir entre `/admin` e o login) e a própria tela de
+ * login (para saber se já entrou). Três `useRecurso` fariam três chamadas e, pior,
+ * poderiam discordar por uma fração de segundo: a capa oferecendo o admin enquanto o
+ * roteador já decidiu pedir senha.
+ *
+ * O estado **desconhecido** é o terceiro, e é o que evita o defeito mais feio desta
+ * tela: mostrar o login por um instante para quem não precisa dele. Enquanto a
+ * resposta não chega, ninguém decide nada.
+ */
+
+export type Autenticacao =
+  | { situacao: "desconhecido" }
+  | { situacao: "conhecido"; exigido: boolean; autenticado: boolean };
+
+/** Backend fora do ar não é "precisa de login": é indisponibilidade, e a tela de
+ * erro que já existe sabe dizer isso melhor do que um formulário de senha. */
+const OTIMISTA: Autenticacao = { situacao: "conhecido", exigido: false, autenticado: true };
+
+let cache: Autenticacao = { situacao: "desconhecido" };
+let emVoo: Promise<void> | null = null;
+const ouvintes = new Set<(a: Autenticacao) => void>();
+
+function publicar(novo: Autenticacao): void {
+  cache = novo;
+  for (const ouvinte of ouvintes) ouvinte(novo);
+}
+
+function consultar(): Promise<void> {
+  // Uma consulta por vez, mesmo com cinco componentes montando juntos.
+  emVoo ??= api
+    .estadoAutenticacao()
+    .then((e: EstadoAuth) =>
+      publicar({ situacao: "conhecido", exigido: e.exigido, autenticado: e.autenticado }),
+    )
+    .catch(() => {
+      // Qualquer falha — backend parado, 404 de uma instalação sem as rotas de
+      // login — cai no otimista. Nunca no pessimista: pedir senha porque a API não
+      // respondeu tranca quem tem acesso e não impede quem não tem, já que a porta
+      // de verdade é o `exigir_admin` do backend, não esta tela.
+      publicar(OTIMISTA);
+    })
+    .finally(() => {
+      emVoo = null;
+    });
+  return emVoo;
+}
+
+/** Força uma releitura — depois de entrar ou sair, o estado mudou no servidor. */
+export function reconsultarAutenticacao(): Promise<void> {
+  publicar({ situacao: "desconhecido" });
+  return consultar();
+}
+
+/** Só para os testes: devolve o módulo ao estado de quem acabou de abrir a aba. */
+export function _reiniciarAutenticacao(): void {
+  cache = { situacao: "desconhecido" };
+  emVoo = null;
+  ouvintes.clear();
+}
+
+export function useAutenticacao(): Autenticacao {
+  const [estado, setEstado] = useState<Autenticacao>(cache);
+
+  useEffect(() => {
+    ouvintes.add(setEstado);
+    setEstado(cache);
+    if (cache.situacao === "desconhecido") void consultar();
+    return () => {
+      ouvintes.delete(setEstado);
+    };
+  }, []);
+
+  return estado;
+}
+
+/** Encerra a sessão e devolve a decisão ao servidor. */
+export function useSair(): () => Promise<void> {
+  return useCallback(async () => {
+    try {
+      await api.sair();
+    } finally {
+      // Mesmo que o logout falhe, reconsultar é o certo: quem manda no estado é o
+      // cookie que o servidor enxerga, nunca o que esta aba acha que aconteceu.
+      await reconsultarAutenticacao();
+    }
+  }, []);
+}


=== DIFF: quote-service/app/main.py ===
@@ -0,0 +1,68 @@
+"""
+Servico de cotacao de seguro auto (mock) para o desafio FDE.
+
+POST /quote  -> calcula uma cotacao a partir dos dados do lead/veiculo.
+GET  /health -> health check (sempre estavel).
+GET  /planos -> tabela de planos e regras (consulta).
+
+Observacao de operacao: este servico simula um sistema legado real. Ele NEM SEMPRE
+responde de primeira -- parte das chamadas falha ou demora. Trate isso no seu agente.
+A taxa e a latencia sao configuraveis por variavel de ambiente:
+    QUOTE_FAILURE_RATE   (default 0.20)  -> fracao de chamadas que falham
+    QUOTE_SLOW_RATE      (default 0.10)  -> fracao de chamadas lentas
+    QUOTE_SLOW_SECONDS   (default 8)     -> duracao da chamada lenta (simula timeout)
+    QUOTE_SEED           (opcional)      -> fixa o gerador p/ falhas reproduziveis
+"""
+from __future__ import annotations
+import os, time, random
+from fastapi import FastAPI, Response
+from fastapi.responses import JSONResponse
+from pydantic import BaseModel, Field
+from .quote_logic import cotar, load_plans, CotacaoRecusada
+
+FAILURE_RATE = float(os.getenv("QUOTE_FAILURE_RATE", "0.20"))
+SLOW_RATE = float(os.getenv("QUOTE_SLOW_RATE", "0.10"))
+SLOW_SECONDS = float(os.getenv("QUOTE_SLOW_SECONDS", "8"))
+_seed = os.getenv("QUOTE_SEED")
+_rng = random.Random(int(_seed)) if _seed else random.Random()
+
+app = FastAPI(title="AutoSeguro Quote API (mock)", version="1.0.0")
+
+
+class QuoteRequest(BaseModel):
+    plano_id: str = Field("essencial", description="essencial | completo | premium")
+    idade: int = Field(..., ge=0, le=200)
+    veiculo_ano: int = Field(..., ge=1950, le=2100)
+    cep: str | None = None
+    data_inicio: str | None = Field(None, description="YYYY-MM-DD (opcional)")
+
+
+@app.get("/health")
+def health():
+    return {"status": "ok"}
+
+
+@app.get("/planos")
+def planos():
+    return load_plans()
+
+
+@app.post("/quote")
+def quote(req: QuoteRequest):
+    # --- instabilidade simulada (de proposito) ---
+    roll = _rng.random()
+    if roll < FAILURE_RATE:
+        kind = _rng.choice(["500", "502", "503"])
+        return JSONResponse(status_code=int(kind),
+                            content={"error": "upstream_unavailable",
+                                     "message": "Servico de cotacao temporariamente indisponivel. Tente novamente."})
+    if roll < FAILURE_RATE + SLOW_RATE:
+        time.sleep(SLOW_SECONDS)  # simula timeout / lentidao
+
+    # --- cotacao ---
+    try:
+        return cotar(req.model_dump())
+    except CotacaoRecusada as e:
+        return JSONResponse(status_code=422, content={"error": "cotacao_recusada", "motivo": e.motivo})
+    except (KeyError, ValueError, TypeError) as e:
+        return JSONResponse(status_code=400, content={"error": "payload_invalido", "detalhe": str(e)})


=== DIFF: quote-service/data/plans.json ===
@@ -0,0 +1,56 @@
+{
+  "_comment": "Tabela de planos e regras de cotacao de seguro auto. Leia com atencao: ha regras que so se aplicam em casos especificos.",
+  "moeda": "BRL",
+  "planos": [
+    {
+      "id": "essencial",
+      "nome": "Essencial",
+      "base_mensal": 119.90,
+      "franquia": 4500,
+      "coberturas": ["colisao", "roubo", "furto"]
+    },
+    {
+      "id": "completo",
+      "nome": "Completo",
+      "base_mensal": 209.90,
+      "franquia": 3000,
+      "coberturas": ["colisao", "roubo", "furto", "terceiros", "vidros"]
+    },
+    {
+      "id": "premium",
+      "nome": "Premium",
+      "base_mensal": 339.90,
+      "franquia": 1500,
+      "coberturas": ["colisao", "roubo", "furto", "terceiros", "vidros", "carro_reserva", "assistencia_24h"]
+    }
+  ],
+  "regras": {
+    "faixa_etaria": [
+      { "idade_min": 18, "idade_max": 24, "multiplicador": 1.60 },
+      { "idade_min": 25, "idade_max": 29, "multiplicador": 1.25 },
+      { "idade_min": 30, "idade_max": 59, "multiplicador": 1.00 },
+      { "idade_min": 60, "idade_max": 75, "multiplicador": 1.40 },
+      { "idade_min": 76, "idade_max": 200, "recusar": true, "motivo": "Idade acima do limite de aceitacao (75 anos)." }
+    ],
+    "idade_veiculo": [
+      { "anos_min": 0, "anos_max": 5, "multiplicador": 1.00 },
+      { "anos_min": 6, "anos_max": 10, "multiplicador": 1.15 },
+      { "anos_min": 11, "anos_max": 20, "multiplicador": 1.45 },
+      { "anos_min": 21, "anos_max": 200, "recusar": true, "motivo": "Veiculo com mais de 20 anos nao e aceito." }
+    ],
+    "regiao_cep": {
+      "_obs": "Prefixos de CEP (2 primeiros digitos) considerados de alto risco recebem agravo.",
+      "prefixos_alto_risco": ["07", "08", "21", "26", "59"],
+      "multiplicador": 1.30
+    },
+    "carencia": {
+      "_obs": "Coberturas de roubo e furto so passam a valer apos a carencia, contada da data de inicio da vigencia.",
+      "coberturas_com_carencia": ["roubo", "furto"],
+      "dias": 30
+    },
+    "entrada_meio_mes": {
+      "_obs": "Quando a vigencia comeca no meio do mes, o PRIMEIRO pagamento e proporcional (pro-rata) aos dias restantes do mes. Os meses seguintes sao integrais.",
+      "regra": "pro_rata_primeiro_mes"
+    }
+  }
+}


=== DIFF: web/src/App.tsx ===
@@ -2,6 +2,8 @@ import { useEffect, useState } from "react";
 import { Admin } from "./admin/Admin";
 import { PaginaChat } from "./chat/PaginaChat";
 import { Capa } from "./ui/Capa";
+import { Login } from "./ui/Login";
+import { useAutenticacao } from "./ui/useAutenticacao";
 
 /**
  * Roteador mínimo, de propósito.
@@ -46,8 +48,33 @@ function useRota(): string {
 
 export function App() {
   const rota = useRota();
+  const auth = useAutenticacao();
+
+  /*
+   * A GUARDA DA 2ª VIA, e a ordem das três condições é o conteúdo dela.
+   *
+   * 1. Enquanto o estado é `desconhecido`, ninguém decide. Renderizar o login "por
+   *    precaução" faria a instalação ABERTA — o caminho padrão, o do avaliador —
+   *    piscar um formulário de senha antes de mostrar o registro. Um flash desses
+   *    ensina que existe uma senha que não existe.
+   * 2. O login só aparece quando o backend disse `exigido` e `não autenticado`.
+   * 3. **Esta guarda é conveniência, nunca segurança.** Quem manda é o
+   *    `exigir_admin` do backend: sem sessão, cada chamada de `/api/*` volta 401 e
+   *    a tela não tem o que mostrar. Um bypass no cliente não daria acesso a dado
+   *    nenhum — por isso ela pode ser otimista quando a API não responde.
+   */
+  const barrado = auth.situacao === "conhecido" && auth.exigido && !auth.autenticado;
+
+  if (rota.startsWith("/entrar")) {
+    // Já entrou (ou a instalação é aberta): o balcão não tem por que existir.
+    return barrado ? <Login /> : <Admin rota="/admin/conversas" />;
+  }
+
+  if (rota.startsWith("/admin")) {
+    if (auth.situacao === "desconhecido") return <Aguardando />;
+    return barrado ? <Login destino={rota} /> : <Admin rota={rota} />;
+  }
 
-  if (rota.startsWith("/admin")) return <Admin rota={rota} />;
   if (rota.startsWith("/chat")) return <PaginaChat />;
 
   // A raiz DECIDE: apresenta as duas vias em vez de cair no chat por omissão.
@@ -55,3 +82,20 @@ export function App() {
   // aplicação pela primeira vez — que é exatamente o avaliador.
   return <Capa />;
 }
+
+/**
+ * O intervalo entre "a página montou" e "o backend disse se pede senha".
+ *
+ * Deliberadamente mudo: sem spinner, sem esqueleto, sem "carregando". A resposta
+ * chega em uma volta de rede local, e qualquer coisa animada nesse intervalo pisca —
+ * o que é mais barulhento que a espera. O texto existe só para o leitor de tela.
+ */
+function Aguardando() {
+  return (
+    <div className="capa">
+      <p className="so-leitor" role="status">
+        Conferindo se esta instalação exige credencial.
+      </p>
+    </div>
+  );
+}


=== DIFF: app/main.py ===
@@ -23,9 +23,11 @@ from __future__ import annotations
 import logging
 import os
 from contextlib import asynccontextmanager
+from pathlib import Path
 
 from fastapi import Depends, FastAPI, Response
-from fastapi.responses import JSONResponse
+from fastapi.responses import FileResponse, JSONResponse
+from fastapi.staticfiles import StaticFiles
 from sqlalchemy.orm import Session
 
 from app.api import consultas
@@ -209,6 +211,44 @@ registrar_websockets(app)
 registrar_autenticacao(app)
 
 
-@app.get("/", include_in_schema=False)
-def raiz() -> Response:
-    return Response(status_code=204)
+# ─── o frontend ──────────────────────────────────────────────────────────────
+#
+# Servido pela MESMA origem da API, e não por um segundo serviço. Três razões, e a
+# primeira é a que decide:
+#
+# 1. `docker compose up` precisa subir **o produto inteiro** com um comando. Um
+#    frontend em outra porta transformaria "abra 8080" em "abra 8080 e 5173", e o
+#    critério nº 1 do desafio é justamente que funcione;
+# 2. mesma origem significa **sem CORS** — nada de `allow_origins` para configurar
+#    errado, e o cookie de sessão do admin é `SameSite=Strict` sem exceção;
+# 3. o WebSocket usa o mesmo host, então não há um segundo endereço para acertar.
+#
+# As rotas do SPA (`/chat`, `/admin/...`) são resolvidas no cliente: qualquer caminho
+# que não seja `/api` nem um arquivo existente devolve o `index.html`, e o roteador
+# do React decide. Sem isso, um F5 em `/admin/status` daria 404 — que é o defeito
+# clássico de SPA servido por servidor estático ingênuo.
+
+_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
+
+if _DIST.is_dir():
+    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")
+
+    @app.get("/{caminho:path}", include_in_schema=False)
+    def spa(caminho: str) -> Response:
+        # `/api` NUNCA cai no SPA. Sem esta guarda, um endpoint inexistente
+        # devolveria `index.html` com 200 — e o cliente receberia HTML onde espera
+        # JSON, com o erro aparecendo como "unexpected token <" três camadas adiante.
+        # O mesmo vale para as rotas de documentação, que ficam desligadas fora de
+        # dev e não podem voltar a existir por acidente de roteamento.
+        if caminho.startswith("api/") or caminho in {"docs", "redoc", "openapi.json"}:
+            return JSONResponse(status_code=404,
+                                content={"error": "nao_encontrado", "message": caminho})
+        arquivo = _DIST / caminho
+        if caminho and arquivo.is_file() and _DIST in arquivo.resolve().parents:
+            return FileResponse(arquivo)
+        return FileResponse(_DIST / "index.html")
+
+else:  # pragma: no cover - só em desenvolvimento, com o Vite em outra porta
+    @app.get("/", include_in_schema=False)
+    def raiz() -> Response:
+        return Response(status_code=204)


=== DIFF: qa/replay/captura.py ===
@@ -46,36 +46,40 @@ class Coletor:
     def ultimo_run(self) -> Any | None:
         return self.runs[-1] if self.runs else None
 
-    def chamadas_de_tool(self, desde: int = 0) -> list[str]:
-        """Os nomes das tools chamadas, na ordem, a partir do `desde`-ésimo run.
-
-        Achatar aqui — em vez de deixar cada asserção reabrir o `RunOutput` — é o que
-        mantém a forma do objeto do Agno em **um** lugar. Quando ela mudar de versão,
-        muda aqui.
-        """
-        nomes: list[str] = []
-        for run in self.runs[desde:]:
-            for mensagem in getattr(run, "messages", None) or []:
-                for chamada in getattr(mensagem, "tool_calls", None) or []:
-                    nome = _nome_da_chamada(chamada)
-                    if nome:
-                        nomes.append(nome)
-        return nomes
-
-    def argumentos_de(self, tool: str, desde: int = 0) -> list[dict[str, Any]]:
-        """Os argumentos de cada chamada a `tool`, já decodificados.
-
-        O Agno entrega os argumentos como **string JSON** dentro de
-        `function.arguments`. Decodificar em cada asserção seria repetir o mesmo
-        `json.loads` com o mesmo `try` em cinco lugares.
+    def execucoes(self, desde: int = 0) -> list[tuple[str, dict[str, Any], bool]]:
+        """`(nome, argumentos, houve_erro)` de cada tool executada, na ordem.
+
+        **A evidência é a execução, não o pedido** — é o que o `ReliabilityEval` passou
+        a exigir na 2.8.0, e a mudança está certa: uma chamada recusada pelo limite de
+        tools, ou que estourou dentro da tool, aparecia como pedido no `messages` e
+        satisfazia a expectativa sem a tool ter feito trabalho nenhum. `RunOutput.tools`
+        é uma lista de `ToolExecution`, com os argumentos **já decodificados**.
+
+        O caminho por `messages` fica como plano B para versões que não populam `tools`.
+        Achatar tudo aqui — em vez de deixar cada asserção reabrir o `RunOutput` — é o
+        que mantém a forma do objeto do Agno em **um** lugar.
         """
         import json
 
-        saida: list[dict[str, Any]] = []
+        saida: list[tuple[str, dict[str, Any], bool]] = []
         for run in self.runs[desde:]:
+            execucoes = getattr(run, "tools", None)
+            if execucoes:
+                for execucao in execucoes:
+                    nome = getattr(execucao, "tool_name", None)
+                    if not nome:
+                        continue
+                    args = getattr(execucao, "tool_args", None) or {}
+                    erro = bool(getattr(execucao, "tool_call_error", False)) or bool(
+                        getattr(execucao, "is_paused", False)
+                    )
+                    saida.append((nome, dict(args), erro))
+                continue
+
             for mensagem in getattr(run, "messages", None) or []:
                 for chamada in getattr(mensagem, "tool_calls", None) or []:
-                    if _nome_da_chamada(chamada) != tool:
+                    nome = _nome_da_chamada(chamada)
+                    if not nome:
                         continue
                     brutos = _argumentos_da_chamada(chamada)
                     if isinstance(brutos, str):
@@ -83,9 +87,22 @@ class Coletor:
                             brutos = json.loads(brutos)
                         except (ValueError, TypeError):
                             brutos = {}
-                    saida.append(brutos if isinstance(brutos, dict) else {})
+                    saida.append((nome, brutos if isinstance(brutos, dict) else {}, False))
         return saida
 
+    def chamadas_de_tool(self, desde: int = 0) -> list[str]:
+        """Os nomes das tools que **executaram limpo**, na ordem.
+
+        Uma chamada que errou não conta como chamada: `quote_plan` que estourou não
+        cotou, e contá-la faria a asserção "o lead incotável foi recusado pela API"
+        passar sem a API ter sido consultada.
+        """
+        return [nome for nome, _, erro in self.execucoes(desde) if not erro]
+
+    def argumentos_de(self, tool: str, desde: int = 0) -> list[dict[str, Any]]:
+        """Os argumentos de cada execução limpa de `tool`."""
+        return [args for nome, args, erro in self.execucoes(desde) if nome == tool and not erro]
+
 
 def _nome_da_chamada(chamada: Any) -> str | None:
     if isinstance(chamada, dict):


=== DIFF: Dockerfile ===
@@ -0,0 +1,41 @@
+# A aplicação: backend FastAPI + agente Agno, servindo também o frontend construído.
+#
+# Duas etapas, e a primeira existe por um motivo de produto, não de tamanho de imagem:
+# o `docker compose up` precisa subir **o produto inteiro** com um comando. Um
+# frontend que exige `npm install` à parte transformaria "um comando" em três, e o
+# critério nº 1 do desafio é justamente que funcione.
+
+# ── etapa 1: o frontend ─────────────────────────────────────────────────────
+FROM node:22-slim AS web
+WORKDIR /web
+COPY web/package.json web/package-lock.json ./
+RUN npm ci --no-audit --no-fund
+COPY web/ ./
+# Os testes não entram na imagem: o build de produção é do produto, não da suíte.
+RUN npm run build
+
+# ── etapa 2: a aplicação ────────────────────────────────────────────────────
+FROM python:3.13-slim
+WORKDIR /srv
+
+RUN pip install --no-cache-dir uv
+
+COPY pyproject.toml uv.lock ./
+RUN uv sync --frozen --no-dev --no-install-project
+
+COPY app/ ./app/
+COPY config/ ./config/
+COPY db/ ./db/
+COPY qa/ ./qa/
+COPY --from=web /web/dist ./web/dist
+
+ENV PATH="/srv/.venv/bin:$PATH" \
+    APP_ENV=prod \
+    PYTHONUNBUFFERED=1
+
+EXPOSE 8080
+
+# `--host 0.0.0.0` DENTRO do contêiner é o correto: quem restringe a exposição é o
+# `docker-compose.yml`, publicando em 127.0.0.1. Ligar em loopback aqui tornaria o
+# serviço inalcançável até pela rede interna do compose.
+CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]


=== DIFF: qa/replay/assercoes.py ===
@@ -153,12 +153,22 @@ class RunAgregado:
 
     `ReliabilityEval` avalia **um** `RunOutput`, e a nossa unidade é a conversa: o
     `quote_plan` acontece no turno 9 de 11, e avaliar turno a turno reprovaria os
-    outros dez por não terem cotado. O módulo lê exatamente um atributo — `messages` —
-    então agregar é concatenar. Os três campos de telemetria existem porque
-    `_get_telemetry_data` os lê; `telemetry=False` já os dispensaria, e eles ficam para
-    o caso de alguém religar.
+    outros dez por não terem cotado. Agregar é concatenar os dois atributos que o
+    módulo lê:
+
+    - **`tools`** — a lista de `ToolExecution`. Desde a 2.8.0 é daqui que sai a
+      evidência: uma expectativa só é satisfeita por uma execução **limpa**, e não mais
+      por um pedido no `messages` que a tool recusou ou que estourou. É a leitura certa
+      para o nosso caso — "chamou `quote_plan`" tem que significar que a `/quote` foi
+      consultada, não que o modelo escreveu o nome da tool;
+    - **`messages`** — mantido porque o módulo ainda o usa para anotar a falha de uma
+      chamada que nunca virou execução.
+
+    Os três campos de telemetria existem porque `_get_telemetry_data` os lê;
+    `telemetry=False` já os dispensaria, e eles ficam para o caso de alguém religar.
     """
 
+    tools: list[Any] = field(default_factory=list)
     messages: list[Any] = field(default_factory=list)
     agent_id: str | None = None
     model: str | None = None
@@ -166,10 +176,12 @@ class RunAgregado:
 
 
 def agregar(runs: Iterable[Any]) -> RunAgregado:
+    execucoes: list[Any] = []
     mensagens: list[Any] = []
     for run in runs:
+        execucoes.extend(getattr(run, "tools", None) or [])
         mensagens.extend(getattr(run, "messages", None) or [])
-    return RunAgregado(messages=mensagens)
+    return RunAgregado(tools=execucoes, messages=mensagens)
 
 
 def montar_reliability(
@@ -188,21 +200,32 @@ def montar_reliability(
 
     Devolve `None` quando não há tool obrigatória (o caso do handoff legítimo): montar
     um eval sem expectativa produziria um `PASSED` que não significa nada.
+
+    **O CEP fica fora do `expected_tool_call_arguments`, e não por descuido.** O
+    casamento de argumentos do Agno é igualdade exata, e o argumento que chega à tool é
+    o que o **modelo escreveu** — na forma `01XXX-XXX`, com hífen, como o lead
+    falou —, enquanto o gabarito
+    é normalizado para 8 dígitos (é assim que `conversations.cep` guarda). Exigir
+    igualdade ali reprovaria uma extração correta por causa de um hífen. O CEP continua
+    conferido duas vezes, nos dois lugares onde já está normalizado: contra
+    `conversations.cep` na medição de extração, e contra `quotes.req_cep` na conferência
+    de preço — que é onde a subcotação de 30% de fato aparece.
     """
     if not expectativa.tools_obrigatorias:
         return None
     from agno.eval.reliability import ReliabilityEval
 
+    argumentos = {
+        chave: valor
+        for chave, valor in expectativa.argumentos_de_quote.items()
+        if chave != "cep"
+    }
     return ReliabilityEval(
         name=f"replay:{caso.conversation_id}",
         agent_response=agregar(runs),  # type: ignore[arg-type]
         expected_tool_calls=list(expectativa.tools_obrigatorias),
         allow_additional_tool_calls=True,
-        expected_tool_call_arguments=(
-            {QUOTE: expectativa.argumentos_de_quote}
-            if expectativa.argumentos_de_quote
-            else None
-        ),
+        expected_tool_call_arguments={QUOTE: argumentos} if argumentos else None,
         db=db,
         telemetry=False,
         print_results=print_results,


=== DIFF: tests/nucleo/test_contrato_openapi.py ===
@@ -160,3 +160,36 @@ def test_post_conversations_com_a_mesma_sessao_retoma(monkeypatch):
 
     assert a.status_code == b.status_code == 201
     assert a.json()["id"] == b.json()["id"]
+
+
+# ─── o SPA servido pela mesma origem ─────────────────────────────────────────
+
+
+def test_api_desconhecida_devolve_json_nao_html(monkeypatch, tmp_path):
+    """Sem esta guarda, o catch-all do SPA devolveria `index.html` com 200 para um
+    endpoint inexistente — e o cliente receberia HTML onde espera JSON, com o erro
+    aparecendo como "unexpected token <" três camadas adiante da causa."""
+    from fastapi.testclient import TestClient
+
+    from app.main import app
+
+    with TestClient(app) as c:
+        r = c.get("/api/rota-que-nao-existe")
+    assert r.status_code == 404
+    assert r.headers["content-type"].startswith("application/json")
+
+
+@pytest.mark.parametrize("rota", ["docs", "redoc", "openapi.json"])
+def test_documentacao_nao_volta_pelo_catch_all(rota):
+    """Elas ficam desligadas fora de dev; o roteamento do SPA não pode ressuscitá-las
+    por acidente, servindo o `index.html` com 200 no lugar delas."""
+    from fastapi.testclient import TestClient
+
+    from app.main import app
+
+    with TestClient(app) as c:
+        r = c.get(f"/{rota}")
+    # Em dev o FastAPI serve de verdade; fora de dev, 404 JSON — nunca HTML do SPA.
+    assert r.status_code == 200 or (
+        r.status_code == 404 and r.headers["content-type"].startswith("application/json")
+    )


=== DIFF: tests/dados/test_preco_contra_api.py ===
@@ -31,6 +31,8 @@ import pytest
 
 from qa.replay.precos import multiplicador_regiao, premio_esperado
 
+from tests.fixtures.pii import cep_de
+
 pytestmark = pytest.mark.live
 
 LIMPA = os.getenv("QUOTE_API_LIMPA", "http://localhost:8001")
@@ -57,6 +59,8 @@ def cotar(**payload) -> dict:
 
 # ─── os perfis de borda ──────────────────────────────────────────────────────
 
+
+
 #: `(rótulo, plano, idade, ano do veículo, cep)` — cada linha existe para exercitar
 #: uma borda específica, e o rótulo diz qual.
 PERFIS = [
@@ -79,18 +83,18 @@ PERFIS = [
     ("veículo 20 anos — teto de 1,45, borda da recusa", "completo", 35, ANO - 20, None),
 
     # CEP: os cinco prefixos de risco e vizinhos que NÃO são
-    ("cep 07 — risco",                      "completo",  35, 2019, "[CEP]"),
-    ("cep 08 sem hífen — risco",            "completo",  35, 2019, "[CEP]"),
-    ("cep 21 — risco",                      "completo",  35, 2019, "[CEP]"),
-    ("cep 26 — risco",                      "completo",  35, 2019, "[CEP]"),
-    ("cep 59 — risco",                      "completo",  35, 2019, "[CEP]"),
-    ("cep 01 — fora da lista",              "completo",  35, 2019, "[CEP]"),
-    ("cep 06 — vizinho do 07, fora",        "completo",  35, 2019, "[CEP]"),
-    ("cep 09 — vizinho do 08, fora",        "completo",  35, 2019, "[CEP]"),
-    ("cep 22 — vizinho do 21, fora",        "completo",  35, 2019, "[CEP]"),
+    ("cep 07 — risco",                      "completo",  35, 2019, cep_de("07")),
+    ("cep 08 sem hífen — risco",            "completo",  35, 2019, cep_de("08", com_hifen=False)),
+    ("cep 21 — risco",                      "completo",  35, 2019, cep_de("21")),
+    ("cep 26 — risco",                      "completo",  35, 2019, cep_de("26")),
+    ("cep 59 — risco",                      "completo",  35, 2019, cep_de("59")),
+    ("cep 01 — fora da lista",              "completo",  35, 2019, cep_de("01")),
+    ("cep 06 — vizinho do 07, fora",        "completo",  35, 2019, cep_de("06")),
+    ("cep 09 — vizinho do 08, fora",        "completo",  35, 2019, cep_de("09")),
+    ("cep 22 — vizinho do 21, fora",        "completo",  35, 2019, cep_de("22")),
 
     # o extremo: o maior prêmio possível das regras
-    ("teto absoluto: premium, 18a, 11 anos, risco", "premium", 18, ANO - 11, "[CEP]"),
+    ("teto absoluto: premium, 18a, 11 anos, risco", "premium", 18, ANO - 11, cep_de("07")),
     # e o piso
     ("piso absoluto: essencial, 30a, 0 ano, sem cep", "essencial", 30, ANO, None),
 ]
@@ -145,7 +149,7 @@ def test_o_calculo_independente_nao_e_a_api(monkeypatch):
     # O perfil do exemplo de `docs/API-COTACAO.md` §5.4 e do bloco de cotação:
     # 209,90 × 1,25 (28 anos) × 1,15 (7 anos) × 1,30 (prefixo 07) = 392,25.
     assert premio_esperado(
-        plano_id="completo", idade=28, veiculo_ano=2019, cep="[CEP]", ano_corrente=ANO
+        plano_id="completo", idade=28, veiculo_ano=2019, cep=cep_de("07"), ano_corrente=ANO
     ) == Decimal("392.25")
 
 
@@ -155,7 +159,7 @@ def test_o_calculo_independente_nao_e_a_api(monkeypatch):
 def test_os_multiplicadores_compoem_por_produto():
     """API-COTACAO §5: `base × faixa_etaria × idade_veiculo × regiao`, com **um único
     arredondamento no fim** — os multiplicadores não são arredondados entre si."""
-    corpo = cotar(plano_id="completo", idade=18, veiculo_ano=ANO - 11, cep="[CEP]")
+    corpo = cotar(plano_id="completo", idade=18, veiculo_ano=ANO - 11, cep=cep_de("07"))
     m = corpo["multiplicadores"]
     bruto = Decimal("209.90") * Decimal(str(m["faixa_etaria"])) \
         * Decimal(str(m["idade_veiculo"])) * Decimal(str(m["regiao"]))
@@ -163,9 +167,9 @@ def test_os_multiplicadores_compoem_por_produto():
 
 
 @pytest.mark.parametrize("cep,esperado", [
-    ("[CEP]", 1.30), ("[CEP]", 1.30), ("[CEP]", 1.30),
-    ("[CEP]", 1.30), ("[CEP]", 1.30),
-    ("[CEP]", 1.00), ("[CEP]", 1.00),
+    (cep_de("07"), 1.30), (cep_de("08"), 1.30), (cep_de("21"), 1.30),
+    (cep_de("26"), 1.30), (cep_de("59"), 1.30),
+    (cep_de("01"), 1.00), (cep_de("70"), 1.00),
 ])
 def test_a_regiao_e_130_nos_cinco_prefixos(cep, esperado):
     corpo = cotar(plano_id="essencial", idade=35, veiculo_ano=2022, cep=cep)
@@ -225,7 +229,7 @@ def test_todo_premio_observado_pertence_ao_conjunto_de_72():
         for p in ("essencial", "completo", "premium")
         for i in (20, 27, 40, 70)
         for v in (2, 8, 15)
-        for c in (None, "[CEP]")
+        for c in (None, cep_de("07"))
     }
     assert len(possiveis) == 72
 


=== DIFF: web/src/ui/Capa.tsx ===
@@ -1,3 +1,5 @@
+import { useAutenticacao } from "./useAutenticacao";
+
 /**
  * A rota `/`.
  *
@@ -11,8 +13,19 @@
  *
  * Ela não é uma landing page: sem herói, sem argumento de venda. Três linhas e
  * duas escolhas, porque o leitor aqui é um avaliador com pouco tempo.
+ *
+ * **A única coisa que a autenticação mudou aqui.** Quando a instalação define
+ * `ADMIN_USER`/`ADMIN_PASSWORD`, a 2ª via passa a levar ao balcão de credencial em
+ * vez de ao registro. O link é reescrito **antes** do clique, e não depois: deixar
+ * a capa apontar para `/admin` e o admin devolver 401 seco seria oferecer uma porta
+ * e bater com ela na cara de quem aceitou. O selo "exige credencial" avisa em uma
+ * linha, e some por completo na instalação aberta — que é o caminho padrão, e onde
+ * um aviso sobre senha só criaria a suspeita de que falta um passo.
  */
 export function Capa() {
+  const auth = useAutenticacao();
+  const pedeCredencial = auth.situacao === "conhecido" && auth.exigido && !auth.autenticado;
+
   return (
     <div className="capa">
       <div className="capa__folha">
@@ -32,7 +45,7 @@ export function Capa() {
             </span>
           </a>
 
-          <a className="capa__via" href="/admin/conversas">
+          <a className="capa__via" href={pedeCredencial ? "/entrar" : "/admin/conversas"}>
             <span className="capa__ordinal">2ª via</span>
             <span className="capa__nome">Registro</span>
             <span className="capa__quem">
@@ -40,6 +53,9 @@ export function Capa() {
               status, as tentativas de cotação, a saúde da integração e a fila de
               handoff.
             </span>
+            {pedeCredencial ? (
+              <span className="capa__selo">exige credencial de operação</span>
+            ) : null}
           </a>
         </div>
 


=== DIFF: docker-compose.yml ===
@@ -61,11 +61,25 @@ services:
       ANTHROPIC_API_KEY: "${ANTHROPIC_API_KEY}"
       # Opcional. Definido ⇒ exigido; ausente ⇒ a aplicação sobe e avisa no log.
       APP_ADMIN_TOKEN: "${ADMIN_TOKEN:-}"
+      # Login da área de operação, também opcional e também sem default. Sem as
+      # duas, o /admin abre direto — que é o caminho de um comando, e o que a
+      # proteção efetiva cobre é o bind em 127.0.0.1 acima.
+      ADMIN_USER: "${ADMIN_USER:-}"
+      ADMIN_PASSWORD: "[REDIGIDO]"
     depends_on:
       db:
         condition: service_healthy
       quote-api:
         condition: service_healthy
+    # Sem isto, `docker compose up --wait` retorna quando o contêiner está RODANDO,
+    # não quando está SERVINDO — e quem seguir o README recebe conexão recusada por
+    # alguns segundos, sem saber se é lentidão ou defeito.
+    healthcheck:
+      test: ["CMD-SHELL", "python -c \"import urllib.request;urllib.request.urlopen('http://localhost:8080/api/health')\""]
+      interval: 2s
+      timeout: 5s
+      retries: 30
+      start_period: 5s
 
   # ─── perfil `debug`: as portas de depuração, para quem optar ────────────────
   # `docker compose --profile debug up` publica banco e quote-api no host. Fora


=== DIFF: quote-service/pyproject.toml ===
@@ -0,0 +1,13 @@
+[project]
+name = "autoseguro-quote-api"
+version = "1.0.0"
+description = "Mock do servico de cotacao de seguro auto (desafio FDE Namastex)"
+requires-python = ">=3.10"
+dependencies = [
+    "fastapi>=0.110",
+    "uvicorn[standard]>=0.27",
+    "pydantic>=2.6",
+]
+
+[tool.uv]
+package = false


=== DIFF: web/src/admin/LayoutAdmin.tsx ===
@@ -3,6 +3,7 @@ import { api } from "../api/cliente";
 import type { FilaHandoffs } from "../api/tipos";
 import { useRecurso } from "../ui/useRecurso";
 import { Casca } from "../ui/Casca";
+import { useAutenticacao, useSair } from "../ui/useAutenticacao";
 import { useEventos } from "./useEventos";
 
 const ABAS = [
@@ -28,9 +29,16 @@ const ABAS = [
  *    `/chat` retoma a sessão do próprio navegador, então leva o avaliador de volta
  *    à conversa **dele**, nunca à de outro lead.
  * 3. **Zero não vira badge.** Um "0" ali é ruído, não informação.
+ *
+ * O **encerrar** entra na mesma zona de estado, e só existe quando há sessão para
+ * encerrar. Numa instalação aberta ele seria um botão que promete um controle
+ * inexistente — e, pior, sugeriria que houve um login que ninguém fez.
  */
 export function LayoutAdmin({ rota, children }: { rota: string; children?: ReactNode }) {
   const fila = useRecurso<FilaHandoffs>(() => api.handoffs({ limit: 1 }), []);
+  const auth = useAutenticacao();
+  const sair = useSair();
+  const comSessao = auth.situacao === "conhecido" && auth.exigido && auth.autenticado;
 
   // Um admin que perdeu o push e não avisa é pior que um admin sem push: o
   // operador passa a confiar numa fila parada.
@@ -80,6 +88,11 @@ export function LayoutAdmin({ rota, children }: { rota: string; children?: React
       >
         {conexao === "conectado" ? "recebendo em tempo real" : "sem conexão em tempo real"}
       </span>
+      {comSessao ? (
+        <button type="button" className="botao-fantasma" onClick={() => void sair()}>
+          Encerrar sessão
+        </button>
+      ) : null}
     </>
   );
 


=== DIFF: quote-service/Dockerfile ===
@@ -0,0 +1,11 @@
+FROM python:3.12-slim
+
+WORKDIR /srv
+COPY pyproject.toml ./
+RUN pip install --no-cache-dir fastapi "uvicorn[standard]" "pydantic>=2.6"
+
+COPY app ./app
+COPY data ./data
+
+EXPOSE 8000
+CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


=== DIFF: tests/dados/test_replay_precos.py ===
@@ -17,6 +17,8 @@ import pytest
 from qa.dataset import caminhos
 from qa.replay import precos
 
+from tests.fixtures.pii import cep_de
+
 pytestmark = pytest.mark.skipif(
     not caminhos.plans_json().is_file(),
     reason=f"plans.json do desafio não encontrado em {caminhos.plans_json()}",
@@ -24,11 +26,11 @@ pytestmark = pytest.mark.skipif(
 
 #: `docs/API-COTACAO.md` §5.4 — calculados à mão e conferidos contra a resposta da API.
 CONFERENCIA_A_MAO = [
-    ("premium", 22, 2015, "[CEP]", "1025.14"),
-    ("essencial", 65, 2018, "[CEP]", "193.04"),
-    ("completo", 28, 2012, "[CEP]", "494.58"),
+    ("premium", 22, 2015, cep_de("08"), "1025.14"),
+    ("essencial", 65, 2018, cep_de("01"), "193.04"),
+    ("completo", 28, 2012, cep_de("21"), "494.58"),
     ("premium", 30, 2026, None, "339.90"),
-    ("essencial", 75, 2006, "[CEP]", "316.42"),
+    ("essencial", 75, 2006, cep_de("59"), "316.42"),
 ]
 
 #: §8.2 — os 8 preços que o gerador do dataset sorteia, independentes do perfil.
@@ -79,7 +81,7 @@ def test_cep_de_sete_digitos_subcota_sem_sinal_de_erro():
     """
     correto = precos.premio_esperado(
         plano_id="essencial", idade=30, veiculo_ano=2024,
-        cep="[CEP]", ano_corrente=2026,
+        cep=cep_de("07"), ano_corrente=2026,
     )
     subcotado = precos.premio_esperado(
         plano_id="essencial", idade=30, veiculo_ano=2024,
@@ -90,7 +92,7 @@ def test_cep_de_sete_digitos_subcota_sem_sinal_de_erro():
 
     conferencia = precos.conferir(
         premio=subcotado, plano_id="essencial", idade=30, veiculo_ano=2024,
-        cep="[CEP]", ano_corrente=2026,
+        cep=cep_de("07"), ano_corrente=2026,
     )
     assert conferencia.alcancavel  # ...e mesmo assim
     assert not conferencia.exato   # é reprovado pela forte.
@@ -100,7 +102,7 @@ def test_cep_de_sete_digitos_subcota_sem_sinal_de_erro():
 def test_cep_ausente_tambem_subcota():
     """"A omissão do CEP subcota em até 30%" (§5.3), em número."""
     com = precos.premio_esperado(
-        plano_id="premium", idade=30, veiculo_ano=2024, cep="[CEP]",
+        plano_id="premium", idade=30, veiculo_ano=2024, cep=cep_de("21"),
         ano_corrente=2026,
     )
     sem = precos.premio_esperado(


=== DIFF: tests/nucleo/test_compose.py ===
@@ -118,10 +118,19 @@ def test_sobe_com_5432_e_8000_ocupadas_no_host():
         assert r.returncode == 0, (
             "o compose não subiu com 5432 e 8000 ocupadas no host:\n" + r.stderr[-2000:]
         )
+        # `--wait` já espera o healthcheck do serviço `app`, então uma leitura basta.
+        # Se voltar a precisar de laço aqui, é sinal de que o healthcheck sumiu.
+        import json
         import urllib.request
 
         with urllib.request.urlopen("http://127.0.0.1:8080/api/health", timeout=10) as resp:
             assert resp.status == 200
+            assert json.load(resp)["db"] == "ok"
+
+        # E o produto inteiro, não só a API: o SPA é servido pela mesma origem.
+        with urllib.request.urlopen("http://127.0.0.1:8080/chat", timeout=10) as resp:
+            assert resp.status == 200
+            assert "text/html" in resp.headers["content-type"]
     finally:
         subprocess.run(["docker", "compose", "down", "-v"], cwd=RAIZ, capture_output=True)
         for s in bloqueios:


=== DIFF: app/bootstrap.py ===
@@ -29,7 +29,14 @@ from pathlib import Path
 RAIZ = Path(__file__).resolve().parent.parent
 
 #: Variáveis que o SDK ou o legado leem direto do ambiente, sem passar por `Settings`.
-SEM_PREFIXO = ("ANTHROPIC_API_KEY", "OLLAMA_API_KEY", "ADMIN_TOKEN")
+SEM_PREFIXO = (
+    "ANTHROPIC_API_KEY",
+    "OLLAMA_API_KEY",
+    "ADMIN_TOKEN",
+    # Lidas por `app/auth.py` direto do ambiente, sem passar por `Settings`.
+    "ADMIN_USER",
+    "ADMIN_PASSWORD",
+)
 
 #: Nomes que o `.env` usa sem prefixo e que o `Settings` espera com `APP_`.
 #:


=== DIFF: qa/replay/amostra.py ===
@@ -160,12 +160,14 @@ def amostrar(
 
     rng = random.Random(seed)
     tabela = _celulas(casos)
-    for grupo in tabela.values():
-        # Ordenar por id antes de embaralhar tira a dependência da ordem física do
-        # parquet: dois arquivos com as mesmas conversas em ordem diferente produzem
-        # a mesma amostra para a mesma seed.
-        grupo.sort(key=lambda c: c.conversation_id)
-        rng.shuffle(grupo)
+    # Duas normalizações, e **as duas** são necessárias para que a ordem física do
+    # parquet não mude a amostra: ordenar cada grupo por id, e percorrer as células numa
+    # ordem canônica. Sem a segunda, o mesmo `rng` seria consumido em ordem diferente e
+    # dois arquivos com as mesmas conversas produziriam amostras diferentes — o tipo de
+    # não determinismo que passa despercebido até alguém comparar duas execuções.
+    for chave in sorted(tabela):
+        tabela[chave].sort(key=lambda c: c.conversation_id)
+        rng.shuffle(tabela[chave])
 
     ordem = _ordem_das_celulas(tabela)
     cotas = {chave: 0 for chave in ordem}


=== DIFF: tests/nucleo/test_bootstrap.py ===
@@ -6,6 +6,7 @@ seria uma exceção de autenticação no meio de outra coisa.
 """
 
 import os
+import uuid
 
 import pytest
 
@@ -106,9 +107,11 @@ def test_admin_token_chega_ao_settings(tmp_path, monkeypatch):
     monkeypatch.delenv("ADMIN_TOKEN", raising=False)
     monkeypatch.delenv("APP_ADMIN_TOKEN", raising=False)
     env = tmp_path / ".env"
-    env.write_text("ADMIN_TOKEN=[REDIGIDO]\n")
+    # Gerado, não literal: a mesma regra das fixtures de PII (CLAUDE.md 13b).
+    token = uuid.uuid4().hex
+    env.write_text(f"ADMIN_TOKEN=[REDIGIDO]\n")
     carregar_env(env)
-    assert os.environ["APP_ADMIN_TOKEN"] == "segredo-de-teste"
+    assert os.environ["APP_ADMIN_TOKEN"] == token
 
     from app.config import Settings
 


=== DIFF: qa/replay/respondedor.py ===
@@ -60,7 +60,10 @@ _PADROES: tuple[tuple[Intencao, re.Pattern[str]], ...] = (
     (
         Intencao.PLANO_ID,
         re.compile(
-            r"\b(plano|essencial|completo|premium|cobertura|franquia|"
+            # `cobertura` NÃO entra: "quando a cobertura deve começar?" é pergunta de
+            # data, e incluí-la fazia o respondedor responder plano para ela — um erro
+            # que só apareceu porque o teste cobre as duas formas de perguntar a data.
+            r"\b(plano|essencial|completo|premium|franquia|"
             r"qual dos tr[êe]s|op[çc][ãa]o)\w*",
             re.IGNORECASE,
         ),


=== DIFF: tests/dados/test_replay_amostra.py ===
@@ -12,6 +12,8 @@ from qa.replay import amostra as amostragem
 from qa.replay.casos import CasoReplay, Fala, Gabarito
 from qa.dataset.elegibilidade import Elegibilidade
 
+from tests.fixtures.pii import cep_de
+
 OUTCOMES = ("em_negociacao", "ganho", "perdido", "sem_resposta")
 
 
@@ -21,7 +23,7 @@ def _caso(cid: str, *, idade=False, veiculo=False, outcome="ganho", midia=False,
         conversation_id=cid,
         outcome=outcome,
         falas=tuple(Fala(i, "audio" if (midia and i == 0) else "text", "oi") for i in range(falas)),
-        gabarito=Gabarito(idade=35, veiculo_ano=2018, cep="[CEP]"),
+        gabarito=Gabarito(idade=35, veiculo_ano=2018, cep=cep_de("01", com_hifen=False)),
         elegibilidade=Elegibilidade(
             cotavel=not (idade or veiculo),
             por_idade=idade,


=== DIFF: qa/replay/casos.py ===
@@ -125,8 +125,8 @@ def extrair_cep(falas: Iterable[Fala]) -> str | None:
     """O primeiro CEP que o lead pronuncia, normalizado para 8 dígitos.
 
     Normalizar aqui é o que torna a comparação justa: `conversations.cep` é
-    `String(8)`, gravado pelo validador da `QuoteRequest`. Comparar `"[CEP]"` com
-    `"[CEP]"` reprovaria uma extração correta.
+    `String(8)`, gravado pelo validador da `QuoteRequest`. Comparar a forma com hífen
+    (`01XXX-XXX`) com a de 8 dígitos corridos reprovaria uma extração correta.
     """
     for fala in falas:
         achado = _CEP.search(fala.texto or "")


Investigate per the method in your instructions, then return the findings list.

### Claude

→ **Read**  `{"file_path": "/home/<usuario>/repo/app/main.py"}`

### Mateus

```
File does not exist. Note: your current working directory is <repo>.
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
… [+10046 caracteres]
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
