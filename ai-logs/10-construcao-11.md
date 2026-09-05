# Sessão de construção 11

> Exportado por `scripts/exportar_ai_logs.py`, com redação de segredo,
> caminho absoluto e PII **na escrita**. 9 turnos; o `jsonl` de
> origem tinha 96 KB, majoritariamente saída de
> ferramenta, truncada em 1200 caracteres por bloco.

### Mateus

Review this change for security vulnerabilities.

Changed files (you may Read these and any other file in the repo):
  - tests/nucleo/test_bootstrap.py
  - tests/web/unit/layout-admin.test.tsx
  - tests/web/unit/markdown.test.tsx
  - web/src/App.tsx
  - web/src/admin/LayoutAdmin.tsx
  - web/src/chat/Bolha.tsx
  - web/src/chat/PaginaChat.tsx
  - web/src/chat/markdown.tsx
  - web/src/ui/Capa.tsx
  - web/src/ui/Casca.tsx

Unified diff (only + lines are new):

=== DIFF: tests/nucleo/test_bootstrap.py ===
@@ -12,6 +12,21 @@ import pytest
 from app.bootstrap import CredencialAusente, carregar_env, exigir_credenciais
 
 
+@pytest.fixture(autouse=True)
+def ambiente_isolado():
+    """`carregar_env` escreve em `os.environ`, e o `monkeypatch` não desfaz o que
+    não existia antes — o valor vazaria para os outros módulos da suíte.
+
+    Foi o que aconteceu: o teste do `ADMIN_TOKEN` deixou `APP_ADMIN_TOKEN` no
+    ambiente e dois testes de `test_config.py` passaram a falhar, num arquivo que
+    ninguém tinha tocado.
+    """
+    antes = dict(os.environ)
+    yield
+    os.environ.clear()
+    os.environ.update(antes)
+
+
 def test_carrega_variavel_sem_prefixo(tmp_path, monkeypatch):
     monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
     env = tmp_path / ".env"


=== DIFF: tests/web/unit/layout-admin.test.tsx ===
@@ -1,4 +1,4 @@
-import { render, screen } from "@testing-library/react";
+import { render, screen, within } from "@testing-library/react";
 import { expect, it } from "vitest";
 import { LayoutAdmin } from "../../../web/src/admin/LayoutAdmin";
 import { montarBackendFalso } from "../fakes/backend-falso";
