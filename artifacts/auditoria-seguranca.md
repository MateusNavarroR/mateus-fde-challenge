# Auditoria de segurança — passe 2 (pós `docs/SEGURANCA.md`)


> ## Estado deste relatório
>
> **Todos os achados abaixo foram corrigidos.** Este documento é mantido como está —
> com o veredito original e os achados na forma em que foram encontrados — porque um
> relatório de auditoria reescrito depois da correção deixa de ser auditoria e vira
> apresentação. O que ele registra é o que existia no momento em que foi escrito.
>
> O que mudou desde então está no histórico do Git (commits `71154f6` e seguintes) e, para cada achado,
> num teste que o trava. Os dois achados de severidade alta — a chave de sessão sem `scrypt` e o WebSocket `/api/events` aberto a anônimos — foram reproduzidos, corrigidos e verificados na aplicação: anônimo recusado, autenticado conectado. O achado baixo (URL de banco no stdout) sai mascarado.


**Veredito: NÃO apto a publicar sem correção.** Dois achados de severidade alta —
um enfraquecimento criptográfico na assinatura da sessão de admin e uma rota de
operação sem controle de acesso equivalente ao `exigir_admin` — foram introduzidos
depois do passe anterior e não têm teste que os cubra. Nenhum deles envolve PII
vazada nem segredo no repositório: a regra máxima de "nada versionado vaza" segue de
pé. O que falha é a autorização/autenticação da área de operação em uma configuração
que o próprio README recomenda.

---

## Método, com honestidade

Os plugins pedidos (`insecure-defaults`, `static-analysis`, `variant-analysis`,
`supply-chain-risk-auditor`, `sharp-edges`, `audit-context-building`,
`differential-review`, `security-guidance`) estão habilitados em
`~/.claude/settings.json`, mas **não apareceram na lista de skills invocáveis desta
sessão** — mesma situação registrada no passe anterior (`docs/SEGURANCA.md` linhas
12–24). Não tentei invocá-los por nome porque eles não constavam na listagem de
skills disponíveis fornecida na sessão; teria sido uma chamada às cegas.

O que foi feito: localizei o marketplace git configurado
(`extraKnownMarketplaces.trailofbits` em `~/.claude/settings.json`, apontando para
`/home/mateus/Documents/YAITEC/securitytest/skills`), li cada `SKILL.md`
correspondente em disco e **executei a metodologia à mão**:

- **insecure-defaults**: procurei fallback inseguro em variável de ambiente e
  segredo hardcoded (`os.getenv(...) or "default"`, `ADMIN_TOKEN`/`ADMIN_PASSWORD`
  sem default, `APP_ENV`). Nada novo desde o passe anterior.
- **sharp-edges**: revisei a superfície nova (`/mensagens`, `/traces`, o WebSocket de
  eventos) por design que convida ao erro — foi assim que a divergência de
  autorização do `/api/events` apareceu.
- **variant-analysis**: usei o achado do `/api/events` como semente e procurei toda
  outra rota que reimplementasse a checagem de admin em vez de usar `exigir_admin`
  (`grep -rn "admin_exigido\|exigir_admin" app/`) — só essa rota reimplementa.
- **audit-context-building**: li `app/auth.py` linha a linha, junto do diff do commit
  que o alterou (`git show 93fcb1b -- app/auth.py`), para entender a troca de
  derivação de chave antes de julgar se ela é regressão.
- **differential-review**: `git log --oneline 9639216..HEAD` para isolar exatamente o
  que entrou depois do passe anterior, e tratei cada commit da lista do prompt como
  unidade de revisão.
- **supply-chain-risk-auditor**: `git diff 9639216..HEAD -- pyproject.toml
  web/package.json` — sem dependência nova desde o passe anterior, então não havia o
  que auditar.
- **static-analysis / security-guidance**: grep dirigido por padrão (segredo em
  string, `eval`/`exec`/`pickle`, chave impressa em log) sobre o código novo.

---

## Achados

