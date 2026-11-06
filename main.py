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

# ==============================================================================
# AUTO-REPARAÇÃO DA BASE DE DADOS
# ==============================================================================
@app.on_event("startup")
def verificar_base_dados():
    try:
        conn = sqlite3.connect("radar_clinico.db")
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM usuarios")
        cursor.execute("SELECT dose_max_padrao_mg FROM antimicrobianos") # Verifica a nova tabela estruturada
        conn.close()
    except sqlite3.OperationalError:
        print("Base de dados desatualizada. A executar setup_db.py automaticamente...")
        try:
            import setup_db
            setup_db.setup_database()
        except Exception as e:
            print("Erro ao forçar a base de dados:", e)

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

def limpar_texto_prescricao(texto: str) -> str:
    texto = re.sub(r'\d{3}\.?\d{3}\.?\d{3}-?\d{2}', '[CPF OCULTO]', texto)
    texto = re.sub(r'(Prontuário|Registro|Atendimento|RG)[\s:]*([0-9A-Za-z\.\-]+)', r' : [RESTRITO]', texto, flags=re.IGNORECASE)
    texto = re.sub(r'(Paciente|Nome)[\s:]+([A-ZÀ-Úa-zà-ú\s]{4,40})', r' : [PACIENTE - LGPD]', texto, flags=re.IGNORECASE)
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
            --brand-nova-triagem: #0dcaf0;
            --bg-login: #3b4252;
            --bg-dashboard: #f3f4f6;
        }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: var(--bg-dashboard); color: #374151; }
        
        #login-view { background-color: var(--bg-login); min-height: 100vh; display: flex; align-items: center; justify-content: center; }
        .login-card { background: #fff; width: 100%; max-width: 400px; border-radius: 12px; padding: 2.5rem; box-shadow: 0 10px 25px rgba(0,0,0,0.2); }
        .login-logo-box { background: #f8fafc; border-radius: 12px; padding: 15px; display: inline-block; margin-bottom: 15px; }
        .login-logo { height: 80px; object-fit: contain; }
        .badge-acesso { background-color: var(--brand-light); color: var(--brand-primary); font-weight: 700; letter-spacing: 0.5px; font-size: 0.75rem; padding: 6px 12px; border-radius: 20px; }
        
        .navbar-radar { background-color: var(--brand-primary); padding: 8px 24px; min-height: 64px; }
        .nav-logo-box { background: white; border-radius: 8px; width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; padding: 4px; flex-shrink: 0; }
        .nav-logo { max-width: 100%; max-height: 100%; object-fit: contain; border-radius: 6px; }
        .btn-nova-triagem { background-color: var(--brand-nova-triagem); color: white; border: none; border-radius: 6px; padding: 8px 16px; font-size: 0.85rem; letter-spacing: 0.5px; text-transform: uppercase; font-weight: 700; }
        .btn-nova-triagem:hover { background-color: #0bacce; color: white; }
        
        .nav-metric-box { text-align: right; line-height: 1.2; }
        .nav-metric-label { font-size: 0.65rem; font-weight: 800; color: rgba(255,255,255,0.85); text-transform: uppercase; letter-spacing: 0.5px; }
        .nav-metric-value { font-size: 1.05rem; font-weight: 800; color: white; }
        .nav-alert-value { font-size: 1.05rem; font-weight: 800; color: #ffc107; }
        
        .btn-admin-nav { background-color: rgba(0,0,0,0.25); color: white; border: 1px solid rgba(255,255,255,0.1); border-radius: 6px; padding: 8px 16px; font-size: 0.85rem; font-weight: 700; }
        .btn-admin-nav:hover { background-color: rgba(0,0,0,0.4); color: white; }
        .btn-sair { background-color: #dc3545; color: white; border: none; border-radius: 6px; padding: 8px 16px; font-size: 0.85rem; font-weight: 700; }
        .btn-sair:hover { background-color: #bb2d3b; color: white; }

        .form-label-custom { font-size: 0.75rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 0.2rem; }
        .form-control-custom { border-radius: 8px; border: 1px solid #d1d5db; padding: 8px 12px; font-size: 0.9rem; }
        .btn-brand { background-color: var(--brand-primary); color: white; border: none; border-radius: 8px; font-weight: 600; padding: 10px 15px; }
        .btn-brand:hover { background-color: var(--brand-dark); color: white; }
        .card-dash { border: none; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); margin-bottom: 20px; background: white; border-top: 4px solid var(--brand-primary); }
        .card-title-dash { font-size: 0.9rem; font-weight: 700; color: var(--brand-primary); text-transform: uppercase; margin-bottom: 1rem; display: flex; align-items: center; }
        .step-number { background: var(--brand-light); color: var(--brand-primary); width: 24px; height: 24px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-size: 0.8rem; margin-right: 10px; flex-shrink: 0; }
        .metric-box { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 15px; text-align: center; height: 100%; display: flex; flex-direction: column; justify-content: center; }
        .metric-value { font-size: 1.8rem; font-weight: 800; color: var(--brand-primary); margin: 5px 0; }
        .soap-output { font-family: 'Consolas', monospace; font-size: 0.9rem; border: 1px solid #e2e8f0; border-radius: 8px; background: #f8fafc; padding: 15px; width: 100%; min-height: 400px; resize: vertical; }
        .d-none { display: none !important; }
        
        /* Modificações novas */
        .slot-container { background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px; margin-bottom: 10px; }
        .comorbidade-check { font-size: 0.85rem; font-weight: 600; color: #4b5563; }
        .slot-row { display: flex; gap: 8px; align-items: center; margin-bottom: 5px; }
        .slot-row > select { flex: 2; }
        .slot-row > input { flex: 1; }
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
            <div class="nav-logo-box"><img src="/static/logo.jpg" class="nav-logo" alt="Logo" onerror="this.style.display='none'"></div>
            <button class="btn-nova-triagem" onclick="novaTriagem()"><i class="bi bi-arrow-clockwise me-1"></i> Nova Triagem</button>
        </div>
        <div class="d-flex align-items-center gap-4">
            <div class="d-flex align-items-center gap-4 me-2">
                <div class="nav-metric-box">
                    <div class="nav-metric-label">CLCR Calculado</div>
                    <div class="nav-metric-value" id="navClcr">-- mL/min</div>
                </div>
                <div class="nav-metric-box">
                    <div class="nav-metric-label">Alertas Gerais</div>
                    <div class="nav-alert-value" id="navAlertas">0</div>
                </div>
            </div>
            <div class="d-flex align-items-center gap-2">
                <button id="btnAdmin" class="btn-admin-nav d-none" data-bs-toggle="modal" data-bs-target="#adminModal"><i class="bi bi-person me-1"></i> ADMIN (ADMIN)</button>
                <button class="btn-sair" onclick="fazerLogout()"><i class="bi bi-box-arrow-right me-1"></i> Sair</button>
            </div>
        </div>
    </nav>

    <div class="container-fluid p-4" style="max-width: 1400px;">
        <div class="row g-4">
            <!-- Bloco 1 -->
            <div class="col-lg-3">
                <div class="card card-dash p-3 h-100">
                    <div class="card-title-dash"><span class="step-number">1</span> Perfil & Risco</div>
                    <div class="row g-2">
                        <div class="col-6"><label class="form-label-custom">Idade</label><input type="number" id="idade" class="form-control form-control-custom" value="65"></div>
                        <div class="col-6"><label class="form-label-custom">Sexo</label><select id="sexo" class="form-select form-control-custom"><option value="m">Masc</option><option value="f">Fem</option></select></div>
                    </div>
                    
                    <label class="form-label-custom mt-3">Comorbidades e Fatores de Risco</label>
                    <div class="bg-light p-2 rounded border" style="font-size: 0.85rem;">
                        <div class="form-check"><input class="form-check-input comorb-chk" type="checkbox" value="Acamado" id="chkAcamado"><label class="form-check-label text-danger fw-bold" for="chkAcamado">Paciente Acamado</label></div>
                        <div class="form-check"><input class="form-check-input comorb-chk" type="checkbox" value="HAS" id="chkHas"><label class="form-check-label" for="chkHas">Hipertensão (HAS)</label></div>
                        <div class="form-check"><input class="form-check-input comorb-chk" type="checkbox" value="DM" id="chkDm"><label class="form-check-label" for="chkDm">Diabetes (DM)</label></div>
                        <div class="form-check"><input class="form-check-input comorb-chk" type="checkbox" value="DRC" id="chkDrc"><label class="form-check-label" for="chkDrc">Insuf. Renal Crônica (DRC)</label></div>
                        <div class="form-check"><input class="form-check-input comorb-chk" type="checkbox" value="Hepatopatia" id="chkHepat"><label class="form-check-label" for="chkHepat">Hepatopatia Grave</label></div>
                    </div>
                </div>
            </div>

            <!-- Bloco 2 -->
            <div class="col-lg-3">
                <div class="card card-dash p-3 h-100">
                    <div class="card-title-dash"><span class="step-number">2</span> Antropometria</div>
                    <div class="row g-2 mb-3">
                        <div class="col-4"><label class="form-label-custom">Cr (mg/dL)</label><input type="number" step="0.1" id="creatinina" class="form-control form-control-custom" value="1.2"></div>
                        <div class="col-4"><label class="form-label-custom">Peso (kg)</label><input type="number" id="peso" class="form-control form-control-custom" value="70"></div>
                        <div class="col-4"><label class="form-label-custom">Alt (cm)</label><input type="number" id="altura" class="form-control form-control-custom" value="170"></div>
                    </div>
                    <div class="metric-box">
                        <div class="form-label-custom text-muted" style="font-size: 0.65rem;">DEPURAÇÃO ESTIMADA (COCKCROFT-GAULT)</div>
                        <div class="metric-value" id="valClcr">-- <span style="font-size:1rem;">mL/min</span></div>
                        <div class="small fw-bold text-secondary mt-1">Peso Adotado: <span id="valPesoAdotado">--</span> kg</div>
                    </div>
                </div>
            </div>

            <!-- Bloco 3 -->
            <div class="col-lg-6">
                <div class="card card-dash p-3 h-100">
                    <div class="card-title-dash"><span class="step-number">3</span> Extração Inteligente & Separação</div>
                    <div class="row g-3">
                        <div class="col-md-6">
                            <label class="form-label-custom text-primary"><i class="bi bi-file-pdf"></i> Passo A: Ler Prescrição</label>
                            <div class="input-group input-group-sm mb-2">
                                <input type="file" class="form-control" id="pdfFile" accept=".pdf">
                                <button class="btn btn-primary fw-bold" type="button" onclick="extrairPdf()">Extrair</button>
                            </div>
                            <!-- Apenas para referência ou rastreio -->
                            <textarea id="textoBruto" class="form-control form-control-custom mt-2" rows="3" placeholder="O PDF bruto será copiado aqui para referência do sistema..." style="font-size: 0.75rem; background-color: #f8fafc;" readonly></textarea>
                        </div>
                        <div class="col-md-6">
                            <label class="form-label-custom text-success"><i class="bi bi-box-seam"></i> Passo B: Outros Medicamentos Isolados</label>
                            <textarea id="outrosMedicamentos" class="form-control form-control-custom mt-1 border-success" rows="4" placeholder="O sistema colocará aqui automaticamente todos os medicamentos comuns encontrados no PDF (separados dos antimicrobianos)..."></textarea>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Bloco 4 -->
            <div class="col-12">
                <div class="card card-dash p-3">
                    <div class="d-flex justify-content-between align-items-center mb-3">
                        <div class="card-title-dash mb-0"><span class="step-number">4</span> Terapêutica Antimicrobiana & Avaliação Clínica</div>
                        <button class="btn btn-brand px-4 py-2 fs-6" onclick="gerarAnalise()"><i class="bi bi-robot me-2"></i> GERAR PARECER CLÍNICO</button>
                    </div>
                    <div class="row g-4">
                        <!-- SLOTS TURBINADOS -->
                        <div class="col-lg-5">
                            <div class="bg-light p-3 rounded border">
                                <label class="form-label-custom mb-3">Antimicrobianos Detectados (Para Julgamento Posológico)</label>
                                
                                <div class="slot-container" id="containerSlot1">
                                    <div class="slot-row">
                                        <select id="slot1" class="form-select form-control-custom form-select-sm"><option value="">-- Antimicrobiano 1 --</option></select>
                                        <input type="text" id="slot1_d" class="form-control form-control-custom form-control-sm" placeholder="Dia (Ex: D4)">
                                    </div>
                                    <input type="text" id="slot1_poso" class="form-control form-control-custom form-control-sm mt-1" placeholder="Posologia p/ Julgamento (Ex: 1000mg a cada 12h)">
                                </div>

                                <div class="slot-container" id="containerSlot2">
                                    <div class="slot-row">
                                        <select id="slot2" class="form-select form-control-custom form-select-sm"><option value="">-- Antimicrobiano 2 --</option></select>
                                        <input type="text" id="slot2_d" class="form-control form-control-custom form-control-sm" placeholder="Dia (Ex: D4)">
                                    </div>
                                    <input type="text" id="slot2_poso" class="form-control form-control-custom form-control-sm mt-1" placeholder="Posologia p/ Julgamento (Ex: 1000mg a cada 12h)">
                                </div>
                                
                                <div class="slot-container" id="containerSlot3">
                                    <div class="slot-row">
                                        <select id="slot3" class="form-select form-control-custom form-select-sm"><option value="">-- Antimicrobiano 3 --</option></select>
                                        <input type="text" id="slot3_d" class="form-control form-control-custom form-control-sm" placeholder="Dia (Ex: D4)">
                                    </div>
                                    <input type="text" id="slot3_poso" class="form-control form-control-custom form-control-sm mt-1" placeholder="Posologia p/ Julgamento (Ex: 1000mg a cada 12h)">
                                </div>

                            </div>
                        </div>
                        
                        <!-- PARECER SOAP -->
                        <div class="col-lg-7 position-relative">
                            <button class="btn btn-sm btn-outline-secondary position-absolute top-0 end-0 m-2 fw-bold" style="z-index: 10;" onclick="copiarSoap()"><i class="bi bi-copy"></i> Copiar SOAP</button>
                            <textarea id="parecerSoap" class="soap-output pt-5" readonly placeholder="Aguardando dados clínicos para gerar o parecer estruturado e o julgamento posológico..."></textarea>
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
    const user = document.getElementById('user').value; const pass = document.getElementById('pass').value;
    try {
        const res = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: user, password: pass }) });
        const data = await res.json();
        if (data.success) {
            document.getElementById('login-view').classList.add('d-none'); document.getElementById('app-view').classList.remove('d-none');
            if (data.role === 'admin') document.getElementById('btnAdmin').classList.remove('d-none');
            carregarCatalogo();
        } else { document.getElementById('loginError').classList.remove('d-none'); }
    } catch (e) {
        document.getElementById('loginError').innerText = "Erro ao contactar base de dados.";
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
    document.querySelectorAll('.comorb-chk').forEach(c => c.checked = false);
    
    document.getElementById('pdfFile').value = ''; 
    document.getElementById('textoBruto').value = '';
    document.getElementById('outrosMedicamentos').value = ''; 
    document.getElementById('parecerSoap').value = '';
    
    document.getElementById('valClcr').innerHTML = '-- <span style="font-size:1rem;">mL/min</span>';
    document.getElementById('navClcr').innerText = '-- mL/min';
    document.getElementById('navAlertas').innerText = '0';
    document.getElementById('valPesoAdotado').innerText = '--';
    
    ['slot1', 'slot2', 'slot3'].forEach(id => {
        document.getElementById(id).value = '';
        document.getElementById(id+'_d').value = '';
        document.getElementById(id+'_poso').value = '';
    });
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
        const selects = [document.getElementById("slot1"), document.getElementById("slot2"), document.getElementById("slot3")];
        selects.forEach(select => {
            if(select.options.length <= 1) { 
                catalogo.forEach(item => { const opt = document.createElement("option"); opt.value = item.nome; opt.innerText = item.nome; select.appendChild(opt); });
            }
        });
    } catch(e) {}
}

async function extrairPdf() {
    const fileInput = document.getElementById("pdfFile");
    if (!fileInput.files[0]) return alert("Selecione um PDF da prescrição.");
    const formData = new FormData(); formData.append("file", fileInput.files[0]);
    const res = await fetch("/api/extrair-pdf", { method: "POST", body: formData });
    const data = await res.json();
    
    // Passo A: Cola o texto bruto oculto/invisível para rastreio farmacotécnico
    document.getElementById("textoBruto").value = data.texto_anonimizado;
    
    // Passo B: A caixa "Outros Medicamentos" recebe os fármacos contínuos
    document.getElementById("outrosMedicamentos").value = data.outros_meds.join(", ");
    
    // Preenche os Slots com os ATBs encontrados
    const slots = ["slot1", "slot2", "slot3"];
    for (let i = 0; i < data.atbs.length && i < 3; i++) {
        document.getElementById(slots[i]).value = data.atbs[i].nome;
        // Se houver posologia extraída no futuro, entrará aqui.
    }
}

async function gerarAnalise() {
    // Recolher Comorbidades
    const comorbs = [];
    document.querySelectorAll('.comorb-chk:checked').forEach(c => comorbs.push(c.value));
    
    // Recolher Slots de ATBs
    const atbs = [];
    ['slot1', 'slot2', 'slot3'].forEach(id => {
        const nome = document.getElementById(id).value;
        if(nome) {
            atbs.push({
                nome: nome,
                dia: document.getElementById(id+'_d').value,
                poso: document.getElementById(id+'_poso').value
            });
        }
    });
    
    const payload = {
        sexo: document.getElementById("sexo").value,
        idade: parseInt(document.getElementById("idade").value) || 0,
        peso: parseFloat(document.getElementById("peso").value) || 0,
        altura: parseFloat(document.getElementById("altura").value) || 0,
        creatinina: parseFloat(document.getElementById("creatinina").value) || 0,
        comorbidades: comorbs,
        antimicrobianos: atbs,
        outros_medicamentos_texto: document.getElementById("outrosMedicamentos").value,
        texto_prescricao_bruto: document.getElementById("textoBruto").value
    };

    const res = await fetch("/api/avaliar", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const data = await res.json();

    document.getElementById("valClcr").innerHTML = data.metricas.clcr + ' <span style="font-size:1rem;">mL/min</span>';
    document.getElementById("navClcr").innerText = data.metricas.clcr + " mL/min";
    document.getElementById("navAlertas").innerText = data.alertas_count;
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
class ATBSlot(BaseModel):
    nome: str
    dia: str
    poso: str

class AvaliacaoPayload(BaseModel):
    sexo: str
    idade: int
    peso: float
    altura: float
    creatinina: float
    comorbidades: List[str]
    antimicrobianos: List[ATBSlot]
    outros_medicamentos_texto: str
    texto_prescricao_bruto: str

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
    try:
        conn = sqlite3.connect("radar_clinico.db")
        cursor = conn.cursor()
        cursor.execute("SELECT role FROM usuarios WHERE username = ? AND password = ?", (data.username, data.password))
        user = cursor.fetchone()
        conn.close()
        if user: return {"success": True, "role": user[0]}
        return {"success": False}
    except Exception as e:
        return {"success": False, "msg": "Erro DB"}

@app.post("/api/usuarios")
def criar_usuario(data: NovoUsuario):
    try:
        conn = sqlite3.connect("radar_clinico.db")
        cursor = conn.cursor()
        cursor.execute("INSERT INTO usuarios (username, password, role) VALUES (?, ?, ?)", (data.username, data.password, data.role))
        conn.commit()
        conn.close()
        return {"success": True}
    except: return {"success": False, "msg": "Erro ou usuário existe."}

@app.get("/api/antimicrobianos")
def get_antimicrobianos():
    conn = sqlite3.connect("radar_clinico.db")
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, nome_generico, nomes_comerciais FROM antimicrobianos ORDER BY nome_generico ASC")
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return [{"id": 0, "nome": "Carregando...", "nome_generico": "Aguarde"}]
    
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
    texto_anon = limpar_texto_prescricao(texto_bruto)
    texto_lower = texto_anon.lower()
    
    # 1. Filtro de Negação: Ignora linhas que contenham ordens de suspensão ou alergia
    linhas_validas = []
    palavras_negacao = ["suspender", "suspenso", "alergia", "não administrar", "parar"]
    for linha in texto_lower.split("\n"):
        if not any(neg in linha for neg in palavras_negacao):
            linhas_validas.append(linha)
    texto_limpo = " ".join(linhas_validas)
    
    conn = sqlite3.connect("radar_clinico.db")
    cursor = conn.cursor()
    cursor.execute("SELECT nome_generico, nomes_comerciais FROM antimicrobianos")
    atbs_db = cursor.fetchall()
    conn.close()
    
    atbs_encontrados = []
    for gen, com in atbs_db:
        nomes_para_buscar = [gen.lower()]
        if com: nomes_para_buscar.extend([c.strip().lower() for c in com.split(',')])
        for n in nomes_para_buscar:
            if n in texto_limpo:
                atbs_encontrados.append({"nome": f"{gen} ({com})" if com else gen})
                break

    # Simulação de Extração de Outros Medicamentos (Fármacos comuns)
    # Na próxima versão real, isto lerá de uma tabela `medicamentos_comuns`
    dicionario_comuns = ["dipirona", "omeprazol", "pantoprazol", "enoxaparina", "heparina", "furosemida", "losartana", "anlodipino", "ondansetrona"]
    comuns_encontrados = set()
    for med in dicionario_comuns:
        if med in texto_limpo:
            comuns_encontrados.add(med.capitalize())

    return {
        "texto_anonimizado": texto_anon,
        "atbs": atbs_encontrados,
        "outros_meds": list(comuns_encontrados)
    }

def extrair_mg_da_posologia(posologia: str) -> int:
    # Função simples para tentar achar o total diário (Ex: "1000mg a cada 12h" -> 2000)
    if not posologia: return 0
    match_dose = re.search(r'(\d+)\s*(mg|g)', posologia.lower())
    match_freq = re.search(r'(12h|8h|6h|24h)', posologia.lower())
    
    if not match_dose: return 0
    dose = int(match_dose.group(1))
    if match_dose.group(2) == 'g': dose *= 1000
    
    freq_multiplicador = 1
    if match_freq:
        if match_freq.group(1) == '12h': freq_multiplicador = 2
        elif match_freq.group(1) == '8h': freq_multiplicador = 3
        elif match_freq.group(1) == '6h': freq_multiplicador = 4
        
    return dose * freq_multiplicador

@app.post("/api/avaliar")
def avaliar_paciente(payload: AvaliacaoPayload):
    metricas = calcular_metricas(payload.sexo, payload.idade, payload.peso, payload.altura, payload.creatinina)
    clcr = metricas["clcr"]
    texto_bruto_min = payload.texto_prescricao_bruto.lower()
    alertas_count = 0
    
    conn = sqlite3.connect("radar_clinico.db")
    cursor = conn.cursor()
    
    # 1. Avaliação de Antimicrobianos (O NOVO JULGADOR)
    avaliacoes = []
    farmacotecnias = []
    
    for atb in payload.antimicrobianos:
        nome_generico = atb.nome.split(" (")[0]
        cursor.execute("SELECT * FROM antimicrobianos WHERE nome_generico = ?", (nome_generico,))
        row = cursor.fetchone()
        if row:
            max_padrao, max_30_50, max_10_30, max_10 = row[4], row[5], row[6], row[7]
            farm_info = row[9]
            
            # Determina limite diário baseado no ClCr
            limite_diario_permitido = 0
            if clcr >= 50: limite_diario_permitido = max_padrao
            elif 30 <= clcr < 50: limite_diario_permitido = max_30_50
            elif 10 <= clcr < 30: limite_diario_permitido = max_10_30
            else: limite_diario_permitido = max_10
                
            dose_diaria_digitada = extrair_mg_da_posologia(atb.poso)
            
            status_julgamento = ""
            if dose_diaria_digitada == 0:
                status_julgamento = f"Pendente (Insira a posologia para julgar. Limite max para este ClCr: {limite_diario_permitido}mg/dia)"
            elif dose_diaria_digitada > limite_diario_permitido:
                status_julgamento = f"ALERTA [!]: POSSÍVEL SUPERDOSAGEM para ClCr de {clcr} mL/min (Limite recomendado: {limite_diario_permitido}mg/dia)."
                alertas_count += 1
            else:
                status_julgamento = f"ADEQUADA para a função renal (ClCr {clcr} mL/min)."

            str_dia = f" ({atb.dia})" if atb.dia else ""
            avaliacoes.append(f"       * {nome_generico}{str_dia}: {atb.poso if atb.poso else 'S/ Posologia'} -> {status_julgamento}")
            farmacotecnias.append(f"• {nome_generico}: {farm_info}")

    # 2. Avaliação de Comorbidades de Risco
    riscos_comorbidade = set()
    if payload.comorbidades:
        cursor.execute("SELECT comorbidade, farmaco_contraindicado, alerta FROM comorbidades_risco")
        todas_regras_risco = cursor.fetchall()
        
        nomes_atbs_usados = [a.nome.lower() for a in payload.antimicrobianos]
        outros_meds_usados = payload.outros_medicamentos_texto.lower()
        
        for doenca_paciente in payload.comorbidades:
            for comorb_regra, farmaco_regra, alerta_regra in todas_regras_risco:
                if comorb_regra.lower() == doenca_paciente.lower():
                    # Checa se o paciente esta a tomar o farmaco perigoso
                    if any(farmaco_regra.lower() in atb for atb in nomes_atbs_usados) or farmaco_regra.lower() in outros_meds_usados:
                        riscos_comorbidade.add(f"[RISCO CLÍNICO] Paciente com {doenca_paciente} em uso de {farmaco_regra}: {alerta_regra}")
                        alertas_count += 1

    # 3. Motor de Incompatibilidades Farmacotécnicas (Linha a Linha no texto Bruto)
    incompatibilidades_encontradas = set()
    cursor.execute("SELECT farmaco, condicao, alerta FROM regras_farmacotecnicas")
    regras = cursor.fetchall()
    linhas_prescricao = texto_bruto_min.split('\n')
    for farmaco, condicao, alerta in regras:
        for linha in linhas_prescricao:
            if farmaco.lower() in linha and condicao.lower() in linha:
                incompatibilidades_encontradas.add(f"[ALERTA FARMACOTÉCNICO] {farmaco.upper()} + {condicao.upper()}: {alerta}")
                
    alertas_count += len(incompatibilidades_encontradas)
    conn.close()

    # 4. Filtro Clínico de Exceção (TEV e LAMG)
    is_acamado = "Acamado" in payload.comorbidades
    meds_gerais = payload.outros_medicamentos_texto.lower() + texto_bruto_min
    
    tem_heparina = "heparina" in meds_gerais or "enoxaparina" in meds_gerais or "versan" in meds_gerais
    tem_ibp = "omeprazol" in meds_gerais or "pantoprazol" in meds_gerais
    
    alerta_tev = ""
    if not tem_heparina and (payload.idade >= 60 or is_acamado):
        alerta_tev = "ALERTA [!]: Paciente de risco (Idoso/Acamado) SEM profilaxia anticoagulante prescrita. Avaliar omissão ou contraindicação."
        alertas_count += 1
    else:
        alerta_tev = "Conforme (Baixo risco ou Profilaxia já prescrita)."
        
    alerta_lamg = ""
    if tem_ibp:
        alerta_lamg = "ALERTA [!]: Protetor gástrico ativo. Reavaliar indicação (ex: uso de corticoides, risco de sangramento) para prevenir desprescrição inadequada."
        alertas_count += 1
    else:
        alerta_lamg = "Conforme (Sem protetor gástrico prescrito)."

    # Montagem Final do SOAP
    soap = [
        "=== EVOLUÇÃO FARMACÊUTICA // RADAR CLÍNICO ===",
        "[S] SUBJETIVO: Acompanhamento da farmacoterapia do leito. Triagem automática da prescrição médica.",
        "[O] OBJETIVO:",
        f"    - Idade: {payload.idade} anos | Sexo: {payload.sexo.upper()} | Peso Real: {payload.peso} kg | Altura: {payload.altura} cm",
        f"    - Função Renal (Cockcroft-Gault): {metricas['clcr']} mL/min (Peso para Ajuste: {metricas['peso_adotado']} kg)",
        f"    - Comorbidades mapeadas: {', '.join(payload.comorbidades) if payload.comorbidades else 'Nenhuma assinalada'}",
        "[A] AVALIAÇÃO FARMACÊUTICA:"
    ]
    
    soap.append("    1. Antimicrobianos (Julgamento Posológico Renal):")
    if avaliacoes:
        for a in avaliacoes: soap.append(a)
    else: 
        soap.append("       * Nenhum antimicrobiano submetido à avaliação.")
    
    soap.append("    2. Profilaxias Institucionais (Filtro por Exceção):")
    soap.append(f"       * TEV: {alerta_tev}")
    soap.append(f"       * LAMG: {alerta_lamg}")

    if riscos_comorbidade:
        soap.append("    3. Alertas de Segurança por Comorbidade:")
        for risco in riscos_comorbidade: soap.append(f"       * {risco}")

    if incompatibilidades_encontradas:
        soap.append("    4. Incompatibilidades Farmacotécnicas Detectadas:")
        for inc in incompatibilidades_encontradas: soap.append(f"       * {inc}")

    soap.append("[P] PLANO DE CUIDADO:")
    soap.append("    1. Sugerir adequação clínica/posológica à equipe médica conforme os alertas acima.")
    if farmacotecnias:
        soap.append("    2. Orientações de Reconstituição e Diluição (Preparo/Enfermagem):")
        for f in farmacotecnias: soap.append(f"       {f}")

    return {"metricas": metricas, "soap": "\n".join(soap), "alertas_count": alertas_count}

if __name__ == "__main__":
    threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:8000")).start()
    uvicorn.run("main:app", host="127.0.0.1", port=8000, log_level="warning")
