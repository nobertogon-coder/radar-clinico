import sqlite3
import re
from typing import List, Optional
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import pypdf
import threading
import webbrowser
import uvicorn

app = FastAPI(title="Radar Clínico", description="Sistema de Apoio à Decisão Farmacêutica")

# ==============================================================================
# 1. MOTOR CLÍNICO
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
# 2. INTERFACE VISUAL (CARMIM / ARDÓSIA + ABAS + MARCA D'ÁGUA)
# ==============================================================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Radar Clínico - Farmácia Hospitalar</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css" rel="stylesheet">
    <style>
        :root {
            --brand-primary: #722F37;
            --brand-dark: #3b171c;
            --brand-slate: #2c3e50;
            --brand-teal: #16697a;
            --bg-canvas: #f8fafc;
        }
        body { background-color: var(--bg-canvas); font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; color: #334155; }
        .header-radar { background: linear-gradient(135deg, var(--brand-primary) 0%, var(--brand-dark) 100%); color: #ffffff; padding: 16px 24px; border-radius: 12px; margin-bottom: 24px; }
        .card-custom { border: 1px solid #e2e8f0; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.04); background: #ffffff; margin-bottom: 20px; }
        .nav-tabs .nav-link { color: #64748b; font-weight: 600; padding: 12px 20px; border-bottom: 3px solid transparent; }
        .nav-tabs .nav-link.active { color: var(--brand-primary); border-bottom: 3px solid var(--brand-primary); background: transparent; }
        .metric-badge { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; text-align: center; }
        .metric-value { font-size: 1.4rem; font-weight: 700; color: var(--brand-primary); }
        .slot-atb { background-color: #f8fafc; border: 1px dashed #cbd5e1; border-radius: 8px; padding: 12px; margin-bottom: 10px; }
        .soap-container { position: relative; background: #ffffff; border-radius: 8px; border: 1px solid #e2e8f0; overflow: hidden; }
        .watermark-bg { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-size: 4.5rem; font-weight: 900; color: rgba(114, 47, 55, 0.04); letter-spacing: 4px; pointer-events: none; user-select: none; }
        .soap-output { position: relative; z-index: 1; background: transparent; font-family: monospace; font-size: 0.90rem; line-height: 1.5; color: #1e293b; border: none; width: 100%; resize: vertical; padding: 16px; outline: none; }
        .btn-carmim { background-color: var(--brand-primary); color: #ffffff; border: none; }
        .btn-carmim:hover { background-color: var(--brand-dark); color: #ffffff; }
    </style>
</head>
<body class="p-3 p-md-4">
<div class="container-fluid max-width-1300">

    <div class="header-radar d-flex justify-content-between align-items-center">
        <div>
            <h3 class="fw-bold mb-1"><i class="bi bi-shield-plus me-2"></i>Radar Clínico</h3>
            <p class="mb-0 text-white-50 small">Sistema Farmacêutico Hospitalar de Suporte à Decisão Clínica</p>
        </div>
        <div>
            <span class="badge bg-white text-dark me-2 py-2 px-3"><i class="bi bi-check-circle-fill text-success"></i> LGPD</span>
        </div>
    </div>

    <div class="row g-2 mb-3">
        <div class="col-md-3 col-6"><div class="metric-badge"><div class="small fw-bold">ClCr Estimado</div><div class="metric-value" id="valClcr">--</div><span class="small">mL/min</span></div></div>
        <div class="col-md-3 col-6"><div class="metric-badge"><div class="small fw-bold">IMC</div><div class="metric-value text-dark" id="valImc">--</div><span class="small">kg/m²</span></div></div>
        <div class="col-md-3 col-6"><div class="metric-badge"><div class="small fw-bold">Peso Ideal</div><div class="metric-value text-dark" id="valPesoIdeal">--</div><span class="small">kg</span></div></div>
        <div class="col-md-3 col-6"><div class="metric-badge"><div class="small fw-bold">Peso Adotado</div><div class="metric-value" style="color: var(--brand-teal);" id="valPesoAdotado">--</div><span class="small">kg</span></div></div>
    </div>

    <div class="row">
        <div class="col-lg-5">
            <div class="card card-custom">
                <div class="card-header bg-white pb-0">
                    <ul class="nav nav-tabs card-header-tabs" role="tablist">
                        <li class="nav-item"><button class="nav-link active" data-bs-toggle="tab" data-bs-target="#content-paciente">1. Paciente</button></li>
                        <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#content-atb">2. Terapêutica</button></li>
                        <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#content-profilaxias">3. Profilaxias</button></li>
                    </ul>
                </div>
                
                <div class="card-body tab-content pt-3">
                    <div class="tab-pane fade show active" id="content-paciente">
                        <h6 class="fw-bold small text-uppercase">Importação (PDF)</h6>
                        <div class="input-group input-group-sm mb-2">
                            <input type="file" class="form-control" id="pdfFile" accept=".pdf">
                            <button class="btn btn-outline-secondary" onclick="extrairPdf()">Anonimizar</button>
                        </div>
                        <textarea id="textoPrescricao" class="form-control form-control-sm mb-3" rows="3"></textarea>

                        <h6 class="fw-bold small text-uppercase">Parâmetros</h6>
                        <div class="row g-2">
                            <div class="col-6"><label class="small">Sexo</label><select id="sexo" class="form-select form-select-sm"><option value="m">Masculino</option><option value="f">Feminino</option></select></div>
                            <div class="col-6"><label class="small">Idade</label><input type="number" id="idade" class="form-control form-control-sm" value="65"></div>
                            <div class="col-4"><label class="small">Peso (kg)</label><input type="number" id="peso" class="form-control form-control-sm" value="70"></div>
                            <div class="col-4"><label class="small">Altura (cm)</label><input type="number" id="altura" class="form-control form-control-sm" value="170"></div>
                            <div class="col-4"><label class="small">Cr (mg/dL)</label><input type="number" step="0.1" id="creatinina" class="form-control form-control-sm" value="1.2"></div>
                        </div>
                        <button class="btn btn-carmim w-100 btn-sm mt-3" onclick="gerarAnalise()">Calcular & Avaliar</button>
                    </div>

                    <div class="tab-pane fade" id="content-atb">
                        <div class="slot-atb"><label class="small fw-bold">Slot 1</label><select id="slot1" class="form-select form-select-sm"><option value="">-- Nenhum --</option></select></div>
                        <div class="slot-atb"><label class="small fw-bold">Slot 2</label><select id="slot2" class="form-select form-select-sm"><option value="">-- Nenhum --</option></select></div>
                        <div class="slot-atb"><label class="small fw-bold">Slot 3</label><select id="slot3" class="form-select form-select-sm"><option value="">-- Nenhum --</option></select></div>
                        <div class="slot-atb"><label class="small fw-bold">Slot 4</label><select id="slot4" class="form-select form-select-sm"><option value="">-- Nenhum --</option></select></div>
                        <button class="btn btn-carmim w-100 btn-sm mt-2" onclick="gerarAnalise()">Atualizar Parecer</button>
                    </div>

                    <div class="tab-pane fade" id="content-profilaxias">
                        <div class="form-check p-2 border rounded mb-2 bg-light">
                            <input class="form-check-input ms-0 me-2" type="checkbox" id="profilaxiaTev" checked>
                            <label class="form-check-label small fw-bold" for="profilaxiaTev">Profilaxia de TEV</label>
                        </div>
                        <div class="form-check p-2 border rounded mb-3 bg-light">
                            <input class="form-check-input ms-0 me-2" type="checkbox" id="profilaxiaLamg" checked>
                            <label class="form-check-label small fw-bold" for="profilaxiaLamg">Profilaxia LAMG</label>
                        </div>
                        <label class="small fw-bold">Outros (Rastreio Interações)</label>
                        <input type="text" id="outrosMedicamentos" class="form-control form-control-sm" placeholder="Ex: amiodarona, furosemida...">
                        <button class="btn btn-carmim w-100 btn-sm mt-3" onclick="gerarAnalise()">Consolidar Parecer</button>
                    </div>
                </div>
            </div>
        </div>

        <div class="col-lg-7">
            <div class="card card-custom p-3 h-100 d-flex flex-column">
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <h5 class="fw-bold mb-0">Evolução (SOAP)</h5>
                    <button class="btn btn-outline-dark btn-sm" onclick="copiarSoap()">Copiar</button>
                </div>
                <div class="soap-container flex-grow-1 position-relative">
                    <div class="watermark-bg">RADAR CLÍNICO</div>
                    <textarea id="parecerSoap" class="soap-output" rows="22" readonly></textarea>
                </div>
            </div>
        </div>
    </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
document.addEventListener("DOMContentLoaded", async () => {
    const res = await fetch("/api/antimicrobianos");
    const catalogo = await res.json();
    const selects = [document.getElementById("slot1"), document.getElementById("slot2"), document.getElementById("slot3"), document.getElementById("slot4")];
    
    selects.forEach(select => {
        catalogo.forEach(item => {
            const opt = document.createElement("option");
            opt.value = item.nome; 
            opt.innerText = item.nome;
            select.appendChild(opt);
        });
    });
});

async function extrairPdf() {
    const fileInput = document.getElementById("pdfFile");
    if (!fileInput.files[0]) return alert("Selecione um PDF.");
    const formData = new FormData(); formData.append("file", fileInput.files[0]);
    const res = await fetch("/api/extrair-pdf", { method: "POST", body: formData });
    const data = await res.json();
    document.getElementById("textoPrescricao").value = data.texto_anonimizado;
}

async function gerarAnalise() {
    const atbs = [document.getElementById("slot1").value, document.getElementById("slot2").value, document.getElementById("slot3").value, document.getElementById("slot4").value].filter(i => i !== "");
    const outros = document.getElementById("outrosMedicamentos").value.split(",").map(s => s.trim()).filter(s => s.length > 0);

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
    document.getElementById("valImc").innerText = data.metricas.imc;
    document.getElementById("valPesoIdeal").innerText = data.metricas.peso_ideal;
    document.getElementById("valPesoAdotado").innerText = data.metricas.peso_adotado;
    document.getElementById("parecerSoap").value = data.soap;
}

function copiarSoap() {
    const txt = document.getElementById("parecerSoap");
    txt.select(); navigator.clipboard.writeText(txt.value);
    alert("Copiado!");
}
</script>
</body>
</html>
"""

# ==============================================================================
# 3. ROTAS E LÓGICA DA API
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
    # Verifica de forma segura se a tabela já possui a coluna nova
    try:
        cursor.execute("SELECT id, nome_generico, nomes_comerciais FROM antimicrobianos ORDER BY nome_generico ASC")
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return [{"id": 0, "nome": "Erro: Base não atualizada. Rode setup_db.py primeiro.", "nome_generico": "Erro"}]
    
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

    # Interações
    todos_farmacos_genericos.extend(payload.outros_medicamentos)
    interacoes_encontradas = []
    
    for i in range(len(todos_farmacos_genericos)):
        for j in range(i + 1, len(todos_farmacos_genericos)):
            d1, d2 = todos_farmacos_genericos[i], todos_farmacos_genericos[j]
            cursor.execute("""
                SELECT gravidade, mecanismo, conduta FROM interacoes 
                WHERE (LOWER(droga_a) = LOWER(?) AND LOWER(droga_b) = LOWER(?)) 
                   OR (LOWER(droga_a) = LOWER(?) AND LOWER(droga_b) = LOWER(?))
            """, (d1, d2, d2, d1))
            res = cursor.fetchone()
            if res:
                interacoes_encontradas.append({"par": f"{d1} + {d2}", "gravidade": res[0], "detalhe": res[1], "conduta": res[2]})

    conn.close()

    # Formatação SOAP
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
    # Função para abrir automaticamente no PC/Pendrive
    threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:8000")).start()
    uvicorn.run("main:app", host="127.0.0.1", port=8000, log_level="warning")
