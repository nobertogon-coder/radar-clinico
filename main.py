import io
import itertools
import sqlite3
from datetime import date, datetime
from typing import Optional
from fastapi import FastAPI, Form, File, UploadFile
from fastapi.responses import HTMLResponse
from pypdf import PdfReader

app = FastAPI(title="Radar Clínico")
DB_FILE = "clinica.db"

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        # Tabela de Antimicrobianos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS antibioticos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                classe TEXT DEFAULT 'Geral',
                indicacao TEXT NOT NULL,
                tempo_tto TEXT NOT NULL,
                dose_ataque TEXT,
                dose_padrao TEXT NOT NULL
            )
        """)
        
        # Tabela de Ajuste Renal
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS regras_renais (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                antibiotico_id INTEGER,
                faixa_nome TEXT NOT NULL,
                clcr_min REAL NOT NULL,
                clcr_max REAL NOT NULL,
                conduta TEXT NOT NULL,
                FOREIGN KEY (antibiotico_id) REFERENCES antibioticos (id)
            )
        """)

        # Tabela de Interações Medicamentosas (Todos contra Todos)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS interacoes_db (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                farmaco_a TEXT NOT NULL,
                farmaco_b TEXT NOT NULL,
                gravidade TEXT NOT NULL,
                detalhe TEXT NOT NULL
            )
        """)
        conn.commit()

        # Seed inicial de Antimicrobianos
        cursor.execute("SELECT COUNT(*) FROM antibioticos")
        if cursor.fetchone()[0] == 0:
            exemplos_atb = [
                (
                    "Meropenem",
                    "Carbapenêmico",
                    "Infecções intra-abdominais graves, pneumonias nosocomiais, sepse grave.",
                    "7 a 14 dias",
                    "Dose plena inicial (sem redução nas primeiras 24-48h de sepse)",
                    "1g EV de 8/8h (infusão estendida de 3h)",
                    [
                        ("ClCr > 50 mL/min (Normal/Leve)", 50.0, 999.0, "1g EV de 8/8h (infusão de 3h)"),
                        ("ClCr 26 a 50 mL/min (Moderado)", 26.0, 49.9, "1g EV de 12/12h"),
                        ("ClCr 10 a 25 mL/min (Grave)", 10.0, 25.9, "500mg EV de 12/12h"),
                        ("ClCr < 10 mL/min (Terminal)", 0.0, 9.9, "500mg EV de 24/24h")
                    ]
                ),
                (
                    "Piperacilina + Tazobactam",
                    "Penicilina / Beta-lactâmico",
                    "Pneumonia nosocomial, sepse abdominal/urinária por Pseudomonas.",
                    "7 a 10 dias",
                    "Dose de ataque inicial plena: 4,5g EV",
                    "4,5g EV de 6/6h (ou infusão estendida de 4h)",
                    [
                        ("ClCr > 50 mL/min", 50.0, 999.0, "4,5g EV de 6/6h (ou infusão estendida de 4h)"),
                        ("ClCr 20 a 50 mL/min", 20.0, 49.9, "3,375g EV de 6/6h"),
                        ("ClCr < 20 mL/min", 0.0, 19.9, "2,25g EV de 6/6h")
                    ]
                ),
                (
                    "Vancomicina",
                    "Glicopeptídeo",
                    "Bacteremia, osteomielite, pneumonia por MRSA.",
                    "7 a 14 dias",
                    "25 a 30 mg/kg em paciente crítico",
                    "15 a 20 mg/kg de 12/12h (monitorizar vancocinemia)",
                    [
                        ("ClCr > 50 mL/min", 50.0, 999.0, "Dose baseada no peso a cada 8-12h"),
                        ("ClCr 20 a 49 mL/min", 20.0, 49.9, "Dose padrão a cada 24h ou por nível sérico"),
                        ("ClCr < 20 mL/min", 0.0, 19.9, "Dose de ataque e manter por nível sérico (<15 mcg/mL)")
                    ]
                )
            ]
            for nome, classe, ind, tempo, ataque, padrao, regras in exemplos_atb:
                cursor.execute("""
                    INSERT INTO antibioticos (nome, classe, indicacao, tempo_tto, dose_ataque, dose_padrao)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (nome, classe, ind, tempo, ataque, padrao))
                atb_id = cursor.lastrowid
                for faixa, c_min, c_max, conduta in regras:
                    cursor.execute("""
                        INSERT INTO regras_renais (antibiotico_id, faixa_nome, clcr_min, clcr_max, conduta)
                        VALUES (?, ?, ?, ?, ?)
                    """, (atb_id, faixa, c_min, c_max, conduta))
            conn.commit()

        # Seed inicial de Interações Medicamentosas Notáveis
        cursor.execute("SELECT COUNT(*) FROM interacoes_db")
        if cursor.fetchone()[0] == 0:
            interacoes_base = [
                ("meropenem", "valproato", "Grave / Contraindicada", "Meropenem reduz em até 80% o nível de Ácido Valproico em 24h. Risco iminente de crise convulsiva descontrolada."),
                ("vancomicina", "amicacina", "Manejo Clínico", "Duplo insulto nefrotóxico. Elevação significativa do risco de Necrose Tubular Aguda. Monitorar creatinina/diurese diariamente."),
                ("vancomicina", "gentamicina", "Manejo Clínico", "Potencialização de toxicidade renal e ototoxicidade sinérgica. Exige controle rigoroso de clearance e audiometria se uso prolongado."),
                ("piperacilina", "vancomicina", "Alerta Clínico", "Associação empírica clássica com taxa aumentada de lesão renal aguda quando comparada a Cefepima + Vancomicina."),
                ("amiodarona", "levofloxacino", "Grave / Contraindicada", "Efeito aditivo de prolongamento do intervalo QTc. Risco de arritmias ventriculares graves e Torsades de Pointes."),
                ("amiodarona", "claritromicina", "Grave / Contraindicada", "Risco elevado de prolongamento de QT e cardiotoxicidade por bloqueio de canais de potássio."),
                ("omeprazol", "clopidogrel", "Moderada", "Inibição competitiva da CYP2C19. Pode reduzir a ativação antiagregante do Clopidogrel (preferir Pantoprazol)."),
                ("espironolactona", "captopril", "Manejo Clínico", "Duplo bloqueio do SRAA gerando retenção de potássio. Monitorar calemia com frequência."),
                ("espironolactona", "enalapril", "Manejo Clínico", "Risco acentuado de hipercalemia potencialmente fatal, especialmente em doentes com disfunção renal prévia.")
            ]
            for fa, fb, grav, det in interacoes_base:
                cursor.execute("""
                    INSERT INTO interacoes_db (farmaco_a, farmaco_b, gravidade, detalhe)
                    VALUES (?, ?, ?, ?)
                """, (fa, fb, grav, det))
            conn.commit()

