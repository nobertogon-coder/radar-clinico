import sqlite3
import re
import os
from typing import List
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import pypdf
import threading
import webbrowser
import uvicorn

app = FastAPI(title="Radar Clínico", description="Sistema de Apoio à Decisão Farmacêutica")

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

    return {"imc": round(imc, 1), "peso_ideal": round(peso_ideal, 1), "peso_adotado": round(peso_adotado, 1), "clcr": round(clcr, 1)}

def anonimizar(texto: str) -> str:
    texto = re.sub(r'\d{3}\.?\d{3}\.?\d{3}-?\d{2}', '[CPF OCULTO]', texto)
    texto = re.sub(r'(Prontuário|Registro|Atendimento|RG)[\s:]*([0-9A-Za-z\.\-]+)', r'\1: [RESTRITO]', texto, flags=re.IGNORECASE)
    texto = re.sub(r'(Paciente|Nome)[\s:]+([A-ZÀ-Úa-zà-ú\s]{4,40})', r'\1: [PACIENTE - LGPD]', texto, flags=re.IGNORECASE)
    return texto

# ==============================================================================
# INTERFACE HTML
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
            --brand-primary: #0056b3; 
            --brand-light: #e0f2fe;
            --brand-dark: #003d82;
            --bg-login: #3b4252;
            --bg-dashboard: #f3f4f6;
        }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: var(--bg-dashboard); color: #374151; }
        
        #login-view { background-color: var(--bg-login); min-height: 100vh; display: flex; align-items: center; justify-content: center; }
        .login-card { background: #fff; width: 100%; max-width: 400px; border-radius: 12px; padding: 2.5rem; box-shadow: 0 10px 25px rgba(0,0,0,0.2); }
        .login-logo-box { background: #f8fafc; border-radius: 12px; padding: 15px; display: inline-block; margin-bottom: 15px; }
        .login-logo { height: 80px; object-fit: contain; }
        .badge-acesso { background-color: var(--brand-light); color: var(--brand-primary); font-weight: 700; letter-spacing: 0.5px; font-size: 0.75rem; padding: 6px 12px; border-radius: 20px; }
        .form-label-custom { font-size: 0.75rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px; }
        .form-control-custom { border-radius: 8px; border: 1px solid #d1d5db; padding: 10px 15px; }
        .form-control-custom:focus { border-color: var(--brand-primary); box-shadow: 0 0 0 3px rgba(0, 86, 179, 0.15); }
        .btn-brand { background-color: var(--brand-primary); color: white; border: none; border-radius: 8px; font-weight: 600; padding: 10px 15px; }
        .btn-brand:hover { background-color: var(--brand-dark); color: white; }

        .navbar-radar { background-color: var(--brand-primary); padding: 10px 20px; }
        .nav-logo { height: 35px; background: white; padding: 4px; border-radius: 6px; }
        .card-dash { border: none; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); margin-bottom: 20px; background: white; border-top: 4px solid var(--brand-primary); }
        .card-title-dash { font-size: 0.9rem; font-weight: 700; color: var(--brand-primary); text-transform: uppercase; margin-bottom: 1.2rem; display: flex; align-items: center; }
        .step-number { background: var(--brand-light); color: var(--brand-primary); width: 24px; height: 24px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-size: 0.8rem; margin-right: 10px; }
        
        .metric-box { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 15px; text-align: center; height: 100%; }
        .metric-value { font-size: 1.8rem; font-weight: 800; color: var(--brand-primary); margin: 5px 0; }
        .soap-output { font-family: 'Consolas', monospace; font-size: 0.9rem; border: 1px solid #e2e8f0; border-radius: 8px; background: #f8fafc; padding: 15px; width: 100%; min-height: 300px; resize: vertical; }
        .d-none { display: none !important; }
    </style>
</head>
<body>

<!-- LOGIN -->
<div id="login-view">
    <div class="login-card text-center">
        <div class="login-logo-box">
            <img src="/static/logo.jpg" alt="Logo" class="login-logo" onerror="this.src='https://via.placeholder.com/80?text=LOGO'">
        </div>
        <div class="mb-4"><span class="badge-acesso">ACESSO FARMACÊUTICO</span></div>
        <form id="loginForm" onsubmit="event.preventDefault(); fazerLogin();" class="text-start">
            <div class="mb-3"><label class="form-label-custom">Usuário</label><input type="text" class="form-control form-control-custom" id="user" required></div>
            <div class="mb-3"><label class="form-label-custom">Senha</label><input type="password" class="form-control form-control-custom" id="pass" required></div>
            <div id="loginError" class="text-danger small mb-3 fw-bold d-none">Usuário ou senha inválidos.</div>
            <button type="submit" class="btn-brand w-100 py-3">Entrar no Sistema</button>
        </form>
    </div>
</div>

<!-- DASHBOARD -->
<div id="app-view" class="d-none">
    <nav class="navbar navbar-radar d-flex justify-content-between align-items-center">
        <div class="d-flex align-items-center gap-3">
            <img src="/static/logo.jpg" class="nav-logo" alt="Logo" onerror="this.style.display='none'">
            <button class="btn btn-sm btn-light fw-bold text-primary px-3 rounded-pill" onclick="novaTriagem()"><i class="bi bi-arrow-clockwise"></i> NOVA TRIAGEM</button>
            <button id="btnAdmin" class="btn btn-sm btn-outline-light fw-bold d-none" data-bs-toggle="modal" data-bs-target="#adminModal"><i class="bi bi-people-fill"></i> ADMIN</button>
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
            <!-- Bloco 1 -->
            <div class="col-lg-4">
                <div class="card card-dash p-3 h-100">
                    <div class="card-title-dash"><span class="step-number">1</span> Paciente & Perfil</div>
                    <div class="row g-3">
                        <div class="col-6"><label class="form-label-custom">Idade (Anos)</label><input type="number" id="idade" class="form-control form-control-custom" value="65"></div>
                        <div class="col-6"><label class="form-label-custom">Sexo Biológico</label><select id="sexo" class="form-select form-control-custom"><option value="m">Masculino</option><option value="f">Feminino</option></select></div>
                        <div class="col-12 mt-3">
                            <label class="form-label-custom">Fatores de Risco</label>
                            <div class="form-check mt-1">
                                <input class="form-check-input" type="checkbox" id="pacienteAcamado">
                                <label class="form-check-label small fw-bold text-danger">Paciente Acamado / Restrito ao leito</label>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Bloco 2 -->
            <div class="col-lg-4">
                <div class="card card-dash p-3 h-100">
                    <div class="card-title-dash"><span class="step-number">2</span> Função Renal & Antropometria</div>
                    <div class="row g-2 mb-3">
                        <div class="col-4"><label class="form-label-custom">Creat. (mg/dL)</label><input type="number" step="0.1" id="creatinina" class="form-control form-control-custom" value="1.2"></div>
                        <div class="col-4"><label class="form-label-custom">Peso (kg)</label><input type="number" id="peso" class="form-control form-control-custom" value="70"></div>
                        <div class="col-4"><label class="form-label-custom">Altura (cm)</label><input type="number" id="altura" class="form-control form-control-custom" value="170"></div>
                    </div>
                    <div class="metric-box">
                        <div class="form-label-custom text-muted">DEPURAÇÃO (COCKCROFT-GAULT)</div>
                        <div class="metric-value" id="valClcr">-- <span style="font-size:1rem;">mL/min</span></div>
                        <div class="small fw-bold text-secondary mt-1">Peso Adotado: <span id="valPesoAdotado">--</span> kg</div>
                    </div>
                </div>
            </div>

            <!-- Bloco 3 -->
            <div class="col-lg-4">
                <div class="card card-dash p-3 h-100">
                    <div class="card-title-dash"><span class="step-number">3</span> Extração Automática</div>
                    <label class="form-label-custom">Importar PDF (Leitura Inteligente)</label>
                    <div class="input-group input-group-sm mb-2">
                        <input type="file" class="form-control" id="pdfFile" accept=".pdf">
                        <button class="btn btn-outline-secondary fw-bold" type="button" onclick="extrairPdf()">Extrair & Distribuir</button>
                    </div>
                    <label class="form-label-custom mt-2">Texto da Prescrição / Outros Fármacos</label>
                    <textarea id="textoPrescricao" class="form-control form-control-custom mt-1" rows="3" placeholder="O PDF será lido e as incompatibilidades (Diluentes, Vias, Interações) serão rastreadas neste campo..."></textarea>
                </div>
            </div>
            
            <!-- Bloco 4 -->
            <div class="col-12">
                <div class="card card-dash p-3">
                    <div class="d-flex justify-content-between align-items-center mb-3">
                        <div class="card-title-dash mb-0"><span class="step-number">4</span> Avaliação Terapêutica SOAP</div>
                        <button class="btn btn-brand px-4" onclick="gerarAnalise()"><i class="bi bi-play-fill"></i> AVALIAR PRESCRIÇÃO</button>
                    </div>
                    <div class="row g-4">
                        <div class="col-lg-5">
                            <div class="bg-light p-3 rounded border">
                                <label class="form-label-custom mb-2">Antimicrobianos Detectados</label>
                                <select id="slot1" class="form-select form-control-custom mb-2"><option value="">-- Slot 1 --</option></select>
                                <select id="slot2" class="form-select form-control-custom mb-2"><option value="">-- Slot 2 --</option></select>
                                <select id="slot3" class="form-select form-control-custom mb-2"><option value="">-- Slot 3 --</option></select>
                                <select id="slot4" class="form-select form-control-custom mb-2"><option value="">-- Slot 4 --</option></select>
                            </div>
                        </div>
                        <div class="col-lg-7 position-relative">
                            <button class="btn btn-sm btn-outline-secondary position-absolute top-0 end-0 m-2 fw-bold" onclick="copiarSoap()">Copiar Parecer</button>
                            <textarea id="parecerSoap" class="soap-output" readonly placeholder="Aguardando dados clínicos..."></textarea>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>

<!-- MODAL ADMIN -->
<div class="modal fade" id="adminModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog">
    <div class="modal-content">
      <div class="modal-header bg-light">
        <h5 class="modal-title fw-bold" style="color: var(--brand-primary);"><i class="bi bi-person-plus-fill"></i> Gerenciar Usuários</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
      </div>
      <div class="modal-body">
        <div class="mb-3"><label class="form-label-custom">Novo Usuário</label><input type="text" id="novoUser" class="form-control form-control-custom"></div>
        <div class="mb-3"><label class="form-label-custom">Nova Senha</label><input type="password" id="novoPass" class="form-control form-control-custom"></div>
        <div id="adminMsg" class="small fw-bold mb-2"></div>
        <button class="btn btn-brand w-100" onclick="criarUsuario()">Cadastrar</button>
      </div>
    </div>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
async function fazerLogin() {
    const user = document.getElementById('user').value;
    const pass = document.getElementById('pass').value;
    const res = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: user, password: pass }) });
    const data = await res.json();
    if (data.success) {
        document.getElementById('login-view').classList.add('d-none');
        document.getElementById('app-view').classList.remove('d-none');
        if (data.role === 'admin') document.getElementById('btnAdmin').classList.remove('d-none');
        carregarCatalogo();
    } else {
        document.getElementById('loginError').classList.remove('d-none');
    }
}

