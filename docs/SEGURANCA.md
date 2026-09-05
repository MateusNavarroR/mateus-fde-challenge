# Passe de segurança — o que foi procurado, o que foi achado, o que foi feito

Este repositório será público. Este documento é o registro do passe de segurança que
antecedeu a publicação: **o que cada varredura apontou, o que virou correção, o que
virou risco aceito, e o que era falso positivo.**

Os falsos positivos estão aqui de propósito. Uma lista que só mostra o que o autor quis
explicar não é auditoria — é apresentação.

---

## Como foi executado, com honestidade sobre o método

Os plugins pedidos estão instalados e habilitados (`insecure-defaults`,
`static-analysis`, `variant-analysis`, `supply-chain-risk-auditor`, `sharp-edges`,
`audit-context-building`, `security-guidance`), mas **não estavam registrados como
skills invocáveis na sessão** — a chamada por nome falhou com `Unknown skill`.

O que foi feito então: a definição de cada plugin foi lida em disco
(`~/.claude/plugins/cache/…/SKILL.md`) e **a metodologia dela foi executada à mão**, com
as buscas que ela prescreve. Os achados abaixo são reais e verificados; o que não posso
afirmar é que a ferramenta rodou como ferramenta. Registro assim porque "rodei o
plugin X" quando não rodei é exatamente o tipo de alegação que este repositório recusa.

---

## Contexto de auditoria

| | |
|---|---|
| **Superfície pública** (sem autenticação) | `GET /api/health`, `POST /api/conversations`, WebSocket `/api/chat/{id}` |
| **Superfície de operação** (`exigir_admin`) | as demais rotas `/api/*` e o WebSocket `/api/events` |
| **Fronteiras de confiança** | ① a mensagem do lead (dado, nunca instrução) · ② a resposta do modelo (nunca fonte de preço) · ③ a `/quote` legada (nunca fonte de verdade sobre erro nosso) |
| **Ativos** | `ANTHROPIC_API_KEY`; PII do lead; o histórico de conversas; a conta de tokens |
| **Bind** | tudo em `127.0.0.1`. É o controle que de fato protege no caminho padrão. |

---

## Achados corrigidos

### 1 · `APP_ENV` falhava para o lado aberto — `insecure-defaults`

**Era:** `os.getenv("APP_ENV", "dev") == "dev"`, em dois lugares. O modo `dev` (a) expõe
`/docs`, `/redoc` e `/openapi.json` e (b) **remove a flag `Secure` do cookie de sessão**.
O `Dockerfile` define `APP_ENV=prod`, então a imagem entregue estava correta.

**Por que ainda é achado:** "a configuração de produção sobrescreve" é uma das
racionalizações que o passe de `insecure-defaults` lista para recusar. Quem rodasse
`uvicorn app.main:app` fora da imagem — desenvolvimento, outro orquestrador, um `systemd`
— ficava com documentação aberta e cookie sem `Secure`, **sem nenhum aviso**.

**Feito:** o padrão passou a ser `prod`; `dev` é opt-in explícito. O pior caso de um erro
de configuração deixou de ser "superfície aberta em produção" e passou a ser "a tela de
documentação não abre em desenvolvimento". Testes em `test_auth.py`, cobrindo ausência,
vazio e valores arbitrários.

**Efeito colateral revelador:** dois testes existentes quebraram, porque dependiam do
default inseguro para o `TestClient` (que fala HTTP) receber o cookie. Um teste que
depende de um default inseguro é um teste que impede corrigi-lo — passaram a declarar
`APP_ENV=dev` e a checar o contraste entre os dois modos.

### 2 · Sem limite de taxa na superfície pública — `sharp-edges`

**Era:** `POST /api/conversations` e o WebSocket do chat são públicos por desenho, e
**cada mensagem do chat é uma inferência do modelo**. Sem limite, quem alcança a porta
esgota a `ANTHROPIC_API_KEY` sem precisar de nenhum bug.

**Feito:** `app/ratelimit.py`, token bucket em memória, por origem. 20 conversas/min e
30 mensagens/min. Sem dependência nova — um Redis só para contar requisições
contradiria o compromisso de subir com um comando.

