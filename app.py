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
cookie_manager = stx.CookieManager(key="cookie_manager_frota_v3")

# --- TRAVA DE SINCRONIA (Essencial para manter logado) ---
# O sistema espera o componente carregar. Se não carregar em 1s, ele continua.
if "cookies_carregados" not in st.session_state:
    time.sleep(0.5) # Pequena pausa física para o navegador "falar" com o Python
    st.session_state.cookies_carregados = True
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

# --- LÓGICA DE RECUPERAÇÃO DE ACESSO (MANTER LOGADO) ---
if not st.session_state.autenticado and not st.session_state.ignorar_cookie:
    sessao_salva = cookie_manager.get(cookie="sessao_frota_jaborandi")
    if sessao_salva:
        try:
            # sessao_salva vem como uma String JSON, vamos abrir o pacote
            dados_sessao = json.loads(sessao_salva)
            st.session_state.autenticado = True
            st.session_state.usuario_logado = dados_sessao["user"]
            st.session_state.nivel_acesso = dados_sessao["nivel"]
        except:
            pass

# Reseta a flag de ignorar após o primeiro carregamento pós-logout
if st.session_state.ignorar_cookie:
    st.session_state.ignorar_cookie = False

# ==========================================
# 2. CUSTOMIZAÇÃO VISUAL (TEMA PREFEITURA)
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
# 3. FUNÇÕES AUXILIARES
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

@st.cache_data(show_spinner="Extraindo dados do PDF...")
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
                    m_n, a_n = mes_sugerido.split("/")
                    dados_gerais.append({
                        "Veículo (Placa e Modelo)": placa_atual, "Setor": setor_atual, "Combustível": comb_atual,
                        "Quantidade (L)": float(nums[-2].replace('.', '').replace(',', '.')),
                        "Valor Total (R$)": float(nums[-1].replace('.', '').replace(',', '.')),
                        "Mês/Ano Numérico": mes_sugerido, "Mês": str(m_n).zfill(2), "Ano": int(a_n)
                    })
                placa_atual = None 
    return dados_gerais, list(meses_identificados)

# ==========================================
# 4. BARRA LATERAL (LOGO E LOGIN)
# ==========================================
with st.sidebar:
    col_img1, col_img2, col_img3 = st.columns([1, 2, 1])
    with col_img2:
        try: st.image("logo.png", use_container_width=True)
        except: pass
    st.markdown("<div style='text-align: center; color: #0C3C7A; font-weight: 700; font-size: 16px; margin-bottom: 10px;'>Prefeitura Municipal<br>de Jaborandi/SP</div>", unsafe_allow_html=True)
    st.markdown("---")

# Se não estiver logado, mostra o portal central e para
if not st.session_state.autenticado:
    st.title("🏛️ Sistema de Gestão de Combustível")
    st.write("---")
    c_e1, col_login, c_e3 = st.columns([1, 2, 1])
    with col_login:
        st.markdown("<h3 style='text-align: center;'>🔒 Acesso Restrito</h3>", unsafe_allow_html=True)
        user_input = st.text_input("Usuário").strip()
        pass_input = st.text_input("Senha", type="password")
        keep_logged = st.checkbox("Manter-me conectado")
        
        if st.button("Entrar", use_container_width=True):
            perfil = ""
            if "admin" in st.secrets and user_input in st.secrets["admin"] and st.secrets["admin"][user_input] == pass_input:
                perfil = "admin"
            elif "viewer" in st.secrets and user_input in st.secrets["viewer"] and st.secrets["viewer"][user_input] == pass_input:
                perfil = "viewer"
            
            if perfil:
                st.session_state.autenticado = True
                st.session_state.usuario_logado = user_input
                st.session_state.nivel_acesso = perfil
                if keep_logged:
                    dados_p = json.dumps({"user": user_input, "nivel": perfil})
                    expira = datetime.datetime.now() + datetime.timedelta(days=30)
                    cookie_manager.set("sessao_frota_jaborandi", dados_p, expires_at=expira)
                    time.sleep(0.5)
                st.rerun()
            else:
                st.error("Credenciais inválidas.")
    st.stop()

# ==========================================
# 5. BANCO DE DADOS (SÓ RODA PÓS-LOGIN)
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
        df_db = pd.DataFrame(columns=["Ano", "Quantidade (L)", "Valor Total (R$)"])
except:
    df_db = pd.DataFrame(columns=["Ano"])

# ==========================================
# 6. BARRA LATERAL (FILTROS E RESUMO NO TOPO)
# ==========================================
with st.sidebar:
    st.subheader("📊 Filtros e Resumo")
    if not df_db.empty and len(df_db) > 0:
        anos_lista = sorted(df_db["Ano"].unique().tolist(), reverse=True)
        ano_selecionado = st.selectbox("Selecione o Ano:", anos_lista)
        df_ano = df_db[df_db["Ano"] == ano_selecionado]
        
        st.info(f"**Totais de {ano_selecionado}:**\n\n💰 {formata_moeda(df_ano['Valor Total (R$)'].sum())}\n\n⛽ {formata_litro(df_ano['Quantidade (L)'].sum())}")
    else:
        ano_selecionado = None
        df_ano = pd.DataFrame()

    st.markdown("---")
    st.write(f"👤 **{st.session_state.usuario_logado.capitalize()}** ({st.session_state.nivel_acesso})")
    if st.button("Sair do Sistema", use_container_width=True):
        cookie_manager.delete("sessao_frota_jaborandi")
        st.session_state.autenticado = False
        st.session_state.ignorar_cookie = True
        time.sleep(0.5)
        st.rerun()

