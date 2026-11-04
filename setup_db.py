import sqlite3

def setup_database():
    conn = sqlite3.connect("radar_clinico.db")
    cursor = conn.cursor()
    
    # 1. Tabela de Antimicrobianos com Suporte a Nomes Comerciais
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS antimicrobianos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_generico TEXT UNIQUE NOT NULL,
            nomes_comerciais TEXT,
            dose_padrao TEXT,
            ajuste_clcr_30_50 TEXT,
            ajuste_clcr_10_30 TEXT,
            ajuste_clcr_menor_10 TEXT,
            ajuste_hemodialise TEXT,
            monitorizacao TEXT,
            farmacotecnia TEXT
        )
    """)
    
    # 2. Lista Expandida (Genérico, Comercial, Dose Padrão, ClCr 30-50, ClCr 10-30, ClCr <10, HD, Monitorização, Farmacotécnica)
    atbs = [
        ("Meropenem", "Meronem", "1g a cada 8h", "1g a cada 12h", "500mg a cada 12h", "500mg a cada 24h", "500mg pós-HD", "Função renal, risco convulsivo", "Diluir em 100mL SF. Infusão estendida (3h)."),
        ("Imipenem + Cilastatina", "Tienam", "500mg a cada 6h", "250mg a cada 6h", "250mg a cada 12h", "125-250mg a cada 12h", "Dose pós-HD", "Risco convulsivo alto em disfunção renal", "Diluir em 100mL SF. Não usar via IM."),
        ("Ertapenem", "Invanz", "1g a cada 24h", "Sem ajuste (1g 24h)", "500mg a cada 24h", "500mg a cada 24h", "500mg pós-HD", "Função renal, hemograma", "Diluir em 50mL SF. Não diluir em SG."),
        ("Ceftriaxona", "Rocefin, Triaxin", "1g a 2g a cada 24h", "Sem ajuste", "Sem ajuste", "Dose máx 2g/dia", "Sem dose extra", "Lama biliar, função hepática", "Incompatível com cálcio (Ringer Lactato)."),
        ("Cefepima", "Maxefime", "2g a cada 8h", "2g a cada 12h", "1g a cada 12h", "1g a cada 24h", "1g pós-HD", "Neurotoxicidade, estado mental", "Diluir em 50-100mL. Infusão em 30 min."),
        ("Ceftazidima", "Fortaz, Tazicef", "2g a cada 8h", "1g a cada 12h", "1g a cada 24h", "500mg a cada 24h", "500mg pós-HD", "Função renal", "Liberação de gás (CO2) na reconstituição."),
        ("Cefazolina", "Kefazol", "1g a 2g a cada 8h", "1g a 2g a cada 12h", "500mg a 1g a cada 12-24h", "500mg a cada 24h", "Dose extra pós-HD", "Função renal, reações alérgicas", "Profilaxia cirúrgica: 2g (ou 3g se >120kg)."),
        ("Piperacilina + Tazobactam", "Tazocin", "4,5g a cada 6h", "3,375g a cada 6h", "2,25g a cada 6h", "2,25g a cada 8h", "2,25g a 8h + 0,75g pós-HD", "Eletrólitos (Na+), plaquetas", "Infusão estendida em 4h recomendada."),
        ("Amoxicilina + Clavulanato", "Sigma-Clav, Clavulin", "1g/200mg a cada 8h", "1g/200mg a cada 12h", "1g/200mg a cada 24h", "Evitar EV se <10", "Dose pós-HD", "Hepatotoxicidade, diarreia", "Administração EV direta lenta ou infusão curta."),
        ("Oxacilina", "Staficilin-N", "2g a cada 4h", "Sem ajuste", "Sem ajuste", "Sem ajuste", "Sem ajuste", "Hepatotoxicidade, flebite", "Alta osmolaridade; preferir acesso central para doses altas."),
        ("Ampicilina", "Binotal", "2g a cada 4-6h", "Sem ajuste", "2g a cada 8-12h", "2g a cada 12-24h", "Dose pós-HD", "Rash cutâneo, função renal", "Diluir exclusivamente em SF (estabilidade curta)."),
        ("Vancomicina", "Vancocina", "15-20mg/kg a cada 8-12h", "15-20mg/kg a cada 24h", "15-20mg/kg a cada 48h", "Guiar por nível", "Ataque 25mg/kg, guiar nível pré-HD", "Vancocinemia, creatinina seriada", "Concentração máx 5mg/mL. Infusão lenta (>60 min)."),
        ("Teicoplanina", "Targocid", "Ataque 6-12mg/kg; Manut 24h", "Ataque padrão; Manut 50%", "Ataque padrão; Manut 33%", "Ataque padrão; Manut 33%", "Não dialisável", "Função auditiva, renal", "Não agitar o frasco (evitar espuma). Pode ser IM ou EV."),
        ("Daptomicina", "Cubicin", "6-8 mg/kg a cada 24h", "Sem ajuste", "6-8 mg/kg a cada 48h", "6-8 mg/kg a cada 48h", "Dose pós-HD", "CPK semanal (risco miopatia)", "Incompatível com SG 5%. Diluir apenas em SF/Ringer."),
        ("Amicacina", "Novamin", "15mg/kg/dia 1x/dia", "Aumentar intervalo p/ 24-48h", "Guiar por nível", "Dose complementar", "Dose pós-HD", "Ototoxicidade, Nefrotoxicidade", "Infundir em 30-60 min. Inativado por beta-lactâmicos na mesma via."),
        ("Gentamicina", "Garamicina", "5-7mg/kg/dia 1x/dia", "Aumentar intervalo p/ 24-48h", "Guiar por nível", "Dose complementar", "Dose pós-HD", "Ototoxicidade, Nefrotoxicidade", "Peso ideal para obesos. Diluir em 50-100mL."),
        ("Ciprofloxacino", "Cipro", "400mg a cada 12h", "400mg a cada 18-24h", "200-400mg a cada 24h", "200mg a cada 24h", "200mg pós-HD", "ECG (QTc), tendinopatias", "Incompatível com heparina. Infusão em 60 min."),
        ("Levofloxacino", "Levaquin, Tavanic", "750mg a cada 24h", "750mg cada 48h", "750mg 1ª dose, depois 500mg 48h", "500mg a cada 48h", "500mg pós-HD", "Glicemia, QTc, neurotoxicidade", "Fotossensível (proteger da luz se não usar imediatamente)."),
        ("Polimixina B", "Ro-Polimixina", "1,5-2,5 mg/kg/dia div 12h", "Sem ajuste", "Sem ajuste", "Sem ajuste", "Sem dose pós-HD", "Nefrotoxicidade severa", "Cálculo pelo Peso Real. Diluir em SG 5% preferencialmente."),
        ("Colistina", "Coly-Mycin", "Ataque 300mg; Manut 150mg 12h", "150mg a cada 12h", "150mg a cada 24h", "150mg a cada 24h", "75mg a cada 12h (dia HD)", "Nefrotoxicidade, neurotoxicidade", "Monitorar creatinina rigorosamente."),
        ("Linezolida", "Zyvox", "600mg a cada 12h", "Sem ajuste", "Sem ajuste", "Sem ajuste", "600mg pós-HD", "Hemograma (plaquetopenia pós 10 dias)", "Não agitar a bolsa. Não misturar com outras drogas."),
        ("Clindamicina", "Dalacin", "600mg a cada 6-8h", "Sem ajuste", "Sem ajuste", "Sem ajuste", "Sem ajuste", "Diarreia (risco de C. difficile)", "Não exceder 30mg/min na infusão EV."),
        ("Metronidazol", "Flagyl", "500mg a cada 8h", "Sem ajuste", "Sem ajuste", "500mg a cada 12h", "Dose pós-HD", "Neuropatia, reação tipo disulfiram", "Não refrigerar a bolsa EV (risco de cristalização)."),
        ("Tigeciclina", "Tygacil", "Ataque 100mg; Manut 50mg 12h", "Sem ajuste", "Sem ajuste", "Sem ajuste", "Sem ajuste", "Hepatotoxicidade, amilase", "Se Child-Pugh C: Manutenção cai para 25mg 12h."),
        ("Sulfametoxazol + Trimetoprima", "Bactrim", "15-20mg/kg/dia div 6h", "50% da dose padrão", "Evitar ou reduzir 50%", "Evitar", "Dose extra pós-HD", "Hipercalemia, função renal", "Diluição volumo-dependente (restrição hídrica pode ser problema)."),
        ("Azitromicina", "Zitromax", "500mg a cada 24h", "Sem ajuste", "Sem ajuste", "Sem ajuste", "Sem ajuste", "QTc, função hepática", "Concentração máx 2mg/mL. Infusão de 1 a 3h."),
        ("Micafungina", "Mycamine", "100mg a cada 24h", "Sem ajuste", "Sem ajuste", "Sem ajuste", "Sem ajuste", "Hepatotoxicidade", "Proteger bolsa EV da luz."),
        ("Fluconazol", "Zoltec", "400mg a cada 24h", "200mg a cada 24h", "200mg a cada 24h", "200mg a cada 24h", "Dose integral pós-HD", "Hepatotoxicidade, QTc", "Pode reduzir dose em 50% após o ataque se ClCr < 50.")
    ]
    
    cursor.executemany("""
        INSERT OR IGNORE INTO antimicrobianos 
        (nome_generico, nomes_comerciais, dose_padrao, ajuste_clcr_30_50, ajuste_clcr_10_30, ajuste_clcr_menor_10, ajuste_hemodialise, monitorizacao, farmacotecnia)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, atbs)

    # 3. Tabela de Interações
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS interacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            droga_a TEXT NOT NULL,
            droga_b TEXT NOT NULL,
            gravidade TEXT,
            mecanismo TEXT,
            conduta TEXT
        )
    """)
    
    interacoes = [
        ("Vancomicina", "Piperacilina + Tazobactam", "Grave", "Potencialização de nefrotoxicidade sinérgica", "Monitorar creatinina e débito urinário diariamente; considerar trocar beta-lactâmico."),
        ("Ciprofloxacino", "Amiodarona", "Maior", "Prolongamento sinérgico do intervalo QTc", "Monitorização eletrocardiográfica diária; avaliar alternativa antimicrobiana."),
        ("Omeprazol", "Clopidogrel", "Moderada", "Inibição competitiva da CYP2C19 com redução de eficácia antiagregante", "Substituir por Pantoprazol se indicado protetor gástrico.")
    ]
    
    cursor.executemany("""
        INSERT OR IGNORE INTO interacoes (droga_a, droga_b, gravidade, mecanismo, conduta)
        VALUES (?, ?, ?, ?, ?)
    """, interacoes)

    conn.commit()
    conn.close()
    print("Base de dados atualizada com sucesso.")

if __name__ == "__main__":
    setup_database()
    
