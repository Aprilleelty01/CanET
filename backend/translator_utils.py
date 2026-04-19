import os
import pickle
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from functools import lru_cache

import joblib
import pandas as pd
import stanza
import json
import urllib.parse
import urllib.request
import urllib.error
from openai import OpenAI
from opencc import OpenCC
from rapidfuzz import fuzz, process
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
from sklearn.preprocessing import LabelEncoder
from transformers import MarianMTModel, MarianTokenizer, pipeline

try:
    from deep_translator import GoogleTranslator as _GoogleTranslator
    _google_translator_available = True
except Exception:
    _google_translator_available = False

try:
    from deep_translator import MyMemoryTranslator as _MyMemoryTranslator
    _mymemory_available = True
except Exception:
    _mymemory_available = False

try:
    from deep_translator import DeeplTranslator as _DeeplTranslator
    _deepl_available = True
except Exception:
    _deepl_available = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(BASE_DIR, "data")


def _existing_or_default(candidates, default):
    for path in candidates:
        if os.path.exists(path):
            return path
    return default


EXCEL_FILE = os.path.join(DATA_DIR, "jyutping_dict.xlsx")
FOUL_FILE = os.path.join(DATA_DIR, "foul.xlsx")

DATA_FILE = _existing_or_default(
    [
        os.path.join(PROJECT_ROOT, "user_feedback.csv"),
        os.path.join(BASE_DIR, "user_feedback.csv"),
    ],
    os.path.join(PROJECT_ROOT, "user_feedback.csv"),
)
ENCODERS_FILE = _existing_or_default(
    [
        os.path.join(PROJECT_ROOT, "label_encoders.pkl"),
        os.path.join(BASE_DIR, "label_encoders.pkl"),
    ],
    os.path.join(PROJECT_ROOT, "label_encoders.pkl"),
)
MODEL_FILE = _existing_or_default(
    [
        os.path.join(PROJECT_ROOT, "rf_model.pkl"),
        os.path.join(BASE_DIR, "rf_model.pkl"),
    ],
    os.path.join(PROJECT_ROOT, "rf_model.pkl"),
)
HISTORY_FILE = _existing_or_default(
    [
        os.path.join(PROJECT_ROOT, "history.csv"),
        os.path.join(BASE_DIR, "history.csv"),
    ],
    os.path.join(PROJECT_ROOT, "history.csv"),
)


cc_s2t = OpenCC("s2t")
cc_t2s = OpenCC("t2s")


@lru_cache(maxsize=None)
def load_dictionary(filepath=EXCEL_FILE):
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Cannot find Excel file: {filepath}")

    excel = pd.ExcelFile(filepath)
    sheets = excel.sheet_names

    df_sfp = pd.read_excel(filepath, sheet_name="SFP")
    df_sfp.columns = [c.strip().lower() for c in df_sfp.columns]
    sfp_dict = {}
    for _, row in df_sfp.iterrows():
        key = str(row.get("text", "")).strip()
        if key:
            sfp_dict[key] = {
                "jyutping": str(row.get("jyutping", "")).strip(),
                "engpinyin": str(row.get("engpinyin", "")).strip(),
                "meaning": str(row.get("meaning/ example", "")).strip() or str(row.get("meaning", "")).strip(),
            }

    phrase_bank = {}
    for name in sheets:
        if name.lower() == "sfp":
            continue
        try:
            df = pd.read_excel(filepath, sheet_name=name)
            df.columns = [c.strip().lower() for c in df.columns]
            for _, row in df.iterrows():
                text = str(row.get("text", "")).strip()
                trans = str(row.get("translation", "")).strip()
                jyut = str(row.get("jyutping", "")).strip() if "jyutping" in df.columns else ""
                abbr = str(row.get("abbreviation", "")).strip() if "abbreviation" in df.columns else ""
                meaning = str(row.get("meaning", "")).strip()
                if text:
                    entry = {
                        "translation": trans,
                        "jyutping": jyut,
                        "meaning": meaning,
                        "source_sheet": name,
                    }
                    phrase_bank.setdefault(text, []).append(entry)
                    if abbr:
                        phrase_bank.setdefault(abbr, []).append(entry)
        except Exception as e:
            print(f"⚠️ Cannot load sheet '{name}': {e}")
    return sfp_dict, phrase_bank, sheets


@lru_cache(maxsize=None)
def load_foul(filepath=FOUL_FILE):
    if not os.path.exists(filepath):
        return [], {}
    try:
        df = pd.read_excel(filepath)
        col_map = {col.lower().strip(): col for col in df.columns}

        canonical_col = col_map.get("chinese characters")
        variations_col = col_map.get("variations")
        literal_col = col_map.get("literal meaning")
        translation_col = col_map.get("translation")

        if not all([canonical_col, variations_col, literal_col, translation_col]):
            return [], {}

        rows = []
        var_map = {}
        for _, row in df.iterrows():
            canonical = str(row[canonical_col]).strip() if not pd.isna(row[canonical_col]) else ""
            variations_cell = str(row[variations_col]) if not pd.isna(row[variations_col]) else ""
            literal = str(row[literal_col]) if not pd.isna(row[literal_col]) else ""
            desired = str(row[translation_col]) if not pd.isna(row[translation_col]) else ""

            if not canonical:
                continue

            parts = [p.strip() for p in re.split(r"[、\,;|/\\]", variations_cell) if p.strip()]
            item = {
                "canonical": canonical,
                "variations": parts,
                "literal": literal,
                "desired": desired,
            }
            rows.append(item)
            for part in parts:
                var_map[part] = item
        return rows, var_map
    except Exception:
        return [], {}


