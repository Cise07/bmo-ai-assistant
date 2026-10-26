import whisper
import ollama
import speech_recognition as sr
import subprocess
import pygame
import os
import threading
from datetime import datetime 
from ddgs import DDGS
import json


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
            # Retrieve the first 3 results to have a solid base
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

# --- GRAPHICAL LOGIC (ANIMATIONS) ---
def load_folder_images(folder):

    """Loads all images from a specific subfolder."""
    images_list = []
    
    if not os.path.exists(folder):
        print(f"ERRORE: La cartella '{folder}' non esiste!")
        # Backup: BMO green rectangle
        surf = pygame.Surface((400, 300))
        surf.fill((150, 220, 200))
        return [surf]
    
    # Gets image files and sorts them alphabetically
    files = sorted([f for f in os.listdir(folder) if f.lower().endswith(('.png', '.jpg', '.jpeg'))])
    
    if not files:
        print(f"AVVISO: La cartella '{folder}' è vuota!")
        surf = pygame.Surface((400, 300))
        surf.fill((150, 220, 200))
        return [surf]

    for f in files:
        img_path = os.path.join(folder, f)
        img = pygame.image.load(img_path)
        images_list.append(pygame.transform.scale(img, (400, 300)))
    
    return images_list
def window_thread():

    """Manages the window and cyclical animations."""
    global current_state
    pygame.init()
    screen = pygame.display.set_mode((400, 300))
    pygame.display.set_caption("BMO INTERFACE")
    
    # Pre-loading of all animations from 'faces' subfolders
    print("Caricamento immagini dalle cartelle...")
    animations = {s: load_folder_images(path) for s, path in FOLDERS.items()}
    
    frame_index = 0
    clock = pygame.time.Clock()
    
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                os._exit(0)

        # Selects the set of images based on the state
        images = animations.get(current_state, animations[IDLE])
        
        # Frame cycle management (changes every 10 ticks for smoothness)
        frame_index = (frame_index + 1) % (len(images) * 10)
        current_frame = frame_index // 10
        
        # Index safety
        if current_frame >= len(images): current_frame = 0

        # Rendering
        screen.blit(images[current_frame], (0, 0))
        pygame.display.flip()
        
        # Maintain 30 FPS to not overload the CPU
        clock.tick(30)

# --- AUDIO LOGIC (PIPER) ---
def speak_with_piper(text):

    """Generates and plays audio, forcing the SPEAKING state."""
    global current_state
    if not text.strip(): return
    
    previous_state = current_state
    current_state = SPEAKING # Activates speaking animation
    
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
            pygame.time.Clock().tick(10) # Waits for end of audio
            
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
        
        # --- TRANSCRIPTION DEBUG ---
        if transcribed_text:
            print(f"\n[DEBUG AUDIO]: Whisper ha rilevato -> \"{transcribed_text}\"")
        
        return transcribed_text
    except Exception as e:
        print(f"Errore trascrizione: {e}")
        return ""

# --- MAIN LOGIC (OLLAMA + RECOGNIZER) ---
def main():
    global current_state 
    
    recognizer = sr.Recognizer()
    recognizer.energy_threshold = 50 
    recognizer.dynamic_energy_threshold = False 
    recognizer.pause_threshold = 0.8
    
    system_prompt = (
        "Sei BMO di Adventure Time. Rispondi sempre in italiano. "
        "Usa frasi corte e semplici. Il tuo tono è ingenuo, robotico e gentile. "
        "Massimo 15 parole per risposta. Se ricevi informazioni esterne marcate come CONTESTO, "
        "usale per dare la risposta corretta alla domanda."
    )

    print(f"\n--- BMO È ONLINE (Dì '{WAKE_WORD.upper()}') ---")
    speak_with_piper("BMO è ora online, quando sei pronto chiamami")

    while True:
        with sr.Microphone() as source:
            current_state = IDLE 
            
            try:
                print(".", end="", flush=True) 
                wake_audio = recognizer.listen(source, timeout=None, phrase_time_limit=4)
                wake_text = transcribe_with_whisper(wake_audio)

                if WAKE_WORD in wake_text:
                    print(f"\n[BMO]: ✨ TI ASCOLTO! ✨")
                    speak_with_piper("Dimmi pure") 
                    
                    current_state = LISTENING 
                    print("...ascolto domanda...")
                    question_audio = recognizer.listen(source, timeout=7, phrase_time_limit=10)
                    question = transcribe_with_whisper(question_audio)
                    
                    if len(question) > 1:
                        speak_with_piper("Ci stò pensando")
                        current_state = THINKING 
                        # The print "Tu: question" acts as debug for the final question
                        print(f"Tu: {question}")
                        
                        context_for_gemma = ""
                        
                        # --- INTERCEPTION SEARCH LOGIC ---
                        
                        # 1. Time/Date Management (Local, no internet needed)
                        if any(x in question for x in ["ore", "ora", "orario", "giorno", "data", "oggi"]):
                            now = datetime.now()
                            days_of_week = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
                            context_for_gemma = f"L'orario attuale è {now.strftime('%H:%M')}. Oggi è {days_of_week[now.weekday()]} {now.strftime('%d/%m/%Y')}."
                        
                        # 2. General Knowledge / News Management (Requires Web Search)
                        elif any(x in question for x in ["chi", "cosa", "scritto", "autore", "meteo", "notizie", "perché"]):
                            context_for_gemma = bmo_web_search(question)

                        # Ollama Call
                        final_prompt_text = question
                        if context_for_gemma:
                            final_prompt_text = f"CONTESTO: {context_for_gemma}\n\nDOMANDA: {question}"

                        response = ollama.chat(model=MODEL_OLLAMA, messages=[
                            {'role': 'system', 'content': system_prompt},
                            {'role': 'user', 'content': final_prompt_text}
                        ])
                        
                        answer = response['message']['content']

                        # 3. Fallback: If Gemma still replies it doesn't know, force web search
                        doubt_words = ["non so", "mi dispiace", "non conosco", "non sono sicuro"]
                        if any(d in answer.lower() for d in doubt_words) and not context_for_gemma:
                            print("🌐 Fallback: Gemma è confusa, cerco sul web...")
                            new_context = bmo_web_search(question)
                            if new_context:
                                response = ollama.chat(model=MODEL_OLLAMA, messages=[
                                    {'role': 'system', 'content': system_prompt},
                                    {'role': 'user', 'content': f"CONTESTO: {new_context}\n\nDOMANDA: {question}"}
                                ])
                                answer = response['message']['content']

                        print(f"BMO: {answer}")
                      
                        speak_with_piper(answer)
                        print("BMO: Se hai altre domande chiamami pure")
                        speak_with_piper("Se hai altre domande chiamami pure")
                    else:
                        current_state = IDLE

            except Exception as e:
                print(f"Errore nel loop principale: {e}")
                current_state = IDLE
                continue

if __name__ == "__main__":
    load_config()
    ui_thread = threading.Thread(target=window_thread, daemon=True)
    ui_thread.start()
    main()