import streamlit as st
import pandas as pd
import io
import csv
import gspread
from google.oauth2.service_account import Credentials
import plotly.express as px
import plotly.io as pio
import os
import plotly.graph_objects as go
import streamlit.components.v1 as components

# Compat st.iframe (Streamlit >= 1.56): components.html foi descontinuado e
# st.iframe não aceita height=0 (usado para injeção invisível de JS). Usa st.iframe
# quando disponível, com "content" no lugar de altura não-positiva; senão, fallback.
def _html_iframe(html, height=0, scrolling=False):
    if hasattr(st, "iframe"):
        h = height if isinstance(height, int) and height > 0 else "content"
        st.iframe(html, height=h)
    else:
        components.html(html, height=height, scrolling=scrolling)

st.set_page_config(page_title="Itamogi - Gestão Educação", layout="wide")

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
        .stButton button {
            width:100%!important; height:45px!important;
            padding:0!important; font-size:10px!important;
            font-weight:700!important; border-radius:4px!important;
            white-space:nowrap!important;
            display:flex!important; align-items:center!important;
            justify-content:center!important;
            animation: slideIn 0.4s ease-out;
        }
        .stButton button:focus { outline:none!important; box-shadow:none!important; }
        [data-testid="column"]  { display:flex; align-items:center; justify-content:center; }
        [data-testid="stSidebarNav"] li:first-child > a > span,
        [data-testid="stSidebarNav"] li:first-child > a > p {
            display: none !important;
        }
        /* ===== CABEÇALHO NO TOPO (regra universal iG2P) =====
           (1) reduz o padding-top padrão do container principal;
           (2) colapsa o container do iframe de injeção de JS (logo iG2P),
               que reservava uma faixa vazia no topo da área principal. */
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
    </style>
