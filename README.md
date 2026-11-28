# 📊 Terminal de Análise Técnica B3 & Bancada de Opções

Aplicação interativa desenvolvida em **Python** e **Streamlit** para acompanhamento em tempo real da carteira de ações e ETFs da **B3**, indicadores macroeconômicos, radar de notícias, alertas técnicos e estruturação completa de **Venda Coberta de Put (Cash-Secured Put)**.

---

## ✨ Funcionalidades Principais

### 📋 Painel Lateral — Watchlist B3 Interativa
* **Seleção Sincronizada:** Lista líquida de ativos da B3 (incluindo ETFs como `BOVA11` e `SMAL11`) com cotação ajustada, variação diária e ícones automáticos de alertas ativos. Clicar em qualquer ticker atualiza instantaneamente os gráficos, notícias e grade de opções.
* **Ordenação Estilo TradingView:** Clique nos cabeçalhos (**Símbolo**, **Preço** ou **Var%**) para alternar entre ordem crescente (`↑`) e decrescente (`↓`).
* **Gerenciar Watchlist B3:** Adicione novos tickers da B3, remova ativos ou restaure a lista padrão diretamente na sessão.

### 🗂️ Estrutura das 8 Abas

1. **📈 GRÁFICO:**
   * Gráfico interativo estilo **TradingView** (`streamlit-lightweight-charts-v5`) sincronizado com a Watchlist.
   * Alternância rápida entre **Timeframe** (`Diário 1D` / `Semanal 1S`) e **Período Histórico** (`3mo`, `1y`, `2y`, `5y`), com **agrupamento OHLC automático** nos períodos longos (`2y` e `5y`) para enquadrar todo o histórico na janela sem distorcer máximas, mínimas, médias ou IFR.
   * Seletor visual de médias móveis (**EMA 17/72**, **EMA 9/21** ou **Ambas**) e subpainel de **IFR / RSI (14)**.
2. **🔍 SCANNER:**
   * Varredura completa da carteira ordenando os ativos do menor para o maior **IFR (14)**.
   * Filtros rápidos para *Sobrevenda (≤ 30)*, *Sobrecompra (≥ 70)*, *Cruzamento recente de Médias* (`EMA 9/21` ou `EMA 17/72` nos últimos 3 pregões) e *Volume Relativo Alto (≥ 150% da MM20)*.
   * Exportação direta da tabela em **CSV (padrão Excel PT-BR)**.
3. **🗂️ MULTI-GRÁFICOS:**
   * Grade visual (**3 gráficos por linha**) com todos os ativos da Watchlist em **3 meses (`1d`)**, com filtros por extremos de IFR e ordenação por *Ordem Alfabética*, *Maior Alta*, *Maior Queda* ou *Menor IFR*.
4. **🌐 MERCADO:**
   * **Macroeconomia Brasil (Banco Central SGS):** Taxa Selic Meta, CDI Anualizado, IPCA acumulado em 12 meses e **Juro Real (Equação de Fisher)**.
   * **Câmbio, Commodities & Cripto:** Dólar Comercial (`USD/BRL`), Euro (`EUR/BRL`), Ouro B3 (`GOLD11`), Petróleo Brent (`US$/barril`) e Bitcoin (`BTC/BRL`).
   * **Benchmarks (3M):** Gráficos comparativos de `BOVA11`, `IVVB11`, `GOLD11` e curva histórica da **Taxa DI / CDI (720 dias)**.
5. **📰 NOTÍCIAS:**
   * Feed integrado via **Google News RSS** (cache de 15 min) com filtro para o **ativo selecionado** (últimos 7 dias) ou **panorama geral Ibovespa / B3** (últimas 24 horas).
6. **🔔 ALERTAS:**
   * Configuração personalizada dos gatilhos de IFR, volume e cruzamento de médias, além de cadastro de **alertas de preço-alvo em R$** com sinalização visual na Watchlist (`🎯`, `🟢`, `🔴`, `⚡`, `🔥`).
7. **🎯 OPÇÕES (Venda de Put):**
   * **Grade de Strikes OTM & Black-Scholes:** Séries mensais da B3 (`M` a `X`, vencimento na 3ª sexta-feira) com **Prêmio Teórico**, **Taxa Anualizada (% a.a.)**, **Delta (Δ)**, **Probabilidade de Não-Exercício** e exportação em **CSV**.
   * **Simulador & Gráfico de Payoff:** Calcula crédito líquido, garantia necessária, breakeven real e **Volatilidade Implícita (IV Book)**, exibindo a curva de resultado no vencimento com marcadores de **Breakeven**, **Spot** e canal sombreado de **±1 Desvio Padrão (`±1σ`)**.
   * **Simulador de Rolagem de Put:** Calcula o fluxo financeiro líquido, o **Novo Breakeven Acumulado** e a taxa anualizada sobre os dias úteis adicionais ao rolar uma operação.
   * **Carteira de Puts Vendidas (Diário):** Registro de operações em andamento com distância até o exercício, garantia total comprometida, **Marcação a Mercado (MtM)** e exportação CSV.
   * **Radar de Candidatas:** Ranking dos ativos mais descontados da carteira (menor IFR).
8. **ℹ️ CRITÉRIOS:**
   * Documentação interna completa das regras de filtragem, fórmulas dos indicadores técnicos e limitações da API.

---

## 🛠️ Tecnologias & Fontes de Dados

* **Frontend & Visualização:** `Streamlit`, `streamlit-lightweight-charts-v5` (TradingView), `Altair`, `Pandas`
* **Cotações B3 & Históricos:** [Brapi API](https://brapi.dev) (preços ajustados por proventos)
* **Macroeconomia & Câmbio:** API de Séries Temporais do **Banco Central do Brasil (BCB / SGS)**
* **Commodities & Criptoativos:** **Yahoo Finance** (`BZ=F` Petróleo Brent) e **CoinGecko API** (`BTC/BRL`)
* **Notícias:** **Google News RSS**

---

## 🚀 Como Executar Localmente

1. **Clone o repositório:**
   ```bash
   git clone https://github.com
   cd seu-repositorio
   ```

2. **Instale as dependências:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure o Token da Brapi:**
   Crie a pasta e o arquivo `.streamlit/secrets.toml` na raiz do projeto e adicione seu token:
   ```toml
   BRAPI_TOKEN = "seu_token_da_brapi_aqui"
   ```

4. **Execute o aplicativo:**
   ```bash
   streamlit run app5W_brapi_ajustes.py
   ```

---

## ⚠️ Aviso Legal

Esta ferramenta tem caráter exclusivamente educacional e informativo para apoio à análise gráfica e simulação de estruturas com opções, **não constituindo recomendação de compra ou venda de valores mobiliários**.

---

*Desenvolvedor: **Daniel** • Colaboradores: **Matheus** e **Maurício***
