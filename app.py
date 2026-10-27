"""Simple Streamlit UI for the Ollama agent router."""

from __future__ import annotations

import time
from typing import Any, Iterator

import ollama
import streamlit as st
from ollama import chat

DEFAULT_CLASSIFIER_MODEL = "tev1:0.8b"

# How many past turns (1 turn = 1 user + 1 assistant message) to replay to the
# model. 0 makes every request stateless.
DEFAULT_MEMORY_TURNS = 6
MAX_MEMORY_TURNS = 20

ROUTE_DEFAULTS = {
    "coding": {
        "model": "nemotron-mini:4b",
        "prompt_suffix": "",
        "label": "Coding",
    },
    "research": {
        "model": "granite3-dense:latest",
        "prompt_suffix": " Please provide a detailed research plan and a list of sources to be used.",
        "label": "Research",
    },
    "writing": {
        "model": "lfm2.5-thinking:latest",
        "prompt_suffix": " Please provide a detailed writing plan and a list of sources to be used.",
        "label": "Writing",
    },
}


CLASSIFIER_QUESTIONS = {
    "coding": {
        "type": "noul",
        "instructions": (
            "Determine whether the user's PRIMARY goal is to implement, modify, "
            "debug, review, or understand software or code. Classify based on "
            "the main deliverable, not merely the presence of technical terms. "
            "A request for an article, report, comparison, or proposal that "
            "contains illustrative code is NOT primarily coding unless building "
            "or validating a working implementation is the main goal. "
            "For mixed requests, choose coding only when producing or changing "
            "working software is the central outcome."
        ),
        "criteria": {
            "true": (
                "The main deliverable is working code, a software implementation, "
                "a bug fix, a code review, a script, or a technical solution "
                "that requires implementing or modifying software."
            ),
            "false": (
                "The main deliverable is an article, report, research evaluation, "
                "comparison, proposal, explanation, or other text. Code is only "
                "illustrative or incidental, and implementing working software "
                "is not the central goal."
            ),
        },
    },
    "research": {
        "type": "noul",
        "instructions": (
            "Determine whether the user's PRIMARY goal is to investigate a "
            "question and reach an evidence-based conclusion. Research involves "
            "gathering or evaluating sources, comparing alternatives, analyzing "
            "evidence, or interpreting data. A request to write an article or "
            "implement software may mention research without research being "
            "the main deliverable. For mixed requests, prioritize research "
            "only when the main outcome is an evidence-based evaluation or finding."
        ),
        "criteria": {
            "true": (
                "The main deliverable is an evidence-based investigation, "
                "technology evaluation, literature review, comparison supported "
                "by sources, data analysis, or findings with a justified conclusion."
            ),
            "false": (
                "The main deliverable is working software, a polished article, "
                "an edited document, or another outcome where investigation "
                "is only a supporting activity."
            ),
        },
    },
    "writing": {
        "type": "noul",
        "instructions": (
            "Determine whether the user's PRIMARY goal is to create or improve "
            "a written artifact for readers. This includes articles, blog posts, "
            "emails, documentation, proposals, reports, and editing existing text. "
            "Technical topics, research, and code examples do not automatically "
            "make a request coding or research. For mixed requests, prioritize "
            "writing when the main deliverable is a polished, reader-facing "
            "document rather than an implementation or an investigation."
        ),
        "criteria": {
            "true": (
                "The main deliverable is a drafted, rewritten, edited, "
                "proofread, formatted, or publication-ready written artifact. "
                "Any code, research, or analysis is primarily supporting that artifact."
            ),
            "false": (
                "The main deliverable is implementing software or producing "
                "an evidence-based investigation. Writing is only used to "
                "explain, document, or summarize the main work."
            ),
        },
    },
}



def ns_to_ms(ns: int | None) -> float | None:
    return None if ns is None else round(ns / 1e6, 2)


def ns_to_s(ns: int | None) -> float | None:
    return None if ns is None else round(ns / 1e9, 3)


