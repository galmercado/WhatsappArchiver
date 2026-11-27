# Getting started: step by step

Goal: read your own WhatsApp chats in a WhatsApp-looking page that runs **only on your computer**.
Time: about 30–45 minutes the first time. You do **not** need to root your phone.

You will do four things:

1. Install a few free programs on your computer.
2. Try the app with **fake demo chats** (so you know your computer is set up right).
3. Prepare your phone and copy your chats to your computer.
4. Open your real chats.

Words used below: **terminal** = the text window where you type commands. **Archive** = the folder this
tool creates with your chats (encrypted). **Vault passphrase** = a password *you invent* that protects the archive.

---

## Step 1. Install the programs (once)

| Program | Why | Where |
|---|---|---|
| **Python 3.12 or newer** | runs the tool | https://www.python.org/downloads/ (Windows: tick **"Add python.exe to PATH"** on the first screen) |
| **Node.js 22 (LTS)** | builds the web page once | https://nodejs.org |
| **Android Platform-Tools** | lets the computer talk to your phone | https://developer.android.com/tools/releases/platform-tools → download for your system → unzip it somewhere easy, e.g. `C:\platform-tools` (Windows) or `~/platform-tools` (Mac/Linux) |
| **An authenticator app** on your phone | makes the 6-digit login codes | Google Authenticator, Aegis, 2FAS, Microsoft Authenticator... any of them |

**Ubuntu / Debian Linux (including ARM computers such as Raspberry Pi or ARM servers):** do not download
Platform-Tools from Google; that download only contains Intel programs and will not run on ARM. Install everything
from the package manager instead:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip adb
sudo snap install node --classic --channel=22      # Node.js 22 (the apt version is too old)
```

Then use plain `adb` everywhere below and **leave out** `--adb-path` in Step 6.
(Check your computer type with `uname -m`: `aarch64` means ARM.)

## Step 2. Download this project

On the GitHub page of the project: green **Code** button → **Download ZIP** → unzip it. (If you know git:
`git clone https://github.com/galmercado/WhatsappArchiver.git`.)

Open a terminal **inside that folder**:

* **Windows:** open the folder in File Explorer, click the address bar, type `powershell`, press Enter.
* **Mac:** right-click the folder → *New Terminal at Folder*.
* **Linux:** right-click in the folder → *Open in Terminal*.

## Step 3. Set up Python (once)

Windows (PowerShell):

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

(If Windows says scripts are disabled, run `Set-ExecutionPolicy -Scope Process Bypass` and try the second line again.)

Mac / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

You will see `(.venv)` at the start of the line. **Every time you open a new terminal later, run the "Activate" line again.**

## Step 4. Try it with fake chats first (10 minutes)

```bash
python start_local.py --demo
```

What happens:

1. The first time it builds the web page (about a minute).
2. It asks you to **choose a login password** (at least 14 characters). Type it twice. Nothing shows while typing; that is normal.
3. It shows a **QR code**. In your authenticator app choose **Add account → Scan a QR code** and scan it from the
   screen. The app now shows a 6-digit code that changes every 30 seconds. Press Enter in the terminal.
   * QR won't scan? A file `local-auth/authenticator-qr.svg` is created: open it in your browser and scan that instead.
   * No camera? Choose "Enter a setup key" and type the key printed under the QR code (type: time-based).
4. Your browser opens at `http://localhost:8000`.
   * **Sign in:** your login password + the current 6-digit code.
   * **Unlock vault:** type the passphrase printed in the terminal (`correct horse battery staple` for the demo).
5. You should see a WhatsApp-looking app with two fake chats. Click around: search, the photo, the voice note, dark mode (⋮ menu).

When you are done: click **⋮ → Lock vault**, then press **Ctrl+C** in the terminal to stop.

If this worked, your computer is ready. If not, see "Something went wrong" at the bottom.

## Step 5. Prepare your phone (once)

**5a. Turn on USB debugging (Samsung):**
*Settings → About phone → Software information* → tap **Build number** 7 times (enter your PIN) →
go back, open **Developer options** → switch **USB debugging** on.

