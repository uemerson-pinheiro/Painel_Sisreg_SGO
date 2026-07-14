"""
Painel SISREG - Regulação Ambulatorial
Identidade visual: paleta SISREG (Verde #00D000, Amarelo #FFD000,
Azul #183EFF, Vermelho #FF0000, Cinza #3C3C3C)
"""

from __future__ import annotations

import re
import glob
from pathlib import Path
from datetime import date, datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ─────────────────────────────────────────────
# CONFIGURAÇÃO
# ─────────────────────────────────────────────
PASTA = Path(__file__).parent

CORES = {
    "verde":       "#00D000",
    "amarelo":     "#FFD000",
    "azul":        "#183EFF",
    "vermelho":    "#FF0000",
    "cinza":       "#3C3C3C",
    "cinza_claro": "#F0F2F6",
    "branco":      "#FFFFFF",
}

SEQ_CORES = [
    CORES["azul"], CORES["verde"], CORES["amarelo"],
    CORES["vermelho"], CORES["cinza"], "#8B5CF6", "#06B6D4", "#F97316",
]

MESES_PT = {
    1: "janeiro", 2: "fevereiro", 3: "marco",     4: "abril",
    5: "maio",    6: "junho",     7: "julho",      8: "agosto",
    9: "setembro",10: "outubro",  11: "novembro",  12: "dezembro",
}
MESES_NUM = {v.lower(): k for k, v in MESES_PT.items()}


# ─────────────────────────────────────────────
# CARREGAMENTO DE DADOS
# ─────────────────────────────────────────────

