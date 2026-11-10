# RANI AI 🎙️ — Wali Hasan ki personal voice assistant

RANI ek **Urdu / Roman Urdu / English** voice assistant hai jo **Windows 10/11** par chalti hai.
Screen ke top-right mein ek chamakta hua orb (HUD) aata hai, RANI Pakistani female awaaz (`ur-PK-UzmaNeural`) mein baat karti hai,
aur aapke laptop ko control karti hai: apps kholna, volume, brightness, screenshot, timer, files, lock/sleep/shutdown, aur AI se baatcheet.

> Poora code aapka apna hai (`rani/` folder). Is mein kisi aur project ka code nahi.

**AI ka order (khud badalta hai):** Gemini → Grok → Groq → OpenRouter → aapka apna cloud → **Ollama (offline, hamesha aakhri)**.
Jis ki limit khatam ho ya internet band ho, RANI foran agle par chali jati hai — aapko kuch karna nahi parta.

---

## Fehrist (Table of contents)

1. [RANI kya kya kar sakti hai?](#1-rani-kya-kya-kar-sakti-hai)
2. [Pehle yeh cheezein chahiye (Requirements)](#2-pehle-yeh-cheezein-chahiye)
3. [Install — Step by step](#3-install--step-by-step)
4. [Pehli dafa chalana](#4-pehli-dafa-chalana)
5. [AI keys lagana (Gemini, Grok, Groq, OpenRouter, Ollama)](#5-ai-keys-lagana-sab-optional)
6. [RANI se baat kaise karein](#6-rani-se-baat-kaise-karein)
7. [Commands ki list](#7-commands-ki-list)
8. [Windows start hote hi RANI aur greeting](#8-windows-start-hote-hi-rani-aur-greeting)
9. [Settings](#9-settings)
10. [Security — RANI kya NAHI kar sakti](#10-security--rani-kya-nahi-kar-sakti)
11. [Masle aur unke hal (Troubleshooting)](#11-masle-aur-unke-hal-troubleshooting)
12. [Aksar poochay jane wale sawal (FAQ)](#12-aksar-poochay-jane-wale-sawal-faq)
13. [Developers ke liye](#13-developers-ke-liye)
14. [Honest status — kya test hua, kya nahi](#14-honest-status--kya-test-hua-kya-nahi)
15. [Uninstall](#15-uninstall)

---

## 1. RANI kya kya kar sakti hai?

| Kaam | Misaal |
|---|---|
| Apps kholna / band karna | "Chrome kholo", "Notepad band karo", "minimize chrome" |
| Volume / mute / brightness | "Volume 30 percent kar do", "mute", "brightness 50 kar do" |
| System info | "battery batao", "CPU RAM batao", "wifi status", "screenshot lo" |
| Timer / reminder / tasks | "5 minute ka timer lagao", "10 minute baad chai yaad dila do", "task add karo report likhni hai" |
| Yaaddasht (memory) | "yaad rakho meri car Honda hai", "kya yaad hai" |
| Web | "open github.com", "youtube par imran khan songs search karo" |
| Files | "Downloads folder kholo", "downloads mein resume dhundo", "Python ka project bana do" |
| Keyboard | "type hello world", "copy kar do", "show desktop" |
| Power | "laptop lock kar do", "laptop sleep kar do", "laptop shutdown kar do" (pehle poochti hai) |
| Baatcheet / sawal-jawab | Koi bhi aur baat — AI (Gemini ya Ollama) jawab deta hai |

---

## 2. Pehle yeh cheezein chahiye

* **Windows 10 ya 11** (RANI sirf Windows par laptop control karti hai)
* **Python 3.10 – 3.13** (64-bit). Python **3.14 abhi support nahi**.
  Na ho to `install.bat` khud `winget` se Python 3.12 install karne ki offer deta hai.
* **Internet** — pehli dafa packages download karne ke liye (PySide6 bara hai, 5–10 minute lag sakte hain),
  aur neural awaaz + AI ke liye.
* **Microphone** (awaaz se baat karne ke liye). Text mode ke liye zaroori nahi.
* **AI key** — optional (Gemini free hai): [section 5](#5-ai-keys-lagana-sab-optional).

---

## 3. Install — Step by step

**Step 1 — Zip extract karein.**
`RANI-AI.zip` par right-click → *Extract All* → chhota path rakhein, jaise `C:\RANI-AI`.

**Step 2 — `install.bat` par double-click.** Bas. Baqi sab khud hota hai:

1. Python 3.12 na ho to **khud install** (winget) aur usi window me aage chalta hai
2. `.venv` (RANI ka alag Python environment) banta hai
3. Zaroori packages install hote hain
4. `.env` file banti hai (API keys ke liye)
5. **Offline AI (Ollama) khud install** + model download (~2 GB, sirf ek dafa). 15 second me khud "Yes"; skip karna ho to **N** dabayein
6. Check chalta hai (`doctor`)
7. Pochta hai: "Windows start par RANI chale?" (15 second me khud "Yes") aur phir RANI **khud start** ho jati hai

Poore process me 10–20 minute lag sakte hain (internet speed par depend). Beech me kuch na dabayein to bhi sab theek chalta hai.

**Agar install fail ho:** screen ka aakhri error padhein, phir [Troubleshooting](#11-masle-aur-unke-hal-troubleshooting) dekhein.

---

## 4. Pehli dafa chalana

```powershell
.\start_rani.bat
```

Screen ke **top-right** mein orb aayega. Ho gaya! 🎉

* Bolne ke liye: **Ctrl + Alt + Space** dabayein (ya orb par click karein), phir bolein: *"Chrome kholo"*.
* Band karne ke liye: `.\stop_rani.bat` (ya tray icon → *Quit RANI*).
* Sirf **text se test** karna ho (awaaz/mic ke baghair):
  `.\.venv\Scripts\python.exe -m rani --cli`  → phir `chrome kholo` jaisi command type karein.

Kuch theek na chale to pehle: `.\doctor.bat` — yeh poora check karke batata hai kya kharab hai
(report `doctor_report.txt` mein bhi save hoti hai).

---

## 5. AI keys lagana (sab optional)

Bina kisi key ke bhi saari basic commands (volume, apps, battery...) chalti hain, aur Ollama ki wajah se baatcheet bhi offline ho jati hai.
Jitni keys aap dalenge utna behtar — **sirf wohi dalein jo aapke paas hain**, baqi khali chhor dein.

| # | Provider | Key kahan se | `.env` ka naam |
|---|---|---|---|
| 1 | **Gemini** (free) | <https://aistudio.google.com/apikey> | `GEMINI_API_KEY` |
| 2 | **Grok** (xAI) | <https://console.x.ai> | `XAI_API_KEY` |
| 3 | **Groq** (free tier, bohat tez) | <https://console.groq.com/keys> | `GROQ_API_KEY` |
| 4 | **OpenRouter** (kuch models free) | <https://openrouter.ai/keys> | `OPENROUTER_API_KEY` |
| 5 | Aapka apna cloud (OpenAI wagairah) | Settings me base URL + model | `OPENAI_COMPAT_API_KEY` |
| 6 | **Ollama** — offline | key nahi chahiye, `install.bat` khud lagata hai | — |

*(Groq aur Grok do alag companies hain.)*

**Kaise lagayein:** orb par **⚙** → **AI Brain** → key paste → **Save** → **Test AI connection**
(key Windows Credential Manager me jati hai). Ya `.env` file kholein aur `GEMINI_API_KEY=aapki_key` likh dein.

**RANI khud kaise badalti hai:**
* Limit khatam (HTTP 429 / quota) → woh provider kuch der (5 minute, phir barhta jata hai) skip hota hai, agla try hota hai.
* Internet band → pehli koshish ke baad saare cloud foran skip, seedha Ollama. Is se jawab me der nahi lagti.
* Galat key → us provider ko 1 ghanta skip; nayi key save karte hi dobara try.
* Ollama ki apni window install ke baad khud band ho jati hai aur login par dobara nahi khulti; RANI sirf background server chalati hai.
* Ollama band ho to RANI use khud start karti hai. Model na ho to background me download kar leti hai.
* Models ke naam Settings me badal sakte hain (company naye models nikalti rehti hai).

**Offline AI baad me lagana ho:** `.\.venv\Scripts\python.exe -m rani --setup-ai`

> ⚠️ Bolna (microphone → text) abhi Google ki service se hota hai, isliye **internet band ho to awaaz se command samajhna kaam nahi karta**
> (Ollama jawab de sakta hai, lekin sunne ke liye net chahiye). Text mode (`--cli`) offline bhi chalta hai.

---

## 6. RANI se baat kaise karein

| Tareeqa | Kaise |
|---|---|
| **Push-to-talk** (default) | **Ctrl+Alt+Space**, orb par click, ya 🎤 button. RANI bol rahi ho to dabane se woh ruk jati hai |
| **Wake word** "RANI" | Settings → General → Listening mode → *Wake word*. Yeh lagataar sunta hai aur audio Google speech recognition ko jata hai, isliye default **band** hai |
| **Text** | `.\.venv\Scripts\python.exe -m rani --cli` |
| 🛑 **Emergency stop** | **Ctrl+Alt+X**, ■ button, tray menu, ya bolein: "stop" / "ruko" / "bas". Awaaz, pending confirmation, aur scheduled shutdown sab cancel |

RANI jawab ke baad thori der follow-up ke liye sunti hai, to aap likh/bol sakte hain:
"Chrome kholo" … "ab YouTube par songs search karo". Urdu script, Roman Urdu aur English teeno samajhti hai.

---

## 7. Commands ki list

```text
RANI!                                   → "Jee Wali! Main hazir hoon. Bataiye?"

# Apps
Chrome kholo / VS Code open karo / Notepad kholo
Chrome band karo / minimize chrome / switch to chrome

# Awaaz aur roshni
Volume 30 percent kar do / awaaz kam karo / volume barhao / mute / unmute
Brightness 50 kar do

# Information
Mujhe battery percentage batao / CPU RAM batao / wifi status / Screenshot lo
Time kya hua hai / aaj ki date kya hai / tum kaun ho

# Productivity
5 minute ka timer lagao / 10 minute baad chai yaad dila do / remind me at 5 pm to call mom
Task add karo report likhni hai / meri tasks batao
Yaad rakho meri car Honda hai / kya yaad hai

# Web
open github.com / open example.com / youtube par imran khan songs search karo / google par weather search karo

# Files
Downloads folder kholo / downloads mein resume dhundo / folder banao projects
RANI mujhe Python ka project bana do        (Documents\RANI Projects mein)

# Keyboard
type hello world  (har baar poochti hai)  / copy kar do / paste kar do / show desktop

# Power
Mera laptop lock kar do / laptop sleep kar do
Laptop shutdown kar do   (poochti hai + 30 second ka cancel window)
Laptop restart kar do    /   shutdown cancel
lid close par laptop chalta rakho  /  lid setting restore
```

Jo baat in patterns mein na ho, woh AI ko jati hai. AI sirf *maang* sakta hai — ijazat hamesha RANI ka safe registry deta hai.

---

## 8. Windows start hote hi RANI aur greeting

* `install.bat` mein **Y** dabayein, ya Settings → General → *Start RANI when Windows starts*.
* Login ke baad orb aata hai, RANI audio ready hone ka intezar karti hai (kabhi pehle nahi bolti), phir:
  *"Assalam-o-Alaikum! Kaisa hain Wali? Aapki RANI AI hazir hai. Bataiye, aaj main aapki kya madad kar sakti hoon?"*
* Greeting **har Windows login mein sirf ek dafa** hoti hai. Test ke liye: Settings → **Test greeting**, ya `python -m rani --greet`.
* Greeting ka message / volume / delay Settings → General mein badal sakte hain.

⚠️ Shutdown ke baad RANI nahi chal sakti, aur laptop ka lid band hone par Windows sleep ho jaye to RANI bhi ruk jati hai.

---

## 9. Settings

Orb par **⚙** (ya tray icon par double-click). Tabs: General, Voice, AI Brain, Permissions, Memory, History, Diagnostics.

* **Permissions:** har category (`apps, system, power, files, input, keys, browser, productivity, memory, network`) ko `allow / ask / deny` kar sakte hain.
  Agar settings file mein spelling ghalat likh di jaye to RANI **"ask"** (poochna) maan leti hai — kabhi chupke se "allow" nahi.
* **Memory:** jo RANI ne yaad rakha dekhein / edit / delete karein.
* **History:** har action ka natija (✓ verified / ✗ NOT verified).
* Settings file: `%APPDATA%\RANI\settings.json`.

---

## 10. Security — RANI kya NAHI kar sakti

* **Koi free-form shell / PowerShell command nahi.** Sirf registered actions (`rani/actions.py`, 41 actions) with validated arguments.
* **Shutdown / restart / lid setting / rename / move hamesha poochte hain** — aur sirf **aapka apna "haan/yes"** confirm kar sakta hai (alag message, 30 second ke andar, ek dafa). AI, koi file, ya webpage confirm nahi kar sakta.
* **Files:** sirf Desktop / Documents / Downloads / Pictures / Videos / Music ke andar. In folders ko khud rename/move nahi kiya ja sakta.
* **Programs nahi chalti:** "open path" se `.exe .bat .ps1 .vbs .lnk ...` jaisi files kabhi launch nahi hoti (taake Downloads mein padi koi cheez AI ke zariye na chal jaye).
* **Shutdown ka cancel window kam az kam 10 second** rehta hai (setting ghalat bhi ho to).
* **API keys:** Windows Credential Manager ya `.env` mein — kabhi `settings.json` ya HUD ke JavaScript mein nahi.
* **Memory:** sirf wohi jo aap kahein, ya AI ne propose kiya aur aapne approve kiya.
* **Wake-word mode** audio Google ko bhejta hai; push-to-talk mein mic sirf dabane par khulta hai.

---

## 11. Masle aur unke hal (Troubleshooting)

Pehle hamesha: **`.\doctor.bat`**.

| Masla | Hal |
|---|---|
| `install.bat`: "Python not found" | "Y" dabayein (winget) ya python.org se **Python 3.12** install karein (*Add to PATH* tick karein). Phir install.bat dobara. |
| PyAudio install error | 64-bit Python 3.10–3.13 hona chahiye. Phir: `.\.venv\Scripts\python.exe -m pip install PyAudio` |
| `pip` "No matching distribution" / version error | `.\.venv\Scripts\python.exe -m pip install --upgrade pip` phir `install.bat` dobara |
| Orb nahi aata | `%APPDATA%\RANI\crash.log` dekhein. Console mein chalayein: `.\.venv\Scripts\python.exe -m rani` (error dikhega). Pehle `stop_rani.bat` — shayad pehle se chal rahi ho (tray icon dekhein). |
| Orb ke peeche kala/sufaid box | GPU driver transparency issue: driver update karein; ya `set QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu` phir `start_rani.bat`. |
| Greeting nahi boli | Settings → General mein greeting on? Greeting sirf ek dafa per login hoti hai — Settings → *Test greeting*. Internet check karein. |
| Awaaz English jaisi / Roman Urdu ghalat parhti hai | Urdu voice ko Urdu script chahiye; custom greeting Urdu script mein likhein. |
| Awaaz bilkul nahi | Windows Sound output check karein; `doctor.bat` → "audio output ready"; Settings → Voice → Test Urdu. |
| Microphone nahi mila | Windows Settings → Privacy → Microphone → *Let desktop apps access* ON; default mic set karein. |
| "RANI" wake word nahi pakadta | Speech recognition "Rani/Ranee" sunti hai; shor kam karein ya Ctrl+Alt+Space use karein. |
| Ctrl+Alt+Space kaam nahi karta | Antivirus/`keyboard` package; orb par click ya tray menu → *Talk to RANI*. |
| Brightness fail | Sirf laptop ki internal screen par (external monitor par nahi). History mein detail dekhein. |
| "sleep" par laptop hibernate hota hai | Windows mein hibernate on hai. Admin PowerShell: `powercfg /h off` (Fast Startup band hoga). |
| Lid band karne par laptop ruk jata hai | Normal (Windows sleep). "lid close par laptop chalta rakho" bolein (warning + confirmation ke baad). Bag mein rakhne se pehle "lid setting restore". |
| Shutdown cancel karna hai | 30 second ke andar "shutdown cancel" bolein, ya PowerShell: `shutdown /a` |
| AI "service available nahi" | Settings → AI Brain → key save → **Test AI connection** (har provider ka sabab dikhata hai). Model ka naam badal gaya ho to Settings me naya likhein. Offline ke liye: `python -m rani --setup-ai`. |
| Offline AI (Ollama) install na hua | `.\.venv\Scripts\python.exe -m rani --setup-ai` dobara (internet chahiye). Ya <https://ollama.com/download> se khud install karein, phir yahi command. |
| Offline AI bohat slow | Pehla jawab model load karta hai (kuch second). Chhota model: Settings → *Offline model* → `qwen2.5:1.5b`, phir `--setup-ai`. |
| Antivirus warning | RANI keyboard/mouse input, registry Run key aur global hotkeys use karti hai — kuch antivirus shak karte hain. Poora source `rani/` mein khula hai. |
| Sab reset | `stop_rani.bat`, phir `%APPDATA%\RANI` folder delete. |

---

## 12. Aksar poochay jane wale sawal (FAQ)

**Kya yeh free hai?** RANI free hai. Gemini ki free tier hai (limits ke saath). Edge neural voice free hai.

**Kya internet zaroori hai?** Basic commands offline chalti hain. Neural awaaz, speech recognition aur Gemini ko internet chahiye.
Internet na ho to Windows ki offline awaaz use hoti hai (Urdu accent installed voices par depend karta hai).

**Kya RANI meri baatein record karti hai?** Push-to-talk mein mic sirf dabane par khulta hai. Speech Google Web Speech ko jati hai (recognition ke liye).
Chat log sirf aapke laptop par `%APPDATA%\RANI\rani.db` mein hota hai (purana log khud saaf hota rehta hai).

**RANI ka naam / owner kaise badlein?** `%APPDATA%\RANI\settings.json` mein `owner_name`, `owner_short`.

**Punjabi?** `settings.json` mein `"stt_languages": ["ur-PK", "pa-IN", "en-US"]`.

---

## 13. Developers ke liye

```text
rani/
  app.py          pipeline: intents → safe actions → AI → voice → HUD state
  intents.py      offline parser (English / Roman Urdu / Urdu script)
  actions.py      safe action registry (permissions, confirmation, validation, verification)
  winapi.py       asli Windows calls (volume, brightness, power, keys, windows)
  brain.py        AI providers: Gemini → Grok → Groq → OpenRouter → custom → Ollama, cooldowns, JSON reply parser
  voice.py        edge-tts speaker + speech-recognition listener
  phrases.py      sab bolne wale jumle (Roman Urdu display + Urdu script speech)
  hud_window.py   Qt + WebEngine orb, tray, hotkeys, settings bridge
  hud/            index.html (orb), settings.html
  store.py        SQLite: memory, history, reminders, tasks, chat
  config.py       settings, .env, secrets (keyring)
  doctor.py       installation checks
  localai.py      Ollama: install / start / model download (offline AI)
  tests/          pytest suite + live_windows_check.py
```

**Tests chalana:** `.\run_tests.bat` — pytest suite (`test_core.py`, `test_regressions.py`, `test_hud_qt.py`) aur phir asli Windows ke safe checks.
Linux/Mac par: `pip install -r requirements-dev.txt && python -m pytest rani/tests -q`.

**Naya action jorna:**
1. `rani/actions.py` mein `def h_meri_cheez(ctx, arg): ... return Result(ok, "phrase_key", {...}, verified=...)`
2. `_register_all` mein `R(A("meri_cheez", h_meri_cheez, "category", "AI ke liye description", {"arg": "str"}))`
3. `rani/phrases.py` mein `"phrase_key"` **dono** `ur` aur `en` tables mein (test check karta hai ke koi key missing na ho)
4. Chahein to `rani/intents.py` mein rule jorein, aur `tests/` mein test.

Asool: har action arguments validate kare, asli kaam kare, aur jahan Windows allow kare wahan natija **verify** kare.

---

## 14. Honest status — kya test hua, kya nahi

**Automated tests (119 pass) — logic, kisi bhi OS par:** intent parsing (English / Roman Urdu / Urdu script), permissions, confirmation (expiry, AI confirm nahi kar sakta),
emergency stop, path safety, hotkey/URL allow-lists, provider fallback, settings/secrets, memory/history, greeting once-per-login, phrase tables, poori command pipeline.
Qt HUD tests (`test_hud_qt.py`) tab chalte hain jab PySide6 install ho.

**Asli Windows laptop par aap hi check karein (`run_tests.bat` ya `doctor.bat`):**
pycaw volume, brightness (WMI), lock / sleep / `shutdown`, `powercfg` lid, keyboard typing, window minimize/focus, Start-Menu search,
Microsoft neural voice ka accent, microphone + wake word + hotkeys, reboot ke baad autostart + greeting, transparency aapke GPU par, Gemini/Ollama live.
Yeh sab sandbox mein (Linux, bina network/Windows) chalaye nahi ja sakte the.

---

## 15. Uninstall

```powershell
.\stop_rani.bat
.\.venv\Scripts\python.exe -m rani --autostart off
```
Phir RANI folder delete kar dein (aur chahein to `%APPDATA%\RANI` bhi).

---
*Owner: Wali Hasan · License: `LICENSE`*