@lru_cache(maxsize=None)
def load_corpus(filepath="cantonese_corpus.xlsm"):
    corpus_path = os.path.join(DATA_DIR, filepath)
    if not os.path.exists(corpus_path):
        return pd.DataFrame()

    try:
        df = pd.read_excel(corpus_path)
        df.columns = [c.strip().lower() for c in df.columns]
        return df
    except Exception as e:
        print(f"⚠️ Failed to load corpus: {e}")
        return pd.DataFrame()


def search_by_tags(emotion_tags=None, attitude_tags=None, relationship_tags=None):
    df = load_corpus()
    if df.empty:
        return df

    def matches_tags(cell, selected_tags):
        if not selected_tags:
            return True
        if pd.isna(cell):
            return False
        cell_str = str(cell).lower()
        cell_tags = [t.strip() for t in re.split(r"[;,/，、]", cell_str) if t.strip()]
        return any(tag.lower() in cell_tags for tag in selected_tags)

    mask = pd.Series([True] * len(df))

    if emotion_tags:
        mask &= df["emotion"].apply(lambda x: matches_tags(x, emotion_tags))
    if attitude_tags:
        mask &= df["attitude"].apply(lambda x: matches_tags(x, attitude_tags))
    if relationship_tags:
        mask &= df["relationship"].apply(lambda x: matches_tags(x, relationship_tags))

    return df[mask]


def log_feedback(entry, filepath=DATA_FILE):
    new = pd.DataFrame([entry])
    if os.path.exists(filepath):
        try:
            df = pd.read_csv(filepath)
        except pd.errors.EmptyDataError:
            df = pd.DataFrame(columns=["clause", "sentence_type", "best_api"])

        for col in ["clause", "best_api"]:
            if col not in df.columns:
                df[col] = pd.NA

        dup = False
        if not df.empty and "clause" in df.columns and "best_api" in df.columns:
            dup = ((df["clause"] == entry["clause"]) & (df["best_api"] == entry["best_api"])).any()

        if dup:
            print("⚠️ 反饋已存在，跳過重複項。")
            return
        df = pd.concat([df, new], ignore_index=True)
    else:
        df = new

    df.to_csv(filepath, index=False)
    print("✅ 反饋已儲存！")


def log_history(
    inp,
    outp,
    filepath=HISTORY_FILE,
    event_type="translation",
    feedback_api="",
    feedback_sentence_type="",
):
    row = pd.DataFrame([
        {
            "input": inp,
            "output": outp,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "event_type": str(event_type or "translation").strip() or "translation",
            "feedback_api": str(feedback_api or "").strip(),
            "feedback_sentence_type": str(feedback_sentence_type or "").strip(),
        }
    ])
    if os.path.exists(filepath):
        try:
            df = pd.read_csv(filepath)
        except pd.errors.EmptyDataError:
            df = row.copy()
        else:
            df = pd.concat([df, row], ignore_index=True).tail(1000)
    else:
        df = row
    df.to_csv(filepath, index=False)


def read_history(filepath=HISTORY_FILE):
    if not os.path.exists(filepath):
        return pd.DataFrame(
            columns=["input", "output", "time", "event_type", "feedback_api", "feedback_sentence_type"]
        )
    try:
        return pd.read_csv(filepath)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(
            columns=["input", "output", "time", "event_type", "feedback_api", "feedback_sentence_type"]
        )


def compute_feedback_weight_suggestion(
    default_weights=None,
    feedback_path=DATA_FILE,
    min_feedback_rows=3,
):
    """
    Build a simple weight-adjustment hint from user feedback distribution.
    The suggestion is intended for `api_weight_map` in the Streamlit UI.
    """
    if default_weights is None:
        default_weights = {
            "google": 0.28,
            "opus-mt": 0.25,
            "mymemory": 0.15,
            "lm": 0.10,
        }

    tracked = [k for k in default_weights.keys()]
    old_total = float(sum(float(v) for v in default_weights.values()))
    if old_total <= 0:
        return {
            "ready": False,
            "message": "目前預設權重無效，無法產生建議。",
            "suggestion_line": "",
            "old": dict(default_weights),
            "new": dict(default_weights),
        }

    if (not os.path.exists(feedback_path)):
        return {
            "ready": False,
            "message": "未找到 feedback 資料檔，先累積回饋後再訓練。",
            "suggestion_line": "",
            "old": dict(default_weights),
            "new": dict(default_weights),
        }

    try:
        df = pd.read_csv(feedback_path)
    except Exception:
        return {
            "ready": False,
            "message": "feedback 資料讀取失敗，暫時無法產生建議。",
            "suggestion_line": "",
            "old": dict(default_weights),
            "new": dict(default_weights),
        }

    if df.empty or "best_api" not in df.columns:
        return {
            "ready": False,
            "message": "feedback 資料不足，暫時無法產生建議。",
            "suggestion_line": "",
            "old": dict(default_weights),
            "new": dict(default_weights),
        }

    work = df.copy()
    work["best_api"] = work["best_api"].fillna("").astype(str).str.strip().str.lower()
    work = work[work["best_api"].isin(tracked)]
    if len(work) < int(min_feedback_rows):
        return {
            "ready": False,
            "message": f"feedback 需要至少 {min_feedback_rows} 筆，目前只有 {len(work)} 筆。",
            "suggestion_line": "",
            "old": dict(default_weights),
            "new": dict(default_weights),
        }

    counts = work["best_api"].value_counts().to_dict()
    total = float(sum(counts.values())) or 1.0

    target = {api: (counts.get(api, 0.0) / total) * old_total for api in tracked}

    # Smooth update: 70% keep current baseline, 30% move to observed distribution.
    blended = {
        api: (float(default_weights.get(api, 0.0)) * 0.70) + (float(target.get(api, 0.0)) * 0.30)
        for api in tracked
    }
    blended_total = float(sum(blended.values())) or 1.0
    scaled = {api: (val / blended_total) * old_total for api, val in blended.items()}
    rounded = {api: round(float(v), 2) for api, v in scaled.items()}

    changed_parts = []
    for api in tracked:
        old_v = round(float(default_weights.get(api, 0.0)), 2)
        new_v = round(float(rounded.get(api, old_v)), 2)
        if abs(new_v - old_v) >= 0.01:
            changed_parts.append(f"({api}): {old_v:.2f} --> {new_v:.2f}")

    if not changed_parts:
        return {
            "ready": True,
            "message": "模型已訓練，現有 feedback 未顯示明顯權重偏移。",
            "suggestion_line": "",
            "old": dict(default_weights),
            "new": dict(rounded),
        }

    suggestion_line = (
        "建議打開 /webpage 內的 /streamlit_app.py 尋找/api_weight_map 修改成以下數值: "
        + "; ".join(changed_parts)
    )
    return {
        "ready": True,
        "message": "模型已訓練，已根據 feedback 產生權重調整建議。",
        "suggestion_line": suggestion_line,
        "old": dict(default_weights),
        "new": dict(rounded),
    }