### 1 · ALTA — chave de assinatura da sessão de admin virou crackável offline por hash rápido

**Onde:** `app/auth.py:150-165` (`_chave_de_sessao`), introduzida no commit `93fcb1b`
(`fix(sessao,handoff): sessão sobrevive ao restart...`), que é justamente o commit que
o prompt desta auditoria pede para reavaliar (item 4).

**O que mudou, com o diff exato:**

```python
# ANTES (commit 5875485, passe anterior)
@property
def chave_de_sessao(self) -> bytes:
    return hashlib.sha256(b"autoseguro/sessao/v1|" + self.salt + self.digest).digest()
    # self.digest = hashlib.scrypt(senha, salt=self.salt, N=2**14, r=8, p=1)
    # self.salt   = secrets.token_bytes(16), sorteado a cada boot, nunca sai do processo

# DEPOIS (commit 93fcb1b, atual)
def _chave_de_sessao(usuario: str, senha: str) -> bytes:
    return hashlib.sha256(
        b"autoseguro/sessao/v2|" + usuario.encode("utf-8") + b"|" + senha.encode("utf-8")
    ).digest()
```

**Por que é explorável.** O cookie de sessão (`app/auth.py:186-190`, `emitir_sessao`)
é `base64(usuario|expiração) + "." + base64(HMAC-SHA256(chave_de_sessao, corpo))`. O
corpo **não é secreto** — é texto legível, só codificado em base64. Antes, calcular
`chave_de_sessao` exigia conhecer `self.salt` (16 bytes aleatórios que nunca saem do
processo, nem vão para o cookie, nem para lugar nenhum observável) **e** rodar
`scrypt` (N=2¹⁴, r=8 — dezenas de ms, deliberadamente caro). Um atacante que
capturasse um cookie válido por qualquer via não tinha como reproduzir a chave nem
offline, porque faltava o salt.

Agora a chave é uma função determinística e pública na forma —
`SHA-256("v2|" + usuario + "|" + senha)` — de duas strings, sendo o `usuario` o
próprio texto legível do corpo do cookie. Quem obtém **um único cookie de sessão
válido** (não precisa nem do `ADMIN_PASSWORD`) pode testar candidatos de senha
inteiramente offline, sem o servidor, usando SHA-256 — uma função rápida (bilhões de
tentativas por segundo em GPU) — em vez do `scrypt` caro que protege a conferência de
login. Ao achar a senha, o atacante não só forja cookies novos como **recupera a
senha de administração de verdade**, porque a mesma `senha` alimenta o `scrypt` do
login (`Credencial.confere`, `app/auth.py:113-121`). Isso derruba inteiramente a
razão de ser do `scrypt` (RFC 7914, `_SCRYPT` em `app/auth.py:56-58`): ele defende a
tentativa de login online, mas deixou de defender a única coisa que hoje depende
apenas da senha em texto puro sem custo computacional por tentativa.

**Como o cookie vazaria, dado que é `httpOnly`.** Não é vetor de XSS (JS não lê
cookie `httpOnly`) — é o vetor que a documentação já trata como risco aceito para o
id de conversa (`docs/SEGURANCA.md` linha 140-148): captura de tela, DevTools aberto
e compartilhado, exportação de perfil do navegador, log de proxy/observabilidade que
grave `Cookie:`, ou qualquer acesso à máquina/rede sem TLS terminal (o compose não
configura TLS; bind em 127.0.0.1 protege da rede, não de quem já tem acesso à
máquina ou está atrás do mesmo proxy reverso em produção).

**Correção proposta.** Manter a chave estável entre reinícios (a propriedade que a
mudança buscava) e ao mesmo tempo cara de atacar offline: derivar com `scrypt`
usando um salt **determinístico mas não public-facing**, por exemplo
`salt = sha256(b"autoseguro/sessao/salt|" + usuario)`, em vez de hashear a senha
crua com SHA-256 direto:

