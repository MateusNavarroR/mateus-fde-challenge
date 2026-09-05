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
from app.contracts.quote import QuoteRequest
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

    #: `text` | `image` | `audio` | `document`. Vem do canal, nunca de argumento de
    #: tool — é o que `MIDIA_SEM_TEXTO` lê, e o modelo não pode escolhê-lo.
    tipo_da_mensagem: str = "text"

    #: `(texto, quote_id) -> None`, **síncrono**. Quem monta o contexto decide como a
    #: mensagem chega ao canal: o console imprime, o web empurra pelo socket. A tool
    #: é síncrona (é o Agno que a chama), então marshalar para o laço de eventos é
    #: responsabilidade de quem constrói — e agendar sem esperar quebraria a ordem
    #: das mensagens no socket.
    enviar: Callable[[str, str | None], None] | None = None

    #: `time.monotonic()` de quando a mensagem do lead chegou. É o **relógio do lead**:
    #: contar do início da tool faria o aviso sair depois de ele já ter esperado 8 s.
    chegada_do_lead: float | None = None

    #: A tool já falou com o lead neste turno ⇒ o texto do modelo é descartado.
    ja_enviou: bool = False

    #: `quote_id` já produzido NESTE turno. Uma segunda chamada a `quote_plan` no
    #: mesmo turno é recusada a partir daqui — ver o guarda em `make_quote_plan`.
    quote_do_turno: str | None = None

    #: Contador que o gatilho de objeção de preço lê. `tentativas_extracao` NÃO mora
    #: aqui: ela conta ao longo da conversa e vem do banco (`repo`), como as mídias e
    #: as violações de guardrail. Um contador de turno reiniciaria a cada mensagem.
    objecoes_de_preco: int = 0


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

        # UMA vez por rejeição. A linha estava duplicada, e o efeito era o gatilho
        # `extracao_falhou` disparar na PRIMEIRA falha — encaminhando por engano um
        # lead que só precisava ser reperguntado.
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
    """Reconstrói o perfil a partir da conversa.

    `tentativas_extracao` entra aqui porque o gatilho `extracao_falhou` conta ao
    longo da CONVERSA, não do turno: sem carregá-lo, o dicionário voltava vazio a
    cada turno e "a segunda falha no mesmo campo" só podia acontecer dentro de um
    turno só — o que é o modelo se atrapalhando, não o lead sendo ilegível.
    """
    return LeadProfile(
        idade=conv.idade, veiculo_ano=conv.veiculo_ano, cep=conv.cep,
        data_inicio=conv.data_inicio, plano_id=conv.plano_id,
        tentativas_extracao=dict(conv.tentativas_extracao or {}),
    )


def _gravar_perfil(ctx: ContextoDoTurno, perfil: LeadProfile) -> None:
    conv = repo.obter_conversa(ctx.sessao, ctx.conversation_id)
    for campo in CAMPOS_QUALIFICACAO:
        setattr(conv, campo, getattr(perfil, campo))
    # Reatribuído, não mutado: o SQLAlchemy não detecta mutação in-place em JSONB.
    conv.tentativas_extracao = dict(perfil.tentativas_extracao)
    if conv.state == "novo":
        conv.state = "qualificando"
    ctx.sessao.flush()


# ─── quote_plan: a fronteira do modelo ───────────────────────────────────────


