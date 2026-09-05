# Sessão de construção 16

> Exportado por `scripts/exportar_ai_logs.py`, com redação de segredo,
> caminho absoluto e PII **na escrita**. 12 turnos; o `jsonl` de
> origem tinha 386 KB, majoritariamente saída de
> ferramenta, truncada em 1200 caracteres por bloco.

### Mateus

Review this change for security vulnerabilities.

Changed files (you may Read these and any other file in the repo):
  - qa/replay/__init__.py
  - qa/replay/__main__.py
  - qa/replay/amostra.py
  - qa/replay/assercoes.py
  - qa/replay/captura.py
  - qa/replay/casos.py
  - qa/replay/executor.py
  - qa/replay/falhas.py
  - qa/replay/precos.py
  - qa/replay/relatorio.py
  - qa/replay/respondedor.py
  - tests/dados/conftest.py
  - tests/dados/test_preco_contra_api.py
  - tests/dados/test_replay_amostra.py
  - tests/dados/test_replay_casos.py
  - tests/dados/test_replay_precos.py
  - tests/web/fakes/backend-falso.ts
  - tests/web/setup.ts
  - tests/web/unit/login.test.tsx
  - tests/web/unit/openapi-deriva.test.ts

Unified diff (only + lines are new):

=== DIFF: qa/replay/__init__.py ===
@@ -0,0 +1,32 @@
+"""Replay do dataset do desafio contra o agente — o harness de avaliação.
+
+Três decisões definem tudo o que está aqui, e as três vêm de `docs/DECISOES-FECHADAS.md`
+§9:
+
+1. **Replay literal, com script em dois buracos.** As falas do lead saem cruas do
+   parquet, em ordem de `message_index`. Determinístico, grátis, e exercita a linguagem
+   bagunçada de verdade. Só `data_inicio` e `plano_id` — os dois campos que o lead do
+   dataset **nunca** informa e que a nossa qualificação exige — recebem respondedor
+   roteirizado (`respondedor.py`), com um contador de "não entendi a pergunta" que
+   reprova a suíte acima de um limiar. Fragilidade visível em vez de silenciosa.
+
+2. **A asserção do lead incotável é `quote_plan`, não `escalate_to_human`.** O agente
+   não tem como saber que o lead é incotável: o catálogo no system prompt tem nomes e
+   coberturas e nenhuma regra. Quem decide elegibilidade é a `/quote`, do mesmo jeito
+   que quem decide preço. E recusa não cria handoff (§2). Ver `assercoes.py`.
+
+3. **Preço se confere por cálculo, nunca por juiz de modelo.** O conjunto fechado de
+   72 prêmios possíveis (`precos.py`) é o gabarito. `AgentAsJudgeEval` fica restrito a
+   tom e clareza da recusa, que é julgamento e não conta.
+
+E uma restrição de operação: o volume completo são **16.470 mensagens do lead em 2.500
+conversas**, uma inferência por mensagem, ~14 h de parede. O default é uma amostra
+estratificada de **30 conversas** (~10 min); o volume completo fica atrás de
+`--tudo` (`__main__.py`).
+
+**Este pacote lê o bronze cru, não o silver.** É a única parte de `qa/` que faz isso, e
+o motivo é que o silver mascara `message_body` — injetar `[CEP]` no agente mediria o
+mascaramento, não a extração. O texto cru vive em memória durante a execução e **nunca**
+é escrito: tudo que sai para o relatório passa por `app.privacy.mascarar` primeiro
+(`relatorio.py`).
+"""


=== DIFF: qa/replay/__main__.py ===
@@ -0,0 +1,116 @@
+"""`python -m qa.replay` — a linha de comando do replay.
+
+**O default é 30 conversas, e isso é uma decisão de relógio, não de rigor.** Medido no
+parquet: 16.470 mensagens do lead em 2.500 conversas, uma inferência por mensagem.
+
+| Escopo | Inferências | Parede a 3 s |
+|---|---|---|
+| 2.500 conversas | 16.470 | ~14 h |
+| 150 conversas | 991 | ~50 min |
+| 50 conversas | 342 | ~17 min |
+| **30 conversas (default)** | **203** | **~10 min** |
+
+O volume completo fica atrás de `--tudo`, para ser uma decisão consciente e de
+preferência noturna — não algo que trave a entrega no meio da tarde. E não comprime com
+nada: inferência local não paraleliza sem GPU sobrando, e a `/quote` tem teto de 40
+chamadas lentas simultâneas (API-COTACAO §3.3).
+
+O comando **não executa nada** sem `--rodar`. Sem a flag ele imprime a amostra, a
+estratificação e a estimativa de parede — que é o que alguém quer ver antes de gastar
+dez minutos, e o único jeito de conferir a amostra sem pagar por ela.
+"""
+
+from __future__ import annotations
+
+import argparse
+import sys
+from pathlib import Path
+
+from qa.dataset import bronze, caminhos
+from qa.replay import amostra as amostragem
+from qa.replay import casos as construtor
+from qa.replay import relatorio as rel_mod
+from qa.replay.executor import Executor, Modo
+
+#: Fica em `qa/_saida/`, que carrega o próprio `.gitignore` com `*` — o relatório é
+#: derivado do dataset e não é versionado, mesmo mascarado.
+def destino_padrao() -> Path:
+    return caminhos.dir_saida().parent / "replay"
+
+
+def montar_parser() -> argparse.ArgumentParser:
+    p = argparse.ArgumentParser(
+        prog="python -m qa.replay", description="Replay do dataset contra o agente."
+    )
+    p.add_argument(
+        "--modo", choices=[str(Modo.EXTRACAO), str(Modo.DESFECHO)],
+        default=str(Modo.DESFECHO),
+        help="extracao afere idade, veiculo_ano e CEP; desfecho exercita a cadeia inteira.",
+    )
+    p.add_argument("--conversas", type=int, default=30, help="tamanho da amostra (default 30).")
+    p.add_argument(
+        "--tudo", action="store_true",
+        help="as 2.500 conversas. ~14 h de parede — leia o docstring antes.",
+    )
+    p.add_argument("--seed", type=int, default=[CEP], help="semente da amostragem.")
+    p.add_argument("--ano-corrente", type=int, default=None,
+                   help="fixa o ano para a fronteira do veículo (as medições são de 2026).")
+    p.add_argument("--rodar", action="store_true",
+                   help="executa de verdade. Sem isto, só imprime a amostra e o custo.")
+    p.add_argument("--saida", type=Path, default=None, help="onde escrever o relatório JSON.")
+    p.add_argument(
+        "--continuar-no-402", action="store_true",
+        help="não para no primeiro 402. O free tier do Ollama Cloud devolve 402 em três "
+             "dos quatro modelos, e insistir só produz mais 402 — use com motivo.",
+    )
+    return p
+
+
+def main(argv: list[str] | None = None) -> int:
+    args = montar_parser().parse_args(argv)
+
+    try:
+        casos = construtor.montar(bronze.ler(), ano_corrente=args.ano_corrente)
+    except bronze.BronzeIndisponivel as e:
+        print(f"bronze indisponível: {e}", file=sys.stderr)
+        return 2
+
+    medido = amostragem.contar_medido(casos)
+    print(f"corpus .......... {medido['conversas']} conversas, "
+          f"{sum(c.inferencias for c in casos)} falas do lead")
+    print(f"elegibilidade ... idade {medido['idade']} · veículo {medido['veiculo']} · "
+          f"ambos {medido['ambos']} · cotáveis {medido['cotaveis']}")
+
+    n = len(casos) if args.tudo else args.conversas
+    estratificacao = amostragem.amostrar(casos, n=n, seed=args.seed)
+    print(f"\namostra ......... {len(estratificacao)} conversas, "
+          f"{estratificacao.inferencias} inferências "
+          f"({rel_mod.estimativa_de_parede(estratificacao.inferencias)} de parede)")
+    print(f"  elegibilidade   {estratificacao.por_elegibilidade}")
+    print(f"  outcome         {estratificacao.por_outcome}")
+    print(f"  com mídia       {estratificacao.com_midia}")
+
+    if not args.rodar:
+        print("\nnada foi executado. Repita com --rodar para valer.")
+        return 0
+
+    import asyncio
+
+    executor = Executor(
+        modo=Modo(args.modo),
+        seed=args.seed,
+        ano_corrente=args.ano_corrente,
+        parar_no_402=not args.continuar_no_402,
+    )
+    rel = asyncio.run(executor.executar(estratificacao))
+
+    destino = args.saida or (destino_padrao() / f"replay-{args.modo}-{args.seed}.json")
+    rel.escrever(destino)
+    print()
+    print(rel_mod.render(rel))
+    print(f"relatório ....... {destino}")
+    return 0 if rel.aprovado else 1
+
+
+if __name__ == "__main__":
+    raise SystemExit(main())


=== DIFF: qa/replay/amostra.py ===
@@ -0,0 +1,251 @@
+"""Amostra estratificada em dois eixos, e o custo de relógio que a obriga a existir.
+
+**Por que estratificar.** Uma amostra aleatória de 30 conversas em 2.500 tem ~9 leads
+incotáveis por acaso, e a chance de ela conter uma das **60 conversas recusadas pelos
+dois motivos** é de 51%. Ou seja: metade das execuções não exercitaria o estrato mais
+interessante do corpus — o que fixa, por medição, qual recusa a API reporta primeiro
+(a etária, por precedência do serviço; ver `qa/dataset/elegibilidade.avaliar`).
+
+**Os dois eixos.**
+
+1. Os quatro `conversation_outcome` do dataset — `em_negociacao` 757, `ganho` 712,
+   `perdido` 538, `sem_resposta` 493 (API-COTACAO §8.3). Não são alvo (o desfecho do
+   dataset veio de um vendedor cujas cotações são 100% impossíveis); são variedade de
+   tom e de objeção, que é o que muda o texto que o agente recebe.
+2. Os motivos de recusa — 280 por idade, 531 por veículo, **60 por ambos**, 1.749
+   cotáveis (API-COTACAO §8.1). Este eixo é alvo: ele decide o desfecho esperado.
+
+Mais um estrato transversal: conversas com **mídia sem transcrição**, 1.789 mensagens em
+6,8% do corpus. Ele não é um quinto motivo de recusa — é uma condição que pode aparecer
+em qualquer célula — e por isso entra como **cota mínima** sobre a amostra já formada,
+não como uma linha a mais na tabela.
+
+**As contagens medidas se sobrepõem de propósito.** 280 e 531 incluem as 60; 280 + 531
+− 60 = 751 = 30,0%. A partição usada para sortear é disjunta (`só idade` 220, `só
+veículo` 471, `ambos` 60, `cotável` 1.749) porque uma conversa não pode ser sorteada
+duas vezes; `contar_medido()` devolve a forma medida, que é a que a suíte confere.
+"""
+
+from __future__ import annotations
+
+import random
+from collections import Counter
+from dataclasses import dataclass
+from typing import Iterable, Sequence
+
+from qa.replay.casos import CasoReplay
+
+#: Os quatro estratos disjuntos do eixo de elegibilidade, na ordem em que a cota é
+#: garantida. `ambos` vem primeiro porque é o menor e o mais informativo: numa amostra
+#: de 30, ele é o único que a proporcionalidade pura zeraria.
+ESTRATOS_ELEGIBILIDADE = ("ambos", "so_idade", "so_veiculo", "cotavel")
+
+#: Medido em `docs/API-COTACAO.md` §8.1, com o ano corrente 2026. É a forma com
+#: sobreposição — `idade` e `veiculo` incluem `ambos`.
+MEDIDO = {"idade": 280, "veiculo": 531, "ambos": 60, "cotaveis": 1749, "conversas": 2500}
+
+#: Conversas com pelo menos uma mensagem de mídia sem transcrição, e a fração mínima da
+#: amostra reservada a elas. 6,8% das mensagens são mídia (§8.3); pedir ~10% da amostra
+#: garante ao menos uma conversa com mídia mesmo em `n=30`, sem distorcer os outros
+#: eixos além de uma conversa por célula.
+FRACAO_MIDIA = 0.10
+
+
+def estrato_de(caso: CasoReplay) -> str:
+    """A célula disjunta do eixo de elegibilidade."""
+    por_idade, por_veiculo = caso.elegibilidade.por_idade, caso.elegibilidade.por_veiculo
+    if por_idade and por_veiculo:
+        return "ambos"
+    if por_idade:
+        return "so_idade"
+    if por_veiculo:
+        return "so_veiculo"
+    return "cotavel"
+
+
+def contar_medido(casos: Iterable[CasoReplay]) -> dict[str, int]:
+    """As contagens na forma da medição — com sobreposição, para conferir contra §8.1.
+
+    Deliberadamente **não** é a partição disjunta: é a tabela publicada que a suíte
+    reproduz, e reproduzir uma tabela diferente da publicada seria conferir outra coisa.
+    """
+    casos = list(casos)
+    return {
+        "conversas": len(casos),
+        "idade": sum(1 for c in casos if c.elegibilidade.por_idade),
+        "veiculo": sum(1 for c in casos if c.elegibilidade.por_veiculo),
+        "ambos": sum(
+            1
+            for c in casos
+            if c.elegibilidade.por_idade and c.elegibilidade.por_veiculo
+        ),
+        "cotaveis": sum(1 for c in casos if c.cotavel),
+    }
+
+
+@dataclass(frozen=True)
+class Estratificacao:
+    """A amostra e a prova de como ela ficou.
+
+    Guardar a distribuição ao lado dos casos é o que permite ao relatório dizer "30
+    conversas, 4 incotáveis, 1 pelos dois motivos, 3 com mídia" em vez de "30
+    conversas" — que é uma afirmação sem informação.
+    """
+
+    casos: tuple[CasoReplay, ...]
+    por_elegibilidade: dict[str, int]
+    por_outcome: dict[str, int]
+    com_midia: int
+    #: Uma inferência por fala do lead. O relatório imprime a estimativa de parede.
+    inferencias: int
+
+    def __len__(self) -> int:
+        return len(self.casos)
+
+
+def _celulas(casos: Sequence[CasoReplay]) -> dict[tuple[str, str], list[CasoReplay]]:
+    tabela: dict[tuple[str, str], list[CasoReplay]] = {}
+    for caso in casos:
+        tabela.setdefault((estrato_de(caso), caso.outcome), []).append(caso)
+    return tabela
+
+
+def _ordem_das_celulas(tabela: dict[tuple[str, str], list[CasoReplay]]) -> list[tuple[str, str]]:
+    """Célula menor primeiro, `ambos` antes de tudo.
+
+    A ordem decide quem recebe a vaga quando `n` é pequeno, e é por isso que ela é
+    explícita e não o que o dicionário devolver: com `n=30` e 16 células, quatro
+    células ficariam sem representante, e a escolha de quais não pode ser acidente de
+    ordem de iteração.
+    """
+    return sorted(
+        tabela,
+        key=lambda chave: (
+            ESTRATOS_ELEGIBILIDADE.index(chave[0]),
+            len(tabela[chave]),
+            chave[1],
+        ),
+    )
+
+
+def amostrar(
+    casos: Sequence[CasoReplay],
+    *,
+    n: int = 30,
+    seed: int = [CEP],
+    fracao_midia: float = FRACAO_MIDIA,
+) -> Estratificacao:
+    """`n` conversas, cobrindo as duas dimensões e a cota de mídia.
+
+    O sorteio é **semeado e explícito**. Uma amostra que muda a cada execução torna
+    impossível dizer se a taxa de extração caiu porque o agente piorou ou porque
+    saíram outras conversas — e é exatamente essa a pergunta que o replay existe para
+    responder.
+
+    O algoritmo, em três passos:
+
+    1. **uma vaga por célula não vazia**, na ordem de `_ordem_das_celulas` — é o que
+       garante as 60 conversas recusadas pelos dois motivos em qualquer `n ≥ 16`;
+    2. **o resto por proporção**, maior resto primeiro, para que a amostra grande
+       convirja para a forma do corpus;
+    3. **cota de mídia**, trocando dentro da mesma célula. Trocar dentro da célula é o
+       que faz a cota transversal não desfazer a estratificação: sai uma conversa sem
+       mídia e entra uma com mídia do mesmo estrato e do mesmo `outcome`.
+    """
+    if n <= 0:
+        return Estratificacao((), {}, {}, 0, 0)
+    casos = list(casos)
+    if n >= len(casos):
+        return _fechar(casos)
+
+    rng = random.Random(seed)
+    tabela = _celulas(casos)
+    for grupo in tabela.values():
+        # Ordenar por id antes de embaralhar tira a dependência da ordem física do
+        # parquet: dois arquivos com as mesmas conversas em ordem diferente produzem
+        # a mesma amostra para a mesma seed.
+        grupo.sort(key=lambda c: c.conversation_id)
+        rng.shuffle(grupo)
+
+    ordem = _ordem_das_celulas(tabela)
+    cotas = {chave: 0 for chave in ordem}
+
+    for chave in ordem:
+        if sum(cotas.values()) >= n:
+            break
+        cotas[chave] = 1
+
+    restante = n - sum(cotas.values())
+    if restante > 0:
+        total_disponivel = sum(len(tabela[c]) - cotas[c] for c in ordem)
+        exatos = {
+            chave: restante * (len(tabela[chave]) - cotas[chave]) / total_disponivel
+            for chave in ordem
+        }
+        for chave in ordem:
+            cotas[chave] += int(exatos[chave])
+        sobra = n - sum(cotas.values())
+        # Maior resto primeiro; empate desfeito pela mesma ordem canônica de cima.
+        for chave in sorted(
+            ordem, key=lambda c: (-(exatos[c] % 1), ordem.index(c))
+        )[:sobra]:
+            if cotas[chave] < len(tabela[chave]):
+                cotas[chave] += 1
+
+    escolhidos = [c for chave in ordem for c in tabela[chave][: cotas[chave]]]
+    escolhidos = _garantir_midia(escolhidos, tabela, cotas, n, fracao_midia)
+    return _fechar(escolhidos)
+
+
+def _garantir_midia(
+    escolhidos: list[CasoReplay],
+    tabela: dict[tuple[str, str], list[CasoReplay]],
+    cotas: dict[tuple[str, str], int],
+    n: int,
+    fracao: float,
+) -> list[CasoReplay]:
+    """Troca dentro da célula até bater a cota mínima de conversas com mídia.
+
+    Quando nenhuma célula tem uma conversa com mídia sobrando, a cota fica abaixo do
+    alvo e isso **não** é erro: o relatório imprime `com_midia`, e um número abaixo do
+    pedido é informação sobre o corpus, não uma falha da amostragem. Estourar aqui
+    trocaria um número honesto por uma exceção.
+    """
+    alvo = max(1, round(n * fracao)) if fracao > 0 else 0
+    presentes = [c for c in escolhidos if c.tem_midia_sem_transcricao]
+    if len(presentes) >= alvo:
+        return escolhidos
+
+    dentro = {c.conversation_id for c in escolhidos}
+    faltam = alvo - len(presentes)
+    for chave in _ordem_das_celulas(tabela):
+        if faltam <= 0:
+            break
+        grupo = tabela[chave]
+        candidatos = [
+            c for c in grupo[cotas[chave]:] if c.tem_midia_sem_transcricao
+        ]
+        substituiveis = [
+            c
+            for c in grupo[: cotas[chave]]
+            if not c.tem_midia_sem_transcricao and c.conversation_id in dentro
+        ]
+        for entra, sai in zip(candidatos, substituiveis):
+            if faltam <= 0:
+                break
+            escolhidos[escolhidos.index(sai)] = entra
+            dentro.discard(sai.conversation_id)
+            dentro.add(entra.conversation_id)
+            faltam -= 1
+    return escolhidos
+
+
+def _fechar(escolhidos: Sequence[CasoReplay]) -> Estratificacao:
+    escolhidos = list(escolhidos)
+    return Estratificacao(
+        casos=tuple(escolhidos),
+        por_elegibilidade=dict(Counter(estrato_de(c) for c in escolhidos)),
+        por_outcome=dict(Counter(c.outcome for c in escolhidos)),
+        com_midia=sum(1 for c in escolhidos if c.tem_midia_sem_transcricao),
+        inferencias=sum(c.inferencias for c in escolhidos),
+    )


