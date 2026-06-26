# ==========================================================
# LINAIA-AGON — servidor OSC + HTTP
#
# Recebe do SC via OSC (porta 57200):
#   /linaia/scenario  cenario_string
#   /linaia/start
#   /linaia/stop
#
# Envia ao SC via OSC (porta 57120):
#   /linaia/tactic  cenario tatica confianca
#
# Serve ao HTML via HTTP (porta 8765):
#   GET /state  → JSON com estado completo
#   GET /       → CORS headers para localhost
#
# Dependências: pip3 install python-osc pyaudio librosa scipy numpy
# ==========================================================

from collections import Counter

import numpy as np # pyright: ignore[reportMissingImports]
import librosa # pyright: ignore[reportMissingImports]
try:
    import pyaudio # type: ignore
    HAVE_PYAUDIO = True
except ImportError:
    pyaudio = None
    HAVE_PYAUDIO = False
import threading
import json
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from scipy.signal import find_peaks, savgol_filter # pyright: ignore[reportMissingImports]
from pythonosc import udp_client, dispatcher, osc_server # pyright: ignore[reportMissingImports]
import warnings
warnings.filterwarnings('ignore')

# ── CONFIGURAÇÃO ──────────────────────────────────────────
SC_IP        = "127.0.0.1"
SC_PORT      = 57120
LISTEN_PORT  = 57200
HTTP_PORT    = 8765
SR           = 22050
CHUNK        = 1024
JANELA_SEG   = 6.0
PASSO_SEG    = 1.0
JANELA_AMOSTRAS = int(JANELA_SEG * SR)
PASSO_AMOSTRAS  = int(PASSO_SEG  * SR)

# ── ESTADO COMPARTILHADO ──────────────────────────────────
estado = {
    # cenários por canal
    "cenario":        "alpha_Linos",
    "cenario_linos":  "alpha_Linos",
    "cenario_apollo": "alpha_Apollon",
    # táticas por canal
    "tatica_linos":   0,
    "tatica_apollo":  0,
    "features_linos":  {},
    "features_apollo": {},
    "ativo":     False,
    "tatica":    0,
    "confianca": 0.0,
    "features":  {},
    "historico": [],
    "scoreLinos":  0,
    "scoreApollo": 0,
    "batalha":   "alpha",
    "segmento":  0,
    "escutando": False,
}
lock = threading.Lock()

# ── EXTRAÇÃO E CLASSIFICADOR DISTÂNCIA EUCLIDIANA ──────────────────

def extrair_features_fft(audio, sr=22050):
    audio = audio - np.mean(audio)
    if np.max(np.abs(audio)) < 0.001:
        return None

    N = len(audio)
    fft = np.fft.rfft(audio)
    amps = np.abs(fft) / N
    freqs = np.fft.rfftfreq(N, d=1/sr)

    a = amps[1:]  # ignora DC (0 Hz)
    f = freqs[1:]

    freq_dom     = float(f[np.argmax(a)])
    centroide    = float(np.sum(f * a) / (np.sum(a) + 1e-10))
    espalhamento = float(np.sqrt(np.sum(((f - centroide)**2) * a) / (np.sum(a) + 1e-10)))
    energia      = float(np.sum(a**2))
    integral     = float(np.trapezoid(a, f))  
    duracao      = N / sr

    return {
        "freq_dom":     round(freq_dom, 1),
        "centroide":    round(centroide, 1),
        "espalhamento": round(espalhamento, 1),
        "energia":      round(energia / duracao, 8),
        "integral":     round(integral / duracao, 6),
    }

