# local-llm-router

> Carry your LLMs on a USB drive. Let a 0.8B model decide which big model answers.

A fully local inference stack built on [Ollama](https://ollama.com):

- a **0.8B classifier** scores every prompt and routes it to a specialist model
- **conversation memory** is replayed to the model, with a configurable depth
- the model weights can live on an **external drive**, not your laptop SSD
- every answer ships with **token counts, load time and tok/s**

No API keys. No cloud.

---

## Why

Two problems, one project.

**1. Models are enormous and your SSD is not.** My Ollama model store hit **75 GB**.
Ollama can read its store from an external drive instead — though the setup has two
traps that make most attempts silently fail. The full writeup is in
[`docs/ollama-external-drive-macos.md`](docs/ollama-external-drive-macos.md).

**2. One model for everything is the wrong default.** A model that writes good prose
is usually not the one you want debugging a segfault. Rather than making the human
pick from a dropdown every time, a very small model picks for them.

---

## How it works

```
                  ┌──────────────────────────┐
   your prompt ──▶│  tev1:0.8b  (classifier) │
                  │  System One scoring      │
                  └───────────┬──────────────┘
                              │ noul scores
                 ┌────────────┼────────────┐
                 ▼            ▼            ▼
              coding      research       writing
            nemotron-     qwen3.8       gpt-oss-
            3.5-bolt:e4b  :latest       safeguard
                 └────────────┼────────────┘
                              │ + replayed conversation history
                              ▼
                   streamed answer + telemetry
```

### 1. The decision model

Routing uses Ollama's **System One** scoring API (`ollama.systemone`), not a chat
model prompted to "reply with one word". That distinction matters:

- it returns **structured scores**, not free text you have to parse
- there is no instruction-following failure mode — the model cannot decide to be chatty
- scoring is cheap enough that a 0.8B model is plenty, so the routing hop is near-free

Each route is a `noul` question with explicit true/false criteria:

```python
CLASSIFIER_QUESTIONS = {
    "coding": {
        "type": "noul",
        "instructions": (
            "Determine whether the user's PRIMARY goal is to implement, modify, "
            "debug, review, or understand software or code. Classify based on "
            "the main deliverable, not merely the presence of technical terms."
        ),
        "criteria": {
            "true":  "The main deliverable is working code, a bug fix, a script ...",
            "false": "The main deliverable is an article, report, or comparison. "
                     "Code is only illustrative or incidental.",
        },
    },
    # research, writing ...
}
```

All questions are scored; the highest wins:

```python
scores = {name: answer.noul for name, answer in response.answers.items()}
route = max(scores, key=scores.get)
```

The word **PRIMARY** is load-bearing. An earlier version routed *"write me a blog post
about Python decorators"* to **coding**, because it saw the word Python. The fix wasn't
a bigger model — it was saying "classify on the main deliverable, not the presence of
technical terms", and writing a `false` branch that names the confusable case instead of
just negating the `true` branch.

### 2. Memory

Conversation history is held in `st.session_state` and replayed to the model on each
request, trimmed to the last N turns:

```python
def build_messages(history, prompt, prompt_suffix, memory_turns):
    recalled = []
    if memory_turns > 0:
        for msg in history[-(memory_turns * 2):]:
            recalled.append({"role": msg["role"], "content": msg["content"]})
    return recalled + [{"role": "user", "content": prompt + prompt_suffix}]
```

Only `role` and `content` go upstream — the decision and metadata stored alongside each
message are UI state and would only waste context. The depth is a sidebar slider
(default 6 turns, 0 = stateless), and the resulting `messages_recalled` count shows up
in the Decision panel so you can see exactly what the model was given.

Note that **classification always runs on the current prompt alone**. Routing a follow-up
on the strength of three turns ago tends to pin the conversation to its first topic.

### 3. Telemetry

Every response surfaces what Ollama reports back:

| Metric | Source |
|---|---|
| Prompt tokens | `prompt_eval_count` |
| Output tokens | `eval_count` |
| Load time | `load_duration` — **this is where a slow USB drive shows up** |
| Prompt eval / generation speed | derived tok/s |
| Total wall clock | measured client-side |

`load_duration` is the number to watch on external storage. Cold-loading weights off
USB is slow; once the model is resident in RAM, generation speed is unaffected because
the disk is no longer in the loop.

---

## Running models from an external drive

**Short version: `export OLLAMA_MODELS=...` does not work with the Ollama desktop app.**

The app stores the model path in its own SQLite database and injects it into the server
on every launch, overwriting whatever you set in the environment. `launchctl setenv`
doesn't help either. You'll see `launchctl getenv` report your path while the server log
reports the old one.

The two things that actually work:

1. the **model location picker in the app's Settings UI**, or
2. updating the app's settings DB directly:

```bash
osascript -e 'tell application "Ollama" to quit'; sleep 3; pkill -f "Ollama.app"
sqlite3 "$HOME/Library/Application Support/Ollama/db.sqlite" \
  "UPDATE settings SET models='/Volumes/YOUR-DRIVE/ollama-models';"
open -a Ollama
```

Also: **do not use a FAT32 drive.** Ollama stores each model as a single blob file, and
FAT32 caps files at 4 GB, so any model above that cannot be written at all. Use APFS
(Mac only) or exFAT (cross-platform).

The CLI (`ollama serve` run by hand) *does* respect `OLLAMA_MODELS` — the conflict is
specific to the desktop app, which manages the server process itself.

Full guide, including reformatting, verification steps, write-speed benchmarking and a
troubleshooting table: **[`docs/ollama-external-drive-macos.md`](docs/ollama-external-drive-macos.md)**

### Expected performance

| Drive type | Typical write | Time to pull a 13 GB model |
|---|---|---|
| USB 2.0 flash drive | ~12 MB/s | ~18 min |
| USB 3.0 flash drive | ~100 MB/s | ~2 min |
| External NVMe SSD | ~800+ MB/s | ~20 s |
| Internal Apple SSD | several GB/s | seconds |

A cheap flash drive is fine for models you run occasionally or carry between machines.
For daily use, an external SSD is worth it.

---

## Setup

```bash
git clone https://github.com/Raghul-M/local-llm-router.git
cd local-llm-router

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Pull the classifier and the three route models:

```bash
ollama pull tev1:0.8b                # the router
ollama pull nemotron-3.5-bolt:e4b    # coding
ollama pull qwen3.8:latest           # research
ollama pull gpt-oss-safeguard:latest # writing
```

Run it:

```bash
streamlit run app.py
```

### Models

| Route | Model | Why |
|---|---|---|
| *(classifier)* | `tev1:0.8b` | Small enough that the routing hop is near-free. It only scores — it never generates. |
| Coding | `nemotron-3.5-bolt:e4b` | Fast on code, and small enough to stay resident in RAM between questions. |
| Research | `qwen3.8:latest` | Handles longer reasoning chains and multi-part questions well. |
| Writing | `gpt-oss-safeguard:latest` | Produces the most usable long-form prose of the three. |

These are the tags in `ROUTE_DEFAULTS`, but nothing is locked to them. The sidebar lists
every model Ollama can see, so you can reassign any route at runtime and compare.

`main.py` is a minimal terminal version if you'd rather read the routing logic without a
UI around it. It hardcodes the same four tags.

---

## Current limitations

- **Routing is winner-takes-all.** No confidence floor, no fallback route when every
  score is low. A prompt that fits nothing still gets routed somewhere.
- **Classification doesn't stream.** System One returns one JSON response, so there's a
  short pause before the route is announced.
- **Memory is per-session.** Closing the Streamlit tab loses the conversation; nothing
  is persisted to disk.
- **Route prompt suffixes are blunt.** The research and writing routes append a fixed
  instruction to every prompt, including follow-ups where it doesn't fit.

---

## Stack

- [Ollama](https://ollama.com) — local inference + System One scoring
- [Streamlit](https://streamlit.io) — UI
- Python 3.11+

Tested on macOS 27 (Apple Silicon), Ollama 0.40.10.

## License

Apache 2.0 — see [LICENSE](LICENSE).
