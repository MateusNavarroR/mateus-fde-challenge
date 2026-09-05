"""Os dois transcripts de `artifacts/` são o **entregável nº 4** do enunciado.

Um artefato gerado uma vez e nunca mais conferido apodrece em silêncio: o código muda,
o texto de espera muda, um limiar muda, e o arquivo continua no repositório afirmando
um comportamento que já não existe. Este arquivo é o que impede isso.

Ele **não** regenera os transcripts — regenerar exige a `/quote` de pé, o modelo vivo e
uns dois minutos de relógio. Ele lê o que está commitado e confere que continua sendo
verdade sobre o código atual: que os textos são os mesmos de `app/textos.py`, que a
sequência de espera respeita os limiares de `Settings`, e que o desfecho gravado é
coerente com o cenário anunciado no cabeçalho.

Quando um destes falha, o conserto é regenerar o artefato com o comando que o próprio
cabeçalho carrega — não editar a asserção.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import textos
from app.config import get_settings

RAIZ = Path(__file__).resolve().parents[2]
FELIZ = RAIZ / "artifacts" / "transcript-feliz.md"
DEGRADADO = RAIZ / "artifacts" / "transcript-degradado.md"

#: `[  +6.0s]  Δ +6.0s  sistema  texto`
LINHA = re.compile(r"^\[\s*([+-][\d.]+)s\]\s+(?:Δ\s*([+-][\d.]+)s)?\s+(\S+)\s+(.*)$")


def _linhas(caminho: Path) -> list[tuple[float, float | None, str, str]]:
    saida = []
    for bruta in caminho.read_text(encoding="utf-8").splitlines():
        m = LINHA.match(bruta)
        if m:
            saida.append((float(m[1]), float(m[2]) if m[2] else None, m[3], m[4]))
    return saida


@pytest.fixture(params=[FELIZ, DEGRADADO], ids=["feliz", "degradado"])
def transcript(request) -> Path:
    if not request.param.exists():
        pytest.fail(
            f"{request.param.relative_to(RAIZ)} não existe. É o entregável nº 4 do "
            "enunciado; gere com `scripts/transcript.py` (o comando está no cabeçalho "
            "do arquivo irmão)."
        )
    return request.param


# ─── o que vale para os dois ─────────────────────────────────────────────────


def test_o_cabecalho_carrega_o_comando_que_reproduz(transcript):
    """Um artefato sem o comando que o gera é uma captura de tela em markdown."""
    texto = transcript.read_text(encoding="utf-8")
    assert "## Como reproduzir" in texto
    assert "docker compose up -d --build --wait" in texto
    assert "scripts/transcript.py --cenario" in texto


def test_nenhum_valor_monetario_sai_sem_cotacao_vinculada(transcript):
    """O guardrail, lido do artefato em vez do banco.

    Toda linha com dinheiro tem de ser do `sistema` — o autor dos textos de template.
    Uma linha do `agente` com `R$` seria o modelo escrevendo preço, que é a coisa que
    o projeto inteiro existe para impedir.
    """
    for _, _, autor, conteudo in _linhas(transcript):
        if re.search(r"R\$\s*[\d.,]+", conteudo):
            assert autor in {"sistema", "lead"}, (
                f"valor monetário numa linha do `{autor}`: {conteudo[:80]!r}"
            )


def test_nenhuma_PII_crua_no_artefato(transcript):
    """`artifacts/` é varrido inteiro pelo portão de segurança (CLAUDE.md 13a).

    A conversa passa um CEP; ele tem de aparecer mascarado, porque é o que fica
    gravado. Se um dia o mascaramento sair do caminho, é aqui que aparece.
    """
    from app.privacy.mascarar import mascarar

    texto = transcript.read_text(encoding="utf-8")
    assert texto == mascarar(texto), "há PII crua no artefato"
    assert "[CEP]" in texto, (
        "o roteiro passa um CEP e ele deveria aparecer mascarado. Sem isto, ou o "
        "roteiro mudou ou o mascaramento parou de acontecer."
    )


# ─── o caminho feliz ─────────────────────────────────────────────────────────


def test_o_feliz_entrega_a_cotacao_e_termina_cotado():
    texto = FELIZ.read_text(encoding="utf-8")
    assert "**Estado final da conversa:** `cotado`" in texto
    assert "Nenhum." in texto.split("### Handoff")[-1], "o feliz não pode ter handoff"


def test_o_feliz_cita_carencia_franquia_e_pro_rata():
    """Os três itens que a decisão 23 obriga no bloco, e que somem com facilidade.

    A carência de 30 dias é a mais fácil de perder: ela vem em 100 % das respostas
    200 e omiti-la é vender cobertura que ainda não vale.
    """
    texto = FELIZ.read_text(encoding="utf-8")
    assert "30 dias" in texto and "Roubo e furto" in texto
    assert "Franquia de R$" in texto
    assert "proporcional" in texto, "o pro-rata do dia 17 tem de aparecer"


def test_o_feliz_nao_avisa_espera_por_uma_cotacao_rapida():
    """O «só um instante» seguido da resposta — decisão 1, e o defeito que o piso
    de `piso_aviso_s` corrigiu. Se voltar, volta aqui."""
    textos_ditos = [c for _, _, _, c in _linhas(FELIZ)]
    assert textos.AVISO_ESPERA not in textos_ditos
    assert textos.REFORCO not in textos_ditos


def test_o_feliz_tem_exatamente_uma_cotacao():
    """Duas linhas em `quotes` para um turno significa que o modelo chamou a tool
    duas vezes — e uma delas fica `pending` para sempre, sujando a tabela que
    responde pelo critério nº 4."""
    corpo = FELIZ.read_text(encoding="utf-8").split("### Cotações")[1]
    ids = re.findall(r"\| `(q_[0-9a-f]+)` \|", corpo.split("####")[0])
    assert len(ids) == 1, f"esperava uma cotação, achei {ids}"
    assert "`pending`" not in corpo


# ─── o caminho degradado ─────────────────────────────────────────────────────


def test_o_degradado_esgota_as_tentativas_e_nao_inventa_preco():
    texto = DEGRADADO.read_text(encoding="utf-8")
    assert "**Estado final da conversa:** `encaminhado`" in texto
    assert "`failed`" in texto
    assert "cotacao_indisponivel" in texto
    assert "disparado por **regra**" in texto

    cfg = get_settings()
    tentativas = re.findall(r"^\| (\d) \| — \(sem resposta\) \| `timeout` \|",
                            texto, re.MULTILINE)
    assert len(tentativas) == cfg.quote_max_attempts, (
        f"o artefato mostra {len(tentativas)} tentativas e a política diz "
        f"{cfg.quote_max_attempts}"
    )
    assert "R$" not in texto.split("## O que ficou gravado")[0], (
        "nenhum valor podia aparecer: nenhuma tentativa devolveu preço"
    )


def test_o_degradado_mostra_aviso_reforco_e_encaminhamento_na_ordem():
    """A sequência que o enunciado chama de «o ponto que mais separa».

    A asserção é sobre a ORDEM e sobre os textos literais de `app/textos.py`: um
    transcript que mostrasse o reforço antes do aviso, ou um texto parafraseado pelo
    modelo, estaria descrevendo outro produto.
    """
    ditos = [(d, c) for _, d, _, c in _linhas(DEGRADADO) if d is not None]
    esperados = [textos.AVISO_ESPERA, textos.REFORCO]

    achados = [(d, c) for d, c in ditos if c in esperados]
    assert [c for _, c in achados] == esperados, (
        f"esperava aviso e depois reforço; achei {[c[:40] for _, c in achados]}"
    )

    encaminhamento = next(d for d, c in ditos if textos.INDISPONIBILIDADE in c)
    assert achados[0][0] < achados[1][0] < encaminhamento


def test_o_degradado_respeita_os_limiares_configurados():
    """Os Δ do artefato contra `Settings`, e não contra números escritos à mão.

    O aviso pode sair DEPOIS do limiar — quem agenda os timers é a tool, e o modelo
    leva alguns segundos para chegar até ela. O que não pode é sair antes: isso
    significaria avisar sobre uma espera que o lead ainda não teve.
    """
    cfg = get_settings()
    ditos = {c: d for _, d, _, c in _linhas(DEGRADADO) if d is not None}

    assert ditos[textos.AVISO_ESPERA] >= cfg.aviso_espera_s - 0.1
    assert ditos[textos.REFORCO] >= cfg.reforco_espera_s - 0.1

    # O pior caso da política: 3 × read timeout, mais backoff, mais o tempo que o
    # modelo levou até a tool. É a aritmética que justifica a cotação ser um job.
    piso = cfg.quote_max_attempts * cfg.quote_read_timeout_s
    encaminhamento = next(d for _, d, _, c in _linhas(DEGRADADO)
                          if d is not None and textos.INDISPONIBILIDADE in c)
    assert encaminhamento >= piso, (
        f"o encaminhamento saiu em {encaminhamento:.1f}s, antes de as "
        f"{cfg.quote_max_attempts} tentativas de {cfg.quote_read_timeout_s}s caberem"
    )


def test_os_textos_do_artefato_sao_os_de_TEXTOS_md():
    """Byte a byte, e é o ponto: o valor do artefato é ser prova, não ilustração.

    Se o texto do aviso mudar em `docs/TEXTOS.md` e o transcript não for regerado, o
    entregável passa a mostrar um produto que não existe mais.
    """
    corpo = DEGRADADO.read_text(encoding="utf-8")
    for nome in ("AVISO_ESPERA", "REFORCO", "INDISPONIBILIDADE", "DESPEDIDA"):
        assert getattr(textos, nome) in corpo, f"{nome} divergiu do artefato"
