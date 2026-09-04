# Fatia 4 — Resiliência

**Objetivo:** provar com `FAILURE_RATE=1.0` e `SLOW_RATE=1.0` que o agente não trava,
não inventa preço, avisa e encaminha. **É o critério que o enunciado diz que mais separa.**

**Arquitetura:** timeout de 12 s, três tentativas, backoff exponencial com jitter,
semáforo de 8 e circuit breaker — tudo **abaixo** da fronteira da tool. A tool bloqueia
até o job resolver e **fala durante a espera**: o que não cabe num turno é o silêncio,
não o turno.

**Depende de:** fatia 3.
**A frente de Frontend abre ao final desta fatia** — é aqui que passam a existir
degradação, breaker e tentativas falhas para a tela mostrar.

**Critério de pronto:** as sete suítes da tabela final, todas verdes, **em série**.

> ⚠️ **Toda suíte que depende de `QUOTE_SEED` roda sequencial, com restart do container
> antes.** O RNG é um fluxo global do processo: uma falha consome dois valores, um
> sucesso consome um, e um 422 do Pydantic não consome nenhum. Cenário reproduzível é a
> tripla (seed, processo reiniciado, sequência exata) — a seed sozinha não é nada.
> Isso é travado por marcador, não por comentário.

---

## Task 1 — Retry, backoff e semáforo

**Files:** Modify `app/quote/client.py` · Test `tests/nucleo/test_resiliencia.py`

- [ ] **Passo 1: teste que falha**

```python
@pytest.mark.serial
async def test_tres_tentativas_em_5xx(porta_falha_total):   # FAILURE_RATE=1.0
    r = await executar_job(...)
    assert r.status is QuoteJobStatus.FAILED
    assert [a.attempt for a in r.attempts] == [1, 2, 3]
    assert all(a.outcome == "transient" for a in r.attempts)

@pytest.mark.serial
async def test_lenta_nao_e_falha(porta_lenta):              # SLOW_RATE=1.0, 8s
    r = await executar_job(...)
    assert r.status is QuoteJobStatus.OK
    assert len(r.attempts) == 1 and 7_900 < r.attempts[0].latency_ms < 12_000

@pytest.mark.serial
async def test_timeout_de_5s_destroi_o_sucesso(porta_lenta, settings_timeout_5s):
    """Regressão: prova POR QUE o timeout é 12s. Se alguém 'otimizar' para 5s,
    este teste passa a falhar por passar."""
    r = await executar_job(...)
    assert r.status is QuoteJobStatus.FAILED
    assert all(a.outcome == "timeout" for a in r.attempts)

async def test_backoff_tem_jitter():
    esperas = [calcular_backoff(n) for n in range(1, 4) for _ in range(20)]
    assert len(set(esperas)) > 3          # não é determinístico
    assert max(esperas) <= 2.0            # teto

@pytest.mark.serial
async def test_semaforo_segura_sob_concorrencia(porta_lenta):
    # sem limite, acima de 40 lentas o legado serializa e o tempo dobra para ~16,6s
    rs = await asyncio.gather(*[executar_job(...) for _ in range(20)])
    assert all(a.latency_ms < 12_000 for r in rs for a in r.attempts)
```

O terceiro é o teste mais valioso da fatia: ele deixa **no código** o motivo de o
timeout ser 12 s, em vez de só na prosa do README.

- [ ] **Passo 2:** FAIL · **Passo 3:** implementar retry, backoff com full jitter e
      `asyncio.Semaphore(8)`. A espera no semáforo **não** conta contra o `read_timeout`
      (é fila nossa, não latência do legado), mas é registrada à parte na tentativa.
- [ ] **Passo 4:** PASS · **Passo 5:** commit

---

## Task 2 — O que NÃO retenta

**Files:** Test `tests/nucleo/test_resiliencia.py`

Os testes que provam o contrário do erro mais provável: alguém "melhora" o cliente e
começa a retentar tudo.

- [ ] **Passo 1: teste que falha**

