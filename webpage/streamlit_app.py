import os
import json
import re
import time
import uuid
import hashlib
import io
import wave
import urllib.error
import urllib.request

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process
import streamlit as st

from backend.translator_utils import (
    ATTITUDE_OPTIONS,
    DATA_DIR,
    EMOTION_OPTIONS,
    EXCEL_FILE,
    PROJECT_ROOT,
    RELATIONSHIP_OPTIONS,
    TRANSLATORS,
    choose_api,
    detect_sfp,
    detect_sentiment,
    fuzzy_lookup,
    init_model,
    is_in_corpus,
    longest_local_match,
    load_dictionary,
    load_foul,
    log_feedback,
    log_history,
    read_history,
    refine_sentence_type_by_pos,
    refine_sentiment_by_sfp,
    retrain_model,
    compute_feedback_weight_suggestion,
    rewrite_with_ollama,
    rewrite_with_openai_advanced,
    sanitize_label,
    search_by_tags,
    semantic_postprocess,
    sentence_type,
    to_traditional_if_simplified,
    translate_lm,
    offline_recognizer_with_fallback,
    offline_recognizer_last_meta,
)

sfp_dict, phrase_bank, _sheet_names = load_dictionary()

EMOTION_ZH_MAP = {
    "sadness": "悲傷",
    "fear": "恐懼",
    "neutral": "中性",
    "surprised": "驚訝",
    "love": "愛",
    "anger": "憤怒",
    "joy": "喜悅",
    "expect": "期待",
    "worry": "擔心",
    "excited": "興奮",
    "positive": "正面",
    "negative": "負面",
}

ATTITUDE_ZH_MAP = {
    "respectful": "尊重",
    "non-respectful": "不尊重",
    "irony": "諷刺",
    "playful": "玩笑",
    "mockery": "嘲弄",
    "warning": "警告",
    "certain": "肯定",
}

RELATIONSHIP_ZH_MAP = {
    "family": "家人",
    "friends": "朋友",
    "hierarchical": "階層關係",
    "professional": "專業關係",
    "not good": "不佳",
    "strangers": "陌生人",
}


def _format_bilingual_value(value, zh_map):
    raw = str(value or "").strip()
    if not raw:
        return raw
    key = raw.lower()
    zh = zh_map.get(key)
    return f"{zh} {raw}" if zh else raw


def _format_api_name(api_name):
    labels = {
        "google": "Google",
        "opus-mt": "Opus-MT",
        "mymemory": "MyMemory",
        "lm": "LM",
        "local": "本地",
    }
    return labels.get(str(api_name).lower(), str(api_name))


def _build_history_output(trial_kind, api_name, final_translation, replacement_notes=None, extras=None):
    out = f"[{trial_kind}] ({api_name or 'unknown'}) {final_translation or ''}"
    if replacement_notes:
        cleaned = [str(x).strip() for x in replacement_notes if str(x).strip()]
        if cleaned:
            out += f" | replacements: {', '.join(cleaned)}"
    if extras:
        cleaned_extras = [str(x).strip() for x in extras if str(x).strip()]
        if cleaned_extras:
            out += " | " + " | ".join(cleaned_extras)
    return out

def _format_zh_value(value, zh_map):
    raw = str(value or "").strip()
    if not raw:
        return raw
    return zh_map.get(raw.lower(), raw)


def _format_bilingual_list(raw_text, zh_map):
    raw = str(raw_text or "").strip()
    if not raw or raw.lower() == "nan":
        return "（未提供） (not available)"

    parts = [p.strip() for p in re.split(r"[;,/，、|]+", raw) if p.strip()]
    if not parts:
        return "（未提供） (not available)"

    return "、".join(_format_bilingual_value(part, zh_map) for part in parts)


def estimate_runtime_seconds(text: str, include_ai: bool = False) -> float:
    chars = len((text or "").strip())
    base = 1.2 + (chars / 45.0)
    if include_ai:
        base += 1.1
    return max(0.8, min(base, 20.0))


def measure_internet_speed_mbps() -> float | None:
    # Keep this local-only: avoid external network probes that can trigger
    # browser/system connectivity prompts in restricted environments.
    return None


def _internet_available() -> bool:
    # Intentionally avoid active internet checks for local-first UX.
    return True


def _normalize_lang_label(raw_lang: str | None) -> str:
    val = str(raw_lang or "").strip().lower()
    if val in {"cantonese", "yue"} or val.startswith("yue"):
        return "yue"
    if val.startswith("en"):
        return "en"
    if val.startswith("zh"):
        return "zh"
    return "yue"


def _speech_to_text_via_api(audio_bytes: bytes, api_base: str, filename: str = "audio.webm") -> tuple[str, str]:
    boundary = f"----Boundary{uuid.uuid4().hex}"
    body = b""
    body += f"--{boundary}\r\n".encode("utf-8")
    body += f"Content-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n".encode("utf-8")
    body += b"Content-Type: application/octet-stream\r\n\r\n"
    body += audio_bytes
    body += b"\r\n"
    body += f"--{boundary}--\r\n".encode("utf-8")

    endpoint = api_base.rstrip("/") + "/speech_to_text"
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            text = str(data.get("text", "")).strip()
            lang_used = _normalize_lang_label(data.get("lang_used") or data.get("language"))
            return text, lang_used
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            body = e.read().decode("utf-8")
            payload = json.loads(body)
            detail = str(payload.get("detail", "")).strip()
        except Exception:
            detail = ""
        msg = f"HTTP {e.code}"
        if detail:
            msg = f"{msg}: {detail}"
        raise RuntimeError(msg)


def _speech_to_text_local(audio_bytes: bytes) -> tuple[str, str]:
    # Use the same backend offline chain: whisper.cpp then local HF fallback.
    text = offline_recognizer_with_fallback(audio_bytes)
    meta = offline_recognizer_last_meta()
    lang_used = _normalize_lang_label(meta.get("lang_used"))
    return str(text or "").strip(), lang_used


def _audio_condition_code(audio_bytes: bytes, transcript: str | None = None, lang_used: str | None = None) -> tuple[str, str]:
    if not audio_bytes:
        return "C03", "好細聲，試吓大聲啲？"

    energy = 0.0
    peak = 0.0
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
            sample_width = wf.getsampwidth()
            channels = wf.getnchannels()
            frames = wf.readframes(wf.getnframes())

        if sample_width == 2:
            arr = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        elif sample_width == 4:
            arr = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
        else:
            arr = np.frombuffer(frames, dtype=np.uint8).astype(np.float32) / 255.0 - 0.5

        if channels > 1 and len(arr) >= channels:
            arr = arr.reshape(-1, channels).mean(axis=1)

        if len(arr) > 0:
            abs_arr = np.abs(arr)
            energy = float(abs_arr.mean())
            peak = float(abs_arr.max())
    except Exception:
        pass

    if transcript:
        lang = _normalize_lang_label(lang_used)
        return "C00", f"已使用({lang}) 錄入"

    if energy < 0.003 and peak < 0.02:
        return "C03", "好細聲，試吓大聲啲？"

    return "C04", "背景有啲嘈，試吓換個地方試試？"


def _classify_stt_failure(exc: Exception) -> tuple[str, str]:
    msg = str(exc or "").lower()
    if any(x in msg for x in ["network is unreachable", "temporary failure", "name or service not known", "nodename nor servname", "failed host lookup"]):
        return "C01", "無網喎"
    return "C02", "無法連至語音分析部分"


