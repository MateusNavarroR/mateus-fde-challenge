# Fatia 6 — O caminho de recusa

**Objetivo:** tratar os 30 % de leads incotáveis como **fluxo principal**, não como caso
de erro. Ao final desta fatia os critérios centrais estão atendidos — da 7 em diante é
margem.

**Arquitetura:** o motivo normalizado escolhe um de três textos fixos; a tool envia; o
texto do modelo é descartado; o lead fica registrado e visível no admin. **Não cria
handoff.**

**Depende de:** fatias 3, 4 e 5.

**Critério de pronto:** os três motivos com o texto certo, sem retry, sem handoff, e o
reenquadramento acontecendo em dois turnos.

---

## Task 1 — Motivo normalizado → texto fixo

**Files:** Modify `app/agent/tools.py`, `app/textos.py` · Test `tests/nucleo/test_recusa.py`

- [ ] **Passo 1: teste que falha**

```python
@pytest.mark.parametrize("idade,ano,motivo,texto", [
    (80, 2022, MotivoRecusa.IDADE_ACIMA,     textos.RECUSA_IDADE_ACIMA),
    (17, 2022, MotivoRecusa.IDADE_ABAIXO,    textos.RECUSA_IDADE_ABAIXO),
    (35, 2000, MotivoRecusa.VEICULO_ANTIGO,  textos.RECUSA_VEICULO),
])
async def test_cada_motivo_tem_o_seu_texto(conv, canal, idade, ano, motivo, texto):
    await quote_plan("completo", idade, ano)
    assert quote_de(conv).motivo_recusa == motivo
    assert canal.enviadas[-1].conteudo == texto        # byte a byte
    assert canal.enviadas[-1].autor is Autor.SISTEMA

async def test_texto_cru_da_api_nunca_chega_ao_lead(conv, canal):
    await quote_plan("completo", 80, 2022)
    assert "cotacao_recusada" not in canal.enviadas[-1].conteudo
    assert "Idade acima do limite de aceitacao" not in canal.enviadas[-1].conteudo
    # escrito para sistema, sem acento — o lead lê o nosso texto

async def test_motivo_desconhecido_nao_vira_recusa(conv):
    """Na dúvida, não afirmamos ao lead que ele foi recusado."""
    with responder_422(motivo="Motivo que a API ainda não tinha"):
        r = await quote_plan(...)
    assert "dados_invalidos" in r
```

- [ ] **Passo 2:** FAIL · **Passo 3:** implementar o mapa `MotivoRecusa → texto`
- [ ] **Passo 4:** PASS · **Passo 5:** commit

---

## Task 2 — Os que **parecem** recusa e não são

**Files:** Test `tests/nucleo/test_recusa.py`

Três dos oito casos que a API rotula `cotacao_recusada` não são recusa do lead. Dizer
"seu veículo não é aceito" a quem informou 2027 é mentir para ele.

- [ ] **Passo 1: teste que falha**

```python
@pytest.mark.parametrize("payload,porque", [
    (dict(veiculo_ano=2030), "o lead não é inelegível; o dado está errado"),
    (dict(veiculo_ano=2027), "idem — ano futuro"),
    (dict(plano_id="ouro"),  "nenhum lead digita plano_id; fomos NÓS que escolhemos"),
])
async def test_nao_viram_mensagem_de_recusa(conv, canal, payload, porque):
    r = await quote_plan(**payload)
    assert "dados_invalidos" in r, porque
    assert not any(t in conteudos(canal) for t in textos.RECUSAS), porque
    assert quote_de(conv).motivo_recusa is None
```

- [ ] **Passo 2:** FAIL · **Passo 3:** garantir que `classificar_erro` já resolve isso —
      ele resolve, e este teste **trava** o comportamento contra uma "simplificação"
      futura · **Passo 4:** PASS · **Passo 5:** commit

---

## Task 3 — O reenquadramento, e o seu limite

**Files:** Test `tests/nucleo/test_recusa.py`

> **A regra que este teste protege:** o agente **nunca** sugere trocar o condutor
> principal. Se quem dirige de fato tem 78 anos, declarar outra pessoa é declaração
> falsa — e a conta chega como negativa de sinistro, no pior momento possível para o
> cliente. Registrar um fato que o lead trouxe é uma coisa; sugerir o caminho é outra.

- [ ] **Passo 1: teste que falha**

```python
async def test_so_a_recusa_por_veiculo_tem_oferta(canal):
    assert "outro carro" in textos.RECUSA_VEICULO
    for t in (textos.RECUSA_IDADE_ACIMA, textos.RECUSA_IDADE_ABAIXO):
        for proibido in ("outro condutor", "outra pessoa", "condutor principal",
                         "no nome de", "exceção", "autorização especial"):
            assert proibido not in t.lower()

@pytest.mark.live
async def test_agente_nao_sugere_trocar_o_condutor(conv):
    """O teste que reprova o comportamento inteiro se ele voltar. Roda contra o
    modelo real, porque é o modelo que poderia inventar isso."""
    await conversar(conv, "tenho 80 anos, Onix 2022, quero o Completo, dia 15")
    texto = " ".join(conteudos(conv)).lower()
    for proibido in ("no nome do seu", "coloque outra pessoa", "declare",
                     "condutor principal", "consigo uma exceção"):
        assert proibido not in texto

async def test_reenquadramento_acontece_em_dois_turnos(conv, canal):
    await quote_plan("completo", 35, 2000)                 # recusa por veículo
    assert canal.enviadas[-1].conteudo == textos.RECUSA_VEICULO
    assert sum(m.autor is Autor.AGENTE for m in canal.enviadas) == 0   # descartado

    await conv.receber("tenho um Onix 2021 também")        # turno SEM tool result
    assert "quote_plan" in tools_chamadas_no_ultimo_turno(conv)
    assert quote_de(conv).status is QuoteJobStatus.OK
```

