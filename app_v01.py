import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st
import pandas as pd
import requests
from lightweight_charts_v5 import lightweight_charts_v5_component


# Imports e função de busca de notícias
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import quote


# Motor matemático de Opções e Vencimentos B3
import math
import calendar
import altair as alt # desenhar e sobrepor linhas verticais marcadas com rótulos no gráfico de Payoff

LETRAS_PUT_B3 = {
    1: "M", 2: "N", 3: "O", 4: "P", 5: "Q", 6: "R",
    7: "S", 8: "T", 9: "U", 10: "V", 11: "W", 12: "X",
}

def proximos_vencimentos_b3(qtd: int = 4) -> list[dict]:
    hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    vencimentos = []
    ano, mes = hoje.year, hoje.month

    while len(vencimentos) < qtd:
        cal = calendar.monthcalendar(ano, mes)
        sextas = [semana[calendar.FRIDAY] for semana in cal if semana[calendar.FRIDAY] != 0]
        terceira_sexta = datetime(ano, mes, sextas[2]).date()

        if terceira_sexta > hoje:
            dias_corridos = (terceira_sexta - hoje).days
            dias_uteis_est = max(1, round(dias_corridos * (252 / 365)))
            letra = LETRAS_PUT_B3[mes]
            vencimentos.append({
                "rotulo": f"Série {letra} • {terceira_sexta.strftime('%d/%m/%Y')} ({dias_corridos}d corridos / ~{dias_uteis_est} du)",
                "data": terceira_sexta,
                "letra": letra,
                "dias_corridos": dias_corridos,
                "dias_uteis": dias_uteis_est,
            })

        mes += 1
        if mes > 12:
            mes = 1
            ano += 1

    return vencimentos

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)

def black_scholes_put(S: float, K: float, T: float, r: float, sigma: float) -> dict:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        intrinseco = max(0.0, K - S)
        return {"premio": intrinseco, "delta": -1.0 if S < K else 0.0, "theta_dia": 0.0, "pop": 100.0 if S >= K else 0.0}

    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    premio = K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)
    delta = _norm_cdf(d1) - 1.0  # Negativo para Put (ex: -0.25)
    theta_anual = (
        -(S * _norm_pdf(d1) * sigma) / (2.0 * math.sqrt(T))
        + r * K * math.exp(-r * T) * _norm_cdf(-d2)
    )
    theta_dia = theta_anual / 252.0
    pop = _norm_cdf(d2) * 100.0  # Probabilidade estimada de expirar OTM (sem exercício)

    return {"premio": max(0.01, premio), "delta": delta, "theta_dia": theta_dia, "pop": pop}

def calcular_iv_put(premio_mercado: float, S: float, K: float, T: float, r: float) -> float:
    if premio_mercado <= max(0.0, K - S) or T <= 0:
        return 0.0
    sigma = 0.35
    for _ in range(50):
        res = black_scholes_put(S, K, T, r, sigma)
        diff = res["premio"] - premio_mercado
        if abs(diff) < 1e-4:
            break
        d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
        vega = S * _norm_pdf(d1) * math.sqrt(T)
        if vega < 1e-6:
            break
        sigma = max(0.05, min(3.0, sigma - diff / vega))
    return sigma * 100.0


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


@st.cache_data(ttl=1800, show_spinner=False)
def buscar_serie_bcb(codigo_serie: int, dias_atras: int = 400) -> list[dict]:
    hoje = datetime.now(ZoneInfo("America/Sao_Paulo"))
    inicio = hoje - timedelta(days=dias_atras)
    url = "/".join([
        "https://api.bcb.gov.br",
        "dados",
        "serie",
        f"bcdata.sgs.{codigo_serie}",
        "dados",
    ])
    params = {
        "formato": "json",
        "dataInicial": inicio.strftime("%d/%m/%Y"),
        "dataFinal": hoje.strftime("%d/%m/%Y"),
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=12)
        resp.raise_for_status()
        dados = resp.json()
        return dados if isinstance(dados, list) else []
    except Exception:
        return []


