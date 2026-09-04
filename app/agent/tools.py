"""As tools do agente — a fronteira entre o que o modelo decide e o que o sistema
garante.

Os **nomes e as assinaturas são contrato**: as asserções do `ReliabilityEval` da frente
de Dados dependem deles, e mudá-los quebra a avaliação sem quebrar nenhum teste.

    qualify_lead(idade, veiculo_ano, cep, data_inicio, plano_id) -> str
    quote_plan(plano_id, idade, veiculo_ano, cep, data_inicio) -> str   (fatia 3)
    escalate_to_human(trigger, reason, summary) -> str                  (fatia 5)

Padrão **write-back**: a tool registra a decisão; quem executa é o backend. Isso mantém
o comportamento testável e impede o modelo de causar efeito colateral direto.

O contexto confiável — qual conversa, qual sessão de banco — vem do **envelope**, por
closure, nunca dos argumentos que o modelo escreveu.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.contracts.conversa import CAMPOS_QUALIFICACAO, LeadProfile
from app.persistence import repo
from app.privacy.mascarar import mascarar

_MESES = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4, "maio": 5,
    "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10,
    "novembro": 11, "dezembro": 12,
}


class DataAmbigua(ValueError):
    """"semana que vem" não é uma data. Reperguntar é melhor que adivinhar."""


def normalizar_data(bruto: str | dt.date | None, hoje: dt.date | None = None) -> dt.date:
    """Texto livre → ISO.

    É o campo mais arriscado dos cinco: a `/quote` devolve **400** para data mal
    formatada, e 400 nunca retenta. E como a data vem de texto livre — "dia 15 do mês
    que vem", "próxima segunda" — é o erro nosso mais provável (API-COTACAO §7.1).

    Na dúvida levanta `DataAmbigua` em vez de chutar: uma data errada vira uma apólice
    com vigência errada, que é pior que uma pergunta a mais.
    """
    if isinstance(bruto, dt.date):
        d = bruto
    else:
        if not bruto:
            raise DataAmbigua("vazio")
        t = str(bruto).strip().lower()
        hoje = hoje or dt.date.today()
        d = None

        if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", t):
            d = dt.date(int(m[1]), int(m[2]), int(m[3]))
        elif m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", t):
            d = dt.date(int(m[3]), int(m[2]), int(m[1]))
        elif m := re.search(r"dia\s+(\d{1,2})\s*º?\s+de\s+(\w+)", t):
            mes = _MESES.get(m[2])
            if mes:
                ano = hoje.year + (1 if mes < hoje.month else 0)
                d = dt.date(ano, mes, int(m[1]))
        elif m := re.search(r"dia\s+(\d{1,2})\s*º?\s+do\s+m[êe]s\s+que\s+vem", t):
            ano, mes = (hoje.year + 1, 1) if hoje.month == 12 else (hoje.year, hoje.month + 1)
            d = dt.date(ano, mes, int(m[1]))
        elif m := re.fullmatch(r"dia\s+(\d{1,2})", t):
            d = dt.date(hoje.year, hoje.month, int(m[1]))
            if d < hoje:
                ano, mes = (hoje.year + 1, 1) if hoje.month == 12 else (hoje.year, hoje.month + 1)
                d = dt.date(ano, mes, int(m[1]))

        if d is None:
            raise DataAmbigua(f"não consegui ler uma data de {bruto!r}")

    # A API aceita data no passado sem reclamar — a validação tem que ser nossa.
    if d < (hoje or dt.date.today()):
        raise DataAmbigua("data no passado")
    return d


@dataclass
class ContextoDoTurno:
    """Envelope confiável. Nunca preenchido por argumento de tool."""

    sessao: Session
    conversation_id: str
    #: Texto do turno, para guardar a origem de cada campo extraído (mascarado).
    texto_do_lead: str = ""
    #: Write-back: o backend lê daqui depois do turno.
    handoffs: list = field(default_factory=list)


def make_qualify_lead(ctx: ContextoDoTurno) -> Callable[..., str]:
    def qualify_lead(
        idade: int | None = None,
        veiculo_ano: int | None = None,
        cep: str | None = None,
        data_inicio: str | None = None,
        plano_id: str | None = None,
    ) -> str:
        """Registra os dados de qualificação do lead que você já apurou.

        Chame assim que um campo aparecer, mesmo fora de ordem e mesmo que o lead
        mande vários de uma vez. Devolve o que ainda falta.

        Args:
            idade: idade do condutor principal, em anos.
            veiculo_ano: ano de fabricação do veículo, com 4 dígitos.
            cep: CEP de onde o carro dorme, como o lead falou.
            data_inicio: quando a cobertura deve começar, como o lead falou.
            plano_id: essencial, completo ou premium.

        Returns:
            str: o que ainda falta perguntar.
        """
        conv = repo.obter_conversa(ctx.sessao, ctx.conversation_id)
        perfil = _perfil_de(conv)
        rejeitados: list[str] = []

        for campo, valor in (
            ("idade", idade),
            ("veiculo_ano", veiculo_ano),
            ("cep", cep),
            ("plano_id", plano_id.lower().strip() if isinstance(plano_id, str) else plano_id),
        ):
            if valor is None:
                continue
            try:
                # Normaliza pela mesma porta que a QuoteRequest usa: CEP de 7 dígitos
                # vira None, plano fora do conjunto levanta.
                setattr(perfil, campo, _normalizar(campo, valor))
            except (ValidationError, ValueError):
                rejeitados.append(campo)

        if data_inicio is not None:
            try:
                perfil.data_inicio = normalizar_data(data_inicio)
            except (DataAmbigua, ValueError):
                rejeitados.append("data_inicio")

        for campo in CAMPOS_QUALIFICACAO:
            if getattr(perfil, campo) is not None and ctx.texto_do_lead:
                perfil.origem.setdefault(campo, mascarar(ctx.texto_do_lead))

        for campo in rejeitados:
            perfil.tentativas_extracao[campo] = perfil.tentativas_extracao.get(campo, 0) + 1

        _gravar_perfil(ctx, perfil)

        faltam = perfil.campos_faltantes
        if not faltam:
            return "Todos os cinco campos registrados. Pode chamar quote_plan."
        aviso = f" Não consegui ler: {', '.join(rejeitados)}." if rejeitados else ""
        return f"Registrado.{aviso} Ainda falta: {', '.join(faltam)}."

    return qualify_lead


def _normalizar(campo: str, valor):
    """Passa pelo mesmo validador que a `QuoteRequest` usa, para que o perfil nunca
    guarde algo que a API aceitaria errado sem devolver erro."""
    from app.contracts.quote import QuoteRequest

    base = {"plano_id": "essencial", "idade": 30, "veiculo_ano": 2020}
    base[campo] = valor
    r = QuoteRequest(**base)
    if campo == "cep" and r.cep is None:
        # O validador devolve None para CEP fora de 8 dígitos em vez de levantar —
        # é o comportamento certo lá (não subcotar calado) e é aqui que ele vira
        # "campo pendente, repergunte".
        raise ValueError("CEP fora de 8 dígitos")
    return getattr(r, campo)


def _perfil_de(conv) -> LeadProfile:
    return LeadProfile(
        idade=conv.idade, veiculo_ano=conv.veiculo_ano, cep=conv.cep,
        data_inicio=conv.data_inicio, plano_id=conv.plano_id,
    )


def _gravar_perfil(ctx: ContextoDoTurno, perfil: LeadProfile) -> None:
    conv = repo.obter_conversa(ctx.sessao, ctx.conversation_id)
    for campo in CAMPOS_QUALIFICACAO:
        setattr(conv, campo, getattr(perfil, campo))
    if conv.state == "novo":
        conv.state = "qualificando"
    ctx.sessao.flush()