def tokens_per_sec(count: int | None, duration_ns: int | None) -> float | None:
    if not count or not duration_ns:
        return None
    return round(count / (duration_ns / 1e9), 2)


def list_available_models() -> list[str]:
    try:
        models = ollama.list().models or []
    except Exception:
        return []
    names = sorted({m.model for m in models if getattr(m, "model", None)})
    return names


def pick_default(preferred: str, models: list[str]) -> str:
    if preferred in models:
        return preferred
    return models[0] if models else preferred


def classify(prompt: str, classifier_model: str, route_models: dict[str, str]) -> dict[str, Any]:
    started = time.perf_counter()
    response = ollama.systemone(
        model=classifier_model,
        state=prompt,
        questions=CLASSIFIER_QUESTIONS,
    )
    wall_s = time.perf_counter() - started

    scores = {name: answer.noul for name, answer in response.answers.items()}
    route = max(scores, key=scores.get)

    return {
        "route": route,
        "label": ROUTE_DEFAULTS[route]["label"],
        "classifier_model": response.model,
        "scores": {k: round(v, 6) for k, v in scores.items()},
        "selected_model": route_models[route],
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
        "timing": {
            "wall_clock_s": round(wall_s, 3),
        },
    }


def extract_chat_metadata(chunk: Any, wall_s: float) -> dict[str, Any]:
    total_ns = getattr(chunk, "total_duration", None)
    load_ns = getattr(chunk, "load_duration", None)
    prompt_ns = getattr(chunk, "prompt_eval_duration", None)
    eval_ns = getattr(chunk, "eval_duration", None)
    prompt_tokens = getattr(chunk, "prompt_eval_count", None)
    output_tokens = getattr(chunk, "eval_count", None)

    return {
        "model": getattr(chunk, "model", None),
        "created_at": getattr(chunk, "created_at", None),
        "done": getattr(chunk, "done", None),
        "done_reason": getattr(chunk, "done_reason", None),
        "tokens": {
            "prompt_eval_count": prompt_tokens,
            "eval_count": output_tokens,
            "total_tokens": (prompt_tokens or 0) + (output_tokens or 0)
            if prompt_tokens is not None or output_tokens is not None
            else None,
        },
        "timing": {
            "wall_clock_s": round(wall_s, 3),
            "total_duration_s": ns_to_s(total_ns),
            "total_duration_ms": ns_to_ms(total_ns),
            "load_duration_ms": ns_to_ms(load_ns),
            "prompt_eval_duration_ms": ns_to_ms(prompt_ns),
            "eval_duration_ms": ns_to_ms(eval_ns),
        },
        "throughput": {
            "prompt_tokens_per_s": tokens_per_sec(prompt_tokens, prompt_ns),
            "generation_tokens_per_s": tokens_per_sec(output_tokens, eval_ns),
        },
    }


def build_messages(
    history: list[dict[str, Any]],
    prompt: str,
    prompt_suffix: str,
    memory_turns: int,
) -> list[dict[str, str]]:
    """Replay the last `memory_turns` turns, then append the current prompt.

    Only role and content are sent upstream; the decision and metadata we keep
    alongside each stored message are UI state and would only waste context.
    """
    recalled: list[dict[str, str]] = []
    if memory_turns > 0:
        for msg in history[-(memory_turns * 2) :]:
            recalled.append({"role": msg["role"], "content": msg["content"]})

    return recalled + [{"role": "user", "content": prompt + prompt_suffix}]


def stream_chat(model: str, messages: list[dict[str, str]]) -> Iterator[str]:
    started = time.perf_counter()
    final_chunk = None
    for chunk in chat(model=model, messages=messages, stream=True):
        final_chunk = chunk
        content = chunk.message.content if chunk.message else None
        if content:
            yield content
    wall_s = time.perf_counter() - started
    stream_chat.last_meta = (  # type: ignore[attr-defined]
        extract_chat_metadata(final_chunk, wall_s) if final_chunk is not None else None
    )


