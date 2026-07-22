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

# ── MULTIMUNICÍPIO ────────────────────────────────────────────────────────────
# O município é detectado AUTOMATICAMENTE pelo nome deste arquivo.
# Para lançar um novo município de Convênios, basta:
#   1) copiar este arquivo para  pages/<Município>_Convênios.py
#      (ex.: "Cássia_Convênios.py", "Itaú de Minas_Convênios.py")
#   2) adicionar 1 linha no secrets, em [convenios]:  "Cássia" = "<sheet_id>"
# Nenhuma outra alteração é necessária.
MUNICIPIO_FALLBACK = "Itaú_de_Minas"   # usado só se não for possível ler o nome do arquivo

def _detectar_municipio():
    try:
        base = os.path.splitext(os.path.basename(__file__))[0]  # "<Município>_Convênios"
        nome = re.sub(r"[_\s]*Conv[êe]nios\s*$", "", base, flags=re.IGNORECASE)
        nome = nome.replace("_", " ").strip()
        return nome or MUNICIPIO_FALLBACK
    except Exception:
        return MUNICIPIO_FALLBACK

MUNICIPIO = _detectar_municipio()


# ══════════════════════════════════════════════════════════════════════════════
# BANDEIRA DO MUNICÍPIO (substitui os ícones/emojis dos cabeçalhos)
# ──────────────────────────────────────────────────────────────────────────────
# >>>>>>>>>>>>>>>>>>>>  COLOQUE A BANDEIRA AQUI  <<<<<<<<<<<<<<<<<<<<
# Salve o PNG da bandeira em:   Logos/Bandeiras/<Município>.png
#     exemplo:                  Logos/Bandeiras/Alpinópolis.png
# É só isso — o arquivo é localizado automaticamente pelo nome do município.
# Enquanto a imagem não existir, o cabeçalho aparece apenas com o texto
# (sem ícone e sem imagem quebrada).
# A bandeira é exibida com ALTURA DE 1em, ou seja, exatamente o tamanho do
# texto/emoji do título, e largura automática — mantém a proporção original
# e nunca estoura a grade do layout.
# ══════════════════════════════════════════════════════════════════════════════
BANDEIRA_ARQUIVO = f"{MUNICIPIO}.png"      # troque aqui se usar outro nome de arquivo


# IMPORTANTE: o cache é keyed pelos ARGUMENTOS. Como todas as páginas de
# Convênios compartilham o mesmo processo, a função PRECISA receber o nome do
# arquivo/município — senão a primeira página carregada serviria a sua bandeira
# (e os seus dados) para todas as outras.
@st.cache_data
def _bandeira_b64(arquivo: str):
    """Lê o PNG da bandeira e devolve um data-URI. Vazio se não encontrar."""
    import base64
    # aceita "Itaú de Minas.png", "Itaú_de_Minas.png" e variações em minúsculas
    nomes = []
    for n in (arquivo, arquivo.replace(" ", "_"), arquivo.replace("_", " ")):
        for v in (n, n.lower()):
            if v not in nomes:
                nomes.append(v)
    pastas = ["Logos/Bandeiras", "../Logos/Bandeiras", "Logos", "../Logos"]
    try:
        d = os.path.dirname(__file__)
        pastas += [os.path.join(d, "Logos", "Bandeiras"),
                   os.path.join(d, "..", "Logos", "Bandeiras"),
                   os.path.join(d, "..", "Logos")]
    except NameError:
        pass
    for pasta in pastas:
        for nome in nomes:
            p = os.path.join(pasta, nome)
            if os.path.exists(p):
                return "data:image/png;base64," + base64.b64encode(open(p, "rb").read()).decode()
    return ""


def _img_bandeira():
    """<img> da bandeira no tamanho de um emoji (height:1em, proporção mantida)."""
    b = _bandeira_b64(BANDEIRA_ARQUIVO)
    if not b:
        return ""
    return ('<img src="' + b + '" alt="" style="height:1em;width:auto;'
            'vertical-align:-0.12em;margin-right:.35em;border-radius:3px;'
            'object-fit:contain;">')