# Vetores de referência (fonte são os calculos no jupiter a partir das gravações originais)
REFERENCIAS = {
    "alpha_Apollon": {
        1: {"freq_dom": 313.6, "centroide": 1326.0, "espalhamento": 1894.2, "energia": 0.000604, "integral": 0.1106},
        2: {"freq_dom": 143.4, "centroide": 531.0,  "espalhamento": 972.5,  "energia": 0.000497, "integral": 0.0742},
        3: {"freq_dom": 181.5, "centroide": 663.2,  "espalhamento": 1116.5, "energia": 0.000374, "integral": 0.0768},
        4: {"freq_dom": 0,     "centroide": 0,      "espalhamento": 0,      "energia": 1e-8,     "integral": 0.00001},
    },
    "alpha_Linos": {
        1: {"freq_dom": 317.0, "centroide": 994.2,  "espalhamento": 1049.3, "energia": 0.000877, "integral": 0.0938},
        2: {"freq_dom": 396.7, "centroide": 1099.6, "espalhamento": 1187.1, "energia": 0.002171, "integral": 0.3067},
        3: {"freq_dom": 225.6, "centroide": 602.5,  "espalhamento": 588.7,  "energia": 0.000237, "integral": 0.0784},
        4: {"freq_dom": 0,     "centroide": 0,      "espalhamento": 0,      "energia": 1e-8,     "integral": 0.00001},
    },
    "beta_Apollon": {
        1: {"freq_dom": 397.0, "centroide": 1353.3, "espalhamento": 1742.7, "energia": 0.007505, "integral": 0.2047},
        2: {"freq_dom": 648.5, "centroide": 1318.9, "espalhamento": 1470.1, "energia": 0.003917, "integral": 0.4475},
        3: {"freq_dom": 297.3, "centroide": 627.8,  "espalhamento": 936.7,  "energia": 0.000099, "integral": 0.0338},
        4: {"freq_dom": 0,     "centroide": 0,      "espalhamento": 0,      "energia": 1e-8,     "integral": 0.00001},
    },
    "beta_Linos": {
        1: {"freq_dom": 475.6, "centroide": 1158.5, "espalhamento": 1302.7, "energia": 0.017463, "integral": 0.6605},
        2: {"freq_dom": 294.2, "centroide": 1229.1, "espalhamento": 1419.7, "energia": 0.020043, "integral": 1.0855},
        3: {"freq_dom": 249.0, "centroide": 617.8,  "espalhamento": 551.5,  "energia": 0.003839, "integral": 0.3093},
        4: {"freq_dom": 0,     "centroide": 0,      "espalhamento": 0,      "energia": 1e-8,     "integral": 0.00001},
    },
    "gamma_Apollon": {
        1: {"freq_dom": 174.2, "centroide": 898.9,  "espalhamento": 1184.8, "energia": 0.000910, "integral": 0.2093},
        2: {"freq_dom": 347.1, "centroide": 947.4,  "espalhamento": 1300.2, "energia": 0.001810, "integral": 0.2501},
        3: {"freq_dom": 499.4, "centroide": 718.3,  "espalhamento": 875.9,  "energia": 0.003817, "integral": 0.3364},
        4: {"freq_dom": 0,     "centroide": 0,      "espalhamento": 0,      "energia": 1e-8,     "integral": 0.00001},
    },
    "gamma_Linos": {
        1: {"freq_dom": 356.6, "centroide": 1000.5, "espalhamento": 1000.7, "energia": 0.000036, "integral": 0.0333},
        2: {"freq_dom": 320.6, "centroide": 992.1,  "espalhamento": 1226.3, "energia": 0.000027, "integral": 0.0274},
        3: {"freq_dom": 363.4, "centroide": 1026.5, "espalhamento": 1241.3, "energia": 0.000049, "integral": 0.0458},
        4: {"freq_dom": 0,     "centroide": 0,      "espalhamento": 0,      "energia": 0.0,      "integral": 0.00001},
    },
}

# Pesos para cada feature na distância euclidiana
PESOS = {
    "freq_dom":      1.0,   # Muito importante
    "centroide":     0.8,   # Centro de gravidade espectral
    "espalhamento":  0.6,   # Largura da distribuição
    "energia":       0.3,   # Menos importante, varia com volume
    "integral":      0.5,   # Área sob a curva
}


def classificar(cenario, f):
    """
    Classifica pela menor distância euclidiana normalizada
    entre o vetor de features observado e os vetores de referência.
    """
    # Silêncio 
    if f is None:
        return 4, 1.00

    if f.get("energia", 0) < 1e-7:
        return 4, 1.00

    refs = REFERENCIAS.get(cenario)
    if refs is None:
        return 1, 0.50  # cenário desconhecido — fallback

    distancias = {}
    for tatica, ref in refs.items():
        dist = 0.0
        peso_total = 0.0

        for feat, peso in PESOS.items():
            if feat in f and feat in ref:
                ref_val = ref[feat]
                obs_val = f[feat]

                # Normaliza pelo valor de referência (evita que features
                # com magnitudes muito diferentes dominem a distância)
                if ref_val > 0.0001:
                    diff = abs(obs_val - ref_val) / ref_val
                else:
                    diff = abs(obs_val - ref_val)

                dist += peso * diff
                peso_total += peso

        # Distância média ponderada
        if peso_total > 0:
            distancias[tatica] = dist / peso_total
        else:
            distancias[tatica] = float('inf')

    if not distancias:
        return 1, 0.50

    # Encontra a menor distância
    tatica_pred = min(distancias, key=distancias.get)
    dist_min = distancias[tatica_pred]

    # Calcula confiança baseada na diferença para a segunda menor distância
    dists = sorted(distancias.values())
    if len(dists) > 1 and dists[0] > 0:
        # Quanto maior a diferença relativa, maior a confiança
        confianca = (dists[1] - dists[0]) / (dists[0] + 1e-10)
        confianca = 1.0 / (1.0 + np.exp(-confianca * 0.5))  
    else:
        confianca = 0.50

    return tatica_pred, round(float(confianca), 3)

