from faster_whisper import WhisperModel
import ollama
import speech_recognition as sr
import subprocess
import pygame
import os
import threading
import queue
import time
import logging
import tkinter as tk
from datetime import datetime
from ddgs import DDGS
import json
from PIL import Image, ImageDraw


# ===========================================================================
# LOGGING
# ===========================================================================
os.makedirs("logs", exist_ok=True)
os.system("")  # Enable ANSI escape sequences in Windows terminal


class ColoredConsoleFormatter(logging.Formatter):
    RESET      = "\033[0m"
    BMO_COLOR  = "\033[1;96m"  # Bright cyan for BMO phrases
    USER_COLOR = "\033[1;93m"  # Bright yellow for transcriptions / user input

    _BMO_PREFIXES  = ("Risposta BMO:", "BMO pronuncia:")
    _USER_PREFIXES = ("Whisper →", "Domanda ricevuta:", "Input testuale:")

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        msg = record.getMessage()
        if msg.startswith(self._BMO_PREFIXES):
            return f"{self.BMO_COLOR}{formatted}{self.RESET}"
        if msg.startswith(self._USER_PREFIXES):
            return f"{self.USER_COLOR}{formatted}{self.RESET}"
        return formatted


_log_fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_file_handler = logging.FileHandler(os.path.join("logs", "bmo.log"), encoding="utf-8")
_file_handler.setFormatter(logging.Formatter(_log_fmt))

_stream_handler = logging.StreamHandler()
_stream_handler.setFormatter(ColoredConsoleFormatter(_log_fmt))

logging.basicConfig(
    level=logging.WARNING,
    handlers=[_file_handler, _stream_handler],
)
for _noisy_logger in ("httpx", "httpcore", "urllib3", "primp", "ddgs", "huggingface_hub", "filelock"):
    logging.getLogger(_noisy_logger).setLevel(logging.WARNING)

log = logging.getLogger("BMO")
log.setLevel(logging.DEBUG)


# ===========================================================================
# STATES
# ===========================================================================
IDLE      = "IDLE"
LISTENING = "LISTENING"
THINKING  = "THINKING"
SPEAKING  = "SPEAKING"
HAPPY     = "HAPPY"
SEARCHING = "SEARCHING"
ERROR     = "ERROR"