init_db()

def calcular_cockcroft_gault(idade: int, peso: float, creatinina: float, sexo: str) -> float:
    if creatinina <= 0:
        return 0.0
    clcr = ((140 - idade) * peso) / (72 * creatinina)
    if sexo.lower() == "f":
        clcr *= 0.85
    return round(clcr, 1)

def checar_alergia_cruzada(alergias_txt: str, atb_nome: str, atb_classe: str):
    if not alergias_txt or alergias_txt.strip() == "":
        return None
    txt = alergias_txt.lower()
    atb_l = atb_nome.lower()
    classe_l = atb_classe.lower()

    for termo in atb_l.split():
        if len(termo) > 3 and termo in txt:
            return f"ALERTA CRÍTICO: Relato direto de alergia a '{termo.upper()}'."

    termos_beta = ["penicilina", "amoxicilina", "ampicilina", "cefalosporina", "ceftriaxona"]
    if any(b in txt for b in termos_beta):
        if "penicilina" in classe_l or "beta-lactâmico" in classe_l:
            return "ALERTA GRAVE: Alergia a Penicilinas relatada. Fármaco compartilha anel beta-lactâmico (Risco iminente de anafilaxia)."
        if "carbapenêmico" in classe_l:
            return "ATENÇÃO: Alergia a Penicilinas relatada. Risco teórico de reação cruzada (~1%). Monitorar primeira administração."
    return None

