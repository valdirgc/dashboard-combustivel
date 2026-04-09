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
# 1. CONFIGURAÇÕES INICIAIS
# ==========================================
st.set_page_config(page_title="Sistema Frota - Jaborandi", layout="wide", initial_sidebar_state="expanded")

# Inicializa o Gerenciador de Cookies
# Usar uma chave fixa ajuda o navegador a não se confundir entre versões
cookie_manager = stx.CookieManager(key="frota_jaborandi_vfinal")

# --- SISTEMA DE VIGILÂNCIA DE LOGIN (ANTI-F5) ---
# Se ainda não sabemos quem é o usuário, damos 1.5 segundos para os cookies aparecerem
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

if not st.session_state.autenticado:
    # Pequena espera para o componente de Cookie "acordar"
    time.sleep(0.5) 
    pacote_cookie = cookie_manager.get(cookie="sessao_frota_jaborandi")
    
    if pacote_cookie:
        try:
            dados_recuperados = json.loads(pacote_cookie)
            st.session_state.autenticado = True
            st.session_state.usuario_logado = dados_recuperados["user"]
            st.session_state.nivel_acesso = dados_recuperados["nivel"]
        except:
            pass

# Outras variáveis de memória
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0
if "usuario_logado" not in st.session_state:
    st.session_state.usuario_logado = ""
