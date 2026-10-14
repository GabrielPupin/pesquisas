# Tutorial — primeiro teste do tolstack

Exemplo: uma engrenagem montada entre duas arruelas dentro de uma caixa. Queremos saber a **folga axial**
entre a arruela 2 e a parede direita da caixa.

```
 parede esq.                                         parede dir.
   |<------------------ CX = 30,00 ±0,10 ------------------>|
   |[ARR1 1,8±0,03][   ENG 26,00 ±0,05   ][ARR2 1,8±0,03]<folga>|
```

Folga nominal = 30 − 1,8 − 26 − 1,8 = **0,40 mm**. Requisito: entre **0,10** e **0,55 mm**.
O conjunto é considerado encostado na parede esquerda.

## 1. Abrir o programa

1. Instale o Python 3.10+ (https://www.python.org/downloads/), marcando **"Add Python to PATH"**.
2. Na pasta `tolstack`, dê dois cliques em **`rodar_windows.bat`** (Mac/Linux: `./rodar_mac_linux.sh`).
   Na primeira vez ele instala as dependências (alguns minutos). Depois abre o navegador em
   `http://localhost:8501`. Para fechar, feche a janela preta.

## 2. Carregar o exemplo

Módulo **1 · Project** → em *Load demonstration model* escolha **Tutorial — engrenagem + arruelas** →
**Load demo**.

## 3. Conferir o modelo

- **3 · Components & features**: 4 peças, 8 faces e 3 contatos (K1, K2, K3 = faces encostadas).
- **4 · Dimensions & tolerances**: as 4 cotas. `from_feature → to_feature` e `direction = 1`
  dizem de qual face a qual face cada cota vai, da esquerda para a direita.
- **5 · Functional characteristic**: folga de `ARR2_D` (face direita da arruela 2) até `CX_D`
  (parede direita), LSL 0,10, USL 0,55, nominal declarado 0,40.
- **6 · Stack-up paths**: dois caminhos — `CERTO` e `ERRADO` (esquece a arruela 1).

## 4. Validar o caminho

**7 · Path validation & review**, caminho `CERTO`:

- Status esperado: **Conditionally Valid**.
- Equação: `y = −1·ARR2 −1·ENG −1·ARR1 +1·CX`. Os sinais foram deduzidos pelo programa a partir das
  faces e contatos, não digitados.
- Em *Path* aparece o percurso face a face.

Troque para o caminho `ERRADO`: status **Invalid**, com a mensagem de descontinuidade
(a cota CX não se conecta à face ENG_E — falta a arruela 1).

Aprove o caminho `CERTO`: preencha *Reviewer* com seu nome, escolha *approved* e clique **Record**.

## 5. Calcular

**9 · Results & sensitivity** → caminho `CERTO` → botão **Run Worst-Case, RSS and Monte Carlo**.

Resultados esperados:

| método | resultado | leitura |
|---|---|---|
| Worst-Case | folga entre **0,19** e **0,61 mm** | mínimo atende (≥ 0,10); máximo **passa 0,06 mm do USL** |
| RSS | média 0,400, σ = **0,0399 mm** | ≈ **84 ppm** fora do limite |
| Monte Carlo (200 000 amostras, seed 12345) | média 0,400, σ ≈ 0,0398 | ≈ **85 ppm**, intervalo 95 % ≈ [53, 136] ppm |

Conferência à mão do σ (hipótese configurada: tolerância = ±3σ):
√((0,10/3)² + (0,05/3)² + 2·(0,03/3)²) = 0,0399 mm.

Sensibilidade: a caixa (CX) é a maior contribuinte — 47,6 % da faixa de pior caso e ≈ 70 % da variância.

**Interpretação:** pelo pior caso o projeto não atende. Pelo critério estatístico, o risco é de cerca de
84 ppm, **mas só se** os processos tiverem σ = tolerância/3 — essa é uma suposição, e o relatório deixa isso
explícito. Sem dados reais de processo, a decisão segura é o pior caso.

## 6. Experimentos

1. **What-if** (no fim do módulo 9): contribuinte `CX`, desvios **+0,04 / −0,04** → *Evaluate*.
   O máximo do pior caso cai para 0,55 mm e passa a atender o USL.
2. **Sem suposição estatística**: módulo **8**, *Statistical assumption* = `none` → *Apply* → rode de novo.
   RSS e Monte Carlo aparecem como *não calculados* (o programa não inventa σ). O pior caso continua.
3. **Erro de sinal**: módulo **4**, mude `direction` da `ENG` para `-1` → *Apply* → módulo 7.
   Status **Invalid**: o nominal calculado não fecha com o declarado (0,40).
4. **Relatório**: módulo **10** → baixe o PDF e o Excel.

## 7. Leitura de desenho (opcional)

Módulo **2 · Drawing import (PDF)** → envie `examples/drawings/TS-100_housing.pdf` → **Extract**.
Verde = lido, laranja = ambíguo (precisa da sua decisão). Nenhum valor entra no cálculo sem confirmação.

## Linha de comando (alternativa sem interface)

```
py -m tolstack.cli analyze examples/exemplo_tutorial.json --chain CERTO --pdf relatorio.pdf
```