def main() -> None:
    st.set_page_config(page_title="Ollama Agent", layout="wide")
    st.title("Ollama Agent")
    st.caption("Classify intent → route to a model → stream the answer")

    available_models = list_available_models()

    with st.sidebar:
        st.subheader("Models")
        if st.button("Refresh model list"):
            st.rerun()

        if not available_models:
            st.warning("No Ollama models found. Is Ollama running?")
            classifier_model = DEFAULT_CLASSIFIER_MODEL
            route_models = {name: cfg["model"] for name, cfg in ROUTE_DEFAULTS.items()}
        else:
            classifier_model = st.selectbox(
                "Classifier",
                options=available_models,
                index=available_models.index(
                    pick_default(DEFAULT_CLASSIFIER_MODEL, available_models)
                ),
            )
            route_models = {}
            for name, cfg in ROUTE_DEFAULTS.items():
                route_models[name] = st.selectbox(
                    cfg["label"],
                    options=available_models,
                    index=available_models.index(pick_default(cfg["model"], available_models)),
                    key=f"route_model_{name}",
                )

        st.subheader("Memory")
        memory_turns = st.slider(
            "Turns replayed to the model",
            min_value=0,
            max_value=MAX_MEMORY_TURNS,
            value=DEFAULT_MEMORY_TURNS,
            help="0 sends every prompt in isolation. Higher values cost prompt tokens.",
        )
        stored_turns = len(st.session_state.get("messages", [])) // 2
        st.caption(f"{stored_turns} turn(s) in this conversation")

        if st.button("Clear conversation"):
            st.session_state.messages = []
            st.rerun()

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            if msg["role"] == "user":
                st.write(msg["content"])
            else:
                st.info(f"Routed to **{msg['decision']['label']}** → `{msg['decision']['selected_model']}`")
                st.markdown(msg["content"])
                col1, col2 = st.columns(2)
                with col1:
                    st.subheader("Decision")
                    st.json(msg.get("decision") or {})
                with col2:
                    st.subheader("Metadata")
                    st.json(msg.get("metadata") or {})

    prompt = st.chat_input("Enter a prompt")
    if not prompt:
        return

    if not available_models:
        st.error("No models available. Start Ollama and pull at least one model.")
        return

    history = list(st.session_state.messages)
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Classifying…"):
            try:
                decision = classify(prompt, classifier_model, route_models)
            except Exception as exc:
                st.error(f"Classifier error: {exc}")
                return

        st.info(f"Routed to **{decision['label']}** → `{decision['selected_model']}`")

        route_cfg = ROUTE_DEFAULTS[decision["route"]]
        selected_model = decision["selected_model"]
        messages = build_messages(
            history, prompt, route_cfg["prompt_suffix"], memory_turns
        )
        decision["memory"] = {
            "turns_requested": memory_turns,
            "messages_recalled": len(messages) - 1,
        }

        stream_chat.last_meta = None  # type: ignore[attr-defined]
        try:
            answer = st.write_stream(stream_chat(selected_model, messages))
        except Exception as exc:
            st.error(f"Model error ({selected_model}): {exc}")
            return

        metadata = stream_chat.last_meta  # type: ignore[attr-defined]

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Decision")
            st.json(decision)
        with col2:
            st.subheader("Metadata")
            if metadata:
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Prompt tokens", metadata["tokens"].get("prompt_eval_count"))
                m2.metric("Output tokens", metadata["tokens"].get("eval_count"))
                m3.metric("Total time (s)", metadata["timing"].get("total_duration_s"))
                m4.metric("Tok/s", metadata["throughput"].get("generation_tokens_per_s"))
                st.json(metadata)
            else:
                st.write("No metadata")

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": answer if isinstance(answer, str) else "".join(answer or []),
            "decision": decision,
            "metadata": metadata,
        }
    )


if __name__ == "__main__":
    main()