**5b. Make an encrypted backup with a key you keep.** This is the important part:

1. Open WhatsApp → **⋮ → Settings → Chats → Chat backup → End-to-end encrypted backup → Turn on**.
2. Choose **"Use 64-digit encryption key instead"** → **Continue** → WhatsApp shows a **64-digit key**.
3. **Copy it and save it somewhere safe** (password manager, or write it down). You will paste it in Step 6.
4. Tap **Create**, then tap the green **Back up** button so a fresh backup file is made on the phone *now*.

> **Please note:** this also encrypts your Google Drive chat backup with the same key. **If you lose the key you
> cannot restore chats on a new phone.** You can switch it off later in the same menu.

## Step 6. Copy your chats to the computer

1. Plug the phone into the computer with a USB cable. On the phone choose **File transfer** if asked.
2. A popup **"Allow USB debugging?"** appears on the phone → tick *Always allow* → **Allow**.
3. Test the connection (replace the path with where you unzipped platform-tools; on Ubuntu just type `adb devices`):

   Windows: `C:\platform-tools\adb.exe devices`  Mac/Linux: `~/platform-tools/adb devices`

   You should see one line ending in `device`. If it says `unauthorized`, look at the phone and tap Allow.
4. Run the tool (Windows example; Mac: use `~/platform-tools/adb`; Ubuntu with apt-installed adb: omit `--adb-path` entirely):

   ```powershell
   python extract_and_ingest.py --adb-path "C:\platform-tools\adb.exe" --out archive
   ```

5. It will:
   * Ask you to **invent a vault passphrase** (at least 12 characters; use 20+). Type it twice.
     **Write it down. It cannot be recovered.**
   * Print a big **"DEVICE IS NOT ROOTED"** box. **This is normal and fine**: it means the tool will not touch private
     phone data and will use your key instead.
   * Ask `Choose how to continue`. Type **1** and press Enter.
   * Ask for the **64-digit key**. Paste the key from Step 5b and press Enter (nothing appears while you paste).
6. Wait. Copying photos and videos can take a while. At the end you should see
   `Done: … chats, … messages, … media files. Archive: …`.

Now unplug the phone. A folder named **`archive`** exists next to the project. **That folder is your encrypted chat archive; keep it private.**

**What to expect:** WhatsApp keeps its own contact names and profile pictures in private storage that an unrooted
phone does not let any computer read. The tool therefore gets **names from your phone's address book** and **pictures
from the photos saved on those contacts** (see Step 6b). Only media stored on the phone's shared storage is included.

## Step 6b. Contact names and pictures

The copy in Step 6 already tries to read your **phone's address book** over the same USB connection (no root needed).
It matches every WhatsApp number to a saved contact, so chats show **names** instead of numbers, and it copies the **photo
saved on that contact** as the chat picture. Check the Step 6 output for a line like
`Contacts: added 212 names and 87 pictures`.

**Already copied everything and the names are missing? Don't copy again.** Add them to the existing archive:

```bash
python enrich_contacts.py --archive archive --adb-path "C:\platform-tools\adb.exe"
```
(Ubuntu with apt `adb`: leave out `--adb-path`.) It asks for your **vault passphrase** and takes a minute.
You can run it again any time, for example after adding contacts on the phone.

**If the phone refuses to share the address book** (you will see a message about `.vcf`), export it by hand:
*Contacts app → ☰ menu → Manage contacts → Import or export contacts → Export → Internal storage*. Copy the `.vcf`
file to your computer (USB file transfer), then:

```bash
python enrich_contacts.py --archive archive --no-phonebook --vcf /path/to/contacts.vcf
```
A `.vcf` export includes contact photos too.

**Your own pictures:** put images in a folder, named by the phone number with country code (no `+`), for example
`972501234567.jpg`, `15551234567.png`, then add `--avatars /path/to/folder` to either command above.

**Honest limits:** these are the pictures *you saved on your contacts*, not the profile pictures people set in
WhatsApp (those are private to the WhatsApp app). Group icons are not available either; groups keep the default group icon.
Numbers that are not in your address book stay as numbers.

## Step 7. Open your real chats

