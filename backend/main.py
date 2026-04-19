from typing import Dict, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from rapidfuzz import fuzz

try:
    from backend.translator_utils import (
        ATTITUDE_OPTIONS,
        EMOTION_OPTIONS,
        RELATIONSHIP_OPTIONS,
        TRANSLATORS,
        choose_api,
        detect_sfp,
        detect_sentiment,
        fuzzy_lookup,
        init_model,
        load_foul,
        log_history,
        load_dictionary,
        read_history,
        refine_sentence_type_by_pos,
        refine_sentiment_by_sfp,
        retrain_model,
        longest_local_match,
        rewrite_with_ollama,
        rewrite_with_openai_advanced,
        sanitize_label,
        search_by_tags,
        semantic_postprocess,
        sentence_type,
        offline_recognizer_status,
        offline_recognizer_with_fallback,
        offline_recognizer_last_meta,
        to_traditional_if_simplified,
        translate_lm,
    )
except ImportError:
    from translator_utils import (
        ATTITUDE_OPTIONS,
        EMOTION_OPTIONS,
        RELATIONSHIP_OPTIONS,
        TRANSLATORS,
        choose_api,
        detect_sfp,
        detect_sentiment,
        fuzzy_lookup,
        init_model,
        load_foul,
        log_history,
        load_dictionary,
        read_history,
        refine_sentence_type_by_pos,
        refine_sentiment_by_sfp,
        retrain_model,
        longest_local_match,
        rewrite_with_ollama,
        rewrite_with_openai_advanced,
        sanitize_label,
        search_by_tags,
        semantic_postprocess,
        sentence_type,
        offline_recognizer_status,
        offline_recognizer_with_fallback,
        offline_recognizer_last_meta,
        to_traditional_if_simplified,
        translate_lm,
    )

sfp_dict = {}
phrase_bank = {}
model = None
encs = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global sfp_dict, phrase_bank, model, encs
    sfp_dict, phrase_bank, _ = load_dictionary()
    model, encs = init_model()
    model = retrain_model(model, encs)
    yield


app = FastAPI(
    title="Cantonese-English Translator API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def offline_recognizer(audio_bytes: bytes) -> str:
    """
    Offline STT hook.
    To enable real offline recognition, define `offline_recognizer(audio_bytes)`
    in `backend/translator_utils.py` (for example using Whisper.cpp bindings).
    """
    try:
        from backend import translator_utils as _tu

        hook = getattr(_tu, "offline_recognizer", None)
        if callable(hook):
            return str(hook(audio_bytes) or "").strip()
    except Exception:
        pass

    raise RuntimeError(
        "offline recognizer not configured; add offline_recognizer(audio_bytes) in backend/translator_utils.py"
    )


class TranslateRequest(BaseModel):
    text: str
    use_fuzzy: bool = True
    use_sentiment: bool = True
    use_lm: bool = False
    allow_simplified: bool = False


class AdvancedSearchRequest(BaseModel):
    text: str
    emotion_tags: List[str] = []
    attitude_tags: List[str] = []
    relationship_tags: List[str] = []
    use_openai: bool = False
    openai_api_key: str = ""
    ollama_model: str = "qwen2.5:7b"
    openai_model: str = "gpt-4o-mini"


class FoulCombinedRequest(BaseModel):
    text: str
    use_fuzzy: bool = True
    use_sentiment: bool = True
    use_lm: bool = False
    allow_simplified: bool = False


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/speech_to_text")
def speech_to_text(
    file: UploadFile | None = File(None),
    audio: UploadFile | None = File(None),
) -> Dict[str, str]:
    # Keep compatibility with both multipart field names used by web/app.
    upload = file or audio
    if upload is None:
        raise HTTPException(status_code=400, detail="missing audio upload: use field 'file' or 'audio'")

    # Requested flow: read file bytes directly from UploadFile.
    audio_bytes = upload.file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="empty audio file")

    try:
        # Prefer whisper.cpp offline recognizer first.
        try:
            text = offline_recognizer(audio_bytes)
        except Exception:
            # Keep resilient fallback chain to preserve current UX.
            text = offline_recognizer_with_fallback(audio_bytes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"speech_to_text failed: {e}")

    meta = offline_recognizer_last_meta()
    return {
        "text": text,
        "engine": str(meta.get("engine", "") or ""),
        "lang_used": str(meta.get("lang_used", "") or ""),
    }


