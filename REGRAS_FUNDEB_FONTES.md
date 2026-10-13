# Regras de classificação de fontes — FUNDEB (Educação)

Documento de referência para os dashboards iG2P. Define **quais fontes compõem cada
indicador** da execução do FUNDEB. As fontes flutuam por município: há município com VAAR,
município só com VAAT, e município sem nenhuma complementação — o indicador soma apenas as
fontes que existirem (fonte ausente = R$ 0, a barra simplesmente não aparece).

Convenção do dígito final das fontes do 4% (complementação):
- **final 1** (…071 / …271 / …371) → Custeio **ou** Capital — classificar pelo **Elemento** da despesa.
- **final 2** (…072 / …272 / …372) → **Folha** (departamento pessoal).

---

## Tabela 1 — Execução do 70% e do 4%

| Indicador | Fontes |
|---|---|
| **FUNDEB 70%** | 15407 · 154072 (Principal final 2) · 15427 (VAAT base) · 154272 (VAAT final 2) |
| **FUNDEB 4% — Folha** | 154072 · 154272 · 154372 (todas final 2) |
| **FUNDEB 4% — Custeio e Capital** | 154071 · 154271 · 154371 (todas final 1) — classificar Custeio × Capital pelo **Elemento** da despesa |

Notas:
- O VAAR **não** entra no 70%. As fontes final 1 (154071/154271) também não entram no 70% (são custeio/capital, não folha).
- Capital = elementos "Obras e Instalações" e "Equipamentos e Materiais Permanentes"; o restante das fontes final 1 = Custeio.
- A execução do 4% é apresentada por **categoria da despesa** (Folha / Custeio / Capital) — como o recurso foi gasto —, não pela fonte.

## Tabela 2 — Indicadores específicos do VAAT

| Indicador | Fontes | Classificar por |
|---|---|---|
| **FUNDEB VAAT – 50% Educação Infantil** | 15423 · 15427 · 154271 · 154272 | coluna **Categoria** |
| **FUNDEB VAAT – 15%** | 15423 · 154271 | coluna **Elemento** |

---

## Status de implementação (atualizar conforme avança)

- Tabela 1 aplicada e conferida: **Cássia**, **São Roque de Minas**.
- Tabela 1 pendente (lógica antiga): Alpinópolis, Capetinga, Claraval, Delfinópolis, Ibiraci,
  Itamogi, Itaú de Minas, Pratápolis, Restinga, São José da Barra, São João Batista do Glória, São Tomás de Aquino.
- Tabela 2 (VAAT 50% Ed. Infantil e VAAT 15%): **indicadores ainda não construídos** em nenhum município.