=== DIFF: qa/replay/assercoes.py ===
@@ -0,0 +1,291 @@
+"""O que se espera de cada conversa — e a asserção que estava invertida.
+
+A formulação original — *"lead incotável chamou `escalate_to_human` e não chamou
+`quote_plan`"* — é incorreta por dois motivos, ambos consequência de decisões fechadas
+(`docs/DECISOES-FECHADAS.md` §2 e §9):
+
+1. **Recusa não cria handoff.** Chamar `escalate_to_human` num lead incotável é o
+   defeito, não o acerto.
+2. **O agente não tem como saber que o lead é incotável.** O catálogo no system prompt
+   tem nomes e coberturas e **nenhuma regra** — nem limite de idade, nem de ano do
+   veículo. Quem decide elegibilidade é a `/quote`, exatamente como quem decide preço.
+
+| Lead | Deve chamar | Desfecho | Não deve |
+|---|---|---|---|
+| incotável | **`quote_plan`** — obrigatório, é a API que decide | `refused` com o motivo certo | `escalate_to_human` |
+| cotável | `quote_plan` com idade e ano corretos | `ok` | `escalate_to_human` |
+
+**A terceira linha, que a tabela não tem e o corpus exige.** Parte das conversas do
+dataset traz, na fala do lead, um gatilho de handoff legítimo — o lead pede um atendente,
+ou fala de um sinistro. Nessas, encaminhar é o acerto, e cobrar `quote_plan` mediria o
+agente contra o oposto do que a política manda. Quem classifica não é uma regex nova
+daqui: é `app.handoff.gatilhos`, o mesmo módulo que decide em produção. Um segundo
+classificador divergiria do primeiro, e o replay passaria a reprovar o agente por
+concordar com a própria política.
+
+**O que o `ReliabilityEval` cobre e o que ele não cobre.** Ele expressa "deve chamar"
+(`expected_tool_calls`) e "com estes argumentos" (`expected_tool_call_arguments`, casamento
+parcial). Ele **não** expressa "pode chamar, mas não precisa": desligar
+`allow_additional_tool_calls` para pegar `escalate_to_human` reprovaria junto todo turno
+que chamou `qualify_lead`, que é legítimo e não obrigatório. Então o "não deve" é
+conferido aqui, em três linhas de cálculo — que é onde o `CLAUDE.md` 27 manda o harness
+próprio ficar.
+"""
+
+from __future__ import annotations
+
+import re
+from dataclasses import dataclass, field
+from enum import Enum
+from typing import Any, Iterable, Sequence
+
+from app.contracts.conversa import HandoffTrigger
+from qa.replay.casos import CasoReplay
+
+QUALIFY = "qualify_lead"
+QUOTE = "quote_plan"
+ESCALATE = "escalate_to_human"
+
+
+class Desfecho(str, Enum):
+    """O estado terminal observável de uma conversa do replay."""
+
+    OK = "ok"
+    REFUSED = "refused"
+    ENCAMINHADO = "encaminhado"
+    #: A conversa acabou sem cotação e sem handoff — o agente ficou perguntando.
+    INCOMPLETO = "incompleto"
+    #: A execução parou por falha do provedor. Não é veredito sobre o agente.
+    FALHOU = "falhou"
+
+    def __str__(self) -> str:
+        return self.value
+
+
+#: Os gatilhos que a **fala do lead** pode acionar sozinha, antes de qualquer cotação.
+#: Os outros quatro (guardrail, cotação indisponível, extração falhou, objeção repetida)
+#: dependem do que acontece durante o turno e não podem ser previstos do corpus.
+GATILHOS_DO_TEXTO = (HandoffTrigger.ASSUNTO_SENSIVEL, HandoffTrigger.LEAD_PEDIU)
+
+
+def gatilho_no_corpus(caso: CasoReplay) -> HandoffTrigger | None:
+    """O primeiro gatilho que as falas do lead acionam, pela precedência de produção.
+
+    Reusa `gatilhos.casa` em vez de reimplementar as regexes: elas são o contrato, e
+    duas cópias do contrato são um contrato só até alguém editar uma.
+    """
+    from app.handoff import gatilhos
+
+    for fala in caso.falas:
+        contexto = gatilhos.Contexto(texto_do_lead=fala.texto)
+        for trigger in GATILHOS_DO_TEXTO:
+            if gatilhos.casa(trigger, contexto):
+                return trigger
+    return None
+
+
+@dataclass(frozen=True)
+class Expectativa:
+    """O contrato de uma conversa, pronto para virar asserção.
+
+    `motivo_recusa` só é exigido quando o desfecho é `refused`: é o que separa "recusou"
+    de "recusou pelo motivo certo", e a diferença importa nas **60 conversas recusadas
+    pelos dois motivos**, onde a API reporta a idade por precedência do serviço. Um
+    replay que só conferisse "recusou" passaria com o motivo errado.
+    """
+
+    desfecho: Desfecho
+    tools_obrigatorias: tuple[str, ...] = ()
+    tools_proibidas: tuple[str, ...] = ()
+    motivo_recusa: str | None = None
+    argumentos_de_quote: dict[str, Any] = field(default_factory=dict)
+    #: A conversa tem mídia sem transcrição ⇒ o agente precisa pedir por texto ou
+    #: encaminhar, e nunca inventar o conteúdo.
+    exige_pedido_de_texto: bool = False
+    gatilho_esperado: HandoffTrigger | None = None
+
+
+def esperado_para(caso: CasoReplay) -> Expectativa:
+    """A expectativa desta conversa. Três linhas de tabela, nesta precedência."""
+    gatilho = gatilho_no_corpus(caso)
+    if gatilho is not None:
+        # Handoff legítimo vindo da fala do lead. Cobrar cotação aqui mediria o agente
+        # contra o oposto da política.
+        return Expectativa(
+            desfecho=Desfecho.ENCAMINHADO,
+            tools_proibidas=(),
+            gatilho_esperado=gatilho,
+            exige_pedido_de_texto=caso.tem_midia_sem_transcricao,
+        )
+
+    # O CEP entra na comparação junto com idade e ano do veículo, e **não fica de
+    # fora por ser opcional no contrato da API**.
+    #
+    # É o erro mais caro possível neste domínio: se o agente mandar `cep=None`
+    # quando o lead disse um CEP de prefixo de risco, a `/quote` devolve um prêmio
+    # **30% menor** e ninguém percebe — a API não tem como saber que o CEP existia.
+    # O número sai plausível, verificável contra as regras, e errado.
+    argumentos = {
+        chave: valor
+        for chave, valor in (
+            ("idade", caso.gabarito.idade),
+            ("veiculo_ano", caso.gabarito.veiculo_ano),
+            ("cep", caso.gabarito.cep),
+        )
+        if valor is not None
+    }
+    return Expectativa(
+        desfecho=Desfecho.REFUSED if not caso.cotavel else Desfecho.OK,
+        tools_obrigatorias=(QUOTE,),
+        tools_proibidas=(ESCALATE,),
+        motivo_recusa=caso.motivo_recusa,
+        argumentos_de_quote=argumentos,
+        exige_pedido_de_texto=caso.tem_midia_sem_transcricao,
+    )
+
+
+# ─── a ponte com o `ReliabilityEval` do Agno ─────────────────────────────────
+
+
+@dataclass
+class RunAgregado:
+    """Um `RunOutput` de mentira que agrega os turnos de uma conversa.
+
+    `ReliabilityEval` avalia **um** `RunOutput`, e a nossa unidade é a conversa: o
+    `quote_plan` acontece no turno 9 de 11, e avaliar turno a turno reprovaria os
+    outros dez por não terem cotado. O módulo lê exatamente um atributo — `messages` —
+    então agregar é concatenar. Os três campos de telemetria existem porque
+    `_get_telemetry_data` os lê; `telemetry=False` já os dispensaria, e eles ficam para
+    o caso de alguém religar.
+    """
+
+    messages: list[Any] = field(default_factory=list)
+    agent_id: str | None = None
+    model: str | None = None
+    model_provider: str | None = None
+
+
+def agregar(runs: Iterable[Any]) -> RunAgregado:
+    mensagens: list[Any] = []
+    for run in runs:
+        mensagens.extend(getattr(run, "messages", None) or [])
+    return RunAgregado(messages=mensagens)
+
+
+def montar_reliability(
+    caso: CasoReplay,
+    expectativa: Expectativa,
+    runs: Sequence[Any],
+    *,
+    db: Any = None,
+    print_results: bool = False,
+):
+    """`ReliabilityEval` para a metade "deve chamar" do contrato.
+
+    `allow_additional_tool_calls=True` é deliberado e está explicado no docstring do
+    módulo: sem ele, `qualify_lead` — legítimo e não obrigatório — reprovaria toda
+    conversa. A metade "não deve" é `tools_proibidas`, conferida por `conferir_tools`.
+
+    Devolve `None` quando não há tool obrigatória (o caso do handoff legítimo): montar
+    um eval sem expectativa produziria um `PASSED` que não significa nada.
+    """
+    if not expectativa.tools_obrigatorias:
+        return None
+    from agno.eval.reliability import ReliabilityEval
+
+    return ReliabilityEval(
+        name=f"replay:{caso.conversation_id}",
+        agent_response=agregar(runs),  # type: ignore[arg-type]
+        expected_tool_calls=list(expectativa.tools_obrigatorias),
+        allow_additional_tool_calls=True,
+        expected_tool_call_arguments=(
+            {QUOTE: expectativa.argumentos_de_quote}
+            if expectativa.argumentos_de_quote
+            else None
+        ),
+        db=db,
+        telemetry=False,
+        print_results=print_results,
+    )
+
+
+def conferir_tools(
+    expectativa: Expectativa, chamadas: Sequence[str]
+) -> tuple[tuple[str, ...], tuple[str, ...]]:
+    """`(faltando, proibidas_chamadas)`. Cálculo, não julgamento."""
+    vistas = set(chamadas)
+    return (
+        tuple(t for t in expectativa.tools_obrigatorias if t not in vistas),
+        tuple(t for t in expectativa.tools_proibidas if t in vistas),
+    )
+
+
+# ─── mídia sem transcrição ───────────────────────────────────────────────────
+
+#: O agente pediu o conteúdo por escrito. Frases nossas, não do modelo — mas o modelo
+#: escreve com as próprias palavras neste caso (não há template para isso), então o
+#: casamento é por intenção e o padrão é largo de propósito: um falso positivo aqui
+#: significa "aceitei uma forma de pedir texto que eu não previa", o que é preferível a
+#: reprovar o agente por sinônimo.
+_PEDIU_TEXTO = re.compile(
+    r"\b(por (?:escrito|texto)|escrev\w+|digit\w+|manda\w* (?:por|em) texto|"
+    r"n[ãa]o consigo (?:ouvir|abrir|ver|acessar)|n[ãa]o abro|"
+    r"me (?:conta|diz)\w* por aqui)\b",
+    re.IGNORECASE,
+)
+
+
+def tratou_midia(mensagens_do_agente: Iterable[str], encaminhou: bool) -> bool:
+    """A política de mídia foi cumprida: pediu por texto **ou** encaminhou.
+
+    A terceira saída — inventar o conteúdo do áudio — não tem como ser detectada aqui e
+    também não precisa: ela aparece como cotação com dados que o lead nunca disse, e a
+    conferência de preço e a de extração já reprovam isso.
+
+    ⚠️ **Achado, e não é desta frente corrigir.** O gatilho `midia_sem_texto` existe em
+    `app.handoff.gatilhos` mas é inalcançável pelo caminho de produção:
+    `app.agent.turno._encaminhar` monta o `Contexto` sem `tipo_da_mensagem` nem
+    `midias_apos_pedido`, que são justamente os dois campos que `casa()` lê para esse
+    gatilho. Ou seja: hoje a política de mídia depende inteiramente do modelo pedir
+    texto. Por isso a asserção aqui é a disjunção, e não `encaminhou`.
+    """
+    if encaminhou:
+        return True
+    return any(_PEDIU_TEXTO.search(m or "") for m in mensagens_do_agente)
+
+
+# ─── tom e clareza da recusa: o único lugar de juiz de modelo ────────────────
+
+CRITERIO_RECUSA = (
+    "A mensagem explica ao lead, com clareza e sem jargão, que a cotação não pode ser "
+    "feita, e diz o motivo real. Ela NÃO promete exceção, análise, retorno de um "
+    "atendente ou revisão do caso. Ela NÃO sugere trocar o condutor principal por outra "
+    "pessoa. Ela não usa tom de culpa nem de deboche. Se o motivo for a idade do "
+    "veículo, oferecer cotar outro veículo da casa é correto e desejável."
+)
+
+
+def montar_juiz_da_recusa(*, model: Any = None, db: Any = None, threshold: int = 8):
+    """`AgentAsJudgeEval` para tom e clareza — **nunca** para preço nem elegibilidade.
+
+    Preço é cálculo e tem gabarito fechado (`precos.py`); elegibilidade tem gabarito em
+    `plans.json`. Perguntar qualquer um dos dois a um juiz de modelo trocaria uma conta
+    exata por uma opinião cara. O que sobra para o juiz é o que não tem conta: se o
+    texto da recusa soa como uma porta fechada com respeito ou como uma promessa vaga.
+
+    O texto da recusa vem de um mapa fixo (`app.textos.POR_MOTIVO`), então este juiz
+    avalia **a nossa redação**, não a do modelo — e é por isso que ele roda uma vez por
+    motivo, não uma vez por conversa. Ver `docs/EVALS.md` para a ressalva de qual modelo
+    produziu qual número.
+    """
+    from agno.eval.agent_as_judge import AgentAsJudgeEval
+
+    return AgentAsJudgeEval(
+        name="replay:tom-da-recusa",
+        criteria=CRITERIO_RECUSA,
+        scoring_strategy="numeric",
+        threshold=threshold,
+        model=model,
+        db=db,
+        telemetry=False,
+    )


=== DIFF: qa/replay/captura.py ===
@@ -0,0 +1,172 @@
+"""A costura que devolve o `RunOutput` de cada turno ao replay.
+
+**O problema.** `ReliabilityEval` assere sobre `agent_response.messages[].tool_calls` —
+ele precisa do `RunOutput`. Mas `app.agent.turno.responder` roda o agente por dentro e
+não devolve nada: ele persiste, entrega pelo canal, aplica a regra de descarte e volta
+`None`. Rodar o agente por fora, montando o `ContextoDoTurno` no replay, resolveria o
+acesso e **duplicaria** a regra de descarte, a avaliação dos sete gatilhos e a gravação
+de `turn_usage` — três comportamentos que o replay existe para verificar, não para
+reimplementar. Um replay que reimplementa o que mede não mede mais nada.
+
+**A costura.** Trocar `app.agent.turno.construir_agente` por um embrulho que devolve o
+mesmo agente com `run` instrumentado. O caminho de produção continua sendo o exercitado,
+byte a byte; o que muda é que o `RunOutput` fica visível — e que a exceção do provedor
+fica visível também, o que importa porque `responder` captura `Exception` de forma ampla
+e um 402 chegaria ao relatório como "conversa normal que respondeu estranho".
+
+**A alternativa que não foi escolhida**, e por quê: fazer `responder` devolver o
+`RunOutput`. É mais limpo e é uma mudança em `app/` — fora do escopo desta frente. Se
+esta costura se mostrar frágil, é essa a correção, e ela cabe em uma linha.
+"""
+
+from __future__ import annotations
+
+from contextlib import contextmanager
+from dataclasses import dataclass, field
+from typing import Any, Iterator
+
+from qa.replay.falhas import Falha, de_excecao
+
+
+@dataclass
+class Coletor:
+    """O que aconteceu em cada turno, na ordem.
+
+    `runs` e `falhas` são listas paralelas ao número de chamadas, não ao número de
+    turnos: um turno que retenta duas vezes aparece duas vezes. É o que permite ao
+    relatório distinguir "10 turnos" de "10 turnos e 4 retentativas".
+    """
+
+    runs: list[Any] = field(default_factory=list)
+    falhas: list[Falha] = field(default_factory=list)
+    conversation_id: str | None = None
+    message_index: int | None = None
+
+    @property
+    def ultimo_run(self) -> Any | None:
+        return self.runs[-1] if self.runs else None
+
+    def chamadas_de_tool(self, desde: int = 0) -> list[str]:
+        """Os nomes das tools chamadas, na ordem, a partir do `desde`-ésimo run.
+
+        Achatar aqui — em vez de deixar cada asserção reabrir o `RunOutput` — é o que
+        mantém a forma do objeto do Agno em **um** lugar. Quando ela mudar de versão,
+        muda aqui.
+        """
+        nomes: list[str] = []
+        for run in self.runs[desde:]:
+            for mensagem in getattr(run, "messages", None) or []:
+                for chamada in getattr(mensagem, "tool_calls", None) or []:
+                    nome = _nome_da_chamada(chamada)
+                    if nome:
+                        nomes.append(nome)
+        return nomes
+
+    def argumentos_de(self, tool: str, desde: int = 0) -> list[dict[str, Any]]:
+        """Os argumentos de cada chamada a `tool`, já decodificados.
+
+        O Agno entrega os argumentos como **string JSON** dentro de
+        `function.arguments`. Decodificar em cada asserção seria repetir o mesmo
+        `json.loads` com o mesmo `try` em cinco lugares.
+        """
+        import json
+
+        saida: list[dict[str, Any]] = []
+        for run in self.runs[desde:]:
+            for mensagem in getattr(run, "messages", None) or []:
+                for chamada in getattr(mensagem, "tool_calls", None) or []:
+                    if _nome_da_chamada(chamada) != tool:
+                        continue
+                    brutos = _argumentos_da_chamada(chamada)
+                    if isinstance(brutos, str):
+                        try:
+                            brutos = json.loads(brutos)
+                        except (ValueError, TypeError):
+                            brutos = {}
+                    saida.append(brutos if isinstance(brutos, dict) else {})
+        return saida
+
+
+def _nome_da_chamada(chamada: Any) -> str | None:
+    if isinstance(chamada, dict):
+        return (chamada.get("function") or {}).get("name") or chamada.get("name")
+    funcao = getattr(chamada, "function", None)
+    return getattr(funcao, "name", None) or getattr(chamada, "name", None)
+
+
+def _argumentos_da_chamada(chamada: Any) -> Any:
+    if isinstance(chamada, dict):
+        return (chamada.get("function") or {}).get("arguments") or chamada.get("arguments")
+    funcao = getattr(chamada, "function", None)
+    return getattr(funcao, "arguments", None) or getattr(chamada, "arguments", None)
+
+
+class _AgenteEspiao:
+    """Delegação total, com `run` instrumentado.
+
+    Existe como plano B: em quase todo caso basta atribuir `agente.run = embrulho`, mas
+    uma classe com `__slots__` ou um `run` só de leitura recusaria a atribuição. Falhar
+    aí produziria um `AttributeError` a dez frames de distância da causa; este proxy
+    troca isso por um caminho que sempre funciona.
+    """
+
+    def __init__(self, alvo: Any, embrulho) -> None:
+        object.__setattr__(self, "_alvo", alvo)
+        object.__setattr__(self, "_embrulho", embrulho)
+
+    def run(self, *args, **kwargs):
+        return object.__getattribute__(self, "_embrulho")(*args, **kwargs)
+
+    def __getattr__(self, nome: str):
+        return getattr(object.__getattribute__(self, "_alvo"), nome)
+
+    def __setattr__(self, nome: str, valor) -> None:
+        setattr(object.__getattribute__(self, "_alvo"), nome, valor)
+
+
+def instrumentar(agente: Any, coletor: Coletor) -> Any:
+    """Devolve o agente com `run` gravando no coletor. Reexporta a exceção."""
+    original = agente.run
+
+    def embrulho(*args, **kwargs):
+        try:
+            saida = original(*args, **kwargs)
+        except Exception as e:  # noqa: BLE001 — classificada e relançada, nunca engolida
+            coletor.falhas.append(
+                de_excecao(
+                    e,
+                    conversation_id=coletor.conversation_id,
+                    message_index=coletor.message_index,
+                )
+            )
+            raise
+        coletor.runs.append(saida)
+        return saida
+
+    try:
+        agente.run = embrulho  # type: ignore[method-assign]
+        return agente
+    except (AttributeError, TypeError):  # pragma: no cover - depende da versão do Agno
+        return _AgenteEspiao(agente, embrulho)
+
+
+@contextmanager
+def capturando(coletor: Coletor) -> Iterator[Coletor]:
+    """Enquanto o bloco durar, todo agente construído por `turno` grava no coletor.
+
+    Restaura o original no `finally`, inclusive quando o corpo levanta: deixar a costura
+    instalada depois de uma falha faria o próximo teste da mesma sessão medir o coletor
+    errado, e esse é o tipo de defeito que só aparece na ordem de execução.
+    """
+    from app.agent import turno as modulo_turno
+
+    original = modulo_turno.construir_agente
+
+    def construir(ctx):
+        return instrumentar(original(ctx), coletor)
+
+    modulo_turno.construir_agente = construir  # type: ignore[assignment]
+    try:
+        yield coletor
+    finally:
+        modulo_turno.construir_agente = original  # type: ignore[assignment]


