# BMO AI Assistant 🤖 ✨

BMO is an advanced interactive voice and text assistant inspired by the character from *Adventure Time*. It is designed to operate almost entirely **offline**, guaranteeing privacy, data security, and low-latency responses.

> [!WARNING]
> **Work in Progress**: This project is currently under active development. It is currently **functional on Windows PCs** and will be ported to **Raspberry Pi 5** in future releases. Features may change as development progresses; the body has not been printed yet.

> [!IMPORTANT]
> **Privacy & Local Computing**: All models (AI Intelligence, Speech-to-Text, and Text-to-Speech) run **locally on your machine**. The only exception is the web search function, which activates exclusively to retrieve real-time data or fill information gaps on current topics.

## 🚀 Key Features

- **Local Execution**: Run LLMs, Speech-to-Text, and Text-to-Speech locally without sending audio data to external servers.
- **Dynamic Graphical Interface**: A Pygame window (`400x286`) styled with BMO's retro console bezel, synchronized facial animations (`IDLE`, `LISTENING`, `THINKING`, `SPEAKING`), text input bar, `INVIA` button, and adaptive Mic/Stop button.
- **Dual Interaction Mode**: Interact by speaking (continuous voice wake-word detection `"bmo"` or clicking the microphone button) or by typing directly into the integrated text input bar.
- **Interruptible TTS (Stop Button / ESC)**: While BMO is speaking, the microphone button dynamically turns into a red Stop button (`■`); clicking it or pressing `ESC` immediately stops audio playback.
- **Rolling Conversation Memory**: Maintains a configurable rolling history of recent turns (`MAX_HISTORY_TURNS` in `config.json`) so BMO remembers context across follow-up questions.
- **Smart Intent Detection & Fallback Web Search**: Classifies queries into `local` (personal/greetings), `datetime` (real-time system clock/date), or `web` (DuckDuckGo search). If the LLM expresses uncertainty on a local query, it automatically triggers a fallback web search.
- **External JSON Configuration**: All paths, model names, audio volume, history length, and word limits are configurable via `config.json` (automatically generated with default values if missing).
- **Color-Coded Terminal Logging & File Logs**: Writes complete logs to `logs/bmo.log` and highlights terminal output using ANSI colors (**bright cyan** for BMO's spoken phrases/responses, **bright yellow** for Whisper transcriptions and user inputs).

## 🛠️ Technology Stack and Libraries

| Library | Model / Purpose | Execution |
| :--- | :--- | :--- |
| `openai-whisper` | OpenAI Whisper (`small`) — Speech-to-Text | **Local** |
| `ollama` | Gemma 3 (`gemma3:4b`) — LLM Brain | **Local** |
| `piper` | `it_IT-paola-medium` — Neural Text-to-Speech | **Local** (`./piper/`) |
| `ddgs` | DuckDuckGo Search — Real-time web context | Cloud |
| `pygame` | Retro GUI & Audio Mixer | **Local** |
| `SpeechRecognition` + `PyAudio` | Microphone Audio Input Stream | **Local** |
| `Pillow` | Anti-aliased UI icon rendering | **Local** |

## 📥 Installation & Setup

### 1. Clone & Python Environment
```powershell
git clone <repo-url>
cd BMO-Ai-assistant
python -m venv virtual
.\virtual\Scripts\Activate.ps1
pip install -r requirements.txt
```
*(Note: The OpenAI Whisper `small` model is downloaded automatically on first launch via `whisper.load_model("small")`.)*

### 2. Install Ollama & LLM Model
1. Download and install **Ollama** from [https://ollama.com/download](https://ollama.com/download).
2. Pull the default model configured in `config.json`:
   ```powershell
   ollama pull gemma3:4b
   ```

### 3. Install Piper TTS & Italian Voice Model (Local `./piper/` Folder)
Piper is kept locally inside the project folder (`./piper/`) and excluded from Git via `.gitignore`:

1. **Download Piper for Windows**:
   - Go to the official Piper releases page: [https://github.com/rhasspy/piper/releases](https://github.com/rhasspy/piper/releases)
   - Download **`piper_windows_amd64.zip`** and extract its contents into `./piper/` inside the project root (so that `./piper/piper.exe` exists).
2. **Download the Preferred Italian Voice Model (`it_IT-paola-medium`)**:
   - Browse all Piper voices (interactive samples): [https://rhasspy.github.io/piper-samples/](https://rhasspy.github.io/piper-samples/)
   - Direct download links for **`it_IT-paola-medium`** on Hugging Face ([model folder](https://huggingface.co/rhasspy/piper-voices/tree/main/it/it_IT/paola/medium)):
     - Model file (`.onnx`): [it_IT-paola-medium.onnx](https://huggingface.co/rhasspy/piper-voices/resolve/main/it/it_IT/paola/medium/it_IT-paola-medium.onnx?download=true)
     - Config file (`.onnx.json`): [it_IT-paola-medium.onnx.json](https://huggingface.co/rhasspy/piper-voices/resolve/main/it/it_IT/paola/medium/it_IT-paola-medium.onnx.json?download=true)
   - Place both `it_IT-paola-medium.onnx` and `it_IT-paola-medium.onnx.json` inside the `./piper/` folder.

### 4. Configuration (`config.json`)
```json
{
    "MODEL_OLLAMA": "gemma3:4b",
    "WAKE_WORD": "bmo",
    "PIPER_PATH": "./piper/piper.exe",
    "PIPER_MODEL": "./piper/it_IT-paola-medium.onnx",
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
        "SPEAKING": "speaking"
    }
}
```

## 🖥️ Running & Real-time Debugging

Run the assistant with:
```powershell
.\virtual\Scripts\python.exe bmo-main.py
```

If Windows does not use your desired microphone by default, run `mic-check.py` to list detected audio input device indices:
```powershell
.\virtual\Scripts\python.exe mic-check.py
```

During execution, logs are saved to `logs/bmo.log` and printed to the terminal with color highlights:
- **Bright Yellow**: User voice transcriptions (`Whisper → ...`, `Domanda ricevuta: ...`) and text inputs (`Input testuale: ...`).
- **Bright Cyan**: Everything BMO speaks (`BMO pronuncia: ...`) and generates (`Risposta BMO: ...`).
- **Standard Output**: State transitions, intent detection, DuckDuckGo searches, and system diagnostics.

## 📦 Assets

**All original components:**
- ✅ **Code**: Written from scratch
- ✅ **Face Images & Animations**: 100% original custom artwork with retro console frame (`./faces/idle/`, `./faces/listening/`, `./faces/thinking/`, `./faces/speaking/`)
- ✅ **Architecture**: Multi-threaded event-driven design (`BMOConfig`, `BMOState`, GUI & Voice workers)
- ✅ **AI Integration**: Ollama + Gemma 3, Whisper, Piper
- ✅ **Web Search Logic**: Intent classifier + automatic uncertainty fallback
- ✅ **GUI System**: Custom Pygame implementation with interactive text bar and adaptive Mic/Stop button

### Disclaimer
> [!IMPORTANT]
> **This is a fan creation.** BMO and Adventure Time are properties of **Cartoon Network**. This project is not affiliated with, endorsed by, or associated with Cartoon Network or any of its parent companies. This project is created for educational and personal use only.

---

## 📜 License & Attribution

This project is released under the **MIT License**.

### Third-Party Dependencies

| Component | License | Purpose |
| :--- | :--- | :--- |
| **OpenAI Whisper** | MIT | Speech-to-Text engine |
| **Ollama** | MIT | LLM runtime and inference |
| **Gemma 3** | Google Terms | Language model |
| **Piper TTS** | MIT | Text-to-Speech synthesis |
| **Pygame** | LGPL | Graphics and audio rendering |
| **DuckDuckGo Search** | MIT | Web search results |
| **SpeechRecognition** | BSD-3-Clause | Audio input stream handling |
| **Pillow** | HPND | UI icon rendering |
