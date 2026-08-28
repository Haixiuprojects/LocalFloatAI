# LocalFloatAI

**LocalFloatAI** is a compact, floating, always-on-top Windows desktop assistant created by a Filipino developer/user. It runs a local `.gguf` language model on the user's own computer and is designed for offline use after the model runtime and files are available.

## Features

| Feature | Behavior |
|---|---|
| Floating chatbox | Compact, transparent, movable, adjustable opacity, and always-on-top. |
| External GGUF import | Use **Import GGUF** to select a `.gguf` file from any local folder, drive, or flash drive. The model is not bundled into the executable. |
| Adaptive hardware detection | Detects the operating system, x64 architecture, RAM, CPU cores, display size, and scaling. |
| CPU tuning | Selects conservative thread, context, and batch settings for the detected hardware and model size. GPU layers are disabled for CPU-only compatibility. |
| Strict output | Returns the requested result without greetings, preambles, filler, or unnecessary explanations. Code requests return code only. |
| Ask mode | Optional concise conversational behavior. |
| Period new-request workflow | Select a complete request in another application, press `.`, and the app copies the request before generating the answer. |
| Custom selection key | Select code or text, press the configurable key from Settings, and choose `fix` or `continue`. |
| Paste mode | Copies the response and automatically pastes it into the previously active application. |
| Type mode | Types the response through Windows keyboard events, with clipboard fallback for Unicode text. |
| Screen OCR | Reads screen text only. The floating GUI is temporarily hidden during capture so its own text is not included. |
| Local API | Provides an OpenAI-compatible API at `127.0.0.1:8765`. |

## Requirements

The compiled build targets **Windows 10/11 x64**. Source mode requires Python 3.11 or newer. A smaller or medium quantized GGUF model is recommended for computers with 8 GB of RAM. Actual speed and memory use depend on the selected model and the target hardware.

> The GGUF model is intentionally external. Select it through **Import GGUF**, or place it in the `models/` folder for automatic discovery.

## Quick start

1. Extract the portable package or start the compiled `LocalFloatAI.exe`.
2. Click **Import GGUF**, select your `.gguf` file, and wait for the model to load.
3. Choose `paste` or `type` output mode.
4. Use the floating chatbox for ordinary requests, or use the keyboard workflows below.

The selected GGUF path is saved in `config.json`. The model does not need to be moved beside the executable and can remain on another drive or on a flash drive.

## New request with the period key

To send a new request without manually typing it into the floating chatbox, write the complete request in Notepad or another editor, select the request, and press the period (`.`) key. LocalFloatAI copies the complete selection, sends it to the local model, and pastes or types the result into the previously active application.

The **Global dot** toggle controls this behavior. Turn it off when you need to type a normal period without triggering a request. The Enter key and the **Send .** button remain available from the chatbox.

## Fix or continue selected code/text

1. Select the complete code or text in Notepad, an editor, a browser field, or another application.
2. Open Settings and assign a custom selected-text key.
3. Choose `fix` to receive the complete corrected code, or choose `continue` to continue the selected text/code from its endpoint.
4. Press the custom key. The app copies the selection first and suppresses the trigger key, so the trigger character is not inserted into the selected content.
5. LocalFloatAI returns the full response using the selected paste or type mode.

## Screen OCR

Click **Screen OCR** to capture text visible on the desktop. The floating LocalFloatAI window is hidden briefly while the screenshot is taken, which prevents the assistant's own GUI text from entering the OCR result. The window is restored after capture. The extracted text is copied to the clipboard and retained as context for the next AI request.

Screen OCR is text extraction only. It does not perform image understanding or describe non-text objects.

## Output cleanup

Strict result delivery removes Markdown code fences and common introductory filler such as `Here is the code:` before a response is pasted or typed. Quotes, punctuation, and syntax that are part of the requested code are preserved.

## Build the Windows executable from source

Run `build_windows.bat` on Windows. The script creates a virtual environment, installs dependencies, and builds a portable executable. The generated executable is placed at:

```text
dist\LocalFloatAI.exe
```

The portable release package also includes the OCR runtime beside the executable. Copy the complete portable folder to a flash drive when moving the application between Windows x64 computers. Do not copy a GGUF model unless you want the model on the same drive; it can be imported from any other accessible location.

## Local API

The API starts with the desktop application and binds to loopback by default:

```text
GET  http://127.0.0.1:8765/health
GET  http://127.0.0.1:8765/v1/models
POST http://127.0.0.1:8765/v1/chat/completions
```

Example using PowerShell:

```powershell
$body = @{
  model = "local-gguf"
  messages = @(
    @{ role = "user"; content = "Write a Python function that reverses a string." }
  )
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Uri http://127.0.0.1:8765/v1/chat/completions `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

Example using the OpenAI Python client:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8765/v1",
    api_key="local-not-used",
)

response = client.chat.completions.create(
    model="local-gguf",
    messages=[{"role": "user", "content": "Return only a JSON object with name and age."}],
)
print(response.choices[0].message.content)
```

The API is bound to the loopback address by default. Other devices on the network cannot access it unless the `host` value is intentionally changed in `config.json`.

## Configuration

`config.json` is created automatically from `config.example.json`. Important settings include:

| Key | Default | Description |
|---|---:|---|
| `model_path` | empty | External GGUF path; also set by **Import GGUF**. |
| `host` | `127.0.0.1` | Local API bind address. |
| `port` | `8765` | Local API port. |
| `opacity` | `0.94` | Floating window opacity. |
| `always_on_top` | `true` | Keep the floating window above other windows. |
| `capture_dot` | `true` | Enable the period-key new-request workflow. |
| `output_mode` | `paste` | `paste` or `type`. |
| `strict_mode` | `true` | Result-only response behavior. |
| `ask_mode` | `false` | Concise conversational behavior. |
| `capture_u_key` | `true` | Enable selected-text capture. |
| `selection_key` | `u` | Custom selected-text trigger; assign it in Settings. |
| `selection_action` | `fix` | `fix` for corrected code or `continue` for continuation. |

In **Settings**, click **Selected-text custom key**, press the desired key, and click **Save**. The new key is rebound immediately and saved to `config.json`.

## Safety and privacy

Paste and type modes write into the currently active application. Confirm the target window before using a keyboard workflow. The global keyboard hook may require Windows permission depending on system policy. The model, prompts, OCR results, and API requests remain local unless you intentionally configure another service or network bind address.

## Creator note

LocalFloatAI was created by a Filipino developer/user as a practical offline desktop tool for local GGUF models, code fixing, code continuation, screen text capture, and reusable localhost integration.

## License

No separate open-source license has been selected yet. Until a license is added, treat the repository as private and use the code only under the repository owner's authorization.

The project intentionally excludes GGUF model files, local `config.json`, secrets, and generated build artifacts from the source repository.
