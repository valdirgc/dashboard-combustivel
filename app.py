import streamlit as st
import pdfplumber
import pandas as pd
import re
import os
import plotly.express as px
from streamlit_gsheets import GSheetsConnection
import extra_streamlit_components as stx
import datetime
import time
import json

# ==========================================
# 1. CONFIGURAÇÕES E MEMÓRIA
# ==========================================
st.set_page_config(page_title="Sistema Frota - Jaborandi", layout="wide", initial_sidebar_state="expanded")

# Gerenciador de Cookies (Chave única para evitar conflitos)
cookie_manager = stx.CookieManager(key="frota_jaborandi_final_v5")

# Trava de Sincronia: Aguarda o navegador entregar os dados
if cookie_manager.get_all() is None:
    st.stop()

if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
if "usuario_logado" not in st.session_state:
    st.session_state.usuario_logado = ""
if "nivel_acesso" not in st.session_state:
    st.session_state.nivel_acesso = ""
if "ignorar_cookie" not in st.session_state:
    st.session_state.ignorar_cookie = False

# --- RECUPERAÇÃO AUTOMÁTICA DE LOGIN ---
if not st.session_state.autenticado and not st.session_state.ignorar_cookie:
    sessao_cookie = cookie_manager.get(cookie="sessao_frota_jaborandi")
    if sessao_cookie:
        try:
            dados_rec = json.loads(sessao_cookie)
            st.session_state.autenticado = True
            st.session_state.usuario_logado = dados_rec["user"]
            st.session_state.nivel_acesso = dados_rec["nivel"]
        except:
            pass

if st.session_state.ignorar_cookie:
    st.session_state.ignorar_cookie = False