def _show_stt_banner(code: str, message: str, kind: str = "info"):
    if kind == "success":
        st.success(f"狀態碼：{code}｜{message}")
    elif kind == "warning":
        st.warning(f"狀態碼：{code}｜{message}")
    elif kind == "error":
        st.error(f"狀態碼：{code}｜{message}")
    else:
        st.info(f"狀態碼：{code}｜{message}")


def _speech_to_text_with_fallback(audio_bytes: bytes, api_base: str, filename: str = "audio.webm") -> tuple[str, str]:
    try:
        text_local, lang_local = _speech_to_text_local(audio_bytes)
        if text_local:
            return text_local, lang_local
        if api_base:
            text_api, lang_api = _speech_to_text_via_api(audio_bytes, api_base=api_base, filename=filename)
            return str(text_api or "").strip(), _normalize_lang_label(lang_api)
        return "", "yue"
    except Exception as e_local:
        if api_base:
            try:
                text_api, lang_api = _speech_to_text_via_api(audio_bytes, api_base=api_base, filename=filename)
                return str(text_api or "").strip(), _normalize_lang_label(lang_api)
            except Exception as e_api:
                raise RuntimeError(f"語音辨識失敗：{e_local}；API 後備亦失敗：{e_api}")
        raise RuntimeError(f"語音辨識失敗：{e_local}")

    # Unreachable, kept for compatibility.
    return "", "yue"


def start_live_progress(estimated_seconds: float):
    progress_bar = st.progress(0)
    status_box = st.empty()
    started = time.perf_counter()
    status_box.caption(f"進度：0%｜預計剩餘 {estimated_seconds:.1f} 秒")
    return {
        "bar": progress_bar,
        "status": status_box,
        "started": started,
        "estimated": max(0.5, estimated_seconds),
        "last_pct": 0,
    }


def update_live_progress(state, fraction: float, note: str):
    pct = max(0, min(99, int(round(fraction * 100))))
    if pct < state["last_pct"]:
        pct = state["last_pct"]
    state["last_pct"] = pct

    elapsed = time.perf_counter() - state["started"]
    remaining = max(0.0, state["estimated"] - elapsed)

    state["bar"].progress(pct)
    state["status"].caption(f"進度：{pct}%｜預計剩餘 {remaining:.1f} 秒｜{note}")


def finish_live_progress(state, note: str = "Done"):
    elapsed = time.perf_counter() - state["started"]
    state["bar"].progress(100)
    state["status"].caption(f"進度：100%｜實際需時：{elapsed:.2f} 秒｜{note}")


def render_speech_input_for(target_key: str, widget_prefix: str):
    signature_key = f"_speech_last_sig_{widget_prefix}"
    api_base = str(st.session_state.get("speech_api_base", "http://127.0.0.1:8000")).strip()

    st.caption("語音辨識")

    audio_input_fn = getattr(st, "audio_input", None)
    if callable(audio_input_fn):
        audio_data = audio_input_fn("🎙️ 按一下開始／停止錄音", key=f"{widget_prefix}_audio")
        if audio_data is None:
            return

        audio_bytes = audio_data.getvalue()
        audio_sig = hashlib.md5(audio_bytes).hexdigest()
        if st.session_state.get(signature_key) == audio_sig:
            return

        st.session_state[signature_key] = audio_sig
        stt_progress = st.progress(0)
        stt_status = st.empty()
        stt_status.caption("語音處理中：準備辨識...")
        try:
            stt_progress.progress(25)
            stt_status.caption("語音處理中：正在離線辨識...")
            transcript, lang_used = _speech_to_text_with_fallback(audio_bytes, api_base=api_base, filename=f"{widget_prefix}.wav")
            stt_progress.progress(85)
        except Exception as e:
            stt_progress.progress(100)
            stt_status.caption("語音處理失敗：無法完成辨識")
            code, msg = _classify_stt_failure(e)
            _show_stt_banner(code, msg, kind="error")
            return

        transcript = str(transcript or "").strip()
        if not transcript:
            stt_progress.progress(100)
            code, msg = _audio_condition_code(audio_bytes, transcript=None)
            stt_status.caption("語音處理完成：未識別到文字")
            _show_stt_banner(code, msg, kind="warning")
            return

        stt_progress.progress(100)
        stt_status.caption("語音處理完成：文字已填入")
        current_val = str(st.session_state.get(target_key, "") or "").strip()
        incoming = str(transcript).strip()
        if incoming:
            st.session_state[target_key] = incoming if not current_val else f"{current_val} {incoming}"
        code, msg = _audio_condition_code(audio_bytes, transcript=transcript, lang_used=lang_used)
        st.session_state["_speech_notice"] = f"狀態碼：{code}｜{msg}"
        return

    audio_file = st.file_uploader("上傳音訊（備用）", type=["wav", "webm", "m4a", "mp3"], key=f"{widget_prefix}_uploader")
    if audio_file is None:
        return

    file_bytes = audio_file.getvalue()
    file_sig = hashlib.md5(file_bytes).hexdigest()
    if st.session_state.get(signature_key) == file_sig:
        return

    st.session_state[signature_key] = file_sig
    stt_progress = st.progress(0)
    stt_status = st.empty()
    stt_status.caption("語音處理中：準備辨識音訊檔...")
    try:
        stt_progress.progress(25)
        stt_status.caption("語音處理中：正在離線辨識...")
        transcript, lang_used = _speech_to_text_with_fallback(
            file_bytes,
            api_base=api_base,
            filename=audio_file.name or f"{widget_prefix}.wav",
        )
        stt_progress.progress(85)
    except Exception as e:
        stt_progress.progress(100)
        stt_status.caption("語音處理失敗：無法完成辨識")
        code, msg = _classify_stt_failure(e)
        _show_stt_banner(code, msg, kind="error")
        return

    transcript = str(transcript or "").strip()
    if not transcript:
        stt_progress.progress(100)
        code, msg = _audio_condition_code(file_bytes, transcript=None)
        stt_status.caption("語音處理完成：未識別到文字")
        _show_stt_banner(code, msg, kind="warning")
        return

    stt_progress.progress(100)
    stt_status.caption("語音處理完成：文字已填入")
    current_val = str(st.session_state.get(target_key, "") or "").strip()
    incoming = str(transcript).strip()
    if incoming:
        st.session_state[target_key] = incoming if not current_val else f"{current_val} {incoming}"
    code, msg = _audio_condition_code(file_bytes, transcript=transcript, lang_used=lang_used)
    st.session_state["_speech_notice"] = f"狀態碼：{code}｜{msg}"


def _apply_pending_input_value(target_key: str):
    pending_key = f"_pending_{target_key}"
    pending_val = st.session_state.pop(pending_key, None)
    if pending_val is not None:
        current_val = str(st.session_state.get(target_key, "") or "").strip()
        incoming = str(pending_val).strip()
        if not incoming:
            return
        st.session_state[target_key] = incoming if not current_val else f"{current_val} {incoming}"