if "nivel_acesso" not in st.session_state:
    st.session_state.nivel_acesso = ""

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
    .stTabs [aria-selected="true"] { background-color: #E8F0FE; border-bottom: 4px solid #0C3C7A !important; color: #0C3C7A !important; font-weight: 800; }
    [data-testid="stSidebar"] { background-color: #F8F9FA; border-right: 1px solid #DEE2E6; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 3. FUNÇÕES DE TRADUÇÃO E LIMPEZA
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

def converter_para_numero(valor):
    if pd.isna(valor): return 0.0
    if isinstance(valor, (int, float)): return float(valor)
    v_str = str(valor).strip()
    v_str = re.sub(r'[^\d\.,\-]', '', v_str)
    if v_str == '': return 0.0
    if '.' in v_str and ',' in v_str: v_str = v_str.replace('.', '')
    v_str = v_str.replace(',', '.')
    try: return float(v_str)
    except: return 0.0

@st.cache_data(show_spinner="Processando relatórios PDF...")
def extrair_dados_pdfs(arquivos):
    dados_gerais = []
    meses_identificados = set()
    for arquivo in arquivos:
        texto_completo = ""
        with pdfplumber.open(arquivo) as pdf:
            for pagina in pdf.pages:
                texto_p = pagina.extract_text(layout=True)
                if texto_p: texto_completo += texto_p + "\n"
        
        mes_sugerido = "00/0000" 
        match_p = re.search(r"Período:\s*De\s*(\d{2}/\d{2}/\d{4})", texto_completo)
        if match_p:
            mes_sugerido = match_p.group(1)[3:] 
            meses_identificados.add(mes_sugerido)
            
        linhas = texto_completo.split('\n')
        placa_atual = None
        comb_atual = "Não Identificado"
        setor_atual = "Não Identificado"
        
        for linha in linhas:
            linha_limpa = linha.replace("|", "").strip()
            match_v = re.search(r"VE[IÍ]CULO\s*:\s*(.*?)(?:\s+ESP[ÉE]CIE|$)", linha_limpa, re.IGNORECASE)
            if match_v:
                placa_atual = re.sub(r'\s+', ' ', match_v.group(1).strip())
                match_c = re.search(r"ESP[ÉE]CIE:\s*([A-Z]+)", linha_limpa, re.IGNORECASE)
                comb_atual = match_c.group(1).strip() if match_c else "Não Identificado"
            elif placa_atual and re.search(r"UNIDADE\s*/\s*SETOR:\s*(.+)", linha_limpa, re.IGNORECASE):
                setor_atual = re.search(r"UNIDADE\s*/\s*SETOR:\s*(.+)", linha_limpa, re.IGNORECASE).group(1).strip()
            elif "TOTAL VE" in linha_limpa.upper() and placa_atual:
                nums = re.findall(r"\d+(?:\.\d+)*(?:,\d+)?", linha_limpa)
                if len(nums) >= 2:
                    try:
                        m_n, a_n = mes_sugerido.split("/")
                        dados_gerais.append({
                            "Veículo (Placa e Modelo)": placa_atual, "Setor": setor_atual, "Combustível": comb_atual,
                            "Quantidade (L)": float(nums[-2].replace('.', '').replace(',', '.')),
                            "Valor Total (R$)": float(nums[-1].replace('.', '').replace(',', '.')),
                            "Mês/Ano Numérico": mes_sugerido, "Mês": str(m_n).zfill(2), "Ano": int(a_n)
                        })
                    except: pass
                placa_atual = None 
    return dados_gerais, list(meses_identificados)

# ==========================================
# 4. PORTAL DE LOGIN (TELA CENTRAL)
# ==========================================
if not st.session_state.autenticado:
    # Logo no topo da tela de login
    col_l1, col_l2, col_l3 = st.columns([1, 1, 1])
    with col_l2:
        try: st.image("logo.png", use_container_width=True)
        except: pass
    
    st.markdown("<h1 style='text-align: center;'>Gestão de Combustível</h1>", unsafe_allow_html=True)
    st.write("---")
    
    col_e1, col_form, col_e3 = st.columns([1, 2, 1])
    with col_form:
        st.markdown("<h3 style='text-align: center; color: #0C3C7A;'>🔒 Login Institucional</h3>", unsafe_allow_html=True)
        user_input = st.text_input("Usuário").strip()
        pass_input = st.text_input("Senha", type="password")
        lembrar = st.checkbox("Manter-me conectado neste computador")
        
        if st.button("Entrar no Sistema", use_container_width=True):
            perfil_encontrado = ""
            if "admin" in st.secrets and user_input in st.secrets["admin"] and st.secrets["admin"][user_input] == pass_input:
                perfil_encontrado = "admin"
            elif "viewer" in st.secrets and user_input in st.secrets["viewer"] and st.secrets["viewer"][user_input] == pass_input:
                perfil_encontrado = "viewer"
            
            if perfil_encontrado:
                st.session_state.autenticado = True
                st.session_state.usuario_logado = user_input
                st.session_state.nivel_acesso = perfil_encontrado
                
                if lembrar:
                    # Empacota os dados para salvar no navegador por 30 dias
                    pacote = json.dumps({"user": user_input, "nivel": perfil_encontrado})
                    validade = datetime.datetime.now() + datetime.timedelta(days=30)
                    cookie_manager.set("sessao_frota_jaborandi", pacote, expires_at=validade)
                    time.sleep(0.5) # Tempo físico para o navegador gravar
                st.rerun()
            else:
                st.error("Usuário ou senha incorretos.")
    st.stop()

# ==========================================
# 5. CONEXÃO E LEITURA DE DADOS (PÓS-LOGIN)
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
    else:
        df_db = pd.DataFrame(columns=["Ano", "Quantidade (L)", "Valor Total (R$)", "Mês/Ano Numérico"])
except:
    df_db = pd.DataFrame(columns=["Ano"])

# ==========================================
# 6. BARRA LATERAL (FILTROS E LOGOUT)
# ==========================================
with st.sidebar:
    # Logo e Identificação
    col_side1, col_side2, col_side3 = st.columns([1, 2, 1])
    with col_side2:
        try: st.image("logo.png", use_container_width=True)
        except: pass
    st.markdown("<div style='text-align: center; color: #0C3C7A; font-weight: 700; font-size: 14px; margin-bottom: 20px;'>Prefeitura Municipal<br>de Jaborandi/SP</div>", unsafe_allow_html=True)
    st.markdown("---")
    
    st.subheader("📊 Filtros Gerenciais")
    if not df_db.empty and len(df_db) > 0:
        anos_disponiveis = sorted(df_db["Ano"].unique().tolist(), reverse=True)
        ano_selecionado = st.selectbox("Escolha o Ano de Análise:", anos_disponiveis)
        df_ano = df_db[df_db["Ano"] == ano_selecionado]
        
        # Resumo no topo da lateral
        st.info(f"**Resumo Global {ano_selecionado}:**\n\n"
                f"Custo: **{formata_moeda(df_ano['Valor Total (R$)'].sum())}**\n\n"
                f"Consumo: **{formata_litro(df_ano['Quantidade (L)'].sum())}**")
    else:
        ano_selecionado = None
        df_ano = pd.DataFrame()

    st.markdown("---")
    st.write(f"✅ Conectado como: **{st.session_state.usuario_logado.capitalize()}**")
    st.caption(f"Perfil: {st.session_state.nivel_acesso.upper()}")
    
    if st.button("Sair do Sistema", use_container_width=True):
        cookie_manager.delete("sessao_frota_jaborandi")
        st.session_state.autenticado = False
        st.session_state.usuario_logado = ""
        st.session_state.nivel_acesso = ""
        time.sleep(0.5)
        st.rerun()

# ==========================================
# 7. ÁREA DE IMPORTAÇÃO (ADMIN)
# ==========================================
st.title("🏛️ Sistema de Gestão de Frota")

if st.session_state.nivel_acesso == "admin":
    with st.expander("📥 Importar Relatórios de Combustível (PDF)"):
        st.write("Selecione um ou mais arquivos PDF gerados pelo sistema de abastecimento.")
        arquivos_pdf = st.file_uploader("Upload de PDFs", type=["pdf"], accept_multiple_files=True, key=f"up_{st.session_state.uploader_key}")
        
        if arquivos_pdf:
            dados_extraidos, meses_lidos = extrair_dados_pdfs(arquivos_pdf)
            if dados_extraidos:
                df_novos = pd.DataFrame(dados_extraidos)
                st.success(f"Foram identificados dados dos meses: {', '.join(meses_lidos)}")
                
                if st.button("💾 Integrar Dados ao Banco na Nuvem"):
                    ja_salvos = df_db["Mês/Ano Numérico"].unique().tolist() if not df_db.empty else []
                    df_final_novos = df_novos[~df_novos["Mês/Ano Numérico"].isin(ja_salvos)]
                    
                    if not df_final_novos.empty:
                        df_consolidado = pd.concat([df_db, df_final_novos], ignore_index=True)
                        conn.update(worksheet="Dados", data=df_consolidado)
                        st.success("Dados salvos com sucesso!")
                        time.sleep(1)
                        st.session_state.uploader_key += 1
                        st.rerun()
                    else:
                        st.warning("Estes arquivos já foram importados anteriormente.")

st.write("---")

# ==========================================
# 8. DASHBOARD VISUAL
# ==========================================
if not df_ano.empty:
    aba1, aba2, aba3, aba4, aba5 = st.tabs(["📈 Evolução Geral", "🏢 Por Setor", "⛽ Por Combustível", "🚛 Por Veículo", "📅 Comparativo Anual"])
    
    ordem_meses = df_db["Mês/Ano Exibição"].unique().tolist()
    sufixo_key = f"_{ano_selecionado}"

    # --- ABA 1: GERAL ---
    with aba1:
        st.subheader(f"Desempenho Geral - {ano_selecionado}")
        resumo_mensal = df_ano.groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        col1, col2 = st.columns(2)
        with col1:
            fig1 = px.bar(resumo_mensal, x="Mês/Ano Exibição", y="Valor Total (R$)", text=resumo_mensal["Valor Total (R$)"].apply(formata_moeda), title="Custo Operacional Mensal (R$)", color_discrete_sequence=["#0C3C7A"], category_orders={"Mês/Ano Exibição": ordem_meses})
            st.plotly_chart(fig1, use_container_width=True, key=f"graf1{sufixo_key}")
        with col2:
            fig2 = px.bar(resumo_mensal, x="Mês/Ano Exibição", y="Quantidade (L)", text=resumo_mensal["Quantidade (L)"].apply(formata_litro), title="Volume Consumido (Litros)", color_discrete_sequence=["#4CAF50"], category_orders={"Mês/Ano Exibição": ordem_meses})
            st.plotly_chart(fig2, use_container_width=True, key=f"graf2{sufixo_key}")
        
        st.markdown("**Detalhamento dos Lançamentos Mensais**")
        st.dataframe(resumo_mensal[["Mês/Ano Exibição", "Quantidade (L)", "Valor Total (R$)"]], use_container_width=True)

    # --- ABA 2: SETOR ---
    with aba2:
        st.subheader("Análise por Secretaria/Setor")
        setor_lista = df_ano["Setor"].unique().tolist()
        setor_escolhido = st.selectbox("Selecione o Setor:", setor_lista)
        df_setor = df_ano[df_ano["Setor"] == setor_escolhido]
        resumo_setor = df_setor.groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.bar(resumo_setor, x="Mês/Ano Exibição", y="Valor Total (R$)", title="Gasto do Setor", color_discrete_sequence=["#0C3C7A"], category_orders={"Mês/Ano Exibição": ordem_meses}), use_container_width=True, key=f"graf3{sufixo_key}")
        c2.plotly_chart(px.bar(resumo_setor, x="Mês/Ano Exibição", y="Quantidade (L)", title="Litros do Setor", color_discrete_sequence=["#4CAF50"], category_orders={"Mês/Ano Exibição": ordem_meses}), use_container_width=True, key=f"graf4{sufixo_key}")

    # --- ABA 3: COMBUSTÍVEL ---
    with aba3:
        st.subheader("Consumo por Tipo de Combustível")
        comb_lista = df_ano["Combustível"].unique().tolist()
        comb_escolhido = st.selectbox("Selecione o Combustível:", comb_lista)
        df_comb = df_ano[df_ano["Combustível"] == comb_escolhido]
        resumo_comb = df_comb.groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.bar(resumo_comb, x="Mês/Ano Exibição", y="Valor Total (R$)", title="Gasto por Tipo", color_discrete_sequence=["#0C3C7A"]), use_container_width=True, key=f"graf5{sufixo_key}")
        c2.plotly_chart(px.bar(resumo_comb, x="Mês/Ano Exibição", y="Quantidade (L)", title="Volume por Tipo", color_discrete_sequence=["#4CAF50"]), use_container_width=True, key=f"graf6{sufixo_key}")

    # --- ABA 4: VEÍCULO ---
    with aba4:
        st.subheader("Evolução Individual por Veículo")
        veic_lista = sorted(df_ano["Veículo (Placa e Modelo)"].unique().tolist())
        veic_escolhido = st.selectbox("Selecione o Veículo:", veic_lista)
        df_veic = df_ano[df_ano["Veículo (Placa e Modelo)"] == veic_escolhido]
        resumo_veic = df_veic.groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.line(resumo_veic, x="Mês/Ano Exibição", y="Valor Total (R$)", markers=True, title="Curva de Gasto", color_discrete_sequence=["#0C3C7A"]), use_container_width=True, key=f"graf7{sufixo_key}")
        c2.plotly_chart(px.line(resumo_veic, x="Mês/Ano Exibição", y="Quantidade (L)", markers=True, title="Curva de Consumo", color_discrete_sequence=["#4CAF50"]), use_container_width=True, key=f"graf8{sufixo_key}")

    # --- ABA 5: COMPARATIVO ---
    with aba5:
        st.subheader("Comparativo Mensal entre Anos")
        mes_lista = df_db["Nome do Mês"].unique().tolist()
        mes_escolhido = st.selectbox("Selecione o Mês para Comparar:", mes_lista)
        df_comp = df_db[df_db["Nome do Mês"] == mes_escolhido]
        resumo_comp = df_comp.groupby("Ano")[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        resumo_comp["Ano"] = resumo_comp["Ano"].astype(str)
        
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.bar(resumo_comp, x="Ano", y="Valor Total (R$)", title=f"Gasto em {mes_escolhido}", color="Ano"), use_container_width=True, key=f"graf9{sufixo_key}")
        c2.plotly_chart(px.bar(resumo_comp, x="Ano", y="Quantidade (L)", title=f"Consumo em {mes_escolhido}", color="Ano"), use_container_width=True, key=f"graf10{sufixo_key}")

else:
    st.info("Aguardando carregamento de dados ou seleção de ano.")
