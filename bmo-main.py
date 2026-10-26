import whisper
import ollama
import speech_recognition as sr
import subprocess
import pygame
import os
import threading
import queue
import time
from datetime import datetime 
from ddgs import DDGS
import json
from PIL import Image, ImageDraw

# --- GLOBAL QUEUES & SYSTEM PROMPT ---
action_queue = queue.Queue()
is_busy = False

SYSTEM_PROMPT = (
    "Sei BMO di Adventure Time. Rispondi sempre in italiano. "
    "Usa frasi corte e semplici. Il tuo tono è ingenuo, robotico e gentile. "
    "Massimo 15 parole per risposta, non usare mai emoji. Se ricevi informazioni esterne marcate come CONTESTO, "
    "usale per dare la risposta corretta alla domanda."
)

# --- UI CONSTANTS & COLORS ---
WINDOW_WIDTH = 400
WINDOW_HEIGHT = 286
FACE_HEIGHT = 240
CONTROL_HEIGHT = 46

CHASSIS_TEAL = (64, 153, 138)
CHASSIS_DARK = (32, 85, 76)

# Retro BMO Mint Screen Inset for Input Box
INPUT_BG = (224, 250, 235)
INPUT_BG_ACTIVE = (236, 255, 245)
INPUT_BORDER = (38, 98, 86)
INPUT_BORDER_ACTIVE = (18, 62, 54)
TEXT_COLOR = (14, 38, 32)
PLACEHOLDER_COLOR = (78, 132, 120)

# "INVIA" Button (BMO D-Pad Console Dark Slate)
BTN_SEND_BG = (38, 56, 64)
BTN_SEND_HOVER = (50, 72, 82)
BTN_SEND_SHADOW = (22, 34, 40)
BTN_SEND_TEXT = (245, 255, 250)

# Mic Button (BMO Arcade Yellow Triangle / Red Recording)
BTN_MIC_BG = (250, 198, 38)
BTN_MIC_HOVER = (255, 212, 60)
BTN_MIC_SHADOW = (205, 155, 20)
MIC_COLOR_NORMAL = (35, 45, 40)

BTN_MIC_RECORDING = (235, 68, 68)
BTN_MIC_REC_SHADOW = (180, 40, 40)

BTN_MIC_BUSY = (130, 155, 150)
BTN_MIC_BUSY_SHADOW = (100, 125, 120)


# --- LOAD CONFIGURATION FROM JSON AND INITIALIZE STATES ---
def load_config():
    """Load configuration, prepare folders and initialize models."""
    global IDLE, LISTENING, THINKING, SPEAKING, current_state
    global MODEL_OLLAMA, WAKE_WORD, PIPER_PATH, PIPER_MODEL, WHISPER_MODEL_TYPE
    global BASE_FACES_PATH, OUTPUT_WAV, TEMP_INPUT_WAV, FOLDERS, whisper_model
    
    # 1. State Definitions
    IDLE, LISTENING, THINKING, SPEAKING = "IDLE", "LISTENING", "THINKING", "SPEAKING"
    current_state = IDLE

    CONFIG_FILE = "config.json"
    default_config = {
        "MODEL_OLLAMA": "gemma3:4b",
        "WAKE_WORD": "bmo",
        "PIPER_PATH": "C:/piper/piper.exe",
        "PIPER_MODEL": "C:/piper/it_IT-paola-medium.onnx",
        "WHISPER_MODEL_TYPE": "small",
        "BASE_FACES_PATH": "./faces",
        "OUTPUT_WAV": "recs/bmo_voice.wav",
        "TEMP_INPUT_WAV": "recs/temp_audio.wav",
        "FOLDER_NAMES": {
            "IDLE": "idle",
            "LISTENING": "listening",
            "THINKING": "thinking",
            "SPEAKING": "speaking"
        }
    }

    # 1. Load JSON
    if not os.path.exists(CONFIG_FILE):
        print(f"Configurazione non trovata. Creazione di {CONFIG_FILE}...")
        with open(CONFIG_FILE, "w") as f:
            json.dump(default_config, f, indent=4)
        config = default_config
    else:
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)

    # 2. Global variables assignment
    MODEL_OLLAMA = config["MODEL_OLLAMA"]
    WAKE_WORD = config["WAKE_WORD"]
    PIPER_PATH = config["PIPER_PATH"]
    PIPER_MODEL = config["PIPER_MODEL"]
    WHISPER_MODEL_TYPE = config["WHISPER_MODEL_TYPE"]
    BASE_FACES_PATH = config["BASE_FACES_PATH"]
    OUTPUT_WAV = config["OUTPUT_WAV"]
    TEMP_INPUT_WAV = config["TEMP_INPUT_WAV"]

    # 3. Face Paths Configuration
    f_names = config["FOLDER_NAMES"]
    FOLDERS = {
        IDLE: os.path.join(BASE_FACES_PATH, f_names["IDLE"]),
        LISTENING: os.path.join(BASE_FACES_PATH, f_names["LISTENING"]),
        THINKING: os.path.join(BASE_FACES_PATH, f_names["THINKING"]),
        SPEAKING: os.path.join(BASE_FACES_PATH, f_names["SPEAKING"])
    }

    # 4. Environment Preparation (Folders)
    if not os.path.exists("recs"):
        os.makedirs("recs")

    # 5. Models Initialization
    print(f"Caricamento Whisper ({WHISPER_MODEL_TYPE}) in corso...")
    whisper_model = whisper.load_model(WHISPER_MODEL_TYPE)
    
    print("✅ Setup completato!")


