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

# Inicialização do Cookie Manager (Chave estável)
cookie_manager = stx.CookieManager(key="frota_jaborandi_vfinal_stable")

# --- TRAVA DE PERSISTÊNCIA (ANTI-F5) ---
# Se o navegador ainda não respondeu sobre os cookies, o Python espera.
# Isso garante que o "Manter Conectado" funcione sempre.
res_cookies = cookie_manager.get_all()
if res_cookies is None:
    st.stop()

if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
if "usuario_logado" not in st.session_state:
    st.session_state.usuario_logado = ""
if "nivel_acesso" not in st.session_state:
    st.session_state.nivel_acesso = ""
if "ignorar_cookie" not in st.session_state:
    st.session_state.ignorar_cookie = False

# Tenta recuperar a sessão via cookie se não estiver autenticado na aba atual
if not st.session_state.autenticado and not st.session_state.ignorar_cookie:
    pacote_json = cookie_manager.get(cookie="sessao_frota_jaborandi")
    if pacote_json:
        try:
            dados_sessao = json.loads(pacote_json)
            st.session_state.autenticado = True
            st.session_state.usuario_logado = dados_sessao["user"]
            st.session_state.nivel_acesso = dados_sessao["nivel"]
        except:
            pass

# Reseta a trava de logout após o primeiro ciclo
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

def formata_moeda(valor):
    return f"R$ {valor:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

def formata_litro(valor):
    return f"{valor:,.2f} L".replace(',', 'X').replace('.', ',').replace('X', '.')

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

@st.cache_data(show_spinner="Analisando PDFs...")
def extrair_dados_pdfs(arquivos):
    dados_gerais = []
    meses_id = set()
    for arquivo in arquivos:
        texto_completo = ""
        with pdfplumber.open(arquivo) as pdf:
            for pagina in pdf.pages:
                txt = pagina.extract_text(layout=True)
                if txt: texto_completo += txt + "\n"
        
        mes_sug = "00/0000" 
        match_p = re.search(r"Período:\s*De\s*(\d{2}/\d{2}/\d{4})", texto_completo)
        if match_p:
            mes_sug = match_p.group(1)[3:] 
            meses_id.add(mes_sug)
            
        linhas = texto_completo.split('\n')
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
                numeros = re.findall(r"\d+(?:\.\d+)*(?:,\d+)?", linha)
                if len(numeros) >= 2:
                    m_n, a_n = mes_sug.split("/")
                    dados_gerais.append({
                        "Veículo (Placa e Modelo)": placa, "Setor": setor, "Combustível": comb,
                        "Quantidade (L)": float(numeros[-2].replace('.', '').replace(',', '.')),
                        "Valor Total (R$)": float(numeros[-1].replace('.', '').replace(',', '.')),
                        "Mês/Ano Numérico": mes_sug, "Mês": str(m_n).zfill(2), "Ano": int(a_n)
                    })
                placa = None 
    return dados_gerais, list(meses_id)

# ==========================================
# 4. PORTAL DE LOGIN (COM LOGO AJUSTADO)
# ==========================================
if not st.session_state.autenticado:
    # Brasão em tamanho proporcional
    col_l1, col_l2, col_l3 = st.columns([2, 1, 2])
    with col_l2:
        try: st.image("logo.png", width=150)
        except: pass
    
    st.markdown("<h1 style='text-align: center;'>Gestão de Combustível</h1>", unsafe_allow_html=True)
    st.write("---")
    
    col_e1, col_form, col_e3 = st.columns([1, 1.5, 1])
    with col_form:
        st.markdown("<h3 style='text-align: center;'>🔒 Login Institucional</h3>", unsafe_allow_html=True)
        u_digitado = st.text_input("Usuário").strip()
        p_digitado = st.text_input("Senha", type="password")
        lembrar = st.checkbox("Manter-me conectado neste computador")
        
        if st.button("Entrar no Sistema"):
            perfil = ""
            if "admin" in st.secrets and u_digitado in st.secrets["admin"] and st.secrets["admin"][u_digitado] == p_digitado:
                perfil = "admin"
            elif "viewer" in st.secrets and u_digitado in st.secrets["viewer"] and st.secrets["viewer"][u_digitado] == p_digitado:
                perfil = "viewer"
            
            if perfil:
                st.session_state.autenticado = True
                st.session_state.usuario_logado = u_digitado
                st.session_state.nivel_acesso = perfil
                
                if lembrar:
                    pacote = json.dumps({"user": u_digitado, "nivel": perfil})
                    validade = datetime.datetime.now() + datetime.timedelta(days=30)
                    cookie_manager.set("sessao_frota_jaborandi", pacote, expires_at=validade)
                    time.sleep(0.5)
                st.rerun()
            else:
                st.error("Credenciais incorretas.")
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
        ano_sel = st.selectbox("Escolha o Ano:", lista_anos)
        df_ano = df_db[df_db["Ano"] == ano_sel]
        
        # Resumo Global no Topo
        st.info(f"**Totais de {ano_sel}:**\n\n💰 {formata_moeda(df_ano['Valor Total (R$)'].sum())}\n\n⛽ {formata_litro(df_ano['Quantidade (L)'].sum())}")
    else:
        ano_sel, df_ano = None, pd.DataFrame()

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
# 7. ÁREA PRINCIPAL
# ==========================================
st.title("🏛️ Gestão de Frota - Jaborandi/SP")