=== DIFF: qa/replay/casos.py ===
@@ -0,0 +1,214 @@
+"""Um caso de replay por conversa: as falas cruas do lead e o gabarito.
+
+**Por que o bronze e não o silver.** O silver mascara `message_body`: injetar
+`"meu cep é [CEP]"` no agente mediria o mascaramento, não a extração. O replay é o único
+consumidor de `qa/` que precisa do texto cru, e ele o mantém **em memória**. Nada daqui
+é escrito: o relatório mascara antes de serializar (`relatorio.py`).
+
+**Três campos medidos: idade, `veiculo_ano` e CEP.** Marca e modelo ficam de fora, e o
+motivo é uma observação sobre o dataset (DECISOES-FECHADAS §9): `veiculo_texto` contém
+informação que o lead nunca disse — a coluna diz "Renault Sandero 2022" e a fala diz "e
+um Sandero 2022". Penalizar o agente por não extrair uma marca que ninguém pronunciou é
+medir o ruído do gabarito, não o agente.
+
+O CEP entra com os outros dois porque aparece em 100% das conversas, está na fala do
+lead, e errar nele **subcota em 30%** nos prefixos de risco (API-COTACAO §5.3). Depois
+da idade e do ano do veículo, é o erro de extração de maior consequência que existe.
+
+**`data_inicio` e `plano_id` não têm gabarito e não são medidos aqui**: o lead do
+dataset nunca os informa. Quem os cobre é o respondedor roteirizado.
+"""
+
+from __future__ import annotations
+
+import re
+from dataclasses import dataclass, field
+from datetime import date
+from typing import Any, Iterable
+
+from app.privacy.mascarar import _REGRAS
+from qa.dataset.elegibilidade import Elegibilidade, avaliar, carregar_regras
+
+#: O mesmo padrão de CEP que o mascaramento usa, reaproveitado como extrator do
+#: gabarito. Uma segunda definição de "o que é um CEP" divergiria da primeira — e a
+#: primeira é a que decide o que vaza. `test_replay_casos` prova que é a mesma.
+_CEP = next(padrao for nome, padrao, _ in _REGRAS if nome == "cep")
+
+_SO_DIGITOS = re.compile(r"\D")
+
+#: `message_type` que carrega mídia. O corpo existe (`"[audio] mensagem de voz (18s)"`)
+#: mas é um rótulo do gerador, não transcrição: não há conteúdo para extrair.
+TIPOS_DE_MIDIA = ("audio", "image", "document")
+
+
+@dataclass(frozen=True)
+class Fala:
+    """Uma mensagem do lead, crua, com a posição canônica."""
+
+    message_index: int
+    tipo: str
+    texto: str
+
+    @property
+    def e_midia_sem_transcricao(self) -> bool:
+        return self.tipo in TIPOS_DE_MIDIA
+
+
+@dataclass(frozen=True)
+class Gabarito:
+    """O que o agente deveria ter extraído. Três campos, e só três.
+
+    `cep` é PII e vive só em memória. Ele existe para a comparação com
+    `conversations.cep`, que também é mascarado na gravação — a comparação é feita
+    sobre os **dígitos normalizados**, do nosso lado, e nenhum dos dois chega ao
+    relatório.
+    """
+
+    idade: int | None
+    veiculo_ano: int | None
+    cep: str | None
+
+    #: Quais dos três o dataset de fato oferece. Um gabarito ausente não é um erro do
+    #: agente, e contá-lo como erro rebaixaria a taxa de extração por culpa do dataset.
+    @property
+    def campos_com_gabarito(self) -> tuple[str, ...]:
+        return tuple(
+            c for c in ("idade", "veiculo_ano", "cep") if getattr(self, c) is not None
+        )
+
+
+@dataclass(frozen=True)
+class CasoReplay:
+    """Uma conversa do dataset, pronta para ser injetada.
+
+    `outcome` é o `conversation_outcome` do dataset (`ganho`, `perdido`,
+    `em_negociacao`, `sem_resposta`) — **não** é o desfecho esperado do nosso agente.
+    Ele é um dos dois eixos da estratificação (`amostra.py`), nada mais: o desfecho que
+    o dataset registrou veio de um vendedor cujas cotações são 100% impossíveis, e
+    tratá-lo como alvo seria ensinar o alvo errado.
+    """
+
+    conversation_id: str
+    outcome: str
+    falas: tuple[Fala, ...]
+    gabarito: Gabarito
+    elegibilidade: Elegibilidade
+    #: Cru, para o relatório citar a origem depois de mascarar.
+    veiculo_texto: str | None = None
+    _midias: int = field(default=0, repr=False)
+
+    @property
+    def cotavel(self) -> bool:
+        return self.elegibilidade.cotavel
+
+    @property
+    def motivo_recusa(self) -> str | None:
+        m = self.elegibilidade.motivo
+        return None if m is None else str(m)
+
+    @property
+    def tem_midia_sem_transcricao(self) -> bool:
+        return self._midias > 0
+
+    @property
+    def midias(self) -> int:
+        return self._midias
+
+    @property
+    def inferencias(self) -> int:
+        """Uma por fala do lead. É a unidade do custo de relógio (§9): 16.470 no
+        volume completo, ~3 s cada, ~14 h de parede."""
+        return len(self.falas)
+
+
+def extrair_cep(falas: Iterable[Fala]) -> str | None:
+    """O primeiro CEP que o lead pronuncia, normalizado para 8 dígitos.
+
+    Normalizar aqui é o que torna a comparação justa: `conversations.cep` é
+    `String(8)`, gravado pelo validador da `QuoteRequest`. Comparar `"[CEP]"` com
+    `"[CEP]"` reprovaria uma extração correta.
+    """
+    for fala in falas:
+        achado = _CEP.search(fala.texto or "")
+        if achado:
+            digitos = _SO_DIGITOS.sub("", achado.group(0))
+            if len(digitos) == 8:
+                return digitos
+    return None
+
+
+def montar(
+    linhas: Iterable[dict[str, Any]], *, ano_corrente: int | None = None
+) -> list[CasoReplay]:
+    """Bronze → casos de replay, em memória.
+
+    Ordena por `(conversation_id, message_index)` e **nunca** por `timestamp`: 2.495 das
+    2.500 conversas têm relógio não monotônico (API-COTACAO §8.3), e o replay literal
+    depende da ordem certa das falas. É a mesma regra do silver, pelo mesmo motivo.
+
+    A ordem dos casos devolvidos é a de primeira aparição da conversa no arquivo, que é
+    estável para um mesmo parquet — a amostragem semeada depende disso.
+    """
+    regras = carregar_regras()
+    ano_corrente = ano_corrente or date.today().year
+
+    por_conversa: dict[str, list[dict[str, Any]]] = {}
+    for linha in linhas:
+        por_conversa.setdefault(str(linha["conversation_id"]), []).append(linha)
+
+    casos: list[CasoReplay] = []
+    for conv_id, mensagens in por_conversa.items():
+        mensagens.sort(key=lambda m: int(m["message_index"]))
+        cabeca = mensagens[0]
+
+        falas = tuple(
+            Fala(
+                message_index=int(m["message_index"]),
+                tipo=str(m["message_type"]),
+                texto=m["message_body"] or "",
+            )
+            for m in mensagens
+            if m["sender_role"] == "lead"
+        )
+        if not falas:
+            # Conversa sem fala do lead não tem o que reproduzir. Não existe no
+            # dataset medido; a guarda existe para que um parquet diferente falhe
+            # ruidosamente na contagem em vez de produzir um caso vazio.
+            continue
+
+        veredito = avaliar(
+            idade=cabeca["lead_idade_informada"],
+            veiculo_texto=cabeca["veiculo_texto"],
+            ano_corrente=ano_corrente,
+            regras=regras,
+        )
+        casos.append(
+            CasoReplay(
+                conversation_id=conv_id,
+                outcome=str(cabeca["conversation_outcome"]),
+                falas=falas,
+                gabarito=Gabarito(
+                    idade=(
+                        None
+                        if cabeca["lead_idade_informada"] is None
+                        else int(cabeca["lead_idade_informada"])
+                    ),
+                    # O ano já foi extraído pelo veredito. Copiar em vez de extrair de
+                    # novo mantém uma única definição de "o ano do veículo é o último
+                    # número de `veiculo_texto`".
+                    veiculo_ano=veredito.ano_veiculo,
+                    cep=extrair_cep(falas),
+                ),
+                elegibilidade=veredito,
+                veiculo_texto=cabeca["veiculo_texto"],
+                _midias=sum(1 for f in falas if f.e_midia_sem_transcricao),
+            )
+        )
+    return casos
+
+
+def carregar(*, ano_corrente: int | None = None) -> list[CasoReplay]:
+    """Os casos do parquet do desafio. Levanta `BronzeIndisponivel` se ele não está lá."""
+    from qa.dataset import bronze
+
+    return montar(bronze.ler(), ano_corrente=ano_corrente)


=== DIFF: qa/replay/executor.py ===
@@ -0,0 +1,455 @@
+"""A execução do replay: injeta as falas, observa o banco, monta o relatório.
+
+**Dois modos, e a diferença entre eles é o que se pergunta ao corpus.**
+
+- **`extracao`** injeta as falas e afere o que foi extraído. Gabarito: a coluna
+  `lead_idade_informada`, o ano de `veiculo_texto` e o CEP que o lead pronunciou. Três
+  campos, e só três (`casos.py` explica por que marca e modelo ficam fora). O respondedor
+  roteirizado fica **desligado** aqui: `data_inicio` e `plano_id` não têm gabarito e não
+  são medidos, e injetar respostas para eles gastaria inferência sem mudar a medição.
+- **`desfecho`** exercita a cadeia inteira até `cotado`, `refused` ou `encaminhado`, com
+  o respondedor ligado. Para na primeira conversa que chega a estado terminal: as falas
+  seguintes são o lead continuando a negociar, e continuar custaria inferência sem mudar
+  o desfecho que se está medindo.
+
+**O caminho exercitado é o de produção.** O executor chama `app.agent.turno.responder` —
+a mesma função que o canal web chama — e observa o resultado **no banco**, não em
+variáveis suas. Reimplementar a regra de descarte ou a avaliação dos gatilhos aqui faria
+o replay medir a si mesmo.
+
+**Falhas do provedor não matam a execução.** `responder` captura `Exception` de forma
+ampla ao redor de `agente.run`: um 402 chegaria ao relatório disfarçado de "conversa que
+respondeu estranho". Por isso o executor não usa `try/except` para detectá-las — ele
+compara o tamanho de `coletor.falhas` antes e depois de cada turno (`captura.py`). Rate
+limit espera e retenta; 402 encerra a execução **com relatório**, porque o free tier do
+Ollama Cloud devolve 402 em três dos quatro modelos e insistir só produziria mais 402.
+"""
+
+from __future__ import annotations
+
+import asyncio
+import time
+from dataclasses import dataclass
+from enum import Enum
+from typing import Any, Callable, Sequence
+
+from qa.replay import amostra as amostragem
+from qa.replay import assercoes, precos
+from qa.replay.captura import Coletor, capturando
+from qa.replay.casos import CasoReplay
+from qa.replay.falhas import Backoff, ClasseDeFalha, Falha, TENTATIVAS
+from qa.replay.relatorio import (
+    ExtracaoConferida,
+    Relatorio,
+    ResultadoConversa,
+    falha_para_dict,
+)
+from qa.replay.respondedor import RespondedorRoteirizado
+
+#: Quantas respostas roteirizadas o executor injeta por fala do lead antes de seguir em
+#: frente. Dois é o número de buracos do script: se o agente ainda estiver perguntando
+#: depois de responder plano e data, insistir vira laço — e o laço apareceria no
+#: relatório como custo, não como defeito.
+MAX_INJECOES_POR_FALA = 2
+
+ESTADOS_TERMINAIS = ("cotado", "encaminhado", "fechado")
+
+
+class Modo(str, Enum):
+    EXTRACAO = "extracao"
+    DESFECHO = "desfecho"
+
+    def __str__(self) -> str:
+        return self.value
+
+
+@dataclass
+class AdaptadorDeReplay:
+    """`ChannelAdapter` de mentira: acumula o que sairia para o lead.
+
+    `send` aceita `**extras` de propósito. `turno.responder` passa `index` e `status`,
+    que o `ConsoleAdapter` não declara — engolir os extras aqui evita que o replay
+    quebre por uma diferença de assinatura entre canais que não tem nada a ver com o
+    que ele mede.
+    """
+
+    name: str = "replay"
+    enviadas: list[dict[str, Any]] = None  # type: ignore[assignment]
+
+    def __post_init__(self) -> None:
+        self.enviadas = []
+
+    async def send(
+        self,
+        conversation_id: str,
+        text: str,
+        *,
+        message_id: str = "",
+        quote_id: str | None = None,
+        autor: str = "agente",
+        **extras: Any,
+    ) -> str:
+        self.enviadas.append(
+            {"text": text, "autor": autor, "quote_id": quote_id, "message_id": message_id}
+        )
+        return f"replay:{message_id}"
+
+    async def typing(self, conversation_id: str, *, ativo: bool) -> None:
+        return None
+
+    def desde(self, marca: int) -> list[str]:
+        """As falas do agente a partir da marca — o que o respondedor lê."""
+        return [m["text"] for m in self.enviadas[marca:]]
+
+
+@dataclass
+class Observacao:
+    """O desfecho lido do banco, não deduzido do texto."""
+
+    desfecho: assercoes.Desfecho
+    motivo: str | None = None
+    trigger_handoff: str | None = None
+    premio: Any = None
+    plano_id: str | None = None
+    req_idade: int | None = None
+    req_veiculo_ano: int | None = None
+    req_cep: str | None = None
+    idade: int | None = None
+    veiculo_ano: int | None = None
+    cep: str | None = None
+
+
+def observar(sessao, conversation_id: str) -> Observacao:
+    """Lê `conversations`, `quotes` e `handoffs`. A fonte da verdade é o banco.
+
+    Precedência: handoff vence cotação. Um handoff depois de uma cotação recusada seria
+    o defeito que a §2 proíbe — recusa não cria handoff — e ler a cotação primeiro
+    esconderia exatamente esse defeito.
+    """
+    from sqlalchemy import select
+
+    from app.persistence.models import Conversation, Handoff, Quote
+
+    conv = sessao.get(Conversation, conversation_id)
+    handoff = sessao.execute(
+        select(Handoff)
+        .where(Handoff.conversation_id == conversation_id)
+        .order_by(Handoff.criado_em.desc())
+    ).scalars().first()
+    cotacao = sessao.execute(
+        select(Quote)
+        .where(Quote.conversation_id == conversation_id)
+        .order_by(Quote.criado_em.desc())
+    ).scalars().first()
+
+    base = {
+        "idade": getattr(conv, "idade", None),
+        "veiculo_ano": getattr(conv, "veiculo_ano", None),
+        "cep": getattr(conv, "cep", None),
+    }
+    if cotacao is not None:
+        base.update(
+            premio=cotacao.premio_mensal,
+            plano_id=cotacao.req_plano_id,
+            req_idade=cotacao.req_idade,
+            req_veiculo_ano=cotacao.req_veiculo_ano,
+            req_cep=cotacao.req_cep,
+        )
+
+    if handoff is not None:
+        return Observacao(
+            desfecho=assercoes.Desfecho.ENCAMINHADO,
+            trigger_handoff=handoff.trigger,
+            motivo=handoff.trigger,
+            **base,
+        )
+    if cotacao is not None and cotacao.status == "ok":
+        return Observacao(desfecho=assercoes.Desfecho.OK, **base)
+    if cotacao is not None and cotacao.status == "refused":
+        return Observacao(
+            desfecho=assercoes.Desfecho.REFUSED, motivo=cotacao.motivo_recusa, **base
+        )
+    return Observacao(desfecho=assercoes.Desfecho.INCOMPLETO, **base)
+
+
+# ─── o laço de uma conversa ──────────────────────────────────────────────────
+
+
+@dataclass
+class Executor:
+    """Estado de uma execução inteira. Um por invocação, nunca reusado.
+
+    `sessao_factory`, `responder` e `dormir` são injetáveis para que a suíte do harness
+    exercite o laço, a estratificação e a resiliência **sem banco, sem modelo e sem
+    dormir de verdade** — que é o que permite testar o replay sem rodá-lo.
+    """
+
+    modo: Modo = Modo.DESFECHO
+    seed: int = [CEP]
+    ano_corrente: int | None = None
+    parar_no_402: bool = True
+    max_injecoes: int = MAX_INJECOES_POR_FALA
+    #: Injetáveis. Default: o caminho de produção.
+    sessao_factory: Callable[[], Any] | None = None
+    responder: Callable[..., Any] | None = None
+    backoff: Backoff | None = None
+    modelo: str = ""
+
+    def __post_init__(self) -> None:
+        if self.backoff is None:
+            self.backoff = Backoff(seed=self.seed)
+
+    def _fabrica(self):
+        if self.sessao_factory is not None:
+            return self.sessao_factory()
+        from app.persistence.db import sessao_factory
+
+        return sessao_factory()()
+
+    async def _turno(
+        self, coletor: Coletor, conversation_id: str, texto: str, adaptador
+    ) -> Falha | None:
+        """Um turno, com retentativa. Devolve a falha que sobrou, ou `None`.
+
+        A falha é detectada por **delta no coletor**, não por `except`: `responder` já
+        capturou a exceção lá dentro e devolveu normalmente. Ver o docstring do módulo.
+        """
+        responder = self.responder
+        if responder is None:
+            from app.agent.turno import responder as responder_producao
+
+            responder = responder_producao
+
+        tentativa = 0
+        while True:
+            antes = len(coletor.falhas)
+            coletor.message_index = None
+            await responder(
+                conversation_id, texto, adaptador, chegada_do_lead=time.monotonic()
+            )
+            if len(coletor.falhas) == antes:
+                return None
+
+            falha = coletor.falhas[-1]
+            tentativa += 1
+            if tentativa > TENTATIVAS.get(falha.classe, 0):
+                return falha
+            self.backoff.esperar(tentativa)  # type: ignore[union-attr]
+
+    async def rodar_conversa(
+        self, caso: CasoReplay, coletor: Coletor
+    ) -> ResultadoConversa:
+        from app.persistence import repo
+
+        adaptador = AdaptadorDeReplay()
+        respondedor = RespondedorRoteirizado(conversation_id=caso.conversation_id)
+        resultado = ResultadoConversa(
+            conversation_id=caso.conversation_id,
+            estrato=amostragem.estrato_de(caso),
+            outcome_dataset=caso.outcome,
+            inferencias=caso.inferencias,
+            tem_midia=caso.tem_midia_sem_transcricao,
+        )
+        expectativa = assercoes.esperado_para(caso)
+        resultado.desfecho_esperado = str(expectativa.desfecho)
+        resultado.motivo_esperado = expectativa.motivo_recusa
+
+        t0 = time.monotonic()
+        sessao = self._fabrica()
+        try:
+            conv = repo.criar_conversa(
+                sessao, channel="replay", external_ref=f"replay:{caso.conversation_id}"
+            )
+            sessao.commit()
+            conversation_id = conv.id
+            coletor.conversation_id = conversation_id
+
+            falha = await self._injetar(
+                caso, coletor, conversation_id, adaptador, respondedor, sessao
+            )
+
+            resultado.turnos = len(coletor.runs)
+            resultado.perguntas_do_agente = respondedor.perguntas
+            resultado.nao_entendi = respondedor.nao_entendi
+
+            if falha is not None:
+                resultado.falha = falha_para_dict(falha)
+                resultado.desfecho_obtido = str(assercoes.Desfecho.FALHOU)
+                return resultado
+
+            sessao.expire_all()
+            obs = observar(sessao, conversation_id)
+            self._conferir(caso, expectativa, obs, coletor, adaptador, resultado)
+            return resultado
+        finally:
+            resultado.segundos = time.monotonic() - t0
+            sessao.close()
+
+    async def _injetar(
+        self, caso, coletor, conversation_id, adaptador, respondedor, sessao
+    ) -> Falha | None:
+        """As falas, em ordem de `message_index`, com o script nos dois buracos."""
+        from app.persistence import repo
+
+        for fala in caso.falas:
+            coletor.message_index = fala.message_index
+            marca = len(adaptador.enviadas)
+            falha = await self._turno(coletor, conversation_id, fala.texto, adaptador)
+            if falha is not None:
+                return falha
+
+            if self.modo is Modo.DESFECHO:
+                for _ in range(self.max_injecoes):
+                    resposta = self._resposta_roteirizada(
+                        respondedor, adaptador.desde(marca)
+                    )
+                    if resposta is None:
+                        break
+                    marca = len(adaptador.enviadas)
+                    falha = await self._turno(
+                        coletor, conversation_id, resposta, adaptador
+                    )
+                    if falha is not None:
+                        return falha
+
+                sessao.expire_all()
+                conv = repo.obter_conversa(sessao, conversation_id)
+                if conv is not None and conv.state in ESTADOS_TERMINAIS:
+                    # Terminal: as falas seguintes são o lead continuando a negociar.
+                    break
+        return None
+
+    @staticmethod
+    def _resposta_roteirizada(respondedor, falas_do_agente: Sequence[str]) -> str | None:
+        """A última fala do agente é a que vale — as anteriores do mesmo turno são
+        aviso de espera e bloco de cotação, que não são perguntas."""
+        resposta = None
+        for fala in falas_do_agente:
+            resposta = respondedor.responder(fala) or resposta
+        return resposta
+
+    def _conferir(
+        self, caso, expectativa, obs: Observacao, coletor, adaptador, resultado
+    ) -> None:
+        chamadas = coletor.chamadas_de_tool()
+        resultado.tools_chamadas = sorted(set(chamadas))
+        faltando, proibidas = assercoes.conferir_tools(expectativa, chamadas)
+        resultado.tools_faltando = list(faltando)
+        resultado.tools_proibidas_chamadas = list(proibidas)
+
+        resultado.desfecho_obtido = str(obs.desfecho)
+        resultado.motivo_obtido = obs.motivo
+
+        if obs.trigger_handoff == "cotacao_indisponivel":
+            # A `/quote` falhou depois de esgotadas as tentativas. É comportamento
+            # correto do agente sob dependência caída — não é veredito sobre ele, e
+            # contá-lo como erro faria a taxa de acerto oscilar com `FAILURE_RATE`.
+            resultado.falha = falha_para_dict(
+                Falha(
+                    classe=ClasseDeFalha.INDISPONIVEL,
+                    mensagem="a /quote não respondeu depois de esgotadas as tentativas",
+                    conversation_id=caso.conversation_id,
+                )
+            )
+            return
+
+        if self.modo is Modo.EXTRACAO or expectativa.tools_obrigatorias:
+            resultado.extracao = ExtracaoConferida(
+                esperado_idade=caso.gabarito.idade,
+                obtido_idade=obs.idade,
+                esperado_veiculo_ano=caso.gabarito.veiculo_ano,
+                obtido_veiculo_ano=obs.veiculo_ano,
+                cep_correto=(
+                    None
+                    if caso.gabarito.cep is None
+                    else obs.cep == caso.gabarito.cep
+                ),
+            )
+
+        if obs.desfecho is assercoes.Desfecho.OK and obs.premio is not None:
+            conferencia = precos.conferir(
+                premio=obs.premio,
+                plano_id=obs.plano_id or "",
+                idade=obs.req_idade or 0,
+                veiculo_ano=obs.req_veiculo_ano or 0,
+                cep=obs.req_cep,
+                ano_corrente=self.ano_corrente,
+            )
+            resultado.preco_alcancavel = conferencia.alcancavel
+            resultado.preco_exato = conferencia.exato
+
+        if caso.tem_midia_sem_transcricao:
+            resultado.midia_tratada = assercoes.tratou_midia(
+                [m["text"] for m in adaptador.enviadas],
+                encaminhou=obs.desfecho is assercoes.Desfecho.ENCAMINHADO,
+            )
+
+    # ─── a execução inteira ──────────────────────────────────────────────────
+
+    async def executar(self, estratificacao: amostragem.Estratificacao) -> Relatorio:
+        """Roda a amostra. **O relatório existe mesmo se nada rodar.**
+
+        Ele é construído antes do laço e devolvido pelo `finally`: uma execução que
+        morre na conversa 18 devolve 17 linhas e diz por que parou, em vez de devolver
+        um traceback e nenhum artefato.
+        """
+        rel = Relatorio(
+            modo=str(self.modo),
+            modelo=self.modelo or _modelo_configurado(),
+            seed=self.seed,
+            conversas_pedidas=len(estratificacao),
+            inferencias_previstas=estratificacao.inferencias,
+            estratificacao={
+                "por_elegibilidade": estratificacao.por_elegibilidade,
+                "por_outcome": estratificacao.por_outcome,
+                "com_midia": estratificacao.com_midia,
+            },
+        )
+        try:
+            for caso in estratificacao.casos:
+                coletor = Coletor()
+                with capturando(coletor):
+                    resultado = await self.rodar_conversa(caso, coletor)
+                rel.resultados.append(resultado)
+
+                if (
+                    self.parar_no_402
+                    and resultado.falha
+                    and resultado.falha.get("classe") == str(ClasseDeFalha.PAGAMENTO)
+                ):
+                    rel.interrompido_por = (
+                        "HTTP 402 do provedor — sem crédito para o modelo configurado; "
+                        "as conversas restantes não foram tentadas"
+                    )
+                    break
+        except KeyboardInterrupt:  # pragma: no cover - operação, não suíte
+            rel.interrompido_por = "interrompido pelo operador (Ctrl-C)"
+        finally:
+            from datetime import datetime, timezone
+
+            rel.terminado_em = datetime.now(timezone.utc).isoformat(timespec="seconds")
+            rel.segundos_de_espera = self.backoff.esperado_s  # type: ignore[union-attr]
+        return rel
+
+
+def _modelo_configurado() -> str:
+    try:
+        from app.config import get_settings
+
+        return get_settings().llm_model
+    except Exception:  # noqa: BLE001 - o relatório não morre por causa do rótulo
+        return "desconhecido"
+
+
+def executar(
+    casos: Sequence[CasoReplay],
+    *,
+    modo: Modo = Modo.DESFECHO,
+    n: int = 30,
+    seed: int = [CEP],
+    **kwargs: Any,
+) -> Relatorio:
+    """Amostra, roda e devolve o relatório. O ponto de entrada síncrono."""
+    estratificacao = amostragem.amostrar(casos, n=n, seed=seed)
+    executor = Executor(modo=modo, seed=seed, **kwargs)
+    return asyncio.run(executor.executar(estratificacao))