# --- WEB SEARCH FUNCTION ---
def bmo_web_search(query):
    """
    Executes a search on DuckDuckGo. 
    This function is called for complex questions or real-time data.
    """
    print(f"🔍 BMO sta consultando i suoi circuiti online per: {query}")
    results_text = ""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
            if results:
                for r in results:
                    results_text += f"Fonte: {r['body']}\n"
                return results_text
            else:
                return "Nessun risultato trovato online."
    except Exception as e:
        print(f"Errore durante la ricerca web: {e}")
        return "Errore di connessione ai circuiti di ricerca."


# --- GRAPHICAL LOGIC (ANIMATIONS + INTERACTIVE UI) ---
def load_folder_images(folder):
    """Loads all images from a specific subfolder scaled to the screen area."""
    images_list = []
    
    if not os.path.exists(folder):
        print(f"ERRORE: La cartella '{folder}' non esiste!")
        surf = pygame.Surface((WINDOW_WIDTH, FACE_HEIGHT))
        surf.fill((150, 220, 200))
        return [surf]
    
    files = sorted([f for f in os.listdir(folder) if f.lower().endswith(('.png', '.jpg', '.jpeg'))])
    
    if not files:
        print(f"AVVISO: La cartella '{folder}' è vuota!")
        surf = pygame.Surface((WINDOW_WIDTH, FACE_HEIGHT))
        surf.fill((150, 220, 200))
        return [surf]

    for f in files:
        img_path = os.path.join(folder, f)
        img = pygame.image.load(img_path)
        # Scaled to 400x240 to preserve native 5:3 aspect ratio of faces
        images_list.append(pygame.transform.scale(img, (WINDOW_WIDTH, FACE_HEIGHT)))
    
    return images_list


