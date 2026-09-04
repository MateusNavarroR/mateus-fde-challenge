# Etapa de preparação — antes de escrever uma linha de código

> Destino sugerido no repositório da entrega: `ai-logs/00-preparacao.md`.
>
> Este documento registra a **sessão de preparação** que antecedeu o desenvolvimento:
> leitura do desafio, medição do dataset, levantamento de código reaproveitável e as
> decisões de arquitetura — incluindo os pontos em que a recomendação da IA estava
> errada e foi corrigida.
>
> Ele existe porque a sessão original ocorreu sobre repositórios privados meus e não
> pôde ser exportada crua. Este é o registro consolidado e anonimizado dela. As sessões
> de construção, essas sim, estão exportadas integralmente em `ai-logs/`.

---

## 1. Por que uma etapa de preparação

O desafio dá três dias e um enunciado curto. A tentação é começar pelo agente. Comecei
pelo contrário: **ler o código do sistema que eu ia integrar** e **medir os dados que me
deram**, antes de decidir qualquer coisa.

O motivo é o próprio enunciado. Ele avisa que a `/quote` "não responde de primeira toda
vez" e diz que tratar isso é "parte central do desafio". Um aviso desses só é acionável
se você souber *exatamente* como a instabilidade se manifesta — e isso está no código,
não no README.

## 2. Método

| Fonte | O que foi feito |
|---|---|
| `quote-service/app/main.py` e `quote_logic.py` | leitura linha a linha do simulador de falha e do cálculo do prêmio |
| `quote-service/data/plans.json` | extração das regras de preço, recusa, carência e pro-rata |
| `scripts/generate_dataset.py` | leitura do gerador do dataset — foi onde apareceu o achado mais importante |
| `dataset/conversations.parquet` | medição direta: 2.500 conversas, 26.470 mensagens |
| projetos anteriores meus | levantamento de código já em produção que resolvesse partes do problema |

## 3. O que a leitura do código revelou

Detalhamento completo em `API-E-DATASET.md`. Os pontos que mudaram decisão:

**A instabilidade tem três regimes, não dois.** O sorteio acontece *antes* do cálculo:
20% falham na hora (500/502/503), 10% dormem 8 segundos **e depois respondem 200
correto**, o resto responde direto. A consequência prática é contraintuitiva: uma
chamada lenta **não é uma falha**, e um timeout de cliente abaixo de 8 segundos
transforma 10% de sucessos em falhas artificiais.

**Nem todo erro é retentável.** Como o sorteio precede a validação, um `5xx` não diz
nada sobre o payload — é puramente transitório e retry funciona (cada tentativa é um
sorteio independente; três tentativas levam a ~0,8% de falha residual). Já `422` é
regra de negócio e `400` é bug de extração do próprio agente. Retentar esses dois
mascara defeito e queima tempo.

**Há regras que só aparecem em casos específicos**, como o próprio `plans.json` avisa:
carência de 30 dias em roubo e furto (vem sempre na resposta, é fácil de omitir) e
pro-rata do primeiro mês, que **só aparece se o agente enviar `data_inicio` com dia
diferente de 1**. Ou seja: se a qualificação não perguntar a data de início, o lead
nunca fica sabendo quanto paga na primeira fatura.

## 4. O que a medição do dataset revelou

**30% dos leads são incotáveis.** Aplicando as regras de `plans.json` às 2.500
conversas: 280 recusadas por idade ≥76 e 531 por veículo com mais de 20 anos.
O caminho de recusa não é uma exceção rara — é um a cada três atendimentos. Isso o
promoveu de `except` a fluxo de produto com tratamento conversacional próprio.

**Todas as cotações do dataset são inválidas.** O gerador sorteia plano e preço de
forma independente do perfil do lead. Medindo: **42% dos preços são matematicamente
impossíveis** para o plano anunciado (fora até da faixa mais generosa de
multiplicadores), **100%** das mensagens repetem a mesma frase de cobertura — a do plano
Essencial, mesmo quando anunciam Premium — e **nenhuma** menciona carência.

Isso é uma armadilha: usar o dataset como few-shot do turno de cotação ensina o modelo
a alucinar preço. Ele foi usado apenas para tom, taxonomia de objeções, ordem das
perguntas de qualificação, casos de teste de extração de PII e avaliação.

**Sujeira confirmada:** `timestamp` fora de ordem em relação a `message_index` em 99,8%
das conversas (ordenar por timestamp embaralha quase tudo), 7,5% de mensagens de mídia
sem transcrição, e CPF e CEP em texto livre em **100%** das conversas.

## 5. A decisão de arquitetura que saiu daí

**O preço nunca é gerado pelo modelo.** A resposta da `/quote` é renderizada por
template determinístico a partir do JSON. O LLM decide *quando* cotar e *como*
conversar; nunca *qual número escrever*.