@lru_cache(maxsize=None)
def load_lm_model():
    tok = MarianTokenizer.from_pretrained("Helsinki-NLP/opus-mt-zh-en")
    mdl = MarianMTModel.from_pretrained("Helsinki-NLP/opus-mt-zh-en")
    return tok, mdl


@lru_cache(maxsize=None)
def load_stanza():
    stanza.download("zh", processors="tokenize,pos")
    return stanza.Pipeline("zh", processors="tokenize,pos", use_gpu=False)


@lru_cache(maxsize=None)
def load_sentiment():
    return pipeline("sentiment-analysis", model="uer/roberta-base-finetuned-jd-binary-chinese")


def translate_opusmt(text):
    try:
        tok, mdl = load_lm_model()
        batch = tok([text], return_tensors="pt", padding=True)
        gen = mdl.generate(**batch, max_new_tokens=100)
        return tok.decode(gen[0], skip_special_tokens=True)
    except Exception as e:
        return f"[OPUS-MT Error] {e}"


def translate_lm(text):
    tok, mdl = load_lm_model()
    batch = tok([text], return_tensors="pt", padding=True)
    gen = mdl.generate(**batch, max_new_tokens=100)
    return tok.decode(gen[0], skip_special_tokens=True)


def init_model():
    encs = {"sentence_type": LabelEncoder(), "best_api": LabelEncoder()}

    if os.path.exists(ENCODERS_FILE):
        try:
            with open(ENCODERS_FILE, "rb") as f:
                encs = pickle.load(f)
        except Exception:
            encs = {"sentence_type": LabelEncoder(), "best_api": LabelEncoder()}

    try:
        encs["best_api"].fit(["google", "deepl", "mymemory", "opus-mt", "local", "lm"])
    except Exception:
        encs["best_api"] = LabelEncoder()
        encs["best_api"].fit(["google", "deepl", "mymemory", "opus-mt", "local", "lm"])

    if os.path.exists(MODEL_FILE):
        try:
            with open(MODEL_FILE, "rb") as f:
                model = pickle.load(f)
        except Exception:
            model = RandomForestClassifier(n_estimators=50, random_state=42)
    else:
        model = RandomForestClassifier(n_estimators=50, random_state=42)

    return model, encs


def retrain_model(model, encs):
    if os.path.exists(DATA_FILE):
        try:
            df = pd.read_csv(DATA_FILE)
        except Exception:
            df = pd.DataFrame(columns=["clause", "sentence_type", "best_api"])
    else:
        df = pd.DataFrame(columns=["clause", "sentence_type", "best_api"])

    if len(df) < 3:
        try:
            with open(MODEL_FILE, "wb") as f:
                pickle.dump(model, f)
            with open(ENCODERS_FILE, "wb") as f:
                pickle.dump(encs, f)
        except Exception:
            pass
        return model

    encs["sentence_type"].fit(df["sentence_type"].astype(str))
    encs["best_api"].fit(df["best_api"].astype(str))

    X = encs["sentence_type"].transform(df["sentence_type"].astype(str)).reshape(-1, 1)
    y = encs["best_api"].transform(df["best_api"].astype(str))

    model.fit(X, y)
    try:
        with open(MODEL_FILE, "wb") as f:
            pickle.dump(model, f)
        with open(ENCODERS_FILE, "wb") as f:
            pickle.dump(encs, f)
    except Exception:
        pass
    return model


def evaluate_model(model, encs):
    if not os.path.exists(DATA_FILE):
        return None
    try:
        df = pd.read_csv(DATA_FILE)
    except pd.errors.EmptyDataError:
        return None

    if df.empty:
        return None

    X = encs["sentence_type"].transform(df["sentence_type"])
    y_true = encs["best_api"].transform(df["best_api"])
    preds = model.predict(X.reshape(-1, 1))
    acc = accuracy_score(y_true, preds)
    return round(acc * 100, 2)


CLASSIFIER_SFPS = sorted([
    "吖", "呀", "呀嘛", "啦", "喇", "喇喂", "㗎喇", "嘞", "吖嗱", "囉", "咯", "嚛",
    "呢", "㗎", "哩", "㗎啦", "嗰喎", "啫", "吒嘛", "喎", "咋", "㗎咋", "嘅", "既",
    "既咩", "咩", "𠺢嘛", "𠿪", "噃", "㗎喇可", "㗎噃", "啩", "吖嘛", "添", "添㗎",
    "先", "嚟", "吓哇", "lu", "嗱", "㗎咋噃", "㗎咋喎", "啊", "咧", "既啫", "㗎喎", "le",
    "咩呀", "吓",
], key=len, reverse=True)