def make_quote_plan(ctx: ContextoDoTurno) -> Callable[..., str]:
    """`quote_plan` embrulha o **cliente resiliente**, não o HTTP.

    O modelo nunca vê status, tentativa, latência ou estado do breaker: 500, 502, 503,
    timeout, backoff, jitter e semáforo vivem inteiramente abaixo desta fronteira. Um
    modelo exposto a "recebi 503" improvisa, e improvisar aí é a falha que a
    arquitetura existe para impedir.

    Ela devolve **um entre quatro desfechos, sem número nenhum**. Três deles a tool já
    resolveu sozinha — ela renderizou e enviou o texto pelo canal — e o texto do modelo
    naquele turno é descartado. Só `dados_invalidos` devolve a palavra ao modelo,
    porque reperguntar um campo depende do contexto e não tem texto único certo.
    """

    def quote_plan(
        plano_id: str,
        idade: int,
        veiculo_ano: int,
        cep: str | None = None,
        data_inicio: str | None = None,
    ) -> str:
        """Cota o plano para este lead. Chame quando tiver os cinco campos.

        Args:
            plano_id: essencial, completo ou premium.
            idade: idade do condutor principal.
            veiculo_ano: ano de fabricação do veículo.
            cep: CEP de onde o carro dorme.
            data_inicio: início da vigência.

        Returns:
            str: o desfecho. Se disser que a mensagem já foi enviada, **não repita
            nada** — nem valor, nem resumo. Apenas encerre o turno.
        """
        from app import textos
        from app.contracts.quote import QuoteJobStatus
        from app.quote.job import executar_job
        from app.quote.renderer import render_de_payload

        # Normaliza pela mesma porta da QuoteRequest: é impossível montar uma
        # requisição que a API aceitaria errado sem devolver erro.
        try:
            req = QuoteRequest(
                plano_id=plano_id, idade=idade, veiculo_ano=veiculo_ano,
                cep=cep,
                data_inicio=normalizar_data(data_inicio) if data_inicio else None,
            )
        except (ValidationError, DataAmbigua, ValueError) as e:
            campo = _campo_do_erro(e)
            return (f"dados_invalidos: não consegui montar a cotação com o campo "
                    f"{campo}. Pergunte esse campo de novo, com as suas palavras.")

        # Checagem cruzada: se o argumento diverge do que `qualify_lead` gravou, isso
        # é bug de extração nosso, não uma cotação válida.
        conv = repo.obter_conversa(ctx.sessao, ctx.conversation_id)
        for campo, valor in (("idade", req.idade), ("veiculo_ano", req.veiculo_ano)):
            registrado = getattr(conv, campo)
            if registrado is not None and registrado != valor:
                return (f"dados_invalidos: o {campo} que você passou ({valor}) não bate "
                        f"com o que foi registrado ({registrado}). Confirme com o lead.")

        # Uma cotação por turno. Medido gerando o transcript do caminho feliz: o
        # modelo chamou `quote_plan` DUAS vezes na mesma volta, e o resultado foi
        # dois jobs, dois avisos de espera idênticos em sequência para o lead, e uma
        # linha em `quotes` que ficou `pending` para sempre — rastro inconsistente
        # justamente na tabela que responde pelo critério nº 4.
        #
        # Recusar é seguro: se o lead mudar de plano, a nova cotação sai no próximo
        # turno. O texto explica para o modelo o que fazer, em vez de só negar.
        if ctx.quote_do_turno is not None:
            return (f"já cotado neste turno: {ctx.quote_do_turno}. A mensagem com o "
                    "resultado JÁ FOI ENVIADA ao lead pelo sistema. Não cote de novo "
                    "e não repita o valor — encerre o turno.")

        conv.state = "cotando"
        ctx.sessao.flush()

        # ⚠️ DEFINIDA ANTES de `executar_job`, e isso não é estilo.
        #
        # O `avisar=` abaixo é um closure sobre este nome, e quem o executa é uma
        # `threading.Timer` — em OUTRA thread, 6 s depois. Com a definição embaixo da
        # chamada, o timer disparava sobre um nome ainda não vinculado e morria com
        # `NameError: cannot access free variable 'enviar'`. Numa thread de timer a
        # exceção não sobe para lugar nenhum: o turno seguia normal, o preço chegava
        # no fim, e o aviso de espera simplesmente NUNCA saía.
        #
        # Achado gerando o transcript do cenário degradado — a suíte passava porque
        # os testes de espera montam o `avisar` diretamente, sem esta função.
        def enviar(texto: str, quote_id: str | None = None) -> None:
            ctx.ja_enviou = True
            if ctx.enviar is not None:
                ctx.enviar(texto, quote_id)

        q = executar_job(
            ctx.sessao, ctx.conversation_id, req,
            chegada_do_lead=ctx.chegada_do_lead,
            # O aviso e o reforço saem por aqui, de dentro da tool, com o relógio do
            # lead — nunca por um watchdog na camada de conversa, que dispararia
            # durante a geração do modelo.
            avisar=(lambda t: enviar(t)) if ctx.enviar else None,
        )
        ctx.quote_do_turno = q.id
        ctx.sessao.commit()

        if q.status == str(QuoteJobStatus.OK):
            enviar(render_de_payload(q.payload), quote_id=q.id)
            conv.state = "cotado"
            ctx.sessao.commit()
            return (f"cotado: {q.id}. A mensagem com o valor JÁ FOI ENVIADA ao lead "
                    "pelo sistema. Não repita o valor nem resuma — encerre o turno.")

        if q.status == str(QuoteJobStatus.REFUSED):
            enviar(textos.POR_MOTIVO[q.motivo_recusa])
            conv.state = "cotado"
            ctx.sessao.commit()
            return (f"recusado: {q.motivo_recusa}. A explicação JÁ FOI ENVIADA ao lead. "
                    "Não repita nem ofereça exceção — encerre o turno.")

        if q.erro_outcome == "bad_request":
            return ("dados_invalidos: a cotação não aceitou os dados. Peça ao lead para "
                    "confirmar o ano do veículo e a data de início, com as suas palavras.")

        # `failed`: o handoff é criado pela fatia 5; aqui a mensagem já sai.
        enviar(textos.compor_handoff("cotacao_indisponivel"))
        from app.contracts.conversa import HandoffTrigger

        ctx.handoffs.append({
            "trigger": HandoffTrigger.COTACAO_INDISPONIVEL,
            "reason": "a cotação não respondeu depois de esgotadas as tentativas",
            "quote_id": q.id, "disparado_por": "regra", "assunto": None,
        })
        return ("indisponivel. O lead JÁ FOI avisado e um atendente foi acionado. "
                "Encerre o turno.")

    return quote_plan


