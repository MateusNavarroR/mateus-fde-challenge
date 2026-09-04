# Fatia 1 — A espinha

**Objetivo:** o console conversa com o agente, cada mensagem é persistida com id e
status, e nenhuma PII crua chega ao banco ou ao log.

**Arquitetura:** um turno entra pelo `ConsoleAdapter`, passa pela camada de conversa
(que garante um turno por vez), roda o agente Agno, e volta pelo mesmo adaptador. Toda
escrita no banco passa por `repo.gravar_mensagem`, que é onde o mascaramento e o
guardrail moram — um ponto de estrangulamento, não uma boa intenção espalhada.

**Stack:** FastAPI (só o que a fatia 8 vai precisar; aqui o console basta), Agno,
SQLAlchemy 2.x, Postgres 16, pytest.

**Depende de:** contratos da Fase 0 e das migrações `0001`/`0002`, ambos prontos.
**Nada depende desta fatia fora do Núcleo**, exceto `privacy/mascarar.py`, que a frente
de Dados reusa na fatia 9.

**Critério de pronto:** `python -m app.console` sustenta uma conversa de ida e volta;
`pytest tests/nucleo/test_turno.py tests/nucleo/test_pii.py` verde; e uma mensagem com
CPF, telefone, e-mail e CEP não deixa nenhum deles cru em `messages.conteudo` nem no log.

---

## Task 1 — Configuração e limiares

**Files:** Create `app/config.py` · Test `tests/nucleo/test_config.py`

Todos os números da política vivem aqui. Espalhá-los pelo código é como se perde a
capacidade de explicar por que o timeout é 12 s.

- [ ] **Passo 1: teste que trava os defaults**

```python
def test_defaults_sao_os_da_politica():
    s = Settings(_env_file=None)
    assert s.quote_read_timeout_s == 12.0      # > SLOW_SECONDS=8 (API-COTACAO §3.2)
    assert s.quote_max_attempts == 3           # 0.2³ = 0,8% residual (§3.4)
    assert s.quote_max_concorrencia == 8       # o legado serializa acima de 40 (§3.3)
    assert s.aviso_espera_s == 6.0             # relógio do lead, caminho da cotação
    assert s.aviso_sem_cotacao_s == 10.0       # demora do modelo é anômala, não projetada
    assert s.reforco_espera_s == 20.0
    assert s.breaker_limiar == 5
    assert s.breaker_cooldown_s == 20.0
```

- [ ] **Passo 2:** `pytest tests/nucleo/test_config.py -v` → FAIL, `No module named 'app.config'`
- [ ] **Passo 3:** implementar `Settings(BaseSettings)` com `env_prefix="APP_"`, mais
      `database_url`, `quote_api_url`, `llm_model` (default `anthropic:claude-opus-5`).
      **Nenhum default carrega segredo**; `ANTHROPIC_API_KEY` é lida do ambiente pelo SDK.
- [ ] **Passo 4:** `pytest tests/nucleo/test_config.py -v` → PASS
- [ ] **Passo 5:** `git commit -m "feat(config): limiares da política em um lugar só"`

---

## Task 2 — Mascaramento de PII

**Files:** Create `app/privacy/mascarar.py` · Test `tests/nucleo/test_pii.py`

> ⚠️ **Nenhum literal de PII neste repositório.** Ver `docs/planos/00-fixtures-pii.md`:
> a fixture é um **gerador semeado** que produz valor válido em formato no momento do
> teste. O regex continua sendo exercitado no formato real, a varredura do portão de
> segurança não tem o que achar, e não existe lista de exceções — que é a porta que não
> se abre num repositório público.

- [ ] **Passo 1: o gerador**

Criar `tests/fixtures/pii.py` com `gerar_pii(seed)` e `frase_do_lead(seed)`, conforme
`00-fixtures-pii.md`. Nenhum valor é literal: nascem em memória e morrem no fim da
execução.

- [ ] **Passo 2: teste que falha**

