# Releasing Aurantium (with WinSparkle auto-updates)

Aurantium ships updates through [WinSparkle](https://winsparkle.org/). On launch
the app checks an **appcast** feed once a day; when a newer, correctly-signed
installer is available it offers to download and run it. Users click once — no
manual re-install.

This doc has two parts: **one-time setup** (do once), and the **per-release
checklist** (every version).

---

## One-time setup

### 1. Create the public GitHub repo

WinSparkle downloads the appcast and installer over plain HTTPS with **no
authentication**, so both must live in a **public** repo.

```bash
cd app            # the folder that holds aurantium/, installer.iss, appcast.xml
git init
git add .
git commit -m "aurantium 1.0.0"
gh repo create aurantium --public --source=. --push
```

### 2. Point the app at your feed

In `aurantium/updater.py`, set your GitHub username:

```python
GITHUB_USER = "your-actual-username"   # was "YOUR_GITHUB_USERNAME"
```

`APPCAST_URL` is derived from it and expects `appcast.xml` at the **repo root**
on the `main` branch. If you keep `appcast.xml` in a subfolder, adjust the URL.

### 3. Install the signing dependency

```bash
.venv/Scripts/python -m pip install -r requirements-dev.txt   # adds cryptography
```

### 4. Generate the signing key (once, ever)

```bash
.venv/Scripts/python tools/gen_keys.py
```

- Writes the **private** key to `tools/eddsa_private.key` — **keep it secret,
  back it up.** It's gitignored. If you lose it, existing users can no longer
  verify updates and you'd have to ship a new public key in a fresh installer.
- Prints the **public** key. Paste the printed line into `aurantium/updater.py`:

  ```python
  EDDSA_PUBLIC_KEY = "…printed value…"
  ```

### 5. Add WinSparkle.dll to the build

Download the latest WinSparkle release zip from
<https://github.com/vslavik/winsparkle/releases>, and copy the **64-bit** DLL
(`x64/WinSparkle.dll` in the zip) to `app/WinSparkle.dll` (next to
`aurantium.spec`). `aurantium.spec` bundles it automatically; it's what
`updater.py` loads at runtime.

> The updater stays fully disabled until `GITHUB_USER` **and**
> `EDDSA_PUBLIC_KEY` are set and the DLL is present — so a half-configured
> build simply runs without updates instead of misbehaving.

> **macOS needs none of this step.** There's no WinSparkle.dll equivalent to
> download — `aurantium/updater_mac.py` is pure Python and reads the exact
> same `GITHUB_USER` / `EDDSA_PUBLIC_KEY` set above. It just needs `<item>`s
> in `appcast.xml` tagged `sparkle:os="macos"` — see the per-release checklist.

---

## Per-release checklist

Say you're going from 1.0.0 → **1.1.0**.

### 1. Bump the version (two files, keep in sync)

- `aurantium/__init__.py` → `__version__ = "1.1.0"`
- `installer.iss` → `AppVersion=1.1.0`

WinSparkle compares `__version__` against the appcast's `sparkle:version`.

### 2. Build the exe and installer

Follow `BUILD.md`:

```bash
.venv/Scripts/pyinstaller aurantium.spec --noconfirm     # -> dist/aurantium.exe
# then compile installer.iss with Inno Setup            -> dist/aurantium-setup.exe
```

### 3. Sign the installer

```bash
.venv/Scripts/python tools/sign_update.py dist/aurantium-setup.exe
```

Note the printed `length:` and `sparkle:edSignature="…"`.

### 4. Update `appcast.xml`

Add a **new `<item>` at the top** (keep older ones for history):

```xml
<item>
  <title>aurantium 1.1.0</title>
  <description><![CDATA[ <ul><li>What changed…</li></ul> ]]></description>
  <pubDate>Fri, 01 Aug 2026 12:00:00 +0000</pubDate>
  <enclosure
    url="https://github.com/your-username/aurantium/releases/download/v1.1.0/aurantium-setup.exe"
    sparkle:version="1.1.0"
    sparkle:os="windows"
    sparkle:installerArguments="/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /FORCECLOSEAPPLICATIONS"
    length="PASTE_LENGTH"
    sparkle:edSignature="PASTE_SIGNATURE"
    type="application/octet-stream" />
</item>
```

- `sparkle:version` must equal `__version__`.
- `url` must match the release tag you create in the next step.
- `pubDate` in RFC-822 (e.g. `date -R`).
- **`sparkle:installerArguments` is required** — it makes WinSparkle run the
  Inno installer silently instead of showing the full setup wizard. `/VERYSILENT`
  hides the UI; `/FORCECLOSEAPPLICATIONS` closes a running Aurantium so its files
  can be replaced. Omit it and every update pops the full wizard.
- **Relaunch** is handled by the installer, not the appcast (WinSparkle does not
  relaunch the app itself, and `/RESTARTAPPLICATIONS` is unreliable). Silent
  auto-updates relaunch from `installer.iss`'s `[Code]` `CurStepChanged` handler,
  which does `Sleep(6000)` then `Exec({app}\aurantium.exe)`. **The delay is
  required:** launched the instant the update finishes, the freshly-written numpy
  C-extension DLLs aren't in place yet and the app crashes with "Importing the
  numpy C-extensions failed" — a slightly later launch works. Interactive installs
  relaunch via the `[Run] … postinstall skipifsilent` entry (no delay needed;
  the Finished page already gives time). Don't add `/RESTARTAPPLICATIONS`.

### 4b. macOS: add its own appcast item (skip if not shipping a Mac build)

Build on an actual Mac (`BUILD.md` § 1b) — you can't cross-build. Then:

```bash
cd dist && zip -r aurantium-mac.zip aurantium.app && cd ..
.venv/bin/python tools/sign_update.py dist/aurantium-mac.zip
```

`tools/sign_update.py` signs raw file bytes — it's not WinSparkle-specific, so
the exact same script and the exact same `tools/eddsa_private.key` work for
both platforms. `updater_mac.py` expects the zip's **top level** to contain
`aurantium.app` (that's what `zip -r … aurantium.app` from inside `dist/`
produces).

Add a **second `<item>`** to `appcast.xml` (alongside, not replacing, the
Windows one — `updater.py`/`updater_mac.py` each only look at the item whose
`sparkle:os` matches their own platform):

```xml
<item>
  <title>aurantium 1.1.0</title>
  <description><![CDATA[ <ul><li>What changed…</li></ul> ]]></description>
  <pubDate>Fri, 01 Aug 2026 12:00:00 +0000</pubDate>
  <enclosure
    url="https://github.com/your-username/aurantium/releases/download/v1.1.0/aurantium-mac.zip"
    sparkle:version="1.1.0"
    sparkle:os="macos"
    length="PASTE_LENGTH"
    sparkle:edSignature="PASTE_SIGNATURE"
    type="application/zip" />
</item>
```

No `sparkle:installerArguments` — there's no installer to run silently.
`updater_mac.py` downloads the zip itself, re-verifies the signature
independently (never trusts the appcast alone), extracts it, and swaps the
running `.app` for the new one via a detached helper that only touches disk
after the app has fully quit. Include the mac asset in the same GitHub
release as the Windows one (next step) so one release, one `gh release
create`, ships both.

### 5. Publish the GitHub release

```bash
gh release create v1.1.0 dist/aurantium-setup.exe dist/aurantium-mac.zip \
  --title "aurantium 1.1.0" --notes "…"
```

(Drop `dist/aurantium-mac.zip` from the command if you're not shipping a Mac
build this round.)

### 6. Push the updated appcast

```bash
git add appcast.xml aurantium/__init__.py installer.iss
git commit -m "aurantium 1.1.0"
git push
```

### 7. Verify

On a machine running the **previous** version, launch Aurantium and pick
**Help ▸ Check for Updates…**. It should find 1.1.0, verify the signature, and
offer to install. (A signature/URL/length mismatch shows a download or
verification error instead — fix the appcast and retry.)

---

## Notes

- **Only the download side must be public.** EdDSA signing — not repo privacy —
  is what keeps updates safe: a tampered installer fails verification and won't
  run.
- **Never regenerate the key** unless you must; it breaks the update path for
  everyone on an older build (they can't verify the new key), forcing a manual
  re-install — on **both** platforms, since Windows and macOS share one key
  pair and one `appcast.xml`.
- **macOS** doesn't use WinSparkle — see `updater_mac.py` and step 4b above.
  Its swap-and-relaunch has only been reasoned through, not run on real
  hardware yet; the first macOS release is also the first real test of it.
  Verify it end-to-end (step 7, on a Mac) before trusting it for others.