def _campo_do_erro(e: Exception) -> str:
    if isinstance(e, ValidationError) and e.errors():
        return str(e.errors()[0]["loc"][0])
    if isinstance(e, DataAmbigua):
        return "data_inicio"
    return "desconhecido"


# ─── escalate_to_human: write-back ───────────────────────────────────────────
#
# **Os dois gatilhos que são do modelo, e só esses.**
#
# A linha é: o modelo decide onde ele enxerga o que a regra não enxerga. Em
# `assunto_sensivel` e `lead_pediu_atendente` a regra é um regex, e regex erra por
# recall — "não aguento mais falar com robô" não casa com nenhum termo da lista, e o
# modelo entende. Aí ele agrega.
#
# Nos outros cinco a regra CONTA (mídias, objeções, tentativas de extração, violações
# de guardrail, tentativas de cotação). O modelo não tem nenhuma informação que a
# contagem não tenha — só a impressão do turno isolado, que é exatamente o que a
# política de "tentar uma vez" existe para não seguir.
_DO_MODELO = frozenset({
    "assunto_sensivel",
    "lead_pediu_atendente",
})


def make_escalate_to_human(ctx: ContextoDoTurno) -> Callable[..., str]:
    """Padrão **write-back**: a tool só registra a intenção; quem executa é o backend.

    Isso mantém o comportamento testável e impede o modelo de causar efeito colateral
    direto. E é o que faz um gatilho determinístico — breaker aberto, job `failed` —
    produzir **exatamente o mesmo sinal** que uma decisão do modelo, distinguidos só
    por `disparado_por`.
    """

    def escalate_to_human(trigger: str, reason: str, summary: str = "") -> str:
        """Passa a conversa para um atendente humano.

        Use quando o lead pedir uma pessoa, quando o assunto for sensível (sinistro,
        jurídico, saúde, reclamação formal), ou quando você não conseguir ajudar.

        Args:
            trigger: `assunto_sensivel` ou `lead_pediu_atendente`.
            reason: por que, em uma frase, para o atendente.
            summary: resumo curto da conversa até aqui.

        Returns:
            str: confirmação interna. **Não repasse ao lead** — a mensagem de
            encaminhamento já foi enviada pelo sistema. Encerre o turno.
        """
        from app.contracts.conversa import HandoffTrigger

        try:
            t = HandoffTrigger(trigger)
        except ValueError:
            return (f"trigger inválido: {trigger!r}. Use um de "
                    f"{', '.join(str(x) for x in _DO_MODELO)}.")

        if t not in _DO_MODELO:
            # A recusa é MECANISMO, não instrução no prompt — a mesma escolha do
            # guardrail. Numa medição real, o modelo encaminhou na PRIMEIRA foto
            # com `midia_sem_texto`, contra a política de tentar uma vez: quando um
            # gatilho de contagem está no menu, ele é escolhido pelo caso isolado.
            return (
                f"{trigger} não é seu para decidir: ele é contado pelo sistema a "
                "partir do que está gravado na conversa, e a política é tentar uma "
                "vez antes. Responda o lead normalmente — peça o dado por texto, "
                "ou trate a objeção. Se a condição se repetir, o encaminhamento "
                "acontece sozinho."
            )

        ctx.handoffs.append({
            "trigger": t, "reason": reason or "decisão do agente",
            "summary": summary.strip() or None, "disparado_por": "modelo",
            "assunto": None,
        })
        return ("encaminhado. A mensagem JÁ FOI ENVIADA ao lead pelo sistema. "
                "Não repita nem prometa prazo — encerre o turno.")

    return escalate_to_human