if st.session_state.nivel_acesso == "admin":
    with st.expander("📥 Importar Novos Relatórios (PDF)"):
        pdf_up = st.file_uploader("Upload de PDFs", type=["pdf"], accept_multiple_files=True)
        if pdf_up:
            d_ext, m_ext = extrair_dados_pdfs(pdf_up)
            if d_ext:
                df_novos = pd.DataFrame(d_ext)
                st.success(f"Identificados: {', '.join(m_ext)}")
                if st.button("💾 Confirmar e Salvar na Nuvem"):
                    ja_salvos = df_db["Mês/Ano Numérico"].unique().tolist() if not df_db.empty else []
                    df_final = df_novos[~df_novos["Mês/Ano Numérico"].isin(ja_salvos)]
                    if not df_final.empty:
                        conn.update(worksheet="Dados", data=pd.concat([df_db, df_final], ignore_index=True))
                        st.success("Dados integrados com sucesso!")
                        time.sleep(1); st.rerun()
                    else: st.warning("Dados já existem no banco.")

st.write("---")

# ==========================================
# 8. DASHBOARD COM TABELAS DE RESUMO
# ==========================================
if not df_ano.empty:
    aba1, aba2, aba3, aba4, aba5 = st.tabs(["📈 Geral", "🏢 Setor", "⛽ Combustível", "🚛 Veículo", "📅 Comparativo"])
    ordem_cron = df_db["Mês/Ano Exibição"].unique().tolist()
    sufix = f"_{ano_sel}"

    with aba1:
        res_g = df_ano.groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.bar(res_g, x="Mês/Ano Exibição", y="Valor Total (R$)", text=res_g["Valor Total (R$)"].apply(formata_moeda), title="Custo Mensal", color_discrete_sequence=["#0C3C7A"], category_orders={"Mês/Ano Exibição": ordem_cron}), use_container_width=True, key=f"g1{sufix}")
        c2.plotly_chart(px.bar(res_g, x="Mês/Ano Exibição", y="Quantidade (L)", text=res_g["Quantidade (L)"].apply(formata_litro), title="Volume Mensal", color_discrete_sequence=["#4CAF50"], category_orders={"Mês/Ano Exibição": ordem_cron}), use_container_width=True, key=f"g2{sufix}")
        
        st.write("**Detalhamento dos Valores Mensais:**")
        st.dataframe(formatar_tabela_exibicao(res_g), use_container_width=True, hide_index=True)

    with aba2:
        setores = df_ano["Setor"].unique().tolist()
        sel_s = st.selectbox("Selecione a Secretaria/Setor:", setores)
        df_s = df_ano[df_ano["Setor"] == sel_s].groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.bar(df_s, x="Mês/Ano Exibição", y="Valor Total (R$)", title=f"Gasto: {sel_s}", color_discrete_sequence=["#0C3C7A"], category_orders={"Mês/Ano Exibição": ordem_cron}), use_container_width=True, key=f"g3{sufix}")
        c2.plotly_chart(px.bar(df_s, x="Mês/Ano Exibição", y="Quantidade (L)", title=f"Consumo: {sel_s}", color_discrete_sequence=["#4CAF50"], category_orders={"Mês/Ano Exibição": ordem_cron}), use_container_width=True, key=f"g4{sufix}")
        
        st.write(f"**Tabela de Dados: {sel_s}**")
        st.dataframe(formatar_tabela_exibicao(df_s), use_container_width=True, hide_index=True)

    with aba3:
        combs = df_ano["Combustível"].unique().tolist()
        sel_c = st.selectbox("Selecione o Combustível:", combs)
        df_c = df_ano[df_ano["Combustível"] == sel_c].groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.bar(df_c, x="Mês/Ano Exibição", y="Valor Total (R$)", title=f"Custo com {sel_c}", color_discrete_sequence=["#0C3C7A"]), use_container_width=True, key=f"g5{sufix}")
        c2.plotly_chart(px.bar(df_c, x="Mês/Ano Exibição", y="Quantidade (L)", title=f"Volume de {sel_c}", color_discrete_sequence=["#4CAF50"]), use_container_width=True, key=f"g6{sufix}")
        st.dataframe(formatar_tabela_exibicao(df_c), use_container_width=True, hide_index=True)

    with aba4:
        veiculos = sorted(df_ano["Veículo (Placa e Modelo)"].unique().tolist())
        sel_v = st.selectbox("Escolha o Veículo:", veiculos)
        df_v = df_ano[df_ano["Veículo (Placa e Modelo)"] == sel_v].groupby("Mês/Ano Exibição", sort=False)[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.line(df_v, x="Mês/Ano Exibição", y="Valor Total (R$)", markers=True, title=f"Curva de Custo: {sel_v}"), use_container_width=True, key=f"g7{sufix}")
        c2.plotly_chart(px.line(df_v, x="Mês/Ano Exibição", y="Quantidade (L)", markers=True, title=f"Curva de Volume: {sel_v}"), use_container_width=True, key=f"g8{sufix}")
        st.dataframe(formatar_tabela_exibicao(df_v), use_container_width=True, hide_index=True)

    with aba5:
        meses_disp = df_db["Nome do Mês"].unique().tolist()
        sel_m = st.selectbox("Comparar qual mês entre anos?", meses_disp)
        df_cp = df_db[df_db["Nome do Mês"] == sel_m].groupby("Ano")[["Valor Total (R$)", "Quantidade (L)"]].sum().reset_index()
        df_cp["Ano"] = df_cp["Ano"].astype(str)
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.bar(df_cp, x="Ano", y="Valor Total (R$)", title=f"Financeiro ({sel_m})", color="Ano"), use_container_width=True, key=f"g9{sufix}")
        c2.plotly_chart(px.bar(df_cp, x="Ano", y="Quantidade (L)", title=f"Volume ({sel_m})", color="Ano"), use_container_width=True, key=f"g10{sufix}")
        st.dataframe(formatar_tabela_exibicao(df_cp), use_container_width=True, hide_index=True)

else: st.info("Selecione um ano válido para carregar as análises.")