def main_page():
    st.title("CanET 粵英翻譯器")
    st.session_state.setdefault("use_fuzzy", True)
    st.session_state.setdefault("use_sentiment", True)
    st.session_state.setdefault("allow_simplified", False)
    st.session_state.setdefault("allow_simplified_confirmed", False)
    st.session_state.setdefault("speech_api_base", "http://127.0.0.1:8000")
    st.session_state.setdefault("bg_theme", "Brick Red")
    st.session_state.setdefault("main_processing", False)

    apply_background(st.session_state.get("bg_theme", "Brick Red"))
    model, encs = init_model()
    model = retrain_model(model, encs)

    st.session_state.setdefault("main_text_input", "")
    render_speech_input_for("main_text_input", "main")
    _apply_pending_input_value("main_text_input")
    notice = st.session_state.pop("_speech_notice", None)
    if notice:
        st.success(notice)
    main_disabled = st.session_state.get("main_processing", False)
    text_input = st.text_input("請輸入粵語:", key="main_text_input", disabled=main_disabled)
    use_fuzzy = st.session_state.get("use_fuzzy", True)
    use_sent = st.session_state.get("use_sentiment", True)

    with st.expander("🔍 進階搜尋（AI）"):
        st.write("根據情感、態度和關係標籤搜尋粵語句子")

        col1, col2, col3 = st.columns(3)
        with col1:
            selected_emotions = st.multiselect(
                "情感:",
                EMOTION_OPTIONS,
                format_func=lambda x: _format_zh_value(x, EMOTION_ZH_MAP),
                disabled=st.session_state.get("main_processing", False),
            )
        with col2:
            selected_attitudes = st.multiselect(
                "態度:",
                ATTITUDE_OPTIONS,
                format_func=lambda x: _format_zh_value(x, ATTITUDE_ZH_MAP),
                disabled=st.session_state.get("main_processing", False),
            )
        with col3:
            selected_relationships = st.multiselect(
                "關係:",
                RELATIONSHIP_OPTIONS,
                format_func=lambda x: _format_zh_value(x, RELATIONSHIP_ZH_MAP),
                disabled=st.session_state.get("main_processing", False),
            )

    search_clicked = st.button("搜尋", disabled=st.session_state.get("main_processing", False))

    if not search_clicked:
        return

    st.session_state["main_processing"] = True
    est_seconds = estimate_runtime_seconds(text_input, include_ai=bool(selected_emotions or selected_attitudes or selected_relationships))
    st.info(f"翻譯緊... 預計需時: {est_seconds:.1f}s")
    started_at = time.perf_counter()
    progress_state = start_live_progress(est_seconds)
    update_live_progress(progress_state, 0.05, "準備翻譯流程")

    foul_rows, foul_map = load_foul()
    if st.session_state.get("foul_choice_for_input") != text_input:
        st.session_state.pop("foul_choice", None)
        st.session_state.pop("foul_choice_for_input", None)
        st.session_state.pop("foul_selected_variant", None)

    foul_matches = []
    if text_input and (foul_rows or foul_map):
        for row in foul_rows:
            canon = row.get("canonical", "")
            if canon and canon in text_input:
                foul_matches.append((canon, row))
        for var, row in foul_map.items():
            if var and var in text_input:
                foul_matches.append((var, row))

    update_live_progress(progress_state, 0.12, "已檢查粗口詞條")

    if foul_matches and not st.session_state.get("foul_choice_for_input"):
        options = []
        token_to_row = {}
        for tok, row in foul_matches:
            if tok not in token_to_row:
                token_to_row[tok] = row
                options.append(tok)

        modal_fn = getattr(st, "modal", None)
        chosen = None
        if callable(modal_fn):
            with st.modal("你是指以下哪個詞語？"):
                st.write("在你的輸入中檢測到可能敏感/粗俗的詞語。請選擇你想表達的詞語，或選擇不替換。")
                sel = st.selectbox("選擇詞語:", ["（請選擇）"] + options, index=0)
                if st.button("替換"):
                    if sel and sel != "（請選擇）":
                        chosen = sel
                    st.session_state["foul_choice_for_input"] = text_input
                    if chosen:
                        st.session_state["foul_choice"] = token_to_row[chosen]
                        st.session_state["foul_selected_variant"] = chosen
                    else:
                        st.session_state.pop("foul_choice", None)
        else:
            with st.expander("檢測到可能的敏感詞語 — 點擊查看"):
                st.write("在你的輸入中檢測到可能敏感/粗俗的詞語。請選擇你想表達的詞語，或繼續不替換。")
                sel = st.selectbox("選擇詞語:", ["（請選擇）"] + options, index=0)
                if st.button("替換"):
                    if sel and sel != "（請選擇）":
                        chosen = sel
                        st.session_state["foul_choice"] = token_to_row[chosen]
                        st.session_state["foul_selected_variant"] = chosen
                    st.session_state["foul_choice_for_input"] = text_input

    if st.session_state.get("foul_choice") and st.session_state.get("foul_selected_variant"):
        fc = st.session_state["foul_choice"]
        sel_var = st.session_state["foul_selected_variant"]
        if sel_var in text_input:
            text_for_lookup = text_input.replace(sel_var, fc.get("canonical"), 1)
        else:
            text_for_lookup = text_input
    else:
        text_for_lookup = text_input

    if st.session_state.get("allow_simplified", False):
        text_for_lookup = to_traditional_if_simplified(text_for_lookup)
        if text_for_lookup != text_input and text_input.strip():
            st.info("⚠️ 偵測到簡體中文輸入，已轉換為繁體以進行離線查詢。")

    update_live_progress(progress_state, 0.22, "已標準化輸入文字")

    if not text_input.strip():
        st.warning("請輸入文字。")
        finish_live_progress(progress_state, "已停止：輸入為空")
        st.session_state["main_processing"] = False
        return

    stype = sentence_type(text_for_lookup)
    stype = refine_sentence_type_by_pos(text_for_lookup, stype)
    sfps = detect_sfp(text_for_lookup, sfp_dict)
    update_live_progress(progress_state, 0.32, "已識別句型與助語詞")

    local_translation, _, local_source_type = fuzzy_lookup(text_for_lookup, phrase_bank, use_fuzzy)
    local_is_authoritative = (
        local_source_type == "exact_sentences"
        or (local_translation is not None and is_in_corpus(text_for_lookup))
    )
    # Longest substring match — used only for the display line, not for scoring.
    display_phrase, display_trans, display_label = longest_local_match(text_for_lookup, phrase_bank)
    update_live_progress(progress_state, 0.42, "已完成本地詞庫匹配")

    local_translators = dict(TRANSLATORS)
    local_translators.pop("deepl", None)
    marianmt_output = translate_lm(text_input)

    translations = {}
    api_weight_map = {
        "google": 0.28,
        "opus-mt": 0.25,
        "mymemory": 0.15,
        "lm": 0.10,
    }
    active_api_weights = {
        name: api_weight_map.get(name, 0.2) for name in local_translators.keys()
    }
    total_weight = sum(active_api_weights.values()) or 1.0
    weighted_cursor = 0.42
    weighted_span = 0.36

    for name, fn in local_translators.items():
        try:
            translations[name] = fn(text_input)
        except Exception as e:
            translations[name] = f"[{name} Error] {e}"
        weighted_cursor += (active_api_weights.get(name, 0.2) / total_weight) * weighted_span
        update_live_progress(progress_state, weighted_cursor, f"已完成 {name} 翻譯")

    # Only add local to the translation pool when it is an authoritative source
    # (exact match in the 'Sentences' sheet of jyutping_dict, or found in the corpus).
    if local_translation and local_is_authoritative:
        translations["local"] = local_translation
        update_live_progress(progress_state, 0.80, "已套用本地詞庫匹配")

    sentiment = detect_sentiment(text_input) if use_sent else None
    base_sentiment = sentiment if sentiment is not None else "neutral"
    refined_sentiment = refine_sentiment_by_sfp(base_sentiment, sfps)

    raw_to_display = sentiment if sentiment is not None else refined_sentiment
    label_to_show = sanitize_label(raw_to_display)
    if stype == "question":
        label_to_show = "neutral"

    sentiment_label = _format_bilingual_value(label_to_show, EMOTION_ZH_MAP)
    sentiment_tag = f"[{sentiment_label}] " if (use_sent and sentiment_label) else ("[中性 neutral] " if use_sent else "")

    # Build per-SFP pragmatic-effect labels: "呢: question", "呀: softening tone", etc.
    sfp_label_parts = []
    for p in sfps:
        char = p.get("character", "")
        meaning = p.get("meaning", "").lower()
        if any(x in meaning for x in ["感歎", "驚訝", "驚奇", "驚嘆", "驚歎", "感慨", "exclamation", "嘆詞"]):
            cat = "exclamation"
        elif any(x in meaning for x in ["軟化", "委婉", "soften", "gentle", "polite", "mild", "緩和"]):
            cat = "softening tone"
        elif any(x in meaning for x in ["強調", "肯定", "斷言", "emphasis", "certain", "definite", "assert", "確定語氣"]):
            cat = "emphasis"
        elif any(x in meaning for x in ["疑問", "詢問", "question", "doubt", "不確定", "確認", "query", "interrogat", "yes/no"]):
            cat = "question"
        elif any(x in meaning for x in ["playful", "輕鬆", "活潑", "casual", "friendly", "親切", "俏皮"]):
            cat = "playful"
        elif any(x in meaning for x in ["催促", "urge", "命令", "impatient", "敦促", "急切"]):
            cat = "urging"
        elif any(x in meaning for x in ["建議", "suggest", "提議", "勸說", "邀請"]):
            cat = "suggestion"
        elif any(x in meaning for x in ["驚喜", "delight", "喜悅", "高興", "喜"]):
            cat = "delightful"
        elif any(x in meaning for x in ["警告", "warn", "提醒", "caution", "告誡"]):
            cat = "warning"
        elif any(x in meaning for x in ["否定", "negat", "denial", "反駁", "不信"]):
            cat = "negation"
        elif any(x in meaning for x in ["同意", "agreement", "approval", "認同", "贊同"]):
            cat = "agreement"
        elif any(x in meaning for x in ["傳達", "語氣", "助詞", "particle", "tone"]):
            cat = "tone marker"
        else:
            # Extract any remaining English words as fallback
            eng = re.sub(r"[\u4e00-\u9fa5，。；、！？()（）【】、/]+", " ", meaning).strip().strip(".,;: ")
            cat = " ".join(eng.split()[:4]) if eng.strip() else "particle"
        if char:
            sfp_label_parts.append(f"{char}: {cat}")

    meaning_tag = f" ({'; '.join(sfp_label_parts)})" if sfp_label_parts else ""

    processed = {}
    for name, output in translations.items():
        if name == "google":
            processed[name] = semantic_postprocess(output, stype, sfps, sentiment)
        else:
            processed[name] = output
    update_live_progress(progress_state, 0.80, "已完成語義後處理")

    try:
        chosen_api, _ = choose_api(stype, sfps, model, encs, translations=translations, text=text_for_lookup, local_is_authoritative=local_is_authoritative)
    except Exception:
        chosen_api = None
    update_live_progress(progress_state, 0.88, "已選擇最佳翻譯路線")

    selected_tags = {}
    if selected_emotions:
        selected_tags["emotion"] = ", ".join(selected_emotions)
    if selected_attitudes:
        selected_tags["attitude"] = ", ".join(selected_attitudes)
    if selected_relationships:
        selected_tags["relationship"] = ", ".join(selected_relationships)

    st.subheader("結果")
    final_trans = ""

    st.markdown("**基本搜尋結果**")
    if "opus-mt" in processed:
        st.markdown(f"**Opus-MT:** {sentiment_tag}{processed['opus-mt']}{meaning_tag}")
    if marianmt_output:
        st.markdown(f"**MarianMT:** {sentiment_tag}{marianmt_output}{meaning_tag}")
    if "google" in processed:
        st.markdown(f"**Google:** {sentiment_tag}{processed['google']}{meaning_tag}")
    if "mymemory" in processed:
        st.markdown(f"**MyMemory:** {sentiment_tag}{processed['mymemory']}{meaning_tag}")

    local_display_line = None
    if local_source_type in ("exact_sentences", "exact_phrase") and phrase_bank:
        best_similar = process.extractOne(text_for_lookup, phrase_bank.keys(), scorer=fuzz.WRatio)
        if best_similar:
            similar_key = best_similar[0]
            similar_entry = phrase_bank.get(similar_key, [])
            if isinstance(similar_entry, list) and similar_entry:
                similar_entry = similar_entry[0]
            similar_trans = str((similar_entry or {}).get("translation", "")).strip()
            similar_label = str((similar_entry or {}).get("source_sheet", "local")).strip() or "local"
            if similar_trans:
                local_display_line = f"{similar_trans} - {similar_key} ({similar_label})"

    if not local_display_line and display_phrase and display_trans:
        local_display_line = f"{display_trans} - {display_phrase} ({display_label or 'local'})"

    if local_display_line:
        st.markdown(f"**本地來源（已使用資料）:** {local_display_line}")
    else:
        st.markdown("**本地來源（已使用資料）:** *(沒有找到本地匹配)*")

    if chosen_api:
        if chosen_api == "local":
            final_trans = local_translation
        else:
            final_trans = processed.get(chosen_api, "")
        st.markdown(
            f":blue-background[**已選翻譯({_format_api_name(chosen_api)}):** {sentiment_tag}{final_trans}{meaning_tag}]"
        )
        st.write("")

    feedback_routes = [name for name in ["local", "google", "opus-mt", "mymemory", "lm"] if name in translations]
    if chosen_api and chosen_api not in feedback_routes:
        feedback_routes.append(chosen_api)

    if text_for_lookup.strip() and stype and feedback_routes:
        st.markdown("---")
        st.markdown("**回饋**")

        default_idx = feedback_routes.index(chosen_api) if chosen_api in feedback_routes else 0
        feedback_token = hashlib.md5(text_for_lookup.encode("utf-8")).hexdigest()[:10]
        selected_feedback_api = st.selectbox(
            "你覺得哪個翻譯來源最好？",
            feedback_routes,
            index=default_idx,
            key=f"feedback_api_{feedback_token}",
        )

        if st.button("儲存回饋", key=f"save_feedback_{feedback_token}"):
            entry = {
                "clause": text_for_lookup,
                "sentence_type": stype,
                "best_api": selected_feedback_api,
            }
            log_feedback(entry)
            log_history(
                text_for_lookup,
                f"[feedback] best_api={selected_feedback_api}",
                event_type="feedback",
                feedback_api=selected_feedback_api,
                feedback_sentence_type=stype,
            )
            model = retrain_model(model, encs)
            st.success("已儲存回饋，並更新模型。")

        st.caption("外部表單：https://forms.gle/s2H8EiFEyTwbVzeq7")

    if selected_tags:
        st.markdown("---")
        st.subheader("進階搜尋")
        use_openai_adv = bool(st.session_state.get("use_openai_advanced", False))
        adv_weights = {"ollama": 0.7, "openai": 0.3 if use_openai_adv else 0.0}
        adv_total = (adv_weights["ollama"] + adv_weights["openai"]) or 1.0
        adv_cursor = 0.90
        adv_span = 0.08
        update_live_progress(progress_state, adv_cursor, "進階搜尋執行中")

        adv_ollama = rewrite_with_ollama(
            source_text=text_input,
            model_name=st.session_state.get("ollama_model", "qwen2.5:7b"),
        )
        st.markdown(f"**1) Ollama（本地 LLM）:** {adv_ollama}")
        adv_cursor += (adv_weights["ollama"] / adv_total) * adv_span
        update_live_progress(progress_state, adv_cursor, "已完成 Ollama 進階搜尋")

        if use_openai_adv:
            adv_openai = rewrite_with_openai_advanced(
                source_text=text_input,
                api_key=st.session_state.get("openai_api_key", ""),
                model_name=st.session_state.get("openai_model", "gpt-4o-mini"),
            )
            if adv_openai:
                st.markdown(f"**2) OpenAI（可選）:** {adv_openai}")
            adv_cursor += (adv_weights["openai"] / adv_total) * adv_span
            update_live_progress(progress_state, adv_cursor, "已完成 OpenAI 進階搜尋")
        update_live_progress(progress_state, 0.98, "進階搜尋完成")

        results = search_by_tags(
            emotion_tags=selected_emotions,
            attitude_tags=selected_attitudes,
            relationship_tags=selected_relationships,
        )
        if not results.empty and "cantonese_text" in results.columns:
            scored = results.copy()
            scored["_match_score"] = scored["cantonese_text"].fillna("").astype(str).apply(lambda value: fuzz.WRatio(text_input, value))
            top_matches = scored.sort_values("_match_score", ascending=False).head(3)

            if not top_matches.empty:
                st.markdown("**本地最佳匹配：**")
                for idx, (_, row) in enumerate(top_matches.iterrows()):
                    chin = str(row.get("cantonese_text", "")).strip()
                    eng = str(row.get("english_translation", "")).strip()
                    if not eng or eng.lower() == "nan":
                        eng = "（未提供）"
                    if idx > 0:
                        st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

                    emo = str(row.get("emotion", "")).strip()
                    att = str(row.get("attitude", "")).strip()
                    rel = str(row.get("relationship", "")).strip()
                    emo = _format_bilingual_list(emo, EMOTION_ZH_MAP)
                    att = _format_bilingual_list(att, ATTITUDE_ZH_MAP)
                    rel = _format_bilingual_list(rel, RELATIONSHIP_ZH_MAP)

                    st.markdown(f"中文：{chin}  英文：{eng}")
                    st.markdown(f"情感：{emo} | 態度：{att} | 關係：{rel}")
                    st.markdown("---")

    if st.session_state.get("foul_choice"):
        fc = st.session_state["foul_choice"]
        final_trans = fc.get("desired", "")
        st.markdown(f"**最終翻譯（來源：粗口）:** {sentiment_tag}{final_trans}{meaning_tag}")
        if fc.get("literal"):
            st.markdown(f"*字面解釋：* {fc.get('literal')}")
        if fc.get("variations"):
            variations_str = ", ".join(fc.get("variations"))
            st.markdown(f"*變體：* {variations_str}")

        source_list = ["Local", "API (Google, Opus-MT, MyMemory)"]
        if selected_tags:
            source_list.append("LLM (Ollama)")
            if st.session_state.get("use_openai_advanced", False):
                source_list.append("AI (OpenAI)")
        st.caption(f"📚 Source: {' + '.join(source_list)}")

    if st.session_state.get("foul_choice"):
        fc = st.session_state["foul_choice"]
        chosen_api_for_history = "foul"
        final_trans_for_history = fc.get("desired", "")
        extras = []
        if fc.get("literal"):
            extras.append(f"literal: {fc.get('literal')}")
    else:
        if not final_trans and chosen_api:
            final_trans = processed.get(chosen_api, "") if chosen_api != "local" else (local_translation or "")
        chosen_api_for_history = chosen_api or "unknown"
        final_trans_for_history = final_trans
        extras = []

    if marianmt_output:
        extras.append(f"marianmt: {marianmt_output}")

    final_output = _build_history_output(
        trial_kind="standard",
        api_name=chosen_api_for_history,
        final_translation=final_trans_for_history,
        extras=extras,
    )
    log_history(text_input, final_output)
    finish_live_progress(progress_state, "Translation completed")

    actual_seconds = time.perf_counter() - started_at
    speed_mbps = measure_internet_speed_mbps()
    if speed_mbps is None:
        st.caption(f"預計需時: {est_seconds:.1f}s | 實際需時: {actual_seconds:.2f}s | 網絡速度: 未能測量")
    else:
        st.caption(f"預計需時: {est_seconds:.1f}s | 實際需時: {actual_seconds:.2f}s | 網絡速度: ~{speed_mbps:.2f} Mbps")
    st.session_state["main_processing"] = False


