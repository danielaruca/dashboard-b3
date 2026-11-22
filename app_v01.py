import time
import streamlit as st
import pandas as pd
import requests
from lightweight_charts_v5 import lightweight_charts_v5_component

st.set_page_config(layout="wide", page_title="Análise Técnica B3 (Brapi)")

st.markdown(
    """
    <style>
        .block-container {
            padding-top: 2.8rem;
            padding-bottom: 1rem;
        }
        iframe {
            border: 1px solid #2A2E39;
            border-radius: 8px;
        }
        /* Aumenta levemente o tamanho e respiro do texto das abas */
        button[data-baseweb="tab"] p {
            font-size: 1.05rem;
            font-weight: 600;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

MEU_TOKEN_BRAPI = st.secrets.get("BRAPI_TOKEN", "")

@st.cache_data(ttl=3600, show_spinner=False)
def _requisitar_brapi(ticker_limpo: str, periodo: str, intervalo: str, token: str) -> dict:
    url = "/".join(["https://brapi.dev", "api", "quote", ticker_limpo])
    ativos_teste = {"PETR4", "VALE3", "ITUB4", "MGLU3"}
    periodos_gratis = ["1mo", "3mo"]

    params = {"range": periodo, "interval": intervalo}
    if token and not (ticker_limpo in ativos_teste and periodo not in periodos_gratis):
        params["token"] = token

    resp = requests.get(url, params=params, timeout=15)
    if resp.status_code != 200:
        try:
            msg = resp.json().get("message", f"Erro HTTP {resp.status_code}")
        except Exception:
            msg = f"Erro HTTP {resp.status_code}"
        raise RuntimeError(msg)

    dados = resp.json()
    resultados = dados.get("results", [])
    if not resultados or "historicalDataPrice" not in resultados[0]:
        raise RuntimeError("A resposta da Brapi não retornou histórico de preços.")
    return dados

def carregar_dados_brapi(ticker: str, periodo: str, intervalo: str, token: str = "") -> tuple[pd.DataFrame, str]:
    ticker_limpo = ticker.replace(".SA", "").strip().upper()
    try:
        dados = _requisitar_brapi(ticker_limpo, periodo, intervalo, token)
    except Exception as e:
        return pd.DataFrame(), str(e)

    historico = dados["results"][0]["historicalDataPrice"]
    df = pd.DataFrame(historico)
    if df.empty:
        return df, "Histórico vazio para este ativo/período."

    df["time"] = pd.to_datetime(df["date"], unit="s").dt.strftime("%Y-%m-%d")
    df = df.sort_values("time").drop_duplicates(subset=["time"]).reset_index(drop=True)

    colunas_preco = ["open", "high", "low", "close"]
    df = df.dropna(subset=colunas_preco)
    df = df[(df["open"] > 0) & (df["high"] > 0) & (df["low"] > 0) & (df["close"] > 0)].copy()

    if "adjustedClose" in df.columns:
        df["adjustedClose"] = pd.to_numeric(df["adjustedClose"], errors="coerce").fillna(df["close"])
        df.loc[df["adjustedClose"] <= 0, "adjustedClose"] = df["close"]
        fator_ajuste = df["adjustedClose"] / df["close"]
        df["open"] = df["open"] * fator_ajuste
        df["high"] = df["high"] * fator_ajuste
        df["low"] = df["low"] * fator_ajuste
        df["close"] = df["adjustedClose"]

    df["EMA_17"] = df["close"].ewm(span=17, adjust=False).mean()
    df["EMA_72"] = df["close"].ewm(span=72, adjust=False).mean()

    delta = df["close"].diff()
    ganho = delta.where(delta > 0, 0.0).ewm(alpha=1 / 14, adjust=False).mean()
    perda = (-delta.where(delta < 0, 0.0)).ewm(alpha=1 / 14, adjust=False).mean()
    df["RSI"] = 100 - (100 / (1 + (ganho / perda)))
    return df, ""

LISTA_CARTEIRA_B3 = [
    "BOVA11", "B3SA3", "BBAS3", "BBDC4", "BEEF3", "BPAC11", "BRAV3",
    "CMIN3", "CSNA3", "CYRE3", "DIRR3", "EGIE3", "EQTL3", "GGBR4",
    "HYPE3", "ITUB4", "KLBN11", "MBRF3", "MRVE3", "PETR4", "PRIO3",
    "RADL3", "RENT3", "SMAL11", "USIM5", "VALE3", "VAMO3", "VBBR3", "WEGE3",
]

with st.sidebar:
    st.header("Configurações (Brapi B3)")
    ativos_b3 = LISTA_CARTEIRA_B3 + ["Outro (digitar)..."]
    escolha = st.selectbox("Ativo da B3", ativos_b3)

    if escolha == "Outro (digitar)...":
        ativo = st.text_input("Código do Ativo (ex: RENT3, BPAC11)", value="RENT3").strip().upper().replace(".SA", "")
    else:
        ativo = escolha

    # Usa o token direto dos segredos sem expor na tela
    token_brapi = MEU_TOKEN_BRAPI

    mapa_timeframe = {"Diário (1D)": "1d", "Semanal (1S)": "1wk"}
    tf_label = st.radio("Timeframe", list(mapa_timeframe.keys()), horizontal=True)
    intervalo = mapa_timeframe[tf_label]

    opcoes_periodo = ["1mo", "3mo", "6mo", "1y", "2y", "5y", "max"]
    periodo = st.selectbox("Período Histórico", opcoes_periodo, index=1)

    st.markdown(
    """
    <div style="
        margin-top: 8px; padding: 10px 14px; background-color: #131722;
        border-left: 3px solid #2962FF; border-radius: 4px;
        line-height: 1.35; font-size: 0.85rem; color: #9BA1B0;
    ">
        <strong style="color: #D1D4DC;">Observações:</strong><br>
        • A seleção acima de <strong>3mo</strong> somente funciona para <strong>PETR4, VALE3, ITUB4 e MGLU3</strong>.<br>
        • Demais ativos somente podem ser vistos nos períodos de <strong>1mo</strong> e <strong>3mo</strong> (Plano gratuito da Brapi).<br>.<br>
        <span style="color: #6C7386;">Desenvolvedor: Daniel</span>.<br>
        <span style="color: #6C7386;">Colaboradores: Matheus e Maurício</span>.<br>
    </div>
    """,
    
     unsafe_allow_html=True,
    )

aba_grafico, aba_scanner = st.tabs(["📈 Gráfico Individual", "🔍 Scanner de RSI (Carteira)"])

with aba_grafico:
    st.title(f"{ativo} - {tf_label}")

    with st.spinner("Buscando cotações na B3..."):
        df, erro_api = carregar_dados_brapi(ativo, periodo, intervalo, token_brapi)

    if df.empty:
        st.error(
            f"Não foi possível carregar **{ativo}**: {erro_api}. "
            "Verifique se o seu Token está preenchido na barra lateral e se o período está em **1mo** ou **3mo**."
        )
        st.stop()

    ultimo = df.iloc[-1]
    penultimo = df.iloc[-2] if len(df) > 1 else ultimo

    preco_atual = float(ultimo["close"])
    preco_anterior = float(penultimo["close"])
    variacao_pct = ((preco_atual - preco_anterior) / preco_anterior) * 100

    rsi_atual = float(ultimo["RSI"])
    rsi_anterior = float(penultimo["RSI"])
    delta_rsi = rsi_atual - rsi_anterior

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(label=f"Fechamento ({ultimo['time']})", value=f"R$ {preco_atual:.2f}", border=True)
    with col2:
        st.metric(label="Variação Percentual", value=f"{variacao_pct:+.2f}%", delta=f"R$ {preco_atual - preco_anterior:+.2f}", border=True)
    with col3:
        st.metric(label="RSI (14)", value=f"{rsi_atual:.2f}", delta=f"{delta_rsi:+.2f} pts", delta_color="off", border=True)
    with col4:
        with st.container(border=True):
            st.caption("Condição RSI")
            if rsi_atual >= 70:
                st.markdown("#### :red[Sobrecompra (≥ 70)]")
            elif rsi_atual <= 30:
                st.markdown("#### :green[Sobrevenda (≤ 30)]")
            else:
                st.markdown("#### :gray[Zona Neutra]")

    st.divider()

    candles = [{"time": r["time"], "open": float(r["open"]), "high": float(r["high"]), "low": float(r["low"]), "close": float(r["close"])} for _, r in df.iterrows()]
    ema_17_data = [{"time": r["time"], "value": float(r["EMA_17"])} for _, r in df.dropna(subset=["EMA_17"]).iterrows()]
    ema_72_data = [{"time": r["time"], "value": float(r["EMA_72"])} for _, r in df.dropna(subset=["EMA_72"]).iterrows()]

    df_rsi = df.dropna(subset=["RSI"])
    rsi_data = [{"time": r["time"], "value": float(r["RSI"])} for _, r in df_rsi.iterrows()]
    linha_70 = [{"time": r["time"], "value": 70.0} for _, r in df_rsi.iterrows()]
    linha_30 = [{"time": r["time"], "value": 30.0} for _, r in df_rsi.iterrows()]

    layout_base = {
        "layout": {"background": {"color": "#131722"}, "textColor": "#D1D4DC"},
        "grid": {"vertLines": {"color": "rgba(42, 46, 57, 0.5)"}, "horzLines": {"color": "rgba(42, 46, 57, 0.5)"}},
    }

    lightweight_charts_v5_component(
        name=f"brapi_{ativo}_{intervalo}_{periodo}",
        charts=[
            {
                "chart": layout_base,
                "height": 480,
                "series": [
                    {"type": "Candlestick", "data": candles, "options": {"upColor": "#26A69A", "downColor": "#EF5350", "borderVisible": False, "wickUpColor": "#26A69A", "wickDownColor": "#EF5350"}},
                    {"type": "Line", "data": ema_17_data, "options": {"color": "#29B6F6", "lineWidth": 1, "title": "EMA 17"}},
                    {"type": "Line", "data": ema_72_data, "options": {"color": "#FF6D00", "lineWidth": 1, "title": "EMA 72"}},
                ],
            },
            {
                "chart": layout_base,
                "height": 180,
                "series": [
                    {"type": "Line", "data": rsi_data, "options": {"color": "#AB47BC", "lineWidth": 2, "title": "RSI (14)"}},
                    {"type": "Line", "data": linha_70, "options": {"color": "#EF5350", "lineWidth": 1, "lineStyle": 2, "priceLineVisible": False, "lastValueVisible": True, "crosshairMarkerVisible": False, "title": "70"}},
                    {"type": "Line", "data": linha_30, "options": {"color": "#26A69A", "lineWidth": 1, "lineStyle": 2, "priceLineVisible": False, "lastValueVisible": True, "crosshairMarkerVisible": False, "title": "30"}},
                ],
            },
        ],
        height=660,
    )

with aba_scanner:
    st.title(f"Scanner de RSI (14)  -  {tf_label}")
    st.caption(f"Varre os **{len(LISTA_CARTEIRA_B3)} ativos** da lista em **3mo** e mantém em cache por 1 hora.")

    col_btn, col_filtro = st.columns([1, 2])
    with col_btn:
        executar_scan = st.button("🔍 Escanear Carteira Agora", type="primary", use_container_width=True)
    with col_filtro:
        filtro_condicao = st.radio(
            "Filtrar por Condição:",
            ["Todos", "Sobrevenda (≤ 30)", "Sobrecompra (≥ 70)", "Extremos (≤ 30 ou ≥ 70)"],
            horizontal=True,
        )

    if executar_scan:
        resultados_scan, erros_scan = [], []
        barra = st.progress(0, text="Iniciando varredura...")

        for idx, ticker_scan in enumerate(LISTA_CARTEIRA_B3):
            barra.progress((idx + 1) / len(LISTA_CARTEIRA_B3), text=f"Analisando {ticker_scan} ({idx + 1}/{len(LISTA_CARTEIRA_B3)})...")
            df_s, err_s = carregar_dados_brapi(ticker_scan, "3mo", intervalo, token_brapi)

            if not df_s.empty and len(df_s) >= 2:
                ult, pen = df_s.iloc[-1], df_s.iloc[-2]
                fech = float(ult["close"])
                var_p = ((fech - float(pen["close"])) / float(pen["close"])) * 100
                rsi_v = float(ult["RSI"])
                cond = "🔴 Sobrecompra (≥ 70)" if rsi_v >= 70 else ("🟢 Sobrevenda (≤ 30)" if rsi_v <= 30 else "⚪ Zona Neutra")

                resultados_scan.append({
                    "Ativo": ticker_scan,
                    "Data": ult["time"],
                    "Fechamento (R$)": fech,
                    "Variação (%)": var_p,
                    "RSI (14)": rsi_v,
                    "Condição": cond,
                })
            else:
                erros_scan.append(f"{ticker_scan}: {err_s}")
            time.sleep(0.15)

        barra.empty()
        st.session_state["df_scanner"] = pd.DataFrame(resultados_scan)
        st.session_state["erros_scanner"] = erros_scan

    if "df_scanner" in st.session_state and not st.session_state["df_scanner"].empty:
        df_res = st.session_state["df_scanner"].copy()

        if filtro_condicao == "Sobrevenda (≤ 30)":
            df_res = df_res[df_res["RSI (14)"] <= 30]
        elif filtro_condicao == "Sobrecompra (≥ 70)":
            df_res = df_res[df_res["RSI (14)"] >= 70]
        elif filtro_condicao == "Extremos (≤ 30 ou ≥ 70)":
            df_res = df_res[(df_res["RSI (14)"] <= 30) | (df_res["RSI (14)"] >= 70)]

        df_res = df_res.sort_values("RSI (14)", ascending=True).reset_index(drop=True)

        total_sv = len(st.session_state["df_scanner"][st.session_state["df_scanner"]["RSI (14)"] <= 30])
        total_sc = len(st.session_state["df_scanner"][st.session_state["df_scanner"]["RSI (14)"] >= 70])

        c1, c2, c3 = st.columns(3)
        c1.metric("Ativos Escaneados", len(st.session_state["df_scanner"]), border=True)
        c2.metric("Em Sobrevenda (≤ 30)", total_sv, border=True)
        c3.metric("Em Sobrecompra (≥ 70)", total_sc, border=True)

        if df_res.empty:
            st.info(f"Nenhum ativo encontrado com o filtro **{filtro_condicao}**.")
        else:
            st.dataframe(
                df_res,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Fechamento (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
                    "Variação (%)": st.column_config.NumberColumn(format="%+.2f%%"),
                    "RSI (14)": st.column_config.ProgressColumn(format="%.2f", min_value=0, max_value=100),
                },
            )

        if st.session_state.get("erros_scanner"):
            with st.expander(f"Ver ativos com aviso ({len(st.session_state['erros_scanner'])})"):
                for msg_e in st.session_state["erros_scanner"]:
                    st.write(f"• {msg_e}")
    else:
        st.info("Clique no botão **🔍 Escanear Carteira Agora** acima para calcular o RSI de todos os 29 ativos.")


