# ai-logs

Registro do uso de IA durante o desafio, conforme pedido no enunciado.

## O que tem aqui

| Arquivo | O que é |
|---|---|
| `00-preparacao.md` | **Etapa de preparação**, anterior a qualquer código: leitura do código-fonte da API de cotação, medição do dataset, levantamento de código reaproveitável e as decisões de arquitetura que saíram daí. Inclui uma seção sobre onde a recomendação da IA estava errada e foi corrigida. |
| `sessions/` | Sessões de construção do Claude Code, exportadas cruas (`.jsonl`), na ordem em que aconteceram. |

## Sobre a etapa de preparação

Ela merece uma explicação, porque é o único item aqui que **não** é um log cru.

A sessão de preparação percorreu repositórios privados meus, para levantar código já em
produção que resolvesse partes deste problema — cliente HTTP com retry e backoff,
integração com WhatsApp, tracing, tool de handoff. O transcript bruto dessa sessão cita
nomes de cliente, endereços de infraestrutura e caminhos internos, e por isso não pode
ir para um repositório público.

O que está em `00-preparacao.md` é o **registro consolidado e anonimizado** dessa
sessão: o método, os achados, as decisões e os erros. Nada foi omitido por conveniência
— inclusive as recomendações da IA que se mostraram erradas estão listadas, com o que as
corrigiu.

O enunciado prevê exatamente este caso ("se a exportação não for viável, avise antes de
entregar"). Estou avisando aqui, e sigo à disposição para mostrar a sessão original em
tela compartilhada, se fizer diferença na avaliação.

As sessões de **construção** — que são onde o código deste repositório nasceu — estão
exportadas integralmente em `sessions/`.

## Ferramentas usadas

- **Claude Code** — sessão orquestradora e sessões de implementação.

## Higiene

Antes do push, os arquivos desta pasta passaram por remoção de:
chaves de API e tokens · caminhos absolutos com o meu usuário · telefones, e-mails e
outros dados pessoais · nomes de clientes e de projetos alheios a este desafio.