```python
def test_mascara_todas_as_classes():
    frase, pii = frase_do_lead(seed=1)
    saida = mascarar(frase)
    for classe, valor in pii.items():
        assert valor not in saida, classe

def test_cem_amostras_nao_escapam():
    """Um literal exercita um formato de CPF. O gerador exercita cem, de graça —
    e é onde aparece o zero à esquerda e a variação que um exemplo a dedo esconde."""
    for seed in range(100):
        frase, pii = frase_do_lead(seed)
        assert not any(v in mascarar(frase) for v in pii.values())

def test_preserva_o_que_nao_e_pii():
    # a idade é dado de qualificação, não PII a mascarar — cotar depende dela
    frase, _ = frase_do_lead(seed=1)
    assert "35 anos" in mascarar(frase)

def test_e_idempotente():
    frase, _ = frase_do_lead(seed=7)
    assert mascarar(mascarar(frase)) == mascarar(frase)

def test_cpf_sem_pontuacao_tambem_e_pego():
    _, pii = frase_do_lead(seed=3)
    nu = pii["cpf"].replace(".", "").replace("-", "")
    assert nu not in mascarar(f"cpf {nu}")
```

- [ ] **Passo 3:** `pytest tests/nucleo/test_pii.py -v` → FAIL
- [ ] **Passo 4:** implementar `mascarar(texto: str) -> str` com uma tabela de
      `(nome, regex, substituto)`. Substitutos marcados: `[CPF]`, `[CEP]`, `[EMAIL]`,
      `[TELEFONE]`, `[PLACA]`. Idempotência sai de graça se os substitutos não casarem
      com os próprios regexes — **escreva o teste antes de acreditar nisso**.
- [ ] **Passo 5:** `pytest tests/nucleo/test_pii.py -v` → PASS
- [ ] **Passo 6:** `git commit -m "feat(privacy): mascaramento por gerador semeado, sem literal de PII"`

---

## Task 3 — Persistência e o ponto de estrangulamento

**Files:** Create `app/persistence/db.py`, `models.py`, `repo.py` · Test `tests/nucleo/test_turno.py`

`repo.gravar_mensagem` é **o único caminho** para a tabela `messages`. Toda fatia
seguinte escreve por aqui, e é por isso que mascaramento e guardrail cabem num lugar só.

- [ ] **Passo 1: teste que falha**

```python
def test_mensagem_persiste_com_id_e_status(sessao):
    conv = repo.criar_conversa(sessao, channel="console", external_ref="s1")
    m = repo.gravar_mensagem(sessao, conv.id, autor=Autor.LEAD,
                             conteudo=frase_do_lead(seed=1)[0],
                             status=MessageStatus.RECEIVED, external_id="e1")
    assert m.id and m.index == 0 and m.status is MessageStatus.RECEIVED
    assert frase_do_lead(seed=1)[1]["cpf"] not in m.conteudo   # mascarado NA GRAVAÇÃO

def test_index_e_sequencial_por_conversa(sessao): ...

def test_external_id_repetido_nao_duplica(sessao):
    # canais reais reentregam; o console não, mas o contrato é o mesmo
    a = repo.gravar_mensagem(..., external_id="e1")
    b = repo.gravar_mensagem(..., external_id="e1")
    assert a.id == b.id
    assert sessao.query(Message).count() == 1
```

- [ ] **Passo 2:** `pytest tests/nucleo/test_turno.py -v` → FAIL
- [ ] **Passo 3:** implementar. `models.py` espelha as migrações **sem redefini-las** —
      o SQL é a fonte. `gravar_mensagem` faz, nesta ordem: mascarar → guardrail →
      calcular `index` → gravar. Dedup por `external_id` usa
      `ON CONFLICT DO NOTHING` + releitura, não `SELECT` antes do `INSERT` (que é corrida).
- [ ] **Passo 4:** `pytest tests/nucleo/test_turno.py -v` → PASS
- [ ] **Passo 5:** `git commit -m "feat(persistence): gravar_mensagem como ponto único de escrita"`

---

## Task 4 — Guardrail, verificação 1

**Files:** Create `app/agent/guardrail.py` · Test `tests/nucleo/test_guardrail.py`

As verificações 2 e 3 chegam na fatia 3, quando existe cotação. A 1 é testável já.

- [ ] **Passo 1: teste que falha**

```python
@pytest.mark.parametrize("texto", [
    "fica R$ 209,90 por mês", "custa 209,90 reais", "sai por R$1.025,14",
    "uns 300 reais", "R$ 119",
])
def test_valor_monetario_em_texto_do_modelo_e_rejeitado(texto):
    with pytest.raises(GuardrailViolado):
        checar_texto_do_modelo(texto)

@pytest.mark.parametrize("texto", [
    "tenho 35 anos", "carro 2019", "o CEP é 01310-100", "cobre roubo e furto",
    "a franquia é menor no Premium",
])
def test_texto_sem_valor_monetario_passa(texto):
    checar_texto_do_modelo(texto)   # não levanta
```

