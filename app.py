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

# --- O "DUPLO CLIQUE INVISÍVEL" PARA SALVAR O F5 ---
# Força o Streamlit a recarregar a página sozinho 1 vez na primeira vez que abre,
# dando tempo exato para o JavaScript do navegador entregar os cookies pro Python.
if "primeira_leitura" not in st.session_state:
    st.session_state.primeira_leitura = True
    time.sleep(0.5) 
    st.rerun() 

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

# --- LÓGICA DE AUTO-LOGIN (LEITURA DO COOKIE EM PACOTE ÚNICO) ---
try:
    if st.session_state.ignorar_cookie:
        st.session_state.ignorar_cookie = False
    else:
        pacote_sessao = cookie_manager.get(cookie="sessao_frota")
        if pacote_sessao and not st.session_state.autenticado:
            dados = json.loads(pacote_sessao)
            st.session_state.autenticado = True
            st.session_state.usuario_logado = dados["user"]
            st.session_state.nivel_acesso = dados["nivel"]
except Exception as e:
    pass


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

@st.cache_data(show_spinner="Analisando PDFs e extraindo dados...")
def extrair_dados_pdfs(arquivos):
    dados_gerais = []
    meses_identificados = set()
    for arquivo in arquivos:
        texto_completo = ""
        with pdfplumber.open(arquivo) as pdf:
            for pagina in pdf.pages:
                texto_pagina = pagina.extract_text(layout=True)
                if texto_pagina:
                    texto_completo += texto_pagina + "\n"
        
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
                if match_combustivel:
                    combustivel_atual = match_combustivel.group(1).strip()
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
                            "Veículo (Placa e Modelo)": placa_atual,
                            "Setor": setor_atual,
                            "Combustível": combustivel_atual,
                            "Quantidade (L)": litros_float,
                            "Valor Total (R$)": valor_float,
                            "Mês/Ano Numérico": mes_sugerido,
                            "Mês": str(mes_num).zfill(2),
                            "Ano": int(ano_num)
                        })
                    except ValueError:
                        pass
                placa_atual = None 
    return dados_gerais, list(meses_identificados)


# ==========================================
# 4. BARRA LATERAL FIXA (LOGO E NOME)
# ==========================================
url_brasao = "logo.png"
col_img1, col_img2, col_img3 = st.sidebar.columns([1, 2, 1])
with col_img2:
    try: st.image(url_brasao, use_container_width=True)
    except: pass 
        
st.sidebar.markdown(
    """
    <div style='text-align: center; color: #0C3C7A; font-weight: 700; font-size: 16px; margin-bottom: 25px;'>
        Prefeitura Municipal<br>de Jaborandi/SP
    </div>
    """, unsafe_allow_html=True
)
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
            try:
                login_sucesso = False
                
                if "admin" in st.secrets and usuario_digitado in st.secrets["admin"]:
                    if st.secrets["admin"][usuario_digitado] == senha_digitada:
                        st.session_state.autenticado = True
                        st.session_state.usuario_logado = usuario_digitado
                        st.session_state.nivel_acesso = "admin"
                        login_sucesso = True
                
                elif "viewer" in st.secrets and usuario_digitado in st.secrets["viewer"]:
                    if st.secrets["viewer"][usuario_digitado] == senha_digitada:
                        st.session_state.autenticado = True
                        st.session_state.usuario_logado = usuario_digitado
                        st.session_state.nivel_acesso = "viewer"
                        login_sucesso = True
                        
                if login_sucesso:
                    if lembrar_me:
                        pacote = json.dumps({"user": usuario_digitado, "nivel": st.session_state.nivel_acesso})
                        expira_em = datetime.datetime.now() + datetime.timedelta(days=30)
                        cookie_manager.set("sessao_frota", pacote, expires_at=expira_em)
                        time.sleep(0.5) 
                    st.rerun()
                else:
                    st.error("Usuário ou senha incorretos! Tente novamente.")
            
            except Exception as e:
                st.error("🚨 ERRO NO PROCESSO DE LOGIN. Copie o erro abaixo:")
                st.exception(e)
                st.stop()
                
    st.stop()


