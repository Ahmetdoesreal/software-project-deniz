ScriptCompanion.app

What this is:
- a real macOS .app bundle structure
- a companion app that launches a Python GUI from inside the .app
- it stores its runtime files in:
  ~/Library/Application Support/ScriptCompanion

What it does:
- choose a .py file
- run it through the companion app's launcher
- copy the script's folder into an app-controlled run workspace
- enforce a simple JSON policy
- capture stdout/stderr

Important limits:
- this is not a cryptographic or kernel-level sandbox
- it is an app wrapper and controlled runner
- truly hostile scripts still need a VM, container, or OS sandbox

How to use on a Mac:
1. Copy ScriptCompanion.app to /Applications or your Desktop.
2. If Gatekeeper warns, right-click > Open the first time.
3. If Python 3 is missing, install it from python.org or Homebrew.
4. Open the app and select a Python script.

Because this bundle was assembled outside macOS, it is not code-signed or notarized.
You may need to remove quarantine flags after downloading:
  xattr -dr com.apple.quarantine ScriptCompanion.app