Três decisões que valem registro:
- **token bucket, não janela fixa**: janela fixa deixa passar o dobro do limite na virada;
- **a chave é `request.client`, nunca `X-Forwarded-For`**: um cabeçalho que o cliente escreve daria limite infinito a quem o variasse;
- **o chat avisa em vez de descartar em silêncio**: um lead olhando para uma conversa que parou de responder é pior que um "me dá um segundo".

**Limite conhecido:** com mais de uma réplica, cada processo tem o seu contador. Está em
*Limitações* no README.

### 3 · `ADMIN_TOKEN` em `localStorage` — `variant-analysis`

**Era:** a tela de 401 oferece colar o `ADMIN_TOKEN`, que ia para `localStorage` e
seguia como cabeçalho. É a credencial **mais forte** do sistema — o backend a aceita
mesmo com login configurado — guardada no lugar **menos** protegido, enquanto a sessão
que ela contorna usa cookie `httpOnly`.

**Feito, parcialmente:** passou a `sessionStorage` (morre com a aba, em vez de ficar em
disco) e o texto da tela recomenda `ADMIN_USER`/`ADMIN_PASSWORD` para uso no navegador.
**Continua legível por XSS** — está registrado como risco aceito abaixo.

### 4 · A varredura de PII produzia falso positivo em binário — `static-analysis`

**Era:** a varredura decodificava PNG e parquet com `errors="ignore"` e regexava os
bytes. Acusou como e-mail uma sequência de sete bytes comprimidos, com letra não-ASCII no meio, dentro de uma captura de tela.

**Por que importa:** um falso positivo numa varredura de segurança treina quem lê o
relatório a ignorá-la. É pior que inofensivo.

**Feito:** em binário, a busca passou a ser sobre as sequências de ASCII imprimível,
como o `strings(1)`. Um teste planta PII dentro de um binário sintético e exige que ela
continue sendo pega — a troca não podia custar a capacidade.

### 5 · `prompt injection` era invariante sem teste

**Era:** `CLAUDE.md` 6 afirma *"prompt injection é caso de teste"*. Não havia nenhum.
Uma promessa do repositório sem código que a sustentasse.

**Feito:** `tests/nucleo/test_injecao.py`, com seis famílias de carga (sobrescrita,
autoridade forjada, exfiltração, preço direto, delimitador falso, troca de papel) em
duas metades — determinística sobre o guardrail e viva contra o modelo real. A viva
passou nas seis: nenhum valor monetário chegou ao lead.

O teste é explícito sobre o que **não** afirma: não se verifica que o modelo "resistiu",
porque isso não é verificável. Verifica-se o que saiu pelo canal.

### 6 · Literais de PII sintética no código — checklist de repositório público

**Era:** CEPs de exemplo escritos à mão em oito arquivos de teste, dois scripts e um
comentário. Sintéticos, mas `CLAUDE.md` 13b diz "nenhum literal, nem sintético".

**Feito:** todos passaram a ser construídos (`cep_de("07")`, ou montagem por prefixo nos
scripts). Um caso divertido: a varredura acusou o **README deste passe** por citar o CEP
da Avenida Paulista ao descrever o próprio achado.

---

## Riscos aceitos

### `ADMIN_TOKEN` continua legível por XSS

Mitigado para `sessionStorage`, não resolvido. A saída correta seria trocá-lo por cookie
`httpOnly`, como a sessão de login faz — **não foi feito porque a sessão é assinada com
chave derivada da credencial, e no modo só-token não existe credencial de onde
derivá-la**. Trocar isso é cirurgia na autenticação, e cirurgia na autenticação sem
revisão humana é como se criam falhas piores que a original.

Recomendação registrada no README: `ADMIN_USER`/`ADMIN_PASSWORD` para navegador,
`ADMIN_TOKEN` só para CI e `curl`.

### O id da conversa é uma capacidade

O WebSocket do chat não autentica: quem tem o id lê a conversa inteira, incluindo o
replay do histórico. O id tem 64 bits de aleatoriedade — adivinhar é inviável; o risco é
vazamento (navegador compartilhado, captura de tela, URL colada).

É consequência direta de o chat ser **anônimo**, que é o desenho do produto: um lead não
faz login para pedir cotação. Alternativas — token por link, expiração — foram
consideradas e ficam fora do escopo declarado.