def create_mic_surfaces():
    """Pre-renders crisp, anti-aliased vector microphone icons in all required states."""
    def render(color, size=(22, 22), scale=4):
        sw, sh = size[0] * scale, size[1] * scale
        im = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
        draw = ImageDraw.Draw(im)
        
        cx = sw // 2
        cy = sh // 2 - int(1.5 * scale)
        
        # 1. Capsule
        cw = int(6.0 * scale)
        ch = int(11.0 * scale)
        r = cw // 2
        cap_box = [cx - cw // 2, cy - ch // 2, cx + cw // 2, cy + ch // 2]
        draw.rounded_rectangle(cap_box, radius=r, fill=color)
        
        # 2. Cradle (smooth U arc)
        cr_w = int(11.0 * scale)
        cr_h = int(10.0 * scale)
        cr_top = cy - int(1.0 * scale)
        cr_box = [cx - cr_w // 2, cr_top, cx + cr_w // 2, cr_top + cr_h]
        stroke_w = int(1.6 * scale)
        draw.arc(cr_box, start=0, end=180, fill=color, width=stroke_w)
        
        # 3. Stem
        stem_top = cr_top + cr_h
        stem_bot = stem_top + int(3.2 * scale)
        draw.line([(cx, stem_top), (cx, stem_bot)], fill=color, width=stroke_w)
        
        # 4. Base stand
        bw = int(9.0 * scale)
        draw.line([(cx - bw // 2, stem_bot), (cx + bw // 2, stem_bot)], fill=color, width=stroke_w)
        
        im_smooth = im.resize(size, Image.Resampling.LANCZOS)
        return pygame.image.fromstring(im_smooth.tobytes(), size, "RGBA")

    return {
        "normal": render(MIC_COLOR_NORMAL),
        "white": render((255, 255, 255)),
        "busy": render((210, 230, 225)),
    }


def window_thread():
    """Manages the window, cyclical animations, and interactive controls."""
    global current_state, is_busy
    pygame.init()
    pygame.font.init()
    
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("BMO INTERFACE")
    
    # Fonts
    font_small = pygame.font.SysFont("Segoe UI, Arial, sans-serif", 13)
    font_btn = pygame.font.SysFont("Segoe UI, Arial, sans-serif", 12, bold=True)
    
    # Single-Row Compact Control Rectangles
    row_y = 247
    row_h = 32
    input_rect = pygame.Rect(10, row_y, 276, row_h)
    send_btn_rect = pygame.Rect(292, row_y, 56, row_h)
    mic_btn_rect = pygame.Rect(354, row_y, 36, row_h)
    
    input_text = ""
    input_active = False
    
    # Pre-render microphone icons
    mic_icons = create_mic_surfaces()
    
    # Pre-loading of animations from 'faces' subfolders
    print("Caricamento immagini dalle cartelle...")
    animations = {s: load_folder_images(path) for s, path in FOLDERS.items()}
    
    frame_index = 0
    clock = pygame.time.Clock()
    
    while True:
        mouse_pos = pygame.mouse.get_pos()
        mouse_pressed = pygame.mouse.get_pressed()[0]
        
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                os._exit(0)
            
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    # Input box clicked
                    if input_rect.collidepoint(event.pos):
                        input_active = True
                    else:
                        input_active = False
                    
                    # Send button clicked
                    if send_btn_rect.collidepoint(event.pos):
                        if input_text.strip() and not is_busy:
                            action_queue.put(("TEXT", input_text.strip()))
                            input_text = ""
                    
                    # Mic wake button clicked
                    if mic_btn_rect.collidepoint(event.pos):
                        if not is_busy:
                            action_queue.put(("WAKE", None))

            elif event.type == pygame.KEYDOWN:
                if input_active:
                    if event.key == pygame.K_RETURN:
                        if input_text.strip() and not is_busy:
                            action_queue.put(("TEXT", input_text.strip()))
                            input_text = ""
                    elif event.key == pygame.K_BACKSPACE:
                        input_text = input_text[:-1]
                    else:
                        if event.unicode and event.unicode.isprintable():
                            input_text += event.unicode

        # 1. Animation frame cycle
        images = animations.get(current_state, animations[IDLE])
        frame_index = (frame_index + 1) % (len(images) * 10)
        current_frame = frame_index // 10
        if current_frame >= len(images): current_frame = 0

        # 2. Render Face Screen (Top Area)
        screen.fill(CHASSIS_TEAL)
        screen.blit(images[current_frame], (0, 0))
        
        # 3. Separator line between face screen and control panel
        pygame.draw.line(screen, CHASSIS_DARK, (0, FACE_HEIGHT), (WINDOW_WIDTH, FACE_HEIGHT), 2)

        # 4. Render Text Input Box (Retro Mint Inset)
        ibg = INPUT_BG_ACTIVE if input_active else INPUT_BG
        iborder = INPUT_BORDER_ACTIVE if input_active else INPUT_BORDER
        pygame.draw.rect(screen, ibg, input_rect, border_radius=6)
        pygame.draw.rect(screen, iborder, input_rect, width=2, border_radius=6)
        
        if not input_text and not input_active:
            txt_surf = font_small.render("Scrivi a BMO e premi Invio...", True, PLACEHOLDER_COLOR)
            screen.blit(txt_surf, (input_rect.x + 8, input_rect.y + 7))
        else:
            visible_text = input_text
            txt_surf = font_small.render(visible_text, True, TEXT_COLOR)
            # Text scroll window if longer than box
            while txt_surf.get_width() > input_rect.width - 24 and len(visible_text) > 1:
                visible_text = visible_text[1:]
                txt_surf = font_small.render(visible_text, True, TEXT_COLOR)
            screen.blit(txt_surf, (input_rect.x + 8, input_rect.y + 7))
            
            # Blinking text cursor
            if input_active and (pygame.time.get_ticks() // 500) % 2 == 0:
                cursor_x = input_rect.x + 8 + txt_surf.get_width() + 1
                pygame.draw.line(screen, TEXT_COLOR, (cursor_x, input_rect.y + 7), (cursor_x, input_rect.y + 24), 2)

        # 5. Render Send Button (INVIA - 3D Tactile Slate Button)
        send_is_hover = send_btn_rect.collidepoint(mouse_pos) and not is_busy
        send_is_down = send_is_hover and mouse_pressed
        send_bg = BTN_SEND_HOVER if send_is_hover else BTN_SEND_BG
        
        # 3D Shadow
        s_shadow = pygame.Rect(send_btn_rect.x, send_btn_rect.y + 2, send_btn_rect.w, send_btn_rect.h)
        pygame.draw.rect(screen, BTN_SEND_SHADOW, s_shadow, border_radius=6)
        # Face (press down 1px when clicked)
        y_off = 1 if send_is_down else 0
        s_face = pygame.Rect(send_btn_rect.x, send_btn_rect.y + y_off, send_btn_rect.w, send_btn_rect.h - 1)
        pygame.draw.rect(screen, send_bg, s_face, border_radius=6)
        
        send_txt = font_btn.render("INVIA", True, BTN_SEND_TEXT)
        screen.blit(send_txt, (send_btn_rect.centerx - send_txt.get_width() // 2, send_btn_rect.centery - send_txt.get_height() // 2 - 1 + y_off))

        # 6. Render Mic Wake Button (3D Tactile Arcade Button with Crisp Mic Icon)
        if current_state == LISTENING:
            mic_bg = BTN_MIC_RECORDING
            mic_shadow = BTN_MIC_REC_SHADOW
            mic_icon_surf = mic_icons["white"]
        elif is_busy:
            mic_bg = BTN_MIC_BUSY
            mic_shadow = BTN_MIC_BUSY_SHADOW
            mic_icon_surf = mic_icons["busy"]
        else:
            mic_is_hover = mic_btn_rect.collidepoint(mouse_pos)
            mic_bg = BTN_MIC_HOVER if mic_is_hover else BTN_MIC_BG
            mic_shadow = BTN_MIC_SHADOW
            mic_icon_surf = mic_icons["normal"]

        mic_is_down = mic_btn_rect.collidepoint(mouse_pos) and mouse_pressed and not is_busy
        my_off = 1 if mic_is_down else 0
        
        m_shadow = pygame.Rect(mic_btn_rect.x, mic_btn_rect.y + 2, mic_btn_rect.w, mic_btn_rect.h)
        pygame.draw.rect(screen, mic_shadow, m_shadow, border_radius=6)
        m_face = pygame.Rect(mic_btn_rect.x, mic_btn_rect.y + my_off, mic_btn_rect.w, mic_btn_rect.h - 1)
        pygame.draw.rect(screen, mic_bg, m_face, border_radius=6)
        screen.blit(mic_icon_surf, (mic_btn_rect.centerx - 11, mic_btn_rect.centery - 12 + my_off))

        pygame.display.flip()
        clock.tick(30)


# --- AUDIO LOGIC (PIPER) ---
def speak_with_piper(text):
    """Generates and plays audio, forcing the SPEAKING state."""
    global current_state
    if not text.strip(): return
    
    previous_state = current_state
    current_state = SPEAKING
    
    command = [PIPER_PATH, "--model", PIPER_MODEL, "--output_file", OUTPUT_WAV, "--length_scale", "0.9"]
    try:
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
            pygame.mixer.quit()
        
        if os.path.exists(OUTPUT_WAV): os.remove(OUTPUT_WAV)
        
        subprocess.run(command, input=text.encode('utf-8'), check=True, capture_output=True)
        
        pygame.mixer.init(frequency=28000, size=-16, channels=1, buffer=4096)
        pygame.mixer.music.load(OUTPUT_WAV)
        pygame.mixer.music.play()
        
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)
            
    except Exception as e:
        print(f"Errore Audio: {e}")
    
    current_state = previous_state


# --- LISTENING LOGIC (WHISPER) ---
def transcribe_with_whisper(audio_data):
    """Saves temporary audio and passes it to Whisper."""
    try:
        with open(TEMP_INPUT_WAV, "wb") as f:
            f.write(audio_data.get_wav_data())
        
        result = whisper_model.transcribe(
            TEMP_INPUT_WAV, 
            language="it", 
            fp16=False, 
            temperature=0.0,
            initial_prompt="BMO, robot, bip, Adventure Time"
        )
        transcribed_text = result["text"].strip().lower()
        
        if transcribed_text:
            print(f"\n[DEBUG AUDIO]: Whisper ha rilevato -> \"{transcribed_text}\"")
        
        return transcribed_text
    except Exception as e:
        print(f"Errore trascrizione: {e}")
        return ""


# --- CENTRAL REASONING & RESPONSE PIPELINE ---
def process_question(question):
    """Processes question (from voice or text), enriches context, queries Ollama, and speaks answer."""
    global current_state

    speak_with_piper("Ci sto pensando")
    current_state = THINKING
    print(f"Tu: {question}")
    
    context_for_gemma = ""
    
    # 1. Date/Time Check (Local clock)
    if any(x in question.lower() for x in ["ore", "ora", "orario", "giorno", "data", "oggi"]):
        now = datetime.now()
        days_of_week = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
        context_for_gemma = f"L'orario attuale è {now.strftime('%H:%M')}. Oggi è {days_of_week[now.weekday()]} {now.strftime('%d/%m/%Y')}."
    
    # 2. General Knowledge / News Search
    elif any(x in question.lower() for x in ["chi", "cosa", "scritto", "autore", "meteo", "notizie", "perché"]):
        context_for_gemma = bmo_web_search(question)

    # 3. Call Ollama
    final_prompt_text = question
    if context_for_gemma:
        final_prompt_text = f"CONTESTO: {context_for_gemma}\n\nDOMANDA: {question}"

    response = ollama.chat(model=MODEL_OLLAMA, messages=[
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {'role': 'user', 'content': final_prompt_text}
    ])
    
    answer = response['message']['content']

    # 4. Fallback: If Gemma is unsure, query web search
    doubt_words = ["non so", "mi dispiace", "non conosco", "non sono sicuro"]
    if any(d in answer.lower() for d in doubt_words) and not context_for_gemma:
        print("🌐 Fallback: Gemma è confusa, cerco sul web...")
        new_context = bmo_web_search(question)
        if new_context:
            response = ollama.chat(model=MODEL_OLLAMA, messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': f"CONTESTO: {new_context}\n\nDOMANDA: {question}"}
            ])
            answer = response['message']['content']

    print(f"BMO: {answer}")
    speak_with_piper(answer)
    print("BMO: Se hai altre domande chiamami pure")
    speak_with_piper("Se hai altre domande chiamami pure")


# --- BACKGROUND VOICE LISTENER THREAD ---
def voice_listener_worker(recognizer):
    """Monitors ambient audio for the Wake Word in background when BMO is idle."""
    while True:
        if current_state == IDLE and not is_busy:
            try:
                with sr.Microphone() as source:
                    print(".", end="", flush=True)
                    audio = recognizer.listen(source, timeout=1.0, phrase_time_limit=4)
                    text = transcribe_with_whisper(audio)
                    if WAKE_WORD in text:
                        action_queue.put(("WAKE", None))
            except sr.WaitTimeoutError:
                continue
            except Exception:
                time.sleep(0.5)
                continue
        else:
            time.sleep(0.3)


# --- MAIN DISPATCHER LOOP ---
def main():
    global current_state, is_busy 
    
    recognizer = sr.Recognizer()
    recognizer.energy_threshold = 50 
    recognizer.dynamic_energy_threshold = False 
    recognizer.pause_threshold = 0.8

    print(f"\n--- BMO È ONLINE (Dì '{WAKE_WORD.upper()}', clicca il microfono o scrivi nella barra) ---")
    speak_with_piper("BMO è ora online, quando sei pronto chiamami, clicca il microfono oppure scrivimi")

    # Start voice wake-word listener thread
    v_thread = threading.Thread(target=voice_listener_worker, args=(recognizer,), daemon=True)
    v_thread.start()

    while True:
        current_state = IDLE
        
        # Blocks until an interaction trigger arrives (GUI mic button, Text, or Voice Wake Word)
        action_type, data = action_queue.get()
        is_busy = True
        
        try:
            if action_type == "WAKE":
                print(f"\n[BMO]: ✨ TI ASCOLTO! ✨")
                speak_with_piper("Dimmi pure")
                
                current_state = LISTENING
                print("...ascolto domanda dal microfono...")
                with sr.Microphone() as source:
                    question_audio = recognizer.listen(source, timeout=7, phrase_time_limit=10)
                question = transcribe_with_whisper(question_audio)
                
                if len(question) > 1:
                    process_question(question)
                else:
                    current_state = IDLE
                    
            elif action_type == "TEXT":
                question = data
                print(f"\n[TESTO DA INTERFACCIA]: Tu: {question}")
                process_question(question)

        except Exception as e:
            print(f"Errore durante l'elaborazione: {e}")
        finally:
            current_state = IDLE
            is_busy = False


if __name__ == "__main__":
    load_config()
    ui_thread = threading.Thread(target=window_thread, daemon=True)
    ui_thread.start()
    main()
