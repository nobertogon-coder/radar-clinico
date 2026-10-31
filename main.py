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

# Garante que o sistema encontra a pasta estática e o banco de dados em qualquer ambiente (Render)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DB_FILE = os.path.join(BASE_DIR, "clinica.db")

os.makedirs(STATIC_DIR, exist_ok=True)

app = FastAPI(title="Radar Clínico")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ==========================================
# 1. MOTOR DE AUTENTICAÇÃO BLINDADO
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
    # Se já tem login válido, vai direto pro Dashboard
    if obter_usuario_logado(request): 
        return RedirectResponse("/dashboard", 302)
    
    msg_erro = f"<div class='alert alert-danger p-2 small mb-3' style='border-radius:8px;'>{erro}</div>" if erro else ""
    
    # LAYOUT IDÊNTICO À REFERÊNCIA DO RADAR BEERS (COM CORES DO CLÍNICO)
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
            .logo-box {{ background-color: #F8FAFC; border-radius: 16px; width: 130px; height: 130px; margin: 0 auto 1.2rem auto; display: flex; align-items: center; justify-content: center; }}
            .logo-box img {{ max-width: 100px; max-height: 100px; border-radius: 8px; }}
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
                <img src="/static/logo.jpg" alt="Logo" onerror="this.src='/static/ESSA.jpg'">
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
# 2. MOTOR CLÍNICO E PDF
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
            if farmaco in palavras_texto and farmaco.title() not in achados: 
                achados.append(farmaco.title())
                
        return achados_ids[:4], ", ".join(achados)
    except Exception: 
        return [], ""

def checar_alertas_multiplos(farmacos: list, comorbs: list, alergia: str):
    interacoes, alertas_clinicos, alertas_alergia = [], [], []
    farmacos_limpos = [f.lower().strip().split("(")[0].strip() for f in farmacos]
    
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        regras_int = cursor.execute("SELECT farmaco_a, farmaco_b, gravidade, detalhe FROM interacoes_db").fetchall()
        regras_doenca = cursor.execute("SELECT termo_farmaco, comorbidade, alerta FROM interacoes_doenca").fetchall()
        regras_alergia = cursor.execute("SELECT farmaco_prescrito, risco FROM alergias_cruzadas WHERE classe_alergia='penicilina'").fetchall()

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
# 3. INTERFACE INTERNA (DASHBOARD E ADMIN)
# ==========================================
def gerar_html_dashboard(usuario, perfil, antibioticos=None, preenchimento_pdf="", pdf_atbs=None, resultado=None, aba_admin=False, msg_admin=""):
    pdf_atbs = pdf_atbs or []
    antibioticos = antibioticos or []
    
    menu_admin = f'<a href="/admin" class="menu-item {"active" if aba_admin else ""}"><i class="me-2">⚙️</i> Gestão de Acessos</a>' if perfil == 'admin' else ''
    conteudo_principal = ""
    
    if aba_admin:
        with sqlite3.connect(DB_FILE) as conn:
            lista_users = conn.cursor().execute("SELECT id, usuario, perfil FROM usuarios").fetchall()
        tbl_users = "".join([f"<tr><td>{u[1]}</td><td><span class='badge bg-{'teal' if u[2]=='admin' else 'secondary'}'>{u[2].upper()}</span></td></tr>" for u in lista_users])
        conteudo_principal = f"""
        <div class="card-panel">
            <h5 class="fw-bold text-teal mb-4">Painel do Administrador</h5>
            {f"<div class='alert alert-info py-2'>{msg_admin}</div>" if msg_admin else ""}
            <div class="row">
                <div class="col-md-5">
                    <form action="/cadastrar_usuario" method="post" class="p-4 border rounded bg-light">
                        <label class="small fw-bold">Novo Usuário</label>
                        <input type="text" name="novo_usuario" class="form-control form-control-sm mb-2" required>
                        <label class="small fw-bold">Senha</label>
                        <input type="password" name="nova_senha" class="form-control form-control-sm mb-2" required>
                        <label class="small fw-bold">Perfil</label>
                        <select name="novo_perfil" class="form-select form-select-sm mb-4">
                            <option value="user">Padrão (Farmácia)</option>
                            <option value="admin">Administrador</option>
                        </select>
                        <button type="submit" class="btn btn-radar w-100 btn-sm">Cadastrar Acesso</button>
                    </form>
                </div>
                <div class="col-md-7">
                    <table class="table table-bordered">
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
            slots_atb += f'<div class="row g-2 mb-3 pb-3 border-bottom"><div class="col-md-6"><label class="small text-muted mb-1 fw-bold">Slot {i}</label><select name="atb_id_{i}" class="select-search slot-atb">{op}</select></div><div class="col-md-6"><label class="small text-muted mb-1 fw-bold">Dose Prescrita</label><input type="text" name="dose_{i}" class="form-control form-control-sm" placeholder="Ex: 1g EV 8/8h"></div></div>'

        painel_resultado = '<div class="h-100 d-flex flex-column align-items-center justify-content-center text-muted" style="min-height: 400px; opacity: 0.6;"><img src="/static/logo.jpg" alt="Logo" style="width: 100px; filter: grayscale(100%); opacity: 0.2; margin-bottom: 1rem;" onerror="this.src=\'/static/ESSA.jpg\'"><h6>Aguardando triagem clínica...</h6></div>'
        
        if resultado:
            alertas = ""
            for a in resultado.get("alertas_dieta", []): alertas += f"<div class='alert alert-warning p-2 small mb-2'><strong>Nutrição:</strong> {a}</div>"
            for a in resultado.get("alertas_doenca", []): alertas += f"<div class='alert alert-warning p-2 small mb-2'><strong>Comorbilidade:</strong> {a}</div>"
            for a in resultado.get("alertas_alergia", []): alertas += f"<div class='alert alert-danger p-2 small mb-2'><strong>Alergia:</strong> {a}</div>"
            for i in resultado.get("interacoes", []): alertas += f"<div class='alert alert-danger p-2 small mb-2'><strong>{i['gravidade']}:</strong> {i['par']} - {i['detalhe']}</div>"
            painel_resultado = f'<div class="d-flex justify-content-between mb-3 border-bottom pb-2"><h6 class="fw-bold text-teal mb-0">Parecer Clínico SOAP</h6><button type="button" class="btn btn-outline-teal btn-sm py-0 px-2" onclick="copiarParecer()">Copiar</button></div>{alertas}<textarea id="parecerTexto" class="form-control font-monospace bg-light p-3 border-0 rounded-3" rows="18" readonly>{resultado["parecer_texto"]}</textarea>'

        conteudo_principal = f"""
        <div class="card p-3 bg-white mb-3 border-0 shadow-sm rounded-3">
            <form action="/upload_pdf" method="post" enctype="multipart/form-data" class="row g-2 align-items-center">
                <div class="col-md-6"><span class="fw-bold text-teal small">📄 Leitor de Prescrição PDF (Tasy / MV / AGHUse)</span><br><small class="text-muted" style="font-size:0.7rem;">Dados anonimizados automaticamente pela LGPD.</small></div>
                <div class="col-md-4"><input type="file" name="arquivo_pdf" accept=".pdf" class="form-control form-control-sm" required></div>
                <div class="col-md-2"><button type="submit" class="btn btn-outline-teal btn-sm w-100 fw-bold">Ler Arquivo</button></div>
            </form>
        </div>
        <div class="row g-3">
            <div class="col-lg-7">
                <form action="/avaliar" method="post" class="card-panel h-100">
                    <ul class="nav nav-tabs mb-3"><li class="nav-item"><button class="nav-link active" id="p1-tab" data-bs-toggle="tab" data-bs-target="#tab-p1" type="button">1. Paciente</button></li><li class="nav-item"><button class="nav-link" id="p2-tab" data-bs-toggle="tab" data-bs-target="#tab-p2" type="button">2. Prescrição</button></li><li class="nav-item"><button class="nav-link" id="p3-tab" data-bs-toggle="tab" data-bs-target="#tab-p3" type="button">3. Profilaxias</button></li></ul>
                    <div class="tab-content">
                        <div class="tab-pane fade show active" id="tab-p1">
                            <div class="row g-3 mb-3">
                                <div class="col-4"><label class="small fw-bold">Idade</label><input type="number" name="idade" class="form-control form-control-sm"></div>
                                <div class="col-4"><label class="small fw-bold">Peso (kg)</label><input type="number" step="0.1" name="peso" class="form-control form-control-sm"></div>
                                <div class="col-4"><label class="small fw-bold">Creatinina</label><input type="number" step="0.01" name="creatinina" class="form-control form-control-sm"></div>
                                <div class="col-6"><label class="small fw-bold">Dieta / Sonda</label><select name="sonda_enteral" class="form-select form-select-sm"><option value="nao">Dieta Livre</option><option value="sim">Sonda Enteral Ativa</option></select></div>
                                <div class="col-6"><label class="small fw-bold">Diálise</label><select name="metodo_dialise" class="form-select form-select-sm"><option value="">Conservador</option><option value="HDI">Hemodiálise (HDI)</option></select></div>
                                <div class="col-12 mt-3 pt-2 border-top">
                                    <label class="small fw-bold text-teal mb-1">Comorbilidades Ativas</label>
                                    <select name="comorbidades" id="comorb_select" multiple><option value="icc">Insuficiência Cardíaca (ICC)</option><option value="asma">Asma / DPOC</option><option value="epilepsia">Epilepsia / Crise Convulsiva</option><option value="hepatopatia">Disfunção Hepática (Child-Pugh C)</option></select>
                                </div>
                                <div class="col-12 mt-2"><label class="small fw-bold text-danger mb-1">Alergia Grave a Penicilinas?</label><select name="alergia_beta" class="form-select form-select-sm border-danger"><option value="nao">Não / Desconhecida</option><option value="sim">SIM (Histórico Confirmado)</option></select></div>
                            </div>
                            <div class="text-end"><button type="button" class="btn btn-outline-secondary btn-sm" onclick="document.getElementById('p2-tab').click()">Avançar &rarr;</button></div>
                        </div>
                        <div class="tab-pane fade" id="tab-p2">
                            <label class="small fw-bold text-teal mb-1">Prescrição Geral (Autocompletar ou PDF)</label>
                            <select id="todos_medicamentos_select" name="todos_medicamentos_lista" multiple class="mb-3">{tags_iniciais}</select>
                            {slots_atb}
                            <div class="d-flex justify-content-between mt-2"><button type="button" class="btn btn-outline-secondary btn-sm" onclick="document.getElementById('p1-tab').click()">&larr; Voltar</button><button type="button" class="btn btn-outline-secondary btn-sm" onclick="document.getElementById('p3-tab').click()">Avançar &rarr;</button></div>
                        </div>
                        <div class="tab-pane fade" id="tab-p3">
                            <div class="p-3 bg-light rounded border mb-3">
                                <h6 class="small fw-bold text-dark mb-2 border-bottom pb-1">Segurança na Enfermaria</h6>
                                <div class="row g-2">
                                    <div class="col-6"><label class="small fw-bold">Heparina Prescrita?</label><select name="tev_prescrito" class="form-select form-select-sm"><option value="nao">Não</option><option value="sim">Sim</option></select></div>
                                    <div class="col-6"><label class="small fw-bold text-danger">Plaquetopenia/Sangra?</label><select name="plaquetas_baixas" class="form-select form-select-sm border-danger"><option value="nao">Não</option><option value="sim">Sim (Risco)</option></select></div>
                                    <div class="col-12"><label class="small fw-bold">Escore Pádua (TEV)</label><select name="pontos_padua" class="form-select form-select-sm"><option value="baixo">Baixo Risco</option><option value="alto">Alto Risco</option></select></div>
                                    <div class="col-6 mt-3"><label class="small fw-bold">IBP Prescrito (Omeprazol)?</label><select name="ibp_prescrito" class="form-select form-select-sm"><option value="nao">Não</option><option value="sim">Sim</option></select></div>
                                    <div class="col-6 mt-3"><label class="small fw-bold">Uso AINEs/Corticoide?</label><select name="uso_aine_corticoide" class="form-select form-select-sm"><option value="nao">Não</option><option value="sim">Sim</option></select></div>
                                </div>
                            </div>
                            <div class="d-flex justify-content-between mt-2"><button type="button" class="btn btn-outline-secondary btn-sm" onclick="document.getElementById('p2-tab').click()">&larr; Voltar</button><button type="submit" class="btn btn-radar">Gerar Avaliação SOAP</button></div>
                        </div>
                    </div>
                </form>
            </div>
            <div class="col-lg-5"><div class="card-panel h-100">{painel_resultado}</div></div>
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <title>Dashboard | Radar Clínico</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
        <link href="https://cdn.jsdelivr.net/npm/tom-select@2.3.1/dist/css/tom-select.bootstrap5.min.css" rel="stylesheet">
        <style>
            :root {{ --brand-teal: #0E7490; --brand-cyan: #06B6D4; --sidebar-bg: #0F172A; }}
            body {{ background-color: #F8FAFC; color: #1E293B; display: flex; height: 100vh; overflow: hidden; font-family: -apple-system, sans-serif; }}
            .sidebar {{ width: 260px; background-color: var(--sidebar-bg); color: #fff; display: flex; flex-direction: column; flex-shrink: 0; }}
            .sidebar-logo {{ padding: 1.5rem; border-bottom: 1px solid #1E293B; display: flex; align-items: center; gap: 12px; }}
            .menu-item {{ padding: 0.85rem 1.5rem; color: #94A3B8; text-decoration: none; display: block; font-weight: 500; font-size: 0.9rem; transition: 0.2s; }}
            .menu-item:hover, .menu-item.active {{ background-color: #1E293B; color: #fff; border-left: 4px solid var(--brand-cyan); }}
            .main-content {{ flex-grow: 1; overflow-y: auto; display: flex; flex-direction: column; }}
            .topbar {{ background: #fff; padding: 1rem 1.5rem; border-bottom: 1px solid #E2E8F0; display: flex; justify-content: space-between; align-items: center; }}
            .content-area {{ padding: 1.5rem; overflow-y: auto; }}
            .card-panel {{ background: #fff; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.03); padding: 1.5rem; border-top: 4px solid var(--brand-teal); margin-bottom: 1rem; }}
            .nav-tabs .nav-link {{ color: #64748B; font-weight: 600; font-size: 0.85rem; border: none; border-bottom: 2px solid transparent; padding: 0.65rem 1rem; cursor: pointer; }}
            .nav-tabs .nav-link.active {{ color: var(--brand-teal); border-bottom: 2px solid var(--brand-teal); background: transparent; }}
            .text-teal {{ color: var(--brand-teal) !important; }}
            .text-cyan {{ color: var(--brand-cyan) !important; }}
            .bg-teal {{ background-color: var(--brand-teal) !important; }}
            .btn-radar {{ background: var(--brand-teal); color: white; border: none; font-weight: 600; padding: 0.5rem 1rem; border-radius: 8px; }}
            .btn-radar:hover {{ background: var(--brand-cyan); color: white; }}
            .btn-outline-teal {{ color: var(--brand-teal); border-color: var(--brand-teal); font-weight: 600; }}
            .btn-outline-teal:hover {{ background: var(--brand-teal); color: white; }}
        </style>
    </head>
    <body>
        <div class="sidebar">
            <div class="sidebar-logo">
                <img src="/static/logo.jpg" alt="Logo" style="height: 40px; border-radius: 6px;" onerror="this.src='/static/ESSA.jpg'">
                <div><div style="font-weight: 700; font-size: 1.1rem; line-height: 1;">RADAR</div><div class="text-cyan" style="font-size: 0.65rem; text-transform: uppercase; font-weight: bold;">Clínico - Enfermaria</div></div>
            </div>
            <div class="flex-grow-1 py-3">
                <a href="/dashboard" class="menu-item {"active" if not aba_admin else ""}">🩺 Triagem Clínica</a>
                {menu_admin}
            </div>
            <div class="p-3 border-top" style="border-color: #1E293B !important;">
                <div class="small text-muted mb-2 px-2">Logado como: <strong>{usuario.upper()}</strong></div>
                <a href="/logout" class="btn btn-outline-secondary btn-sm w-100 border-0 text-start text-light">⏻ Sair do Sistema</a>
            </div>
        </div>
        <div class="main-content">
            <div class="topbar"><h5 class="mb-0 fw-bold text-teal">{"Gestão de Usuários" if aba_admin else "Ambiente de Triagem"}</h5><span class="badge bg-light text-teal border py-2 px-3 rounded-pill">{"Painel Admin" if aba_admin else "Hospital / Enfermaria"}</span></div>
            <div class="content-area">{conteudo_principal}</div>
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
    if not user_data: return RedirectResponse("/logout", 302)
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
    res_dict = {"parecer_texto": parecer, "alertas_dieta": alertas_dieta, "alertas_doenca": alertas_doenca, "alertas_alergia": alertas_alergia, "interacoes": interacoes}
    return gerar_html_dashboard(usuario=user_data[0], perfil=user_data[1], antibioticos=atbs, preenchimento_pdf=",".join(todos_medicamentos_lista), resultado=res_dict)
