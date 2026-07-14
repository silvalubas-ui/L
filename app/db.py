"""
Módulo de Banco de Dados (db.py) - Versão Estruturada
==================================================
Gerencia a conexão SQLite, tabelas relacionais de profissionais,
procedimentos, horários de funcionamento e agendamentos estruturados.
"""

import sqlite3
import os
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Define o caminho do banco de dados na pasta do projeto
DB_PATH = Path(os.environ.get("LURI_DB_PATH", Path(__file__).parent / "luri.db"))   

def obter_conexao():
    """Retorna uma conexão ativa com o banco de dados SQLite com suporte a chaves estrangeiras."""
    os.makedirs(DB_PATH.parent, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn
def init_db():
    """Cria a estrutura relacional completa da clínica se não existir."""
    logger.info("Inicializando o banco de dados relacional...")
    with obter_conexao() as conn:
        cursor = conn.cursor()
        
        # 1. Informações e Horários de Funcionamento da Clínica
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS config_clinica (
                chave TEXT PRIMARY KEY,
                valor TEXT NOT NULL
            )
        """)
        
        # 2. Cadastro de Profissionais
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS profissionais (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                especialidade TEXT NOT NULL,
                ativo INTEGER DEFAULT 1
            )
        """)
        
        # 3. Cadastro de Procedimentos (com duração e preço tabelados)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS procedimentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL UNIQUE,
                duracao_minutos INTEGER NOT NULL DEFAULT 30,
                preco REAL
            )
        """)
        
        # 4. Histórico de Mensagens do Chat
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mensagens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sessao TEXT NOT NULL,
                origem TEXT NOT NULL, -- 'usuario' ou 'agente'
                texto TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)
        
        # 5. Atendimentos Ativos (Estado atual do fluxo)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS atendimentos (
                sessao TEXT PRIMARY KEY,
                nome TEXT,
                telefone TEXT,
                status TEXT DEFAULT 'aberto', -- 'aberto', 'concluido', 'arquivado'
                ultima_interacao TEXT NOT NULL
            )
        """)
        
        # 6. Consultas (Totalmente estruturada com Chaves Estrangeiras)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS consultas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome_paciente TEXT NOT NULL,
                telefone_paciente TEXT NOT NULL,
                profissional_id INTEGER NOT NULL,
                procedimento_id INTEGER NOT NULL,
                data_hora TEXT NOT NULL,
                criado_em TEXT NOT NULL,
                FOREIGN KEY (profissional_id) REFERENCES profissionais(id),
                FOREIGN KEY (procedimento_id) REFERENCES procedimentos(id)
            )
        """)
        conn.commit()

# --- Funções de Consulta e Listagem ---

def listar_profissionais():
    """Retorna todos os profissionais ativos cadastrados."""
    with obter_conexao() as conn:
        rows = conn.execute("SELECT * FROM profissionais WHERE ativo = 1").fetchall()
        return [dict(r) for r in rows]

def listar_procedimentos():
    """Retorna todos os procedimentos e tabelas de preço disponíveis."""
    with obter_conexao() as conn:
        rows = conn.execute("SELECT * FROM procedimentos").fetchall()
        return [dict(r) for r in rows]

def obter_horario_funcionamento():
    """Retorna as configurações de horário e dados cadastrais da clínica em um dicionário."""
    with obter_conexao() as conn:
        rows = conn.execute("SELECT * FROM config_clinica").fetchall()
        return {r["chave"]: r["valor"] for r in rows}

def listar_mensagens(sessao: str = None):
    """Lista o histórico de mensagens, opcionalmente filtrado por sessão."""
    query = "SELECT origem, texto, timestamp FROM mensagens"
    args = ()
    if sessao:
        query += " WHERE sessao = ? ORDER BY id ASC"
        args = (sessao,)
    else:
        query += " ORDER BY id ASC"
        
    with obter_conexao() as conn:
        rows = conn.execute(query, args).fetchall()
        return [dict(r) for r in rows]
    
def carregar_historico(sessao: str) -> list:
    """Retorna o histórico de mensagens de uma sessão no formato esperado pela API da OpenAI."""
    mensagens = listar_mensagens(sessao)
    mapa_origem = {"usuario": "user", "agente": "assistant"}
    return [
        {"role": mapa_origem.get(m["origem"], "user"), "content": m["texto"]}
        for m in mensagens
    ]

def listar_atendimentos():
    """Retorna a lista de todas as sessões ativas e status de atendimento na clínica."""
    with obter_conexao() as conn:
        rows = conn.execute("SELECT * FROM atendimentos ORDER BY ultima_interacao DESC").fetchall()
        return [dict(r) for r in rows]

def buscar_por_telefone(telefone: str):
    """Busca consultas trazendo os dados reais do profissional e do procedimento via JOIN."""
    query = """
        SELECT c.id, c.nome_paciente, c.telefone_paciente, c.data_hora, 
               p.nome AS profissional, p.especialidade,
               pr.nome AS procedimento, pr.duracao_minutos, pr.preco
        FROM consultas c
        JOIN profissionais p ON c.profissional_id = p.id
        JOIN procedimentos pr ON c.procedimento_id = pr.id
        WHERE c.telefone_paciente = ?
        ORDER BY c.data_hora ASC
    """
    with obter_conexao() as conn:
        rows = conn.execute(query, (telefone,)).fetchall()
        return [dict(r) for r in rows]

# --- Funções de Escrita e Mutação ---

def salvar_mensagem(sessao: str, origem: str, texto: str):
    """Registra uma mensagem no histórico de chat e atualiza o atendimento ativo."""
    agora = datetime.now().isoformat()
    with obter_conexao() as conn:
        conn.execute(
            "INSERT INTO mensagens (sessao, origem, texto, timestamp) VALUES (?, ?, ?, ?)",
            (sessao, origem, texto, agora)
        )
        conn.execute("""
            INSERT INTO atendimentos (sessao, ultima_interacao) 
            VALUES (?, ?)
            ON CONFLICT(sessao) DO UPDATE SET ultima_interacao = excluded.ultima_interacao
        """, (sessao, agora))
        conn.commit()

def agendar_estruturado(nome_paciente: str, telefone_paciente: str, profissional_id: int, procedimento_id: int, data_hora: str):
    """Realiza o agendamento amarrado estritamente aos IDs relacionais do banco."""
    agora = datetime.now().isoformat()
    with obter_conexao() as conn:
        conn.execute("""
            INSERT INTO consultas (nome_paciente, telefone_paciente, profesional_id, procedimento_id, data_hora, criado_em)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (nome_paciente, telefone_paciente, profissional_id, procedimento_id, data_hora, agora))
        
        conn.execute("""
            UPDATE atendimentos SET nome = ?, telefone = ?, status = 'concluido' WHERE sessao = ?
        """, (nome_paciente, telefone_paciente, telefone_paciente))
        conn.commit()
    logger.info(f"Consulta estruturada agendada com sucesso para {nome_paciente}.")
    return {"status": "sucesso", "mensagem": "Agendamento estruturado realizado com sucesso."}