# ==========================================
# 6. LER BANCO DE DADOS (PÓS-LOGIN)
# ==========================================
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
    colunas_bd = [
        "Veículo (Placa e Modelo)", "Setor", "Combustível", 
        "Quantidade (L)", "Valor Total (R$)", "Mês/Ano Numérico", "Mês", "Ano"
    ]

    df_db = conn.read(worksheet="Dados", ttl=0)
    if df_db.empty or "Veículo (Placa e Modelo)" not in df_db.columns:
        df_db = pd.DataFrame(columns=colunas_bd)
    else:
        df_db["Quantidade (L)"] = df_db["Quantidade (L)"].apply(converter_para_numero)
        df_db["Valor Total (R$)"] = df_db["Valor Total (R$)"].apply(converter_para_numero)
        
        df_db["Mês"] = df_db["Mês"].astype(str).str.replace(".0", "", regex=False).str.zfill(2)
        df_db["Ano"] = df_db["Ano"].astype(str).str.replace(".0", "", regex=False)
        df_db = df_db.sort_values(by=["Ano", "Mês"])
        df_db["Nome do Mês"] = df_db["Mês"].map(MESES_PT).fillna("Desconhecido")
        df_db["Mês/Ano Exibição"] = df_db["Nome do Mês"] + " " + df_db["Ano"]
        ordem_cronologica = df_db["Mês/Ano Exibição"].unique().tolist()
        
except Exception as e:
    st.error("🚨 Erro ao conectar com o Google Sheets:")
    st.exception(e)
    df_db = pd.DataFrame(columns=["Ano"]) 
    ordem_cronologica = []


# ==========================================
# 7. BARRA LATERAL E LOGOUT PROTEGIDO
# ==========================================
st.sidebar.title("Filtros Gerenciais")

if not df_db.empty and len(df_db) > 0:
    anos_disponiveis = df_db["Ano"].dropna().unique().tolist()
    anos_disponiveis.sort(reverse=True)
    if anos_disponiveis:
        ano_escolhido = st.sidebar.selectbox("Filtre as análises por Ano:", anos_disponiveis)
        df_ano = df_db[df_db["Ano"] == ano_escolhido]
        
        # O RESUMO BONITÃO DE VOLTA!
        st.sidebar.write("---")
        st.sidebar.info(f"**Resumo Global ({ano_escolhido}):**\n\n"
                        f"💰 Custo: **{formata_moeda(df_ano['Valor Total (R$)'].sum())}**\n\n"
                        f"⛽ Volume: **{formata_litro(df_ano['Quantidade (L)'].sum())}**")
    else:
        ano_escolhido = None
        df_ano = pd.DataFrame()
else:
    ano_escolhido = None
    df_ano = pd.DataFrame()

# Rodapé da Barra Lateral e Soft Logout
st.sidebar.markdown("---")
st.sidebar.success(f"✅ Logado como: **{st.session_state.usuario_logado.capitalize()}**")
tipo_perfil = "Administrador" if st.session_state.nivel_acesso == "admin" else "Visualizador"
st.sidebar.caption(f"Nível de Acesso: {tipo_perfil}")

if st.sidebar.button("Sair do Sistema", use_container_width=True):
    try:
        todos_cookies_del = cookie_manager.get_all()
        if type(todos_cookies_del) is dict:
            if "sessao_frota" in todos_cookies_del:
                cookie_manager.delete("sessao_frota")
        
        st.session_state.autenticado = False
        st.session_state.usuario_logado = ""
        st.session_state.nivel_acesso = ""
        st.session_state.ignorar_cookie = True 
        
        time.sleep(0.5) 
        st.rerun()
    except Exception as e:
        st.sidebar.error("🚨 ERRO AO SAIR:")
        st.sidebar.exception(e)


# ==========================================
# 8. ÁREA PRINCIPAL E UPLOAD PROTEGIDO
# ==========================================
st.title("🏛️ Painel de Gestão de Combustível")

