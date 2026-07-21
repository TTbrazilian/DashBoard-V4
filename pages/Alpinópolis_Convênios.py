# pyright: reportMissingModuleSource=false
"""
iG2P · Convênios & Emendas — Dashboard por Município
Fonte de dados: Google Sheets API (planilha "Emendas - <Município>").
As abas da planilha têm exatamente os nomes usados em ABAS abaixo.
Para desenvolvimento local, cai automaticamente em CSVs na pasta zConvenios/.
"""

import os
import io
import csv
import re
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.io as pio
import plotly.graph_objects as go
import streamlit.components.v1 as components

st.set_page_config(page_title="Convênios - Gestão iG2P", layout="wide")
pio.templates.default = "plotly_dark"
CONFIG_PT = {'displaylogo': False, 'showTips': False}

MUNICIPIO = "Alpinópolis"

# Nomes EXATOS das abas (refletem os arquivos CSV). Atenção a espaços!
ABAS = {
    "conv_fed":  "Convênios Federais ",
    "conv_est":  " Convênios Estaduais",
    "emen_fed":  "Emendas Especiais Federais",
    "emen_est":  "Emendas Especiais Estaduais",
    "mds":       "MDS",
    "relatorio": "Relatório",
}

# Cores institucionais
C_FED   = "#1f6feb"   # Federal (azul)
C_EST   = "#2ea043"   # Estadual (verde)
C_REP   = "#003366"
C_CONTR = "#860000"
C_SALDO = "#f39c12"


# ══════════════════════════════════════════════════════════════════════════════
# Compat st.iframe (Streamlit >= 1.56)
# ══════════════════════════════════════════════════════════════════════════════
def _html_iframe(html, height=0, scrolling=False):
    if hasattr(st, "iframe"):
        h = height if isinstance(height, int) and height > 0 else "content"
        st.iframe(html, height=h)
    else:
        components.html(html, height=height, scrolling=scrolling)


# ══════════════════════════════════════════════════════════════════════════════
# Utilidades
# ══════════════════════════════════════════════════════════════════════════════
def formar_real(v):
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"


def _m(v):
    """Converte ' R$  1.000.000,00 ' → 1000000.0 ; '-'/''/'R$ -' → 0.0"""
    if v is None:
        return 0.0
    s = str(v).replace("R$", "").strip()
    s = s.replace(".", "").replace(",", ".")
    s = re.sub(r"[^0-9.\-]", "", s)
    if s in ("", "-", ".", "-."):
        return 0.0
    try:
        return float(s)
    except Exception:
        return 0.0


def buscar_arquivo(nome):
    cands = [nome, os.path.join("zConvenios", nome)]
    try:
        d = os.path.dirname(__file__)
        cands += [os.path.join(d, nome), os.path.join(d, "zConvenios", nome)]
    except NameError:
        pass
    for p in cands:
        if os.path.exists(p):
            return p
    return None


# ══════════════════════════════════════════════════════════════════════════════
# LEITURA VIA GOOGLE SHEETS API  (com fallback CSV local p/ desenvolvimento)
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_resource
def _conectar_sheets():
    from google.oauth2.service_account import Credentials
    import gspread
    escopos = ["https://www.googleapis.com/auth/spreadsheets.readonly",
               "https://www.googleapis.com/auth/drive.readonly"]
    cred = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=escopos)
    return gspread.authorize(cred)


def _abrir_aba(gc, sheet_id, nome_aba):
    """Abre a aba tolerando diferenças de espaço/caixa no nome."""
    sh = gc.open_by_key(sheet_id)
    try:
        return sh.worksheet(nome_aba)
    except Exception:
        alvo = nome_aba.strip().lower()
        for ws in sh.worksheets():
            if ws.title.strip().lower() == alvo:
                return ws
        raise


def _valores_para_df(valores):
    """valores = lista de linhas (get_all_values). Cabeçalho na linha índice 1;
    coluna A vazia é descartada. Reaproveita pd.read_csv (dedup de colunas)."""
    buf = io.StringIO()
    csv.writer(buf).writerows(valores)
    buf.seek(0)
    df = pd.read_csv(buf, header=1, dtype=str, keep_default_na=False)
    df = df.loc[:, ~df.columns.astype(str).str.match(r"^Unnamed: 0")]
    df.columns = [str(c).strip() for c in df.columns]
    return df


