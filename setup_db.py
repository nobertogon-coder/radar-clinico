import sqlite3
import os

def setup_database():
    if os.path.exists("radar_clinico.db"):
        os.remove("radar_clinico.db")
        print("Base de dados antiga removida. Criando uma nova...")

    conn = sqlite3.connect("radar_clinico.db")
    cursor = conn.cursor()
    
    # 1. Usuários
    cursor.execute("CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL)")
    cursor.execute("INSERT OR IGNORE INTO usuarios (username, password, role) VALUES ('admin', 'admin', 'admin')")

    # 2. Antimicrobianos (AGORA COM DOSES NUMÉRICAS)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS antimicrobianos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_generico TEXT UNIQUE NOT NULL,
            nomes_comerciais TEXT,
            indicacao TEXT,
            dose_max_padrao_mg INTEGER,
            dose_max_clcr30_50_mg INTEGER,
            dose_max_clcr10_30_mg INTEGER,
            dose_max_clcr10_mg INTEGER,
            monitorizacao TEXT,
            farmacotecnia TEXT
        )
    ''')
    atbs = [
        ("Meropenem", "Meronem", "Infecções Graves", 3000, 2000, 1000, 500, "Função renal, risco convulsivo", "Diluir em 100mL SF. Infusão estendida (3h)."),
        ("Imipenem + Cilastatina", "Tienam", "Geral", 2000, 1000, 500, 250, "Risco convulsivo alto em disfunção renal", "Diluir em 100mL SF. Não usar via IM."),
        ("Ertapenem", "Invanz", "Geral", 1000, 1000, 500, 500, "Função renal, hemograma", "Diluir em 50mL SF. Não diluir em SG."),
        ("Ceftriaxona", "Rocefin, Triaxin", "Geral", 2000, 2000, 2000, 2000, "Lama biliar, função hepática", "Incompatível com cálcio (Ringer Lactato)."),
        ("Cefepima", "Maxefime", "Geral", 6000, 4000, 2000, 1000, "Neurotoxicidade, estado mental", "Diluir em 50-100mL. Infusão em 30 min."),
        ("Piperacilina + Tazobactam", "Tazocin", "Geral", 18000, 13500, 9000, 6750, "Eletrólitos (Na+), plaquetas", "Infusão estendida em 4h recomendada."),
        ("Vancomicina", "Vancocina", "Geral", 2000, 1000, 500, 500, "Vancocinemia, creatinina seriada", "Concentração máx 5mg/mL. Infusão lenta (>60 min).")
    ]
    cursor.executemany("INSERT OR IGNORE INTO antimicrobianos (nome_generico, nomes_comerciais, indicacao, dose_max_padrao_mg, dose_max_clcr30_50_mg, dose_max_clcr10_30_mg, dose_max_clcr10_mg, monitorizacao, farmacotecnia) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", atbs)

    # 3. Interações
    cursor.execute("CREATE TABLE IF NOT EXISTS interacoes (id INTEGER PRIMARY KEY AUTOINCREMENT, droga_a TEXT NOT NULL, droga_b TEXT NOT NULL, gravidade TEXT, mecanismo TEXT, conduta TEXT)")
    interacoes = [
        ("Vancomicina", "Piperacilina + Tazobactam", "Grave", "Potencialização de nefrotoxicidade sinérgica", "Monitorar creatinina e débito urinário diariamente; considerar trocar beta-lactâmico."),
        ("Ciprofloxacino", "Amiodarona", "Maior", "Prolongamento sinérgico do intervalo QTc", "Monitorização eletrocardiográfica diária; avaliar alternativa antimicrobiana."),
        ("Omeprazol", "Clopidogrel", "Moderada", "Inibição competitiva da CYP2C19 com redução de eficácia antiagregante", "Substituir por Pantoprazol se indicado protetor gástrico.")
    ]
    cursor.executemany("INSERT OR IGNORE INTO interacoes (droga_a, droga_b, gravidade, mecanismo, conduta) VALUES (?, ?, ?, ?, ?)", interacoes)

    # 4. Regras Farmacotécnicas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS regras_farmacotecnicas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            farmaco TEXT NOT NULL,
            condicao TEXT NOT NULL,
            alerta TEXT NOT NULL
        )
    ''')
    regras_farmaco = [
        ("dipirona", "ad", "Água Destilada pode causar dor e flebite na infusão. Sugere-se SF 0,9% ou SG 5%."),
        ("dipirona", "agua destilada", "Água Destilada pode causar dor e flebite na infusão. Sugere-se SF 0,9% ou SG 5%."),
        ("fenitoina", "sg", "Incompatível com Soro Glicosado (risco de cristalização). Utilizar apenas SF 0,9%."),
        ("ampicilina", "sg", "Baixa estabilidade em Soro Glicosado. Diluir exclusivamente em SF 0,9%."),
        ("daptomicina", "sg", "Incompatível com Soro Glicosado. Diluir em SF 0,9% ou Ringer Lactato."),
        ("omeprazol", "sg", "Menos estável em SG 5%. Recomenda-se reconstituição/diluição em SF 0,9%.")
    ]
    cursor.executemany("INSERT OR IGNORE INTO regras_farmacotecnicas (farmaco, condicao, alerta) VALUES (?, ?, ?)", regras_farmaco)

    # 5. Comorbidades e Riscos (NOVO)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS comorbidades_risco (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            comorbidade TEXT NOT NULL,
            farmaco_contraindicado TEXT NOT NULL,
            alerta TEXT NOT NULL
        )
    ''')
    comorbidades = [
        ("Hepatopatia", "Tigeciclina", "Uso cauteloso em hepatopatas graves (Child-Pugh C). Reduzir dose de manutenção pela metade."),
        ("DRC", "Nitrofurantoína", "Contraindicado em ClCr < 30 mL/min por falta de eficácia e risco de toxicidade sistêmica."),
        ("Hepatopatia", "Ceftriaxona", "Risco de pseudolitíase biliar. Monitorizar função hepática.")
    ]
    cursor.executemany("INSERT OR IGNORE INTO comorbidades_risco (comorbidade, farmaco_contraindicado, alerta) VALUES (?, ?, ?)", comorbidades)

    conn.commit()
    conn.close()
    print("Base de dados criada/atualizada com sucesso!")

if __name__ == "__main__":
    setup_database()
