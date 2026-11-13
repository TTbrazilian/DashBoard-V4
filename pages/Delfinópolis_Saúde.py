import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import datetime
import io
import csv
import gspread
from google.oauth2.service_account import Credentials
import plotly.express as px
import plotly.io as pio
import os
import unicodedata
import plotly.graph_objects as go
import streamlit.components.v1 as components
from random import random

st.set_page_config(page_title="Gestão de Recursos - Delfinópolis", layout="wide")

st.markdown("""
    <style>
        @keyframes subirBarra {
            from { clip-path: inset(100% 0 0 0); }
            to   { clip-path: inset(0%   0 0 0); }
        }
        .js-plotly-plot .point path {
            animation: subirBarra 1.5s cubic-bezier(0.25,1,0.5,1) forwards;
            animation-delay: 0.3s;
            clip-path: inset(100% 0 0 0);
        }
        @keyframes slideIn {
            from { opacity:0; transform:translateX(20px); }
            to   { opacity:1; transform:translateX(0);    }
        }
        .stButton button { animation: slideIn 0.4s ease-out; }
        [data-testid="stSidebarNav"] li:first-child > a > span,
        [data-testid="stSidebarNav"] li:first-child > a > p {
            display: none !important;
        }
        /* ===== CABEÇALHO NO TOPO (regra universal iG2P) =====
           Remove o espaço vazio acima do título:
           (1) reduz o padding-top padrão do container principal;
           (2) colapsa o container do iframe de injeção de JS (logo iG2P), que
               renderiza uma faixa vazia no topo da área principal.
           Obs.: os únicos iframes do fluxo principal são os de injeção de JS
           (logo e scroll); gráficos Plotly não são iframes, então não são afetados. */
        [data-testid="stMainBlockContainer"], .stMainBlockContainer,
        .block-container {
            padding-top: 1.5rem !important;
        }
        [data-testid="stElementContainer"]:has(iframe),
        .element-container:has(iframe),
        [data-testid="stIFrame"] {
            height: 0 !important;
            min-height: 0 !important;
            margin: 0 !important;
            padding: 0 !important;
            overflow: hidden !important;
        }
        /* ===== LOGO iG2P no topo do sidebar (alinhado com a setinha de recolher) ===== */
        [data-testid="stSidebarHeader"] {
            padding-top: .2rem !important;
            padding-bottom: 0 !important;
            min-height: 0 !important;
        }
        [data-testid="stSidebarNav"] {
            margin-top: -2.6rem !important;
            padding-top: 0 !important;
        }
        [data-testid="stSidebarNav"] > ul { padding-top: 0 !important; }
        section[data-testid="stSidebar"] .ig2p-logo-sidebar {
            margin: 0 0 2px 0 !important;
        }
    </style>
""", unsafe_allow_html=True)

pio.templates.default = "plotly_white"
CONFIG_PT = {'displaylogo': False, 'showTips': False}

# Compatibilidade: st.components.v1.html (components.html) foi descontinuado na
# versão 1.56 do Streamlit em favor de st.iframe (que também embute string HTML
# num iframe e executa o JavaScript). Usa st.iframe quando disponível e mantém
# fallback para versões antigas.
def _html_iframe(html, height=0, scrolling=False):
    if hasattr(st, "iframe"):
        # st.iframe (Streamlit >= 1.56) NÃO aceita height=0 (usado aqui para injeção
        # invisível de JS). Altura precisa ser inteiro positivo ou "stretch"/"content".
        # Usamos "content" (auto-ajuste, colapsa para ~0) quando height não é positivo.
        h = height if isinstance(height, int) and height > 0 else "content"
        st.iframe(html, height=h)
    else:
        components.html(html, height=height, scrolling=scrolling)

MESES_ORDEM = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
               'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']

# Rótulos amigáveis das fontes de saúde (baseado no Delfinópolis_DF.csv)
FONTE_LABEL = {
    '1500':'1500 · Próprio Saúde','1600':'1600 · Federal Custeio','1601':'1601 · Federal Capital',
    '1602':'1602 · Covid','1603':'1603 · Covid','1604':'1604 · Agentes','1605':'1605 · Piso Enferm.',
    '1621':'1621 · Estadual','1631':'1631 · Conv. Federal','1659':'1659 · Trans. Federais',
    '2621':'2621 · Supr. Estadual','1706':'1706 · Emenda Federal',
    # Superávit de exercícios anteriores (só aparecem nas fichas)
    '2501':'2501 · Supr. Próprio','2600':'2600 · Supr. Federal Custeio',
    '2706':'2706 · Supr. Emenda Federal','2755':'2755 · Supr. Federal',
    # Fontes específicas do Delfinópolis (inferidas pelo padrão — confirmar):
    '1501':'1501 · Próprio Saúde (compl.)','1632':'1632 · Conv. Federal',
    '1709':'1709 · Emenda Federal','2601':'2601 · Supr. Federal',
}
def fonte_lbl(f): return FONTE_LABEL.get(str(f).strip(), f"Fonte {f}")

# Paleta QUENTE para despesas por fonte (distinta dos azuis usados nas receitas)
CORES_FONTE = {
    '1500':'#7f8c8d','1600':'#e67e22','1601':'#8e44ad','1602':'#c0392b','1603':'#9b59b6',
    '1604':'#16a085','1605':'#f1c40f','1621':'#c0392b','1631':'#d35400','1659':'#27ae60',
    '2621':'#e74c3c','1706':'#a93226',
    '2501':'#95a5a6','2600':'#ca6f1e','2706':'#922b21','2755':'#b03a2e',
    '1501':'#7f8c8d','1632':'#d35400','1709':'#a93226','2601':'#ca6f1e',
}
def cor_fonte(f): return CORES_FONTE.get(str(f).strip(), '#95a5a6')

# Receitas em AZUL (contraste com as despesas quentes)
C_FEDERAL  = '#003366'
C_ESTADUAL = '#2E86C1'

# Cores do bloco 15% (mesmas da Educação: receita azul, despesa vermelha, meta laranja)
C_15_RECEITA = '#003366'
C_15_DESPESA = '#860000'
C_META       = '#f39c12'

# Grupos de fonte para o comparativo de vinculados (Visão Macro)
GRUPO_DESP_VINC = {
    'Federal Custeio': ['1600','1604','1605'],
    'Federal Capital': ['1601'],
    'Estadual':        ['1621'],
}
COR_GRUPO_DESP = {
    'Federal Custeio': '#e67e22',
    'Federal Capital': '#8e44ad',
    'Estadual':        '#c0392b',
}

# Origem de cada fonte de despesa (usado no filtro Federal/Estadual dos vinculados)
ORIGEM_FONTE = {
    '1600':'Federal','1601':'Federal','1602':'Federal','1603':'Federal',
    '1604':'Federal','1605':'Federal','1631':'Federal','1659':'Federal','1706':'Federal',
    '2600':'Federal','2706':'Federal','2755':'Federal',
    '1632':'Federal','1709':'Federal','2601':'Federal',
    '1621':'Estadual','2621':'Estadual',
}

# Fontes PRÓPRIAS (recurso do município) — não entram no comparativo de vinculados
FONTES_PROPRIAS = ['1500']
def origem_da_fonte(f): return ORIGEM_FONTE.get(str(f).strip())

# Elementos de folha/pessoal (ajustável). Usados em "Folha por Fonte".
FOLHA_ELEMENTOS = [
    'Vencimentos e Vantagens Fixas - Pessoal Civil',
    'Obrigações Patronais',
    'Contratação por tempo Determinado',
    'Outras Despesas Variáveis - Pessoal Civil',
    'Indenizações e Restituições Trabalhistas',
    'Auxílio-Alimentação',
    'Auxílio Alimentação',
    'Diárias - Pessoal Civil',
    'Outras Despesas de Pessoal decorrentes de Contratos',
]

CAPITAL_ELEM = [
    'Equipamentos e Materiais Permanentes',
    'Obras e Instalações',
    'Aquisição de Imóveis',
]

# ── FUNÇÕES UTILITÁRIAS ───────────────────────────────────────────────────────
def remover_acentos(texto):
    if not texto: return ""
    return "".join(
        c for c in unicodedata.normalize('NFD', str(texto))
        if unicodedata.category(c) != 'Mn'
    ).lower().strip()

def limpar_valor(valor):
    if pd.isna(valor) or str(valor).strip() in ["","−","-","R$ 0,00","0","#REF!"]:
        return 0.0
    s = str(valor).replace('R$','').replace(' ','').replace('.','').replace(',','.')
    try:
        if '(' in s and ')' in s: s = '-' + s.replace('(','').replace(')','')
        return float(s)
    except: return 0.0

def formar_real(valor):
    if valor is None: return "R$ 0,00"
    return f"R$ {valor:,.2f}".replace(",","X").replace(".",",").replace("X",".")

def soma_cols(df, cols):
    presentes = [c for c in cols if c in df.columns]
    return df[presentes].sum().sum() if presentes else 0.0

# ── CARGA DE DADOS ────────────────────────────────────────────────────────────
# Arquivos:
# • Delfinópolis.csv    — FICHAS (header=1; Empenhado/Liquidado/Pago por mês; '.1'=Liquidado;
#                   'Abril ' com espaço). 5 categorias.
# • Delfinópolis_R.csv  — Receitas de Impostos + Cota-Parte (base do índice de 15%).
# • Delfinópolis_DF.csv — Despesas por Fonte (blocos Empenhado/Liquidado/Pago; fonte 1500 = próprio).
# • Delfinópolis_RV.csv — Receitas Vinculadas Federais/Estaduais por categoria (novo).
# ── LEITURA VIA GOOGLE SHEETS (com fallback CSV local durante a migração) ─────
@st.cache_resource
def _conectar_sheets():
    escopos = ["https://www.googleapis.com/auth/spreadsheets.readonly",
               "https://www.googleapis.com/auth/drive.readonly"]
    cred = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=escopos)
    gc = gspread.authorize(cred)
    # Timeout HTTP explícito → se a API travar, a chamada falha em ~15s (tratada
    # pelo retry/erro) em vez de pendurar a página em spinner infinito.
    try:
        gc.set_timeout(15)                     # gspread 6.x (Client → HTTPClient)
    except Exception:
        try:
            gc.http_client.set_timeout(15)
        except Exception:
            try:                               # gspread 5.x: força timeout na sessão
                _hc = getattr(gc, 'http_client', None)
                _s = getattr(gc, 'session', None)
                if _s is None and _hc is not None:
                    _s = getattr(_hc, 'session', None)
                if _s is not None:
                    _orig_req = _s.request
                    def _req_timeout(*a, **k):
                        if not k.get('timeout'):
                            k['timeout'] = 15
                        return _orig_req(*a, **k)
                    _s.request = _req_timeout
            except Exception:
                pass
    return gc