# ==========================================
# 2. ESTILO VISUAL (TEMA JABORANDI)
# ==========================================
st.markdown("""
<style>
    .block-container { padding-top: 1rem; }
    h1, h2, h3 { color: #0C3C7A; font-family: 'Segoe UI', sans-serif; font-weight: 700; }
    .stButton>button {
        background-color: #0C3C7A; color: white; border-radius: 8px; font-weight: 600;
        width: 100%; border: none; padding: 0.6rem; transition: 0.3s;
    }
    .stButton>button:hover { background-color: #082954; transform: translateY(-1px); }
    [data-testid="stMetricValue"] { color: #0C3C7A; font-weight: 800; }
    .stTabs [aria-selected="true"] { background-color: #E8F0FE; border-bottom: 4px solid #0C3C7A !important; color: #0C3C7A !important; font-weight: 800; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 3. TRADUTORES E FORMATADORES
# ==========================================
MESES_PT = {
    "01": "Janeiro", "02": "Fevereiro", "03": "Março", "04": "Abril",
    "05": "Maio", "06": "Junho", "07": "Julho", "08": "Agosto",
    "09": "Setembro", "10": "Outubro", "11": "Novembro", "12": "Dezembro"
}

def formata_moeda(v): return f"R$ {v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
def formata_litro(v): return f"{v:,.2f} L".replace(',', 'X').replace('.', ',').replace('X', '.')

def converter_para_numero(valor):
    if pd.isna(valor): return 0.0
    if isinstance(valor, (int, float)): return float(valor)
    v_str = str(valor).strip()
    v_str = re.sub(r'[^\d\.,\-]', '', v_str)
    if v_str == '': return 0.0
    if '.' in v_str and ',' in v_str: v_str = v_str.replace('.', '')
    return float(v_str.replace(',', '.'))

@st.cache_data(show_spinner="Extraindo dados...")
def extrair_dados_pdfs(arquivos):
    dados_gerais = []
    meses_id = set()
    for arquivo in arquivos:
        texto = ""
        with pdfplumber.open(arquivo) as pdf:
            for p in pdf.pages:
                txt_p = p.extract_text(layout=True)
                if txt_p: texto += txt_p + "\n"
        
        mes_sug = "00/0000"
        match_p = re.search(r"Período:\s*De\s*(\d{2}/\d{2}/\d{4})", texto)
        if match_p:
            mes_sug = match_p.group(1)[3:]
            meses_id.add(mes_sug)
            
        linhas = texto.split('\n')
        placa, comb, setor = None, "Não Identificado", "Não Identificado"
        
        for linha in linhas:
            match_v = re.search(r"VE[IÍ]CULO\s*:\s*(.*?)(?:\s+ESP[ÉE]CIE|$)", linha, re.IGNORECASE)
            if match_v:
                placa = re.sub(r'\s+', ' ', match_v.group(1).strip())
                match_c = re.search(r"ESP[ÉE]CIE:\s*([A-Z]+)", linha, re.IGNORECASE)
                comb = match_c.group(1).strip() if match_c else "Não Identificado"
            elif placa and "UNIDADE / SETOR:" in linha.upper():
                setor = linha.split("SETOR:")[1].strip()
            elif "TOTAL VE" in linha.upper() and placa:
                nums = re.findall(r"\d+(?:\.\d+)*(?:,\d+)?", linha)
                if len(nums) >= 2:
                    m_n, a_n = mes_sug.split("/")
                    dados_gerais.append({
                        "Veículo (Placa e Modelo)": placa, "Setor": setor, "Combustível": comb,
                        "Quantidade (L)": float(nums[-2].replace('.', '').replace(',', '.')),
                        "Valor Total (R$)": float(nums[-1].replace('.', '').replace(',', '.')),
                        "Mês/Ano Numérico": mes_sug, "Mês": str(m_n).zfill(2), "Ano": int(a_n)
                    })
                placa = None
    return dados_gerais, list(meses_id)

# ==========================================
# 4. TELA DE LOGIN (BRASÃO AJUSTADO)
# ==========================================
if not st.session_state.autenticado:
    # Centraliza e reduz o tamanho do brasão
    col_l1, col_l2, col_l3 = st.columns([2, 1, 2])
    with col_l2:
        try: st.image("logo.png", width=150)
        except: pass
    
    st.markdown("<h1 style='text-align: center;'>Gestão de Combustível</h1>", unsafe_allow_html=True)
    st.write("---")
    
    col_e1, col_form, col_e3 = st.columns([1, 1.5, 1])
    with col_form:
        st.markdown("<h3 style='text-align: center;'>🔒 Acesso Restrito</h3>", unsafe_allow_html=True)
        u_in = st.text_input("Usuário").strip()
        p_in = st.text_input("Senha", type="password")
        lembrar = st.checkbox("Manter-me conectado")
        
        if st.button("Entrar no Sistema"):
            perfil = ""
            if "admin" in st.secrets and u_in in st.secrets["admin"] and st.secrets["admin"][u_in] == p_in: perfil = "admin"
            elif "viewer" in st.secrets and u_in in st.secrets["viewer"] and st.secrets["viewer"][u_in] == p_in: perfil = "viewer"
            
            if perfil:
                st.session_state.autenticado = True
                st.session_state.usuario_logado = u_in
                st.session_state.nivel_acesso = perfil
                if lembrar:
                    pacote = json.dumps({"user": u_in, "nivel": perfil})
                    val = datetime.datetime.now() + datetime.timedelta(days=30)
                    cookie_manager.set("sessao_frota_jaborandi", pacote, expires_at=val)
                    time.sleep(0.5)
                st.rerun()
            else: st.error("Acesso Negado.")
    st.stop()

# ==========================================
# 5. CARREGAMENTO DE DADOS
# ==========================================
conn = st.connection("gsheets", type=GSheetsConnection)
try:
    df_db = conn.read(worksheet="Dados", ttl=0)
    if not df_db.empty and "Veículo (Placa e Modelo)" in df_db.columns:
        df_db["Quantidade (L)"] = df_db["Quantidade (L)"].apply(converter_para_numero)
        df_db["Valor Total (R$)"] = df_db["Valor Total (R$)"].apply(converter_para_numero)
        df_db["Mês"] = df_db["Mês"].astype(str).str.replace(".0", "", regex=False).str.zfill(2)
        df_db["Ano"] = df_db["Ano"].astype(str).str.replace(".0", "", regex=False)
        df_db = df_db.sort_values(by=["Ano", "Mês"])
        df_db["Nome do Mês"] = df_db["Mês"].map(MESES_PT).fillna("Desconhecido")
        df_db["Mês/Ano Exibição"] = df_db["Nome do Mês"] + " " + df_db["Ano"]
    else: df_db = pd.DataFrame(columns=["Ano", "Quantidade (L)", "Valor Total (R$)"])
except: df_db = pd.DataFrame(columns=["Ano"])

# ==========================================
# 6. BARRA LATERAL (FILTROS NO TOPO)
# ==========================================
with st.sidebar:
    st.subheader("📊 Filtros Gerenciais")
    if not df_db.empty and len(df_db) > 0:
        anos_list = sorted(df_db["Ano"].unique().tolist(), reverse=True)
        ano_sel = st.selectbox("Escolha o Ano:", anos_list)
        df_ano = df_db[df_db["Ano"] == ano_sel]
        
        st.info(f"**Resumo Global {ano_sel}:**\n\n💰 {formata_moeda(df_ano['Valor Total (R$)'].sum())}\n\n⛽ {formata_litro(df_ano['Quantidade (L)'].sum())}")
    else:
        ano_sel, df_ano = None, pd.DataFrame()

    st.markdown("---")
    st.write(f"✅ **{st.session_state.usuario_logado.capitalize()}**")
    if st.button("Sair do Sistema"):
        cookie_manager.delete("sessao_frota_jaborandi")
        st.session_state.autenticado = False
        st.session_state.ignorar_cookie = True
        time.sleep(0.5)
        st.rerun()

# ==========================================
# 7. IMPORTAÇÃO (ADMIN) E TÍTULO
# ==========================================
st.title("🏛️ Sistema de Gestão de Frota")

if st.session_state.nivel_acesso == "admin":
    with st.expander("📥 Importar Relatórios Mensais (PDF)"):
        pdf_up = st.file_uploader("Upload de PDFs", type=["pdf"], accept_multiple_files=True, key="up_main")
        if pdf_up:
            d_ext, m_ext = extrair_dados_pdfs(pdf_up)
            if d_ext:
                df_novos = pd.DataFrame(d_ext)
                st.success(f"Detectado: {', '.join(m_ext)}")
                if st.button("💾 Confirmar Integração"):
                    ja_tem = df_db["Mês/Ano Numérico"].unique().tolist() if not df_db.empty else []
                    df_final = df_novos[~df_novos["Mês/Ano Numérico"].isin(ja_tem)]
                    if not df_final.empty:
                        conn.update(worksheet="Dados", data=pd.concat([df_db, df_final], ignore_index=True))
                        st.success("Dados salvos!"); time.sleep(1); st.rerun()
                    else: st.warning("Dados já importados.")

st.write("---")

# ==========================================
# 8. DASHBOARD COM TABELAS RESTAURADAS
# ==========================================
if not df_ano.empty:
    aba1, aba2, aba3, aba4, aba5 = st.tabs(["📈 Geral", "🏢 Setor", "⛽ Combustível", "🚛 Veículo", "📅 Comparativo"])
    ordem = df_db["Mês/Ano Exibição"].unique().tolist()
    suf = f"_{ano_sel}"

    with aba1:
        res = df_ano.groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.bar(res, x="Mês/Ano Exibição", y="Valor Total (R$)", text=res["Valor Total (R$)"].apply(formata_moeda), title="Custo Mensal", color_discrete_sequence=["#0C3C7A"], category_orders={"Mês/Ano Exibição": ordem}), use_container_width=True, key=f"g1{suf}")
        c2.plotly_chart(px.bar(res, x="Mês/Ano Exibição", y="Quantidade (L)", text=res["Quantidade (L)"].apply(formata_litro), title="Volume Mensal", color_discrete_sequence=["#4CAF50"], category_orders={"Mês/Ano Exibição": ordem}), use_container_width=True, key=f"g2{suf}")
        
        st.write("**Tabela de Dados Mensais (Consolidado)**")
        df_tab1 = res.copy()
        df_tab1["Valor Total (R$)"] = df_tab1["Valor Total (R$)"].apply(formata_moeda)
        df_tab1["Quantidade (L)"] = df_tab1["Quantidade (L)"].apply(formata_litro)
        st.dataframe(df_tab1, use_container_width=True, hide_index=True)

    with aba2:
        sel_s = st.selectbox("Selecione o Setor:", df_ano["Setor"].unique())
        df_s = df_ano[df_ano["Setor"] == sel_s].groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.bar(df_s, x="Mês/Ano Exibição", y="Valor Total (R$)", title=f"Gasto: {sel_s}", color_discrete_sequence=["#0C3C7A"], category_orders={"Mês/Ano Exibição": ordem}), use_container_width=True, key=f"g3{suf}")
        c2.plotly_chart(px.bar(df_s, x="Mês/Ano Exibição", y="Quantidade (L)", title=f"Volume: {sel_s}", color_discrete_sequence=["#4CAF50"], category_orders={"Mês/Ano Exibição": ordem}), use_container_width=True, key=f"g4{suf}")
        
        st.write(f"**Detalhamento - {sel_s}**")
        df_tab2 = df_s.copy()
        df_tab2["Valor Total (R$)"] = df_tab2["Valor Total (R$)"].apply(formata_moeda)
        df_tab2["Quantidade (L)"] = df_tab2["Quantidade (L)"].apply(formata_litro)
        st.dataframe(df_tab2, use_container_width=True, hide_index=True)

    with aba3:
        sel_c = st.selectbox("Selecione o Combustível:", df_ano["Combustível"].unique())
        df_c = df_ano[df_ano["Combustível"] == sel_c].groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.bar(df_c, x="Mês/Ano Exibição", y="Valor Total (R$)", title=f"Gasto com {sel_c}", color_discrete_sequence=["#0C3C7A"]), use_container_width=True, key=f"g5{suf}")
        c2.plotly_chart(px.bar(df_c, x="Mês/Ano Exibição", y="Quantidade (L)", title=f"Consumo de {sel_c}", color_discrete_sequence=["#4CAF50"]), use_container_width=True, key=f"g6{suf}")

    with aba4:
        sel_v = st.selectbox("Selecione o Veículo:", sorted(df_ano["Veículo (Placa e Modelo)"].unique()))
        df_v = df_ano[df_ano["Veículo (Placa e Modelo)"] == sel_v].groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.line(df_v, x="Mês/Ano Exibição", y="Valor Total (R$)", markers=True, title=f"Curva de Gasto: {sel_v}"), use_container_width=True, key=f"g7{suf}")
        c2.plotly_chart(px.line(df_v, x="Mês/Ano Exibição", y="Quantidade (L)", markers=True, title=f"Curva de Volume: {sel_v}"), use_container_width=True, key=f"g8{suf}")
        
        st.write(f"**Histórico do Veículo: {sel_v}**")
        df_tab4 = df_v.copy()
        df_tab4["Valor Total (R$)"] = df_tab4["Valor Total (R$)"].apply(formata_moeda)
        df_tab4["Quantidade (L)"] = df_tab4["Quantidade (L)"].apply(formata_litro)
        st.dataframe(df_tab4, use_container_width=True, hide_index=True)

    with aba5:
        sel_m = st.selectbox("Escolha o Mês para comparar:", df_db["Nome do Mês"].unique())
        df_comp = df_db[df_db["Nome do Mês"] == sel_m].groupby("Ano")[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        df_comp["Ano"] = df_comp["Ano"].astype(str)
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.bar(df_comp, x="Ano", y="Valor Total (R$)", title=f"Comparativo Gasto ({sel_m})", color="Ano"), use_container_width=True, key=f"g9{suf}")
        c2.plotly_chart(px.bar(df_comp, x="Ano", y="Quantidade (L)", title=f"Comparativo Litros ({sel_m})", color="Ano"), use_container_width=True, key=f"g10{suf}")

else: st.info("Selecione um ano com dados para visualizar os gráficos.")