@app.get("/speech_to_text_health")
def speech_to_text_health() -> Dict[str, object]:
    status = offline_recognizer_status()
    if bool(status.get("ready", False)):
        status["mode"] = "whisper_cpp"
        return status

    # Backend /speech_to_text also supports a transformers fallback.
    try:
        from transformers import pipeline as _pipeline  # noqa: F401
        return {
            "ready": True,
            "mode": "hf_whisper_fallback",
            "message": "使用 Hugging Face Whisper 後備語音辨識",
        }
    except Exception:
        return status


@app.get("/sfp")
def sfp_dictionary() -> Dict[str, object]:
    items = []
    for ch, props in sfp_dict.items():
        items.append(
            {
                "character": ch,
                "jyutping": props.get("jyutping", ""),
                "engpinyin": props.get("engpinyin", ""),
                "meaning": props.get("meaning", ""),
            }
        )
    items.sort(key=lambda row: str(row.get("character", "")))
    return {"items": items, "count": len(items)}


@app.get("/foul")
def foul_entries() -> Dict[str, object]:
    rows, _ = load_foul()
    return {"items": rows, "count": len(rows)}


@app.get("/history")
def history(limit: int = 100) -> Dict[str, object]:
    safe_limit = max(1, min(limit, 1000))
    df = read_history()
    if df.empty:
        return {"items": [], "count": 0}

    if "time" in df.columns:
        try:
            df = df.sort_values("time", ascending=False)
        except Exception:
            pass

    cols = [c for c in ["input", "output", "time"] if c in df.columns]
    out = df[cols].head(safe_limit).fillna("")
    items = out.to_dict(orient="records")
    return {"items": items, "count": len(items)}


@app.get("/advanced_options")
def advanced_options() -> Dict[str, object]:
    return {
        "emotion_options": EMOTION_OPTIONS,
        "attitude_options": ATTITUDE_OPTIONS,
        "relationship_options": RELATIONSHIP_OPTIONS,
    }


@app.post("/advanced_search")
def advanced_search(payload: AdvancedSearchRequest) -> Dict[str, object]:
    text_input = payload.text.strip()
    if not text_input:
        return {"error": "text is required"}

    ollama_text = rewrite_with_ollama(
        source_text=text_input,
        model_name=payload.ollama_model or "qwen2.5:7b",
    )

    openai_text = ""
    if payload.use_openai and payload.openai_api_key.strip():
        try:
            openai_text = rewrite_with_openai_advanced(
                source_text=text_input.strip(),
                api_key=payload.openai_api_key.strip(),
                model_name=payload.openai_model or "gpt-4o-mini",
            )
        except Exception as e:
            openai_text = f"(OpenAI Error: {e})"

    results = search_by_tags(
        emotion_tags=payload.emotion_tags,
        attitude_tags=payload.attitude_tags,
        relationship_tags=payload.relationship_tags,
    )

    top_matches = []
    if results is not None and not results.empty and "cantonese_text" in results.columns:
        scored = results.copy()
        scored["_match_score"] = scored["cantonese_text"].fillna("").astype(str).apply(
            lambda value: fuzz.WRatio(text_input, value)
        )
        for _, row in scored.sort_values("_match_score", ascending=False).head(3).iterrows():
            top_matches.append(
                {
                    "cantonese_text": str(row.get("cantonese_text", "") or ""),
                    "english_translation": str(row.get("english_translation", "") or ""),
                    "emotion": str(row.get("emotion", "") or ""),
                    "attitude": str(row.get("attitude", "") or ""),
                    "relationship": str(row.get("relationship", "") or ""),
                    "match_score": float(row.get("_match_score", 0.0) or 0.0),
                }
            )

    return {
        "ollama": ollama_text,
        "openai": openai_text,
        "top_matches": top_matches,
    }


@app.post("/translate")
def translate(payload: TranslateRequest) -> Dict[str, object]:
    return _run_translate_pipeline(
        text=payload.text,
        use_fuzzy=payload.use_fuzzy,
        use_sentiment=payload.use_sentiment,
        use_lm=payload.use_lm,
        allow_simplified=payload.allow_simplified,
        normalize_foul=False,
    )


@app.post("/foul_combined_translate")
def foul_combined_translate(payload: FoulCombinedRequest) -> Dict[str, object]:
    return _run_translate_pipeline(
        text=payload.text,
        use_fuzzy=payload.use_fuzzy,
        use_sentiment=payload.use_sentiment,
        use_lm=payload.use_lm,
        allow_simplified=payload.allow_simplified,
        normalize_foul=True,
    )