Isso elimina por construção a pior falha possível (informar um preço errado) e torna
trivial garantir que carência e pro-rata sempre apareçam. Foi a decisão mais barata e
de maior efeito de toda a preparação — e ela só ficou óbvia depois de ver que o dataset
inteiro é um exemplo de como esse erro acontece na prática.

## 5b. A decisão de canal — e como ela mudou três vezes

O cenário do desafio é WhatsApp, então a primeira proposta foi ambiciosa: uma porta
`ChannelAdapter` com três adaptadores — console, Baileys e WhatsApp Cloud API oficial.

**Primeira revisão.** Como eu tenho um número na Cloud API oficial, a IA sugeriu cortar
o Baileys por ser não-oficial. Eu discordei: a Cloud API exige webhook HTTPS público, o
que obriga a manter um túnel de pé durante o desenvolvimento, e o Baileys conversa a
partir de `localhost`. O argumento foi aceito e os três voltaram.

**Segunda revisão.** Na releitura integral do enunciado apareceu o dado decisivo: a
palavra "WhatsApp" aparece **uma única vez** no README do desafio, na frase de cenário.
Não está em nenhum entregável, em nenhum critério de avaliação, em nenhuma instrução.
O canal é graduado em zero.

Isso também desmontou o meu próprio argumento sobre o túnel: o loop de desenvolvimento
do **agente** roda no console, não em WhatsApp nenhum. O atrito da Cloud API existiria
só para desenvolver o adaptador dela — uma tarde, não três dias.

**Decisão final.** Nenhuma integração externa de mensageria. Dois adaptadores, ambos
rodando sem credencial:

- `console` — determinístico, gera o log de execução completa, roda no CI;
- `web` — uma interface que **simula o WhatsApp**, onde se conversa com o agente pelo
  navegador.

O ganho não é só de escopo. A interface simulada é a superfície onde a degradação fica
visível: quando a `/quote` demora, o "digitando..." e o aviso de que o valor vem em
seguida aparecem na conversa. Isso demonstra o critério que mais separa melhor do que
qualquer log. E o avaliador clona, sobe com um comando e conversa com o agente — sem
número, sem QR, sem túnel, sem credencial de canal.

Cloud API e Baileys ficam documentados no README como implementações possíveis da mesma
porta, com o contrato que cada uma cumpriria — declarados como decisão de escopo, não
como omissão.

## 5c. Observabilidade: por que o Langfuse ficou de fora

O plano inicial previa instrumentação OpenTelemetry exportando para uma instância
self-hosted do Langfuse. A ideia não era decoração: eu queria mostrar **custo por
conversa e economia real do prompt caching** — coisas que um agente em produção obriga
a conhecer, e que nenhum critério do desafio pede explicitamente, mas que separam quem
já operou agente de quem só construiu um.

**O que mudou foi a conta do custo para quem avalia.**

O Langfuse v3 exige seis containers: `langfuse-web`, `langfuse-worker`, Postgres,
ClickHouse, Redis e MinIO. Não existe variante enxuta — a própria documentação do
projeto registra que a alternativa só-Postgres foi avaliada e recusada. Medi numa
instância própria em produção: **~5,6 GB de imagens e ~3,2 GB de RAM**.

Colocar isso no caminho que o avaliador precisa percorrer contradiria o requisito mais
básico da entrega, que é subir com um comando. E deixar como profile opcional resolveria
o peso, mas não o essencial: **um diferencial só diferencia se a pessoa conseguir ver.**
Métrica que exige 5,6 GB de download para ser verificada é, na prática, uma alegação.

**A alternativa se mostrou melhor, não apenas mais barata.** Consultando a documentação
oficial do framework de agentes, três coisas que eu ia construir à mão já são nativas:
verificação de que a tool certa foi chamada com os argumentos certos, juiz por modelo com
critério e escala configuráveis, e acumulação de métricas de token — inclusive separando
o consumo do agente do consumo do próprio avaliador. E os resultados persistem no **mesmo
Postgres da aplicação**.

Com o consumo por turno gravado numa tabela própria (tokens de entrada e saída, leitura e
escrita de cache, latência) e o preço vindo de um arquivo de configuração com data de
vigência, o custo passa a ser calculado a partir da nossa própria base. A visualização
virou um painel no admin.

O resultado é a mesma informação — custo por conversa, taxa de acerto de cache,
confiabilidade das chamadas de ferramenta, notas do juiz — disponível para qualquer
pessoa que rode a aplicação, sem dependência externa nenhuma.

**E há um argumento que só apareceu depois:** plugar uma ferramenta de observabilidade
demonstra que você conhece a ferramenta. Construir o painel demonstra que você sabe **o
que medir** — e a escolha das métricas é a parte que de fato exige julgamento.

A instrumentação OTel continua sendo cerca de trinta linhas, e o código já está escrito e
é inerte sem chave. Se o tempo permitir, entra como profile opcional. Se não, esta seção
é o registro do porquê.