O segundo conjunto é o que impede o regex de virar paranoia inútil: se ele reprovar
"tenho 35 anos", o agente não consegue conversar.

- [ ] **Passo 2:** `pytest tests/nucleo/test_guardrail.py -v` → FAIL
- [ ] **Passo 3:** implementar `checar_texto_do_modelo(texto)`, chamado por
      `gravar_mensagem` quando `autor is Autor.AGENTE`. Levanta `GuardrailViolado`.
- [ ] **Passo 4:** `pytest tests/nucleo/test_guardrail.py -v` → PASS
- [ ] **Passo 5:** `git commit -m "feat(guardrail): nenhum valor monetário em texto do modelo"`

---

## Task 5 — Adaptador de console e o transcript

**Files:** Create `app/channels/console.py` · Test `tests/nucleo/test_console.py`

- [ ] **Passo 1: teste que falha**

```python
async def test_typing_e_no_op_e_nao_escreve_nada(capsys):
    ad = ConsoleAdapter()
    await ad.typing("c1", ativo=True)
    assert capsys.readouterr().out == ""      # [digitando...] documenta a coisa errada

async def test_transcript_marca_tempo_relativo(relogio_falso):
    ad = ConsoleAdapter(transcript=True, inicio=relogio_falso.agora)
    relogio_falso.avancar(6.2)
    await ad.send("c1", "aviso", message_id="m1")
    assert "[+6.2s]" in ad.transcript_linhas[-1]

def test_adaptador_satisfaz_a_porta():
    assert isinstance(ConsoleAdapter(), ChannelAdapter)
```

O relógio é injetado. Sem isso o teste do transcript dorme de verdade, e uma suíte que
dorme 37 s ninguém roda.

- [ ] **Passo 2:** `pytest tests/nucleo/test_console.py -v` → FAIL
- [ ] **Passo 3:** implementar. `send` grava por `repo.gravar_mensagem` com status
      `pending`, imprime, e promove a `sent`. `typing` é `return None`.
- [ ] **Passo 4:** `pytest tests/nucleo/test_console.py -v` → PASS
- [ ] **Passo 5:** `git commit -m "feat(channels): console com typing no-op e transcript com tempo relativo"`

---

## Task 6 — A camada de conversa: um turno por vez

**Files:** Create `app/conversa.py` · Test `tests/nucleo/test_conversa.py`

Regra da spec §3.3: **um turno por vez por conversa; mensagem que chega durante um turno
entra na fila.** A fatia 4 exercita isso sob espera de 8 s; aqui a regra nasce e é
testada isolada.

- [ ] **Passo 1: teste que falha**

```python
async def test_segunda_mensagem_entra_na_fila(conversa, agente_lento):
    t1 = asyncio.create_task(conversa.receber("primeira"))
    await agente_lento.comecou.wait()
    t2 = asyncio.create_task(conversa.receber("segunda"))
    await asyncio.gather(t1, t2)
    assert conversa.turnos_simultaneos_maximo == 1     # a asserção que importa
    assert [m.conteudo for m in mensagens(conversa)] == [
        "primeira", "resposta 1", "segunda", "resposta 2"]

async def test_aviso_de_demora_do_modelo_aos_10s(conversa, agente_lento, relogio_falso):
    # ①b de docs/TEXTOS.md — fora do caminho da cotação
    agente_lento.duracao = 11.0
    await conversa.receber("oi")
    assert textos.AVISO_SEM_COTACAO in conteudos(conversa)

async def test_modelo_em_6s_nao_dispara_aviso(conversa, agente_lento):
    agente_lento.duracao = 6.5   # latência plausível, não sintoma
    await conversa.receber("oi")
    assert textos.AVISO_SEM_COTACAO not in conteudos(conversa)
```

O terceiro é o que justifica o limiar de 10 s existir. Sem ele, alguém "uniformiza" para
6 s e o agente passa a se desculpar por nada.

- [ ] **Passo 2:** `pytest tests/nucleo/test_conversa.py -v` → FAIL
- [ ] **Passo 3:** implementar `Conversa` com um `asyncio.Lock` por `conversation_id` e
      um relógio de 10 s cancelado pela primeira saída. **Desligado no estado
      `encaminhado`** — senão o lead que escreve depois do handoff recebe "só um
      instante" a cada 10 s, para sempre.
