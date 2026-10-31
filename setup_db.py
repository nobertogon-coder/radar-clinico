import sqlite3
import os

def criar_banco_dados():
    db_name = "clinica.db"
    if os.path.exists(db_name):
        os.remove(db_name)
        
    with sqlite3.connect(db_name) as conn:
        cursor = conn.cursor()
        
        # 1. Criação das Tabelas
        cursor.execute("CREATE TABLE usuarios (id INTEGER PRIMARY KEY, usuario TEXT, senha TEXT)")
        cursor.execute("CREATE TABLE antibioticos (id INTEGER PRIMARY KEY, nome TEXT, classe TEXT, vias TEXT, tempo_tto_padrao TEXT, dose_ataque TEXT, dose_padrao TEXT, cuidados_pkpd TEXT, focos_compativeis TEXT)")
        cursor.execute("CREATE TABLE regras_renais (id INTEGER PRIMARY KEY, antibiotico_id INTEGER, faixa_nome TEXT, clcr_min REAL, clcr_max REAL, conduta TEXT)")
        cursor.execute("CREATE TABLE interacoes_db (id INTEGER PRIMARY KEY, farmaco_a TEXT, farmaco_b TEXT, gravidade TEXT, detalhe TEXT)")
        cursor.execute("CREATE TABLE interacoes_alimento (id INTEGER PRIMARY KEY, farmaco TEXT, regra_dieta TEXT)")
        cursor.execute("CREATE TABLE interacoes_doenca (id INTEGER PRIMARY KEY, termo_farmaco TEXT, comorbidade TEXT, alerta TEXT)")
        cursor.execute("CREATE TABLE alergias_cruzadas (id INTEGER PRIMARY KEY, classe_alergia TEXT, farmaco_prescrito TEXT, risco TEXT)")
        
        # 2. Utilizador de Acesso
        cursor.execute("INSERT INTO usuarios (usuario, senha) VALUES ('farmacia', 'radar2026')")

        # 3. Antimicrobianos Essenciais (Foco Enfermaria)
        atbs = [
            ("Ceftriaxona (Rocefin)", "Cefalosporina 3ª Ger.", "EV / IM", "5-7d", "1g a 2g", "1g a 2g 24/24h", "Sem ajuste para ClCr isolado. Evitar Ringer Lactato simultâneo.", "PAC, ITU", [("Qualquer", 0, 999, "1g a 2g EV 24/24h"), ("HDI", -1, -1, "Manter dose plena")]),
            ("Azitromicina (Zithromax)", "Macrolídeo", "EV / VO", "3-5d", "500mg", "500mg 24/24h", "Não requer ajuste renal. Risco de QTc.", "PAC, Exacerbação DPOC", [("Qualquer", 0, 999, "500mg 24/24h"), ("HDI", -1, -1, "Manter dose plena")]),
            ("Cefepima (Maxcef)", "Cefalosporina 4ª Ger.", "EV", "7-10d", "1g a 2g", "1g a 2g 8/8h ou 12/12h", "Alto risco de neurotoxicidade se não ajustado.", "Pneumonia, ITU Complicada", [("> 60", 60, 999, "2g EV 8/8h ou 12/12h"), ("30-59", 30, 59.9, "1g a 2g EV 12/12h"), ("11-29", 11, 29.9, "1g a 2g EV 24/24h"), ("< 11", 0, 10.9, "500mg a 1g EV 24/24h"), ("HDI", -1, -1, "1g no D1, depois 500mg 24/24h pós-diálise")]),
            ("Ciprofloxacino (Cipro)", "Fluoroquinolona", "EV / VO", "7d", "400mg EV / 500mg VO", "400mg EV / 500mg VO 12/12h", "Quelado por cátions (Ca, Fe, Mg). Risco de delírio em idosos.", "ITU, Foco Abdominal", [("> 50", 50, 999, "Dose plena 12/12h"), ("30-50", 30, 49.9, "400mg EV 12/12h"), ("< 30", 0, 29.9, "400mg EV 24/24h"), ("HDI", -1, -1, "Administrar pós-diálise")]),
            ("Teicoplanina (Targocid)", "Glicopeptídeo", "EV / IM", "7-14d", "6 mg/kg (3 a 5 doses)", "6 mg/kg 24/24h", "Exige 3 a 5 doses de ataque (12/12h) para atingir steady-state.", "Pele/Partes Moles, Osteomielite", [("Qualquer (Ataque)", 0, 999, "Dose de ataque normal independente do ClCr"), ("> 60", 60, 999, "Manter dose plena 24/24h"), ("< 60", 0, 59.9, "Reduzir dose em 50% após o 4º dia.")]),
            ("Linezolida (Zyvox)", "Oxazolidinona", "EV / VO", "10-14d", "600mg", "600mg EV/VO 12/12h", "Biodisponibilidade VO 100%. Inibidor IMAO fraco. Monitorar plaquetas.", "MRSA, VRE, Infecção de Pele", [("Qualquer", 0, 999, "600mg 12/12h. Sem ajuste renal."), ("HDI", -1, -1, "600mg 12/12h.")]),
            ("Vancomicina", "Glicopeptídeo", "EV", "7-14d", "20-25 mg/kg", "15-20 mg/kg 12/12h", "Guiar obrigatoriamente por nível de vale sérico (15-20 mcg/mL).", "Infecção de Cateter, Pele/Partes Moles", [("> 50", 50, 999, "15-20 mg/kg 12/12h"), ("20-49", 20, 49.9, "15-20 mg/kg 24/24h"), ("< 20", 0, 19.9, "Ataque 15mg/kg e guiar por nível"), ("HDI", -1, -1, "Ataque 20 mg/kg. Redosar guiado por nível.")]),
            ("Piperacilina + Tazobactam", "Penicilina+Inibidor", "EV", "7-10d", "4,5g EV", "4,5g EV 6/6h", "Associação com Vancomicina aumenta taxa de LRA.", "Foco Abdominal, Pneumonia", [("> 50", 50, 999, "4,5g EV 6/6h"), ("20-50", 20, 49.9, "3,375g EV 6/6h"), ("< 20", 0, 19.9, "2,25g EV 6/6h ou 8/8h"), ("HDI", -1, -1, "2,25g 8/8h + suplemento 0,75g pós-diálise")]),
            ("Meropenem", "Carbapenêmico", "EV", "7-10d", "1g a 2g EV", "1g EV 8/8h", "Tempo-dependente (%T > MIC). Infusão prolongada de 3h.", "Foco Abdominal Complicado", [("> 50", 50, 999, "1g EV 8/8h"), ("26-50", 26, 49.9, "1g EV 12/12h"), ("10-25", 10, 25.9, "500mg EV 12/12h"), ("< 10", 0, 9.9, "500mg EV 24/24h"), ("HDI", -1, -1, "500mg EV 24h pós-diálise")]),
            ("Clindamicina", "Lincosamida", "EV / VO", "7-10d", "600mg", "600mg EV/VO 6/6h ou 8/8h", "ALERTA: Maior risco para colite por C. difficile.", "Infecção Odontogênica, Pele", [("Qualquer", 0, 999, "Dose plena mantida. Ajustar apenas em falência hepática severa."), ("HDI", -1, -1, "Manter dose plena.")]),
        ]
        for n, c, v, t, da, dp, pk, f, regras in atbs:
            cursor.execute("INSERT INTO antibioticos (nome, classe, vias, tempo_tto_padrao, dose_ataque, dose_padrao, cuidados_pkpd, focos_compativeis) VALUES (?,?,?,?,?,?,?,?)", (n, c, v, t, da, dp, pk, f))
            atb_id = cursor.lastrowid
            for fx, cmin, cmax, cond in regras:
                cursor.execute("INSERT INTO regras_renais (antibiotico_id, faixa_nome, clcr_min, clcr_max, conduta) VALUES (?,?,?,?,?)", (atb_id, fx, cmin, cmax, cond))

        # 4. Sonda Nasoenteral
        dietas = [
            ("fenitoina", "ALERTA SNE: Absorção reduzida por quelação ao tubo. Pausar dieta 2h antes e 2h após a dose."),
            ("levotiroxina", "ALERTA SNE: Quelação no TGI por proteínas. Administrar em jejum, pausar dieta 1h antes."),
            ("ciprofloxacino", "ALERTA SNE: Cátions bivalentes quelam o antibiótico. Pausar dieta 1h antes e 2h após.")
        ]
        for f, r in dietas: cursor.execute("INSERT INTO interacoes_alimento (farmaco, regra_dieta) VALUES (?, ?)", (f, r))

        # 5. Interações Fármaco x Fármaco
        interacoes = [
            ("omeprazol", "clopidogrel", "Grave / Monitorar", "Omeprazol inibe CYP2C19. Falha antiplaquetária. Trocar para Pantoprazol."),
            ("varfarina", "cetoprofeno", "Grave / Contraindicada", "Risco hemorrágico digestivo alto. AINEs lesam barreira gástrica."),
            ("espironolactona", "cloreto de potassio", "Grave / Contraindicada", "Risco iminente de hipercalemia fatal."),
            ("tramadol", "ondansetrona", "Alerta Clínico", "Ondansetrona bloqueia 5-HT3 reduzindo efeito do tramadol."),
            ("meropenem", "valproato", "Grave / Contraindicada", "Meropenem reduz Ácido Valproico em até 80% em 24h. Risco de convulsão."),
            ("linezolida", "fluoxetina", "Grave / Contraindicada", "Risco de Síndrome Serotoninérgica fatal (Linezolida é IMAO reversível).")
        ]
        for fa, fb, grav, det in interacoes: cursor.execute("INSERT INTO interacoes_db (farmaco_a, farmaco_b, gravidade, detalhe) VALUES (?,?,?,?)", (fa, fb, grav, det))

        # 6. Interações Fármaco x Doença (Comorbilidades)
        doencas = [
            ("cetoprofeno", "icc", "ALERTA CARDIOLÓGICO: AINEs em Insuficiência Cardíaca precipitam retenção hídrica e Edema Agudo de Pulmão."),
            ("ibuprofeno", "icc", "ALERTA CARDIOLÓGICO: AINEs em Insuficiência Cardíaca precipitam retenção hídrica."),
            ("diclofenaco", "icc", "ALERTA CARDIOLÓGICO: AINEs em Insuficiência Cardíaca precipitam retenção hídrica e EAP."),
            ("propranolol", "asma", "ALERTA PNEUMOLÓGICO: Betabloqueadores não-seletivos podem induzir broncoespasmo severo em asmáticos/DPOC."),
            ("carvedilol", "asma", "ALERTA PNEUMOLÓGICO: Pode piorar a reatividade brônquica no DPOC/Asma."),
            ("cefepima", "epilepsia", "ALERTA NEUROLÓGICO: Risco aumentado de rebaixamento do limiar convulsivo e status epilepticus."),
            ("meropenem", "epilepsia", "ALERTA NEUROLÓGICO: Risco de neurotoxicidade e crises convulsivas de escape."),
            ("ciprofloxacino", "epilepsia", "ALERTA NEUROLÓGICO: Quinolonas podem precipitar crises em doentes epiléticos."),
            ("metronidazol", "hepatopatia", "ALERTA HEPÁTICO: Disfunção hepática grave (Child-Pugh C) requer aumento do intervalo do Metronidazol para 12/12h."),
            ("clindamicina", "hepatopatia", "ALERTA HEPÁTICO: Em hepatopatia grave, meia-vida é muito prolongada. Ajustar posologia."),
            ("fluconazol", "hepatopatia", "ALERTA HEPÁTICO: Risco de agravamento da lesão hepática. Monitorizar transaminases de perto.")
        ]
        for f, c, a in doencas: cursor.execute("INSERT INTO interacoes_doenca (termo_farmaco, comorbidade, alerta) VALUES (?,?,?)", (f, c, a))

        # 7. Alergias Cruzadas
        alergias = [
            ("penicilina", "ceftriaxona", "Risco de Reatividade Cruzada (1 a 3%). Monitorizar 1ª dose."),
            ("penicilina", "cefepima", "Risco de Reatividade Cruzada (1 a 3%). Monitorizar 1ª dose."),
            ("penicilina", "meropenem", "Risco de Reatividade Cruzada (< 1%). Geralmente seguro, mas requer vigilância.")
        ]
        for ac, fp, r in alergias: cursor.execute("INSERT INTO alergias_cruzadas (classe_alergia, farmaco_prescrito, risco) VALUES (?,?,?)", (ac, fp, r))

        conn.commit()
        print("Banco 'clinica.db' gerado com SUCESSO! Inclui Doenças, Alergias e Hepatopatia.")

if __name__ == "__main__":
    criar_banco_dados()
