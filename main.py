import sqlite3
import re
import os
from typing import List, Optional
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import pypdf
import threading
import webbrowser
import uvicorn

app = FastAPI(title="Radar Clínico", description="Sistema de Apoio à Decisão Farmacêutica")

# Montar a pasta static para carregar a logo original (logo.jpg)
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# ==============================================================================
# LÓGICA CLÍNICA
# ==============================================================================
def calcular_metricas(sexo: str, idade: int, peso_atual: float, altura_cm: float, creatinina: float):
    alt_m = altura_cm / 100.0
    imc = peso_atual / (alt_m ** 2) if alt_m > 0 else 0
    
    if sexo.lower() == "m":
        peso_ideal = 50.0 + 2.3 * ((altura_cm / 2.54) - 60)
    else:
        peso_ideal = 45.5 + 2.3 * ((altura_cm / 2.54) - 60)
        
    if peso_atual > (1.2 * peso_ideal):
        peso_adotado = peso_ideal + 0.4 * (peso_atual - peso_ideal)
    elif peso_atual < peso_ideal:
        peso_adotado = peso_atual
    else:
        peso_adotado = peso_ideal

    if creatinina > 0:
        clcr = ((140 - idade) * peso_adotado) / (72 * creatinina)
        if sexo.lower() == "f":
            clcr *= 0.85
    else:
        clcr = 0.0

    return {
        "imc": round(imc, 1),
        "peso_ideal": round(peso_ideal, 1),
        "peso_adotado": round(peso_adotado, 1),
        "clcr": round(clcr, 1)
    }

def anonimizar(texto: str) -> str:
    texto = re.sub(r'\d{3}\.?\d{3}\.?\d{3}-?\d{2}', '[CPF OCULTO]', texto)
    texto = re.sub(r'(Prontuário|Registro|Atendimento|RG)[\s:]*([0-9A-Za-z\.\-]+)', r'\1: [RESTRITO]', texto, flags=re.IGNORECASE)
    texto = re.sub(r'(Paciente|Nome)[\s:]+([A-ZÀ-Úa-zà-ú\s]{4,40})', r'\1: [PACIENTE - LGPD]', texto, flags=re.IGNORECASE)
    return texto