```python
def _chave_de_sessao(usuario: str, senha: str) -> bytes:
    salt = hashlib.sha256(b"autoseguro/sessao/salt/v3|" + usuario.encode()).digest()
    return hashlib.scrypt(senha.encode("utf-8"), salt=salt, **_SCRYPT)
```

Isso preserva: estabilidade entre boots (determinístico), invalidação ao trocar
usuário/senha, e reencaminha o atacante para o mesmo custo de `scrypt` por tentativa
— o mesmo nível de proteção que a conferência de login já tem.

**Não testado.** `tests/nucleo/test_auth.py` tem "três testes, incluindo o negativo"
para a propriedade "sobrevive a reinício / muda com a credencial" (mencionado na
mensagem do commit), mas nenhum deles mede o custo computacional de recuperar a
senha a partir da chave — o que é esperado, porque isso não é uma propriedade
funcional testável por unit test convencional; é uma propriedade de **taxa de
ataque**, e nenhum teste captura isso além de revisão manual.

---

### 2 · ALTA — `WS /api/events` não reconhece a sessão de login, só o `ADMIN_TOKEN`

**Onde:** `app/channels/web.py:272-289` (função `eventos`).

```python
@app.websocket("/api/events")
async def eventos(ws: WebSocket) -> None:
    cfg = get_settings()
    apresentado = ws.query_params.get("token") or ""
    if cfg.admin_exigido and not hmac.compare_digest(
        apresentado.encode("utf-8"), (cfg.admin_token or "").encode("utf-8")
    ):
        await ws.close(code=4401)
        return
    await ws.accept()
    ...
```

`cfg.admin_exigido` é `admin_token is not None` (`app/config.py:122-124`) — **não**
leva em conta `login_configurado()` (`ADMIN_USER`/`ADMIN_PASSWORD`, `app/auth.py`).
Toda rota REST de operação usa `Depends(exigir_admin)`
(`app/main.py:156,166,180,201,216,225,237,249,312`), que checa **os dois** mecanismos
na ordem certa (`app/auth.py:263-291`: sessão OU token quando login está configurado;
só token quando não está). Este WebSocket é a única superfície de operação que
reimplementa a checagem em vez de reusar `exigir_admin`, e reimplementou só metade
dela.