""", unsafe_allow_html=True)

pio.templates.default = "plotly_dark"
CONFIG_PT   = {'displaylogo': False, 'showTips': False}
HOVER_STYLE = dict(bgcolor="rgba(0,0,0,0.9)", font_size=13,
                   font_family="Arial", font_color="white")
ORDEM_MESES = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
               'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']

if 'setor' not in st.session_state:
    st.session_state.setor = 'FUNDEB'

COR_REC = {
    'Principal':   '#1a7a4a',
    'Rendimentos': '#0d47a1',
    'VAAT':        '#69f0ae',
    'VAAR':        '#b2dfdb',
    'ETI':         '#40c4ff',
}
COR_DESP = {
    'FUNDEB 70% – Vigente': '#4a0000',
    'FUNDEB 30% – Vigente': '#ff1744',
}
# FUNDEB 4% (complementação) — 6 fontes; TODAS entram no 70% (mostradas separadas)
FUNDEB4_FONTES = [
    ('154071', 'FUNDEB 4% Principal (154071)', '#7b241c'),
    ('154072', 'FUNDEB 4% Principal (154072)', '#cb4335'),
    ('154271', 'FUNDEB 4% VAAT (154271)',      '#1e8449'),
    ('154272', 'FUNDEB 4% VAAT (154272)',      '#28b463'),
    ('154371', 'FUNDEB 4% VAAR (154371)',      '#b9770e'),
    ('154372', 'FUNDEB 4% VAAR (154372)',      '#f1c40f'),
]
COR_DESP.update({_lb: _cor for _fc, _lb, _cor in FUNDEB4_FONTES})
FUNDEB4_VAAR = {'154371', '154372'}   # VAAR: entra só nos 4%, NÃO no 70% (só 4% ETI)

def limpar_valor(valor):
    if pd.isna(valor) or str(valor).strip() in ["","−","-","R$ 0,00","0"]:
        return 0.0
    s = str(valor).replace('R$','').replace(' ','').replace('.','').replace(',','.')
    try:
        if '(' in s and ')' in s: s = '-' + s.replace('(','').replace(')','')
        return float(s)
    except: return 0.0

def formar_real(v):
    return f"R$ {v:,.2f}".replace(",","X").replace(".",",").replace("X",".")

def metric_contabil(label, valor_atual, meta):
    delta       = valor_atual - meta
    status_icon = "✅" if valor_atual >= meta else "⚠️"
    return st.metric(label=label,
                     value=f"{status_icon} {valor_atual:.2f}%",
                     delta=f"{delta:.2f}%",
                     delta_color="normal")

def buscar_arquivo(nome):
    caminhos = [nome, os.path.join("..",nome), os.path.join("pages",nome),
                os.path.join(os.path.dirname(__file__),"..",nome)]
    for p in caminhos:
        if os.path.exists(p): return p
    # Fallback tolerante: acha o arquivo ignorando acento/caixa/espaço no nome
    import unicodedata
    def _nz(x):
        x = unicodedata.normalize('NFKD', str(x)).encode('ascii', 'ignore').decode('ascii')
        return ''.join(x.lower().split())
    alvo = _nz(os.path.basename(nome)); subdir = os.path.dirname(nome)
    bases = ['.', '..', os.path.join(os.path.dirname(__file__), '..')]
    for base in bases:
        d = os.path.join(base, subdir) if subdir else base
        try:
            for arq in os.listdir(d):
                if _nz(arq) == alvo:
                    return os.path.join(d, arq)
        except Exception:
            pass
    return None

def soma(df, cols):
    presentes = [c for c in cols if c in df.columns]
    return df[presentes].sum().sum() if presentes else 0.0

# ── CARGA DE DADOS ────────────────────────────────────────────────────────────
# Atualização: Jan+Fev+Mar+Abr (4 meses) — base de dados de Junho 2026
# Individualidades Itamogi:
# • 'Dedução FUNDEB' (categoria sem espaço extra)
# • Elemento Aposentadorias: '- Aposentadorias, Reserva Remunerada e Reformas'
# • FUNDEB 30% (15403) com baixa liquidação no período
# • QESE fontes DF: ['1550'] apenas
# • Novos elementos Folha: '- OBRIGAÇÕES TRIBUTÁRIAS E CONTRIBUTIVAS',
#   'Diárias - Pessoal Civil', 'Outros Auxílios  financeiros PF'
# • _desconto_superavit_ant = 32.015,17
# ── LEITURA VIA GOOGLE SHEETS (com fallback CSV local durante a migração) ─────
@st.cache_resource
def _conectar_sheets():
    escopos = ["https://www.googleapis.com/auth/spreadsheets.readonly",
               "https://www.googleapis.com/auth/drive.readonly"]
    cred = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=escopos)
    return gspread.authorize(cred)


def _norm_aba(s):
    """Normaliza o título de uma aba para casamento tolerante: remove acentos,
    caixa e espaços redundantes. Ex.: 'São João ' ≈ 'sao joao'."""
    import unicodedata
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode('ascii')
    return ' '.join(s.lower().split())

def _gs_call(fn, tentativas=4, espera=1.0):
    """Chamada à API do Google Sheets com retry/backoff para erros transitórios
    (429 rate-limit, 5xx, timeout). Erros definitivos (acesso negado, aba ausente)
    são relançados imediatamente, sem retry."""
    import time
    _ult = None
    for _i in range(tentativas):
        try:
            return fn()
        except Exception as _e:
            _ult = _e
            _m = str(_e).lower()
            _transit = any(t in _m for t in ('429', 'quota', 'rate limit', 'ratelimit',
                                             'resource has been exhausted', '500', '502',
                                             '503', 'internal error', 'backend',
                                             'temporarily', 'timeout', 'timed out',
                                             'deadline', 'connection'))
            if _i < tentativas - 1 and _transit:
                time.sleep(espera * (2 ** _i))
                continue
            raise
    if _ult:
        raise _ult

def _abrir_ws(sheet_id, aba):
    """Abre a worksheet casando o nome de forma tolerante (acento/caixa/espaço),
    com retry para erros transitórios da API."""
    sh = _gs_call(lambda: _conectar_sheets().open_by_key(sheet_id))
    try:
        return _gs_call(lambda: sh.worksheet(aba))
    except Exception:
        _alvo = _norm_aba(aba)
        for _w in _gs_call(lambda: sh.worksheets()):
            if _norm_aba(_w.title) == _alvo:
                return _w
        raise KeyError("aba '%s' nao encontrada na planilha" % aba)

def _ler_aba(sheet_id, aba, **read_csv_kwargs):
    """Lê uma aba reconstruindo um CSV em memória e reutilizando pd.read_csv
    (preserva header=[0,1] etc.). Casa o nome da aba de forma tolerante e usa
    retry para erros transitórios."""
    ws = _abrir_ws(sheet_id, aba)
    vals = _gs_call(lambda: ws.get_all_values())
    buf = io.StringIO()
    csv.writer(buf).writerows(vals)
    buf.seek(0)
    return pd.read_csv(buf, **read_csv_kwargs)

def _ler_aba_raw(sheet_id, aba):
    """Lê uma aba como DataFrame BRUTO (sem cabeçalho e sem detecção de separador),
    direto das células — ideal para layouts livres (PDDE por escola / Programas).
    Evita erros de parse do pd.read_csv(sep=None) e usa retry para 429/5xx."""
    ws = _abrir_ws(sheet_id, aba)
    vals = _gs_call(lambda: ws.get_all_values())
    return pd.DataFrame(vals)


def _fonte(sid, aba, path_local, **kwargs):
    """Fonte de dados: Google Sheets (se sid configurado) → CSV local (fallback)."""
    if sid:
        try:
            kw = {k: v for k, v in kwargs.items() if k != "encoding"}
            return _ler_aba(sid, aba, **kw)
        except Exception:
            pass
    return pd.read_csv(path_local, **kwargs)


def _fonte_raw(sid, aba, path_local):
    """Como _fonte, mas leitura BRUTA (get_all_values → DataFrame, sem sniff de
    separador) para layouts livres (PDDE por escola / Programas). Tenta a API
    (com retry); só cai no CSV local se a API falhar de fato."""
    if sid:
        try:
            return _ler_aba_raw(sid, aba)
        except Exception:
            pass
    if path_local:
        return pd.read_csv(path_local, header=None, dtype=str)
    raise FileNotFoundError("sem fonte (API e local) para a aba %r" % aba)


# ── NORMALIZAÇÃO DE CABEÇALHOS DE MÊS (regra universal iG2P) ──────────────────
# Corrige a captura de valores quando o cabeçalho de um mês vem grafado de forma
# diferente entre as abas (ex.: "MAIO", "Maio ", "Maio/2025", "maio"). Sem isto,
# soma() procura a coluna exata "Maio" e devolve 0 embora a base tenha o dado.
def _canon_mes(nome):
    base = str(nome).strip().lower().replace('ç', 'c').replace('ã', 'a')
    tok = ''
    for ch in base:
        if ch.isalpha():
            tok += ch
        else:
            break
    for _mes in ORDEM_MESES:
        if tok == _mes.lower().replace('ç', 'c').replace('ã', 'a'):
            return _mes
    return None

_TIPOS_FICHA = ('Empenhado', 'Liquidado', 'Pago')

def _monta_col_ficha(col):
    """Monta o nome da coluna de FICHAS (cabeçalho duplo) tolerando a ORDEM dos
    níveis: aceita Tipo-em-cima/Mês-embaixo OU o inverso, e normaliza o mês.
    Garante o padrão '<Mês>_<Tipo>' esperado (ex.: 'Maio_Liquidado'), evitando
    zeros quando a planilha inverte as linhas do cabeçalho."""
    a = str(col[0]).strip()
    b = str(col[1]).strip()
    if 'Unnamed' in str(col[0]) or a == '':
        return b
    if 'Unnamed' in str(col[1]) or b == '':
        return a
    if a in _TIPOS_FICHA:
        tipo, mes = a, b
    elif b in _TIPOS_FICHA:
        tipo, mes = b, a
    else:
        return f"{b}_{a}"
    return f"{(_canon_mes(mes) or mes)}_{tipo}"

def _canoniza_meses_flat(df):
    if df is None:
        return df
    ren = {}
    for c in list(df.columns):
        cm = _canon_mes(c)
        if cm and c != cm and cm not in df.columns:
            ren[c] = cm
    return df.rename(columns=ren) if ren else df


@st.cache_data(ttl=300)
def load_all_data():
    path_f  = buscar_arquivo("zEducação/Itamogi.csv")
    path_r  = buscar_arquivo("zEducação/Itamogi_R.csv")
    path_df = buscar_arquivo("zEducação/Itamogi_DF.csv")
    sid = st.secrets.get("educacao", {}).get("Itamogi", "")
    if not sid and (not path_f or not path_r or not path_df): return None, None, None

    # Fichas — cabeçalho duplo
    df_f = _fonte(sid, "Fichas", path_f, sep=None, engine='python', encoding='utf-8', header=[0,1])
    df_f.columns = [_monta_col_ficha(col) for col in df_f.columns]
    for col in df_f.columns:
        if any(k in col for k in ['Orçado','Saldo','Liquidado','Empenhado','Pago',
                                   'Creditado','Anulado']):
            df_f[col] = df_f[col].apply(limpar_valor)

    # Receitas — header=0 direto
    df_r = _fonte(sid, "Receitas", path_r, sep=None, engine='python', encoding='utf-8', header=0)
    df_r.columns = [str(c).strip() for c in dr.columns] if False else [str(c).strip() for c in df_r.columns]
    COLS_R = ORDEM_MESES + ['Total','Orçado Receitas','Repasse','2025']
    for col in df_r.columns:
        if col in COLS_R:
            df_r[col] = df_r[col].apply(limpar_valor)

    # Despesas por fonte
    df_df = _fonte(sid, "Despesas por fonte", path_df, sep=None, engine='python', encoding='utf-8')
    df_df.columns = [str(c).strip() for c in df_df.columns]
    for col in df_df.columns:
        if col in ORDEM_MESES + ['Total']:
            df_df[col] = df_df[col].apply(limpar_valor)

    for df, colname in [(df_f,'Fonte'),(df_df,'Fonte')]:
        if colname in df.columns:
            df[colname] = df[colname].astype(str).str.replace('.0','',regex=False).str.strip()

    df_r  = _canoniza_meses_flat(df_r)
    df_df = _canoniza_meses_flat(df_df)
    return df_f, df_r, df_df

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




# ══════════════════════════════════════════════════════════════════════════════
# RELATÓRIO DE CONSULTORIA (padrão Itaú de Minas) — CONFIG DO MUNICÍPIO (REVISAR)
#  _REL_DESC_25 : descontos do 25% (FUNDEB não util. + superávit + restos a pagar),
#                 extraídos da seção "Recursos Próprios" deste município.
#  _REL_FOLHA   : elementos de folha (mesma lista do gráfico "Folha de Pagamento").
#  Fontes assumidas: próprios=15001 · FUNDEB 70%=15407 · FUNDEB 30%=15403.
# ══════════════════════════════════════════════════════════════════════════════
_REL_DESC_25 = 32015.17
_REL_FOLHA = [
            'Vencimentos e Vantagens Fixas - Pessoal Civil',
            'Obrigações Patronais',
            'Contratação por tempo Determinado',
            'Outras Despesas Variáveis - Pessoal Civil',
            'Indenizações e Restituições Trabalhistas',
            'Auxílio-alimentação',
            '- Aposentadorias, Reserva Remunerada e Reformas',
            '- OBRIGAÇÕES TRIBUTÁRIAS E CONTRIBUTIVAS',  # ← com traço (grafia real)
            'OBRIGAÇÕES TRIBUTÁRIAS E CONTRIBUTIVAS',    # ← sem traço (variante)
            'Diárias - Pessoal Civil',
            'Outros Auxílios  financeiros PF',
        ]

def _rel_tabela(data, header_color, zebra, col_widths=None):
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle
    if col_widths is None:
        col_widths = [95*mm, 75*mm]
    t = Table(data, colWidths=col_widths, hAlign='LEFT')
    style = [
        ('BACKGROUND',(0,0),(-1,0),header_color),
        ('TEXTCOLOR',(0,0),(-1,0),colors.white),
        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
        ('FONTSIZE',(0,0),(-1,-1),9),
        ('ALIGN',(1,0),(-1,-1),'LEFT'),
        ('GRID',(0,0),(-1,-1),0.4,colors.HexColor('#cccccc')),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('TOPPADDING',(0,0),(-1,-1),4),
        ('BOTTOMPADDING',(0,0),(-1,-1),4),
        ('LEFTPADDING',(0,0),(-1,-1),6),
    ]
    for r in range(1, len(data)):
        if r % 2 == 1:
            style.append(('BACKGROUND',(0,r),(-1,r),zebra))
    t.setStyle(TableStyle(style))
    return t

def _dados_relatorio(df_f, df_r, df_df, meses):
    """Calcula TODOS os indicadores do relatório (lógica Itaú de Minas),
    independentemente do setor selecionado."""
    d = {}
    d['periodo'] = f"{meses[0]}–{meses[-1]}" if meses else "—"

    def cat_receita(desc):
        x = str(desc).upper().strip()
        if 'VAAT' in x:                             return 'VAAT'
        if 'VAAR' in x:                             return 'VAAR'
        if 'ETI'  in x or 'TEMPO INTEGRAL' in x:    return 'ETI'
        if 'APLICAÇÃO' in x or 'RENDIMENTOS' in x:  return 'Rendimentos'
        return 'Principal'
    dfb = df_r[df_r['Categoria'].str.strip() == 'FUNDEB'].copy()
    dfb['Descrição da Receita'] = dfb['Descrição da Receita'].str.strip()
    dfb['Sub'] = dfb['Descrição da Receita'].apply(cat_receita)
    val_quad = dfb['Atualização Quadrimestral'].apply(limpar_valor).sum() \
        if 'Atualização Quadrimestral' in dfb.columns else 0.0
    tot_rec_periodo = soma(dfb, meses)
    rend_fundeb = soma(dfb[dfb['Sub']=='Rendimentos'], meses)
    dff = df_df[df_df['Fonte'].isin(['15407','15403'])]
    desp_70 = soma(dff[(dff['Fonte']=='15407') & (dff['Tipo']=='Liquidado')], meses)
    desp_30 = soma(dff[(dff['Fonte']=='15403') & (dff['Tipo']=='Liquidado')], meses)
    tot_desp_vig = desp_70 + desp_30
    base_70 = soma(dfb[dfb['Sub'].isin(['Principal','Rendimentos'])], meses)
    perc_70 = (desp_70/base_70*100) if base_70>0 else 0.0
    # Base ETI (ITM): Principal + Rendimentos + VAAT (só VAAT). Referência 4%.
    base_eti = soma(dfb[dfb['Sub'].isin(['Principal','Rendimentos','VAAT'])], meses)
    meta_eti = base_eti * 0.04
    d.update(prev_quad=val_quad, fundeb_rec=tot_rec_periodo, fundeb_desp=tot_desp_vig,
             fundeb_saldo=tot_rec_periodo-tot_desp_vig, base_70=base_70, desp_70=desp_70,
             perc_70=perc_70, rend_fundeb=rend_fundeb, base_eti=base_eti, meta_eti=meta_eti)

    base = df_r[df_r['Categoria'].str.strip().isin(['Impostos','Cota-Parte'])].copy()
    ded  = df_r[df_r['Categoria'].str.strip().str.startswith('Dedução', na=False)].copy()
    tot_rec_base = soma(base, meses)
    tot_ded      = abs(soma(ded, meses))
    d15001 = df_df[(df_df['Fonte']=='15001') & (df_df['Tipo']=='Liquidado')]
    total_15001 = soma(d15001, meses)
    # Descontos do 25% (individualidade do município) — ver _REL_DESC_25 no topo.
    _total_desc = _REL_DESC_25
    esforco = max(0.0, total_15001 + tot_ded - _total_desc)
    perc_25 = (esforco/tot_rec_base*100) if tot_rec_base>0 else 0.0
    d.update(rp_base=tot_rec_base, rp_meta=tot_rec_base*0.25, rp_esforco=esforco, perc_25=perc_25)

    mapa_desp = {'PNAE':['1552'],'PNATE':['1553'],'PTE':['1576'],'QESE':['1550']}
    programas = ['PNAE','PNATE','PTE','QESE']
    dvinc = df_r[df_r['Descrição da Receita'].str.upper().str.strip().isin(programas)].copy()
    drem  = df_r[df_r['Categoria'].str.strip() == 'Remunerações Bancárias'].copy()
    vinc = {}
    for prog in programas:
        dprog = dvinc[dvinc['Descrição da Receita'].str.upper().str.strip()==prog]
        rmask = drem['Descrição da Receita'].str.upper().str.strip().str.contains(prog, na=False)
        transf = soma(dprog, meses)
        rend   = soma(drem[rmask], meses)
        receita = transf + rend
        desp    = soma(df_df[df_df['Fonte'].isin(mapa_desp[prog]) &
                             (df_df['Tipo']=='Liquidado')], meses)
        saldo   = receita - desp
        saldo_perc = (saldo/receita*100) if receita>0 else 0.0
        vinc[prog] = dict(receita=receita, despesa=desp, saldo=saldo, saldo_perc=saldo_perc)
    d['vinc'] = vinc

    liq_cols = [f"{m}_Liquidado" for m in meses if f"{m}_Liquidado" in df_f.columns]
    CAP = ['Obras e Instalações', 'Equipamentos e Materiais Permanentes']
    dm = df_f.copy()
    dm['Nat'] = dm['Elemento'].apply(lambda x: 'Capital' if str(x).strip() in CAP else 'Custeio')
    cap = dm[dm['Nat']=='Capital'][liq_cols].sum().sum()
    cus = dm[dm['Nat']=='Custeio'][liq_cols].sum().sum()
    tot = cap + cus
    d.update(macro_total=tot, macro_capital=cap, macro_custeio=cus,
             macro_perc_capital=(cap/tot*100 if tot>0 else 0),
             macro_perc_custeio=(cus/tot*100 if tot>0 else 0))

    FOLHA = list(_REL_FOLHA)
    d['folha_total'] = df_f[df_f['Elemento'].isin(FOLHA)][liq_cols].sum().sum()
    return d


# Nome da Secretária(o) de Educação (opcional). Em branco, a linha NÃO aparece
# no relatório. Para exibir, basta preencher com o nome.
RELATORIO_SECRETARIA = ""

def _pdf_relatorio(d, municipio, secretaria=None):
    """Gera o PDF do relatório de consultoria (análise gerencial completa)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle, HRFlowable)
    from reportlab.lib.enums import TA_CENTER
    from io import BytesIO
    from datetime import datetime

    if secretaria is None:
        secretaria = RELATORIO_SECRETARIA

    AZUL  = colors.HexColor('#003366')
    VERDE = colors.HexColor('#1a7a4a')
    VERM  = colors.HexColor('#b00020')
    LARANJA = colors.HexColor('#b9770e')
    CINZA = colors.HexColor('#f0f2f5')

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm,
                            topMargin=16*mm, bottomMargin=16*mm,
                            title="IG2P - Relatórios",
                            author="iG2P — Plataforma de Gestão Pública",
                            subject=f"Relatório Analítico e Gerencial — Educação ({municipio})")
    ss = getSampleStyleSheet()
    h_title = ParagraphStyle('t', parent=ss['Title'], fontSize=16, textColor=AZUL,
                             alignment=TA_CENTER, spaceAfter=2)
    h_sub = ParagraphStyle('s', parent=ss['Normal'], fontSize=9.5, textColor=colors.grey,
                           alignment=TA_CENTER, spaceAfter=10)
    h2 = ParagraphStyle('h2', parent=ss['Heading2'], fontSize=12, textColor=AZUL,
                        spaceBefore=10, spaceAfter=4)
    h3 = ParagraphStyle('h3', parent=ss['Heading3'], fontSize=10.5,
                        textColor=colors.HexColor('#222'), spaceBefore=6, spaceAfter=2)
    body = ParagraphStyle('b', parent=ss['Normal'], fontSize=9.5, leading=13)
    a_ok = ParagraphStyle('aok', parent=body, textColor=VERDE)
    a_bad = ParagraphStyle('abad', parent=body, textColor=VERM)
    a_warn = ParagraphStyle('awarn', parent=body, textColor=LARANJA)
    legal = ParagraphStyle('legal', parent=body, fontSize=8.2,
                           textColor=colors.HexColor('#555'), leftIndent=2)

    def base_legal(txt):
        return Paragraph(f"<b>Base legal:</b> {txt}", legal)

    el = []
    el.append(Paragraph("Relatório Analítico e Gerencial — Educação", h_title))
    el.append(Paragraph("Consultoria iG2P — Plataforma de Gestão Pública", h_sub))
    el.append(HRFlowable(width="100%", color=AZUL, thickness=1.2, spaceAfter=8))

    # 1. Informações
    el.append(Paragraph("1. Informações da Reunião", h2))
    hoje = datetime.now().strftime("%d/%m/%Y")
    info = [["Município:", f"{municipio} - MG"]]
    sec_val = secretaria.strip() if secretaria else ""
    if sec_val:  # só exibe a linha se um nome for informado (sem linha em branco)
        info.append(["Secretária(o) de Educação:", sec_val])
    info.append(["Data:", hoje])
    info.append(["Pauta Principal:", f"Análise de dados financeiros e orçamentários da "
                                      f"Educação ({d['periodo']})."])
    t = Table(info, colWidths=[48*mm, 122*mm])
    t.setStyle(TableStyle([('FONTNAME',(0,0),(0,-1),'Helvetica-Bold'),
        ('FONTSIZE',(0,0),(-1,-1),9.5),('TEXTCOLOR',(0,0),(0,-1),AZUL),
        ('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),3)]))
    el.append(t)

    # 2. FUNDEB
    el.append(Paragraph("2. FUNDEB — Receitas, Despesas e Aplicação", h2))
    saldo = d['fundeb_saldo']
    sit_saldo = f"{formar_real(saldo)} ({'Superávit' if saldo>=0 else 'Déficit'})"
    el.append(_rel_tabela([
        ["Indicador", "Valor / Situação"],
        ["Previsão Atualizada (Quadrimestral)", formar_real(d['prev_quad'])],
        [f"Total Receitas ({d['periodo']})", formar_real(d['fundeb_rec'])],
        [f"  • dos quais Rendimentos de aplicação", formar_real(d['rend_fundeb'])],
        [f"Despesas Liquidadas ({d['periodo']})", formar_real(d['fundeb_desp'])],
        ["Saldo Quadrimestral", sit_saldo],
    ], AZUL, CINZA))
    p70 = d['perc_70']
    if p70 > 100:
        el.append(Paragraph(f"⚠ Alerta crítico: a aplicação em pessoal atingiu "
            f"<b>{p70:.2f}%</b> ({formar_real(d['desp_70'])}) da base de cálculo, consumindo "
            f"integralmente os recursos do período. Recomenda-se monitorar para não "
            f"comprometer o saldo dos próximos meses.", a_bad))
    elif p70 >= 70:
        el.append(Paragraph(f"✔ A aplicação em pessoal atingiu <b>{p70:.2f}%</b> "
            f"({formar_real(d['desp_70'])}), cumprindo o mínimo de 70%. O FUNDEB deve "
            f"manter o foco no investimento da folha de pagamento dos profissionais da "
            f"educação.", a_ok))
    else:
        el.append(Paragraph(f"⚠ Alerta: a aplicação em pessoal está em <b>{p70:.2f}%</b> "
            f"({formar_real(d['desp_70'])}), <b>abaixo</b> do mínimo de 70%. É necessário "
            f"ampliar a destinação do FUNDEB à folha dos profissionais da educação.", a_bad))
    el.append(Paragraph(f"Ensino em Tempo Integral (ETI): a referência de 4% sobre a base de "
        f"cálculo equivale a <b>{formar_real(d['meta_eti'])}</b>. Recomenda-se direcionar "
        f"recursos para a estruturação do ETI, observando o levantamento de matrículas ativas.",
        a_warn))
    el.append(base_legal("Lei nº 14.113/2020 (FUNDEB), art. 25 (mínimo de 70% para "
        "remuneração dos profissionais da educação) e art. 26; Lei nº 13.005/2014 (PNE) "
        "para a estratégia de Ensino em Tempo Integral."))

    # 3. Recursos Próprios 25%
    el.append(Paragraph("3. Recursos Próprios — Aplicação Mínima (25%)", h2))
    el.append(_rel_tabela([
        ["Indicador", "Valor"],
        [f"Receitas Base (Arrecadadas {d['periodo']})", formar_real(d['rp_base'])],
        ["Meta 25%", formar_real(d['rp_meta'])],
        ["Esforço Líquido Aplicado", formar_real(d['rp_esforco'])],
    ], AZUL, CINZA))
    p25 = d['perc_25']
    if p25 < 25:
        el.append(Paragraph(f"⚠ Alerta crítico: o índice de aplicação está em "
            f"<b>{p25:.2f}%</b>, <b>abaixo</b> do mínimo constitucional de 25%. Recomenda-se "
            f"reforçar a aplicação em Manutenção e Desenvolvimento do Ensino (MDE) até o "
            f"encerramento do exercício.", a_bad))
    else:
        el.append(Paragraph(f"✔ O índice de aplicação está em <b>{p25:.2f}%</b>, cumprindo o "
            f"mínimo constitucional de 25%. Estando acima da meta, a recomendação principal é "
            f"verificar se os recursos vinculados estão sendo plenamente utilizados, cruzando "
            f"os dados entre PNATE e PTE para otimizar o uso das fontes específicas antes do "
            f"recurso próprio.", a_ok))
    el.append(base_legal("Constituição Federal de 1988, art. 212 (mínimo de 25% da receita "
        "de impostos e transferências em MDE)."))

    # 4. Recursos Vinculados
    el.append(Paragraph("4. Recursos Vinculados — Federais e Estaduais", h2))
    tab_v = [["Programa", "Receita", "Despesa Liq.", "Saldo", "Saldo %"]]
    for prog in ['PNAE','PNATE','PTE','QESE']:
        v = d['vinc'][prog]
        tab_v.append([prog, formar_real(v['receita']), formar_real(v['despesa']),
                      formar_real(v['saldo']), f"{v['saldo_perc']:.1f}%"])
    el.append(_rel_tabela(tab_v, AZUL, CINZA,
                          col_widths=[24*mm,40*mm,40*mm,40*mm,26*mm]))

    pnae, pnate, pte, qese = (d['vinc']['PNAE'], d['vinc']['PNATE'],
                              d['vinc']['PTE'], d['vinc']['QESE'])
    # PNAE
    if pnae['saldo_perc'] > 15:
        el.append(Paragraph(f"• <b>PNAE</b>: saldo de <b>{pnae['saldo_perc']:.1f}%</b> "
            f"(acima de 15%) — verificar execução. Conferir ainda a aquisição da agricultura "
            f"familiar (mínimo de 30% — Lei 11.947/2009; diretriz de gestão de 45%, priorizando "
            f"50% de mulheres).", a_warn))
    else:
        el.append(Paragraph(f"• <b>PNAE</b>: saldo de {pnae['saldo_perc']:.1f}%. Conferir a "
            f"aquisição da agricultura familiar (mínimo de 30% — Lei 11.947/2009; diretriz de "
            f"gestão de 45%, priorizando 50% de mulheres).", body))
    # PNATE
    if pnate['saldo_perc'] > 30:
        el.append(Paragraph(f"• <b>PNATE</b>: saldo de <b>{pnate['saldo_perc']:.1f}%</b> "
            f"(acima de 30%) — avaliar a aplicação no transporte escolar e possível "
            f"complementação via PTE.", a_warn))
    else:
        el.append(Paragraph(f"• <b>PNATE</b>: saldo de {pnate['saldo_perc']:.1f}%, dentro do "
            f"parâmetro de execução do transporte escolar.", body))
    # PTE
    if pte['saldo'] > 0:
        el.append(Paragraph(f"• <b>PTE</b>: há saldo não utilizado de "
            f"<b>{formar_real(pte['saldo'])}</b> — justificar e priorizar o uso desta fonte "
            f"estadual no transporte antes do recurso próprio.", a_warn))
    else:
        el.append(Paragraph(f"• <b>PTE</b>: fonte aplicada no período (sem saldo ocioso "
            f"relevante).", body))
    # QESE
    el.append(Paragraph(f"• <b>QESE</b>: receita {formar_real(qese['receita'])} / despesa "
        f"{formar_real(qese['despesa'])}. Observar se o uso está elevado enquanto o índice "
        f"do recurso próprio (25%) permanece abaixo da meta — situação que indica "
        f"oportunidade de melhor alocação entre as fontes.", body))
    el.append(base_legal("PNAE — Lei nº 11.947/2009, art. 14; PNATE — Lei nº 10.880/2004; "
        "QESE (Salário-Educação) — CF/1988, art. 212, §5º e Lei nº 9.424/1996."))

    # 5. Visão Macro e Folha
    el.append(Paragraph("5. Visão Macro e Folha de Pagamento", h2))
    el.append(Paragraph(f"Execução orçamentária do período (Total: "
        f"<b>{formar_real(d['macro_total'])}</b>), distribuída entre Custeio e Capital:", body))
    el.append(_rel_tabela([
        ["Natureza", "Valor", "Participação"],
        ["Custeio", formar_real(d['macro_custeio']), f"{d['macro_perc_custeio']:.1f}%"],
        ["Capital", formar_real(d['macro_capital']), f"{d['macro_perc_capital']:.1f}%"],
    ], AZUL, CINZA, col_widths=[56*mm,57*mm,57*mm]))
    if d['macro_custeio'] >= d['macro_capital']:
        el.append(Paragraph(f"✔ Conforme esperado na educação, o Custeio "
            f"({d['macro_perc_custeio']:.1f}%) supera o Capital "
            f"({d['macro_perc_capital']:.1f}%), refletindo a natureza de manutenção da "
            f"rede de ensino.", a_ok))
    else:
        el.append(Paragraph(f"⚠ Atenção: o Capital ({d['macro_perc_capital']:.1f}%) superou "
            f"o Custeio ({d['macro_perc_custeio']:.1f}%), o que é atípico na educação e "
            f"merece verificação.", a_warn))
    el.append(Paragraph(f"A Folha de Pagamento ({formar_real(d['folha_total'])}) é a "
        f"principal fonte de pressão sobre as receitas correntes do período.", body))

    # 6. SIOPE x Balancete
    el.append(Paragraph("6. SIOPE × Balancete (FUNDEB)", h2))
    el.append(Paragraph(f"Despesa do FUNDEB 70% apurada no Balancete (painel): "
        f"<b>{formar_real(d['desp_70'])}</b>, correspondente a um índice de aplicação de "
        f"<b>{d['perc_70']:.2f}%</b> sobre a base de cálculo. Recomenda-se confrontar estes "
        f"valores com o extrato do SIOPE: pequenas divergências são esperadas, mas devem ser "
        f"justificadas e conciliadas. Atenção para que os rendimentos de aplicação "
        f"({formar_real(d['rend_fundeb'])}) estejam considerados em ambas as bases.", body))
    el.append(base_legal("Lei nº 14.113/2020 e Portaria STN/SOF sobre o SIOPE — Sistema de "
        "Informações sobre Orçamentos Públicos em Educação."))

    # 7. Deliberações
    el.append(Paragraph("7. Deliberações e Próximos Passos", h2))
    delibs = ["Levantamento do número exato de matrículas ativas no Ensino em Tempo Integral "
              "(ETI), para embasar o enquadramento de despesas de estruturação — avaliando se é "
              "mais estratégico alocá-las na cota de 4% do FUNDEB ETI ou em Recursos Próprios "
              "para impulsionar o índice constitucional dos 25%.",
              "Conciliar os valores do FUNDEB entre Balancete e SIOPE, garantindo a inclusão "
              "dos rendimentos de aplicação financeira em ambas as bases."]
    if d['perc_25'] < 25:
        delibs.append("Reforçar a aplicação em Recursos Próprios (MDE) para atingir o mínimo "
                      "constitucional de 25% até o encerramento do exercício.")
    else:
        delibs.append("Priorizar o uso pleno dos recursos vinculados (PNATE e PTE no "
                      "transporte; PNAE na alimentação) antes do recurso próprio, otimizando "
                      "as fontes específicas.")
    if d['perc_70'] > 100:
        delibs.append("Monitorar a aplicação em pessoal do FUNDEB, que já consome "
                      "integralmente a receita do período.")
    for i, dl in enumerate(delibs, 1):
        el.append(Paragraph(f"<b>{i}.</b> {dl}", body)); el.append(Spacer(1, 2))

    el.append(Spacer(1, 8))
    el.append(HRFlowable(width="100%", color=colors.grey, thickness=0.6, spaceAfter=4))
    el.append(Paragraph(f"Documento gerado automaticamente para uso da Secretaria de "
        f"Educação de {municipio}-MG. Consultoria iG2P — {hoje}.",
        ParagraphStyle('foot', parent=body, fontSize=8, textColor=colors.grey,
                       alignment=TA_CENTER)))

    doc.build(el)
    buf.seek(0)
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
# PROGRAMAS E PDDE — planilha SEPARADA de Acompanhamentos (consumo via API)
#  IMPORTANTE: a conta de serviço precisa ter ACESSO DE LEITOR às duas planilhas.
#  Fallback local p/ pré-visualizar: zEducação/Itamogi_PROG.csv e zEducação/Itamogi_PDDE.csv
# ══════════════════════════════════════════════════════════════════════════════
ACOMP_ABA = "Itamogi"   # aba do município nas DUAS planilhas de acompanhamento
# IDs lidos do secrets → [acompanhamentos] (com fallback nos IDs já conhecidos):
try:
    _acomp = dict(st.secrets.get("acompanhamentos", {}))
except Exception:
    _acomp = {}
ACOMP_SHEET_PROGRAMAS = _acomp.get("programas", "1GgpB5OZfa4M50uVziGqMi12KEC6bKis2TrqpPRU54is")
ACOMP_SHEET_ESCOLAS   = _acomp.get("escolas",   "1OhP-i6CC3nTL2tvlS8QXklgoXjLlDtjncBywpgdN8K0")
_ACOMP_SECOES = {'SIMEC', 'PROGRAMAS SEB', 'PDDE EQUIDADE', 'PNLD',
                 'RECOMPOSIÇÃO DAS APRENDIZAGENS'}


def _parse_pdde_escolas(raw):
    """Lê o layout livre da aba de Escolas (blocos por escola) e devolve
    {escola: {'programas': [(prog, previsto, recebido)], 'prev': x, 'rec': y}}."""
    raw = raw.fillna("")
    escolas = {}; cur = None
    for _, r in raw.iterrows():
        c0 = str(r.iloc[0]).strip()
        c1 = str(r.iloc[1]).strip() if raw.shape[1] > 1 else ""
        if "previsto" in c1.lower():   # casa "Previstos" e "Recursos Previstos"
            nome = c0.strip('*').strip()
            cur = None if nome.lower() == "escolas" else nome
            if cur:
                escolas[cur] = {"programas": [], "prev": 0.0, "rec": 0.0}
            continue
        if cur is None:
            continue
        if c0.lower().startswith("total recebido"):
            escolas[cur]["prev"] = limpar_valor(r.iloc[1])
            escolas[cur]["rec"]  = limpar_valor(r.iloc[2]) if raw.shape[1] > 2 else 0.0
            cur = None
            continue
        if c0 and not c0.lower().startswith("saldo"):
            pv = limpar_valor(r.iloc[1])
            rc = limpar_valor(r.iloc[2]) if raw.shape[1] > 2 else 0.0
            if pv > 0 or rc > 0:
                escolas[cur]["programas"].append((c0, pv, rc))
    return escolas


@st.cache_data(ttl=300)
def load_acompanhamentos():
    df_prog = df_esc = None
    try:                                    # Programas — detecta a linha do cabeçalho ('PROGRAMAS')
        _rawp = _fonte_raw(ACOMP_SHEET_PROGRAMAS, ACOMP_ABA, buscar_arquivo("zEducação/Itamogi_PROG.csv"))
        _hi = 0
        for _k in range(min(6, len(_rawp))):
            if _rawp.iloc[_k].astype(str).str.upper().str.contains('PROGRAMAS').any():
                _hi = _k; break
        df_prog = _rawp.iloc[_hi + 1:].copy()
        df_prog.columns = [str(c).strip() for c in _rawp.iloc[_hi]]
        df_prog = df_prog.reset_index(drop=True)
    except Exception:
        df_prog = None
    try:                                    # Escolas/PDDE — layout livre (sem cabeçalho fixo)
        df_esc = _fonte_raw(ACOMP_SHEET_ESCOLAS, ACOMP_ABA, buscar_arquivo("zEducação/Itamogi_PDDE.csv"))
    except Exception:
        df_esc = None
    return df_prog, df_esc


df_f_raw, df_r, df_df_raw = load_all_data()

# ATUALIZADO: 4 meses disponíveis
def _detectar_meses(df_f, df_r, df_df):
    meses = []
    for m in ORDEM_MESES:
        tem = False
        cl = f"{m}_Liquidado"
        if df_f is not None and cl in df_f.columns and df_f[cl].abs().sum() > 0:
            tem = True
        if df_r is not None and m in df_r.columns and \
           pd.to_numeric(df_r[m], errors='coerce').abs().sum() > 0:
            tem = True
        if df_df is not None and m in df_df.columns and df_df[m].abs().sum() > 0:
            tem = True
        if tem:
            meses.append(m)
    return meses if meses else ['Janeiro']

meses_disponiveis = _detectar_meses(df_f_raw, df_r, df_df_raw)
if df_f_raw is not None and df_r is not None:

    st.sidebar.title("🔍 Filtros de Análise")
    search_term = st.sidebar.text_input("Filtrar Fichas:", "")
    st.sidebar.markdown("---")
    st.sidebar.subheader("Setores")
    for label, key in [("FUNDEB","FUNDEB"),
                        ("Recursos Próprios","Recursos Próprios"),
                        ("Recursos Vinculados","Recursos Vinculados"),
                        ("Visão Macro","Visão Macro"),
                        ("Folha de Pagamento","Folha de Pagamento"),
                        ("Programas e PDDE","Programas e PDDE")]:
        if st.sidebar.button(label, use_container_width=True):
            st.session_state.setor = key

    # ── ATUALIZAR DADOS (busca a última versão das planilhas) ─────────────────
    st.sidebar.markdown("---")
    if st.sidebar.button("🔄 Atualizar dados", use_container_width=True,
                         help="Busca agora as últimas alterações feitas nas planilhas."):
        st.cache_data.clear()
        st.rerun()

    # ── RELATÓRIO DE CONSULTORIA (gerado na hora) ─────────────────────────────

    st.sidebar.markdown("---")
    st.sidebar.subheader("📄 Relatório de Consultoria")
    st.sidebar.caption("Gera um relatório financeiro do município em PDF, com os "
                       "indicadores do período.")
    try:
        # regenera se trocar de município (fingerprint) OU se os dados mudarem
        _rel_fp = "Itamogi|" + str(len(meses_disponiveis)) + "|" + \
                  str(round(float(df_f_raw.select_dtypes('number').sum().sum()), 2))
        if st.session_state.get('_pdf_rel_fp') != _rel_fp:
            st.session_state['_pdf_rel_fp'] = _rel_fp
            st.session_state['_pdf_rel_bytes'] = _pdf_relatorio(
                _dados_relatorio(df_f_raw, df_r, df_df_raw, meses_disponiveis),
                "Itamogi")
        st.sidebar.download_button(
            "📥 Baixar Relatório (PDF)",
            data=st.session_state['_pdf_rel_bytes'],
            file_name="Relatorio_Consultoria_Itamogi.pdf",
            mime="application/pdf",
            use_container_width=True,
        )
    except ModuleNotFoundError:
        st.sidebar.info("Adicione 'reportlab' ao requirements.txt para habilitar o relatório.")
    except Exception:
        st.sidebar.warning("Não foi possível gerar o relatório no momento.")


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
            candidatos += [os.path.join(d,"Logos",nome_arquivo),
                           os.path.join(d,"..","Logos",nome_arquivo)]
        except NameError:
            pass
        for p in candidatos:
            if os.path.exists(p):
                with open(p,"rb") as _f:
                    return "data:image/png;base64," + _b64.b64encode(_f.read()).decode()
        return ""

    _logo_escuro = _ler_logo("LOGOTIPO IG2P - OFICIAL - BRANCO.png")
    _logo_claro  = _ler_logo("LOGOTIPO IG2P - OFICIAL.png")

    _js_sidebar = (
        '<script>(function(){'
        'var LE="' + _logo_escuro + '";'
        'var LC="' + _logo_claro  + '";'
        'function dE(){try{'
        'var bg=window.parent.getComputedStyle(window.parent.document.body).backgroundColor;'
        'if(!bg||bg==="rgba(0,0,0,0)")return true;'
        'var v=bg.match(/[0-9]+/g).map(Number);return v[0]<128;'
        '}catch(e){return true;}}'
        'function run(){try{'
        'var doc=window.parent.document;'
        'var nav=doc.querySelector(\'[data-testid="stSidebarNav"]\');'
        'if(!nav)return;'
        'nav.querySelectorAll(\'li\').forEach(function(it){'
        'var _t=it.textContent;'
        'if(_t.indexOf(\'Sa\u00fade\')!==-1||_t.indexOf(\'Conv\u00ea\')!==-1){'
        'it.style.setProperty(\'display\',\'none\',\'important\');return;}'
        'var lk=it.querySelector(\'a\');if(!lk)return;'
        'var sp=lk.querySelector(\'span\');'
        'var tx=(sp?sp.textContent:lk.textContent).trim();'
        'var eh=tx==="Home"||tx.toLowerCase()==="home"||'
        '(lk.href&&lk.href.toLowerCase().indexOf(\'/home\')!==-1);'
        'if(!eh)return;'
        'if(lk.querySelector(\'img.ig2p-logo-sidebar\'))return;'
        'if(sp)sp.style.setProperty(\'display\',\'none\',\'important\');'
        'lk.style.setProperty(\'padding\',\'4px 8px 4px 8px\',\'important\');'
        'lk.style.setProperty(\'display\',\'flex\',\'important\');'
        'lk.style.setProperty(\'align-items\',\'center\',\'important\');'
        'lk.style.setProperty(\'background\',\'transparent\',\'important\');'
        'var img=doc.createElement(\'img\');'
        'img.src=dE()?LE:LC;'
        'img.className=\'ig2p-logo-sidebar\';'
        'img.style.cssText=\'width:130px;height:auto;cursor:pointer;display:block;margin:4px 0;\';'
        'var mq=window.parent.matchMedia(\'(prefers-color-scheme:dark)\');'
        'function up(){img.src=dE()?LE:LC;}'
        'if(mq.addEventListener)mq.addEventListener(\'change\',up);'
        'else if(mq.addListener)mq.addListener(up);'
        'lk.insertBefore(img,lk.firstChild);'
        '});'
        '}catch(e){}}'
        'run();setTimeout(run,50);setTimeout(run,200);setTimeout(run,600);'
        '})()</script>'
    )
    _html_iframe(_js_sidebar, height=0)

    # =========================================================================
    # SETOR FUNDEB
    # =========================================================================
    if st.session_state.setor == 'FUNDEB':
        st.markdown("<h1 style='text-align:left;'>📖 Itamogi — FUNDEB</h1>",
                    unsafe_allow_html=True)

        def cat_receita(desc):
            d = str(desc).upper().strip()
            if 'VAAT' in d:                              return 'VAAT'
            if 'VAAR' in d:                              return 'VAAR'
            if 'ETI'  in d or 'TEMPO INTEGRAL' in d:    return 'ETI'
            if 'APLICAÇÃO' in d or 'RENDIMENTOS' in d:  return 'Rendimentos'
            return 'Principal'

        df_r_fundeb = df_r[df_r['Categoria'].str.strip() == 'FUNDEB'].copy()
        df_r_fundeb['Descrição da Receita'] = df_r_fundeb['Descrição da Receita'].str.strip()
        df_r_fundeb['Subcategoria'] = df_r_fundeb['Descrição da Receita'].apply(cat_receita)

        tot_prev_municipio = df_r_fundeb[df_r_fundeb['Subcategoria']=='Principal'
                                         ]['Orçado Receitas'].sum()
        tot_prev_portaria  = df_r_fundeb['Repasse'].sum() if 'Repasse' in df_r_fundeb.columns else 0.0
        tot_rec_periodo    = soma(df_r_fundeb, meses_disponiveis)

        df_df_fundeb = df_df_raw[df_df_raw['Fonte'].isin(
            ['15407','15403'] + [_f for _f, _l, _c in FUNDEB4_FONTES])].copy()
        df_df_fundeb['Fonte_Nome'] = df_df_fundeb['Fonte'].apply(
            lambda x: 'FUNDEB 70%' if x=='15407' else 'FUNDEB 30%')

        base_indice_70  = soma(df_r_fundeb[df_r_fundeb['Subcategoria'].isin(
                                ['Principal','Rendimentos','VAAT'])], meses_disponiveis)
        def _desp_f(fcod, meses):
            return soma(df_df_fundeb[(df_df_fundeb['Fonte'] == fcod) &
                                     (df_df_fundeb['Tipo'] == 'Liquidado')], meses)
        desp_15407 = _desp_f('15407', meses_disponiveis)
        desp_f4 = {_f: _desp_f(_f, meses_disponiveis) for _f, _l, _c in FUNDEB4_FONTES}
        desp_f4_70    = sum(v for k, v in desp_f4.items() if k not in FUNDEB4_VAAR)
        desp_f4_vaar  = sum(v for k, v in desp_f4.items() if k in FUNDEB4_VAAR)
        desp_f4_total = desp_f4_70 + desp_f4_vaar
        desp_70_vigente = desp_15407 + desp_f4_70   # 15407 + Principal + VAAT (VAAR fora do 70%)
        desp_30_vigente = soma(df_df_fundeb[(df_df_fundeb['Fonte']=='15403') &
                                (df_df_fundeb['Tipo']=='Liquidado')], meses_disponiveis)
        tot_desp_vigente = desp_70_vigente + desp_30_vigente
        perc_70_indice   = (desp_70_vigente/base_indice_70*100) if base_indice_70>0 else 0.0

        st.markdown("##### Previsões Orçamentárias")
        p1, p2, p3 = st.columns(3)
        with p1: st.metric("Previsão Receitas (Orçamento Município)",
                            formar_real(tot_prev_municipio))
        with p2: st.metric("Previsão de Receitas (Portaria Interministerial MEC/MF Nº 5 de Abril de 2026)",
                            formar_real(tot_prev_portaria))
        _val_quad = df_r_fundeb['Atualização Quadrimestral'].apply(
            lambda v: limpar_valor(v)
        ).sum() if 'Atualização Quadrimestral' in df_r_fundeb.columns else 0.0
        def _parse_perc_quad(v):
            try:
                s = str(v).replace('%','').replace(',','.').strip()
                return float(s)
            except: return None
        _perc_quad = None
        if '% Atualização' in df_r_fundeb.columns:
            _vals_p = df_r_fundeb['% Atualização'].apply(_parse_perc_quad).dropna()
            if len(_vals_p) > 0: _perc_quad = _vals_p.iloc[0]
        _delta_quad = f"{_perc_quad:.2f}%" if _perc_quad is not None else None
        with p3: st.metric(
            "Atualização Quadrimestral",
            formar_real(_val_quad) if _val_quad > 0 else "—",
            delta=_delta_quad, delta_color="normal"
        )
        st.markdown("---")

        st.subheader("🔹 1. Receitas e Despesas FUNDEB")
        saldo     = tot_rec_periodo - tot_desp_vigente
        exec_perc = (tot_desp_vigente/tot_rec_periodo*100) if tot_rec_periodo>0 else 0

        t1, t2, t3 = st.columns(3)
        with t1: st.metric(f"Total Receitas ({meses_disponiveis[0]}–{meses_disponiveis[-1]})",
                            formar_real(tot_rec_periodo))
        with t2: st.metric("Total Despesas Liquidadas – Ano Vigente",
                            formar_real(tot_desp_vigente))
        with t3:
            delta_val = exec_perc if saldo >= 0 else -exec_perc
            st.metric("Saldo (Receitas − Despesas Vigentes)", formar_real(saldo),
                      delta=f"{delta_val:.1f}% Saldo", delta_color="normal")

        # ── Composição das Receitas FUNDEB (Rendimentos + VAAT + VAAR + ETI) ──
        st.markdown(
            "<p style='font-size:.82rem;color:#94A3B8;margin:6px 0 4px 0'>"
            "📊 <b>Composição das Receitas FUNDEB</b> — detalhamento por subcategoria</p>",
            unsafe_allow_html=True
        )
        _val_principal = soma(df_r_fundeb[df_r_fundeb['Subcategoria']=='Principal'], meses_disponiveis)
        _val_rend      = soma(df_r_fundeb[df_r_fundeb['Subcategoria']=='Rendimentos'], meses_disponiveis)
        _val_vaat      = soma(df_r_fundeb[df_r_fundeb['Subcategoria']=='VAAT'], meses_disponiveis)
        _val_vaar      = soma(df_r_fundeb[df_r_fundeb['Subcategoria']=='VAAR'], meses_disponiveis)
        _val_eti       = soma(df_r_fundeb[df_r_fundeb['Subcategoria']=='ETI'], meses_disponiveis)
        _c1, _c2, _c3, _c4, _c5 = st.columns(5)
        with _c1: st.metric("Principal", formar_real(_val_principal),
                             delta=f"{_val_principal/tot_rec_periodo*100:.1f}% do total" if tot_rec_periodo>0 else "—",
                             delta_color="off")
        with _c2: st.metric("Rendimentos FUNDEB", formar_real(_val_rend),
                             delta=f"{_val_rend/tot_rec_periodo*100:.1f}% do total" if tot_rec_periodo>0 else "—",
                             delta_color="off")
        with _c3: st.metric("VAAT (entra 70% e 4%)", formar_real(_val_vaat),
                             delta=f"{_val_vaat/tot_rec_periodo*100:.1f}% do total" if tot_rec_periodo>0 else "—",
                             delta_color="off")
        with _c4: st.metric("VAAR (só 4%)", formar_real(_val_vaar),
                             delta=f"{_val_vaar/tot_rec_periodo*100:.1f}% do total" if tot_rec_periodo>0 else "—",
                             delta_color="off")
        with _c5: st.metric("ETI (Tempo Integral)", formar_real(_val_eti),
                             delta=f"{_val_eti/tot_rec_periodo*100:.1f}% do total" if tot_rec_periodo>0 else "—",
                             delta_color="off")

        tipo_rd = st.segmented_control("Visualização:", ["Mensal","Acumulado"],
                                       default="Mensal", key="rd_btn_f")
        fig_rd = go.Figure()
        categorias_rec  = list(df_r_fundeb['Subcategoria'].unique())
        legendas_usadas = set()

        if tipo_rd == "Mensal":
            for m in meses_disponiveis:
                tot_rec_m  = soma(df_r_fundeb, [m])
                tot_desp_m = soma(df_df_fundeb[df_df_fundeb['Tipo']=='Liquidado'], [m])
                for cat in categorias_rec:
                    val = soma(df_r_fundeb[df_r_fundeb['Subcategoria']==cat], [m])
                    if val == 0: continue
                    desc_list = df_r_fundeb[df_r_fundeb['Subcategoria']==cat][
                        'Descrição da Receita'].unique().tolist()
                    show = f"rec_{cat}" not in legendas_usadas
                    legendas_usadas.add(f"rec_{cat}")
                    part = f"{val/tot_rec_m*100:.1f}%" if tot_rec_m>0 else "—"
                    fig_rd.add_trace(go.Bar(
                        name=cat, x=[[m],["Receitas"]], y=[val],
                        marker_color=COR_REC.get(cat,'#27ae60'),
                        legendgroup=f"rec_{cat}", showlegend=show,
                        text=formar_real(val),
                        textposition='inside', insidetextanchor='middle',
                        customdata=[[cat,"FUNDEB"," | ".join(desc_list),
                                     formar_real(val),formar_real(tot_rec_m),part,m]],
                        hovertemplate=(
                            "<span style='color:white;'>"
                            "<b>📥 %{customdata[6]} — Receita %{customdata[0]}</b><br>"
                            "Categoria: %{customdata[0]}<br>Fundo: %{customdata[1]}<br>"
                            "Rubrica(s): %{customdata[2]}<br>─────────────────────<br>"
                            "Valor: <b>%{customdata[3]}</b><br>"
                            "Total Rec. mês: %{customdata[4]}<br>"
                            "Participação: %{customdata[5]}</span><extra></extra>"
                        ),
                    ))
                for fonte_cod, label_desp in [('15407','FUNDEB 70% – Vigente'),
                                              ('15403','FUNDEB 30% – Vigente'),
                                              ('154071','FUNDEB 4% Principal (154071)'),
                                              ('154072','FUNDEB 4% Principal (154072)'),
                                              ('154271','FUNDEB 4% VAAT (154271)'),
                                              ('154272','FUNDEB 4% VAAT (154272)'),
                                              ('154371','FUNDEB 4% VAAR (154371)'),
                                              ('154372','FUNDEB 4% VAAR (154372)')]:
                    val = soma(df_df_fundeb[(df_df_fundeb['Fonte']==fonte_cod) &
                                            (df_df_fundeb['Tipo']=='Liquidado')], [m])
                    show = label_desp not in legendas_usadas
                    legendas_usadas.add(label_desp)
                    prop = f"{val/tot_desp_m*100:.1f}%" if tot_desp_m>0 else "—"
                    fig_rd.add_trace(go.Bar(
                        name=label_desp, x=[[m],["Despesas"]], y=[val],
                        marker_color=COR_DESP[label_desp],
                        legendgroup=label_desp, showlegend=show,
                        text=formar_real(val) if val>0 else "",
                        textposition='outside' if fonte_cod=='15403' else 'inside',
                        insidetextanchor='middle',
                        customdata=[[fonte_cod,"Liquidado – Ano Vigente",prop,
                                     formar_real(val),formar_real(tot_desp_m),prop,m]],
                        hovertemplate=(
                            "<span style='color:white;'>"
                            "<b>📤 %{customdata[6]} — %{customdata[0]}</b><br>"
                            "Fonte: %{customdata[0]}<br>Estágio: %{customdata[1]}<br>"
                            "─────────────────────<br>Valor: <b>%{customdata[3]}</b><br>"
                            "Total Desp. mês: %{customdata[4]}<br>"
                            "Participação: %{customdata[5]}</span><extra></extra>"
                        ),
                    ))
        else:
            for cat in categorias_rec:
                val = soma(df_r_fundeb[df_r_fundeb['Subcategoria']==cat], meses_disponiveis)
                if val == 0: continue
                desc_list = df_r_fundeb[df_r_fundeb['Subcategoria']==cat][
                    'Descrição da Receita'].unique().tolist()
                part = f"{val/tot_rec_periodo*100:.1f}%" if tot_rec_periodo>0 else "—"
                fig_rd.add_trace(go.Bar(
                    name=cat, x=[["Acumulado"],["Receitas"]], y=[val],
                    marker_color=COR_REC.get(cat,'#27ae60'),
                    legendgroup=f"rec_{cat}", showlegend=True,
                    text=formar_real(val),
                    textposition='inside', insidetextanchor='middle',
                    customdata=[[cat,"FUNDEB"," | ".join(desc_list),
                                 formar_real(val),formar_real(tot_rec_periodo),part]],
                    hovertemplate=(
                        "<span style='color:white;'>"
                        "<b>📥 Receita — %{customdata[0]}</b><br>"
                        "Categoria: %{customdata[0]}<br>Fundo: %{customdata[1]}<br>"
                        "Rubrica(s): %{customdata[2]}<br>─────────────────────<br>"
                        "Valor: <b>%{customdata[3]}</b><br>"
                        "Total Receitas: %{customdata[4]}<br>"
                        "Participação: %{customdata[5]}</span><extra></extra>"
                    ),
                ))
            for fonte_cod, label_desp in [('15407','FUNDEB 70% – Vigente'),
                                          ('15403','FUNDEB 30% – Vigente'),
                                          ('154071','FUNDEB 4% Principal (154071)'),
                                          ('154072','FUNDEB 4% Principal (154072)'),
                                          ('154271','FUNDEB 4% VAAT (154271)'),
                                          ('154272','FUNDEB 4% VAAT (154272)'),
                                          ('154371','FUNDEB 4% VAAR (154371)'),
                                          ('154372','FUNDEB 4% VAAR (154372)')]:
                val = soma(df_df_fundeb[(df_df_fundeb['Fonte']==fonte_cod) &
                                        (df_df_fundeb['Tipo']=='Liquidado')], meses_disponiveis)
                prop = f"{val/tot_desp_vigente*100:.1f}%" if tot_desp_vigente>0 else "—"
                fig_rd.add_trace(go.Bar(
                    name=label_desp, x=[["Acumulado"],["Despesas"]], y=[val],
                    marker_color=COR_DESP[label_desp],
                    legendgroup=label_desp, showlegend=True,
                    text=formar_real(val) if val>0 else "",
                    textposition='outside' if fonte_cod=='15403' else 'inside',
                    insidetextanchor='middle',
                    customdata=[[fonte_cod,"Liquidado – Ano Vigente",prop,
                                 formar_real(val),formar_real(tot_desp_vigente),prop]],
                    hovertemplate=(
                        "<span style='color:white;'>"
                        "<b>📤 Despesa — %{customdata[0]}</b><br>"
                        "Fonte: %{customdata[0]}<br>Estágio: %{customdata[1]}<br>"
                        "─────────────────────<br>Valor: <b>%{customdata[3]}</b><br>"
                        "Total Desp. vigentes: %{customdata[4]}<br>"
                        "Participação: %{customdata[5]}</span><extra></extra>"
                    ),
                ))

        fig_rd.update_layout(
            separators=",.", barmode='stack', hoverlabel=HOVER_STYLE,
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=-0.30, xanchor="center", x=0.5),
            height=500, yaxis=dict(showticklabels=False),
            uniformtext_minsize=9, uniformtext_mode='hide',
        )
        st.plotly_chart(fig_rd, use_container_width=True, config=CONFIG_PT)
        st.markdown("---")

        st.subheader("🔹 2. Índice de Aplicação em Pessoal (Mín. 70%)")
        tipo_70 = st.segmented_control("Visualização:", ["Mensal","Acumulado"],
                                       default="Mensal", key="tipo_70_btn")

        if tipo_70 == "Acumulado":
            a1, a2 = st.columns(2)
            with a1: st.metric("Base de Cálculo (Principal + Rendimentos + VAAT)",
                                formar_real(base_indice_70))
            with a2: st.metric("Despesas FUNDEB 70% – Liquidado",
                                formar_real(desp_70_vigente))
            metric_contabil("Aplicação em Pessoal (Mín. 70%)", perc_70_indice, 70.0)
            fig_70 = go.Figure()
            fig_70.add_trace(go.Bar(
                x=["Receita Base\n(Principal + Rendimentos + VAAT)"], y=[base_indice_70],
                name="Receita Base", marker_color="#003366",
                text=[formar_real(base_indice_70)],
                textposition='inside', insidetextanchor='middle',
                hovertemplate=("<span style='color:white;'><b>Receita Base FUNDEB</b><br>"
                               "Principal + Rendimentos + VAAT<br>"
                               "Valor: <b>"+formar_real(base_indice_70)+"</b></span><extra></extra>"),
            ))
            fig_70.add_trace(go.Bar(
                x=["Despesas 70%\n(Liquidado)"], y=[desp_15407],
                name="FUNDEB 70% (15407)", marker_color=COR_DESP['FUNDEB 70% – Vigente'],
                text=[formar_real(desp_15407)], textposition='inside', insidetextanchor='middle',
                hovertemplate=("<span style='color:white;'><b>FUNDEB 70% — Fonte 15407</b><br>"
                               "Liquidado: <b>"+formar_real(desp_15407)+"</b></span><extra></extra>"),
            ))
            for _fc, _lb, _cor in FUNDEB4_FONTES:
                if _fc in FUNDEB4_VAAR: continue   # VAAR não entra no 70%
                _v = desp_f4.get(_fc, 0.0)
                fig_70.add_trace(go.Bar(
                    x=["Despesas 70%\n(Liquidado)"], y=[_v], name=_lb, marker_color=_cor,
                    text=[formar_real(_v) if _v > 0 else ""], textposition='inside',
                    insidetextanchor='middle',
                    hovertemplate=("<span style='color:white;'><b>"+_lb+"</b><br>"
                                   "Liquidado: <b>"+formar_real(_v)+"</b><br>"
                                   "Compõe o índice dos 70%</span><extra></extra>"),
                ))
            fig_70.add_annotation(x="Despesas 70%\n(Liquidado)", y=desp_70_vigente,
                text=f"<b>{formar_real(desp_70_vigente)}</b> ({perc_70_indice:.2f}%)",
                showarrow=False, yshift=14, font=dict(size=13, color="#333"))
            fig_70.add_hline(y=base_indice_70*0.70, line_dash="dot", line_color="green",
                             annotation_text=f"Meta 70% = {formar_real(base_indice_70*0.70)}",
                             annotation_position="top left")
            fig_70.update_layout(
                separators=",.", barmode='stack', hoverlabel=HOVER_STYLE,
                yaxis=dict(showticklabels=False), showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=-0.25, xanchor="center", x=0.5),
                height=440, margin=dict(b=80),
            )
        else:
            _meses = meses_disponiveis
            _base_m = [soma(df_r_fundeb[df_r_fundeb['Subcategoria'].isin(
                            ['Principal','Rendimentos','VAAT'])], [m]) for m in _meses]
            fig_70 = go.Figure()
            fig_70.add_bar(x=_meses, y=_base_m, name="Receita Base",
                           marker_color="#003366", offsetgroup='rec')
            fig_70.add_bar(x=_meses, y=[_desp_f('15407', [m]) for m in _meses],
                           name="FUNDEB 70% (15407)",
                           marker_color=COR_DESP['FUNDEB 70% – Vigente'], offsetgroup='desp')
            for _fc, _lb, _cor in FUNDEB4_FONTES:
                if _fc in FUNDEB4_VAAR: continue   # VAAR não entra no 70%
                fig_70.add_bar(x=_meses, y=[_desp_f(_fc, [m]) for m in _meses],
                               name=_lb, marker_color=_cor, offsetgroup='desp')
            fig_70.update_layout(barmode='stack')
            # REGRA LINHA DE META: shapes com _OFFSET=0.22
            df_meta_70 = pd.DataFrame([
                {"Mês":m, "Meta 70%": soma(df_r_fundeb[df_r_fundeb['Subcategoria'].isin(
                    ['Principal','Rendimentos','VAAT'])],[m])*0.70}
                for m in meses_disponiveis
            ])
            _OFFSET = 0.22
            _shapes_70 = []
            for _i, _row in df_meta_70.iterrows():
                _meta = _row['Meta 70%']
                _shapes_70.append(dict(type='line', xref='x', yref='y',
                    x0=_i-_OFFSET, x1=_i+_OFFSET, y0=_meta, y1=_meta,
                    line=dict(color='green', dash='dot', width=2)))
                if _i < len(df_meta_70)-1:
                    _shapes_70.append(dict(type='line', xref='x', yref='y',
                        x0=_i+_OFFSET, x1=_i+1-_OFFSET,
                        y0=_meta, y1=df_meta_70.loc[_i+1,'Meta 70%'],
                        line=dict(color='green', dash='dot', width=2)))
            fig_70.update_layout(shapes=_shapes_70)
            fig_70.add_trace(go.Scatter(x=[None], y=[None], mode='lines',
                name='Meta 70% (Mensal)', showlegend=True,
                line=dict(color='green', dash='dot', width=2)))
            fig_70.update_traces(
                selector=dict(type='bar'), textposition='outside', hoverlabel=HOVER_STYLE,
                hovertemplate=("<span style='color:white;'><b>%{x} — %{data.name}</b><br>"
                               "Valor: <b>R$ %{y:,.2f}</b></span><extra></extra>")
            )
            fig_70.update_layout(
                separators=",.", yaxis=dict(showticklabels=False), xaxis_title=None,
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=-0.25, xanchor="center", x=0.5),
                height=460, margin=dict(b=90),
            )

        st.plotly_chart(fig_70, use_container_width=True, config=CONFIG_PT)
        st.markdown("---")

        st.subheader("🔹 3. Percentual Tempo Integral")
        meta_eti_perc = 4.0
        _base_eti = soma(
            df_r_fundeb[df_r_fundeb['Subcategoria'].isin(['Principal','Rendimentos','VAAT'])],
            meses_disponiveis
        )
        val_meta_eti = _base_eti * (meta_eti_perc/100)
        e1, e2 = st.columns(2)
        with e1: st.metric("Base para Cálculo ETI (Principal + Rendimentos + VAAT)",
                            formar_real(_base_eti))
        with e2: st.metric(f"Meta {meta_eti_perc:.0f}% (Referência ETI)",
                            formar_real(val_meta_eti))
        fig_eti = go.Figure()
        fig_eti.add_trace(go.Bar(
            x=["Base ETI\n(Principal + Rend. + VAAT)"], y=[_base_eti],
            name="Base ETI", marker_color="#003366",
            text=[formar_real(_base_eti)],
            textposition='inside', insidetextanchor='middle',
            hovertemplate=("<span style='color:white;'><b>Base de Cálculo ETI</b><br>"
                           "Principal + Rendimentos + VAAT<br>"
                           "(VAAR e ETI não entram no cálculo)<br>"
                           "Valor: <b>"+formar_real(_base_eti)+"</b></span><extra></extra>"),
        ))
        fig_eti.add_hline(
            y=val_meta_eti, line_dash="dot", line_color="#f39c12", line_width=2,
            annotation_text=f"Referência ETI {meta_eti_perc:.0f}% = {formar_real(val_meta_eti)}",
            annotation_position="top left"
        )
        fig_eti.update_layout(
            separators=",.", hoverlabel=HOVER_STYLE,
            yaxis=dict(showticklabels=False), showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=-0.30, xanchor="center", x=0.5),
            height=380,
        )
        st.plotly_chart(fig_eti, use_container_width=True, config=CONFIG_PT)

    # =========================================================================
    # SETOR RECURSOS PRÓPRIOS
    # =========================================================================
    elif st.session_state.setor == 'Recursos Próprios':
        st.markdown("<h1 style='text-align:left;'>📖 Itamogi — Recursos Próprios (25%)</h1>",
                    unsafe_allow_html=True)

        def obter_soma_rp(df, meses):
            col_map = {c.strip().lower():c for c in df.columns}
            cols = [col_map[m.lower()] for m in meses if m.lower() in col_map]
            return df[cols].sum().sum() if cols else 0.0

        ABREV_IMPOSTO = {
            'PROPRIEDADE PREDIAL E TERRITORIAL URBANA':'IPTU',
            'TRANSMISSÃO "INTER VIVOS"':'ITBI','TRANSMISSÃO INTER VIVOS':'ITBI',
            'RENDA - RETIDO NA FONTE':'IR','RENDA – RETIDO NA FONTE':'IR',
            'SERVIÇOS DE QUALQUER NATUREZA':'ISS',
            'FUNDO DE PARTICIPAÇÃO DOS MUNICÍPIOS':'FPM',
            'FUNDO DE PARTICIPAÇÃO DO MUNICÍPIOS':'FPM',
            'PROPRIEDADE TERRITORIAL RURAL':'ITR',
            'ICMS':'ICMS','IPVA':'IPVA','IPI':'IPI','INSS':'INSS',
        }

        def abrev_imposto(desc):
            du = str(desc).upper()
            du = du.replace('\u201c','"').replace('\u201d','"')\
                   .replace('\u2018',"'").replace('\u2019',"'")
            for longo, curto in ABREV_IMPOSTO.items():
                if longo in du:
                    if 'DÍVIDA ATIVA' in du and 'MULTAS' in du: return f"{curto} – D.A. M/J"
                    if 'DÍVIDA ATIVA' in du:                     return f"{curto} – D.A."
                    if 'MULTAS' in du:                           return f"{curto} – M/J"
                    if 'OUTROS RENDIMENTOS' in du:               return f"{curto} – Outros"
                    if 'DEZEMBRO' in du:                         return f"{curto} – Dez"
                    if 'JULHO' in du or 'SETEMBRO' in du:        return f"{curto} – Jul/Set"
                    return curto
            return desc.strip()[:20]

        def grupo_imposto(abrev):
            return abrev.split(' –')[0].strip()

        PALETA_RP = ['#1a7a4a','#27ae60','#17a589','#1abc9c',
                     '#2980b9','#1565c0','#0288d1','#00838f',
                     '#00acc1','#26c6da','#43a047','#66bb6a',
                     '#80cbc4','#4dd0e1']

        df_r_base = df_r[df_r['Categoria'].str.strip().isin(['Impostos','Cota-Parte'])].copy()
        df_r_base['Descrição da Receita'] = df_r_base['Descrição da Receita'].str.strip()
        df_r_base['Abrev'] = df_r_base['Descrição da Receita'].apply(abrev_imposto)
        df_r_base['Grupo'] = df_r_base['Abrev'].apply(grupo_imposto)

        df_r_grupo = df_r_base.groupby('Grupo')[meses_disponiveis].sum().reset_index()
        grupos_unicos = list(df_r_grupo['Grupo'].unique())
        mapa_cores_grupos = {g: PALETA_RP[i%len(PALETA_RP)] for i,g in enumerate(grupos_unicos)}

        df_r_ded = df_r[df_r['Categoria'].str.strip().str.startswith('Dedução', na=False)].copy()

        prev_total_rp = df_r_base['Orçado Receitas'].sum()
        tot_rec_base  = obter_soma_rp(df_r_base, meses_disponiveis)
        tot_deducoes  = abs(obter_soma_rp(df_r_ded, meses_disponiveis))
        meta_25_valor = tot_rec_base * 0.25

        fase_despesa = st.segmented_control(
            " (Impacta Indicadores Superiores):",
            ["Empenhado","Liquidado","Pago"], default="Liquidado", key="fase_desp_rp")
        df_df_15001 = df_df_raw[(df_df_raw['Fonte']=='15001') &
                                 (df_df_raw['Tipo']==fase_despesa)].copy()

        _desconto_fundeb_nao_util = 0.0
        _desconto_superavit_ant   = 32_015.17
        _total_descontos_25       = _desconto_fundeb_nao_util + _desconto_superavit_ant

        total_desp_15001 = df_df_15001[meses_disponiveis].sum().sum()
        esforco_total    = max(0.0, total_desp_15001 + tot_deducoes - _total_descontos_25)
        perc_25          = (esforco_total/tot_rec_base*100) if tot_rec_base>0 else 0.0
        saldo_nec_25     = max(0.0, meta_25_valor - esforco_total)

        df_15000_outras = df_df_raw[
            df_df_raw['Fonte'].str.match(r'^150\d*$', na=False) &
            (df_df_raw['Fonte']!='15001') & (df_df_raw['Tipo']=='Liquidado')].copy()
        val_outras_fontes = df_15000_outras[meses_disponiveis].sum().sum()

        st.markdown("##### Previsões e Arrecadação")
        c1, c2, c3 = st.columns(3)
        with c1: st.metric("Previsão Orçamentária — Impostos e Cota-Parte (Janeiro a Dezembro)",
                            formar_real(prev_total_rp))
        with c2: st.metric(f"Receitas Arrecadadas ({meses_disponiveis[0]}–{meses_disponiveis[-1]})",
                            formar_real(tot_rec_base))
        with c3: st.metric("Meta 25% (sobre o arrecadado)", formar_real(meta_25_valor))
        st.markdown("---")

        st.subheader("🔹 Receitas Recursos Próprios (Impostos e Cota-Parte)")
        view_rp = st.segmented_control("Visualização Receitas:", ["Mensal","Acumulado"],
                                       default="Mensal", key="view_rp")

        lista_completa = ["📊 Acumulado Geral"] + grupos_unicos
        if 'idx_nav_rp' not in st.session_state: st.session_state.idx_nav_rp = 0

        grid = st.columns([0.5,1.2,1.2,1.2,1.2,1.2,0.5])
        with grid[0]:
            if st.button("◀", key="rp_left"):
                st.session_state.idx_nav_rp = max(0, st.session_state.idx_nav_rp-5)
                st.rerun()
        fim_idx = min(st.session_state.idx_nav_rp+5, len(lista_completa))
        fatia   = lista_completa[st.session_state.idx_nav_rp:fim_idx]
        for i, item in enumerate(fatia):
            with grid[i+1]:
                label = item.replace("📊 ","") if "📊" in item else item
                if st.button(label, key=f"rp_btn_{item}", help=item, use_container_width=True):
                    st.session_state['ativo_rp'] = item.replace("📊 ","")
                    st.rerun()
        with grid[6]:
            if st.button("▶", key="rp_right"):
                if st.session_state.idx_nav_rp+5 < len(lista_completa):
                    st.session_state.idx_nav_rp += 5
                    st.rerun()

        ativo = st.session_state.get('ativo_rp', "Acumulado Geral")
        st.markdown(f"#### 📈 {ativo}")

        if view_rp == "Acumulado":
            if ativo == "Acumulado Geral":
                df_acum = df_r_grupo.copy()
                df_acum['Valor'] = df_acum[meses_disponiveis].sum(axis=1)
                df_acum = df_acum.sort_values('Valor', ascending=False)
                tot_acum = df_acum['Valor'].sum()
                fig_rp = px.bar(df_acum, x='Grupo', y='Valor', color='Grupo',
                                text_auto='.3s', color_discrete_map=mapa_cores_grupos)
                fig_rp.update_traces(
                    hovertemplate=(
                        "<span style='color:white;'><b>%{x}</b><br>"
                        "Imposto: %{data.name}<br>"
                        "Valor: <b>R$ %{y:,.2f}</b><br>"
                        f"Total Geral: <b>{formar_real(tot_acum)}</b>"
                        "</span><extra></extra>"
                    ), hoverlabel=HOVER_STYLE
                )
            else:
                row = df_r_grupo[df_r_grupo['Grupo']==ativo]
                val = row[meses_disponiveis].sum().sum() if len(row)>0 else 0
                fig_rp = px.bar(x=[ativo], y=[val], text_auto='.3s',
                                color_discrete_sequence=[mapa_cores_grupos.get(ativo,'#003366')])
                fig_rp.update_traces(
                    hovertemplate=(
                        "<span style='color:white;'>"
                        f"<b>{ativo}</b><br>"
                        "Valor Acumulado: <b>R$ %{y:,.2f}</b>"
                        "</span><extra></extra>"
                    ), hoverlabel=HOVER_STYLE
                )
        else:
            if ativo == "Acumulado Geral":
                totais_mes = {m: df_r_base[m].sum() for m in meses_disponiveis}
                dados_m = []
                for m in meses_disponiveis:
                    for _, row in df_r_grupo.iterrows():
                        dados_m.append({"Mês":m,"Imposto":row['Grupo'],"Valor":row[m],
                                         "TotalMes":totais_mes[m]})
                df_dm = pd.DataFrame(dados_m)
                fig_rp = px.bar(df_dm, x='Mês', y='Valor', color='Imposto',
                                barmode='stack', text_auto='.2s',
                                color_discrete_map=mapa_cores_grupos,
                                category_orders={"Mês":ORDEM_MESES},
                                custom_data=['TotalMes','Imposto'])
                fig_rp.update_traces(
                    hovertemplate=(
                        "<span style='color:white;'><b>%{x}</b><br>"
                        "Imposto: %{customdata[1]}<br>"
                        "Valor: <b>R$ %{y:,.2f}</b><br>"
                        "Total do Mês: <b>R$ %{customdata[0]:,.2f}</b>"
                        "</span><extra></extra>"
                    ), hoverlabel=HOVER_STYLE
                )
            else:
                row = df_r_grupo[df_r_grupo['Grupo']==ativo]
                dados_m = [{"Mês":m,"Valor":row[m].sum() if len(row)>0 else 0}
                           for m in meses_disponiveis]
                fig_rp = px.bar(pd.DataFrame(dados_m), x='Mês', y='Valor', text_auto='.2s',
                                color_discrete_sequence=[mapa_cores_grupos.get(ativo,'#003366')],
                                category_orders={"Mês":ORDEM_MESES})
                fig_rp.update_traces(
                    hovertemplate=(
                        "<span style='color:white;'><b>%{x}</b><br>"
                        f"Imposto: {ativo}<br>"
                        "Valor: <b>R$ %{y:,.2f}</b>"
                        "</span><extra></extra>"
                    ), hoverlabel=HOVER_STYLE
                )

        fig_rp.update_layout(separators=",.", yaxis=dict(showticklabels=False))
        st.plotly_chart(fig_rp, use_container_width=True, config=CONFIG_PT)
        st.markdown("---")

        st.subheader("🔹 Despesas Fonte 15001")
        st.markdown("Detalhamento por Estágio (Empenhado, Liquidado, Pago)")
        view_desp = st.segmented_control("Visualização Despesas:", ["Mensal","Acumulado"],
                                         default="Mensal", key="view_desp")
        df_15001_todas = df_df_raw[(df_df_raw['Fonte']=='15001') &
                                    (df_df_raw['Tipo'].isin(['Empenhado','Liquidado','Pago']))].copy()

        if view_desp == "Acumulado":
            total_rp_acum = df_15001_todas[meses_disponiveis].sum().sum()
            df_desp_plot  = []
            for fase in ["Empenhado","Liquidado","Pago"]:
                val  = df_15001_todas[df_15001_todas['Tipo']==fase][meses_disponiveis].sum().sum()
                prop = (val/total_rp_acum*100) if total_rp_acum>0 else 0
                df_desp_plot.append({"Fase":fase,"Valor":val,
                                     "Proporção":f"{prop:.2f}%","Dedução":tot_deducoes,"Despesa":val})
            df_desp_plot = pd.DataFrame(df_desp_plot)
            df_desp_plot['Fase'] = pd.Categorical(df_desp_plot['Fase'],["Empenhado","Liquidado","Pago"])
            fig_d = px.bar(df_desp_plot, x='Fase', y='Valor', color='Fase', text_auto='.3s',
                           custom_data=['Proporção','Dedução','Despesa'],
                           color_discrete_map={'Empenhado':'#fa3d3d','Liquidado':'#860000','Pago':'#470000'})
        else:
            dados_d_m = []
            for m in meses_disponiveis:
                col_d   = m if m in df_15001_todas.columns else None
                col_ded = m if m in df_r_ded.columns else None
                total_m = df_15001_todas[col_d].sum() if col_d else 0
                ded_m   = abs(df_r_ded[col_ded].sum()) if col_ded else 0
                for fase in ['Empenhado','Liquidado','Pago']:
                    val  = df_15001_todas[df_15001_todas['Tipo']==fase][col_d].sum() if col_d else 0
                    prop = (val/total_m*100) if total_m>0 else 0
                    dados_d_m.append({"Mês":m,"Fase":fase,"Valor":val,
                                      "Proporção":f"{prop:.2f}%","Dedução":ded_m,"Despesa":val})
            df_dados_d_m = pd.DataFrame(dados_d_m)
            df_dados_d_m['Fase'] = pd.Categorical(df_dados_d_m['Fase'],["Empenhado","Liquidado","Pago"])
            fig_d = px.bar(df_dados_d_m, x='Mês', y='Valor', color='Fase', barmode='group',
                           text_auto='.2s', custom_data=['Proporção','Dedução','Despesa'],
                           color_discrete_map={'Empenhado':'#fa3d3d','Liquidado':'#860000','Pago':'#470000'},
                           category_orders={"Mês":ORDEM_MESES,"Fase":["Empenhado","Liquidado","Pago"]})

        fig_d.update_traces(
            hovertemplate=("<span style='color:white;'><b>%{x}</b><br>"
                           "Estágio: %{fullData.name}<br>"
                           "Valor (15001): R$ %{customdata[2]:,.2f}<br>"
                           "Dedução FUNDEB: R$ %{customdata[1]:,.2f}<br>"
                           "Proporção: %{customdata[0]}</span><extra></extra>"),
            hoverlabel=HOVER_STYLE)
        fig_d.update_layout(separators=",.", yaxis=dict(showticklabels=False))
        st.plotly_chart(fig_d, use_container_width=True, config=CONFIG_PT)
        st.markdown("---")

        st.subheader("🔹 Análise Comparativa e Meta (Mínimo 25%)")
        view_meta = st.segmented_control("Visualização Meta:", ["Mensal","Acumulado"],
                                         default="Mensal", key="view_meta")

        if view_meta == "Acumulado":
            idx1, idx2, idx3 = st.columns(3)
            with idx1: st.metric("Receitas Base (Impostos + Cota-Parte)", formar_real(tot_rec_base))
            with idx2: st.metric(
                f"Esforço Líquido ({fase_despesa} 15001 + Deduções − Desconto)",
                formar_real(esforco_total),
                delta=f"−{formar_real(_total_descontos_25)} descontados",
                delta_color="off"
            )
            with idx3: metric_contabil("Índice de Aplicação (Mín. 25%)", perc_25, 25.0)

            prop_desp = (total_desp_15001/esforco_total*100) if esforco_total>0 else 0
            prop_ded  = (tot_deducoes/esforco_total*100)    if esforco_total>0 else 0
            fig_meta  = go.Figure()
            fig_meta.add_trace(go.Bar(
                x=["Receitas Base"], y=[tot_rec_base], name="Receitas Base",
                marker_color="#003366", text=[formar_real(tot_rec_base)],
                textposition='inside', insidetextanchor='middle',
                hovertemplate=("<span style='color:white;'><b>Receitas Base</b><br>"
                               "Impostos + Cota-Parte<br>Valor: <b>"+formar_real(tot_rec_base)+"</b></span><extra></extra>"),
            ))
            fig_meta.add_trace(go.Bar(
                x=["Aplicação Total"], y=[tot_deducoes],
                name="Dedução FUNDEB", marker_color="#f39c12",
                text=[""], textposition='inside',
                customdata=[[formar_real(tot_deducoes), f"{prop_ded:.1f}%",
                             formar_real(esforco_total)]],
                hovertemplate=(
                    "<span style='color:white;'><b>Dedução FUNDEB</b><br>"
                    "Valor: <b>%{customdata[0]}</b><br>"
                    "% do esforço: %{customdata[1]}<br>"
                    "─────────────────────<br>"
                    "Esforço Total: <b>%{customdata[2]}</b></span><extra></extra>"
                ),
            ))
            fig_meta.add_trace(go.Bar(
                x=["Aplicação Total"], y=[total_desp_15001],
                name=f"Despesa 15001 ({fase_despesa})", marker_color="#860000",
                text=[""], textposition='inside',
                customdata=[[formar_real(total_desp_15001), f"{prop_desp:.1f}%", fase_despesa,
                             formar_real(_desconto_fundeb_nao_util),
                             formar_real(_desconto_superavit_ant),
                             formar_real(_total_descontos_25)]],
                hovertemplate=(
                    "<span style='color:white;'><b>Despesa Fonte 15001</b><br>"
                    "Estágio: %{customdata[2]}<br>"
                    "Valor: <b>%{customdata[0]}</b><br>"
                    "% do esforço: %{customdata[1]}<br>"
                    "─────────────────────<br>"
                    "🔻 Descontos aplicados:<br>"
                    "FUNDEB não util.: %{customdata[3]}<br>"
                    "Superávit anos ant.: %{customdata[4]}<br>"
                    "Total descontado: <b>%{customdata[5]}</b></span><extra></extra>"
                ),
            ))
            fig_meta.add_hline(y=tot_rec_base*0.25, line_dash="dash", line_color="#f39c12",
                               annotation_text=f"Meta 25% = {formar_real(tot_rec_base*0.25)}",
                               annotation_position="top left")
            if val_outras_fontes>0:
                fig_meta.add_annotation(x="Aplicação Total", y=esforco_total*1.05,
                    text=f"⚠️ Outras fontes (anos ant.): {formar_real(val_outras_fontes)}",
                    showarrow=False, font=dict(color="#aaaaaa",size=11))
            fig_meta.update_layout(separators=",.", barmode='stack', hoverlabel=HOVER_STYLE,
                                   yaxis=dict(showticklabels=False), showlegend=True,
                                   legend=dict(orientation="h",yanchor="bottom",y=-0.20,
                                               xanchor="center",x=0.5), height=450)
        else:
            dados_meta_m = []
            for m in meses_disponiveis:
                col_b = m if m in df_r_base.columns else None
                col_d = m if m in df_df_15001.columns else None
                col_e = m if m in df_r_ded.columns else None
                r_m   = df_r_base[col_b].sum() if col_b else 0
                d_m   = df_df_15001[col_d].sum() if col_d else 0
                ded_m = abs(df_r_ded[col_e].sum()) if col_e else 0
                total_desp_m = d_m + ded_m
                perc_m = (total_desp_m / r_m * 100) if r_m > 0 else 0
                dados_meta_m += [
                    {"Mês":m,"Tipo":"Receitas (Impostos + Cota-Parte)","Valor":r_m,
                     "DetalheA":formar_real(r_m),"DetalheB":"—","Total":r_m,"Perc":"100%"},
                    {"Mês":m,"Tipo":"Despesas (15001 + Deduções)","Valor":total_desp_m,
                     "DetalheA":formar_real(d_m),"DetalheB":formar_real(ded_m),
                     "Total":total_desp_m,"Perc":f"{perc_m:.1f}% das receitas"},
                ]
            df_meta_m = pd.DataFrame(dados_meta_m)
            fig_meta = px.bar(
                df_meta_m, x='Mês', y='Valor', color='Tipo', barmode='group',
                custom_data=['DetalheA','DetalheB','Perc'],
                color_discrete_map={
                    "Receitas (Impostos + Cota-Parte)": "#003366",
                    "Despesas (15001 + Deduções)":      "#860000",
                },
                text='Valor', category_orders={"Mês":ORDEM_MESES}
            )
            fig_meta.update_traces(
                texttemplate="R$ %{y:,.0f}",
                textposition='inside', insidetextanchor='middle',
                hovertemplate=(
                    "<span style='color:white;'>"
                    "<b>%{x} — %{data.name}</b><br>"
                    "Total: <b>R$ %{y:,.2f}</b><br>"
                    "── Detalhamento ──<br>"
                    "%{customdata[0]}<br>%{customdata[1]}<br>%{customdata[2]}"
                    "</span><extra></extra>"
                ),
                hoverlabel=HOVER_STYLE
            )
            # REGRA LINHA DE META: shapes com _OFFSET=0.22
            df_linha = df_meta_m[df_meta_m['Tipo']=='Receitas (Impostos + Cota-Parte)'].copy()
            df_linha = df_linha.reset_index(drop=True)
            df_linha['Meta 25%'] = df_linha['Valor'] * 0.25
            _OFFSET = 0.22
            _shapes_25 = []
            for _i, _row in df_linha.iterrows():
                _meta = _row['Meta 25%']
                _shapes_25.append(dict(type='line', xref='x', yref='y',
                    x0=_i-_OFFSET, x1=_i+_OFFSET, y0=_meta, y1=_meta,
                    line=dict(color='#f39c12', dash='dash', width=2)))
                if _i < len(df_linha)-1:
                    _shapes_25.append(dict(type='line', xref='x', yref='y',
                        x0=_i+_OFFSET, x1=_i+1-_OFFSET,
                        y0=_meta, y1=df_linha.loc[_i+1,'Meta 25%'],
                        line=dict(color='#f39c12', dash='dash', width=2)))
            fig_meta.update_layout(shapes=_shapes_25)
            fig_meta.add_trace(go.Scatter(x=[None], y=[None], mode='lines',
                name='Meta 25% (Mensal)', showlegend=True,
                line=dict(color='#f39c12', dash='dash', width=2)))
            fig_meta.update_layout(
                separators=",.", yaxis=dict(showticklabels=False), showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=-0.25, xanchor="center", x=0.5)
            )

        st.plotly_chart(fig_meta, use_container_width=True, config=CONFIG_PT)

    # =========================================================================
    # SETOR RECURSOS VINCULADOS
    # =========================================================================
    elif st.session_state.setor == 'Recursos Vinculados':
        st.markdown("<h1 style='text-align:left;'>📖 Itamogi — Recursos Vinculados</h1>",
                    unsafe_allow_html=True)

        mapa_desp = {'PNAE':['1552'],'PNATE':['1553'],'PTE':['1576'],'QESE':['1550']}
        programas = ['PNAE','PNATE','PTE','QESE']
        COR_PROG  = {'PNAE':'#1a7a4a','PNATE':'#17a589','PTE':'#2980b9','QESE':'#1565c0'}
        COR_DESP_V = '#860000'

        def soma_vinc(df, meses):
            col_map = {c.strip().lower():c for c in df.columns}
            cols = [col_map[m.lower()] for m in meses if m.lower() in col_map]
            return df[cols].sum().sum() if cols else 0.0

        df_r_vinc = df_r[df_r['Descrição da Receita'].str.upper().str.strip().isin(programas)].copy()
        st.markdown("---")

        for prog in programas:
            df_prog_r = df_r_vinc[df_r_vinc['Descrição da Receita'].str.upper().str.strip()==prog].copy()

            rep_2025     = df_prog_r['2025'].sum()             if '2025'             in df_prog_r.columns else 0
            prev_repasse = df_prog_r['Repasse'].sum()          if 'Repasse'          in df_prog_r.columns else 0
            orcado_2026  = df_prog_r['Orçado Receitas'].sum()  if 'Orçado Receitas'  in df_prog_r.columns else 0
            desp_liq     = df_df_raw[df_df_raw['Fonte'].isin(mapa_desp[prog]) &
                                      (df_df_raw['Tipo']=='Liquidado')][meses_disponiveis].sum().sum()

            st.markdown(f"<h4 style='color:{COR_PROG[prog]};margin-bottom:4px;'>"
                        f"📊 Programa: {prog}</h4>", unsafe_allow_html=True)
            c1, c2, c3 = st.columns(3)
            with c1: st.metric("Arrecadado em 2025", formar_real(rep_2025))
            with c2: st.metric("Previsão de Repasse", formar_real(prev_repasse))
            with c3: st.metric("Orçado 2026 (Município)", formar_real(orcado_2026))

            tipo_vinc = st.segmented_control(
                "Visualização:", ["Mensal","Acumulado"],
                default="Mensal", key=f"vinc_btn_{prog}"
            )

            if tipo_vinc == "Mensal":
                dados_m = []
                for m in meses_disponiveis:
                    col_r  = m if m in df_prog_r.columns else None
                    col_df = m if m in df_df_raw.columns else None
                    rec_m  = df_prog_r[col_r].sum() if col_r else 0.0
                    desp_m = df_df_raw[df_df_raw['Fonte'].isin(mapa_desp[prog]) &
                                        (df_df_raw['Tipo']=='Liquidado')][col_df].sum() if col_df else 0.0
                    dados_m += [{"Mês":m,"Tipo":"Receita","Valor":rec_m},
                                 {"Mês":m,"Tipo":"Despesa (Liquidado)","Valor":desp_m}]
                fig_vinc = px.bar(pd.DataFrame(dados_m), x='Mês', y='Valor', color='Tipo',
                                  barmode='group', text_auto='.2s',
                                  color_discrete_map={'Receita':COR_PROG[prog],'Despesa (Liquidado)':COR_DESP_V},
                                  category_orders={"Mês":ORDEM_MESES})
                fig_vinc.update_traces(
                    selector=dict(type='bar'), textposition='outside', hoverlabel=HOVER_STYLE,
                    hovertemplate=("<span style='color:white;'><b>%{x}</b><br>"
                                   "Programa: "+prog+"<br>Tipo: %{data.name}<br>"
                                   "Valor: <b>R$ %{y:,.2f}</b></span><extra></extra>"))
                fig_vinc.update_layout(
                    separators=",.", yaxis=dict(showticklabels=False,title=None),
                    xaxis_title=None, showlegend=True,
                    legend=dict(orientation="h",yanchor="bottom",y=-0.30,
                                xanchor="center",x=0.5), height=380)
            else:
                rec_acum = soma_vinc(df_prog_r, meses_disponiveis)
                fig_vinc = go.Figure()
                fig_vinc.add_trace(go.Bar(
                    x=[f"Receita (Jan–{meses_disponiveis[-1][:3]})"], y=[rec_acum],
                    name="Receita", marker_color=COR_PROG[prog],
                    text=[formar_real(rec_acum)], textposition='outside',
                    hovertemplate=("<span style='color:white;'><b>Receita Acumulada</b><br>"
                                   "Programa: "+prog+"<br>Valor: <b>"+formar_real(rec_acum)+"</b></span><extra></extra>"),
                ))
                fig_vinc.add_trace(go.Bar(
                    x=["Despesa (Liquidado)"], y=[desp_liq],
                    name="Despesa (Liquidado)", marker_color=COR_DESP_V,
                    text=[formar_real(desp_liq)], textposition='outside',
                    hovertemplate=("<span style='color:white;'><b>Despesa Liquidada</b><br>"
                                   "Programa: "+prog+"<br>Valor: <b>"+formar_real(desp_liq)+"</b></span><extra></extra>"),
                ))
                fig_vinc.update_layout(
                    separators=",.", barmode='group',
                    bargap=0.15, bargroupgap=0.05,
                    yaxis=dict(showticklabels=False,title=None),
                    xaxis_title=None, showlegend=True, hoverlabel=HOVER_STYLE,
                    legend=dict(orientation="h",yanchor="bottom",y=-0.30,
                                xanchor="center",x=0.5), height=380)

            st.plotly_chart(fig_vinc, use_container_width=True, config=CONFIG_PT)
            st.markdown("---")

    # =========================================================================
    # SETOR VISÃO MACRO
    # =========================================================================
    elif st.session_state.setor == 'Visão Macro':
        st.markdown("<h1 style='text-align:left;'>📖 Itamogi — Visão Macro da Educação</h1>",
                    unsafe_allow_html=True)
        st.markdown("---")

        # Dinâmico: usa meses_disponiveis
        liq_cols = [f"{m}_Liquidado" for m in meses_disponiveis
                    if f"{m}_Liquidado" in df_f_raw.columns]

        CAPITAL_ELEMENTOS = ['Obras e Instalações', 'Equipamentos e Materiais Permanentes']
        df_macro = df_f_raw.copy()
        df_macro['Natureza'] = df_macro['Elemento'].apply(
            lambda x: 'Capital' if str(x).strip() in CAPITAL_ELEMENTOS else 'Custeio'
        )

        total_capital = df_macro[df_macro['Natureza']=='Capital'][liq_cols].sum().sum()
        total_custeio = df_macro[df_macro['Natureza']=='Custeio'][liq_cols].sum().sum()
        total_macro   = total_capital + total_custeio

        m1, m2, m3 = st.columns(3)
        with m1: st.metric(f"Total Liquidado (Jan–{meses_disponiveis[-1][:3]})", formar_real(total_macro))
        with m2: st.metric("Capital Liquidado", formar_real(total_capital),
                           delta=f"{total_capital/total_macro*100:.1f}% do total" if total_macro>0 else "—",
                           delta_color="off")
        with m3: st.metric("Custeio Liquidado", formar_real(total_custeio),
                           delta=f"{total_custeio/total_macro*100:.1f}% do total" if total_macro>0 else "—",
                           delta_color="off")
        st.markdown("---")

        st.subheader(f"🔹 1. Capital × Custeio (Liquidado Jan–{meses_disponiveis[-1][:3]})")
        df_pizza = pd.DataFrame([
            {"Natureza":"Capital","Valor":total_capital},
            {"Natureza":"Custeio","Valor":total_custeio},
        ])
        df_pizza = df_pizza[df_pizza['Valor']>0]
        fig_macro_pizza = px.pie(
            df_pizza, values='Valor', names='Natureza', hole=0.42,
            color='Natureza', color_discrete_map={'Capital':'#e74c3c','Custeio':'#1a7a4a'},
        )
        fig_macro_pizza.update_traces(
            textinfo='percent+label', textposition='inside',
            hovertemplate=(
                "<span style='color:white;'><b>%{label}</b><br>"
                "Valor: <b>R$ %{value:,.2f}</b><br>"
                "Participação: <b>%{percent}</b></span><extra></extra>"
            ),
            hoverlabel=HOVER_STYLE,
        )
        fig_macro_pizza.update_layout(
            separators=",.", showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=-0.15, xanchor="center", x=0.5),
            height=420, margin=dict(t=40, b=60),
        )
        _, col_pizza, _ = st.columns([1,2,1])
        with col_pizza:
            st.plotly_chart(fig_macro_pizza, use_container_width=True, config=CONFIG_PT)
        st.markdown("---")

        st.subheader("🔹 2. Liquidado por Elemento")
        df_elem = df_macro.groupby(['Elemento','Natureza'])[liq_cols].sum().reset_index()
        df_elem['Total'] = df_elem[liq_cols].sum(axis=1)
        df_elem = df_elem[df_elem['Total']>0].sort_values('Total', ascending=True)
        fig_macro_elem = px.bar(
            df_elem, x='Total', y='Elemento', orientation='h',
            color='Natureza', color_discrete_map={'Capital':'#e74c3c','Custeio':'#1a7a4a'},
            text='Total',
        )
        fig_macro_elem.update_traces(
            texttemplate="R$ %{x:,.0f}", textposition='outside',
            hovertemplate=(
                "<span style='color:white;'><b>%{y}</b><br>"
                "Natureza: %{data.name}<br>"
                "Liquidado: <b>R$ %{x:,.2f}</b></span><extra></extra>"
            ),
            hoverlabel=HOVER_STYLE,
        )
        fig_macro_elem.update_layout(
            separators=",.", xaxis=dict(showticklabels=False, title=None),
            yaxis=dict(title=None), showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=-0.15, xanchor="center", x=0.5),
            height=520, margin=dict(r=200),
        )
        st.plotly_chart(fig_macro_elem, use_container_width=True, config=CONFIG_PT)

    # =========================================================================
    # SETOR FOLHA DE PAGAMENTO
    # =========================================================================
    elif st.session_state.setor == 'Folha de Pagamento':
        st.markdown("<h1 style='text-align:left;'>📖 Itamogi — Folha de Pagamento</h1>",
                    unsafe_allow_html=True)
        st.markdown("---")

        FOLHA_ELEMENTOS = [
            'Vencimentos e Vantagens Fixas - Pessoal Civil',
            'Obrigações Patronais',
            'Contratação por tempo Determinado',
            'Outras Despesas Variáveis - Pessoal Civil',
            'Indenizações e Restituições Trabalhistas',
            'Auxílio-alimentação',
            '- Aposentadorias, Reserva Remunerada e Reformas',
            '- OBRIGAÇÕES TRIBUTÁRIAS E CONTRIBUTIVAS',  # ← com traço (grafia real)
            'OBRIGAÇÕES TRIBUTÁRIAS E CONTRIBUTIVAS',    # ← sem traço (variante)
            'Diárias - Pessoal Civil',
            'Outros Auxílios  financeiros PF',
        ]
        # Dinâmico: usa meses_disponiveis
        liq_cols_f = [f"{m}_Liquidado" for m in meses_disponiveis
                      if f"{m}_Liquidado" in df_f_raw.columns]

        df_folha = df_f_raw[df_f_raw['Elemento'].isin(FOLHA_ELEMENTOS)].copy()

        def origem_fonte(f):
            if f == '15407': return 'FUNDEB 70%'
            if f == '15403': return 'FUNDEB 30%'
            if f == '25407': return 'FUNDEB 70% – Superávit'
            if f == '25403': return 'FUNDEB 30% – Superávit'
            if f == '2540':  return 'FUNDEB – Superávit (2540)'
            if f == '25427': return 'FUNDEB – Superávit (25427)'
            if f == '25467': return 'FUNDEB – Superávit (25467)'
            if f == '15001': return 'Rec. Próprios (15001)'
            if f == '1500':  return 'Rec. Próprios (1500)'
            return f'Fonte {f}'

        df_folha['Origem'] = df_folha['Fonte'].apply(origem_fonte)

        total_folha  = df_folha[liq_cols_f].sum().sum()
        total_fund70 = df_folha[df_folha['Origem']=='FUNDEB 70%'][liq_cols_f].sum().sum()
        total_fund30 = df_folha[df_folha['Origem']=='FUNDEB 30%'][liq_cols_f].sum().sum()
        total_rp     = df_folha[df_folha['Origem'].str.startswith('Rec. Próprios', na=False)][liq_cols_f].sum().sum()
        total_sup    = df_folha[df_folha['Origem'].str.contains('Superávit', na=False)][liq_cols_f].sum().sum()

        f1, f2, f3, f4 = st.columns(4)
        with f1: st.metric(f"Total Folha (Jan–{meses_disponiveis[-1][:3]})", formar_real(total_folha))
        with f2: st.metric("FUNDEB 70% (Fonte 15407)", formar_real(total_fund70),
                           delta=f"{total_fund70/total_folha*100:.1f}%" if total_folha>0 else "—",
                           delta_color="off")
        with f3: st.metric("Recursos Próprios (15001/1500)", formar_real(total_rp),
                           delta=f"{total_rp/total_folha*100:.1f}%" if total_folha>0 else "—",
                           delta_color="off")
        with f4: st.metric("FUNDEB 30% (Fonte 15403)", formar_real(total_fund30),
                           delta=f"{total_fund30/total_folha*100:.1f}%" if total_folha>0 else "—",
                           delta_color="off")
        st.markdown("---")

        st.subheader("🔹 1. Origem dos Recursos — Folha de Pagamento")
        df_orig = (df_folha.groupby('Origem')[liq_cols_f].sum()
                   .sum(axis=1).reset_index().rename(columns={0:'Valor'}))
        df_orig = df_orig[df_orig['Valor']>0]

        COR_ORIGEM = {
            'FUNDEB 70%':                '#4a0000',
            'FUNDEB 30%':                '#ff1744',
            'FUNDEB 70% – Superávit':    '#b71c1c',
            'FUNDEB 30% – Superávit':    '#ff6d00',
            'FUNDEB – Superávit (2540)': '#e65100',
            'FUNDEB – Superávit (25427)':'#bf360c',
            'FUNDEB – Superávit (25467)':'#ff8a65',
            'Rec. Próprios (15001)':     '#1a7a4a',
            'Rec. Próprios (1500)':      '#43a047',
        }
        fig_folha_pizza = px.pie(
            df_orig, values='Valor', names='Origem', hole=0.42,
            color='Origem', color_discrete_map=COR_ORIGEM,
        )
        fig_folha_pizza.update_traces(
            textinfo='percent+label', textposition='inside',
            hovertemplate=(
                "<span style='color:white;'><b>%{label}</b><br>"
                "Valor: <b>R$ %{value:,.2f}</b><br>"
                "Participação: <b>%{percent}</b></span><extra></extra>"
            ),
            hoverlabel=HOVER_STYLE,
        )
        fig_folha_pizza.update_layout(
            separators=",.", showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=-0.15, xanchor="center", x=0.5),
            height=420, margin=dict(t=40, b=60),
        )
        _, col_fpizza, _ = st.columns([1,2,1])
        with col_fpizza:
            st.plotly_chart(fig_folha_pizza, use_container_width=True, config=CONFIG_PT)
        st.markdown("---")

        st.subheader("🔹 2. Liquidado por Elemento da Folha")
        # Total por elemento (barra única, sem divisão por origem)
        df_elem_total = df_folha.groupby('Elemento')[liq_cols_f].sum().reset_index()
        df_elem_total['Total'] = df_elem_total[liq_cols_f].sum(axis=1)
        df_elem_total = df_elem_total[df_elem_total['Total']>0].sort_values('Total', ascending=True)

        _det_by_elem = df_folha.groupby(['Elemento','Origem'])[liq_cols_f].sum().sum(axis=1).reset_index()
        _det_by_elem.columns = ['Elemento','Origem','ValOrig']
        _det_by_elem = _det_by_elem[_det_by_elem['ValOrig']>0]

        def _hover_elem(elem, total):
            linhas = _det_by_elem[_det_by_elem['Elemento']==elem].sort_values('ValOrig', ascending=False)
            det = "".join(
                f"  {row['Origem']}: R$ {row['ValOrig']:,.2f}<br>".replace(",","X").replace(".",",").replace("X",".")
                for _, row in linhas.iterrows()
            )
            return f"<b>{elem}</b><br>Total: <b>{formar_real(total)}</b><br>── Por origem ──<br>{det}"

        df_elem_total['HoverText'] = df_elem_total.apply(
            lambda r: _hover_elem(r['Elemento'], r['Total']), axis=1
        )
        fig_folha_elem = go.Figure()
        fig_folha_elem.add_trace(go.Bar(
            x=df_elem_total['Total'],
            y=df_elem_total['Elemento'],
            orientation='h',
            marker_color='#1a7a4a',
            text=df_elem_total['Total'].apply(
                lambda v: f"R$ {v:,.0f}".replace(",","X").replace(".",",").replace("X",".")),
            textposition='outside',
            customdata=df_elem_total['HoverText'],
            hovertemplate="<span style='color:white;'>%{customdata}</span><extra></extra>",
        ))
        fig_folha_elem.update_layout(
            separators=",.", hoverlabel=HOVER_STYLE,
            xaxis=dict(showticklabels=False, title=None),
            yaxis=dict(title=None), showlegend=False,
            height=max(380, len(df_elem_total)*52),
            margin=dict(r=220),
        )
        st.plotly_chart(fig_folha_elem, use_container_width=True, config=CONFIG_PT)
        st.markdown("---")

        st.subheader("🔹 3. Evolução Mensal da Folha")
        dados_mensal_f = []
        for m in meses_disponiveis:
            col = f"{m}_Liquidado"
            if col not in df_folha.columns: continue
            for orig in df_folha['Origem'].unique():
                v = df_folha[df_folha['Origem']==orig][col].sum()
                dados_mensal_f.append({"Mês":m,"Origem":orig,"Valor":v})
        df_mensal_f = pd.DataFrame(dados_mensal_f)
        df_mensal_f = df_mensal_f[df_mensal_f['Valor']>0]

        fig_folha_mensal = px.bar(
            df_mensal_f, x='Mês', y='Valor', color='Origem',
            barmode='stack', text_auto=False,
            color_discrete_map=COR_ORIGEM,
            category_orders={"Mês":ORDEM_MESES},
        )
        fig_folha_mensal.update_traces(
            hovertemplate=(
                "<span style='color:white;'><b>%{x} — %{data.name}</b><br>"
                "Valor: <b>R$ %{y:,.2f}</b></span><extra></extra>"
            ),
            hoverlabel=HOVER_STYLE,
        )
        fig_folha_mensal.update_layout(
            separators=",.", yaxis=dict(showticklabels=False), showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=-0.30, xanchor="center", x=0.5),
            height=400,
        )
        st.plotly_chart(fig_folha_mensal, use_container_width=True, config=CONFIG_PT)

    elif st.session_state.setor == 'Programas e PDDE':
        st.markdown("<h1 style='text-align:left;'>🎓 Itamogi — Programas e PDDE</h1>",
                    unsafe_allow_html=True)
        df_prog, df_esc = load_acompanhamentos()

        # ── PROGRAMAS: apenas os com adesão em 2026 ───────────────────────────
        st.subheader("📋 Programas — Adesões em 2026")
        if df_prog is None or df_prog.empty:
            st.info("Configure a planilha de Acompanhamentos (aba de Programas) para exibir as "
                    "adesões — ou coloque o arquivo em zEducação/Itamogi_PROG.csv.")
        else:
            _cn = next((c for c in df_prog.columns if 'PROGRAMAS' in str(c).upper()), None)
            _cols = list(df_prog.columns)
            _ca = _cols[_cols.index(_cn) + 1] if (_cn in _cols and _cols.index(_cn) + 1 < len(_cols)) else None
            _cc = next((c for c in df_prog.columns
                        if 'COORDENAD' in str(c).upper() or 'ARTICUL' in str(c).upper()), None)
            _cb = next((c for c in df_prog.columns if str(c).strip().upper() == 'BOLSA'), None)
            if not _cn or not _ca:
                st.warning("Não encontrei a coluna 'PROGRAMAS PARA ADESÃO' na planilha.")
            else:
                sec = "(Geral)"; linhas = []
                for _, r in df_prog.iterrows():
                    nome = str(r[_cn]).strip()
                    ades = str(r[_ca]).strip() if pd.notna(r[_ca]) else ""
                    if not nome or nome.lower() == 'nan':
                        continue
                    vazio = ades == "" or ades.lower() == "nan"
                    if vazio and (nome.upper() in _ACOMP_SECOES or 'ADESÃO' in nome.upper()
                                  or nome.upper() == 'PNLD'):
                        sec = nome; continue          # cabeçalho de seção
                    if vazio:
                        continue                       # programa sem decisão — ignora
                    if ades.lower() == 'sim':
                        coord = str(r[_cc]).strip() if _cc and pd.notna(r[_cc]) else ""
                        bolsa = str(r[_cb]).strip() if _cb and pd.notna(r[_cb]) else ""
                        linhas.append({"Seção": sec, "Programa": nome,
                                       "Coordenador/Articulador": "" if coord in ('-', 'nan') else coord,
                                       "Bolsa": "Sim" if bolsa.lower() == 'sim' else "—"})
                if not linhas:
                    st.info("Nenhum programa com adesão 'Sim' encontrado na planilha.")
                else:
                    dfa = pd.DataFrame(linhas)
                    for s in dfa['Seção'].unique():
                        st.markdown(f"**{s}**")
                        st.dataframe(
                            dfa[dfa['Seção'] == s][["Programa", "Coordenador/Articulador", "Bolsa"]],
                            use_container_width=True, hide_index=True)
        st.markdown("---")

        # ── PDDE: previsão 2026 por escola ────────────────────────────────────
        st.subheader("🏫 Recursos PDDE — Previsão 2026 por Escola")
        _esc = _parse_pdde_escolas(df_esc) if df_esc is not None and not df_esc.empty else {}
        if not _esc:
            st.info("Não consegui ler a relação do PDDE por escola. Verifique se a conta de serviço "
                    "tem acesso à planilha 'Escolas Acompanhamento 2026' (aba Itamogi), ou o arquivo "
                    "local zEducação/Itamogi_PDDE.csv.")
        else:
            _res = pd.DataFrame([{"Escola": e, "Previsto 2026": d["prev"], "Recebido": d["rec"]}
                                 for e, d in _esc.items()])
            _mp1, _mp2, _mp3 = st.columns(3)
            with _mp1: st.metric("Escolas", len(_res))
            with _mp2: st.metric("Total Previsto 2026", formar_real(_res["Previsto 2026"].sum()))
            with _mp3: st.metric("Total Recebido", formar_real(_res["Recebido"].sum()))
            fig_pdde = px.bar(_res.sort_values("Previsto 2026"), x="Previsto 2026", y="Escola",
                              orientation='h', color_discrete_sequence=['#1a7a4a'],
                              text="Previsto 2026")
            fig_pdde.update_traces(texttemplate="R$ %{x:,.0f}", cliponaxis=False,
                                   hovertemplate="<b>%{y}</b><br>Previsto 2026: R$ %{x:,.2f}<extra></extra>")
            fig_pdde.update_layout(height=max(340, 48 * len(_res)), separators=',.',
                                   xaxis_tickprefix='R$ ', xaxis_title="Previsto 2026",
                                   yaxis_title="", margin=dict(l=10, r=40, t=20, b=20))
            st.plotly_chart(fig_pdde, use_container_width=True, config=CONFIG_PT)

            st.markdown("**Detalhamento por escola (programa · previsto · recebido):**")
            for e, d in _esc.items():
                if not d["programas"]:
                    continue
                with st.expander(f"{e}  —  Previsto {formar_real(d['prev'])} · "
                                 f"Recebido {formar_real(d['rec'])}"):
                    _det = pd.DataFrame(d["programas"], columns=["Programa", "Previsto", "Recebido"])
                    _det["Previsto"] = _det["Previsto"].apply(formar_real)
                    _det["Recebido"] = _det["Recebido"].apply(formar_real)
                    st.dataframe(_det, use_container_width=True, hide_index=True)

            _rt = _res.copy()
            _rt["Previsto 2026"] = _rt["Previsto 2026"].apply(formar_real)
            _rt["Recebido"] = _rt["Recebido"].apply(formar_real)
            st.dataframe(_rt, use_container_width=True, hide_index=True)
        st.markdown("---")


    st.markdown("### 📋 Relatório Geral de Fichas")
    df_f_filt = df_f_raw[df_f_raw['Atividade'].str.contains(
        search_term, na=False, case=False)].copy()
    st.dataframe(df_f_filt, use_container_width=True, hide_index=True)

else:
    st.error("Erro ao carregar os arquivos CSV. Verifique a pasta 'zEducação'.")


# ── FIM DO SCRIPT: libera o loader (a página terminou de renderizar) ──────────
if _LOGO_ESCURO or _LOGO_CLARO:
    _html_iframe(
        "<script>(function(){try{"
        "var d=window.parent.document;"
        "function done(){var l=d.querySelectorAll('.ig2p-loader');"
        "for(var i=0;i<l.length;i++){l[i].classList.add('ig2p-done');}}"
        "done();setTimeout(done,80);"
        "}catch(e){}})()</script>", height=0)
