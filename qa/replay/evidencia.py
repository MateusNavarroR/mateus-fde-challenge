"""Os transcripts do replay, gravados **ao lado do relatório**.

O problema que isto resolve, em uma frase: *uma execução de avaliação cuja evidência
desaparece ao parar o contêiner não é evidência reproduzível.*

O relatório JSON sobrevivia — ele é um arquivo — mas ele carrega só o veredito por
conversa: desfecho esperado, obtido, tools chamadas. **As mensagens ficavam no banco**,
e o banco é um contêiner. Quando alguém dá `docker compose down -v`, ou quando a suíte
trunca as tabelas para rodar, some justamente o que permite responder *"por que esta
conversa reprovou?"*.

Foi exatamente essa pergunta que expôs o defeito de 36,7%: só olhando as mensagens
gravadas deu para ver «Error code: 400 … Your credit balance is too low …» no lugar da
fala do agente. Sem elas, o número teria sido publicado como se fosse desempenho.

Então a evidência passa a viajar com o relatório: um Markdown por conversa, no mesmo
diretório, legível num diff e sem depender de nada estar de pé.

**Mascarado como tudo o mais.** O conteúdo já vem mascarado do banco — não existe versão
crua do lado do servidor —, mas a passada aqui é de cinto e suspensório: o diretório de
saída é varrido pelo portão de segurança como qualquer artefato.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from app.privacy.mascarar import mascarar


def escrever_transcripts(
    sessao_factory,
    conversation_ids: dict[str, str],
    destino: Path,
    *,
    modelo: str,
) -> int:
    """Um `.md` por conversa em `destino/transcripts/`. Devolve quantos escreveu.

    `conversation_ids` mapeia **id do dataset → id da nossa conversa**, porque é o do
    dataset que o relatório cita e o nosso que o banco conhece. Guardar os dois no
    cabeçalho é o que permite ir do relatório ao transcript sem adivinhação.
    """
    from app.persistence import repo
    from app.persistence.models import Quote, QuoteAttempt

    pasta = destino / "transcripts"
    pasta.mkdir(parents=True, exist_ok=True)
    escritos = 0

    for id_dataset, id_conversa in conversation_ids.items():
        with sessao_factory() as s:
            conv = repo.obter_conversa(s, id_conversa)
            if conv is None:
                continue
            mensagens = repo.mensagens(s, id_conversa)
            cotacoes = s.query(Quote).filter_by(conversation_id=id_conversa).all()

            linhas = [
                f"# {id_dataset}",
                "",
                f"> Replay de `{id_dataset}` contra `{modelo}`.",
                f"> Conversa `{id_conversa}`, estado final **{conv.state}**.",
                f"> Gerado em {dt.datetime.now(dt.UTC).isoformat(timespec='seconds')}.",
                "",
                "## Mensagens",
                "",
                "| # | autor | tipo | status | conteúdo |",
                "|---|---|---|---|---|",
            ]
            for m in mensagens:
                # O pipe quebraria a tabela; a quebra de linha também.
                corpo = mascarar(m.conteudo).replace("|", "\\|").replace("\n", "<br>")
                linhas.append(
                    f"| {m.index} | `{m.autor}` | `{m.tipo}` | `{m.status}` | {corpo} |"
                )

            if cotacoes:
                linhas += ["", "## Cotações", "",
                           "| quote_id | status | prêmio | motivo | outcome |",
                           "|---|---|---|---|---|"]
                for q in cotacoes:
                    premio = f"R$ {q.premio_mensal}" if q.premio_mensal is not None else "—"
                    linhas.append(
                        f"| `{q.id}` | `{q.status}` | {premio} | "
                        f"{q.motivo_recusa or '—'} | `{q.erro_outcome or '—'}` |"
                    )
                    tentativas = (
                        s.query(QuoteAttempt).filter_by(quote_id=q.id)
                        .order_by(QuoteAttempt.attempt).all()
                    )
                    for a in tentativas:
                        linhas.append(
                            f"| ↳ #{a.attempt} | {a.http_status or '— (sem resposta)'} "
                            f"| {a.latency_ms} ms | | `{a.outcome}` |"
                        )
            else:
                linhas += ["", "## Cotações", "",
                           "Nenhuma. O agente não chegou a chamar `quote_plan`."]

        (pasta / f"{id_dataset}.md").write_text("\n".join(linhas) + "\n",
                                                encoding="utf-8")
        escritos += 1

    return escritos