function fazerLogout() {
    document.getElementById('app-view').classList.add('d-none'); document.getElementById('login-view').classList.remove('d-none');
    document.getElementById('user').value = ''; document.getElementById('pass').value = '';
    document.getElementById('loginError').classList.add('d-none'); document.getElementById('btnAdmin').classList.add('d-none');
    novaTriagem();
}

function novaTriagem() {
    document.getElementById('idade').value = '65'; document.getElementById('peso').value = '70';
    document.getElementById('altura').value = '170'; document.getElementById('creatinina').value = '1.2';
    document.getElementById('pacienteAcamado').checked = false;
    document.getElementById('pdfFile').value = ''; document.getElementById('textoPrescricao').value = ''; document.getElementById('parecerSoap').value = '';
    document.getElementById('valClcr').innerHTML = '-- <span style="font-size:1rem;">mL/min</span>';
    document.getElementById('navClcr').innerText = '-- mL/min';
    document.getElementById('valPesoAdotado').innerText = '--';
    ['slot1', 'slot2', 'slot3', 'slot4'].forEach(id => document.getElementById(id).value = '');
}

async function criarUsuario() {
    const user = document.getElementById('novoUser').value; const pass = document.getElementById('novoPass').value;
    if (!user || !pass) return alert("Preencha ambos os campos.");
    const res = await fetch("/api/usuarios", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: user, password: pass }) });
    const data = await res.json();
    const msg = document.getElementById('adminMsg');
    if (data.success) {
        msg.className = "small fw-bold mb-2 text-success"; msg.innerText = "Usuário cadastrado com sucesso!";
        document.getElementById('novoUser').value = ''; document.getElementById('novoPass').value = '';
    } else { msg.className = "small fw-bold mb-2 text-danger"; msg.innerText = data.msg; }
}

