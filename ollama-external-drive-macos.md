# Running Ollama models from an external USB drive on macOS

Tested on macOS 27 (Darwin 27.0.0), Apple Silicon (M3 Pro), **Ollama 0.40.10** desktop app.

Moving Ollama's model storage to an external drive looks like a one-line env var change. It isn't. There are two traps, and the second one is the reason most attempts silently fail.

---

## TL;DR — the two traps

| Trap | Symptom | Fix |
|---|---|---|
| Drive is **FAT32** (4 GB max file size) | `ollama pull` dies partway on any model over 4 GB | Reformat to APFS or exFAT |
| Ollama desktop app **ignores `OLLAMA_MODELS`** | `launchctl getenv` shows your path, but the server logs the old one | Update the app's SQLite settings DB |

If you only take one thing from this: **setting `OLLAMA_MODELS` does not work with the Ollama desktop app.** It stores the path in its own database and injects it into the server on every launch, overwriting whatever you set.

---

## Variables used below

```bash
DRIVE_NAME="RAGHUL-DRIV"                              # your volume label
MODELS_DIR="/Volumes/${DRIVE_NAME}/ollama-models"     # where models will live
OLLAMA_DB="$HOME/Library/Application Support/Ollama/db.sqlite"
```

---

## Step 1 — Check the drive's filesystem

Ollama stores each model as a **single blob file**. A 13 GB model is one 13 GB file. FAT32 caps files at 4 GB, so most models cannot be written at all.

```bash
diskutil info "/Volumes/${DRIVE_NAME}" | grep -E "File System Personality|Free Space"
```

If it says `MS-DOS FAT32`, you must reformat. Check what your models actually weigh:

```bash
find ~/.ollama/models/blobs -type f -size +3G -exec ls -lh {} \; \
  | awk '{print $5, $9}' | sort -rh | head
```

---

## Step 2 — Identify the disk (do this carefully)

```bash
diskutil list
```

Confirm the target is external and removable before erasing anything:

```bash
diskutil info disk4 | grep -E "Device Location|Removable|Media Name|Disk Size"
```

Expected output for a USB stick:

```
Device / Media Name:  Cruzer Blade
Disk Size:            30.8 GB
Device Location:      External
Removable Media:      Removable
```

> ⚠️ **Verify the disk number every time.** Disk identifiers are assigned at
> connection time and change between reboots and replugs. Erasing the wrong
> disk is unrecoverable. Internal disks are typically `disk0`/`disk3`.

---

## Step 3 — Quit Ollama completely

Not just the menu-bar window — the whole app, including the `ollama serve` subprocess.

```bash
osascript -e 'tell application "Ollama" to quit'
sleep 3
pkill -f "Ollama.app"

# confirm nothing is left
pgrep -lf "Ollama.app|ollama serve"
```

---

## Step 4 — Reformat the drive

**This erases the entire drive.** Back up anything on it first.

```bash
# APFS — Mac only, full POSIX permissions (recommended for Mac-only use)
diskutil eraseDisk APFS "${DRIVE_NAME}" /dev/disk4

# exFAT — use this instead if you also need the drive on Windows
# diskutil eraseDisk ExFAT "${DRIVE_NAME}" /dev/disk4
```

Verify — and note the device identifier changes after formatting (APFS creates a synthesized container, e.g. `disk4` → `disk5s1`):

```bash
diskutil info "/Volumes/${DRIVE_NAME}" | grep -E "File System Personality|Free Space"
```

Confirm the 4 GB limit is actually gone by writing a 5 GB file:

```bash
dd if=/dev/zero of="/Volumes/${DRIVE_NAME}/.sizetest" bs=1m count=5120
ls -lh "/Volumes/${DRIVE_NAME}/.sizetest"
rm "/Volumes/${DRIVE_NAME}/.sizetest"
```