# ===========================================================================
# CONFIGURATION CLASS
# ===========================================================================
class BMOConfig:
    """Loads and exposes all settings from config.json. Read-only after init."""

    _DEFAULTS: dict = {
        "MODEL_OLLAMA": "gemma3:4b",
        "WAKE_WORD": "bmo",
        "PIPER_PATH": "./piper/piper.exe",
        "PIPER_MODEL": "./piper/it_IT-paola-medium.onnx",
        "WHISPER_MODEL_TYPE": "small",
        "BASE_FACES_PATH": "./assets/faces",
        "OUTPUT_WAV": "assets/recs/bmo_voice.wav",
        "TEMP_INPUT_WAV": "assets/recs/temp_audio.wav",
        "MAX_HISTORY_TURNS": 6,
        "MAX_RESPONSE_WORDS": 15,
        "AUDIO_VOLUME": 1.0,
        "FOLDER_NAMES": {
            "IDLE": "idle",
            "LISTENING": "listening",
            "THINKING": "thinking",
            "SPEAKING": "speaking",
            "HAPPY": "happy",
            "SEARCHING": "searching",
            "ERROR": "error",
        },
    }

    _FILE = "config.json"

    def __init__(self) -> None:
        data = self._load()
        self.MODEL_OLLAMA: str = data["MODEL_OLLAMA"]
        self.WAKE_WORD: str = data["WAKE_WORD"].lower()
        self.PIPER_PATH: str = data["PIPER_PATH"]
        self.PIPER_MODEL: str = data["PIPER_MODEL"]
        self.WHISPER_MODEL_TYPE: str = data["WHISPER_MODEL_TYPE"]
        self.BASE_FACES_PATH: str = data["BASE_FACES_PATH"]
        self.OUTPUT_WAV: str = data["OUTPUT_WAV"]
        self.TEMP_INPUT_WAV: str = data["TEMP_INPUT_WAV"]
        self.MAX_HISTORY_TURNS: int = int(data.get("MAX_HISTORY_TURNS", 6))
        self.MAX_RESPONSE_WORDS: int = int(data.get("MAX_RESPONSE_WORDS", 15))
        self.AUDIO_VOLUME: float = float(data.get("AUDIO_VOLUME", 1.0))

        default_fn = dict(self._DEFAULTS["FOLDER_NAMES"])
        default_fn.update(data.get("FOLDER_NAMES", {}))
        self.FOLDERS: dict[str, str] = {
            IDLE:      os.path.join(self.BASE_FACES_PATH, default_fn["IDLE"]),
            LISTENING: os.path.join(self.BASE_FACES_PATH, default_fn["LISTENING"]),
            THINKING:  os.path.join(self.BASE_FACES_PATH, default_fn["THINKING"]),
            SPEAKING:  os.path.join(self.BASE_FACES_PATH, default_fn["SPEAKING"]),
            HAPPY:     os.path.join(self.BASE_FACES_PATH, default_fn["HAPPY"]),
            SEARCHING: os.path.join(self.BASE_FACES_PATH, default_fn["SEARCHING"]),
            ERROR:     os.path.join(self.BASE_FACES_PATH, default_fn["ERROR"]),
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
        # Event set by the GUI thread to interrupt TTS (#14)
        self._stop_speaking = threading.Event()
        # Rolling conversation history (#6)
        self._history: list[dict] = []
        # Retro subtitle overlay state
        self._subtitle_text: str = ""
        self._subtitle_role: str = "bmo"
        self._subtitle_time: float = 0.0
        self._subtitle_duration: float = 0.0
        # Real-time audio RMS mouth level (0..5 across 6 progressive mouth frames)
        self._mouth_level: int = 0
        self._is_speaking: bool = False
        self._gui_ready = threading.Event()

    def mark_gui_ready(self) -> None:
        self._gui_ready.set()

    def wait_gui_ready(self, timeout: float = 10.0) -> None:
        self._gui_ready.wait(timeout=timeout)

    # --- active TTS speaking flag ---
    @property
    def is_speaking(self) -> bool:
        with self._lock:
            return self._is_speaking

    @is_speaking.setter
    def is_speaking(self, value: bool) -> None:
        with self._lock:
            self._is_speaking = value

    # --- mouth level for real-time lip-sync ---
    @property
    def mouth_level(self) -> int:
        with self._lock:
            return self._mouth_level

    @mouth_level.setter
    def mouth_level(self, value: int) -> None:
        with self._lock:
            self._mouth_level = value

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
        with self._lock:
            self._history.append({"role": role, "content": content})
            # Keep only the last max_turns turns (each turn = 1 user + 1 assistant)
            cap = max_turns * 2
            if len(self._history) > cap:
                self._history = self._history[-cap:]

    def get_history(self) -> list[dict]:
        with self._lock:
            return list(self._history)

    def clear_history(self) -> None:
        with self._lock:
            self._history.clear()
        log.info("Cronologia conversazione azzerata.")

    # --- retro subtitle overlay ---
    def set_subtitle(self, text: str, role: str = "bmo", duration: float = 0.0) -> None:
        with self._lock:
            self._subtitle_text = text.strip()
            self._subtitle_role = role
            self._subtitle_time = time.time()
            self._subtitle_duration = duration

    def get_subtitle(self) -> tuple[str, str, float, float]:
        with self._lock:
            return (
                self._subtitle_text,
                self._subtitle_role,
                self._subtitle_time,
                self._subtitle_duration,
            )


# ===========================================================================
# UI CONSTANTS & COLORS
# ===========================================================================
WINDOW_WIDTH   = 400
WINDOW_HEIGHT  = 286
FACE_HEIGHT    = 240
CONTROL_HEIGHT = 46

CHASSIS_TEAL = (64, 153, 138)
CHASSIS_DARK = (32, 85, 76)

INPUT_BG            = (224, 250, 235)
INPUT_BG_ACTIVE     = (236, 255, 245)
INPUT_BORDER        = (38, 98, 86)
INPUT_BORDER_ACTIVE = (18, 62, 54)
TEXT_COLOR          = (14, 38, 32)
PLACEHOLDER_COLOR   = (78, 132, 120)

BTN_SEND_BG     = (38, 56, 64)
BTN_SEND_HOVER  = (50, 72, 82)
BTN_SEND_SHADOW = (22, 34, 40)
BTN_SEND_TEXT   = (245, 255, 250)

BTN_CLEAR_BG     = (48, 112, 102)
BTN_CLEAR_HOVER  = (62, 132, 120)
BTN_CLEAR_SHADOW = (26, 68, 60)

BTN_MIC_BG       = (250, 198, 38)
BTN_MIC_HOVER    = (255, 212, 60)
BTN_MIC_SHADOW   = (205, 155, 20)
MIC_COLOR_NORMAL = (35, 45, 40)

BTN_MIC_RECORDING  = (235, 68, 68)
BTN_MIC_REC_SHADOW = (180, 40, 40)

BTN_MIC_BUSY        = (130, 155, 150)
BTN_MIC_BUSY_SHADOW = (100, 125, 120)

BTN_MIC_STOP        = (200, 40, 40)   # dark red → STOP during SPEAKING
BTN_MIC_STOP_SHADOW = (140, 20, 20)

SUBTITLE_BG_BMO     = (238, 255, 244, 235)
SUBTITLE_BG_USER    = (255, 250, 218, 235)
SUBTITLE_BORDER     = (32, 85, 76)
SUBTITLE_TAG_BMO    = (24, 118, 98)
SUBTITLE_TAG_USER   = (168, 112, 12)


# ===========================================================================
# WEB SEARCH
# ===========================================================================
def bmo_web_search(query: str, state: BMOState | None = None) -> str:
    """Queries DuckDuckGo. Switches state to SEARCHING while querying."""
    log.info(f"Web search: {query!r}")
    if state is not None:
        state.state = SEARCHING
        state.set_subtitle(f"Ricerca sul web: {query}", role="bmo")
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
        if results:
            return "\n".join(f"Fonte: {r['body']}" for r in results)
        return "Nessun risultato trovato online."
    except Exception as exc:
        log.error(f"Web search error: {exc}")
        if state is not None:
            state.state = ERROR
            time.sleep(0.8)
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
# Personal questions -> never web search, always local
_LOCAL_KW = frozenset([
    "come stai", "come ti chiami", "chi sei", "cosa sei",
    "ciao", "salve", "buongiorno", "buonasera", "sei bmo",
    "grazie", "bravo", "ti voglio bene", "amico",
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
def build_context(question: str, state: BMOState) -> tuple[str, str]:
    """Returns (enriched context string, detected intent)."""
    intent = detect_intent(question)
    log.debug(f"Intent: {intent!r}")

    if intent == "datetime":
        now = datetime.now()
        days = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
        return (
            f"L'orario attuale è {now.strftime('%H:%M')}. "
            f"Oggi è {days[now.weekday()]} {now.strftime('%d/%m/%Y')}.",
            intent,
        )
    if intent == "web":
        return bmo_web_search(question, state), intent
    return "", intent


# ===========================================================================
# LLM QUERY
# ===========================================================================
def query_llm(
    question: str,
    context: str,
    state: BMOState,
    config: BMOConfig,
) -> tuple[str, bool]:
    """Builds messages (system + history + question) and queries Ollama.
    Returns (answer, had_error).
    """
    final_prompt = (
        f"CONTESTO: {context}\n\nDOMANDA: {question}" if context else question
    )

    messages = [{"role": "system", "content": config.SYSTEM_PROMPT}]
    messages += state.get_history()
    messages.append({"role": "user", "content": final_prompt})

    state.state = THINKING
    try:
        response = ollama.chat(model=config.MODEL_OLLAMA, messages=messages)
        answer: str = response["message"]["content"]
    except Exception as exc:
        log.error(f"Ollama error: {exc}")
        state.state = ERROR
        return "I miei circuiti hanno avuto un problema. Riprova tra poco.", True

    # Fallback: if the model is uncertain
    doubt = {"non so", "mi dispiace", "non conosco", "non sono sicuro", "non ho informazioni"}
    if any(d in answer.lower() for d in doubt) and not context:
        log.info("LLM incerto → fallback web search.")
        new_ctx = bmo_web_search(question, state)
        if new_ctx:
            state.state = THINKING
            messages[-1] = {"role": "user", "content": f"CONTESTO: {new_ctx}\n\nDOMANDA: {question}"}
            try:
                response = ollama.chat(model=config.MODEL_OLLAMA, messages=messages)
                answer = response["message"]["content"]
            except Exception as exc:
                log.error(f"Ollama fallback error: {exc}")
                state.state = ERROR
                return answer, True

    return answer, False


# ===========================================================================
# AUDIO — PIPER TTS
# ===========================================================================
def speak_with_piper(
    text: str,
    state: BMOState,
    config: BMOConfig,
    face_state: str = SPEAKING,
) -> None:
    """Generates WAV with Piper and plays it. Stops immediately if stop flag set."""
    if not text.strip():
        return

    log.debug(f"BMO pronuncia: {text!r}")
    state.clear_stop_speaking()
    previous_state = state.state

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
            state.state = ERROR
            time.sleep(0.8)
            state.state = previous_state
            return

        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
        pygame.mixer.music.set_volume(min(1.0, max(0.0, config.AUDIO_VOLUME)))
        pygame.mixer.music.load(config.OUTPUT_WAV)
        pygame.mixer.music.play()

        state.is_speaking = True
        state.state = face_state
        state.set_subtitle(text, role="bmo")

        while pygame.mixer.music.get_busy():
            if state.should_stop_speaking():          # (#14)
                pygame.mixer.music.stop()
                log.info("TTS interrotto.")
                break
            pygame.time.Clock().tick(60)

    except FileNotFoundError:
        log.error(f"Piper non trovato: {config.PIPER_PATH!r}")
        state.state = ERROR
        time.sleep(0.8)
    except subprocess.TimeoutExpired:
        log.error("Piper: timeout generazione audio.")
        state.state = ERROR
        time.sleep(0.8)
    except Exception as exc:
        log.error(f"Audio error: {exc}")
        state.state = ERROR
        time.sleep(0.8)
    finally:
        state.is_speaking = False
        state.state = previous_state


# ===========================================================================
# AUDIO — FASTER-WHISPER STT
# ===========================================================================
def transcribe_with_whisper(audio_data, config: BMOConfig, whisper_model: WhisperModel) -> str:
    """Saves temp WAV and transcribes with faster-whisper. Returns lowercased text."""
    try:
        with open(config.TEMP_INPUT_WAV, "wb") as f:
            f.write(audio_data.get_wav_data())
        segments, _ = whisper_model.transcribe(
            config.TEMP_INPUT_WAV,
            language="it",
            beam_size=5,
            temperature=0.0,
            vad_filter=True,
            initial_prompt="BMO, robot, bip, Adventure Time",
        )
        text: str = " ".join(seg.text for seg in segments).strip().lower()
        if text:
            log.debug(f"Whisper → {text!r}")
        return text
    except Exception as exc:
        log.error(f"Trascrizione fallita: {exc}")
        return ""


def find_wake_word_span(text: str, wake_word: str) -> tuple[int, int] | None:
    """Finds (start, end) of wake_word or its common Italian phonetic variants in text."""
    variants = [wake_word]
    if wake_word == "bmo":
        variants.extend(["bimo", "bimeo", "bi mo", "b.m.o", "b-mo"])
    for v in variants:
        idx = text.find(v)
        if idx != -1:
            return idx, idx + len(v)
    return None


def extract_inline_question(text: str, wake_word: str) -> str:
    """Extracts any question spoken immediately after the wake word in the same phrase."""
    span = find_wake_word_span(text, wake_word)
    if span is None:
        return ""
    after = text[span[1]:].strip(" ,.!?:;-'\"")
    return after if len(after) >= 3 else ""


# ===========================================================================
# CORE PIPELINE
# ===========================================================================
def process_question(
    question: str,
    state: BMOState,
    config: BMOConfig,
    whisper_model: WhisperModel,
) -> None:
    """Full pipeline: context → LLM → TTS → history update."""
    log.info(f"Domanda ricevuta: {question!r}")
    state.set_subtitle(question, role="user")

    speak_with_piper("Ci sto pensando", state, config)
    state.state = THINKING

    context, intent = build_context(question, state)
    answer, had_error = query_llm(question, context, state, config)

    log.info(f"Risposta BMO: {answer!r}")

    if had_error:
        speak_with_piper(answer, state, config, face_state=ERROR)
        return

    # Update History (#6)
    state.add_to_history("user",      question, config.MAX_HISTORY_TURNS)
    state.add_to_history("assistant", answer,   config.MAX_HISTORY_TURNS)

    # Express HAPPY when responding to personal/friendly greetings, otherwise SPEAKING
    response_face = HAPPY if intent == "local" else SPEAKING
    speak_with_piper(answer, state, config, face_state=response_face)
    speak_with_piper("Se hai altre domande chiamami pure", state, config, face_state=HAPPY)


# ===========================================================================
# VOICE LISTENER
# ===========================================================================
def voice_listener_worker(
    recognizer,
    action_queue: queue.Queue,
    state: BMOState,
    config: BMOConfig,
    whisper_model: WhisperModel,
) -> None:
    log.info("Voice listener avviato.")
    while True:
        if state.state == IDLE and not state.is_busy:
            try:
                with sr.Microphone() as source:
                    log.debug("Microfono aperto — in ascolto wake word.")
                    while state.state == IDLE and not state.is_busy:
                        try:
                            audio = recognizer.listen(source, timeout=1.0, phrase_time_limit=6)
                            text  = transcribe_with_whisper(audio, config, whisper_model)
                            if find_wake_word_span(text, config.WAKE_WORD) is not None:
                                inline_q = extract_inline_question(text, config.WAKE_WORD)
                                if inline_q:
                                    log.info(f"Wake word + domanda diretta rilevata: {inline_q!r}")
                                    action_queue.put(("VOICE_DIRECT", inline_q))
                                else:
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


def get_clipboard_text() -> str:
    """Reads plain text from the system clipboard via Tkinter."""
    try:
        root = tk.Tk()
        root.withdraw()
        text = root.clipboard_get()
        root.destroy()
        return " ".join(str(text).splitlines())
    except Exception:
        return ""


def wrap_text_lines(text: str, font: pygame.font.Font, max_width: int, max_lines: int = 2) -> list[str]:
    """Word-wraps text into at most max_lines lines fitting max_width."""
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    cur = words[0]
    for w in words[1:]:
        test = f"{cur} {w}"
        if font.size(test)[0] <= max_width:
            cur = test
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    return lines


def draw_subtitle_overlay(
    screen: pygame.Surface,
    state: BMOState,
    font_sub: pygame.font.Font,
    font_tag: pygame.font.Font,
) -> None:
    """Draws a retro speech bubble overlay on the bottom of BMO's screen with audio-synced typewriter effect."""
    sub_text, sub_role, sub_time, sub_duration = state.get_subtitle()
    if not sub_text:
        return

    elapsed = time.time() - sub_time
    # Hide subtitle after 7 seconds if BMO is idle
    if elapsed > 7.0 and state.state == IDLE and not state.is_busy:
        return

    # Sync typewriter speed to actual WAV duration when available
    if sub_duration > 0.2:
        progress = min(1.0, elapsed / (sub_duration * 0.92))
        visible_chars = max(1, int(len(sub_text) * progress))
    else:
        visible_chars = max(1, int(elapsed * 32))
    typed_text = sub_text[:visible_chars]

    box_rect = pygame.Rect(24, 182, WINDOW_WIDTH - 48, 44)
    tag_label = "BMO:" if sub_role == "bmo" else "TU:"
    tag_color = SUBTITLE_TAG_BMO if sub_role == "bmo" else SUBTITLE_TAG_USER
    bg_color  = SUBTITLE_BG_BMO if sub_role == "bmo" else SUBTITLE_BG_USER

    # Semi-transparent pill surface
    pill = pygame.Surface((box_rect.w, box_rect.h), pygame.SRCALPHA)
    pygame.draw.rect(pill, bg_color, pill.get_rect(), border_radius=8)
    pygame.draw.rect(pill, SUBTITLE_BORDER, pill.get_rect(), width=2, border_radius=8)
    screen.blit(pill, box_rect.topleft)

    tag_surf = font_tag.render(tag_label, True, tag_color)
    screen.blit(tag_surf, (box_rect.x + 8, box_rect.y + 6))

    text_x = box_rect.x + 12 + tag_surf.get_width()
    max_text_w = box_rect.w - (text_x - box_rect.x) - 10
    lines = wrap_text_lines(typed_text, font_sub, max_text_w, max_lines=2)

    for idx, line in enumerate(lines):
        line_surf = font_sub.render(line, True, TEXT_COLOR)
        screen.blit(line_surf, (text_x, box_rect.y + 5 + idx * 17))


# ===========================================================================
# GUI THREAD
# ===========================================================================
def window_thread(
    action_queue: queue.Queue,
    state: BMOState,
    config: BMOConfig,
) -> None:
    """Manages Pygame window, animations, subtitles, and interactive controls."""
    pygame.init()
    pygame.font.init()

    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("BMO INTERFACE")

    font_small = pygame.font.SysFont("Segoe UI, Arial, sans-serif", 13)
    font_sub   = pygame.font.SysFont("Consolas, Segoe UI, sans-serif", 12, bold=True)
    font_tag   = pygame.font.SysFont("Consolas, Segoe UI, sans-serif", 12, bold=True)
    font_btn   = pygame.font.SysFont("Segoe UI, Arial, sans-serif", 11, bold=True)
    font_stop  = pygame.font.SysFont("Segoe UI, Arial, sans-serif", 16, bold=True)

    row_y          = 247
    row_h          = 32
    input_rect     = pygame.Rect(8,   row_y, 242, row_h)
    send_btn_rect  = pygame.Rect(255, row_y,  52, row_h)
    clear_btn_rect = pygame.Rect(312, row_y,  36, row_h)
    mic_btn_rect   = pygame.Rect(353, row_y,  38, row_h)

    input_text   = ""
    cursor_pos   = 0
    input_active = False

    mic_icons  = create_mic_surfaces()
    log.info("Caricamento animazioni...")
    animations = {s: load_folder_images(path) for s, path in config.FOLDERS.items()}
    if not pygame.mixer.get_init():
        try:
            pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
        except Exception as exc:
            log.warning(f"Mixer pre-init warning: {exc}")

    frame_index = 0
    prev_state  = IDLE
    clock = pygame.time.Clock()
    state.mark_gui_ready()

    while True:
        mouse_pos     = pygame.mouse.get_pos()
        mouse_pressed = pygame.mouse.get_pressed()[0]

        cur_state    = state.state
        cur_busy     = state.is_busy
        cur_speaking = state.is_speaking

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
                        cursor_pos = 0

                if clear_btn_rect.collidepoint(event.pos):
                    state.clear_history()
                    state.set_subtitle("Memoria conversazione azzerata!", role="bmo")

                if mic_btn_rect.collidepoint(event.pos):
                    if cur_speaking:
                        state.request_stop_speaking()
                    elif not cur_busy:
                        action_queue.put(("WAKE", None))

            elif event.type == pygame.KEYDOWN:
                mods = pygame.key.get_mods()
                ctrl_pressed = bool(mods & pygame.KMOD_CTRL)

                if event.key == pygame.K_ESCAPE:
                    if cur_speaking:
                        state.request_stop_speaking()
                elif ctrl_pressed and event.key == pygame.K_l:
                    state.clear_history()
                    state.set_subtitle("Memoria conversazione azzerata!", role="bmo")
                elif input_active:
                    if event.key == pygame.K_RETURN:
                        if input_text.strip() and not cur_busy:
                            action_queue.put(("TEXT", input_text.strip()))
                            input_text = ""
                            cursor_pos = 0
                    elif ctrl_pressed and event.key == pygame.K_v:
                        pasted = get_clipboard_text()
                        if pasted:
                            input_text = input_text[:cursor_pos] + pasted + input_text[cursor_pos:]
                            cursor_pos += len(pasted)
                    elif event.key == pygame.K_LEFT:
                        cursor_pos = max(0, cursor_pos - 1)
                    elif event.key == pygame.K_RIGHT:
                        cursor_pos = min(len(input_text), cursor_pos + 1)
                    elif event.key == pygame.K_HOME:
                        cursor_pos = 0
                    elif event.key == pygame.K_END:
                        cursor_pos = len(input_text)
                    elif event.key == pygame.K_BACKSPACE:
                        if cursor_pos > 0:
                            input_text = input_text[:cursor_pos - 1] + input_text[cursor_pos:]
                            cursor_pos -= 1
                    elif event.key == pygame.K_DELETE:
                        if cursor_pos < len(input_text):
                            input_text = input_text[:cursor_pos] + input_text[cursor_pos + 1:]
                    elif event.unicode and event.unicode.isprintable() and not ctrl_pressed:
                        input_text = input_text[:cursor_pos] + event.unicode + input_text[cursor_pos:]
                        cursor_pos += len(event.unicode)

        # ── Animation frame ────────────────────────────────────────────────
        if cur_state != prev_state:
            frame_index = 0
            prev_state  = cur_state
        images      = animations.get(cur_state, animations[IDLE])
        frame_index = (frame_index + 1) % (len(images) * 10)
        cur_frame   = min(frame_index // 10, len(images) - 1)

        # ── Background & face ──────────────────────────────────────────────
        screen.fill(CHASSIS_TEAL)
        screen.blit(images[cur_frame], (0, 0))
        draw_subtitle_overlay(screen, state, font_sub, font_tag)
        pygame.draw.line(screen, CHASSIS_DARK, (0, FACE_HEIGHT), (WINDOW_WIDTH, FACE_HEIGHT), 2)

        # ── Input box with cursor navigation ───────────────────────────────
        ibg     = INPUT_BG_ACTIVE     if input_active else INPUT_BG
        iborder = INPUT_BORDER_ACTIVE if input_active else INPUT_BORDER
        pygame.draw.rect(screen, ibg,     input_rect, border_radius=6)
        pygame.draw.rect(screen, iborder, input_rect, width=2, border_radius=6)

        if not input_text and not input_active:
            ph = font_small.render("Scrivi a BMO (Ctrl+V incolla)...", True, PLACEHOLDER_COLOR)
            screen.blit(ph, (input_rect.x + 8, input_rect.y + 7))
        else:
            # Scroll window around cursor_pos so the active cursor is always visible
            max_w = input_rect.width - 18
            start_idx = 0
            while start_idx < cursor_pos and font_small.size(input_text[start_idx:cursor_pos])[0] > max_w - 8:
                start_idx += 1
            end_idx = len(input_text)
            while end_idx > cursor_pos and font_small.size(input_text[start_idx:end_idx])[0] > max_w:
                end_idx -= 1

            vis = input_text[start_idx:end_idx]
            ts  = font_small.render(vis, True, TEXT_COLOR)
            screen.blit(ts, (input_rect.x + 8, input_rect.y + 7))

            if input_active and (pygame.time.get_ticks() // 500) % 2 == 0:
                prefix_w = font_small.size(input_text[start_idx:cursor_pos])[0]
                cx = input_rect.x + 8 + prefix_w
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

        # ── Clear history button (RESET) ───────────────────────────────────
        c_hover = clear_btn_rect.collidepoint(mouse_pos)
        c_down  = c_hover and mouse_pressed
        c_bg    = BTN_CLEAR_HOVER if c_hover else BTN_CLEAR_BG
        cy_off  = 1 if c_down else 0
        pygame.draw.rect(screen, BTN_CLEAR_SHADOW,
                         pygame.Rect(clear_btn_rect.x, clear_btn_rect.y + 2, clear_btn_rect.w, clear_btn_rect.h),
                         border_radius=6)
        pygame.draw.rect(screen, c_bg,
                         pygame.Rect(clear_btn_rect.x, clear_btn_rect.y + cy_off, clear_btn_rect.w, clear_btn_rect.h - 1),
                         border_radius=6)
        ct = font_btn.render("RST", True, BTN_SEND_TEXT)
        screen.blit(ct, (clear_btn_rect.centerx - ct.get_width() // 2,
                         clear_btn_rect.centery - ct.get_height() // 2 - 1 + cy_off))

        # ── Mic / Stop button ──────────────────────────────────────────────
        is_speaking_now = cur_speaking
        if is_speaking_now:
            # (#14) Button becomes STOP
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

        if is_speaking_now:
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

    os.makedirs(os.path.dirname(config.OUTPUT_WAV) or "assets/recs", exist_ok=True)

    # --- Faster-Whisper (#4) ---
    log.info(f"Caricamento Faster-Whisper ({config.WHISPER_MODEL_TYPE}, int8)...")
    try:
        whisper_model = WhisperModel(
            config.WHISPER_MODEL_TYPE,
            device="cpu",
            compute_type="int8",
        )
    except Exception as exc:
        log.critical(f"Impossibile caricare Faster-Whisper: {exc}")
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
    recognizer.energy_threshold         = 50
    recognizer.dynamic_energy_threshold = False
    recognizer.pause_threshold          = 0.8

    # --- GUI thread ---
    ui_thread = threading.Thread(
        target=window_thread, args=(action_queue, state, config), daemon=True
    )
    ui_thread.start()
    state.wait_gui_ready()

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
        state, config, face_state=HAPPY,
    )

    # --- Main event loop ---
    while True:
        state.state = IDLE

        action_type, data = action_queue.get()
        state.is_busy = True

        try:
            if action_type == "VOICE_DIRECT":
                question = str(data)
                process_question(question, state, config, whisper_model)

            elif action_type == "WAKE":
                log.info("Wake event ricevuto.")
                speak_with_piper("Dimmi pure", state, config)

                state.state = LISTENING
                state.set_subtitle("In ascolto...", role="bmo")
                log.info("Ascolto domanda...")
                question = ""
                try:
                    with sr.Microphone() as source:
                        q_audio = recognizer.listen(source, timeout=7, phrase_time_limit=10)
                    question = transcribe_with_whisper(q_audio, config, whisper_model)
                except sr.WaitTimeoutError:
                    log.info("Timeout — nessuna domanda ricevuta.")
                    speak_with_piper(
                        "Non ho sentito niente. Richiamami quando sei pronto.",
                        state, config, face_state=ERROR,
                    )
                except Exception as exc:
                    log.error(f"Errore ascolto domanda: {exc}")
                    state.state = ERROR
                    time.sleep(0.8)

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
            state.state = ERROR
            time.sleep(0.8)
        finally:
            state.state   = IDLE
            state.is_busy = False


# ===========================================================================
# ENTRY POINT
# ===========================================================================
if __name__ == "__main__":
    main()