async function carregarCatalogo() {
    try {
        const res = await fetch("/api/antimicrobianos");
        const catalogo = await res.json();
        const selects = [document.getElementById("slot1"), document.getElementById("slot2"), document.getElementById("slot3"), document.getElementById("slot4")];
        selects.forEach(select => {
            if(select.options.length <= 1) { 
                catalogo.forEach(item => { const opt = document.createElement("option"); opt.value = item.nome; opt.innerText = item.nome; select.appendChild(opt); });
            }
        });
    } catch(e) {}
}

async function extrairPdf() {
    const fileInput = document.getElementById("pdfFile");
    if (!fileInput.files[0]) return alert("Selecione um PDF.");
    const formData = new FormData(); formData.append("file", fileInput.files[0]);
    const res = await fetch("/api/extrair-pdf", { method: "POST", body: formData });
    const data = await res.json();
    
    // Distribuição Automática
    document.getElementById("textoPrescricao").value = data.texto_anonimizado;
    
    // Preenche os Slots com os ATBs encontrados
    const slots = ["slot1", "slot2", "slot3", "slot4"];
    for (let i = 0; i < data.atbs.length && i < 4; i++) {
        document.getElementById(slots[i]).value = data.atbs[i];
    }
}

async function gerarAnalise() {
    const atbs = [document.getElementById("slot1").value, document.getElementById("slot2").value, document.getElementById("slot3").value, document.getElementById("slot4").value].filter(i => i !== "");
    
    const payload = {
        sexo: document.getElementById("sexo").value,
        idade: parseInt(document.getElementById("idade").value) || 0,
        peso: parseFloat(document.getElementById("peso").value) || 0,
        altura: parseFloat(document.getElementById("altura").value) || 0,
        creatinina: parseFloat(document.getElementById("creatinina").value) || 0,
        acamado: document.getElementById("pacienteAcamado").checked,
        antimicrobianos: atbs,
        texto_prescricao: document.getElementById("textoPrescricao").value
    };

    const res = await fetch("/api/avaliar", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const data = await res.json();

    document.getElementById("valClcr").innerHTML = data.metricas.clcr + ' <span style="font-size:1rem;">mL/min</span>';
    document.getElementById("navClcr").innerText = data.metricas.clcr + " mL/min";
    document.getElementById("valPesoAdotado").innerText = data.metricas.peso_adotado;
    document.getElementById("parecerSoap").value = data.soap;
}

function copiarSoap() {
    const txt = document.getElementById("parecerSoap"); txt.select(); navigator.clipboard.writeText(txt.value);
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
    acamado: bool
    antimicrobianos: List[str]
    texto_prescricao: str

class LoginData(BaseModel):
    username: str
    password: str

class NovoUsuario(BaseModel):
    username: str
    password: str
    role: str = "user"

@app.get("/", response_class=HTMLResponse)
def index(): return HTML_TEMPLATE

@app.post("/api/login")
def login(data: LoginData):
    conn = sqlite3.connect("radar_clinico.db")
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM usuarios WHERE username = ? AND password = ?", (data.username, data.password))
    user = cursor.fetchone()
    conn.close()
    if user: return {"success": True, "role": user[0]}
    return {"success": False}

@app.post("/api/usuarios")
def criar_usuario(data: NovoUsuario):
    try:
        conn = sqlite3.connect("radar_clinico.db")
        cursor = conn.cursor()
        cursor.execute("INSERT INTO usuarios (username, password, role) VALUES (?, ?, ?)", (data.username, data.password, data.role))
        conn.commit()
        conn.close()
        return {"success": True}
    except: return {"success": False, "msg": "Nome de usuário já existe!"}

@app.get("/api/antimicrobianos")
def get_antimicrobianos():
    conn = sqlite3.connect("radar_clinico.db")
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, nome_generico, nomes_comerciais FROM antimicrobianos ORDER BY nome_generico ASC")
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return [{"id": 0, "nome": "Base não atualizada.", "nome_generico": "Erro"}]
    
    items = []
    for r in rows:
        nome_exibicao = f"{r[1]} ({r[2]})" if r[2] else r[1]
        items.append({"id": r[0], "nome": nome_exibicao, "nome_generico": r[1]})
    conn.close()
    return items

@app.post("/api/extrair-pdf")
async def processar_pdf(file: UploadFile = File(...)):
    reader = pypdf.PdfReader(file.file)
    texto_bruto = "".join([p.extract_text() or "" for p in reader.pages])
    texto_anon = anonimizar(texto_bruto)
    texto_lower = texto_anon.lower()
    
    # Busca automática de Antimicrobianos
    conn = sqlite3.connect("radar_clinico.db")
    cursor = conn.cursor()
    cursor.execute("SELECT nome_generico, nomes_comerciais FROM antimicrobianos")
    atbs_db = cursor.fetchall()
    conn.close()
    
    atbs_encontrados = set()
    for gen, com in atbs_db:
        nomes_para_buscar = [gen.lower()]
        if com: nomes_para_buscar.extend([c.strip().lower() for c in com.split(',')])
        
        for n in nomes_para_buscar:
            if n in texto_lower:
                atbs_encontrados.add(f"{gen} ({com})" if com else gen)
                break

    return {
        "texto_anonimizado": texto_anon,
        "atbs": list(atbs_encontrados)
    }

@app.post("/api/avaliar")
def avaliar_paciente(payload: AvaliacaoPayload):
    metricas = calcular_metricas(payload.sexo, payload.idade, payload.peso, payload.altura, payload.creatinina)
    clcr = metricas["clcr"]
    texto_min = payload.texto_prescricao.lower()
    
    conn = sqlite3.connect("radar_clinico.db")
    cursor = conn.cursor()
    
    # 1. Avaliação de Antimicrobianos
    avaliacoes = []
    farmacotecnias = []
    for nome_selecionado in payload.antimicrobianos:
        nome_generico = nome_selecionado.split(" (")[0]
        cursor.execute("SELECT * FROM antimicrobianos WHERE nome_generico = ?", (nome_generico,))
        row = cursor.fetchone()
        if row:
            d_padrao, c_30_50, c_10_30, c_menor_10, farm = row[3], row[4], row[5], row[6], row[9]
            if clcr >= 50: poso = f"{d_padrao} (Dose plena preservada)"
            elif 30 <= clcr < 50: poso = c_30_50
            elif 10 <= clcr < 30: poso = c_10_30
            else: poso = c_menor_10
            avaliacoes.append({"nome": nome_generico, "posologia": poso})
            farmacotecnias.append(f"• {nome_generico}: {farm}")

    # 2. Motor de Incompatibilidades Farmacotécnicas (Leitura de Contexto Linha a Linha)
    incompatibilidades_encontradas = set()
    cursor.execute("SELECT farmaco, condicao, alerta FROM regras_farmacotecnicas")
    regras = cursor.fetchall()
    
    linhas_prescricao = texto_min.split('\n')
    for farmaco, condicao, alerta in regras:
        for linha in linhas_prescricao:
            if farmaco.lower() in linha and condicao.lower() in linha:
                incompatibilidades_encontradas.add(f"[ALERTA FARMACOTÉCNICO] {farmaco.upper()} + {condicao.upper()}: {alerta}")

    conn.close()

    # 3. Filtro Clínico de Exceção (TEV e LAMG)
    tem_heparina = "heparina" in texto_min or "enoxaparina" in texto_min or "versan" in texto_min or "clexane" in texto_min
    tem_ibp = "omeprazol" in texto_min or "pantoprazol" in texto_min or "esomeprazol" in texto_min
    
    alerta_tev = ""
    if not tem_heparina and (payload.idade >= 60 or payload.acamado):
        alerta_tev = "ALERTA [!]: Paciente de risco (Idoso/Acamado) SEM profilaxia anticoagulante. Avaliar omissão ou contraindicação (sangramento, plaquetas)."
    else:
        alerta_tev = "Conforme (Baixo risco ou Profilaxia já prescrita)."
        
    alerta_lamg = ""
    if tem_ibp:
        alerta_lamg = "ALERTA [!]: Protetor gástrico prescrito. Reavaliar real indicação para prevenir desprescrição inadequada."
    else:
        alerta_lamg = "Conforme (Sem protetor gástrico prescrito)."

    # 4. Montagem Final do SOAP
    soap = [
        "=== EVOLUÇÃO FARMACÊUTICA // RADAR CLÍNICO ===",
        "[S] SUBJETIVO: Acompanhamento da farmacoterapia do leito. Triagem automática de prescrição médica.",
        "[O] OBJETIVO:",
        f"    - Idade: {payload.idade} anos | Sexo: {payload.sexo.upper()} | Peso Real: {payload.peso} kg | Altura: {payload.altura} cm",
        f"    - Peso Adotado para Ajuste: {metricas['peso_adotado']} kg | IMC: {metricas['imc']} kg/m²",
        f"    - Função Renal (Cockcroft-Gault): {metricas['clcr']} mL/min",
        "[A] AVALIAÇÃO FARMACÊUTICA:"
    ]
    
    if avaliacoes:
        soap.append("    1. Terapêutica Antimicrobiana & Ajuste Renal:")
        for a in avaliacoes: soap.append(f"       * {a['nome']}: Sugestão p/ ClCr {clcr} mL/min -> {a['posologia']}")
    else: soap.append("    1. Nenhum antimicrobiano detectado para ajuste de dose.")
    
    soap.append("    2. Profilaxias Institucionais (Filtro por Exceção):")
    soap.append(f"       * TEV: {alerta_tev}")
    soap.append(f"       * LAMG: {alerta_lamg}")

    if incompatibilidades_encontradas:
        soap.append("    3. Incompatibilidades e Vias de Administração Detectadas:")
        for inc in incompatibilidades_encontradas: soap.append(f"       * {inc}")

    soap.append("[P] PLANO DE CUIDADO:")
    soap.append("    1. Sugerir adequação clínica/posológica à equipe médica conforme achados.")
    if farmacotecnias:
        soap.append("    2. Orientações de Reconstituição e Diluição:")
        for f in farmacotecnias: soap.append(f"       {f}")

    return {"metricas": metricas, "soap": "\n".join(soap)}

if __name__ == "__main__":
    threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:8000")).start()
    uvicorn.run("main:app", host="127.0.0.1", port=8000, log_level="warning")
