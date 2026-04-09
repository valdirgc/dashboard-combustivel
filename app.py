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

# Gerenciador de Cookies
cookie_manager = stx.CookieManager(key="frota_jaborandi_vfinal_fix")

# --- TRAVA DE PERSISTÊNCIA (O SEGREDO DO F5) ---
# Se o navegador ainda não respondeu sobre os cookies, o sistema aguarda.
if "cookies_verificados" not in st.session_state:
    time.sleep(0.7) # Tempo essencial para o navegador entregar os cookies
    st.session_state.cookies_verificados = True
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

# --- LÓGICA DE RECUPERAÇÃO AUTOMÁTICA ---
if not st.session_state.autenticado and not st.session_state.ignorar_cookie:
    sessao = cookie_manager.get(cookie="sessao_frota_jaborandi")
    if sessao:
        try:
            dados_sessao = json.loads(sessao)
            st.session_state.autenticado = True
            st.session_state.usuario_logado = dados_sessao["user"]
            st.session_state.nivel_acesso = dados_sessao["nivel"]
        except:
            pass

if st.session_state.ignorar_cookie:
    st.session_state.ignorar_cookie = False

# ==========================================
# 2. CUSTOMIZAÇÃO VISUAL (CSS PARA CENTRALIZAR)
# ==========================================
st.markdown(f"""
<style>
    .block-container {{ padding-top: 2rem; }}
    h1, h2, h3 {{ color: #0C3C7A; font-family: 'Segoe UI', sans-serif; font-weight: 700; }}
    
    /* Botão Estilizado */
    .stButton>button {{
        background-color: #0C3C7A; color: white; border-radius: 8px; 
        border: none; padding: 0.5rem 1rem; transition: all 0.3s ease; font-weight: 600;
        width: 100%;
    }}
    .stButton>button:hover {{ background-color: #082954; transform: translateY(-2px); }}
    
    /* Metric Card */
    div[data-testid="stMetricValue"] {{ color: #0C3C7A; font-weight: 800; }}
    
    /* Tabs */
    .stTabs [aria-selected="true"] {{ background-color: #E8F0FE; border-bottom: 4px solid #0C3C7A !important; color: #0C3C7A !important; font-weight: 800; }}
    
    /* Sidebar */
    [data-testid="stSidebar"] {{ background-color: #F8F9FA; border-right: 1px solid #DEE2E6; }}
</style>
""", unsafe_allow_html=True)

# ==========================================
# 3. FUNÇÕES DE TRADUÇÃO E FORMATAÇÃO
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

def formatar_tabela_para_exibir(df_original):
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

@st.cache_data(show_spinner="Analisando relatórios...")
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
                match_combustivel = re.search(r"ESP[ÉE]CIE:\s*([A-Z]+)", linha_limpa, re.IGNORECASE)
                combustivel_atual = match_combustivel.group(1).strip() if match_combustivel else "Não Identificado"
            elif placa_atual and re.search(r"UNIDADE\s*/\s*SETOR:\s*(.+)", linha_limpa, re.IGNORECASE):
                setor_atual = re.search(r"UNIDADE\s*/\s*SETOR:\s*(.+)", linha_limpa, re.IGNORECASE).group(1).strip()
            elif "TOTAL VE" in linha_limpa.upper() and placa_atual:
                numeros = re.findall(r"\d+(?:\.\d+)*(?:,\d+)?", linha_limpa)
                if len(numeros) >= 2:
                    try:
                        m_num, a_num = mes_sugerido.split("/")
                        dados_gerais.append({
                            "Veículo (Placa e Modelo)": placa_atual, "Setor": setor_atual, "Combustível": combustivel_atual,
                            "Quantidade (L)": float(numeros[-2].replace('.', '').replace(',', '.')),
                            "Valor Total (R$)": float(numeros[-1].replace('.', '').replace(',', '.')),
                            "Mês/Ano Numérico": mes_sugerido, "Mês": str(m_num).zfill(2), "Ano": int(a_num)
                        })
                    except: pass
                placa_atual = None 
    return dados_gerais, list(meses_identificados)