@st.cache_data(show_spinner="Carregando agendamentos...")
def carregar_agendamentos() -> pd.DataFrame:
    arquivos = glob.glob(str(PASTA / "Agendamento" / "**" / "*.csv"), recursive=True)
    partes = []

    for arq in arquivos:
        p = Path(arq)
        # extrai estabelecimento do nome do arquivo: "NOME ESTAB-YYYYMMDD.csv"
        nome_base = p.stem
        match = re.match(r"^(.+?)-\d{8}$", nome_base)
        estabelecimento = match.group(1).strip() if match else nome_base

        # mês e ano da pasta
        try:
            mes_pasta = p.parent.name.lower()
            ano_pasta = int(p.parent.parent.name)
            mes_num = MESES_NUM.get(mes_pasta, 0)
        except Exception:
            mes_num, ano_pasta = 0, 0

        try:
            df = pd.read_csv(arq, sep=";", encoding="utf-8", on_bad_lines="skip", low_memory=False)
            if df.empty or len(df.columns) < 5:
                continue
            df["estabelecimento_executor"] = estabelecimento
            df["mes_pasta"]  = mes_num
            df["ano_pasta"]  = ano_pasta
            partes.append(df)
        except Exception:
            continue

    if not partes:
        return pd.DataFrame()

    df = pd.concat(partes, ignore_index=True)

    # datas
    for col in ("data_agendamento", "data_solicitacao", "data_autorizacao"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce", format="mixed")

    # coluna de absenteísmo (para agendamentos PASSADOS)
    hoje = pd.Timestamp(date.today())
    if "data_agendamento" in df.columns:
        df["passado"] = df["data_agendamento"] < hoje
        df["ausente"] = df["passado"] & (df.get("situacao", pd.Series()) == "PENDENTE")
        df["compareceu"] = df["passado"] & (df.get("situacao", pd.Series()) == "CONFIRMADO")

    # tipo label
    if "tipo" in df.columns:
        df["tipo_label"] = df["tipo"].map({0: "Primeira Vez", 1: "Retorno"}).fillna("Outro")

    return df


@st.cache_data(show_spinner="Carregando demanda reprimida...")
def carregar_demanda_reprimida() -> dict[str, pd.DataFrame]:
    resultado: dict[str, pd.DataFrame] = {}

    def _ler_csv(caminho: str) -> pd.DataFrame:
        try:
            return pd.read_csv(caminho, sep=";", encoding="utf-8-sig", low_memory=False)
        except UnicodeDecodeError:
            return pd.read_csv(caminho, sep=";", encoding="latin-1", low_memory=False)

    # CG = Campo Grande — gerado por sisreg_pendentes.py (demanda_reprimida_cg_*.csv)
    arqs_cg = sorted(glob.glob(str(PASTA / "Demanda_Reprimida_CG" / "demanda_reprimida_cg_*.csv")))
    if arqs_cg:
        try:
            df = _ler_csv(arqs_cg[-1])
            df.columns = [c.strip() for c in df.columns]
            df = df.rename(columns={c: c.lower().replace(".", "").replace(" ", "_") for c in df.columns})
            for col in df.columns:
                if "dias" in col:
                    df["dias_espera"] = pd.to_numeric(df[col], errors="coerce")
                    break
            resultado["CG"] = df
        except Exception as e:
            st.warning(f"Erro ao carregar demanda CG: {e}")

    # SGO = São Gabriel do Oeste — exportação oficial SISREG (SISREG_AMB_SOL_REG_*.csv)
    arqs_sgo = sorted(glob.glob(str(PASTA / "Demanda_Reprimida_SGO" / "SISREG_AMB_SOL_REG_*.csv")))
    if arqs_sgo:
        try:
            df = _ler_csv(arqs_sgo[-1])
            df.columns = [c.strip() for c in df.columns]
            # mapeia colunas do formato oficial para os nomes esperados pelo painel
            renomear = {}
            for c in df.columns:
                cl = c.upper()
                if cl == "NOME DO USUARIO":
                    renomear[c] = "paciente"
                elif "DESC. INTERNA DO ITEM" in cl:
                    renomear[c] = "procedimento"
                elif "NOME UNIDADE SOLICITANTE" in cl:
                    renomear[c] = "unidade_solicitante"
                elif "COD. SOLICITACAO" in cl or "COD SOLICITACAO" in cl:
                    renomear[c] = "cod_solicitacao"
                else:
                    renomear[c] = c.lower().replace(".", "").replace(" ", "_").replace("/", "_")
            df = df.rename(columns=renomear)
            # dias em espera = hoje − data da solicitação
            data_sol = next((c for c in df.columns if "data" in c and "solicit" in c), None)
            if data_sol:
                datas = pd.to_datetime(df[data_sol], errors="coerce", format="mixed")
                df["dias_espera"] = (pd.Timestamp("today").normalize() - datas.dt.normalize()).dt.days
            resultado["SGO"] = df
        except Exception as e:
            st.warning(f"Erro ao carregar demanda SGO: {e}")

    return resultado


@st.cache_data(show_spinner="Carregando oferta de vagas...")
def carregar_oferta() -> pd.DataFrame:
    arquivos = glob.glob(str(PASTA / "Oferta" / "**" / "*.csv"), recursive=True)
    partes = []

    for arq in arquivos:
        p = Path(arq)
        try:
            mes_pasta = p.parent.name.lower()
            ano_pasta = int(p.parent.parent.name)
            mes_num = MESES_NUM.get(mes_pasta, 0)
        except Exception:
            mes_num, ano_pasta = 0, 0

        try:
            df = pd.read_csv(arq, sep=";", encoding="latin-1", on_bad_lines="skip", low_memory=False)
            if df.empty or len(df.columns) < 5:
                continue
            df.columns = [c.strip() for c in df.columns]
            df["mes_competencia"] = mes_num
            df["ano_competencia"] = ano_pasta
            partes.append(df)
        except Exception:
            continue

    if not partes:
        return pd.DataFrame()

    df = pd.concat(partes, ignore_index=True)
    # numéricas
    num_cols = [c for c in df.columns if any(k in c.upper() for k in ["OFERTA", "TETO", "PPI"])]
    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


# ─────────────────────────────────────────────
# COMPONENTES VISUAIS
# ─────────────────────────────────────────────

def css_global() -> None:
    st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Barlow:wght@400;600;700&display=swap');

    html, body, [class*="css"] {{
        font-family: 'Barlow', sans-serif;
        color: {CORES['cinza']};
    }}

    /* Header principal */
    .sisreg-header {{
        background: linear-gradient(135deg, {CORES['azul']} 0%, #0D2BB5 100%);
        padding: 1.4rem 2rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        display: flex;
        align-items: center;
        gap: 1rem;
    }}
    .sisreg-header h1 {{
        font-family: 'Bebas Neue', sans-serif;
        color: {CORES['branco']};
        font-size: 2.2rem;
        margin: 0;
        letter-spacing: 2px;
    }}
    .sisreg-header p {{
        color: rgba(255,255,255,0.8);
        margin: 0;
        font-size: 0.9rem;
    }}

    /* Cards KPI */
    .kpi-card {{
        background: {CORES['branco']};
        border-radius: 12px;
        padding: 1.2rem 1.4rem;
        border-left: 5px solid {CORES['azul']};
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        margin-bottom: 0.5rem;
    }}
    .kpi-card .valor {{
        font-family: 'Bebas Neue', sans-serif;
        font-size: 2.4rem;
        line-height: 1;
        color: {CORES['azul']};
    }}
    .kpi-card .label {{
        font-size: 0.8rem;
        color: #888;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-top: 0.3rem;
    }}
    .kpi-card.verde  .valor {{ color: {CORES['verde']}; }}
    .kpi-card.verde  {{ border-left-color: {CORES['verde']}; }}
    .kpi-card.amarelo .valor {{ color: #C89800; }}
    .kpi-card.amarelo {{ border-left-color: {CORES['amarelo']}; }}
    .kpi-card.vermelho .valor {{ color: {CORES['vermelho']}; }}
    .kpi-card.vermelho {{ border-left-color: {CORES['vermelho']}; }}

    /* Separador de seção */
    .sec-title {{
        font-family: 'Bebas Neue', sans-serif;
        font-size: 1.3rem;
        letter-spacing: 2px;
        color: {CORES['cinza']};
        border-bottom: 3px solid {CORES['amarelo']};
        padding-bottom: 4px;
        margin: 1.5rem 0 1rem 0;
    }}

    /* Sidebar */
    section[data-testid="stSidebar"] {{
        background: {CORES['cinza']};
    }}
    section[data-testid="stSidebar"] > div {{
        color: {CORES['branco']};
    }}
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] span:not([data-baseweb]) {{
        color: {CORES['branco']} !important;
    }}
    /* Labels dos filtros */
    section[data-testid="stSidebar"] .stSelectbox label,
    section[data-testid="stSidebar"] .stMultiSelect label {{
        color: {CORES['amarelo']} !important;
        font-weight: 600;
        font-size: 0.8rem;
        letter-spacing: 1px;
        text-transform: uppercase;
    }}
    /* Texto do valor selecionado dentro do selectbox */
    section[data-testid="stSidebar"] [data-baseweb="select"] [data-baseweb="tag"],
    section[data-testid="stSidebar"] [data-baseweb="select"] span,
    section[data-testid="stSidebar"] [data-baseweb="select"] div {{
        color: {CORES['cinza']} !important;
        background-color: white !important;
    }}
    section[data-testid="stSidebar"] [data-baseweb="select"] svg {{
        color: {CORES['cinza']} !important;
        fill: {CORES['cinza']} !important;
    }}

    </style>
    """, unsafe_allow_html=True)


def fmt_br(n: int | float) -> str:
    """Formata número com separador de milhar brasileiro (ponto)."""
    return f"{int(n):,}".replace(",", ".")


def kpi(valor: str, label: str, variante: str = "") -> None:
    cls = f"kpi-card {variante}"
    st.markdown(f"""
    <div class="{cls}">
        <div class="valor">{valor}</div>
        <div class="label">{label}</div>
    </div>
    """, unsafe_allow_html=True)


def titulo_secao(texto: str) -> None:
    st.markdown(f'<div class="sec-title">{texto}</div>', unsafe_allow_html=True)


def gauge_absenteismo(taxa: float, titulo: str = "Taxa de Absenteísmo") -> go.Figure:
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=taxa,
        number={"suffix": "%", "font": {"size": 36, "family": "Bebas Neue"}},
        title={"text": titulo, "font": {"size": 14}},
        gauge={
            "axis": {"range": [0, 100], "tickwidth": 1},
            "bar": {"color": CORES["azul"]},
            "steps": [
                {"range": [0,  20], "color": CORES["verde"]},
                {"range": [20, 40], "color": CORES["amarelo"]},
                {"range": [40, 100], "color": "#FFCCCC"},
            ],
            "threshold": {
                "line": {"color": CORES["vermelho"], "width": 3},
                "thickness": 0.75,
                "value": taxa,
            },
        },
    ))
    fig.update_layout(height=260, margin=dict(t=50, b=10, l=20, r=20))
    return fig


# ─────────────────────────────────────────────
# FILTROS — sidebar
# ─────────────────────────────────────────────

def sidebar_filtros(df_ag: pd.DataFrame) -> dict:
    st.sidebar.markdown(f"""
    <div style='text-align:center; padding: 1rem 0;'>
        <span style='font-family:Bebas Neue,sans-serif; font-size:1.6rem;
                     color:{CORES["amarelo"]}; letter-spacing:3px;'>⚕ SISREG</span><br>
        <span style='font-size:0.7rem; opacity:0.7;'>REGULAÇÃO AMBULATORIAL</span>
    </div>
    """, unsafe_allow_html=True)

    st.sidebar.markdown("---")

    filtros: dict = {}

    # Período
    anos_disp = sorted(df_ag["ano_pasta"].dropna().unique().astype(int).tolist()) if not df_ag.empty else []
    meses_nomes = [MESES_PT[m] for m in sorted(MESES_PT.keys())]

    filtros["ano"] = st.sidebar.selectbox(
        "Ano", options=["Todos"] + [str(a) for a in anos_disp], index=0
    )
    filtros["mes"] = st.sidebar.selectbox(
        "Mês", options=["Todos"] + [m.capitalize() for m in meses_nomes], index=0
    )

    st.sidebar.markdown("---")

    # Procedimento
    procs = sorted(df_ag["descricao_procedimento"].dropna().unique().tolist()) if not df_ag.empty else []
    filtros["procedimento"] = st.sidebar.multiselect(
        "Procedimento", options=procs, default=[]
    )

    # Unidade Solicitante
    unids_sol = sorted(df_ag["unidade_fantasia"].dropna().unique().tolist()) if not df_ag.empty else []
    filtros["unidade_sol"] = st.sidebar.multiselect(
        "Unidade Solicitante", options=unids_sol, default=[]
    )

    # Unidade Executante
    unids_exec = sorted(df_ag["estabelecimento_executor"].dropna().unique().tolist()) if not df_ag.empty else []
    filtros["unidade_exec"] = st.sidebar.multiselect(
        "Unidade Executante", options=unids_exec, default=[]
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown(
        f"<small style='opacity:0.5;'>Atualizado: {datetime.now():%d/%m/%Y %H:%M}</small>",
        unsafe_allow_html=True
    )

    return filtros


def aplicar_filtros(df: pd.DataFrame, filtros: dict) -> pd.DataFrame:
    if df.empty:
        return df

    if filtros["ano"] != "Todos":
        df = df[df["ano_pasta"] == int(filtros["ano"])]

    if filtros["mes"] != "Todos":
        mes_num = MESES_NUM.get(filtros["mes"].lower(), 0)
        df = df[df["mes_pasta"] == mes_num]

    if filtros["procedimento"]:
        df = df[df["descricao_procedimento"].isin(filtros["procedimento"])]

    if filtros["unidade_sol"]:
        df = df[df["unidade_fantasia"].isin(filtros["unidade_sol"])]

    if filtros["unidade_exec"]:
        df = df[df["estabelecimento_executor"].isin(filtros["unidade_exec"])]

    return df


# ─────────────────────────────────────────────
# ABAS
# ─────────────────────────────────────────────

def aba_visao_geral(df: pd.DataFrame, demanda: dict, oferta: pd.DataFrame) -> None:
    st.markdown('<div class="sisreg-header"><div><h1>⚕ PAINEL SISREG</h1><p>Regulação Ambulatorial — São Gabriel do Oeste / MS</p></div></div>', unsafe_allow_html=True)

    # KPIs
    total_ag   = len(df)
    confirmados = int(df.get("compareceu", pd.Series(dtype=bool)).sum()) if not df.empty else 0
    ausentes   = int(df.get("ausente",    pd.Series(dtype=bool)).sum()) if not df.empty else 0
    passados   = int(df.get("passado",    pd.Series(dtype=bool)).sum()) if not df.empty else 0
    taxa_abs   = round(ausentes / passados * 100, 1) if passados > 0 else 0

    total_sgo  = len(demanda.get("SGO", pd.DataFrame()))
    total_cg   = len(demanda.get("CG",  pd.DataFrame()))

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: kpi(fmt_br(total_ag), "Total Agendamentos", "azul")
    with c2: kpi(fmt_br(confirmados), "Confirmados", "verde")
    with c3: kpi(f"{taxa_abs}%", "Absenteísmo", "vermelho" if taxa_abs > 30 else "amarelo")
    with c4: kpi(fmt_br(total_sgo), "Fila SGO", "amarelo")
    with c5: kpi(fmt_br(total_cg), "Fila CG", "amarelo")

    st.markdown("<br>", unsafe_allow_html=True)

    # Situação geral
    col1, col2 = st.columns([1, 2])

    with col1:
        titulo_secao("SITUAÇÃO GERAL")
        if not df.empty and "situacao" in df.columns:
            sit = df["situacao"].value_counts().reset_index()
            sit.columns = ["Situação", "Qtd"]
            fig = px.pie(sit, names="Situação", values="Qtd",
                         color="Situação",
                         color_discrete_map={"CONFIRMADO": CORES["verde"], "PENDENTE": CORES["amarelo"]},
                         hole=0.55)
            fig.update_traces(textposition="inside", textinfo="percent+label")
            fig.update_layout(height=280, margin=dict(t=10, b=10, l=10, r=10),
                              showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

    with col2:
        titulo_secao("AGENDAMENTOS POR MÊS")
        if not df.empty and "data_agendamento" in df.columns:
            df_mes = df.dropna(subset=["data_agendamento"]).copy()
            df_mes["mes_ano"] = df_mes["data_agendamento"].dt.strftime("%m/%Y")
            ag_mes = df_mes.groupby(["mes_ano", "situacao"]).size().reset_index(name="qtd")
            fig = px.bar(ag_mes, x="mes_ano", y="qtd", color="situacao",
                         color_discrete_map={"CONFIRMADO": CORES["verde"], "PENDENTE": CORES["amarelo"]},
                         labels={"mes_ano": "Mês/Ano", "qtd": "Agendamentos", "situacao": "Situação"},
                         barmode="stack")
            fig.update_layout(height=280, margin=dict(t=10, b=40, l=10, r=10),
                              legend=dict(orientation="h", y=-0.3),
                              plot_bgcolor="white", paper_bgcolor="white")
            fig.update_xaxes(tickangle=-30)
            st.plotly_chart(fig, use_container_width=True)

    # Top procedimentos — empilhado por situação
    titulo_secao("TOP 10 PROCEDIMENTOS")
    if not df.empty and "descricao_procedimento" in df.columns and "situacao" in df.columns:
        top10_nomes = df["descricao_procedimento"].value_counts().head(10).index.tolist()
        df_top = df[df["descricao_procedimento"].isin(top10_nomes)].copy()
        grp_top = df_top.groupby(["descricao_procedimento", "situacao"]).size().reset_index(name="Qtd")
        # ordena pelo total decrescente no eixo Y
        ordem = df_top["descricao_procedimento"].value_counts().index.tolist()
        grp_top["descricao_procedimento"] = pd.Categorical(
            grp_top["descricao_procedimento"], categories=ordem[::-1], ordered=True
        )
        grp_top = grp_top.sort_values("descricao_procedimento")
        fig = px.bar(grp_top, x="Qtd", y="descricao_procedimento", color="situacao",
                     color_discrete_map={"CONFIRMADO": CORES["verde"], "PENDENTE": CORES["amarelo"]},
                     orientation="h", barmode="stack",
                     labels={"descricao_procedimento": "", "Qtd": "Agendamentos", "situacao": "Situação"})
        fig.update_layout(height=400, margin=dict(t=10, b=10, l=10, r=20),
                          legend=dict(orientation="h", y=-0.15, title_text=""),
                          plot_bgcolor="white", paper_bgcolor="white")
        st.plotly_chart(fig, use_container_width=True)


def aba_absenteismo(df: pd.DataFrame) -> None:
    titulo_secao("ABSENTEÍSMO")

    passados = df[df.get("passado", pd.Series(dtype=bool))] if not df.empty else pd.DataFrame()
    ausentes_total = int(passados.get("ausente", pd.Series(dtype=bool)).sum()) if not passados.empty else 0
    total_passados = len(passados)
    taxa_geral = round(ausentes_total / total_passados * 100, 1) if total_passados > 0 else 0

    _, col_centro, _ = st.columns([1, 2, 1])
    with col_centro:
        fig = gauge_absenteismo(taxa_geral, "Absenteísmo Geral")
        st.plotly_chart(fig, use_container_width=True)

    col_exec, col_sol = st.columns(2)

    with col_exec:
        titulo_secao("POR UNIDADE EXECUTANTE")
        if not passados.empty and "estabelecimento_executor" in passados.columns:
            grp = passados.groupby("estabelecimento_executor").agg(
                total=("ausente", "count"),
                ausentes=("ausente", "sum")
            ).reset_index()
            grp["taxa"] = (grp["ausentes"] / grp["total"] * 100).round(1)
            grp = grp.sort_values("taxa", ascending=True)
            fig = px.bar(grp, x="taxa", y="estabelecimento_executor", orientation="h",
                         color="taxa",
                         color_continuous_scale=["#00D000", "#FFD000", "#FF0000"],
                         range_color=[0, 100],
                         labels={"taxa": "Absenteísmo (%)", "estabelecimento_executor": ""},
                         text="taxa")
            fig.update_traces(texttemplate="%{text}%", textposition="outside")
            fig.update_layout(height=320, coloraxis_showscale=False,
                              margin=dict(t=10, b=10, l=10, r=50),
                              xaxis=dict(range=[0, 115]),
                              plot_bgcolor="white", paper_bgcolor="white")
            st.plotly_chart(fig, use_container_width=True)

    with col_sol:
        titulo_secao("POR UNIDADE SOLICITANTE")
        if not passados.empty and "unidade_fantasia" in passados.columns:
            grp = passados.groupby("unidade_fantasia").agg(
                total=("ausente", "count"),
                ausentes=("ausente", "sum")
            ).reset_index()
            grp["taxa"] = (grp["ausentes"] / grp["total"] * 100).round(1)
            grp = grp.sort_values("taxa", ascending=False).head(12)
            fig = px.bar(grp, x="taxa", y="unidade_fantasia", orientation="h",
                         color="taxa",
                         color_continuous_scale=["#00D000", "#FFD000", "#FF0000"],
                         range_color=[0, 100],
                         labels={"taxa": "Absenteísmo (%)", "unidade_fantasia": ""},
                         text="taxa")
            fig.update_traces(texttemplate="%{text}%", textposition="outside")
            fig.update_layout(height=320, coloraxis_showscale=False,
                              margin=dict(t=10, b=10, l=10, r=50),
                              xaxis=dict(range=[0, 115]),
                              plot_bgcolor="white", paper_bgcolor="white")
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    titulo_secao("TEMPO AUTORIZAÇÃO → AGENDAMENTO  |  PENDENTES")

    tem_colunas = not df.empty and "data_autorizacao" in df.columns and "data_agendamento" in df.columns
    if not tem_colunas:
        st.info("Colunas de data_autorizacao ou data_agendamento não encontradas nos dados.")
    else:
        df_pend = df[df.get("situacao", pd.Series(dtype=str)) == "PENDENTE"].copy()

        if df_pend.empty:
            st.info("Nenhum agendamento PENDENTE encontrado.")
        else:
            df_pend["tempo_dias"] = (
                df_pend["data_agendamento"].dt.normalize()
                - df_pend["data_autorizacao"].dt.normalize()
            ).dt.days

            df_pend["tipo_agend"] = df_pend.apply(
                lambda r: "EM TELA"
                if pd.notna(r["data_autorizacao"]) and pd.notna(r["data_agendamento"])
                and r["data_autorizacao"].normalize() == r["data_agendamento"].normalize()
                else "REGULADO",
                axis=1,
            )

            ordem_faixas = ["≤ 7 dias", "8–15 dias", "16–30 dias", "31–45 dias", "46–60 dias", "> 60 dias"]

            def _faixa(dias):
                if pd.isna(dias) or dias < 0: return None
                if dias <= 7:  return "≤ 7 dias"
                if dias <= 15: return "8–15 dias"
                if dias <= 30: return "16–30 dias"
                if dias <= 45: return "31–45 dias"
                if dias <= 60: return "46–60 dias"
                return "> 60 dias"

            df_pend["faixa_tempo"] = df_pend["tempo_dias"].apply(_faixa)

            tot_reg  = int((df_pend["tipo_agend"] == "REGULADO").sum())
            tot_tela = int((df_pend["tipo_agend"] == "EM TELA").sum())
            media_t  = df_pend["tempo_dias"].dropna()
            media_str = f"{int(media_t.mean())} dias" if not media_t.empty else "—"
            c1, c2, c3 = st.columns(3)
            with c1: kpi(fmt_br(tot_reg),  "REGULADO",        "azul")
            with c2: kpi(fmt_br(tot_tela), "EM TELA",         "verde")
            with c3: kpi(media_str,         "Média de Espera", "amarelo")

            df_chart = (
                df_pend.dropna(subset=["faixa_tempo"])
                .groupby(["faixa_tempo", "tipo_agend"])
                .size().reset_index(name="Qtd")
            )
            df_chart["faixa_tempo"] = pd.Categorical(
                df_chart["faixa_tempo"], categories=ordem_faixas, ordered=True
            )
            df_chart = df_chart.sort_values("faixa_tempo")

            fig_t = px.bar(
                df_chart, x="faixa_tempo", y="Qtd", color="tipo_agend",
                barmode="stack",
                color_discrete_map={"REGULADO": CORES["azul"], "EM TELA": CORES["verde"]},
                labels={"faixa_tempo": "Tempo Autorização → Agendamento",
                        "Qtd": "Solicitações", "tipo_agend": "Tipo"},
                text="Qtd",
            )
            fig_t.update_traces(textposition="inside", textfont_size=11)
            fig_t.update_layout(
                height=380,
                margin=dict(t=10, b=50, l=10, r=10),
                legend=dict(orientation="h", y=-0.2, title_text=""),
                plot_bgcolor="white", paper_bgcolor="white",
            )
            st.plotly_chart(fig_t, use_container_width=True)

            titulo_secao("REGISTROS PENDENTES — DETALHE")
            cols_tab = [c for c in [
                "data_solicitacao", "unidade_fantasia", "descricao_procedimento",
                "data_autorizacao", "data_agendamento", "tempo_dias", "tipo_agend",
            ] if c in df_pend.columns]
            df_tab = df_pend[cols_tab].copy()
            for col in ["data_solicitacao", "data_autorizacao", "data_agendamento"]:
                if col in df_tab.columns:
                    df_tab[col] = df_tab[col].dt.strftime("%d/%m/%Y")
            df_tab = df_tab.rename(columns={
                "data_solicitacao":       "Data Solicitação",
                "unidade_fantasia":       "Unidade Solicitante",
                "descricao_procedimento": "Procedimento",
                "data_autorizacao":       "Data Autorização",
                "data_agendamento":       "Data Agendamento",
                "tempo_dias":             "Tempo (dias)",
                "tipo_agend":             "Tipo",
            })
            df_tab = df_tab.sort_values("Tempo (dias)", ascending=False).reset_index(drop=True)
            st.dataframe(df_tab, use_container_width=True, height=380)


def aba_agendamentos(df: pd.DataFrame) -> None:
    titulo_secao("VOLUME DE AGENDAMENTOS")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Por Unidade Executante**")
        if not df.empty and "estabelecimento_executor" in df.columns:
            cnt = df["estabelecimento_executor"].value_counts().head(15).reset_index()
            cnt.columns = ["Executante", "Qtd"]
            fig = px.bar(cnt, x="Qtd", y="Executante", orientation="h",
                         color_discrete_sequence=[CORES["azul"]],
                         text="Qtd")
            fig.update_traces(textposition="outside")
            fig.update_layout(height=380, yaxis=dict(categoryorder="total ascending"),
                              margin=dict(t=10, b=10, l=10, r=60),
                              plot_bgcolor="white", paper_bgcolor="white")
            st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.markdown("**Por Procedimento**")
        if not df.empty and "descricao_procedimento" in df.columns:
            cnt = df["descricao_procedimento"].value_counts().head(15).reset_index()
            cnt.columns = ["Procedimento", "Qtd"]
            fig = px.bar(cnt, x="Qtd", y="Procedimento", orientation="h",
                         color_discrete_sequence=[CORES["verde"]],
                         text="Qtd")
            fig.update_traces(textposition="outside")
            fig.update_layout(height=480, yaxis=dict(categoryorder="total ascending"),
                              margin=dict(t=10, b=10, l=10, r=80),
                              xaxis=dict(range=[0, cnt["Qtd"].max() * 1.18]),
                              plot_bgcolor="white", paper_bgcolor="white")
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    titulo_secao("PROFISSIONAIS SOLICITANTES")

    if not df.empty and "nome_profissional_solicitante" in df.columns:
        top = (df["nome_profissional_solicitante"].dropna()
               .str.strip().value_counts().head(15).reset_index())
        top.columns = ["Profissional", "Qtd"]
        top = top[top["Profissional"] != ""]
        fig = px.bar(top, x="Qtd", y="Profissional", orientation="h",
                     color_discrete_sequence=[CORES["amarelo"]],
                     text="Qtd")
        fig.update_traces(textposition="outside", marker_line_color=CORES["cinza"], marker_line_width=0.3)
        fig.update_layout(height=460, yaxis=dict(categoryorder="total ascending"),
                          margin=dict(t=10, b=10, l=10, r=80),
                          xaxis=dict(range=[0, top["Qtd"].max() * 1.18]),
                          plot_bgcolor="white", paper_bgcolor="white",
                          font=dict(color=CORES["cinza"]))
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    titulo_secao("DADOS DETALHADOS")
    if not df.empty:
        filtro_nome_ag = st.text_input(
            "Filtrar por nome do paciente",
            key="filtro_nome_agendamentos",
            placeholder="Digite parte do nome..."
        )
        cols_exibir = [c for c in [
            "data_agendamento", "descricao_procedimento", "nome",
            "unidade_fantasia", "estabelecimento_executor",
            "nome_profissional_solicitante", "nome_profissional_executante",
            "situacao", "cid", "tipo_label"
        ] if c in df.columns]
        df_det = df[cols_exibir].sort_values("data_agendamento", ascending=False).reset_index(drop=True)
        if filtro_nome_ag and "nome" in df_det.columns:
            df_det = df_det[df_det["nome"].str.upper().str.contains(
                filtro_nome_ag.upper(), na=False)]
        df_det = df_det.head(500).reset_index(drop=True)
        if "data_agendamento" in df_det.columns:
            df_det["data_agendamento"] = df_det["data_agendamento"].dt.strftime("%d/%m/%Y")
        st.dataframe(df_det, use_container_width=True, height=350)


def aba_demanda_reprimida(demanda: dict) -> None:
    st.markdown("""
    <div style='background:#FFF8E1; border-left:5px solid #FFD000;
                padding:0.8rem 1rem; border-radius:6px; margin-bottom:1rem;'>
        <b>⚠️ Atenção:</b> As filas CG (Campo Grande) e SGO (São Gabriel do Oeste) são independentes.
        Pacientes podem estar em ambas as filas para procedimentos distintos ou semelhantes.
        Não some os totais entre as filas.
    </div>
    """, unsafe_allow_html=True)

    tab_sgo, tab_cg, tab_comparativo = st.tabs(["📍 Fila SGO", "📍 Fila CG", "🔍 Pacientes em Ambas"])

    # ─── Fila SGO ───
    with tab_sgo:
        df = demanda.get("SGO", pd.DataFrame())
        if df.empty:
            st.info("Dados da fila SGO não disponíveis.")
        else:
            cor = CORES["azul"]
            dias_col = "dias_espera" if "dias_espera" in df.columns else None
            _media = df[dias_col].mean() if dias_col else float("nan")
            _max   = df[dias_col].max()  if dias_col else float("nan")
            media_dias = str(int(_media)) if not pd.isna(_media) else "—"
            max_dias   = str(int(_max))   if not pd.isna(_max)   else "—"

            c1, c2, c3 = st.columns(3)
            with c1: kpi(fmt_br(len(df)), "Total na Fila SGO")
            with c2: kpi(media_dias, "Média Dias Espera", "amarelo")
            with c3: kpi(max_dias, "Maior Espera (dias)", "vermelho")

            # Gráfico 1 — Por Procedimento (linha inteira)
            titulo_secao("POR PROCEDIMENTO")
            if "procedimento" in df.columns:
                top_proc = df["procedimento"].value_counts().head(15).reset_index()
                top_proc.columns = ["Procedimento", "Qtd"]
                fig = px.bar(top_proc, x="Qtd", y="Procedimento", orientation="h",
                             color_discrete_sequence=[cor], text="Qtd")
                fig.update_traces(textposition="outside")
                fig.update_layout(height=460, yaxis=dict(categoryorder="total ascending"),
                                  margin=dict(t=10, b=10, l=10, r=70),
                                  plot_bgcolor="white", paper_bgcolor="white")
                st.plotly_chart(fig, use_container_width=True)

            # Gráfico 2 — Estimativa de atendimento por procedimento (linha inteira)
            estim_col = "estim_de_atendimento_do_procedimento"
            if estim_col in df.columns and "procedimento" in df.columns:
                titulo_secao("DISTRIBUIÇÃO DIAS DE ESPERA")
                df_estim = (df.groupby("procedimento")[estim_col]
                              .mean().reset_index()
                              .rename(columns={estim_col: "Estimativa (dias)"}))
                df_estim = df_estim.sort_values("Estimativa (dias)", ascending=False).head(15)
                fig2 = px.bar(df_estim, x="Estimativa (dias)", y="procedimento", orientation="h",
                              color_discrete_sequence=[cor], text="Estimativa (dias)")
                fig2.update_traces(texttemplate="%{text:.0f}", textposition="outside")
                fig2.update_layout(height=460, yaxis=dict(categoryorder="total ascending"),
                                   margin=dict(t=10, b=10, l=10, r=70),
                                   plot_bgcolor="white", paper_bgcolor="white")
                st.plotly_chart(fig2, use_container_width=True)

            # Gráfico 3 — Por Unidade Solicitante (linha inteira)
            titulo_secao("POR UNIDADE SOLICITANTE")
            if "unidade_solicitante" in df.columns:
                cnt_unid = df["unidade_solicitante"].value_counts().head(20).reset_index()
                cnt_unid.columns = ["Unidade Solicitante", "Qtd"]
                fig3 = px.bar(cnt_unid, x="Qtd", y="Unidade Solicitante", orientation="h",
                              color_discrete_sequence=[cor], text="Qtd")
                fig3.update_traces(textposition="outside")
                fig3.update_layout(height=460, yaxis=dict(categoryorder="total ascending"),
                                   margin=dict(t=10, b=10, l=10, r=70),
                                   plot_bgcolor="white", paper_bgcolor="white")
                st.plotly_chart(fig3, use_container_width=True)

            # Gráfico 4 — Por Profissional Solicitante (linha inteira)
            titulo_secao("POR PROFISSIONAL SOLICITANTE")
            prof_col_sgo = next(
                (c for c in df.columns if ("profissional" in c or "medico" in c) and "unidade" not in c),
                None
            )
            if prof_col_sgo:
                cnt_prof = df[prof_col_sgo].dropna().str.strip().value_counts().head(20).reset_index()
                cnt_prof.columns = ["Profissional Solicitante", "Qtd"]
                cnt_prof = cnt_prof[cnt_prof["Profissional Solicitante"] != ""]
                fig4 = px.bar(cnt_prof, x="Qtd", y="Profissional Solicitante", orientation="h",
                              color_discrete_sequence=[CORES["amarelo"]], text="Qtd")
                fig4.update_traces(textposition="outside")
                fig4.update_layout(height=460, yaxis=dict(categoryorder="total ascending"),
                                   margin=dict(t=10, b=10, l=10, r=70),
                                   plot_bgcolor="white", paper_bgcolor="white")
                st.plotly_chart(fig4, use_container_width=True)

            # Tabela — filtro por nome do paciente
            titulo_secao("REGISTROS")
            filtro_pac = st.text_input("Filtrar por nome do paciente [SGO]",
                                       key="filtro_pac_sgo", placeholder="Digite parte do nome...")
            colunas_sgo = ["data_hora_da_solicitacao", "unidade_solicitante", "cod_solicitacao",
                           "procedimento", "paciente", "data_de_nascimento_do_usuario",
                           "posicao_na_fila", "dias_espera"]
            cols_disp = [c for c in colunas_sgo if c in df.columns]
            df_show = df[cols_disp].copy()
            if "data_de_nascimento_do_usuario" in df_show.columns:
                df_show["data_de_nascimento_do_usuario"] = (
                    pd.to_datetime(df_show["data_de_nascimento_do_usuario"], errors="coerce")
                    .dt.strftime("%d/%m/%Y")
                )
            label_sgo = {
                "data_hora_da_solicitacao": "Data/Hora Solicitação",
                "unidade_solicitante":      "Unidade Solicitante",
                "cod_solicitacao":          "Cód. Solicitação",
                "procedimento":             "Procedimento",
                "paciente":                 "Paciente",
                "data_de_nascimento_do_usuario": "Nascimento",
                "posicao_na_fila":          "Posição na Fila",
                "dias_espera":              "Dias de Espera",
            }
            df_show = df_show.rename(columns=label_sgo)
            if filtro_pac:
                df_show = df_show[df_show["Paciente"].str.upper().str.contains(
                    filtro_pac.upper(), na=False)]
            if "Dias de Espera" in df_show.columns:
                df_show = df_show.sort_values("Dias de Espera", ascending=False)
            st.dataframe(df_show.reset_index(drop=True), use_container_width=True, height=350)

    # ─── Fila CG ───
    with tab_cg:
        df = demanda.get("CG", pd.DataFrame())
        if df.empty:
            st.info("Dados da fila CG não disponíveis.")
        else:
            cor = CORES["verde"]
            dias_col = "dias_espera" if "dias_espera" in df.columns else None
            _media = df[dias_col].mean() if dias_col else float("nan")
            _max   = df[dias_col].max()  if dias_col else float("nan")
            media_dias = str(int(_media)) if not pd.isna(_media) else "—"
            max_dias   = str(int(_max))   if not pd.isna(_max)   else "—"

            c1, c2, c3 = st.columns(3)
            with c1: kpi(fmt_br(len(df)), "Total na Fila CG")
            with c2: kpi(media_dias, "Média Dias Espera", "amarelo")
            with c3: kpi(max_dias, "Maior Espera (dias)", "vermelho")

            # Gráfico — Por Procedimento
            titulo_secao("POR PROCEDIMENTO")
            proc_col = next((c for c in df.columns if "proc" in c.lower()), None)
            if proc_col:
                top_proc = df[proc_col].value_counts().head(15).reset_index()
                top_proc.columns = ["Procedimento", "Qtd"]
                fig = px.bar(top_proc, x="Qtd", y="Procedimento", orientation="h",
                             color_discrete_sequence=[cor], text="Qtd")
                fig.update_traces(textposition="outside")
                fig.update_layout(height=460, yaxis=dict(categoryorder="total ascending"),
                                  margin=dict(t=10, b=10, l=10, r=70),
                                  plot_bgcolor="white", paper_bgcolor="white")
                st.plotly_chart(fig, use_container_width=True)

            # Tabela — filtro por nome do paciente
            titulo_secao("REGISTROS")
            filtro_pac_cg = st.text_input("Filtrar por nome do paciente [CG]",
                                          key="filtro_pac_cg", placeholder="Digite parte do nome...")
            df_show = df.copy()
            if filtro_pac_cg and "paciente" in df_show.columns:
                df_show = df_show[df_show["paciente"].str.upper().str.contains(
                    filtro_pac_cg.upper(), na=False)]
            if dias_col:
                df_show = df_show.sort_values(dias_col, ascending=False)
            st.dataframe(df_show.reset_index(drop=True), use_container_width=True, height=350)

    # Aba comparativo
    with tab_comparativo:
        df_sgo = demanda.get("SGO", pd.DataFrame())
        df_cg  = demanda.get("CG",  pd.DataFrame())

        if df_sgo.empty or df_cg.empty:
            st.info("Necessário ter dados de ambas as filas (SGO e CG) para o comparativo.")
            return

        titulo_secao("PACIENTES PRESENTES NAS DUAS FILAS")
        pac_col_sgo = next((c for c in df_sgo.columns if "paciente" in c.lower()), None)
        pac_col_cg  = next((c for c in df_cg.columns  if "paciente" in c.lower()), None)

        if pac_col_sgo and pac_col_cg:
            nomes_sgo = set(df_sgo[pac_col_sgo].dropna().str.upper().str.strip())
            nomes_cg  = set(df_cg[pac_col_cg].dropna().str.upper().str.strip())
            em_ambas  = nomes_sgo & nomes_cg

            c1, c2, c3 = st.columns(3)
            with c1: kpi(fmt_br(len(nomes_sgo)), "Pacientes Fila SGO", "azul")
            with c2: kpi(fmt_br(len(nomes_cg)),  "Pacientes Fila CG",  "verde")
            with c3: kpi(fmt_br(len(em_ambas)),  "Em Ambas as Filas",  "amarelo")

            if em_ambas:
                st.markdown(f"**{len(em_ambas)} paciente(s) identificados nas duas filas:**")
                df_ambas_sgo = df_sgo[df_sgo[pac_col_sgo].str.upper().str.strip().isin(em_ambas)]
                df_ambas_cg  = df_cg[df_cg[pac_col_cg].str.upper().str.strip().isin(em_ambas)]

                label_map = {"paciente": "Paciente", "procedimento": "Procedimento", "dias_espera": "Dias de Espera"}

                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**Registros na Fila SGO**")
                    cols_sgo = [c for c in ["paciente", "procedimento", "dias_espera"] if c in df_ambas_sgo.columns]
                    st.dataframe(df_ambas_sgo[cols_sgo].rename(columns=label_map).reset_index(drop=True),
                                 use_container_width=True, height=280)
                with col2:
                    st.markdown("**Registros na Fila CG**")
                    cols_cg = [c for c in ["paciente", "procedimento", "dias_espera"] if c in df_ambas_cg.columns]
                    st.dataframe(df_ambas_cg[cols_cg].rename(columns=label_map).reset_index(drop=True),
                                 use_container_width=True, height=280)

                titulo_secao("REGISTRO EM AMBAS")
                proc_sgo = "procedimento" if "procedimento" in df_sgo.columns else None
                proc_cg  = "procedimento" if "procedimento" in df_cg.columns else None
                registros_ambas = []
                for nome in sorted(em_ambas):
                    ps = df_sgo[df_sgo[pac_col_sgo].str.upper().str.strip() == nome][proc_sgo].dropna().unique().tolist() if proc_sgo else []
                    pc = df_cg[df_cg[pac_col_cg].str.upper().str.strip() == nome][proc_cg].dropna().unique().tolist() if proc_cg else []
                    registros_ambas.append({
                        "Paciente": nome.title(),
                        "Procedimento SGO": " | ".join(ps),
                        "Procedimento CG":  " | ".join(pc),
                    })
                st.dataframe(pd.DataFrame(registros_ambas).reset_index(drop=True),
                             use_container_width=True, height=300)


def aba_oferta(oferta: pd.DataFrame) -> None:
    if oferta.empty:
        st.info("Dados de oferta de vagas não disponíveis.")
        return

    # KPIs gerais
    col_oferta_ativa = next((c for c in oferta.columns if "OFERTA ATIVA GERAL" in c.upper()), None)
    col_oferta_total = next((c for c in oferta.columns if "OFERTA TOTAL GERAL" in c.upper()), None)
    col_bloqueada    = next((c for c in oferta.columns if "BLOQUEADA GERAL" in c.upper()), None)
    col_teto         = next((c for c in oferta.columns if "TETO" in c.upper()), None)
    col_proc         = next((c for c in oferta.columns if "DESC. PROC" in c.upper()), None)
    col_estab        = next((c for c in oferta.columns if "DESC. ESTAB" in c.upper()), None)

    total_ativa    = int(oferta[col_oferta_ativa].sum()) if col_oferta_ativa else 0
    total_total    = int(oferta[col_oferta_total].sum()) if col_oferta_total else 0
    total_bloq     = int(oferta[col_bloqueada].sum())    if col_bloqueada else 0
    pct_bloqueada  = round(total_bloq / total_total * 100, 1) if total_total > 0 else 0

    c1, c2, c3, c4 = st.columns(4)
    with c1: kpi(fmt_br(total_total), "Oferta Total", "azul")
    with c2: kpi(fmt_br(total_ativa), "Oferta Ativa", "verde")
    with c3: kpi(fmt_br(total_bloq), "Oferta Bloqueada", "vermelho")
    with c4: kpi(f"{pct_bloqueada}%", "% Bloqueada", "vermelho" if pct_bloqueada > 30 else "amarelo")

    # Filtro competência
    if "mes_competencia" in oferta.columns and "ano_competencia" in oferta.columns:
        competencias = sorted(
            oferta.dropna(subset=["ano_competencia", "mes_competencia"])
            .apply(lambda r: f"{int(r['mes_competencia']):02d}/{int(r['ano_competencia'])}", axis=1)
            .unique().tolist()
        )
        sel_comp = st.selectbox("Competência", ["Todas"] + competencias)
        if sel_comp != "Todas":
            m, a = sel_comp.split("/")
            oferta = oferta[(oferta["mes_competencia"] == int(m)) & (oferta["ano_competencia"] == int(a))]

    col1, col2 = st.columns(2)

    with col1:
        titulo_secao("OFERTA ATIVA × BLOQUEADA — POR PROCEDIMENTO")
        if col_proc and col_oferta_ativa and col_bloqueada:
            grp = oferta.groupby(col_proc)[[col_oferta_ativa, col_bloqueada]].sum().reset_index()
            grp = grp.sort_values(col_oferta_ativa, ascending=False).head(15)
            fig = go.Figure()
            fig.add_bar(x=grp[col_proc], y=grp[col_oferta_ativa], name="Ativa",
                        marker_color=CORES["verde"])
            fig.add_bar(x=grp[col_proc], y=grp[col_bloqueada], name="Bloqueada",
                        marker_color=CORES["vermelho"])
            fig.update_layout(barmode="stack", height=420,
                              xaxis_tickangle=-35,
                              legend=dict(orientation="h", y=-0.35),
                              margin=dict(t=10, b=80, l=10, r=10),
                              plot_bgcolor="white", paper_bgcolor="white")
            st.plotly_chart(fig, use_container_width=True)

    with col2:
        titulo_secao("TETO × OFERTA ATIVA — POR ESTABELECIMENTO")
        if col_estab and col_teto and col_oferta_ativa:
            grp = oferta.groupby(col_estab)[[col_teto, col_oferta_ativa]].sum().reset_index()
            grp["pct_uso"] = (grp[col_oferta_ativa] / grp[col_teto] * 100).round(1)
            grp = grp.sort_values("pct_uso", ascending=True)
            fig = px.bar(grp, x="pct_uso", y=col_estab, orientation="h",
                         color="pct_uso",
                         color_continuous_scale=["#FF0000", "#FFD000", "#00D000"],
                         range_color=[0, 100],
                         text="pct_uso",
                         labels={"pct_uso": "% do Teto Utilizado", col_estab: ""})
            fig.update_traces(texttemplate="%{text}%", textposition="outside")
            fig.update_layout(height=420, coloraxis_showscale=False,
                              margin=dict(t=10, b=10, l=10, r=60),
                              plot_bgcolor="white", paper_bgcolor="white")
            st.plotly_chart(fig, use_container_width=True)

    titulo_secao("DADOS COMPLETOS — OFERTA")
    col_exib = [c for c in [col_proc, col_estab, "mes_competencia", "ano_competencia",
                             col_teto, col_oferta_total, col_oferta_ativa, col_bloqueada]
                if c is not None]
    st.dataframe(oferta[col_exib].reset_index(drop=True), use_container_width=True, height=350)


# ─────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────

def tela_login() -> bool:
    """Exibe formulário de login; retorna True se autenticado."""
    if st.session_state.get("autenticado"):
        return True

    # Credenciais lidas do secrets.toml (local) ou Streamlit Cloud Secrets
    _user = st.secrets.get("ADMIN_USER", "admin")
    _pass = st.secrets.get("ADMIN_PASS", "821504")

    st.markdown("""
    <div style='max-width:420px; margin:4rem auto 0; text-align:center;'>
        <div style='background:linear-gradient(135deg,#183EFF 0%,#0D2BB5 100%);
                    padding:2rem 2rem 1.5rem; border-radius:16px; margin-bottom:1.5rem;'>
            <div style='font-family:Bebas Neue,sans-serif; color:white;
                        font-size:2.4rem; letter-spacing:3px;'>PAINEL SISREG</div>
            <p style='color:rgba(255,255,255,0.8); margin:0; font-size:0.85rem;'>
                Regulação Ambulatorial — São Gabriel do Oeste / MS
            </p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col = st.columns([1, 2, 1])[1]
    with col:
        with st.form("login_form"):
            usuario = st.text_input("Usuário")
            senha   = st.text_input("Senha", type="password")
            entrar  = st.form_submit_button("Entrar", use_container_width=True)
        if entrar:
            if usuario == _user and senha == _pass:
                st.session_state.autenticado = True
                st.rerun()
            else:
                st.error("Usuário ou senha incorretos.")

    return False


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="Painel SISREG",
        page_icon="⚕",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    css_global()

    if not tela_login():
        st.stop()

    # Carrega dados
    df_ag    = carregar_agendamentos()
    demanda  = carregar_demanda_reprimida()
    df_of    = carregar_oferta()

    # Filtros sidebar
    filtros = sidebar_filtros(df_ag)
    df_filtrado = aplicar_filtros(df_ag.copy(), filtros)

    # Tabs principais
    t1, t2, t3, t4, t5 = st.tabs([
        "📊 Visão Geral",
        "📅 Agendamentos",
        "🚫 Absenteísmo",
        "⏳ Demanda Reprimida",
        "🏥 Oferta de Vagas",
    ])

    with t1:
        aba_visao_geral(df_filtrado, demanda, df_of)
    with t2:
        aba_agendamentos(df_filtrado)
    with t3:
        aba_absenteismo(df_filtrado)
    with t4:
        aba_demanda_reprimida(demanda)
    with t5:
        aba_oferta(df_of)


if __name__ == "__main__":
    main()