@st.cache_data(ttl=300, show_spinner=False)
def buscar_cambio_e_ouro() -> dict:
    resultado = {}
    headers = {"User-Agent": "Mozilla/5.0"}

    # 1. Dólar (Série 1 - BCB) e Euro (Série 21619 - BCB)
    for chave, serie_id in [("USDBRL", 1), ("EURBRL", 21619)]:
        serie = buscar_serie_bcb(serie_id, dias_atras=15)
        if len(serie) >= 2:
            ult = float(serie[-1]["valor"])
            ant = float(serie[-2]["valor"])
            pct = ((ult - ant) / ant) * 100.0 if ant > 0 else 0.0
            resultado[chave] = {"bid": ult, "pctChange": pct}
        elif len(serie) == 1:
            resultado[chave] = {"bid": float(serie[-1]["valor"]), "pctChange": 0.0}

    # 2. Bitcoin (BTC/BRL) via CoinGecko Public API (sem bloqueio geográfico nos EUA ou Brasil)
    try:
        host_cg = ".".join(["api", "coingecko", "com"])
        url_btc = "/".join([f"https://{host_cg}", "api", "v3", "simple", "price"])
        resp_btc = requests.get(
            url_btc,
            params={
                "ids": "bitcoin",
                "vs_currencies": "brl",
                "include_24hr_change": "true",
            },
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        if resp_btc.status_code == 200:
            btc_info = resp_btc.json().get("bitcoin", {})
            ult_btc = float(btc_info.get("brl", 0.0))
            pct_btc = float(btc_info.get("brl_24h_change", 0.0))
            if ult_btc > 0:
                resultado["BTCBRL"] = {"bid": ult_btc, "pctChange": pct_btc}
    except Exception:
        pass



    # 3. Petróleo Brent Real (US$/barril) via Yahoo Finance Chart API (BZ=F)
    try:
        host_yf = ".".join(["query1", "finance", "yahoo", "com"])
        url_brent = "/".join([f"https://{host_yf}", "v8", "finance", "chart", "BZ=F"])
        resp_brent = requests.get(
            url_brent,
            params={"range": "5d", "interval": "1d"},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=10,
        )
        if resp_brent.status_code == 200:
            meta = resp_brent.json()["chart"]["result"][0]["meta"]
            ult_brent = float(meta.get("regularMarketPrice", 0.0))
            ant_brent = float(meta.get("chartPreviousClose", meta.get("previousClose", 0.0)))
            if ult_brent > 0:
                pct_brent = ((ult_brent - ant_brent) / ant_brent) * 100.0 if ant_brent > 0 else 0.0
                resultado["BRENT"] = {"bid": ult_brent, "pctChange": pct_brent}
    except Exception:
        pass

    return resultado



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

    barra.empty()
    st.session_state["df_scanner"] = pd.DataFrame(resultados_scan)
    st.session_state["dados_grade_3m"] = dados_grade
    st.session_state["erros_scanner"] = erros_scan
    st.session_state["ultima_atualizacao"] = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M:%S")


# Carrega os preços da Watchlist, Scanner e Subplots automaticamente na primeira abertura
if "df_scanner" not in st.session_state:
    executar_varredura_unificada()


# Configurações padrão da Central de Alertas
if "cfg_alertas" not in st.session_state:
    st.session_state["cfg_alertas"] = {
        "rsi_sobrevenda": 30.0,
        "rsi_sobrecompra": 70.0,
        "vol_minimo": 150.0,
        "mon_ema_9_21": True,
        "mon_ema_17_72": True,
    }

if "alertas_preco" not in st.session_state:
    st.session_state["alertas_preco"] = []


with st.sidebar:
    st.header("📋 Watchlist B3")

    if st.button("🔄 Atualizar Cotações", width="stretch"):
        _requisitar_brapi.clear()
        executar_varredura_unificada()
        st.rerun()

    if "ultima_atualizacao" in st.session_state:
        st.markdown(
            f'<div style="text-align: center; font-size: 0.75rem; color: #e80505; font-weight: 500; margin-top: 2px; margin-bottom: 4px;">'
            f'🕒 Última leitura: {st.session_state["ultima_atualizacao"]}'
            f'</div>',
            unsafe_allow_html=True,
        )


    # Busca preços, variações e gatilhos técnicos já carregados na sessão
    mapa_cotacoes = {}
    mapa_badges_wl = {}
    cfg_a = st.session_state["cfg_alertas"]

    # Mapeia alvos de preço atingidos
    alvos_atingidos = set()
    if "df_scanner" in st.session_state and not st.session_state["df_scanner"].empty:
        precos_atuais_map = dict(
            zip(st.session_state["df_scanner"]["Ativo"], st.session_state["df_scanner"]["Fechamento (R$)"])
        )
        for ap in st.session_state["alertas_preco"]:
            p_agora = precos_atuais_map.get(ap["ativo"])
            if p_agora is not None:
                if (ap["condicao"] == "≥" and p_agora >= ap["alvo"]) or (ap["condicao"] == "≤" and p_agora <= ap["alvo"]):
                    alvos_atingidos.add(ap["ativo"])

        for _, row in st.session_state["df_scanner"].iterrows():
            tk = row["Ativo"]
            mapa_cotacoes[tk] = (row["Fechamento (R$)"], row["Variação (%)"])

            # Define ícone de destaque prioritário na Watchlist
            rsi_val_row = float(row["RSI (14)"])
            vol_num = float(str(row["Vol. vs MM20"]).replace("🔥", "").replace("%", "").strip() or 0)
            cruz_9_21 = cfg_a["mon_ema_9_21"] and row["EMA 9/21 (3D)"] != "➖ Sem cruzamento"
            cruz_17_72 = cfg_a["mon_ema_17_72"] and row["EMA 17/72 (3D)"] != "➖ Sem cruzamento"

            if tk in alvos_atingidos:
                mapa_badges_wl[tk] = "🎯"
            elif rsi_val_row <= cfg_a["rsi_sobrevenda"]:
                mapa_badges_wl[tk] = "🟢"
            elif rsi_val_row >= cfg_a["rsi_sobrecompra"]:
                mapa_badges_wl[tk] = "🔴"
            elif cruz_9_21 or cruz_17_72:
                mapa_badges_wl[tk] = "⚡"
            elif vol_num >= cfg_a["vol_minimo"]:
                mapa_badges_wl[tk] = "🔥"


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

    for ticker_w in lista_watchlist:
        col_tk, col_pr, col_vr = st.columns([1.15, 0.85, 0.95])

        with col_tk:
            destaque = "primary" if st.session_state["ativo_selecionado"] == ticker_w else "secondary"
            badge_w = mapa_badges_wl.get(ticker_w, "")
            rotulo_btn = f"{ticker_w} {badge_w}".strip()
            if st.button(rotulo_btn, key=f"wl_{ticker_w}", type=destaque, width="stretch"):
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

aba_grafico, aba_scanner, aba_subplots, aba_mercado, aba_noticias, aba_alertas, aba_opcoes, aba_guia = st.tabs([
    "📈 Gráfico Individual",
    "🔍 Scanner de RSI (Carteira)",
    "🗂️ Visão Geral (Subplots 3M)",
    "🌐 Mercado",
    "📰 Notícias",
    "🔔 Alertas",
    "🎯 Opções",
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



with aba_mercado:
    st.title("🌐 Indicadores de Mercado & Macroeconomia")
    st.caption("Panorama macroeconômico (Banco Central), câmbio, ouro, juros futuros DI e benchmarks (B3 & EUA).")

    # --- 1. MACRO BRASIL & JUROS FUTUROS DI (BANCO CENTRAL) ---
    st.subheader("🇧🇷 Juros, Inflação & Juro Real (Banco Central)")

    selic_dados = buscar_serie_bcb(432, dias_atras=720)       # Meta Selic (% a.a.)
    cdi_dados = buscar_serie_bcb(4389, dias_atras=720)        # CDI Anualizado (% a.a.)
    ipca_dados = buscar_serie_bcb(433, dias_atras=400)[-12:]  # Últimos 12 meses do IPCA

    selic_val = float(selic_dados[-1]["valor"]) if selic_dados else 0.0
    cdi_val = float(cdi_dados[-1]["valor"]) if cdi_dados else 0.0

    # Cálculo composto do IPCA acumulado nos últimos 12 meses
    ipca_12m = 0.0
    ipca_mes = 0.0
    if ipca_dados:
        ipca_mes = float(ipca_dados[-1]["valor"])
        fator_ipca = 1.0
        for item_ipca in ipca_dados:
            fator_ipca *= 1 + (float(item_ipca["valor"]) / 100.0)
        ipca_12m = (fator_ipca - 1.0) * 100.0

    # Cálculo do Juro Real Ex-Post (Equação de Fisher: CDI descontado do IPCA 12M)
    juro_real = (((1.0 + cdi_val / 100.0) / (1.0 + ipca_12m / 100.0)) - 1.0) * 100.0 if ipca_12m > -100 else 0.0
    spread_simples = cdi_val - ipca_12m

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Taxa Selic Meta", f"{selic_val:.2f}% a.a.", border=True)
    m2.metric("CDI Anualizado", f"{cdi_val:.2f}% a.a.", border=True)
    m3.metric(
        "IPCA (Acum. 12M)",
        f"{ipca_12m:.2f}%",
        delta=f"Último mês: {ipca_mes:+.2f}%",
        delta_color="off",
        border=True,
    )
    m4.metric(
        "Juro Real (CDI − IPCA)",
        f"{juro_real:.2f}% a.a.",
        delta=f"Spread nominal: {spread_simples:+.2f} p.p.",
        delta_color="off",
        border=True,
    )

    st.divider()

    # --- 2. CÂMBIO, OURO & COMMODITIES ---
    st.subheader("💱 Câmbio, Ouro & Commodities")

    cotacoes_fx = buscar_cambio_e_ouro()

    def extrair_fx(chave: str):
        item = cotacoes_fx.get(chave, {})
        bid = float(item.get("bid", 0.0))
        pct = float(item.get("pctChange", 0.0))
        return bid, pct

    usd_val, usd_pct = extrair_fx("USDBRL")
    eur_val, eur_pct = extrair_fx("EURBRL")
    btc_val, btc_pct = extrair_fx("BTCBRL")
    xau_usd, xau_pct = extrair_fx("XAUUSD")

    brent_val, brent_pct = extrair_fx("BRENT")
    df_gold11, _ = carregar_dados_brapi("GOLD11", "3mo", "1d", token_brapi)

    def resumo_ativo_b3(df_temp: pd.DataFrame):
        if df_temp.empty or len(df_temp) < 2:
            return 0.0, 0.0
        ult_p = float(df_temp.iloc[-1]["close"])
        ant_p = float(df_temp.iloc[-2]["close"])
        return ult_p, ((ult_p - ant_p) / ant_p) * 100.0

    gold11_val, gold11_pct = resumo_ativo_b3(df_gold11)

    c_fx1, c_fx2, c_fx3, c_fx4, c_fx5 = st.columns(5)
    c_fx1.metric("Dólar (USD/BRL)", f"R$ {usd_val:.2f}", delta=f"{usd_pct:+.2f}%", border=True)
    c_fx2.metric("Euro (EUR/BRL)", f"R$ {eur_val:.2f}", delta=f"{eur_pct:+.2f}%", border=True)
    c_fx3.metric("Ouro B3 (GOLD11)", f"R$ {gold11_val:.2f}", delta=f"{gold11_pct:+.2f}%", border=True)
    c_fx4.metric("Petróleo Brent", f"US$ {brent_val:.2f}", delta=f"{brent_pct:+.2f}%", border=True)
    c_fx5.metric("Bitcoin (BTC/BRL)", f"R$ {btc_val:,.0f}".replace(",", "."), delta=f"{btc_pct:+.2f}%", border=True)


    st.divider()

    # --- 3. GRÁFICOS DE REFERÊNCIA (3 MESES - DIÁRIO) ---
    st.subheader("📊 Benchmarks de Mercado (3 Meses • Diário)")

    benchmarks = [
        ("Ibovespa (BOVA11)", "BOVA11"),
        ("S&P 500 Brasil (IVVB11)", "IVVB11"),
        ("Ouro B3 (GOLD11)", "GOLD11"),
    ]

    layout_bench = {
        "layout": {"background": {"color": "#131722"}, "textColor": "#D1D4DC"},
        "grid": {
            "vertLines": {"color": "rgba(42, 46, 57, 0.5)"},
            "horzLines": {"color": "rgba(42, 46, 57, 0.5)"},
        },
        "timeScale": {
            "barSpacing": 5,
            "rightOffset": 2,
            "fixLeftEdge": True,
            "fixRightEdge": True,
        },
    }

    serie_di_3m = []
    for item_d in cdi_dados:
        try:
            dt_iso = datetime.strptime(item_d["data"], "%d/%m/%Y").strftime("%Y-%m-%d")
            serie_di_3m.append({"time": dt_iso, "value": float(item_d["valor"])})
        except Exception:
            pass

    for idx_b in range(0, 4, 2):
        cols_b = st.columns(2)
        for j_b in range(2):
            pos = idx_b + j_b
            with cols_b[j_b]:
                if pos < len(benchmarks):
                    titulo_b, ticker_b = benchmarks[pos]
                    df_b, err_b = carregar_dados_brapi(ticker_b, "3mo", "1d", token_brapi)
                    if not df_b.empty and len(df_b) >= 2:
                        p_fim, v_dia = resumo_ativo_b3(df_b)
                        rsi_b = float(df_b.iloc[-1]["RSI"])
                        cor_b = "green" if v_dia >= 0 else "red"
                        st.markdown(
                            f"**{titulo_b}** | R$ {p_fim:.2f} :{cor_b}[**({v_dia:+.2f}%)**] | IFR: {rsi_b:.1f}"
                        )
                        candles_b = [
                            {
                                "time": r["time"],
                                "open": float(r["open"]),
                                "high": float(r["high"]),
                                "low": float(r["low"]),
                                "close": float(r["close"]),
                            }
                            for _, r in df_b.iterrows()
                        ]
                        lightweight_charts_v5_component(
                            name=f"bench_3m_{ticker_b}",
                            charts=[
                                {
                                    "chart": layout_bench,
                                    "height": 270,
                                    "series": [
                                        {
                                            "type": "Candlestick",
                                            "data": candles_b,
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
                            height=270,
                        )
                    else:
                        st.warning(f"Não foi possível carregar **{titulo_b}**: {err_b}")
                else:
                    # 4º Quadrante: Histórico da Taxa DI / CDI (Banco Central - Série 4389)
                    if len(serie_di_3m) >= 2:
                        taxa_atual_di = serie_di_3m[-1]["value"]
                        taxa_ant_di = serie_di_3m[-2]["value"]
                        diff_di = taxa_atual_di - taxa_ant_di
                        cor_di = "red" if diff_di > 0 else "green"
                        st.markdown(
                            f"**Taxa DI / CDI (2 Anos • BCB)** | {taxa_atual_di:.2f}% a.a. :{cor_di}[**({diff_di:+.2f} p.p.)**]"
                        )
                        lightweight_charts_v5_component(
                            name="bench_3m_di_360",
                            charts=[
                                {
                                    "chart": layout_bench,
                                    "height": 270,
                                    "series": [
                                        {
                                            "type": "Line",
                                            "data": serie_di_3m,
                                            "options": {
                                                "color": "#FFA726",
                                                "lineWidth": 2,
                                                "title": "DI (% a.a.)",
                                            },
                                        },
                                    ],
                                }
                            ],
                            height=270,
                        )
                    else:
                        st.warning("Histórico da taxa DI indisponível no Banco Central.")



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


with aba_alertas:
    st.title("🔔 Central de Alertas & Gatilhos Técnicos")
    st.caption("Monitoramento automático da carteira B3 e alertas personalizados de preço-alvo.")

    # --- 1. CONFIGURAÇÃO DOS GATILHOS TÉCNICOS ---
    with st.expander("⚙️ Configurar Parâmetros dos Gatilhos Técnicos", expanded=False):
        c_cfg1, c_cfg2, c_cfg3 = st.columns(3)
        with c_cfg1:
            novo_sv = st.number_input(
                "IFR Sobrevenda (≤)",
                min_value=5.0,
                max_value=45.0,
                value=float(st.session_state["cfg_alertas"]["rsi_sobrevenda"]),
                step=1.0,
            )
        with c_cfg2:
            novo_sc = st.number_input(
                "IFR Sobrecompra (≥)",
                min_value=55.0,
                max_value=95.0,
                value=float(st.session_state["cfg_alertas"]["rsi_sobrecompra"]),
                step=1.0,
            )
        with c_cfg3:
            novo_vol = st.number_input(
                "Volume Relativo Mínimo (%)",
                min_value=100.0,
                max_value=500.0,
                value=float(st.session_state["cfg_alertas"]["vol_minimo"]),
                step=10.0,
            )

        c_chk1, c_chk2, c_btn_cfg = st.columns([1.2, 1.2, 1])
        with c_chk1:
            mon_9_21 = st.checkbox(
                "Alertar Cruzamento EMA 9/21 (3D)",
                value=st.session_state["cfg_alertas"]["mon_ema_9_21"],
            )
        with c_chk2:
            mon_17_72 = st.checkbox(
                "Alertar Cruzamento EMA 17/72 (3D)",
                value=st.session_state["cfg_alertas"]["mon_ema_17_72"],
            )
        with c_btn_cfg:
            if st.button("💾 Aplicar Regras", width="stretch"):
                st.session_state["cfg_alertas"] = {
                    "rsi_sobrevenda": novo_sv,
                    "rsi_sobrecompra": novo_sc,
                    "vol_minimo": novo_vol,
                    "mon_ema_9_21": mon_9_21,
                    "mon_ema_17_72": mon_17_72,
                }
                st.rerun()

    # --- 2. ALERTAS PERSONALIZADOS DE PREÇO-ALVO ---
    with st.expander("🎯 Criar Alerta de Preço-Alvo (R$)", expanded=False):
        ca1, ca2, ca3, ca4 = st.columns([1.3, 1.1, 1.1, 1])
        with ca1:
            alvo_ativo = st.selectbox("Ativo:", LISTA_CARTEIRA_B3, key="sel_alvo_ativo")
        with ca2:
            alvo_cond = st.selectbox("Condição:", ["≥ (Romper Alta)", "≤ (Cair Abaixo)"], key="sel_alvo_cond")
        with ca3:
            preco_sug = mapa_cotacoes.get(alvo_ativo, (20.0, 0.0))[0]
            alvo_preco = st.number_input("Preço Alvo (R$):", min_value=0.01, value=float(round(preco_sug, 2)), step=0.10)
        with ca4:
            st.markdown("<div style='padding-top: 28px;'></div>", unsafe_allow_html=True)
            if st.button("➕ Adicionar Alerta", width="stretch"):
                simbolo_cond = "≥" if "≥" in alvo_cond else "≤"
                st.session_state["alertas_preco"].append({
                    "ativo": alvo_ativo,
                    "condicao": simbolo_cond,
                    "alvo": float(alvo_preco),
                })
                st.rerun()

        if st.session_state["alertas_preco"]:
            st.markdown("**Alertas de preço cadastrados nesta sessão:**")
            for idx_ap, ap in enumerate(st.session_state["alertas_preco"]):
                col_ap_txt, col_ap_del = st.columns([4, 1])
                p_atual_ap = mapa_cotacoes.get(ap["ativo"], (0.0, 0.0))[0]
                atingiu = (ap["condicao"] == "≥" and p_atual_ap >= ap["alvo"]) or (ap["condicao"] == "≤" and p_atual_ap <= ap["alvo"])
                status_ap = "🎯 **ATINGIDO!**" if atingiu else "⏳ Aguardando"
                col_ap_txt.write(
                    f"• **{ap['ativo']}** {ap['condicao']} **R$ {ap['alvo']:.2f}** (Atual: R$ {p_atual_ap:.2f}) — {status_ap}"
                )
                if col_ap_del.button("🗑️ Remover", key=f"del_ap_{idx_ap}", width="stretch"):
                    st.session_state["alertas_preco"].pop(idx_ap)
                    st.rerun()

    st.divider()

    # --- 3. PAINEL DE GATILHOS DISPARADOS NA CARTEIRA ---
    if "df_scanner" in st.session_state and not st.session_state["df_scanner"].empty:
        df_al = st.session_state["df_scanner"].copy()
        cfg = st.session_state["cfg_alertas"]
        lista_disparos = []

        # Verifica alertas de preço atingidos
        for ap in st.session_state["alertas_preco"]:
            p_agora = mapa_cotacoes.get(ap["ativo"], (None, 0.0))[0]
            if p_agora is not None:
                if (ap["condicao"] == "≥" and p_agora >= ap["alvo"]) or (ap["condicao"] == "≤" and p_agora <= ap["alvo"]):
                    lista_disparos.append({
                        "ativo": ap["ativo"],
                        "tipo": "🎯 Preço-Alvo",
                        "cor": "#FFD54F",
                        "preco": p_agora,
                        "var": mapa_cotacoes[ap["ativo"]][1],
                        "descricao": f"Cotação atual (R$ {p_agora:.2f}) atingiu o alvo {ap['condicao']} R$ {ap['alvo']:.2f}.",
                    })

        # Verifica gatilhos técnicos nos 29 ativos
        for _, r in df_al.iterrows():
            tk = r["Ativo"]
            fech_r = float(r["Fechamento (R$)"])
            var_r = float(r["Variação (%)"])
            rsi_r = float(r["RSI (14)"])
            vol_r = float(str(r["Vol. vs MM20"]).replace("🔥", "").replace("%", "").strip() or 0)

            if rsi_r <= cfg["rsi_sobrevenda"]:
                lista_disparos.append({
                    "ativo": tk,
                    "tipo": "🟢 Sobrevenda (IFR)",
                    "cor": "#26A69A",
                    "preco": fech_r,
                    "var": var_r,
                    "descricao": f"IFR (14) em {rsi_r:.2f} (abaixo do limite de {cfg['rsi_sobrevenda']:.0f}).",
                })
            elif rsi_r >= cfg["rsi_sobrecompra"]:
                lista_disparos.append({
                    "ativo": tk,
                    "tipo": "🔴 Sobrecompra (IFR)",
                    "cor": "#EF5350",
                    "preco": fech_r,
                    "var": var_r,
                    "descricao": f"IFR (14) em {rsi_r:.2f} (acima do limite de {cfg['rsi_sobrecompra']:.0f}).",
                })

            if cfg["mon_ema_9_21"] and r["EMA 9/21 (3D)"] != "➖ Sem cruzamento":
                lista_disparos.append({
                    "ativo": tk,
                    "tipo": "⚡ Cruzamento EMA 9/21",
                    "cor": "#4DA6FF",
                    "preco": fech_r,
                    "var": var_r,
                    "descricao": f"Sinal recente nos últimos 3 pregões: {r['EMA 9/21 (3D)']}.",
                })

            if cfg["mon_ema_17_72"] and r["EMA 17/72 (3D)"] != "➖ Sem cruzamento":
                lista_disparos.append({
                    "ativo": tk,
                    "tipo": "⚡ Cruzamento EMA 17/72",
                    "cor": "#FFA726",
                    "preco": fech_r,
                    "var": var_r,
                    "descricao": f"Sinal recente nos últimos 3 pregões: {r['EMA 17/72 (3D)']}.",
                })

            if vol_r >= cfg["vol_minimo"]:
                lista_disparos.append({
                    "ativo": tk,
                    "tipo": "🔥 Volume Anormal",
                    "cor": "#FF7043",
                    "preco": fech_r,
                    "var": var_r,
                    "descricao": f"Volume financeiro em {vol_r:.0f}% da média de 20 dias (gatilho ≥ {cfg['vol_minimo']:.0f}%).",
                })

        # Resumo no topo da aba
        k1, k2, k3 = st.columns(3)
        k1.metric("Total de Alertas Ativos", len(lista_disparos), border=True)
        k2.metric("Ativos Sinalizados", len({d["ativo"] for d in lista_disparos}), border=True)
        k3.metric("Alertas de Preço-Alvo", len(st.session_state["alertas_preco"]), border=True)

        if not lista_disparos:
            st.info("Nenhum gatilho técnico disparado na carteira com os parâmetros atuais.")
        else:
            filtro_tipo_alerta = st.radio(
                "Filtrar alertas por categoria:",
                ["Todos", "🎯 Preço-Alvo", "🟢 Sobrevenda (IFR)", "🔴 Sobrecompra (IFR)", "⚡ Cruzamento EMA", "🔥 Volume Anormal"],
                horizontal=True,
            )

            for idx_d, d in enumerate(lista_disparos):
                if filtro_tipo_alerta != "Todos" and not d["tipo"].startswith(filtro_tipo_alerta):
                    continue

                with st.container(border=True):
                    c_info, c_acao = st.columns([4.5, 1])
                    with c_info:
                        cor_v = "green" if d["var"] >= 0 else "red"
                        st.markdown(
                            f"**{d['ativo']}** &nbsp;|&nbsp; <span style='color:{d['cor']}; font-weight:600;'>{d['tipo']}</span> "
                            f"&nbsp;|&nbsp; R$ {d['preco']:.2f} :{cor_v}[**({d['var']:+.2f}%)**]",
                            unsafe_allow_html=True,
                        )
                        st.caption(d["descricao"])
                    with c_acao:
                        if st.button("📈 Selecionar", key=f"btn_al_{idx_d}_{d['ativo']}", width="stretch"):
                            st.session_state["ativo_selecionado"] = d["ativo"]
                            st.rerun()
    else:
        st.info("Nenhum dado carregado no momento. Clique em **🔄 Atualizar Cotações** na barra lateral.")



with aba_opcoes:
    st.title("🎯 Bancada de Opções — Venda de Put (B3)")
    st.caption(
        "Grade de Strikes OTM, precificação Black-Scholes, taxas anualizadas e simulador de payoff para geração de renda com Venda de Put."
    )

    # Busca Selic vigente do Banco Central para taxa livre de risco (r)
    selic_op_dados = buscar_serie_bcb(432, dias_atras=60)
    taxa_selic_anual = (float(selic_op_dados[-1]["valor"]) / 100.0) if selic_op_dados else 0.1325

    # --- SEÇÃO 1: CONTROLES DO ATIVO E VENCIMENTO ---
    with st.container(border=True):
        c_op1, c_op2, c_op3 = st.columns([1.2, 1.8, 1])

        with c_op1:
            idx_op = (
                LISTA_CARTEIRA_B3.index(st.session_state["ativo_selecionado"])
                if st.session_state["ativo_selecionado"] in LISTA_CARTEIRA_B3
                else 0
            )
            ativo_op = st.selectbox("Ativo-Objeto (B3):", LISTA_CARTEIRA_B3, index=idx_op, key="sel_ativo_opcoes")
            st.session_state["ativo_selecionado"] = ativo_op

        lista_vencs = proximos_vencimentos_b3(4)
        with c_op2:
            rotulos_venc = [v["rotulo"] for v in lista_vencs]
            venc_escolhido_rot = st.selectbox("Vencimento (3ª Sexta-feira B3):", rotulos_venc, index=0)
            venc_info = next(v for v in lista_vencs if v["rotulo"] == venc_escolhido_rot)

        df_op, err_op = carregar_dados_brapi(ativo_op, "3mo", "1d", token_brapi)
        if not df_op.empty and len(df_op) >= 15:
            preco_spot = float(df_op.iloc[-1]["close"])
            retornos_log = (df_op["close"] / df_op["close"].shift(1)).dropna().apply(math.log)
            hv_anual = float(retornos_log.std() * math.sqrt(252)) * 100.0
        else:
            preco_spot = mapa_cotacoes.get(ativo_op, (30.0, 0.0))[0]
            hv_anual = 32.0

        with c_op3:
            vol_usada = st.number_input(
                "Volatilidade Implícita / HV (% a.a.):",
                min_value=5.0,
                max_value=200.0,
                value=float(round(hv_anual, 1)),
                step=1.0,
                help="Preenchida automaticamente com a Volatilidade Histórica de 3 meses do ativo. Ajuste se a IV do book estiver maior.",
            )

    # Cards de Contexto do Ativo-Objeto
    rsi_op_val = float(df_op.iloc[-1]["RSI"]) if (not df_op.empty and "RSI" in df_op.columns) else 50.0
    o1, o2, o3, o4 = st.columns(4)
    o1.metric(f"Cotação {ativo_op}", f"R$ {preco_spot:.2f}", border=True)
    o2.metric("Volatilidade Histórica (3M)", f"{hv_anual:.1f}% a.a.", border=True)
    o3.metric("IFR (14) Atual", f"{rsi_op_val:.1f} pts", border=True)
    o4.metric("Taxa Selic (Livre de Risco)", f"{taxa_selic_anual * 100:.2f}% a.a.", border=True)

    st.divider()

    # --- SEÇÃO 2: GRADE DE STRIKES OTM PARA VENDA DE PUT ---
    st.subheader(f"📋 Grade de Strikes OTM — Série {venc_info['letra']} ({venc_info['data'].strftime('%d/%m/%Y')})")

    T_anos = venc_info["dias_uteis"] / 252.0
    sigma_dec = vol_usada / 100.0
    raiz_ticker = ativo_op[:4]

    # Gera 7 strikes OTM / ATM (-10% até 0% em passos de 0.50 ou 0.25 conforme o preço)
    passo_strike = 0.25 if preco_spot < 15 else (0.50 if preco_spot < 50 else 1.00)
    strike_atm = round(preco_spot / passo_strike) * passo_strike

    linhas_grade_put = []
    for degrau in range(0, 7):
        k_strike = round(strike_atm - (degrau * passo_strike), 2)
        if k_strike <= 0:
            continue

        dist_pct = ((k_strike - preco_spot) / preco_spot) * 100.0
        bs = black_scholes_put(preco_spot, k_strike, T_anos, taxa_selic_anual, sigma_dec)
        premio_est = bs["premio"]
        taxa_operacao = (premio_est / k_strike) * 100.0
        taxa_anualizada = ((1.0 + premio_est / k_strike) ** (252.0 / venc_info["dias_uteis"]) - 1.0) * 100.0
        breakeven = k_strike - premio_est
        desconto_total = ((breakeven - preco_spot) / preco_spot) * 100.0
        codigo_ref = f"{raiz_ticker}{venc_info['letra']}{int(round(k_strike * 100))}"

        linhas_grade_put.append({
            "Ticker Ref.": codigo_ref,
            "Strike (R$)": k_strike,
            "Dist. Spot (%)": dist_pct,
            "Prêmio Teórico (R$)": premio_est,
            "Taxa / Strike (%)": taxa_operacao,
            "Taxa Anual. (% a.a.)": taxa_anualizada,
            "Breakeven (R$)": breakeven,
            "Desconto Total (%)": desconto_total,
            "Delta (Δ)": bs["delta"],
            "Prob. Não-Exercício": bs["pop"],
        })

    df_grade_put = pd.DataFrame(linhas_grade_put)
    st.dataframe(
        df_grade_put,
        width="stretch",
        hide_index=True,
        column_config={
            "Strike (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
            "Dist. Spot (%)": st.column_config.NumberColumn(format="%+.2f%%"),
            "Prêmio Teórico (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
            "Taxa / Strike (%)": st.column_config.NumberColumn(format="%.2f%%"),
            "Taxa Anual. (% a.a.)": st.column_config.NumberColumn(format="%.1f%%"),
            "Breakeven (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
            "Desconto Total (%)": st.column_config.NumberColumn(format="%+.2f%%"),
            "Delta (Δ)": st.column_config.NumberColumn(format="%.2f"),
            "Prob. Não-Exercício": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
        },
    )

    st.divider()

    # --- SEÇÃO 3: SIMULADOR DE POSIÇÃO & PAYOFF NO VENCIMENTO ---
    st.subheader("🧮 Simulador de Venda de Put & Payoff no Vencimento")

    strikes_disp = [r["Strike (R$)"] for r in linhas_grade_put]
    idx_k_padrao = min(2, len(strikes_disp) - 1) if strikes_disp else 0

    sp1, sp2, sp3 = st.columns(3)
    with sp1:
        k_sim = st.selectbox("Strike da Put Vendida (R$):", strikes_disp, index=idx_k_padrao)
    with sp2:
        premio_sug_sim = next(
            (r["Prêmio Teórico (R$)"] for r in linhas_grade_put if r["Strike (R$)"] == k_sim),
            0.50,
        )
        premio_real = st.number_input(
            "Prêmio Recebido no Book (R$ / ação):",
            min_value=0.01,
            value=float(round(premio_sug_sim, 2)),
            step=0.01,
        )
    with sp3:
        qtd_opcoes = st.number_input(
            "Quantidade de Opções Vendidas:",
            min_value=100,
            max_value=100000,
            value=1000,
            step=100,
        )

    credito_total = premio_real * qtd_opcoes
    caixa_garantia = k_sim * qtd_opcoes
    yield_operacao = (premio_real / k_sim) * 100.0
    yield_anual = ((1.0 + premio_real / k_sim) ** (252.0 / venc_info["dias_uteis"]) - 1.0) * 100.0
    pm_exercicio = k_sim - premio_real
    iv_implicita = calcular_iv_put(premio_real, preco_spot, k_sim, T_anos, taxa_selic_anual)

    r1, r2, r3, r4 = st.columns(4)
    r1.metric(
        "Crédito Líquido Recebido",
        f"R$ {credito_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        delta=f"Taxa: {yield_operacao:.2f}% ({yield_anual:.1f}% a.a.)",
        border=True,
    )
    r2.metric(
        "Caixa / Garantia p/ Exercício",
        f"R$ {caixa_garantia:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        delta=f"{qtd_opcoes} ações @ R$ {k_sim:.2f}",
        delta_color="off",
        border=True,
    )
    r3.metric(
        "Preço Médio se Exercido (Breakeven)",
        f"R$ {pm_exercicio:.2f}",
        delta=f"{((pm_exercicio - preco_spot) / preco_spot) * 100:+.2f}% abaixo do spot",
        border=True,
    )
    r4.metric(
        "Volatilidade Implícita (IV Book)",
        f"{iv_implicita:.1f}% a.a.",
        delta=f"HV 3M: {hv_anual:.1f}% a.a.",
        delta_color="off",
        border=True,
    )

    # Gráfico de Payoff no Vencimento com Linhas Verticais (Breakeven, Spot e ±1 Desvio Padrão)
    vol_para_sigma = (iv_implicita / 100.0) if iv_implicita > 0 else sigma_dec
    desvio_1_reais = preco_spot * vol_para_sigma * math.sqrt(T_anos)
    sigma_inf = round(max(0.01, preco_spot - desvio_1_reais), 2)
    sigma_sup = round(preco_spot + desvio_1_reais, 2)


    # Centraliza o eixo X em torno do ponto médio entre Strike e Spot
    centro_x = (k_sim + preco_spot) / 2.0
    alcance_x = max(abs(sigma_sup - centro_x), abs(centro_x - sigma_inf), abs(preco_spot - k_sim) * 1.4, preco_spot * 0.08) * 1.15
    faixa_min = round(max(0.01, centro_x - alcance_x), 2)
    faixa_max = round(centro_x + alcance_x, 2)
    passo_eixo = max(0.05, round((faixa_max - faixa_min) / 80, 2))

    pontos_payoff = []
    p_iter = faixa_min
    while p_iter <= faixa_max:
        lucro_acao = premio_real if p_iter >= k_sim else (premio_real - (k_sim - p_iter))
        pontos_payoff.append({
            "preco": round(p_iter, 2),
            "resultado": round(lucro_acao * qtd_opcoes, 2),
        })
        p_iter += passo_eixo

    df_payoff_alt = pd.DataFrame(pontos_payoff)

    # Tabela de referências verticais (Desvio Padrão com linha mais fina)
    df_refs = pd.DataFrame([
        {"preco": sigma_inf, "rotulo": f"-1σ (R$ {sigma_inf:.2f})", "cor": "#FFF243", "largura": 1.0},
        {"preco": round(pm_exercicio, 2), "rotulo": f"Breakeven (R$ {pm_exercicio:.2f})", "cor": "#FC0000", "largura": 3.0},
        {"preco": round(k_sim, 2), "rotulo": f"Strike (R$ {k_sim:.2f})", "cor": "#FFFFFF", "largura": 1.0},
        {"preco": round(preco_spot, 2), "rotulo": f"Spot (R$ {preco_spot:.2f})", "cor": "#29B6F6", "largura": 3.0},
        {"preco": sigma_sup, "rotulo": f"+1σ (R$ {sigma_sup:.2f})", "cor": "#FFF243", "largura": 1.0},
    ])

    # Centraliza o eixo Y em torno da linha zero (equilibrando lucro máximo e prejuízo exibido)
    max_lucro = float(df_payoff_alt["resultado"].max()) if not df_payoff_alt.empty else 100.0
    min_prej = float(df_payoff_alt["resultado"].min()) if not df_payoff_alt.empty else -100.0
    amplitude_y = max(abs(max_lucro) * 2.2, abs(min_prej) * 1.15, 100.0)
    y_topo_label = amplitude_y * 0.55
    y_min_chart = -amplitude_y * 0.75


    escala_x_travada = alt.Scale(domain=[faixa_min, faixa_max], zero=False, nice=False)
    escala_y_travada = alt.Scale(domain=[y_min_chart, y_topo_label], zero=False, nice=False)

    # 0. Faixa Sombreada Transparente entre -1σ e +1σ (68,2% de probabilidade)
    faixa_sigma = alt.Chart(pd.DataFrame([{"x1": sigma_inf, "x2": sigma_sup}])).mark_rect(
        color="#FFF243",
        opacity=0.08,
        clip=True,
    ).encode(
        x=alt.X("x1:Q", scale=escala_x_travada),
        x2="x2:Q",
    )

    # 1. Curva de Payoff
    curva = alt.Chart(df_payoff_alt).mark_line(color="#26A69A", strokeWidth=3, clip=True).encode(
        x=alt.X("preco:Q", title="Preço no Vencimento (R$)", scale=escala_x_travada),
        y=alt.Y("resultado:Q", title="Resultado Líquido (R$)", scale=escala_y_travada),
        tooltip=[
            alt.Tooltip("preco:Q", title="Preço Venc. (R$)", format=".2f"),
            alt.Tooltip("resultado:Q", title="Resultado (R$)", format=",.2f"),
        ],
    )

    # 2. Linha Horizontal Zero (Lucro / Prejuízo)
    linha_zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(
        color="#6C7386", strokeDash=[3, 3], strokeWidth=1
    ).encode(y=alt.Y("y:Q", scale=escala_y_travada))

    # 3. Linhas Verticais de Referência
    regras_verticais = alt.Chart(df_refs).mark_rule(strokeDash=[5, 4], clip=True).encode(
        x=alt.X("preco:Q", scale=escala_x_travada),
        strokeWidth=alt.StrokeWidth("largura:Q", scale=None, legend=None),
        color=alt.Color("rotulo:N", scale=alt.Scale(
            domain=df_refs["rotulo"].tolist(),
            range=df_refs["cor"].tolist(),
        ), legend=alt.Legend(title="Referências no Vencimento", orient="top")),
        tooltip=[
            alt.Tooltip("rotulo:N", title="Referência"),
            alt.Tooltip("preco:Q", title="Preço (R$)", format=".2f"),
        ],
    )

    grafico_payoff = (faixa_sigma + curva + linha_zero + regras_verticais).properties(height=320).interactive()

    st.altair_chart(grafico_payoff, width="stretch")


    st.divider()

    # --- SEÇÃO 4: RADAR DE CANDIDATAS A VENDA DE PUT NA CARTEIRA ---
    st.subheader("🔍 Radar de Candidatas à Venda de Put (Carteira B3)")
    st.caption("Ativos ordenados pelo menor IFR (14) — papéis descontados onde os prêmios de Put costumam oferecer melhor relação risco/retorno.")

    if "df_scanner" in st.session_state and not st.session_state["df_scanner"].empty:
        df_cand = st.session_state["df_scanner"][["Ativo", "Fechamento (R$)", "Variação (%)", "RSI (14)", "Condição", "EMA 9/21 (3D)"]].copy()
        df_cand = df_cand.sort_values("RSI (14)", ascending=True).head(10).reset_index(drop=True)
        st.dataframe(
            df_cand,
            width="stretch",
            hide_index=True,
            column_config={
                "Fechamento (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
                "Variação (%)": st.column_config.NumberColumn(format="%+.2f%%"),
                "RSI (14)": st.column_config.ProgressColumn(format="%.2f", min_value=0, max_value=100),
            },
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
        * **Carregamento Automático e Horário de Leitura:** Ao abrir o aplicativo, todas as cotações são carregadas automaticamente com registro de data e hora no fuso de Brasília (**🕒 Última leitura**). O botão **🔄 Atualizar Cotações** limpa o cache e sincroniza toda a carteira.
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
            st.subheader("🌐 Aba 4: Mercado")
            st.markdown(
                r"""
                Painel macroeconômico e de benchmarks globais:
                * **Juros & Inflação (Banco Central):** Exibe **Selic Meta**, **CDI Anualizado**, **IPCA acumulado em 12 meses** e o **Juro Real (CDI − IPCA)** via Equação de Fisher.
                * **Câmbio & Commodities:** Acompanha **Dólar (USD/BRL)**, **Euro (EUR/BRL)**, **Ouro Spot**, **Petróleo Brent (US$/barril)** e **Bitcoin (`BTC/BRL`)**.
                * **Gráficos de Referência:** Exibe **Ibovespa (`BOVA11`)**, **S&P 500 (`IVVB11`)**, **Ouro B3 (`GOLD11`)** e a curva histórica da **Taxa DI / CDI (720 dias)**.
                """
            )

    col_g5, col_g6 = st.columns(2)

    with col_g5:
        with st.container(border=True):
            st.subheader("📰 Aba 5: Notícias")
            st.markdown(
                r"""
                Feed integrado de manchetes financeiras via **Google News RSS** (com cache de **15 minutos**):
                * **Ativo Selecionado:** Exibe as notícias mais recentes dos **últimos 7 dias** referentes ao papel escolhido (já sincronizado com a Watchlist).
                * **Panorama Carteira / Ibovespa:** Traz as manchetes das **últimas 24 horas** sobre o Ibovespa, B3 e câmbio, ordenadas da mais recente para a mais antiga.
                """
            )

    with col_g6:
        with st.container(border=True):
            st.subheader("🔔 Aba 6: Alertas")
            st.markdown(
                r"""
                Central de monitoramento e sinalização automática na Watchlist:
                * **Destaques na Watchlist:** Exibe ícones diretamente nos ativos sinalizados (`🎯` Alvo de Preço, `🟢` Sobrevenda, `🔴` Sobrecompra, `⚡` Cruzamento de EMA e `🔥` Volume Anormal).
                * **Regras & Preços-Alvo:** Permite ajustar os limites de IFR/Volume e cadastrar alertas personalizados em **R$** com seleção direta para o gráfico.
                """
            )

    with st.container(border=True):
        st.subheader("🎯 Aba 7: Opções (Venda de Put)")
        st.markdown(
            r"""
            Bancada completa para estruturação e simulação de **Venda Coberta de Put (Cash-Secured Put)**:
            * **Grade de Strikes OTM & Black-Scholes:** Gera automaticamente os códigos de referência das séries mensais da B3 (`M` a `X`, vencimento na 3ª sexta-feira) com **Prêmio Teórico**, **Taxa Anualizada (% a.a.)**, **Delta (Δ)** e **Probabilidade de Não-Exercício**.
            * **Simulador & Gráfico de Payoff:** Calcula o **Crédito Líquido**, **Caixa/Garantia necessária**, **Breakeven real** e a **Volatilidade Implícita (IV Book)**, exibindo a curva de resultado no vencimento com marcadores de **Breakeven**, **Spot** e canal sombreado de **±1 Desvio Padrão (`±1σ`)**.
            * **Radar de Candidatas:** Lista os ativos mais descontados da carteira (menor IFR) para facilitar a escolha de oportunidades.
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
        | **Juro Real (Fisher)** | `((1 + CDI) / (1 + IPCA_12M) - 1) × 100` com séries oficiais do Banco Central (SGS). | Mede o retorno real anualizado acima da inflação acumulada nos últimos 12 meses. |
        | **Black-Scholes & ±1σ** | Modelo europeu com Selic vigente (BCB) e Volatilidade Histórica anualizada (252 du); faixa de `1σ = S × σ × √T`. | Estima prêmio justo da Put, Delta, IV do book e o intervalo esperado de 68,2% até o vencimento. |
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
