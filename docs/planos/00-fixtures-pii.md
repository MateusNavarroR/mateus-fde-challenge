# Convenção transversal — PII em fixture

> Vale para **todas** as fatias e para as três frentes. Um plano que precisar de PII em
> teste usa isto; nenhum plano escreve um literal.

## A regra

**Nenhum arquivo versionado contém uma string com cara de PII.** Os testes que precisam
exercitar o mascaramento usam um **gerador semeado**, que produz valores válidos em
formato no momento da execução.

## Por que não as duas alternativas óbvias

| Alternativa | Por que não |
|---|---|
| literal sintético (um CPF de dígitos repetidos, por exemplo) mais lista de exceções na varredura de segurança | lista de exceções em varredura é a mesma porta que é ruim em guardrail: uma vez aberta, a próxima entrada é fácil. Num repositório público não vale o risco. |
| valores que não casam com o formato real | enfraquece exatamente o teste que se quer fazer — o regex passa a ser exercitado contra algo que a produção nunca verá |

O gerador não perde nada dos dois lados: o regex continua sendo exercitado no formato
real, e a varredura não tem o que achar porque **não há string de PII no repositório**.

## O gerador

**Arquivo:** `tests/fixtures/pii.py` — criado na **fatia 1**, Task 2, e reusado por todas.

```python
"""Gera PII válida em formato, no momento do teste.

Nenhum valor daqui é literal no repositório: eles nascem em memória e morrem no fim
da execução. É o que permite que a varredura do portão de segurança seja absoluta,
sem lista de exceções.
"""
import random

def gerar_pii(seed: int) -> dict[str, str]:
    """Semeado ⇒ determinístico. O mesmo seed dá o mesmo conjunto, sempre."""
    rng = random.Random(seed)
    return {
        "cpf":      _cpf(rng),        # com dígitos verificadores corretos
        "cep":      _cep(rng),        # 8 dígitos, com hífen
        "email":    _email(rng),      # domínio reservado pela RFC 2606
        "telefone": _telefone(rng),   # +55 DD 9XXXX-XXXX
        "placa":    _placa(rng),      # padrão Mercosul
    }

def frase_do_lead(seed: int) -> tuple[str, dict[str, str]]:
    """Devolve a fala e os valores, para o teste assertar sobre os dois."""
    p = gerar_pii(seed)
    return (f"Tenho 35 anos, CPF {p['cpf']}, CEP {p['cep']}, "
            f"meu email é {p['email']} e o whats é {p['telefone']}, "
            f"placa {p['placa']}"), p
```

Os dígitos verificadores do CPF seguem o mesmo cálculo do gerador do desafio — formato
perfeito, conteúdo inventado em tempo de execução.

## Como o teste fica

```python
def test_mascara_todas_as_classes():
    frase, pii = frase_do_lead(seed=1)
    saida = mascarar(frase)
    for classe, valor in pii.items():
        assert valor not in saida, classe

def test_varias_amostras_nao_escapam():
    """Um literal testa um caso. O gerador testa cem, de graça, e pega a variação
    de formato que um exemplo escolhido a dedo esconde."""
    for seed in range(100):
        frase, pii = frase_do_lead(seed)
        saida = mascarar(frase)
        assert not any(v in saida for v in pii.values())
```

O segundo teste é o ganho que não estava no problema original: um literal exercita **um**
formato de CPF; o gerador exercita cem, e é onde aparece o caso com zero à esquerda, o
DDD de dois dígitos que colide com outra coisa, e a placa cuja letra final vira uma
palavra.

## Duas regras que vêm junto

1. **Nenhum golden file com a saída do gerador.** Gravar o resultado num arquivo de
   referência traria o literal de volta pela porta dos fundos, e é o jeito mais fácil de
   anular tudo isto. Testes assertam sobre o par `(frase, pii)` devolvido em memória.
2. **O seed é explícito no teste**, nunca `random.seed()` global — senão a ordem de
   execução muda o valor e a falha deixa de ser reproduzível.

## O que isto não cobre

O `dataset/conversations.parquet` do desafio **contém** PII sintética e continua como
veio — é arquivo deles, entregue assim, e a camada silver é o que responde por ele. A
regra acima é sobre o que **nós** escrevemos.