def seed_demo():
    """Limpa o banco completo e popula com os dados corporativos e as simulações fictícias."""
    logger.info("Executando seed de demonstração com tabelas estruturadas...")
    agora = datetime.now()
    
    # Define data dinâmica para o agendamento de teste bater sempre no futuro próximo
    amanha_mesmo_horario = (agora + timedelta(days=1)).replace(minute=0, second=0, microsecond=0).isoformat()
    
    with obter_conexao() as conn:
        conn.execute("DROP TABLE IF EXISTS consultas")
        conn.execute("DROP TABLE IF EXISTS atendimentos")
        conn.execute("DROP TABLE IF EXISTS mensagens")
        conn.execute("DROP TABLE IF EXISTS procedimentos")
        conn.execute("DROP TABLE IF EXISTS profissionais")
        conn.execute("DROP TABLE IF EXISTS config_clinica")
        conn.commit()
    
    # Recria as tabelas estruturadas limpas
    init_db()
    
    with obter_conexao() as conn:
        # 1. Inserindo dados cadastrais e regras da clínica
        configuracoes = [
            ("nome_clinica", "Clínica Sorriso Pleno"),
            ("horario_abertura", "08:00"),
            ("horario_fechamento", "18:00"),
            ("inicio_almoco", "12:00"),
            ("fim_almoco", "13:30")
        ]
        conn.executemany("INSERT INTO config_clinica (chave, valor) VALUES (?, ?)", configuracoes)
        
        # 2. Inserindo Corpo Clínico Profissional
        profissionais = [
            ("Dr. Henrique Prado", "Ortodontia"),
            ("Dra. Renata Silva", "Clínica Geral e Limpeza")
        ]
        conn.executemany("INSERT INTO profissionais (nome, especialidade) VALUES (?, ?)", profissionais)
        
        # 3. Inserindo Catálogo de Procedimentos
        procedimentos = [
            ("Limpeza", 45, 150.00),
            ("Avaliação", 30, 80.00),
            ("Clareamento", 60, 400.00)
        ]
        conn.executemany("INSERT INTO procedimentos (nome, duracao_minutos, preco) VALUES (?, ?, ?)", procedimentos)

        # 4. Inserindo Registro Fictício de Paciente Antiga (Para o teste de remarcação)
        # Ana Paula cadastrada com uma Limpeza (Procedimento ID: 1) com a Dra. Renata (Profissional ID: 2)
        conn.execute(
            "INSERT INTO atendimentos (sessao, nome, telefone, status, ultima_interacao) VALUES (?, ?, ?, ?, ?)",
            ("+5511990001111", "Ana Paula", "+5511990001111", "concluido", agora.isoformat())
        )
        conn.execute("""
            INSERT INTO consultas (nome_paciente, telefone_paciente, profissional_id, procedimento_id, data_hora, criado_em)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("Ana Paula", "+5511990001111", 2, 1, amanha_mesmo_horario, agora.isoformat()))
        
        conn.commit()
        
    return {
        "status": "seed_completo", 
        "mensagem": "Banco de dados relacional populado com sucesso (Clínica Sorriso Pleno configurada)."
    }

    def salvar_historico(sessao: str, historico: list):
    """Persiste as mensagens novas (texto puro) de uma sessão de conversa.

    Importante: espera receber só as mensagens NOVAS desde o último carregamento
    (não o histórico inteiro), para não duplicar o que já está salvo.
    """
    mapa_origem = {"user": "usuario", "assistant": "agente"}
    for msg in historico:
        role = msg.get("role")
        if role not in mapa_origem:
            continue  # ignora mensagens de sistema e de ferramentas ("tool")
        conteudo = msg.get("content")
        if not isinstance(conteudo, str) or not conteudo.strip():
            continue  # ignora blocos de chamada de ferramenta (não são texto puro)
        salvar_mensagem(sessao, mapa_origem[role], conteudo)