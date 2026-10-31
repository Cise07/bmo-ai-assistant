import whisper
import ollama
import speech_recognition as sr
import subprocess
import pygame
import os
import threading
import queue
import time
import logging
from datetime import datetime
from ddgs import DDGS
import json
from PIL import Image, ImageDraw


# ===========================================================================
# LOGGING
# ===========================================================================
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.join("logs", "bmo.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("BMO")


# ===========================================================================
# STATES
# ===========================================================================
IDLE, LISTENING, THINKING, SPEAKING = "IDLE", "LISTENING", "THINKING", "SPEAKING"


# ===========================================================================
# CONFIGURATION CLASS 
# ===========================================================================
class BMOConfig:
    """Loads and exposes all settings from config.json. Read-only after init."""

    _DEFAULTS: dict = {
        "MODEL_OLLAMA": "gemma3:4b",
        "WAKE_WORD": "bmo",
        "PIPER_PATH": "C:/piper/piper.exe",
        "PIPER_MODEL": "C:/piper/it_IT-paola-medium.onnx",
        "WHISPER_MODEL_TYPE": "small",
        "BASE_FACES_PATH": "./faces",
        "OUTPUT_WAV": "recs/bmo_voice.wav",
        "TEMP_INPUT_WAV": "recs/temp_audio.wav",
        "MAX_HISTORY_TURNS": 6,
        "MAX_RESPONSE_WORDS": 15,
        "AUDIO_VOLUME": 1.0,
        "FOLDER_NAMES": {
            "IDLE": "idle",
            "LISTENING": "listening",
            "THINKING": "thinking",
            "SPEAKING": "speaking",
        },
    }

    _FILE = "config.json"

    def __init__(self) -> None:
        data = self._load()
        self.MODEL_OLLAMA: str = data["MODEL_OLLAMA"]
        self.WAKE_WORD: str = data["WAKE_WORD"]
        self.PIPER_PATH: str = data["PIPER_PATH"]
        self.PIPER_MODEL: str = data["PIPER_MODEL"]
        self.WHISPER_MODEL_TYPE: str = data["WHISPER_MODEL_TYPE"]
        self.BASE_FACES_PATH: str = data["BASE_FACES_PATH"]
        self.OUTPUT_WAV: str = data["OUTPUT_WAV"]
        self.TEMP_INPUT_WAV: str = data["TEMP_INPUT_WAV"]
        self.MAX_HISTORY_TURNS: int = int(data.get("MAX_HISTORY_TURNS", 6))
        self.MAX_RESPONSE_WORDS: int = int(data.get("MAX_RESPONSE_WORDS", 15))
        self.AUDIO_VOLUME: float = float(data.get("AUDIO_VOLUME", 1.0))
        fn = data["FOLDER_NAMES"]
        self.FOLDERS: dict[str, str] = {
            IDLE:     os.path.join(self.BASE_FACES_PATH, fn["IDLE"]),
            LISTENING: os.path.join(self.BASE_FACES_PATH, fn["LISTENING"]),
            THINKING:  os.path.join(self.BASE_FACES_PATH, fn["THINKING"]),
            SPEAKING:  os.path.join(self.BASE_FACES_PATH, fn["SPEAKING"]),
        }


    # ===========================================================================
    # SYSTEM PROMPT
    # ===========================================================================

    @property
    def SYSTEM_PROMPT(self) -> str:
        return (
            f"Sei BMO di Adventure Time. Rispondi sempre in italiano. "
            f"Usa frasi corte e semplici. Il tuo tono è ingenuo, robotico e gentile. "
            f"Non usare mai più di {self.MAX_RESPONSE_WORDS} parole e non usare mai emoji. "
            f"Se ricevi informazioni esterne marcate come CONTESTO, "
            f"usale per dare la risposta corretta alla domanda."
        )

    def _load(self) -> dict:
        if not os.path.exists(self._FILE):
            log.warning("config.json non trovato — creo defaults.")
            with open(self._FILE, "w", encoding="utf-8") as f:
                json.dump(self._DEFAULTS, f, indent=4)
            return dict(self._DEFAULTS)
        with open(self._FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = dict(self._DEFAULTS)
        merged.update(data)
        return merged


# ===========================================================================
# STATE CLASS 
# ===========================================================================
class BMOState:
    """Thread-safe runtime state. All reads/writes go through a Lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: str = IDLE
        self._is_busy: bool = False
        # Event che il GUI thread setta per interrompere il TTS (#14)
        self._stop_speaking = threading.Event()
        # Cronologia conversazione rolling (#6)
        self._history: list[dict] = []

    # --- current state ---
    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @state.setter
    def state(self, value: str) -> None:
        with self._lock:
            self._state = value

    # --- busy flag ---
    @property
    def is_busy(self) -> bool:
        with self._lock:
            return self._is_busy

    @is_busy.setter
    def is_busy(self, value: bool) -> None:
        with self._lock:
            self._is_busy = value

    # --- TTS stop signal (#14) ---
    def request_stop_speaking(self) -> None:
        log.info("Stop TTS richiesto dall'utente.")
        self._stop_speaking.set()

    def clear_stop_speaking(self) -> None:
        self._stop_speaking.clear()

    def should_stop_speaking(self) -> bool:
        return self._stop_speaking.is_set()

    # --- conversation history (#6) ---
    def add_to_history(self, role: str, content: str, max_turns: int) -> None:
        self._history.append({"role": role, "content": content})
        # Mantieni solo gli ultimi max_turns turni (ogni turno = 1 user + 1 assistant)
        cap = max_turns * 2
        if len(self._history) > cap:
            self._history = self._history[-cap:]

    def get_history(self) -> list[dict]:
        return list(self._history)

    def clear_history(self) -> None:
        self._history.clear()


# ===========================================================================
# UI CONSTANTS & COLORS
# ===========================================================================
WINDOW_WIDTH  = 400
WINDOW_HEIGHT = 286
FACE_HEIGHT   = 240
CONTROL_HEIGHT = 46

CHASSIS_TEAL = (64, 153, 138)
CHASSIS_DARK = (32, 85, 76)

INPUT_BG           = (224, 250, 235)
INPUT_BG_ACTIVE    = (236, 255, 245)
INPUT_BORDER       = (38, 98, 86)
INPUT_BORDER_ACTIVE = (18, 62, 54)
TEXT_COLOR         = (14, 38, 32)
PLACEHOLDER_COLOR  = (78, 132, 120)

BTN_SEND_BG     = (38, 56, 64)
BTN_SEND_HOVER  = (50, 72, 82)
BTN_SEND_SHADOW = (22, 34, 40)
BTN_SEND_TEXT   = (245, 255, 250)

BTN_MIC_BG      = (250, 198, 38)
BTN_MIC_HOVER   = (255, 212, 60)
BTN_MIC_SHADOW  = (205, 155, 20)
MIC_COLOR_NORMAL = (35, 45, 40)

BTN_MIC_RECORDING   = (235, 68, 68)
BTN_MIC_REC_SHADOW  = (180, 40, 40)

BTN_MIC_BUSY        = (130, 155, 150)
BTN_MIC_BUSY_SHADOW = (100, 125, 120)

BTN_MIC_STOP        = (200, 40, 40)   # rosso scuro → STOP durante SPEAKING
BTN_MIC_STOP_SHADOW = (140, 20, 20)


# ===========================================================================
# WEB SEARCH
# ===========================================================================
def bmo_web_search(query: str) -> str:
    """Queries DuckDuckGo. Returns concatenated body texts or error string."""
    log.info(f"Web search: {query!r}")
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
        if results:
            return "\n".join(f"Fonte: {r['body']}" for r in results)
        return "Nessun risultato trovato online."
    except Exception as exc:
        log.error(f"Web search error: {exc}")
        return "Errore di connessione ai circuiti di ricerca."


# ===========================================================================
# INTENT DETECTION 
# ===========================================================================
_DATETIME_KW = frozenset([
    "ore", "ora", "orario", "giorno", "data", "oggi", "adesso",
    "momento", "che ore", "che giorno", "che data",
])
_WEB_KW = frozenset([
    "chi", "cosa", "qual", "quale", "quando", "dove", "scritto",
    "autore", "meteo", "tempo fa", "notizie", "perché", "perche",
    "come mai", "spiegami", "dimmi", "cos'è", "dov'è",
    "dove si trova", "quanto costa", "prezzo", "news",
    "ultimo", "recente", "inventato", "fondato", "creato",
])
# Personal questions -> never web search , always local
_LOCAL_KW = frozenset([
    "come stai", "come ti chiami", "chi sei", "cosa sei",
    "ciao", "salve", "buongiorno", "buonasera", "sei bmo",
])


def detect_intent(question: str) -> str:
    """Returns 'local', 'datetime', or 'web'."""
    q = question.lower()
    if any(kw in q for kw in _LOCAL_KW):
        return "local"
    if any(kw in q for kw in _DATETIME_KW):
        return "datetime"
    if any(kw in q for kw in _WEB_KW):
        return "web"
    return "local"


# ===========================================================================
# CONTEXT BUILDING 
# ===========================================================================
def build_context(question: str) -> str:
    """Returns enriched context string, or empty string if not needed."""
    intent = detect_intent(question)
    log.debug(f"Intent: {intent!r}")

    if intent == "datetime":
        now = datetime.now()
        days = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
        return (
            f"L'orario attuale è {now.strftime('%H:%M')}. "
            f"Oggi è {days[now.weekday()]} {now.strftime('%d/%m/%Y')}."
        )
    if intent == "web":
        return bmo_web_search(question)
    return ""

# ===========================================================================
# LLM QUERY 
# ===========================================================================
def query_llm(
    question: str,
    context: str,
    state: BMOState,
    config: BMOConfig,
) -> str:
    """Builds messages (system + history + question) and queries Ollama."""
    final_prompt = (
        f"CONTESTO: {context}\n\nDOMANDA: {question}" if context else question
    )

    messages = [{"role": "system", "content": config.SYSTEM_PROMPT}]
    messages += state.get_history()
    messages.append({"role": "user", "content": final_prompt})

    try:
        response = ollama.chat(model=config.MODEL_OLLAMA, messages=messages)
        answer: str = response["message"]["content"]
    except Exception as exc:
        log.error(f"Ollama error: {exc}")
        return "I miei circuiti hanno avuto un problema. Riprova tra poco."

    # Fallback: if the model is uncertain
    doubt = {"non so", "mi dispiace", "non conosco", "non sono sicuro", "non ho informazioni"}
    if any(d in answer.lower() for d in doubt) and not context:
        log.info("LLM incerto → fallback web search.")
        new_ctx = bmo_web_search(question)
        if new_ctx:
            messages[-1] = {"role": "user", "content": f"CONTESTO: {new_ctx}\n\nDOMANDA: {question}"}
            try:
                response = ollama.chat(model=config.MODEL_OLLAMA, messages=messages)
                answer = response["message"]["content"]
            except Exception as exc:
                log.error(f"Ollama fallback error: {exc}")

    return answer


# ===========================================================================
# AUDIO — PIPER TTS  
# ===========================================================================
def speak_with_piper(text: str, state: BMOState, config: BMOConfig) -> None:
    """Generates WAV with Piper and plays it. Stops immediately if stop flag set."""
    if not text.strip():
        return

    state.clear_stop_speaking()
    previous_state = state.state
    state.state = SPEAKING

    command = [
        config.PIPER_PATH,
        "--model", config.PIPER_MODEL,
        "--output_file", config.OUTPUT_WAV,
        "--length_scale", "0.9",
    ]
    try:
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
            pygame.mixer.quit()

        if os.path.exists(config.OUTPUT_WAV):
            os.remove(config.OUTPUT_WAV)

        result = subprocess.run(
            command,
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            log.error(f"Piper exit {result.returncode}: {result.stderr.decode(errors='replace')}")
            state.state = previous_state
            return

        pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=4096)
        pygame.mixer.music.set_volume(min(1.0, max(0.0, config.AUDIO_VOLUME)))
        pygame.mixer.music.load(config.OUTPUT_WAV)
        pygame.mixer.music.play()

        while pygame.mixer.music.get_busy():
            if state.should_stop_speaking():          # (#14)
                pygame.mixer.music.stop()
                log.info("TTS interrotto.")
                break
            pygame.time.Clock().tick(20)

    except FileNotFoundError:
        log.error(f"Piper non trovato: {config.PIPER_PATH!r}")
    except subprocess.TimeoutExpired:
        log.error("Piper: timeout generazione audio.")
    except Exception as exc:
        log.error(f"Audio error: {exc}")

    state.state = previous_state


# ===========================================================================
# AUDIO — WHISPER STT 
# ===========================================================================
def transcribe_with_whisper(audio_data, config: BMOConfig, whisper_model) -> str:
    """Saves temp WAV and transcribes with Whisper. Returns lowercased text."""
    try:
        with open(config.TEMP_INPUT_WAV, "wb") as f:
            f.write(audio_data.get_wav_data())
        result = whisper_model.transcribe(
            config.TEMP_INPUT_WAV,
            language="it",
            fp16=False,
            temperature=0.0,
            initial_prompt="BMO, robot, bip, Adventure Time",
        )
        text: str = result["text"].strip().lower()
        if text:
            log.debug(f"Whisper → {text!r}")
        return text
    except Exception as exc:
        log.error(f"Trascrizione fallita: {exc}")
        return ""


# ===========================================================================
# CORE PIPELINE
# ===========================================================================
def process_question(
    question: str,
    state: BMOState,
    config: BMOConfig,
    whisper_model,
) -> None:
    """Full pipeline: context → LLM → TTS → history update."""
    log.info(f"Domanda ricevuta: {question!r}")

    speak_with_piper("Ci sto pensando", state, config)
    state.state = THINKING

    context = build_context(question)
    answer  = query_llm(question, context, state, config)

    log.info(f"Risposta BMO: {answer!r}")

    # Update History (#6)
    state.add_to_history("user",      question, config.MAX_HISTORY_TURNS)
    state.add_to_history("assistant", answer,   config.MAX_HISTORY_TURNS)

    speak_with_piper(answer, state, config)
    speak_with_piper("Se hai altre domande chiamami pure", state, config)


# ===========================================================================
# VOICE LISTENER 
# ===========================================================================
def voice_listener_worker(
    recognizer,
    action_queue: queue.Queue,
    state: BMOState,
    config: BMOConfig,
    whisper_model,
) -> None:
    
    log.info("Voice listener avviato.")
    while True:
        if state.state == IDLE and not state.is_busy:
            try:
                
                with sr.Microphone() as source:
                    log.debug("Microfono aperto — in ascolto wake word.")
                    while state.state == IDLE and not state.is_busy:
                        try:
                            audio = recognizer.listen(source, timeout=1.0, phrase_time_limit=4)
                            text  = transcribe_with_whisper(audio, config, whisper_model)
                            if config.WAKE_WORD in text:
                                log.info("Wake word rilevata!")
                                action_queue.put(("WAKE", None))
                                break  
                        except sr.WaitTimeoutError:
                            continue
                        except Exception as exc:
                            log.warning(f"Voice listener (inner): {exc}")
                            time.sleep(0.2)
            except Exception as exc:
                log.error(f"Voice listener (outer): {exc}")
                time.sleep(1.0)
        else:
            time.sleep(0.3)


# ===========================================================================
# GUI HELPERS
# ===========================================================================
def load_folder_images(folder: str) -> list:
    if not os.path.exists(folder):
        log.warning(f"Cartella animazioni mancante: {folder!r}")
        surf = pygame.Surface((WINDOW_WIDTH, FACE_HEIGHT))
        surf.fill((150, 220, 200))
        return [surf]

    files = sorted(
        f for f in os.listdir(folder)
        if f.lower().endswith((".png", ".jpg", ".jpeg"))
    )
    if not files:
        log.warning(f"Nessuna immagine in: {folder!r}")
        surf = pygame.Surface((WINDOW_WIDTH, FACE_HEIGHT))
        surf.fill((150, 220, 200))
        return [surf]

    images = []
    for f in files:
        img = pygame.image.load(os.path.join(folder, f))
        images.append(pygame.transform.scale(img, (WINDOW_WIDTH, FACE_HEIGHT)))
    return images


def create_mic_surfaces() -> dict:
    """Pre-renders anti-aliased mic icon in normal, white, busy variants."""
    def render(color, size=(22, 22), scale=4):
        sw, sh = size[0] * scale, size[1] * scale
        im   = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
        draw = ImageDraw.Draw(im)
        cx = sw // 2
        cy = sh // 2 - int(1.5 * scale)

        cw, ch = int(6.0 * scale), int(11.0 * scale)
        r = cw // 2
        draw.rounded_rectangle(
            [cx - cw // 2, cy - ch // 2, cx + cw // 2, cy + ch // 2],
            radius=r, fill=color,
        )
        cr_w, cr_h = int(11.0 * scale), int(10.0 * scale)
        cr_top = cy - int(1.0 * scale)
        stroke_w = int(1.6 * scale)
        draw.arc(
            [cx - cr_w // 2, cr_top, cx + cr_w // 2, cr_top + cr_h],
            start=0, end=180, fill=color, width=stroke_w,
        )
        stem_top = cr_top + cr_h
        stem_bot = stem_top + int(3.2 * scale)
        draw.line([(cx, stem_top), (cx, stem_bot)], fill=color, width=stroke_w)
        bw = int(9.0 * scale)
        draw.line(
            [(cx - bw // 2, stem_bot), (cx + bw // 2, stem_bot)],
            fill=color, width=stroke_w,
        )
        im_smooth = im.resize(size, Image.Resampling.LANCZOS)
        return pygame.image.fromstring(im_smooth.tobytes(), size, "RGBA")

    return {
        "normal": render(MIC_COLOR_NORMAL),
        "white":  render((255, 255, 255)),
        "busy":   render((210, 230, 225)),
    }


# ===========================================================================
# GUI THREAD
# ===========================================================================
def window_thread(
    action_queue: queue.Queue,
    state: BMOState,
    config: BMOConfig,
) -> None:
    """Manages Pygame window, animations, and interactive controls."""
    pygame.init()
    pygame.font.init()

    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("BMO INTERFACE")

    font_small = pygame.font.SysFont("Segoe UI, Arial, sans-serif", 13)
    font_btn   = pygame.font.SysFont("Segoe UI, Arial, sans-serif", 12, bold=True)
    font_stop  = pygame.font.SysFont("Segoe UI, Arial, sans-serif", 16, bold=True)

    row_y        = 247
    row_h        = 32
    input_rect   = pygame.Rect(10,  row_y, 276, row_h)
    send_btn_rect = pygame.Rect(292, row_y,  56, row_h)
    mic_btn_rect  = pygame.Rect(354, row_y,  36, row_h)

    input_text   = ""
    input_active = False

    mic_icons  = create_mic_surfaces()
    log.info("Caricamento animazioni...")
    animations = {s: load_folder_images(path) for s, path in config.FOLDERS.items()}

    frame_index = 0
    clock = pygame.time.Clock()

    while True:
        mouse_pos     = pygame.mouse.get_pos()
        mouse_pressed = pygame.mouse.get_pressed()[0]

        
        cur_state = state.state
        cur_busy  = state.is_busy

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                os._exit(0)

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                input_active = input_rect.collidepoint(event.pos)

                if send_btn_rect.collidepoint(event.pos):
                    if input_text.strip() and not cur_busy:
                        action_queue.put(("TEXT", input_text.strip()))
                        input_text = ""

                if mic_btn_rect.collidepoint(event.pos):
                    if cur_state == SPEAKING:
                        state.request_stop_speaking()  
                    elif not cur_busy:
                        action_queue.put(("WAKE", None))

            elif event.type == pygame.KEYDOWN and input_active:
                if event.key == pygame.K_RETURN:
                    if input_text.strip() and not cur_busy:
                        action_queue.put(("TEXT", input_text.strip()))
                        input_text = ""
                elif event.key == pygame.K_BACKSPACE:
                    input_text = input_text[:-1]
                elif event.key == pygame.K_ESCAPE:
                    if cur_state == SPEAKING:
                        state.request_stop_speaking()
                elif event.unicode and event.unicode.isprintable():
                    input_text += event.unicode

        # ── Animation frame ────────────────────────────────────────────────
        images      = animations.get(cur_state, animations[IDLE])
        frame_index = (frame_index + 1) % (len(images) * 10)
        cur_frame   = min(frame_index // 10, len(images) - 1)

        # ── Background & face ──────────────────────────────────────────────
        screen.fill(CHASSIS_TEAL)
        screen.blit(images[cur_frame], (0, 0))
        pygame.draw.line(screen, CHASSIS_DARK, (0, FACE_HEIGHT), (WINDOW_WIDTH, FACE_HEIGHT), 2)

        # ── Input box ──────────────────────────────────────────────────────
        ibg     = INPUT_BG_ACTIVE    if input_active else INPUT_BG
        iborder = INPUT_BORDER_ACTIVE if input_active else INPUT_BORDER
        pygame.draw.rect(screen, ibg,     input_rect, border_radius=6)
        pygame.draw.rect(screen, iborder, input_rect, width=2, border_radius=6)

        if not input_text and not input_active:
            ph = font_small.render("Scrivi a BMO e premi Invio...", True, PLACEHOLDER_COLOR)
            screen.blit(ph, (input_rect.x + 8, input_rect.y + 7))
        else:
            vis = input_text
            ts  = font_small.render(vis, True, TEXT_COLOR)
            while ts.get_width() > input_rect.width - 24 and len(vis) > 1:
                vis = vis[1:]
                ts  = font_small.render(vis, True, TEXT_COLOR)
            screen.blit(ts, (input_rect.x + 8, input_rect.y + 7))
            if input_active and (pygame.time.get_ticks() // 500) % 2 == 0:
                cx = input_rect.x + 8 + ts.get_width() + 1
                pygame.draw.line(screen, TEXT_COLOR, (cx, input_rect.y + 7), (cx, input_rect.y + 24), 2)

        # ── Send button ────────────────────────────────────────────────────
        s_hover = send_btn_rect.collidepoint(mouse_pos) and not cur_busy
        s_down  = s_hover and mouse_pressed
        s_bg    = BTN_SEND_HOVER if s_hover else BTN_SEND_BG
        y_off   = 1 if s_down else 0
        pygame.draw.rect(screen, BTN_SEND_SHADOW,
                         pygame.Rect(send_btn_rect.x, send_btn_rect.y + 2, send_btn_rect.w, send_btn_rect.h),
                         border_radius=6)
        pygame.draw.rect(screen, s_bg,
                         pygame.Rect(send_btn_rect.x, send_btn_rect.y + y_off, send_btn_rect.w, send_btn_rect.h - 1),
                         border_radius=6)
        st = font_btn.render("INVIA", True, BTN_SEND_TEXT)
        screen.blit(st, (send_btn_rect.centerx - st.get_width() // 2,
                         send_btn_rect.centery - st.get_height() // 2 - 1 + y_off))

        # ── Mic / Stop button ──────────────────────────────────────────────
        if cur_state == SPEAKING:
            # (#14) Bottone diventa STOP
            m_bg     = BTN_MIC_STOP
            m_shadow = BTN_MIC_STOP_SHADOW
        elif cur_state == LISTENING:
            m_bg     = BTN_MIC_RECORDING
            m_shadow = BTN_MIC_REC_SHADOW
        elif cur_busy:
            m_bg     = BTN_MIC_BUSY
            m_shadow = BTN_MIC_BUSY_SHADOW
        else:
            m_hover  = mic_btn_rect.collidepoint(mouse_pos)
            m_bg     = BTN_MIC_HOVER if m_hover else BTN_MIC_BG
            m_shadow = BTN_MIC_SHADOW

        m_down = mic_btn_rect.collidepoint(mouse_pos) and mouse_pressed
        my_off = 1 if m_down else 0

        pygame.draw.rect(screen, m_shadow,
                         pygame.Rect(mic_btn_rect.x, mic_btn_rect.y + 2, mic_btn_rect.w, mic_btn_rect.h),
                         border_radius=6)
        pygame.draw.rect(screen, m_bg,
                         pygame.Rect(mic_btn_rect.x, mic_btn_rect.y + my_off, mic_btn_rect.w, mic_btn_rect.h - 1),
                         border_radius=6)

        if cur_state == SPEAKING:
            sq = font_stop.render("■", True, (255, 255, 255))
            screen.blit(sq, (mic_btn_rect.centerx - sq.get_width() // 2,
                             mic_btn_rect.centery - sq.get_height() // 2 + my_off))
        else:
            icon_key = "white" if cur_state == LISTENING else ("busy" if cur_busy else "normal")
            screen.blit(mic_icons[icon_key],
                        (mic_btn_rect.centerx - 11, mic_btn_rect.centery - 12 + my_off))

        pygame.display.flip()
        clock.tick(30)


# ===========================================================================
# MAIN DISPATCHER
# ===========================================================================
def main() -> None:
    # --- Config (#11) ---
    try:
        config = BMOConfig()
    except Exception as exc:
        print(f"[FATAL] Errore configurazione: {exc}")
        raise

    os.makedirs("recs", exist_ok=True)

    # --- Whisper (#4) ---
    log.info(f"Caricamento Whisper ({config.WHISPER_MODEL_TYPE})...")
    try:
        whisper_model = whisper.load_model(config.WHISPER_MODEL_TYPE)
    except Exception as exc:
        log.critical(f"Impossibile caricare Whisper: {exc}")
        raise

    # --- Piper sanity check ---
    if not os.path.exists(config.PIPER_PATH):
        log.warning(f"Piper non trovato: {config.PIPER_PATH!r} — il TTS non funzionerà.")

    # --- Ollama connectivity check (#5) ---
    try:
        ollama.list()
        log.info("Ollama raggiungibile ✓")
    except Exception as exc:
        log.warning(f"Ollama non raggiungibile: {exc} — assicurati che 'ollama serve' sia attivo.")

    log.info("✅ Setup completato!")

    state        = BMOState()
    action_queue = queue.Queue()

    recognizer = sr.Recognizer()
    recognizer.energy_threshold       = 50
    recognizer.dynamic_energy_threshold = False
    recognizer.pause_threshold        = 0.8

    # --- GUI thread ---
    ui_thread = threading.Thread(
        target=window_thread, args=(action_queue, state, config), daemon=True
    )
    ui_thread.start()

    # --- Voice listener thread ---
    v_thread = threading.Thread(
        target=voice_listener_worker,
        args=(recognizer, action_queue, state, config, whisper_model),
        daemon=True,
    )
    v_thread.start()

    log.info(f"BMO ONLINE — Dì '{config.WAKE_WORD.upper()}', clicca il microfono o scrivi.")
    speak_with_piper(
        "BMO è ora online, quando sei pronto chiamami, clicca il microfono oppure scrivimi",
        state, config,
    )

    # --- Main event loop ---
    while True:
        state.state = IDLE

        action_type, data = action_queue.get()
        state.is_busy = True

        try:
            if action_type == "WAKE":
                log.info("Wake event ricevuto.")
                speak_with_piper("Dimmi pure", state, config)

                state.state = LISTENING
                log.info("Ascolto domanda...")
                question = ""
                try:
                    with sr.Microphone() as source:
                        q_audio = recognizer.listen(source, timeout=7, phrase_time_limit=10)
                    question = transcribe_with_whisper(q_audio, config, whisper_model)
                except sr.WaitTimeoutError:
                    log.info("Timeout — nessuna domanda ricevuta.")
                    speak_with_piper("Non ho sentito niente. Richiamami quando sei pronto.", state, config)
                except Exception as exc:
                    log.error(f"Errore ascolto domanda: {exc}")

                if len(question) > 1:
                    process_question(question, state, config, whisper_model)
                else:
                    state.state = IDLE

            elif action_type == "TEXT":
                question = str(data)
                log.info(f"Input testuale: {question!r}")
                process_question(question, state, config, whisper_model)

        except Exception as exc:
            log.error(f"Errore elaborazione: {exc}", exc_info=True)
        finally:
            state.state   = IDLE
            state.is_busy = False


# ===========================================================================
# ENTRY POINT
# ===========================================================================
if __name__ == "__main__":
    main()