NEGATION_WORDS = ["唔", "冇", "未", "無", "莫"]
VERB_WORDS = ["食", "飲", "去", "返", "瞓", "睇", "講", "等", "諗", "玩"]
NOUN_WORDS = ["我", "你", "佢", "媽咪", "老豆", "朋友", "學校", "公司", "老師", "時間"]
ADJ_WORDS = ["開心", "快樂", "唔錯", "靚", "驚", "大", "細", "好", "差", "正"]

EMOTION_OPTIONS = [
    "sadness", "fear", "neutral", "surprised", "love",
    "anger", "joy", "expect", "worry", "excited",
]
ATTITUDE_OPTIONS = [
    "respectful", "non-respectful", "irony", "playful", "mockery", "warning", "certain",
]
RELATIONSHIP_OPTIONS = [
    "family", "friends", "hierarchical", "professional", "not good", "strangers",
]


def guess_word_type(char):
    if any(w in char for w in VERB_WORDS):
        return "verb"
    if any(w in char for w in NOUN_WORDS):
        return "noun"
    if any(w in char for w in ADJ_WORDS):
        return "adj"
    return "other"


def extract_longest_sfp(text):
    for sfp in CLASSIFIER_SFPS:
        if sfp in text:
            return sfp
    return None


def extract_features(sentence):
    row = {}
    longest = extract_longest_sfp(sentence)
    if longest:
        row["sfp_list"] = longest
        row["num_sfp"] = len(longest)
        row["multiple_sfp"] = 1 if sentence.count(longest) > 1 else 0
        row["sfp_distance_end"] = len(sentence) - (sentence.find(longest) + len(longest))
        idx = sentence.find(longest)
        prev_char = sentence[max(0, idx - 1):idx]
        row["sfp_pos"] = guess_word_type(prev_char)
        row["main_pos_pattern"] = f"{row['sfp_pos']}-sfp"
    else:
        row["sfp_list"] = ""
        row["num_sfp"] = 0
        row["multiple_sfp"] = 0
        row["sfp_distance_end"] = -1
        row["sfp_pos"] = "none"
        row["main_pos_pattern"] = "none"

    row["negation_present"] = 1 if any(n in sentence for n in NEGATION_WORDS) else 0

    if "咩" in sentence or "嗎" in sentence:
        stype = "question"
    elif any(a in sentence for a in ["快啲", "唔好", "要", "畀我"]):
        stype = "command"
    elif any(a in sentence for a in ["開心", "驚", "嬲", "鍾意", "愛", "笑"]):
        stype = "emotion"
    else:
        stype = "statement"

    row["sentence_type_guess"] = stype
    row["emotion_marker_present"] = 1 if stype == "emotion" else 0
    return row


@lru_cache(maxsize=None)
def load_classifiers():
    model_dir = os.path.join(BASE_DIR, "models")
    combined_path = os.path.join(model_dir, "combined_ear_classifier.pkl")
    if os.path.exists(combined_path):
        try:
            return {"combined": joblib.load(combined_path)}
        except Exception as e:
            print(f"⚠️ Failed to load combined classifier: {e}")

    model_paths = {
        "emotion": os.path.join(model_dir, "emotion_classifier.pkl"),
        "attitude": os.path.join(model_dir, "attitude_classifier.pkl"),
        "relationship": os.path.join(model_dir, "relationship_classifier.pkl"),
    }

    if not all(os.path.exists(path) for path in model_paths.values()):
        return None

    try:
        return {name: joblib.load(path) for name, path in model_paths.items()}
    except Exception as e:
        print(f"⚠️ Failed to load classifiers: {e}")
        return None


def decode_combined_label(label):
    parts = str(label).split("|||")
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    return str(label), "", ""


def analyse_sentence(sentence):
    classifiers = load_classifiers()
    if not classifiers:
        return None

    try:
        feat = extract_features(sentence)
        X = pd.DataFrame([feat])
        if "combined" in classifiers:
            pred = str(classifiers["combined"].predict(X)[0])
            emo, att, rel = decode_combined_label(pred)
            return {
                "emotion": emo,
                "attitude": att,
                "relationship": rel,
            }

        return {
            "emotion": str(classifiers["emotion"].predict(X)[0]),
            "attitude": str(classifiers["attitude"].predict(X)[0]),
            "relationship": str(classifiers["relationship"].predict(X)[0]),
        }
    except Exception as e:
        print(f"⚠️ Sentence tagging failed: {e}")
        return None


def pretty_tone_tag(label):
    if not label:
        return "Unknown"
    label_map = {
        "love": "Affection",
        "family": "Family",
        "friends": "Friends",
        "respectful": "Respectful",
        "non-respectful": "Non-respectful",
    }
    normalized = str(label).strip().lower()
    if normalized in label_map:
        return label_map[normalized]
    return str(label).replace("_", " ").replace("-", " ").strip().title()


def is_simplified_chinese(text: str) -> bool:
    if not text:
        return False
    if not any("\u4e00" <= ch <= "\u9fff" for ch in text):
        return False
    try:
        trad = cc_s2t.convert(text)
        back = cc_t2s.convert(trad)
        return back == text and trad != text
    except Exception:
        return False


def to_traditional_if_simplified(text: str) -> str:
    return cc_s2t.convert(text) if is_simplified_chinese(text) else text


