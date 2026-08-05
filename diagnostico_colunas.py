# -*- coding: utf-8 -*-
# ─────────────────────────────────────────────────────────────────────────────
# DIAGNÓSTICO DE COLETA — iG2P
# Mostra os NOMES REAIS das colunas lidas do Google Sheets (com repr(), que
# revela espaços/caracteres invisíveis) e a soma por mês do que o dashboard
# realmente enxerga. Serve para achar por que "vários valores aparecem zerados".
#
# Como rodar (na mesma pasta do app, com o mesmo .streamlit/secrets.toml):
#     streamlit run diagnostico_colunas.py
# ─────────────────────────────────────────────────────────────────────────────
import io, csv
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="Diagnóstico de Coleta iG2P", layout="wide")
st.title("🔎 Diagnóstico de Coleta — Google Sheets")

MESES = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho','Agosto',
         'Setembro','Outubro','Novembro','Dezembro']
TIPOS = ('Empenhado', 'Liquidado', 'Pago')


@st.cache_resource
def _gc():
    esc = ["https://www.googleapis.com/auth/spreadsheets.readonly",
           "https://www.googleapis.com/auth/drive.readonly"]
    cred = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=esc)
    return gspread.authorize(cred)


def _ler(sid, aba, **kw):
    ws = _gc().open_by_key(sid).worksheet(aba)
    buf = io.StringIO(); csv.writer(buf).writerows(ws.get_all_values()); buf.seek(0)
    return pd.read_csv(buf, **kw)


def _canon_mes(nome):
    base = str(nome).strip().lower().replace('ç', 'c').replace('ã', 'a')
    tok = ''
    for ch in base:
        if ch.isalpha(): tok += ch
        else: break
    for m in MESES:
        if tok == m.lower().replace('ç', 'c').replace('ã', 'a'):
            return m
    return None


def _limpar(v):
    if pd.isna(v) or str(v).strip() in ["", "−", "-", "R$ 0,00", "0", "#REF!"]:
        return 0.0
    s = str(v).replace('R$', '').replace(' ', '').replace('.', '').replace(',', '.')
    try:
        if '(' in s and ')' in s: s = '-' + s.replace('(', '').replace(')', '')
        return float(s)
    except Exception:
        return 0.0


# ── seleção de setor/município a partir do secrets ───────────────────────────
setor = st.selectbox("Setor", ["educacao", "saude"])
mapa = dict(st.secrets.get(setor, {}))
if not mapa:
    st.error(f"Nenhum município configurado em st.secrets['{setor}'].")
    st.stop()
mun = st.selectbox("Município", sorted(mapa.keys()))
sid = mapa[mun]
st.caption(f"Sheet ID: `{sid}`")

abas_edu = {"Fichas": "fichas", "Receitas": "flat", "Despesas por fonte": "flat"}
abas_sau = {"Fichas": "fichas", "Receitas de Impostos": "flat",
            "Despesas por fonte": "flat", "Receitas Vinculadas": "flat"}
abas = abas_edu if setor == "educacao" else abas_sau

for aba, tipo in abas.items():
    st.markdown("---")
    st.header(f"📄 Aba: `{aba}`")
    try:
        if tipo == "fichas":
            raw = _ler(sid, aba, sep=None, engine='python',
                       header=([0, 1] if setor == "educacao" else 1))
        else:
            raw = _ler(sid, aba, sep=None, engine='python', header=0)
    except Exception as e:
        st.error(f"Falha ao ler a aba: {e}")
        continue

    if tipo == "fichas" and setor == "educacao":
        st.write("**Cabeçalho duplo (nível 0 / nível 1) — repr revela caracteres ocultos:**")
        st.code("\n".join(f"nivel0={c[0]!r:35}  nivel1={c[1]!r}" for c in raw.columns[:40]))
        cols = []
        for c in raw.columns:
            a, b = str(c[0]).strip(), str(c[1]).strip()
            if 'Unnamed' in str(c[0]) or a == '': cols.append(b); continue
            if 'Unnamed' in str(c[1]) or b == '': cols.append(a); continue
            if a in TIPOS: tipo_, mes = a, b
            elif b in TIPOS: tipo_, mes = b, a
            else: cols.append(f"{b}_{a}"); continue
            cols.append(f"{(_canon_mes(mes) or mes)}_{tipo_}")
        raw.columns = cols
        st.write("**Colunas finais montadas pelo dashboard:**")
        st.code(", ".join(map(str, cols)))
        st.write("**Soma por mês (coluna `<Mês>_Liquidado`):**")
        linhas = []
        for m in MESES:
            col = f"{m}_Liquidado"
            tot = raw[col].apply(_limpar).sum() if col in raw.columns else None
            linhas.append({"Mês": m, "Coluna esperada": col,
                           "Existe?": "✅" if col in raw.columns else "❌ FALTA",
                           "Soma Liquidado": tot})
        st.dataframe(pd.DataFrame(linhas), use_container_width=True, hide_index=True)
    else:
        raw.columns = [str(c).strip() for c in raw.columns]
        st.write("**Colunas (repr revela espaços/acentos/invisíveis):**")
        st.code("\n".join(f"{i:2}: {c!r}" for i, c in enumerate(raw.columns)))
        if 'Tipo' in raw.columns:
            st.write("**Valores distintos em `Tipo`:**",
                     sorted(map(str, raw['Tipo'].dropna().unique())))
        st.write("**Soma por mês (linhas Tipo == 'Liquidado', se houver):**")
        base = raw[raw['Tipo'].astype(str).str.strip() == 'Liquidado'] if 'Tipo' in raw.columns else raw
        linhas = []
        for m in MESES:
            existe = m in raw.columns
            tot = base[m].apply(_limpar).sum() if existe else None
            linhas.append({"Mês": m, "Existe coluna?": "✅" if existe else "❌ FALTA",
                           "Soma": tot})
        st.dataframe(pd.DataFrame(linhas), use_container_width=True, hide_index=True)

st.markdown("---")
st.info("Se um mês aparece com **❌ FALTA** ou soma 0 mesmo tendo dados na planilha, "
        "o `repr` acima mostra o nome real da coluna — compare com o mês esperado "
        "para achar o caractere/grafia divergente.")