def page_sfp():
    st.header("📗 助語詞詞典")
    try:
        df = pd.read_excel(EXCEL_FILE, sheet_name="SFP")
        max_cols = min(9, len(df.columns))
        cols = list(df.columns[:max_cols])
        if len(cols) >= 2:
            cols.pop(1)
        df_display = df[cols].copy()
        df_display.insert(0, "No", range(1, len(df_display) + 1))
        st.dataframe(df_display)
    except Exception:
        st.error("無法載入 SFP 工作表 Cannot load SFP sheet.")

    rows, _ = load_foul()
    if rows:
        st.markdown("---")
        st.markdown("**粗口詞彙表**")
        foul_df = pd.DataFrame(rows)
        foul_df_display = foul_df.copy()
        foul_df_display["variations"] = foul_df_display["variations"].apply(
            lambda v: ", ".join(v) if isinstance(v, list) else v
        )
        st.dataframe(foul_df_display)

    if st.button("🔙 返回 Back"):
        st.session_state.page = "home"


def page_foul():
    st.header("💢 粗口翻譯")
    rows, var_map = load_foul()
    st.session_state.setdefault("foul_combined_processing", False)

    def _resolve_phrase_entry(token):
        entry = phrase_bank.get(token, [])
        if isinstance(entry, list) and entry:
            entry = entry[0]
        if not isinstance(entry, dict):
            return None
        translation = str(entry.get("translation", "")).strip()
        if not translation:
            return None
        source_label = str(entry.get("source_sheet", "local")).strip() or "local"
        return {
            "token": token,
            "translation": translation,
            "source_label": source_label,
        }

    def collect_local_source_candidates(query_text, limit=3, fuzzy_threshold=90.0):
        query = (query_text or "").strip()
        if not query:
            return [], "none"

        keys = [str(k).strip() for k in phrase_bank.keys() if str(k).strip()]
        if not keys:
            return [], "none"

        # 1) Prefer exact substring hits and return all likely matches.
        exact_hits = []
        seen = set()
        for token in sorted(keys, key=len, reverse=True):
            if token in query and token not in seen:
                resolved = _resolve_phrase_entry(token)
                if resolved:
                    exact_hits.append({**resolved, "score": 100.0, "match_type": "exact"})
                    seen.add(token)
        if exact_hits:
            return exact_hits[:limit], "exact"

        # 2) If no exact hit, use fuzzy matches and keep those >= 90 first.
        fuzzy_hits = process.extract(query, keys, scorer=fuzz.WRatio, limit=10)
        strong_hits = []
        fallback_hits = []
        used_tokens = set()
        for token, score, _ in fuzzy_hits:
            if token in used_tokens:
                continue
            resolved = _resolve_phrase_entry(token)
            if not resolved:
                continue
            entry = {**resolved, "score": float(score), "match_type": "fuzzy"}
            used_tokens.add(token)
            if float(score) >= fuzzy_threshold:
                strong_hits.append(entry)
            fallback_hits.append(entry)

        if strong_hits:
            return strong_hits[:limit], "strong_fuzzy"
        return fallback_hits[:limit], "fallback_top3"

    if not rows:
        st.info("找不到 foul.xlsx. 請新增包含 canonical, variations, literal, desired 四種欄位的工作表。")
    else:
        st.subheader("混合搜尋 combined search")
        st.session_state.setdefault("foul_combined_input", "")
        render_speech_input_for("foul_combined_input", "foul_combined")
        _apply_pending_input_value("foul_combined_input")
        foul_combined_disabled = st.session_state.get("foul_combined_processing", False)
        combined_input = st.text_area("混合搜尋 combined search", key="foul_combined_input", disabled=foul_combined_disabled)
        if st.button("執行混合搜尋 Run combined search", key="foul_combined_search", disabled=st.session_state.get("foul_combined_processing", False)):
            st.session_state["foul_combined_processing"] = True
            est_seconds = estimate_runtime_seconds(combined_input, include_ai=True)
            st.info(f"翻譯緊... 預計需時: {est_seconds:.1f}s")
            started_at = time.perf_counter()
            progress_state = start_live_progress(est_seconds)
            update_live_progress(progress_state, 0.05, "Preparing combined search")
            if not combined_input.strip():
                st.warning("請輸入句子。")
                finish_live_progress(progress_state, "Stopped: empty input")
                st.session_state["foul_combined_processing"] = False
            else:
                use_fuzzy = st.session_state.get("use_fuzzy", True)
                use_sent = st.session_state.get("use_sentiment", True)

                model, encs = init_model()
                model = retrain_model(model, encs)

                text_for_lookup = combined_input.strip()
                replacement_notes = []

                foul_tokens = []
                for row in rows:
                    canon = str(row.get("canonical", "")).strip()
                    if canon:
                        foul_tokens.append((canon, canon))
                    for var in row.get("variations", []):
                        var_text = str(var).strip()
                        if var_text:
                            foul_tokens.append((var_text, canon))

                seen = set()
                for token, canonical in sorted(foul_tokens, key=lambda x: len(x[0]), reverse=True):
                    if not token or token in seen:
                        continue
                    seen.add(token)
                    if token in text_for_lookup and canonical:
                        if token != canonical:
                            replacement_notes.append(f"{token} -> {canonical}")
                        text_for_lookup = text_for_lookup.replace(token, canonical)
                update_live_progress(progress_state, 0.20, "Normalized foul-language phrases")

                stype = sentence_type(text_for_lookup)
                stype = refine_sentence_type_by_pos(text_for_lookup, stype)
                sfps = detect_sfp(text_for_lookup, sfp_dict)
                update_live_progress(progress_state, 0.30, "Detected sentence type and SFP")

                local_translation, _, local_source_type = fuzzy_lookup(text_for_lookup, phrase_bank, use_fuzzy)
                local_is_authoritative = (
                    local_source_type == "exact_sentences"
                    or (local_translation is not None and is_in_corpus(text_for_lookup))
                )

                local_translators = dict(TRANSLATORS)
                local_translators.pop("deepl", None)

                translations = {}
                api_weight_map = {
                    "google": 0.28,
                    "opus-mt": 0.25,
                    "mymemory": 0.15,
                    "lm": 0.10,
                }
                active_api_weights = {
                    name: api_weight_map.get(name, 0.2) for name in local_translators.keys()
                }
                total_weight = sum(active_api_weights.values()) or 1.0
                weighted_cursor = 0.30
                weighted_span = 0.35

                for name, fn in local_translators.items():
                    try:
                        translations[name] = fn(text_for_lookup)
                    except Exception as e:
                        translations[name] = f"[{name} Error] {e}"
                    weighted_cursor += (active_api_weights.get(name, 0.2) / total_weight) * weighted_span
                    update_live_progress(progress_state, weighted_cursor, f"Translated via {name}")

                marianmt_output = translate_lm(text_for_lookup)

                if local_translation and local_is_authoritative:
                    translations["local"] = local_translation
                    update_live_progress(progress_state, 0.68, "Local dictionary match applied")

                sentiment = detect_sentiment(text_for_lookup) if use_sent else None
                base_sentiment = sentiment if sentiment is not None else "neutral"
                refined_sentiment = refine_sentiment_by_sfp(base_sentiment, sfps)
                label_to_show = sanitize_label(sentiment if sentiment is not None else refined_sentiment)
                if stype == "question":
                    label_to_show = "neutral"
                sentiment_label = _format_bilingual_value(label_to_show, EMOTION_ZH_MAP)
                sentiment_tag = f"[{sentiment_label}] " if (use_sent and sentiment_label) else ("[中性 neutral] " if use_sent else "")

                sfp_label_parts = []
                for p in sfps:
                    char = str(p.get("character", "")).strip()
                    meaning = str(p.get("meaning", "")).strip().lower()
                    if not char:
                        continue
                    if any(x in meaning for x in ["軟化", "soften", "gentle", "polite", "mild", "緩和"]):
                        cat = "softening tone"
                    elif any(x in meaning for x in ["疑問", "詢問", "question", "query", "interrogat", "yes/no"]):
                        cat = "question"
                    elif any(x in meaning for x in ["強調", "肯定", "emphasis", "assert", "certain"]):
                        cat = "emphasis"
                    elif any(x in meaning for x in ["感歎", "驚訝", "驚嘆", "exclamation", "嘆詞"]):
                        cat = "exclamation"
                    else:
                        cat = "tone marker"
                    sfp_label_parts.append(f"{char}: {cat}")
                meaning_tag = f" ({'; '.join(sfp_label_parts)})" if sfp_label_parts else ""

                processed = {}
                for name, output in translations.items():
                    if name == "google":
                        processed[name] = semantic_postprocess(output, stype, sfps, sentiment)
                    else:
                        processed[name] = output
                update_live_progress(progress_state, 0.75, "Applied semantic post-processing")

                try:
                    chosen_api, _ = choose_api(
                        stype,
                        sfps,
                        model,
                        encs,
                        translations=translations,
                        text=text_for_lookup,
                        local_is_authoritative=local_is_authoritative,
                    )
                except Exception:
                    chosen_api = None
                update_live_progress(progress_state, 0.85, "Selected best translation route")

                if replacement_notes:
                    st.info("粗口正規化: " + ", ".join(replacement_notes))

                if sfps:
                    sfp_tags = ", ".join([f"{p.get('character', '')}" for p in sfps if p.get("character")])
                    if sfp_tags:
                        st.markdown(f"**助語詞標籤 SFP tags:** {sfp_tags}")

                st.markdown("**混合翻譯結果 Combined translation results**")
                if "opus-mt" in processed:
                    st.markdown(f"**Opus-MT:** {sentiment_tag}{processed['opus-mt']}{meaning_tag}")
                if marianmt_output:
                    st.markdown(f"**MarianMT:** {sentiment_tag}{marianmt_output}{meaning_tag}")
                if "google" in processed:
                    st.markdown(f"**Google translate:** {sentiment_tag}{processed['google']}{meaning_tag}")
                if "mymemory" in processed:
                    st.markdown(f"**MyMemory:** {sentiment_tag}{processed['mymemory']}{meaning_tag}")

                local_hits, local_mode = collect_local_source_candidates(text_for_lookup, limit=3, fuzzy_threshold=90.0)
                st.markdown("**本地來源（已使用資料）:**")
                if local_hits:
                    if local_mode == "fallback_top3":
                        st.markdown("*(未找到 >=90 分匹配，以下為最相似 Top 3)*")
                    for idx, hit in enumerate(local_hits, start=1):
                        token = hit.get("token", "")
                        translation = hit.get("translation", "")
                        source_label = hit.get("source_label", "local")
                        score = float(hit.get("score", 0.0))
                        match_type = hit.get("match_type", "exact")
                        if match_type == "fuzzy":
                            st.markdown(
                                f"{idx}. {translation} - {token} ({source_label}, fuzzy {score:.1f})"
                            )
                        else:
                            st.markdown(f"{idx}. {translation} - {token} ({source_label})")
                else:
                    st.markdown("*(沒有找到本地匹配 no local match found)*")
                update_live_progress(progress_state, 0.95, "Rendered combined search output")

                final_trans = ""
                if chosen_api:
                    if chosen_api == "local":
                        final_trans = local_translation
                    else:
                        final_trans = processed.get(chosen_api, "")
                    st.markdown(
                        f":blue-background[**已選翻譯({_format_api_name(chosen_api)}):** {sentiment_tag}{final_trans}{meaning_tag}]"
                    )
                    st.write("")

                if not final_trans:
                    final_trans = local_translation or ""
                history_output = _build_history_output(
                    trial_kind="foul_combined",
                    api_name=chosen_api or "unknown",
                    final_translation=final_trans,
                    replacement_notes=replacement_notes,
                )
                log_history(combined_input, history_output)

                actual_seconds = time.perf_counter() - started_at
                speed_mbps = measure_internet_speed_mbps()
                if speed_mbps is None:
                    st.caption(f"預計需時: {est_seconds:.1f}s | 實際需時: {actual_seconds:.2f}s | 網絡速度: 未能測量")
                else:
                    st.caption(f"預計需時: {est_seconds:.1f}s | 實際需時: {actual_seconds:.2f}s | 網絡速度: ~{speed_mbps:.2f} Mbps")
                finish_live_progress(progress_state, "Combined search completed")
                st.session_state["foul_combined_processing"] = False

    if st.button("🔙 返回"):
        st.session_state.page = "home"