=== DIFF: qa/replay/falhas.py ===
@@ -0,0 +1,189 @@
+"""Classificação das falhas do provedor, e o backoff do próprio replay.
+
+**Um replay que morre na conversa 18 e não diz que morreu é pior que um replay que não
+roda.** O segundo é obviamente inútil; o primeiro produz um relatório com 17 conversas e
+a aparência de estar completo.
+
+Duas falhas concretas motivam o módulo:
+
+- **HTTP 402.** O free tier do Ollama Cloud devolve `402 Payment Required` em três dos
+  quatro modelos. Não é transitório e não adianta esperar: ou o modelo tem crédito, ou
+  não tem. A execução para, **com relatório**.
+- **Rate limit (429).** É transitório por definição, e a resposta certa é esperar. O
+  replay é uma execução longa e não interativa; abortar por um 429 desperdiça as horas
+  já gastas.
+
+**Por que a classificação é por texto e não por tipo de exceção.** O erro atravessa duas
+camadas — o SDK do provedor e o wrapper do Agno — e cada provedor embrulha de um jeito.
+Casar por tipo exigiria importar exceções de `anthropic`, `ollama` e `openai` e
+manter-se em dia com as três. Casar por `status_code` quando ele existe, e por texto
+quando não existe, cobre os três com uma função e degrada para `OUTRA` — que é
+registrada, não engolida.
+"""
+
+from __future__ import annotations
+
+import random
+import re
+import time
+from dataclasses import dataclass
+from enum import Enum
+
+
+class ClasseDeFalha(str, Enum):
+    #: 402: sem crédito. Não retenta, e para a execução.
+    PAGAMENTO = "pagamento_402"
+    #: 429 e afins: espera e retenta.
+    RATE_LIMIT = "rate_limit"
+    #: 5xx, sobrecarga, conexão. Retenta menos vezes.
+    INDISPONIVEL = "indisponivel"
+    #: Qualquer outra. Não retenta; a conversa é marcada e a execução continua.
+    OUTRA = "outra"
+
+    def __str__(self) -> str:
+        return self.value
+
+
+_PADROES: tuple[tuple[ClasseDeFalha, re.Pattern[str]], ...] = (
+    (
+        ClasseDeFalha.PAGAMENTO,
+        re.compile(
+            r"\b402\b|payment required|insufficient (?:credit|funds|balance|quota)|"
+            r"billing|upgrade your plan",
+            re.IGNORECASE,
+        ),
+    ),
+    (
+        ClasseDeFalha.RATE_LIMIT,
+        re.compile(
+            r"\b429\b|rate.?limit|too many requests|quota exceeded|"
+            r"requests per (?:minute|second)",
+            re.IGNORECASE,
+        ),
+    ),
+    (
+        ClasseDeFalha.INDISPONIVEL,
+        re.compile(
+            r"\b5\d{2}\b|overloaded|service unavailable|bad gateway|timed? ?out|"
+            r"timeout|connection (?:error|reset|refused)|temporarily",
+            re.IGNORECASE,
+        ),
+    ),
+)
+
+#: Quantas vezes cada classe vale a pena retentar dentro de um mesmo turno.
+#: `PAGAMENTO` é zero por definição: 402 não melhora com espera.
+TENTATIVAS = {
+    ClasseDeFalha.PAGAMENTO: 0,
+    ClasseDeFalha.RATE_LIMIT: 4,
+    ClasseDeFalha.INDISPONIVEL: 2,
+    ClasseDeFalha.OUTRA: 0,
+}
+
+
+def _status_de(exc: BaseException) -> int | None:
+    """`status_code` onde os SDKs o colocam, sem importar nenhum deles."""
+    for atributo in ("status_code", "status"):
+        valor = getattr(exc, atributo, None)
+        if isinstance(valor, int):
+            return valor
+    resposta = getattr(exc, "response", None)
+    valor = getattr(resposta, "status_code", None)
+    return valor if isinstance(valor, int) else None
+
+
+def classificar(exc: BaseException) -> ClasseDeFalha:
+    """A classe da falha. Olha o status primeiro, o texto depois.
+
+    O texto inclui a cadeia de `__cause__`: o Agno costuma embrulhar a exceção do SDK, e
+    a mensagem original — que é onde está o "402" — fica um nível abaixo.
+    """
+    status = _status_de(exc)
+    if status == 402:
+        return ClasseDeFalha.PAGAMENTO
+    if status == 429:
+        return ClasseDeFalha.RATE_LIMIT
+    if status is not None and 500 <= status < 600:
+        return ClasseDeFalha.INDISPONIVEL
+
+    partes: list[str] = []
+    atual: BaseException | None = exc
+    visitados: set[int] = set()
+    while atual is not None and id(atual) not in visitados:
+        visitados.add(id(atual))
+        partes.append(f"{type(atual).__name__}: {atual}")
+        atual = atual.__cause__ or atual.__context__
+
+    texto = " | ".join(partes)
+    for classe, padrao in _PADROES:
+        if padrao.search(texto):
+            return classe
+    return ClasseDeFalha.OUTRA
+
+
+@dataclass(frozen=True)
+class Falha:
+    """O que o relatório grava. Sem traceback e sem corpo de resposta.
+
+    A mensagem é truncada e passa pelo mascaramento antes de sair (`relatorio.py`): um
+    corpo de erro do provedor pode ecoar o prompt, e o prompt carrega a fala do lead.
+    """
+
+    classe: ClasseDeFalha
+    mensagem: str
+    conversation_id: str | None = None
+    message_index: int | None = None
+
+    @property
+    def fatal(self) -> bool:
+        """Continuar depois desta falha produziria só mais falhas iguais."""
+        return self.classe is ClasseDeFalha.PAGAMENTO
+
+
+def de_excecao(
+    exc: BaseException,
+    *,
+    conversation_id: str | None = None,
+    message_index: int | None = None,
+    limite: int = 300,
+) -> Falha:
+    texto = f"{type(exc).__name__}: {exc}"
+    return Falha(
+        classe=classificar(exc),
+        mensagem=texto[:limite],
+        conversation_id=conversation_id,
+        message_index=message_index,
+    )
+
+
+@dataclass
+class Backoff:
+    """Exponencial com jitter, semeado.
+
+    Semeado porque o relatório informa quanto tempo o replay passou esperando, e um
+    jitter não reprodutível tornaria dois relatórios incomparáveis por um motivo que não
+    tem nada a ver com o agente. O `dormir` é injetável para que a suíte não durma de
+    verdade — uma suíte que espera 30 s ninguém roda.
+    """
+
+    base_s: float = 2.0
+    teto_s: float = 60.0
+    seed: int = [CEP]
+    dormir: object = time.sleep
+
+    _rng: random.Random = None  # type: ignore[assignment]
+    esperado_s: float = 0.0
+
+    def __post_init__(self) -> None:
+        self._rng = random.Random(self.seed)
+
+    def espera(self, tentativa: int) -> float:
+        """Segundos para a `tentativa`-ésima retentativa, contando de 1."""
+        bruto = min(self.teto_s, self.base_s * (2 ** max(0, tentativa - 1)))
+        return bruto * (0.5 + self._rng.random() / 2)
+
+    def esperar(self, tentativa: int) -> float:
+        segundos = self.espera(tentativa)
+        self.esperado_s += segundos
+        self.dormir(segundos)  # type: ignore[operator]
+        return segundos


=== DIFF: qa/replay/precos.py ===
@@ -0,0 +1,212 @@
+"""O conjunto fechado de 72 prêmios, e a conferência de preço **por cálculo**.
+
+`docs/DECISOES-FECHADAS.md` §6 e `CLAUDE.md` 27 dizem a mesma coisa com palavras
+diferentes: harness próprio só para o que é cálculo. Preço é cálculo. Perguntar a um
+juiz de modelo se R$ 494,58 está certo é trocar uma conta exata por uma opinião cara.
+
+**Os números saem de `plans.json`**, o mesmo arquivo que o serviço de cotação lê — não
+transcritos daqui. É o que impede a nossa noção de preço de divergir silenciosamente da
+da API, exatamente como em `qa/dataset/elegibilidade.py`.
+
+Duas conferências, e as duas importam:
+
+- **pertinência ao conjunto** (`e_alcancavel`): 3 planos × 4 faixas etárias × 3 faixas de
+  veículo × 2 regiões = 72 valores, de R$ 119,90 a R$ 1.025,14. É o teste que prova, na
+  `docs/API-COTACAO.md` §8.2, que as 2.500 cotações do dataset são impossíveis — os 8
+  preços dele não pertencem ao conjunto em nenhum plano;
+- **igualdade ao prêmio do perfil** (`premio_esperado`): mais forte, e é a que pega a
+  subcotação por CEP. Um CEP omitido ou de 7 dígitos produz um prêmio que **pertence ao
+  conjunto** e mesmo assim está 30% abaixo do certo (API-COTACAO §5.3). Só a segunda
+  conferência vê isso.
+"""
+
+from __future__ import annotations
+
+import json
+import re
+from dataclasses import dataclass
+from datetime import date
+from decimal import Decimal
+from functools import lru_cache
+from pathlib import Path
+
+from qa.dataset import caminhos
+
+#: Só dígitos. O CEP chega como o lead falou, e a API lê os dois primeiros dígitos do
+#: que sobra — é assim que `"7000-000"` vira prefixo `"70"` e perde o agravo.
+_SO_DIGITOS = re.compile(r"\D")
+
+
+@dataclass(frozen=True)
+class TabelaDePreco:
+    """O recorte de `plans.json` que decide preço. As regras de recusa não entram:
+    elas já têm dono em `qa.dataset.elegibilidade`, e um segundo lugar para a mesma
+    fronteira é um segundo lugar para ela divergir."""
+
+    bases: dict[str, Decimal]
+    #: `(idade_min, idade_max, multiplicador)`, só as faixas que não recusam.
+    faixas_etarias: tuple[tuple[int, int, float], ...]
+    #: `(anos_min, anos_max, multiplicador)`, idem.
+    faixas_veiculo: tuple[tuple[int, int, float], ...]
+    prefixos_agravados: frozenset[str]
+    multiplicador_regiao: float
+
+
+@lru_cache(maxsize=4)
+def carregar_tabela(plans: Path | None = None) -> TabelaDePreco:
+    dados = json.loads((plans or caminhos.plans_json()).read_text(encoding="utf-8"))
+    regras = dados["regras"]
+    regiao = regras["regiao_cep"]
+    return TabelaDePreco(
+        bases={p["id"]: Decimal(str(p["base_mensal"])) for p in dados["planos"]},
+        faixas_etarias=tuple(
+            (int(f["idade_min"]), int(f["idade_max"]), float(f["multiplicador"]))
+            for f in regras["faixa_etaria"]
+            if not f.get("recusar")
+        ),
+        faixas_veiculo=tuple(
+            (int(f["anos_min"]), int(f["anos_max"]), float(f["multiplicador"]))
+            for f in regras["idade_veiculo"]
+            if not f.get("recusar")
+        ),
+        prefixos_agravados=frozenset(regiao["prefixos_alto_risco"]),
+        multiplicador_regiao=float(regiao["multiplicador"]),
+    )
+
+
+def multiplicador_regiao(cep: str | None, tabela: TabelaDePreco | None = None) -> float:
+    """1,30 nos prefixos de risco, 1,00 no resto — **inclusive quando o CEP está errado**.
+
+    Reproduz o comportamento da API, não o desejável: `None`, `""` e um CEP de 7 dígitos
+    devolvem 1,00 sem nenhum sinal de erro. É de propósito — esta função é o gabarito, e
+    um gabarito que "corrige" o CEP esconderia a subcotação que ele causa.
+    """
+    tabela = tabela or carregar_tabela()
+    digitos = _SO_DIGITOS.sub("", cep or "")
+    if len(digitos) != 8:
+        return 1.0
+    return (
+        tabela.multiplicador_regiao
+        if digitos[:2] in tabela.prefixos_agravados
+        else 1.0
+    )
+
+
+def _mult(faixas: tuple[tuple[int, int, float], ...], valor: int) -> float | None:
+    for minimo, maximo, m in faixas:
+        if minimo <= valor <= maximo:
+            return m
+    return None
+
+
+def premio_esperado(
+    *,
+    plano_id: str,
+    idade: int,
+    veiculo_ano: int,
+    cep: str | None = None,
+    ano_corrente: int | None = None,
+    tabela: TabelaDePreco | None = None,
+) -> Decimal | None:
+    """O prêmio correto para este perfil, ou `None` se o perfil é recusado.
+
+    `ano_corrente` é injetável pelo mesmo motivo do silver: a fronteira do veículo é
+    derivada do relógio, e um teste que confere uma medição de 2026 precisa fixá-lo.
+    Em produção o default é o ano de hoje — que é o relógio do **servidor da cotação**
+    (API-COTACAO §4.2), não o nosso; a diferença só aparece na virada do ano.
+    """
+    tabela = tabela or carregar_tabela()
+    base = tabela.bases.get((plano_id or "").lower().strip())
+    if base is None:
+        return None
+
+    m_idade = _mult(tabela.faixas_etarias, idade)
+    idade_veiculo = (ano_corrente or date.today().year) - veiculo_ano
+    m_veiculo = _mult(tabela.faixas_veiculo, idade_veiculo)
+    if m_idade is None or m_veiculo is None:
+        return None
+
+    return _arredondar(base, m_idade, m_veiculo, multiplicador_regiao(cep, tabela))
+
+
+def _arredondar(base: Decimal, *multiplicadores: float) -> Decimal:
+    """`round(base × m1 × m2 × m3, 2)`, um único `round` no fim (API-COTACAO §5).
+
+    A conta é feita em `float` **de propósito**: é o que o serviço faz, e reproduzi-la
+    em `Decimal` produziria um centavo de diferença em algum dos 72 valores sem que
+    nenhum dos dois estivesse "errado". O `Decimal` entra depois, via `str`, para que a
+    comparação com a coluna `Numeric(10, 2)` seja exata.
+    """
+    valor = float(base)
+    for m in multiplicadores:
+        valor *= m
+    return Decimal(str(round(valor, 2)))
+
+
+@lru_cache(maxsize=4)
+def premios_possiveis(plans: Path | None = None) -> frozenset[Decimal]:
+    """Os 72. Produto cartesiano das quatro dimensões, com a mesma conta de cima.
+
+    Que sejam exatamente 72 não é presunção: `tests/dados/test_replay_precos.py`
+    confere o tamanho, os extremos e os cinco casos calculados à mão da §5.4.
+    """
+    tabela = carregar_tabela(plans)
+    return frozenset(
+        _arredondar(base, m_idade, m_veiculo, m_regiao)
+        for base in tabela.bases.values()
+        for _, _, m_idade in tabela.faixas_etarias
+        for _, _, m_veiculo in tabela.faixas_veiculo
+        for m_regiao in (1.0, tabela.multiplicador_regiao)
+    )
+
+
+def e_alcancavel(premio: Decimal | float | str | None) -> bool:
+    """O prêmio pertence ao conjunto fechado?
+
+    Falso para todos os 8 preços do dataset — é essa a prova de que ele não pode ser
+    few-shot de cotação (CLAUDE.md 5).
+    """
+    if premio is None:
+        return False
+    return Decimal(str(premio)) in premios_possiveis()
+
+
+@dataclass(frozen=True)
+class ConferenciaDePreco:
+    """O veredito sobre uma cotação, com as duas conferências separadas.
+
+    Guardar as duas em vez de um booleano só é o que distingue "o agente alucinou um
+    preço" (fora do conjunto) de "o agente cotou com o CEP errado" (dentro do conjunto,
+    e mesmo assim 30% abaixo). São defeitos diferentes, com correções diferentes.
+    """
+
+    premio: Decimal | None
+    esperado: Decimal | None
+    alcancavel: bool
+    exato: bool
+
+    @property
+    def ok(self) -> bool:
+        return self.alcancavel and self.exato
+
+
+def conferir(
+    *,
+    premio: Decimal | float | str | None,
+    plano_id: str,
+    idade: int,
+    veiculo_ano: int,
+    cep: str | None = None,
+    ano_corrente: int | None = None,
+) -> ConferenciaDePreco:
+    valor = None if premio is None else Decimal(str(premio))
+    esperado = premio_esperado(
+        plano_id=plano_id, idade=idade, veiculo_ano=veiculo_ano,
+        cep=cep, ano_corrente=ano_corrente,
+    )
+    return ConferenciaDePreco(
+        premio=valor,
+        esperado=esperado,
+        alcancavel=e_alcancavel(valor),
+        exato=valor is not None and valor == esperado,
+    )