def detect_sfp(text, sfp_dict):
    found = []
    for ch, props in sfp_dict.items():
        if ch in text:
            found.append(
                {
                    "character": ch,
                    "jyutping": props.get("jyutping", ""),
                    "engpinyin": props.get("engpinyin", ""),
                    "meaning": props.get("meaning", ""),
                }
            )
    return found


def sentence_type(text: str) -> str:
    t = text.strip()
    if t.startswith(("?!", "！？", "?! ", "！？ ", "？！", "?!", "？!", "!?", "！?")):
        return "exclamation_masked_as_question"
    if t.endswith(("?", "？")):
        return "question"
    if t.endswith(("!", "！")):
        return "exclamation"
    return "statement"


def refine_sentence_type_by_pos(text: str, stype: str) -> str:
    if stype in ("question", "exclamation", "exclamation_masked_as_question"):
        return stype

    try:
        nlp = load_stanza()
        doc = nlp(text)
        tokens = [w.text for s in doc.sentences for w in s.words]
        joined = "".join(tokens).lower()

        question_particles = {"嗎", "咩", "呢", "啦", "喇", "唔", "未", "吧", "吖", "喎"}
        question_words = {"誰", "誰人", "乜", "什麼", "甚麼", "點解", "為乜", "點樣", "邊", "邊個", "幾時", "幾多", "點"}

        if any(p in joined for p in question_particles) or any(q in joined for q in question_words):
            return "question"
    except Exception:
        return stype

    return stype


def translate_google(text):
    if not _google_translator_available:
        return "[Google Error] deep-translator package not available"
    try:
        return _GoogleTranslator(source="zh-CN", target="en").translate(text)
    except Exception as e:
        return f"[Google Error] {e}"


def translate_mymemory(text):
    if not _mymemory_available:
        return "[MyMemory Error] deep-translator package not available"

    # Preferred source is Cantonese (`yue`); fall back to Traditional Chinese (`zh-TW`).
    for source_lang in ("yue", "zh-TW"):
        try:
            result = _MyMemoryTranslator(source=source_lang, target="en-US").translate(text)
            if result:
                return result.strip("'\"")
        except Exception:
            continue

    return "[MyMemory Error] failed for both yue and zh-TW"


def translate_deepl(text):
    api_key = _get_deepl_api_key()
    if not api_key:
        return "[DeepL Error] DEEPL_API_KEY not set"

    # 1) direct HTTP API first (more reliable for :fx keys)
    try:
        out = _deepl_http_translate(text, api_key)
        if out:
            return out
    except Exception:
        pass

    # 2) fallback to deep-translator wrapper if available
    if _deepl_available:
        for source_lang in ("zh", "auto"):
            try:
                result = _DeeplTranslator(
                    api_key=api_key,
                    source=source_lang,
                    target="en-us",
                    use_free_api=api_key.endswith(":fx"),
                ).translate(text)
                if result:
                    return str(result).strip("'\"")
            except Exception:
                continue

    return "[DeepL Error] translation failed"


TRANSLATORS = {
    "opus-mt": translate_opusmt,
    "google": translate_google,
    "deepl": translate_deepl,
    "mymemory": translate_mymemory,
}


def sanitize_label(label):
    val = str(label or "").strip().lower()
    if not val:
        return "neutral"
    if "neg" in val or "sad" in val or "anger" in val or "fear" in val:
        return "negative"
    if "pos" in val or "joy" in val or "love" in val or "happy" in val:
        return "positive"
    if "neutral" in val:
        return "neutral"
    return val


def detect_sentiment(text):
    try:
        clf = load_sentiment()
        out = clf(text)
        if out and isinstance(out, list):
            return sanitize_label(out[0].get("label", "neutral"))
    except Exception:
        pass
    return "neutral"


def _pick_primary_entry(entries):
    if not entries:
        return None
    if isinstance(entries, list):
        return entries[0]
    return entries


def fuzzy_lookup(text, phrase_bank, use_fuzzy=True):
    raw = (text or "").strip()
    if not raw or not phrase_bank:
        return None, {"method": "none", "score": 0}, None

    if raw in phrase_bank:
        entry = _pick_primary_entry(phrase_bank.get(raw))
        trans = str((entry or {}).get("translation", "")).strip()
        source_sheet = str((entry or {}).get("source_sheet", "")).strip().lower()
        source_type = "exact_sentences" if source_sheet == "sentences" else "exact_phrase"
        return trans or None, {"method": "exact", "score": 100, "key": raw}, source_type

    if use_fuzzy:
        try:
            match = process.extractOne(raw, phrase_bank.keys(), scorer=fuzz.WRatio)
        except Exception:
            match = None
        if match:
            key, score, _ = match
            if score >= 85:
                entry = _pick_primary_entry(phrase_bank.get(key))
                trans = str((entry or {}).get("translation", "")).strip()
                source_sheet = str((entry or {}).get("source_sheet", "")).strip().lower()
                source_type = "exact_sentences" if source_sheet == "sentences" else "fuzzy"
                return trans or None, {"method": "fuzzy", "score": float(score), "key": key}, source_type

    return None, {"method": "none", "score": 0, "key": ""}, None


def longest_local_match(text, phrase_bank):
    raw = (text or "").strip()
    if not raw or not phrase_bank:
        return None, None, None

    best_key = None
    best_entry = None
    for key, entries in phrase_bank.items():
        if key and key in raw:
            if best_key is None or len(key) > len(best_key):
                best_key = key
                best_entry = _pick_primary_entry(entries)

    if not best_key or not best_entry:
        return None, None, None

    label = str(best_entry.get("source_sheet", "local"))
    trans = str(best_entry.get("translation", "")).strip() or None
    return best_key, trans, label


