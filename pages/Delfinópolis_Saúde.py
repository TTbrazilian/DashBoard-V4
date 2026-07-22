import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.io as pio
import os
import unicodedata
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
        .stButton button {
            animation: slideIn 0.4s ease-out;
        }
        [data-testid="stSidebarNav"] li:first-child > a > span,
        [data-testid="stSidebarNav"] li:first-child > a > p {
            display: none !important;
        }
    </style>
""", unsafe_allow_html=True)

pio.templates.default = "plotly_white"

CONFIG_PT = {
    'displaylogo': False,
    'showTips': False,
}

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

# ── CARGA DE DADOS ────────────────────────────────────────────────────────────
# Especificidades Delfinópolis:
# • Delfinópolis.csv: mesmo padrão — header=1, colunas triplicadas por mês.
#   'Abril .1' com espaço antes do ponto → rename_liq explícito.
#   Categoria NaN nas últimas linhas → dropna no filtro.
# • 5 categorias: Secretaria, Atenção Primária, Vigilância, Farmácia, MAC.
# • Capital Liq = R$ 181.094,36 | Custeio Liq = R$ 5.115.748,04
# • Delfinópolis_DF.csv: tem linha de cabeçalho repetida (Tipo='Tipo') → filtrada.
#   Apenas 7 fontes com Liquidado (sem Estadual/Conv.Federal/Piso2).
# • Delfinópolis_R.csv: só categoria 'Impostos' (sem Cota-Parte).
#   Colunas sem espaço extra (Março sem espaço).
@st.cache_data
def load_data():
    diretorio_atual = os.path.dirname(os.path.abspath(__file__))

    def _buscar(nome):
        candidatos = [
            os.path.join(diretorio_atual, '..', 'zSaúde', nome),
            os.path.join(diretorio_atual, 'zSaúde', nome),
            nome,
        ]
        for p in candidatos:
            if os.path.exists(p): return p
        return None

    path_f  = _buscar("Delfinópolis.csv")
    path_r  = _buscar("Delfinópolis_R.csv")
    path_df = _buscar("Delfinópolis_DF.csv")
    if not path_f: return None, None, None

    # ── FICHAS ───────────────────────────────────────────────────────────────
    df = pd.read_csv(path_f, sep=None, engine='python', encoding='utf-8', header=1)
    df.columns = [str(c).strip() for c in df.columns]

    for col in df.columns:
        if any(k in col for k in [
            'Orçado','Creditado','Anulado','Saldo',
            'Janeiro','Fevereiro','Março','Abril','Maio','Junho',
            'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro','Total'
        ]):
            df[col] = df[col].apply(limpar_valor)

    df['Ficha']     = df['Ficha'].astype(str).str.replace('.0','',regex=False).str.strip()
    df['Fonte']     = df['Fonte'].astype(str).str.replace('.0','',regex=False).str.strip()
    df['Categoria'] = df['Categoria'].astype(str).str.strip()
    df['Elemento']  = df['Elemento'].astype(str).str.strip()

    # Remove linhas sem categoria válida (NaN convertido para 'nan')
    df = df[df['Categoria'] != 'nan'].copy()

    rename_liq = {
        'Janeiro.1':  'Janeiro_Liq',
        'Fevereiro.1':'Fevereiro_Liq',
        'Março.1':    'Março_Liq',
        'Abril .1':   'Abril_Liq',
        'Maio.1':     'Maio_Liq',
        'Junho.1':    'Junho_Liq',
        'Julho.1':    'Julho_Liq',
        'Agosto.1':   'Agosto_Liq',
        'Setembro.1': 'Setembro_Liq',
        'Outubro.1':  'Outubro_Liq',
        'Novembro.1': 'Novembro_Liq',
        'Dezembro.1': 'Dezembro_Liq',
        'Total.1':    'Total_Liq',
    }
    df = df.rename(columns={k: v for k, v in rename_liq.items() if k in df.columns})

    CAPITAL_ELEM = [
        'Equipamentos e Materiais Permanentes',
        'Obras e Instalações',
        'Aquisição de Imóveis',
    ]
    df['Natureza'] = df['Elemento'].apply(
        lambda x: 'Capital (Invest.)' if x in CAPITAL_ELEM else 'Custeio (Manut.)'
    )

    # ── RECEITAS ─────────────────────────────────────────────────────────────
    df_r = None
    if path_r:
        df_r = pd.read_csv(path_r, sep=None, engine='python', encoding='utf-8', header=0)
        df_r.columns = [str(c).strip() for c in df_r.columns]
        MESES = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
                 'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']
        for col in df_r.columns:
            if col.strip() in MESES + ['Total','Orçado Receitas']:
                df_r[col] = df_r[col].apply(limpar_valor)

    # ── DESPESAS POR FONTE ────────────────────────────────────────────────────
    # Tem linha de cabeçalho repetida (Tipo='Tipo') → filtrada
    df_df = None
    if path_df:
        df_df = pd.read_csv(path_df, sep=None, engine='python', encoding='utf-8')
        df_df.columns = [str(c).strip() for c in df_df.columns]
        df_df = df_df[df_df['Tipo'].isin(['Empenhado','Liquidado','Pago'])].copy()
        df_df['Tipo']  = df_df['Tipo'].str.strip()
        df_df['Fonte'] = df_df['Fonte'].astype(str).str.replace('.0','',regex=False).str.strip()
        for col in df_df.columns:
            if col in ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
                       'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro','Total']:
                df_df[col] = df_df[col].apply(limpar_valor)

    return df, df_r, df_df

df_raw, df_r, df_df = load_data()

# ── INTERFACE ─────────────────────────────────────────────────────────────────
if df_raw is not None:

    # ── SIDEBAR ───────────────────────────────────────────────────────────────
    st.sidebar.header("🔍 Filtros")

    if 'busca' not in st.session_state:
        st.session_state.busca = ""

    busca = st.sidebar.text_input("Filtrar:", value=st.session_state.busca)
    st.session_state.busca = busca

    st.sidebar.write("---")
    st.sidebar.write("Categorias:")
    cats = sorted(df_raw['Categoria'].dropna().unique())
    for c in cats:
        if st.sidebar.button(c, use_container_width=True, key=f"cat_{c}"):
            st.session_state.busca = c
            st.rerun()

    if st.sidebar.button("Limpar Filtros", type="secondary", use_container_width=True):
        st.session_state.busca = ""
        st.rerun()

    # ── Sidebar universal iG2P ────────────────────────────────────────────────
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
            candidatos += [
                os.path.join(d, "Logos", nome_arquivo),
                os.path.join(d, "..", "Logos", nome_arquivo),
            ]
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
            "var _ob=new MutationObserver(function(){run();});"
            "_ob.observe(window.parent.document.body,{childList:true,subtree:true});"
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

    # ── FILTRO GLOBAL ─────────────────────────────────────────────────────────
    df_filtrado_global = df_raw.copy()
    if st.session_state.busca:
        termo = remover_acentos(st.session_state.busca)
        categorias_existentes = {
            remover_acentos(cat): cat
            for cat in df_raw['Categoria'].unique() if pd.notna(cat)
        }
        if termo in categorias_existentes:
            mask = df_filtrado_global['Categoria'].apply(remover_acentos) == termo
        else:
            mask = (
                df_filtrado_global['Categoria'].apply(remover_acentos).str.contains(termo, na=False)
                | (df_filtrado_global['Ficha'] == st.session_state.busca.strip())
                | df_filtrado_global['Elemento'].apply(remover_acentos).str.contains(termo, na=False)
                | df_filtrado_global['Fonte'].str.contains(st.session_state.busca.strip(), na=False)
            )
        df_filtrado_global = df_filtrado_global[mask]

    # ── TÍTULO ────────────────────────────────────────────────────────────────
    st.title("📊 Delfinópolis — Saúde")
    st.markdown("---")

    # ── MÉTRICAS GERAIS ───────────────────────────────────────────────────────
    orcado_total = df_filtrado_global['Orçado'].sum()
    liq_total    = df_filtrado_global['Total_Liq'].sum() if 'Total_Liq' in df_filtrado_global.columns else 0.0
    saldo_total  = df_filtrado_global['Saldo'].sum()
    perc_exec    = (liq_total / orcado_total * 100) if orcado_total > 0 else 0.0

    c1, c2, c3, c4 = st.columns(4)
    with c1: st.metric("Previsão (Orçado)",    formar_real(orcado_total))
    with c2: st.metric("Saldo Disponível",      formar_real(saldo_total))
    with c3: st.metric("Executado (Liquidado)", formar_real(liq_total))
    with c4: st.metric("% de Execução",         f"{perc_exec:.2f}%".replace('.',','))

    # ── EVOLUÇÃO MENSAL ───────────────────────────────────────────────────────
    st.subheader("📈 Evolução Mensal da Execução (Liquidado)")

    meses_liq_map = {
        'Janeiro': 'Janeiro_Liq', 'Fevereiro': 'Fevereiro_Liq', 'Março': 'Março_Liq',
        'Abril': 'Abril_Liq', 'Maio': 'Maio_Liq', 'Junho': 'Junho_Liq',
        'Julho': 'Julho_Liq', 'Agosto': 'Agosto_Liq', 'Setembro': 'Setembro_Liq',
        'Outubro': 'Outubro_Liq', 'Novembro': 'Novembro_Liq', 'Dezembro': 'Dezembro_Liq',
    }
    mensal_dados = []
    for mes, col in meses_liq_map.items():
        val = df_filtrado_global[col].sum() if col in df_filtrado_global.columns else 0.0
        mensal_dados.append({"Mês": mes, "Valor": val})
    df_mensal = pd.DataFrame(mensal_dados)

    fig_evolucao = px.line(df_mensal, x='Mês', y='Valor', markers=True,
                           color_discrete_sequence=["#00CC96"])
    fig_evolucao.update_layout(
        yaxis_tickprefix='R$ ', yaxis_tickformat=',.2f', separators=',.',
        xaxis_title=None, yaxis_title="Liquidado (R$)", height=380,
    )
    fig_evolucao.update_traces(
        hovertemplate="<b>%{x}</b><br>Liquidado: R$ %{y:,.2f}<extra></extra>"
    )
    st.plotly_chart(fig_evolucao, use_container_width=True, config=CONFIG_PT)
    st.markdown("---")

    # ── DETALHAMENTO POR ELEMENTO ─────────────────────────────────────────────
    st.markdown('<div id="foco_grafico"></div>', unsafe_allow_html=True)
    st.subheader("📦 Detalhamento por Elemento")

    st.markdown("""
        <style>
        @keyframes subirBarra {
            from { clip-path: inset(100% 0 0 0); }
            to   { clip-path: inset(0% 0 0 0); }
        }
        .js-plotly-plot .point path {
            animation: subirBarra 0.8s cubic-bezier(0.25, 1, 0.5, 1) forwards;
            clip-path: inset(100% 0 0 0);
        }
        </style>
    """, unsafe_allow_html=True)

    elementos_disponiveis = sorted([
        str(x) for x in df_filtrado_global['Elemento'].dropna().unique()
    ])

    if elementos_disponiveis:
        st.write("Selecione um elemento para visualizar o detalhamento:")
        cols_botoes = st.columns(4)
        for i, elemento in enumerate(elementos_disponiveis):
            with cols_botoes[i % 4]:
                if st.button(elemento, use_container_width=True, key=f"btn_detalhamento_fichas_{i}"):
                    st.session_state['elemento_ativo'] = elemento
                    st.rerun()

        if 'elemento_ativo' in st.session_state:
            ele = st.session_state['elemento_ativo']
            scroll_id = random()
            _html_iframe(
                f"""
                <script id="scroll_{scroll_id}">
                    var scroll = () => {{
                        const el = window.parent.document.querySelector('.st-key-detalhamento-fichas');
                        if (el) el.scrollIntoView({{ behavior: "smooth", block: "center" }});
                    }};
                    setTimeout(scroll, 150);
                </script>
                """,
                height=0,
            )

            df_detalhe = (
                df_filtrado_global[df_filtrado_global['Elemento'] == ele]
                .sort_values('Orçado', ascending=False)
                .copy()
            )

            st.subheader(f"📊 Detalhamento de Fichas: {ele}")

            lista_elementos = [remover_acentos(e) for e in df_raw['Elemento'].unique() if pd.notna(e)]
            busca_limpa = remover_acentos(st.session_state.busca)
            label_hover = (
                "Categoria" if st.session_state.busca and busca_limpa in lista_elementos
                else ("Elemento" if st.session_state.busca else "Categoria")
            )

            fig_detalhe = px.bar(
                df_detalhe, x='Ficha', y='Orçado',
                color_discrete_sequence=["#00CC96"],
                custom_data=[label_hover, 'Fonte']
            )
            fig_detalhe.update_traces(
                hovertemplate=(
                    f"<b>{label_hover}:</b> %{{customdata[0]}}<br>"
                    "<b>Fonte:</b> %{customdata[1]}<br>"
                    "<b>Valor:</b> R$ %{y:,.2f}<extra></extra>"
                ),
                text=df_detalhe['Orçado'].apply(formar_real),
                textposition='outside',
                cliponaxis=False,
                width=0.8 if len(df_detalhe) < 12 else 0.5
            )
            fig_detalhe.update_layout(
                xaxis_type='category', height=550, separators=',.',
                yaxis=dict(range=[0, df_detalhe['Orçado'].max() * 1.30]),
                margin=dict(t=80, b=50, l=50, r=50)
            )
            st.plotly_chart(
                fig_detalhe, use_container_width=True, theme=None,
                config=CONFIG_PT, key="detalhamento-fichas"
            )

            if st.button("⬅️ Voltar para Visão Geral"):
                del st.session_state['elemento_ativo']
                st.rerun()

    st.markdown("---")

    # ── CUSTEIO x CAPITAL ─────────────────────────────────────────────────────
    st.subheader("📊 Custeio × Capital")

    df_natureza = (
        df_filtrado_global.groupby('Natureza')['Total_Liq']
        .sum().reset_index()
    )
    for nat in ['Capital (Invest.)','Custeio (Manut.)']:
        if nat not in df_natureza['Natureza'].values:
            df_natureza = pd.concat(
                [df_natureza, pd.DataFrame({'Natureza':[nat],'Total_Liq':[0.0]})],
                ignore_index=True
            )

    fig_natureza = px.pie(
        df_natureza, values='Total_Liq', names='Natureza', hole=.4,
        color='Natureza',
        color_discrete_map={'Custeio (Manut.)':'#00CC96','Capital (Invest.)':'#EF553B'}
    )
    fig_natureza.update_layout(
        margin=dict(t=50, b=50, l=20, r=20), height=450,
        showlegend=True, separators=',.',
        legend=dict(orientation="v", yanchor="middle", y=0.5,
                    xanchor="left", x=1.05, font=dict(size=16))
    )
    fig_natureza.update_traces(
        textinfo='percent', textposition='inside',
        hovertemplate="<b>Natureza:</b> %{label}<br><b>Valor Total:</b> R$ %{value:,.2f}<extra></extra>"
    )
    _, col_central_1, _ = st.columns([1,2,1])
    with col_central_1:
        st.plotly_chart(fig_natureza, use_container_width=True, config=CONFIG_PT)

    st.markdown("---")

    # ── % DE EXECUÇÃO POR CATEGORIA ───────────────────────────────────────────
    st.subheader("🎯 % de Execução por Categoria")

    df_exec_cat = (
        df_filtrado_global.groupby('Categoria')
        .agg(Orçado=('Orçado','sum'), Liquidado=('Total_Liq','sum'))
        .reset_index()
    )
    df_exec_cat['Perc'] = (
        df_exec_cat['Liquidado'] / df_exec_cat['Orçado'] * 100
    ).fillna(0)
    df_exec_cat = df_exec_cat.sort_values('Perc', ascending=True)

    fig_exec = px.bar(
        df_exec_cat, x='Perc', y='Categoria', orientation='h',
        text='Perc', color='Perc', color_continuous_scale='Greens'
    )
    fig_exec.update_traces(
        texttemplate='%{text:.1f}%', textposition='outside',
        hovertemplate="<b>Categoria:</b> %{y}<br><b>Execução:</b> %{x:.2f}%<extra></extra>"
    )
    fig_exec.update_layout(
        xaxis_title="Liquidado (%)", yaxis_title="",
        coloraxis_showscale=False, height=400,
        separators=',.',
        margin=dict(l=200),
        xaxis=dict(range=[0, 120])
    )
    st.plotly_chart(fig_exec, use_container_width=True, config=CONFIG_PT)

    st.markdown("---")

    # ── ORÇADO × EXECUTADO POR CATEGORIA ──────────────────────────────────────
    st.subheader("💰 Orçado × Executado por Categoria")

    df_comp_cat = (
        df_filtrado_global.groupby('Categoria')
        .agg(Orçado=('Orçado','sum'), Liquidado=('Total_Liq','sum'))
        .reset_index()
    )
    ordem_categorias = df_comp_cat.sort_values('Orçado', ascending=False)['Categoria'].tolist()
    df_melted = df_comp_cat.melt(
        id_vars='Categoria', value_vars=['Orçado','Liquidado'],
        var_name='Tipo', value_name='Valor'
    )

    fig_comp = px.bar(
        df_melted, x='Categoria', y='Valor', color='Tipo',
        barmode='group',
        color_discrete_map={'Orçado':'#2196F3','Liquidado':'#00CC96'},
        category_orders={'Categoria': ordem_categorias},
        text='Valor'
    )
    fig_comp.update_traces(
        texttemplate='R$ %{y:,.2f}', textposition='outside',
        hovertemplate="<b>Categoria:</b> %{x}<br><b>%{data.name}:</b> R$ %{y:,.2f}<extra></extra>"
    )
    fig_comp.update_layout(
        xaxis_title="", yaxis_title="Valor (R$)", height=500,
        legend_title="Legenda", separators=',.',
        yaxis=dict(range=[0, df_comp_cat['Orçado'].max() * 1.25])
    )
    st.plotly_chart(fig_comp, use_container_width=True, config=CONFIG_PT)

    st.markdown("---")

    # ── TOTAL INVESTIDO EM SAÚDE — PIZZA POR CATEGORIA ───────────────────────
    st.subheader("🏥 Total Investido em Saúde — Valor Liquidado (Janeiro a Março)")

    NOME_CATEGORIA = {
        'Secretaria':      'Administração',
        'Atenção Primária':'Atenção Primária',
        'MAC':             'Ambulatorial e Especialidades (MAC)',
        'Farmácia':        'Farmácia',
        'Vigilância':      'Vigilância',
    }
    CORES_CATEGORIA = {
        'Administração':                       '#f39c12',
        'Atenção Primária':                    '#4A90D9',
        'Ambulatorial e Especialidades (MAC)': '#1a3a6b',
        'Farmácia':                            '#27ae60',
        'Vigilância':                          '#e74c3c',
    }

    df_pizza_cat = (
        df_raw
        .groupby('Categoria')['Total_Liq']
        .sum()
        .reset_index()
    )
    df_pizza_cat['Categoria_Label'] = df_pizza_cat['Categoria'].map(NOME_CATEGORIA).fillna(df_pizza_cat['Categoria'])
    df_pizza_cat = df_pizza_cat[df_pizza_cat['Total_Liq'] > 0]
    total_liq_geral = df_pizza_cat['Total_Liq'].sum()

    fig_pizza_cat = px.pie(
        df_pizza_cat,
        values='Total_Liq',
        names='Categoria_Label',
        hole=0.0,
        color='Categoria_Label',
        color_discrete_map=CORES_CATEGORIA,
    )
    fig_pizza_cat.update_traces(
        textinfo='label+percent',
        textposition='outside',
        pull=[0.03] * len(df_pizza_cat),
        hovertemplate=(
            "<span style='color:white;'>"
            "<b>%{label}</b><br>"
            "Liquidado: <b>R$ %{value:,.2f}</b><br>"
            "Participação: <b>%{percent}</b>"
            "</span><extra></extra>"
        ),
        hoverlabel=dict(
            bgcolor="rgba(0,0,0,0.85)",
            font_size=13,
            font_family="Arial",
            font_color="white"
        ),
    )
    fig_pizza_cat.update_layout(
        title=dict(
            text=f"Total Liquidado: <b>R$ {total_liq_geral:,.2f}".replace(',','X').replace('.',',').replace('X','.') + "</b>",
            x=0.5, xanchor='center',
            font=dict(size=14)
        ),
        showlegend=True,
        legend=dict(
            orientation="v",
            yanchor="middle", y=0.5,
            xanchor="left",   x=1.02,
            font=dict(size=13),
            itemclick="toggle",
            itemdoubleclick="toggleothers",
        ),
        height=480,
        separators=',.',
        margin=dict(t=60, b=40, l=20, r=180),
        transition={'duration': 800, 'easing': 'cubic-in-out'},
    )

    _, col_pizza_cat, _ = st.columns([0.5, 3, 0.5])
    with col_pizza_cat:
        st.plotly_chart(fig_pizza_cat, use_container_width=True, config=CONFIG_PT)

    st.markdown("---")

    # ── RELATÓRIO DETALHADO ────────────────────────────────────────────────────
    st.subheader("📋 Relatório Detalhado")

    df_relatorio = df_filtrado_global.copy()
    df_relatorio['Orçado_F'] = df_relatorio['Orçado'].apply(formar_real)
    df_relatorio['Saldo_F']  = df_relatorio['Saldo'].apply(formar_real)
    df_relatorio['Liq_F']    = df_relatorio['Total_Liq'].apply(formar_real)

    st.data_editor(
        df_relatorio[['Categoria','Ficha','Elemento','Fonte','Orçado_F','Liq_F','Saldo_F']],
        use_container_width=True, hide_index=True, disabled=True,
        column_config={
            "Orçado_F":  "Orçado",
            "Liq_F":     "Liquidado",
            "Saldo_F":   "Saldo",
            "Elemento":  st.column_config.TextColumn("Elemento", width="large"),
            "Ficha":     st.column_config.TextColumn("Ficha"),
            "Fonte":     st.column_config.TextColumn("Fonte"),
            "Categoria": st.column_config.TextColumn("Categoria"),
        },
    )

else:
    st.error("Arquivos de dados não encontrados! Verifique a pasta 'zSaúde'.")