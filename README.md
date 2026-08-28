# LocalFloatAI

**LocalFloatAI** ay isang maliit, floating, always-on-top Windows desktop assistant na gumagamit ng lokal na `.gguf` model. Ang inference ay tumatakbo sa sariling PC at hindi nangangailangan ng cloud API pagkatapos mailagay ang model file.

## Kasalukuyang feature set

| Feature | Behavior |
|---|---|
| Floating chatbox | Compact, transparent, movable, adjustable opacity, at always-on-top |
| Offline GGUF | May **Import GGUF** button para pumili ng `.gguf` mula sa anumang local folder, flash drive, o custom path |
| Adaptive hardware | Awtomatikong bumabasa ng OS, x64 architecture, RAM, CPU cores, screen size, at scaling |
| CPU tuning | Awtomatikong pumipili ng conservative threads, context size, batch size, at zero GPU layers |
| Strict output | Walang greeting, preamble, filler, o “here is the code”; code-only kapag code ang hiningi |
| Ask mode | Optional normal concise Q&A behavior |
| Global dot key | Ang `.` key ay nagse-send ng request kapag naka-enable ang toggle |
| U key selection | Kinokopya ang selected text/code mula sa active app at ipinapadala ito sa Continue o Fix Code action |
| Paste mode | Kinokopya ang sagot at awtomatikong nagta-`Ctrl+V` sa kasalukuyang app |
| Type mode | Tina-type ang sagot sa kasalukuyang app gamit ang OS keyboard events |
| Local API | OpenAI-compatible endpoint sa `127.0.0.1:8765` |

## Requirements

Ang Windows build ay para sa **Windows 10/11 x64** at nangangailangan ng Python 3.11 o mas bago para sa source mode. Para sa PC na may 8 GB RAM, mas praktikal ang maliit o medium quantized GGUF model. Ang aktuwal na bilis at memory use ay nakadepende sa model size at sa hardware.

> Hindi kasama ang GGUF model sa source package. Ang model ay kailangang ilagay ng user sa `models/` dahil ang assistant ay idinisenyo para sa lokal at offline na paggamit.

## Quick start mula sa source

1. I-install ang 64-bit Python 3.11+ sa Windows kung source mode ang gagamitin, o buksan ang compiled EXE.
2. I-double-click ang `run_windows.bat` o ang compiled `LocalFloatAI.exe`.
3. Pindutin ang **Import GGUF**, pumili ng `.gguf` mula sa kahit anong folder o flash drive, at hintayin ang automatic load.
4. Pagkatapos ma-load, ipadala ang prompt gamit ang `Send .`, Enter, o global `.` key.

Hindi kinakailangang ilipat o kopyahin ang GGUF sa tabi ng EXE. Naka-save ang napiling external path sa `config.json` at maaaring palitan anumang oras gamit ang **Import GGUF** button. Kapag walang manually imported model, saka lamang mag-a-auto-select ang app mula sa `models/` folder.

## Selected text o code gamit ang U key

1. Sa Notepad, code editor, browser, o ibang app, i-highlight ang text o code.
2. Pindutin ang **U**. Awtomatikong mag-`Ctrl+C` ang app at babasahin ang clipboard contents; hindi ilalagay ang U sa selected text.
3. Piliin sa floating box ang `fix` para ibalik ang kumpletong corrected code, o `continue` para ipagpatuloy ang selected code/text mula sa dulo.
4. Gagamitin ng app ang napiling paste o type mode para ibalik ang result sa dating active window. Ang strict output ay result-only at walang Markdown fences.

## Paano gamitin ang output

Piliin ang `paste` kung nais mong awtomatikong ilagay ang sagot sa Notepad, editor, browser field, o ibang aktibong application. Piliin ang `type` kung nais mong dumaan ang sagot bilang simulated keyboard typing. Sa type mode, ang Unicode text ay awtomatikong gumagamit ng clipboard fallback kapag hindi maipadala bilang direct keyboard event.

Kapag ginagamit ang `.` bilang send key sa ibang app, ang toggle na **Global dot** ang kumokontrol kung naka-capture ito. I-off ito kapag kailangan mong mag-type ng normal na period nang hindi nagsi-send ng prompt. Ang Escape key ay nagtatago ng floating window.

## Build ng Windows EXE

I-double-click ang `build_windows.bat`. Gumagawa ito ng `.venv`, nag-i-install ng dependencies, at nagbu-build ng portable folder:

```text
dist\LocalFloatAI\LocalFloatAI.exe
dist\LocalFloatAI\models\
```

Ilagay ang `.gguf` file sa `dist\LocalFloatAI\models\` pagkatapos ng build. Ang output ay one-folder build upang madaling maisama ang native llama.cpp libraries at maiwasan ang dependency issues ng single-file executable.

## Local API

Ang API ay nagsisimula kasama ng desktop app:

```text
GET  http://127.0.0.1:8765/health
GET  http://127.0.0.1:8765/v1/models
POST http://127.0.0.1:8765/v1/chat/completions
```

Halimbawa gamit ang PowerShell:

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

Halimbawa gamit ang Python client:

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

Ang API ay naka-bind sa loopback address lamang bilang default, kaya ang ibang devices sa network ay hindi makaka-access maliban kung sadyang babaguhin ang `host` sa `config.json`.

## Configuration

Ang `config.json` ay awtomatikong ginagawa mula sa `config.example.json`. Mahahalagang setting:

| Key | Default | Gamit |
|---|---:|---|
| `model_path` | empty | External GGUF path; itinatakda rin ito ng Import GGUF button |
| `host` | `127.0.0.1` | Local API bind address |
| `port` | `8765` | Local API port |
| `opacity` | `0.94` | Floating window opacity |
| `always_on_top` | `true` | Laging nasa ibabaw ng ibang windows |
| `capture_dot` | `true` | Global period/dot send key |
| `output_mode` | `paste` | `paste` o `type` |
| `strict_mode` | `true` | Result-only response behavior |
| `ask_mode` | `false` | Concise conversational behavior |
| `capture_u_key` | `true` | Enable selected-text capture |
| `selection_key` | `u` | Custom selected-text trigger; set it in Settings |
| `selection_action` | `fix` | `fix` for corrected code or `continue` for continuation |

Sa **Settings**, i-click ang field na **Selected-text custom key**, pindutin ang gusto mong isang key, at i-click ang **Save**. Puwedeng gumamit ng `U`, `F8`, `Home`, `Up`, `Space`, o ibang key na kinikilala ng Windows keyboard hook. Ang bagong key ay nire-rebind agad at sine-save sa `config.json`.

## Important safety behavior

Ang paste at type mode ay sumusulat sa kasalukuyang active application. Bago pindutin ang send key, siguraduhing tama ang target window. Ang global hotkey ay maaaring mangailangan ng Windows permission depende sa system policy. Kung hindi gumana ang dot hook, puwedeng gamitin ang Enter o ang `Send .` button.
