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

# Gerenciador de Cookies
cookie_manager = stx.CookieManager(key="frota_jaborandi_vfinal_full")

# --- TRAVA DE PERSISTÊNCIA (ANTI-F5) ---
# Se o navegador ainda não carregou os cookies, o Python aguarda um instante.
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

# Tenta recuperar a sessão via cookie
if not st.session_state.autenticado and not st.session_state.ignorar_cookie:
    sessao_json = cookie_manager.get(cookie="sessao_frota_jaborandi")
    if sessao_json:
        try:
            dados_sessao = json.loads(sessao_json)
            st.session_state.autenticado = True
            st.session_state.usuario_logado = dados_sessao["user"]
            st.session_state.nivel_acesso = dados_sessao["nivel"]
        except:
            pass

if st.session_state.ignorar_cookie:
    st.session_state.ignorar_cookie = False

# ==========================================
# 2. CUSTOMIZAÇÃO VISUAL (TEMA JABORANDI)
# ==========================================
st.markdown("""
<style>
    .block-container { padding-top: 2rem; }
    h1, h2, h3 { color: #0C3C7A; font-family: 'Segoe UI', sans-serif; font-weight: 700; }
    .stButton>button {
        background-color: #0C3C7A; color: white; border-radius: 8px; 
        border: none; padding: 0.5rem 1rem; transition: all 0.3s ease; font-weight: 600;
        width: 100%;
    }
    .stButton>button:hover { background-color: #082954; transform: translateY(-2px); }
    div[data-testid="stMetricValue"] { color: #0C3C7A; font-weight: 800; }
    .stTabs [aria-selected="true"] { background-color: #E8F0FE; border-bottom: 4px solid #0C3C7A !important; color: #0C3C7A !important; font-weight: 800; }
    [data-testid="stSidebar"] { background-color: #F8F9FA; border-right: 1px solid #DEE2E6; }
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

def formatar_tabela_exibicao(df_original):
    df_f = df_original.copy()
    if "Valor Total (R$)" in df_f.columns:
        df_f["Valor Total (R$)"] = df_f["Valor Total (R$)"].apply(formata_moeda)
    if "Quantidade (L)" in df_f.columns:
        df_f["Quantidade (L)"] = df_f["Quantidade (L)"].apply(formata_litro)
    return df_f

def converter_para_numero(valor):
    if pd.isna(valor): return 0.0
    if isinstance(valor, (int, float)): return float(valor)
    v_str = str(valor).strip()
    v_str = re.sub(r'[^\d\.,\-]', '', v_str)
    if v_str == '': return 0.0
    if '.' in v_str and ',' in v_str: v_str = v_str.replace('.', '')
    try: return float(v_str.replace(',', '.'))
    except: return 0.0

@st.cache_data(show_spinner="Extraindo dados detalhados do PDF...")
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
            elif placa and re.search(r"UNIDADE\s*/\s*SETOR:\s*(.+)", linha, re.IGNORECASE):
                setor = re.search(r"UNIDADE\s*/\s*SETOR:\s*(.+)", linha, re.IGNORECASE).group(1).strip()
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
# 4. TELA DE LOGIN CENTRALIZADA
# ==========================================
if not st.session_state.autenticado:
    col_l1, col_l2, col_l3 = st.columns([2, 1, 2])
    with col_l2:
        try: st.image("logo.png", width=150)
        except: pass
    
    st.markdown("<h1 style='text-align: center;'>Gestão de Combustível</h1>", unsafe_allow_html=True)
    st.write("---")
    
    col_f1, col_f2, col_f3 = st.columns([1, 1.5, 1])
    with col_f2:
        st.markdown("<h3 style='text-align: center; color: #0C3C7A;'>🔒 Login de Acesso</h3>", unsafe_allow_html=True)
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
    else: df_db = pd.DataFrame(columns=["Ano", "Quantidade (L)", "Valor Total (R$)", "Veículo (Placa e Modelo)", "Setor", "Combustível"])
except: df_db = pd.DataFrame(columns=["Ano"])

# ==========================================
# 6. BARRA LATERAL (RESUMO NO TOPO)
# ==========================================
with st.sidebar:
    st.subheader("📊 Filtros e Resumo")
    if not df_db.empty and len(df_db) > 1:
        anos_list = sorted(df_db["Ano"].unique().tolist(), reverse=True)
        ano_sel = st.selectbox("Escolha o Ano:", anos_list)
        df_ano = df_db[df_db["Ano"] == ano_sel]
        
        st.info(f"**Totais de {ano_sel}:**\n\n💰 {formata_moeda(df_ano['Valor Total (R$)'].sum())}\n\n⛽ {formata_litro(df_ano['Quantidade (L)'].sum())}")
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
# 7. IMPORTAÇÃO (ADMIN)
# ==========================================
st.title("🏛️ Gestão de Frota")

if st.session_state.nivel_acesso == "admin":
    with st.expander("📥 Importar Novos Relatórios Mensais (PDF)"):
        pdf_up = st.file_uploader("Upload de PDFs", type=["pdf"], accept_multiple_files=True)
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
# 8. DASHBOARD (AS TABELAS VOLTARAM!)
# ==========================================
if not df_ano.empty:
    aba1, aba2, aba3, aba4, aba5 = st.tabs(["📈 Geral", "🏢 Setor", "⛽ Combustível", "🚛 Veículo", "📅 Comparativo"])
    ordem_c = df_db["Mês/Ano Exibição"].unique().tolist()
    suf = f"_{ano_sel}"

    with aba1:
        st.subheader(f"Desempenho Geral - {ano_sel}")
        res_g = df_ano.groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        res_g["TXT_V"] = res_g["Valor Total (R$)"].apply(formata_moeda)
        res_g["TXT_L"] = res_g["Quantidade (L)"].apply(formata_litro)
        
        c1, c2 = st.columns(2)
        with c1:
            fig1 = px.bar(res_g, x="Mês/Ano Exibição", y="Valor Total (R$)", text="TXT_V", title="Custo Mensal", color_discrete_sequence=["#0C3C7A"], category_orders={"Mês/Ano Exibição": ordem_c})
            fig1.update_traces(textposition='outside')
            st.plotly_chart(fig1, use_container_width=True, key=f"g1{suf}")
        with c2:
            fig2 = px.bar(res_g, x="Mês/Ano Exibição", y="Quantidade (L)", text="TXT_L", title="Volume Mensal", color_discrete_sequence=["#4CAF50"], category_orders={"Mês/Ano Exibição": ordem_c})
            fig2.update_traces(textposition='outside')
            st.plotly_chart(fig2, use_container_width=True, key=f"g2{suf}")
        
        st.write("**Resumo da Operação Mensal:**")
        st.dataframe(formatar_tabela_exibicao(res_g[["Mês/Ano Exibição", "Quantidade (L)", "Valor Total (R$)"]]), use_container_width=True, hide_index=True)

    with aba2:
        st.subheader("Análise por Secretaria/Setor")
        sel_s = st.selectbox("Selecione o Setor:", sorted(df_ano["Setor"].unique().tolist()))
        df_s = df_ano[df_ano["Setor"] == sel_s]
        res_s_mes = df_s.groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        
        c1, c2 = st.columns(2)
        with c1: st.plotly_chart(px.bar(res_s_mes, x="Mês/Ano Exibição", y="Valor Total (R$)", title="Gasto Mensal", color_discrete_sequence=["#0C3C7A"], category_orders={"Mês/Ano Exibição": ordem_c}), use_container_width=True, key=f"g3{suf}")
        with c2: st.plotly_chart(px.bar(res_s_mes, x="Mês/Ano Exibição", y="Quantidade (L)", title="Volume Mensal", color_discrete_sequence=["#4CAF50"], category_orders={"Mês/Ano Exibição": ordem_c}), use_container_width=True, key=f"g4{suf}")
        
        st.write(f"**🚗 Veículos e Placas do Setor: {sel_s}**")
        df_detalhe_s = df_s.groupby("Veículo (Placa e Modelo)")[["Quantidade (L)", "Valor Total (R$)"]].sum().reset_index()
        st.dataframe(formatar_tabela_exibicao(df_detalhe_s), use_container_width=True, hide_index=True)

    with aba3:
        st.subheader("Análise por Combustível")
        sel_c = st.selectbox("Selecione o Combustível:", df_ano["Combustível"].unique().tolist())
        df_c = df_ano[df_ano["Combustível"] == sel_c]
        res_c_mes = df_c.groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        
        c1, c2 = st.columns(2)
        with c1: st.plotly_chart(px.bar(res_c_mes, x="Mês/Ano Exibição", y="Valor Total (R$)", title="Custo", color_discrete_sequence=["#0C3C7A"]), use_container_width=True, key=f"g5{suf}")
        with c2: st.plotly_chart(px.bar(res_c_mes, x="Mês/Ano Exibição", y="Quantidade (L)", title="Volume", color_discrete_sequence=["#4CAF50"]), use_container_width=True, key=f"g6{suf}")
        
        st.write(f"**🚛 Veículos que utilizaram {sel_c}:**")
        df_detalhe_c = df_c.groupby(["Veículo (Placa e Modelo)", "Setor"])[["Quantidade (L)", "Valor Total (R$)"]].sum().reset_index()
        st.dataframe(formatar_tabela_exibicao(df_detalhe_c), use_container_width=True, hide_index=True)

    with aba4:
        st.subheader("Evolução Individual de Veículo")
        sel_v = st.selectbox("Escolha o Veículo:", sorted(df_ano["Veículo (Placa e Modelo)"].unique().tolist()))
        df_v = df_ano[df_ano["Veículo (Placa e Modelo)"] == sel_v]
        res_v = df_v.groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        
        c1, c2 = st.columns(2)
        with c1: st.plotly_chart(px.line(res_v, x="Mês/Ano Exibição", y="Valor Total (R$)", markers=True, title="Curva Financeira", color_discrete_sequence=["#0C3C7A"]), use_container_width=True, key=f"g7{suf}")
        with c2: st.plotly_chart(px.line(res_v, x="Mês/Ano Exibição", y="Quantidade (L)", markers=True, title="Curva de Consumo", color_discrete_sequence=["#4CAF50"]), use_container_width=True, key=f"g8{suf}")
        st.write(f"**Histórico de Abastecimentos: {sel_v}**")
        st.dataframe(formatar_tabela_exibicao(res_v), use_container_width=True, hide_index=True)

    with aba5:
        st.subheader("Comparativo Mensal entre Anos")
        sel_m = st.selectbox("Selecione o Mês:", df_db["Nome do Mês"].unique().tolist())
        df_cp = df_db[df_db["Nome do Mês"] == sel_m].groupby("Ano")[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        df_cp["Ano"] = df_cp["Ano"].astype(str)
        
        c1, c2 = st.columns(2)
        with c1: st.plotly_chart(px.bar(df_cp, x="Ano", y="Valor Total (R$)", title=f"Financeiro ({sel_m})", color="Ano"), use_container_width=True, key=f"g9{suf}")
        with c2: st.plotly_chart(px.bar(df_cp, x="Ano", y="Quantidade (L)", title=f"Volume ({sel_m})", color="Ano"), use_container_width=True, key=f"g10{suf}")
        st.dataframe(formatar_tabela_exibicao(df_cp), use_container_width=True, hide_index=True)

else: st.info("Selecione um ano para carregar os dados.")
