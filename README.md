# BMO AI Assistant 🤖 ✨

BMO is an advanced interactive voice assistant inspired by the character from *Adventure Time*. It is designed to operate almost entirely **offline**, guaranteeing privacy, data security, and low-latency responses.

> [!WARNING]
> **Work in Progress**: This project is currently under active development. It is currently **functional on Windows PCs** and will be ported to **Raspberry Pi 5** in future releases. Features may change as development progresses , the body has not been printed yet.

> [!IMPORTANT]
> **Privacy & Local Computing**: All models (AI Intelligence, Voice-to-Text, and Text-to-Speech) run **locally on your machine**. The only exception is the web search function, which activates exclusively to retrieve real-time data or fill information gaps on current topics.

## 🚀 Key Features

- **Local Execution**: Leverage your hardware's power to run LLMs and Speech-to-Text without sending audio data to external servers.
- **Dynamic Graphical Interface**: A Pygame window styled with BMO's retro console bezel and synchronized facial animations (Idle with sleeping Zzz, Listening, Thinking with animated question marks, Speaking with lip-sync).
- **Dual Interaction Mode**: Interact by speaking (voice wake-word or graphical 'Sveglia BMO' button) or by typing directly into the integrated text input bar.
- **Voice Recognition (STT)**: Based on **OpenAI Whisper**, optimized for accurate Italian transcription.
- **AI Brain**: Powered by **Gemma 3 (4b)** via Ollama, configured with a specific personality system.
- **Voice Synthesis (TTS)**: Uses **Piper**, an ultra-fast neural engine for fluid and reactive speech.
- **Predictive Web Search**: If BMO detects a question about current events or general knowledge, it automatically queries **DuckDuckGo** to provide accurate answers.

## 🛠️ Technology Stack and Libraries

| Library | Model / Purpose | Execution |
| :--- | :--- | :--- |
| `whisper` | OpenAI Whisper (Small) | **Local** |
| `ollama` | Gemma 3 (4b) | **Local** |
| `piper` | it_IT-paola-medium | **Local** |
| `ddgs` | DuckDuckGo Search | Cloud |
| `pygame` | GUI & Audio Mixer | **Local** |
| `speech_recognition` | Audio Input Stream | **Local** |

## ⚙️ How It Works

1. **Monitoring**: The system remains in `IDLE` state. Whisper continuously monitors ambient audio for the **Wake Word** ("BMO").
2. **Interception and Analysis**: Once activated, BMO listens to the complete question. The system analyzes in real-time whether the request involves:
   - **Date/Time**: Responds using the system clock (no external search).
   - **Web Search**: If the question contains keywords like "who", "what", "weather", "news", or other terms requiring current information, it queries DuckDuckGo.
3. **Reasoning**: Data obtained from the search (if necessary) is passed to Gemma 3 as enriched context. If the model lacks sufficient information, the system attempts a second automatic search fallback.
4. **Synthesized Response**: The generated text is converted to audio by Piper and played while the GUI animates BMO in `SPEAKING` state with lip-sync.

## 📁 System Requirements

- **Ollama**: Model `gemma3:4b` installed.
- **Piper TTS**: `piper.exe` file and `.onnx` model configured in the correct paths.
- **Faces Folder**: A folder structure containing animation frames:
  - `./faces/idle/`
  - `./faces/listening/`
  - `./faces/thinking/`
  - `./faces/speaking/`
- **Whisper**: Open Ai `Whisper` model installed.
## 🖥️ Real-time Debugging
To facilitate development, the code prints to the terminal every phase of the process:
- `[DEBUG AUDIO]`: Shows exactly what Whisper understood from your words.
- `🔍 BMO is consulting...`: Indicates when the assistant is accessing the network to search for information.
- `BMO: [Response]`: Shows the text output from the AI.

## 📦 Assets

**All original components:**
- ✅ **Code**: Written from scratch
- ✅ **Face Images & Animations**: 100% original custom artwork with retro console frame
- ✅ **Architecture**: Designed from scratch
- ✅ **AI Integration**: Ollama + Gemma 3, Whisper, Piper - custom implementation
- ✅ **Web Search Logic**: Custom implementation
- ✅ **GUI System**: Custom Pygame implementation with interactive text bar and wake button


### Disclaimer
>[!IMPORTANT]
>**This is a fan creation.** BMO and Adventure Time are properties of **Cartoon Network**. This project is not affiliated with, endorsed by, or associated with Cartoon Network or any of its parent companies. This project is created for educational and personal use only.

---

## 📜 License & Attribution

This project is released under the **MIT License**.

### Third-Party Dependencies

This project uses the following open-source libraries and models:

| Component | License | Purpose |
| :--- | :--- | :--- |
| **OpenAI Whisper** | MIT | Speech-to-Text engine |
| **Ollama** | MIT | LLM runtime and inference |
| **Gemma 3** | Google Terms | Language model |
| **Piper TTS** | MIT | Text-to-Speech synthesis |
| **Pygame** | LGPL | Graphics and audio rendering |
| **DuckDuckGo Search** | Proprietary | Web search results |
| **SpeechRecognition** | BSD-3-Clause | Audio input stream handling |


### Compliance Notes

When using this project, ensure compliance with:
- MIT License for original code and direct dependencies
- Respective model licenses (Gemma 3, Whisper, Piper)
- Third-party service terms (DuckDuckGo)

---