# ==========================================
# 7. ÁREA PRINCIPAL
# ==========================================
st.title("🏛️ Gestão de Frota")

if st.session_state.nivel_acesso == "admin":
    with st.expander("📥 Importar Relatórios Mensais (PDF)"):
        pdf_files = st.file_uploader("Arraste os PDFs aqui", type=["pdf"], accept_multiple_files=True, key=f"up_{st.session_state.uploader_key}")
        if pdf_files:
            extraidos, meses_lidos = extrair_dados_pdfs(pdf_files)
            if extraidos:
                df_novos = pd.DataFrame(extraidos)
                st.success(f"Identificados: {', '.join(meses_lidos)}")
                if st.button("💾 Salvar no Banco de Dados"):
                    ja_salvos = df_db["Mês/Ano Numérico"].unique().tolist() if not df_db.empty else []
                    df_filtrado = df_novos[~df_novos["Mês/Ano Numérico"].isin(ja_salvos)]
                    if not df_filtrado.empty:
                        df_final = pd.concat([df_db, df_filtrado], ignore_index=True)
                        conn.update(worksheet="Dados", data=df_final)
                        st.success("Dados integrados!")
                        time.sleep(1)
                        st.session_state.uploader_key += 1
                        st.rerun()
                    else: st.error("Estes meses já constam no sistema.")

st.write("---")

# ==========================================
# 8. DASHBOARD
# ==========================================
if not df_ano.empty:
    t1, t2, t3, t4, t5 = st.tabs(["📊 Geral", "🏢 Setor", "⛽ Combustível", "🚛 Veículo", "📅 Comparativo"])
    ordem = df_db["Mês/Ano Exibição"].unique().tolist()
    suf = f"_{ano_selecionado}"

    with t1:
        res = df_ano.groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.bar(res, x="Mês/Ano Exibição", y="Valor Total (R$)", text=res["Valor Total (R$)"].apply(formata_moeda), title="Custo Mensal", color_discrete_sequence=["#0C3C7A"], category_orders={"Mês/Ano Exibição": ordem}), use_container_width=True, key=f"g1{suf}")
        c2.plotly_chart(px.bar(res, x="Mês/Ano Exibição", y="Quantidade (L)", text=res["Quantidade (L)"].apply(formata_litro), title="Volume Mensal", color_discrete_sequence=["#4CAF50"], category_orders={"Mês/Ano Exibição": ordem}), use_container_width=True, key=f"g2{suf}")
        st.dataframe(res[["Mês/Ano Exibição", "Quantidade (L)", "Valor Total (R$)"]], use_container_width=True)

    with t2:
        sel_setor = st.selectbox("Escolha o Setor:", df_ano["Setor"].unique())
        res_s = df_ano[df_ano["Setor"] == sel_setor].groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.bar(res_s, x="Mês/Ano Exibição", y="Valor Total (R$)", title="Custo por Setor", color_discrete_sequence=["#0C3C7A"], category_orders={"Mês/Ano Exibição": ordem}), use_container_width=True, key=f"g3{suf}")
        c2.plotly_chart(px.bar(res_s, x="Mês/Ano Exibição", y="Quantidade (L)", title="Volume por Setor", color_discrete_sequence=["#4CAF50"], category_orders={"Mês/Ano Exibição": ordem}), use_container_width=True, key=f"g4{suf}")

    with t3:
        sel_comb = st.selectbox("Escolha o Combustível:", df_ano["Combustível"].unique())
        res_c = df_ano[df_ano["Combustível"] == sel_comb].groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.bar(res_c, x="Mês/Ano Exibição", y="Valor Total (R$)", title="Custo Combustível", color_discrete_sequence=["#0C3C7A"]), use_container_width=True, key=f"g5{suf}")
        c2.plotly_chart(px.bar(res_c, x="Mês/Ano Exibição", y="Quantidade (L)", title="Volume Combustível", color_discrete_sequence=["#4CAF50"]), use_container_width=True, key=f"g6{suf}")

    with t4:
        sel_veic = st.selectbox("Escolha o Veículo:", sorted(df_ano["Veículo (Placa e Modelo)"].unique()))
        res_v = df_ano[df_ano["Veículo (Placa e Modelo)"] == sel_veic].groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.line(res_v, x="Mês/Ano Exibição", y="Valor Total (R$)", markers=True, title="Curva Financeira"), use_container_width=True, key=f"g7{suf}")
        c2.plotly_chart(px.line(res_v, x="Mês/Ano Exibição", y="Quantidade (L)", markers=True, title="Curva de Consumo"), use_container_width=True, key=f"g8{suf}")

    with t5:
        sel_mes = st.selectbox("Comparar qual mês?", df_db["Nome do Mês"].unique())
        res_comp = df_db[df_db["Nome do Mês"] == sel_mes].groupby("Ano")[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.bar(res_comp, x="Ano", y="Valor Total (R$)", title=f"Variação de {sel_mes}", color="Ano"), use_container_width=True, key=f"g9{suf}")
        c2.plotly_chart(px.bar(res_comp, x="Ano", y="Quantidade (L)", title=f"Consumo de {sel_mes}", color="Ano"), use_container_width=True, key=f"g10{suf}")

else: st.info("Nenhum dado encontrado para o ano selecionado.")
