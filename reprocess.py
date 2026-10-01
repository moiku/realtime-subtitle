"""Post-lecture reprocessing: re-transcribe a session's audio with a larger model and
re-translate it with wide context, producing the reference log and subtitle files.

    uv run python reprocess.py transcripts/20260929-124157            # session dir
    uv run python reprocess.py lecture.wav --out out_dir               # any 16 kHz WAV

Outputs (in the session dir or --out): refined.jsonl, refined.ja.srt, refined.en.srt
"""
import argparse
import json
import os

from openai import OpenAI

from config import config
from glossary import load_glossary

SYSTEM_PROMPT = """You translate the Japanese transcript of a university lecture{domain} into English for review subtitles.
You receive numbered ASR segments. Translate each segment into natural, accurate English.

Rules:
1. The ASR text contains fillers, self-corrections and occasional misrecognitions. Drop fillers, keep only the corrected version of a self-correction, and fix obvious misrecognitions (homophones) using context and the glossary.
2. Keep one translation per segment id, aligned with the source. A sentence may span several segments; split its English naturally across them without repeating or anticipating content.
3. Always use the glossary translation for any listed term.
4. Japanese fractions read denominator first: "X分のY" means Y/X (λ分の1 = 1/λ).
5. Preserve numbers, formulas, negations and who-did-what exactly. Do not add content that was not said.
6. If a segment has no content, return an empty string for it.
Return JSON: {{"translations": [{{"id": <id>, "en": "<English>"}}, ...]}}
{glossary}"""


def transcribe(wav, model, language, hints):
    import mlx_whisper
    repo = model if "/" in model else (
        "mlx-community/whisper-large-v3-turbo" if model in ("large-v3-turbo", "turbo")
        else f"mlx-community/whisper-{model}-mlx")
    print(f"[Reprocess] Transcribing {wav} with {repo} ...")
    result = mlx_whisper.transcribe(
        wav, path_or_hf_repo=repo, language=language, initial_prompt=hints or None,
        # Conditioning on previous text helps consistency but can loop on silence; keep it off
        condition_on_previous_text=False, verbose=False)
    segs = [{"id": i, "start": round(s["start"], 2), "end": round(s["end"], 2), "ja": s["text"].strip()}
            for i, s in enumerate(result["segments"]) if s["text"].strip()]
    print(f"[Reprocess] {len(segs)} segments")
    return segs


def translate(segs, model, glossary, domain, batch=20, context=10):
    client = OpenAI(api_key=config.api_key, base_url=config.api_base_url)
    system = SYSTEM_PROMPT.format(
        domain=f" on {domain}" if domain else "",
        glossary=("\nGlossary (Japanese = English):\n" + glossary.prompt_block()) if glossary.terms else "")
    done = []
    for b in range(0, len(segs), batch):
        chunk = segs[b:b + batch]
        ctx = "\n".join(f"JA: {s['ja']}\nEN: {s['en']}" for s in done[-context:])
        src = "\n".join(f"[{s['id']}] {s['ja']}" for s in chunk)
        user = (f"Previous segments (context only):\n{ctx}\n\n" if ctx else "") + f"Segments to translate:\n{src}"
        resp = client.chat.completions.create(
            model=model, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        out = {t["id"]: t.get("en", "") for t in json.loads(resp.choices[0].message.content)["translations"]}
        for s in chunk:
            s["en"] = out.get(s["id"], "")
            if s["id"] not in out:
                print(f"[Reprocess] Warning: no translation for segment {s['id']}")
        done += chunk
        print(f"[Reprocess] Translated {len(done)}/{len(segs)}")
    return segs


def srt_time(t):
    h, rem = divmod(int(t * 1000), 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def write_srt(segs, key, path):
    with open(path, "w", encoding="utf-8") as f:
        n = 0
        for s in segs:
            if not s.get(key):
                continue
            n += 1
            f.write(f"{n}\n{srt_time(s['start'])} --> {srt_time(s['end'])}\n{s[key]}\n\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="session dir (containing audio.wav) or a WAV file")
    ap.add_argument("--out", help="output dir (default: the session dir / the WAV's dir)")
    ap.add_argument("--asr-model", default="large-v3")
    ap.add_argument("--mt-model", default="gpt-4.1")
    args = ap.parse_args()

    wav = os.path.join(args.source, "audio.wav") if os.path.isdir(args.source) else args.source
    out = args.out or (args.source if os.path.isdir(args.source) else os.path.dirname(os.path.abspath(wav)))
    os.makedirs(out, exist_ok=True)

    glossary = load_glossary(config.glossary_files)
    glossary.add_slide_hints(config.slide_files)
    segs = transcribe(wav, args.asr_model, config.source_language, glossary.asr_prompt())
    segs = translate(segs, args.mt_model, glossary, config.domain)

    with open(os.path.join(out, "refined.jsonl"), "w", encoding="utf-8") as f:
        for s in segs:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    write_srt(segs, "ja", os.path.join(out, "refined.ja.srt"))
    write_srt(segs, "en", os.path.join(out, "refined.en.srt"))
    print(f"[Reprocess] Wrote refined.jsonl / refined.ja.srt / refined.en.srt to {out}")


if __name__ == "__main__":
    main()