# ==========================================
# 4. TELA DE LOGIN CENTRALIZADA
# ==========================================
if not st.session_state.autenticado:
    # Centraliza o logo e o formulário
    col_l1, col_l2, col_l3 = st.columns([2, 1, 2])
    with col_l2:
        try: st.image("logo.png", width=150)
        except: pass
    
    st.markdown("<h1 style='text-align: center;'>Gestão de Combustível</h1>", unsafe_allow_html=True)
    st.write("---")
    
    col_f1, col_f2, col_f3 = st.columns([1, 1.5, 1])
    with col_f2:
        st.markdown("<h3 style='text-align: center; color: #0C3C7A;'>🔒 Acesso ao Sistema</h3>", unsafe_allow_html=True)
        u_digitado = st.text_input("Usuário").strip()
        p_digitada = st.text_input("Senha", type="password")
        lembrar = st.checkbox("Manter-me conectado neste computador")
        
        if st.button("Entrar no Sistema"):
            perfil = ""
            if "admin" in st.secrets and u_digitado in st.secrets["admin"] and st.secrets["admin"][u_digitado] == p_digitada:
                perfil = "admin"
            elif "viewer" in st.secrets and u_digitado in st.secrets["viewer"] and st.secrets["viewer"][u_digitado] == p_digitada:
                perfil = "viewer"
            
            if perfil:
                st.session_state.autenticado = True
                st.session_state.usuario_logado = u_digitado
                st.session_state.nivel_acesso = perfil
                
                if lembrar:
                    pacote = json.dumps({"user": u_digitado, "nivel": perfil})
                    expira = datetime.datetime.now() + datetime.timedelta(days=30)
                    cookie_manager.set("sessao_frota_jaborandi", pacote, expires_at=expira)
                    time.sleep(0.5)
                st.rerun()
            else:
                st.error("Usuário ou senha inválidos.")
    st.stop()

# ==========================================
# 5. CARREGAMENTO DO BANCO DE DADOS
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
        df_db = pd.DataFrame(columns=["Ano", "Quantidade (L)", "Valor Total (R$)", "Mês/Ano Numérico", "Mês/Ano Exibição"])
        ordem_cronologica = []
except Exception as e:
    st.error(f"Erro ao carregar banco: {e}")
    df_db = pd.DataFrame()

# ==========================================
# 6. BARRA LATERAL (FILTROS E RESUMO NO TOPO)
# ==========================================
with st.sidebar:
    st.subheader("📊 Filtros e Resumo")
    if not df_db.empty and len(df_db) > 0:
        anos_disp = sorted(df_db["Ano"].unique().tolist(), reverse=True)
        ano_escolhido = st.selectbox("Selecione o Ano:", anos_disp)
        df_ano = df_db[df_db["Ano"] == ano_escolhido]
        
        st.info(f"**Resumo Global {ano_escolhido}:**\n\n"
                f"Custo: **{formata_moeda(df_ano['Valor Total (R$)'].sum())}**\n\n"
                f"Volume: **{formata_litro(df_ano['Quantidade (L)'].sum())}**")
    else:
        ano_escolhido, df_ano = None, pd.DataFrame()

    st.markdown("---")
    st.write(f"✅ Logado: **{st.session_state.usuario_logado.capitalize()}**")
    if st.button("Sair do Sistema"):
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
        files_up = st.file_uploader("Selecione os PDFs", type=["pdf"], accept_multiple_files=True)
        if files_up:
            dados_lidos, meses_lidos = extrair_dados_pdfs(files_up)
            if dados_lidos:
                df_novos = pd.DataFrame(dados_lidos)
                st.success(f"Identificados meses: {', '.join(meses_lidos)}")
                if st.button("💾 Salvar Dados na Nuvem"):
                    ja_salvos = df_db["Mês/Ano Numérico"].unique().tolist() if not df_db.empty else []
                    df_filtrado = df_novos[~df_novos["Mês/Ano Numérico"].isin(ja_salvos)]
                    if not df_filtrado.empty:
                        df_final = pd.concat([df_db, df_filtrado], ignore_index=True)
                        conn.update(worksheet="Dados", data=df_final)
                        st.success("Dados integrados!")
                        time.sleep(1); st.rerun()
                    else: st.error("Esses meses já existem no banco de dados.")