- [ ] **Passo 4:** `pytest tests/nucleo/test_conversa.py -v` → PASS
- [ ] **Passo 5:** `git commit -m "feat(conversa): um turno por vez e aviso de demora do modelo"`

---

## Task 7 — O runner do agente e `turn_usage`

**Files:** Create `app/agent/runner.py`, `app/console_main.py` · Test `tests/nucleo/test_runner.py`

Nesta fatia o agente ainda não tem tool nenhuma — só conversa. O que importa aqui é o
turno fechar e o uso ser gravado.

- [ ] **Passo 1: teste que falha**

```python
async def test_turno_grava_turn_usage(sessao, agente_stub):
    m = await runner.rodar_turno(conv_id="c1", texto="oi")
    u = sessao.query(TurnUsage).filter_by(message_id=m.id).one()
    assert u.tokens_in > 0 and u.provider == "anthropic"
    assert u.latency_ms > 0

def test_ollama_grava_cache_como_null(sessao, agente_stub_ollama):
    # o Ollama não popula cache_read/cache_write; 0 diria "o cache não acertou",
    # e a verdade é "não existe cache neste caminho"
    assert sessao.query(TurnUsage).one().cache_read is None
```

- [ ] **Passo 2:** `pytest tests/nucleo/test_runner.py -v` → FAIL
- [ ] **Passo 3:** implementar. `rodar_turno` lê `response.metrics` (`RunMetrics`,
      granularidade de turno) e grava. `cost_usd` e `pricing_vigencia` saem de
      `config/model_pricing.yaml`; se o modelo não estiver na tabela, ambos ficam `NULL`
      — **nunca zero**, que seria afirmar que foi grátis.
- [ ] **Passo 4:** `pytest tests/nucleo/test_runner.py -v` → PASS
- [ ] **Passo 5:** commit

---

## Task 8 — O compose, com o bind certo

**Files:** Create `docker-compose.yml`, `.env.example`

O compose do desafio publica `"8000:8000"`, que é bind em `0.0.0.0`. **O nosso não
repete isso.** É uma linha, e é o que torna a superfície administrativa inalcançável da
rede independente de autenticação (`CLAUDE.md` 14b).

- [ ] **Passo 1: teste que falha**

```python
def test_nenhuma_porta_publica_em_todas_as_interfaces():
    compose = yaml.safe_load(open("docker-compose.yml"))
    for nome, svc in compose["services"].items():
        for porta in svc.get("ports", []):
            assert str(porta).startswith("127.0.0.1:"), (
                f"{nome} publica em 0.0.0.0: {porta}")

def test_env_example_so_tem_placeholder():
    for linha in open(".env.example"):
        if "=" in linha and not linha.startswith("#"):
            valor = linha.split("=", 1)[1].strip()
            assert valor == "" or valor.startswith("<"), linha
```

O segundo é barato e pega o acidente mais caro que existe num repositório público: uma
chave real deixada no arquivo de exemplo.

- [ ] **Passo 2:** `pytest tests/nucleo/test_compose.py -v` → FAIL
- [ ] **Passo 3:** escrever o compose. Serviços `db`, `quote-api` e `app`, todos com
      `ports` no formato `"127.0.0.1:PORTA:PORTA"`. `ANTHROPIC_API_KEY` repassada do
      ambiente, **sem default**. `ADMIN_TOKEN` opcional, ausente por padrão.
- [ ] **Passo 4:** `pytest tests/nucleo/test_compose.py -v` → PASS
- [ ] **Passo 5:** `git commit -m "feat(infra): compose publicando só em 127.0.0.1"`

---

## Task 9 — Fechar a fatia

- [ ] **Passo 1:** `docker compose up -d db quote-api && python -m app.console`,
      trocar três mensagens, `Ctrl-D`
- [ ] **Passo 2:** conferir no banco:

```sql
SELECT index, autor, status, left(conteudo, 40) FROM messages ORDER BY index;
```

Esperado: alternância lead/agente, `index` sequencial, status `received`/`sent`, e
**nenhum CPF, telefone ou e-mail cru** se você tiver escrito algum.

- [ ] **Passo 3:** `pytest tests/nucleo -q` → tudo verde
- [ ] **Passo 4:** relatar: o que ficou pronto, o comando que provou, a saída, e o que
      ficou de fora
- [ ] **Passo 5:** `git commit -m "chore: fatia 1 fechada — a espinha roda"`