if st.session_state.nivel_acesso == "admin":
    st.write("Importe os novos relatórios mensais (PDF) para alimentar a base de dados.")
    
    with st.expander("📥 Importar Novos Relatórios"):
        arquivos_pdf = st.file_uploader(
            "Selecione os arquivos PDF para adicionar ao histórico", 
            type=["pdf"], accept_multiple_files=True, key=f"uploader_{st.session_state.uploader_key}"
        )

        if arquivos_pdf:
            try:
                dados_gerais, meses_identificados = extrair_dados_pdfs(arquivos_pdf)
                if dados_gerais:
                    df_extraido = pd.DataFrame(dados_gerais)
                    st.success(f"Foram extraídas {len(df_extraido)} linhas de dados de {len(arquivos_pdf)} arquivo(s)!")
                    st.info(f"Meses identificados: {', '.join(meses_identificados)}")
                    
                    if st.button("💾 Integrar Dados ao Servidor na Nuvem"):
                        meses_ja_salvos = df_db["Mês/Ano Numérico"].dropna().unique().tolist()
                        df_novos = df_extraido[~df_extraido["Mês/Ano Numérico"].isin(meses_ja_salvos)]
                        meses_ignorados = df_extraido[df_extraido["Mês/Ano Numérico"].isin(meses_ja_salvos)]["Mês/Ano Numérico"].unique().tolist()
                        
                        if not df_novos.empty:
                            df_completo = pd.concat([df_db, df_novos], ignore_index=True)
                            conn.update(worksheet="Dados", data=df_completo)
                            st.success("Novos dados enviados e consolidados com sucesso!")
                        
                        if meses_ignorados:
                            st.error(f"Atenção: Os meses {', '.join(meses_ignorados)} já existiam no banco e foram ignorados para evitar duplicidade de valores.")
                        
                        st.session_state.uploader_key += 1
                        st.rerun()
            except Exception as e:
                st.error(f"Erro ao processar o arquivo: {e}")

elif st.session_state.nivel_acesso == "viewer":
    st.write("Acompanhe o histórico de consumo e custos operacionais da frota municipal abaixo.")


# ==========================================
# 9. DASHBOARD GERENCIAL (TABELAS ORIGINAIS MANTIDAS)
# ==========================================
st.write("---")