def is_in_corpus(text):
    raw = (text or "").strip()
    if not raw:
        return False
    df = load_corpus()
    if df.empty:
        return False

    for col in ("cantonese_text", "text"):
        if col in df.columns:
            series = df[col].fillna("").astype(str).str.strip()
            if (series == raw).any():
                return True
    return False


def refine_sentiment_by_sfp(sentiment, sfps):
    base = sanitize_label(sentiment)
    if not sfps:
        return base

    meanings = " ".join(str(p.get("meaning", "")).lower() for p in sfps)
    if "question" in meanings or "疑問" in meanings:
        return "neutral"
    if "soft" in meanings or "軟化" in meanings:
        return "neutral" if base == "negative" else base
    if "exclamation" in meanings or "感歎" in meanings or "驚嘆" in meanings:
        return "positive" if base == "neutral" else base
    return base


def semantic_postprocess(output, stype, sfps, sentiment):
    text = str(output or "").strip()
    if not text:
        return text

    if stype == "question":
        text = text.rstrip(".!") + "?"
    elif stype in ("exclamation", "exclamation_masked_as_question"):
        text = text.rstrip(".?") + "!"

    label = sanitize_label(sentiment)
    if label == "negative":
        text = text.replace("!", ".")
    return text


def _is_bad_translation(value):
    txt = str(value or "").strip()
    return (not txt) or txt.startswith("[") or txt.startswith("(")


def choose_api(stype, sfps, model, encs, translations=None, text="", local_is_authoritative=False):
    translations = translations or {}
    scores = {name: 0.0 for name in translations.keys()}

    if local_is_authoritative and "local" in translations and not _is_bad_translation(translations.get("local")):
        scores["local"] = 2.0
        return "local", {"scores": scores, "reason": "authoritative_local"}

    priority = ["deepl", "google", "opus-mt", "mymemory", "lm", "local"]
    if stype == "question":
        priority = ["google", "deepl", "opus-mt", "mymemory", "lm", "local"]

    for idx, name in enumerate(priority):
        if name in scores and not _is_bad_translation(translations.get(name)):
            scores[name] += (len(priority) - idx) / 10.0

    try:
        if model is not None and encs and "sentence_type" in encs and "best_api" in encs:
            x = encs["sentence_type"].transform([str(stype)]).reshape(-1, 1)
            pred_idx = model.predict(x)[0]
            pred = encs["best_api"].inverse_transform([pred_idx])[0]
            if pred in translations and not _is_bad_translation(translations.get(pred)):
                scores[pred] = scores.get(pred, 0.0) + 0.25
    except Exception:
        pass

    valid = [(name, score) for name, score in scores.items() if not _is_bad_translation(translations.get(name))]
    if valid:
        chosen = max(valid, key=lambda item: item[1])[0]
        return chosen, {"scores": scores, "reason": "scored"}

    if "opus-mt" in translations:
        return "opus-mt", {"scores": scores, "reason": "fallback"}
    return next(iter(translations.keys()), None), {"scores": scores, "reason": "empty"}