## 6. Onde a IA errou e foi corrigida

Esta seção existe de propósito. O desafio pede transparência sobre o uso de IA, e a
parte honesta disso não é mostrar onde a IA acertou.

**a) Recomendou WebSocket para falar com a `/quote`.** Errado: `/quote` é `POST` HTTP
síncrono e o legado não expõe canal WebSocket nenhum. O que resolve é cliente HTTP
resiliente com timeout maior que 8s, retry classificado, backoff com jitter e circuit
breaker. WebSocket tem lugar legítimo em outro ponto — empurrar atualização para a
interface de administração e sustentar o padrão "aviso agora, trago o valor depois".

**b) Rebaixou o Baileys, e eu reverti.** A IA argumentou que, tendo eu um número na
Cloud API oficial, o Baileys viraria dependência desnecessária. Eu discordei: a Cloud
API exige webhook HTTPS público, o que obriga a manter um túnel de pé durante todo o
desenvolvimento. O Baileys conversa a partir de `localhost` e é o ciclo de feedback
rápido. Além disso, uma porta de canal com uma única implementação não prova
abstração nenhuma. O argumento foi aceito e os três adaptadores ficaram.

**c) Exigiu que o projeto rodasse sem nenhuma chave de API, como requisito.** Eu
questionei se o enunciado pedia isso. Não pede: os entregáveis falam em "README
explicando como rodar" e "log de uma execução completa". Exigir `ANTHROPIC_API_KEY` é
normal. Um modo de replay determinístico continua sendo desejável — não porque o
avaliador não tenha chave, mas porque **um log colado não prova nada e um log
reproduzível prova** — mas foi rebaixado de requisito para melhoria opcional.

**d) Recomendou um `model_factory` com despacho por prefixo do id do modelo.** Obsoleto:
o Agno resolve provider por model-string (`"anthropic:..."`, `"ollama:..."`). O
multiprovider é uma variável de ambiente, não uma fábrica. Eu levantei essa dúvida e a
verificação na documentação oficial confirmou.

**e) Recomendou uma técnica de prompt caching desatualizada** — prefixar o conteúdo
volátil na última mensagem do usuário, um contorno de um projeto anterior. A
documentação oficial mostrou que o Agno já resolve isso nativamente com blocos de
system prompt marcados como não-cacheáveis.

**f) Ia recomendar o cache de resposta nativo do framework como mecanismo de replay.**
A documentação oficial desmente: um acerto de cache retorna a resposta **antes da
execução das tools**, o que faria o cliente da `/quote`, o retry, o circuit breaker e a
persistência não rodarem — justamente o que está sendo avaliado.

**g) Escreveu um prompt de orquestração que perdeu seis requisitos meus.** Ao enxugar o
prompt em volta do portão de aprovação, a IA cortou a estrutura de frentes e papéis, a
disciplina de avaliação, o papel de QA sobre o dataset, o passe de segurança e a
validação de interface — tudo que eu havia pedido explicitamente. Eu cobrei, ela auditou
o próprio prompt com busca literal em vez de memória, confirmou as seis perdas e
reescreveu. Lição registrada: **prompt longo não é o risco; requisito que some no
resumo é.**

O padrão comum a (d), (e) e (f): **a memória do modelo estava desatualizada e a
documentação oficial corrigiu**. Por isso a regra que atravessa todo o projeto é
"referência é ponto de partida, documentação oficial é autoridade".

## 7. Código reaproveitado

Levantei código de projetos meus já em produção e extraí, anonimizado, o que resolvia
partes do problema: backoff e classificação de erro retentável, token bucket,
deduplicação por id de mensagem, ciclo de vida de sessão Baileys, validação de
assinatura de webhook da Meta, tracing OpenTelemetry para Langfuse que vira no-op sem
chave, e o padrão de tool de handoff em que a tool apenas registra a intenção e o
backend executa.

O ganho não é digitar menos: é que esse código já sangrou. Os comentários dentro dele
registram as armadilhas que custaram caro na época — a versão do WhatsApp Web que
envelhece e impede o QR de aparecer, o envio concorrente que perde mensagem sem fila,
o log em nível `warn` que esconde reconexão.

## 8. O que ficou combinado para a construção

- Contratos antes de código: schemas, migração, porta de canal, OpenAPI, política de
  retry e tabela de handoff fechados **antes** de qualquer implementação.
- Implementação por fatia vertical, uma por vez, cada uma validada antes da seguinte.
- Quatro decisões deixadas explicitamente **abertas** para discussão em vez de decididas
  pela IA: a tabela de gatilhos de handoff, o comportamento conversacional quando a
  cotação falha, o caminho de recusa e o formato da mensagem de cotação. São os pontos
  que o enunciado diz de propósito não ter resposta certa.
- Tudo que o repositório prometer precisa estar testado. O que não deu certo é
  declarado no README, com o motivo.