```bash
python start_local.py
```

Sign in (login password + 6-digit code) → unlock with your **vault passphrase** → enjoy.
Use **⋮ → Lock vault** when done, then **Ctrl+C**.

## Everyday use

* Start: open a terminal in the folder → run the **Activate** line (Step 3) → `python start_local.py`.
* The app is only reachable from this computer (`localhost`). Nothing is uploaded anywhere.
* Back up the `archive` folder to an encrypted drive. Without your vault passphrase it is unreadable, and that is the point.
* Putting it on a server so you can read it from your phone anywhere is optional and covered in `docs/DEPLOYMENT.md`. Do the local steps first.

## Something went wrong

| What you see | What to do |
|---|---|
| `python` / `pip` not found | Reinstall Python and tick "Add to PATH"; open a **new** terminal. On Mac/Linux use `python3`. |
| `npm` not found / "Node.js is not installed" | Install Node.js 22 (Step 1), open a **new** terminal, run again. |
| `adb not found` | Add `--adb-path "<full path to adb>"` exactly as in Step 6. |
| `No matching distribution found for sqlcipher3…` | Update pip first: `python3 -m pip install --upgrade pip`, then `pip install -e .` again. If it still fails, run `uname -m && python3 --version && pip --version` and send me the output. |
| `no Android device found` | Cable/port, screen unlocked, USB mode *File transfer*, USB debugging on (Step 5a). |
| `adb devices` shows an empty list | (1) On the phone pull down the notification "Charging this device via USB" → tap it → choose **File transfer**. (2) Samsung **Auto Blocker** blocks USB commands: *Settings → Security and privacy → Auto Blocker → off*. (3) Developer options → **Revoke USB debugging authorizations**, switch USB debugging off and on, unplug and replug, tap **Allow**. (4) Try another cable (many are charge-only) and a different USB port. (5) Linux: `adb kill-server && adb start-server && adb devices`. (6) Still empty: use wireless debugging, see below. |
| `device is unauthorized` | Unlock the phone and tap **Allow** on the "USB debugging" popup. |
| `No WhatsApp data found` or "no database found" | Do Step 5b again and press **Back up**; then retry. |
| `decryption failed: wrong key, corrupt file or unsupported format` | Re-check the 64 digits (no spaces/typos). If it is still wrong, the backup format may differ from what the tool expects: copy the error text and send it to me (do **not** send the backup file or the key). |
| `Port 8000 is already in use` | Add `--port 8001` to `python start_local.py`. |
| Sign-in says "Invalid credentials" | Use the **current** code (it changes every 30 s); check the computer's clock is correct; wait 30 s between tries (too many tries make it wait longer). |
| "Unlock" says it did not unlock | That is the **vault passphrase** from Step 6, not the login password. |
| Chats still show numbers instead of names | Run `python enrich_contacts.py --archive archive ...` (Step 6b). If it says the phone did not share the address book, use the `.vcf` export. A name only appears when the number in your address book matches the WhatsApp number. |
| `Nothing to add: no contact source was readable` | The phone was not found or refused; add `--vcf FILE` or `--avatars FOLDER`, or fix the USB connection first. |
| Forgot the vault passphrase | It cannot be recovered. Delete the `archive` folder and redo Step 6 with a new one. |

To start completely over: delete the `archive` folder and the `local-auth` folder.

## Phone not showing up in `adb devices`: wireless fallback (Android 11+, no cable needed)

1. Put the phone and the computer on the **same Wi-Fi**.
2. Phone: *Settings → Developer options → Wireless debugging → on* → tap **Pair device with pairing code**. It shows an address like `192.168.1.20:37099` and a 6-digit code.
3. Computer: `adb pair 192.168.1.20:37099` and type the 6-digit code.
4. Back on the *Wireless debugging* screen note the **IP address & Port** (a different port, e.g. `192.168.1.20:41555`), then: `adb connect 192.168.1.20:41555`
5. `adb devices` should now list `192.168.1.20:41555  device`. Continue with Step 6 as normal
   (if several devices are listed, add `--serial 192.168.1.20:41555` to the `extract_and_ingest.py` command).