def page_background():
    st.header("📘 背景資訊")
    md_path = os.path.join(PROJECT_ROOT, "BACKGROUND.md")
    if not os.path.exists(md_path):
        md_path = os.path.join(DATA_DIR, "BACKGROUND.md")
    content = None
    try:
        if os.path.exists(md_path):
            with open(md_path, "r", encoding="utf-8") as f:
                content = f.read()
    except Exception:
        content = None

    if content:
        st.markdown(content, unsafe_allow_html=True)
    else:
        st.write("背景資訊不可用。請新增 BACKGROUND.md 檔案。")

    img_path = os.path.join(PROJECT_ROOT, "assets", "placeholder.svg")
    if os.path.exists(img_path):
        try:
            st.image(img_path)
        except Exception:
            pass

    if st.button("🔙 返回"):
        st.session_state.page = "home"


def page_ack():
    st.header("🙏 鳴謝")
    md_path = os.path.join(PROJECT_ROOT, "ACKNOWLEDGMENTS.md")
    if not os.path.exists(md_path):
        md_path = os.path.join(DATA_DIR, "ACKNOWLEDGMENTS.md")
    content = None
    try:
        if os.path.exists(md_path):
            with open(md_path, "r", encoding="utf-8") as f:
                content = f.read()
    except Exception:
        content = None

    if content:
        st.markdown(content, unsafe_allow_html=True)
    else:
        st.write("鳴謝內容不可用。請在專案根目錄加入 ACKNOWLEDGMENTS.md。")

    if st.button("🔙 返回"):
        st.session_state.page = "home"


