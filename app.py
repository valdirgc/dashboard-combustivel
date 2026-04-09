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
# 1. CONFIGURAÇÕES INICIAIS E MEMÓRIA
# ==========================================
st.set_page_config(page_title="Sistema Frota - Jaborandi", layout="wide", initial_sidebar_state="expanded")

# Inicialização do Cookie Manager
cookie_manager = stx.CookieManager(key="gerenciador_cookies_frota_vfinal")

# --- TRAVA DE PERSISTÊNCIA (ESSENCIAL PARA O F5) ---
# Se o navegador ainda não carregou os cookies, o Python "congela" e espera.
# Isso garante que o 'Manter Conectado' funcione 100% das vezes.
todos_cookies = cookie_manager.get_all()
if todos_cookies is None:
    st.stop()

if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
if "usuario_logado" not in st.session_state:
    st.session_state.usuario_logado = ""
if "nivel_acesso" not in st.session_state:
    st.session_state.nivel_acesso = ""
if "ignorar_cookie" not in st.session_state:
    st.session_state.ignorar_cookie = False

# --- LÓGICA DE RECUPERAÇÃO DE LOGIN (COOKIE) ---
if not st.session_state.autenticado and not st.session_state.ignorar_cookie:
    pacote_sessao = cookie_manager.get(cookie="sessao_frota_jaborandi")
    if pacote_sessao:
        try:
            dados = json.loads(pacote_sessao)
            st.session_state.autenticado = True
            st.session_state.usuario_logado = dados["user"]
            st.session_state.nivel_acesso = dados["nivel"]
        except:
            pass

# Reseta a flag de segurança após o primeiro ciclo
if st.session_state.ignorar_cookie:
    st.session_state.ignorar_cookie = False

