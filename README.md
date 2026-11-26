# 📈 Análise Técnica B3 (Brapi + TradingView)

Aplicativo interativo desenvolvido em **Streamlit** para acompanhamento em tempo real, varredura técnica e análise gráfica de ativos da **B3** utilizando a API da **Brapi** e gráficos interativos **TradingView Lightweight Charts v5**.

---

## ✨ Funcionalidades Principais

* **📋 Watchlist Interativa (Barra Lateral):**
  * Lista compacta estilo TradingView com **29 ativos líquidos da B3** (incluindo ETFs como `BOVA11` e `SMAL11`).
  * Exibe preço de fechamento ajustado e variação percentual diária com destaque visual.
  * Ordenação dinâmica por **Ativo**, **Preço** ou **Variação %** (crescente ou decrescente).
  * Carregamento automático ao abrir o aplicativo e botão **🔄 Atualizar Cotações** que limpa o cache e sincroniza todas as abas simultaneamente.

* **📈 Aba 1 — Gráfico Individual:**
  * Consulta qualquer ativo da carteira ou ticker personalizado da B3 nos timeframes **Diário (`1d`)** e **Semanal (`1wk`)**.
  * Cards de resumo com fechamento ajustado, variação percentual/monetária e pontuação do **IFR (14)**.
  * Gráfico candlestick com ajuste de proventos (`adjustedClose`), seletor dinâmico de médias exponenciais (**EMA 17/72**, **EMA 9/21** ou **Ambas**) e subpainel sincronizado de **RSI (14)**.

* **🔍 Aba 2 — Scanner de RSI (Carteira):**
  * Varredura unificada dos 29 ativos em janela de 3 meses (`1d`) com cache inteligente de 1 hora.
  * Detecção automática de zonas extremas de **IFR (≤ 30 e ≥ 70)**, **cruzamentos recentes de EMAs (9/21 e 17/72)** nos últimos 3 pregões e **alertas de volume anormal (≥ 150% da MM20)**.
  * Filtros rápidos por condição técnica e barra visual de progresso para o IFR.

* **🗂️ Aba 3 — Visão Geral (Subplots 3M):**
  * Grade visual com **3 gráficos por linha** exibindo os últimos 3 meses (`1d`) de toda a carteira.
  * Filtros por zonas de IFR e ordenação por **Alfabética**, **Maior Alta do Dia**, **Maior Queda do Dia** ou **Menor IFR**.

* **ℹ️ Aba 4 — Guia e Critérios:**
  * Documentação completa dentro do próprio app detalhando a arquitetura, limites do plano gratuito da Brapi e fórmulas dos indicadores.

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

3. **Configure o Token da Brapi (opcional para ativos de teste):**
   Crie o arquivo `.streamlit/secrets.toml` na raiz do projeto com o conteúdo:
   ```toml
   BRAPI_TOKEN = "seu_token_aqui"
   ```

4. **Execute o aplicativo:**
   ```bash
   streamlit run app.py
   ```

---

## ⚠️ Aviso Legal

Este aplicativo tem caráter exclusivamente educacional e informativo para apoio à análise gráfica, não constituindo recomendação de compra ou venda de valores mobiliários.

---

*Desenvolvedor: Daniel — Colaboradores: Matheus e Maurício*
