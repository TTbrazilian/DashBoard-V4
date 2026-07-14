import streamlit as st
import pandas as pd
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

# ── CONFIGURAÇÃO DA PÁGINA ────────────────────────────────────────────────────
st.set_page_config(page_title="São Tomás de Aquino - Gestão Educação", layout="wide")

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
           Remove o espaço vazio acima do título:
           (1) reduz o padding-top padrão do container principal;
           (2) colapsa o container do iframe de injeção de JS (logo iG2P), que
               renderiza uma faixa vazia no topo da área principal.
           Obs.: o único iframe do fluxo principal é o de injeção do logo;
           gráficos Plotly não são iframes, então não são afetados. */
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

# ── PALETA DE CORES GLOBAL ────────────────────────────────────────────────────
# Receitas FUNDEB — verde/azul com alto contraste entre categorias
COR_REC = {
    'Principal':   '#1a7a4a',   # verde floresta escuro
    'Rendimentos': '#0d47a1',   # azul marinho escuro
    'VAAR/VAAT':   '#69f0ae',   # verde neon claro  (bem diferente do escuro)
    'ETI':         '#40c4ff',   # azul céu brilhante (bem diferente do marinho)
}
# Despesas FUNDEB — vermelho, 70% muito escuro / 30% muito claro (bem distintos)
COR_DESP = {
    'FUNDEB 70% – Vigente': '#4a0000',   # vermelho quase preto
    'FUNDEB 30% – Vigente': '#ff1744',   # vermelho vivo/saturado
}

# ── FUNÇÕES UTILITÁRIAS ───────────────────────────────────────────────────────
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
    """Card de índice com ícone ✅/⚠️ e delta colorido."""
    delta      = valor_atual - meta
    status_icon = "✅" if valor_atual >= meta else "⚠️"
    return st.metric(label=label,
                     value=f"{status_icon} {valor_atual:.2f}%",
                     delta=f"{delta:.2f}%",
                     delta_color="normal")

def abreviar_extremo(nome):
    if "📊" in nome: return "GERAL"
    n = nome.upper()
    for longo, curto in {
        "IMPOSTO SOBRE A PROPRIEDADE PREDIAL E TERRITORIAL URBANA":"IPTU",
        "IMPOSTO SOBRE TRANSMISSÃO DE BENS IMÓVEIS":"ITBI",
        "IMPOSTO SOBRE SERVIÇOS DE QUALQUER NATUREZA":"ISS",
        "IMPOSTO SOBRE A RENDA":"IR","IMPOSTO TERRITORIAL RURAL":"ITR",
        "DÍVIDA ATIVA":"D.A.","COTA-PARTE":"COTA",
        "CONTRIBUIÇÃO PARA O CUSTEIO DO SERVIÇO DE ILUMINAÇÃO PÚBLICA":"COSIP"
    }.items(): n = n.replace(longo, curto)
    n = n.replace("PRINCIPAL","PRIN.").replace("MULTAS E JUROS","M/J")\
         .replace("OUTRAS RECEITAS","OUTR.")
    if "-" in n:
        p = n.split("-")
        return f"{p[0].strip()[:6]} {p[1].strip()[:5]}"
    return n[:12]

def buscar_arquivo(nome):
    caminhos = [nome, os.path.join("..",nome), os.path.join("pages",nome),
                os.path.join(os.path.dirname(__file__),"..",nome)]
    for p in caminhos:
        if os.path.exists(p): return p
    return None

def soma(df, cols):
    """Soma apenas colunas que existem no df."""
    presentes = [c for c in cols if c in df.columns]
    return df[presentes].sum().sum() if presentes else 0.0

# ── CARGA DE DADOS ────────────────────────────────────────────────────────────
@st.cache_data
def load_all_data():
    path_f  = buscar_arquivo("zEducação/São Tomás de Aquino.csv")
    path_r  = buscar_arquivo("zEducação/São Tomás de Aquino_R.csv")
    path_df = buscar_arquivo("zEducação/São Tomás de Aquino_DF.csv")
    if not path_f or not path_r or not path_df: return None, None, None

    # Fichas (F) — cabeçalho duplo → colunas no formato "Mês_Tipo"
    df_f = pd.read_csv(path_f, sep=None, engine='python', encoding='utf-8', header=[0,1])
    new_cols = []
    for col in df_f.columns:
        new_cols.append(col[1].strip() if "Unnamed" in col[0]
                        else f"{col[1].strip()}_{col[0].strip()}")
    df_f.columns = new_cols

    # Receitas (R) — header=0 obrigatório (header=1 destruiria os nomes das colunas)
    df_r = pd.read_csv(path_r, sep=None, engine='python', encoding='utf-8', header=0)
    df_r.columns = [str(c).strip() for c in df_r.columns]

    # Despesas por fonte (DF)
    df_df = pd.read_csv(path_df, sep=None, engine='python', encoding='utf-8')
    df_df.columns = [str(c).strip() for c in df_df.columns]

    # Limpeza numérica — F
    for col in df_f.columns:
        if any(k in col for k in ['Orçado','Saldo','Liquidado','Empenhado','Pago',
                                   'Creditado','Anulado']):
            df_f[col] = df_f[col].apply(limpar_valor)

    # Limpeza numérica — R (inclui Repasse e Orçado Receitas)
    COLS_R = ORDEM_MESES + ['Total','Orçado Receitas','Repasse','2025']
    for col in df_r.columns:
        if col in COLS_R: df_r[col] = df_r[col].apply(limpar_valor)

    # Limpeza numérica — DF
    for col in df_df.columns:
        if col in ORDEM_MESES + ['Total']:
            df_df[col] = df_df[col].apply(limpar_valor)

    # Padronizar coluna Fonte
    for df, colname in [(df_f,'Fonte'),(df_df,'Fonte')]:
        if colname in df.columns:
            df[colname] = df[colname].astype(str).str.replace('.0','',regex=False).str.strip()

    return df_f, df_r, df_df

df_f_raw, df_r, df_df_raw = load_all_data()

# ── MESES DISPONÍVEIS (DINÂMICO) ──────────────────────────────────────────────
# REGRA UNIVERSAL #4: meses_disponiveis nunca hardcoded. Um mês é considerado
# disponível quando há EXECUÇÃO de despesa nele — seja nas FICHAS ({m}_Liquidado)
# ou nas despesas por fonte (DF[m]). Receita isolada (ex.: rendimento bancário
# residual em Maio sem fichas/despesas) NÃO qualifica o mês, evitando colunas
# vazias nos gráficos. Para São Tomás isto detecta Janeiro–Abril.
def _detectar_meses(df_f, df_df):
    meses = []
    for m in ORDEM_MESES:
        tem = False
        cl = f"{m}_Liquidado"
        if df_f is not None and cl in df_f.columns and df_f[cl].abs().sum() > 0:
            tem = True
        if df_df is not None and m in df_df.columns and df_df[m].abs().sum() > 0:
            tem = True
        if tem:
            meses.append(m)
    return meses if meses else ['Janeiro']