def rewrite_with_ollama(source_text, model_name="qwen2.5:7b"):
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    endpoint = f"{ollama_url}/api/generate"

    if not _ensure_ollama_server(ollama_url):
        return _ollama_fallback_translation(source_text)

    prompt = (
        "Translate this Cantonese sentence into natural English.\n"
        "Return only one line of English.\n\n"
        f"Cantonese: {source_text}"
    )

    payload = json.dumps({
        "model": model_name,
        "prompt": prompt,
        "stream": False,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return (data.get("response", "") or "").strip() or "(Ollama Error: empty response)"
    except urllib.error.URLError:
        return _ollama_fallback_translation(source_text)
    except Exception as e:
        return f"(Ollama Error: {e})"


def rewrite_with_openai_advanced(source_text, api_key, model_name="gpt-4o-mini"):
    if not api_key or not api_key.strip():
        return ""

    prompt = (
        "Translate this Cantonese sentence into natural English.\n"
        "Return exactly one concise translation only.\n\n"
        f"Cantonese: {source_text}"
    )

    try:
        client = OpenAI(api_key=api_key.strip())
        resp = client.chat.completions.create(
            model=(model_name or "gpt-4o-mini").strip(),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
        )
        msg = resp.choices[0].message.content if resp.choices else ""
        return (msg or "").strip()
    except Exception:
        return ""


def _get_deepl_api_key() -> str:
    key = os.getenv("DEEPL_API_KEY", "").strip()
    if key:
        return key
    try:
        return str(os.environ.get("DEEPL_API_KEY", "")).strip()
    except Exception:
        return ""


def _deepl_http_translate(text: str, api_key: str) -> str:
    # DeepL Free keys end with :fx and must use api-free endpoint
    is_free = api_key.endswith(":fx")
    endpoint = "https://api-free.deepl.com/v2/translate" if is_free else "https://api.deepl.com/v2/translate"

    payload = urllib.parse.urlencode(
        {
            "auth_key": api_key,
            "text": text,
            "target_lang": "EN-US",
            "source_lang": "ZH",
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=25) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        arr = data.get("translations", [])
        if arr and arr[0].get("text"):
            return str(arr[0]["text"]).strip()
    return ""


def _ollama_healthcheck(ollama_url: str, timeout: float = 1.5) -> bool:
    url = f"{ollama_url.rstrip('/')}/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _ensure_ollama_server(ollama_url: str) -> bool:
    if _ollama_healthcheck(ollama_url):
        return True

    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        return False

    # Give the daemon a short warm-up window, then retry health checks.
    for _ in range(6):
        time.sleep(0.5)
        if _ollama_healthcheck(ollama_url):
            return True

    return False


def _ollama_fallback_translation(source_text: str) -> str:
    fallback = translate_opusmt(source_text)
    if fallback and not str(fallback).startswith("["):
        return f"{fallback} (fallback: Opus-MT, Ollama unavailable)"
    return "(Ollama Error: local server unreachable. Start with `ollama serve` and ensure model is pulled.)"


def offline_recognizer(audio_bytes: bytes) -> str:
    """
    Offline speech recognizer powered by whisper.cpp CLI.

    Required environment variables:
    - WHISPER_CPP_MODEL: absolute path to ggml model file

    Optional environment variables:
    - WHISPER_CPP_BIN: whisper.cpp executable path/name (default: whisper-cli)
    - WHISPER_CPP_LANG: language code (default: yue)
    - WHISPER_CPP_EXTRA_ARGS: extra CLI args, space separated
    """
    if not audio_bytes:
        return ""

    model_path = os.getenv("WHISPER_CPP_MODEL", "").strip()
    if not model_path:
        raise RuntimeError("WHISPER_CPP_MODEL not set")
    if not os.path.exists(model_path):
        raise RuntimeError(f"model not found: {model_path}")

    bin_path = os.getenv("WHISPER_CPP_BIN", "whisper-cli").strip() or "whisper-cli"
    lang = os.getenv("WHISPER_CPP_LANG", "yue").strip() or "yue"
    extra_args = [arg for arg in os.getenv("WHISPER_CPP_EXTRA_ARGS", "").split() if arg]

    audio_path = ""
    txt_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
            f.write(audio_bytes)
            audio_path = f.name

        # whisper.cpp writes <audio_path>.txt when -otxt is enabled.
        txt_path = f"{audio_path}.txt"
        cmd = [
            bin_path,
            "-m",
            model_path,
            "-f",
            audio_path,
            "-l",
            lang,
            "-otxt",
            "-nt",
        ] + extra_args

        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )

        if proc.returncode != 0:
            err_msg = (proc.stderr or proc.stdout or "whisper.cpp failed").strip()
            raise RuntimeError(err_msg)

        if os.path.exists(txt_path):
            with open(txt_path, "r", encoding="utf-8", errors="ignore") as t:
                return t.read().strip()

        # Fallback: return stdout text if .txt was not generated.
        return (proc.stdout or "").strip()
    finally:
        for path in (audio_path, txt_path):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass


def _offline_recognizer_with_lang(audio_bytes: bytes, lang: str) -> str:
    if not audio_bytes:
        return ""

    model_path = os.getenv("WHISPER_CPP_MODEL", "").strip()
    if not model_path:
        raise RuntimeError("WHISPER_CPP_MODEL not set")
    if not os.path.exists(model_path):
        raise RuntimeError(f"model not found: {model_path}")

    bin_path = os.getenv("WHISPER_CPP_BIN", "whisper-cli").strip() or "whisper-cli"
    extra_args = [arg for arg in os.getenv("WHISPER_CPP_EXTRA_ARGS", "").split() if arg]

    audio_path = ""
    txt_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
            f.write(audio_bytes)
            audio_path = f.name

        txt_path = f"{audio_path}.txt"
        cmd = [
            bin_path,
            "-m",
            model_path,
            "-f",
            audio_path,
            "-otxt",
            "-nt",
        ] + extra_args

        use_lang = str(lang or "").strip().lower()
        if use_lang and use_lang not in {"auto", "auto-detect"}:
            cmd.extend(["-l", use_lang])

        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if proc.returncode != 0:
            err_msg = (proc.stderr or proc.stdout or "whisper.cpp failed").strip()
            raise RuntimeError(err_msg)

        if os.path.exists(txt_path):
            with open(txt_path, "r", encoding="utf-8", errors="ignore") as t:
                return t.read().strip()

        return (proc.stdout or "").strip()
    finally:
        for path in (audio_path, txt_path):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass


def _resample_audio_to_16k(audio_data, sample_rate):
    import numpy as np

    if sample_rate == 16000 or len(audio_data) == 0:
        return audio_data.astype(np.float32)

    old_len = len(audio_data)
    new_len = max(1, int(round(old_len * 16000.0 / float(sample_rate))))
    old_x = np.linspace(0.0, 1.0, num=old_len, endpoint=False)
    new_x = np.linspace(0.0, 1.0, num=new_len, endpoint=False)
    return np.interp(new_x, old_x, audio_data).astype(np.float32)


def offline_recognizer_status() -> dict:
    model_path = os.getenv("WHISPER_CPP_MODEL", "").strip()
    bin_path = os.getenv("WHISPER_CPP_BIN", "whisper-cli").strip() or "whisper-cli"

    if not model_path:
        return {"ready": False, "message": "WHISPER_CPP_MODEL 未設定"}
    if not os.path.exists(model_path):
        return {"ready": False, "message": f"模型檔不存在: {model_path}"}

    bin_ready = os.path.isabs(bin_path) and os.path.exists(bin_path)
    if not bin_ready:
        bin_ready = shutil.which(bin_path) is not None
    if not bin_ready:
        return {"ready": False, "message": f"找不到 whisper.cpp 執行檔: {bin_path}"}

    return {
        "ready": True,
        "message": "離線語音辨識已就緒",
        "model": model_path,
        "bin": bin_path,
        "lang": os.getenv("WHISPER_CPP_LANG", "yue").strip() or "yue",
    }


_LAST_STT_META = {
    "engine": "",
    "lang_used": "",
}


def _set_last_stt_meta(engine: str, lang_used: str):
    _LAST_STT_META["engine"] = str(engine or "").strip()
    _LAST_STT_META["lang_used"] = str(lang_used or "").strip()


def offline_recognizer_last_meta() -> dict:
    return dict(_LAST_STT_META)


def offline_recognizer_with_fallback(audio_bytes: bytes) -> str:
    """
    Fallback-enabled offline STT: try whisper.cpp first, then HF Whisper.
    
    This allows STT to work even when WHISPER_CPP_MODEL is not configured.
    Returns the transcribed text or raises RuntimeError if all methods fail.
    """
    if not audio_bytes:
        return ""

    # Try whisper.cpp first if configured.
    # Language order: auto -> yue -> en -> zh(last resort)
    # so we do not hard-force Cantonese while keeping zh as the final fallback.
    non_canto_env = os.getenv("STT_ALLOW_NON_CANTONESE_FALLBACK", "").strip().lower()
    if non_canto_env in {"0", "false", "no", "off"}:
        allow_non_cantonese = False
    else:
        allow_non_cantonese = True
    cpp_decode_order = ("auto", "yue", "en", "zh") if allow_non_cantonese else ("auto", "yue", "zh")

    model_path = os.getenv("WHISPER_CPP_MODEL", "").strip()
    if model_path and os.path.exists(model_path):
        for lang in cpp_decode_order:
            try:
                text = _offline_recognizer_with_lang(audio_bytes, lang)
                if text:
                    _set_last_stt_meta("whisper_cpp", lang)
                    return text
            except Exception:
                continue

    # Fallback to Hugging Face transformers Whisper using scipy-only decoding.
    hf_err_detail = ""
    try:
        import io
        import numpy as np
        from transformers import pipeline
        
        # Initialize ASR pipeline
        try:
            asr = pipeline(
                "automatic-speech-recognition",
                model="openai/whisper-small",
                device="cpu",
            )
        except Exception as e:
            hf_err_detail = f"Pipeline init: {e}"
            raise
        
        # Load audio from bytes using stdlib+numpy only (no ffmpeg/scipy dependency)
        try:
            from scipy.io import wavfile
        except Exception:
            wavfile = None

        try:
            if wavfile is None:
                import io
                import wave
                import numpy as np

                wav_buffer = io.BytesIO(audio_bytes)
                with wave.open(wav_buffer, "rb") as wf:
                    sample_rate = wf.getframerate()
                    channels = wf.getnchannels()
                    sample_width = wf.getsampwidth()
                    frames = wf.readframes(wf.getnframes())

                if sample_width == 2:
                    audio_data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
                elif sample_width == 4:
                    audio_data = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
                else:
                    raise RuntimeError(f"unsupported WAV sample width: {sample_width}")

                if channels > 1:
                    audio_data = audio_data.reshape(-1, channels).mean(axis=1)
            else:
                wav_buffer = io.BytesIO(audio_bytes)
                sample_rate, audio_data = wavfile.read(wav_buffer)

            # Convert multi-channel audio to mono.
            if getattr(audio_data, "ndim", 1) > 1:
                audio_data = audio_data.mean(axis=1)
            
            # Ensure float32 and 16kHz
            if audio_data.dtype != np.float32:
                if np.issubdtype(audio_data.dtype, np.integer):
                    info = np.iinfo(audio_data.dtype)
                    scale = float(max(abs(info.min), abs(info.max)))
                    audio_data = audio_data.astype(np.float32) / (scale or 1.0)
                else:
                    audio_data = audio_data.astype(np.float32)

            audio_data = np.clip(audio_data, -1.0, 1.0)
            
            # Resample to 16kHz if needed (numpy linear interpolation).
            audio_data = _resample_audio_to_16k(audio_data, sample_rate)

            # Guard against Whisper hallucinations on near-silent audio.
            if len(audio_data) == 0:
                return ""

            abs_audio = np.abs(audio_data)
            max_amp = float(abs_audio.max())
            mean_amp = float(abs_audio.mean())

            if mean_amp < 0.001 and max_amp < 0.008:
                return ""

            # Trim leading/trailing silence to focus on speech region.
            voice_threshold = max(0.004, min(0.02, max_amp * 0.12))
            voiced = np.where(abs_audio > voice_threshold)[0]
            if voiced.size > 0:
                start = max(int(voiced[0]) - 800, 0)
                end = min(int(voiced[-1]) + 800, len(audio_data) - 1)
                audio_data = audio_data[start : end + 1]

            # Language order: auto -> yue -> en -> zh(last resort).
            decode_order = [None, {"task": "transcribe", "language": "yue"}]
            if allow_non_cantonese:
                decode_order.extend(
                    [
                        {"task": "transcribe", "language": "en"},
                        {"task": "transcribe", "language": "zh"},
                    ]
                )
            else:
                decode_order.extend(
                    [
                        {"task": "transcribe", "language": "zh"},
                    ]
                )
            for generate_kwargs in decode_order:
                try:
                    if generate_kwargs is None:
                        out = asr({"sampling_rate": 16000, "raw": audio_data})
                        lang_used = "auto"
                    else:
                        out = asr(
                            {"sampling_rate": 16000, "raw": audio_data},
                            generate_kwargs=generate_kwargs,
                        )
                        lang_used = str(generate_kwargs.get("language", "auto") or "auto")
                    text = str(out.get("text", "")).strip() if isinstance(out, dict) else str(out).strip()
                    if text:
                        _set_last_stt_meta("hf_whisper", lang_used)
                        return text
                except Exception:
                    continue
            return ""
        except Exception as e:
            hf_err_detail = f"Audio decoding/transcription: {e}"
            raise
    except Exception as e_hf:
        if not hf_err_detail:
            hf_err_detail = str(e_hf)

    raise RuntimeError(
        f"STT failed: {hf_err_detail}"
    )