```python
@pytest.mark.serial
async def test_recusa_nao_consome_tentativa(porta_limpa):
    r = await executar_job(..., idade=80)
    assert r.status is QuoteJobStatus.REFUSED
    assert len(r.attempts) == 1 and r.attempts[0].attempt == 1   # EXATAMENTE uma

@pytest.mark.serial
@pytest.mark.parametrize("payload,motivo", [
    (dict(data_inicio="15/07/2026"), "400 payload_invalido"),
    (dict(idade=201),                "422 do Pydantic"),
    (dict(plano_id="ouro"),          "422 vestido de recusa, mas é bug nosso"),
    (dict(veiculo_ano=2030),         "ano futuro: dado errado, não recusa"),
])
async def test_bad_request_nao_retenta(porta_limpa, payload, motivo):
    r = await executar_job(..., **payload)
    assert len(r.attempts) == 1, motivo
    assert r.error.outcome is QuoteOutcome.BAD_REQUEST

@pytest.mark.serial
async def test_recusa_mascarada_por_5xx(porta_seed_42):
    """O sorteio roda ANTES da regra de negócio: ~20% dos leads incotáveis chegam
    primeiro como 5xx. O 5xx CONSOME tentativa; o 422 que vem depois NÃO. E o
    desfecho é refused, nunca failed."""
    r = await executar_job(..., idade=80)
    assert r.status is QuoteJobStatus.REFUSED
    assert r.attempts[-1].outcome == "refused"
    assert any(a.outcome == "transient" for a in r.attempts[:-1])
```

Contar linhas em `quote_attempts` é a asserção certa: a tabela é a evidência que o
`/admin/status` e a linha do tempo já leem, então o teste checa o que o avaliador vai
ver, não um contador interno.

- [ ] **Passo 2:** FAIL · **Passo 3:** ajustar o laço de retry · **Passo 4:** PASS
- [ ] **Passo 5:** commit

---

## Task 3 — Circuit breaker

**Files:** Create `app/quote/breaker.py` · Test `tests/nucleo/test_breaker.py`

- [ ] **Passo 1: teste que falha**

```python
@pytest.mark.serial
async def test_abre_na_quinta_falha_consecutiva(porta_falha_total):
    for _ in range(2): await executar_job(...)     # 2 jobs × 3 tentativas = 6 > 5
    assert breaker.estado is Estado.ABERTO

@pytest.mark.serial
async def test_job_com_circuito_aberto_nasce_failed_sem_tentativa():
    r = await executar_job(...)
    assert r.status is QuoteJobStatus.FAILED
    assert r.attempts == [] and r.circuito_aberto is True
    # a tela precisa distinguir isso de "tentamos 3 vezes e falhou"

async def test_recusa_e_bad_request_nao_contam_para_o_breaker(porta_limpa):
    for _ in range(10): await executar_job(..., idade=80)
    assert breaker.estado is Estado.FECHADO
    # recusa é a API funcionando perfeitamente; contá-la abriria o circuito
    # num dia de muitos leads idosos

@pytest.mark.serial
async def test_meia_abertura_usa_a_proxima_cotacao_real(relogio_falso):
    # a sonda não é requisição sintética: é a próxima cotação de verdade,
    # que assim não é desperdiçada
```

- [ ] **Passo 2:** FAIL · **Passo 3:** implementar. Global por processo — a
      instabilidade é do legado, e descobri-la numa conversa deve poupar as outras.
      Limiar 5, cooldown 20 s, meia-abertura com uma chamada real.
- [ ] **Passo 4:** PASS · **Passo 5:** commit

---

## Task 4 — Aviso e reforço, com o relógio do lead

**Files:** Modify `app/agent/tools.py` · Test `tests/nucleo/test_espera.py`

O disparo é **de dentro da tool**, pelo `ChannelAdapter`. O relógio é **o do lead**: o
timestamp de chegada da mensagem entra na tool e a contagem sai de lá.

- [ ] **Passo 1: teste que falha**

