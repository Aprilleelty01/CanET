# ===========================================================
# enrich_corpus.py  —  Enrich Cantonese corpus with structure
# ===========================================================
import pandas as pd
import re
from pathlib import Path

SFP_LIST = sorted([
    "吖","呀","呀嘛","啦","喇","喇喂","㗎喇","嘞","吖嗱","囉","咯","嚛",
    "呢","㗎","哩","㗎啦","嗰喎","啫","吒嘛","喎","咋","㗎咋","嘅","既",
    "既咩","咩","𠺢嘛","𠿪","噃","㗎喇可","㗎噃","啩","吖嘛","添","添㗎",
    "先","嚟","吓哇","lu","嗱","㗎咋噃","㗎咋喎","啊","咧","既啫","㗎喎","le",
    "咩呀","吓"
], key=len, reverse=True)   # sort longest first!

NEGATION_WORDS = ["唔","冇","未","無","莫"]

VERB_WORDS = ["食","飲","去","返","瞓","睇","講","等","諗","玩"]
NOUN_WORDS = ["我","你","佢","媽咪","老豆","朋友","學校","公司","老師","時間"]
ADJ_WORDS  = ["開心","快樂","唔錯","靚","驚","大","細","好","差","正"]

def guess_word_type(char):
    if any(w in char for w in VERB_WORDS): return "verb"
    if any(w in char for w in NOUN_WORDS): return "noun"
    if any(w in char for w in ADJ_WORDS):  return "adj"
    return "other"

def extract_longest_sfp(text):
    """Return longest matching SFP substring if found."""
    for sfp in SFP_LIST:
        if sfp in text:
            return sfp
    return None

def enrich_row(text):
    row = {}
    longest = extract_longest_sfp(text)
    if longest:
        row["sfp_list"] = longest
        row["num_sfp"] = len(longest)
        row["multiple_sfp"] = 1 if text.count(longest) > 1 else 0
        row["sfp_distance_end"] = len(text) - (text.find(longest) + len(longest))
        idx = text.find(longest)
        prev_char = text[max(0, idx-1):idx]
        row["sfp_pos"] = guess_word_type(prev_char)
        row["main_pos_pattern"] = f"{row['sfp_pos']}-sfp"
    else:
        row["sfp_list"] = ""
        row["num_sfp"] = 0
        row["multiple_sfp"] = 0
        row["sfp_distance_end"] = -1
        row["sfp_pos"] = "none"
        row["main_pos_pattern"] = "none"

    row["negation_present"] = 1 if any(n in text for n in NEGATION_WORDS) else 0

    # Sentence heuristics
    if "咩" in text or "嗎" in text:
        stype = "question"
    elif any(a in text for a in ["快啲","唔好","要","畀我"]):
        stype = "command"
    elif any(a in text for a in ["開心","驚","嬲","鍾意","愛","笑"]):
        stype = "emotion"
    else:
        stype = "statement"
    row["sentence_type_guess"] = stype
    row["emotion_marker_present"] = 1 if stype=="emotion" else 0
    return row

def run_enrichment(file_in: Path, out_file: Path) -> Path:
    df = pd.read_excel(file_in)
    features = df["cantonese_text"].apply(enrich_row)
    df_enriched = pd.concat([df.iloc[:, :2], pd.DataFrame(list(features)), df.iloc[:, 2:]], axis=1)
    df_enriched.to_excel(out_file, index=False)
    return out_file


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    project_root = base_dir.parent

    candidates = [
        base_dir / "can_corpus.xlsm",
        project_root / "can_corpus.xlsm",
    ]

    file_in = None
    for candidate in candidates:
        if candidate.exists():
            file_in = candidate
            break

    if file_in is None:
        raise FileNotFoundError("Cannot find can_corpus.xlsm in train/ or project root")

    out = file_in.parent / "can_enriched.xlsx"
    saved = run_enrichment(file_in, out)
    print(f"Enriched file: {saved}")


if __name__ == "__main__":
    main()