# ==========================================
# 2. CUSTOMIZAÇÃO VISUAL (TEMA JABORANDI)
# ==========================================
st.markdown("""
<style>
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    h1, h2, h3 { color: #0C3C7A; font-family: 'Segoe UI', sans-serif; font-weight: 700; }
    .stButton>button {
        background-color: #0C3C7A; color: white; border-radius: 8px; 
        border: none; padding: 0.5rem 1rem; transition: all 0.3s ease; font-weight: 600;
        width: 100%;
    }
    .stButton>button:hover { background-color: #082954; transform: translateY(-2px); box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
    div[data-testid="stMetricValue"] { color: #0C3C7A; font-weight: 800; }
    .stTabs [data-baseweb="tab-list"] { gap: 10px; }
    .stTabs [aria-selected="true"] { background-color: #E8F0FE; border-bottom: 4px solid #0C3C7A !important; color: #0C3C7A !important; font-weight: 800; }
    [data-testid="stSidebar"] { background-color: #F8F9FA; border-right: 1px solid #DEE2E6; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 3. FUNÇÕES BASE E FORMATADORES
# ==========================================
MESES_PT = {
    "01": "Janeiro", "02": "Fevereiro", "03": "Março", "04": "Abril",
    "05": "Maio", "06": "Junho", "07": "Julho", "08": "Agosto",
    "09": "Setembro", "10": "Outubro", "11": "Novembro", "12": "Dezembro"
}

def formata_moeda(valor):
    return f"R$ {valor:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

def formata_litro(valor):
    return f"{valor:,.2f} L".replace(',', 'X').replace('.', ',').replace('X', '.')

def formatar_tabela_exibicao(df_entrada):
    df_formatado = df_entrada.copy()
    if "Valor Total (R$)" in df_formatado.columns:
        df_formatado["Valor Total (R$)"] = df_formatado["Valor Total (R$)"].apply(formata_moeda)
    if "Quantidade (L)" in df_formatado.columns:
        df_formatado["Quantidade (L)"] = df_formatado["Quantidade (L)"].apply(formata_litro)
    return df_formatado

def converter_para_numero(valor):
    if pd.isna(valor): return 0.0
    if isinstance(valor, (int, float)): return float(valor)
    v_str = str(valor).strip()
    v_str = re.sub(r'[^\d\.,\-]', '', v_str)
    if v_str == '': return 0.0
    if '.' in v_str and ',' in v_str: v_str = v_str.replace('.', '')
    try: return float(v_str.replace(',', '.'))
    except: return 0.0

@st.cache_data(show_spinner="Extraindo dados dos relatórios...")
def extrair_dados_pdfs(arquivos):
    dados_gerais = []
    meses_identificados = set()
    for arquivo in arquivos:
        texto_completo = ""
        with pdfplumber.open(arquivo) as pdf:
            for pagina in pdf.pages:
                texto_pagina = pagina.extract_text(layout=True)
                if texto_pagina: texto_completo += texto_pagina + "\n"
        
        mes_sugerido = "00/0000" 
        match_periodo = re.search(r"Período:\s*De\s*(\d{2}/\d{2}/\d{4})", texto_completo)
        if match_periodo:
            mes_sugerido = match_periodo.group(1)[3:] 
            meses_identificados.add(mes_sugerido)
            
        linhas = texto_completo.split('\n')
        placa_atual = None
        combustivel_atual = "Não Identificado"
        setor_atual = "Não Identificado"
        
        for linha in linhas:
            linha_limpa = linha.replace("|", "").strip()
            match_veiculo = re.search(r"VE[IÍ]CULO\s*:\s*(.*?)(?:\s+ESP[ÉE]CIE|$)", linha_limpa, re.IGNORECASE)
            if match_veiculo:
                placa_atual = re.sub(r'\s+', ' ', match_veiculo.group(1).strip())
                match_comb = re.search(r"ESP[ÉE]CIE:\s*([A-Z]+)", linha_limpa, re.IGNORECASE)
                combustivel_atual = match_comb.group(1).strip() if match_comb else "Não Identificado"
            elif placa_atual and re.search(r"UNIDADE\s*/\s*SETOR:\s*(.+)", linha_limpa, re.IGNORECASE):
                setor_atual = re.search(r"UNIDADE\s*/\s*SETOR:\s*(.+)", linha_limpa, re.IGNORECASE).group(1).strip()
            elif "TOTAL VE" in linha_limpa.upper() and placa_atual:
                numeros = re.findall(r"\d+(?:\.\d+)*(?:,\d+)?", linha_limpa)
                if len(numeros) >= 2:
                    try:
                        m_n, a_n = mes_sugerido.split("/")
                        dados_gerais.append({
                            "Veículo (Placa e Modelo)": placa_atual, "Setor": setor_atual, "Combustível": combustivel_atual,
                            "Quantidade (L)": float(numeros[-2].replace('.', '').replace(',', '.')),
                            "Valor Total (R$)": float(numeros[-1].replace('.', '').replace(',', '.')),
                            "Mês/Ano Numérico": mes_sugerido, "Mês": str(m_n).zfill(2), "Ano": int(a_n)
                        })
                    except: pass
                placa_atual = None 
    return dados_gerais, list(meses_identificados)

# ==========================================
# 4. TELA DE LOGIN CENTRALIZADA
# ==========================================
if not st.session_state.autenticado:
    col_logo1, col_logo2, col_logo3 = st.columns([2, 1, 2])
    with col_logo2:
        try: st.image("logo.png", width=150)
        except: pass
    st.markdown("<h1 style='text-align: center;'>Gestão de Combustível</h1>", unsafe_allow_html=True)
    st.write("---")
    
    col_e1, col_login, col_e3 = st.columns([1, 1.5, 1])
    with col_login:
        st.markdown("<h3 style='text-align: center;'>🔒 Login de Acesso</h3>", unsafe_allow_html=True)
        usuario = st.text_input("Usuário").strip()
        senha = st.text_input("Senha", type="password")
        lembrar = st.checkbox("Manter-me conectado neste computador")
        
        if st.button("Entrar no Sistema"):
            perfil = ""
            if "admin" in st.secrets and usuario in st.secrets["admin"] and st.secrets["admin"][usuario] == senha:
                perfil = "admin"
            elif "viewer" in st.secrets and usuario in st.secrets["viewer"] and st.secrets["viewer"][usuario] == senha:
                perfil = "viewer"
            
            if perfil:
                st.session_state.autenticado = True
                st.session_state.usuario_logado = usuario
                st.session_state.nivel_acesso = perfil
                if lembrar:
                    pacote = json.dumps({"user": usuario, "nivel": perfil})
                    validade = datetime.datetime.now() + datetime.timedelta(days=30)
                    cookie_manager.set("sessao_frota_jaborandi", pacote, expires_at=validade)
                    time.sleep(0.5)
                st.rerun()
            else:
                st.error("Credenciais inválidas.")
    st.stop()

# ==========================================
# 5. CARREGAMENTO DE DADOS (PÓS-LOGIN)
# ==========================================
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
    df_db = conn.read(worksheet="Dados", ttl=0)
    if not df_db.empty and "Veículo (Placa e Modelo)" in df_db.columns:
        df_db["Quantidade (L)"] = df_db["Quantidade (L)"].apply(converter_para_numero)
        df_db["Valor Total (R$)"] = df_db["Valor Total (R$)"].apply(converter_para_numero)
        df_db["Mês"] = df_db["Mês"].astype(str).str.replace(".0", "", regex=False).str.zfill(2)
        df_db["Ano"] = df_db["Ano"].astype(str).str.replace(".0", "", regex=False)
        df_db = df_db.sort_values(by=["Ano", "Mês"])
        df_db["Nome do Mês"] = df_db["Mês"].map(MESES_PT).fillna("Desconhecido")
        df_db["Mês/Ano Exibição"] = df_db["Nome do Mês"] + " " + df_db["Ano"]
    else:
        df_db = pd.DataFrame(columns=["Ano", "Quantidade (L)", "Valor Total (R$)", "Mês/Ano Numérico"])
except:
    df_db = pd.DataFrame(columns=["Ano"])

# ==========================================
# 6. BARRA LATERAL (FILTROS E RESUMO NO TOPO)
# ==========================================
with st.sidebar:
    st.subheader("📊 Filtros e Resumo")
    if not df_db.empty and len(df_db) > 1:
        lista_anos = sorted(df_db["Ano"].unique().tolist(), reverse=True)
        ano_selecionado = st.selectbox("Escolha o Ano:", lista_anos)
        df_ano = df_db[df_db["Ano"] == ano_selecionado]
        
        st.info(f"**Resumo Global {ano_selecionado}:**\n\n💰 {formata_moeda(df_ano['Valor Total (R$)'].sum())}\n\n⛽ {formata_litro(df_ano['Quantidade (L)'].sum())}")
    else:
        ano_selecionado, df_ano = None, pd.DataFrame()

    st.markdown("---")
    st.write(f"✅ Logado como: **{st.session_state.usuario_logado.capitalize()}**")
    if st.button("Sair do Sistema"):
        # Limpa Cookies de forma segura
        if type(todos_cookies) is dict and "sessao_frota_jaborandi" in todos_cookies:
            cookie_manager.delete("sessao_frota_jaborandi")
        st.session_state.autenticado = False
        st.session_state.usuario_logado = ""
        st.session_state.nivel_acesso = ""
        st.session_state.ignorar_cookie = True 
        time.sleep(0.5)
        st.rerun()

# ==========================================
# 7. ÁREA DE IMPORTAÇÃO (ADMIN)
# ==========================================
st.title("🏛️ Sistema de Gestão de Frota")

if st.session_state.nivel_acesso == "admin":
    with st.expander("📥 Importar Novos Relatórios (PDF)"):
        arquivos_pdf = st.file_uploader("Upload de PDFs", type=["pdf"], accept_multiple_files=True)
        if arquivos_pdf:
            dados_pdf, meses_pdf = extrair_dados_pdfs(arquivos_pdf)
            if dados_pdf:
                df_novos = pd.DataFrame(dados_pdf)
                st.success(f"Identificados meses: {', '.join(meses_pdf)}")
                if st.button("💾 Salvar na Nuvem (Google Sheets)"):
                    ja_salvos = df_db["Mês/Ano Numérico"].unique().tolist() if not df_db.empty else []
                    df_final = df_novos[~df_novos["Mês/Ano Numérico"].isin(ja_salvos)]
                    if not df_final.empty:
                        conn.update(worksheet="Dados", data=pd.concat([df_db, df_final], ignore_index=True))
                        st.success("Sincronização concluída!")
                        time.sleep(1); st.rerun()
                    else: st.error("Esses dados já constam no banco.")

st.write("---")

# ==========================================
# 8. DASHBOARD COMPLETO (COM TABELAS DETALHADAS)
# ==========================================
if not df_ano.empty:
    aba1, aba2, aba3, aba4, aba5 = st.tabs(["📈 Geral", "🏢 Setor", "⛽ Combustível", "🚛 Veículo", "📅 Comparativo"])
    ordem_meses = df_db["Mês/Ano Exibição"].unique().tolist()
    id_grafico = f"_{ano_selecionado}"

    with aba1:
        st.subheader(f"Evolução Total - {ano_selecionado}")
        resumo_geral = df_ano.groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        col1, col2 = st.columns(2)
        col1.plotly_chart(px.bar(resumo_geral, x="Mês/Ano Exibição", y="Valor Total (R$)", text=resumo_geral["Valor Total (R$)"].apply(formata_moeda), title="Custo Mensal", color_discrete_sequence=["#0C3C7A"], category_orders={"Mês/Ano Exibição": ordem_meses}), use_container_width=True, key=f"g1{id_grafico}")
        col2.plotly_chart(px.bar(resumo_geral, x="Mês/Ano Exibição", y="Quantidade (L)", text=resumo_geral["Quantidade (L)"].apply(formata_litro), title="Consumo Mensal", color_discrete_sequence=["#4CAF50"], category_orders={"Mês/Ano Exibição": ordem_meses}), use_container_width=True, key=f"g2{id_grafico}")
        st.write("**Detalhamento dos Dados Mensais:**")
        st.dataframe(formatar_tabela_exibicao(resumo_geral), use_container_width=True, hide_index=True)

    with aba2:
        setores_disp = df_ano["Setor"].unique().tolist()
        setor_escolhido = st.selectbox("Selecione o Setor:", setores_disp)
        resumo_setor = df_ano[df_ano["Setor"] == setor_escolhido].groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        col1, col2 = st.columns(2)
        col1.plotly_chart(px.bar(resumo_setor, x="Mês/Ano Exibição", y="Valor Total (R$)", title=f"Gasto: {setor_escolhido}", color_discrete_sequence=["#0C3C7A"], category_orders={"Mês/Ano Exibição": ordem_meses}), use_container_width=True, key=f"g3{id_grafico}")
        col2.plotly_chart(px.bar(resumo_setor, x="Mês/Ano Exibição", y="Quantidade (L)", title=f"Volume: {setor_escolhido}", color_discrete_sequence=["#4CAF50"], category_orders={"Mês/Ano Exibição": ordem_meses}), use_container_width=True, key=f"g4{id_grafico}")
        st.write(f"**Tabela Resumo - {setor_escolhido}:**")
        st.dataframe(formatar_tabela_exibicao(resumo_setor), use_container_width=True, hide_index=True)

    with aba3:
        combs_disp = df_ano["Combustível"].unique().tolist()
        comb_escolhido = st.selectbox("Selecione o Combustível:", combs_disp)
        resumo_comb = df_ano[df_ano["Combustível"] == comb_escolhido].groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        col1, col2 = st.columns(2)
        col1.plotly_chart(px.bar(resumo_comb, x="Mês/Ano Exibição", y="Valor Total (R$)", title=f"Custo com {comb_escolhido}", color_discrete_sequence=["#0C3C7A"]), use_container_width=True, key=f"g5{id_grafico}")
        col2.plotly_chart(px.bar(resumo_comb, x="Mês/Ano Exibição", y="Quantidade (L)", title=f"Volume de {comb_escolhido}", color_discrete_sequence=["#4CAF50"]), use_container_width=True, key=f"g6{id_grafico}")
        st.write(f"**Tabela de Consumo - {comb_escolhido}:**")
        st.dataframe(formatar_tabela_exibicao(resumo_comb), use_container_width=True, hide_index=True)

    with aba4:
        veiculos_disp = sorted(df_ano["Veículo (Placa e Modelo)"].unique().tolist())
        veic_escolhido = st.selectbox("Escolha o Veículo:", veiculos_disp)
        resumo_veic = df_ano[df_ano["Veículo (Placa e Modelo)"] == veic_escolhido].groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        col1, col2 = st.columns(2)
        col1.plotly_chart(px.line(resumo_veic, x="Mês/Ano Exibição", y="Valor Total (R$)", markers=True, title=f"Curva Financeira: {veic_escolhido}", color_discrete_sequence=["#0C3C7A"]), use_container_width=True, key=f"g7{id_grafico}")
        col2.plotly_chart(px.line(resumo_veic, x="Mês/Ano Exibição", y="Quantidade (L)", markers=True, title=f"Curva de Consumo: {veic_escolhido}", color_discrete_sequence=["#4CAF50"]), use_container_width=True, key=f"g8{id_grafico}")
        st.write(f"**Histórico Individual: {veic_escolhido}:**")
        st.dataframe(formatar_tabela_exibicao(resumo_veic), use_container_width=True, hide_index=True)

    with aba5:
        meses_lista = df_db["Nome do Mês"].unique().tolist()
        mes_escolhido = st.selectbox("Escolha o Mês para Comparativo Anual:", meses_lista)
        df_comp = df_db[df_db["Nome do Mês"] == mes_escolhido].groupby("Ano")[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        df_comp["Ano"] = df_comp["Ano"].astype(str)
        col1, col2 = st.columns(2)
        col1.plotly_chart(px.bar(df_comp, x="Ano", y="Valor Total (R$)", title=f"Comparativo Financeiro ({mes_escolhido})", color="Ano"), use_container_width=True, key=f"g9{id_grafico}")
        col2.plotly_chart(px.bar(df_comp, x="Ano", y="Quantidade (L)", title=f"Comparativo de Litros ({mes_escolhido})", color="Ano"), use_container_width=True, key=f"g10{id_grafico}")
        st.write(f"**Dados Históricos do Mês de {mes_escolhido}:**")
        st.dataframe(formatar_tabela_exibicao(df_comp), use_container_width=True, hide_index=True)

else: st.info("Selecione um ano para carregar o Dashboard.")