def _run_translate_pipeline(
    text: str,
    use_fuzzy: bool,
    use_sentiment: bool,
    use_lm: bool,
    allow_simplified: bool,
    normalize_foul: bool,
) -> Dict[str, object]:
    text_input = (text or "").strip()
    if not text_input:
        return {"error": "text is required"}

    text_for_lookup = text_input
    if allow_simplified:
        text_for_lookup = to_traditional_if_simplified(text_input)

    replacement_notes = []
    if normalize_foul:
        rows, _ = load_foul()
        foul_tokens = []
        for row in rows:
            canonical = str(row.get("canonical", "")).strip()
            if canonical:
                foul_tokens.append((canonical, canonical))
            for var in row.get("variations", []):
                var_text = str(var).strip()
                if var_text and canonical:
                    foul_tokens.append((var_text, canonical))

        seen = set()
        for token, canonical in sorted(foul_tokens, key=lambda x: len(x[0]), reverse=True):
            if not token or token in seen:
                continue
            seen.add(token)
            if token in text_for_lookup:
                if token != canonical:
                    replacement_notes.append(f"{token} -> {canonical}")
                text_for_lookup = text_for_lookup.replace(token, canonical)

    stype = sentence_type(text_for_lookup)
    stype = refine_sentence_type_by_pos(text_for_lookup, stype)
    sfps = detect_sfp(text_for_lookup, sfp_dict)

    local_translation, trace_info, local_source_type = fuzzy_lookup(text_for_lookup, phrase_bank, use_fuzzy)
    local_is_authoritative = local_source_type == "exact_sentences"

    local_display_line = None
    if phrase_bank:
        best_similar = longest_local_match(text_for_lookup, phrase_bank)
        if best_similar:
            display_phrase, display_trans, display_label = best_similar
            if display_phrase and display_trans:
                local_display_line = f"{display_trans} - {display_phrase} ({display_label or 'local'})"
    if not local_display_line and local_translation and local_is_authoritative:
        local_display_line = f"{local_translation} - {text_for_lookup} (local)"

    local_translators = dict(TRANSLATORS)
    local_translators.pop("deepl", None)
    if use_lm:
        local_translators["lm"] = translate_lm

    translations = {}
    for name, fn in local_translators.items():
        try:
            translations[name] = fn(text_for_lookup)
        except Exception as e:
            translations[name] = f"[{name} Error] {e}"

    # Only use local translation when it comes from an authoritative source
    if local_translation and local_is_authoritative:
        translations["local"] = local_translation

    sentiment = detect_sentiment(text_for_lookup) if use_sentiment else None
    base_sentiment = sentiment if sentiment is not None else "neutral"
    refined_sentiment = refine_sentiment_by_sfp(base_sentiment, sfps)

    raw_to_display = sentiment if sentiment is not None else refined_sentiment
    label_to_show = sanitize_label(raw_to_display)
    if stype == "question":
        label_to_show = "neutral"

    processed = {}
    for name, output in translations.items():
        if name == "google":
            processed[name] = semantic_postprocess(output, stype, sfps, sentiment)
        else:
            processed[name] = output

    sfp_details = [
        {
            "character": p.get("character", ""),
            "meaning": p.get("meaning", ""),
            "jyutping": p.get("jyutping", ""),
            "engpinyin": p.get("engpinyin", ""),
        }
        for p in sfps
        if p.get("character")
    ]

    chosen_api, meta = choose_api(
        stype,
        sfps,
        model,
        encs,
        translations=translations,
        text=text_for_lookup,
        local_is_authoritative=local_is_authoritative,
    )

    final_translation = local_translation if chosen_api == "local" else processed.get(chosen_api, "")

    # Persist all translation trials so mobile/webpage/API invocations share one history sink.
    try:
        trial_kind = "foul_combined" if normalize_foul else "standard"
        api_name = str(chosen_api or "unknown")
        history_output = f"[{trial_kind}] ({api_name}) {final_translation}"
        if replacement_notes:
            history_output += f" | replacements: {', '.join(replacement_notes)}"
        log_history(text_input, history_output)
    except Exception:
        # Never block user responses due to history write failures.
        pass

    return {
        "input": text_input,
        "normalized_input": text_for_lookup,
        "sentence_type": stype,
        "sfp_count": len(sfps),
        "trace": trace_info,
        "sentiment": label_to_show,
        "translations": processed,
        "chosen_api": chosen_api,
        "scores": meta.get("scores", {}),
        "final_translation": final_translation,
        "replacement_notes": replacement_notes,
        "local_source_line": local_display_line or "",
        "sfp_details": sfp_details,
    }
