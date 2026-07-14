import json
import time
import requests

BASE_URL = "http://localhost:8000"
ARQUIVO_MOCK = "mock_data.json"
TEMPO_ENTRE_MENSAGENS = 3

def checar_saude():
    try:
        res = requests.get(f"{BASE_URL}/api/health", timeout=10)
        print(f"[health] status ok: {res.json()}")
        return True
    except:
        print(f"[ERRO] Falha ao conectar em {BASE_URL}. O container está rodando?")
        return False

def rodar_seed():
    print(f"\n--- Rodando seed de demonstração ---")
    requests.post(f"{BASE_URL}/api/demo/seed", timeout=15)
    print("[seed] Banco relacional resetado e populado.")

def enviar_mensagem(sessao: str, texto: str):
    print(f"\n>> Paciente ({sessao}): {texto}")
    res = requests.post(f"{BASE_URL}/api/chat", json={"sessao": sessao, "mensagem": texto}, timeout=30)
    if res.status_code == 200:
        print(f"<< Lúri: {res.json().get('resposta')}")
    else:
        print(f"[ERRO] {res.status_code}")

def rodar_conversa(nome_conversa: str, conversa: dict):
    print("\n" + "=" * 60)
    print(f"TESTE: {nome_conversa}")
    print("=" * 60)
    sessao = conversa["telefone_simulado"]
    for msg in conversa["mensagens"]:
        enviar_mensagem(sessao, msg)
        time.sleep(TEMPO_ENTRE_MENSAGENS)
    return sessao

def conferir_consulta(telefone: str):
    print(f"\n--- Conferindo consultas no banco para {telefone} ---")
    res = requests.get(f"{BASE_URL}/api/consultas", params={"telefone": telefone})
    dados = res.json()
    if dados:
        print(f"[OK] Consultas encontradas: {dados}")
    else:
        print(f"[ATENÇÃO] Nenhuma consulta encontrada para {telefone}.")

def main():
    if not checar_saude(): return
    with open(ARQUIVO_MOCK, "r", encoding="utf-8") as f:
        mock = json.load(f)
    
    rodar_seed()
    
    tel_novo = rodar_conversa("Paciente Novo", mock["conversa_teste_paciente_novo"])
    conferir_consulta(tel_novo)
    
    tel_existente = rodar_conversa("Paciente Existente", mock["conversa_teste_paciente_existente"])
    conferir_consulta(tel_existente)

if __name__ == "__main__":
    main()