@st.cache_data(ttl=600)
def load_convenios():
    """Retorna dict {chave: DataFrame} para cada aba. Sheets API → fallback CSV."""
    dados = {}
    # 1) Tenta Google Sheets
    if "gcp_service_account" in st.secrets and "convenios" in st.secrets:
        try:
            gc = _conectar_sheets()
            sid = st.secrets["convenios"]["sheet_id"]
            for chave, aba in ABAS.items():
                ws = _abrir_aba(gc, sid, aba)
                dados[chave] = _valores_para_df(ws.get_all_values())
            return dados
        except Exception as e:
            st.warning(f"Falha ao ler Google Sheets ({type(e).__name__}: {e}). "
                       "Tentando arquivos locais...")

    # 2) Fallback CSV local — casa o arquivo pela aba normalizando espaços/underscores
    import glob
    arquivos = glob.glob("zConvenios/Emendas_*.csv") + glob.glob("Emendas_*.csv")
    try:
        d = os.path.dirname(__file__)
        arquivos += glob.glob(os.path.join(d, "zConvenios", "Emendas_*.csv"))
    except NameError:
        pass

    def _norm(s):
        return re.sub(r"[\s_]+", "", str(s)).strip().lower()

    for chave, aba in ABAS.items():
        alvo = _norm(aba)
        achado = None
        for p in arquivos:
            base = os.path.basename(p).replace(".csv", "")
            parte = re.sub(r"^Emendas_-_.*?_-_", "", base)  # remove 'Emendas_-_<Mun>_-_'
            if _norm(parte) == alvo:
                achado = p
                break
        if achado:
            with open(achado, encoding="utf-8") as fh:
                valores = list(csv.reader(fh))
            dados[chave] = _valores_para_df(valores)
        else:
            dados[chave] = pd.DataFrame()
    return dados


def _linhas_validas(df):
    """Mantém apenas as linhas reais do município, removendo linhas de TOTAL,
    cabeçalhos repetidos e vazias (todas sem 'Município' preenchido)."""
    if df.empty or "Município" not in df.columns:
        return df
    m = df["Município"].astype(str).str.strip().str.lower()
    return df[m == MUNICIPIO.strip().lower()].reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════════
# TEMA / CSS (padrão iG2P + regra universal de cabeçalho no topo)
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
    <style>
        #MainMenu, footer {visibility: hidden;}
        .stButton button { border-radius: 10px; font-weight: 600; }
        [data-testid="stSidebarNav"] li:first-child > a > span,
        [data-testid="stSidebarNav"] li:first-child > a > p { display: none !important; }
        /* ===== CABEÇALHO NO TOPO (regra universal iG2P) ===== */
        [data-testid="stMainBlockContainer"], .stMainBlockContainer,
        .block-container { padding-top: 1.5rem !important; }
        [data-testid="stElementContainer"]:has(iframe),
        .element-container:has(iframe),
        [data-testid="stIFrame"] {
            height: 0 !important; min-height: 0 !important;
            margin: 0 !important; padding: 0 !important; overflow: hidden !important;
        }
    </style>