def checar_matriz_interacoes(lista_farmacos: list):
    """Cruza toda a lista de fármacos N x N consultando o banco SQLite."""
    if len(lista_farmacos) < 2:
        return []
    
    interacoes_encontradas = []
    pares = list(itertools.combinations(lista_farmacos, 2))

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT farmaco_a, farmaco_b, gravidade, detalhe FROM interacoes_db")
        regras = cursor.fetchall()

    for f1, f2 in pares:
        f1_limpo = f1.lower().strip()
        f2_limpo = f2.lower().strip()

        for fa, fb, grav, det in regras:
            match_1 = (fa in f1_limpo and fb in f2_limpo)
            match_2 = (fb in f1_limpo and fa in f2_limpo)
            if match_1 or match_2:
                interacoes_encontradas.append({
                    "par": f"{f1.strip().capitalize()} + {f2.strip().capitalize()}",
                    "gravidade": grav,
                    "detalhe": det
                })

    return interacoes_encontradas

def extrair_texto_pdf(arquivo_bytes: bytes) -> str:
    """Lê um PDF em memória e extrai os nomes de possíveis medicamentos."""
    try:
        reader = PdfReader(io.BytesIO(arquivo_bytes))
        texto_completo = ""
        for page in reader.pages:
            t = page.extract_text()
            if t:
                texto_completo += "\n" + t
        
        # Filtra palavras-chave de fármacos cadastrados no sistema
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT nome FROM antibioticos")
            nomes_atb = [r[0] for r in cursor.fetchall()]
            cursor.execute("SELECT DISTINCT farmaco_a FROM interacoes_db UNION SELECT DISTINCT farmaco_b FROM interacoes_db")
            outros_banco = [r[0] for r in cursor.fetchall()]

        dicionario = set([x.lower() for x in (nomes_atb + outros_banco)])
        achados = []
        for linha in texto_completo.split("\n"):
            linha_l = linha.lower()
            for termo in dicionario:
                if termo in linha_l and termo not in achados:
                    achados.append(termo.capitalize())
        
        return ", ".join(achados) if achados else texto_completo.strip()[:200]
    except Exception:
        return ""