**Consequência concreta.** Na configuração que o próprio projeto recomenda para
instalação que abre navegador — `ADMIN_USER` + `ADMIN_PASSWORD` **sem**
`ADMIN_TOKEN` (README linhas 695-696: *"Recomendação: use `ADMIN_USER`/`ADMIN_PASSWORD`
em qualquer instalação que abra o navegador, e reserve `ADMIN_TOKEN` para CI e
`curl`"*) — `cfg.admin_exigido` é `False`, a condição do `if` nunca dispara, e
`/api/events` aceita **qualquer conexão, sem cookie, sem token, sem sessão**. Nessa
configuração, todas as rotas REST de operação exigem login corretamente; só o
WebSocket de eventos fica aberto.

O que trafega nele hoje: `handoff.created` — `{"id", "conversation_id", "trigger"}`
(`app/agent/turno.py:253-255`) — e `handoff.updated` — `{"id"}`
(`app/main.py:320`). O campo que importa é `conversation_id`: o próprio
`docs/SEGURANCA.md` (linhas 140-148) trata o id de conversa como uma **capacidade**
cuja segurança depende de ser impossível de adivinhar (64 bits de aleatoriedade) e
não de ser vazada. Um `/api/events` sem autenticação **distribui essas capacidades
de graça** para qualquer um que conecte, no exato momento em que a conversa vira
`encaminhado` — convertendo "adivinhar é inviável" em "não precisa adivinhar, é
anunciado". Quem tiver o id pode entrar direto no WebSocket público
`/api/chat/{conversation_id}` e ler a conversa inteira, PII incluída.

**Diferença marcante entre comentário e comportamento real.** O teste de frontend
`tests/web/unit/console.test.tsx:130-131` documenta a premissa — *"`/api/events`
exige sessão"* — mas essa premissa nunca é exercitada contra o backend real: o teste
só verifica que o **cliente** não tenta abrir o socket quando não autenticado; ele
não abre um servidor real sem `ADMIN_TOKEN` e com login configurado para confirmar
que o backend recusaria. `tests/nucleo/test_auth.py:459-491`
(`test_rest_e_websocket_concordam_sobre_o_mesmo_token`) é o teste mais próximo e
cobre exatamente a simetria REST/WS — mas só para o eixo do token; nunca configura
`ADMIN_USER`/`ADMIN_PASSWORD` no mesmo teste. É um ponto cego real, não apenas
teórico.

**Correção proposta.** Trocar a checagem manual por uma que também aceite sessão
válida — o mais simples é aceitar o cookie no handshake do WebSocket (o navegador
manda cookies no handshake, diferente do cabeçalho custom) e reusar
`sessao_valida()`:

```python
apresentado = ws.query_params.get("token") or ""
cookie = ws.cookies.get(auth.COOKIE_SESSAO)
autorizado = (
    (auth.login_configurado() and auth.sessao_valida(cookie))
    or (cfg.admin_exigido and hmac.compare_digest(
        apresentado.encode("utf-8"), (cfg.admin_token or "").encode("utf-8")))
)
if not autorizado and (auth.login_configurado() or cfg.admin_exigido):
    await ws.close(code=4401)
    return
```

E um teste que configure `ADMIN_USER`/`ADMIN_PASSWORD` (sem `ADMIN_TOKEN`) e
verifique que uma conexão sem cookie de sessão é recusada.

---

### 3 · BAIXA — `qa/replay/__main__.py` imprime a URL de banco crua no stdout

**Onde:** `qa/replay/__main__.py:136-139`.

```python
url_dos_evals = args.evals_db or get_settings().database_url
db_evals = db_de_evals(url_dos_evals)
alvo = "o mesmo banco do replay" if args.evals_db is None else args.evals_db
print(f"\nevals .......... ligados; gravam em ai.eval_runs de {alvo}")
```

Quando `--evals-db` é passado (o próprio `--help` do comando recomenda apontar para
"o banco da aplicação" quando o replay roda isolado), a URL completa — que em Postgres
inclui usuário e senha na forma `postgres://user:pass@host/db` — é impressa
literalmente no terminal. É uma ferramenta de operador/CI, não uma rota HTTP, e o
valor já veio de um argumento de linha de comando que o próprio operador digitou
(portanto já está no `history` do shell de qualquer forma) — por isso a severidade é
baixa, não média. Mas em CI, saída de `print` costuma ir para log persistente e
pesquisável, o que a credencial da URL não deveria fazer.

**Correção proposta:** mascarar a URL antes de imprimir (`re.sub(r"://[^@]+@",
"://***:***@", alvo)`), como o resto do sistema já faz para PII.

---

### Observação sem severidade — evento `quote.attempt` documentado e nunca emitido

`app/channels/web.py:150` cita `quote.attempt` como um dos tipos que `publicar_evento`
carrega; `grep -rn '"quote.attempt"' app/` não encontra nenhum emissor. Não é achado
de segurança — é o mesmo padrão de deriva de documentação que o próprio
`test_publicar_evento_e_de_fato_chamado_pelo_backend` (`tests/nucleo/test_auth.py:505-528`)
foi escrito para pegar, só que para `handoff.created`/`handoff.updated`, não para
este terceiro tipo. Registrado para quem for revisar o painel de eventos depois.

---

## O que verifiquei e estava correto

- **Item 1 (`POST /mensagens`)** — `app/main.py:244-305`: exige `exigir_admin`
  (`app/main.py:249`), só aceita em `state == "encaminhado"` com 409 caso contrário
  (`app/main.py:280-284`), grava com `autor="operador"` (`app/main.py:286-288`), e o
  texto passa por `mascarar()` incondicionalmente em `repo.gravar_mensagem`
  (`app/persistence/repo.py:142`) — não há bypass por parâmetro nem por tipo de
  autor.
- **Item 2 (`GET /traces`)** — `app/api/consultas.py:242-318`: `_limpar()`
  (linhas 282-290) mascara recursivamente `dict`, `list` e `str`, então campo
  aninhado dentro de `tool_args` é coberto. `resultado` também passa por
  `mascarar()` (linha 302). O que **não** é mascarado, por design e corretamente: os
  metadados de execução (`nome`, `duracao_ms`, `erro`, `modelo`, `provider`,
  contagens de token) — nenhum deles carrega texto livre do lead. Testei mentalmente
  o caso "PII dentro de uma lista dentro de um dict dentro de `tool_args`" e a
  recursão cobre.
- **Item 3 (sockets por conversa, `_chats`)** — `app/channels/web.py:96-121`: é um
  `set` por conversa (permite duas abas), remove sockets mortos ao falhar o envio; a
  falha ao enviar é silenciosa por design documentado (o lead recebe no replay do
  `hello`). Não vaza para outra conversa: o push é sempre por `conversation_id`
  explícito.
- **Item 5 (`/simulador` fora do login)** — confere com o próprio backend: `POST
  /api/conversations` e `WS /api/chat/{id}` são públicos por desenho
  (`docs/SEGURANCA.md` linha 31), então proteger a tela no cliente seria teatro. O
  comentário em `web/src/App.tsx:95-104` é coerente com isso, e
  `console.test.tsx:129-138` prova que o simulador **não** abre o socket de operação
  (`/api/events`) — reduzindo, aliás, a superfície do achado 2 a quem acessa a URL
  do WebSocket diretamente, não a quem só usa a tela do simulador.
- **Item 6 (histórico local em `localStorage`)** — `web/src/chat/sessao.ts:47-115`:
  fica só no navegador do próprio lead, nunca é enviado ao servidor nem lido de
  volta por outra rota; o rótulo trunca o resumo em 38 caracteres
  (`web/src/chat/sessao.ts:135`). É um risco de máquina compartilhada, já coberto
  pela mesma classe de risco aceito do id de conversa como capacidade — não é achado
  novo.
- **Item 7 (`qa/replay/evals.py`)** — além do achado 3 (impressão da URL), o restante
  é coerente: `db_de_evals` (linha 45-54) só é chamado quando `--evals` está
  explícito, é uma ferramenta de linha de comando sem rota HTTP correspondente, e a
  gravação exige `--rodar`.
- **Item 8 (migração `0006`)** — `db/migrations/0006_lead_aceitou_cotacao.sql`: só
  amplia dois `CHECK` com literais fixos; sem SQL dinâmico, sem entrada de usuário.
- `.env` não está versionado (`git ls-files | grep '\.env'` só retorna
  `.env.example`); `.claude/` não está versionado.
- Bind em `127.0.0.1`: confirmado tanto no `docker-compose.yml`
  (linhas 55, 93, 100, 121) quanto ao vivo via `docker ps` — os contêineres deste
  repositório (`mateus-fde-challenge-app-1`, `mateus-fde-challenge-db-1`) publicam
  só em `127.0.0.1`; os demais contêineres na máquina pertencem a outros projetos e
  estão fora de escopo.
- `tests/nucleo/test_repo_publico.py` passa (9 passed, 2 skipped) rodando de fato
  contra o estado atual do repositório.
- Nenhuma dependência nova entrou desde o commit do passe anterior
  (`git diff 9639216..HEAD -- pyproject.toml web/package.json` vazio) — nada a
  auditar em `supply-chain-risk-auditor` além do que já foi coberto.
- Varredura de segredo no histórico completo (50 commits) sobre padrões de chave
  Anthropic/AWS/GitHub/chave privada: nenhum literal real, só valores sintéticos de
  teste (a linha da chave da Anthropic preenchida com um placeholder, `=do-arquivo`).

---

## Falsos positivos (o que investiguei e não é achado)

- **Screenshots em `artifacts/vistoria/*.png` "contêm PII crua"** — a hipótese
  inicial era que capturas de tela recentes pudessem ter escapado da varredura
  automatizada, já que ela procura ASCII imprimível em binário e uma imagem PNG
  comprimida não expõe o texto renderizado como bytes legíveis (o teste captura
  segredo em *metadado*/chunk de texto, não em pixel). Abri visualmente
  `artifacts/vistoria/trace.png` e `artifacts/vistoria/04-detalhe-conversa.png`: o
  CEP aparece mascarado na tela (`58••••-•••`, `[CEP]`) nas duas — a aplicação
  mascara antes de renderizar, então não há PII no pixel também. **Sem achado**, mas
  registro a limitação do método: a varredura automatizada por `strings` não prova
  nada sobre o conteúdo *visual* de uma imagem, só sobre texto embutido nela; a
  garantia real aqui vem do mascaramento na origem, não da varredura de binário.
- **`qa/replay/evals.py::db_de_evals` como superfície de conexão a banco arbitrário**
  — a hipótese era que aceitar uma URL de banco por argumento fosse, em si, um
  problema de superfície. Não é: é uma ferramenta de linha de comando local, sem
  rota HTTP, sem input de rede não confiável — o "atacante" seria quem já tem
  acesso de shell à máquina que roda o replay, que já tem acesso a tudo. O achado
  real correlato (nº 3) é só a impressão em texto claro, não a aceitação do
  argumento em si.
- **`_chats` (dict global por conversa) como vazamento entre conversas** — cogitei
  que um `set()` global pudesse, por algum caminho, misturar sockets de conversas
  diferentes. `publicar_no_chat` sempre indexa por `conversation_id` explícito
  (`app/channels/web.py:106-121`) e o registro em `registrar_websockets`
  (`app/channels/web.py:196`) usa o `conversation_id` da própria rota. Sem achado.
- **A troca de `chave_de_sessao` de `@property` para função — hipótese de que a
  mudança de forma (não só de fórmula) introduzisse algum outro bug** — comparei o
  diff inteiro do commit `93fcb1b`: a mudança estrutural (de `@property` sem
  argumento para função com `usuario, senha`) é só para poder computar a chave
  **antes** de `senha` ser apagada do processo, o que é a correção certa para o
  problema que o commit resolve. O que é achado é só a fórmula (achado 1), não a
  reestruturação.

---

## O que NÃO consegui verificar

- **Custo real de força bruta do achado 1** — não tenho GPU/benchmark disponível
  nesta sessão para medir quantas tentativas de senha por segundo um atacante
  conseguiria contra `SHA-256("v2|"+usuario+"|"+senha)` neste hardware específico;
  a afirmação de "bilhões por segundo em GPU" é conhecimento geral sobre SHA-256,
  não uma medição feita aqui.
- **Se algum proxy reverso de produção loga cabeçalho `Cookie` ou a URL completa
  passada a `qa/replay`** — não tenho acesso à configuração de infraestrutura de
  produção (fora do escopo desta auditoria de repositório) para confirmar se o
  vetor de captura de cookie do achado 1, ou a impressão da URL do achado 3,
  chegam de fato a algum log persistente fora desta máquina.
- **Reprodução ao vivo do achado 2** — não subi uma segunda instância nem alterei
  variáveis de ambiente do contêiner em execução (fora do escopo de escrita
  permitido, e há avaliações em curso no ambiente atual); a leitura do código
  (`cfg.admin_exigido` definido só por `admin_token`, nenhum outro branch checando
  `login_configurado()` em `eventos()`) é suficiente para afirmar o gap com
  confiança alta, mas não há uma prova de execução capturada nesta sessão.
- **Conteúdo de `.claude/worktrees/agent-*/`** — há pelo menos uma worktree de outra
  frente ativa no disco (`.claude/worktrees/agent-af7af3091aef99dcb/`); não entrei
  nela, por não ser meu escopo e por haver outra sessão possivelmente escrevendo
  ali.