if not df_ano.empty:
    aba1, aba2, aba3, aba4, aba5 = st.tabs([
        "📈 Evolução Geral", "🏢 Por Setor", "⛽ Por Combustível", "🚛 Por Veículo", "📅 Comparativo Anual"
    ])
    
    id_sufixo = f"_{ano_escolhido}"
    
    # --- ABA 1: GERAL ---
    with aba1:
        st.subheader(f"Custos e Volume Totais ({ano_escolhido})")
        resumo_mes = df_ano.groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        resumo_mes["Texto Valor"] = resumo_mes["Valor Total (R$)"].apply(formata_moeda)
        resumo_mes["Texto Litros"] = resumo_mes["Quantidade (L)"].apply(formata_litro)
        
        col1, col2 = st.columns(2)
        with col1:
            fig1 = px.bar(resumo_mes, x="Mês/Ano Exibição", y="Valor Total (R$)", text="Texto Valor", title="Custo Financeiro (R$)", color_discrete_sequence=["#0C3C7A"], category_orders={"Mês/Ano Exibição": ordem_cronologica})
            fig1.update_traces(textposition='outside')
            st.plotly_chart(fig1, use_container_width=True, key=f"graf_geral_custo{id_sufixo}")
        with col2:
            fig2 = px.bar(resumo_mes, x="Mês/Ano Exibição", y="Quantidade (L)", text="Texto Litros", title="Volume Consumido (Litros)", color_discrete_sequence=["#4CAF50"], category_orders={"Mês/Ano Exibição": ordem_cronologica})
            fig2.update_traces(textposition='outside')
            st.plotly_chart(fig2, use_container_width=True, key=f"graf_geral_vol{id_sufixo}")
            
        st.write("**Tabela de Consolidação Mensal**")
        st.dataframe(formatar_tabela(resumo_mes[["Mês/Ano Exibição", "Quantidade (L)", "Valor Total (R$)"]]), use_container_width=True)
        
    # --- ABA 2: SETOR ---
    with aba2:
        st.subheader(f"Investigação por Setor ({ano_escolhido})")
        setor_escolhido = st.selectbox("Selecione o Setor:", df_ano["Setor"].unique().tolist())
        df_setor = df_ano[df_ano["Setor"] == setor_escolhido]
        resumo_setor_mes = df_setor.groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        resumo_setor_mes["Texto Valor"] = resumo_setor_mes["Valor Total (R$)"].apply(formata_moeda)
        resumo_setor_mes["Texto Litros"] = resumo_setor_mes["Quantidade (L)"].apply(formata_litro)
        
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            fig_s1 = px.bar(resumo_setor_mes, x="Mês/Ano Exibição", y="Valor Total (R$)", text="Texto Valor", color_discrete_sequence=["#0C3C7A"], title=f"Custo (R$)", category_orders={"Mês/Ano Exibição": ordem_cronologica})
            fig_s1.update_traces(textposition='auto')
            st.plotly_chart(fig_s1, use_container_width=True, key=f"graf_setor_custo{id_sufixo}")
        with col_s2:
            fig_s2 = px.bar(resumo_setor_mes, x="Mês/Ano Exibição", y="Quantidade (L)", text="Texto Litros", color_discrete_sequence=["#4CAF50"], title=f"Consumo (L)", category_orders={"Mês/Ano Exibição": ordem_cronologica})
            fig_s2.update_traces(textposition='auto')
            st.plotly_chart(fig_s2, use_container_width=True, key=f"graf_setor_vol{id_sufixo}")
            
        col_tabela1, col_tabela2 = st.columns([2, 1])
        with col_tabela1:
            st.write(f"**Detalhamento Financeiro - {setor_escolhido}**")
            st.dataframe(formatar_tabela(resumo_setor_mes[["Mês/Ano Exibição", "Quantidade (L)", "Valor Total (R$)"]]), use_container_width=True)
        with col_tabela2:
            st.write(f"**Frota Ativa neste Setor ({ano_escolhido})**")
            veiculos_do_setor = pd.DataFrame(df_setor["Veículo (Placa e Modelo)"].unique(), columns=["Veículos Vinculados"])
            st.dataframe(veiculos_do_setor, hide_index=True, use_container_width=True)
            
    # --- ABA 3: COMBUSTÍVEL ---
    with aba3:
        st.subheader(f"Investigação por Combustível ({ano_escolhido})")
        comb_escolhido = st.selectbox("Selecione o Combustível:", df_ano["Combustível"].unique().tolist())
        df_comb = df_ano[df_ano["Combustível"] == comb_escolhido]
        resumo_comb_mes = df_comb.groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        resumo_comb_mes["Texto Valor"] = resumo_comb_mes["Valor Total (R$)"].apply(formata_moeda)
        resumo_comb_mes["Texto Litros"] = resumo_comb_mes["Quantidade (L)"].apply(formata_litro)
        
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            fig_c1 = px.bar(resumo_comb_mes, x="Mês/Ano Exibição", y="Valor Total (R$)", text="Texto Valor", color_discrete_sequence=["#0C3C7A"], title=f"Custo (R$)", category_orders={"Mês/Ano Exibição": ordem_cronologica})
            fig_c1.update_traces(textposition='auto')
            st.plotly_chart(fig_c1, use_container_width=True, key=f"graf_comb_custo{id_sufixo}")
        with col_c2:
            fig_c2 = px.bar(resumo_comb_mes, x="Mês/Ano Exibição", y="Quantidade (L)", text="Texto Litros", color_discrete_sequence=["#4CAF50"], title=f"Consumo (L)", category_orders={"Mês/Ano Exibição": ordem_cronologica})
            fig_c2.update_traces(textposition='auto')
            st.plotly_chart(fig_c2, use_container_width=True, key=f"graf_comb_vol{id_sufixo}")
            
        st.write(f"**Tabela de Detalhamento - {comb_escolhido}**")
        st.dataframe(formatar_tabela(resumo_comb_mes[["Mês/Ano Exibição", "Quantidade (L)", "Valor Total (R$)"]]), use_container_width=True)

    # --- ABA 4: POR VEÍCULO ---
    with aba4:
        st.subheader(f"Evolução Individual de Veículo ({ano_escolhido})")
        veiculos_disp = df_ano["Veículo (Placa e Modelo)"].sort_values().unique().tolist()
        veiculo_escolhido = st.selectbox("Selecione o Veículo:", veiculos_disp)
        
        df_veiculo = df_ano[df_ano["Veículo (Placa e Modelo)"] == veiculo_escolhido]
        resumo_veiculo = df_veiculo.groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        resumo_veiculo["Texto Valor"] = resumo_veiculo["Valor Total (R$)"].apply(formata_moeda)
        resumo_veiculo["Texto Litros"] = resumo_veiculo["Quantidade (L)"].apply(formata_litro)
        
        setor_veic = df_veiculo["Setor"].iloc[0] if not df_veiculo.empty else "-"
        comb_veic = df_veiculo["Combustível"].iloc[0] if not df_veiculo.empty else "-"
        st.info(f"📍 **Setor Atual:** {setor_veic} | ⛽ **Combustível Predominante:** {comb_veic}")
        
        col_v1, col_v2 = st.columns(2)
        with col_v1:
            fig_v1 = px.line(resumo_veiculo, x="Mês/Ano Exibição", y="Valor Total (R$)", text="Texto Valor", markers=True, color_discrete_sequence=["#0C3C7A"], title="Curva de Custo (R$)")
            fig_v1.update_traces(textposition="top center")
            st.plotly_chart(fig_v1, use_container_width=True, key=f"graf_veic_custo{id_sufixo}")
        with col_v2:
            fig_v2 = px.line(resumo_veiculo, x="Mês/Ano Exibição", y="Quantidade (L)", text="Texto Litros", markers=True, color_discrete_sequence=["#4CAF50"], title="Curva de Volume (L)")
            fig_v2.update_traces(textposition="top center")
            st.plotly_chart(fig_v2, use_container_width=True, key=f"graf_veic_vol{id_sufixo}")
            
        st.write(f"**Histórico de Lançamentos - {veiculo_escolhido}**")
        st.dataframe(formatar_tabela(resumo_veiculo[["Mês/Ano Exibição", "Quantidade (L)", "Valor Total (R$)"]]), use_container_width=True)
            
    # --- ABA 5: COMPARATIVO ANUAL ---
    with aba5:
        st.subheader("Variação do Mesmo Mês entre Anos Diferentes")
        st.write("*(Esta análise cruza toda a base histórica ignorando o filtro lateral)*")
        
        meses_salvos = df_db["Nome do Mês"].unique().tolist()
        mes_escolhido = st.selectbox("Selecione o Mês para comparar:", meses_salvos)
        
        df_comparativo = df_db[df_db["Nome do Mês"] == mes_escolhido]
        resumo_comparativo = df_comparativo.groupby("Ano")[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        resumo_comparativo["Ano"] = resumo_comparativo["Ano"].astype(str)
        resumo_comparativo["Texto Valor"] = resumo_comparativo["Valor Total (R$)"].apply(formata_moeda)
        resumo_comparativo["Texto Litros"] = resumo_comparativo["Quantidade (L)"].apply(formata_litro)
        
        col_a1, col_a2 = st.columns(2)
        with col_a1:
            fig_a1 = px.bar(resumo_comparativo, x="Ano", y="Valor Total (R$)", text="Texto Valor", color="Ano", title=f"Variação Financeira - {mes_escolhido}", color_discrete_sequence=px.colors.qualitative.Set1)
            fig_a1.update_traces(textposition='outside')
            st.plotly_chart(fig_a1, use_container_width=True, key=f"graf_ano_custo{id_sufixo}")
        with col_a2:
            fig_a2 = px.bar(resumo_comparativo, x="Ano", y="Quantidade (L)", text="Texto Litros", color="Ano", title=f"Variação de Volume (L) - {mes_escolhido}", color_discrete_sequence=px.colors.qualitative.Set1)
            fig_a2.update_traces(textposition='outside')
            st.plotly_chart(fig_a2, use_container_width=True, key=f"graf_ano_vol{id_sufixo}")
            
        st.write(f"**Tabela Comparativa Anual - {mes_escolhido}**")
        st.dataframe(formatar_tabela(resumo_comparativo[["Ano", "Quantidade (L)", "Valor Total (R$)"]]), hide_index=True, use_container_width=True)