def renderizar_pagina(antibioticos, resultado=None, preenchimento_pdf=""):
    hoje = date.today().isoformat()
    
    options_atb = "".join([
        f'<option value="{a[0]}">{a[1]} ({a[2]})</option>' for a in antibioticos
    ])

    painel_resultado = ""
    if resultado:
        alerta_alergia_html = ""
        if resultado["alerta_alergia"]:
            alerta_alergia_html = f'''
            <div class="alert alert-danger py-2 px-3 mb-2 small fw-bold">
                ⚠️ {resultado["alerta_alergia"]}
            </div>
            '''

        interacoes_html = ""
        if resultado["interacoes"]:
            interacoes_html = '<div class="alert alert-warning py-2 px-3 mb-2 small">'
            interacoes_html += '<strong class="d-block mb-1 text-danger">⚠️ Interações Cruzadas Detectadas (N × N):</strong>'
            for inter in resultado["interacoes"]:
                interacoes_html += f'''
                <div class="border-bottom py-1">
                    <span class="badge bg-danger">{inter["gravidade"]}</span> 
                    <strong>{inter["par"]}:</strong> {inter["detalhe"]}
                </div>
                '''
            interacoes_html += '</div>'

        cor_tev = "bg-danger" if "Alerta" in resultado["status_tev"] else ("bg-warning text-dark" if "Contraindicação" in resultado["status_tev"] else "bg-success")
        cor_lamg = "bg-warning text-dark" if "Alerta" in resultado["status_lamg"] else "bg-success"

        painel_resultado = f'''
        <div class="card card-panel p-3 bg-white border-start border-4 border-primary">
            <div class="d-flex justify-content-between align-items-center mb-2 pb-1 border-bottom">
                <h5 class="fw-bold mb-0 text-dark">
                    Leito: {resultado["leito"]} <span class="badge bg-secondary fs-6">{resultado["setor"]}</span>
                </h5>
                <span class="badge bg-primary fs-6">
                    ClCr: {resultado["clcr"]} mL/min
                </span>
            </div>

            {alerta_alergia_html}
            {interacoes_html}

            <div class="alert alert-light border p-2 mb-2 small">
                <div class="d-flex justify-content-between fw-bold mb-1">
                    <span class="text-primary fs-6">{resultado["atb_nome"]} ({resultado["d_str"]})</span>
                    <span class="text-muted">Tempo previsto: {resultado["tempo_tto"]}</span>
                </div>
                <div>
                    <strong>Prescrito:</strong> {resultado["dose_prescrita"]}<br>
                    <strong>Ajuste Sugerido:</strong> <span class="text-danger fw-bold">{resultado["ajuste_recomendado"]}</span>
                </div>
            </div>

            <div class="row g-2 mb-3">
                <div class="col-6">
                    <div class="p-2 border rounded bg-light small">
                        <div class="fw-bold text-dark mb-1">Status TEV:</div>
                        <span class="badge {cor_tev} mb-1">{resultado["status_tev"]}</span>
                        <div class="text-muted" style="font-size: 0.75rem;">{resultado["conduta_tev"]}</div>
                    </div>
                </div>
                <div class="col-6">
                    <div class="p-2 border rounded bg-light small">
                        <div class="fw-bold text-dark mb-1">Status LAMG:</div>
                        <span class="badge {cor_lamg} mb-1">{resultado["status_lamg"]}</span>
                        <div class="text-muted" style="font-size: 0.75rem;">{resultado["conduta_lamg"]}</div>
                    </div>
                </div>
            </div>

            <div class="mb-1">
                <div class="d-flex justify-content-between align-items-center mb-1">
                    <span class="section-header text-success">Parecer Estruturado (SOAP)</span>
                    <button type="button" class="btn btn-outline-secondary btn-sm" onclick="copiarParecer()">
                        📋 Copiar para AGHUse
                    </button>
                </div>
                <textarea id="parecerTexto" class="form-control font-monospace small bg-light" rows="9" readonly>{resultado["parecer_texto"]}</textarea>
            </div>
        </div>
        '''
    else:
        painel_resultado = '''
        <div class="card card-panel p-5 bg-white text-center text-muted">
            <h5 class="fw-bold mb-1">Radar Clínico Pronto</h5>
            <small>Importe uma prescrição em PDF ou preencha os dados manualmente para rastrear interações N × N, função renal e profilaxias.</small>
        </div>
        '''

    return f'''
    <!DOCTYPE html>
    <html lang="pt-pt">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Radar Clínico - Apoio Farmacêutico</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body {{ background-color: #f1f5f9; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
            .card-panel {{ border-radius: 12px; border: none; box-shadow: 0 4px 16px rgba(15,23,42,0.06); }}
            .section-header {{ font-size: 0.8rem; text-transform: uppercase; font-weight: 700; letter-spacing: 0.05em; color: #64748b; }}
        </style>
    </head>
    <body class="py-3">
        <div class="container-fluid" style="max-width: 1320px;">
            
            <!-- CABEÇALHO COM A LOGO DO RADAR CLÍNICO -->
            <div class="d-flex justify-content-between align-items-center mb-3 pb-2 border-bottom">
                <div class="d-flex align-items-center gap-2">
                    <svg width="46" height="46" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <defs>
                            <mask id="cruz-top-mask">
                                <rect x="35" y="10" width="30" height="80" rx="9" fill="white"/>
                                <rect x="10" y="35" width="80" height="30" rx="9" fill="white"/>
                            </mask>
                        </defs>
                        <g mask="url(#cruz-top-mask)">
                            <rect x="0" y="0" width="48" height="100" fill="#10b981"/>
                            <path d="M 50 10 A 40 40 0 0 1 50 90" stroke="#059669" stroke-width="10"/>
                            <path d="M 50 10 A 40 40 0 0 1 50 90" stroke="#ffffff" stroke-width="4" fill="none"/>
                            <path d="M 58 15 A 38 38 0 0 1 58 85" stroke="#0284c7" stroke-width="9" fill="none"/>
                            <path d="M 58 15 A 38 38 0 0 1 58 85" stroke="#ffffff" stroke-width="3" fill="none"/>
                            <path d="M 68 25 A 32 32 0 0 1 68 75" stroke="#2563eb" stroke-width="9" fill="none"/>
                        </g>
                    </svg>

                    <div>
                        <div class="d-flex align-items-center gap-1 lh-1">
                            <span class="fs-4 fw-bold text-dark" style="letter-spacing: -0.5px;">RADAR</span>
                            <span class="fs-4 fw-bold text-primary" style="letter-spacing: -0.5px;">CLÍNICO</span>
                        </div>
                        <small class="text-muted fw-semibold" style="font-size: 0.70rem; letter-spacing: 0.08em; text-transform: uppercase;">
                            Decisão Farmacêutica & Interações N × N
                        </small>
                    </div>
                </div>
            </div>

            <!-- CARD PARA UPLOAD DE PRESCRIÇÃO EM PDF -->
            <div class="card card-panel p-3 bg-white mb-3 border-start border-4 border-info">
                <form action="/upload_pdf" method="post" enctype="multipart/form-data" class="d-flex align-items-center gap-3">
                    <div>
                        <span class="fw-bold text-dark small d-block">📄 Leitor Inteligente de Prescrição (PDF)</span>
                        <small class="text-muted">Selecione o arquivo da prescrição para extrair os medicamentos automaticamente:</small>
                    </div>
                    <input type="file" name="arquivo_pdf" accept=".pdf" class="form-control form-control-sm" style="max-width: 300px;" required>
                    <button type="submit" class="btn btn-outline-info btn-sm fw-bold">Ler Prescrição</button>
                </form>
            </div>

            <div class="row g-3">
                <div class="col-lg-6">
                    <div class="card card-panel p-3 bg-white">
                        <form action="/avaliar" method="post">
                            
                            <div class="section-header mb-2">1. Identificação & Função Renal</div>
                            <div class="row g-2 mb-2">
                                <div class="col-4">
                                    <label class="form-label small fw-semibold">Leito</label>
                                    <input type="text" name="leito" class="form-control form-control-sm" placeholder="Ex: 204-B" required>
                                </div>
                                <div class="col-4">
                                    <label class="form-label small fw-semibold">Setor</label>
                                    <select name="setor" class="form-select form-select-sm" required>
                                        <option value="Enfermaria">Enfermaria</option>
                                        <option value="UTI">UTI</option>
                                    </select>
                                </div>
                                <div class="col-4">
                                    <label class="form-label small fw-semibold">Hemodiálise?</label>
                                    <select name="em_dialise" class="form-select form-select-sm">
                                        <option value="nao">Não</option>
                                        <option value="sim">Sim</option>
                                    </select>
                                </div>
                            </div>

                            <div class="row g-2 mb-3">
                                <div class="col-3">
                                    <label class="form-label small fw-semibold">Idade</label>
                                    <input type="number" name="idade" class="form-control form-control-sm" placeholder="68" required>
                                </div>
                                <div class="col-3">
                                    <label class="form-label small fw-semibold">Sexo</label>
                                    <select name="sexo" class="form-select form-select-sm">
                                        <option value="m">Masc</option>
                                        <option value="f">Fem</option>
                                    </select>
                                </div>
                                <div class="col-3">
                                    <label class="form-label small fw-semibold">Peso (kg)</label>
                                    <input type="number" step="0.1" name="peso" class="form-control form-control-sm" placeholder="70" required>
                                </div>
                                <div class="col-3">
                                    <label class="form-label small fw-semibold">Creatinina</label>
                                    <input type="number" step="0.01" name="creatinina" class="form-control form-control-sm" placeholder="1.3" required>
                                </div>
                            </div>

                            <div class="section-header mb-2">2. Terapia Antimicrobiana Central</div>
                            <div class="row g-2 mb-2">
                                <div class="col-6">
                                    <label class="form-label small fw-semibold">Antimicrobiano</label>
                                    <select name="antibiotico_id" class="form-select form-select-sm" required>
                                        {options_atb}
                                    </select>
                                </div>
                                <div class="col-6">
                                    <label class="form-label small fw-semibold">Foco Clínico</label>
                                    <input type="text" name="foco_clinico" class="form-control form-control-sm" placeholder="Ex: Pneumonia Hospitalar" required>
                                </div>
                            </div>

                            <div class="row g-2 mb-3">
                                <div class="col-6">
                                    <label class="form-label small fw-semibold">Data Início (D1)</label>
                                    <input type="date" name="data_inicio" value="{hoje}" class="form-control form-control-sm" required>
                                </div>
                                <div class="col-6">
                                    <label class="form-label small fw-semibold">Dose Prescrita</label>
                                    <input type="text" name="dose_prescrita" class="form-control form-control-sm" placeholder="Ex: 1g EV 8/8h" required>
                                </div>
                            </div>

                            <div class="section-header mb-2">3. Todos os Fármacos da Prescrição (Cruzamento N × N)</div>
                            <div class="mb-2">
                                <label class="form-label small fw-semibold text-primary">Lista Completa de Medicamentos (separados por vírgula):</label>
                                <textarea name="todos_medicamentos" rows="2" class="form-control form-control-sm" placeholder="Ex: Meropenem, Valproato, Enoxaparina, Amiodarona, Levofloxacino">{preenchimento_pdf}</textarea>
                                <small class="text-muted" style="font-size: 0.72rem;">O sistema cruzará cada medicamento contra todos os outros em busca de interações simultâneas.</small>
                            </div>

                            <div class="mb-3">
                                <label class="form-label small fw-semibold text-danger">Alergias Relatadas</label>
                                <input type="text" name="alergias" class="form-control form-control-sm" placeholder="Ex: Penicilina, Amoxicilina">
                            </div>

                            <div class="section-header mb-2">4. Profilaxias de TEV & LAMG</div>
                            <div class="p-2 border rounded bg-light mb-3">
                                <div class="row g-2">
                                    <div class="col-6">
                                        <label class="form-label small fw-semibold text-primary">Anticoagulante Prescrito?</label>
                                        <select name="tev_prescrito" class="form-select form-select-sm">
                                            <option value="sim">Sim (Enoxaparina / Heparina)</option>
                                            <option value="nao">Não prescrito</option>
                                        </select>
                                    </div>
                                    <div class="col-6">
                                        <label class="form-label small fw-semibold text-danger">Plaquetas &lt; 50k / Hemorragia?</label>
                                        <select name="plaquetas_baixas" class="form-select form-select-sm">
                                            <option value="nao">Não</option>
                                            <option value="sim">Sim (Contraindicação)</option>
                                        </select>
                                    </div>
                                    <div class="col-12 mt-1">
                                        <label class="form-label small fw-semibold text-muted">Escore de Pádua:</label>
                                        <select name="pontos_padua" class="form-select form-select-sm">
                                            <option value="0">Baixo Risco (&lt; 4 pontos)</option>
                                            <option value="4">Alto Risco (&ge; 4 pontos)</option>
                                        </select>
                                    </div>
                                </div>

                                <hr class="my-2">

                                <div class="row g-2">
                                    <div class="col-4">
                                        <label class="form-label small fw-semibold text-primary">IBP Prescrito?</label>
                                        <select name="ibp_prescrito" class="form-select form-select-sm">
                                            <option value="nao">Não prescrito</option>
                                            <option value="sim">Sim (Omeprazol / Panto)</option>
                                        </select>
                                    </div>
                                    <div class="col-4">
                                        <label class="form-label small fw-semibold">Ventilação &gt; 48h?</label>
                                        <select name="vm_48h" class="form-select form-select-sm">
                                            <option value="nao">Não</option>
                                            <option value="sim">Sim</option>
                                        </select>
                                    </div>
                                    <div class="col-4">
                                        <label class="form-label small fw-semibold">Coagulopatia?</label>
                                        <select name="coagulopatia" class="form-select form-select-sm">
                                            <option value="nao">Não</option>
                                            <option value="sim">Sim</option>
                                        </select>
                                    </div>
                                </div>
                            </div>

                            <button type="submit" class="btn btn-primary w-100 fw-bold py-2">
                                Rastrear Prescrição & Gerar Parecer
                            </button>
                        </form>
                    </div>
                </div>

                <div class="col-lg-6">
                    {painel_resultado}
                </div>
            </div>
        </div>

        <script>
            function copiarParecer() {{
                const copyText = document.getElementById("parecerTexto");
                copyText.select();
                navigator.clipboard.writeText(copyText.value);
                alert("Parecer copiado com sucesso! Pode colar na evolução clínica.");
            }}
        </script>
    </body>
    </html>
    '''