# ==============================================================================
# INTERFACE HTML (LOGIN + DASHBOARD UNIFICADO AZUL)
# ==============================================================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Radar Clínico - Triagem Farmacêutica</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css" rel="stylesheet">
    <style>
        :root {
            /* Paleta Azul do Radar Clínico */
            --brand-primary: #0056b3; 
            --brand-light: #e0f2fe;
            --brand-dark: #003d82;
            --bg-login: #3b4252; /* Fundo ardósia escuro idêntico ao Radar Beers */
            --bg-dashboard: #f3f4f6;
        }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: var(--bg-dashboard); color: #374151; }
        
        /* TELA DE LOGIN */
        #login-view { background-color: var(--bg-login); min-height: 100vh; display: flex; align-items: center; justify-content: center; }
        .login-card { background: #fff; width: 100%; max-width: 400px; border-radius: 12px; padding: 2.5rem; box-shadow: 0 10px 25px rgba(0,0,0,0.2); }
        .login-logo-box { background: #f8fafc; border-radius: 12px; padding: 15px; display: inline-block; margin-bottom: 15px; }
        .login-logo { height: 80px; object-fit: contain; }
        .badge-acesso { background-color: var(--brand-light); color: var(--brand-primary); font-weight: 700; letter-spacing: 0.5px; font-size: 0.75rem; padding: 6px 12px; border-radius: 20px; }
        .form-label-custom { font-size: 0.75rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px; }
        .form-control-custom { border-radius: 8px; border: 1px solid #d1d5db; padding: 10px 15px; }
        .form-control-custom:focus { border-color: var(--brand-primary); box-shadow: 0 0 0 3px rgba(0, 86, 179, 0.15); }
        .btn-login { background-color: var(--brand-primary); color: white; border: none; border-radius: 8px; font-weight: 600; padding: 12px; margin-top: 10px; }
        .btn-login:hover { background-color: var(--brand-dark); color: white; }

        /* DASHBOARD (Estilo Radar Beers) */
        .navbar-radar { background-color: var(--brand-primary); padding: 10px 20px; }
        .nav-logo { height: 35px; background: white; padding: 4px; border-radius: 6px; }
        .card-dash { border: none; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); margin-bottom: 20px; background: white; border-top: 4px solid var(--brand-primary); }
        .card-title-dash { font-size: 0.9rem; font-weight: 700; color: var(--brand-primary); text-transform: uppercase; margin-bottom: 1.2rem; display: flex; align-items: center; }
        .step-number { background: var(--brand-light); color: var(--brand-primary); width: 24px; height: 24px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-size: 0.8rem; margin-right: 10px; }
        
        .metric-box { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 15px; text-align: center; height: 100%; }
        .metric-value { font-size: 1.8rem; font-weight: 800; color: var(--brand-primary); margin: 5px 0; }
        
        .soap-output { font-family: 'Consolas', monospace; font-size: 0.9rem; border: 1px solid #e2e8f0; border-radius: 8px; background: #f8fafc; padding: 15px; width: 100%; min-height: 300px; resize: vertical; }
        
        /* Utilitários */
        .d-none { display: none !important; }
    </style>
</head>
<body>

<!-- TELA DE LOGIN -->
<div id="login-view">
    <div class="login-card text-center">
        <div class="login-logo-box">
            <img src="/static/logo.jpg" alt="Logo Radar Clínico" class="login-logo" onerror="this.src='https://via.placeholder.com/80?text=LOGO'">
        </div>
        <div class="mb-4">
            <span class="badge-acesso">ACESSO FARMACÊUTICO</span>
        </div>
        
        <form id="loginForm" onsubmit="event.preventDefault(); fazerLogin();" class="text-start">
            <div class="mb-3">
                <label class="form-label-custom">Usuário</label>
                <input type="text" class="form-control form-control-custom" id="user" placeholder="admin" required>
            </div>
            <div class="mb-3">
                <label class="form-label-custom">Senha</label>
                <input type="password" class="form-control form-control-custom" id="pass" placeholder="••••••••" required>
            </div>
            <div id="loginError" class="text-danger small mb-3 fw-bold d-none">Usuário ou senha inválidos.</div>
            
            <button type="submit" class="btn-login w-100">Entrar no Sistema</button>
        </form>
    </div>
</div>

<!-- DASHBOARD DO SISTEMA -->
<div id="app-view" class="d-none">
    <!-- Navbar -->
    <nav class="navbar navbar-radar d-flex justify-content-between align-items-center">
        <div class="d-flex align-items-center gap-3">
            <img src="/static/logo.jpg" class="nav-logo" alt="Logo" onerror="this.style.display='none'">
            <span class="text-white fw-bold">RADAR CLÍNICO</span>
            <button class="btn btn-sm btn-light fw-bold text-primary px-3 rounded-pill ms-3"><i class="bi bi-shield-check"></i> LGPD Ativo</button>
        </div>
        <div class="d-flex align-items-center gap-4">
            <div class="text-end">
                <div class="text-white-50" style="font-size: 0.7rem; font-weight: 700; letter-spacing: 1px;">CLCR CALCULADO</div>
                <div class="text-white fw-bold" id="navClcr">-- mL/min</div>
            </div>
            <button class="btn btn-outline-light btn-sm fw-bold px-3" onclick="fazerLogout()"><i class="bi bi-box-arrow-right"></i> Sair</button>
        </div>
    </nav>

    <div class="container-fluid p-4 max-width-1300">
        <div class="row g-4">
            
            <!-- Bloco 1: Paciente -->
            <div class="col-lg-4">
                <div class="card card-dash p-3 h-100">
                    <div class="card-title-dash"><span class="step-number">1</span> Paciente & Perfil</div>
                    <div class="row g-3">
                        <div class="col-6">
                            <label class="form-label-custom">Idade (Anos)</label>
                            <input type="number" id="idade" class="form-control form-control-custom" value="65">
                        </div>
                        <div class="col-6">
                            <label class="form-label-custom">Sexo Biológico</label>
                            <select id="sexo" class="form-select form-control-custom">
                                <option value="m">Masculino</option>
                                <option value="f">Feminino</option>
                            </select>
                        </div>
                        <div class="col-12 mt-3">
                            <label class="form-label-custom">Profilaxias Institucionais Ativas</label>
                            <div class="d-flex gap-3 mt-2">
                                <div class="form-check">
                                    <input class="form-check-input" type="checkbox" id="profilaxiaTev" checked>
                                    <label class="form-check-label small fw-bold">TEV</label>
                                </div>
                                <div class="form-check">
                                    <input class="form-check-input" type="checkbox" id="profilaxiaLamg" checked>
                                    <label class="form-check-label small fw-bold">LAMG</label>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Bloco 2: Antropometria & Renal -->
            <div class="col-lg-4">
                <div class="card card-dash p-3 h-100">
                    <div class="card-title-dash"><span class="step-number">2</span> Função Renal & Antropometria</div>
                    <div class="row g-2 mb-3">
                        <div class="col-4">
                            <label class="form-label-custom">Creat. (mg/dL)</label>
                            <input type="number" step="0.1" id="creatinina" class="form-control form-control-custom" value="1.2">
                        </div>
                        <div class="col-4">
                            <label class="form-label-custom">Peso (kg)</label>
                            <input type="number" id="peso" class="form-control form-control-custom" value="70">
                        </div>
                        <div class="col-4">
                            <label class="form-label-custom">Altura (cm)</label>
                            <input type="number" id="altura" class="form-control form-control-custom" value="170">
                        </div>
                    </div>
                    <div class="metric-box">
                        <div class="form-label-custom text-muted">DEPURAÇÃO ESTIMADA (COCKCROFT-GAULT)</div>
                        <div class="metric-value" id="valClcr">-- <span style="font-size:1rem;">mL/min</span></div>
                        <div class="small fw-bold text-secondary mt-1">Peso p/ Ajuste: <span id="valPesoAdotado">--</span> kg</div>
                    </div>
                </div>
            </div>

            <!-- Bloco 3: Extração de Prescrição -->
            <div class="col-lg-4">
                <div class="card card-dash p-3 h-100">
                    <div class="card-title-dash"><span class="step-number">3</span> Entrada da Prescrição</div>
                    <label class="form-label-custom">Importar PDF (Anonimizado)</label>
                    <div class="input-group input-group-sm mb-2">
                        <input type="file" class="form-control" id="pdfFile" accept=".pdf">
                        <button class="btn btn-outline-secondary fw-bold" type="button" onclick="extrairPdf()">Extrair</button>
                    </div>
                    <label class="form-label-custom mt-2">Ou cole a prescrição (Rastreio N x N)</label>
                    <textarea id="outrosMedicamentos" class="form-control form-control-custom mt-1" rows="3" placeholder="Digite medicamentos separados por vírgula..."></textarea>
                </div>
            </div>
            
            <!-- Bloco 4: Terapêutica Antimicrobiana -->
            <div class="col-12">
                <div class="card card-dash p-3">
                    <div class="d-flex justify-content-between align-items-center mb-3">
                        <div class="card-title-dash mb-0"><span class="step-number">4</span> Terapêutica Antimicrobiana & Avaliação SOAP</div>
                        <button class="btn btn-primary fw-bold px-4" style="background-color: var(--brand-primary); border:none; border-radius: 8px;" onclick="gerarAnalise()">
                            <i class="bi bi-play-fill"></i> GERAR AVALIAÇÃO CLÍNICA
                        </button>
                    </div>
                    
                    <div class="row g-4">
                        <div class="col-lg-5">
                            <div class="bg-light p-3 rounded border">
                                <label class="form-label-custom mb-2">Seleção de Fármacos em Uso</label>
                                <select id="slot1" class="form-select form-control-custom mb-2"><option value="">-- Antimicrobiano 1 --</option></select>
                                <select id="slot2" class="form-select form-control-custom mb-2"><option value="">-- Antimicrobiano 2 --</option></select>
                                <select id="slot3" class="form-select form-control-custom mb-2"><option value="">-- Antimicrobiano 3 --</option></select>
                                <select id="slot4" class="form-select form-control-custom mb-2"><option value="">-- Antimicrobiano 4 --</option></select>
                            </div>
                        </div>
                        <div class="col-lg-7">
                            <div class="position-relative">
                                <button class="btn btn-sm btn-outline-secondary position-absolute top-0 end-0 m-2 fw-bold" onclick="copiarSoap()">Copiar Parecer</button>
                                <textarea id="parecerSoap" class="soap-output" readonly placeholder="Preencha os dados e clique em 'Gerar Avaliação Clínica' para processar o parecer estruturado..."></textarea>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

        </div>
    </div>
</div>

<script>
// Mock Login Simples
function fazerLogin() {
    const user = document.getElementById('user').value;
    const pass = document.getElementById('pass').value;
    if(user === 'admin' && pass === 'admin') {
        document.getElementById('login-view').classList.add('d-none');
        document.getElementById('app-view').classList.remove('d-none');
        carregarCatalogo();
    } else {
        document.getElementById('loginError').classList.remove('d-none');
    }
}

function fazerLogout() {
    document.getElementById('app-view').classList.add('d-none');
    document.getElementById('login-view').classList.remove('d-none');
    document.getElementById('user').value = '';
    document.getElementById('pass').value = '';
    document.getElementById('loginError').classList.add('d-none');
}

// Carregar BD
async function carregarCatalogo() {
    try {
        const res = await fetch("/api/antimicrobianos");
        const catalogo = await res.json();
        const selects = [document.getElementById("slot1"), document.getElementById("slot2"), document.getElementById("slot3"), document.getElementById("slot4")];
        
        selects.forEach(select => {
            if(select.options.length <= 1) { // Evita duplicar se recarregar
                catalogo.forEach(item => {
                    const opt = document.createElement("option");
                    opt.value = item.nome; 
                    opt.innerText = item.nome;
                    select.appendChild(opt);
                });
            }
        });
    } catch(e) { console.log("Aguardando Banco de Dados..."); }
}

async function extrairPdf() {
    const fileInput = document.getElementById("pdfFile");
    if (!fileInput.files[0]) return alert("Selecione um PDF.");
    const formData = new FormData(); formData.append("file", fileInput.files[0]);
    const res = await fetch("/api/extrair-pdf", { method: "POST", body: formData });
    const data = await res.json();
    document.getElementById("outrosMedicamentos").value = data.texto_anonimizado;
}

async function gerarAnalise() {
    const atbs = [document.getElementById("slot1").value, document.getElementById("slot2").value, document.getElementById("slot3").value, document.getElementById("slot4").value].filter(i => i !== "");
    const outros = document.getElementById("outrosMedicamentos").value.split(",").map(s => s.trim()).filter(s => s.length > 0 && s.length < 50); // Filtro básico p/ não enviar texto inteiro do PDF

    const payload = {
        sexo: document.getElementById("sexo").value,
        idade: parseInt(document.getElementById("idade").value) || 0,
        peso: parseFloat(document.getElementById("peso").value) || 0,
        altura: parseFloat(document.getElementById("altura").value) || 0,
        creatinina: parseFloat(document.getElementById("creatinina").value) || 0,
        antimicrobianos: atbs,
        outros_medicamentos: outros,
        tev_ativo: document.getElementById("profilaxiaTev").checked,
        lamg_ativo: document.getElementById("profilaxiaLamg").checked
    };

    const res = await fetch("/api/avaliar", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const data = await res.json();

    document.getElementById("valClcr").innerText = data.metricas.clcr;
    document.getElementById("navClcr").innerText = data.metricas.clcr + " mL/min";
    document.getElementById("valPesoAdotado").innerText = data.metricas.peso_adotado;
    document.getElementById("parecerSoap").value = data.soap;
}

function copiarSoap() {
    const txt = document.getElementById("parecerSoap");
    txt.select(); navigator.clipboard.writeText(txt.value);
    alert("Parecer SOAP copiado para a área de transferência!");
}
</script>
</body>
</html>
"""

# ==============================================================================
# ROTAS DA API
# ==============================================================================
class AvaliacaoPayload(BaseModel):
    sexo: str
    idade: int
    peso: float
    altura: float
    creatinina: float
    antimicrobianos: List[str]
    outros_medicamentos: List[str] = []
    tev_ativo: bool
    lamg_ativo: bool

@app.get("/", response_class=HTMLResponse)
def index():
    return HTML_TEMPLATE

@app.get("/api/antimicrobianos")
def get_antimicrobianos():
    conn = sqlite3.connect("radar_clinico.db")
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, nome_generico, nomes_comerciais FROM antimicrobianos ORDER BY nome_generico ASC")
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return [{"id": 0, "nome": "Base não atualizada. Rode setup_db.py", "nome_generico": "Erro"}]
    
    items = []
    for r in rows:
        nome_gen, nomes_com = r[1], r[2]
        nome_exibicao = f"{nome_gen} ({nomes_com})" if nomes_com else nome_gen
        items.append({"id": r[0], "nome": nome_exibicao, "nome_generico": nome_gen})
        
    conn.close()
    return items

@app.post("/api/extrair-pdf")
async def processar_pdf(file: UploadFile = File(...)):
    reader = pypdf.PdfReader(file.file)
    texto = "".join([p.extract_text() or "" for p in reader.pages])
    return {"texto_anonimizado": anonimizar(texto)}

@app.post("/api/avaliar")
def avaliar_paciente(payload: AvaliacaoPayload):
    metricas = calcular_metricas(payload.sexo, payload.idade, payload.peso, payload.altura, payload.creatinina)
    clcr = metricas["clcr"]
    
    conn = sqlite3.connect("radar_clinico.db")
    cursor = conn.cursor()
    avaliacoes = []
    farmacotecnias = []
    todos_farmacos_genericos = []
    
    for nome_selecionado in payload.antimicrobianos:
        nome_generico = nome_selecionado.split(" (")[0]
        todos_farmacos_genericos.append(nome_generico)
        
        cursor.execute("SELECT * FROM antimicrobianos WHERE nome_generico = ?", (nome_generico,))
        row = cursor.fetchone()
        if row:
            d_padrao, c_30_50, c_10_30, c_menor_10, c_hd, mon, farm = row[3], row[4], row[5], row[6], row[7], row[8], row[9]
            if clcr >= 50: poso = f"{d_padrao} (Dose plena preservada)"
            elif 30 <= clcr < 50: poso = c_30_50
            elif 10 <= clcr < 30: poso = c_10_30
            else: poso = c_menor_10
                
            avaliacoes.append({"nome": nome_generico, "posologia": poso, "monitor": mon})
            farmacotecnias.append(f"• {nome_generico}: {farm}")

    # Interações (Verificação N x N)
    todos_farmacos_genericos.extend(payload.outros_medicamentos)
    interacoes_encontradas = []
    
    for i in range(len(todos_farmacos_genericos)):
        for j in range(i + 1, len(todos_farmacos_genericos)):
            d1, d2 = todos_farmacos_genericos[i].strip(), todos_farmacos_genericos[j].strip()
            if not d1 or not d2: continue
            cursor.execute("""
                SELECT gravidade, mecanismo, conduta FROM interacoes 
                WHERE (LOWER(droga_a) = LOWER(?) AND LOWER(droga_b) = LOWER(?)) 
                   OR (LOWER(droga_a) = LOWER(?) AND LOWER(droga_b) = LOWER(?))
            """, (d1, d2, d2, d1))
            res = cursor.fetchone()
            if res:
                interacoes_encontradas.append({"par": f"{d1} + {d2}", "gravidade": res[0], "detalhe": res[1], "conduta": res[2]})

    conn.close()

    # Montagem do SOAP
    soap = [
        "=== EVOLUÇÃO FARMACÊUTICA // RADAR CLÍNICO ===",
        "[S] SUBJETIVO: Acompanhamento da farmacoterapia do leito. Triagem de prescrição médica ativa.",
        "[O] OBJETIVO:",
        f"    - Idade: {payload.idade} anos | Sexo: {payload.sexo.upper()} | Peso Real: {payload.peso} kg | Altura: {payload.altura} cm",
        f"    - Peso Adotado para Ajuste: {metricas['peso_adotado']} kg | IMC: {metricas['imc']} kg/m²",
        f"    - Função Renal (Cockcroft-Gault): {metricas['clcr']} mL/min",
        "[A] AVALIAÇÃO FARMACÊUTICA:"
    ]
    
    if avaliacoes:
        soap.append("    1. Terapêutica Antimicrobiana & Ajuste Renal:")
        for a in avaliacoes:
            soap.append(f"       * {a['nome']}: Posologia sugerida para ClCr {clcr} mL/min -> {a['posologia']}")
    else:
        soap.append("    1. Nenhum antimicrobiano ativo selecionado para ajuste de dose.")

    soap.append("    2. Profilaxias Institucionais:")
    soap.append(f"       * TEV: {'Conforme.' if payload.tev_ativo else 'ALERTA: Ausência detectada (avaliar Pádua/Caprini).'}")
    soap.append(f"       * LAMG: {'Conforme.' if payload.lamg_ativo else 'NOTA: Sem profilaxia prescrita.'}")

    if interacoes_encontradas:
        soap.append("    3. Interações Medicamentosas Relevantes:")
        for inter in interacoes_encontradas:
            soap.append(f"       * [{inter['gravidade']}] {inter['par']}: {inter['conduta']}")

    soap.append("[P] PLANO DE CUIDADO:")
    soap.append("    1. Sugerir à equipe assistente a adequação clínica e posológica conforme apontado.")
    if farmacotecnias:
        soap.append("    2. Orientações Farmacotécnicas e Administração:")
        for f in farmacotecnias: soap.append(f"       {f}")

    return {"metricas": metricas, "soap": "\n".join(soap)}

if __name__ == "__main__":
    threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:8000")).start()
    uvicorn.run("main:app", host="127.0.0.1", port=8000, log_level="warning")