meses_disponiveis = _detectar_meses(df_f_raw, df_df_raw)

if df_f_raw is not None and df_r is not None:

    # ── SIDEBAR ───────────────────────────────────────────────────────────────
    st.sidebar.title("🔍 Filtros de Análise")
    search_term = st.sidebar.text_input("Filtrar Fichas:", "")
    st.sidebar.markdown("---")
    st.sidebar.subheader("Setores")
    for label, key in [("FUNDEB","FUNDEB"),
                        ("Recursos Próprios","Recursos Próprios"),
                        ("Recursos Vinculados","Recursos Vinculados"),
                        ("Visão Macro","Visão Macro"),
                        ("Folha de Pagamento","Folha de Pagamento")]:
        if st.sidebar.button(label, use_container_width=True):
            st.session_state.setor = key

    # ── SIDEBAR UNIVERSAL: logo iG2P no Home + filtro de setor ───────────────
    # Injeta o logo iG2P sobre o botão "Home" da nav e oculta municípios do
    # setor oposto (Saúde). Roda via MutationObserver para persistir mesmo
    # quando a página é aberta diretamente pela home do sistema.
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
            "if(_sau&&temEduca)ocultar=true;"
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

    # =========================================================================
    # SETOR FUNDEB
    # =========================================================================
    if st.session_state.setor == 'FUNDEB':
        st.markdown("<h1 style='text-align:left;'>📖 São Tomás de Aquino — FUNDEB</h1>",
                    unsafe_allow_html=True)

        def cat_receita(desc):
            d = str(desc).upper().strip()
            if 'VAAR' in d or 'VAAT' in d:             return 'VAAR/VAAT'
            if 'ETI'  in d or 'TEMPO INTEGRAL' in d:   return 'ETI'
            if 'APLICAÇÃO' in d or 'RENDIMENTOS' in d: return 'Rendimentos'
            return 'Principal'

        # ── Receitas ─────────────────────────────────────────────────────────
        df_r_fundeb = df_r[df_r['Categoria'].str.strip() == 'FUNDEB'].copy()
        df_r_fundeb['Descrição da Receita'] = df_r_fundeb['Descrição da Receita'].str.strip()
        df_r_fundeb['Subcategoria'] = df_r_fundeb['Descrição da Receita'].apply(cat_receita)

        tot_prev_municipio = df_r_fundeb[df_r_fundeb['Subcategoria']=='Principal'
                                         ]['Orçado Receitas'].sum()
        tot_prev_portaria  = df_r_fundeb['Repasse'].sum()
        tot_rec_periodo    = soma(df_r_fundeb, meses_disponiveis)
        tot_eti            = soma(df_r_fundeb[df_r_fundeb['Subcategoria']=='ETI'],
                                  meses_disponiveis)

        # ── Despesas (somente fontes do ano vigente: 15407 / 15403) ──────────
        df_df_fundeb = df_df_raw[df_df_raw['Fonte'].isin(['15407','15403'])]
        df_df_fundeb['Fonte_Nome'] = df_df_fundeb['Fonte'].apply(
            lambda x: 'FUNDEB 70%' if x=='15407' else 'FUNDEB 30%')

        base_indice_70  = soma(df_r_fundeb[df_r_fundeb['Subcategoria'].isin(
                                ['Principal','Rendimentos'])], meses_disponiveis)
        desp_70_vigente = soma(df_df_fundeb[(df_df_fundeb['Fonte']=='15407') &
                                (df_df_fundeb['Tipo']=='Liquidado')], meses_disponiveis)
        desp_30_vigente = soma(df_df_fundeb[(df_df_fundeb['Fonte']=='15403') &
                                (df_df_fundeb['Tipo']=='Liquidado')], meses_disponiveis)
        tot_desp_vigente = desp_70_vigente + desp_30_vigente
        perc_70_indice   = (desp_70_vigente/base_indice_70*100) if base_indice_70>0 else 0.0

        # ── Cards de previsão ─────────────────────────────────────────────────
        st.markdown("##### Previsões Orçamentárias")
        p1, p2, p3 = st.columns(3)
        with p1: st.metric("Previsão Receitas (Orçamento Município)",
                            formar_real(tot_prev_municipio))
        with p2: st.metric("Previsão de Receitas (Port. Intermin. nº 14 de 29 dez 2025)",
                            formar_real(tot_prev_portaria))
        # 'Atualização Quadrimestral' não está em COLS_R → permanece string bruta;
        # aplica limpar_valor UMA vez. % Atualização vira o delta do card.
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
            delta=_delta_quad,
            delta_color="normal"
        )
        st.markdown("---")

        # ═════════════════════════════════════════════════════════════════════
        # GRÁFICO 1 — Receitas e Despesas FUNDEB
        # ═════════════════════════════════════════════════════════════════════
        st.subheader("🔹 1. Receitas e Despesas FUNDEB")

        saldo     = tot_rec_periodo - tot_desp_vigente
        exec_perc = (tot_desp_vigente/tot_rec_periodo*100) if tot_rec_periodo>0 else 0

        t1, t2, t3 = st.columns(3)
        with t1: st.metric(f"Total Receitas ({meses_disponiveis[0]}–{meses_disponiveis[-1]})",
                            formar_real(tot_rec_periodo))
        with t2: st.metric("Total Despesas Liquidadas – Ano Vigente",
                            formar_real(tot_desp_vigente))
        with t3:
            # Verde se saldo positivo (receitas > despesas), vermelho se negativo
            delta_val   = exec_perc if saldo >= 0 else -exec_perc
            st.metric("Saldo (Receitas − Despesas Vigentes)", formar_real(saldo),
                      delta=f"{delta_val:.1f}% Saldo", delta_color="normal")

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
                    desc_list = df_r_fundeb[df_r_fundeb['Subcategoria']==cat][
                        'Descrição da Receita'].unique().tolist()
                    show = f"rec_{cat}" not in legendas_usadas
                    legendas_usadas.add(f"rec_{cat}")
                    part = f"{val/tot_rec_m*100:.1f}%" if tot_rec_m>0 else "—"
                    fig_rd.add_trace(go.Bar(
                        name=cat, x=[[m],["Receitas"]], y=[val],
                        marker_color=COR_REC.get(cat,'#27ae60'),
                        legendgroup=f"rec_{cat}", showlegend=show,
                        text=formar_real(val) if val>0 else "",
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
                                              ('15403','FUNDEB 30% – Vigente')]:
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
                        textposition='inside', insidetextanchor='middle',
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
        else:  # Acumulado
            for cat in categorias_rec:
                val = soma(df_r_fundeb[df_r_fundeb['Subcategoria']==cat], meses_disponiveis)
                desc_list = df_r_fundeb[df_r_fundeb['Subcategoria']==cat][
                    'Descrição da Receita'].unique().tolist()
                part = f"{val/tot_rec_periodo*100:.1f}%" if tot_rec_periodo>0 else "—"
                fig_rd.add_trace(go.Bar(
                    name=cat, x=[["Acumulado"],["Receitas"]], y=[val],
                    marker_color=COR_REC.get(cat,'#27ae60'),
                    legendgroup=f"rec_{cat}", showlegend=True,
                    text=formar_real(val) if val>0 else "",
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
                                          ('15403','FUNDEB 30% – Vigente')]:
                val = soma(df_df_fundeb[(df_df_fundeb['Fonte']==fonte_cod) &
                                        (df_df_fundeb['Tipo']=='Liquidado')], meses_disponiveis)
                prop = f"{val/tot_desp_vigente*100:.1f}%" if tot_desp_vigente>0 else "—"
                fig_rd.add_trace(go.Bar(
                    name=label_desp, x=[["Acumulado"],["Despesas"]], y=[val],
                    marker_color=COR_DESP[label_desp],
                    legendgroup=label_desp, showlegend=True,
                    text=formar_real(val) if val>0 else "",
                    textposition='inside', insidetextanchor='middle',
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

        # ═════════════════════════════════════════════════════════════════════
        # GRÁFICO 2 — Índice de Aplicação em Pessoal (Mín. 70%)
        # metric_contabil exibido APENAS na visão Acumulado
        # Legenda posicionada para não cobrir o eixo X
        # ═════════════════════════════════════════════════════════════════════
        st.subheader("🔹 2. Índice de Aplicação em Pessoal (Mín. 70%)")
        tipo_70 = st.segmented_control("Visualização:", ["Mensal","Acumulado"],
                                       default="Mensal", key="tipo_70_btn")

        if tipo_70 == "Acumulado":
            a1, a2 = st.columns(2)
            with a1: st.metric("Base de Cálculo (Principal + Rendimentos)",
                                formar_real(base_indice_70))
            with a2: st.metric("Despesas FUNDEB 70% – Liquidado",
                                formar_real(desp_70_vigente))
            metric_contabil("Aplicação em Pessoal (Mín. 70%)", perc_70_indice, 70.0)

            cor_barra = "#27ae60" if perc_70_indice>=70 else "#e74c3c"
            fig_70 = go.Figure()
            fig_70.add_trace(go.Bar(
                x=["Receita Base\n(Principal + Rendimentos)"], y=[base_indice_70],
                name="Receita Base", marker_color="#003366",
                text=[formar_real(base_indice_70)],
                textposition='inside', insidetextanchor='middle',
                hovertemplate=("<span style='color:white;'><b>Receita Base FUNDEB</b><br>"
                               "Valor: <b>"+formar_real(base_indice_70)+"</b></span><extra></extra>"),
            ))
            fig_70.add_trace(go.Bar(
                x=["Despesas 70%\n(Liquidado)"], y=[desp_70_vigente],
                name=f"Despesas 70% — {perc_70_indice:.2f}%", marker_color=COR_DESP['FUNDEB 70% – Vigente'],
                text=[f"{formar_real(desp_70_vigente)}\n({perc_70_indice:.2f}%)"],
                textposition='inside', insidetextanchor='middle',
                hovertemplate=("<span style='color:white;'><b>Despesas FUNDEB 70%</b><br>"
                               "Fonte: 15407 | Liquidado<br>"
                               "Valor: <b>"+formar_real(desp_70_vigente)+"</b><br>"
                               "Índice: <b>"+f"{perc_70_indice:.2f}%"+"</b></span><extra></extra>"),
            ))
            fig_70.add_hline(y=base_indice_70*0.70, line_dash="dot", line_color="green",
                             annotation_text=f"Meta 70% = {formar_real(base_indice_70*0.70)}",
                             annotation_position="top left")
            fig_70.update_layout(
                separators=",.", barmode='group', hoverlabel=HOVER_STYLE,
                yaxis=dict(showticklabels=False),
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=-0.25, xanchor="center", x=0.5),
                height=440, margin=dict(b=80),
            )

        else:  # Mensal — sem metric_contabil
            dados_70_m = []
            for m in meses_disponiveis:
                base_m   = soma(df_r_fundeb[df_r_fundeb['Subcategoria'].isin(
                                    ['Principal','Rendimentos'])], [m])
                liq_70_m = soma(df_df_fundeb[(df_df_fundeb['Fonte']=='15407') &
                                             (df_df_fundeb['Tipo']=='Liquidado')], [m])
                liq_30_m = soma(df_df_fundeb[(df_df_fundeb['Fonte']=='15403') &
                                             (df_df_fundeb['Tipo']=='Liquidado')], [m])
                perc_m   = (liq_70_m/base_m*100) if base_m>0 else 0.0
                dados_70_m += [
                    {"Mês":m,"Tipo":"Receita Base","Valor":base_m,"Texto":""},
                    {"Mês":m,"Tipo":"FUNDEB 70% (Liquidado)","Valor":liq_70_m,"Texto":f"{perc_m:.1f}%"},
                    {"Mês":m,"Tipo":"FUNDEB 30% (Liquidado)","Valor":liq_30_m,"Texto":""},
                ]
            fig_70 = px.bar(
                pd.DataFrame(dados_70_m), x='Mês', y='Valor', color='Tipo',
                barmode='group', text='Texto',
                color_discrete_map={
                    "Receita Base":           "#003366",
                    "FUNDEB 70% (Liquidado)": COR_DESP['FUNDEB 70% – Vigente'],
                    "FUNDEB 30% (Liquidado)": COR_DESP['FUNDEB 30% – Vigente'],
                },
                category_orders={"Mês":ORDEM_MESES}
            )
            # REGRA UNIVERSAL: linha de meta com add_shape, nunca go.Scatter.
            # Grupo de 3 barras (Receita Base, 70%, 30%) → _OFFSET=0.30 cobre o grupo.
            metas_70 = [soma(df_r_fundeb[df_r_fundeb['Subcategoria'].isin(
                            ['Principal','Rendimentos'])], [m]) * 0.70
                        for m in meses_disponiveis]
            _OFFSET = 0.30
            for i, _mv in enumerate(metas_70):
                fig_70.add_shape(type='line', xref='x', yref='y',
                    x0=i-_OFFSET, x1=i+_OFFSET, y0=_mv, y1=_mv,
                    line=dict(color='green', dash='dot', width=2))
                if i < len(metas_70)-1:
                    fig_70.add_shape(type='line', xref='x', yref='y',
                        x0=i+_OFFSET, x1=(i+1)-_OFFSET, y0=_mv, y1=metas_70[i+1],
                        line=dict(color='green', dash='dot', width=2))
            fig_70.add_trace(go.Scatter(
                x=[None], y=[None], mode='lines', name='Meta 70% (Mensal)',
                line=dict(color='green', dash='dot')
            ))
            fig_70.update_traces(
                selector=dict(type='bar'), textposition='outside', hoverlabel=HOVER_STYLE,
                hovertemplate=("<span style='color:white;'><b>%{x} — %{data.name}</b><br>"
                               "Valor: <b>R$ %{y:,.2f}</b></span><extra></extra>")
            )
            fig_70.update_layout(
                separators=",.", yaxis=dict(showticklabels=False),
                xaxis_title=None,   # remove "Mês" do eixo para não sobrepor à legenda
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=-0.25, xanchor="center", x=0.5),
                height=460, margin=dict(b=90),
            )

        st.plotly_chart(fig_70, use_container_width=True, config=CONFIG_PT)
        st.markdown("---")

        # ═════════════════════════════════════════════════════════════════════
        # GRÁFICO 3 — Percentual Tempo Integral
        # Uma única barra (Receita Base FUNDEB) + linha de referência 4%
        # ═════════════════════════════════════════════════════════════════════
        st.subheader("🔹 3. Percentual Tempo Integral")

        meta_eti_perc = 4.0
        val_meta_eti  = base_indice_70 * (meta_eti_perc/100)

        e1, e2 = st.columns(2)
        with e1: st.metric("Total Receitas FUNDEB (período)", formar_real(tot_rec_periodo))
        with e2: st.metric(f"Equivalente a {meta_eti_perc:.0f}% da Receita Base",
                            formar_real(val_meta_eti))

        fig_eti = go.Figure()
        fig_eti.add_trace(go.Bar(
            x=["Receita Base FUNDEB"], y=[base_indice_70],
            name="Receita Base", marker_color="#003366",
            text=[formar_real(base_indice_70)],
            textposition='inside', insidetextanchor='middle',
            hovertemplate=("<span style='color:white;'><b>Receita Base FUNDEB</b><br>"
                           "Principal + Rendimentos<br>"
                           "Valor: <b>"+formar_real(base_indice_70)+"</b></span><extra></extra>"),
        ))
        fig_eti.add_hline(
            y=val_meta_eti, line_dash="dot", line_color="#f39c12", line_width=2,
            annotation_text=f"Referência ETI {meta_eti_perc:.0f}% = {formar_real(val_meta_eti)}",
            annotation_position="top left"
        )
        fig_eti.update_layout(
            separators=",.", hoverlabel=HOVER_STYLE,
            yaxis=dict(showticklabels=False), showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=-0.20, xanchor="center", x=0.5),
            height=380,
        )
        st.plotly_chart(fig_eti, use_container_width=True, config=CONFIG_PT)

    # =========================================================================
    # SETOR RECURSOS PRÓPRIOS
    # =========================================================================
    elif st.session_state.setor == 'Recursos Próprios':
        st.markdown("<h1 style='text-align:left;'>📖 São Tomás de Aquino — Recursos Próprios (25%)</h1>",
                    unsafe_allow_html=True)

        def obter_soma_rp(df, meses):
            col_map = {c.strip().lower():c for c in df.columns}
            cols = [col_map[m.lower()] for m in meses if m.lower() in col_map]
            return df[cols].sum().sum() if cols else 0.0

        # Mapeamento: nome longo → sigla do grupo principal
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
            """Retorna a sigla completa (ex: IPTU – D.A.) para uso interno.
            Normaliza aspas tipográficas (\u201c\u201d) para aspas retas antes de comparar."""
            du = str(desc).upper()
            # Normaliza aspas curvas/tipográficas → aspas retas (ex: "Inter Vivos" → "Inter Vivos")
            du = du.replace('\u201c', '"').replace('\u201d', '"').replace('\u2018', "'").replace('\u2019', "'")
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
            """Extrai apenas o nome do grupo, sem subcategoria (D.A., M/J etc.)."""
            return abrev.split(' –')[0].strip()

        PALETA_RP = ['#1a7a4a','#27ae60','#17a589','#1abc9c',
                     '#2980b9','#1565c0','#0288d1','#00838f',
                     '#00acc1','#26c6da','#43a047','#66bb6a',
                     '#80cbc4','#4dd0e1']

        # Base: Impostos + Cota-Parte
        df_r_base = df_r[df_r['Categoria'].str.strip().isin(['Impostos','Cota-Parte'])].copy()
        df_r_base['Descrição da Receita'] = df_r_base['Descrição da Receita'].str.strip()
        df_r_base['Abrev'] = df_r_base['Descrição da Receita'].apply(abrev_imposto)
        df_r_base['Grupo'] = df_r_base['Abrev'].apply(grupo_imposto)

        # Agrupamento por grupo (soma IPTU + IPTU D.A. + IPTU M/J → IPTU único)
        df_r_grupo = df_r_base.groupby('Grupo')[meses_disponiveis].sum().reset_index()
        grupos_unicos = list(df_r_grupo['Grupo'].unique())
        mapa_cores_grupos = {g: PALETA_RP[i%len(PALETA_RP)] for i,g in enumerate(grupos_unicos)}

        # Dedução FUNDEB
        df_r_ded = df_r[df_r['Categoria'].str.strip().str.startswith('Dedução',na=False)].copy()

        # ALTERAÇÃO 3: previsão inclui Impostos + Cota-Parte
        prev_total_rp = df_r_base['Orçado Receitas'].sum()
        tot_rec_base  = obter_soma_rp(df_r_base, meses_disponiveis)
        tot_deducoes  = abs(obter_soma_rp(df_r_ded, meses_disponiveis))
        meta_25_valor = tot_rec_base * 0.25

        fase_despesa = st.segmented_control(
            " (Impacta Indicadores Superiores):",
            ["Empenhado","Liquidado","Pago"], default="Liquidado", key="fase_desp_rp")
        df_df_15001 = df_df_raw[(df_df_raw['Fonte']=='15001') &
                                 (df_df_raw['Tipo']==fase_despesa)].copy()

        # ── DESCONTOS APLICADOS AO CÁLCULO DOS 25% (individualidade São Tomás) ──
        # Recursos do FUNDEB não utilizados  → R$ 0,00
        # Superávit de anos anteriores       → R$ 327.585,77  (deduzido do esforço)
        _desconto_fundeb_nao_util = 0.0
        _desconto_superavit_ant   = 327585.77
        _total_descontos_25       = _desconto_fundeb_nao_util + _desconto_superavit_ant

        total_desp_15001 = df_df_15001[meses_disponiveis].sum().sum()
        esforco_total    = max(0.0, total_desp_15001 + tot_deducoes - _total_descontos_25)
        perc_25          = (esforco_total/tot_rec_base*100) if tot_rec_base>0 else 0.0
        saldo_nec_25     = max(0.0, meta_25_valor - esforco_total)

        df_15000_outras = df_df_raw[
            df_df_raw['Fonte'].str.match(r'^150\d*$',na=False) &
            (df_df_raw['Fonte']!='15001') & (df_df_raw['Tipo']=='Liquidado')].copy()
        val_outras_fontes = df_15000_outras[meses_disponiveis].sum().sum()

        # Cards superiores
        st.markdown("##### Previsões e Arrecadação")
        c1, c2, c3 = st.columns(3)
        with c1: st.metric("Previsão Orçamentária — Impostos e Cota-Parte (Janeiro a Dezembro)",
                            formar_real(prev_total_rp))
        with c2: st.metric(f"Receitas Arrecadadas ({meses_disponiveis[0]}–{meses_disponiveis[-1]})",
                            formar_real(tot_rec_base))
        # Saldo vs meta: positivo = meta atingida (verde ↑), negativo = abaixo da meta (vermelho ↓)
        # Mesmo padrão do FUNDEB Gráfico 1
        with c3: st.metric("Meta 25% (sobre o arrecadado)", formar_real(meta_25_valor))
        st.markdown("---")

        # ── Gráfico Receitas por Imposto (AGRUPADO) ───────────────────────────
        # M/J, D.A. e D.A. M/J são somados com o principal de cada imposto
        st.subheader("🔹 Receitas Recursos Próprios (Impostos e Cota-Parte)")
        view_rp = st.segmented_control("Visualização Receitas:", ["Mensal","Acumulado"],
                                       default="Mensal", key="view_rp")

        # Navegação — botões mostram apenas o grupo (IPTU, ITBI, FPM…)
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
                fig_rp = px.bar(df_acum, x='Grupo', y='Valor', color='Grupo',
                                text_auto='.3s', color_discrete_map=mapa_cores_grupos)
            else:
                row = df_r_grupo[df_r_grupo['Grupo']==ativo]
                val = row[meses_disponiveis].sum().sum() if len(row)>0 else 0
                fig_rp = px.bar(x=[ativo], y=[val], text_auto='.3s',
                                color_discrete_sequence=[mapa_cores_grupos.get(ativo,'#003366')])
        else:  # Mensal
            if ativo == "Acumulado Geral":
                dados_m = []
                for m in meses_disponiveis:
                    for _, row in df_r_grupo.iterrows():
                        dados_m.append({"Mês":m,"Imposto":row['Grupo'],"Valor":row[m]})
                fig_rp = px.bar(pd.DataFrame(dados_m), x='Mês', y='Valor', color='Imposto',
                                barmode='stack', text_auto='.2s',
                                color_discrete_map=mapa_cores_grupos,
                                category_orders={"Mês":ORDEM_MESES})
            else:
                row = df_r_grupo[df_r_grupo['Grupo']==ativo]
                dados_m = [{"Mês":m,"Valor":row[m].sum() if len(row)>0 else 0}
                           for m in meses_disponiveis]
                fig_rp = px.bar(pd.DataFrame(dados_m), x='Mês', y='Valor', text_auto='.2s',
                                color_discrete_sequence=[mapa_cores_grupos.get(ativo,'#003366')],
                                category_orders={"Mês":ORDEM_MESES})

        # Hover — no Acumulado Geral %{data.name} traz o nome do grupo (trace nomeado);
        # nos botões individuais (FPM, ICMS…) o trace não tem nome, então injeta o ativo diretamente
        nome_hover = "%{data.name}" if ativo == "Acumulado Geral" else ativo
        fig_rp.update_traces(
            hovertemplate=(
                "<span style='color:white;'>"
                "<b>%{x}</b><br>"
                f"Imposto: {nome_hover}<br>"
                "Setor: Recursos Próprios<br>"
                "Valor: <b>R$ %{y:,.2f}</b>"
                "</span><extra></extra>"
            ),
            hoverlabel=HOVER_STYLE
        )
        fig_rp.update_layout(separators=",.", yaxis=dict(showticklabels=False))
        st.plotly_chart(fig_rp, use_container_width=True, config=CONFIG_PT)
        st.markdown("---")

        # ── Despesas Fonte 15001 ──────────────────────────────────────────────
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
            df_desp_plot['Fase'] = pd.Categorical(df_desp_plot['Fase'],
                                                   ["Empenhado","Liquidado","Pago"])
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

        # ── Análise Comparativa e Meta (25%) ─────────────────────────────────
        st.subheader("🔹 Análise Comparativa e Meta (Mínimo 25%)")
        view_meta     = st.segmented_control("Visualização Meta:", ["Mensal","Acumulado"],
                                             default="Mensal", key="view_meta")
        cor_aplicacao = "#27ae60" if perc_25>=25 else "#e74c3c"

        if view_meta == "Acumulado":
            idx1, idx2, idx3 = st.columns(3)
            with idx1: st.metric("Receitas Base (Impostos + Cota-Parte)", formar_real(tot_rec_base))
            with idx2: st.metric(f"Esforço Total ({fase_despesa} 15001 + Deduções)", formar_real(esforco_total))
            with idx3: metric_contabil("Índice de Aplicação (Mín. 25%)", perc_25, 25.0)

            # REGRA UNIVERSAL — Gráfico 25% Acumulado: barras SEM texto interno (text=[""]),
            # SEM annotations flutuantes. Todos os descontos e "Outras fontes" vão APENAS
            # no hover da barra vermelha (Despesa). Única anotação: linha de Meta 25% (add_hline).
            prop_desp = (total_desp_15001/esforco_total*100) if esforco_total>0 else 0
            prop_ded  = (tot_deducoes/esforco_total*100)    if esforco_total>0 else 0
            fig_meta  = go.Figure()
            fig_meta.add_trace(go.Bar(
                x=["Receitas Base"], y=[tot_rec_base], name="Receitas Base",
                marker_color="#003366", text=[""],
                hovertemplate=("<span style='color:white;'><b>Receitas Base</b><br>"
                               "Impostos + Cota-Parte<br>Valor: <b>"+formar_real(tot_rec_base)+"</b></span><extra></extra>"),
            ))
            fig_meta.add_trace(go.Bar(
                x=["Aplicação Total"], y=[tot_deducoes],
                name="Dedução FUNDEB", marker_color="#f39c12", text=[""],
                customdata=[[formar_real(tot_deducoes),f"{prop_ded:.1f}%"]],
                hovertemplate=("<span style='color:white;'><b>Dedução FUNDEB</b><br>"
                               "Valor: <b>%{customdata[0]}</b><br>"
                               "% do esforço: %{customdata[1]}</span><extra></extra>"),
            ))
            fig_meta.add_trace(go.Bar(
                x=["Aplicação Total"], y=[total_desp_15001],
                name=f"Despesa 15001 ({fase_despesa})", marker_color="#860000", text=[""],
                customdata=[[formar_real(total_desp_15001),f"{prop_desp:.1f}%",fase_despesa,
                             formar_real(_desconto_fundeb_nao_util),
                             formar_real(_desconto_superavit_ant),
                             formar_real(_total_descontos_25),
                             formar_real(val_outras_fontes)]],
                hovertemplate=("<span style='color:white;'><b>Despesa Fonte 15001</b><br>"
                               "Estágio: %{customdata[2]}<br>Valor: <b>%{customdata[0]}</b><br>"
                               "% do esforço: %{customdata[1]}<br>"
                               "─────────────────────<br>"
                               "🔻 Descontos aplicados:<br>"
                               "Rec. FUNDEB não util.: %{customdata[3]}<br>"
                               "Superávit anos ant.: %{customdata[4]}<br>"
                               "Total descontado: %{customdata[5]}<br>"
                               "Outras fontes (anos ant.): %{customdata[6]}"
                               "</span><extra></extra>"),
            ))
            fig_meta.add_hline(y=tot_rec_base*0.25, line_dash="dash", line_color="#f39c12",
                               annotation_text=f"Meta 25% = {formar_real(tot_rec_base*0.25)}",
                               annotation_position="top left")
            fig_meta.update_layout(separators=",.", barmode='stack', hoverlabel=HOVER_STYLE,
                                   yaxis=dict(showticklabels=False), showlegend=True,
                                   legend=dict(orientation="h",yanchor="bottom",y=-0.20,
                                               xanchor="center",x=0.5), height=450)
        else:
            # Mensal → DUAS COLUNAS AGRUPADAS por mês
            # Coluna 1: Receitas (total mensal)
            # Coluna 2: Despesas (15001 + Deduções juntas)
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
                     "DetalheA":formar_real(r_m),"DetalheB":"—","Total":r_m,
                     "Perc":"100%"},
                    {"Mês":m,"Tipo":"Despesas (15001 + Deduções)","Valor":total_desp_m,
                     "DetalheA":formar_real(d_m),"DetalheB":formar_real(ded_m),
                     "Total":total_desp_m,"Perc":f"{perc_m:.1f}% das receitas"},
                ]
            df_meta_m = pd.DataFrame(dados_meta_m)
            fig_meta = px.bar(
                df_meta_m, x='Mês', y='Valor', color='Tipo',
                barmode='group',
                custom_data=['DetalheA','DetalheB','Perc'],
                color_discrete_map={
                    "Receitas (Impostos + Cota-Parte)": "#003366",
                    "Despesas (15001 + Deduções)":      "#860000",
                },
                text='Valor',
                category_orders={"Mês":ORDEM_MESES}
            )
            fig_meta.update_traces(
                texttemplate="R$ %{y:,.0f}",
                textposition='inside',
                insidetextanchor='middle',
                hovertemplate=(
                    "<span style='color:white;'>"
                    "<b>%{x} — %{data.name}</b><br>"
                    "Total: <b>R$ %{y:,.2f}</b><br>"
                    "── Detalhamento ──<br>"
                    "%{customdata[0]}<br>"
                    "%{customdata[1]}<br>"
                    "%{customdata[2]}"
                    "</span><extra></extra>"
                ),
                hoverlabel=HOVER_STYLE
            )
            # REGRA UNIVERSAL: linha de meta com add_shape (_OFFSET=0.22), nunca go.Scatter.
            df_linha = df_meta_m[df_meta_m['Tipo']=='Receitas (Impostos + Cota-Parte)'].copy()
            metas_25 = (df_linha['Valor'] * 0.25).tolist()
            _OFFSET = 0.22
            for i, _mv in enumerate(metas_25):
                fig_meta.add_shape(type='line', xref='x', yref='y',
                    x0=i-_OFFSET, x1=i+_OFFSET, y0=_mv, y1=_mv,
                    line=dict(color='#f39c12', dash='dash', width=2))
                if i < len(metas_25)-1:
                    fig_meta.add_shape(type='line', xref='x', yref='y',
                        x0=i+_OFFSET, x1=(i+1)-_OFFSET, y0=_mv, y1=metas_25[i+1],
                        line=dict(color='#f39c12', dash='dash', width=2))
            fig_meta.add_trace(go.Scatter(
                x=[None], y=[None], mode='lines', name='Meta 25% (Mensal)',
                line=dict(color='#f39c12', dash='dash')
            ))
            fig_meta.update_layout(
                separators=",.", yaxis=dict(showticklabels=False), showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=-0.25,
                            xanchor="center", x=0.5)
            )

        st.plotly_chart(fig_meta, use_container_width=True, config=CONFIG_PT)

    # =========================================================================
    # SETOR RECURSOS VINCULADOS
    # =========================================================================
    elif st.session_state.setor == 'Recursos Vinculados':
        st.markdown("<h1 style='text-align:left;'>📖 São Tomás de Aquino — Recursos Vinculados</h1>",
                    unsafe_allow_html=True)

        # Fontes confirmadas nas fichas de São Tomás (sem pares 2xxx)
        mapa_desp = {'PNAE':['1552'],'PNATE':['1553'],'PTE':['1576'],'QESE':['1550']}
        programas = ['PNAE','PNATE','PTE','QESE']
        COR_PROG  = {'PNAE':'#1a7a4a','PNATE':'#17a589','PTE':'#2980b9','QESE':'#1565c0'}
        COR_DESP_V = '#860000'

        def soma_vinc(df, meses):
            col_map = {c.strip().lower():c for c in df.columns}
            cols = [col_map[m.lower()] for m in meses if m.lower() in col_map]
            return df[cols].sum().sum() if cols else 0.0

        # Receita de cada programa = repasse principal + "Rendimentos {prog}"
        # (categoria Remunerações Bancárias). Antes os rendimentos não eram puxados.
        alvos_vinc = programas + [f"RENDIMENTOS {p}" for p in programas]
        df_r_vinc = df_r[df_r['Descrição da Receita'].str.upper().str.strip().isin(alvos_vinc)].copy()
        st.markdown("---")

        for prog in programas:
            # df_prog_r inclui a linha do programa + a de Rendimentos (entra na receita).
            df_prog_r    = df_r_vinc[df_r_vinc['Descrição da Receita'].str.upper().str.strip()
                                     .isin([prog, f"RENDIMENTOS {prog}"])].copy()
            # Cards (Repasse/Orçado/2025) usam apenas a linha principal do programa.
            df_prog_main = df_prog_r[df_prog_r['Descrição da Receita'].str.upper().str.strip()==prog]
            rep_2025     = df_prog_main['2025'].sum() if '2025' in df_prog_main.columns else 0
            prev_repasse = df_prog_main['Repasse'].sum() if 'Repasse' in df_prog_main.columns else 0
            orcado_2026  = df_prog_main['Orçado Receitas'].sum() if 'Orçado Receitas' in df_prog_main.columns else 0
            desp_liq     = df_df_raw[df_df_raw['Fonte'].isin(mapa_desp[prog]) &
                                      (df_df_raw['Tipo']=='Liquidado')][meses_disponiveis].sum().sum()

            st.markdown(f"<h4 style='color:{COR_PROG[prog]};margin-bottom:4px;'>"
                        f"📊 Programa: {prog}</h4>", unsafe_allow_html=True)
            c1, c2, c3 = st.columns(3)
            with c1: st.metric("Arrecadado em 2025", formar_real(rep_2025))
            with c2: st.metric("Previsão de Repasse", formar_real(prev_repasse))
            with c3: st.metric("Orçado 2026 (Município)", formar_real(orcado_2026))

            # ALTERAÇÃO 10: botão individual por programa
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
            else:
                rec_acum = soma_vinc(df_prog_r, meses_disponiveis)
                fig_vinc = go.Figure()
                fig_vinc.add_trace(go.Bar(
                    x=[f"Receita ({meses_disponiveis[0][:3]}–{meses_disponiveis[-1][:3]})"], y=[rec_acum],
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
                    yaxis=dict(showticklabels=False, title=None),
                    xaxis_title=None, showlegend=True, hoverlabel=HOVER_STYLE,
                    legend=dict(orientation="h", yanchor="bottom", y=-0.30,
                                xanchor="center", x=0.5), height=380)

            fig_vinc.update_traces(selector=dict(type='bar'), textposition='outside',
                hovertemplate=("<span style='color:white;'><b>%{x}</b><br>"
                               "Programa: "+prog+"<br>Tipo: %{data.name}<br>"
                               "Valor: <b>R$ %{y:,.2f}</b></span><extra></extra>"),
                hoverlabel=HOVER_STYLE)
            fig_vinc.update_layout(separators=",.", yaxis=dict(showticklabels=False,title=None),
                                   xaxis_title=None, showlegend=True,
                                   legend=dict(orientation="h",yanchor="bottom",y=-0.30,
                                               xanchor="center",x=0.5), height=380)
            st.plotly_chart(fig_vinc, use_container_width=True, config=CONFIG_PT)
            st.markdown("---")

    # =========================================================================
    # SETOR VISÃO MACRO DA EDUCAÇÃO
    # =========================================================================
    elif st.session_state.setor == 'Visão Macro':
        st.markdown("<h1 style='text-align:left;'>📖 São Tomás de Aquino — Visão Macro da Educação</h1>",
                    unsafe_allow_html=True)
        st.markdown("---")

        # ── Colunas de liquidado disponíveis no período (dinâmico) ────────────
        liq_cols = [f"{m}_Liquidado" for m in meses_disponiveis
                    if f"{m}_Liquidado" in df_f_raw.columns]
        _periodo = f"{meses_disponiveis[0][:3]}–{meses_disponiveis[-1][:3]}"

        # Capital: Obras e Instalações + Equipamentos e Materiais Permanentes
        # Custeio: todos os demais elementos
        CAPITAL_ELEMENTOS = ['Obras e Instalações', 'Equipamentos e Materiais Permanentes']
        df_macro = df_f_raw.copy()
        df_macro['Natureza'] = df_macro['Elemento'].apply(
            lambda x: 'Capital' if str(x).strip() in CAPITAL_ELEMENTOS else 'Custeio'
        )

        total_capital = df_macro[df_macro['Natureza']=='Capital'][liq_cols].sum().sum()
        total_custeio = df_macro[df_macro['Natureza']=='Custeio'][liq_cols].sum().sum()
        total_macro   = total_capital + total_custeio
        orcado_total  = df_macro['Orçado'].sum()

        # Cards superiores
        m1, m2, m3 = st.columns(3)
        with m1: st.metric(f"Total Liquidado ({_periodo})", formar_real(total_macro))
        with m2: st.metric("Capital Liquidado", formar_real(total_capital),
                           delta=f"{total_capital/total_macro*100:.1f}% do total" if total_macro>0 else "—",
                           delta_color="off")
        with m3: st.metric("Custeio Liquidado", formar_real(total_custeio),
                           delta=f"{total_custeio/total_macro*100:.1f}% do total" if total_macro>0 else "—",
                           delta_color="off")
        st.markdown("---")

        # ═════════════════════════════════════════════════════════════════════
        # GRÁFICO 1 — Pizza Capital x Custeio
        # ═════════════════════════════════════════════════════════════════════
        st.subheader(f"🔹 1. Capital × Custeio (Liquidado {_periodo})")

        df_pizza = pd.DataFrame([
            {"Natureza": "Capital",  "Valor": total_capital},
            {"Natureza": "Custeio",  "Valor": total_custeio},
        ])
        fig_macro_pizza = px.pie(
            df_pizza, values='Valor', names='Natureza', hole=0.42,
            color='Natureza',
            color_discrete_map={'Capital':'#e74c3c', 'Custeio':'#1a7a4a'},
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

        # ═════════════════════════════════════════════════════════════════════
        # GRÁFICO 2 — Liquidado por Elemento (barras horizontais)
        # ═════════════════════════════════════════════════════════════════════
        st.subheader("🔹 2. Liquidado por Elemento")

        df_elem = df_macro.groupby(['Elemento','Natureza'])[liq_cols].sum().reset_index()
        df_elem['Total'] = df_elem[liq_cols].sum(axis=1)
        df_elem = df_elem[df_elem['Total']>0].sort_values('Total', ascending=True)

        fig_macro_elem = px.bar(
            df_elem, x='Total', y='Elemento', orientation='h',
            color='Natureza',
            color_discrete_map={'Capital':'#e74c3c', 'Custeio':'#1a7a4a'},
            text='Total',
        )
        fig_macro_elem.update_traces(
            texttemplate="R$ %{x:,.0f}",
            textposition='outside',
            hovertemplate=(
                "<span style='color:white;'><b>%{y}</b><br>"
                "Natureza: %{data.name}<br>"
                "Liquidado: <b>R$ %{x:,.2f}</b></span><extra></extra>"
            ),
            hoverlabel=HOVER_STYLE,
        )
        fig_macro_elem.update_layout(
            separators=",.",
            xaxis=dict(showticklabels=False, title=None),
            yaxis=dict(title=None), showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=-0.15, xanchor="center", x=0.5),
            height=500, margin=dict(r=200),
        )
        st.plotly_chart(fig_macro_elem, use_container_width=True, config=CONFIG_PT)

    # =========================================================================
    # SETOR FOLHA DE PAGAMENTO
    # =========================================================================
    elif st.session_state.setor == 'Folha de Pagamento':
        st.markdown("<h1 style='text-align:left;'>📖 São Tomás de Aquino — Folha de Pagamento</h1>",
                    unsafe_allow_html=True)
        st.markdown("---")

        # ── Elementos de pessoal (folha) ─────────────────────────────────────
        FOLHA_ELEMENTOS = [
            'Vencimentos e Vantagens Fixas - Pessoal Civil',
            'Obrigações Patronais',
            'Contratação por tempo Determinado',
            'Outras Despesas Variáveis - Pessoal Civil',
            'Indenizações e Restituições Trabalhistas',
            'Aposentadorias, Reserva Remunerada e Reformas',
            'Diárias - Pessoal Civil',
            'Auxílio-alimentação',
            'Obrigações Tributárias e Contributivas',
        ]
        liq_cols_f = [f"{m}_Liquidado" for m in meses_disponiveis
                      if f"{m}_Liquidado" in df_f_raw.columns]
        _periodo_f = f"{meses_disponiveis[0][:3]}–{meses_disponiveis[-1][:3]}"

        df_folha = df_f_raw[df_f_raw['Elemento'].isin(FOLHA_ELEMENTOS)].copy()

        # REGRA UNIVERSAL — origem_fonte separa TODAS as fontes individualmente
        # (padrão Delfinópolis): nunca agrupar 15001/1500 num único 'Recursos Próprios'.
        def origem_fonte(f):
            if f == '15407': return 'FUNDEB 70%'
            if f == '15403': return 'FUNDEB 30%'
            if f == '15001': return 'Rec. Próprios (15001)'
            if f == '1500':  return 'Rec. Próprios (1500)'
            return f'Fonte {f}'

        df_folha['Origem'] = df_folha['Fonte'].apply(origem_fonte)

        total_folha   = df_folha[liq_cols_f].sum().sum()
        total_fund70  = df_folha[df_folha['Origem']=='FUNDEB 70%'][liq_cols_f].sum().sum()
        total_fund30  = df_folha[df_folha['Origem']=='FUNDEB 30%'][liq_cols_f].sum().sum()
        total_rp      = df_folha[df_folha['Origem'].str.startswith('Rec. Próprios', na=False)][liq_cols_f].sum().sum()

        # ── Cards superiores ──────────────────────────────────────────────────
        f1, f2, f3, f4 = st.columns(4)
        with f1: st.metric(f"Total Folha ({_periodo_f})", formar_real(total_folha))
        with f2: st.metric("FUNDEB 70% (Fonte 15407)",  formar_real(total_fund70),
                           delta=f"{total_fund70/total_folha*100:.1f}%" if total_folha>0 else "—",
                           delta_color="off")
        with f3: st.metric("Rec. Próprios (15001 + 1500)", formar_real(total_rp),
                           delta=f"{total_rp/total_folha*100:.1f}%" if total_folha>0 else "—",
                           delta_color="off")
        with f4: st.metric("FUNDEB 30% (Fonte 15403)", formar_real(total_fund30),
                           delta=f"{total_fund30/total_folha*100:.1f}%" if total_folha>0 else "—",
                           delta_color="off")
        st.markdown("---")

        # ═════════════════════════════════════════════════════════════════════
        # GRÁFICO 1 — Pizza: Origem dos recursos da folha
        # ═════════════════════════════════════════════════════════════════════
        st.subheader("🔹 1. Origem dos Recursos — Folha de Pagamento")

        df_orig = (df_folha.groupby('Origem')[liq_cols_f].sum()
                   .sum(axis=1).reset_index().rename(columns={0:'Valor'}))
        df_orig = df_orig[df_orig['Valor']>0]

        COR_ORIGEM = {
            'FUNDEB 70%':            '#4a0000',
            'FUNDEB 30%':            '#ff1744',
            'Rec. Próprios (15001)': '#1a7a4a',
            'Rec. Próprios (1500)':  '#17a589',
            'Outras Fontes':         '#888888',
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

        # ═════════════════════════════════════════════════════════════════════
        # GRÁFICO 2 — Liquidado por Elemento da Folha
        # REGRA UNIVERSAL: UMA barra por elemento (Total); detalhamento por
        # origem APENAS no hover (nunca empilhar por origem).
        # ═════════════════════════════════════════════════════════════════════
        st.subheader("🔹 2. Liquidado por Elemento da Folha")

        df_eo = df_folha.groupby(['Elemento','Origem'])[liq_cols_f].sum()
        df_eo = df_eo.sum(axis=1).reset_index().rename(columns={0:'Valor'})
        df_eo = df_eo[df_eo['Valor']>0]

        det_map = {}
        for elem, grp in df_eo.groupby('Elemento'):
            linhas = [f"{r['Origem']}: {formar_real(r['Valor'])}"
                      for _, r in grp.sort_values('Valor', ascending=False).iterrows()]
            det_map[elem] = "<br>".join(linhas)

        df_elem_f = (df_folha.groupby('Elemento')[liq_cols_f].sum()
                     .sum(axis=1).reset_index().rename(columns={0:'Total'}))
        df_elem_f = df_elem_f[df_elem_f['Total']>0].sort_values('Total', ascending=True)
        df_elem_f['Detalhe'] = df_elem_f['Elemento'].map(det_map)

        fig_folha_elem = px.bar(
            df_elem_f, x='Total', y='Elemento', orientation='h',
            text='Total', custom_data=['Detalhe'],
            color_discrete_sequence=['#4a0000'],
        )
        fig_folha_elem.update_traces(
            texttemplate="R$ %{x:,.0f}",
            textposition='outside',
            hovertemplate=(
                "<span style='color:white;'><b>%{y}</b><br>"
                "Liquidado: <b>R$ %{x:,.2f}</b><br>"
                "─── Por origem ───<br>%{customdata[0]}</span><extra></extra>"
            ),
            hoverlabel=HOVER_STYLE,
        )
        fig_folha_elem.update_layout(
            separators=",.",
            xaxis=dict(showticklabels=False, title=None),
            yaxis=dict(title=None), showlegend=False,
            height=480, margin=dict(r=180),
        )
        st.plotly_chart(fig_folha_elem, use_container_width=True, config=CONFIG_PT)
        st.markdown("---")

        # ═════════════════════════════════════════════════════════════════════
        # GRÁFICO 3 — Evolução Mensal da Folha
        # ═════════════════════════════════════════════════════════════════════
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

    # ── Relatório Geral de Fichas (todos os setores) ──────────────────────────
    st.markdown("### 📋 Relatório Geral de Fichas")
    df_f_filt = df_f_raw[df_f_raw['Atividade'].str.contains(
        search_term, na=False, case=False)].copy()
    st.dataframe(df_f_filt, use_container_width=True, hide_index=True)

else:
    st.error("Erro ao carregar os arquivos CSV. Verifique a pasta 'zEducação'.")