@app.get("/", response_class=HTMLResponse)
async def home():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, nome, classe FROM antibioticos ORDER BY nome ASC")
        antibioticos = cursor.fetchall()
    return renderizar_pagina(antibioticos)

@app.post("/upload_pdf", response_class=HTMLResponse)
async def upload_pdf(arquivo_pdf: UploadFile = File(...)):
    conteudo = await arquivo_pdf.read()
    medicamentos_extraidos = extrair_texto_pdf(conteudo)
    
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, nome, classe FROM antibioticos ORDER BY nome ASC")
        antibioticos = cursor.fetchall()

    return renderizar_pagina(antibioticos, preenchimento_pdf=medicamentos_extraidos)

@app.post("/avaliar", response_class=HTMLResponse)
async def avaliar(
    leito: str = Form(...),
    setor: str = Form(...),
    idade: int = Form(...),
    sexo: str = Form(...),
    peso: float = Form(...),
    creatinina: float = Form(...),
    em_dialise: str = Form("nao"),
    antibiotico_id: int = Form(...),
    foco_clinico: str = Form(...),
    data_inicio: str = Form(...),
    dose_prescrita: str = Form(...),
    todos_medicamentos: str = Form(""),
    alergias: str = Form(""),
    tev_prescrito: str = Form("nao"),
    pontos_padua: int = Form(0),
    plaquetas_baixas: str = Form("nao"),
    vm_48h: str = Form("nao"),
    coagulopatia: str = Form("nao"),
    ibp_prescrito: str = Form("nao")
):
    clcr = calcular_cockcroft_gault(idade, peso, creatinina, sexo)
    is_dialise = (em_dialise == "sim")

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, nome, classe FROM antibioticos ORDER BY nome ASC")
        antibioticos = cursor.fetchall()
        
        cursor.execute("SELECT id, nome, classe, tempo_tto FROM antibioticos WHERE id = ?", (antibiotico_id,))
        atb = cursor.fetchone()

        cursor.execute("""
            SELECT conduta FROM regras_renais
            WHERE antibiotico_id = ? AND ? >= clcr_min AND ? <= clcr_max
        """, (antibiotico_id, clcr, clcr))
        regra = cursor.fetchone()

    ajuste_recomendado = "Paciente em Hemodiálise: Administrar dose de reforço pós-diálise." if is_dialise else (regra[0] if regra else "Consultar CCIH.")

    try:
        dt_ini = datetime.strptime(data_inicio, "%Y-%m-%d").date()
        dias_tto = max((date.today() - dt_ini).days + 1, 1)
        d_str = f"D{dias_tto}"
    except Exception:
        d_str = "D1"

    alerta_alergia = checar_alergia_cruzada(alergias, atb[1], atb[2])

    # Lista consolidada de todos os medicamentos para o cruzamento N x N
    lista_farmacos = [f.strip() for f in todos_medicamentos.split(",") if f.strip()]
    if atb[1] not in lista_farmacos:
        lista_farmacos.append(atb[1])
    
    interacoes_detectadas = checar_matriz_interacoes(lista_farmacos)

    # Profilaxias
    alto_risco_tev = (setor == "UTI") or (pontos_padua >= 4)
    if plaquetas_baixas == "sim":
        status_tev = "Contraindicação Formal"
        conduta_tev = "Plaquetas < 50.000 ou hemorragia ativa. Optar por profilaxia mecânica."
    elif alto_risco_tev:
        status_tev = "Profilaxia Adequada" if tev_prescrito == "sim" else "Alerta: Omissão de Profilaxia de TEV"
        conduta_tev = "Alto risco de TEV com anticoagulação ativa." if tev_prescrito == "sim" else "Doente de alto risco sem profilaxia prescrita."
    else:
        status_tev = "Alerta: Potencial Sobreuso" if tev_prescrito == "sim" else "Conduta Apropriada"
        conduta_tev = "Baixo risco por Pádua com anticoagulante ativo." if tev_prescrito == "sim" else "Baixo risco sem indicação de profilaxia."

    criterio_lamg = (vm_48h == "sim") or (coagulopatia == "sim")
    if criterio_lamg:
        status_lamg = "Profilaxia Adequada" if ibp_prescrito == "sim" else "Alerta: Omissão de Profilaxia para LAMG"
        conduta_lamg = "Critérios maiores presentes e IBP ativo." if ibp_prescrito == "sim" else "Critérios maiores sem gastroproteção prescrita."
    else:
        status_lamg = "Alerta: Avaliar Desprescrição" if ibp_prescrito == "sim" else "Conduta Apropriada"
        conduta_lamg = "Sem critérios maiores de estresse com IBP em uso." if ibp_prescrito == "sim" else "Sem indicação de profilaxia."

    parecer_texto = (
        f"RADAR CLÍNICO - AVALIAÇÃO FARMACÊUTICA\n"
        f"Leito: {leito} | Setor: {setor} | Data: {date.today().strftime('%d/%m/%Y')}\n\n"
        f"[S/O] Paciente {idade}a, {peso}kg. Creatinina: {creatinina} mg/dL | ClCr: {clcr} mL/min.\n"
        f"Alergias: {alergias if alergias else 'Nega alergias conhecidas'}.\n\n"
        f"[I] TERAPIA ANTIMICROBIANA:\n"
        f"- Fármaco: {atb[1]} ({d_str}) | Foco: {foco_clinico}\n"
        f"- Dose Prescrita: {dose_prescrita}\n"
        f"- Ajuste Sugerido: {ajuste_recomendado}\n"
        f"- Prazo Previsto: {atb[3]}\n"
    )
    if alerta_alergia:
        parecer_texto += f"\n[!] ALERTA DE ALERGIA:\n- {alerta_alergia}\n"
    if interacoes_detectadas:
        parecer_texto += "\n[!] INTERAÇÕES MEDICAMENTOSAS IDENTIFICADAS (N × N):\n"
        for i in interacoes_detectadas:
            parecer_texto += f"- [{i['gravidade']}] {i['par']}: {i['detalhe']}\n"
    parecer_texto += (
        f"\n[C] MONITORIZAÇÃO DE PROFILAXIAS:\n"
        f"- TEV: {status_tev} ({conduta_tev})\n"
        f"- LAMG: {status_lamg} ({conduta_lamg})\n\n"
        f"Farmacêutico Clínico à disposição para discussão multidisciplinar."
    )

    resultado = {
        "leito": leito,
        "setor": setor,
        "clcr": clcr,
        "atb_nome": atb[1],
        "d_str": d_str,
        "tempo_tto": atb[3],
        "dose_prescrita": dose_prescrita,
        "ajuste_recomendado": ajuste_recomendado,
        "alerta_alergia": alerta_alergia,
        "interacoes": interacoes_detectadas,
        "status_tev": status_tev,
        "conduta_tev": conduta_tev,
        "status_lamg": status_lamg,
        "conduta_lamg": conduta_lamg,
        "parecer_texto": parecer_texto
    }

    return renderizar_pagina(antibioticos, resultado)