This doubles as a **write-speed benchmark** — read the `bytes/sec` figure `dd` prints. See [Performance](#performance-reality-check) below.

---

## Step 5 — Create the models directory

```bash
mkdir -p "${MODELS_DIR}"
```

Ollama will populate it with `blobs/`, `manifests/` and `manifests-v2/` on next launch.

---

## Step 6 — Point Ollama at the drive (the part that actually matters)

### ❌ What does NOT work

```bash
# All of these are ignored by the Ollama desktop app:
export OLLAMA_MODELS="${MODELS_DIR}"            # shell only, app never sees it
launchctl setenv OLLAMA_MODELS "${MODELS_DIR}"  # app overrides it on launch
```

A LaunchAgent that calls `launchctl setenv` at login is **also pointless** for the same reason. Don't bother creating one.

The giveaway that you've hit this trap:

```bash
launchctl getenv OLLAMA_MODELS
# /Volumes/RAGHUL-DRIV/ollama-models        <- looks right

grep -o "OLLAMA_MODELS:[^ ]*" ~/.ollama/logs/server.log
# OLLAMA_MODELS:/Users/you/.ollama/models   <- but the server disagrees
```

The app spawns `ollama serve` with an explicitly injected environment, so its stored value always wins.

### ✅ What does work

The path lives in the `models` column of the `settings` table in the app's SQLite database.

Inspect the current value:

```bash
sqlite3 "file:${OLLAMA_DB}?immutable=1" "SELECT models FROM settings;"
```

Back up the database, then update it (**with Ollama fully quit** — see Step 3):

```bash
cp "${OLLAMA_DB}" "/tmp/ollama-db-backup-$(date +%s).sqlite"

sqlite3 "${OLLAMA_DB}" "UPDATE settings SET models='${MODELS_DIR}';"
```

> The app's **Settings UI** has a model-location picker that does exactly the
> same thing. Use it if you prefer clicking — the point of this section is that
> the *environment variable* is the wrong lever, not that you must use SQL.

---

## Step 7 — Relaunch and verify

```bash
open -a Ollama
sleep 10

# 1. The server must now report the drive path
grep -o "OLLAMA_MODELS:[^ ]*" ~/.ollama/logs/server.log
# OLLAMA_MODELS:/Volumes/RAGHUL-DRIV/ollama-models

# 2. Ollama created its storage tree on the drive
ls -la "${MODELS_DIR}"
# blobs/  manifests/  manifests-v2/

# 3. Model list is empty (fresh drive)
ollama list
```

End-to-end test with a small model:

```bash
ollama pull tev1:0.8b
du -sh "${MODELS_DIR}"
ollama list
```

---

## Switching back to internal storage

Your old models are **not deleted** — they stay at `~/.ollama/models` and simply
become invisible while Ollama points elsewhere.

```bash
osascript -e 'tell application "Ollama" to quit'; sleep 3; pkill -f "Ollama.app"

sqlite3 "${OLLAMA_DB}" "UPDATE settings SET models='$HOME/.ollama/models';"

open -a Ollama
```

---

## Performance reality check

Measure before you commit to this setup:

| Drive type | Typical write | Time to pull a 13 GB model |
|---|---|---|
| USB 2.0 flash drive | ~12 MB/s | ~18 min |
| USB 3.0 flash drive | ~100 MB/s | ~2 min |
| External NVMe SSD | ~800+ MB/s | ~20 s |
| Internal Apple SSD | several GB/s | seconds |

The reference drive here (SanDisk Cruzer Blade, 30 GB) benchmarked at
**12.2 MB/s** — USB 2.0. It works correctly, but cold-loading a large model
into RAM is slow every single time.

**Practical guidance:** a cheap flash drive is fine for models you run
occasionally or want to carry between machines. For anything you use daily,
an external SSD is worth it, and the internal disk is better still.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ollama list` is empty | Drive unplugged, or path changed | Replug the drive; this is expected, not data loss |
| Pull fails partway on big models | Still FAT32 | Reformat (Step 4) |
| Server logs the old path after relaunch | App overrode the env var | Update the SQLite setting (Step 6) |
| Setting reverts after you change it | App was running during the `UPDATE` | Quit fully (Step 3), then re-apply |
| `database is locked` | App holds the DB open | Quit Ollama first |
| Models load very slowly | Slow USB bus | Benchmark with `dd`; consider an SSD |

### Capacity

Check that your models actually fit before copying anything:

```bash
du -sh ~/.ollama/models              # what you have
df -h "/Volumes/${DRIVE_NAME}"       # what the drive holds
```

---

## Notes

- Ollama's CLI (`ollama serve` run manually from a terminal) **does** respect
  `OLLAMA_MODELS`. The conflict described here is specific to the **desktop app**,
  which manages the server process itself.
- External volumes mount with `noowners` on macOS, so files appear owned by the
  current user. This is harmless for Ollama and means no `sudo` is needed.
- Behaviour confirmed on Ollama 0.40.10. The app's settings schema may change in
  future releases — check with the `PRAGMA table_info(settings);` query if the
  `models` column has moved.