def page_settings():
    st.header("⚙️ 設定")
    use_fuzzy = st.checkbox("容許模糊匹配", value=st.session_state.get("use_fuzzy", True))
    st.session_state["use_fuzzy"] = use_fuzzy

    use_sent = st.checkbox("顯示情感標籤", value=st.session_state.get("use_sentiment", True))
    st.session_state["use_sentiment"] = use_sent

    allow_simp = st.checkbox("容許簡體輸入 (自動轉換)", value=st.session_state.get("allow_simplified", False))
    if allow_simp and not st.session_state.get("allow_simplified_confirmed", False):
        st.warning("容許簡體輸入會降低翻譯準確度，要繼續嗎？")
        col1, col2 = st.columns(2)
        if col1.button("繼續"):
            st.session_state["allow_simplified"] = True
            st.session_state["allow_simplified_confirmed"] = True
            safe_rerun()
        if col2.button("取消"):
            st.session_state["allow_simplified"] = False
            st.session_state["allow_simplified_confirmed"] = False
            safe_rerun()
    else:
        st.session_state["allow_simplified"] = allow_simp

    st.caption("語音辨識固定使用後端 /speech_to_text。")

    if st.button("Train model"):
        model, encs = init_model()
        retrain_model(model, encs)
        hint = compute_feedback_weight_suggestion()
        log_history("settings", "[model_training] retrain_model", event_type="model_training")
        st.success("隨機森林模型訓練完成。")

        old_weights = hint.get("old", {}) if isinstance(hint, dict) else {}
        new_weights = hint.get("new", {}) if isinstance(hint, dict) else {}
        apis = sorted(set(list(old_weights.keys()) + list(new_weights.keys())))
        if apis:
            rows = []
            for api_name in apis:
                old_v = float(old_weights.get(api_name, 0.0))
                new_v = float(new_weights.get(api_name, old_v))
                rows.append(
                    {
                        "api": api_name,
                        "old_weight": round(old_v, 2),
                        "new_weight": round(new_v, 2),
                        "delta": round(new_v - old_v, 2),
                    }
                )
            st.markdown("**API 權重建議（訓練後）**")
            st.dataframe(pd.DataFrame(rows))

        if hint.get("suggestion_line"):
            st.info(hint.get("suggestion_line"))
        elif hint.get("message"):
            st.caption(hint.get("message"))

    st.subheader("進階搜尋設定")

    ollama_model = st.text_input(
        "Ollama 模型",
        value=st.session_state.get("ollama_model", "qwen2.5:7b"),
    )
    st.session_state["ollama_model"] = ollama_model.strip() or "qwen2.5:7b"

    ollama_url = st.text_input(
        "Ollama 伺服器網址",
        value=st.session_state.get("ollama_url", "http://localhost:11434"),
    )
    st.session_state["ollama_url"] = ollama_url.strip() or "http://localhost:11434"
    os.environ["OLLAMA_URL"] = st.session_state["ollama_url"]

    st.caption("OpenAI 僅供海外用戶使用。")
    use_openai = st.toggle(
        "OpenAI 進階搜尋（僅供海外用戶）",
        value=st.session_state.get("use_openai_advanced", False),
    )
    st.session_state["use_openai_advanced"] = use_openai

    if use_openai:
        openai_key = st.text_input(
            "OpenAI API 金鑰",
            value=st.session_state.get("openai_api_key", ""),
            type="password",
            placeholder="sk-...",
        )
        st.session_state["openai_api_key"] = openai_key.strip()

        openai_model = st.text_input(
            "OpenAI 模型",
            value=st.session_state.get("openai_model", "gpt-4o-mini"),
        )
        st.session_state["openai_model"] = openai_model.strip() or "gpt-4o-mini"

    prev_theme = st.session_state.get("bg_theme", "poly紅")
    theme = st.selectbox(
        "背景主題",
        ["光", "暗", "poly紅", "海軍藍"],
        index={"光": 0, "暗": 1, "poly紅": 2, "海軍藍": 3}.get(prev_theme, 2),
    )

    if theme != prev_theme:
        st.session_state["bg_theme"] = theme
        apply_background(theme)
        safe_rerun()
    else:
        st.session_state["bg_theme"] = theme

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<a href="https://forms.gle/s2H8EiFEyTwbVzeq7" target="_blank"><button>開啟回饋表單</button></a>', unsafe_allow_html=True)

    if st.button("🔙 返回"):
        st.session_state.page = "home"