### PII sintética no histórico do Git

O histórico inteiro (34 commits) foi varrido por chave, token e PII. **Zero segredos.**
Há CEPs de exemplo e um CPF placeholder inválido em commits antigos — nenhum dado de
pessoa real, em nenhum commit. O HEAD está limpo pela regra estrita.

Reescrever o histórico para remover endereços públicos invalidaria todas as referências
de commit da documentação, em troca de nenhum ganho de privacidade real.

---

## Falsos positivos

### `openai` como dependência morta — e a remoção quase virou commit

**A hipótese:** nenhum arquivo do projeto importa `openai`, o README declara que só
Anthropic e Ollama são validados, e a verificação — importar `agno.models.anthropic` com
o módulo ausente — passou. Dependência que ninguém usa é superfície de ataque de graça.
A linha foi removida do `pyproject.toml` e o lock refeito.

**Estava errada.** O caminho **Ollama**, um dos dois providers validados, importa
`agno.models.ollama.responses` → `agno.models.openai.open_responses`, que levanta
`ImportError` sem o SDK. O erro da primeira verificação foi checar o provider errado —
e o `pyproject.toml` **já tinha um comentário** explicando isso, que eu não li antes de
agir.

**Feito:** revertido. `tests/nucleo/test_dependencias.py` guarda a conclusão, rodando o
teste em **subprocesso** — no processo do pytest o `openai` já está em `sys.modules` por
importações anteriores, e qualquer bloqueio em memória mede a ordem de importação em vez
da dependência real. Foi assim que a primeira verificação se enganou.

### `except Exception: pass` no laço de ping do admin

`app/channels/web.py`. Parece erro engolido; é o encerramento normal de um WebSocket
fechado pelo cliente, e o `finally` remove o socket do conjunto. Sem achado.

### `.env.example` ignorado pelo `.gitignore`

`.gitignore` tem `.env.*`, que casaria com `.env.example` — e o README manda copiá-lo.
Há um `!.env.example` logo abaixo, e o arquivo está versionado. Sem achado.

### A semente do replay acusada como CEP

A varredura de PII acusou a semente padrão do replay: ela é uma data compacta, e
oito dígitos seguidos casam com o regex de CEP. Falso positivo real da varredura, corrigido na origem — a semente virou constante
nomeada em `qa/replay/amostra.py`, escrita em duas partes concatenadas, com o motivo no
comentário.

**Este documento levou a mesma reprovação**, por citar os literais ao descrever os
achados — e a varredura estava certa. Não há lista de exceções nem para quem a escreveu:
o texto foi reescrito para descrever as formas em vez de reproduzi-las.

---

## Checklist de repositório público

| Item | Estado |
|---|---|
| Segredo ou token em **qualquer** commit do histórico | ✅ nenhum, 34 commits varridos |
| Caminho absoluto de máquina | ✅ nenhum |
| PII crua em código, fixture, log, captura ou artefato | ✅ nenhuma — varredura na suíte, sem lista de exceções |
| PII nos `ai-logs` exportados | ✅ redação **na escrita**; o export aborta se um segredo sobreviver |
| Nome de cliente ou projeto alheio | ✅ nenhum |
| CORS com origem explícita | ✅ **não há CORS**: SPA e API na mesma origem, então não há `allow_origins` para errar |
| Rate limit no que é público | ✅ `app/ratelimit.py` |
| Teste de injeção | ✅ `tests/nucleo/test_injecao.py`, determinístico e vivo |
| `/docs` e `/redoc` fora de dev | ✅ e agora com o default do lado seguro |
| Bind em `127.0.0.1` | ✅ todas as portas, inclusive o profile `debug` |
| SQL montado por string | ✅ nenhum — SQLAlchemy em todo o acesso |
| `eval`, `exec`, `pickle`, `os.system` | ✅ nenhum em `app/` |
| `yaml.load` inseguro | ✅ `safe_load` |
| `dangerouslySetInnerHTML` | ✅ nenhum — o renderizador de Markdown constrói nós React |
| Lock de dependências com hash | ✅ 65 pacotes, 975 hashes |