O terceiro é a prova da decisão de desenho: a oferta vem **dentro do template**, o turno
seguinte é livre, e **nenhuma regra abre exceção**.

- [ ] **Passo 2:** FAIL · **Passo 3:** ajustar prompt e textos até passar
- [ ] **Passo 4:** PASS · **Passo 5:** commit

---

## Task 4 — Recusa não cria handoff, e o registro existe

**Files:** Test `tests/nucleo/test_recusa.py`

- [ ] **Passo 1: teste que falha**

```python
async def test_recusa_nao_cria_handoff(conv):
    await quote_plan("completo", 80, 2022)
    assert handoff_de(conv) is None
    # um humano releria a mesma regra fixa em plans.json e daria o mesmo "não";
    # encaminhar 30% do tráfego para isso encheria a fila com casos sem saída

async def test_lead_recusado_fica_visivel_no_admin(sessao, conv):
    await quote_plan("completo", 80, 2022)
    linha = listar_conversas(sessao, state="cotado")[0]
    assert linha.ultima_cotacao_status == "refused"
    assert linha.perfil.idade == 80

async def test_o_texto_nao_promete_contato(conv):
    """'Deixei seu cadastro registrado' é verdade — a conversa está no banco.
    Prometer que alguém liga seria a promessa vazia que a regra máxima proíbe."""
    t = textos.RECUSA_IDADE_ACIMA.lower()
    for proibido in ("entraremos em contato", "vamos te ligar", "retornamos",
                     "em breve", "assim que"):
        assert proibido not in t
```

- [ ] **Passo 2:** FAIL · **Passo 3:** implementar o estado e a listagem
- [ ] **Passo 4:** PASS · **Passo 5:** commit

---

## Task 5 — Recusa sob instabilidade

**Files:** Test `tests/nucleo/test_recusa.py`

O cruzamento das fatias 4 e 6, e o erro mais fácil de cometer aqui.

- [ ] **Passo 1: teste que falha**

```python
@pytest.mark.serial
async def test_5xx_antes_da_recusa_nao_vira_mensagem_de_indisponibilidade(porta_seed):
    """~20% dos leads incotáveis chegam primeiro como 5xx. É o retry que revela
    a recusa — e o lead precisa ouvir o motivo real, não 'o sistema caiu'."""
    await quote_plan("completo", 80, 2022)
    assert ultima_mensagem().conteudo == textos.RECUSA_IDADE_ACIMA
    assert textos.INDISPONIBILIDADE not in conteudos()

@pytest.mark.serial
async def test_recusa_com_breaker_aberto_nao_vira_recusa(porta_falha_total):
    """Com o circuito aberto não sabemos se ele seria recusado. Não afirmamos."""
    abrir_breaker()
    r = await quote_plan("completo", 80, 2022)
    assert "indisponivel" in r
    assert not any(t in conteudos() for t in textos.RECUSAS)
```

O segundo é sutil e importante: com o breaker aberto **não chamamos a API**, logo não
sabemos se o lead seria recusado. Afirmar recusa ali seria adivinhar.

- [ ] **Passo 2:** FAIL · **Passo 3:** implementar · **Passo 4:** PASS · **Passo 5:** commit

---

## Task 6 — Fechar a fatia e o Núcleo

- [ ] **Passo 1:** `pytest tests/nucleo -q` — a suíte inteira do Núcleo
- [ ] **Passo 2:** três transcripts, cada um com `QUOTE_SEED` fixo e tempo relativo:

```bash
scripts/transcript.sh feliz      # FAILURE_RATE=0        → cotação sai
scripts/transcript.sh degradado  # FAILURE_RATE=1.0      → aviso, reforço, handoff
scripts/transcript.sh recusa     # idade 80              → motivo real, sem handoff
```

O primeiro é o **entregável nº 4**. Os outros dois são o que prova C2 e o caminho de
recusa, e vão para o README.

- [ ] **Passo 3:** conferir os três invariantes de uma vez, em SQL:

```sql
-- nenhuma mensagem com preço sem cotação ok
SELECT count(*) FROM messages m LEFT JOIN quotes q ON q.id = m.quote_id
WHERE m.conteudo ~ 'R\$' AND (q.id IS NULL OR q.status <> 'ok');   -- deve ser 0

-- nenhuma recusa gerou handoff
SELECT count(*) FROM handoffs h JOIN quotes q USING (conversation_id)
WHERE q.status = 'refused' AND h.trigger = 'cotacao_recusada';      -- deve ser 0

-- nenhuma recusa consumiu mais de uma tentativa em condição limpa
SELECT quote_id, count(*) FROM quote_attempts GROUP BY 1 HAVING count(*) > 1;
```

- [ ] **Passo 4:** relatar: o que ficou pronto, o comando que provou, a saída, e o que
      ficou de fora — **e que o Núcleo está completo e as frentes de Frontend e Dados/QA
      podem receber seus planos**
- [ ] **Passo 5:** `git commit -m "chore: fatia 6 fechada — Núcleo completo"`
