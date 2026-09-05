# Sessão de construção 12

> Exportado por `scripts/exportar_ai_logs.py`, com redação de segredo,
> caminho absoluto e PII **na escrita**. 23 turnos; o `jsonl` de
> origem tinha 167 KB, majoritariamente saída de
> ferramenta, truncada em 1200 caracteres por bloco.

### Mateus

Review this change for security vulnerabilities.

Changed files (you may Read these and any other file in the repo):
  - tests/web/unit/reducer-conversa.test.ts
  - tests/web/unit/texto-cru-local.test.ts
  - web/src/chat/textoCruLocal.ts
  - web/src/chat/useConversa.ts

Unified diff (only + lines are new):

=== DIFF: tests/web/unit/reducer-conversa.test.ts ===
@@ -61,7 +61,7 @@ describe("bolha otimista", () => {
     expect(e.mensagens.at(-1)).toMatchObject({ id: "tmp-1", autor: "lead", pendente: true });
   });
 
-  it("reconcilia por id, e o texto exibido passa a ser o MASCARADO", () => {
+  it("reconcilia por id — nunca por texto, porque o eco vem mascarado", () => {
     // Reconciliar por texto seria bug: não existe endpoint que devolva a versão
     // crua (openapi.yaml, invariante 2). Aqui o digitado e o ecoado diferem por
     // construção, porque a frase carrega PII.
@@ -71,7 +71,23 @@ describe("bolha otimista", () => {
     expect(e.mensagens).toHaveLength(1);
     expect(e.mensagens[0]!.id).toBe("m0");
     expect(e.mensagens[0]!.pendente).toBe(false);
-    expect(e.mensagens[0]!.conteudo).not.toContain(pii.cpf);
+  });
+
+  it("o lead continua vendo o que digitou — o servidor é que não guarda", () => {
+    // Este teste substitui um que exigia o oposto. A versão anterior assertava que
+    // a bolha do lead passava a exibir o texto MASCARADO depois do eco, e o efeito
+    // era o lead ver a própria mensagem alterada — o que parece defeito, porque ele
+    // sabe o que escreveu.
+    //
+    // O invariante do backend não mudou nem um pouco: o eco vem mascarado, o banco
+    // guarda mascarado, e não existe endpoint com a versão crua. O que mudou é que
+    // o NAVEGADOR DELE lembra o que ele digitou, em sessionStorage, e nada disso
+    // sai da aba.
+    const [frase, pii] = fraseDoLead(11);
+    let e = reduzir(estadoInicial(), { type: "envio-local", idTemp: "tmp-1", texto: frase });
+    e = reduzir(e, msg(0, "lead", frase.replace(pii.cpf, "[CPF]")));
+    expect(e.mensagens[0]!.conteudo).toBe(frase);
+    expect(e.mensagens[0]!.conteudo).toContain(pii.cpf);
   });
 
   it("reconcilia FIFO quando o lead envia duas antes do eco (a conversa enfileira)", () => {


=== DIFF: tests/web/unit/texto-cru-local.test.ts ===
@@ -0,0 +1,97 @@
+import { beforeEach, expect, it } from "vitest";
+import { estadoInicial, reduzir } from "../../../web/src/chat/useConversa";
+import { esquecerCru, gravarCru, lerCru } from "../../../web/src/chat/textoCruLocal";
+
+const CPF = "[CPF]";
+const DIGITADO = `meu cpf é ${CPF}`;
+const MASCARADO = "meu cpf é [CPF]";
+
+function ecoDoServidor(id: string, index: number) {
+  return {
+    type: "message" as const,
+    message: {
+      id,
+      index,
+      autor: "lead" as const,
+      tipo: "text" as const,
+      // O servidor SEMPRE devolve mascarado: não existe endpoint com a versão crua.
+      conteudo: MASCARADO,
+      status: "received" as const,
+      quote_id: null,
+      criado_em: new Date().toISOString(),
+    },
+  };
+}
+
+beforeEach(() => sessionStorage.clear());
+
+it("o lead vê o que digitou, não a versão mascarada", () => {
+  let e = estadoInicial();
+  e = reduzir(e, { type: "envio-local", idTemp: "t1", texto: DIGITADO });
+  e = reduzir(e, ecoDoServidor("m1", 0));
+  expect(e.mensagens).toHaveLength(1);
+  expect(e.mensagens[0]!.conteudo).toBe(DIGITADO);
+});
+
+it("o texto cru migra do id temporário para o canônico", () => {
+  let e = estadoInicial();
+  e = reduzir(e, { type: "envio-local", idTemp: "t1", texto: DIGITADO });
+  e = reduzir(e, ecoDoServidor("m1", 0));
+  expect(e.cruDoLead["m1"]).toBe(DIGITADO);
+  expect(e.cruDoLead["t1"]).toBeUndefined();
+});
+
+it("só a fala do LEAD tem versão local", () => {
+  // O que a empresa disse vem do servidor e não pode ter segunda fonte da verdade.
+  let e = estadoInicial({ m2: "texto local indevido" });
+  e = reduzir(e, {
+    type: "message",
+    message: {
+      id: "m2", index: 0, autor: "agente", tipo: "text",
+      conteudo: "Oi! Como posso ajudar?", status: "sent",
+      quote_id: null, criado_em: new Date().toISOString(),
+    },
+  });
+  expect(e.mensagens[0]!.conteudo).toBe("Oi! Como posso ajudar?");
+});
+
+it("sem versão local, cai na mascarada — degrada, não quebra", () => {
+  let e = estadoInicial();
+  e = reduzir(e, ecoDoServidor("m1", 0));
+  expect(e.mensagens[0]!.conteudo).toBe(MASCARADO);
+});
+
+it("o histórico do servidor também usa a versão local quando existe", () => {
+  // Depois de um F5: o histórico vem mascarado, o sessionStorage tem o cru.
+  const e = reduzir(estadoInicial({ m1: DIGITADO }), {
+    type: "historico",
+    messages: [ecoDoServidor("m1", 0).message],
+  });
+  expect(e.mensagens[0]!.conteudo).toBe(DIGITADO);
+});
+
+it("sessionStorage: grava, lê e esquece", () => {
+  gravarCru("c1", { m1: DIGITADO });
+  expect(lerCru("c1")).toEqual({ m1: DIGITADO });
+  esquecerCru("c1");
+  expect(lerCru("c1")).toEqual({});
+});
+
+it("é por conversa — uma não vaza para a outra", () => {
+  gravarCru("c1", { m1: DIGITADO });
+  expect(lerCru("c2")).toEqual({});
+});
+
+it("storage bloqueado não quebra a tela", () => {
+  const original = Storage.prototype.setItem;
+  Storage.prototype.setItem = () => {
+    throw new Error("bloqueado");
+  };
+  expect(() => gravarCru("c1", { m1: DIGITADO })).not.toThrow();
+  Storage.prototype.setItem = original;
+});
+
+it("JSON corrompido no storage não quebra a tela", () => {
+  sessionStorage.setItem("autoseguro:cru:c1", "{isso não é json");
+  expect(lerCru("c1")).toEqual({});
+});


=== DIFF: web/src/chat/textoCruLocal.ts ===
@@ -0,0 +1,61 @@
+/**
+ * O texto que o lead digitou, guardado **só na sessão do navegador dele**.
+ *
+ * O PROBLEMA. O mascaramento acontece na gravação, então não existe versão crua em
+ * lugar nenhum do servidor — nem no banco, nem no log, nem para o operador. Isso é
+ * deliberado e é a garantia mais forte do projeto: não é uma regra que alguém precisa
+ * lembrar de aplicar, é uma ausência.
+ *
+ * O efeito colateral era feio: o lead digitava o CPF e via `[CPF]` na própria bolha.
+ * Ele sabe o que escreveu, e a mensagem alterada parece defeito.
+ *
+ * A SAÍDA que não enfraquece nada: o navegador dele lembra o que ele digitou, e só
+ * ele. Três propriedades, e as três importam:
+ *
+ * 1. **`sessionStorage`, não `localStorage`.** Morre quando a aba fecha. Um CPF que
+ *    sobrevive a um reboot num computador compartilhado é um problema novo criado
+ *    para resolver um problema de aparência.
+ * 2. **Nunca sai do navegador.** Nada aqui é enviado, sincronizado ou lido pelo
+ *    servidor. O invariante do backend fica intacto: ele continua sem nunca ter a
+ *    versão crua persistida.
+ * 3. **Só a fala do lead.** O texto do agente e do sistema vem do servidor, já
+ *    mascarado, e não tem versão local — se tivesse, seria uma segunda fonte da
+ *    verdade para o que a empresa disse.
+ *
+ * Quando o `sessionStorage` não está disponível (aba anônima com storage bloqueado,
+ * navegador travado), tudo degrada para o comportamento anterior: o lead vê a versão
+ * mascarada. Feio, e correto.
+ */
+
+const PREFIXO = "autoseguro:cru:";
+
+function chave(conversationId: string): string {
+  return `${PREFIXO}${conversationId}`;
+}
+
+export function lerCru(conversationId: string): Record<string, string> {
+  try {
+    const bruto = sessionStorage.getItem(chave(conversationId));
+    if (bruto === null) return {};
+    const lido: unknown = JSON.parse(bruto);
+    return typeof lido === "object" && lido !== null ? (lido as Record<string, string>) : {};
+  } catch {
+    return {};
+  }
+}
+
+export function gravarCru(conversationId: string, mapa: Record<string, string>): void {
+  try {
+    sessionStorage.setItem(chave(conversationId), JSON.stringify(mapa));
+  } catch {
+    /* storage bloqueado: degrada para a versão mascarada */
+  }
+}
+
+export function esquecerCru(conversationId: string): void {
+  try {
+    sessionStorage.removeItem(chave(conversationId));
+  } catch {
+    /* idem */
+  }
+}


=== DIFF: web/src/chat/useConversa.ts ===
@@ -10,6 +10,7 @@
  */
 
 import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";
+import { gravarCru, lerCru } from "./textoCruLocal";
 import { conectarChat, type StatusConexao } from "../api/ws";
 import type { EstadoConversa, EventoChat, Message } from "../api/tipos";
 
@@ -25,6 +26,14 @@ export type Mensagem = Message & {
 
 export type Estado = {
   porId: Map<string, Mensagem>;
+  /**
+   * `id da mensagem → texto que o LEAD digitou`, antes do mascaramento.
+   *
+   * Só existe no navegador dele (`textoCruLocal.ts`). O servidor continua sem nunca
+   * ter a versão crua persistida — o que muda é que o lead deixa de ver a própria
+   * mensagem alterada, que parecia defeito.
+   */
+  cruDoLead: Record<string, string>;
   /** Ids temporários na ordem de envio. A reconciliação é FIFO. */
   pendentesDoLead: string[];
   mensagens: Mensagem[];
@@ -54,13 +63,26 @@ function pareceCotacaoSemLastro(m: Message): boolean {
   return DINHEIRO.test(m.conteudo) && !temQuote;
 }
 
-function enriquecer(m: Message, pendente: boolean): Mensagem {
-  return { ...m, pendente, suspeitaDeBug: pareceCotacaoSemLastro(m) };
+function enriquecer(
+  m: Message,
+  pendente: boolean,
+  cruDoLead: Record<string, string> = {},
+): Mensagem {
+  const cru = m.autor === "lead" ? cruDoLead[m.id] : undefined;
+  return {
+    ...m,
+    // Só a fala do LEAD tem versão local. O que a empresa disse vem do servidor e
+    // não pode ter uma segunda fonte da verdade.
+    conteudo: cru ?? m.conteudo,
+    pendente,
+    suspeitaDeBug: pareceCotacaoSemLastro(m),
+  };
 }
 
-export function estadoInicial(): Estado {
+export function estadoInicial(cruDoLead: Record<string, string> = {}): Estado {
   return {
     porId: new Map(),
+    cruDoLead,
     pendentesDoLead: [],
     mensagens: [],
     digitando: false,
@@ -98,6 +120,7 @@ export function reduzir(estado: Estado, acao: Acao): Estado {
     case "message": {
       const porId = new Map(estado.porId);
       let pendentes = estado.pendentesDoLead;
+      let cruDoLead = estado.cruDoLead;
       const chegando = acao.message;
 
       /*
@@ -115,18 +138,24 @@ export function reduzir(estado: Estado, acao: Acao): Estado {
       ) {
         const [primeiro, ...resto] = pendentes;
         if (primeiro !== undefined) {
+          // O texto cru migra do id temporário para o canônico junto com a bolha.
+          const cru = estado.cruDoLead[primeiro];
+          if (cru !== undefined) {
+            cruDoLead = { ...cruDoLead, [chegando.id]: cru };
+            delete cruDoLead[primeiro];
+          }
           porId.delete(primeiro);
           pendentes = resto;
         }
       }
 
-      porId.set(chegando.id, enriquecer(chegando, false));
-      return fechar(porId, pendentes, estado);
+      porId.set(chegando.id, enriquecer(chegando, false, cruDoLead));
+      return fechar(porId, pendentes, { ...estado, cruDoLead });
     }
 
     case "historico": {
       const porId = new Map(estado.porId);
-      for (const m of acao.messages) porId.set(m.id, enriquecer(m, false));
+      for (const m of acao.messages) porId.set(m.id, enriquecer(m, false, estado.cruDoLead));
       const base = acao.state
         ? { ...estado, state: acao.state, entradaBloqueada: acao.state === "encaminhado" }
         : estado;
@@ -149,7 +178,10 @@ export function reduzir(estado: Estado, acao: Acao): Estado {
         suspeitaDeBug: false,
       };
       porId.set(acao.idTemp, otimista);
-      return fechar(porId, [...estado.pendentesDoLead, acao.idTemp], estado);
+      return fechar(porId, [...estado.pendentesDoLead, acao.idTemp], {
+        ...estado,
+        cruDoLead: { ...estado.cruDoLead, [acao.idTemp]: acao.texto },
+      });
     }
 
     /*
@@ -186,7 +218,11 @@ export function novoIdTemporario(): string {
 
 /** Liga o reducer ao socket. O componente não conhece o protocolo. */
 export function useConversa(conversationId: string | null, historico?: Message[] | null) {
-  const [estado, despachar] = useReducer(reduzir, undefined, estadoInicial);
+  // O texto cru do lead é lido do `sessionStorage` na montagem: um F5 no meio da
+  // conversa mantém o que ele digitou, e fechar a aba o descarta.
+  const [estado, despachar] = useReducer(reduzir, conversationId, (id) =>
+    estadoInicial(id !== null ? lerCru(id) : {}),
+  );
   const enviarRef = useRef<(texto: string) => boolean>(() => false);
   const ultimoIndexRef = useRef(-1);
   ultimoIndexRef.current = estado.ultimoIndex;
@@ -196,6 +232,13 @@ export function useConversa(conversationId: string | null, historico?: Message[]
     despachar({ type: "historico", messages: historico });
   }, [historico]);
 
+  // Persiste o cru do lead na sessão do NAVEGADOR. Nada disto é enviado, e o
+  // servidor continua sem nunca ter a versão crua persistida.
+  useEffect(() => {
+    if (conversationId === null) return;
+    gravarCru(conversationId, estado.cruDoLead);
+  }, [conversationId, estado.cruDoLead]);
+
   useEffect(() => {
     if (conversationId === null) return;
     const sessao = conectarChat(conversationId, {


Investigate per the method in your instructions, then return the findings list.

### Claude

→ **Read**  `{"file_path": "/home/<usuario>/web/src/chat/textoCruLocal.ts"}`

### Mateus

```
File does not exist. Note: your current working directory is <repo>.
```

### Claude

→ **Read**  `{"file_path": "<repo>/web/src/chat/textoCruLocal.ts"}`

### Mateus

```
1	/**
2	 * O texto que o lead digitou, guardado **só na sessão do navegador dele**.
3	 *
4	 * O PROBLEMA. O mascaramento acontece na gravação, então não existe versão crua em
5	 * lugar nenhum do servidor — nem no banco, nem no log, nem para o operador. Isso é
6	 * deliberado e é a garantia mais forte do projeto: não é uma regra que alguém precisa
7	 * lembrar de aplicar, é uma ausência.
8	 *
9	 * O efeito colateral era feio: o lead digitava o CPF e via `[CPF]` na própria bolha.
10	 * Ele sabe o que escreveu, e a mensagem alterada parece defeito.
11	 *
12	 * A SAÍDA que não enfraquece nada: o navegador dele lembra o que ele digitou, e só
13	 * ele. Três propriedades, e as três importam:
14	 *
15	 * 1. **`sessionStorage`, não `localStorage`.** Morre quando a aba fecha. Um CPF que
16	 *    sobrevive a um reboot num computador compartilhado é um problema novo criado
17	 *    para resolver um problema de aparência.
18	 * 2. **Nunca sai do navegador.** Nada aqui é enviado, sincronizado ou lido pelo
19	 *    servidor. O invariante do backend fica intacto: ele continua sem nunca ter a
20	 *    versão crua persistida.
21	 * 3. **Só a fala do lead.** O texto do agente e do sistema vem do se
… [+1353 caracteres]
```

### Claude

→ **Read**  `{"file_path": "<repo>/web/src/chat/useConversa.ts"}`

### Mateus

```
1	/**
2	 * O coração da tela `/chat` é uma **função pura**.
3	 *
4	 * A tela não decide nada sobre a conversa: recebe frames e os reduz. Não existe
5	 * `setTimeout(6000)` no navegador — se existisse, a política de degradação teria
6	 * duas cópias, e elas divergiriam na primeira mudança de limiar.
7	 *
8	 * Testar o reducer sem navegador é o que permite exercitar a janela de 37 s em
9	 * milissegundos: uma suíte que dorme 37 s ninguém roda.
10	 */
11	
12	import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";
13	import { gravarCru, lerCru } from "./textoCruLocal";
14	import { conectarChat, type StatusConexao } from "../api/ws";
15	import type { EstadoConversa, EventoChat, Message } from "../api/tipos";
16	
17	export type Mensagem = Message & {
18	  /** Bolha otimista: existe na tela e ainda não no banco. */
19	  pendente: boolean;
20	  /**
21	   * Texto com valor monetário e `quote_id` nulo é **bug** (openapi.yaml,
22	   * invariante 1). A tela **exibe** o bug; quem o impede é o backend.
23	   */
24	  suspeitaDeBug: boolean;
25	};
26	
27	export type Estado = {
28	  porId: Map<string, Mensagem>;
29	  /**
30	   * `id da mensagem → texto que o LEAD digitou`, ante
… [+9009 caracteres]
```

### Claude

→ **Grep**  `{"pattern": "conteudo", "path": "<repo>/web/src", "output_mode": "files_with_matches"}`

### Mateus

```
Found 7 files
web/src/chat/useConversa.ts
web/src/estilos.css
web/src/chat/Bolha.tsx
web/src/admin/LayoutAdmin.tsx
web/src/admin/DetalheConversa.tsx
web/src/chat/BlocoCotacao.tsx
web/src/api/tipos.ts
```

### Claude

→ **Grep**  `{"pattern": "dangerouslySetInnerHTML|innerHTML", "path": "<repo>/web/src", "output_mode": "content"}`

### Mateus

```
web/src/chat/markdown.tsx:15: * 2. **Nada aqui passa por `dangerouslySetInnerHTML`.** O texto renderizado vem em
web/src/chat/Bolha.tsx:12: * `dangerouslySetInnerHTML` — o texto vem em parte do modelo e em parte do lead, e
```

### Claude

→ **Read**  `{"file_path": "<repo>/web/src/chat/Bolha.tsx"}`

### Mateus

```
1	import { Markdown } from "./markdown";
2	import type { Mensagem } from "./useConversa";
3	
4	/**
5	 * `sistema` e `agente` são **visualmente idênticos** para o lead — mesma classe,
6	 * sem rótulo que denuncie a origem. A distinção é auditoria, não produto: para
7	 * quem está do outro lado, é a mesma empresa falando. Ela existe e é visível no
8	 * admin, onde é informação.
9	 *
10	 * O conteúdo passa pelo renderizador de Markdown: o agente escreve `**negrito**` e
11	 * listas, e sem isso o lead lê asteriscos. É um subconjunto próprio e sem
12	 * `dangerouslySetInnerHTML` — o texto vem em parte do modelo e em parte do lead, e
13	 * os dois são conteúdo não confiável.
14	 */
15	export function Bolha({ mensagem }: { mensagem: Mensagem }) {
16	  const doLead = mensagem.autor === "lead";
17	  const classe = [
18	    "bolha",
19	    doLead ? "bolha--lead" : "bolha--empresa",
20	    mensagem.pendente ? "bolha--pendente" : "",
21	  ]
22	    .filter(Boolean)
23	    .join(" ");
24	
25	  return (
26	    <div className={classe} data-testid={`bolha-${mensagem.id}`}>
27	      <Markdown texto={mensagem.conteudo} />
28	      {mensagem.suspeitaDeBug ? (
29	        <span className="marca-bug" dat
… [+131 caracteres]
```

### Claude

Let me verify how `conversationId` flows and whether the useConversa hook remounts on conversation change.

### Claude

→ **Grep**  `{"pattern": "useConversa", "path": "<repo>/web/src", "output_mode": "content", "-n": true}`

### Mateus

```
web/src/chat/PaginaChat.tsx:8:import { useConversa } from "./useConversa";
web/src/chat/PaginaChat.tsx:54:  const { estado, enviar } = useConversa(id, historico);
web/src/chat/Bolha.tsx:2:import type { Mensagem } from "./useConversa";
web/src/chat/BlocoCotacao.tsx:1:import type { Mensagem } from "./useConversa";
web/src/chat/useConversa.ts:220:export function useConversa(conversationId: string | null, historico?: Message[] | null) {
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

→ **Read**  `{"file_path": "<repo>/web/src/chat/PaginaChat.tsx"}`

### Mateus

```
1	import { Casca } from "../ui/Casca";
2	import { useEffect, useRef, useState } from "react";
3	import type { ConversationDetail, Message } from "../api/tipos";
4	import { Bolha } from "./Bolha";
5	import { BlocoCotacao } from "./BlocoCotacao";
6	import { Digitando } from "./Digitando";
7	import { abrirSessao, reiniciarSessao } from "./sessao";
8	import { useConversa } from "./useConversa";
9	
10	const ESTADO_LEGIVEL: Record<string, string> = {
11	  novo: "conversa aberta",
12	  qualificando: "coletando dados",
13	  cotando: "cotação em andamento",
14	  cotado: "cotação entregue",
15	  fechado: "conversa encerrada",
16	  encaminhado: "com a equipe",
17	};
18	
19	/**
20	 * A tela é um **cliente burro** de um fluxo de eventos. Ela não decide nada
21	 * sobre a conversa: recebe `MessageEvent`, `TypingEvent` e `StateEvent`, mantém
22	 * um mapa `id → Message` e renderiza ordenado por `index`.
23	 *
24	 * Não existe cronômetro aqui. Os 6 s e os 20 s da política de degradação são do
25	 * backend — se a tela tivesse um `setTimeout(6000)`, existiriam duas cópias da
26	 * política e elas divergiriam na primeira mudança de limiar.
27	 */
28	export function PaginaChat({ conversationId }: { c
… [+5905 caracteres]
```

### Claude

Analysis complete. Now I have enough context to identify a concrete defect.

**Trace of the finding:**

1. `PaginaChat.tsx:29` keeps `id` in `useState`. On "Nova conversa" (`trocarDeConversa`, line 67–74), it calls `setId(nova)` without unmounting — same `PaginaChat` instance keeps running.
2. `useConversa(id, ...)` is called with the new `id`, but `useReducer`'s third-argument initializer (`useConversa.ts:223-225`) only runs ONCE at mount. So `estado.cruDoLead` still holds the previous conversation's raw-PII map after `id` changes.
3. The persistence effect (`useConversa.ts:237-240`) has deps `[conversationId, estado.cruDoLead]`. When `conversationId` changes from `conv-1` → `conv-2`, this effect fires with the NEW id and the OLD (still-stale) `estado.cruDoLead`, writing `sessionStorage["autoseguro:cru:conv-2"] = <conv-1's raw text map>`.
4. The state never resets — subsequent `envio-local` actions spread the stale `estado.cruDoLead` (still carrying `conv-1`'s CPFs) into every rewrite of `conv-2`'s storage entry. `lerCru("conv-2")` is silently discarded on switch. `esquecerCru` is exported but never invoked.

This directly violates the file's stated invariant "É por conversa — uma não vaza para a outra" (which the test at `texto-cru-local.test.ts:73` asserts only at the storage-key layer, not across conversation switches within a single tab session).

### Claude

→ **StructuredOutput**  `{"findings": [{"filePath": "web/src/chat/useConversa.ts", "category": "cross-tenant-leakage", "vulnerableCode": "const [estado, despachar] = useReducer(reduzir, conversationId, (id) =>\n    estadoInicial(id !== null ? lerCru(id) : {}),\n  );\n  ...\n  useEffect(() => {\n    if (conversationId === nu
… [+2029 caracteres]`

### Mateus

```
Structured output provided successfully
```
