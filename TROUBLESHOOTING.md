# RANI AI — Troubleshooting

Pehle hamesha: `.\doctor.bat` (report `doctor_report.txt` mein bhi save hoti hai).

| Masla | Wajah / hal |
|---|---|
| `install.bat`: "Python not found" | "Y" dabayein (winget), ya python.org se **Python 3.12** install karein (*Add to PATH* tick). Python 3.14 abhi support nahi — 3.10–3.13 use karein. |
| `pip` PyAudio error | Python 3.10–3.13 + 64-bit hona chahiye. Phir: `.\.venv\Scripts\python.exe -m pip install PyAudio`. |
| Orb nahi aata | `%APPDATA%\RANI\crash.log` dekhein. `.\.venv\Scripts\python.exe -m rani` (console mein error dikhega). Pehle `stop_rani.bat` chalayein (shayad pehle se chal rahi ho — tray icon dekhein). |
| Orb dikhta hai lekin background kala/sufaid box hai | GPU driver transparency issue. Settings mein compact mode try karein; NVIDIA driver update karein; phir bhi ho to batayein (hum software rendering flag add kar denge: `set QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu`). |
| Greeting nahi boli | Settings → General → greeting on? Greeting sirf ek dafa per login hoti hai — test ke liye Settings mein **Test greeting**, ya `python -m rani --greet`. Internet check (neural voice). `doctor.bat` mein "voice ur-PK-UzmaNeural" dekhein. |
| Awaaz English jaisi / Roman Urdu ghalat parhti hai | Urdu voice ko Urdu script chahiye; RANI ke apne jumle sahi hain. Custom greeting Urdu script mein likhein. |
| Awaaz bilkul nahi | Windows Sound output theek? `doctor.bat` → "audio output ready". Settings → Voice → Test Urdu. Offline fallback ke liye `pyttsx3` installed hona chahiye. |
| Microphone nahi mila | Windows Settings → Privacy → Microphone → "Let desktop apps access" ON. Default mic set karein. `doctor.bat` → microphone. |
| "RANI" wake word nahi pakarta | Speech recognition cloud par hoti hai aur "RANI" ko "Rani/Ranee" sunti hai; Settings → Listening mode = Wake. Shor kam karein, ya Ctrl+Alt+Space use karein. Wake mode mein RANI jab khud bol rahi ho tab nahi sunti. |
| Ctrl+Alt+Space kaam nahi karta | `keyboard` package/anti-virus. Orb par click ya tray menu → *Talk to RANI* use karein. |
| Volume/brightness command fail | Brightness sirf laptop ki internal screen par (external monitor par nahi). History mein "NOT verified" detail dekhein. |
| "sleep" karne par laptop hibernate hota hai | Windows mein hibernate on hai. Admin PowerShell: `powercfg /h off` (Fast Startup band hoga). Ya `powercfg /a` se dekhein sleep available hai. |
| Lid band karne par RANI/laptop ruk jata hai | Normal hai: Windows sleep. "lid close par laptop chalta rakho" bolein (warning + confirmation ke baad). Garmi ka khayal rakhein, bag mein rakhne se pehle "lid setting restore". |
| Shutdown cancel karna hai | 30 second ke andar "shutdown cancel" bolein ya PowerShell: `shutdown /a` |
| AI "service available nahi" | Settings → AI Brain → key save karein → **Test AI connection**. Gemini model ka naam badal chuka ho sakta hai — Gemini model field mein current naam likhein. Ollama chal raha ho (`ollama serve`) aur model pull ho. |
| Antivirus warning | RANI keyboard/mouse (SendInput), registry Run key aur `keyboard` hotkeys use karti hai — kuch antivirus ise shak se dekhte hain. Source `rani/` mein khula hai. |
| Sab reset karna hai | `stop_rani.bat`, phir `%APPDATA%\RANI` folder delete. |
