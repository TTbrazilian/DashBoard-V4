import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.io as pio
import os
import unicodedata
import plotly.graph_objects as go
import streamlit.components.v1 as components
from random import random

st.set_page_config(page_title="Gestão de Recursos - Cássia", layout="wide")

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
    </style>
""", unsafe_allow_html=True)

pio.templates.default = "plotly_white"
CONFIG_PT = {'displaylogo': False, 'showTips': False}

MESES_ORDEM = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
               'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']

# Rótulos amigáveis das fontes de saúde (baseado no Cássia_DF.csv)
FONTE_LABEL = {
    '1500':'1500 · Próprio Saúde','1600':'1600 · Federal Custeio','1601':'1601 · Federal Capital',
    '1602':'1602 · Covid','1603':'1603 · Covid','1604':'1604 · Agentes','1605':'1605 · Piso Enferm.',
    '1621':'1621 · Estadual','1631':'1631 · Conv. Federal','1659':'1659 · Trans. Federais',
    '2621':'2621 · Supr. Estadual','1706':'1706 · Emenda Federal',
}
def fonte_lbl(f): return FONTE_LABEL.get(str(f).strip(), f"Fonte {f}")

# Paleta para despesas por fonte
CORES_FONTE = {
    '1500':'#7f8c8d','1600':'#2E86C1','1601':'#154360','1602':'#8e44ad','1603':'#9b59b6',
    '1604':'#16a085','1605':'#f39c12','1621':'#27ae60','1631':'#2980b9','1659':'#1abc9c',
    '2621':'#e67e22','1706':'#c0392b',
}
def cor_fonte(f): return CORES_FONTE.get(str(f).strip(), '#95a5a6')

C_FEDERAL  = '#2E86C1'
C_ESTADUAL = '#28B463'

# Elementos de folha/pessoal (ajustável). Usados em "Folha por Fonte".
FOLHA_ELEMENTOS = [
    'Vencimentos e Vantagens Fixas - Pessoal Civil',
    'Obrigações Patronais',
    'Contratação por tempo Determinado',
    'Outras Despesas Variáveis - Pessoal Civil',
    'Indenizações e Restituições Trabalhistas',
    'Auxílio-Alimentação',
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
# • Cássia.csv    — FICHAS (header=1; Empenhado/Liquidado/Pago por mês; '.1'=Liquidado;
#                   'Abril ' com espaço). 5 categorias.
# • Cássia_R.csv  — Receitas de Impostos + Cota-Parte (base do índice de 15%).
# • Cássia_DF.csv — Despesas por Fonte (blocos Empenhado/Liquidado/Pago; fonte 1500 = próprio).
# • Cássia_RV.csv — Receitas Vinculadas Federais/Estaduais por categoria (novo).
@st.cache_data
def load_data():
    diretorio_atual = os.path.dirname(os.path.abspath(__file__))

    def _buscar(nome):
        for p in [os.path.join(diretorio_atual, '..', 'zSaúde', nome),
                  os.path.join(diretorio_atual, 'zSaúde', nome), nome]:
            if os.path.exists(p): return p
        return None

    path_f  = _buscar("Cássia.csv")
    path_r  = _buscar("Cássia_R.csv")
    path_df = _buscar("Cássia_DF.csv")
    path_rv = _buscar("Cássia_RV.csv")
    if not path_f: return None, None, None, None

    # ── FICHAS ───────────────────────────────────────────────────────────────
    df = pd.read_csv(path_f, sep=None, engine='python', encoding='utf-8', header=1)
    df.columns = [str(c).strip() for c in df.columns]
    for col in df.columns:
        if any(k in col for k in ['Orçado','Creditado','Anulado','Saldo'] + MESES_ORDEM + ['Total']):
            df[col] = df[col].apply(limpar_valor)
    df['Ficha']     = df['Ficha'].astype(str).str.replace('.0','',regex=False).str.strip()
    df['Fonte']     = df['Fonte'].astype(str).str.replace('.0','',regex=False).str.strip()
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
    if path_r:
        df_r = pd.read_csv(path_r, sep=None, engine='python', encoding='utf-8', header=0)
        df_r.columns = [str(c).strip() for c in df_r.columns]
        if 'Categoria' in df_r.columns:
            df_r['Categoria'] = df_r['Categoria'].astype(str).str.strip()
        for col in df_r.columns:
            if col in MESES_ORDEM + ['Total','Orçado Receitas']:
                df_r[col] = df_r[col].apply(limpar_valor)

    # ── DESPESAS POR FONTE ───────────────────────────────────────────────────
    df_df = None
    if path_df:
        df_df = pd.read_csv(path_df, sep=None, engine='python', encoding='utf-8')
        df_df.columns = [str(c).strip() for c in df_df.columns]
        df_df['Tipo'] = df_df['Tipo'].replace({'Empenho': 'Liquidado'})
        df_df = df_df[df_df['Tipo'].isin(['Empenhado','Liquidado','Pago'])].copy()
        df_df['Tipo']  = df_df['Tipo'].str.strip()
        df_df['Fonte'] = df_df['Fonte'].astype(str).str.replace('.0','',regex=False).str.strip()
        for col in df_df.columns:
            if col in MESES_ORDEM + ['Total']:
                df_df[col] = df_df[col].apply(limpar_valor)

    # ── RECEITAS VINCULADAS (Federal/Estadual por categoria) ─────────────────
    df_rv = None
    if path_rv:
        df_rv = pd.read_csv(path_rv, sep=None, engine='python', encoding='utf-8', header=0)
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

df_raw, df_r, df_df, df_rv = load_data()

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
    cols_liq = [f"{m}_Liq" for m in meses_disp if f"{m}_Liq" in df_raw.columns]
    cats = sorted(df_raw['Categoria'].dropna().unique())

    # ── ESTADO / NAVEGAÇÃO ────────────────────────────────────────────────────
    if 'modo' not in st.session_state:
        st.session_state.modo = 'Visão Macro'

    st.sidebar.header("🧭 Navegação")
    if st.sidebar.button("🌐 Visão Macro", use_container_width=True,
                         type=("primary" if st.session_state.modo == 'Visão Macro' else "secondary")):
        st.session_state.modo = 'Visão Macro'
        st.rerun()

    st.sidebar.write("Análise por Categoria:")
    for c in cats:
        if st.sidebar.button(c, use_container_width=True, key=f"cat_{c}",
                             type=("primary" if st.session_state.modo == c else "secondary")):
            st.session_state.modo = c
            st.rerun()

    # ── Sidebar universal iG2P (logo como botão Home) ─────────────────────────
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

    components.html(
        _js_sidebar_universal(
            _ler_logo("LOGOTIPO IG2P - OFICIAL - BRANCO.png"),
            _ler_logo("LOGOTIPO IG2P - OFICIAL.png"),
        ),
        height=0,
    )

    # ══════════════════════════════════════════════════════════════════════════
    # HELPERS DE RENDERIZAÇÃO (compartilhados entre Visão Macro e Categoria)
    # ══════════════════════════════════════════════════════════════════════════
    def render_execucao_orcamentaria(dados, titulo="Execução Orçamentária"):
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
        linhas = []
        for m in meses_disp:
            col = f"{m}_Liq"
            linhas.append({"Mês": m, "Valor": dados[col].sum() if col in dados.columns else 0.0})
        dfm = pd.DataFrame(linhas)
        fig = px.line(dfm, x='Mês', y='Valor', markers=True,
                      color_discrete_sequence=["#00CC96"])
        fig.update_layout(yaxis_tickprefix='R$ ', yaxis_tickformat=',.2f', separators=',.',
                          xaxis_title=None, yaxis_title="Liquidado (R$)", height=360)
        fig.update_traces(hovertemplate="<b>%{x}</b><br>Liquidado: R$ %{y:,.2f}<extra></extra>")
        st.plotly_chart(fig, use_container_width=True, config=CONFIG_PT)

    def render_custeio_capital_pizza(dados):
        st.subheader("📊 Custeio × Capital")
        dn = dados.groupby('Natureza')['Total_Liq'].sum().reset_index()
        for nat in ['Capital (Invest.)','Custeio (Manut.)']:
            if nat not in dn['Natureza'].values:
                dn = pd.concat([dn, pd.DataFrame({'Natureza':[nat],'Total_Liq':[0.0]})], ignore_index=True)
        fig = px.pie(dn, values='Total_Liq', names='Natureza', hole=.4, color='Natureza',
                     color_discrete_map={'Custeio (Manut.)':'#00CC96','Capital (Invest.)':'#EF553B'})
        fig.update_layout(margin=dict(t=40,b=40,l=20,r=20), height=420, separators=',.',
                          legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.05,
                                      font=dict(size=15)))
        fig.update_traces(textinfo='percent', textposition='inside',
                          hovertemplate="<b>%{label}</b><br>Valor: R$ %{value:,.2f}<extra></extra>")
        _, cc, _ = st.columns([1,2,1])
        with cc: st.plotly_chart(fig, use_container_width=True, config=CONFIG_PT)

    def render_folha_por_fonte(dados, titulo="💼 Folha de Pagamento por Fonte"):
        st.subheader(titulo)
        folha = dados[dados['Elemento'].isin(FOLHA_ELEMENTOS)]
        total = folha['Total_Liq'].sum()
        if total <= 0:
            st.info("Sem despesas de folha liquidadas no período para este recorte.")
            return
        gf = folha.groupby('Fonte')['Total_Liq'].sum().reset_index()
        gf = gf[gf['Total_Liq'] > 0].sort_values('Total_Liq', ascending=True)
        gf['Rotulo'] = gf['Fonte'].apply(fonte_lbl)
        fig = go.Figure(go.Bar(
            x=gf['Total_Liq'], y=gf['Rotulo'], orientation='h',
            marker_color=[cor_fonte(f) for f in gf['Fonte']],
            text=[formar_real(v) for v in gf['Total_Liq']], textposition='outside',
            hovertemplate="<b>%{y}</b><br>Folha Liquidada: R$ %{x:,.2f}<extra></extra>",
        ))
        fig.update_layout(height=90+55*len(gf), separators=',.',
                          xaxis_title="Folha Liquidada (R$)", yaxis_title="",
                          margin=dict(l=170, r=120, t=30, b=40),
                          xaxis=dict(range=[0, gf['Total_Liq'].max()*1.22]))
        st.plotly_chart(fig, use_container_width=True, config=CONFIG_PT)
        st.caption(f"Folha total do recorte: **{formar_real(total)}**")

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
            components.html(f"""<script id="scroll_{sid}">
                var s=()=>{{const el=window.parent.document.querySelector('.st-key-detalhamento-fichas');
                if(el)el.scrollIntoView({{behavior:"smooth",block:"center"}});}};setTimeout(s,150);
                </script>""", height=0)
            dd = dados[dados['Elemento'] == ele].sort_values('Orçado', ascending=False).copy()
            st.subheader(f"📊 Detalhamento de Fichas: {ele}")
            fig = px.bar(dd, x='Ficha', y='Orçado', color_discrete_sequence=["#00CC96"],
                         custom_data=['Categoria','Fonte'])
            fig.update_traces(
                hovertemplate=("<b>Categoria:</b> %{customdata[0]}<br>"
                               "<b>Fonte:</b> %{customdata[1]}<br>"
                               "<b>Valor:</b> R$ %{y:,.2f}<extra></extra>"),
                text=dd['Orçado'].apply(formar_real), textposition='outside',
                cliponaxis=False, width=0.8 if len(dd) < 12 else 0.5)
            fig.update_layout(xaxis_type='category', height=520, separators=',.',
                              yaxis=dict(range=[0, dd['Orçado'].max()*1.30]),
                              margin=dict(t=80,b=50,l=50,r=50))
            st.plotly_chart(fig, use_container_width=True, theme=None,
                            config=CONFIG_PT, key="detalhamento-fichas")
            if st.button("⬅️ Voltar para Visão Geral", key=f"{key_prefix}_voltar"):
                del st.session_state['elemento_ativo']
                st.rerun()

    # ══════════════════════════════════════════════════════════════════════════
    # MODO 1 — VISÃO MACRO
    # ══════════════════════════════════════════════════════════════════════════
    if st.session_state.modo == 'Visão Macro':
        st.title("🌐 Cássia — Saúde · Visão Macro")
        st.caption("Análise dos recursos totais da Saúde no período "
                   f"({meses_disp[0]}–{meses_disp[-1]}).")
        st.markdown("---")

        # 2.1 — Execução orçamentária (mantida)
        render_execucao_orcamentaria(df_raw)
        st.markdown("---")

        # 2.3 — Análise dos 15% (mínimo constitucional em saúde, sem deduções)
        st.subheader("🎯 Aplicação Mínima em Saúde (15%)")
        if df_r is not None and df_df is not None:
            base_15 = soma_cols(df_r[df_r['Categoria'].isin(['Impostos','Cota-Parte'])], meses_disp)
            desp_1500 = soma_cols(
                df_df[(df_df['Fonte'] == '1500') & (df_df['Tipo'] == 'Liquidado')], meses_disp)
            indice_15 = (desp_1500 / base_15 * 100) if base_15 > 0 else 0.0
            meta_valor = base_15 * 0.15

            k1, k2, k3, k4 = st.columns(4)
            with k1: st.metric("Receita Base (Impostos + Cota-Parte)", formar_real(base_15))
            with k2: st.metric("Aplicado em Saúde (Fonte 1500)", formar_real(desp_1500))
            with k3: st.metric("Índice de Aplicação",
                               f"{indice_15:.2f}%".replace('.',','),
                               delta=f"{indice_15-15:.2f} p.p. vs 15%".replace('.',','),
                               delta_color=("normal" if indice_15 >= 15 else "inverse"))
            with k4: st.metric("Mínimo Exigido (15%)", formar_real(meta_valor))

            fig15 = go.Figure()
            fig15.add_bar(x=['Aplicado em Saúde<br>(Fonte 1500)'], y=[desp_1500],
                          marker_color=('#27ae60' if indice_15 >= 15 else '#e74c3c'),
                          text=[formar_real(desp_1500)], textposition='outside',
                          hovertemplate="Aplicado: R$ %{y:,.2f}<extra></extra>", width=0.5)
            fig15.add_hline(y=meta_valor, line_dash="dash", line_color="#003366",
                            annotation_text=f"Meta 15% = {formar_real(meta_valor)}",
                            annotation_position="top left")
            fig15.update_layout(height=380, separators=',.', yaxis_title="R$",
                                yaxis=dict(range=[0, max(desp_1500, meta_valor)*1.25]),
                                margin=dict(t=40,b=30,l=40,r=40), showlegend=False)
            st.plotly_chart(fig15, use_container_width=True, config=CONFIG_PT)
            if indice_15 >= 15:
                st.success(f"✔ O município aplicou **{indice_15:.2f}%** das receitas de impostos e "
                           f"transferências em Ações e Serviços Públicos de Saúde (ASPS), acima do "
                           f"mínimo constitucional de 15%.".replace('.',',',1))
            else:
                st.error(f"⚠ Aplicação de **{indice_15:.2f}%**, abaixo do mínimo constitucional de "
                         f"15% (ASPS).".replace('.',',',1))
            st.caption("Base legal: CF/1988 art. 198 §2º e §3º; LC nº 141/2012 (define ASPS e o "
                       "mínimo de 15%). Cálculo sem deduções: despesa própria de saúde (fonte 1500) "
                       "sobre a receita de impostos e cota-parte.")
        else:
            st.info("Dados de receitas/despesas indisponíveis para o cálculo dos 15%.")
        st.markdown("---")

        # 2.4 — Receitas Federais e Estaduais por categoria
        st.subheader("🏛️ Receitas Vinculadas — Federais e Estaduais por Categoria")
        if df_rv is not None and not df_rv.empty:
            grv = (df_rv.assign(V=df_rv[[m for m in meses_disp if m in df_rv.columns]].sum(axis=1))
                        .groupby(['Categoria','Origem'])['V'].sum().reset_index())
            grv = grv[grv['V'] > 0]
            ordem_cat = (grv.groupby('Categoria')['V'].sum()
                         .sort_values(ascending=False).index.tolist())
            fig_rv = px.bar(grv, x='Categoria', y='V', color='Origem', barmode='group',
                            color_discrete_map={'Federal':C_FEDERAL,'Estadual':C_ESTADUAL},
                            category_orders={'Categoria': ordem_cat})
            fig_rv.update_traces(
                hovertemplate="<b>%{x}</b><br><b>%{data.name}:</b> R$ %{y:,.2f}<extra></extra>")
            fig_rv.update_layout(height=430, separators=',.', xaxis_title="",
                                 yaxis_title="Receita (R$)", legend_title="Origem",
                                 margin=dict(t=30,b=40))
            st.plotly_chart(fig_rv, use_container_width=True, config=CONFIG_PT)
            tot_fed = grv[grv['Origem']=='Federal']['V'].sum()
            tot_est = grv[grv['Origem']=='Estadual']['V'].sum()
            cfed, cest, ctot = st.columns(3)
            with cfed: st.metric("Total Federal", formar_real(tot_fed))
            with cest: st.metric("Total Estadual", formar_real(tot_est))
            with ctot: st.metric("Total Vinculado", formar_real(tot_fed+tot_est))
        else:
            st.info("Arquivo de Receitas Vinculadas (Cássia_RV) indisponível.")
        st.markdown("---")

        # 2.5 — Custeio × Capital detalhado por fonte
        st.subheader("📊 Custeio × Capital — Detalhado por Fonte")
        gcc = (df_raw.groupby(['Fonte','Natureza'])['Total_Liq'].sum().reset_index())
        gcc = gcc[gcc['Total_Liq'] > 0].copy()
        gcc['Rotulo'] = gcc['Fonte'].apply(fonte_lbl)
        ordem_f = (gcc.groupby('Rotulo')['Total_Liq'].sum()
                   .sort_values(ascending=False).index.tolist())
        fig_cc = px.bar(gcc, x='Rotulo', y='Total_Liq', color='Natureza',
                        barmode='stack', category_orders={'Rotulo': ordem_f},
                        color_discrete_map={'Custeio (Manut.)':'#00CC96',
                                            'Capital (Invest.)':'#EF553B'})
        fig_cc.update_traces(
            hovertemplate="<b>%{x}</b><br><b>%{data.name}:</b> R$ %{y:,.2f}<extra></extra>")
        fig_cc.update_layout(height=440, separators=',.', xaxis_title="",
                             yaxis_title="Liquidado (R$)", legend_title="Natureza",
                             margin=dict(t=30,b=90), xaxis_tickangle=-25)
        st.plotly_chart(fig_cc, use_container_width=True, config=CONFIG_PT)
        tc = df_raw[df_raw['Natureza']=='Custeio (Manut.)']['Total_Liq'].sum()
        tk = df_raw[df_raw['Natureza']=='Capital (Invest.)']['Total_Liq'].sum()
        cc1, cc2 = st.columns(2)
        with cc1: st.metric("Total Custeio", formar_real(tc))
        with cc2: st.metric("Total Capital", formar_real(tk))
        st.markdown("---")

        # 2.8 — Total Investido em Saúde (pizza por categoria) — mantido
        st.subheader(f"🏥 Total Investido em Saúde — Liquidado ({meses_disp[0]}–{meses_disp[-1]})")
        NOME_CAT = {'Secretaria':'Administração','Atenção Primária':'Atenção Primária',
                    'MAC':'Ambulatorial e Especialidades (MAC)','Farmácia':'Farmácia',
                    'Vigilância':'Vigilância'}
        CORES_CAT = {'Administração':'#f39c12','Atenção Primária':'#4A90D9',
                     'Ambulatorial e Especialidades (MAC)':'#1a3a6b','Farmácia':'#27ae60',
                     'Vigilância':'#e74c3c'}
        dpz = df_raw.groupby('Categoria')['Total_Liq'].sum().reset_index()
        dpz['Label'] = dpz['Categoria'].map(NOME_CAT).fillna(dpz['Categoria'])
        dpz = dpz[dpz['Total_Liq'] > 0]
        total_geral = dpz['Total_Liq'].sum()
        fig_pz = px.pie(dpz, values='Total_Liq', names='Label', hole=0.0,
                        color='Label', color_discrete_map=CORES_CAT)
        fig_pz.update_traces(
            textinfo='label+percent', textposition='outside', pull=[0.03]*len(dpz),
            hovertemplate=("<b>%{label}</b><br>Liquidado: <b>R$ %{value:,.2f}</b><br>"
                           "Participação: <b>%{percent}</b><extra></extra>"),
            hoverlabel=dict(bgcolor="rgba(0,0,0,0.85)", font_size=13, font_color="white"))
        fig_pz.update_layout(
            title=dict(text=f"Total Liquidado: <b>{formar_real(total_geral)}</b>",
                       x=0.5, xanchor='center', font=dict(size=14)),
            showlegend=True, height=480, separators=',.',
            legend=dict(orientation="v", yanchor="middle", y=0.8, xanchor="left", x=1.02,
                        font=dict(size=13), itemclick="toggle", itemdoubleclick="toggleothers"),
            margin=dict(t=60,b=40,l=20,r=180))
        _, cpz, _ = st.columns([0.5,3,0.5])
        with cpz: st.plotly_chart(fig_pz, use_container_width=True, config=CONFIG_PT)
        st.markdown("---")

        # 2.9 — Folha Total por fonte
        render_folha_por_fonte(df_raw, "💼 Folha de Pagamento Total — por Fonte")

    # ══════════════════════════════════════════════════════════════════════════
    # MODO 2 — ANÁLISE POR CATEGORIA
    # ══════════════════════════════════════════════════════════════════════════
    else:
        cat = st.session_state.modo
        df_cat = df_raw[df_raw['Categoria'] == cat].copy()
        st.title(f"📂 {cat} — Saúde")
        st.caption(f"Análise da categoria no período ({meses_disp[0]}–{meses_disp[-1]}).")
        st.markdown("---")

        # 3.1 — Execução orçamentária da categoria (mantida)
        render_execucao_orcamentaria(df_cat)
        st.markdown("---")

        # 3.2 — Receitas × Despesas mensal — Vinculados Federal/Estadual (modelo FUNDEB)
        st.subheader("🔄 Receitas × Despesas Mensal — Recursos Vinculados (Federal/Estadual)")
        rv_cat = df_rv[df_rv['Categoria'] == cat] if df_rv is not None else None
        desp_vinc = df_cat[df_cat['Fonte'] != '1500']
        tem_rec = rv_cat is not None and not rv_cat.empty
        tem_desp = not desp_vinc.empty and desp_vinc[cols_liq].sum().sum() > 0
        if tem_rec or tem_desp:
            fig_rd = go.Figure()
            # Receitas por origem (empilhadas), offsetgroup 'Receita'
            if tem_rec:
                for origem, cor in [('Federal', C_FEDERAL), ('Estadual', C_ESTADUAL)]:
                    sub = rv_cat[rv_cat['Origem'] == origem]
                    vals = [sub[m].sum() if m in sub.columns else 0.0 for m in meses_disp]
                    if sum(vals) <= 0: continue
                    fig_rd.add_bar(x=meses_disp, y=vals, name=f"Receita {origem}",
                                   marker_color=cor, offsetgroup='Receita', legendgroup='rec',
                                   hovertemplate=(f"<b>%{{x}}</b><br>Receita {origem}: "
                                                  "R$ %{y:,.2f}<extra></extra>"))
            # Despesas por fonte (empilhadas), offsetgroup 'Despesa'
            if tem_desp:
                for fonte in sorted(desp_vinc['Fonte'].unique()):
                    sub = desp_vinc[desp_vinc['Fonte'] == fonte]
                    vals = [sub[f"{m}_Liq"].sum() if f"{m}_Liq" in sub.columns else 0.0
                            for m in meses_disp]
                    if sum(vals) <= 0: continue
                    fig_rd.add_bar(x=meses_disp, y=vals, name=fonte_lbl(fonte),
                                   marker_color=cor_fonte(fonte), offsetgroup='Despesa',
                                   legendgroup='desp',
                                   hovertemplate=(f"<b>%{{x}}</b><br>{fonte_lbl(fonte)} (desp.): "
                                                  "R$ %{y:,.2f}<extra></extra>"))
            fig_rd.update_layout(barmode='relative', height=470, separators=',.',
                                 yaxis_title="R$", xaxis_title="",
                                 legend_title="Receitas (cor) × Despesas (fonte)",
                                 margin=dict(t=30,b=40))
            st.plotly_chart(fig_rd, use_container_width=True, config=CONFIG_PT)
            st.caption("Barra à esquerda de cada mês = **Receitas Vinculadas** (por origem); "
                       "barra à direita = **Despesas** liquidadas (por fonte). Fonte própria (1500) "
                       "não entra neste comparativo de recursos vinculados.")
        else:
            st.info("Sem receitas vinculadas ou despesas de fontes vinculadas para esta categoria "
                    "no período.")
        st.markdown("---")

        # 3.5 — Custeio × Capital ANTES do detalhamento de fichas
        render_custeio_capital_pizza(df_cat)
        st.markdown("---")

        # 3.3 / 3.4 — Detalhamento por elemento + fichas
        render_detalhamento_elemento(df_cat, key_prefix=f"cat_{remover_acentos(cat)}")
        st.markdown("---")

        # 3.8 — Folha por fonte (categoria)
        render_folha_por_fonte(df_cat, "💼 Folha de Pagamento da Categoria — por Fonte")

else:
    st.error("Arquivos de dados não encontrados! Verifique a pasta 'zSaúde'.")