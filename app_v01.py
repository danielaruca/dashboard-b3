import time
import streamlit as st
import pandas as pd
import requests
from lightweight_charts_v5 import lightweight_charts_v5_component


# Imports e função de busca de notícias
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import quote

@st.cache_data(ttl=900, show_spinner=False)
def buscar_noticias_rss(consulta: str, limite: int = 12) -> list[dict]:
    query_codificada = quote(consulta)
    base_rss = "/".join(["https://news.google.com", "rss", "search"])
    url = f"{base_rss}?q={query_codificada}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        raiz = ET.fromstring(resp.content)
    except Exception:
        return []

    noticias = []
    for item in raiz.findall(".//item")[:40]:
        titulo_bruto = item.findtext("title", default="")
        link = item.findtext("link", default="")
        pub_date = item.findtext("pubDate", default="")
        fonte_tag = item.find("source")
        fonte = fonte_tag.text if fonte_tag is not None else ""

        if fonte and titulo_bruto.endswith(f" - {fonte}"):
            titulo = titulo_bruto[: -(len(fonte) + 3)]
        else:
            titulo = titulo_bruto

        try:
            dt_pub = parsedate_to_datetime(pub_date)
            data_fmt = dt_pub.strftime("%d/%m/%Y %H:%M")
            ts_ordem = dt_pub.timestamp()
        except Exception:
            data_fmt = pub_date
            ts_ordem = 0.0

        noticias.append({
            "titulo": titulo,
            "link": link,
            "fonte": fonte or "Portal Financeiro",
            "data": data_fmt,
            "ts": ts_ordem,
        })

    # Ordena rigorosamente da notícia mais recente para a mais antiga
    noticias.sort(key=lambda x: x["ts"], reverse=True)
    return noticias[:limite]



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
        /* Compacta o espaçamento vertical dos itens da Watchlist na Sidebar */
        [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
            gap: 0.25rem;
        }
        [data-testid="stSidebar"] .stButton button {
            padding-top: 0.15rem;
            padding-bottom: 0.15rem;
            min-height: 2.0rem;
        }
        /* Estiliza os 3 botões do cabeçalho da Watchlist como texto clicável (estilo TradingView) */
        [data-testid="stSidebar"] div[data-testid="stHorizontalBlock"]:has(button[kind="tertiary"]) {
            border-bottom: 1px solid #2A2E39;
            padding-bottom: 2px;
            margin-top: 6px;
            margin-bottom: 8px;
        }
        [data-testid="stSidebar"] button[kind="tertiary"] {
            padding: 0px 2px;
            min-height: 1.5rem;
            font-size: 0.75rem;
            font-weight: 600;
            color: #8A93A6;
        }
        [data-testid="stSidebar"] button[kind="tertiary"]:hover {
            color: #FFFFFF;
        }
        /* Tipografia moderna e hover para os títulos das notícias */
        a.noticia-titulo {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            font-size: 0.98rem;
            font-weight: 500;
            letter-spacing: -0.01em;
            color: #E2E8F0 !important;
            text-decoration: none !important;
            display: inline-block;
            transition: color 0.15s ease;
        }
        a.noticia-titulo:hover {
            color: #4DA6FF !important;
            text-decoration: underline !important;
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

    df["EMA_9"] = df["close"].ewm(span=9, adjust=False).mean()
    df["EMA_21"] = df["close"].ewm(span=21, adjust=False).mean()

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

# Inicializa o ativo selecionado na sessão para permitir clique na Watchlist da Sidebar
if "ativo_selecionado" not in st.session_state:
    st.session_state["ativo_selecionado"] = "BOVA11"

token_brapi = MEU_TOKEN_BRAPI

def executar_varredura_unificada():
    resultados_scan, dados_grade, erros_scan = [], [], []
    barra = st.progress(0, text="Iniciando varredura unificada da carteira...")

    for idx, ticker_scan in enumerate(LISTA_CARTEIRA_B3):
        barra.progress(
            (idx + 1) / len(LISTA_CARTEIRA_B3),
            text=f"Buscando {ticker_scan} ({idx + 1}/{len(LISTA_CARTEIRA_B3)})...",
        )
        df_s, err_s = carregar_dados_brapi(ticker_scan, "3mo", "1d", token_brapi)

        if not df_s.empty and len(df_s) >= 4:
            ult, pen = df_s.iloc[-1], df_s.iloc[-2]
            fech = float(ult["close"])
            var_p = ((fech - float(pen["close"])) / float(pen["close"])) * 100
            rsi_v = float(ult["RSI"])

            # Condição IFR
            cond_ifr = (
                "🔴 Sobrecompra (≥ 70)"
                if rsi_v >= 70
                else ("🟢 Sobrevenda (≤ 30)" if rsi_v <= 30 else "⚪ Zona Neutra")
            )

            # Detecção de Cruzamento EMA 17 x EMA 72 nos últimos 3 pregões
            sinal_ema = "➖ Sem cruzamento"
            for k in [-1, -2, -3]:
                ema17_atual = float(df_s.iloc[k]["EMA_17"])
                ema72_atual = float(df_s.iloc[k]["EMA_72"])
                ema17_ant = float(df_s.iloc[k - 1]["EMA_17"])
                ema72_ant = float(df_s.iloc[k - 1]["EMA_72"])

                if ema17_ant <= ema72_ant and ema17_atual > ema72_atual:
                    sinal_ema = "🟢 Cruzou p/ Cima"
                    break
                elif ema17_ant >= ema72_ant and ema17_atual < ema72_atual:
                    sinal_ema = "🔴 Cruzou p/ Baixo"
                    break

            # Detecção de Cruzamento EMA 9 x EMA 21 nos últimos 3 pregões
            sinal_ema_curta = "➖ Sem cruzamento"
            for k in [-1, -2, -3]:
                ema9_atual = float(df_s.iloc[k]["EMA_9"])
                ema21_atual = float(df_s.iloc[k]["EMA_21"])
                ema9_ant = float(df_s.iloc[k - 1]["EMA_9"])
                ema21_ant = float(df_s.iloc[k - 1]["EMA_21"])

                if ema9_ant <= ema21_ant and ema9_atual > ema21_atual:
                    sinal_ema_curta = "🟢 Cruzou p/ Cima"
                    break
                elif ema9_ant >= ema21_ant and ema9_atual < ema21_atual:
                    sinal_ema_curta = "🔴 Cruzou p/ Baixo"
                    break

            # Cálculo de Volume Relativo (vs Média Móvel de 20 dias)
            vol_relativo = 100.0
            if "volume" in df_s.columns and len(df_s) >= 20:
                media_vol_20 = float(df_s["volume"].iloc[-20:].mean())
                vol_atual = float(ult["volume"])
                if media_vol_20 > 0:
                    vol_relativo = (vol_atual / media_vol_20) * 100

            alerta_vol = f"🔥 {vol_relativo:.0f}%" if vol_relativo >= 150 else f"{vol_relativo:.0f}%"

            # 1. Alimenta Aba 2 (Scanner)
            resultados_scan.append({
                "Ativo": ticker_scan,
                "Data": ult["time"],
                "Fechamento (R$)": fech,
                "Variação (%)": var_p,
                "RSI (14)": rsi_v,
                "Condição": cond_ifr,
                "EMA 9/21 (3D)": sinal_ema_curta,
                "EMA 17/72 (3D)": sinal_ema,
                "Vol. vs MM20": alerta_vol,
            })

            # 2. Alimenta Aba 3 (Grade de Subplots)
            candles_sub = [
                {
                    "time": r["time"],
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                }
                for _, r in df_s.iterrows()
            ]
            dados_grade.append({
                "ativo": ticker_scan,
                "var_diaria": var_p,
                "preco_fim": fech,
                "rsi": rsi_v,
                "candles": candles_sub,
                "erro": "",
            })
        else:
            erros_scan.append(f"{ticker_scan}: {err_s}")
            dados_grade.append({
                "ativo": ticker_scan,
                "var_diaria": -9999.0,
                "preco_fim": 0.0,
                "rsi": 999.0,
                "candles": [],
                "erro": err_s or "Dados insuficientes",
            })

        time.sleep(0.15)

    barra.empty()
    st.session_state["df_scanner"] = pd.DataFrame(resultados_scan)
    st.session_state["dados_grade_3m"] = dados_grade
    st.session_state["erros_scanner"] = erros_scan

# Carrega os preços da Watchlist, Scanner e Subplots automaticamente na primeira abertura
if "df_scanner" not in st.session_state:
    executar_varredura_unificada()



with st.sidebar:
    st.header("📋 Watchlist B3")

    if st.button("🔄 Atualizar Cotações", width="stretch"):
        _requisitar_brapi.clear()
        executar_varredura_unificada()
        st.rerun()

    # Busca preços e variações já carregados na sessão (sem custo extra de API)
    mapa_cotacoes = {}
    if "df_scanner" in st.session_state and not st.session_state["df_scanner"].empty:
        for _, row in st.session_state["df_scanner"].iterrows():
            mapa_cotacoes[row["Ativo"]] = (row["Fechamento (R$)"], row["Variação (%)"])

    # Estado da ordenação clicável (estilo TradingView)
    if "wl_sort_col" not in st.session_state:
        st.session_state["wl_sort_col"] = "Ativo"
        st.session_state["wl_sort_desc"] = False

    def alternar_ordenacao_wl(coluna: str):
        if st.session_state["wl_sort_col"] == coluna:
            st.session_state["wl_sort_desc"] = not st.session_state["wl_sort_desc"]
        else:
            st.session_state["wl_sort_col"] = coluna
            st.session_state["wl_sort_desc"] = coluna in ["Preço", "Var %"]

    def rotulo_coluna_wl(nome: str, chave: str) -> str:
        if st.session_state["wl_sort_col"] == chave:
            seta = "↓" if st.session_state["wl_sort_desc"] else "↑"
            return f"{nome} {seta}"
        return nome

    # Cabeçalhos clicáveis alinhados com as 3 colunas da Watchlist
    h_tk, h_pr, h_vr = st.columns([1.15, 0.85, 0.95])
    with h_tk:
        if st.button(rotulo_coluna_wl("Símbolo", "Ativo"), key="hdr_wl_ativo", type="tertiary", width="stretch"):
            alternar_ordenacao_wl("Ativo")
            st.rerun()
    with h_pr:
        if st.button(rotulo_coluna_wl("Preço", "Preço"), key="hdr_wl_preco", type="tertiary", width="stretch"):
            alternar_ordenacao_wl("Preço")
            st.rerun()
    with h_vr:
        if st.button(rotulo_coluna_wl("Var%", "Var %"), key="hdr_wl_var", type="tertiary", width="stretch"):
            alternar_ordenacao_wl("Var %")
            st.rerun()

    col_ativa_wl = st.session_state["wl_sort_col"]
    reverso_wl = st.session_state["wl_sort_desc"]

    if col_ativa_wl == "Ativo":
        lista_watchlist = sorted(LISTA_CARTEIRA_B3, reverse=reverso_wl)
    elif col_ativa_wl == "Preço":
        lista_watchlist = sorted(
            LISTA_CARTEIRA_B3,
            key=lambda t: mapa_cotacoes[t][0] if t in mapa_cotacoes else (-1.0 if reverso_wl else 999999.0),
            reverse=reverso_wl,
        )
    else:  # Var %
        lista_watchlist = sorted(
            LISTA_CARTEIRA_B3,
            key=lambda t: mapa_cotacoes[t][1] if t in mapa_cotacoes else (-9999.0 if reverso_wl else 9999.0),
            reverse=reverso_wl,
        )

    # Lista interativa em 3 colunas: Ativo | Preço | Variação
    for ticker_w in lista_watchlist:
        col_tk, col_pr, col_vr = st.columns([1.15, 0.85, 0.95])

        with col_tk:
            destaque = "primary" if st.session_state["ativo_selecionado"] == ticker_w else "secondary"
            if st.button(ticker_w, key=f"wl_{ticker_w}", type=destaque, width="stretch"):
                st.session_state["ativo_selecionado"] = ticker_w
                st.rerun()

        if ticker_w in mapa_cotacoes:
            preco_w, var_w = mapa_cotacoes[ticker_w]
            cor_w = "#26A69A" if var_w >= 0 else "#EF5350"

            with col_pr:
                st.markdown(
                    f'<div style="text-align: right; font-size: 0.82rem; font-weight: 600; color: #D1D4DC; padding-top: 6px;">{preco_w:.2f}</div>',
                    unsafe_allow_html=True,
                )
            with col_vr:
                st.markdown(
                    f'<div style="text-align: right; font-size: 0.82rem; font-weight: 600; color: {cor_w}; padding-top: 6px;">{var_w:+.2f}%</div>',
                    unsafe_allow_html=True,
                )
        else:
            with col_pr:
                st.markdown('<div style="text-align: right; color: #6C7386; font-size: 0.8rem; padding-top: 6px;">--</div>', unsafe_allow_html=True)
            with col_vr:
                st.markdown('<div style="text-align: right; color: #6C7386; font-size: 0.8rem; padding-top: 6px;">--</div>', unsafe_allow_html=True)

aba_grafico, aba_scanner, aba_subplots, aba_noticias, aba_guia = st.tabs([
    "📈 Gráfico Individual",
    "🔍 Scanner de RSI (Carteira)",
    "🗂️ Visão Geral (Subplots 3M)",
    "📰 Notícias",
    "ℹ️ Guia e Critérios",
])



with aba_grafico:
    # Controles do Gráfico Individual (movidos da Sidebar para a Aba 1)
    with st.container(border=True):
        c_at, c_tf, c_per = st.columns([1.5, 1.2, 1])

        with c_at:
            ativos_b3 = LISTA_CARTEIRA_B3 + ["Outro (digitar)..."]
            idx_padrao = (
                LISTA_CARTEIRA_B3.index(st.session_state["ativo_selecionado"])
                if st.session_state["ativo_selecionado"] in LISTA_CARTEIRA_B3
                else len(LISTA_CARTEIRA_B3)
            )
            escolha = st.selectbox("Ativo da B3", ativos_b3, index=idx_padrao)

            if escolha == "Outro (digitar)...":
                ativo = st.text_input(
                    "Código do Ativo (ex: RENT3, BPAC11)",
                    value=st.session_state["ativo_selecionado"] if st.session_state["ativo_selecionado"] not in LISTA_CARTEIRA_B3 else "MGLU3",
                ).strip().upper().replace(".SA", "")
            else:
                ativo = escolha
                st.session_state["ativo_selecionado"] = ativo

        with c_tf:
            mapa_timeframe = {"Diário (1D)": "1d", "Semanal (1S)": "1wk"}
            tf_label = st.radio("Timeframe", list(mapa_timeframe.keys()), horizontal=True)
            intervalo = mapa_timeframe[tf_label]

        with c_per:
            opcoes_periodo = ["1mo", "3mo", "6mo", "1y", "2y", "5y", "max"]
            periodo = st.selectbox("Período Histórico", opcoes_periodo, index=1)

    st.title(f"{ativo} - {tf_label}")

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
        diff_reais = preco_atual - preco_anterior
        sinal_r = "+" if diff_reais >= 0 else "-"
        st.metric(
            label="Variação Percentual",
            value=f"{variacao_pct:+.2f}%",
            delta=f"{sinal_r}R$ {abs(diff_reais):.2f}",
            border=True,
        )
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

    # Seletor visual de Médias Móveis na Aba 1
    par_medias = st.radio(
        "Médias Móveis no Gráfico:",
        ["EMA 17 / 72", "EMA 9 / 21", "Ambas (9, 17, 21 e 72)"],
        horizontal=True,
    )

    candles = [{"time": r["time"], "open": float(r["open"]), "high": float(r["high"]), "low": float(r["low"]), "close": float(r["close"])} for _, r in df.iterrows()]

    # Montagem dinâmica das séries do painel principal
    series_principal = [
        {"type": "Candlestick", "data": candles, "options": {"upColor": "#26A69A", "downColor": "#EF5350", "borderVisible": False, "wickUpColor": "#26A69A", "wickDownColor": "#EF5350"}},
    ]

    if par_medias in ["EMA 17 / 72", "Ambas (9, 17, 21 e 72)"]:
        ema_17_data = [{"time": r["time"], "value": float(r["EMA_17"])} for _, r in df.dropna(subset=["EMA_17"]).iterrows()]
        ema_72_data = [{"time": r["time"], "value": float(r["EMA_72"])} for _, r in df.dropna(subset=["EMA_72"]).iterrows()]
        series_principal.extend([
            {"type": "Line", "data": ema_17_data, "options": {"color": "#29B6F6", "lineWidth": 1, "title": "EMA 17"}},
            {"type": "Line", "data": ema_72_data, "options": {"color": "#FF6D00", "lineWidth": 1, "title": "EMA 72"}},
        ])

    if par_medias in ["EMA 9 / 21", "Ambas (9, 17, 21 e 72)"]:
        ema_9_data = [{"time": r["time"], "value": float(r["EMA_9"])} for _, r in df.dropna(subset=["EMA_9"]).iterrows()]
        ema_21_data = [{"time": r["time"], "value": float(r["EMA_21"])} for _, r in df.dropna(subset=["EMA_21"]).iterrows()]
        series_principal.extend([
            {"type": "Line", "data": ema_9_data, "options": {"color": "#00E676", "lineWidth": 1, "title": "EMA 9"}},
            {"type": "Line", "data": ema_21_data, "options": {"color": "#FFD54F", "lineWidth": 1, "title": "EMA 21"}},
        ])

    df_rsi = df.dropna(subset=["RSI"])
    rsi_data = [{"time": r["time"], "value": float(r["RSI"])} for _, r in df_rsi.iterrows()]
    linha_70 = [{"time": r["time"], "value": 70.0} for _, r in df_rsi.iterrows()]
    linha_30 = [{"time": r["time"], "value": 30.0} for _, r in df_rsi.iterrows()]

    layout_base = {
        "layout": {"background": {"color": "#131722"}, "textColor": "#D1D4DC"},
        "grid": {"vertLines": {"color": "rgba(42, 46, 57, 0.5)"}, "horzLines": {"color": "rgba(42, 46, 57, 0.5)"}},
    }

    lightweight_charts_v5_component(
        name=f"brapi_{ativo}_{intervalo}_{periodo}_{par_medias}",
        charts=[
            {
                "chart": layout_base,
                "height": 480,
                "series": series_principal,
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
    st.title("Scanner de RSI (14) - Diário (1D)")
    st.caption(f"Exibe os **{len(LISTA_CARTEIRA_B3)} ativos** da carteira em **3mo** (timeframe **1d**). Para atualizar os dados, use o botão na barra lateral.")

    filtro_condicao = st.radio(
        "Filtrar por Condição:",
        [
            "Todos",
            "Sobrevenda (≤ 30)",
            "Sobrecompra (≥ 70)",
            "Cruzamento EMA 9/21",
            "Cruzamento EMA 17/72",
            "Volume Alto (≥ 150%)",
        ],
        horizontal=True,
    )

    if "df_scanner" in st.session_state and not st.session_state["df_scanner"].empty:
        df_res = st.session_state["df_scanner"].copy()

        if filtro_condicao == "Sobrevenda (≤ 30)":
            df_res = df_res[df_res["RSI (14)"] <= 30]
        elif filtro_condicao == "Sobrecompra (≥ 70)":
            df_res = df_res[df_res["RSI (14)"] >= 70]
        elif filtro_condicao == "Cruzamento EMA 9/21":
            df_res = df_res[df_res["EMA 9/21 (3D)"] != "➖ Sem cruzamento"]
        elif filtro_condicao == "Cruzamento EMA 17/72":
            df_res = df_res[df_res["EMA 17/72 (3D)"] != "➖ Sem cruzamento"]
        elif filtro_condicao == "Volume Alto (≥ 150%)":
            df_res = df_res[df_res["Vol. vs MM20"].str.contains("🔥")]

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
                width="stretch",
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
        st.info("Nenhum dado carregado no momento. Clique em **🔄 Atualizar Cotações** na barra lateral.")
        erros_iniciais = st.session_state.get("erros_scanner", [])
        if erros_iniciais:
            st.error(f"**Motivo informado pela API:** {erros_iniciais[0]}")



with aba_subplots:
    st.title("Visão Geral - 3 Meses (Diário)")
    st.caption(f"Exibe os **{len(LISTA_CARTEIRA_B3)} ativos** em **3mo** (timeframe **1d**) com variação diária e IFR (14). Para atualizar os dados, use o botão na barra lateral.")

    col_filt_sub, col_ord_sub = st.columns(2)
    with col_filt_sub:
        filtro_ifr_grade = st.radio(
            "Filtrar gráficos por IFR:",
            ["Todos", "Sobrevenda (≤ 30)", "Sobrecompra (≥ 70)", "Extremos (≤ 30 ou ≥ 70)"],
            horizontal=True,
        )
    with col_ord_sub:
        ordenacao_sub = st.radio(
            "Ordenar grade por:",
            ["Alfabética (A-Z)", "Maior Alta (Dia)", "Maior Queda (Dia)", "Menor IFR (Sobrevenda)"],
            horizontal=True,
        )

    if "dados_grade_3m" in st.session_state and st.session_state["dados_grade_3m"]:
        lista_exibicao = list(st.session_state["dados_grade_3m"])

        if ordenacao_sub == "Maior Alta (Dia)":
            lista_exibicao.sort(key=lambda x: x["var_diaria"], reverse=True)
        elif ordenacao_sub == "Maior Queda (Dia)":
            lista_exibicao.sort(key=lambda x: x["var_diaria"] if x["candles"] else 9999.0)
        elif ordenacao_sub == "Menor IFR (Sobrevenda)":
            lista_exibicao.sort(key=lambda x: x["rsi"])

        layout_subplot = {
            "layout": {"background": {"color": "#131722"}, "textColor": "#D1D4DC"},
            "grid": {
                "vertLines": {"color": "rgba(42, 46, 57, 0.5)"},
                "horzLines": {"color": "rgba(42, 46, 57, 0.5)"},
            },
            "timeScale": {
                "barSpacing": 4,       # Deixa os candles mais finos para caber os 3 meses (~63 pregões)
                "rightOffset": 2,      # Pequena margem à direita do último candle
                "fixLeftEdge": True,   # Trava a borda esquerda no início dos 3 meses
                "fixRightEdge": True,  # Trava a borda direita no último pregão
            },
        }

        # Aplica o filtro rápido de IFR na grade visual
        if filtro_ifr_grade == "Sobrevenda (≤ 30)":
            lista_exibicao = [x for x in lista_exibicao if x["candles"] and x["rsi"] <= 30]
        elif filtro_ifr_grade == "Sobrecompra (≥ 70)":
            lista_exibicao = [x for x in lista_exibicao if x["candles"] and x["rsi"] >= 70]
        elif filtro_ifr_grade == "Extremos (≤ 30 ou ≥ 70)":
            lista_exibicao = [x for x in lista_exibicao if x["candles"] and (x["rsi"] <= 30 or x["rsi"] >= 70)]

        if not lista_exibicao:
            st.info(f"Nenhum ativo encontrado com o filtro **{filtro_ifr_grade}** no momento.")

        num_colunas = 3
        for i in range(0, len(lista_exibicao), num_colunas):
            cols = st.columns(num_colunas)
            for j in range(num_colunas):
                if i + j < len(lista_exibicao):
                    item = lista_exibicao[i + j]
                    ticker_atual = item["ativo"]

                    with cols[j]:
                        if item["candles"]:
                            var = item["var_diaria"]
                            rsi = item["rsi"]
                            cor_var = "green" if var >= 0 else "red"
                            
                            # Destaca o IFR se estiver em sobrecompra (>=70) ou sobrevenda (<=30)
                            if rsi >= 70:
                                texto_ifr = f":red[IFR: {rsi:.1f}]"
                            elif rsi <= 30:
                                texto_ifr = f":green[IFR: {rsi:.1f}]"
                            else:
                                texto_ifr = f"IFR: {rsi:.1f}"

                            st.markdown(
                                f"**{ticker_atual}** | R$ {item['preco_fim']:.2f} :{cor_var}[**({var:+.2f}%)**] | {texto_ifr}"
                            )

                            lightweight_charts_v5_component(
                                name=f"subplot_3m_{ticker_atual}",
                                charts=[
                                    {
                                        "chart": layout_subplot,
                                        "height": 260,
                                        "series": [
                                            {
                                                "type": "Candlestick",
                                                "data": item["candles"],
                                                "options": {
                                                    "upColor": "#26A69A",
                                                    "downColor": "#EF5350",
                                                    "borderVisible": False,
                                                    "wickUpColor": "#26A69A",
                                                    "wickDownColor": "#EF5350",
                                                },
                                            },
                                        ],
                                    }
                                ],
                                height=260,
                            )
                        else:
                            st.markdown(f"**{ticker_atual}**")
                            st.warning(f"Indisponível: {item['erro']}")
    else:
        st.info("Nenhum dado carregado no momento. Clique em **🔄 Atualizar Cotações** na barra lateral.")
        erros_iniciais = st.session_state.get("erros_scanner", [])
        if erros_iniciais:
            st.error(f"**Motivo informado pela API:** {erros_iniciais[0]}")



with aba_noticias:
    st.title("📰 Radar de Notícias da Carteira")
    st.caption("Manchetes recentes filtradas por ativo ou panorama geral da B3 (cache de 15 minutos).")

    col_n1, col_n2 = st.columns([1.4, 2])
    with col_n1:
        modo_noticia = st.radio(
            "Escopo das notícias:",
            ["Ativo Selecionado", "Panorama Carteira / Ibovespa"],
            horizontal=True,
        )
    with col_n2:
        opcoes_n = LISTA_CARTEIRA_B3 + ["Outro (digitar)..."]
        idx_n = (
            LISTA_CARTEIRA_B3.index(st.session_state["ativo_selecionado"])
            if st.session_state["ativo_selecionado"] in LISTA_CARTEIRA_B3
            else 0
        )
        if modo_noticia == "Ativo Selecionado":
            ticker_noticia = st.selectbox(
                "Filtrar manchetes do ativo:",
                LISTA_CARTEIRA_B3,
                index=idx_n,
            )
            termo_busca = f"{ticker_noticia} ações OR B3 when:7d"

        else:
            ticker_noticia = "Ibovespa / Carteira B3"
            termo_busca = "Ibovespa OR B3 OR dólar when:1d"

    lista_noticias = buscar_noticias_rss(termo_busca, limite=12)


    if not lista_noticias:
        st.warning(f"Nenhuma notícia recente encontrada para **{ticker_noticia}** no momento.")
    else:
        for n in lista_noticias:
            st.markdown(
                f"""
                <div style="
                    padding: 8px 4px;
                    border-bottom: 1px solid #2A2E39;
                    line-height: 1.38;
                ">
                    <a class="noticia-titulo" href="{n['link']}" target="_blank">{n['titulo']}</a>
                    <div style="
                        color: #8A93A6;
                        font-size: 0.78rem;
                        margin-top: 3px;
                    ">
                        🗞️ {n['fonte']} &nbsp;•&nbsp; 🕒 {n['data']}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )



with aba_guia:
    st.title("ℹ️ Guia de Uso e Critérios Técnicos")
    st.markdown(
        "Esta página documenta o funcionamento de cada seção do aplicativo, "
        "os indicadores calculados e as regras utilizadas nos filtros e varreduras."
    )

    st.divider()

    # 1. Barra Lateral (Watchlist B3)
    st.header(":blue[Painel Lateral (Watchlist B3)]")
    st.markdown(
        r"""
        * **Lista Interativa de Ativos:** Exibe os **29 ativos líquidos da B3** (incluindo ETFs como `BOVA11` e `SMAL11`) com cotação de fechamento e variação diária. Clicar em qualquer ativo carrega imediatamente seu gráfico na **Aba 1**.
        * **Ordenação Clicável (Estilo TradingView):** Clique diretamente nos títulos das colunas (**Símbolo**, **Preço** ou **Var%**) para alternar entre ordem crescente (`↑`) e decrescente (`↓`).
        * **Carregamento Automático e Atualização:** Ao abrir o aplicativo, todas as cotações são carregadas automaticamente. Para buscar preços atualizados durante o pregão, utilize o botão **🔄 Atualizar Cotações** no topo da barra lateral (ele limpa o cache e sincroniza a Watchlist, o Scanner e a Grade de Gráficos de uma só vez).
        """
    )

    st.divider()

    # 2. Abas do Sistema
    st.header(":blue[Estrutura das Abas]")

    col_g1, col_g2 = st.columns(2)

    with col_g1:
        with st.container(border=True):
            st.subheader("📈 Aba 1: Gráfico Individual")
            st.markdown(
                r"""
                Focada na análise detalhada de um único ativo:
                * **Controles do Gráfico:** Seletor de ativo (incluindo a opção *"Outro (digitar)..."* para consultar qualquer ticker da B3), **Timeframe** (`1d` ou `1wk`) e **Período Histórico**.
                * **Limitações da API (Brapi):** No plano gratuito, períodos acima de **3 meses (`3mo`)** funcionam apenas para `PETR4`, `VALE3`, `ITUB4` e `MGLU3`. Os demais ativos operam em **`1mo`** ou **`3mo`**.
                * **Cards e Gráfico (TradingView):** Exibem fechamento ajustado, variação percentual, **IFR (14)**, candlesticks com seletor de médias (**EMA 17/72**, **EMA 9/21** ou **Ambas**) e subpainel de IFR.
                """
            )

    with col_g2:
        with st.container(border=True):
            st.subheader("🔍 Aba 2: Scanner de RSI (Carteira)")
            st.markdown(
                r"""
                Exibe a tabela completa dos **29 ativos** da carteira em **3 meses (`1d`)**, já carregada automaticamente na abertura do app:
                * **Filtros Rápidos:** Permite isolar papéis em *Sobrevenda*, *Sobrecompra*, com *Cruzamento recente de Médias* (`9/21` ou `17/72`) ou com *Volume Anormal*.
                * **Ordenação Padrão:** A tabela inicia ordenada do **menor IFR para o maior**, destacando primeiro os ativos mais descontados.
                * **Atualização:** Utilize o botão **🔄 Atualizar Cotações** na barra lateral para renovar os dados.
                """
            )

    col_g3, col_g4 = st.columns(2)

    with col_g3:
        with st.container(border=True):
            st.subheader("🗂️ Aba 3: Visão Geral (Subplots 3M)")
            st.markdown(
                r"""
                Apresenta uma grade visual limpa (**3 gráficos por linha**) com os 29 ativos no período fixo de **3 meses** e timeframe **Diário (`1d`)**:
                * **Cabeçalho de cada Card:** Mostra o código do ativo, preço de fechamento, **variação percentual diária** e o valor atual do **IFR (14)** destacado em cor quando atinge extremos.
                * **Controles:** Permite filtrar por zonas de IFR (*Sobrevenda*, *Sobrecompra* ou *Extremos*) e ordenar os gráficos por *Ordem Alfabética*, *Maior Alta*, *Maior Queda* ou *Menor IFR*.
                """
            )

    with col_g4:
        with st.container(border=True):
            st.subheader("📰 Aba 4: Notícias")
            st.markdown(
                r"""
                Feed integrado de manchetes financeiras via **Google News RSS** (com cache de **15 minutos**):
                * **Ativo Selecionado:** Exibe as notícias mais recentes dos **últimos 7 dias** referentes ao papel escolhido (já sincronizado com a Watchlist).
                * **Panorama Carteira / Ibovespa:** Traz as manchetes das **últimas 24 horas** sobre o Ibovespa, B3 e câmbio, ordenadas da mais recente para a mais antiga.
                """
            )

    st.divider()

    # 3. Metodologia dos Indicadores
    st.header(":blue[Critérios e Metodologia dos Indicadores]")

    st.markdown(
        r"""

        | Indicador / Regra | Parâmetros e Fórmula | Critério de Sinalização |
        | :--- | :--- | :--- |
        | **Preços Ajustados** | Fator `adjustedClose / close` aplicado sobre Abertura, Máxima, Mínima e Fechamento. | Corrige distorções históricas causadas por dividendos, JCP e desdobramentos. |
        | **IFR / RSI (14)** | Média Móvel Exponencial de Wilder (`alpha = 1/14`) sobre ganhos e perdas de 14 períodos. | **≤ 30:** Sobrevenda (Verde) \| **≥ 70:** Sobrecompra (Vermelho) \| **30 a 70:** Zona Neutra. |
        | **Cruzamento EMA 9/21** | Médias Móveis Exponenciais de **9** e **21** períodos verificadas nos **últimos 3 pregões**. | **🟢 Cruzou p/ Cima:** EMA 9 superou a EMA 21 \| **🔴 Cruzou p/ Baixo:** EMA 9 perdeu a EMA 21. |
        | **Cruzamento EMA 17/72** | Médias Móveis Exponenciais de **17** e **72** períodos verificadas nos **últimos 3 pregões**. | **🟢 Cruzou p/ Cima:** EMA 17 superou a EMA 72 \| **🔴 Cruzou p/ Baixo:** EMA 17 perdeu a EMA 72. |
        | **Volume Relativo** | Comparação entre o volume financeiro do último pregão e a **Média Móvel Simples de 20 dias (MM20)**. | **🔥 Alerta de Volume:** Sinalizado quando o volume do dia é **≥ 150%** da média de 20 dias. |
        """
    )

    st.info(
        "**Aviso Legal:** Esta ferramenta tem caráter exclusivamente educacional e informativo para apoio à análise gráfica, não constituindo recomendação de compra ou venda de ativos mobiliários."
    )

    st.markdown(
        '<div style="text-align: center; font-style: italic; color: #8A93A6; font-size: 0.85rem; margin-top: 8px;">'
        'Desenvolvedor: Daniel &nbsp;-•-&nbsp; Colaboradores: Matheus e Maurício'
        '</div>',
        unsafe_allow_html=True,
    )