def _norm_aba(s):
    """Normaliza o título de uma aba: remove acentos, caixa e espaços redundantes."""
    import unicodedata
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode('ascii')
    return ' '.join(s.lower().split())


def _norm_aba_sing(s):
    """Como _norm_aba, mas remove o 's' final de cada palavra para tolerar
    diferenças de singular/plural (ex.: 'Receitas'≈'Receita', 'Vinculadas'≈'Vinculada')."""
    return ' '.join(w[:-1] if len(w) > 3 and w.endswith('s') else w
                    for w in _norm_aba(s).split())


def _gs_call(fn, tentativas=3, espera=1.0):
    """Chamada à API do Google Sheets com retry/backoff para erros transitórios
    (429 rate-limit, 5xx, timeout). Erros definitivos são relançados na hora."""
    import time
    _ult = None
    for _i in range(tentativas):
        try:
            return fn()
        except Exception as _e:
            _ult = _e
            _m = str(_e).lower()
            # timeout NÃO re-tenta (falha rápido em ~15s p/ não pendurar a página);
            # 429/5xx re-tentam (respondem rápido, só custam o backoff).
            _transit = any(t in _m for t in ('429', 'quota', 'rate limit', 'ratelimit',
                                             'resource has been exhausted', '500', '502',
                                             '503', 'internal error', 'backend',
                                             'temporarily', 'connection reset',
                                             'connection aborted'))
            if _i < tentativas - 1 and _transit:
                time.sleep(espera * (2 ** _i))
                continue
            raise
    if _ult:
        raise _ult


def _abrir_ws(sheet_id, aba):
    """Abre a worksheet casando o nome de forma tolerante: exato → sem acento/caixa/
    espaço → sem plural → contido. Com retry para erros transitórios da API."""
    sh = _gs_call(lambda: _conectar_sheets().open_by_key(sheet_id))
    try:
        return _gs_call(lambda: sh.worksheet(aba))
    except Exception:
        cands = _gs_call(lambda: sh.worksheets())
        _an = _norm_aba(aba); _as = _norm_aba_sing(aba)
        for _w in cands:
            if _norm_aba(_w.title) == _an:
                return _w
        for _w in cands:
            if _norm_aba_sing(_w.title) == _as:
                return _w
        for _w in cands:
            _tn = _norm_aba(_w.title)
            if _an and (_an in _tn or _tn in _an):
                return _w
        raise KeyError("aba '%s' nao encontrada na planilha" % aba)


def _ler_aba(sheet_id, aba, **read_csv_kwargs):
    """Lê uma aba do Google Sheets reconstruindo o CSV a partir das células e
    reutilizando pd.read_csv. Casa o nome da aba de forma tolerante (acento/caixa/
    espaço/singular-plural) e usa retry para erros transitórios."""
    ws = _abrir_ws(sheet_id, aba)
    vals = _gs_call(lambda: ws.get_all_values())
    buf = io.StringIO()
    csv.writer(buf).writerows(vals)
    buf.seek(0)
    return pd.read_csv(buf, **read_csv_kwargs)


def _fonte(sid, aba, path_local, **kwargs):
    """Fonte de dados com PRIORIDADE TOTAL para a API viva. Com 'sid' configurado,
    a API é AUTORITATIVA (com retry): se falhar, o erro é PROPAGADO — nunca exibe
    CSV local defasado no lugar dos dados vivos (era isso que fazia o Itaú mostrar
    maio em vez de junho). O CSV local só é usado quando NÃO há API (sid vazio)."""
    # ID placeholder ("COLE_O_ID...") não é API válida → usa o CSV local direto.
    if sid and not str(sid).upper().startswith("COLE"):
        kw = {k: v for k, v in kwargs.items() if k != "encoding"}
        return _ler_aba(sid, aba, **kw)
    if path_local:
        return pd.read_csv(path_local, **kwargs)
    raise FileNotFoundError("sem fonte (API e local) para a aba %r" % aba)


@st.cache_data(ttl=300)
def load_data():
    diretorio_atual = os.path.dirname(os.path.abspath(__file__))

    def _buscar(nome):
        for p in [os.path.join(diretorio_atual, '..', 'zSaúde', nome),
                  os.path.join(diretorio_atual, 'zSaúde', nome), nome]:
            if os.path.exists(p): return p
        return None

    path_f  = _buscar("Delfinópolis.csv")
    path_r  = _buscar("Delfinópolis_R.csv")
    path_df = _buscar("Delfinópolis_DF.csv")
    path_rv = _buscar("Delfinópolis_RV.csv")
    sid = st.secrets.get("saude", {}).get("Delfinópolis", "")
    if not sid and not path_f: return None, None, None, None

    # ── FICHAS ───────────────────────────────────────────────────────────────
    df = _fonte(sid, "Fichas", path_f, sep=None, engine='python', encoding='utf-8', header=1)
    df.columns = [str(c).strip() for c in df.columns]
    for col in df.columns:
        if any(k in col for k in ['Orçado','Creditado','Anulado','Saldo'] + MESES_ORDEM + ['Total']):
            df[col] = df[col].apply(limpar_valor)
    df['Ficha']     = df['Ficha'].astype(str).str.replace('.0','',regex=False).str.strip()
    df['Fonte']     = df['Fonte'].fillna('').astype(str).str.replace('.0','',regex=False).str.strip()
    df['Categoria'] = df['Categoria'].astype(str).str.strip()
    df['Elemento']  = df['Elemento'].astype(str).str.strip()
    df = df[df['Categoria'] != 'nan'].copy()

    rename_liq = {f"{m}.1": f"{m}_Liq" for m in MESES_ORDEM}
    rename_liq['Abril .1'] = 'Abril_Liq'   # coluna de Abril tem espaço
    rename_liq['Total.1']  = 'Total_Liq'
    df = df.rename(columns={k: v for k, v in rename_liq.items() if k in df.columns})

    df['Natureza'] = df['Elemento'].apply(
        lambda x: 'Capital (Invest.)' if x in CAPITAL_ELEM else 'Custeio (Manut.)'
    )

    # ── RECEITAS (Impostos + Cota-Parte) ─────────────────────────────────────
    df_r = None
    if sid or path_r:
        df_r = _fonte(sid, "Receitas de Impostos", path_r, sep=None, engine='python', encoding='utf-8', header=0)
        df_r.columns = [str(c).strip() for c in df_r.columns]
        if 'Categoria' in df_r.columns:
            df_r['Categoria'] = df_r['Categoria'].astype(str).str.strip()
        for col in df_r.columns:
            if col in MESES_ORDEM + ['Total','Orçado Receitas']:
                df_r[col] = df_r[col].apply(limpar_valor)

    # ── DESPESAS POR FONTE ───────────────────────────────────────────────────
    df_df = None
    if sid or path_df:
        df_df = _fonte(sid, "Despesas por fonte", path_df, sep=None, engine='python', encoding='utf-8')
        df_df.columns = [str(c).strip() for c in df_df.columns]
        df_df['Tipo'] = df_df['Tipo'].replace({'Empenho': 'Liquidado'})
        df_df = df_df[df_df['Tipo'].isin(['Empenhado','Liquidado','Pago'])].copy()
        df_df['Tipo']  = df_df['Tipo'].str.strip()
        df_df['Fonte'] = df_df['Fonte'].fillna('').astype(str).str.replace('.0','',regex=False).str.strip()
        for col in df_df.columns:
            if col in MESES_ORDEM + ['Total']:
                df_df[col] = df_df[col].apply(limpar_valor)

    # ── RECEITAS VINCULADAS (Federal/Estadual por categoria) ─────────────────
    df_rv = None
    if sid or path_rv:
        df_rv = _fonte(sid, "Receitas Vinculadas", path_rv, sep=None, engine='python', encoding='utf-8', header=0)
        df_rv.columns = [str(c).strip() for c in df_rv.columns]
        for c in ['Origem','Tipo','Categoria']:
            if c in df_rv.columns: df_rv[c] = df_rv[c].astype(str).str.strip()
        for col in df_rv.columns:
            if col in MESES_ORDEM + ['Total','Orçado Receitas']:
                df_rv[col] = df_rv[col].apply(limpar_valor)
        # remove linhas vazias/residuais
        df_rv = df_rv[df_rv['Categoria'].notna() & (df_rv['Categoria'] != 'nan') &
                      (df_rv['Categoria'] != '')].copy()

    return df, df_r, df_df, df_rv

# ══════════════════════════════════════════════════════════════════════════════
# LOADER central com logo (regra universal iG2P)
# Criado ANTES de qualquer carregamento pesado e liberado só no FIM do script,
# cobrindo o tempo real de carregamento (junto do indicador nativo do Streamlit).
# ══════════════════════════════════════════════════════════════════════════════
import base64 as _b64_loader


def _logo_loader(nome):
    cands = [f"Logos/{nome}", f"../Logos/{nome}"]
    try:
        _d = os.path.dirname(os.path.abspath(__file__))
        cands += [os.path.join(_d, "Logos", nome), os.path.join(_d, "..", "Logos", nome)]
    except NameError:
        pass
    for p in cands:
        if os.path.exists(p):
            return "data:image/png;base64," + _b64_loader.b64encode(open(p, "rb").read()).decode()
    return ""


_LOGO_ESCURO = _logo_loader("LOGOTIPO IG2P - OFICIAL - BRANCO.png")
_LOGO_CLARO  = _logo_loader("LOGOTIPO IG2P - OFICIAL.png")