""", unsafe_allow_html=True)


def kpi_row(pares):
    cols = st.columns(len(pares))
    for c, (lbl, val) in zip(cols, pares):
        with c:
            st.metric(lbl, val)


def barras_por(df, coluna, valor_col, titulo, cor=C_FED, topn=None, horizontal=True):
    if df.empty or coluna not in df.columns:
        st.info(f"Sem dados de '{coluna}'.")
        return
    g = df.copy()
    g["_v"] = g[valor_col].apply(_m) if valor_col in g.columns else 0.0
    g = g.groupby(g[coluna].astype(str).str.strip())["_v"].sum().reset_index()
    g = g[g["_v"] > 0].sort_values("_v", ascending=True)
    if topn:
        g = g.tail(topn)
    if g.empty:
        st.info(f"Sem valores para '{coluna}'.")
        return
    st.metric(f"Total — {titulo}", formar_real(g["_v"].sum()))
    if horizontal:
        fig = px.bar(g, x="_v", y=coluna, orientation="h", color_discrete_sequence=[cor])
        fig.update_layout(xaxis_tickprefix="R$ ", xaxis_tickformat=",.2f")
    else:
        g = g.sort_values(coluna)
        fig = px.bar(g, x=coluna, y="_v", color_discrete_sequence=[cor])
        fig.update_layout(yaxis_tickprefix="R$ ", yaxis_tickformat=",.2f")
    fig.update_layout(height=max(360, 34 * len(g)), separators=",.",
                      xaxis_title="", yaxis_title="", margin=dict(t=20, b=30))
    fig.update_traces(hovertemplate="<b>%{y}</b><br>R$ %{x:,.2f}<extra></extra>"
                      if horizontal else "<b>%{x}</b><br>R$ %{y:,.2f}<extra></extra>")
    st.plotly_chart(fig, use_container_width=True, config=CONFIG_PT)


def tabela_detalhe(df, colunas):
    cols = [c for c in colunas if c in df.columns]
    if df.empty or not cols:
        return
    st.markdown("##### 📋 Detalhamento")
    st.dataframe(df[cols], use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# INTERFACE
# ══════════════════════════════════════════════════════════════════════════════
DADOS = load_convenios()

if "setor" not in st.session_state:
    st.session_state.setor = "Visão Geral"

st.sidebar.title("🤝 Convênios & Emendas")
st.sidebar.caption(f"Município: {MUNICIPIO}")
st.sidebar.markdown("---")
for label in ["Visão Geral", "Convênios Federais", "Convênios Estaduais",
              "Emendas Especiais Federais", "Emendas Especiais Estaduais", "MDS"]:
    if st.sidebar.button(label, use_container_width=True,
                         type=("primary" if st.session_state.setor == label else "secondary")):
        st.session_state.setor = label
        st.rerun()

# Logo iG2P na sidebar (injeção via iframe invisível)
import base64 as _b64
def _ler_logo(nome):
    for p in [f"Logos/{nome}", f"../Logos/{nome}"]:
        if os.path.exists(p):
            return "data:image/png;base64," + _b64.b64encode(open(p, "rb").read()).decode()
    return ""
_logo = _ler_logo("LOGOTIPO IG2P - OFICIAL - BRANCO.png")
if _logo:
    _html_iframe(f"""<script>(function(){{
        var img=window.parent.document.querySelector('img.ig2p-logo-conv');
        if(img)return;
        var nav=window.parent.document.querySelector('[data-testid="stSidebarNav"]');
        if(!nav)return;
        var i=window.parent.document.createElement('img');
        i.src="{_logo}"; i.className="ig2p-logo-conv";
        i.style.cssText="width:130px;display:block;margin:8px auto;";
        nav.parentNode.insertBefore(i, nav);
    }})()</script>""", height=0)

setor = st.session_state.setor


# ─────────────────────────────────────────────────────────────────────────────
# VISÃO GERAL (consolidado do Relatório + panorama de todas as fontes)
# ─────────────────────────────────────────────────────────────────────────────
if setor == "Visão Geral":
    st.title(f"🏛️ {MUNICIPIO} — Convênios & Emendas · Visão Geral")
    st.markdown("---")

    rel = DADOS.get("relatorio", pd.DataFrame())
    if not rel.empty and "FONTE" in rel.columns:
        rel = rel[rel["FONTE"].astype(str).str.strip().isin(
            ["FEDERAL", "E. FEDERAL", "ESTADUAL", "E. ESTADUAL"])].copy()

    def _s(col):
        return rel[col].apply(_m).sum() if (not rel.empty and col in rel.columns) else 0.0

    tot_rep = _s("R$ REPASSE"); tot_rec = _s("R$ RECEBIDO")
    tot_con = _s("R$ CONTRAPARTIDA"); tot_dep = _s("DEPOSITADO"); tot_sal = _s("SALDO")

    st.subheader("Consolidado (aba Relatório)")
    kpi_row([("Repasse Total", formar_real(tot_rep)),
             ("Recebido", formar_real(tot_rec)),
             ("Contrapartida", formar_real(tot_con)),
             ("Depositado", formar_real(tot_dep)),
             ("Saldo", formar_real(tot_sal))])

    if not rel.empty and "FONTE" in rel.columns:
        st.markdown("---")
        st.subheader("Repasse × Recebido × Saldo por Fonte")
        g = rel.copy()
        for c in ["R$ REPASSE", "R$ RECEBIDO", "SALDO"]:
            if c in g.columns:
                g[c] = g[c].apply(_m)
        gg = g.groupby(g["FONTE"].astype(str).str.strip())[
            [c for c in ["R$ REPASSE", "R$ RECEBIDO", "SALDO"] if c in g.columns]].sum().reset_index()
        fig = go.Figure()
        cores = {"R$ REPASSE": C_REP, "R$ RECEBIDO": C_EST, "SALDO": C_SALDO}
        for c in [c for c in ["R$ REPASSE", "R$ RECEBIDO", "SALDO"] if c in gg.columns]:
            fig.add_bar(x=gg["FONTE"], y=gg[c], name=c.replace("R$ ", "").title(),
                        marker_color=cores[c],
                        hovertemplate="<b>%{x}</b><br>R$ %{y:,.2f}<extra></extra>")
        fig.update_layout(barmode="group", height=430, separators=",.",
                          yaxis_tickprefix="R$ ", legend=dict(orientation="h", y=-0.2),
                          margin=dict(t=20, b=40))
        st.plotly_chart(fig, use_container_width=True, config=CONFIG_PT)

    # Panorama por fonte de captação (soma bruta de cada aba)
    st.markdown("---")
    st.subheader("Captação por Origem")
    origens = []
    for chave, rotulo, valcol, cor in [
        ("conv_fed", "Convênios Federais", "Valor Repasse", C_FED),
        ("conv_est", "Convênios Estaduais", "Valor Repasse", C_FED),
        ("emen_fed", "Emendas Especiais Federais", "Valor", C_EST),
        ("emen_est", "Emendas Especiais Estaduais", "Valor", C_EST),
        ("mds", "MDS", "Valor", C_SALDO),
    ]:
        d = _linhas_validas(DADOS.get(chave, pd.DataFrame()))
        v = d[valcol].apply(_m).sum() if (not d.empty and valcol in d.columns) else 0.0
        origens.append({"Origem": rotulo, "Valor": v})
    do = pd.DataFrame(origens)
    do = do[do["Valor"] > 0]
    if not do.empty:
        c1, c2 = st.columns([2, 1])
        with c1:
            fig = px.bar(do.sort_values("Valor"), x="Valor", y="Origem", orientation="h",
                         color="Origem", color_discrete_sequence=px.colors.qualitative.Set2)
            fig.update_layout(height=360, separators=",.", showlegend=False,
                              xaxis_tickprefix="R$ ", xaxis_title="", yaxis_title="",
                              margin=dict(t=10, b=20))
            fig.update_traces(hovertemplate="<b>%{y}</b><br>R$ %{x:,.2f}<extra></extra>")
            st.plotly_chart(fig, use_container_width=True, config=CONFIG_PT)
        with c2:
            st.metric("Captação Total (bruta)", formar_real(do["Valor"].sum()))
            for _, r in do.iterrows():
                st.caption(f"**{r['Origem']}**: {formar_real(r['Valor'])}")


# ─────────────────────────────────────────────────────────────────────────────
# CONVÊNIOS (Federais / Estaduais) — estrutura compartilhada
# ─────────────────────────────────────────────────────────────────────────────
def render_convenios(chave, titulo, dim_orgao, cor):
    df = _linhas_validas(DADOS.get(chave, pd.DataFrame()))
    st.title(f"{titulo}")
    st.markdown("---")
    if df.empty:
        st.info("Sem dados nesta aba.")
        return
    tot_rep = df["Valor Repasse"].apply(_m).sum() if "Valor Repasse" in df.columns else 0.0
    tot_con = df["Contrapartida"].apply(_m).sum() if "Contrapartida" in df.columns else 0.0
    col_saldo = next((c for c in df.columns if "saldo" in c.lower()), None)
    tot_sal = df[col_saldo].apply(_m).sum() if col_saldo else 0.0
    kpi_row([("Nº de Convênios", str(len(df))),
             ("Repasse Total", formar_real(tot_rep)),
             ("Contrapartida", formar_real(tot_con)),
             ("Saldo em Conta", formar_real(tot_sal))])

    st.markdown("---")
    st.subheader(f"Repasse por {dim_orgao}")
    barras_por(df, dim_orgao, "Valor Repasse", dim_orgao, cor=cor)

    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Repasse por Ano")
        barras_por(df, "Ano", "Valor Repasse", "Ano", cor=cor, horizontal=False)
    with c2:
        st.subheader("Situação (Status)")
        scol = "Status PB /TR" if "Status PB /TR" in df.columns else None
        if scol:
            g = df.groupby(df[scol].astype(str).str.strip()).size().reset_index(name="n")
            g = g[g[scol] != ""]
            if not g.empty:
                fig = px.pie(g, values="n", names=scol, hole=.45,
                             color_discrete_sequence=px.colors.qualitative.Set2)
                fig.update_layout(height=360, margin=dict(t=10, b=10),
                                  legend=dict(orientation="v", x=1.02, y=0.5))
                fig.update_traces(textinfo="value+percent")
                st.plotly_chart(fig, use_container_width=True, config=CONFIG_PT)
        else:
            st.info("Sem coluna de status.")

    st.markdown("---")
    tabela_detalhe(df, [dim_orgao, "Nº do Convênio", "Ano", "Objeto",
                        "Valor Repasse", "Contrapartida", "GND",
                        "Status PB /TR", "Status Execução"])


if setor == "Convênios Federais":
    render_convenios("conv_fed", "🇧🇷 Convênios Federais", "Ministério", C_FED)

if setor == "Convênios Estaduais":
    render_convenios("conv_est", "🏛️ Convênios Estaduais", "Secretaria", C_EST)


# ─────────────────────────────────────────────────────────────────────────────
# EMENDAS ESPECIAIS (Federais / Estaduais)
# ─────────────────────────────────────────────────────────────────────────────
def render_emendas(chave, titulo, dim_orgao, cor):
    df = _linhas_validas(DADOS.get(chave, pd.DataFrame()))
    st.title(titulo)
    st.markdown("---")
    if df.empty:
        st.info("Sem dados nesta aba.")
        return
    tot = df["Valor"].apply(_m).sum() if "Valor" in df.columns else 0.0
    col_saldo = next((c for c in df.columns if "saldo" in c.lower()), None)
    tot_sal = df[col_saldo].apply(_m).sum() if col_saldo else 0.0
    kpi_row([("Nº de Emendas", str(len(df))),
             ("Valor Total", formar_real(tot)),
             ("Saldo em Conta", formar_real(tot_sal)),
             ("Parlamentares", str(df["Parlamentar"].astype(str).str.strip().nunique()
                                    if "Parlamentar" in df.columns else 0))])

    st.markdown("---")
    st.subheader("Valor por Parlamentar")
    barras_por(df, "Parlamentar", "Valor", "Parlamentar", cor=cor, topn=15)

    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Valor por Ano")
        barras_por(df, "Ano", "Valor", "Ano", cor=cor, horizontal=False)
    with c2:
        st.subheader(f"Valor por {dim_orgao}")
        barras_por(df, dim_orgao, "Valor", dim_orgao, cor=cor)

    if "GND" in df.columns:
        st.markdown("---")
        st.subheader("Investimento × Custeio (GND)")
        g = df.copy(); g["_v"] = g["Valor"].apply(_m)
        g = g[g["GND"].astype(str).str.strip().isin(["Investimento", "Custeio"])]
        gg = g.groupby("GND")["_v"].sum().reset_index()
        if not gg.empty:
            fig = px.pie(gg, values="_v", names="GND", hole=.45,
                         color="GND", color_discrete_map={"Investimento": C_FED, "Custeio": C_SALDO})
            fig.update_layout(height=340, margin=dict(t=10, b=10))
            fig.update_traces(textinfo="percent",
                              hovertemplate="<b>%{label}</b><br>R$ %{value:,.2f}<extra></extra>")
            _, cc, _ = st.columns([1, 2, 1])
            with cc:
                st.plotly_chart(fig, use_container_width=True, config=CONFIG_PT)

    st.markdown("---")
    tabela_detalhe(df, ["Parlamentar", dim_orgao, "Ano", "Objeto", "Valor",
                        "GND", "Data Pagamento", "Status Plano de Trabalho"])


if setor == "Emendas Especiais Federais":
    render_emendas("emen_fed", "📋 Emendas Especiais Federais", "Ministério", C_FED)

if setor == "Emendas Especiais Estaduais":
    render_emendas("emen_est", "📋 Emendas Especiais Estaduais", "Secretaria", C_EST)


# ─────────────────────────────────────────────────────────────────────────────
# MDS
# ─────────────────────────────────────────────────────────────────────────────
if setor == "MDS":
    st.title("🤝 Emendas MDS")
    st.markdown("---")
    df = DADOS.get("mds", pd.DataFrame())
    if not df.empty and "Valor" in df.columns:
        df = df[df["Valor"].apply(_m) > 0].reset_index(drop=True)
    if df.empty:
        st.info("Não há emendas MDS lançadas para este município.")
    else:
        tot = df["Valor"].apply(_m).sum()
        kpi_row([("Nº de Emendas MDS", str(len(df))), ("Valor Total", formar_real(tot))])
        st.markdown("---")
        barras_por(df, "Ano", "Valor", "Ano", cor=C_SALDO, horizontal=False)
        st.markdown("---")
        tabela_detalhe(df, ["Emendas MDS", "Ano", "Instituição Beneficiária",
                            "Valor", "Status Plano de Trabalho"])