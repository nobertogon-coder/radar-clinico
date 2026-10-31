import io
import itertools
import os
import sqlite3
import re
from datetime import date
from typing import Optional, List
from fastapi import FastAPI, Form, Request, Response, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pypdf import PdfReader

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DB_FILE = os.path.join(BASE_DIR, "clinica.db")

os.makedirs(STATIC_DIR, exist_ok=True)

app = FastAPI(title="Radar Clínico")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ==========================================
# 1. AUTENTICAÇÃO E LOGIN (ESTILO BEERS)
# ==========================================
def obter_usuario_logado(request: Request):
    token = request.cookies.get("session_token")
    if not token: return None
    try:
        with sqlite3.connect(DB_FILE) as conn:
            return conn.cursor().execute("SELECT usuario, perfil FROM usuarios WHERE usuario = ?", (token,)).fetchone()
    except Exception:
        return None

@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request, erro: str = ""):
    if obter_usuario_logado(request): 
        return RedirectResponse("/dashboard", 302)
    
    msg_erro = f"<div class='alert alert-danger p-2 small mb-3' style='border-radius:8px;'>{erro}</div>" if erro else ""
    
    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <title>Login | Radar Clínico</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body {{ background-color: #374151; height: 100vh; display: flex; align-items: center; justify-content: center; font-family: -apple-system, sans-serif; }}
            .login-card {{ background: #ffffff; border-radius: 12px; padding: 3rem 2.5rem; width: 100%; max-width: 400px; box-shadow: 0 10px 25px rgba(0,0,0,0.2); text-align: center; }}
            .logo-box {{ background-color: #F8FAFC; border-radius: 16px; width: 130px; height: 130px; margin: 0 auto 1.2rem auto; display: flex; align-items: center; justify-content: center; overflow: hidden; }}
            .logo-box img {{ max-width: 100%; max-height: 100%; object-fit: contain; }}
            .badge-acesso {{ background-color: #E0F2FE; color: #0E7490; font-weight: 700; font-size: 0.8rem; padding: 0.5rem 1.2rem; border-radius: 20px; margin-bottom: 2rem; display: inline-block; letter-spacing: 0.5px; border: 1px solid #BAE6FD; }}
            .form-label-custom {{ text-align: left; display: block; font-size: 0.75rem; font-weight: 700; color: #64748B; margin-bottom: 0.4rem; text-transform: uppercase; }}
            .form-control-custom {{ border-radius: 8px; border: 1px solid #CBD5E1; padding: 0.7rem 1rem; margin-bottom: 1.2rem; width: 100%; background: #F8FAFC; }}
            .form-control-custom:focus {{ border-color: #0E7490; outline: none; background: #fff; box-shadow: 0 0 0 3px rgba(14,116,144, 0.1); }}
            .btn-login {{ background-color: #0E7490; color: white; font-weight: 600; border: none; border-radius: 8px; padding: 0.8rem; width: 100%; transition: 0.2s; }}
            .btn-login:hover {{ background-color: #06B6D4; color: white; }}
        </style>
    </head>
    <body>
        <div class="login-card">
            <div class="logo-box">
                <img src="/static/logo.jpg" alt="Logo">
            </div>
            <div class="badge-acesso">ACESSO FARMACÊUTICO</div>
            {msg_erro}
            <form action="/login" method="post" style="text-align: left;">
                <label class="form-label-custom">Usuário</label>
                <input type="text" name="usuario" class="form-control-custom" placeholder="admin" required>
                <label class="form-label-custom">Senha</label>
                <input type="password" name="senha" class="form-control-custom" placeholder="••••••••" required>
                <button type="submit" class="btn-login">Entrar no Sistema</button>
            </form>
        </div>
    </body>
    </html>
    """)

@app.post("/login")
async def processar_login(usuario: str = Form(...), senha: str = Form(...)):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            user = conn.cursor().execute("SELECT usuario FROM usuarios WHERE usuario = ? AND senha = ?", (usuario.strip(), senha.strip())).fetchone()
        if user:
            res = RedirectResponse("/dashboard", 302)
            res.set_cookie("session_token", user[0], httponly=True)
            return res
        return RedirectResponse("/?erro=Credenciais+inválidas", 302)
    except Exception:
        return RedirectResponse("/?erro=Erro+no+servidor", 302)

@app.get("/logout")
async def logout():
    res = RedirectResponse("/", 302)
    res.delete_cookie("session_token")
    return res

# ==========================================
# 2. MOTOR CLÍNICO E LEITOR DE PDF
# ==========================================
def extrair_texto_pdf(arquivo_bytes: bytes):
    try:
        reader = PdfReader(io.BytesIO(arquivo_bytes))
        texto = " ".join([p.extract_text() for p in reader.pages if p.extract_text()]).lower()
        palavras_texto = set(re.findall(r'\b[a-zãõáéíóúç-]+\b', texto))
        
        with sqlite3.connect(DB_FILE) as conn:
            lista_atbs = conn.cursor().execute("SELECT id, nome FROM antibioticos").fetchall()
            outros = [r[0].lower() for r in conn.cursor().execute("SELECT DISTINCT farmaco_a FROM interacoes_db UNION SELECT DISTINCT farmaco_b FROM interacoes_db UNION SELECT farmaco FROM interacoes_alimento UNION SELECT termo_farmaco FROM interacoes_doenca").fetchall()]
        
        achados, achados_ids = [], []
        for atb_id, atb_nome in lista_atbs:
            nm = atb_nome.split("(")[0].strip().lower()
            if nm in palavras_texto: 
                achados.append(atb_nome.title())
                achados_ids.append(atb_id)
                
        for farmaco in outros:
            if farmaco in palavras_texto and farmaco.title() not in achados: achados.append(farmaco.title())
        return achados_ids[:4], ", ".join(achados)
    except Exception: return [], ""

def checar_alertas_multiplos(farmacos: list, comorbs: list, alergia: str):
    interacoes, alertas_clinicos, alertas_alergia = [], [], []
    farmacos_limpos = [f.lower().strip().split("(")[0].strip() for f in farmacos]
    
    with sqlite3.connect(DB_FILE) as conn:
        regras_int = conn.cursor().execute("SELECT farmaco_a, farmaco_b, gravidade, detalhe FROM interacoes_db").fetchall()
        regras_doenca = conn.cursor().execute("SELECT termo_farmaco, comorbidade, alerta FROM interacoes_doenca").fetchall()
        regras_alergia = conn.cursor().execute("SELECT farmaco_prescrito, risco FROM alergias_cruzadas WHERE classe_alergia='penicilina'").fetchall()

    for f1, f2 in itertools.combinations(farmacos_limpos, 2):
        for fa, fb, grav, det in regras_int:
            if (fa in f1 and fb in f2) or (fb in f1 and fa in f2):
                interacoes.append({"par": f"{f1.title()} + {f2.title()}", "gravidade": grav, "detalhe": det})
                
    for f in farmacos_limpos:
        for tf, c_db, alerta in regras_doenca:
            if tf in f and c_db in [c.lower() for c in comorbs]: alertas_clinicos.append(alerta)
        if alergia == "sim":
            for fp, risco in regras_alergia:
                if fp in f: alertas_alergia.append(f"Alergia Penicilina -> {f.title()}: {risco}")
                
    return interacoes, list(set(alertas_clinicos)), list(set(alertas_alergia))

# ==========================================
# 3. INTERFACE PRINCIPAL (LAYOUT RADAR BEERS)
# ==========================================
def gerar_html_dashboard(usuario, perfil, antibioticos=None, preenchimento_pdf="", pdf_atbs=None, resultado=None, aba_admin=False, msg_admin=""):
    pdf_atbs = pdf_atbs or []
    antibioticos = antibioticos or []
    clcr_display = f"{resultado['clcr']}" if resultado else "--"
    status_display = f"{len(resultado['interacoes'])} Alertas" if resultado else "0 Alertas"
    
    # Seção Admin ou Formulário Clínico
    if aba_admin:
        with sqlite3.connect(DB_FILE) as conn:
            lista_users = conn.cursor().execute("SELECT id, usuario, perfil FROM usuarios").fetchall()
        tbl_users = "".join([f"<tr><td>{u[1]}</td><td><span class='badge bg-{'teal' if u[2]=='admin' else 'secondary'}'>{u[2].upper()}</span></td></tr>" for u in lista_users])
        conteudo_corpo = f"""
        <div class="card-custom">
            <h5 class="fw-bold text-teal mb-4">Painel do Administrador</h5>
            {f"<div class='alert alert-info py-2'>{msg_admin}</div>" if msg_admin else ""}
            <div class="row">
                <div class="col-md-4">
                    <form action="/cadastrar_usuario" method="post" class="p-4 border rounded bg-light">
                        <label class="form-label-custom">Novo Usuário</label>
                        <input type="text" name="novo_usuario" class="form-control form-control-sm mb-3" required>
                        <label class="form-label-custom">Senha</label>
                        <input type="password" name="nova_senha" class="form-control form-control-sm mb-3" required>
                        <label class="form-label-custom">Perfil</label>
                        <select name="novo_perfil" class="form-select form-select-sm mb-4">
                            <option value="user">Padrão (Farmácia)</option>
                            <option value="admin">Administrador</option>
                        </select>
                        <button type="submit" class="btn btn-radar w-100">Cadastrar Acesso</button>
                    </form>
                </div>
                <div class="col-md-8">
                    <table class="table table-bordered bg-white">
                        <thead class="table-light"><tr><th>Usuário</th><th>Perfil de Acesso</th></tr></thead>
                        <tbody>{tbl_users}</tbody>
                    </table>
                </div>
            </div>
        </div>
        """
    else:
        tags_iniciais = "".join([f'<option value="{m.strip()}" selected>{m.strip()}</option>' for m in preenchimento_pdf.split(",") if m.strip()])
        slots_atb = ""
        for i in range(1, 5):
            selec = pdf_atbs[i-1] if (i-1) < len(pdf_atbs) else None
            op = '<option value="">(Selecione o antimicrobiano...)</option>'
            for a in antibioticos:
                sel = "selected" if selec == a[0] else ""
                op += f'<option value="{a[0]}" data-nome="{a[1]}" {sel}>{a[1]} ({a[2]})</option>'
            slots_atb += f'<div class="row g-2 mb-2"><div class="col-md-8"><select name="atb_id_{i}" class="select-search slot-atb">{op}</select></div><div class="col-md-4"><input type="text" name="dose_{i}" class="form-control form-control-sm" placeholder="Ex: 1g EV 8/8h"></div></div>'

        painel_resultado = '<div class="text-center text-muted p-5 bg-light rounded" style="border: 1px dashed #cbd5e1;">Nenhuma triagem realizada ainda.</div>'
        if resultado:
            alertas = ""
            for a in resultado.get("alertas_dieta", []): alertas += f"<div class='alert alert-warning p-2 small mb-2'><strong>Nutrição:</strong> {a}</div>"
            for a in resultado.get("alertas_doenca", []): alertas += f"<div class='alert alert-warning p-2 small mb-2'><strong>Comorbilidade:</strong> {a}</div>"
            for a in resultado.get("alertas_alergia", []): alertas += f"<div class='alert alert-danger p-2 small mb-2'><strong>Alergia:</strong> {a}</div>"
            for i in resultado.get("interacoes", []): alertas += f"<div class='alert alert-danger p-2 small mb-2'><strong>{i['gravidade']}:</strong> {i['par']} - {i['detalhe']}</div>"
            painel_resultado = f'<div class="d-flex justify-content-between mb-2"><h6 class="fw-bold text-teal mb-0">Avaliação SOAP</h6><button type="button" class="btn btn-outline-teal btn-sm py-0 px-2" onclick="copiarParecer()">Copiar</button></div>{alertas}<textarea id="parecerTexto" class="form-control font-monospace bg-light p-3 border rounded-3" rows="12" readonly>{resultado["parecer_texto"]}</textarea>'

        conteudo_corpo = f"""
        <div class="row g-4 mb-4">
            <!-- COLUNA 1: PACIENTE -->
            <div class="col-lg-4">
                <form id="formClinico" action="/avaliar" method="post">
                <div class="card-custom h-100">
                    <h6 class="card-title-custom"><span class="number-badge">1</span> PACIENTE E COMORBILIDADES</h6>
                    <div class="row g-2 mb-3">
                        <div class="col-6"><label class="form-label-custom">Idade</label><input type="number" name="idade" class="form-control form-control-sm"></div>
                        <div class="col-6"><label class="form-label-custom">Setor</label><select class="form-select form-select-sm"><option>Enfermaria</option></select></div>
                    </div>
                    <div class="row g-2 mb-3">
                        <div class="col-6"><label class="form-label-custom">Suporte/Dieta</label><select name="sonda_enteral" class="form-select form-select-sm"><option value="nao">Dieta Livre</option><option value="sim">Sonda Enteral</option></select></div>
                        <div class="col-6"><label class="form-label-custom">Diálise</label><select name="metodo_dialise" class="form-select form-select-sm"><option value="">Conservador</option><option value="HDI">Hemodiálise</option></select></div>
                    </div>
                    <label class="form-label-custom">Comorbilidades Clássicas</label>
                    <select name="comorbidades" id="comorb_select" multiple class="mb-3">
                        <option value="icc">Insuficiência Cardíaca (ICC)</option>
                        <option value="asma">Asma / DPOC</option>
                        <option value="epilepsia">Epilepsia / Convulsão</option>
                        <option value="hepatopatia">Disfunção Hepática</option>
                    </select>
                    <label class="form-label-custom text-danger">Alergia a Penicilinas?</label>
                    <select name="alergia_beta" class="form-select form-select-sm border-danger"><option value="nao">Não / Desconhecida</option><option value="sim">Sim (Grave)</option></select>
                </div>
            </div>

            <!-- COLUNA 2: RENAL & PROFILAXIAS -->
            <div class="col-lg-4">
                <div class="card-custom h-100">
                    <h6 class="card-title-custom"><span class="number-badge">2</span> FUNÇÃO RENAL & PROFILAXIAS</h6>
                    <div class="row g-2 mb-3">
                        <div class="col-6"><label class="form-label-custom">Creat. (mg/dL)</label><input type="number" step="0.01" name="creatinina" class="form-control form-control-sm"></div>
                        <div class="col-6"><label class="form-label-custom">Peso (kg)</label><input type="number" step="0.1" name="peso" class="form-control form-control-sm"></div>
                    </div>
                    <div class="bg-light p-3 rounded border text-center mb-3">
                        <small class="text-muted fw-bold d-block mb-1">DEPURAÇÃO ESTIMADA</small>
                        <h4 class="text-teal mb-0 fw-bold">{clcr_display} <small style="font-size:0.9rem">mL/min</small></h4>
                    </div>
                    <hr>
                    <div class="row g-2">
                        <div class="col-6"><label class="form-label-custom">Heparina?</label><select name="tev_prescrito" class="form-select form-select-sm"><option value="nao">Não</option><option value="sim">Sim</option></select></div>
                        <div class="col-6"><label class="form-label-custom">Escore Pádua</label><select name="pontos_padua" class="form-select form-select-sm"><option value="baixo">Baixo Risco</option><option value="alto">Alto Risco</option></select></div>
                        <div class="col-6"><label class="form-label-custom">Omeprazol/IBP?</label><select name="ibp_prescrito" class="form-select form-select-sm"><option value="nao">Não</option><option value="sim">Sim</option></select></div>
                        <div class="col-6"><label class="form-label-custom">Uso de AINEs?</label><select name="uso_aine_corticoide" class="form-select form-select-sm"><option value="nao">Não</option><option value="sim">Sim</option></select></div>
                        <div class="col-12"><label class="form-label-custom text-danger">Plaquetopenia / Sangramento?</label><select name="plaquetas_baixas" class="form-select form-select-sm border-danger"><option value="nao">Não</option><option value="sim">Sim (Risco)</option></select></div>
                    </div>
                </div>
            </div>

            <!-- COLUNA 3: LEITOR PDF -->
            <div class="col-lg-4">
                </form> <!-- Fecha o form principal temporariamente -->
                <div class="card-custom h-100">
                    <h6 class="card-title-custom"><span class="number-badge">3</span> ENTRADA DA PRESCRIÇÃO</h6>
                    <label class="form-label-custom">PRESCRIÇÃO EM PDF (MV / TASY)</label>
                    <form action="/upload_pdf" method="post" enctype="multipart/form-data" class="mb-3 p-3 bg-light rounded border">
                        <input type="file" name="arquivo_pdf" accept=".pdf" class="form-control form-control-sm mb-2" required>
                        <button type="submit" class="btn btn-dark w-100 btn-sm fw-bold">EXTRAIR PRESCRIÇÃO</button>
                    </form>
                    <label class="form-label-custom text-muted">OU SELECIONE OS MEDICAMENTOS</label>
                    <p class="small text-muted mb-1">A extração em PDF preencherá a lista abaixo automaticamente.</p>
                </div>
            </div>
        </div>
        
        <!-- LINHA 4: ANTIMICROBIANOS E AVALIAÇÃO -->
        <div class="card-custom">
            <h6 class="card-title-custom"><span class="number-badge">4</span> MEDICAMENTOS EM USO E AVALIAÇÃO</h6>
            <div class="row">
                <div class="col-md-5 border-end pe-4">
                    <form form="formClinico"> <!-- Reconecta os campos soltos ao form principal -->
                    <label class="form-label-custom">LISTA GERAL DE FÁRMACOS</label>
                    <select id="todos_medicamentos_select" name="todos_medicamentos_lista" multiple class="mb-4">{tags_iniciais}</select>
                    
                    <label class="form-label-custom">SLOTS DE ANTIMICROBIANOS</label>
                    {slots_atb}
                    
                    <button type="submit" class="btn btn-radar w-100 mt-3 fw-bold fs-6 py-2" onclick="document.getElementById('formClinico').submit();">AVALIAR PRESCRIÇÃO</button>
                    </form>
                </div>
                <div class="col-md-7 ps-4">
                    {painel_resultado}
                </div>
            </div>
        </div>
        """

    admin_btn = f'<a class="btn btn-sm btn-outline-light me-2 fw-bold" href="/admin">ADMIN (ACESSOS)</a>' if perfil == 'admin' else ''
    
    return f"""
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <title>Dashboard | Radar Clínico</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
        <link href="https://cdn.jsdelivr.net/npm/tom-select@2.3.1/dist/css/tom-select.bootstrap5.min.css" rel="stylesheet">
        <style>
            :root {{ --brand-teal: #0E7490; --brand-cyan: #06B6D4; --bg-color: #F0F4F8; }}
            body {{ background-color: var(--bg-color); font-family: -apple-system, sans-serif; padding-bottom: 2rem; }}
            .navbar-custom {{ background-color: var(--brand-teal); box-shadow: 0 2px 4px rgba(0,0,0,0.1); padding: 0.5rem 1.5rem; }}
            .logo-header {{ background: #fff; border-radius: 8px; width: 45px; height: 45px; display: flex; align-items: center; justify-content: center; overflow: hidden; }}
            .logo-header img {{ max-width: 100%; max-height: 100%; }}
            .card-custom {{ background: #fff; border-radius: 10px; border: 1px solid #E2E8F0; padding: 1.5rem; box-shadow: 0 4px 6px rgba(0,0,0,0.02); }}
            .card-title-custom {{ color: var(--brand-teal); font-weight: 700; font-size: 0.95rem; display: flex; align-items: center; margin-bottom: 1.2rem; }}
            .number-badge {{ background-color: #E0F2FE; color: var(--brand-teal); border-radius: 6px; width: 24px; height: 24px; display: inline-flex; align-items: center; justify-content: center; margin-right: 8px; font-weight: bold; font-size: 0.85rem; }}
            .form-label-custom {{ text-align: left; display: block; font-size: 0.7rem; font-weight: 700; color: #64748B; margin-bottom: 0.3rem; text-transform: uppercase; }}
            .btn-radar {{ background-color: var(--brand-teal); color: white; border: none; }}
            .btn-radar:hover {{ background-color: var(--brand-cyan); color: white; }}
            .text-teal {{ color: var(--brand-teal) !important; }}
        </style>
    </head>
    <body>
        <nav class="navbar navbar-expand-lg navbar-custom">
            <div class="container-fluid">
                <div class="d-flex align-items-center">
                    <div class="logo-header me-3"><img src="/static/logo.jpg" onerror="this.style.display='none'"></div>
                    <a class="btn btn-sm text-teal fw-bold" style="background-color: #06B6D4; color: white;" href="/dashboard">NOVA TRIAGEM</a>
                </div>
                <div class="d-flex align-items-center text-white">
                    <div class="me-4 text-end d-none d-md-block">
                        <small class="d-block" style="font-size: 0.65rem; color: #bae6fd; font-weight: bold;">CLCR CALCULADO</small>
                        <strong style="font-size: 1.1rem;">{clcr_display} <small>mL/min</small></strong>
                    </div>
                    <div class="me-4 text-end d-none d-md-block">
                        <small class="d-block" style="font-size: 0.65rem; color: #bae6fd; font-weight: bold;">ALERTAS CLÍNICOS</small>
                        <strong style="font-size: 1.1rem; color: #fef08a;">{status_display}</strong>
                    </div>
                    {admin_btn}
                    <div class="me-3 px-3 py-1 rounded d-none d-md-block" style="background: rgba(0,0,0,0.2);">
                        <small class="fw-bold"><i class="bi bi-person"></i> {usuario.upper()}</small>
                    </div>
                    <a href="/logout" class="btn btn-danger btn-sm fw-bold">Sair</a>
                </div>
            </div>
        </nav>
        
        <div class="container-fluid px-4 mt-4">
            {conteudo_corpo}
        </div>

        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/tom-select@2.3.1/dist/js/tom-select.complete.min.js"></script>
        <script>
            document.querySelectorAll('.select-search').forEach(el => new TomSelect(el, {{ create: false }}));
            const comorb = document.getElementById('comorb_select');
            if(comorb) new TomSelect(comorb, {{ create: false, plugins: ['remove_button'] }});
            const geral = document.getElementById('todos_medicamentos_select');
            if(geral) {{
                const selectGeral = new TomSelect(geral, {{ create: true, plugins: ['remove_button'] }});
                document.querySelectorAll('.slot-atb').forEach(selectEl => {{
                    selectEl.addEventListener('change', function() {{
                        const atbNome = this.options[this.selectedIndex]?.getAttribute('data-nome');
                        if (atbNome) {{ selectGeral.addOption({{ value: atbNome, text: atbNome }}); selectGeral.addItem(atbNome); }}
                    }});
                }});
            }}
            function copiarParecer() {{
                const el = document.getElementById("parecerTexto");
                if(el) {{ el.select(); navigator.clipboard.writeText(el.value); alert("Parecer copiado com sucesso!"); }}
            }}
        </script>
    </body>
    </html>
    """

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    user_data = obter_usuario_logado(request)
    if not user_data: return RedirectResponse("/", 302)
    with sqlite3.connect(DB_FILE) as conn:
        atbs = conn.cursor().execute("SELECT id, nome, classe FROM antibioticos ORDER BY nome ASC").fetchall()
    return gerar_html_dashboard(usuario=user_data[0], perfil=user_data[1], antibioticos=atbs)

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request, msg: str = ""):
    user_data = obter_usuario_logado(request)
    if not user_data or user_data[1] != 'admin': return RedirectResponse("/dashboard", 302)
    return gerar_html_dashboard(usuario=user_data[0], perfil=user_data[1], aba_admin=True, msg_admin=msg)

@app.post("/cadastrar_usuario")
async def cadastrar_usuario(request: Request, novo_usuario: str = Form(...), nova_senha: str = Form(...), novo_perfil: str = Form(...)):
    user_data = obter_usuario_logado(request)
    if not user_data or user_data[1] != 'admin': return RedirectResponse("/dashboard", 302)
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.cursor().execute("INSERT INTO usuarios (usuario, senha, perfil) VALUES (?, ?, ?)", (novo_usuario.strip(), nova_senha.strip(), novo_perfil))
            conn.commit()
        return RedirectResponse("/admin?msg=Usuário+cadastrado+com+sucesso!", 302)
    except sqlite3.IntegrityError:
        return RedirectResponse("/admin?msg=Erro:+Este+usuário+já+existe.", 302)

@app.post("/upload_pdf", response_class=HTMLResponse)
async def upload_pdf(request: Request, arquivo_pdf: UploadFile = File(...)):
    user_data = obter_usuario_logado(request)
    if not user_data: return RedirectResponse("/", 302)
    conteudo = await arquivo_pdf.read()
    pdf_atbs, meds = extrair_texto_pdf(conteudo)
    with sqlite3.connect(DB_FILE) as conn:
        atbs = conn.cursor().execute("SELECT id, nome, classe FROM antibioticos ORDER BY nome ASC").fetchall()
    return gerar_html_dashboard(usuario=user_data[0], perfil=user_data[1], antibioticos=atbs, preenchimento_pdf=meds, pdf_atbs=pdf_atbs)

@app.post("/avaliar", response_class=HTMLResponse)
async def avaliar(
    request: Request, idade: int=Form(0), peso: float=Form(0.0), creatinina: float=Form(0.0),
    metodo_dialise: str=Form(""), sonda_enteral: str=Form("nao"), alergia_beta: str=Form("nao"),
    comorbidades: List[str]=Form([]), todos_medicamentos_lista: List[str]=Form([]),
    atb_id_1: str=Form(""), atb_id_2: str=Form(""), atb_id_3: str=Form(""), atb_id_4: str=Form(""),
    tev_prescrito: str=Form("nao"), pontos_padua: str=Form("baixo"), plaquetas_baixas: str=Form("nao"),
    ibp_prescrito: str=Form("nao"), uso_aine_corticoide: str=Form("nao")
):
    user_data = obter_usuario_logado(request)
    if not user_data: return RedirectResponse("/", 302)

    clcr = round((((140 - idade) * peso) / (72 * max(creatinina, 0.8))), 1) if (creatinina > 0 and peso > 0 and idade > 0) else 0.0

    avaliacoes_atb, alertas_dieta = [], []
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        for i, atb_id_str in enumerate([atb_id_1, atb_id_2, atb_id_3, atb_id_4]):
            if atb_id_str.isdigit():
                atb = cursor.execute("SELECT nome, dose_padrao FROM antibioticos WHERE id = ?", (int(atb_id_str),)).fetchone()
                if atb:
                    if metodo_dialise == "HDI": ajuste = "Dose suplementar pós-sessão de hemodiálise."
                    else:
                        regra = cursor.execute("SELECT conduta FROM regras_renais WHERE antibiotico_id = ? AND ? >= clcr_min AND ? <= clcr_max", (int(atb_id_str), clcr, clcr)).fetchone()
                        ajuste = regra[0] if regra else "Dose padrão mantida."
                    
                    avaliacoes_atb.append(f"{i+1}. {atb[0]} | Recomendado: {atb[1]}\n   => Posologia Clínica (ClCr {clcr}): {ajuste}")
                    if atb[0] not in todos_medicamentos_lista: todos_medicamentos_lista.append(atb[0])

        if sonda_enteral == "sim":
            for med in todos_medicamentos_lista:
                r_dieta = cursor.execute("SELECT regra_dieta FROM interacoes_alimento WHERE farmaco = ?", (med.lower().strip(),)).fetchone()
                if r_dieta: alertas_dieta.append(r_dieta[0])
                
        atbs = cursor.execute("SELECT id, nome, classe FROM antibioticos ORDER BY nome ASC").fetchall()

    interacoes, alertas_doenca, alertas_alergia = checar_alertas_multiplos(todos_medicamentos_lista, comorbidades, alergia_beta)

    if plaquetas_baixas == "sim": tev = "[CONTRAINDICADO] Risco hemorrágico alto. Suspender TEV farmacológico."
    elif pontos_padua == "alto": tev = "[ADEQUADO] Alto Risco." if tev_prescrito == "sim" else "[ALERTA] Omissão de profilaxia TEV."
    elif tev_prescrito == "sim": tev = "[ALERTA DESPRESCRIÇÃO] Baixo risco no escore de Pádua com Heparina ativa."
    else: tev = "[ADEQUADO] Paciente de baixo risco sem necessidade de TEV."

    if uso_aine_corticoide == "sim": lamg = "[ADEQUADO] Fatores presentes." if ibp_prescrito == "sim" else "[ALERTA] Omissão de IBP."
    elif ibp_prescrito == "sim": lamg = "[ALERTA DESPRESCRIÇÃO] Uso de IBP sem indicação na enfermaria."
    else: lamg = "[ADEQUADO] Sem indicação de gastroproteção profilática."

    parecer = f"""RADAR CLÍNICO - TRIAGEM DE ENFERMARIA
Data: {date.today().strftime('%d/%m/%Y')}
ClCr Estimado: {clcr} mL/min | Suporte: {metodo_dialise if metodo_dialise else 'Conservador'}

[ANTIMICROBIANOS E FUNÇÃO RENAL]
{chr(10).join(avaliacoes_atb) if avaliacoes_atb else 'Sem prescrição de antimicrobianos sistémicos.'}

[PROFILAXIAS INSTITUCIONAIS]
TEV: {tev}
LAMG: {lamg}
"""
    res_dict = {"parecer_texto": parecer, "alertas_dieta": alertas_dieta, "alertas_doenca": alertas_doenca, "alertas_alergia": alertas_alergia, "interacoes": interacoes, "clcr": clcr}
    return gerar_html_dashboard(usuario=user_data[0], perfil=user_data[1], antibioticos=atbs, preenchimento_pdf=",".join(todos_medicamentos_lista), resultado=res_dict)