def page_history():
    st.header("🕘 翻譯紀錄 (最近 100 項)")
    df = read_history()
    if not df.empty:
        st.dataframe(df.sort_values("time", ascending=False).head(100))
    else:
        st.info("尚無紀錄。")
    if st.button("🔙 返回"):
        st.session_state.page = "home"


def run_app():
    pages = {
        "home": main_page,
        "sfp": page_sfp,
        "foul": page_foul,
        "background": page_background,
        "ack": page_ack,
        "settings": page_settings,
        "history": page_history,
    }
    if "page" not in st.session_state:
        st.session_state.page = "home"

    st.session_state.setdefault("bg_theme", "Brick Red")
    apply_background(st.session_state.get("bg_theme", "Brick Red"))

    st.sidebar.title("導覽")
    if st.sidebar.button("🏠 主頁"):
        st.session_state.page = "home"
    if st.sidebar.button("📗 助語詞字典"):
        st.session_state.page = "sfp"
    if st.sidebar.button("💢 粗口"):
        st.session_state.page = "foul"
    if st.sidebar.button("📘 背景"):
        st.session_state.page = "background"
    if st.sidebar.button("🙏 鳴謝"):
        st.session_state.page = "ack"
    if st.sidebar.button("⚙️ 設定"):
        st.session_state.page = "settings"
    if st.sidebar.button("🕘 翻譯紀錄"):
        st.session_state.page = "history"

    page_fn = pages[st.session_state.page]
    page_fn()