def titulo_pagina(texto):
    """Cabeçalho da página: bandeira do município + texto (sem emojis)."""
    st.markdown('<h1 style="margin:0 0 .25em 0;">' + _img_bandeira() + texto + '</h1>',
                unsafe_allow_html=True)

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


def _sheet_id_do_municipio():
    """Lê o sheet_id do município atual em [convenios]. Aceita mapa por município
    ( "Alpinópolis" = "id..." ) ou a chave única legada ( sheet_id = "id..." )."""
    if "convenios" not in st.secrets:
        return None
    sec = st.secrets["convenios"]
    if MUNICIPIO in sec:
        return sec[MUNICIPIO]
    if "sheet_id" in sec:
        return sec["sheet_id"]
    return None


@st.cache_data(ttl=600, show_spinner=False)
def load_convenios(municipio: str, sid: str):
    """Retorna (dados, aviso). O cache é keyed por (município, sheet_id) — sem
    isso, todas as páginas de Convênios compartilhariam o mesmo cache e a
    primeira a carregar serviria os seus dados para as demais.
    Nada de st.warning/st.info aqui dentro: chamadas de UI seriam gravadas no
    cache e reexibidas na página errada. O aviso volta como texto."""
    dados = {}
    aviso = ""
    tem_credenciais = "gcp_service_account" in st.secrets
    # 1) Tenta Google Sheets (sheet_id específico do município)
    if tem_credenciais and sid:
        try:
            gc = _conectar_sheets()
            for chave, aba in ABAS.items():
                # Aba ausente nesta planilha (ex.: municípios sem "Relatório")
                # não pode derrubar a página inteira → vira DataFrame vazio.
                try:
                    ws = _abrir_aba(gc, sid, aba)
                    dados[chave] = _valores_para_df(ws.get_all_values())
                except Exception:
                    dados[chave] = pd.DataFrame()
            return dados, aviso
        except Exception as e:
            aviso = (f"Falha ao ler o Google Sheets de {municipio} "
                     f"({type(e).__name__}: {e}). Tentando arquivos locais...")
    elif tem_credenciais and not sid:
        aviso = (f"Defina o sheet_id de **{municipio}** no secrets, em `[convenios]` "
                 f"(ex.: `\"{municipio}\" = \"<id_da_planilha>\"`).")

    # 2) Fallback CSV local — casa o arquivo pelo município + nome da aba,
    #    aceitando qualquer prefixo ("Emendas_-_X_-_Aba" ou "Convênios_X_-_Aba").
    import glob
    arquivos = glob.glob("zConvenios/*.csv") + glob.glob("*.csv")
    try:
        d = os.path.dirname(__file__)
        arquivos += glob.glob(os.path.join(d, "zConvenios", "*.csv"))
    except NameError:
        pass

    def _norm(s):
        return re.sub(r"[\s_\-]+", "", str(s)).strip().lower()

    alvo_mun = _norm(municipio)
    for chave, aba in ABAS.items():
        alvo = _norm(aba)
        achado = None
        for p in arquivos:
            base = os.path.basename(p).replace(".csv", "")
            mm = re.match(r"^(.*)_-_(.*)$", base)       # último '_-_': (prefixo+município)(aba)
            if not mm or alvo_mun not in _norm(mm.group(1)):
                continue
            if _norm(mm.group(2)) == alvo:
                achado = p
                break
        if achado:
            with open(achado, encoding="utf-8") as fh:
                valores = list(csv.reader(fh))
            dados[chave] = _valores_para_df(valores)
        else:
            dados[chave] = pd.DataFrame()
    return dados, aviso


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
        /* ===== ANIMAÇÃO DOS GRÁFICOS (regra universal iG2P) ===== */
        @keyframes subirBarra { from { clip-path: inset(100% 0 0 0); } to { clip-path: inset(0% 0 0 0); } }
        .js-plotly-plot .point path {
            animation: subirBarra 1.2s cubic-bezier(0.25,1,0.5,1) forwards;
            animation-delay: 0.15s; clip-path: inset(100% 0 0 0);
        }
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


def _abrev(texto, n=44):
    """Abrevia mantendo palavras inteiras e sinaliza o corte com reticências."""
    t = " ".join(str(texto).split())
    if len(t) <= n:
        return t
    corte = t[:n - 1]
    if " " in corte[int(n * 0.6):]:
        corte = corte[:corte.rstrip().rfind(" ")]
    return corte.rstrip(" ,.;-") + "…"


