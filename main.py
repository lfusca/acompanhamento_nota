###############################################################################
#  📊 Acompanhamento de Desempenho – FIAP Moodle + Streamlit                  #
#  Versão: 05-jul-2025                                                        #
#  • Credenciais Oracle lidas apenas de st.secrets (TOML)                     #
#  • Conexão python-oracledb (pool)                                           #
#  • Botão 🔄 Atualizar dados (cache clear + rerun)                            #
#  • Sanitiza espaços em branco (strip)                                       #
#  • Ranking “Ir Além”                                                        #
###############################################################################
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import oracledb
from streamlit.errors import StreamlitSecretNotFoundError

# --------------------------------------------------------------------------- #
# CREDENCIAIS – exclusivamente via st.secrets                                 #
# --------------------------------------------------------------------------- #
try:
    cfg = st.secrets["oracle"]
    ORCL_USER = cfg["user"]
    ORCL_PWD  = cfg["password"]
    ORCL_DSN  = cfg["dsn"]
except (KeyError, StreamlitSecretNotFoundError):
    st.error(
        "⚠️ Credenciais Oracle não encontradas.\n\n"
        "• Produção: cole o bloco TOML em  Settings ▸ Secrets\n"
        "• Local: crie .streamlit/secrets.toml com o mesmo bloco"
    )
    st.stop()

# --------------------------------------------------------------------------- #
# POOL ORACLE                                                                 #
# --------------------------------------------------------------------------- #
POOL = oracledb.create_pool(
    user      = ORCL_USER,
    password  = ORCL_PWD,
    dsn       = ORCL_DSN,
    min       = 1, max = 4, increment = 1, timeout = 60
)

# --------------------------------------------------------------------------- #
# FUNÇÕES                                                                     #
# --------------------------------------------------------------------------- #
def _fetch_df(sql: str, params=()):
    """Executa consulta e devolve DataFrame, convertendo CLOB→str e strip()."""
    with POOL.acquire() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d[0].lower() for d in cur.description]

        def fix(row):
            return [
                (c.read() if isinstance(c, oracledb.LOB) else c).rstrip()
                if isinstance(c, str) else c
                for c in row
            ]

        return pd.DataFrame([fix(r) for r in cur.fetchall()], columns=cols)


@st.cache_data(show_spinner=False)
def carregar_dados():
    atv = _fetch_df("""
        SELECT id_atividade, turma, fase,
               nome_atividade, nota_maxima
        FROM   atividades
    """)
    alu = _fetch_df("""
        SELECT id_atividade, id_aluno, rm, nome,
               nota, feedback, ir_alem
        FROM   alunos
    """)

    # limpeza de textos
    for df in (atv, alu):
        for col in ("id_atividade", "turma", "fase", "rm", "nome"):
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip()

    alu["nota"] = pd.to_numeric(
        alu["nota"].astype(str).str.replace(",", "."), errors="coerce"
    )

    dados = alu.merge(atv, on="id_atividade", how="left")
    dados["percentual"] = (
        (dados["nota"] / dados["nota_maxima"]) * 100
    ).round(3).clip(upper=100)

    return dados.sort_values(["fase", "nome_atividade"])


def resumo_alunos(df):
    def pct_faltas(x): return round(100 * x.isna().sum() / len(x))
    res = (df.groupby(["id_aluno", "rm", "nome"])["percentual"]
             .agg(media_pct="mean",
                  notas_lancadas=lambda x: x.notna().sum(),
                  pct_sem_nota=pct_faltas)
             .reset_index())
    res["media_pct"] = res["media_pct"].round(1)
    return (res.rename(columns={"rm":"RM", "nome":"Nome",
                                "media_pct":"Média (%)",
                                "notas_lancadas":"Notas lançadas",
                                "pct_sem_nota":"% sem nota"})
              .sort_values("Nome"))

# --------------------------------------------------------------------------- #
# INTERFACE STREAMLIT                                                         #
# --------------------------------------------------------------------------- #
st.title("📊 Acompanhamento de Desempenho dos Alunos")

if st.sidebar.button("🔄 Atualizar dados"):
    carregar_dados.clear()
    (st.rerun if hasattr(st, "rerun") else st.experimental_rerun)()

dados = carregar_dados()
if dados.empty:
    st.warning("Banco vazio. Cadastre atividades primeiro.")
    st.stop()

# ------------------------ Turma ------------------------------------------- #
turmas = sorted(dados["turma"].dropna().unique())
turma_sel = st.selectbox("Turma", turmas)
df_turma = dados[dados["turma"] == turma_sel]
if df_turma.empty:
    st.info("Sem dados para esta turma.")
    st.stop()

# ------------------------ Resumo geral ------------------------------------ #
st.subheader("Resumo geral da turma")
resumo = resumo_alunos(df_turma)
st.dataframe(resumo.drop(columns="id_aluno"),
             hide_index=True, use_container_width=True)

# ------------------------ Seleção de aluno -------------------------------- #
st.subheader("Evolução individual")
label_map = {f"{r.Nome} — {r.RM}": r.id_aluno for r in resumo.itertuples()}
aluno_sel = st.selectbox("Aluno", list(label_map.keys()))
id_aluno = label_map[aluno_sel]

df_aluno = (df_turma[df_turma["id_aluno"] == id_aluno]
            .sort_values(["fase", "nome_atividade"]))

if df_aluno.empty:
    st.info("Este aluno ainda não tem notas.")
else:
    # -------- Gráfico ---------------------------------------------------- #
    fig, ax = plt.subplots(figsize=(6, 3))
    x_lbl = df_aluno["fase"] + " - " + df_aluno["nome_atividade"]
    ax.plot(x_lbl, df_aluno["percentual"], marker="o")
    ax.set_ylabel("Nota (% da nota máxima)")
    ax.set_xlabel("Atividade")
    ax.set_ylim(0, 100)
    ax.set_xticklabels(x_lbl, rotation=45, ha="right")
    ax.grid(alpha=0.3)
    st.pyplot(fig)

    # -------- Tabela de detalhes ---------------------------------------- #
    st.markdown("#### Notas detalhadas")
    tabela = (df_aluno[["fase", "nome_atividade", "nota",
                        "nota_maxima", "percentual",
                        "feedback", "ir_alem"]]
              .rename(columns={"fase":"Fase",
                               "nome_atividade":"Atividade",
                               "nota":"Nota obtida",
                               "nota_maxima":"Nota máxima",
                               "percentual":"%",
                               "feedback":"Feedback",
                               "ir_alem":"Ir Além"}))
    tabela[["Nota obtida", "Nota máxima", "%"]] = \
        tabela[["Nota obtida", "Nota máxima", "%"]].round(3)
    st.dataframe(tabela, hide_index=True, use_container_width=True)

# ------------------------ Ranking “Ir Além” ------------------------------- #
st.subheader("🏅 Ranking – quem mais foi marcado como “Ir Além”")

ranking = (df_turma[df_turma["ir_alem"].str.upper() == "SIM"]
           .groupby(["rm", "nome"])["ir_alem"]
           .size()
           .reset_index(name="Quantidade")
           .sort_values("Quantidade", ascending=False))

if ranking.empty:
    st.info("Ainda não há nenhum “Ir Além” para esta turma.")
else:
    ranking = ranking.rename(columns={"rm": "RM", "nome": "Nome"})
    st.dataframe(ranking, hide_index=True, use_container_width=True)