@@ -15,7 +15,7 @@ it("o badge de pendentes aparece nas três telas", async () => {
 it("o badge some quando não há pendente — zero não é informação, é ruído", async () => {
   montarBackendFalso({ handoffs: { items: [], pendentes: 0 } });
   render(<LayoutAdmin rota="/admin/status" />);
-  expect(await screen.findByRole("navigation")).toBeVisible();
+  expect(await screen.findByRole("navigation", { name: /seções/i })).toBeVisible();
   expect(screen.queryByTestId("badge-pendentes")).toBeNull();
 });
 
@@ -31,15 +31,45 @@ it("o badge sobe no push, sem recarregar", async () => {
 it("as três telas se ligam entre si", () => {
   montarBackendFalso({});
   render(<LayoutAdmin rota="/admin/status" />);
-  const nav = screen.getByRole("navigation");
+  // Duas navegações, de propósito: "Áreas" troca de contexto (chat ↔ admin) e
+  // "Seções da operação" troca de tela dentro do admin. Consultar por papel sem
+  // nomear qual seria ambíguo — e a ambiguidade é a confusão que a casca resolve.
+  const secoes = screen.getByRole("navigation", { name: /seções/i });
   for (const [nome, href] of [
     [/convers/i, "/admin/conversas"],
     [/status/i, "/admin/status"],
     [/handoff/i, "/admin/handoffs"],
   ] as const) {
-    expect(screen.getByRole("link", { name: nome })).toHaveAttribute("href", href);
+    expect(within(secoes).getByRole("link", { name: nome })).toHaveAttribute("href", href);
   }
-  expect(nav).toBeVisible();
+});
+
+it("a seção atual se anuncia ao olho, não só ao leitor de tela", () => {
+  // `aria-current` resolve para leitor de tela e não resolve para quem enxerga.
+  // A aba ativa perde o filete inferior e encosta na folha — o `data-atual` é o
+  // que o CSS usa, e é o que este teste trava.
+  montarBackendFalso({});
+  render(<LayoutAdmin rota="/admin/status" />);
+  const secoes = screen.getByRole("navigation", { name: /seções/i });
+  const ativa = within(secoes).getByRole("link", { name: /status/i });
+  expect(ativa).toHaveAttribute("data-atual", "sim");
+  expect(ativa).toHaveAttribute("aria-current", "page");
+  expect(within(secoes).getByRole("link", { name: /convers/i })).toHaveAttribute(
+    "data-atual",
+    "nao",
+  );
+});
+
+it("a via atual é a do admin, e a do chat fica disponível", () => {
+  montarBackendFalso({});
+  render(<LayoutAdmin rota="/admin/conversas" />);
+  const areas = screen.getByRole("navigation", { name: /áreas/i });
+  const links = within(areas).getAllByRole("link");
+  expect(links).toHaveLength(2);
+  const admin = links.find((a) => a.getAttribute("href")?.startsWith("/admin"));
+  const chat = links.find((a) => a.getAttribute("href") === "/chat");
+  expect(admin).toHaveAttribute("data-atual", "sim");
+  expect(chat).toHaveAttribute("data-atual", "nao");
 });
 
 it("existe navegação para o chat — o admin não é beco sem saída", () => {


=== DIFF: tests/web/unit/markdown.test.tsx ===
@@ -0,0 +1,73 @@
+import { render, screen } from "@testing-library/react";
+import { expect, it } from "vitest";
+import { Markdown } from "../../../web/src/chat/markdown";
+
+it("negrito vira <strong>, e o asterisco some", () => {
+  const { container } = render(<Markdown texto="Quero o **Completo** mesmo" />);
+  expect(container.querySelector("strong")).toHaveTextContent("Completo");
+  expect(container.textContent).not.toContain("*");
+});
+
+it("lista com hífen vira <ul>", () => {
+  const { container } = render(
+    <Markdown texto={"Os planos:\n- Essencial: colisão\n- Completo: + vidros"} />,
+  );
+  expect(container.querySelectorAll("ul li")).toHaveLength(2);
+  expect(container.textContent).not.toContain("- Essencial");
+});
+
+it("lista numerada vira <ol>", () => {
+  const { container } = render(
+    <Markdown texto={"Faltam duas:\n1. A data\n2. O plano"} />,
+  );
+  expect(container.querySelectorAll("ol li")).toHaveLength(2);
+});
+
+it("o caso real do agente: parágrafo, lista e negrito juntos", () => {
+  const { container } = render(
+    <Markdown
+      texto={
+        "CEP registrado!\n\nFaltam só duas coisas:\n\n1. Quando começa?\n2. Qual plano?\n\n" +
+        "- **Essencial**: colisão, roubo e furto\n- **Completo**: tudo do Essencial + vidros"
+      }
+    />,
+  );
+  expect(container.querySelectorAll("ol li")).toHaveLength(2);
+  expect(container.querySelectorAll("ul li")).toHaveLength(2);
+  expect(container.querySelectorAll("strong")).toHaveLength(2);
+  expect(container.textContent).not.toContain("**");
+});
+
+it("quebra simples vira <br>, quebra dupla separa parágrafos", () => {
+  const { container } = render(<Markdown texto={"uma\ndois\n\ntrês"} />);
+  expect(container.querySelectorAll("p")).toHaveLength(2);
+  expect(container.querySelectorAll("br")).toHaveLength(1);
+});
+
+it("NÃO renderiza HTML — texto do lead e do modelo são não confiáveis", () => {
+  const { container } = render(
+    <Markdown texto={'<img src=x onerror="alert(1)"> <b>a</b> <script>x</script>'} />,
+  );
+  expect(container.querySelector("img")).toBeNull();
+  expect(container.querySelector("script")).toBeNull();
+  expect(container.querySelector("b")).toBeNull();
+  // sai como texto, que é feio e é o comportamento certo
+  expect(container.textContent).toContain("<img");
+});
+
+it("NÃO renderiza link — superfície que ninguém pediu numa tela pública", () => {
+  const { container } = render(
+    <Markdown texto="veja [aqui](javascript:alert(1))" />,
+  );
+  expect(container.querySelector("a")).toBeNull();
+});
+
+it("texto sem marcação nenhuma sai igual", () => {
+  render(<Markdown texto="Oi! Tudo bem?" />);
+  expect(screen.getByText("Oi! Tudo bem?")).toBeVisible();
+});
+
+it("asterisco solto não quebra a renderização", () => {
+  const { container } = render(<Markdown texto="custa 2 * 3 reais" />);
+  expect(container.textContent).toBe("custa 2 * 3 reais");
+});


=== DIFF: web/src/App.tsx ===
@@ -1,6 +1,7 @@
 import { useEffect, useState } from "react";
 import { Admin } from "./admin/Admin";
 import { PaginaChat } from "./chat/PaginaChat";
+import { Capa } from "./ui/Capa";
 
 /**
  * Roteador mínimo, de propósito.
@@ -12,7 +13,7 @@ import { PaginaChat } from "./chat/PaginaChat";
  */
 function useRota(): string {
   const [rota, setRota] = useState(
-    () => globalThis.location?.pathname ?? "/chat",
+    () => globalThis.location?.pathname ?? "/",
   );
 
   useEffect(() => {
@@ -49,5 +50,8 @@ export function App() {
   if (rota.startsWith("/admin")) return <Admin rota={rota} />;
   if (rota.startsWith("/chat")) return <PaginaChat />;
 
-  return <PaginaChat />;
+  // A raiz DECIDE: apresenta as duas vias em vez de cair no chat por omissão.
+  // Caindo, a existência da segunda área ficava escondida de quem abre a
+  // aplicação pela primeira vez — que é exatamente o avaliador.
+  return <Capa />;
 }


=== DIFF: web/src/admin/LayoutAdmin.tsx ===
@@ -2,6 +2,7 @@ import type { ReactNode } from "react";
 import { api } from "../api/cliente";
 import type { FilaHandoffs } from "../api/tipos";
 import { useRecurso } from "../ui/useRecurso";
+import { Casca } from "../ui/Casca";
 import { useEventos } from "./useEventos";
 
 const ABAS = [
@@ -39,41 +40,52 @@ export function LayoutAdmin({ rota, children }: { rota: string; children?: React
 
   const pendentes = fila.dado?.pendentes ?? 0;
 
-  return (
-    <div className="admin">
-      <header className="admin__barra">
-        <p className="admin__marca">AutoSeguro</p>
-        {/* Navegação, não deep link: leva à conversa do próprio navegador. */}
-        <a className="admin__voltar" href="/chat">
-          ← Ir para o chat
-        </a>
-        <nav className="admin__nav" aria-label="Telas de operação">
-          {ABAS.map((aba) => (
-            <a
-              key={aba.href}
-              href={aba.href}
-              aria-current={rota.startsWith(aba.href) ? "page" : undefined}
-            >
-              {aba.nome}
-            </a>
-          ))}
-        </nav>
-        {pendentes > 0 ? (
-          <span className="badge-pendentes" data-testid="badge-pendentes">
-            {pendentes}
-            <span className="so-leitor"> handoffs pendentes</span>
-          </span>
-        ) : null}
-        <span
-          className={
-            conexao === "conectado" ? "admin__conexao pilula" : "admin__conexao pilula pilula--atencao"
-          }
-          data-testid="conexao-eventos"
-        >
-          {conexao === "conectado" ? "recebendo em tempo real" : "sem conexão em tempo real"}
+  const separadores = (
+    <nav className="separadores" aria-label="Seções da operação">
+      {ABAS.map((aba) => {
+        const atual = rota.startsWith(aba.href);
+        return (
+          <a
+            key={aba.href}
+            className="separador"
+            href={aba.href}
+            aria-current={atual ? "page" : undefined}
+            data-atual={atual ? "sim" : "nao"}
+          >
+            {aba.nome}
+            {aba.href === "/admin/handoffs" && pendentes > 0 ? (
+              <span className="separador__contagem">{pendentes}</span>
+            ) : null}
+          </a>
+        );
+      })}
+    </nav>
+  );
+
+  const estado = (
+    <>
+      {pendentes > 0 ? (
+        <span className="badge-pendentes" data-testid="badge-pendentes">
+          {pendentes}
+          <span className="so-leitor"> handoffs pendentes</span>
         </span>
-      </header>
+      ) : null}
+      <span
+        className={
+          conexao === "conectado"
+            ? "admin__conexao pilula"
+            : "admin__conexao pilula pilula--atencao"
+        }
+        data-testid="conexao-eventos"
+      >
+        {conexao === "conectado" ? "recebendo em tempo real" : "sem conexão em tempo real"}
+      </span>
+    </>
+  );
+
+  return (
+    <Casca via="admin" separadores={separadores} estado={estado}>
       <div className="admin__conteudo">{children}</div>
-    </div>
+    </Casca>
   );
 }


=== DIFF: web/src/chat/Bolha.tsx ===
@@ -1,3 +1,4 @@
+import { Markdown } from "./markdown";
 import type { Mensagem } from "./useConversa";
 
 /**
@@ -5,6 +6,11 @@ import type { Mensagem } from "./useConversa";
  * sem rótulo que denuncie a origem. A distinção é auditoria, não produto: para
  * quem está do outro lado, é a mesma empresa falando. Ela existe e é visível no
  * admin, onde é informação.
+ *
+ * O conteúdo passa pelo renderizador de Markdown: o agente escreve `**negrito**` e
+ * listas, e sem isso o lead lê asteriscos. É um subconjunto próprio e sem
+ * `dangerouslySetInnerHTML` — o texto vem em parte do modelo e em parte do lead, e
+ * os dois são conteúdo não confiável.
  */
 export function Bolha({ mensagem }: { mensagem: Mensagem }) {
   const doLead = mensagem.autor === "lead";
@@ -18,7 +24,7 @@ export function Bolha({ mensagem }: { mensagem: Mensagem }) {
 
   return (
     <div className={classe} data-testid={`bolha-${mensagem.id}`}>
-      {mensagem.conteudo}
+      <Markdown texto={mensagem.conteudo} />
       {mensagem.suspeitaDeBug ? (
         <span className="marca-bug" data-testid="marca-bug">
           valor sem cotação vinculada


=== DIFF: web/src/chat/PaginaChat.tsx ===
@@ -1,3 +1,4 @@
+import { Casca } from "../ui/Casca";
 import { useEffect, useRef, useState } from "react";
 import type { ConversationDetail, Message } from "../api/tipos";
 import { Bolha } from "./Bolha";
@@ -72,17 +73,15 @@ export function PaginaChat({ conversationId }: { conversationId?: string }) {
       .catch(() => setFalhaAoAbrir(true));
   };
 
-  return (
-    <div className="chat">
-      <header className="chat__topo">
-        <h1 className="chat__marca">AutoSeguro</h1>
-        <div className="chat__meta">
-          <span className="pilula" data-testid="estado-conversa">
-            {ESTADO_LEGIVEL[estado.state] ?? estado.state}
-          </span>
-        </div>
-      </header>
+  const estadoDaConversa = (
+    <span className="pilula" data-testid="estado-conversa">
+      {ESTADO_LEGIVEL[estado.state] ?? estado.state}
+    </span>
+  );
 
+  return (
+    <Casca via="chat" estado={estadoDaConversa}>
+      <div className="chat">
       <div className="chat__acoes">
         <button type="button" className="botao-fantasma" onClick={trocarDeConversa}>
           Nova conversa
@@ -189,6 +188,7 @@ export function PaginaChat({ conversationId }: { conversationId?: string }) {
           </button>
         </form>
       </footer>
-    </div>
+      </div>
+    </Casca>
   );
 }


=== DIFF: web/src/chat/markdown.tsx ===
@@ -0,0 +1,134 @@
+import type { ReactNode } from "react";
+
+/**
+ * Um subconjunto seguro de Markdown, renderizado como elementos React.
+ *
+ * O agente escreve `**Essencial**`, listas com `-` e listas numeradas — é assim que
+ * ele explica os planos, e sem renderizar isso o lead lê asteriscos.
+ *
+ * **Por que um renderizador próprio e não uma biblioteca.** Duas razões, e a segunda
+ * é a que decide:
+ *
+ * 1. O que o agente produz é um subconjunto pequeno e conhecido: negrito, itálico,
+ *    código, listas e parágrafos. Uma biblioteca completa traria tabelas, HTML
+ *    embutido, links e imagens — superfície que ninguém pediu.
+ * 2. **Nada aqui passa por `dangerouslySetInnerHTML`.** O texto renderizado vem em
+ *    parte do modelo e em parte do próprio lead, e os dois são conteúdo não
+ *    confiável. Construir nós React em vez de HTML significa que uma tentativa de
+ *    injeção sai como texto — que é exatamente o que se quer, e é o mesmo princípio
+ *    que trata a mensagem do lead como dado e nunca como instrução.
+ *
+ * O que NÃO é suportado, de propósito: links, imagens, HTML embutido, tabelas e
+ * títulos. Se o agente algum dia produzir isso, o lead vê o texto cru — que é feio,
+ * e é infinitamente melhor que uma superfície de injeção numa tela pública.
+ */
+
+type Trecho = { tipo: "texto" | "negrito" | "italico" | "codigo"; valor: string };
+
+/** `**negrito**`, `*itálico*` e `` `código` `` — o que o agente de fato usa. */
+function fatiar(linha: string): Trecho[] {
+  const trechos: Trecho[] = [];
+  const padrao = /(\*\*[^*]+\*\*|\*[^*\n]+\*|`[^`\n]+`)/g;
+  let ultimo = 0;
+  for (const m of linha.matchAll(padrao)) {
+    const i = m.index;
+    if (i > ultimo) trechos.push({ tipo: "texto", valor: linha.slice(ultimo, i) });
+    const bruto = m[0];
+    if (bruto.startsWith("**")) {
+      trechos.push({ tipo: "negrito", valor: bruto.slice(2, -2) });
+    } else if (bruto.startsWith("`")) {
+      trechos.push({ tipo: "codigo", valor: bruto.slice(1, -1) });
+    } else {
+      trechos.push({ tipo: "italico", valor: bruto.slice(1, -1) });
+    }
+    ultimo = i + bruto.length;
+  }
+  if (ultimo < linha.length) trechos.push({ tipo: "texto", valor: linha.slice(ultimo) });
+  return trechos;
+}
+
+function Inline({ linha }: { linha: string }): ReactNode {
+  return fatiar(linha).map((t, i) => {
+    if (t.tipo === "negrito") return <strong key={i}>{t.valor}</strong>;
+    if (t.tipo === "italico") return <em key={i}>{t.valor}</em>;
+    if (t.tipo === "codigo") return <code key={i}>{t.valor}</code>;
+    return <span key={i}>{t.valor}</span>;
+  });
+}
+
+const ITEM_SOLTO = /^\s*[-*•]\s+(.*)$/;
+const ITEM_NUMERADO = /^\s*(\d+)[.)]\s+(.*)$/;
+
+/**
+ * Renderiza o texto da mensagem.
+ *
+ * Quebra em blocos: listas viram `<ul>`/`<ol>`, o resto vira parágrafos. Linhas em
+ * branco separam parágrafos; quebras simples dentro de um parágrafo viram `<br>`,
+ * porque o agente usa quebra simples para separar frases curtas — e colapsá-las
+ * grudaria o texto de um jeito que ele não escreveu.
+ */
+export function Markdown({ texto }: { texto: string }): ReactNode {
+  const linhas = texto.replace(/\r\n/g, "\n").split("\n");
+  const blocos: ReactNode[] = [];
+
+  let paragrafo: string[] = [];
+  let lista: { ordenada: boolean; itens: string[] } | null = null;
+
+  const fecharParagrafo = () => {
+    if (paragrafo.length === 0) return;
+    blocos.push(
+      <p key={`p${blocos.length}`}>
+        {paragrafo.map((l, i) => (
+          <span key={i}>
+            {i > 0 ? <br /> : null}
+            <Inline linha={l} />
+          </span>
+        ))}
+      </p>,
+    );
+    paragrafo = [];
+  };
+
+  const fecharLista = () => {
+    if (lista === null) return;
+    const itens = lista.itens.map((it, i) => (
+      <li key={i}>
+        <Inline linha={it} />
+      </li>
+    ));
+    blocos.push(
+      lista.ordenada ? (
+        <ol key={`l${blocos.length}`}>{itens}</ol>
+      ) : (
+        <ul key={`l${blocos.length}`}>{itens}</ul>
+      ),
+    );
+    lista = null;
+  };
+
+  for (const linha of linhas) {
+    const solto = ITEM_SOLTO.exec(linha);
+    const numerado = ITEM_NUMERADO.exec(linha);
+
+    if (solto !== null || numerado !== null) {
+      fecharParagrafo();
+      const ordenada = numerado !== null;
+      const item = ordenada ? numerado[2] : solto![1];
+      if (lista === null || lista.ordenada !== ordenada) {
+        fecharLista();
+        lista = { ordenada, itens: [] };
+      }
+      lista.itens.push(item ?? "");
+      continue;
+    }
+
+    fecharLista();
+    if (linha.trim() === "") fecharParagrafo();
+    else paragrafo.push(linha);
+  }
+
+  fecharLista();
+  fecharParagrafo();
+
+  return <div className="md">{blocos}</div>;
+}


=== DIFF: web/src/ui/Capa.tsx ===
@@ -0,0 +1,52 @@
+/**
+ * A rota `/`.
+ *
+ * Antes ela caía no chat por omissão, e o efeito era que a existência da segunda
+ * área ficava escondida: quem abria a aplicação via uma conversa e não tinha
+ * motivo para supor que houvesse um admin.
+ *
+ * A capa **decide alguma coisa**: apresenta as duas vias, diz quem lê cada uma, e
+ * deixa a escolha explícita. É a folha de rosto de uma proposta — a peça que
+ * existe justamente para dizer o que vem depois.
+ *
+ * Ela não é uma landing page: sem herói, sem argumento de venda. Três linhas e
+ * duas escolhas, porque o leitor aqui é um avaliador com pouco tempo.
+ */
+export function Capa() {
+  return (
+    <div className="capa">
+      <div className="capa__folha">
+        <p className="capa__formulario">seguro auto · proposta</p>
+        <h1 className="capa__marca">AutoSeguro</h1>
+        <p className="capa__linha">
+          Um agente atende o lead por mensagem, qualifica, cota na API de cotação e
+          decide sozinho quando passar para um humano.
+        </p>
+
+        <div className="capa__vias">
+          <a className="capa__via" href="/chat">
+            <span className="capa__ordinal">1ª via</span>
+            <span className="capa__nome">Atendimento</span>
+            <span className="capa__quem">
+              A conversa, como o lead vê. Fale com o agente e peça uma cotação.
+            </span>
+          </a>
+
+          <a className="capa__via" href="/admin/conversas">
+            <span className="capa__ordinal">2ª via</span>
+            <span className="capa__nome">Registro</span>
+            <span className="capa__quem">
+              O mesmo atendimento pelo lado da operação: cada mensagem com id e
+              status, as tentativas de cotação, a saúde da integração e a fila de
+              handoff.
+            </span>
+          </a>
+        </div>
+
+        <p className="capa__rodape">
+          A mesma conversa aparece nas duas vias. É por isso que elas existem.
+        </p>
+      </div>
+    </div>
+  );
+}


=== DIFF: web/src/ui/Casca.tsx ===
@@ -0,0 +1,89 @@
+import type { ReactNode } from "react";
+
+/**
+ * A casca comum às duas áreas.
+ *
+ * O PROBLEMA que ela resolve não é estético: a aplicação tem **dois públicos** —
+ * o lead, em `/chat`, e o operador, em `/admin` — e a interface tratava isso como
+ * um app só com abas. Quem entrava numa área não sabia que a outra existia, e o
+ * cabeçalho do admin empilhava cinco coisas de naturezas diferentes numa fileira.
+ *
+ * A METÁFORA vem do próprio vernáculo do domínio, e não de uma convenção de
+ * dashboard: um documento de seguro tem **vias**. A 1ª via é do cliente, a 2ª
+ * fica no arquivo. É exatamente a distinção de dois públicos olhando o mesmo
+ * papel — e por ser nativa do assunto, ela se explica sozinha.
+ *
+ * QUATRO NATUREZAS, QUATRO TRATAMENTOS. Era essa a confusão:
+ *
+ *   1. `timbre`      identidade do sistema — canto, discreto, voz de documento
+ *   2. `vias`        navegação entre ÁREAS — o elemento mais forte da casca;
+ *                    a via inativa fica lavada, como cópia carbono
+ *   3. `separadores` navegação entre SEÇÕES — abas de pasta, só no admin, em
+ *                    linha própria, e a ativa **se conecta à folha** (sem filete
+ *                    inferior), que é o que a torna óbvia ao olho e não só ao
+ *                    `aria-current`
+ *   4. `estado`      operação — badge e conexão, à direita, em Courier
+ *
+ * As duas navegações usam linguagens visuais **diferentes de propósito**: se
+ * "ir para o admin" e "ir para status" parecerem a mesma coisa, o leitor não tem
+ * como saber que uma troca de contexto e a outra não.
+ */
+
+export type Via = "chat" | "admin";
+
+const VIAS = [
+  { id: "chat" as const, href: "/chat", ordinal: "1ª", nome: "Atendimento", quem: "o cliente" },
+  { id: "admin" as const, href: "/admin/conversas", ordinal: "2ª", nome: "Registro", quem: "a operação" },
+];
+
+export function Casca({
+  via,
+  separadores,
+  estado,
+  children,
+}: {
+  via: Via;
+  /** Abas de seção. Só o admin tem; o chat passa `undefined` e a linha some. */
+  separadores?: ReactNode;
+  /** Badge de pendentes e pílula de conexão. Zona própria, nunca junto das abas. */
+  estado?: ReactNode;
+  children?: ReactNode;
+}) {
+  return (
+    <div className="casca" data-via={via}>
+      <header className="casca__cabecalho">
+        <div className="casca__timbre">
+          <span className="casca__marca">AutoSeguro</span>
+          <span className="casca__formulario">seguro auto · proposta</span>
+        </div>
+
+        <nav className="casca__vias" aria-label="Áreas">
+          {VIAS.map((v) => {
+            const atual = v.id === via;
+            return (
+              <a
+                key={v.id}
+                className="via"
+                href={v.href}
+                aria-current={atual ? "true" : undefined}
+                data-atual={atual ? "sim" : "nao"}
+              >
+                <span className="via__ordinal">{v.ordinal} via</span>
+                <span className="via__nome">{v.nome}</span>
+                <span className="so-leitor"> — para {v.quem}</span>
+              </a>
+            );
+          })}
+        </nav>
+
+        {estado !== undefined ? <div className="casca__estado">{estado}</div> : null}
+      </header>
+
+      {separadores !== undefined ? (
+        <div className="casca__separadores">{separadores}</div>
+      ) : null}
+
+      <div className="casca__folha">{children}</div>
+    </div>
+  );
+}


Investigate per the method in your instructions, then return the findings list.

### Claude

Looking at this change, the highest-risk surface is the new custom markdown renderer (`web/src/chat/markdown.tsx`), which processes untrusted content from both the LLM and the lead. Let me trace this carefully.

### Claude

→ **Read**  `{"file_path": "/home/<usuario>/web/src/chat/markdown.tsx"}`

### Mateus

```
File does not exist. Note: your current working directory is <repo>.
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
… [+3859 caracteres]
```

### Claude

After reviewing all changed files, I found no security vulnerabilities.

Key analysis:

**`web/src/chat/markdown.tsx` (highest-risk file — new custom parser for untrusted lead + LLM content):**
- All output is emitted as React children (`<strong>{t.valor}</strong>`, `<em>`, `<code>`, `<span>`, `<li>`, `<p>`). React auto-escapes text children, so `<img onerror>`, `<script>`, etc. become literal text.
- No `dangerouslySetInnerHTML`, no dynamic tag names, no `href`/`src` attributes anywhere.
- Links and images are deliberately unsupported — no vector for `javascript:` URIs, `data:` URIs, or img-tag XSS.
- Regex patterns (`\*\*[^*]+\*\*`, `\*[^*\n]+\*`, `` `[^`\n]+` ``) use bounded negated character classes with no nested quantifiers — not vulnerable to ReDoS.
- Tests explicitly assert no `<img>`, `<script>`, `<b>`, or `<a>` elements are produced from injection payloads.

**`web/src/chat/Bolha.tsx`:** Renders `mensagem.conteudo` via the Markdown component — safe by the above.

**`web/src/ui/Casca.tsx`, `Capa.tsx`, `admin/LayoutAdmin.tsx`:** All navigation targets (`href`), `data-via`, `data-atual`, and `aria-current` values come from hardcoded literals (`VIAS`, `ABAS`) or a typed `via: "chat" | "admin"` prop — no user input reaches attributes or URLs. The refactor moves markup around but introduces no new sinks.

**`web/src/App.tsx`:** Default-route change from `/chat` to Capa — pure routing, no auth/authz impact.

**`web/src/chat/PaginaChat.tsx`:** Refactor to wrap in `Casca`; `ESTADO_LEGIVEL[estado.state]` is a static lookup table with fallback.

**`tests/nucleo/test_bootstrap.py`:** New pytest fixture that snapshots/restores `os.environ`. Test-only hygiene, no runtime impact.

### Claude

→ **StructuredOutput**  `{"findings": []}`

### Mateus

```
Structured output provided successfully
```
