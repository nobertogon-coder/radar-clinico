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