def _rotulos_unicos(labels):
    """Evita que convênios de nome igual virem a MESMA barra no gráfico."""
    vistos, saida = {}, []
    for l in labels:
        if l in vistos:
            vistos[l] += 1
            saida.append(f"{l} ({vistos[l]})")
        else:
            vistos[l] = 1
            saida.append(l)
    return saida


def tabela_detalhe(df, colunas):
    cols = [c for c in colunas if c in df.columns]
    if df.empty or not cols:
        return
    st.markdown("##### 📋 Detalhamento")
    st.dataframe(df[cols], use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# INTERFACE
# ══════════════════════════════════════════════════════════════════════════════
# ── LOGO + LOADER (regra universal iG2P) ─────────────────────────────────────
# O loader é criado ANTES de qualquer carregamento pesado e só é removido no
# FIM do script — assim ele cobre o tempo real de carregamento da página,
# em paralelo com o indicador nativo do Streamlit.
import base64 as _b64
def _ler_logo(nome):
    cands = [f"Logos/{nome}", f"../Logos/{nome}"]
    try:
        d = os.path.dirname(__file__)
        cands += [os.path.join(d, "Logos", nome), os.path.join(d, "..", "Logos", nome)]
    except NameError:
        pass
    for p in cands:
        if os.path.exists(p):
            return "data:image/png;base64," + _b64.b64encode(open(p, "rb").read()).decode()
    return ""

_logo_escuro = _ler_logo("LOGOTIPO IG2P - OFICIAL - BRANCO.png")   # p/ fundo escuro
_logo_claro  = _ler_logo("LOGOTIPO IG2P - OFICIAL.png")            # p/ fundo claro

if _logo_escuro or _logo_claro:
    st.markdown(f"""
    <div class="ig2p-loader" id="ig2p-loader">
      <img class="ig2p-logo-escuro" src="{_logo_escuro}">
      <img class="ig2p-logo-claro"  src="{_logo_claro}">
    </div>
    <style>
      /* o container do markdown não pode ocupar espaço (evita "linha" no topo) */
      [data-testid="stElementContainer"]:has(.ig2p-loader),
      .element-container:has(.ig2p-loader) {{
        height:0!important; min-height:0!important;
        margin:0!important; padding:0!important;
      }}
      .ig2p-loader {{ position:fixed; inset:0; z-index:99999; pointer-events:none;
        display:flex; align-items:center; justify-content:center;
        background:#0E1117; opacity:1; transition:opacity .45s ease; }}
      .ig2p-loader.ig2p-done {{ opacity:0; visibility:hidden; }}
      .ig2p-loader img {{ width:150px; height:auto;
        animation: ig2pPulse 1.1s ease-in-out infinite; }}
      .ig2p-loader .ig2p-logo-claro {{ display:none; }}
      @media (prefers-color-scheme: light) {{
        .ig2p-loader {{ background:#FFFFFF; }}
        .ig2p-loader .ig2p-logo-escuro {{ display:none; }}
        .ig2p-loader .ig2p-logo-claro  {{ display:block; }}
      }}
      @keyframes ig2pPulse {{ 0%,100%{{opacity:.35;transform:scale(.94)}}
                              50%{{opacity:1;transform:scale(1.05)}} }}
    </style>
    """, unsafe_allow_html=True)


DADOS, _AVISO = load_convenios(MUNICIPIO, _sheet_id_do_municipio() or "")
if _AVISO:
    st.info(_AVISO)

if "setor" not in st.session_state:
    st.session_state.setor = "Visão Macro"

st.sidebar.markdown('<h2 style="margin:0 0 .2em 0;font-size:1.35rem;">'
                    + _img_bandeira() + 'Convênios &amp; Emendas</h2>',
                    unsafe_allow_html=True)
st.sidebar.caption(f"Município: {MUNICIPIO}")
st.sidebar.markdown("---")
for label in ["Visão Macro", "Convênio a Convênio", "Convênios Federais", "Convênios Estaduais",
              "Emendas Especiais Federais", "Emendas Especiais Estaduais", "MDS"]:
    if st.sidebar.button(label, use_container_width=True,
                         type=("primary" if st.session_state.setor == label else "secondary")):
        st.session_state.setor = label
        st.rerun()

# ── FOCO NO TOPO ao trocar de setor (regra universal iG2P) ──
_ig2p_foco = str(st.session_state.get("setor", ""))
if st.session_state.get("_ig2p_foco") != _ig2p_foco:
    st.session_state["_ig2p_foco"] = _ig2p_foco
    _html_iframe(
        "<script>(function(){try{"
        "var w=window.parent,d=w.document;"
        "var sels=['section.main','[data-testid=\"stMain\"]',"
        "'[data-testid=\"stAppViewContainer\"]','[data-testid=\"stMainBlockContainer\"]'];"
        "function top(){try{w.scrollTo(0,0);}catch(e){}"
        "sels.forEach(function(s){var el=d.querySelector(s);if(el)el.scrollTop=0;});}"
        "top();setTimeout(top,60);setTimeout(top,200);"
        "}catch(e){}})()</script>", height=0)

# ── SIDEBAR: mostra só páginas de Convênios + logo como botão Home (regra universal) ──
def _js_sidebar_conv(LE, LC):
    return (
        "<script>(function(){"
        'var LE="' + LE + '";var LC="' + LC + '";'
        "function dE(){try{"
        "var bg=window.parent.getComputedStyle(window.parent.document.body).backgroundColor;"
        "if(!bg||bg==='rgba(0,0,0,0)')return true;"
        "var v=bg.match(/[0-9]+/g).map(Number);return v[0]<128;"
        "}catch(e){return true;}}"
        "var _busy=false;"
        "function run(){if(_busy)return;_busy=true;try{"
        "var doc=window.parent.document;"
        "var nav=doc.querySelector('[data-testid=\"stSidebarNav\"]');"
        "if(!nav){_busy=false;return;}"
        "nav.querySelectorAll('li').forEach(function(it){"
        "var lk=it.querySelector('a');if(!lk)return;"
        "var sp=lk.querySelector('span');"
        "var tx=(sp?sp.textContent:lk.textContent).trim();"
        "var isH=tx==='Home'||tx.toLowerCase()==='home'||(lk.href&&lk.href.toLowerCase().indexOf('/home')!==-1);"
        "var isC=it.textContent.indexOf('Conv\u00eanio')!==-1;"
        "if(!isH&&!isC){it.style.setProperty('display','none','important');return;}"
        "it.style.removeProperty('display');"
        "if(!isH)return;"
        "if(lk.querySelector('img.ig2p-logo-sidebar'))return;"
        "if(sp)sp.style.setProperty('display','none','important');"
        "lk.style.setProperty('padding','4px 8px','important');"
        "lk.style.setProperty('display','flex','important');"
        "lk.style.setProperty('align-items','center','important');"
        "lk.style.setProperty('background','transparent','important');"
        "var img=doc.createElement('img');img.src=dE()?LE:LC;"
        "img.className='ig2p-logo-sidebar';"
        "img.style.cssText='width:130px;height:auto;cursor:pointer;display:block;margin:4px 0;';"
        "var mq=window.parent.matchMedia('(prefers-color-scheme:dark)');"
        "function up(){img.src=dE()?LE:LC;}"
        "if(mq.addEventListener)mq.addEventListener('change',up);"
        "lk.insertBefore(img,lk.firstChild);"
        "});"
        "}catch(e){}_busy=false;}"
        "run();setTimeout(run,50);setTimeout(run,200);setTimeout(run,600);"
        "try{if(window.parent._ig2p_obs)window.parent._ig2p_obs.disconnect();"
        "var _ob=new MutationObserver(function(){run();});"
        "_ob.observe(window.parent.document.body,{childList:true,subtree:true});"
        "window.parent._ig2p_obs=_ob;}catch(e){}"
        "})()</script>"
    )
if _logo_escuro or _logo_claro:
    _html_iframe(_js_sidebar_conv(_logo_escuro, _logo_claro), height=0)

setor = st.session_state.setor


# ─────────────────────────────────────────────────────────────────────────────
# VISÃO GERAL (consolidado do Relatório + panorama de todas as fontes)
# ─────────────────────────────────────────────────────────────────────────────
if setor == "Visão Macro":
    titulo_pagina(f"{MUNICIPIO} — Convênios &amp; Emendas · Visão Macro")
    st.markdown("---")

    rel = DADOS.get("relatorio", pd.DataFrame())
    if not rel.empty and "FONTE" in rel.columns:
        rel = rel[rel["FONTE"].astype(str).str.strip().isin(
            ["FEDERAL", "E. FEDERAL", "ESTADUAL", "E. ESTADUAL"])].copy()

    def _s(col):
        return rel[col].apply(_m).sum() if (not rel.empty and col in rel.columns) else 0.0

    tot_rep = _s("R$ REPASSE"); tot_rec = _s("R$ RECEBIDO")
    tot_con = _s("R$ CONTRAPARTIDA"); tot_dep = _s("DEPOSITADO"); tot_sal = _s("SALDO")

    if not rel.empty:
        # Planilha COM aba Relatório (consolidado oficial)
        st.subheader("Consolidado (aba Relatório)")
        kpi_row([("Repasse Total", formar_real(tot_rep)),
                 ("Recebido", formar_real(tot_rec)),
                 ("Contrapartida", formar_real(tot_con)),
                 ("Depositado", formar_real(tot_dep)),
                 ("Saldo", formar_real(tot_sal))])

        taxa_exec = (tot_rec / tot_rep * 100) if tot_rep > 0 else 0.0
        st.metric("Taxa de Execução (Recebido / Repasse)",
                  f"{taxa_exec:.1f}%".replace(".", ","),
                  help="Percentual do repasse que já foi efetivamente recebido.")
    else:
        # Planilha SEM aba Relatório → consolida direto das abas de origem
        st.subheader("Consolidado")
        st.caption("Esta planilha não possui a aba **Relatório**; os totais abaixo são "
                   "calculados diretamente das abas de Convênios e Emendas.")

        def _soma_aba(chave, coluna):
            d = _linhas_validas(DADOS.get(chave, pd.DataFrame()))
            return d[coluna].apply(_m).sum() if (not d.empty and coluna in d.columns) else 0.0

        def _soma_saldo(chave):
            d = _linhas_validas(DADOS.get(chave, pd.DataFrame()))
            if d.empty:
                return 0.0
            c = next((c for c in d.columns if "saldo" in c.lower()), None)
            return d[c].apply(_m).sum() if c else 0.0

        rep_conv = _soma_aba("conv_fed", "Valor Repasse") + _soma_aba("conv_est", "Valor Repasse")
        con_conv = _soma_aba("conv_fed", "Contrapartida") + _soma_aba("conv_est", "Contrapartida")
        val_emen = (_soma_aba("emen_fed", "Valor") + _soma_aba("emen_est", "Valor")
                    + _soma_aba("mds", "Valor"))
        sal_tot  = sum(_soma_saldo(k) for k in ("conv_fed", "conv_est", "emen_fed", "emen_est"))

        kpi_row([("Repasse — Convênios", formar_real(rep_conv)),
                 ("Contrapartida", formar_real(con_conv)),
                 ("Emendas (Fed. + Est. + MDS)", formar_real(val_emen)),
                 ("Saldo em Conta", formar_real(sal_tot)),
                 ("Captação Total", formar_real(rep_conv + val_emen))])

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
# CONVÊNIO A CONVÊNIO — detalhe individual + taxa de execução (aba Relatório)
# ─────────────────────────────────────────────────────────────────────────────
if setor == "Convênio a Convênio":
    titulo_pagina(f"{MUNICIPIO} — Convênio a Convênio")
    st.markdown("---")
    rel = DADOS.get("relatorio", pd.DataFrame())
    if not rel.empty and "FONTE" in rel.columns:
        rel = rel[rel["FONTE"].astype(str).str.strip().isin(
            ["FEDERAL", "E. FEDERAL", "ESTADUAL", "E. ESTADUAL"])].copy()
    if rel.empty:
        # Sem aba Relatório → monta o convênio a convênio a partir das abas
        # de Convênios Federais e Estaduais (sem taxa: não há "Recebido").
        partes = []
        for chave, origem in [("conv_fed", "Federal"), ("conv_est", "Estadual")]:
            d = _linhas_validas(DADOS.get(chave, pd.DataFrame()))
            if d.empty:
                continue
            col_saldo = next((c for c in d.columns if "saldo" in c.lower()), None)
            p = pd.DataFrame({
                "Origem": origem,
                "Nº do Convênio": d.get("Nº do Convênio", pd.Series([""] * len(d))).astype(str),
                "Objeto": d.get("Objeto", pd.Series([""] * len(d))).astype(str),
                "Ano": d.get("Ano", pd.Series([""] * len(d))).astype(str),
                "_rep": d["Valor Repasse"].apply(_m) if "Valor Repasse" in d.columns else 0.0,
                "_con": d["Contrapartida"].apply(_m) if "Contrapartida" in d.columns else 0.0,
                "_sal": d[col_saldo].apply(_m) if col_saldo else 0.0,
            })
            partes.append(p)
        cc = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()

        if cc.empty:
            st.info("Sem convênios lançados para este município.")
        else:
            st.caption("Esta planilha não possui a aba **Relatório**; o detalhamento abaixo "
                       "vem das abas de Convênios. A *taxa de execução* depende da coluna "
                       "**Recebido** (exclusiva da aba Relatório) e por isso não é exibida aqui.")
            kpi_row([("Nº de Convênios", str(len(cc))),
                     ("Repasse Total", formar_real(cc["_rep"].sum())),
                     ("Contrapartida", formar_real(cc["_con"].sum())),
                     ("Saldo em Conta", formar_real(cc["_sal"].sum()))])

            st.markdown("---")
            st.subheader("Repasse por Convênio")
            # nome COMPLETO no hover; no eixo, abreviação com reticências
            cc["_full"] = (cc["Nº do Convênio"].str.strip() + " · " +
                           cc["Objeto"].str.strip()).str.strip(" ·")
            cc["_lbl"] = _rotulos_unicos([_abrev(x) for x in cc["_full"]])
            gg = cc[cc["_rep"] > 0].sort_values("_rep", ascending=True)
            if not gg.empty:
                fig = px.bar(gg, x="_rep", y="_lbl", orientation="h", color="Origem",
                             color_discrete_map={"Federal": C_FED, "Estadual": C_EST},
                             custom_data=["_full"])
                fig.update_layout(height=max(360, 34 * len(gg)), separators=",.",
                                  xaxis_tickprefix="R$ ", xaxis_title="", yaxis_title="",
                                  yaxis=dict(automargin=True),
                                  legend=dict(orientation="h", y=-0.12),
                                  margin=dict(t=20, b=40))
                fig.update_traces(hovertemplate=("<b>%{customdata[0]}</b><br>"
                                                 "Repasse: R$ %{x:,.2f}<extra></extra>"))
                st.plotly_chart(fig, use_container_width=True, config=CONFIG_PT)

            st.markdown("---")
            st.markdown("##### 📋 Detalhamento por Convênio")
            det = cc.copy()
            det["Valor Repasse"] = det["_rep"].apply(formar_real)
            det["Contrapartida"] = det["_con"].apply(formar_real)
            det["Saldo em Conta"] = det["_sal"].apply(formar_real)
            st.dataframe(det[["Origem", "Nº do Convênio", "Ano", "Objeto",
                              "Valor Repasse", "Contrapartida", "Saldo em Conta"]],
                         use_container_width=True, hide_index=True)
    else:
        rel["_rep"] = rel["R$ REPASSE"].apply(_m) if "R$ REPASSE" in rel.columns else 0.0
        rel["_rec"] = rel["R$ RECEBIDO"].apply(_m) if "R$ RECEBIDO" in rel.columns else 0.0
        rel["_sal"] = rel["SALDO"].apply(_m) if "SALDO" in rel.columns else 0.0
        rel["_taxa"] = rel.apply(lambda r: (r["_rec"] / r["_rep"] * 100) if r["_rep"] > 0 else 0.0, axis=1)

        taxa_media = (rel["_rec"].sum() / rel["_rep"].sum() * 100) if rel["_rep"].sum() > 0 else 0.0
        kpi_row([("Nº de Convênios", str(len(rel))),
                 ("Repasse Total", formar_real(rel["_rep"].sum())),
                 ("Recebido", formar_real(rel["_rec"].sum())),
                 ("Taxa de Execução Média", f"{taxa_media:.1f}%".replace(".", ","))])

        st.markdown("---")
        st.subheader("Taxa de Execução por Convênio (Recebido / Repasse)")
        rr = rel.sort_values("_taxa", ascending=True).copy()
        rotulo = ("Nº CONVÊNIO" if "Nº CONVÊNIO" in rr.columns else None)
        _obj = rr.get("OBJETO", pd.Series([""] * len(rr))).astype(str).str.strip()
        rr["_full"] = ((rr[rotulo].astype(str).str.strip() + " · " + _obj).str.strip(" ·")
                       if rotulo else _obj)
        rr["_lbl"] = _rotulos_unicos([_abrev(x) for x in rr["_full"]])
        fig = px.bar(rr, x="_taxa", y="_lbl", orientation="h",
                     color="_taxa", color_continuous_scale=["#860000", "#f39c12", "#2ea043"],
                     range_color=[0, 100], custom_data=["_full", "_rep", "_rec"])
        fig.update_layout(height=max(360, 34 * len(rr)), separators=",.",
                          xaxis_title="Taxa de Execução (%)", yaxis_title="",
                          yaxis=dict(automargin=True),
                          coloraxis_showscale=False, margin=dict(t=20, b=30))
        fig.update_traces(hovertemplate=("<b>%{customdata[0]}</b><br>"
                                         "Execução: %{x:.1f}%<br>"
                                         "Repasse: R$ %{customdata[1]:,.2f}<br>"
                                         "Recebido: R$ %{customdata[2]:,.2f}<extra></extra>"))
        st.plotly_chart(fig, use_container_width=True, config=CONFIG_PT)

        st.markdown("---")
        st.markdown("##### 📋 Detalhamento por Convênio")
        det = rel.copy()
        det["Taxa Execução"] = det["_taxa"].apply(lambda x: f"{x:.1f}%".replace(".", ","))
        cols_show = [c for c in ["FONTE", "Nº CONVÊNIO", "OBJETO", "R$ REPASSE",
                                 "R$ RECEBIDO", "SALDO", "Taxa Execução"] if c in det.columns]
        st.dataframe(det[cols_show], use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# CONVÊNIOS (Federais / Estaduais) — estrutura compartilhada
# ─────────────────────────────────────────────────────────────────────────────
def render_convenios(chave, titulo, dim_orgao, cor):
    df = _linhas_validas(DADOS.get(chave, pd.DataFrame()))
    titulo_pagina(f"{MUNICIPIO} — {titulo}")
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
    render_convenios("conv_fed", "Convênios Federais", "Ministério", C_FED)

if setor == "Convênios Estaduais":
    render_convenios("conv_est", "Convênios Estaduais", "Secretaria", C_EST)


# ─────────────────────────────────────────────────────────────────────────────
# EMENDAS ESPECIAIS (Federais / Estaduais)
# ─────────────────────────────────────────────────────────────────────────────
def render_emendas(chave, titulo, dim_orgao, cor):
    df = _linhas_validas(DADOS.get(chave, pd.DataFrame()))
    titulo_pagina(f"{MUNICIPIO} — {titulo}")
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
    render_emendas("emen_fed", "Emendas Especiais Federais", "Ministério", C_FED)

if setor == "Emendas Especiais Estaduais":
    render_emendas("emen_est", "Emendas Especiais Estaduais", "Secretaria", C_EST)


# ─────────────────────────────────────────────────────────────────────────────
# MDS
# ─────────────────────────────────────────────────────────────────────────────
if setor == "MDS":
    titulo_pagina(f"{MUNICIPIO} — Emendas MDS")
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


# ── FIM DO SCRIPT: libera o loader (a página terminou de renderizar) ──────────
if _logo_escuro or _logo_claro:
    _html_iframe(
        "<script>(function(){try{"
        "var d=window.parent.document;"
        "function done(){var l=d.querySelectorAll('.ig2p-loader');"
        "for(var i=0;i<l.length;i++){l[i].classList.add('ig2p-done');}}"
        "done();setTimeout(done,80);"
        "}catch(e){}})()</script>", height=0)