def apply_background(theme: str):
    normalized = (theme or "light").strip().lower()

    if normalized in ("dark", "暗"):
        bg = "#0e1117"
        fg = "#e6edf3"
    elif normalized in ("poly紅", "brick red", "poly红"):
        bg = "#ffffff"
        fg = "#000000"
    elif normalized in ("海軍藍", "navy blue"):
        bg = "#034c94"
        fg = "#ffffff"
    else:
        bg = "#ffffff"
        fg = "#000000"

    css = f"""
    <style>
    body, .stApp {{ background-color: {bg} !important; color: {fg} !important; }}
    .stApp * {{ color: {fg} !important; }}
    .stSidebar, .css-1d391kg, .sidebar-content {{ background-color: {bg} !important; color: {fg} !important; }}
    .stCheckbox label, .stCheckbox div, .stCheckbox {{ color: {fg} !important; }}
    .stRadio label, .stSelectbox label, .stText, .stCaption, .stMarkdown, .stMetric {{ color: {fg} !important; }}
    a, a:hover, button, .stButton button {{ color: {fg} !important; }}

    /* Keep advanced-search expander and criteria inputs white with black frame */
    .streamlit-expanderHeader, .streamlit-expanderContent, div[data-testid="stExpander"] {{
        background-color: #ffffff !important;
        color: #000000 !important;
        border: 1px solid #000000 !important;
    }}
    div[data-baseweb="select"] > div,
    div[data-baseweb="select"] > div:focus,
    div[data-baseweb="select"] > div:active,
    div[data-baseweb="select"] > div[aria-expanded="true"] {{
        background-color: #ffffff !important;
        color: #000000 !important;
        border: 1px solid #000000 !important;
        box-shadow: none !important;
    }}
    div[data-baseweb="popover"] * {{
        background-color: #ffffff !important;
        color: #000000 !important;
    }}
    """

    if normalized in ("light", "光"):
        gry_bg = "#808080"
        css += f"""
        .stSidebar {{ background-color: {gry_bg} !important; color: #ffffff !important; }}
        .stSidebar h1, .stSidebar h2, .stSidebar .css-1d391kg, .stSidebar .css-1v3fvcr, .stSidebar .stMarkdown {{ color: #ffffff !important; }}
        header, .stApp > header {{ background-color: {gry_bg} !important; color: #ffffff !important; }}
        header h1, header h2, header h3 {{ color: #ffffff !important; }}
        input[type='text'], textarea, .stTextInput input, .stTextInput textarea {{ background-color: #ffffff !important; color: #000000 !important; border: 1px solid #000000 !important; }}
        .stSidebar .stButton > button, .stSidebar button {{ background-color: #ffffff !important; color: #000000 !important; border: 1px solid #000000 !important; }}
        .stButton > button, button {{ background-color: #ffffff !important; color: #000000 !important; border: 1px solid #000000 !important; }}
        .stCheckbox label, .stCheckbox div, .stCheckbox {{ color: #000000 !important; }}
        .stSelectbox, .stSelectbox > div, .stSelectbox *, .stSelectbox div[role='listbox'], .stSelectbox select, .stSelectbox .css-1v3fvcr {{ color: #000000 !important; }}
        select, select option {{ color: #000000 !important; }}
        """

    if normalized in ("poly紅", "brick red", "poly红"):
        nav_bg = "#8F1329"
        css += f"""
        .stSidebar {{ background-color: {nav_bg} !important; color: #ffffff !important; }}
        .stSidebar h1, .stSidebar h2, .stSidebar .css-1d391kg, .stSidebar .css-1v3fvcr, .stSidebar .stMarkdown {{ color: #ffffff !important; }}
        header, .stApp > header {{ background-color: {nav_bg} !important; color: #ffffff !important; }}
        header h1, header h2, header h3 {{ color: #ffffff !important; }}
        input[type='text'], textarea, .stTextInput input, .stTextInput textarea {{ background-color: #ffffff !important; color: #000000 !important; border: 1px solid #000000 !important; }}
        .stSidebar .stButton > button, .stSidebar button {{ background-color: #ffffff !important; color: #000000 !important; border: 1px solid #000000 !important; }}
        .stButton > button, button {{ background-color: #ffffff !important; color: #000000 !important; border: 1px solid #000000 !important; }}
        .stCheckbox label, .stCheckbox div, .stCheckbox {{ color: #000000 !important; }}
        .stSelectbox, .stSelectbox > div, .stSelectbox *, .stSelectbox div[role='listbox'], .stSelectbox select, .stSelectbox .css-1v3fvcr {{ color: #000000 !important; }}
        select, select option {{ color: #000000 !important; }}
        """

    css += "</style>"

    try:
        st.markdown(css, unsafe_allow_html=True)
    except Exception:
        pass


def safe_rerun():
    rerun_fn = getattr(st, "experimental_rerun", None)
    if callable(rerun_fn):
        try:
            rerun_fn()
            return
        except Exception:
            pass

    try:
        from streamlit.runtime.scriptrunner import RerunException

        raise RerunException()
    except Exception:
        try:
            st.session_state["_needs_rerun"] = True
        except Exception:
            pass
        st.stop()


if __name__ == "__main__":
    run_app()