st.write("---")

# ==========================================
# 8. DASHBOARD (COM TABELAS RESTAURADAS)
# ==========================================
if not df_ano.empty:
    aba1, aba2, aba3, aba4, aba5 = st.tabs(["📊 Geral", "🏢 Setor", "⛽ Combustível", "🚛 Veículo", "📅 Comparativo"])
    s_key = f"_{ano_escolhido}"

    # --- ABA 1: GERAL ---
    with aba1:
        st.subheader(f"Evolução Total - {ano_escolhido}")
        res_geral = df_ano.groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        res_geral["TXT_V"] = res_geral["Valor Total (R$)"].apply(formata_moeda)
        res_geral["TXT_L"] = res_geral["Quantidade (L)"].apply(formata_litro)
        
        c1, c2 = st.columns(2)
        with c1:
            fig1 = px.bar(res_geral, x="Mês/Ano Exibição", y="Valor Total (R$)", text="TXT_V", title="Custo Mensal", color_discrete_sequence=["#0C3C7A"], category_orders={"Mês/Ano Exibição": ordem_cronologica})
            st.plotly_chart(fig1, use_container_width=True, key=f"g1{s_key}")
        with c2:
            fig2 = px.bar(res_geral, x="Mês/Ano Exibição", y="Quantidade (L)", text="TXT_L", title="Volume Mensal", color_discrete_sequence=["#4CAF50"], category_orders={"Mês/Ano Exibição": ordem_cronologica})
            st.plotly_chart(fig2, use_container_width=True, key=f"g2{s_key}")
            
        st.write("**Detalhamento dos Dados Mensais:**")
        st.dataframe(formatar_tabela_para_exibir(res_geral[["Mês/Ano Exibição", "Quantidade (L)", "Valor Total (R$)"]]), use_container_width=True, hide_index=True)

    # --- ABA 2: POR SETOR ---
    with aba2:
        setores = sorted(df_ano["Setor"].unique().tolist())
        sel_setor = st.selectbox("Selecione o Setor/Secretaria:", setores)
        df_set = df_ano[df_ano["Setor"] == sel_setor]
        res_set = df_set.groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        res_set["TXT_V"] = res_set["Valor Total (R$)"].apply(formata_moeda)
        res_set["TXT_L"] = res_set["Quantidade (L)"].apply(formata_litro)
        
        c1, c2 = st.columns(2)
        with c1:
            fig3 = px.bar(res_set, x="Mês/Ano Exibição", y="Valor Total (R$)", text="TXT_V", title=f"Custo: {sel_setor}", color_discrete_sequence=["#0C3C7A"], category_orders={"Mês/Ano Exibição": ordem_cronologica})
            st.plotly_chart(fig3, use_container_width=True, key=f"g3{s_key}")
        with c2:
            fig4 = px.bar(res_set, x="Mês/Ano Exibição", y="Quantidade (L)", text="TXT_L", title=f"Volume: {sel_setor}", color_discrete_sequence=["#4CAF50"], category_orders={"Mês/Ano Exibição": ordem_cronologica})
            st.plotly_chart(fig4, use_container_width=True, key=f"g4{s_key}")
        
        st.write(f"**Tabela Resumo - {sel_setor}:**")
        st.dataframe(formatar_tabela_para_exibir(res_set[["Mês/Ano Exibição", "Quantidade (L)", "Valor Total (R$)"]]), use_container_width=True, hide_index=True)

    # --- ABA 3: COMBUSTÍVEL ---
    with aba3:
        combs = df_ano["Combustível"].unique().tolist()
        sel_comb = st.selectbox("Selecione o Combustível:", combs)
        df_c = df_ano[df_ano["Combustível"] == sel_comb]
        res_c = df_c.groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        res_c["TXT_V"] = res_c["Valor Total (R$)"].apply(formata_moeda)
        res_c["TXT_L"] = res_c["Quantidade (L)"].apply(formata_litro)
        
        c1, c2 = st.columns(2)
        with c1:
            fig5 = px.bar(res_c, x="Mês/Ano Exibição", y="Valor Total (R$)", text="TXT_V", title=f"Gasto com {sel_comb}", color_discrete_sequence=["#0C3C7A"], category_orders={"Mês/Ano Exibição": ordem_cronologica})
            st.plotly_chart(fig5, use_container_width=True, key=f"g5{s_key}")
        with c2:
            fig6 = px.bar(res_c, x="Mês/Ano Exibição", y="Quantidade (L)", text="TXT_L", title=f"Consumo de {sel_comb}", color_discrete_sequence=["#4CAF50"], category_orders={"Mês/Ano Exibição": ordem_cronologica})
            st.plotly_chart(fig6, use_container_width=True, key=f"g6{s_key}")
        
        st.write(f"**Tabela de Consumo - {sel_comb}:**")
        st.dataframe(formatar_tabela_para_exibir(res_c[["Mês/Ano Exibição", "Quantidade (L)", "Valor Total (R$)"]]), use_container_width=True, hide_index=True)

    # --- ABA 4: POR VEÍCULO ---
    with aba4:
        veiculos = sorted(df_ano["Veículo (Placa e Modelo)"].unique().tolist())
        sel_veic = st.selectbox("Escolha o Veículo:", veiculos)
        df_v = df_ano[df_ano["Veículo (Placa e Modelo)"] == sel_veic]
        res_v = df_v.groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        res_v["TXT_V"] = res_v["Valor Total (R$)"].apply(formata_moeda)
        res_v["TXT_L"] = res_v["Quantidade (L)"].apply(formata_litro)
        
        c1, c2 = st.columns(2)
        with c1:
            fig7 = px.line(res_v, x="Mês/Ano Exibição", y="Valor Total (R$)", text="TXT_V", markers=True, title=f"Gasto: {sel_veic}", color_discrete_sequence=["#0C3C7A"], category_orders={"Mês/Ano Exibição": ordem_cronologica})
            st.plotly_chart(fig7, use_container_width=True, key=f"g7{s_key}")
        with c2:
            fig8 = px.line(res_v, x="Mês/Ano Exibição", y="Quantidade (L)", text="TXT_L", markers=True, title=f"Consumo: {sel_veic}", color_discrete_sequence=["#4CAF50"], category_orders={"Mês/Ano Exibição": ordem_cronologica})
            st.plotly_chart(fig8, use_container_width=True, key=f"g8{s_key}")
        
        st.write(f"**Histórico Individual - {sel_veic}:**")
        st.dataframe(formatar_tabela_para_exibir(res_v[["Mês/Ano Exibição", "Quantidade (L)", "Valor Total (R$)"]]), use_container_width=True, hide_index=True)

    # --- ABA 5: COMPARATIVO ---
    with aba5:
        meses_disp = sorted(df_db["Nome do Mês"].unique().tolist())
        sel_mes = st.selectbox("Mês para comparação:", meses_disp)
        df_comp = df_db[df_db["Nome do Mês"] == sel_mes]
        res_comp = df_comp.groupby("Ano")[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        res_comp["Ano"] = res_comp["Ano"].astype(str)
        res_comp["TXT_V"] = res_comp["Valor Total (R$)"].apply(formata_moeda)
        res_comp["TXT_L"] = res_comp["Quantidade (L)"].apply(formata_litro)
        
        c1, c2 = st.columns(2)
        with c1:
            fig9 = px.bar(res_comp, x="Ano", y="Valor Total (R$)", text="TXT_V", title=f"Financeiro em {sel_mes}", color="Ano")
            st.plotly_chart(fig9, use_container_width=True, key=f"g9{s_key}")
        with c2:
            fig10 = px.bar(res_comp, x="Ano", y="Quantidade (L)", text="TXT_L", title=f"Consumo em {sel_mes}", color="Ano")
            st.plotly_chart(fig10, use_container_width=True, key=f"g10{s_key}")
        
        st.write(f"**Dados Históricos - {sel_mes}:**")
        st.dataframe(formatar_tabela_para_exibir(res_comp[["Ano", "Quantidade (L)", "Valor Total (R$)"]]), use_container_width=True, hide_index=True)

else:
    st.info("Selecione um ano para carregar o Dashboard.")