# ── THREAD DE ÁUDIO ───────────────────────────────────────
DEVICE_INDEX = None  # None = dispositivo padrão; troca pelo número da interface 8828 no musidance

def thread_audio():
    if not HAVE_PYAUDIO:
        print("[áudio] pyaudio não disponível.")
        return

    try:
        pa = pyaudio.PyAudio()

        idx = DEVICE_INDEX if DEVICE_INDEX is not None else pa.get_default_input_device_info()["index"]
        info = pa.get_device_info_by_index(idx)
        max_ch = int(info["maxInputChannels"])
        canais = 2 if max_ch >= 2 else 1
        print(f"[áudio] dispositivo [{idx}] '{info['name']}' → {canais} canal(is)")

        stream = pa.open(
            format=pyaudio.paFloat32,
            channels=canais,
            rate=SR,
            input=True,
            input_device_index=DEVICE_INDEX,
            frames_per_buffer=CHUNK
        )
    except Exception as exc:
        print(f"[áudio] erro ao abrir stream: {exc}")
        return

    client = udp_client.SimpleUDPClient(SC_IP, SC_PORT)

    acumulado_linos  = np.zeros(0, dtype=np.float32)
    acumulado_apollo = np.zeros(0, dtype=np.float32)

    # históricos separados para votação
    hist_linos  = []
    hist_apollo = []

    print(f"[áudio] estéreo capturando @ {SR}Hz  (L=Linos, R=Apollo)")

    while True:
        with lock:
            ativo = estado["ativo"]
        if not ativo:
            time.sleep(0.05)
            acumulado_linos  = np.zeros(0, dtype=np.float32)
            acumulado_apollo = np.zeros(0, dtype=np.float32)
            hist_linos.clear()
            hist_apollo.clear()
            continue

        raw      = stream.read(CHUNK, exception_on_overflow=False)
        chunk_np = np.frombuffer(raw, dtype=np.float32)

        # separa canais — estéreo intercala L e R; mono replica para ambos
        if canais == 2:
            acumulado_linos  = np.concatenate([acumulado_linos,  chunk_np[0::2]])
            acumulado_apollo = np.concatenate([acumulado_apollo, chunk_np[1::2]])
        else:
            # mono: mesmo sinal nos dois canais (útil para teste com 1 microfone)
            acumulado_linos  = np.concatenate([acumulado_linos,  chunk_np])
            acumulado_apollo = np.concatenate([acumulado_apollo, chunk_np])

        # processa canal
        def processar_canal(janela_np, hist, cenario, nome, osc_path):
            features = extrair_features_fft(janela_np, SR)
            tatica, conf = (4, 1.00) if features is None else classificar(cenario, features)
            hist.append(tatica)
            if len(hist) > 10: hist.pop(0)
            hist_r = hist[-5:]
            hist_s = [v for v in hist_r if v != 4]
            if not hist_s:                                  estavel = 4
            elif len(hist_s) < len(hist_r) * 0.4:          estavel = 4
            else:                                           estavel = Counter(hist_s).most_common(1)[0][0]
            with lock:
                estado[f"tatica_{nome}"]   = estavel
                estado[f"features_{nome}"] = features or {}
            client.send_message(osc_path, [cenario, estavel, round(conf, 3)])
            print(f"[{nome}] T{estavel} conf={conf:.2f} "
                  + (f"freq={features['freq_dom']:.1f}Hz" if features else "silêncio"))

        with lock:
            cen_linos  = estado["cenario_linos"]
            cen_apollo = estado["cenario_apollo"]

        while len(acumulado_linos) >= JANELA_AMOSTRAS:
            processar_canal(acumulado_linos[:JANELA_AMOSTRAS],
                            hist_linos, cen_linos, "linos", "/linaia/tactic/linos")
            acumulado_linos = acumulado_linos[PASSO_AMOSTRAS:]

        while len(acumulado_apollo) >= JANELA_AMOSTRAS:
            processar_canal(acumulado_apollo[:JANELA_AMOSTRAS],
                            hist_apollo, cen_apollo, "apollo", "/linaia/tactic/apollo")
            acumulado_apollo = acumulado_apollo[PASSO_AMOSTRAS:]

# ── SERVIDOR HTTP ─────────────────────────────────────────
# O HTML faz GET /state a cada 500ms e recebe o estado como JSON.
# Isso elimina a necessidade de WebSocket ou OSC no browser.

class HTMLHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  

    def do_GET(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")

        # Serve o HTML da interface quando acessar http://localhost:8765/
        if self.path == "/" or self.path == "/index.html":
            import os
            html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Inteface3.html")
            if os.path.exists(html_path):
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                with open(html_path, "rb") as f:
                    self.wfile.write(f.read())
                return
            else:
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Interface3.html nao encontrada na mesma pasta que o servidor.")
                return

        # Serve o estado JSON em qualquer outra rota (incluindo /state)
        self.send_header("Content-Type", "application/json")
        self.end_headers()

        with lock:
            resp = {
                "tatica_linos":    estado.get("tatica_linos", 0),
                "tatica_apollo":   estado.get("tatica_apollo", 0),
                "features_linos":  estado.get("features_linos", {}),
                "features_apollo": estado.get("features_apollo", {}),
                "ativo":           estado["ativo"],
                "escutando":       estado["escutando"],
                "batalha":         estado["batalha"],
                "segmento":        estado["segmento"],
                "cenario_linos":   estado.get("cenario_linos", "alpha_Linos"),
                "cenario_apollo":  estado.get("cenario_apollo", "alpha_Apollon"),
                "scoreLinos":      estado["scoreLinos"],
                "scoreApollo":     estado["scoreApollo"],
            }
        self.wfile.write(json.dumps(resp).encode())

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

# ── HANDLERS OSC ─────────────────────────────────────────

def handler_scenario(addr, cenario_novo):
    with lock:
        if "Linos" in cenario_novo:
            estado["cenario_linos"] = cenario_novo
        else:
            estado["cenario_apollo"] = cenario_novo
        if "alpha" in cenario_novo:   estado["batalha"] = "alpha"
        elif "beta" in cenario_novo:  estado["batalha"] = "beta"
        elif "gamma" in cenario_novo: estado["batalha"] = "gamma"
    print(f"[osc] cenário → {cenario_novo}")

def handler_battle(addr, battle):
    with lock:
        estado["batalha"] = battle
    print(f"[osc] batalha → {battle}")

def handler_start(addr):
    with lock:
        estado["ativo"]     = True
        estado["escutando"] = True
    print("[osc] escuta ATIVA")

def handler_stop(addr):
    with lock:
        estado["ativo"]     = False
        estado["escutando"] = False
    print("[osc] escuta PAUSADA")

def handler_score(addr, score_linos, score_apollo):
    with lock:
        estado["scoreLinos"]  = int(score_linos)
        estado["scoreApollo"] = int(score_apollo)
    print(f"[osc] placar → Linos {score_linos} | Apollo {score_apollo}")

def handler_segment(addr, seg_num):
    with lock:
        estado["segmento"] = int(seg_num)
    print(f"[osc] segmento → {seg_num}")

# ── LISTAR DISPOSITIVOS ───────────────────────────────────
def listar_dispositivos():
    if not HAVE_PYAUDIO:
        print("\n[aviso] pyaudio não disponível; não é possível listar dispositivos de áudio.\n")
        return

    pa = pyaudio.PyAudio()
    print("\nDispositivos de entrada:")
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if info["maxInputChannels"] > 0:
            print(f"  [{i}] {info['name']}")
    pa.terminate()
    print()

# ── MAIN ─────────────────────────────────────────────────
if __name__ == "__main__":
    if HAVE_PYAUDIO:
        listar_dispositivos()
        threading.Thread(target=thread_audio, daemon=True).start()
    else:
        print("[aviso] pyaudio não instalado; servidor HTTP e OSC iniciarão sem captura de áudio.")

    # Servidor HTTP para o HTML
    http = HTTPServer(("0.0.0.0", HTTP_PORT), HTMLHandler)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    print(f"[http] servindo estado em http://localhost:{HTTP_PORT}/state")

    # Servidor OSC para receber do SC
    disp = dispatcher.Dispatcher()
    disp.map("/linaia/scenario", handler_scenario)
    disp.map("/linaia/start",    handler_start)
    disp.map("/linaia/stop",     handler_stop)
    disp.map("/linaia/battle", handler_battle)
    disp.map("/linaia/score",    handler_score)
    disp.map("/linaia/segment",  handler_segment)

    osc = osc_server.ThreadingOSCUDPServer(("0.0.0.0", LISTEN_PORT), disp)
    print(f"[osc]  escutando SC em porta {LISTEN_PORT}")
    print(f"[osc]  enviando para SC em {SC_IP}:{SC_PORT}")
    print("Ctrl+C para encerrar\n")

    try:
        osc.serve_forever()
    except KeyboardInterrupt:
        estado["ativo"] = False
        http.shutdown()
        print("Encerrado.")