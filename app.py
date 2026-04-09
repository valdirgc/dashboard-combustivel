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
cookie_manager = stx.CookieManager(key="gerenciador_cookies_frota")

# Trava de Sincronia: Espera o navegador responder
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

# --- LÓGICA DE AUTO-LOGIN (LEITURA DO PACOTE ÚNICO) ---
if not st.session_state.autenticado and not st.session_state.ignorar_cookie:
    pacote_sessao = cookie_manager.get(cookie="sessao_frota")
    if pacote_sessao:
        try:
            # O cookie guarda um texto JSON, vamos transformar de volta em dados
            dados = json.loads(pacote_sessao)
            st.session_state.autenticado = True
            st.session_state.usuario_logado = dados["user"]
            st.session_state.nivel_acesso = dados["nivel"]
        except:
            pass

# Reseta a flag de ignorar após o ciclo
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
    }
    .stButton>button:hover { background-color: #082954; color: white; transform: translateY(-2px); box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
    div[data-testid="stMetricValue"] { color: #0C3C7A; font-weight: 800; }
    .stTabs [data-baseweb="tab-list"] { gap: 10px; }
    .stTabs [data-baseweb="tab"] { height: 50px; background-color: transparent; border-radius: 6px 6px 0px 0px; padding: 10px 20px; border: 1px solid transparent; }
    .stTabs [aria-selected="true"] { background-color: #E8F0FE; border-bottom: 4px solid #0C3C7A !important; color: #0C3C7A !important; font-weight: 800; }
    [data-testid="stSidebar"] { background-color: #F8F9FA; border-right: 1px solid #DEE2E6; }
</style>
""", unsafe_allow_html=True)


# ==========================================
# 3. FUNÇÕES BASE E EXTRAÇÃO
# ==========================================
MESES_PT = {
    "01": "Janeiro", "02": "Fevereiro", "03": "Março", "04": "Abril",
    "05": "Maio", "06": "Junho", "07": "Julho", "08": "Agosto",
    "09": "Setembro", "10": "Outubro", "11": "Novembro", "12": "Dezembro", "00": "Desconhecido"
}

def formata_moeda(valor):
    return f"R$ {valor:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

def formata_litro(valor):
    return f"{valor:,.2f} L".replace(',', 'X').replace('.', ',').replace('X', '.')

def formatar_tabela(df_tabela):
    df_formatado = df_tabela.copy()
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
    if '.' in v_str and ',' in v_str:
        v_str = v_str.replace('.', '')
    v_str = v_str.replace(',', '.')
    try: return float(v_str)
    except ValueError: return 0.0

@st.cache_data(show_spinner="Analisando PDFs...")
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
                placa_atual = match_veiculo.group(1).strip()
                placa_atual = re.sub(r'\s+', ' ', placa_atual)
                combustivel_atual = "Não Identificado"
                setor_atual = "Não Identificado"
                match_combustivel = re.search(r"ESP[ÉE]CIE:\s*([A-Z]+)", linha_limpa, re.IGNORECASE)
                if match_combustivel: combustivel_atual = match_combustivel.group(1).strip()
            elif placa_atual and re.search(r"ESP[ÉE]CIE:\s*([A-Z]+)", linha_limpa, re.IGNORECASE):
                match_combustivel = re.search(r"ESP[ÉE]CIE:\s*([A-Z]+)", linha_limpa, re.IGNORECASE)
                combustivel_atual = match_combustivel.group(1).strip()
            elif placa_atual and re.search(r"UNIDADE\s*/\s*SETOR:\s*(.+)", linha_limpa, re.IGNORECASE):
                match_setor = re.search(r"UNIDADE\s*/\s*SETOR:\s*(.+)", linha_limpa, re.IGNORECASE)
                setor_atual = match_setor.group(1).strip()
            elif "TOTAL VE" in linha_limpa.upper() and placa_atual:
                numeros = re.findall(r"\d+(?:\.\d+)*(?:,\d+)?", linha_limpa)
                if len(numeros) >= 2:
                    try:
                        litros_float = float(numeros[-2].replace('.', '').replace(',', '.'))
                        valor_float = float(numeros[-1].replace('.', '').replace(',', '.'))
                        mes_num, ano_num = mes_sugerido.split("/")
                        dados_gerais.append({
                            "Veículo (Placa e Modelo)": placa_atual, "Setor": setor_atual, "Combustível": combustivel_atual,
                            "Quantidade (L)": litros_float, "Valor Total (R$)": valor_float, "Mês/Ano Numérico": mes_sugerido,
                            "Mês": str(mes_num).zfill(2), "Ano": int(ano_num)
                        })
                    except ValueError: pass
                placa_atual = None 
    return dados_gerais, list(meses_identificados)


# ==========================================
# 4. BARRA LATERAL FIXA
# ==========================================
url_brasao = "logo.png"
col_img1, col_img2, col_img3 = st.sidebar.columns([1, 2, 1])
with col_img2:
    try: st.image(url_brasao, use_container_width=True)
    except: pass 
        
st.sidebar.markdown("<div style='text-align: center; color: #0C3C7A; font-weight: 700; font-size: 16px; margin-bottom: 25px;'>Prefeitura Municipal<br>de Jaborandi/SP</div>", unsafe_allow_html=True)
st.sidebar.markdown("---")


# ==========================================
# 5. TELA DE LOGIN CENTRALIZADA
# ==========================================
if not st.session_state.autenticado:
    st.title("🏛️ Sistema de Gestão de Combustível")
    st.write("---")
    
    col_espaco1, col_login, col_espaco3 = st.columns([1, 2, 1])
    
    with col_login:
        st.markdown("<h3 style='text-align: center; color: #0C3C7A;'>🔒 Acesso ao Painel</h3>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center;'>Por favor, insira suas credenciais institucionais.</p>", unsafe_allow_html=True)
        st.write("") 
        
        usuario_digitado = st.text_input("Usuário").strip()
        senha_digitada = st.text_input("Senha", type="password")
        lembrar_me = st.checkbox("Manter-me conectado neste computador")
        
        if st.button("Entrar no Sistema", use_container_width=True):
            sucesso = False
            nivel = ""
            
            if "admin" in st.secrets and usuario_digitado in st.secrets["admin"]:
                if st.secrets["admin"][usuario_digitado] == senha_digitada:
                    sucesso, nivel = True, "admin"
            elif "viewer" in st.secrets and usuario_digitado in st.secrets["viewer"]:
                if st.secrets["viewer"][usuario_digitado] == senha_digitada:
                    sucesso, nivel = True, "viewer"
            
            if sucesso:
                st.session_state.autenticado = True
                st.session_state.usuario_logado = usuario_digitado
                st.session_state.nivel_acesso = nivel
                
                if lembrar_me:
                    # Salva tudo em UM único cookie para evitar o erro de duplicidade
                    dados_pacote = json.dumps({"user": usuario_digitado, "nivel": nivel})
                    expira = datetime.datetime.now() + datetime.timedelta(days=30)
                    cookie_manager.set("sessao_frota", dados_pacote, expires_at=expira)
                    time.sleep(0.5)
                st.rerun()
            else:
                st.error("Usuário ou senha incorretos!")
                
    st.stop()


# ==========================================
# 6. BANCO DE DADOS (PÓS-LOGIN)
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
        ordem_cronologica = df_db["Mês/Ano Exibição"].unique().tolist()
    else:
        df_db = pd.DataFrame(columns=["Ano"])
        ordem_cronologica = []
except:
    df_db = pd.DataFrame(columns=["Ano"])
    ordem_cronologica = []


# ==========================================
# 7. BARRA LATERAL (FILTROS E SAIR)
# ==========================================
st.sidebar.title("Filtros Gerenciais")

if not df_db.empty and len(df_db) > 1:
    anos_disponiveis = df_db["Ano"].dropna().unique().tolist()
    anos_disponiveis.sort(reverse=True)
    ano_escolhido = st.sidebar.selectbox("Ano:", anos_disponiveis)
    df_ano = df_db[df_db["Ano"] == ano_escolhido]
    st.sidebar.write("---")
    st.sidebar.write(f"**Resumo Global ({ano_escolhido}):**")
    st.sidebar.write(f"Custo: {formata_moeda(df_ano['Valor Total (R$)'].sum())}")
    st.sidebar.write(f"Volume: {formata_litro(df_ano['Quantidade (L)'].sum())}")
else:
    ano_escolhido = None
    df_ano = pd.DataFrame()

st.sidebar.markdown("---")
st.sidebar.success(f"✅ Logado: **{st.session_state.usuario_logado.capitalize()}**")
if st.sidebar.button("Sair do Sistema", use_container_width=True):
    cookie_manager.delete("sessao_frota") # Deleta o pacote único
    st.session_state.autenticado = False
    st.session_state.usuario_logado = ""
    st.session_state.nivel_acesso = ""
    st.session_state.ignorar_cookie = True 
    time.sleep(0.5)
    st.rerun()


# ==========================================
# 8. ÁREA PRINCIPAL
# ==========================================
st.title("🏛️ Gestão de Combustível")

if st.session_state.nivel_acesso == "admin":
    with st.expander("📥 Importar Novos Relatórios (PDF)"):
        arquivos_pdf = st.file_uploader("Selecione os arquivos", type=["pdf"], accept_multiple_files=True, key=f"up_{st.session_state.uploader_key}")
        if arquivos_pdf:
            dados, meses = extrair_dados_pdfs(arquivos_pdf)
            if dados:
                df_ex = pd.DataFrame(dados)
                st.success(f"Extraídas {len(df_ex)} linhas!")
                if st.button("💾 Salvar no Google Sheets"):
                    meses_salvos = df_db["Mês/Ano Numérico"].dropna().unique().tolist()
                    df_novos = df_ex[~df_ex["Mês/Ano Numérico"].isin(meses_salvos)]
                    if not df_novos.empty:
                        df_comp = pd.concat([df_db, df_novos], ignore_index=True)
                        conn.update(worksheet="Dados", data=df_comp)
                        st.success("Dados salvos na nuvem!")
                        st.session_state.uploader_key += 1
                        st.rerun()
                    else: st.error("Meses já existentes no banco.")

st.write("---")

if not df_ano.empty:
    aba1, aba2, aba3, aba4, aba5 = st.tabs(["📈 Evolução", "🏢 Setor", "⛽ Combustível", "🚛 Veículo", "📅 Comparativo"])
    id_s = f"_{ano_escolhido}"
    
    with aba1:
        res_m = df_ano.groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        res_m["V"] = res_m["Valor Total (R$)"].apply(formata_moeda)
        res_m["L"] = res_m["Quantidade (L)"].apply(formata_litro)
        c1, c2 = st.columns(2)
        with c1: st.plotly_chart(px.bar(res_m, x="Mês/Ano Exibição", y="Valor Total (R$)", text="V", title="Custo (R$)", color_discrete_sequence=["#0C3C7A"], category_orders={"Mês/Ano Exibição": ordem_cronologica}), use_container_width=True, key=f"g1{id_s}")
        with c2: st.plotly_chart(px.bar(res_m, x="Mês/Ano Exibição", y="Quantidade (L)", text="L", title="Volume (L)", color_discrete_sequence=["#4CAF50"], category_orders={"Mês/Ano Exibição": ordem_cronologica}), use_container_width=True, key=f"g2{id_s}")
        st.dataframe(formatar_tabela(res_m[["Mês/Ano Exibição", "Quantidade (L)", "Valor Total (R$)"]]), use_container_width=True)

    with aba2:
        setor = st.selectbox("Setor:", df_ano["Setor"].unique().tolist())
        df_s = df_ano[df_ano["Setor"] == setor]
        res_s = df_s.groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        res_s["V"], res_s["L"] = res_s["Valor Total (R$)"].apply(formata_moeda), res_s["Quantidade (L)"].apply(formata_litro)
        c1, c2 = st.columns(2)
        with c1: st.plotly_chart(px.bar(res_s, x="Mês/Ano Exibição", y="Valor Total (R$)", text="V", title="Custo", color_discrete_sequence=["#0C3C7A"], category_orders={"Mês/Ano Exibição": ordem_cronologica}), use_container_width=True, key=f"g3{id_s}")
        with c2: st.plotly_chart(px.bar(res_s, x="Mês/Ano Exibição", y="Quantidade (L)", text="L", title="Volume", color_discrete_sequence=["#4CAF50"], category_orders={"Mês/Ano Exibição": ordem_cronologica}), use_container_width=True, key=f"g4{id_s}")

    with aba3:
        comb = st.selectbox("Combustível:", df_ano["Combustível"].unique().tolist())
        df_c = df_ano[df_ano["Combustível"] == comb]
        res_c = df_c.groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        res_c["V"], res_c["L"] = res_c["Valor Total (R$)"].apply(formata_moeda), res_c["Quantidade (L)"].apply(formata_litro)
        c1, c2 = st.columns(2)
        with c1: st.plotly_chart(px.bar(res_c, x="Mês/Ano Exibição", y="Valor Total (R$)", text="V", title="Custo", color_discrete_sequence=["#0C3C7A"], category_orders={"Mês/Ano Exibição": ordem_cronologica}), use_container_width=True, key=f"g5{id_s}")
        with c2: st.plotly_chart(px.bar(res_c, x="Mês/Ano Exibição", y="Quantidade (L)", text="L", title="Volume", color_discrete_sequence=["#4CAF50"], category_orders={"Mês/Ano Exibição": ordem_cronologica}), use_container_width=True, key=f"g6{id_s}")

    with aba4:
        veic = st.selectbox("Veículo:", df_ano["Veículo (Placa e Modelo)"].sort_values().unique().tolist())
        df_v = df_ano[df_ano["Veículo (Placa e Modelo)"] == veic]
        res_v = df_v.groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        res_v["V"], res_v["L"] = res_v["Valor Total (R$)"].apply(formata_moeda), res_v["Quantidade (L)"].apply(formata_litro)
        c1, c2 = st.columns(2)
        with c1: st.plotly_chart(px.line(res_v, x="Mês/Ano Exibição", y="Valor Total (R$)", text="V", markers=True, title="Custo", color_discrete_sequence=["#0C3C7A"]), use_container_width=True, key=f"g7{id_s}")
        with c2: st.plotly_chart(px.line(res_v, x="Mês/Ano Exibição", y="Quantidade (L)", text="L", markers=True, title="Volume", color_discrete_sequence=["#4CAF50"]), use_container_width=True, key=f"g8{id_s}")

    with aba5:
        mes_comp = st.selectbox("Mês:", df_db["Nome do Mês"].unique().tolist())
        df_comp = df_db[df_db["Nome do Mês"] == mes_comp]
        res_comp = df_comp.groupby("Ano")[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        res_comp["Ano"] = res_comp["Ano"].astype(str)
        c1, c2 = st.columns(2)
        with c1: st.plotly_chart(px.bar(res_comp, x="Ano", y="Valor Total (R$)", text=res_comp["Valor Total (R$)"].apply(formata_moeda), title="Financeiro", color="Ano"), use_container_width=True, key=f"g9{id_s}")
        with c2: st.plotly_chart(px.bar(res_comp, x="Ano", y="Quantidade (L)", text=res_comp["Quantidade (L)"].apply(formata_litro), title="Volume", color="Ano"), use_container_width=True, key=f"g10{id_s}")

else: st.info("Sem dados para o ano selecionado.")