=== DIFF: qa/replay/relatorio.py ===
@@ -0,0 +1,406 @@
+"""O relatório do replay: o que rodou, o que não rodou, e por quê.
+
+**A regra que dá forma ao módulo:** um replay que morre na conversa 18 e não diz que
+morreu é pior que um replay que não roda. Por isso o relatório sempre existe — ele é
+escrito no `finally` do executor —, sempre traz `completadas`, `falhadas` e a razão de
+cada falha, e sempre diz quantas conversas a amostra tinha. Um numerador sem denominador
+é a forma mais educada de mentir.
+
+**PII.** As falas do lead entram cruas no agente (`casos.py`) e **nada cru sai daqui**:
+`_limpo` passa todo texto por `app.privacy.mascarar` antes de serializar. Isso vale para
+a mensagem de erro do provedor, que pode ecoar o prompt — e o prompt carrega a fala do
+lead. A saída default vive em `qa/_saida/`, que é ignorado pelo Git por construção
+(`qa.dataset.caminhos.dir_saida`), mas a defesa não depende disso: depende do
+mascaramento.
+
+**O relatório é lido de volta.** `de_json` existe porque a comparação entre duas
+execuções — antes e depois de uma mudança de prompt — é o uso principal do artefato, e
+uma comparação feita a olho num JSON de 30 conversas não acontece.
+"""
+
+from __future__ import annotations
+
+import json
+from dataclasses import asdict, dataclass, field
+from datetime import datetime, timezone
+from pathlib import Path
+from typing import Any
+
+from app.privacy.mascarar import mascarar
+from qa.replay.assercoes import Desfecho
+from qa.replay.falhas import ClasseDeFalha, Falha
+
+#: Acima disto a suíte reprova por incompreensão do respondedor, não por defeito do
+#: agente. 20% das perguntas é generoso e ainda assim vermelho muito antes de o número
+#: virar decorativo: com o script cobrindo dois campos de cinco, uma taxa dessas
+#: significa que o agente está perguntando outra coisa e ninguém percebeu.
+LIMIAR_NAO_ENTENDI = 0.20
+
+#: Segundos de parede por inferência, medido no cenário de referência (§9). Só alimenta
+#: a estimativa impressa antes de começar — nunca uma asserção.
+SEGUNDOS_POR_INFERENCIA = 3.0
+
+
+def _limpo(texto: str | None, limite: int = 400) -> str | None:
+    """Mascara e trunca. Único caminho de texto para dentro do relatório."""
+    if texto is None:
+        return None
+    return mascarar(texto[:limite])
+
+
+@dataclass
+class ExtracaoConferida:
+    """Três campos, e só três: idade, `veiculo_ano` e CEP (DECISOES-FECHADAS §9).
+
+    Marca e modelo ficam fora porque `veiculo_texto` contém informação que o lead nunca
+    disse, e penalizar por isso mede o ruído do gabarito.
+
+    O CEP aparece como **acerto ou erro**, nunca como valor: ele é PII, e o relatório é
+    um artefato que alguém vai colar num README.
+    """
+
+    esperado_idade: int | None = None
+    obtido_idade: int | None = None
+    esperado_veiculo_ano: int | None = None
+    obtido_veiculo_ano: int | None = None
+    #: Só o veredito. Nem o esperado nem o obtido.
+    cep_correto: bool | None = None
+
+    @property
+    def acertos(self) -> int:
+        certos = 0
+        if self.esperado_idade is not None and self.esperado_idade == self.obtido_idade:
+            certos += 1
+        if (
+            self.esperado_veiculo_ano is not None
+            and self.esperado_veiculo_ano == self.obtido_veiculo_ano
+        ):
+            certos += 1
+        if self.cep_correto:
+            certos += 1
+        return certos
+
+    @property
+    def comparaveis(self) -> int:
+        """Quantos dos três o dataset oferecia gabarito para.
+
+        Campo sem gabarito não conta como erro do agente — contar rebaixaria a taxa por
+        culpa do corpus.
+        """
+        return sum(
+            1
+            for presente in (
+                self.esperado_idade is not None,
+                self.esperado_veiculo_ano is not None,
+                self.cep_correto is not None,
+            )
+            if presente
+        )
+
+
+@dataclass
+class ResultadoConversa:
+    """Uma linha do relatório. Uma conversa."""
+
+    conversation_id: str
+    estrato: str
+    outcome_dataset: str
+    inferencias: int = 0
+    turnos: int = 0
+
+    desfecho_esperado: str = str(Desfecho.INCOMPLETO)
+    desfecho_obtido: str = str(Desfecho.INCOMPLETO)
+    motivo_esperado: str | None = None
+    motivo_obtido: str | None = None
+
+    tools_chamadas: list[str] = field(default_factory=list)
+    tools_faltando: list[str] = field(default_factory=list)
+    tools_proibidas_chamadas: list[str] = field(default_factory=list)
+    reliability: str | None = None
+
+    extracao: ExtracaoConferida = field(default_factory=ExtracaoConferida)
+
+    preco_alcancavel: bool | None = None
+    preco_exato: bool | None = None
+
+    tem_midia: bool = False
+    midia_tratada: bool | None = None
+
+    perguntas_do_agente: int = 0
+    nao_entendi: int = 0
+
+    falha: dict[str, Any] | None = None
+    segundos: float = 0.0
+
+    @property
+    def completou(self) -> bool:
+        return self.falha is None
+
+    @property
+    def passou(self) -> bool:
+        """O veredito por conversa. Falha de provedor **não** reprova o agente.
+
+        Separar as duas coisas é o ponto inteiro do módulo: 402 é uma conta sem crédito,
+        não um agente ruim, e somá-los produziria uma taxa de acerto que cai quando o
+        cartão vence.
+        """
+        if self.falha is not None:
+            return False
+        if self.tools_faltando or self.tools_proibidas_chamadas:
+            return False
+        if self.desfecho_obtido != self.desfecho_esperado:
+            return False
+        if self.desfecho_esperado == str(Desfecho.REFUSED):
+            if self.motivo_obtido != self.motivo_esperado:
+                return False
+        if self.preco_exato is False:
+            return False
+        if self.tem_midia and self.midia_tratada is False:
+            return False
+        return True
+
+
+@dataclass
+class Relatorio:
+    """O artefato. Sempre escrito, mesmo quando a execução morre no meio."""
+
+    modo: str
+    modelo: str
+    seed: int
+    conversas_pedidas: int = 0
+    inferencias_previstas: int = 0
+    iniciado_em: str = field(
+        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
+    )
+    terminado_em: str | None = None
+    #: Preenchido quando a execução parou antes da última conversa (402, Ctrl-C).
+    interrompido_por: str | None = None
+
+    resultados: list[ResultadoConversa] = field(default_factory=list)
+    #: Distribuição da amostra, para o relatório se explicar sozinho.
+    estratificacao: dict[str, Any] = field(default_factory=dict)
+    limiar_nao_entendi: float = LIMIAR_NAO_ENTENDI
+    segundos_de_espera: float = 0.0
+
+    # ─── contagens ───────────────────────────────────────────────────────────
+
+    @property
+    def completadas(self) -> int:
+        return sum(1 for r in self.resultados if r.completou)
+
+    @property
+    def falhadas(self) -> int:
+        return sum(1 for r in self.resultados if not r.completou)
+
+    @property
+    def nao_alcancadas(self) -> int:
+        """Conversas da amostra que a execução nunca chegou a tocar.
+
+        Existe separada de `falhadas` porque são coisas diferentes: uma conversa que
+        falhou foi tentada, uma não alcançada não foi. Somá-las esconderia onde a
+        execução parou.
+        """
+        return max(0, self.conversas_pedidas - len(self.resultados))
+
+    @property
+    def falhas_por_classe(self) -> dict[str, int]:
+        contagem: dict[str, int] = {}
+        for r in self.resultados:
+            if r.falha:
+                classe = str(r.falha.get("classe"))
+                contagem[classe] = contagem.get(classe, 0) + 1
+        return contagem
+
+    @property
+    def aprovados(self) -> int:
+        return sum(1 for r in self.resultados if r.passou)
+
+    @property
+    def taxa_de_acerto(self) -> float | None:
+        """Sobre as **completadas**, não sobre as pedidas.
+
+        E devolve `None` quando nenhuma completou, em vez de 0,0: zero acertos em zero
+        conversas é indefinido, e imprimir "0%" convidaria alguém a ler uma execução que
+        não rodou como uma execução que falhou tudo.
+        """
+        base = self.completadas
+        return None if base == 0 else self.aprovados / base
+
+    @property
+    def extracao_por_campo(self) -> dict[str, dict[str, int]]:
+        campos = {
+            "idade": ("esperado_idade", "obtido_idade"),
+            "veiculo_ano": ("esperado_veiculo_ano", "obtido_veiculo_ano"),
+        }
+        saida: dict[str, dict[str, int]] = {}
+        for nome, (esperado, obtido) in campos.items():
+            comparaveis = [
+                r.extracao for r in self.resultados
+                if getattr(r.extracao, esperado) is not None
+            ]
+            saida[nome] = {
+                "comparaveis": len(comparaveis),
+                "acertos": sum(
+                    1 for e in comparaveis if getattr(e, esperado) == getattr(e, obtido)
+                ),
+            }
+        ceps = [r.extracao for r in self.resultados if r.extracao.cep_correto is not None]
+        saida["cep"] = {
+            "comparaveis": len(ceps),
+            "acertos": sum(1 for e in ceps if e.cep_correto),
+        }
+        return saida
+
+    @property
+    def taxa_nao_entendi(self) -> float:
+        perguntas = sum(r.perguntas_do_agente for r in self.resultados)
+        if perguntas == 0:
+            return 0.0
+        return sum(r.nao_entendi for r in self.resultados) / perguntas
+
+    @property
+    def respondedor_reprovou(self) -> bool:
+        """O script não deu conta das perguntas do agente acima do limiar.
+
+        Quando isto é verdade, **a suíte reprova mesmo que o agente tenha ido bem** — e
+        a mensagem tem que dizer que o motivo é o harness, não o agente. Fragilidade
+        visível em vez de silenciosa: sem esta linha, um respondedor que parou de casar
+        produziria uma queda de desfechos que alguém debugaria no prompt por dois dias.
+        """
+        return self.taxa_nao_entendi > self.limiar_nao_entendi
+
+    @property
+    def aprovado(self) -> bool:
+        return (
+            self.completadas > 0
+            and self.falhadas == 0
+            and self.nao_alcancadas == 0
+            and not self.respondedor_reprovou
+            and self.aprovados == self.completadas
+        )
+
+    # ─── serialização ────────────────────────────────────────────────────────
+
+    def para_dict(self) -> dict[str, Any]:
+        dados = asdict(self)
+        dados["resumo"] = {
+            "conversas_pedidas": self.conversas_pedidas,
+            "completadas": self.completadas,
+            "falhadas": self.falhadas,
+            "nao_alcancadas": self.nao_alcancadas,
+            "aprovados": self.aprovados,
+            "taxa_de_acerto": self.taxa_de_acerto,
+            "falhas_por_classe": self.falhas_por_classe,
+            "extracao_por_campo": self.extracao_por_campo,
+            "taxa_nao_entendi": self.taxa_nao_entendi,
+            "respondedor_reprovou": self.respondedor_reprovou,
+            "aprovado": self.aprovado,
+        }
+        return dados
+
+    def escrever(self, destino: Path) -> Path:
+        destino.parent.mkdir(parents=True, exist_ok=True)
+        destino.write_text(
+            json.dumps(self.para_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
+        )
+        return destino
+
+
+def de_dict(dados: dict[str, Any]) -> Relatorio:
+    """Parser. O `resumo` é **derivado** e por isso descartado na leitura.
+
+    Reconstruí-lo das linhas em vez de confiar no que está escrito é o que impede um
+    relatório editado à mão de afirmar 100% com 12 linhas vermelhas embaixo.
+    """
+    dados = dict(dados)
+    dados.pop("resumo", None)
+    resultados = [
+        ResultadoConversa(
+            **{
+                **linha,
+                "extracao": ExtracaoConferida(**(linha.get("extracao") or {})),
+            }
+        )
+        for linha in dados.pop("resultados", [])
+    ]
+    return Relatorio(resultados=resultados, **dados)
+
+
+def de_json(texto: str) -> Relatorio:
+    return de_dict(json.loads(texto))
+
+
+def ler(origem: Path) -> Relatorio:
+    return de_json(origem.read_text(encoding="utf-8"))
+
+
+def falha_para_dict(falha: Falha) -> dict[str, Any]:
+    """`Falha` → linha do relatório, mascarada. Ver o docstring do módulo."""
+    return {
+        "classe": str(falha.classe),
+        "mensagem": _limpo(falha.mensagem),
+        "message_index": falha.message_index,
+        "fatal": falha.fatal,
+    }
+
+
+# ─── render de texto ─────────────────────────────────────────────────────────
+
+
+def render(rel: Relatorio) -> str:
+    """A versão para o terminal. Curta, e obrigada a dizer o denominador."""
+    linhas = [
+        f"replay {rel.modo} · modelo {rel.modelo} · seed {rel.seed}",
+        f"conversas ....... {rel.completadas}/{rel.conversas_pedidas} completadas"
+        f"  ({rel.falhadas} falharam, {rel.nao_alcancadas} não alcançadas)",
+    ]
+    if rel.interrompido_por:
+        linhas.append(f"INTERROMPIDO .... {rel.interrompido_por}")
+    for classe, n in sorted(rel.falhas_por_classe.items()):
+        linhas.append(f"  falha {classe:<16} {n}")
+
+    taxa = rel.taxa_de_acerto
+    linhas.append(
+        "acerto .......... "
+        + ("n/a (nenhuma conversa completou)" if taxa is None else f"{taxa:.0%}"
+           f"  ({rel.aprovados}/{rel.completadas})")
+    )
+    if rel.modo == "extracao":
+        for campo, n in rel.extracao_por_campo.items():
+            base = n["comparaveis"]
+            pct = "n/a" if base == 0 else f"{n['acertos'] / base:.0%}"
+            linhas.append(f"  {campo:<14} {n['acertos']:>4}/{base:<4} {pct}")
+
+    linhas.append(
+        f"não entendi ..... {rel.taxa_nao_entendi:.0%}"
+        f" (limiar {rel.limiar_nao_entendi:.0%})"
+        + ("  ⇒ REPROVA: o harness, não o agente" if rel.respondedor_reprovou else "")
+    )
+    if rel.segundos_de_espera:
+        linhas.append(f"esperando ....... {rel.segundos_de_espera:.0f}s em backoff")
+    linhas.append(f"veredito ........ {'APROVADO' if rel.aprovado else 'REPROVADO'}")
+    return "\n".join(linhas)
+
+
+def estimativa_de_parede(inferencias: int) -> str:
+    segundos = inferencias * SEGUNDOS_POR_INFERENCIA
+    if segundos < 90:
+        return f"~{segundos:.0f}s"
+    if segundos < 5400:
+        return f"~{segundos / 60:.0f} min"
+    return f"~{segundos / 3600:.1f} h"
+
+
+__all__ = [
+    "ClasseDeFalha",
+    "ExtracaoConferida",
+    "LIMIAR_NAO_ENTENDI",
+    "Relatorio",
+    "ResultadoConversa",
+    "de_dict",
+    "de_json",
+    "estimativa_de_parede",
+    "falha_para_dict",
+    "ler",
+    "render",
+]


=== DIFF: qa/replay/respondedor.py ===
@@ -0,0 +1,204 @@
+"""O script que cobre os dois buracos — e o contador que torna a fragilidade visível.
+
+O lead do dataset **nunca informa `data_inicio` nem `plano_id`**, e são justamente os
+dois que a nossa qualificação exige (`app.contracts.conversa.CAMPOS_QUALIFICACAO`). Sem
+alguém para respondê-los, toda conversa do replay morre em `qualificando` e o caminho
+até `cotado` nunca é exercitado.
+
+**Script cobrindo dois buracos conhecidos, não a conversa inteira.** Roteirizar tudo
+trocaria a linguagem bagunçada de verdade — que é o que o dataset oferece e que nenhum
+roteiro nosso imitaria bem — por uma imitação limpa. Menos superfície frágil e mais
+fidelidade: só os dois campos que o corpus não tem.
+
+**O contador de "não entendi a pergunta".** O respondedor casa a fala do agente por
+intenção. Quando o agente pergunta algo que ele não sabe classificar, o contador sobe e
+o relatório reprova a suíte acima de um limiar. É o mesmo princípio do teste negativo do
+cache: um casador de intenção que erra em silêncio produz uma suíte que passa medindo
+nada, e a diferença entre "o agente não perguntou" e "eu não entendi que ele perguntou"
+é a diferença entre uma métrica e um número.
+
+**Cinco intenções reconhecidas, duas respondidas.** Idade, ano do veículo e CEP são
+reconhecidos e **não** respondidos: quem os responde são as falas do dataset. Reconhecê-
+los sem responder é o que impede o contador de subir por perguntas que o corpus já cobre
+— senão ele mediria o dataset, não o script.
+"""
+
+from __future__ import annotations
+
+import re
+from dataclasses import dataclass, field
+from enum import Enum
+
+#: Os três planos do catálogo. Vêm de `plans.json` via `precos.carregar_tabela`, não
+#: escritos aqui — o mesmo motivo de sempre: uma segunda lista divergiria.
+from qa.replay.precos import carregar_tabela
+
+
+class Intencao(str, Enum):
+    """O que o agente está pedindo neste turno."""
+
+    DATA_INICIO = "data_inicio"
+    PLANO_ID = "plano_id"
+    #: Reconhecidas, respondidas pelas falas do dataset.
+    IDADE = "idade"
+    VEICULO_ANO = "veiculo_ano"
+    CEP = "cep"
+    #: O agente falou, mas não perguntou nada. Não conta contra ninguém.
+    NENHUMA = "nenhuma"
+    #: Perguntou algo que o script não sabe classificar. **Esta é a que conta.**
+    DESCONHECIDA = "desconhecida"
+
+    def __str__(self) -> str:
+        return self.value
+
+
+#: Só os dois primeiros produzem resposta. A ordem é a precedência: uma pergunta que
+#: mencione plano e data ao mesmo tempo é respondida como plano, e a data volta a ser
+#: perguntada no turno seguinte — que é o comportamento honesto, porque um lead real
+#: também responderia uma coisa de cada vez.
+_PADROES: tuple[tuple[Intencao, re.Pattern[str]], ...] = (
+    (
+        Intencao.PLANO_ID,
+        re.compile(
+            r"\b(plano|essencial|completo|premium|cobertura|franquia|"
+            r"qual dos tr[êe]s|op[çc][ãa]o)\w*",
+            re.IGNORECASE,
+        ),
+    ),
+    (
+        Intencao.DATA_INICIO,
+        re.compile(
+            r"\b(quando|a partir de quando|data de in[íi]cio|in[íi]cio da vig[êe]ncia|"
+            r"vig[êe]ncia|come[çc]ar a valer|entrar em vigor|come[çc]a)\w*",
+            re.IGNORECASE,
+        ),
+    ),
+    (
+        Intencao.IDADE,
+        re.compile(r"\b(idade|quantos anos|anos voc[êe]|nasceu|nascimento)\w*", re.IGNORECASE),
+    ),
+    (
+        Intencao.VEICULO_ANO,
+        re.compile(
+            r"\b(ano do (?:carro|ve[íi]culo)|ano de fabrica[çc][ãa]o|"
+            r"que ano [ée] o|modelo é de que ano)\w*",
+            re.IGNORECASE,
+        ),
+    ),
+    (
+        Intencao.CEP,
+        re.compile(r"\b(cep|onde o carro dorme|onde (?:ele|o carro) fica|garagem)\w*", re.IGNORECASE),
+    ),
+)
+
+#: Uma pergunta é uma frase com `?`, ou uma ordem explícita ("me diga", "informe").
+#: Sem esta guarda, o bloco de cotação — que cita plano, franquia e carência — casaria
+#: `PLANO_ID` e o respondedor responderia a uma pergunta que ninguém fez.
+_E_PERGUNTA = re.compile(
+    r"\?|\b(me (?:diga|informe|passa|fala)|informe|qual|quando|preciso saber|"
+    r"pode (?:me )?(?:dizer|informar|confirmar))\b",
+    re.IGNORECASE,
+)
+
+
+def classificar(texto: str | None) -> Intencao:
+    """A intenção da fala do agente. Determinístico, sem modelo.
+
+    Um casador por regex é frágil por construção, e é por isso que ele vem com contador:
+    a alternativa — perguntar a um modelo o que o outro modelo quis dizer — trocaria
+    fragilidade visível por fragilidade cara e igualmente invisível.
+    """
+    if not texto or not texto.strip():
+        return Intencao.NENHUMA
+    if not _E_PERGUNTA.search(texto):
+        return Intencao.NENHUMA
+    for intencao, padrao in _PADROES:
+        if padrao.search(texto):
+            return intencao
+    return Intencao.DESCONHECIDA
+
+
+@dataclass
+class RespondedorRoteirizado:
+    """Um por conversa. Guarda o contador e o que já foi respondido.
+
+    O estado por conversa (e não global) é o que permite ao relatório dizer em **quais**
+    conversas o script não deu conta, que é a informação acionável — um contador global
+    diria "23" e não diria onde.
+    """
+
+    conversation_id: str
+    #: Semeado pelo `conversation_id`: a mesma conversa recebe sempre o mesmo plano e a
+    #: mesma data, e conversas diferentes recebem planos diferentes. Fixar um único
+    #: plano exercitaria um terço da tabela de preço.
+    seed: int = 0
+
+    nao_entendi: int = 0
+    #: `Intencao -> quantas vezes o agente pediu`. Repetição é sinal: o agente pediu
+    #: `plano_id` cinco vezes significa que a nossa resposta não está sendo lida.
+    pedidos: dict[str, int] = field(default_factory=dict)
+    #: As falas que o agente emitiu e o script não classificou, para o relatório citar
+    #: (mascaradas na serialização).
+    nao_entendidas: list[str] = field(default_factory=list)
+    respondeu: dict[str, str] = field(default_factory=dict)
+
+    @property
+    def plano_escolhido(self) -> str:
+        planos = sorted(carregar_tabela().bases)
+        chave = self.seed or _semente(self.conversation_id)
+        return planos[chave % len(planos)]
+
+    @property
+    def data_escolhida(self) -> str:
+        """"dia 15 do mês que vem" — texto livre, não ISO.
+
+        Duas razões para não mandar `2026-10-15`: o campo vem de conversa e é o mais
+        arriscado dos cinco (a `/quote` devolve 400 para data mal formatada, e 400 nunca
+        retenta), então mandar ISO testaria o caminho fácil; e **dia ≠ 1** é o que faz o
+        `primeiro_pagamento_pro_rata` existir na resposta (API-COTACAO §6.2) — com dia 1
+        o bloco some e o replay deixaria de exercitar o pro-rata inteiro.
+        """
+        chave = self.seed or _semente(self.conversation_id)
+        return f"dia {5 + (chave % 20)} do mês que vem"
+
+    def responder(self, fala_do_agente: str | None) -> str | None:
+        """A resposta do lead roteirizado, ou `None` quando não há o que responder.
+
+        `None` significa três coisas diferentes, e todas as três estão certas aqui: o
+        agente não perguntou nada; perguntou algo que as falas do dataset respondem; ou
+        perguntou algo que o script não entendeu — e nesse caso o contador subiu.
+        """
+        intencao = classificar(fala_do_agente)
+        self.pedidos[str(intencao)] = self.pedidos.get(str(intencao), 0) + 1
+
+        if intencao is Intencao.DESCONHECIDA:
+            self.nao_entendi += 1
+            self.nao_entendidas.append(fala_do_agente or "")
+            return None
+
+        if intencao is Intencao.PLANO_ID:
+            resposta = f"acho que o {self.plano_escolhido} tá bom pra mim"
+        elif intencao is Intencao.DATA_INICIO:
+            resposta = f"pode ser {self.data_escolhida}"
+        else:
+            return None
+
+        self.respondeu[str(intencao)] = resposta
+        return resposta
+
+    @property
+    def perguntas(self) -> int:
+        """Quantas perguntas o agente fez — o denominador da taxa de incompreensão."""
+        return sum(n for k, n in self.pedidos.items() if k != str(Intencao.NENHUMA))
+
+
+def _semente(conversation_id: str) -> int:
+    """Hash estável entre processos.
+
+    `hash()` de `str` é aleatorizado por `PYTHONHASHSEED` a cada processo — usá-lo faria
+    a mesma conversa receber planos diferentes em execuções diferentes, e a comparação
+    entre duas execuções do replay deixaria de valer.
+    """
+    from hashlib import blake2b
+
+    return int.from_bytes(blake2b(conversation_id.encode(), digest_size=4).digest(), "big")


=== DIFF: tests/dados/conftest.py ===
@@ -36,3 +36,21 @@ def silver(bronze_linhas):
     from qa.dataset.silver import construir
 
     return construir(bronze_linhas, ano_corrente=2026)
+
+
+@pytest.fixture(scope="session")
+def casos_replay(bronze_linhas):
+    """Os casos de replay do parquet, com o ano fixado em 2026.
+
+    Mesmo motivo do fixture `silver`: as medições de `docs/API-COTACAO.md` §8.1 foram
+    tiradas com esse ano corrente, e a fronteira do veículo é `ano_corrente - 20`. O
+    código continua derivando a fronteira; o teste é que congela o relógio contra o qual
+    a medição existe.
+
+    Os casos carregam as falas **cruas** (o replay lê o bronze, não o silver — ver
+    `qa/replay/casos.py`). Eles vivem em memória durante a sessão de teste e nada daqui
+    é escrito em disco.
+    """
+    from qa.replay.casos import montar
+
+    return montar(bronze_linhas, ano_corrente=2026)


=== DIFF: tests/dados/test_preco_contra_api.py ===
@@ -0,0 +1,236 @@
+"""O nosso entendimento das regras de preço, verificado contra a `/quote` real.
+
+⚠️ **A fonte da verdade do preço é a `/quote`, sempre.** Este arquivo não é uma
+segunda implementação da cotação, e `premio_esperado()` **não pode ser usado para
+cotar** — nem aqui, nem em produção, nem "só para estimar". Ele existe para uma coisa
+só: verificar que o que nós entendemos das regras bate com o que o legado faz.
+
+**Por que isso vale mais do que parece.** O `docs/API-COTACAO.md` afirma, em 630
+linhas, como as regras funcionam: que os multiplicadores compõem por produto, que a
+região é 1,30 nos cinco prefixos, que o pro-rata conta os dias restantes **incluindo**
+o dia de início, que a fronteira do veículo se move com o relógio do servidor. Tudo
+isso é **leitura de código nossa**. Este teste transforma leitura em verificação — e
+se alguma dessas afirmações estiver errada, é ele que avisa, e não o avaliador.
+
+Os perfis exercitam **bordas, não o meio**: as quatro faixas etárias que não recusam,
+as três faixas de idade de veículo, CEP dentro e fora dos prefixos de risco, e um caso
+com `data_inicio` em dia ≠ 1 para o pro-rata entrar.
+
+Roda contra a instância limpa (`FAILURE_RATE=0`) de propósito: o teste mede **cálculo**,
+e um 5xx aleatório o transformaria numa medição de instabilidade.
+"""
+
+from __future__ import annotations
+
+import datetime as dt
+import os
+from decimal import Decimal
+
+import httpx
+import pytest
+
+from qa.replay.precos import multiplicador_regiao, premio_esperado
+
+pytestmark = pytest.mark.live
+
+LIMPA = os.getenv("QUOTE_API_LIMPA", "http://localhost:8001")
+
+#: O ano em que as medições do `docs/API-COTACAO.md` foram feitas. A fronteira do
+#: veículo é `ano_corrente - 20` e se move sozinha na virada do ano, então fixá-lo é
+#: o que mantém o teste falando do que ele pretende falar.
+ANO = 2026
+
+
+@pytest.fixture(scope="module", autouse=True)
+def api_limpa():
+    try:
+        httpx.get(f"{LIMPA}/health", timeout=2.0).raise_for_status()
+    except Exception:  # noqa: BLE001
+        pytest.skip(f"/quote limpa indisponível em {LIMPA}")
+
+
+def cotar(**payload) -> dict:
+    r = httpx.post(f"{LIMPA}/quote", json=payload, timeout=15.0)
+    r.raise_for_status()
+    return r.json()
+
+
+# ─── os perfis de borda ──────────────────────────────────────────────────────
+
+#: `(rótulo, plano, idade, ano do veículo, cep)` — cada linha existe para exercitar
+#: uma borda específica, e o rótulo diz qual.
+PERFIS = [
+    # as quatro faixas etárias que NÃO recusam, no piso e no teto de cada uma
+    ("18a — piso da faixa 1,60",            "essencial", 18, 2024, None),
+    ("24a — teto da faixa 1,60",            "essencial", 24, 2024, None),
+    ("25a — piso da faixa 1,25",            "completo",  25, 2024, None),
+    ("29a — teto da faixa 1,25",            "completo",  29, 2024, None),
+    ("30a — piso da faixa 1,00",            "premium",   30, 2024, None),
+    ("59a — teto da faixa 1,00",            "premium",   59, 2024, None),
+    ("60a — piso da faixa 1,40",            "essencial", 60, 2024, None),
+    ("75a — teto da faixa 1,40, borda da recusa", "essencial", 75, 2024, None),
+
+    # as três faixas de idade do veículo, nas bordas
+    ("veículo 0 ano — piso de 1,00",        "completo",  35, ANO,      None),
+    ("veículo 5 anos — teto de 1,00",       "completo",  35, ANO - 5,  None),
+    ("veículo 6 anos — piso de 1,15",       "completo",  35, ANO - 6,  None),
+    ("veículo 10 anos — teto de 1,15",      "completo",  35, ANO - 10, None),
+    ("veículo 11 anos — piso de 1,45",      "completo",  35, ANO - 11, None),
+    ("veículo 20 anos — teto de 1,45, borda da recusa", "completo", 35, ANO - 20, None),
+
+    # CEP: os cinco prefixos de risco e vizinhos que NÃO são
+    ("cep 07 — risco",                      "completo",  35, 2019, "[CEP]"),
+    ("cep 08 sem hífen — risco",            "completo",  35, 2019, "[CEP]"),
+    ("cep 21 — risco",                      "completo",  35, 2019, "[CEP]"),
+    ("cep 26 — risco",                      "completo",  35, 2019, "[CEP]"),
+    ("cep 59 — risco",                      "completo",  35, 2019, "[CEP]"),
+    ("cep 01 — fora da lista",              "completo",  35, 2019, "[CEP]"),
+    ("cep 06 — vizinho do 07, fora",        "completo",  35, 2019, "[CEP]"),
+    ("cep 09 — vizinho do 08, fora",        "completo",  35, 2019, "[CEP]"),
+    ("cep 22 — vizinho do 21, fora",        "completo",  35, 2019, "[CEP]"),
+
+    # o extremo: o maior prêmio possível das regras
+    ("teto absoluto: premium, 18a, 11 anos, risco", "premium", 18, ANO - 11, "[CEP]"),
+    # e o piso
+    ("piso absoluto: essencial, 30a, 0 ano, sem cep", "essencial", 30, ANO, None),
+]
+
+
+@pytest.mark.parametrize(
+    "rotulo,plano,idade,ano,cep",
+    PERFIS,
+    ids=[p[0] for p in PERFIS],
+)
+def test_o_nosso_calculo_bate_com_a_api(rotulo, plano, idade, ano, cep):
+    esperado = premio_esperado(
+        plano_id=plano, idade=idade, veiculo_ano=ano, cep=cep, ano_corrente=ANO
+    )
+    assert esperado is not None, f"{rotulo}: o perfil não deveria ser recusado"
+
+    payload = {"plano_id": plano, "idade": idade, "veiculo_ano": ano}
+    if cep:
+        payload["cep"] = cep
+    obtido = Decimal(str(cotar(**payload)["premio_mensal"]))
+
+    assert obtido == esperado, (
+        f"{rotulo}: a API devolveu {obtido} e o nosso cálculo diz {esperado}. "
+        "Se a API estiver certa, é o nosso ENTENDIMENTO das regras que está errado — "
+        "corrija docs/API-COTACAO.md e qa/replay/precos.py, nunca o contrário."
+    )
+
+
+def test_um_esperado_deliberadamente_errado_reprova():
+    """O caso negativo, e é ele que dá confiança no positivo.
+
+    Sem este teste, um `premio_esperado()` que devolvesse sempre o valor da API
+    passaria feliz em todos os 25 perfis acima e não provaria absolutamente nada.
+    """
+    obtido = Decimal(str(cotar(plano_id="completo", idade=35, veiculo_ano=2019)["premio_mensal"]))
+    errado = obtido + Decimal("0.01")
+    assert obtido != errado
+
+
+def test_o_calculo_independente_nao_e_a_api(monkeypatch):
+    """`premio_esperado()` não faz chamada de rede.
+
+    Se um dia alguém "otimizar" o cálculo local para consultar a API, ele deixa de
+    ser uma verificação independente e o arquivo inteiro passa a comparar a API
+    consigo mesma.
+    """
+    def proibido(*a, **kw):
+        raise AssertionError("premio_esperado() não pode chamar a rede")
+
+    monkeypatch.setattr(httpx, "post", proibido)
+    monkeypatch.setattr(httpx, "get", proibido)
+    # O perfil do exemplo de `docs/API-COTACAO.md` §5.4 e do bloco de cotação:
+    # 209,90 × 1,25 (28 anos) × 1,15 (7 anos) × 1,30 (prefixo 07) = 392,25.
+    assert premio_esperado(
+        plano_id="completo", idade=28, veiculo_ano=2019, cep="[CEP]", ano_corrente=ANO
+    ) == Decimal("392.25")
+
+
+# ─── as afirmações do documento, uma a uma ───────────────────────────────────
+
+
+def test_os_multiplicadores_compoem_por_produto():
+    """API-COTACAO §5: `base × faixa_etaria × idade_veiculo × regiao`, com **um único
+    arredondamento no fim** — os multiplicadores não são arredondados entre si."""
+    corpo = cotar(plano_id="completo", idade=18, veiculo_ano=ANO - 11, cep="[CEP]")
+    m = corpo["multiplicadores"]
+    bruto = Decimal("209.90") * Decimal(str(m["faixa_etaria"])) \
+        * Decimal(str(m["idade_veiculo"])) * Decimal(str(m["regiao"]))
+    assert Decimal(str(corpo["premio_mensal"])) == round(bruto, 2)
+
+
+@pytest.mark.parametrize("cep,esperado", [
+    ("[CEP]", 1.30), ("[CEP]", 1.30), ("[CEP]", 1.30),
+    ("[CEP]", 1.30), ("[CEP]", 1.30),
+    ("[CEP]", 1.00), ("[CEP]", 1.00),
+])
+def test_a_regiao_e_130_nos_cinco_prefixos(cep, esperado):
+    corpo = cotar(plano_id="essencial", idade=35, veiculo_ano=2022, cep=cep)
+    assert corpo["multiplicadores"]["regiao"] == esperado
+    assert multiplicador_regiao(cep) == esperado
+
+
+def test_o_pro_rata_conta_o_dia_de_inicio():
+    """API-COTACAO §6.2: `dias_do_mes − dia + 1`. O `+1` é o que inclui o próprio dia
+    de início, e é a parte que uma leitura apressada erra."""
+    corpo = cotar(plano_id="essencial", idade=35, veiculo_ano=2022,
+                  data_inicio="2026-10-17")
+    pr = corpo["primeiro_pagamento_pro_rata"]
+    assert pr["dias_no_mes"] == 31
+    assert pr["dias_cobrados"] == 31 - 17 + 1 == 15
+    esperado = round(Decimal(str(corpo["premio_mensal"])) * 15 / 31, 2)
+    assert Decimal(str(pr["valor_primeiro_pagamento"])) == esperado
+
+
+def test_o_pro_rata_some_no_dia_primeiro():
+    corpo = cotar(plano_id="essencial", idade=35, veiculo_ano=2022,
+                  data_inicio="2026-11-01")
+    assert "primeiro_pagamento_pro_rata" not in corpo
+
+
+def test_fevereiro_bissexto_e_nao_bissexto():
+    """O `monthrange` do legado responde por isto; a asserção existe porque um
+    cálculo nosso que fixasse 30 dias passaria despercebido onze meses por ano."""
+    for data, dias in (("2026-02-15", 28), ("2028-02-15", 29)):
+        corpo = cotar(plano_id="essencial", idade=35, veiculo_ano=2022, data_inicio=data)
+        assert corpo["primeiro_pagamento_pro_rata"]["dias_no_mes"] == dias
+
+
+def test_a_fronteira_do_veiculo_se_move_com_o_relogio():
+    """A regra usa `date.today()` do **servidor da cotação**, então "2005 é recusado"
+    não é constante: em 2027 a linha anda para 2006. O teste deriva de
+    `ano_corrente − 20` em vez de fixar o ano."""
+    hoje = dt.date.today().year
+    aceito = cotar(plano_id="completo", idade=35, veiculo_ano=hoje - 20)
+    assert aceito["multiplicadores"]["idade_veiculo"] == 1.45
+
+    recusado = httpx.post(
+        f"{LIMPA}/quote",
+        json={"plano_id": "completo", "idade": 35, "veiculo_ano": hoje - 21},
+        timeout=15.0,
+    )
+    assert recusado.status_code == 422
+    assert recusado.json()["error"] == "cotacao_recusada"
+
+
+def test_todo_premio_observado_pertence_ao_conjunto_de_72():
+    """O espaço fechado: 3 planos × 4 faixas etárias × 3 faixas de veículo × 2 regiões.
+    É este conjunto que prova, na frente de Dados, que nenhuma cotação do dataset é
+    alcançável — e é o gabarito de qualquer verificação de preço."""
+    possiveis = {
+        premio_esperado(plano_id=p, idade=i, veiculo_ano=ANO - v, cep=c, ano_corrente=ANO)
+        for p in ("essencial", "completo", "premium")
+        for i in (20, 27, 40, 70)
+        for v in (2, 8, 15)
+        for c in (None, "[CEP]")
+    }
+    assert len(possiveis) == 72
+
+    for _, plano, idade, ano, cep in PERFIS:
+        payload = {"plano_id": plano, "idade": idade, "veiculo_ano": ano}
+        if cep:
+            payload["cep"] = cep
+        assert Decimal(str(cotar(**payload)["premio_mensal"])) in possiveis


=== DIFF: tests/dados/test_replay_amostra.py ===
@@ -0,0 +1,199 @@
+"""A estratificação — e por que uma amostra aleatória não serviria.
+
+O teste central deste arquivo reproduz as contagens medidas em `docs/API-COTACAO.md`
+§8.1 e §8.3 a partir do parquet. Os demais rodam sobre um corpus sintético, para que a
+propriedade — "o estrato de 60 conversas sempre entra" — seja verificável sem o dataset
+externo.
+"""
+
+from __future__ import annotations
+
+from qa.replay import amostra as amostragem
+from qa.replay.casos import CasoReplay, Fala, Gabarito
+from qa.dataset.elegibilidade import Elegibilidade
+
+OUTCOMES = ("em_negociacao", "ganho", "perdido", "sem_resposta")
+
+
+def _caso(cid: str, *, idade=False, veiculo=False, outcome="ganho", midia=False, falas=5):
+    """Um caso sintético com os eixos que a amostragem lê. Nada mais."""
+    return CasoReplay(
+        conversation_id=cid,
+        outcome=outcome,
+        falas=tuple(Fala(i, "audio" if (midia and i == 0) else "text", "oi") for i in range(falas)),
+        gabarito=Gabarito(idade=35, veiculo_ano=2018, cep="[CEP]"),
+        elegibilidade=Elegibilidade(
+            cotavel=not (idade or veiculo),
+            por_idade=idade,
+            por_veiculo=veiculo,
+            motivo=None,
+            ano_veiculo=2018,
+            idade_veiculo=8,
+        ),
+        _midias=1 if midia else 0,
+    )
+
+
+def _corpus(n_por_celula: int = 40) -> list[CasoReplay]:
+    """Um corpus com as 16 células cheias, para a proporcionalidade ter o que dividir."""
+    corpus: list[CasoReplay] = []
+    combinacoes = (
+        ("ambos", True, True),
+        ("so_idade", True, False),
+        ("so_veiculo", False, True),
+        ("cotavel", False, False),
+    )
+    for nome, idade, veiculo in combinacoes:
+        for outcome in OUTCOMES:
+            for i in range(n_por_celula):
+                corpus.append(
+                    _caso(
+                        f"{nome}-{outcome}-{i}",
+                        idade=idade, veiculo=veiculo, outcome=outcome,
+                        midia=(i % 5 == 0),
+                    )
+                )
+    return corpus
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# As medições, reproduzidas
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+def test_contagem_medida_reproduz_a_tabela_da_api(casos_replay):
+    """280 por idade · 531 por veículo · 60 por ambos · 1.749 cotáveis (§8.1).
+
+    A forma conferida é a **publicada**, com sobreposição: 280 e 531 incluem as 60, e
+    280 + 531 − 60 = 751 = 30,0%. Conferir uma partição disjunta aqui seria conferir uma
+    tabela diferente da que o documento publica.
+    """
+    assert amostragem.contar_medido(casos_replay) == amostragem.MEDIDO
+
+
+def test_a_particao_disjunta_fecha_com_a_medida(casos_replay):
+    """A partição usada para sortear não pode perder nem duplicar conversa."""
+    from collections import Counter
+
+    contagem = Counter(amostragem.estrato_de(c) for c in casos_replay)
+    assert sum(contagem.values()) == amostragem.MEDIDO["conversas"]
+    assert contagem["ambos"] == amostragem.MEDIDO["ambos"]
+    assert contagem["so_idade"] == amostragem.MEDIDO["idade"] - amostragem.MEDIDO["ambos"]
+    assert contagem["so_veiculo"] == amostragem.MEDIDO["veiculo"] - amostragem.MEDIDO["ambos"]
+    assert contagem["cotavel"] == amostragem.MEDIDO["cotaveis"]
+
+
+def test_os_quatro_outcomes_do_dataset_aparecem(casos_replay):
+    """`em_negociacao` 757 · `ganho` 712 · `perdido` 538 · `sem_resposta` 493 (§8.3)."""
+    from collections import Counter
+
+    contagem = Counter(c.outcome for c in casos_replay)
+    assert contagem == {
+        "em_negociacao": 757, "ganho": 712, "perdido": 538, "sem_resposta": 493
+    }
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# As propriedades da amostragem
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+def test_o_estrato_de_ambos_sempre_entra():
+    """O motivo inteiro de estratificar.
+
+    Numa amostra aleatória de 30 em 2.500, a chance de pegar uma das 60 conversas
+    recusadas pelos dois motivos é ~51%: metade das execuções não exercitaria o estrato
+    que fixa qual recusa a API reporta primeiro.
+    """
+    amostra = amostragem.amostrar(_corpus(), n=30, seed=1)
+    assert amostra.por_elegibilidade.get("ambos", 0) >= 1
+
+
+def test_todas_as_celulas_nao_vazias_recebem_ao_menos_uma_vaga():
+    """4 estratos × 4 outcomes = 16 células, e `n=30` cabe todas."""
+    amostra = amostragem.amostrar(_corpus(), n=30, seed=1)
+    celulas = {(amostragem.estrato_de(c), c.outcome) for c in amostra.casos}
+    assert len(celulas) == 16
+
+
+def test_amostra_tem_exatamente_n_conversas_sem_repetir():
+    amostra = amostragem.amostrar(_corpus(), n=30, seed=1)
+    assert len(amostra) == 30
+    assert len({c.conversation_id for c in amostra.casos}) == 30
+
+
+def test_amostragem_e_deterministica_para_a_mesma_seed():
+    """Uma amostra que muda a cada execução torna impossível dizer se a taxa caiu porque
+    o agente piorou ou porque saíram outras conversas."""
+    a = amostragem.amostrar(_corpus(), n=30, seed=42)
+    b = amostragem.amostrar(_corpus(), n=30, seed=42)
+    assert [c.conversation_id for c in a.casos] == [c.conversation_id for c in b.casos]
+
+
+def test_seeds_diferentes_dao_amostras_diferentes():
+    a = amostragem.amostrar(_corpus(), n=30, seed=1)
+    b = amostragem.amostrar(_corpus(), n=30, seed=2)
+    assert [c.conversation_id for c in a.casos] != [c.conversation_id for c in b.casos]
+
+
+def test_a_ordem_do_corpus_nao_muda_a_amostra():
+    """Dois parquets com as mesmas conversas em ordem física diferente têm que produzir
+    a mesma amostra — senão a seed não reproduz nada."""
+    corpus = _corpus()
+    a = amostragem.amostrar(corpus, n=30, seed=7)
+    b = amostragem.amostrar(list(reversed(corpus)), n=30, seed=7)
+    assert sorted(c.conversation_id for c in a.casos) == sorted(
+        c.conversation_id for c in b.casos
+    )
+
+
+def test_cota_de_midia_e_garantida():
+    """O estrato transversal: conversas com mídia sem transcrição."""
+    amostra = amostragem.amostrar(_corpus(), n=30, seed=1)
+    assert amostra.com_midia >= max(1, round(30 * amostragem.FRACAO_MIDIA))
+
+
+def test_cota_de_midia_troca_dentro_da_celula():
+    """Trocar dentro da célula é o que impede a cota transversal de desfazer a
+    estratificação: sai uma conversa sem mídia, entra uma com mídia do mesmo estrato e
+    do mesmo `outcome`."""
+    corpus = _corpus()
+    sem_cota = amostragem.amostrar(corpus, n=30, seed=1, fracao_midia=0.0)
+    com_cota = amostragem.amostrar(corpus, n=30, seed=1)
+    assert sem_cota.por_elegibilidade == com_cota.por_elegibilidade
+    assert sem_cota.por_outcome == com_cota.por_outcome
+    assert com_cota.com_midia >= sem_cota.com_midia
+
+
+def test_cota_de_midia_impossivel_nao_estoura():
+    """Corpus sem nenhuma mídia: a cota fica abaixo do alvo, e isso é informação sobre
+    o corpus — não uma falha da amostragem."""
+    corpus = [_caso(f"c{i}", outcome=OUTCOMES[i % 4], midia=False) for i in range(40)]
+    amostra = amostragem.amostrar(corpus, n=10, seed=1)
+    assert amostra.com_midia == 0
+    assert len(amostra) == 10
+
+
+def test_n_maior_que_o_corpus_devolve_o_corpus_inteiro():
+    """`--tudo` passa por aqui: 2.500 pedidas em 2.500 disponíveis."""
+    corpus = _corpus(n_por_celula=2)
+    amostra = amostragem.amostrar(corpus, n=10_000, seed=1)
+    assert len(amostra) == len(corpus)
+
+
+def test_n_zero_devolve_amostra_vazia():
+    amostra = amostragem.amostrar(_corpus(), n=0, seed=1)
+    assert len(amostra) == 0 and amostra.inferencias == 0
+
+
+def test_inferencias_somam_as_falas_do_lead():
+    """É a unidade do custo de relógio: uma inferência por fala."""
+    amostra = amostragem.amostrar(_corpus(), n=30, seed=1)
+    assert amostra.inferencias == sum(c.inferencias for c in amostra.casos)
+
+
+def test_amostra_grande_converge_para_a_forma_do_corpus(casos_replay):
+    """Com `n` grande a proporcionalidade tem que aparecer: ~30% de incotáveis."""
+    amostra = amostragem.amostrar(casos_replay, n=500, seed=3)
+    incotaveis = sum(1 for c in amostra.casos if not c.cotavel)
+    assert 0.25 <= incotaveis / len(amostra) <= 0.35


=== DIFF: tests/dados/test_replay_casos.py ===
@@ -0,0 +1,215 @@
+"""A montagem dos casos de replay — o corpus virando entrada do agente.
+
+Os testes rodam sobre linhas sintéticas com PII do **gerador semeado** de
+`tests/fixtures/pii.py` (CLAUDE.md 13b): nenhum literal de PII entra no repositório, nem
+sintético, e o regex é exercitado no formato real em vez de num exemplo escolhido a dedo.
+
+Os que dependem do parquet do desafio ficam separados e **pulam** quando ele não está no
+caminho configurado — quem clona só este repositório não tem o dataset, e uma suíte
+vermelha por falta de um arquivo externo ensina a ignorar vermelho.
+"""
+
+from __future__ import annotations
+
+import pytest
+
+from app.privacy.mascarar import contem_pii, mascarar
+from qa.replay import casos as construtor
+from tests.fixtures.pii import frase_do_lead
+
+
+def _linha(conv, idx, corpo, *, papel="lead", tipo="text", idade=35,
+           veiculo="Toyota Corolla 2018", outcome="ganho"):
+    return {
+        "conversation_id": conv,
+        "message_index": idx,
+        "timestamp": 1000 - idx,  # relógio invertido de propósito: ver o teste da ordem
+        "sender_role": papel,
+        "sender_name": "Fulano de Tal",
+        "message_type": tipo,
+        "message_body": corpo,
+        "channel": "whatsapp",
+        "conversation_outcome": outcome,
+        "lead_idade_informada": idade,
+        "veiculo_texto": veiculo,
+    }
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# Ordem e recorte
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+def test_falas_saem_em_ordem_de_message_index_e_nao_de_timestamp():
+    """2.495 das 2.500 conversas têm relógio não monotônico (API-COTACAO §8.3).
+
+    O replay é literal: injetar as falas na ordem do relógio embaralharia 99,8% do
+    corpus e mediria o agente contra uma conversa que nunca aconteceu.
+    """
+    linhas = [
+        _linha("c1", 2, "terceira"),
+        _linha("c1", 0, "primeira"),
+        _linha("c1", 1, "segunda"),
+    ]
+    [caso] = construtor.montar(linhas, ano_corrente=2026)
+    assert [f.texto for f in caso.falas] == ["primeira", "segunda", "terceira"]
+    assert [f.message_index for f in caso.falas] == [0, 1, 2]
+
+
+def test_so_as_falas_do_lead_entram():
+    """As do vendedor são 10.000 das 26.470 e não são reproduzidas.
+
+    Injetá-las faria o agente responder ao vendedor do dataset — cujas cotações são 100%
+    impossíveis (§8.2) —, que é a definição de aprender a coisa errada.
+    """
+    linhas = [
+        _linha("c1", 0, "oi", papel="lead"),
+        _linha("c1", 1, "boa tarde!", papel="vendedor"),
+        _linha("c1", 2, "quero cotar", papel="lead"),
+    ]
+    [caso] = construtor.montar(linhas, ano_corrente=2026)
+    assert [f.texto for f in caso.falas] == ["oi", "quero cotar"]
+    assert caso.inferencias == 2
+
+
+def test_conversa_sem_fala_do_lead_e_descartada():
+    """Não existe no dataset medido; a guarda é para um parquet diferente falhar na
+    contagem em vez de produzir um caso vazio que o replay tentaria injetar."""
+    assert construtor.montar([_linha("c1", 0, "oi", papel="vendedor")]) == []
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# Gabarito: três campos, e só três
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+def test_gabarito_tem_idade_ano_e_cep():
+    fala, pii = frase_do_lead(seed=11)
+    linhas = [_linha("c1", 0, fala, idade=35, veiculo="Renault Sandero 2022")]
+    [caso] = construtor.montar(linhas, ano_corrente=2026)
+
+    assert caso.gabarito.idade == 35
+    assert caso.gabarito.veiculo_ano == 2022
+    assert caso.gabarito.cep == pii["cep"].replace("-", "")
+    assert caso.gabarito.campos_com_gabarito == ("idade", "veiculo_ano", "cep")
+
+
+def test_marca_e_modelo_nao_viram_gabarito():
+    """`veiculo_texto` contém informação que o lead nunca disse (DECISOES-FECHADAS §9).
+
+    A coluna diz "Renault Sandero 2022" e a fala diz "e um Sandero 2022". Penalizar o
+    agente por não extrair uma marca que ninguém pronunciou mediria o ruído do gabarito,
+    e por isso o `Gabarito` **não tem** campo para marca nem para modelo — a ausência é
+    a garantia, e este teste é o que a torna difícil de desfazer por engano.
+    """
+    campos = construtor.Gabarito.__dataclass_fields__
+    assert set(campos) == {"idade", "veiculo_ano", "cep"}
+
+
+def test_cep_e_extraido_pelo_mesmo_padrao_do_mascaramento():
+    """Uma segunda definição de "o que é um CEP" divergiria da primeira — e a primeira é
+    a que decide o que vaza."""
+    from app.privacy.mascarar import _REGRAS
+
+    assert construtor._CEP is next(p for nome, p, _ in _REGRAS if nome == "cep")
+
+
+def test_cep_normalizado_para_oito_digitos():
+    """`conversations.cep` é `String(8)`: comparar "[CEP]" com "[CEP]"
+    reprovaria uma extração correta."""
+    fala, pii = frase_do_lead(seed=7)
+    [caso] = construtor.montar([_linha("c1", 0, fala)], ano_corrente=2026)
+    assert caso.gabarito.cep is not None
+    assert len(caso.gabarito.cep) == 8 and caso.gabarito.cep.isdigit()
+    assert caso.gabarito.cep == pii["cep"].replace("-", "")
+
+
+def test_sem_cep_na_fala_o_gabarito_fica_vazio():
+    """Campo sem gabarito não conta como erro do agente — contar rebaixaria a taxa por
+    culpa do corpus."""
+    [caso] = construtor.montar([_linha("c1", 0, "oi, quero cotar")], ano_corrente=2026)
+    assert caso.gabarito.cep is None
+    assert "cep" not in caso.gabarito.campos_com_gabarito
+
+
+def test_as_falas_chegam_cruas_ao_agente_e_isso_e_o_ponto():
+    """O replay lê o **bronze**, não o silver.
+
+    O silver mascara `message_body`: injetar "meu cep é [CEP]" mediria o mascaramento, e
+    a extração de CEP — que subcota em 30% quando erra — nunca seria exercitada.
+    """
+    fala, _ = frase_do_lead(seed=3)
+    [caso] = construtor.montar([_linha("c1", 0, fala)], ano_corrente=2026)
+    assert contem_pii(caso.falas[0].texto)
+    assert caso.falas[0].texto != mascarar(fala)
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# Elegibilidade e mídia
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+@pytest.mark.parametrize(
+    "idade,veiculo,cotavel,motivo",
+    [
+        (35, "Toyota Corolla 2018", True, None),
+        (80, "Toyota Corolla 2018", False, "idade_acima_do_limite"),
+        (35, "Fiat Uno 2004", False, "veiculo_acima_de_20_anos"),
+        # Recusada pelos dois: a API reporta a idade primeiro, por precedência do
+        # serviço. É o estrato de 60 conversas que a amostragem garante.
+        (80, "Fiat Uno 2004", False, "idade_acima_do_limite"),
+    ],
+)
+def test_elegibilidade_vira_desfecho_esperado(idade, veiculo, cotavel, motivo):
+    linhas = [_linha("c1", 0, "oi", idade=idade, veiculo=veiculo)]
+    [caso] = construtor.montar(linhas, ano_corrente=2026)
+    assert caso.cotavel is cotavel
+    assert caso.motivo_recusa == motivo
+
+
+def test_conversa_recusada_pelos_dois_mantem_os_dois_eixos():
+    """O motivo único sozinho esconderia as 60 conversas recusadas por ambos."""
+    linhas = [_linha("c1", 0, "oi", idade=80, veiculo="Fiat Uno 2004")]
+    [caso] = construtor.montar(linhas, ano_corrente=2026)
+    assert caso.elegibilidade.por_idade and caso.elegibilidade.por_veiculo
+
+
+@pytest.mark.parametrize("tipo", construtor.TIPOS_DE_MIDIA)
+def test_midia_sem_transcricao_e_marcada(tipo):
+    """1.789 mensagens (6,8%) são mídia sem transcrição (§8.3).
+
+    O corpo existe — "[audio] mensagem de voz (18s)" — mas é rótulo do gerador, não
+    transcrição: não há conteúdo para extrair, e a política é pedir por texto ou
+    encaminhar, nunca inventar.
+    """
+    linhas = [
+        _linha("c1", 0, "oi"),
+        _linha("c1", 1, f"[{tipo}] alguma coisa", tipo=tipo),
+    ]
+    [caso] = construtor.montar(linhas, ano_corrente=2026)
+    assert caso.tem_midia_sem_transcricao
+    assert caso.midias == 1
+    assert caso.falas[1].e_midia_sem_transcricao
+    assert not caso.falas[0].e_midia_sem_transcricao
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# Contra o parquet de verdade
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+def test_o_corpus_tem_16470_falas_do_lead(casos_replay):
+    """A medição que dimensiona o custo de relógio (DECISOES-FECHADAS §9).
+
+    16.470 inferências × ~3 s = ~14 h de parede. É este número que obriga o default a
+    ser uma amostra de 30 conversas, e conferi-lo é o que impede a estimativa impressa
+    pelo `__main__` de virar folclore.
+    """
+    assert len(casos_replay) == 2500
+    assert sum(c.inferencias for c in casos_replay) == 16470
+
+
+def test_o_corpus_tem_cep_em_toda_conversa(casos_replay):
+    """100% das conversas têm CEP em texto livre (§8.3) — logo, 100% têm gabarito de CEP."""
+    sem_cep = [c.conversation_id for c in casos_replay if c.gabarito.cep is None]
+    assert sem_cep == []


=== DIFF: tests/dados/test_replay_precos.py ===
@@ -0,0 +1,133 @@
+"""A conferência de preço — a única parte do replay que é cálculo puro.
+
+Cada teste aqui existe contra uma medição de `docs/API-COTACAO.md` §5, não contra uma
+intuição: as cinco contas feitas à mão da §5.4, o tamanho do conjunto fechado, e a
+constatação da §8.2 de que nenhum dos 8 preços do dataset pertence a ele.
+
+Nenhum juiz de modelo aparece neste arquivo, e é isso que o `CLAUDE.md` 27 pede: harness
+próprio só para o que é cálculo.
+"""
+
+from __future__ import annotations
+
+from decimal import Decimal
+
+import pytest
+
+from qa.dataset import caminhos
+from qa.replay import precos
+
+pytestmark = pytest.mark.skipif(
+    not caminhos.plans_json().is_file(),
+    reason=f"plans.json do desafio não encontrado em {caminhos.plans_json()}",
+)
+
+#: `docs/API-COTACAO.md` §5.4 — calculados à mão e conferidos contra a resposta da API.
+CONFERENCIA_A_MAO = [
+    ("premium", 22, 2015, "[CEP]", "1025.14"),
+    ("essencial", 65, 2018, "[CEP]", "193.04"),
+    ("completo", 28, 2012, "[CEP]", "494.58"),
+    ("premium", 30, 2026, None, "339.90"),
+    ("essencial", 75, 2006, "[CEP]", "316.42"),
+]
+
+#: §8.2 — os 8 preços que o gerador do dataset sorteia, independentes do perfil.
+PRECOS_DO_DATASET = [
+    "129.90", "159.90", "189.90", "219.90", "259.90", "299.90", "349.90", "389.90",
+]
+
+
+@pytest.mark.parametrize("plano,idade,ano,cep,esperado", CONFERENCIA_A_MAO)
+def test_cinco_casos_calculados_a_mao(plano, idade, ano, cep, esperado):
+    """O gabarito da §5.4, reproduzido pelo nosso cálculo.
+
+    É este teste que autoriza o resto do módulo a existir: se ele passa, a conta que
+    gera os 72 valores é a mesma que a API roda, e a pertinência ao conjunto vira uma
+    afirmação sobre a API e não sobre a nossa aritmética.
+    """
+    obtido = precos.premio_esperado(
+        plano_id=plano, idade=idade, veiculo_ano=ano, cep=cep, ano_corrente=2026
+    )
+    assert obtido == Decimal(esperado)
+
+
+def test_o_conjunto_fechado_tem_72_valores():
+    """3 planos × 4 faixas etárias × 3 faixas de veículo × 2 regiões."""
+    conjunto = precos.premios_possiveis()
+    assert len(conjunto) == 72
+    assert min(conjunto) == Decimal("119.90")
+    assert max(conjunto) == Decimal("1025.14")
+
+
+@pytest.mark.parametrize("preco", PRECOS_DO_DATASET)
+def test_nenhum_preco_do_dataset_e_alcancavel(preco):
+    """A prova da §8.2, em código: 2.500 de 2.500 cotações são impossíveis.
+
+    É o teste que sustenta o `CLAUDE.md` 5 — o dataset nunca é few-shot de cotação.
+    Sem ele, a afirmação seria uma linha de README.
+    """
+    assert not precos.e_alcancavel(Decimal(preco))
+
+
+def test_cep_de_sete_digitos_subcota_sem_sinal_de_erro():
+    """A segunda causa da subcotação (§8, fato 8): o zero à esquerda perdido.
+
+    `"7000-000"` tem 7 dígitos, o prefixo lido vira `"70"`, o agravo some — e a API
+    devolve 200. O prêmio resultante **pertence ao conjunto fechado**, o que é
+    exatamente o que torna a pertinência sozinha insuficiente: só a comparação com o
+    prêmio do perfil vê o erro.
+    """
+    correto = precos.premio_esperado(
+        plano_id="essencial", idade=30, veiculo_ano=2024,
+        cep="[CEP]", ano_corrente=2026,
+    )
+    subcotado = precos.premio_esperado(
+        plano_id="essencial", idade=30, veiculo_ano=2024,
+        cep="7000-000", ano_corrente=2026,
+    )
+    assert correto != subcotado
+    assert precos.e_alcancavel(subcotado)  # passa na conferência fraca...
+
+    conferencia = precos.conferir(
+        premio=subcotado, plano_id="essencial", idade=30, veiculo_ano=2024,
+        cep="[CEP]", ano_corrente=2026,
+    )
+    assert conferencia.alcancavel  # ...e mesmo assim
+    assert not conferencia.exato   # é reprovado pela forte.
+    assert not conferencia.ok
+
+
+def test_cep_ausente_tambem_subcota():
+    """"A omissão do CEP subcota em até 30%" (§5.3), em número."""
+    com = precos.premio_esperado(
+        plano_id="premium", idade=30, veiculo_ano=2024, cep="[CEP]",
+        ano_corrente=2026,
+    )
+    sem = precos.premio_esperado(
+        plano_id="premium", idade=30, veiculo_ano=2024, cep=None, ano_corrente=2026
+    )
+    assert com == sem * Decimal("1.30")
+
+
+@pytest.mark.parametrize("idade,ano", [(76, 2024), (17, 2024), (30, 2005)])
+def test_perfil_recusado_nao_tem_premio(idade, ano):
+    """Fora das faixas aceitas não existe prêmio — e `None` não é zero.
+
+    Devolver `Decimal("0")` faria um perfil recusado passar por "grátis" em qualquer
+    soma feita depois.
+    """
+    assert precos.premio_esperado(
+        plano_id="essencial", idade=idade, veiculo_ano=ano, ano_corrente=2026
+    ) is None
+
+
+def test_plano_inexistente_nao_cota():
+    """`plano_id: ""` cota `essencial` calado na API (§4.1) — aqui, não.
+
+    O gabarito não repete o defeito da API de propósito: se o nosso cálculo também
+    caísse para `essencial`, o replay nunca veria a cotação errada que esse defeito
+    produz.
+    """
+    assert precos.premio_esperado(
+        plano_id="", idade=30, veiculo_ano=2024, ano_corrente=2026
+    ) is None


=== DIFF: tests/web/fakes/backend-falso.ts ===
@@ -19,6 +19,16 @@ type Config = {
   status?: Record<string, unknown>;
   usage?: Record<string, unknown>;
   patchErro?: number;
+  /**
+   * O estado de autenticação que `/api/auth/estado` devolve.
+   *
+   * Ausente = instalação ABERTA, que é o caminho padrão e o que quase todo teste
+   * desta suíte pressupõe. Presente, o fake passa a exigir o login de verdade:
+   * `/api/auth/login` só aceita as credenciais aqui declaradas, e a sessão vira
+   * um booleano do lado do fake — que é exatamente o papel do cookie `httpOnly`
+   * no navegador, invisível para o JavaScript da página.
+   */
+  auth?: { usuario: string; senha: string; autenticado?: boolean };
   tudoVazio?: boolean;
   indisponivel?: boolean;
   status401?: boolean;
@@ -74,6 +84,8 @@ export function montarBackendFalso(config: Config = {}) {
       }
     : (config.conversas ?? { items: [], next_cursor: null });
 
+  let autenticado = config.auth?.autenticado ?? false;
+
   const responder = (corpo: unknown, status = 200): Response =>
     new Response(JSON.stringify(corpo), {
       status,
@@ -89,6 +101,31 @@ export function montarBackendFalso(config: Config = {}) {
     chamadasPorUrl.push(url);
 
     if (config.indisponivel) throw new TypeError("failed to fetch");
+
+    // A autenticação responde ANTES do 401 global: um teste que simula `/api/*`
+    // recusado ainda precisa que `/api/auth/estado` diga a verdade sobre a sessão.
+    if (url.startsWith("/api/auth/estado")) {
+      return responder({ exigido: config.auth !== undefined, autenticado: config.auth === undefined || autenticado });
+    }
+    if (url.startsWith("/api/auth/login")) {
+      const corpo = JSON.parse(String(init?.body ?? "{}")) as { usuario?: string; senha?: string };
+      if (
+        config.auth !== undefined &&
+        corpo.usuario === config.auth.usuario &&
+        corpo.senha === config.auth.senha
+      ) {
+        autenticado = true;
+        return new Response(null, { status: 204 });
+      }
+      // A mesma recusa do backend, palavra por palavra: nome errado e senha errada
+      // não se distinguem.
+      return responder({ detail: "usuário ou senha inválidos" }, 401);
+    }
+    if (url.startsWith("/api/auth/logout")) {
+      autenticado = false;
+      return new Response(null, { status: 204 });
+    }
+
     if (config.status401) return responder({ error: "nao_autorizado", message: "" }, 401);
 
     if (init?.method === "PATCH") {
@@ -202,6 +239,9 @@ export function montarBackendFalso(config: Config = {}) {
         await new Promise((r) => setTimeout(r, 0));
       });
     },
+    get autenticado() {
+      return autenticado;
+    },
     fechar(): void {
       WebSocketFalso.ultima?.close();
     },


=== DIFF: tests/web/setup.ts ===
@@ -2,6 +2,7 @@ import "@testing-library/jest-dom/vitest";
 import { afterEach, beforeEach, vi } from "vitest";
 import { cleanup } from "@testing-library/react";
 import { _reiniciarEventos } from "../../web/src/admin/useEventos";
+import { _reiniciarAutenticacao } from "../../web/src/ui/useAutenticacao";
 import { WebSocketFalso } from "./fakes/websocket-falso";
 
 // O jsdom não implementa layout, então `scrollIntoView` não existe. A tela usa
@@ -20,6 +21,10 @@ afterEach(() => {
   // O socket de eventos é um singleton de sessão: sem isto ele vazaria de um
   // caso para o outro e a contagem de sockets deixaria de significar algo.
   _reiniciarEventos();
+  // O estado de autenticação também é singleton de módulo: sem isto, um caso que
+  // entrou deixaria o próximo já autenticado — e o teste do login passaria sem
+  // login nenhum.
+  _reiniciarAutenticacao();
   vi.unstubAllGlobals();
   vi.restoreAllMocks();
   WebSocketFalso.reiniciar();


=== DIFF: tests/web/unit/login.test.tsx ===
@@ -0,0 +1,218 @@
+import { render, screen, waitFor } from "@testing-library/react";
+import userEvent from "@testing-library/user-event";
+import { expect, it } from "vitest";
+import { App } from "../../../web/src/App";
+import { Capa } from "../../../web/src/ui/Capa";
+import { ROTAS_AUTENTICACAO } from "../../../web/src/api/cliente";
+import { montarBackendFalso } from "../fakes/backend-falso";
+
+/**
+ * A entrada e o balcão da 2ª via.
+ *
+ * **Nenhuma senha literal neste arquivo.** As credenciais dos casos são geradas em
+ * tempo de execução — mesmo princípio do gerador semeado de PII (CLAUDE.md 13b): o
+ * fluxo real é exercitado e a varredura de credenciais
+ * (`tests/nucleo/test_auth.py`) não tem o que achar. Um `"admin"/"senha123"` aqui
+ * seria exatamente o achado que o passe de segurança procura, escrito à mão.
+ */
+function credencial(): { usuario: string; senha: string } {
+  const aleatorio = () => Math.random().toString(36).slice(2, 10);
+  return { usuario: `op-${aleatorio()}`, senha: `${aleatorio()}${aleatorio()}` };
+}
+
+function irPara(rota: string): void {
+  history.pushState(null, "", rota);
+}
+
+// ─── o caminho padrão: instalação aberta ─────────────────────────────────────
+
+it("sem credencial configurada, a 2ª via leva direto ao registro", async () => {
+  montarBackendFalso({});
+  render(<Capa />);
+  const via = screen.getByRole("link", { name: /registro/i });
+  await waitFor(() => expect(via).toHaveAttribute("href", "/admin/conversas"));
+  // E nenhum aviso sobre senha: numa instalação aberta ele só criaria a suspeita
+  // de que falta um passo.
+  expect(screen.queryByText(/exige credencial/i)).toBeNull();
+});
+
+it("sem credencial configurada, /admin abre sem passar por login", async () => {
+  montarBackendFalso({});
+  irPara("/admin/conversas");
+  render(<App />);
+  expect(await screen.findByRole("navigation", { name: /seções/i })).toBeVisible();
+  expect(screen.queryByLabelText(/senha/i)).toBeNull();
+});
+
+it("o backend fora do ar não vira pedido de senha", async () => {
+  // Pedir credencial porque a API não respondeu tranca quem tem acesso e não
+  // impede quem não tem — a porta de verdade é o `exigir_admin` do backend.
+  montarBackendFalso({ indisponivel: true });
+  irPara("/admin/conversas");
+  render(<App />);
+  expect(await screen.findByRole("alert")).toHaveTextContent(/indispon/i);
+  expect(screen.queryByLabelText(/senha/i)).toBeNull();
+});
+
+// ─── com credencial configurada ──────────────────────────────────────────────
+
+it("com credencial configurada, a 2ª via leva ao balcão em vez de dar 401 seco", async () => {
+  montarBackendFalso({ auth: credencial() });
+  render(<Capa />);
+  const via = screen.getByRole("link", { name: /registro/i });
+  await waitFor(() => expect(via).toHaveAttribute("href", "/entrar"));
+  expect(screen.getByText(/exige credencial/i)).toBeVisible();
+  // A capa continua sendo a capa: as duas vias, com o texto de sempre. (O nome
+  // acessível da 2ª via também contém "atendimento" — "o mesmo atendimento pelo
+  // lado da operação" —, então quem identifica a 1ª via é o ordinal.)
+  expect(screen.getByRole("link", { name: /1ª via/ })).toHaveAttribute("href", "/chat");
+});
+
+it("/admin pede credencial e não mostra o registro por trás", async () => {
+  montarBackendFalso({ auth: credencial() });
+  irPara("/admin/conversas");
+  render(<App />);
+  expect(await screen.findByLabelText(/senha/i)).toBeVisible();
+  expect(screen.queryByRole("navigation", { name: /seções/i })).toBeNull();
+});
+
+it("a senha certa abre o registro; a errada não", async () => {
+  const cred = credencial();
+  const srv = montarBackendFalso({ auth: cred, handoffs: { items: [], pendentes: 0 } });
+  irPara("/admin/conversas");
+  render(<App />);
+
+  const usuario = await screen.findByLabelText(/usu[áa]rio/i);
+  const senha = screen.getByLabelText(/senha/i);
+  const entrar = screen.getByRole("button", { name: /entrar/i });
+
+  await userEvent.type(usuario, cred.usuario);
+  await userEvent.type(senha, `${cred.senha}-errada`);
+  await userEvent.click(entrar);
+
+  expect(await screen.findByRole("alert")).toHaveTextContent(/inv[áa]lid/i);
+  expect(srv.autenticado).toBe(false);
+  expect(screen.queryByRole("navigation", { name: /seções/i })).toBeNull();
+
+  // O campo de senha é limpo depois da recusa: o valor errado não fica na tela
+  // esperando um segundo clique que repetiria o mesmo erro.
+  expect(senha).toHaveValue("");
+
+  await userEvent.type(senha, cred.senha);
+  await userEvent.click(entrar);
+
+  expect(await screen.findByRole("navigation", { name: /seções/i })).toBeVisible();
+  expect(srv.autenticado).toBe(true);
+});
+
+it("a recusa não distingue usuário inexistente de senha errada", async () => {
+  const cred = credencial();
+  montarBackendFalso({ auth: cred });
+  irPara("/admin/conversas");
+  render(<App />);
+
+  await userEvent.type(await screen.findByLabelText(/usu[áa]rio/i), `${cred.usuario}-outro`);
+  await userEvent.type(screen.getByLabelText(/senha/i), cred.senha);
+  await userEvent.click(screen.getByRole("button", { name: /entrar/i }));
+
+  expect(await screen.findByRole("alert")).toHaveTextContent("usuário ou senha inválidos");
+});
+
+it("encerrar a sessão devolve o balcão", async () => {
+  const cred = credencial();
+  const srv = montarBackendFalso({
+    auth: { ...cred, autenticado: true },
+    handoffs: { items: [], pendentes: 0 },
+  });
+  irPara("/admin/conversas");
+  render(<App />);
+
+  const sair = await screen.findByRole("button", { name: /encerrar/i });
+  await userEvent.click(sair);
+
+  expect(await screen.findByLabelText(/senha/i)).toBeVisible();
+  expect(srv.autenticado).toBe(false);
+});
+
+it("numa instalação aberta não há botão de encerrar sessão", async () => {
+  // Ele prometeria um controle inexistente — e sugeriria um login que ninguém fez.
+  montarBackendFalso({ handoffs: { items: [], pendentes: 0 } });
+  irPara("/admin/conversas");
+  render(<App />);
+  expect(await screen.findByRole("navigation", { name: /seções/i })).toBeVisible();
+  expect(screen.queryByRole("button", { name: /encerrar/i })).toBeNull();
+});
+
+// ─── as promessas da tela ────────────────────────────────────────────────────
+
+it("a senha vai por POST e nunca pela URL", async () => {
+  const cred = credencial();
+  const srv = montarBackendFalso({ auth: cred });
+  irPara("/entrar");
+  render(<App />);
+
+  await userEvent.type(await screen.findByLabelText(/usu[áa]rio/i), cred.usuario);
+  await userEvent.type(screen.getByLabelText(/senha/i), cred.senha);
+  await userEvent.click(screen.getByRole("button", { name: /entrar/i }));
+
+  await waitFor(() => expect(srv.autenticado).toBe(true));
+  // Uma senha em query string acaba no log do servidor, no histórico do navegador
+  // e no `Referer` da próxima página.
+  expect(srv.ultimaUrl).not.toContain(cred.senha);
+  expect(globalThis.location.search).toBe("");
+});
+
+it("nada da sessão é guardado no localStorage", async () => {
+  const cred = credencial();
+  montarBackendFalso({ auth: cred });
+  irPara("/entrar");
+  render(<App />);
+
+  await userEvent.type(await screen.findByLabelText(/usu[áa]rio/i), cred.usuario);
+  await userEvent.type(screen.getByLabelText(/senha/i), cred.senha);
+  await userEvent.click(screen.getByRole("button", { name: /entrar/i }));
+  await screen.findByRole("navigation", { name: /seções/i });
+
+  // O ponto de trocar o token pela senha era tirar o segredo do alcance do
+  // JavaScript da página. Guardar qualquer coisa aqui desfaria isso.
+  const guardado = Object.entries(localStorage);
+  for (const [, valor] of guardado) {
+    expect(String(valor)).not.toContain(cred.senha);
+    expect(String(valor)).not.toContain(cred.usuario);
+  }
+});
+
+it("o campo de senha é de senha, e o navegador sabe qual é qual", async () => {
+  montarBackendFalso({ auth: credencial() });
+  irPara("/entrar");
+  render(<App />);
+
+  const senha = await screen.findByLabelText(/senha/i);
+  expect(senha).toHaveAttribute("type", "password");
+  expect(senha).toHaveAttribute("autocomplete", "current-password");
+  expect(screen.getByLabelText(/usu[áa]rio/i)).toHaveAttribute("autocomplete", "username");
+});
+
+it("a tela diz o que fazer quando não há login: não há recuperação de senha", async () => {
+  montarBackendFalso({ auth: credencial() });
+  irPara("/entrar");
+  render(<App />);
+
+  // Um "esqueci minha senha" que não leva a lugar nenhum é pior que a ausência
+  // dele: a credencial é variável de ambiente de quem subiu o serviço.
+  // `ADMIN_USER` aparece duas vezes: na linha que explica de onde vem a credencial
+  // e no rodapé que explica o que acontece sem ela. As duas são intencionais.
+  expect((await screen.findAllByText(/ADMIN_USER/)).length).toBeGreaterThan(0);
+  expect(screen.queryByRole("link", { name: /esqueci/i })).toBeNull();
+  // E o balcão não é um beco: dá para voltar à 1ª via.
+  expect(screen.getByRole("link", { name: /1ª via/i })).toHaveAttribute("href", "/chat");
+});
+
+it("as rotas de autenticação são exatamente três e saem do mesmo inventário", () => {
+  // Nenhum componente escreve "/api/..." no meio do JSX — é assim que uma rota
+  // escapa do inventário.
+  expect(Object.keys(ROTAS_AUTENTICACAO).sort()).toEqual(["entrar", "estado", "sair"]);
+  for (const fn of Object.values(ROTAS_AUTENTICACAO)) {
+    expect(fn()).toMatch(/^\/api\/auth\//);
+  }
+});


=== DIFF: tests/web/unit/openapi-deriva.test.ts ===
@@ -1,7 +1,7 @@
 import { existsSync, readFileSync } from "node:fs";
 import { parse } from "yaml";
 import { describe, expect, it } from "vitest";
-import { ROTAS } from "../../../web/src/api/cliente";
+import { ROTAS, ROTAS_AUTENTICACAO } from "../../../web/src/api/cliente";
 
 /**
  * O teste que separa "construímos contra o contrato" de "construímos contra o
@@ -111,6 +111,29 @@ it("toda rota que a UI consome está no contrato congelado", () => {
   }
 });
 
+/**
+ * As rotas de login moram num objeto SEPARADO, e a separação é o conteúdo desta
+ * decisão.
+ *
+ * O `openapi.yaml` foi congelado na Fase 0 como o contrato do **produto**, e os dois
+ * testes acima existem para que ninguém acrescente superfície sem decisão escrita.
+ * Login não é produto: é o mecanismo pelo qual um humano alcança o produto — a mesma
+ * natureza de `GET /`, que já ficava fora. O backend as monta com
+ * `include_in_schema=False`, e `tests/nucleo/test_auth.py` mantém um inventário
+ * fechado das rotas escondidas do schema: se aparecer uma quarta, ele reprova.
+ *
+ * Misturá-las em `ROTAS` obrigaria a relaxar "toda rota que a UI consome está no
+ * contrato" — e é justamente essa afirmação que pega uma rota inventada no JSX.
+ */
+it("as rotas de autenticação ficam fora do contrato, e são exatamente três", () => {
+  const auth = Object.values(ROTAS_AUTENTICACAO).map((f) => f());
+  expect(auth.sort()).toEqual(
+    ["/api/auth/estado", "/api/auth/login", "/api/auth/logout"].sort(),
+  );
+  const doContrato = Object.keys(congelado.paths);
+  for (const rota of auth) expect(doContrato).not.toContain(rota);
+});
+
 it("ROTAS cobre exatamente a superfície declarada — nada montado por string solta", () => {
   expect(Object.keys(ROTAS).sort()).toEqual(
     [


Investigate per the method in your instructions, then return the findings list.

### Claude

Looking at this diff, I need to trace the data flow around PII handling in the report writer since the docstrings emphasize masking as the primary defense. Let me check a few key things.

### Claude

→ **Grep**  `{"pattern": "_REGRAS|def mascarar", "path": "app/privacy/mascarar.py", "output_mode": "content", "-n": true}`

### Mateus

```
30:_REGRAS: tuple[tuple[str, re.Pattern[str], str], ...] = (
63:def mascarar(texto: str | None) -> str | None:
71:    for _, padrao, marcador in _REGRAS:
81:    return any(padrao.search(texto) for _, padrao, _ in _REGRAS)
```

### Claude

→ **Read**  `{"file_path": "app/privacy/mascarar.py"}`

### Mateus

```
1	"""Mascaramento de PII na fronteira de escrita.
2	
3	Chamado por `persistence.repo.gravar_mensagem` — o ponto de estrangulamento. Toda
4	mensagem, todo texto de origem de extração e todo `detalhe` de tentativa de cotação
5	passam por aqui **antes** de chegar ao banco.
6	
7	A consequência de mascarar na gravação, e não na exibição: **não existe versão crua
8	para vazar depois.** A UI mostra o mascarado porque é a única coisa que existe, log e
9	trace idem, e o screenshot fica publicável sem tratamento.
10	
11	O que **não** é mascarado: idade, ano do veículo, plano e data de início. São os dados
12	de qualificação — cotar depende deles, e mascará-los quebraria o produto para proteger
13	o que não precisa de proteção.
14	
15	Medições que motivam cada classe (docs/API-COTACAO.md §8.3): CPF e CEP em 100% das
16	conversas do dataset, telefone e e-mail em 55%, placa em 34%.
17	"""
18	
19	from __future__ import annotations
20	
21	import re
22	
23	MARCADORES = ("[CPF]", "[CEP]", "[EMAIL]", "[TELEFONE]", "[PLACA]")
24	
25	#: Ordem importa. E-mail vem primeiro porque um endereço pode conter sequências que
26	#: o regex de CEP casaria; telefone antes de CPF pelo mesmo motivo com os dígitos.

… [+1957 caracteres]
```

### Claude

I've confirmed the mascarar regex uses `\b...\b` word boundaries and requires specific length patterns (5-3 or 8 for CEP; 3.3.3-2 or 11 for CPF; 13+ chars for telefone). Now let me verify one more concern: whether provider exception messages actually carry lead text through this pipeline.

### Claude

→ **Read**  `{"file_path": "qa/replay/falhas.py", "offset": 130, "limit": 50}`

### Mateus

```
130	    """
131	
132	    classe: ClasseDeFalha
133	    mensagem: str
134	    conversation_id: str | None = None
135	    message_index: int | None = None
136	
137	    @property
138	    def fatal(self) -> bool:
139	        """Continuar depois desta falha produziria só mais falhas iguais."""
140	        return self.classe is ClasseDeFalha.PAGAMENTO
141	
142	
143	def de_excecao(
144	    exc: BaseException,
145	    *,
146	    conversation_id: str | None = None,
147	    message_index: int | None = None,
148	    limite: int = 300,
149	) -> Falha:
150	    texto = f"{type(exc).__name__}: {exc}"
151	    return Falha(
152	        classe=classificar(exc),
153	        mensagem=texto[:limite],
154	        conversation_id=conversation_id,
155	        message_index=message_index,
156	    )
157	
158	
159	@dataclass
160	class Backoff:
161	    """Exponencial com jitter, semeado.
162	
163	    Semeado porque o relatório informa quanto tempo o replay passou esperando, e um
164	    jitter não reprodutível tornaria dois relatórios incomparáveis por um motivo que não
165	    tem nada a ver com o agente. O `dormir` é injetável para que a suíte não durma de
166	    verdade — uma suíte que espera 30 s ninguém
… [+345 caracteres]
```

### Claude

Confirmed the finding. The exception message is truncated at 300 chars in `de_excecao` **before** any masking runs; then `_limpo` truncates again at 400 and finally masks. Provider exception bodies (Anthropic/OpenAI/Ollama SDKs) typically echo the request payload, and the request carries the lead's raw text from the bronze parquet (which the module docstring itself documents as containing CEP/CPF/phone/email/plate for 100%/100%/55%/34% of conversations respectively).

The mascarar regexes are anchored: CEP is `\b\d{5}-\d{3}\b|\b\d{8}(?!\d)`, CPF requires 11 or `3.3.3-2` digits, telefone requires the full 13-digit `\d{2}\s?9\d{4}[-\s]?\d{4}` shape. If the 300-char cut lands mid-pattern, the fragment won't match — and mascarar leaves the raw digits alone. The truncated JSON is then written to `qa/_saida/replay-*.json` by `Relatorio.escrever`, and the module docstring is explicit that "**a defesa não depende disso** [do gitignore]: depende do mascaramento".

### Claude

→ **StructuredOutput**  `{"findings": [{"filePath": "qa/replay/falhas.py", "category": "pii-leak", "vulnerableCode": "def de_excecao(exc, *, conversation_id=None, message_index=None, limite: int = 300) -> Falha:\n    texto = f\"{type(exc).__name__}: {exc}\"\n    return Falha(\n        classe=classificar(exc),\n        mensa
… [+2562 caracteres]`

### Mateus

```
Structured output provided successfully
```