if _LOGO_ESCURO or _LOGO_CLARO:
    st.markdown(f"""
    <div class="ig2p-loader">
      <img class="ig2p-logo-escuro" src="{_LOGO_ESCURO}">
      <img class="ig2p-logo-claro"  src="{_LOGO_CLARO}">
    </div>
    <style>
      [data-testid="stElementContainer"]:has(.ig2p-loader),
      .element-container:has(.ig2p-loader) {{
        height:0!important; min-height:0!important; margin:0!important; padding:0!important;
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


# ── RELATÓRIO DE CONSULTORIA — SAÚDE (PDF gerado na hora) ─────────────────────
RELATORIO_SECRETARIA = ""   # nome da Secretária(o) de Saúde (opcional; vazio = oculto)


def _rel_tab_saude(data, header_color, zebra, col_widths=None):
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle
    if col_widths is None:
        col_widths = [95*mm, 75*mm]
    t = Table(data, colWidths=col_widths, hAlign='LEFT')
    style = [('BACKGROUND',(0,0),(-1,0),header_color),('TEXTCOLOR',(0,0),(-1,0),colors.white),
        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),9),
        ('ALIGN',(1,0),(-1,-1),'LEFT'),('GRID',(0,0),(-1,-1),0.4,colors.HexColor('#cccccc')),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),('TOPPADDING',(0,0),(-1,-1),4),
        ('BOTTOMPADDING',(0,0),(-1,-1),4),('LEFTPADDING',(0,0),(-1,-1),6)]
    for r in range(1, len(data)):
        if r % 2 == 1:
            style.append(('BACKGROUND',(0,r),(-1,r),zebra))
    t.setStyle(TableStyle(style)); return t


def _dados_relatorio_saude(df, df_r, df_df, df_rv, meses):
    """Indicadores do relatório de Saúde (uniformes; reusa as constantes da página)."""
    d = {'periodo': f"{meses[0]}–{meses[-1]}" if meses else "—"}
    cols_liq = [f"{m}_Liq" for m in meses if f"{m}_Liq" in df.columns]
    # constantes da página (com fallback — o relatório é portável entre municípios)
    _FP = globals().get('FONTES_PROPRIAS', ['1500'])
    _orig = globals().get('origem_da_fonte', lambda f: None)
    _FE = globals().get('FOLHA_ELEMENTOS', [])

    orcado = df['Orçado'].sum() if 'Orçado' in df.columns else 0.0
    liq = (df[cols_liq].sum().sum() if cols_liq
           else (df['Total_Liq'].sum() if 'Total_Liq' in df.columns else 0.0))
    d.update(orcado=orcado, liquidado=liq, saldo=orcado - liq,
             perc_exec=(liq / orcado * 100) if orcado > 0 else 0.0)

    base = df_r[df_r['Categoria'].astype(str).str.strip().isin(['Impostos', 'Cota-Parte'])]
    base_15 = soma_cols(base, meses)
    aplic = df_df[(df_df['Fonte'] == '1500') & (df_df['Tipo'] == 'Liquidado')]
    aplic_15 = soma_cols(aplic, meses)
    d.update(base_15=base_15, aplic_15=aplic_15, minimo_15=base_15 * 0.15,
             indice_15=(aplic_15 / base_15 * 100) if base_15 > 0 else 0.0)

    def _rv(org):
        if df_rv is None or 'Origem' not in df_rv.columns:
            return 0.0
        return soma_cols(df_rv[df_rv['Origem'].astype(str).str.strip() == org], meses)

    def _desp(org):
        dd = df_df[(df_df['Tipo'] == 'Liquidado') & (~df_df['Fonte'].isin(_FP))]
        dd = dd[dd['Fonte'].map(_orig) == org]
        return soma_cols(dd, meses)

    rf, re_ = _rv('Federal'), _rv('Estadual')
    df_, de_ = _desp('Federal'), _desp('Estadual')
    d.update(rec_fed=rf, rec_est=re_, rec_vinc=rf + re_,
             desp_fed=df_, desp_est=de_, desp_vinc=df_ + de_,
             saldo_vinc=(rf + re_) - (df_ + de_))

    tc = df[df['Natureza'] == 'Custeio (Manut.)']['Total_Liq'].sum() if 'Natureza' in df.columns else 0.0
    tk = df[df['Natureza'] == 'Capital (Invest.)']['Total_Liq'].sum() if 'Natureza' in df.columns else 0.0
    d.update(custeio=tc, capital=tk)

    folha = df[df['Elemento'].isin(_FE)] if 'Elemento' in df.columns else df.iloc[0:0]
    d['folha'] = (folha[cols_liq].sum().sum() if cols_liq
                  else (folha['Total_Liq'].sum() if 'Total_Liq' in folha.columns else 0.0))
    return d


def _pdf_relatorio_saude(d, municipio, secretaria=None):
    """Gera o PDF do relatório gerencial de Saúde."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle, HRFlowable)
    from reportlab.lib.enums import TA_CENTER

    if secretaria is None:
        secretaria = RELATORIO_SECRETARIA
    AZUL = colors.HexColor('#003366'); VERDE = colors.HexColor('#1a7a4a')
    VERM = colors.HexColor('#b00020'); LARANJA = colors.HexColor('#b9770e')
    CINZA = colors.HexColor('#f0f2f5')

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm,
                            topMargin=16*mm, bottomMargin=16*mm, title="IG2P - Relatórios",
                            author="iG2P — Plataforma de Gestão Pública",
                            subject=f"Relatório Analítico e Gerencial — Saúde ({municipio})")
    ss = getSampleStyleSheet()
    h_title = ParagraphStyle('t', parent=ss['Title'], fontSize=16, textColor=AZUL, alignment=TA_CENTER, spaceAfter=2)
    h_sub = ParagraphStyle('s', parent=ss['Normal'], fontSize=9.5, textColor=colors.grey, alignment=TA_CENTER, spaceAfter=10)
    h2 = ParagraphStyle('h2', parent=ss['Heading2'], fontSize=12, textColor=AZUL, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle('b', parent=ss['Normal'], fontSize=9.5, leading=13)
    a_ok = ParagraphStyle('aok', parent=body, textColor=VERDE)
    a_bad = ParagraphStyle('abad', parent=body, textColor=VERM)
    a_warn = ParagraphStyle('awarn', parent=body, textColor=LARANJA)
    legal = ParagraphStyle('legal', parent=body, fontSize=8.2, textColor=colors.HexColor('#555'), leftIndent=2)

    def base_legal(txt):
        return Paragraph(f"<b>Base legal:</b> {txt}", legal)

    el = []
    el.append(Paragraph("Relatório Analítico e Gerencial — Saúde", h_title))
    el.append(Paragraph("Consultoria iG2P — Plataforma de Gestão Pública", h_sub))
    el.append(HRFlowable(width="100%", color=AZUL, thickness=1.2, spaceAfter=8))

    # 1. Informações
    el.append(Paragraph("1. Informações da Reunião", h2))
    hoje = datetime.now().strftime("%d/%m/%Y")
    info = [["Município:", f"{municipio} - MG"]]
    if (secretaria or "").strip():
        info.append(["Secretária(o) de Saúde:", secretaria.strip()])
    info.append(["Data:", hoje])
    info.append(["Pauta Principal:", f"Análise de dados financeiros e orçamentários da "
                                     f"Saúde ({d['periodo']})."])
    t = Table(info, colWidths=[48*mm, 122*mm])
    t.setStyle(TableStyle([('FONTNAME',(0,0),(0,-1),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),9.5),
        ('TEXTCOLOR',(0,0),(0,-1),AZUL),('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),3)]))
    el.append(t)

    # 2. Execução Orçamentária
    el.append(Paragraph("2. Execução Orçamentária", h2))
    el.append(_rel_tab_saude([["Indicador", "Valor"],
        ["Previsão (Orçado)", formar_real(d['orcado'])],
        [f"Executado / Liquidado ({d['periodo']})", formar_real(d['liquidado'])],
        ["Saldo Orçamentário", formar_real(d['saldo'])],
        ["% de Execução", f"{d['perc_exec']:.2f}%".replace('.', ',')],
    ], AZUL, CINZA))

    # 3. Aplicação Mínima em Saúde (15%)
    el.append(Paragraph("3. Aplicação Mínima em Saúde (15%)", h2))
    el.append(_rel_tab_saude([["Indicador", "Valor"],
        [f"Receita Base (Impostos + Cota-Parte, {d['periodo']})", formar_real(d['base_15'])],
        ["Mínimo Constitucional (15%)", formar_real(d['minimo_15'])],
        ["Aplicado em Saúde (Recurso Próprio — Fonte 1500)", formar_real(d['aplic_15'])],
    ], AZUL, CINZA))
    idx = d['indice_15']
    if idx < 15:
        el.append(Paragraph(f"⚠ Alerta crítico: o índice de aplicação em saúde está em "
            f"<b>{idx:.2f}%</b>, <b>abaixo</b> do mínimo constitucional de 15%. É necessário "
            f"ampliar a aplicação de recursos próprios em ações e serviços públicos de saúde "
            f"até o encerramento do exercício.", a_bad))
    else:
        el.append(Paragraph(f"✔ O índice de aplicação em saúde está em <b>{idx:.2f}%</b>, "
            f"cumprindo o mínimo constitucional de 15% de recursos próprios em ações e "
            f"serviços públicos de saúde.", a_ok))
    el.append(base_legal("Constituição Federal, art. 198, §2º, III e §3º; Emenda Constitucional "
        "nº 29/2000; Lei Complementar nº 141/2012 (define as ações e serviços públicos de saúde "
        "e a base de cálculo do mínimo de 15% para os Municípios)."))

    # 4. Recursos Vinculados
    el.append(Paragraph("4. Recursos Vinculados (Transferências SUS)", h2))
    sv = d['saldo_vinc']
    el.append(_rel_tab_saude([["Origem", "Receita", "Despesa", "Saldo"],
        ["Federal", formar_real(d['rec_fed']), formar_real(d['desp_fed']),
         formar_real(d['rec_fed'] - d['desp_fed'])],
        ["Estadual", formar_real(d['rec_est']), formar_real(d['desp_est']),
         formar_real(d['rec_est'] - d['desp_est'])],
        ["Total", formar_real(d['rec_vinc']), formar_real(d['desp_vinc']), formar_real(sv)],
    ], AZUL, CINZA, col_widths=[38*mm, 44*mm, 44*mm, 44*mm]))
    if sv >= 0:
        el.append(Paragraph(f"✔ As receitas vinculadas superam as despesas no período, com saldo "
            f"de <b>{formar_real(sv)}</b> a executar. Recomenda-se planejar a aplicação dos "
            f"recursos vinculados dentro dos respectivos blocos de financiamento do SUS.", a_ok))
    else:
        el.append(Paragraph(f"⚠ As despesas vinculadas superam as receitas do período em "
            f"<b>{formar_real(abs(sv))}</b>, indicando uso de recursos próprios para cobrir "
            f"ações vinculadas. Recomenda-se revisar a execução por bloco.", a_warn))
    el.append(base_legal("Lei Complementar nº 141/2012, arts. 2º e 3º; transferências fundo a "
        "fundo do SUS (Blocos de Custeio e de Investimento das Ações e Serviços de Saúde)."))

    # 5. Despesas por Natureza
    el.append(Paragraph("5. Despesas por Natureza", h2))
    el.append(_rel_tab_saude([["Natureza", "Valor Liquidado"],
        ["Custeio (Manutenção)", formar_real(d['custeio'])],
        ["Capital (Investimento)", formar_real(d['capital'])],
    ], AZUL, CINZA))

    # 6. Folha de Pagamento
    el.append(Paragraph("6. Folha de Pagamento", h2))
    el.append(_rel_tab_saude([["Indicador", "Valor"],
        [f"Folha de Pagamento — Saúde ({d['periodo']})", formar_real(d['folha'])],
    ], AZUL, CINZA))

    el.append(Spacer(1, 6))
    el.append(HRFlowable(width="100%", color=colors.HexColor('#cccccc'), thickness=0.6, spaceAfter=4))
    el.append(Paragraph("Documento gerado automaticamente pela plataforma iG2P — Inteligência em "
        "Gestão Pública. Os valores refletem a base de dados do período analisado.", h_sub))

    doc.build(el)
    buf.seek(0)
    return buf.getvalue()


try:
    df_raw, df_r, df_df, df_rv = load_data()
except Exception as _e_load:
    try:  # libera o loader; senão o overlay do logo esconde o aviso e parece "travado"
        _html_iframe("<script>(function(){try{var d=window.parent.document;"
                     "var l=d.querySelectorAll('.ig2p-loader');"
                     "for(var i=0;i<l.length;i++){l[i].classList.add('ig2p-done');}"
                     "}catch(e){}})()</script>", height=0)
    except Exception:
        pass
    if isinstance(_e_load, PermissionError):
        _sa = ""
        try:
            _sa = dict(st.secrets["gcp_service_account"]).get("client_email", "")
        except Exception:
            pass
        st.error("🔒 A conta de serviço **não tem acesso** à planilha deste município "
                 "(a API do Google retornou 403 FORBIDDEN). Compartilhe a planilha do "
                 "Google Sheets com o e-mail **" + (_sa or "da conta de serviço") + "** "
                 "como *Leitor* e recarregue. Os demais municípios funcionam porque suas "
                 "planilhas já estão compartilhadas com essa conta.")
    else:
        st.error("⚠️ Não foi possível ler os dados **vivos** da planilha via API "
                 f"({type(_e_load).__name__}: {_e_load}). Os dados **não foram atualizados**. "
                 "Para evitar decisões com base em números defasados, nenhum dado antigo é "
                 "exibido — verifique a planilha (nomes de aba/estrutura/permissão) e recarregue.")
    st.stop()

def _detectar_meses(df_f, df_dfonte):
    out = []
    for m in MESES_ORDEM:
        liq = f"{m}_Liq"
        v_f = df_f[liq].sum() if liq in df_f.columns else 0.0
        v_d = 0.0
        if df_dfonte is not None and m in df_dfonte.columns:
            v_d = df_dfonte[df_dfonte['Tipo'] == 'Liquidado'][m].sum()
        if abs(v_f) > 0.005 or abs(v_d) > 0.005:
            out.append(m)
    return out or ['Janeiro','Fevereiro','Março','Abril']


# ══════════════════════════════════════════════════════════════════════════════
# INTERFACE
# ══════════════════════════════════════════════════════════════════════════════
if df_raw is not None:

    meses_disp = _detectar_meses(df_raw, df_df)

    # ── FILTRO DE PERÍODO (regra universal iG2P) ─────────────────────────────
    #   Restringe meses_disp → todos os gráficos somam sobre ele, então a página
    #   inteira passa a respeitar o período escolhido.
    st.sidebar.subheader("📆 Período de Análise")
    _per_modo = st.sidebar.radio("Filtrar por:",
        ["Todo o período", "Bimestre", "Semestre", "Personalizado (de–até)"],
        key="per_modo_sau")
    _mdetect = [m for m in MESES_ORDEM if m in meses_disp]
    _sel_per = None
    if _per_modo == "Bimestre":
        _BIMS = {"1º Bim (Jan–Fev)": MESES_ORDEM[0:2], "2º Bim (Mar–Abr)": MESES_ORDEM[2:4],
                 "3º Bim (Mai–Jun)": MESES_ORDEM[4:6], "4º Bim (Jul–Ago)": MESES_ORDEM[6:8],
                 "5º Bim (Set–Out)": MESES_ORDEM[8:10], "6º Bim (Nov–Dez)": MESES_ORDEM[10:12]}
        _sel_per = _BIMS[st.sidebar.selectbox("Bimestre:", list(_BIMS.keys()), key="per_bim_sau")]
    elif _per_modo == "Semestre":
        _SEMS = {"1º Semestre (Jan–Jun)": MESES_ORDEM[0:6], "2º Semestre (Jul–Dez)": MESES_ORDEM[6:12]}
        _sel_per = _SEMS[st.sidebar.selectbox("Semestre:", list(_SEMS.keys()), key="per_sem_sau")]
    elif _per_modo == "Personalizado (de–até)":
        _opts = _mdetect if _mdetect else list(MESES_ORDEM)
        _de  = st.sidebar.selectbox("De:",  _opts, index=0, key="per_de_sau")
        _ate = st.sidebar.selectbox("Até:", _opts, index=len(_opts)-1, key="per_ate_sau")
        _i0, _i1 = MESES_ORDEM.index(_de), MESES_ORDEM.index(_ate)
        if _i0 > _i1: _i0, _i1 = _i1, _i0
        _sel_per = MESES_ORDEM[_i0:_i1+1]
    if _sel_per is not None:
        _filtrado = [m for m in _mdetect if m in _sel_per]
        if _filtrado:
            meses_disp = _filtrado
            st.sidebar.caption("📊 Exibindo: " + _filtrado[0] + " → " + _filtrado[-1])
        else:
            st.sidebar.caption("Sem lançamentos nesse período — exibindo tudo.")
    st.sidebar.markdown("---")

    # ── RELATÓRIO PDF (regra geral iG2P) ──────────────────────────────────────
    try:
        _mun_rel = os.path.splitext(os.path.basename(__file__))[0].replace('_Saúde', '').replace('_', ' ')
    except NameError:
        _mun_rel = "Município"
    try:
        if '_pdf_saude_bytes' not in st.session_state:
            st.session_state['_pdf_saude_bytes'] = _pdf_relatorio_saude(
                _dados_relatorio_saude(df_raw, df_r, df_df, df_rv, meses_disp), _mun_rel)
        st.sidebar.download_button(
            "📄 Gerar Relatório (PDF)",
            data=st.session_state['_pdf_saude_bytes'],
            file_name=f"Relatorio_Saude_{_mun_rel}.pdf",
            mime="application/pdf", use_container_width=True)
    except Exception:
        st.sidebar.caption("Relatório indisponível no momento.")

    cols_liq = [f"{m}_Liq" for m in meses_disp if f"{m}_Liq" in df_raw.columns]
    cats = sorted(df_raw['Categoria'].dropna().unique())

    if 'modo' not in st.session_state:
        st.session_state.modo = 'Visão Macro'

    # ── ATUALIZAR DADOS (busca a última versão das planilhas) ─────────────────
    st.sidebar.markdown("---")
    if st.sidebar.button("🔄 Atualizar dados", use_container_width=True,
                         help="Busca agora as últimas alterações feitas nas planilhas."):
        st.cache_data.clear()
        st.rerun()

    st.sidebar.header("🧭 Navegação")
    if st.sidebar.button("🌐 Visão Macro", use_container_width=True,
                         type=("primary" if st.session_state.modo == 'Visão Macro' else "secondary")):
        st.session_state.modo = 'Visão Macro'
        st.rerun()
    if st.sidebar.button("📚 Investimento por Categoria", use_container_width=True,
                         type=("primary" if st.session_state.modo == '__investimento__' else "secondary")):
        st.session_state.modo = '__investimento__'
        st.rerun()

    st.sidebar.write("Análise por Categoria:")
    for c in cats:
        if st.sidebar.button(c, use_container_width=True, key=f"cat_{c}",
                             type=("primary" if st.session_state.modo == c else "secondary")):
            st.session_state.modo = c
            st.rerun()

    # ── Sidebar universal iG2P (logo como botão Home) ─────────────────────────
    # ── FOCO NO TOPO ao trocar de setor/categoria (regra universal iG2P) ──
    _ig2p_foco = f"{st.session_state.get('setor','')}|{st.session_state.get('modo','')}"
    if st.session_state.get('_ig2p_foco') != _ig2p_foco:
        st.session_state['_ig2p_foco'] = _ig2p_foco
        _html_iframe(
            "<script>(function(){try{"
            "var w=window.parent,d=w.document;"
            "var sels=['section.main','[data-testid=\"stMain\"]',"
            "'[data-testid=\"stAppViewContainer\"]','[data-testid=\"stMainBlockContainer\"]'];"
            "function top(){try{w.scrollTo(0,0);}catch(e){}"
            "sels.forEach(function(s){var el=d.querySelector(s);if(el)el.scrollTop=0;});}"
            "top();setTimeout(top,60);setTimeout(top,200);"
            "}catch(e){}})()</script>", height=0)

    import base64 as _b64

    def _ler_logo(nome_arquivo):
        candidatos = [f"Logos/{nome_arquivo}", f"../Logos/{nome_arquivo}"]
        try:
            d = os.path.dirname(__file__)
            candidatos += [os.path.join(d, "Logos", nome_arquivo),
                           os.path.join(d, "..", "Logos", nome_arquivo)]
        except NameError:
            pass
        for p in candidatos:
            if os.path.exists(p):
                with open(p, "rb") as _f:
                    return "data:image/png;base64," + _b64.b64encode(_f.read()).decode()
        return ""

    def _js_sidebar_universal(logo_escuro, logo_claro):
        return (
            "<script>(function(){"
            'var LE="' + logo_escuro + '";'
            'var LC="' + logo_claro  + '";'
            "function dE(){try{"
            "var bg=window.parent.getComputedStyle(window.parent.document.body).backgroundColor;"
            "if(!bg||bg===\"rgba(0,0,0,0)\")return true;"
            "var v=bg.match(/[0-9]+/g).map(Number);return v[0]<128;"
            "}catch(e){return true;}}"
            "var _p=(window.parent.location.pathname||'').toLowerCase();"
            "var _home=_p==='/'||_p.indexOf('/home')!==-1;"
            "var _edu=!_home&&_p.indexOf('educa')!==-1;"
            "var _sau=!_home&&!_edu;"
            "var _busy=false;"
            "function run(){"
            "if(_busy)return;_busy=true;"
            "try{"
            "var doc=window.parent.document;"
            "var nav=doc.querySelector('[data-testid=\"stSidebarNav\"]');"
            "if(!nav){_busy=false;return;}"
            "nav.querySelectorAll('li').forEach(function(it){"
            "var txt=it.textContent;"
            "var temEduca=txt.indexOf('Educa')!==-1;"
            "var ocultar=false;"
            "if(_edu&&!temEduca){"
            "var _a=it.querySelector('a');"
            "var _h=_a&&((_a.href||'').toLowerCase().indexOf('/home')!==-1||txt.trim().toLowerCase()==='home');"
            "if(!_h)ocultar=true;"
            "}"
            "if(_sau&&(temEduca||txt.indexOf('Conv\u00ea')!==-1))ocultar=true;"
            "if(ocultar){it.style.setProperty('display','none','important');return;}"
            "it.style.removeProperty('display');"
            "var lk=it.querySelector('a');if(!lk)return;"
            "var sp=lk.querySelector('span');"
            "var tx=(sp?sp.textContent:lk.textContent).trim();"
            "var isH=tx==='Home'||tx.toLowerCase()==='home'||"
            "(lk.href&&lk.href.toLowerCase().indexOf('/home')!==-1);"
            "if(!isH)return;"
            "if(lk.querySelector('img.ig2p-logo-sidebar'))return;"
            "if(sp)sp.style.setProperty('display','none','important');"
            "lk.style.setProperty('padding','4px 8px 4px 8px','important');"
            "lk.style.setProperty('display','flex','important');"
            "lk.style.setProperty('align-items','center','important');"
            "lk.style.setProperty('background','transparent','important');"
            "var img=doc.createElement('img');"
            "img.src=dE()?LE:LC;"
            "img.className='ig2p-logo-sidebar';"
            "img.style.cssText='width:130px;height:auto;cursor:pointer;display:block;margin:4px 0;';"
            "var mq=window.parent.matchMedia('(prefers-color-scheme:dark)');"
            "function up(){img.src=dE()?LE:LC;}"
            "if(mq.addEventListener)mq.addEventListener('change',up);"
            "else if(mq.addListener)mq.addListener(up);"
            "lk.insertBefore(img,lk.firstChild);"
            "});"
            "}catch(e){}"
            "_busy=false;}"
            "run();setTimeout(run,50);setTimeout(run,200);setTimeout(run,600);"
            "try{"
            "if(window.parent._ig2p_obs)window.parent._ig2p_obs.disconnect();"
            "var _ob=new MutationObserver(function(){run();});"
            "_ob.observe(window.parent.document.body,{childList:true,subtree:true});"
            "window.parent._ig2p_obs=_ob;"
            "}catch(e){}"
            "})()</script>"
        )

    _html_iframe(
        _js_sidebar_universal(
            _ler_logo("LOGOTIPO IG2P - OFICIAL - BRANCO.png"),
            _ler_logo("LOGOTIPO IG2P - OFICIAL.png"),
        ),
        height=0,
    )

    # ══════════════════════════════════════════════════════════════════════════
    # HELPERS DE RENDERIZAÇÃO
    # ══════════════════════════════════════════════════════════════════════════
    def _fig_evolucao(dados, cor="#00CC96"):
        linhas = [{"Mês": m, "Valor": dados[f"{m}_Liq"].sum() if f"{m}_Liq" in dados.columns else 0.0}
                  for m in meses_disp]
        dfm = pd.DataFrame(linhas)
        fig = px.line(dfm, x='Mês', y='Valor', markers=True, color_discrete_sequence=[cor])
        fig.update_layout(yaxis_tickprefix='R$ ', yaxis_tickformat=',.2f', separators=',.',
                          xaxis_title=None, yaxis_title="Liquidado (R$)", height=360)
        fig.update_traces(hovertemplate="<b>%{x}</b><br>Liquidado: R$ %{y:,.2f}<extra></extra>")
        return fig

    def render_execucao_orcamentaria(dados):
        orcado = dados['Orçado'].sum()
        liq    = dados['Total_Liq'].sum() if 'Total_Liq' in dados.columns else 0.0
        saldo  = dados['Saldo'].sum()
        perc   = (liq / orcado * 100) if orcado > 0 else 0.0
        c1, c2, c3, c4 = st.columns(4)
        with c1: st.metric("Previsão (Orçado)",     formar_real(orcado))
        with c2: st.metric("Saldo Disponível",       formar_real(saldo))
        with c3: st.metric("Executado (Liquidado)",  formar_real(liq))
        with c4: st.metric("% de Execução",          f"{perc:.2f}%".replace('.',','))
        st.subheader("📈 Evolução Mensal da Execução (Liquidado)")
        st.plotly_chart(_fig_evolucao(dados), use_container_width=True, config=CONFIG_PT)

    def render_custeio_capital_pizza(dados):
        st.subheader("📊 Custeio × Capital")
        tc = dados[dados['Natureza']=='Custeio (Manut.)']['Total_Liq'].sum()
        tk = dados[dados['Natureza']=='Capital (Invest.)']['Total_Liq'].sum()
        m1, m2 = st.columns(2)
        with m1: st.metric("Total Custeio", formar_real(tc))
        with m2: st.metric("Total Capital", formar_real(tk))
        dn = pd.DataFrame({'Natureza':['Custeio (Manut.)','Capital (Invest.)'],'Total_Liq':[tc,tk]})
        fig = px.pie(dn, values='Total_Liq', names='Natureza', hole=.4, color='Natureza',
                     color_discrete_map={'Custeio (Manut.)':'#00CC96','Capital (Invest.)':'#EF553B'})
        fig.update_layout(margin=dict(t=40,b=40,l=20,r=20), height=420, separators=',.',
                          legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.05,
                                      font=dict(size=15)))
        fig.update_traces(textinfo='percent', textposition='inside',
                          hovertemplate="<b>%{label}</b><br>Valor: R$ %{value:,.2f}<extra></extra>")
        _, cc, _ = st.columns([1,2,1])
        with cc: st.plotly_chart(fig, use_container_width=True, config=CONFIG_PT)

    def _pizza_por_fonte(dados_valor_por_fonte, titulo_total):
        """Recebe DataFrame com colunas ['Fonte','Valor'] (>0) e desenha pizza por fonte."""
        d = dados_valor_por_fonte[dados_valor_por_fonte['Valor'] > 0].copy()
        total = d['Valor'].sum()
        st.metric(titulo_total, formar_real(total))
        if d.empty:
            st.info("Sem valores para exibir neste recorte.")
            return
        d['Rotulo'] = d['Fonte'].apply(fonte_lbl)
        fig = px.pie(d, values='Valor', names='Rotulo', hole=.35, color='Fonte',
                     color_discrete_map={f: cor_fonte(f) for f in d['Fonte']})
        fig.update_traces(textinfo='percent', textposition='outside', pull=[0.03]*len(d),
                          hovertemplate="<b>%{label}</b><br>R$ %{value:,.2f}<br>%{percent}<extra></extra>")
        fig.update_layout(height=460, separators=',.', margin=dict(t=30,b=30,l=20,r=170),
                          legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02,
                                      font=dict(size=13)))
        _, cc, _ = st.columns([0.5,3,0.6])
        with cc: st.plotly_chart(fig, use_container_width=True, config=CONFIG_PT)

    def render_folha(dados, titulo="💼 Folha de Pagamento"):
        st.subheader(titulo)
        folha = dados[dados['Elemento'].isin(FOLHA_ELEMENTOS)]
        gf = folha.groupby('Fonte')['Total_Liq'].sum().reset_index().rename(columns={'Total_Liq':'Valor'})
        # total ACIMA + pizza por fonte
        _pizza_por_fonte(gf, "Folha Total (Liquidada)")
        # Evolução mensal da folha (formato Educação)
        st.markdown("**📈 Evolução Mensal da Folha (Liquidado)**")
        st.plotly_chart(_fig_evolucao(folha, cor="#1a7a4a"), use_container_width=True, config=CONFIG_PT)

    def render_total_investido_fonte(dados, titulo="🏥 Total Investido em Saúde — por Fonte"):
        st.subheader(titulo)
        gf = dados.groupby('Fonte')['Total_Liq'].sum().reset_index().rename(columns={'Total_Liq':'Valor'})
        _pizza_por_fonte(gf, "Total Investido (Liquidado)")

    def render_detalhamento_elemento(dados, key_prefix="cat"):
        st.markdown('<div id="foco_grafico"></div>', unsafe_allow_html=True)
        st.subheader("📦 Detalhamento por Elemento")
        elementos = sorted([str(x) for x in dados['Elemento'].dropna().unique()])
        if not elementos:
            st.info("Sem elementos para exibir.")
            return
        st.write("Selecione um elemento para visualizar o detalhamento das fichas:")
        colsb = st.columns(4)
        for i, ele in enumerate(elementos):
            with colsb[i % 4]:
                if st.button(ele, use_container_width=True, key=f"{key_prefix}_ele_{i}"):
                    st.session_state['elemento_ativo'] = ele
                    st.rerun()

        if 'elemento_ativo' in st.session_state and st.session_state['elemento_ativo'] in elementos:
            ele = st.session_state['elemento_ativo']
            sid = random()
            _html_iframe(f"""<script id="scroll_{sid}">
                var s=()=>{{const el=window.parent.document.querySelector('.st-key-detalhamento-fichas');
                if(el)el.scrollIntoView({{behavior:"smooth",block:"center"}});}};setTimeout(s,150);
                </script>""", height=0)
            dd = dados[dados['Elemento'] == ele].sort_values('Orçado', ascending=False).copy()
            st.subheader(f"📊 Detalhamento de Fichas: {ele}")
            st.metric("Total Orçado do Elemento", formar_real(dd['Orçado'].sum()))
            dd['FonteLabel'] = dd['Fonte'].apply(fonte_lbl)
            # cores diferentes por fonte
            fig = px.bar(dd, x='Ficha', y='Orçado', color='FonteLabel',
                         color_discrete_map={fonte_lbl(f): cor_fonte(f)
                                             for f in dd['Fonte'].unique()},
                         custom_data=['Categoria','FonteLabel'])
            fig.update_traces(
                hovertemplate=("<b>Categoria:</b> %{customdata[0]}<br>"
                               "<b>%{customdata[1]}</b><br>"
                               "<b>Valor:</b> R$ %{y:,.2f}<extra></extra>"),
                text=dd['Orçado'].apply(formar_real), textposition='outside', cliponaxis=False)
            fig.update_layout(xaxis_type='category', height=540, separators=',.',
                              yaxis=dict(range=[0, dd['Orçado'].max()*1.30]),
                              legend_title="Fonte", barmode='group',
                              margin=dict(t=80,b=50,l=50,r=50))
            st.plotly_chart(fig, use_container_width=True, theme=None,
                            config=CONFIG_PT, key="detalhamento-fichas")
            if st.button("⬅️ Voltar para Visão Geral", key=f"{key_prefix}_voltar"):
                del st.session_state['elemento_ativo']
                st.rerun()

    # ══════════════════════════════════════════════════════════════════════════
    # BLOCO 15% (com toggle Mensal/Acumulado) — usado na Visão Macro
    # ══════════════════════════════════════════════════════════════════════════
    def bloco_15():
        st.subheader("🎯 Aplicação Mínima em Saúde (15%)")
        if df_r is None or df_df is None:
            st.info("Dados de receitas/despesas indisponíveis para o cálculo dos 15%.")
            return
        base_df = df_r[df_r['Categoria'].isin(['Impostos','Cota-Parte'])]
        base_tot = soma_cols(base_df, meses_disp)
        desp_df = df_df[(df_df['Fonte'] == '1500') & (df_df['Tipo'] == 'Liquidado')]
        desp_tot = soma_cols(desp_df, meses_disp)
        indice = (desp_tot / base_tot * 100) if base_tot > 0 else 0.0
        meta_valor = base_tot * 0.15

        # Totais ACIMA do gráfico
        k1, k2, k3, k4 = st.columns(4)
        with k1: st.metric("Receita Base (Impostos + Cota-Parte)", formar_real(base_tot))
        with k2: st.metric("Aplicado em Saúde (Fonte 1500)", formar_real(desp_tot))
        with k3: st.metric("Índice de Aplicação", f"{indice:.2f}%".replace('.',','),
                           delta=f"{indice-15:.2f} p.p. vs 15%".replace('.',','),
                           delta_color=("normal" if indice >= 15 else "inverse"))
        with k4: st.metric("Mínimo Exigido (15%)", formar_real(meta_valor))

        view = st.segmented_control("Visualização:", ["Mensal","Acumulado"],
                                    default="Mensal", key="view_15")

        if view == "Acumulado":
            fig = go.Figure()
            fig.add_bar(x=["Receita Base"], y=[base_tot], name="Receita Base",
                        marker_color=C_15_RECEITA, text=[formar_real(base_tot)],
                        textposition='outside',
                        hovertemplate="Receita Base: R$ %{y:,.2f}<extra></extra>")
            fig.add_bar(x=["Aplicado (Fonte 1500)"], y=[desp_tot], name="Aplicado em Saúde",
                        marker_color=C_15_DESPESA, text=[formar_real(desp_tot)],
                        textposition='outside',
                        hovertemplate="Aplicado: R$ %{y:,.2f}<extra></extra>")
            fig.add_hline(y=meta_valor, line_dash="dash", line_color=C_META,
                          annotation_text=f"Meta 15% = {formar_real(meta_valor)}",
                          annotation_position="top left")
            fig.update_layout(height=430, separators=',.', barmode='group',
                              yaxis=dict(showticklabels=False), showlegend=True,
                              legend=dict(orientation="h", yanchor="bottom", y=-0.18,
                                          xanchor="center", x=0.5), margin=dict(t=40,b=40))
        else:
            linhas = []
            for m in meses_disp:
                r_m = base_df[m].sum() if m in base_df.columns else 0.0
                d_m = desp_df[m].sum() if m in desp_df.columns else 0.0
                linhas += [
                    {"Mês": m, "Tipo": "Receita (Impostos + Cota-Parte)", "Valor": r_m},
                    {"Mês": m, "Tipo": "Despesa (Fonte 1500)", "Valor": d_m},
                ]
            dfm = pd.DataFrame(linhas)
            fig = px.bar(dfm, x='Mês', y='Valor', color='Tipo', barmode='group',
                         color_discrete_map={"Receita (Impostos + Cota-Parte)": C_15_RECEITA,
                                             "Despesa (Fonte 1500)": C_15_DESPESA},
                         text='Valor', category_orders={"Mês": meses_disp})
            fig.update_traces(texttemplate="R$ %{y:,.0f}", textposition='inside',
                              insidetextanchor='middle',
                              hovertemplate="<b>%{x} — %{data.name}</b><br>R$ %{y:,.2f}<extra></extra>")
            # REGRA UNIVERSAL: linha de meta via shapes, _OFFSET=0.22
            df_lin = dfm[dfm['Tipo'] == "Receita (Impostos + Cota-Parte)"].reset_index(drop=True)
            df_lin['Meta'] = df_lin['Valor'] * 0.15
            _OFF = 0.22
            shapes = []
            for i, row in df_lin.iterrows():
                mt = row['Meta']
                shapes.append(dict(type='line', xref='x', yref='y', x0=i-_OFF, x1=i+_OFF,
                                   y0=mt, y1=mt, line=dict(color=C_META, dash='dash', width=2)))
                if i < len(df_lin)-1:
                    shapes.append(dict(type='line', xref='x', yref='y', x0=i+_OFF, x1=i+1-_OFF,
                                       y0=mt, y1=df_lin.loc[i+1,'Meta'],
                                       line=dict(color=C_META, dash='dash', width=2)))
            fig.update_layout(shapes=shapes)
            fig.add_trace(go.Scatter(x=[None], y=[None], mode='lines', name='Meta 15% (Mensal)',
                                     line=dict(color=C_META, dash='dash', width=2)))
            fig.update_layout(separators=',.', yaxis=dict(showticklabels=False), showlegend=True,
                              legend=dict(orientation="h", yanchor="bottom", y=-0.22,
                                          xanchor="center", x=0.5), height=450)
        st.plotly_chart(fig, use_container_width=True, config=CONFIG_PT)
        if indice >= 15:
            st.success(f"✔ Aplicação de {indice:.2f}% em ASPS, acima do mínimo constitucional de "
                       "15%.".replace('.',',',1))
        else:
            st.error(f"⚠ Aplicação de {indice:.2f}%, abaixo do mínimo constitucional de "
                     "15% (ASPS).".replace('.',',',1))
        st.caption("Base legal: CF/1988 art. 198 §2º e §3º; LC nº 141/2012. Cálculo sem deduções.")

    # ══════════════════════════════════════════════════════════════════════════
    # BLOCO Vinculados: Receitas × Despesas por categoria (Mensal/Acumulado)
    # ══════════════════════════════════════════════════════════════════════════
    def _desp_grupo_cat(cat, fontes, cols):
        sub = df_raw[(df_raw['Categoria'] == cat) & (df_raw['Fonte'].isin(fontes))]
        return soma_cols(sub, cols)

    def bloco_vinc_macro():
        st.subheader("🔄 Recursos Vinculados — Receitas × Despesas por Categoria (Acumulado)")
        if df_rv is None:
            st.info("Arquivo de Receitas Vinculadas (Delfinópolis_RV) indisponível.")
            return
        # União: categorias das fichas + categorias que só existem no RV
        # (ex.: 'Atenção Psicossocial' tem receita vinculada mas não tem ficha).
        cats_rv = list(cats)
        for _c in sorted(df_rv['Categoria'].astype(str).str.strip().unique()):
            if _c and _c != 'nan' and _c not in cats_rv:
                cats_rv.append(_c)
        rec_meses = [m for m in meses_disp if m in df_rv.columns]

        tot_rec = tot_desp = 0.0
        fig = go.Figure()
        # Receitas (empilhadas por origem) — offsetgroup 'Receita'
        for origem, cor in [('Federal', C_FEDERAL), ('Estadual', C_ESTADUAL)]:
            vals = []
            for c in cats_rv:
                sub = df_rv[(df_rv['Categoria'] == c) & (df_rv['Origem'] == origem)]
                vals.append(soma_cols(sub, rec_meses))
            tot_rec += sum(vals)
            if sum(vals) > 0:
                fig.add_bar(x=cats_rv, y=vals, name=f"Receita {origem}", marker_color=cor,
                            offsetgroup='Receita', legendgroup='rec',
                            hovertemplate=f"<b>%{{x}}</b><br>Receita {origem}: R$ %{{y:,.2f}}<extra></extra>")
        # Despesas (empilhadas por grupo de fonte) — offsetgroup 'Despesa'
        for grupo, fontes in GRUPO_DESP_VINC.items():
            vals = [_desp_grupo_cat(c, fontes, cols_liq) for c in cats_rv]
            tot_desp += sum(vals)
            if sum(vals) > 0:
                fig.add_bar(x=cats_rv, y=vals, name=f"Despesa {grupo}",
                            marker_color=COR_GRUPO_DESP[grupo], offsetgroup='Despesa',
                            legendgroup='desp',
                            hovertemplate=f"<b>%{{x}}</b><br>Despesa {grupo}: R$ %{{y:,.2f}}<extra></extra>")

        c1, c2, c3 = st.columns(3)
        with c1: st.metric("Total Receitas Vinculadas", formar_real(tot_rec))
        with c2: st.metric("Total Despesas Vinculadas", formar_real(tot_desp))
        with c3: st.metric("Saldo (Rec. − Desp.)", formar_real(tot_rec - tot_desp))
        fig.update_layout(barmode='relative', height=470, separators=',.',
                          yaxis_title="R$", xaxis_title="",
                          legend_title="Receitas (azul) × Despesas (fonte)",
                          legend=dict(orientation="h", yanchor="bottom", y=-0.28,
                                      xanchor="center", x=0.5), margin=dict(t=20,b=40))
        st.plotly_chart(fig, use_container_width=True, config=CONFIG_PT)
        st.caption("Barra à esquerda de cada categoria = **Receitas Vinculadas** (Federal/Estadual); "
                   "à direita = **Despesas executadas** por grupo de fonte "
                   "(Federal Custeio 1600+1604+1605 · Federal Capital 1601 · Estadual 1621).")

    def bloco_vinc_categoria(cat):
        st.subheader("🔄 Receitas × Despesas — Recursos Vinculados (Federal/Estadual)")
        rv_cat = df_rv[df_rv['Categoria'] == cat] if df_rv is not None else None
        desp_vinc = df_raw[(df_raw['Categoria'] == cat) &
                           (~df_raw['Fonte'].isin(FONTES_PROPRIAS))]
        rec_meses = [m for m in meses_disp if df_rv is not None and m in df_rv.columns]
        fontes_desp = sorted(f for f in desp_vinc['Fonte'].dropna().astype(str).unique()
                             if f and f != 'nan') if not desp_vinc.empty else []

        tot_rec = soma_cols(rv_cat, rec_meses) if rv_cat is not None else 0.0
        tot_desp = desp_vinc[cols_liq].sum().sum() if not desp_vinc.empty else 0.0
        if tot_rec <= 0 and tot_desp <= 0:
            st.info("Sem receitas vinculadas ou despesas de fontes vinculadas para esta categoria.")
            return

        # ── Filtro Federal/Estadual — botão alterna: clicar no ativo desativa ──
        _kf = f"filtro_vinc_{remover_acentos(cat)}"
        if _kf not in st.session_state:
            st.session_state[_kf] = None
        filtro = st.session_state[_kf]

        # Receitas (por Origem) e despesas (por origem da fonte) seguem o filtro
        origens_plot = ['Federal', 'Estadual'] if filtro is None else [filtro]
        fontes_plot  = ([f for f in fontes_desp if origem_da_fonte(f) == filtro]
                        if filtro else fontes_desp)

        rv_plot   = rv_cat[rv_cat['Origem'].isin(origens_plot)] if rv_cat is not None else None
        desp_plot = (desp_vinc[desp_vinc['Fonte'].isin(fontes_plot)]
                     if not desp_vinc.empty else desp_vinc)

        # Totais ACIMA do gráfico (refletem o filtro ativo)
        tot_rec  = soma_cols(rv_plot, rec_meses) if rv_plot is not None else 0.0
        tot_desp = desp_plot[cols_liq].sum().sum() if not desp_plot.empty else 0.0

        c1, c2, c3 = st.columns(3)
        with c1: st.metric("Total Receitas Vinculadas", formar_real(tot_rec))
        with c2: st.metric("Total Despesas Vinculadas", formar_real(tot_desp))
        with c3: st.metric("Saldo (Rec. − Desp.)", formar_real(tot_rec - tot_desp))

        view = st.segmented_control("Visualização:", ["Mensal","Acumulado"],
                                    default="Mensal", key=f"view_vinc_{remover_acentos(cat)}")

        st.caption("Origem (clique novamente para voltar à visualização padrão):")
        fb1, fb2, _fb = st.columns([1, 1, 6])
        with fb1:
            if st.button("Federal", key=f"{_kf}_fed", use_container_width=True,
                         type=("primary" if filtro == 'Federal' else "secondary")):
                st.session_state[_kf] = None if filtro == 'Federal' else 'Federal'
                st.rerun()
        with fb2:
            if st.button("Estadual", key=f"{_kf}_est", use_container_width=True,
                         type=("primary" if filtro == 'Estadual' else "secondary")):
                st.session_state[_kf] = None if filtro == 'Estadual' else 'Estadual'
                st.rerun()

        fig = go.Figure()
        if view == "Mensal":
            for origem, cor in [('Federal', C_FEDERAL), ('Estadual', C_ESTADUAL)]:
                if rv_cat is None or origem not in origens_plot: continue
                sub = rv_cat[rv_cat['Origem'] == origem]
                vals = [sub[m].sum() if m in sub.columns else 0.0 for m in meses_disp]
                if sum(vals) > 0:
                    fig.add_bar(x=meses_disp, y=vals, name=f"Receita {origem}", marker_color=cor,
                                offsetgroup='Receita', legendgroup='rec',
                                hovertemplate=f"<b>%{{x}}</b><br>Receita {origem}: R$ %{{y:,.2f}}<extra></extra>")
            for fonte in fontes_plot:
                sub = desp_vinc[desp_vinc['Fonte'] == fonte]
                vals = [sub[f"{m}_Liq"].sum() if f"{m}_Liq" in sub.columns else 0.0 for m in meses_disp]
                if sum(vals) > 0:
                    fig.add_bar(x=meses_disp, y=vals, name=fonte_lbl(fonte),
                                marker_color=cor_fonte(fonte), offsetgroup='Despesa', legendgroup='desp',
                                hovertemplate=f"<b>%{{x}}</b><br>{fonte_lbl(fonte)} (desp.): R$ %{{y:,.2f}}<extra></extra>")
            xlabel = ""
        else:
            for origem, cor in [('Federal', C_FEDERAL), ('Estadual', C_ESTADUAL)]:
                if rv_cat is None or origem not in origens_plot: continue
                v = soma_cols(rv_cat[rv_cat['Origem'] == origem], rec_meses)
                if v > 0:
                    fig.add_bar(x=["Vinculados"], y=[v], name=f"Receita {origem}", marker_color=cor,
                                offsetgroup='Receita', legendgroup='rec',
                                hovertemplate=f"Receita {origem}: R$ %{{y:,.2f}}<extra></extra>")
            for fonte in fontes_plot:
                v = desp_vinc[desp_vinc['Fonte'] == fonte][cols_liq].sum().sum()
                if v > 0:
                    fig.add_bar(x=["Vinculados"], y=[v], name=fonte_lbl(fonte),
                                marker_color=cor_fonte(fonte), offsetgroup='Despesa', legendgroup='desp',
                                hovertemplate=f"{fonte_lbl(fonte)} (desp.): R$ %{{y:,.2f}}<extra></extra>")
            xlabel = ""
        if not fig.data:
            st.info("Sem valores para a origem selecionada nesta categoria.")
            return
        # Legenda à DIREITA (padrão dos demais gráficos) + margem reservada
        fig.update_layout(barmode='relative', height=470, separators=',.', yaxis_title="R$",
                          xaxis_title=xlabel, legend_title="Receitas × Despesas",
                          legend=dict(orientation="v", yanchor="middle", y=0.5,
                                      xanchor="left", x=1.02, font=dict(size=12)),
                          margin=dict(t=20, b=40, l=20, r=240))
        st.plotly_chart(fig, use_container_width=True, config=CONFIG_PT)
        st.caption("Receitas em azul (Federal/Estadual) · Despesas por fonte (cores específicas). "
                   "Fontes próprias (1500/2501) não entram no comparativo de vinculados.")

    # ══════════════════════════════════════════════════════════════════════════
    # MODO 1 — VISÃO MACRO
    # ══════════════════════════════════════════════════════════════════════════
    if st.session_state.modo == 'Visão Macro':
        st.title("🌐 Delfinópolis — Saúde · Visão Macro")
        st.caption(f"Análise dos recursos totais da Saúde ({meses_disp[0]}–{meses_disp[-1]}).")
        st.markdown("---")

        render_execucao_orcamentaria(df_raw)
        st.markdown("---")

        bloco_15()
        st.markdown("---")

        bloco_vinc_macro()
        st.markdown("---")

        # Custeio × Capital por fonte (totais ACIMA)
        st.subheader("📊 Custeio × Capital — Detalhado por Fonte")
        tc = df_raw[df_raw['Natureza']=='Custeio (Manut.)']['Total_Liq'].sum()
        tk = df_raw[df_raw['Natureza']=='Capital (Invest.)']['Total_Liq'].sum()
        cc1, cc2 = st.columns(2)
        with cc1: st.metric("Total Custeio", formar_real(tc))
        with cc2: st.metric("Total Capital", formar_real(tk))
        gcc = df_raw.groupby(['Fonte','Natureza'])['Total_Liq'].sum().reset_index()
        gcc = gcc[gcc['Total_Liq'] > 0].copy()
        gcc['Rotulo'] = gcc['Fonte'].apply(fonte_lbl)
        ordem_f = (gcc.groupby('Rotulo')['Total_Liq'].sum().sort_values(ascending=False).index.tolist())
        fig_cc = px.bar(gcc, x='Rotulo', y='Total_Liq', color='Natureza', barmode='stack',
                        category_orders={'Rotulo': ordem_f},
                        color_discrete_map={'Custeio (Manut.)':'#00CC96','Capital (Invest.)':'#EF553B'})
        fig_cc.update_traces(hovertemplate="<b>%{x}</b><br><b>%{data.name}:</b> R$ %{y:,.2f}<extra></extra>")
        fig_cc.update_layout(height=440, separators=',.', xaxis_title="", yaxis_title="Liquidado (R$)",
                             legend_title="Natureza", margin=dict(t=20,b=90), xaxis_tickangle=-25)
        st.plotly_chart(fig_cc, use_container_width=True, config=CONFIG_PT)
        st.markdown("---")

        # Folha (pizza + evolução) — ANTES do Total Investido
        render_folha(df_raw, "💼 Folha de Pagamento Total")
        st.markdown("---")

        # Total Investido em Saúde por CATEGORIA (pizza) — total ACIMA
        st.subheader(f"🏥 Total Investido em Saúde — por Categoria ({meses_disp[0]}–{meses_disp[-1]})")
        NOME_CAT = {'Secretaria':'Administração','Atenção Primária':'Atenção Primária',
                    'MAC':'Ambulatorial e Especialidades (MAC)','Farmácia':'Farmácia',
                    'Vigilância':'Vigilância'}
        CORES_CAT = {'Administração':'#f39c12','Atenção Primária':'#4A90D9',
                     'Ambulatorial e Especialidades (MAC)':'#1a3a6b','Farmácia':'#27ae60',
                     'Vigilância':'#e74c3c'}
        dpz = df_raw.groupby('Categoria')['Total_Liq'].sum().reset_index()
        dpz['Label'] = dpz['Categoria'].map(NOME_CAT).fillna(dpz['Categoria'])
        dpz = dpz[dpz['Total_Liq'] > 0]
        st.metric("Total Liquidado", formar_real(dpz['Total_Liq'].sum()))
        fig_pz = px.pie(dpz, values='Total_Liq', names='Label', hole=0.0,
                        color='Label', color_discrete_map=CORES_CAT)
        fig_pz.update_traces(textinfo='label+percent', textposition='outside', pull=[0.03]*len(dpz),
                             hovertemplate=("<b>%{label}</b><br>Liquidado: <b>R$ %{value:,.2f}</b><br>"
                                            "Participação: <b>%{percent}</b><extra></extra>"),
                             hoverlabel=dict(bgcolor="rgba(0,0,0,0.85)", font_size=13, font_color="white"))
        fig_pz.update_layout(showlegend=True, height=470, separators=',.',
                             legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02,
                                         font=dict(size=13), itemclick="toggle", itemdoubleclick="toggleothers"),
                             margin=dict(t=30,b=40,l=20,r=180))
        _, cpz, _ = st.columns([0.5,3,0.5])
        with cpz: st.plotly_chart(fig_pz, use_container_width=True, config=CONFIG_PT)
        st.markdown("---")

        # Total Investido em Saúde por FONTE (pizza) — item novo
        render_total_investido_fonte(df_raw, "🏥 Total Investido em Saúde — por Fonte")

    # ══════════════════════════════════════════════════════════════════════════
    # MODO — INVESTIMENTO POR CATEGORIA (interativo: categoria + fontes + mensal)
    #   Categoria = coluna 'Categoria'; se o Elemento terminar em "Hospital",
    #   o item entra como categoria 'Hospital' (marcador no fim do Elemento).
    # ══════════════════════════════════════════════════════════════════════════
    elif st.session_state.modo == '__investimento__':
        st.title("📚 Delfinópolis — Saúde · Investimento por Categoria")
        st.caption(f"Quanto foi investido em cada categoria ({meses_disp[0]}–{meses_disp[-1]}). "
                   "Itens cujo Elemento termina em 'Hospital' entram na categoria 'Hospital'.")
        st.markdown("---")
        _HOVER = dict(bgcolor="rgba(0,0,0,0.9)", font_size=13, font_color="white")
        _liqS = [c for c in cols_liq]
        if not _liqS or 'Categoria' not in df_raw.columns or 'Elemento' not in df_raw.columns:
            st.info("Dados insuficientes (colunas Categoria/Elemento ou meses) para esta análise.")
        else:
            _dfi = df_raw.copy()
            def _cat_inv(_row):
                _e = str(_row['Elemento']).strip().lower()
                if _e.endswith('hospital'):
                    return 'Hospital'
                return str(_row['Categoria']).strip()
            _dfi['CatInv'] = _dfi.apply(_cat_inv, axis=1)
            _dfi = _dfi[~_dfi['CatInv'].str.lower().isin(['', 'nan', 'none', '<na>'])]
            for _c in _liqS:
                _dfi[_c] = pd.to_numeric(_dfi[_c], errors='coerce').fillna(0.0)
            _dfi['Total'] = _dfi[_liqS].sum(axis=1)
            _catsI = sorted({_v for _v in (str(_x).strip()
                             for _x in _dfi.loc[_dfi['Total'] > 0, 'CatInv'].tolist())
                             if _v and _v.lower() not in ('nan', 'none', '<na>')}, key=str)
            if not _catsI:
                st.info("Sem despesas liquidadas por categoria no período selecionado.")
            else:
                _selI = st.multiselect("Filtrar categorias:", _catsI, default=_catsI,
                                       key="filtro_cat_saude")
                _dff = _dfi[_dfi['CatInv'].isin(_selI)].copy()
                _totI = float(_dff[_liqS].sum().sum())
                _PAL = ['#4A90D9', '#27ae60', '#e74c3c', '#f39c12', '#8e44ad',
                        '#16a085', '#1a3a6b', '#d35400', '#7f8c8d', '#2563eb']
                k1, k2 = st.columns(2)
                with k1: st.metric(f"Total Liquidado ({meses_disp[0][:3]}–{meses_disp[-1][:3]})",
                                   formar_real(_totI))
                with k2: st.metric("Categorias no período", str(len(_catsI)))
                st.markdown("---")

                # Acumulado por categoria — pizza
                st.subheader("🔹 Acumulado por categoria")
                _dpz = _dff.groupby('CatInv')[_liqS].sum().sum(axis=1).reset_index()
                _dpz.columns = ['Categoria', 'Valor']
                _dpz = _dpz[_dpz['Valor'] > 0].sort_values('Valor', ascending=False)
                fig_pzc = px.pie(_dpz, values='Valor', names='Categoria', hole=0.42,
                                 color_discrete_sequence=_PAL)
                fig_pzc.update_traces(textinfo='percent', textposition='inside',
                    domain=dict(x=[0.0, 1.0], y=[0.34, 1.0]),
                    hovertemplate=("<b>%{label}</b><br>Valor: <b>R$ %{value:,.2f}</b><br>"
                                   "Participação: <b>%{percent}</b><extra></extra>"),
                    hoverlabel=_HOVER)
                fig_pzc.update_layout(separators=",.", showlegend=True,
                    legend=dict(orientation="h", yanchor="top", y=0.24, xanchor="center", x=0.5,
                                font=dict(size=11)),
                    height=560, margin=dict(t=30, b=20))
                _, _cp, _ = st.columns([1, 2, 1])
                with _cp:
                    st.plotly_chart(fig_pzc, use_container_width=True, config=CONFIG_PT)

                # Mensal — empilhado por categoria
                st.subheader("🔹 Execução mensal (empilhado por categoria)")
                fig_mc = go.Figure()
                for _i, _ct in enumerate(_dpz['Categoria'].tolist()):
                    _ser = _dff[_dff['CatInv'] == _ct]
                    _ys = [float(_ser[f"{m}_Liq"].sum()) if f"{m}_Liq" in _ser.columns else 0.0
                           for m in meses_disp]
                    if sum(_ys) == 0: continue
                    fig_mc.add_bar(x=meses_disp, y=_ys, name=str(_ct),
                                   marker_color=_PAL[_i % len(_PAL)])
                fig_mc.update_layout(barmode='stack', separators=",.", hoverlabel=_HOVER,
                    yaxis=dict(showticklabels=False), showlegend=True,
                    legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5,
                                font=dict(size=10)),
                    height=470, margin=dict(b=130, t=20))
                fig_mc.update_traces(hovertemplate=(
                    "<b>%{x} — %{data.name}</b><br>Liquidado: <b>R$ %{y:,.2f}</b><extra></extra>"))
                st.plotly_chart(fig_mc, use_container_width=True, config=CONFIG_PT)

                _tabc = _dpz.copy()
                _tabc['Participação'] = (_tabc['Valor'] / _totI * 100).map(lambda v: f"{v:.1f}%") \
                    if _totI > 0 else "—"
                _tabc['Valor'] = _tabc['Valor'].apply(formar_real)
                st.dataframe(_tabc, use_container_width=True, hide_index=True)

                # ── Fontes de investimento (do recorte selecionado) ──
                st.markdown("---")
                if len(_selI) == len(_catsI):
                    _rot = "todas as categorias (visão macro)"
                elif len(_selI) <= 2:
                    _rot = " · ".join(_selI)
                else:
                    _rot = f"{len(_selI)} categorias selecionadas"
                st.subheader("🔹 Fontes de investimento")
                st.caption(f"Recorte atual: **{_rot}**. Mostra de quais fontes veio o investimento "
                           "das categorias selecionadas (selecione uma categoria para ver só as dela).")
                if 'Fonte' not in _dff.columns or _dff.empty:
                    st.info("Sem informação de fonte para o recorte selecionado.")
                else:
                    _fontesS = sorted(
                        {_v for _v in (str(_x).strip() for _x in _dfi['Fonte'].tolist())
                         if _v and _v.lower() not in ('nan', 'none', '<na>')}, key=str)
                    _PALF = ['#2980b9', '#8e44ad', '#e67e22', '#c0392b', '#16a085',
                             '#2c3e50', '#d35400', '#7f8c8d', '#2563eb', '#9b59b6', '#27ae60']
                    _CORF, _pf = {}, 0
                    for _ft in _fontesS:
                        if _ft == '15001':
                            _CORF[_ft] = '#1a7a4a'
                        else:
                            _CORF[_ft] = _PALF[_pf % len(_PALF)]; _pf += 1
                    _dff2 = _dff.copy()
                    _dff2['Fonte'] = _dff2['Fonte'].apply(lambda _v: str(_v).strip())
                    _dff2 = _dff2[~_dff2['Fonte'].str.lower().isin(['', 'nan', 'none', '<na>'])]
                    _dpf = _dff2.groupby('Fonte')[_liqS].sum().sum(axis=1).reset_index()
                    _dpf.columns = ['Fonte', 'Valor']
                    _dpf = _dpf[_dpf['Valor'] > 0].sort_values('Valor', ascending=False)
                    if not len(_dpf):
                        st.info("Sem despesas liquidadas por fonte no recorte selecionado.")
                    else:
                        st.markdown("**Acumulado por fonte**")
                        fig_fpz = px.pie(_dpf, values='Valor', names='Fonte', hole=0.42,
                                         color='Fonte', color_discrete_map=_CORF)
                        fig_fpz.update_traces(textinfo='percent', textposition='inside',
                            domain=dict(x=[0.0, 1.0], y=[0.34, 1.0]),
                            hovertemplate=("<b>Fonte %{label}</b><br>Valor: <b>R$ %{value:,.2f}</b><br>"
                                           "Participação: <b>%{percent}</b><extra></extra>"),
                            hoverlabel=_HOVER)
                        fig_fpz.update_layout(separators=",.", showlegend=True,
                            legend=dict(orientation="h", yanchor="top", y=0.24, xanchor="center", x=0.5,
                                        font=dict(size=11)),
                            height=560, margin=dict(t=30, b=20))
                        _, _cpf, _ = st.columns([1, 2, 1])
                        with _cpf:
                            st.plotly_chart(fig_fpz, use_container_width=True, config=CONFIG_PT)

                        st.markdown("**Movimentação mensal por fonte**")
                        fig_fm = go.Figure()
                        for _i, _ft in enumerate(_dpf['Fonte'].tolist()):
                            _ser = _dff2[_dff2['Fonte'] == _ft]
                            _ys = [float(_ser[f"{m}_Liq"].sum()) if f"{m}_Liq" in _ser.columns else 0.0
                                   for m in meses_disp]
                            if sum(_ys) == 0: continue
                            fig_fm.add_bar(x=meses_disp, y=_ys, name=str(_ft),
                                           marker_color=_CORF.get(_ft, _PALF[_i % len(_PALF)]))
                        fig_fm.update_layout(barmode='stack', separators=",.", hoverlabel=_HOVER,
                            yaxis=dict(showticklabels=False), showlegend=True,
                            legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5,
                                        font=dict(size=10)),
                            height=470, margin=dict(b=130, t=20))
                        fig_fm.update_traces(hovertemplate=(
                            "<b>%{x} — Fonte %{data.name}</b><br>Liquidado: <b>R$ %{y:,.2f}</b><extra></extra>"))
                        st.plotly_chart(fig_fm, use_container_width=True, config=CONFIG_PT)

    # ══════════════════════════════════════════════════════════════════════════
    # MODO 2 — ANÁLISE POR CATEGORIA
    # ══════════════════════════════════════════════════════════════════════════
    else:
        cat = st.session_state.modo
        df_cat = df_raw[df_raw['Categoria'] == cat].copy()
        st.title(f"📂 {cat} — Saúde")
        st.caption(f"Análise da categoria ({meses_disp[0]}–{meses_disp[-1]}).")
        st.markdown("---")

        render_execucao_orcamentaria(df_cat)
        st.markdown("---")

        bloco_vinc_categoria(cat)
        st.markdown("---")

        render_custeio_capital_pizza(df_cat)   # antes do detalhamento de fichas
        st.markdown("---")

        render_detalhamento_elemento(df_cat, key_prefix=f"cat_{remover_acentos(cat)}")
        st.markdown("---")

        render_folha(df_cat, "💼 Folha de Pagamento da Categoria")
        st.markdown("---")

        render_total_investido_fonte(df_cat, "🏥 Total Investido na Categoria — por Fonte")

else:
    st.error("Arquivos de dados não encontrados! Verifique a pasta 'zSaúde'.")


# ── FIM DO SCRIPT: libera o loader (a página terminou de renderizar) ──────────
if _LOGO_ESCURO or _LOGO_CLARO:
    _html_iframe(
        "<script>(function(){try{"
        "var d=window.parent.document;"
        "function done(){var l=d.querySelectorAll('.ig2p-loader');"
        "for(var i=0;i<l.length;i++){l[i].classList.add('ig2p-done');}}"
        "done();setTimeout(done,80);"
        "}catch(e){}})()</script>", height=0)