```python
@pytest.mark.serial
async def test_aviso_aos_6s_e_reforco_aos_20s(porta_falha_total, relogio_falso, canal):
    await quote_plan(..., chegada_do_lead=relogio_falso.t0)
    assert [m.conteudo for m in canal.enviadas if m.autor is Autor.SISTEMA] == [
        textos.AVISO_ESPERA, textos.REFORCO,
        textos.INDISPONIBILIDADE + "\\n\\n" + textos.DESPEDIDA]

async def test_falha_rapida_com_retry_rapido_nao_avisa(porta_falha_1x):
    # 5xx volta em ~2ms e o retry responde ~250ms depois — o lead não percebe,
    # e um aviso aí seria ruído
    await quote_plan(...)
    assert textos.AVISO_ESPERA not in conteudos(canal)

async def test_relogio_conta_da_chegada_do_lead(relogio_falso, canal):
    """O turno gastou 2s de modelo antes da tool. Se contássemos do início da
    tool, o lead ficaria 8s no escuro antes do aviso."""
    chegada = relogio_falso.t0; relogio_falso.avancar(2.0)
    await quote_plan(..., chegada_do_lead=chegada)   # lenta de 8s
    assert canal.instante_de(textos.AVISO_ESPERA) == pytest.approx(6.0, abs=0.3)
```

- [ ] **Passo 2:** FAIL · **Passo 3:** implementar com `asyncio` timers cancelados na
      resolução do job · **Passo 4:** PASS · **Passo 5:** commit

---

## Task 5 — Um turno por vez, sob espera real

**Files:** Test `tests/nucleo/test_conversa.py`

A regra nasceu na fatia 1; aqui ela é exercitada sob 8 s de espera de verdade.

- [ ] **Passo 1: teste que falha**

```python
@pytest.mark.serial
async def test_mensagem_durante_a_espera_entra_na_fila(porta_lenta, conv):
    t = asyncio.create_task(conv.receber("pode cotar"))
    await asyncio.sleep(3)
    await conv.receber("ah, e tem desconto?")
    await t
    assert conv.turnos_simultaneos_maximo == 1        # a asserção que importa
    idx = [m.index for m in mensagens(conv)]
    assert idx == sorted(idx)                          # nada se perdeu, nada trocou
    assert conteudos(conv).index("R$") < conteudos(conv).index("desconto")
```

A do meio é a que importa: sem ela o teste passaria mesmo com dois turnos concorrentes
que por acaso não se atrapalharam.

- [ ] **Passo 2:** FAIL · **Passo 3:** ajustar o lock por conversa · **Passo 4:** PASS
- [ ] **Passo 5:** commit

---

## Task 6 — Fechar a fatia

- [ ] **Passo 1:** as sete suítes, em série:

```bash
pytest tests/nucleo -q -m "serial" -p no:randomly -x
```

| Suíte | Configuração | Prova |
|---|---|---|
| feliz | `FAILURE_RATE=0` | a cotação sai |
| degradado | `FAILURE_RATE=1.0` | não trava, não inventa preço, avisa, encaminha |
| lentidão | `SLOW_RATE=1.0` | 1 tentativa, ~8 s, **a cotação sai** |
| timeout curto | `SLOW_RATE=1.0` + 5 s | prova por que é 12 s |
| não-retentáveis | `FAILURE_RATE=0` | 422 e 400 com **uma** tentativa |
| recusa mascarada | seed fixa | 5xx não vira "você foi recusado" |
| breaker + concorrência | `FAILURE_RATE=1.0` / 20 jobs | abre na 5ª; nenhuma acima de 12 s |

- [ ] **Passo 2:** gerar `artifacts/transcript-degradado.md` com `QUOTE_SEED` fixo e
      conferir a sequência `[+6.0s] [+20.0s] [+37.1s]`
- [ ] **Passo 3:** rodar de novo com restart e conferir que é idêntico
- [ ] **Passo 4:** relatar pronto / comando / saída / fora de escopo — **e avisar que a
      frente de Frontend está liberada**
- [ ] **Passo 5:** `git commit -m "chore: fatia 4 fechada — degradação provada"`
