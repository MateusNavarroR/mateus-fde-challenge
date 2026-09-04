# Fatia 2 — Qualificação

**Objetivo:** os cinco campos saem de texto livre bagunçado, e a conversa fica útil.

**Arquitetura:** o catálogo de planos é buscado no boot e entra no system prompt
estático — **sem nenhum valor monetário**, que é o que torna o guardrail absoluto em vez
de heurístico. A tool `qualify_lead` é write-back: grava o que foi extraído e devolve o
que falta, e é `campos_faltantes` que conduz a próxima pergunta.

**Depende de:** fatia 1 (persistência, mascaramento, guardrail 1, camada de conversa).

**Critério de pronto:** uma conversa no console em que o lead informa idade, veículo,
CEP, data de início e plano em qualquer ordem, em linguagem torta, e o perfil fecha.

---

## Task 1 — O catálogo, sem valor monetário

**Files:** Create `app/agent/catalogo.py` · Test `tests/nucleo/test_catalogo.py`

`fetch_plans` **não é tool**. `GET /planos` é estável, não passa pelo sorteio de falha e
não muda durante a execução: buscar no boot elimina um round trip e põe o catálogo no
prefixo cacheável.

O motivo mais forte é outro, e é ele que este teste trava: **o catálogo entra sem
`base_mensal` e sem valor de franquia.** Se `base_mensal` estivesse no prompt, o modelo
poderia dizer "o Essencial começa em R$ 119,90" — verdadeiro, e ainda assim um preço
escrito pelo modelo. Aí o guardrail precisaria de uma lista de exceções, e é ali que
guardrail morre.

- [ ] **Passo 1: teste que falha**

```python
def test_catalogo_nao_contem_nenhum_valor_monetario(catalogo_texto):
    for proibido in ("119", "209", "339", "4500", "3000", "1500", "R$"):
        assert proibido not in catalogo_texto

def test_catalogo_tem_nomes_e_coberturas(catalogo_texto):
    assert "Premium" in catalogo_texto
    assert "carro_reserva" in catalogo_texto or "carro reserva" in catalogo_texto

def test_franquia_entra_como_ordem_relativa(catalogo_texto):
    # o lead pergunta "qual tem franquia menor?" e isso tem resposta sem número
    assert "menor franquia" in catalogo_texto.lower()

def test_boot_falha_alto_se_planos_nao_responde(monkeypatch):
    monkeypatch.setenv("APP_QUOTE_API_URL", "http://127.0.0.1:1")
    with pytest.raises(CatalogoIndisponivel):
        carregar_catalogo()
```

O último é deliberado: **falhar alto é melhor que subir com catálogo vazio.** Um agente
que não sabe os nomes dos planos conversa errado sem nenhum sinal.

- [ ] **Passo 2:** `pytest tests/nucleo/test_catalogo.py -v` → FAIL
- [ ] **Passo 3:** implementar `carregar_catalogo() -> str`. Busca `GET /planos` com
      retry limitado (o compose sobe os dois juntos e a ordem não é garantida), extrai
      `id`, `nome` e `coberturas`, **descarta `base_mensal` e `franquia`**, e deriva a
      ordem relativa das franquias em texto.
- [ ] **Passo 4:** `pytest tests/nucleo/test_catalogo.py -v` → PASS
- [ ] **Passo 5:** `git commit -m "feat(agent): catálogo no boot, sem valor monetário"`

---

## Task 2 — O system prompt cacheável

**Files:** Create `app/agent/prompt.py` · Test `tests/nucleo/test_prompt.py`

A separação estático × volátil é requisito do cache, não estilo. Conteúdo volátil
concatenado no system message zera o cache **silenciosamente** — nada quebra, o custo
sobe e ninguém vê.

- [ ] **Passo 1: teste que falha**

```python
def test_system_estatico_nao_varia_entre_chamadas():
    a, b = construir_system(), construir_system()
    assert a == b          # nenhuma data, nenhum id, nenhum estado do lead

def test_bloco_volatil_e_callable_e_marcado_sem_cache():
    blocos = construir_blocos_volateis()
    assert all(b.cache is False for b in blocos)
    assert callable(construir_blocos_volateis)

def test_volatil_nao_esta_no_system():
    assert datetime.now().strftime("%Y-%m-%d") not in construir_system()
```

- [ ] **Passo 2:** `pytest tests/nucleo/test_prompt.py -v` → FAIL
- [ ] **Passo 3:** implementar. `construir_system()` devolve papel + catálogo + ordem de
      qualificação + guardrails, tudo imutável. `construir_blocos_volateis()` é o
      **callable** passado a `system_prompt_blocks`, devolvendo
      `SystemPromptBlock(text=..., cache=False)` com data e estado do perfil.
      Few-shot **só de tom, objeção e ordem de qualificação** — nunca de cotação.
- [ ] **Passo 4:** `pytest tests/nucleo/test_prompt.py -v` → PASS
- [ ] **Passo 5:** `git commit -m "feat(agent): system estático cacheável + bloco volátil"`

---

## Task 3 — `qualify_lead`

**Files:** Create `app/agent/tools.py` · Test `tests/nucleo/test_qualificacao.py`

Assinatura **congelada** — o `ReliabilityEval` da frente de Dados depende dela:

```python
qualify_lead(idade=None, veiculo_ano=None, cep=None,
             data_inicio=None, plano_id=None) -> str
```

- [ ] **Passo 1: teste que falha**

```python
def test_grava_parcial_e_devolve_o_que_falta(conv):
    r = qualify_lead(idade=35, veiculo_ano=2019)
    assert "cep" in r and "data_inicio" in r and "plano_id" in r
    assert perfil(conv).idade == 35

def test_cep_de_sete_digitos_nao_e_aceito(conv):
    # "7000-000" seria lido pela API como prefixo "70" e perderia o agravo de 30%
    qualify_lead(cep="7000-000")
    assert perfil(conv).cep is None
    assert perfil(conv).tentativas_extracao["cep"] == 1

def test_plano_invalido_nao_vira_essencial_calado(conv):
    qualify_lead(plano_id="ouro")
    assert perfil(conv).plano_id is None

@pytest.mark.parametrize("dito,iso", [
    ("2026-10-17",        date(2026, 10, 17)),
    ("17/10/2026",        date(2026, 10, 17)),
    ("dia 17 de outubro", date(2026, 10, 17)),
    ("dia 1º do mês que vem", PRIMEIRO_DO_MES_SEGUINTE),
])
def test_data_inicio_normaliza_para_iso(conv, dito, iso):
    """O campo mais arriscado dos cinco. API-COTACAO §7.1: 'como a data vem de
    texto livre, é o erro nosso mais provável' — e ele vira 400 na /quote, que
    NÃO retenta. Task 4 não cobre isto porque o lead do dataset nunca informa
    data de início, então é aqui ou em lugar nenhum."""
    qualify_lead(data_inicio=dito)
    assert perfil(conv).data_inicio == iso

@pytest.mark.parametrize("dito", ["semana que vem", "quando der", "urgente"])
def test_data_ambigua_fica_pendente_em_vez_de_chutar(conv, dito):
    qualify_lead(data_inicio=dito)
    assert perfil(conv).data_inicio is None      # repergunta, não adivinha

def test_data_no_passado_nao_e_aceita(conv):
    # a API aceita sem reclamar; a validação tem que ser nossa
    qualify_lead(data_inicio="2020-03-10")
    assert perfil(conv).data_inicio is None

def test_origem_do_campo_e_guardada_mascarada(conv):
    frase, pii = frase_do_lead(seed=5)
    qualify_lead(idade=35, origem=frase)
    assert perfil(conv).origem["idade"]        # existe
    assert not any(v in str(perfil(conv).origem) for v in pii.values())
```

- [ ] **Passo 2:** `pytest tests/nucleo/test_qualificacao.py -v` → FAIL
- [ ] **Passo 3:** implementar como write-back: valida contra `LeadProfile`, grava em
      `conversations`, incrementa `tentativas_extracao` no campo rejeitado, devolve
      texto curto com `campos_faltantes`. **Não levanta exceção em campo inválido** —
      devolve o campo como pendente, para o modelo reperguntar.
- [ ] **Passo 4:** `pytest tests/nucleo/test_qualificacao.py -v` → PASS
- [ ] **Passo 5:** `git commit -m "feat(tools): qualify_lead com write-back e normalização"`

---

## Task 4 — Extração contra texto real do dataset

**Files:** Test `tests/nucleo/test_extracao_dataset.py`

O dataset é gabarito legítimo **aqui** — `lead_idade_informada` e o ano em
`veiculo_texto` são colunas de verdade. Não é few-shot de cotação; é caso de teste.

- [ ] **Passo 1: teste que falha**

```python
@pytest.mark.parametrize("molde,esperado", [
    ("Tenho 35 anos, cep {cep}, cpf {cpf}",   {"idade": 35}),
    ("e um Sandero 2022",                     {"veiculo_ano": 2022}),
    ("Toyota Corolla, ano 2008",              {"veiculo_ano": 2008}),
    ("Cpf {cpf}, tenho 62 anos, cep {cep}",   {"idade": 62}),
])
def test_extrai_de_texto_torto(molde, esperado):
    """O CPF e o CEP vêm do gerador semeado — nenhum literal de PII no repositório
    (docs/planos/00-fixtures-pii.md). O CEP esperado é derivado do gerado."""
    pii = gerar_pii(seed=11)
    fala = molde.format(**pii)
    if "{cep}" in molde:
        esperado["cep"] = re.sub(r"\D", "", pii["cep"])
    assert extraido(fala) | esperado == extraido(fala)
```

Note que **marca e modelo não são medidos** — `veiculo_texto` contém informação que o
lead nunca disse ("Renault Sandero 2022" na coluna, "e um Sandero 2022" na fala), e
penalizar o agente por isso mede o ruído do gabarito. Os três campos medidos são
**idade, `veiculo_ano` e CEP**.

- [ ] **Passo 2:** rodar → FAIL onde a extração estiver frágil
- [ ] **Passo 3:** ajustar prompt e/ou normalizadores até passar
- [ ] **Passo 4:** rodar → PASS
- [ ] **Passo 5:** commit

---

## Task 5 — Fechar a fatia

- [ ] **Passo 1:** `python -m app.console`, informar os cinco campos fora de ordem e em
      linguagem torta; conferir que o agente pergunta só o que falta e **pergunta a data
      de início** — sem ela o pro-rata não existe na fatia 3
- [ ] **Passo 2:** `SELECT idade, veiculo_ano, cep, data_inicio, plano_id FROM conversations;`
- [ ] **Passo 3:** `pytest tests/nucleo -q` verde
- [ ] **Passo 4:** relatar pronto / comando / saída / fora de escopo
- [ ] **Passo 5:** `git commit -m "chore: fatia 2 fechada — conversa útil"`
