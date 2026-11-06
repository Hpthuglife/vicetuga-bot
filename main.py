"""
GTA 6 Bot — página de notícias GTA 6 100% automática (PT-PT)

Fluxo: RSS de notícias -> Gemini escolhe notícia e escreve guião -> edge-tts (voz)
-> Pexels (vídeos de fundo) -> ffmpeg (vídeo 9:16 com legendas) -> GitHub Release
(aloja o vídeo) -> Metricool (publica no Instagram, TikTok e YouTube Shorts).

Corre sozinho no GitHub Actions (ver .github/workflows/gta6bot.yml).
"""
import asyncio
import datetime as dt
import glob
import hashlib
import html
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import edge_tts
import feedparser
import requests

# ---------------------------------------------------------------- config
ROOT = Path(__file__).resolve().parent
WORK = ROOT / "work"
POSTED_FILE = ROOT / "posted.json"
QUEUE_FILE = ROOT / "queue.json"
MUSIC_DIR = ROOT / "assets" / "music"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
METRICOOL_TOKEN = os.getenv("METRICOOL_TOKEN", "")
METRICOOL_USER_ID = os.getenv("METRICOOL_USER_ID", "")
METRICOOL_BLOG_ID = os.getenv("METRICOOL_BLOG_ID", "")
NETWORKS = [n.strip() for n in os.getenv("NETWORKS", "instagram,tiktok,youtube").split(",") if n.strip()]
VOICE = os.getenv("VOICE", "pt-PT-RaquelNeural")  # alternativa: pt-PT-DuarteNeural
TIMEZONE = os.getenv("TIMEZONE", "Europe/Lisbon")
BRAND = os.getenv("BRAND", "@VICETUGA • GTA 6 EM PORTUGUÊS")
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "")

FEEDS = [
    "https://news.google.com/rss/search?q=%22GTA+6%22+when:2d&hl=pt-PT&gl=PT&ceid=PT:pt-150",
    "https://news.google.com/rss/search?q=%22GTA+6%22+OR+%22GTA+VI%22+when:2d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=Rockstar+%22GTA+VI%22+when:2d&hl=en-GB&gl=GB&ceid=GB:en",
]

W, H, FPS = 1080, 1920, 30
FONT = "DejaVu Sans"


def log(*a):
    print("[gta6bot]", *a, flush=True)


# ---------------------------------------------------------------- histórico
def load_posted():
    if POSTED_FILE.exists():
        return json.loads(POSTED_FILE.read_text(encoding="utf-8"))
    return []


def save_posted(posted):
    POSTED_FILE.write_text(json.dumps(posted[-300:], ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 1. notícias
def clean(text):
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    return re.sub(r"\s+", " ", text).strip()


def fetch_news(posted_ids):
    items, seen = [], set()
    for url in FEEDS:
        try:
            feed = feedparser.parse(url)
        except Exception as e:  # noqa
            log("feed falhou:", url, e)
            continue
        for e in feed.entries:
            title = clean(e.get("title"))
            if not re.search(r"GTA\s*(6|VI)\b", title, re.I):
                continue
            nid = hashlib.md5(title.lower().encode()).hexdigest()[:12]
            if nid in posted_ids or nid in seen:
                continue
            seen.add(nid)
            ts = e.get("published_parsed")
            items.append({
                "id": nid,
                "title": title,
                "summary": clean(e.get("summary"))[:500],
                "source": clean(e.get("source", {}).get("title", "")) if e.get("source") else "",
                "ts": time.mktime(ts) if ts else 0,
            })
    items.sort(key=lambda x: x["ts"], reverse=True)
    log(f"{len(items)} notícias novas encontradas")
    return items[:15]


# ---------------------------------------------------------------- 2. guião (Gemini)
PROMPT = """És o editor da ViceTuga, uma página de notícias de GTA 6 em Instagram/TikTok/YouTube Shorts, para público de PORTUGAL.
Escreve SEMPRE em português de Portugal (PT-PT), nunca brasileiro: usa "estás", "fixe", "telemóvel", "comboio", "a jogar" (nunca "jogando"), "vocês" e não "você" para o público.

Notícias candidatas (JSON):
{candidates}

Títulos que JÁ publicámos (não repitas a mesma história, mesmo com outras palavras):
{recent}

Tarefa:
1. Escolhe a notícia candidata mais interessante para fãs de GTA 6 que NÃO repita uma história já publicada.
2. Regras rígidas:
   - Usa APENAS factos presentes no título/resumo da notícia. Não inventes datas, números, preços nem citações.
   - Se a notícia for um rumor/leak não confirmado, só a podes usar se o guião disser claramente que é um rumor.
   - Ignora notícias sem interesse (artigos de opinião vagos, listas de "10 coisas", spam, outros jogos).
   - Se nenhuma servir, devolve {{"skip": true}}.
3. Guião para narração de 20-30 segundos (55 a 80 palavras): 1ª frase é um gancho forte que prende nos primeiros 2 segundos; depois os factos; termina com uma pergunta aos seguidores ou com "segue a ViceTuga para mais novidades de GTA 6".
   Escreve números por extenso quando ajudar a leitura em voz alta. Nada de emojis nem hashtags no guião.

Responde só com JSON neste formato:
{{
 "skip": false,
 "id": "<id da notícia escolhida>",
 "title_overlay": "<título curto para o ecrã, máx 6 palavras, MAIÚSCULAS>",
 "script": "<guião>",
 "caption": "<legenda do post, 1-2 frases, pode ter 1-2 emojis>",
 "hashtags": ["vicetuga", "gta6", "gtavi", "..."],
 "youtube_title": "<título YouTube, máx 90 caracteres, inclui GTA 6>",
 "pexels_queries": ["<3 pesquisas em INGLÊS para vídeos de fundo verticais: Miami, neon, carros desportivos, praia à noite, cidade à noite, etc.>"]
}}"""


def gemini_json(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.7},
    }
    for attempt in range(3):
        r = requests.post(url, params={"key": GEMINI_API_KEY}, json=body, timeout=90)
        if r.status_code == 429 or r.status_code >= 500:
            log("Gemini ocupado, a tentar de novo...", r.status_code)
            time.sleep(20 * (attempt + 1))
            continue
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)
    raise RuntimeError("Gemini não respondeu")


def write_script(candidates, posted):
    recent = [p["title"] for p in posted[-25:]]
    cands = [{k: c[k] for k in ("id", "title", "summary", "source")} for c in candidates]
    data = gemini_json(PROMPT.format(candidates=json.dumps(cands, ensure_ascii=False, indent=1),
                                     recent=json.dumps(recent, ensure_ascii=False)))
    if data.get("skip"):
        return None
    chosen = next((c for c in candidates if c["id"] == data.get("id")), None)
    if not chosen:
        log("Gemini devolveu id desconhecido — a ignorar")
        return None
    words = len(data["script"].split())
    if not 35 <= words <= 110:
        log(f"guião com {words} palavras — fora do intervalo, a ignorar")
        return None
    data["news"] = chosen
    return data


# ---------------------------------------------------------------- 3. voz (edge-tts)
async def _tts(text, mp3):
    comm = edge_tts.Communicate(text, VOICE, rate="+8%", boundary="WordBoundary")
    words = []
    with open(mp3, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append({"text": chunk["text"], "start": start, "end": start + chunk["duration"] / 1e7})
    return words


def tts(text, mp3):
    return asyncio.run(_tts(text, mp3))


def media_duration(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "default=nk=1:nw=1", str(path)])
    return float(out.strip())


# ---------------------------------------------------------------- 4. legendas (ASS)
def ass_time(t):
    t = max(t, 0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def ass_escape(t):
    return t.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def build_ass(words, title, total, path):
    # agrupa 2-3 palavras por legenda; parte em pontuação
    groups, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= 3 or re.search(r"[.,!?;:]$", w["text"]):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)

    lines = []
    for i, g in enumerate(groups):
        start = g[0]["start"]
        end = groups[i + 1][0]["start"] if i + 1 < len(groups) else g[-1]["end"] + 0.3
        text = ass_escape(" ".join(x["text"] for x in g)).upper()
        lines.append(f"Dialogue: 1,{ass_time(start)},{ass_time(end)},Sub,,0,0,0,,{{\\fscx80\\fscy80\\t(0,90,\\fscx100\\fscy100)}}{text}")

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{FONT},92,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,7,3,5,60,60,0,1
Style: Title,{FONT},70,&H00000000,&H00000000,&H0000E1FF,&H0000E1FF,-1,0,0,0,100,100,0,0,3,18,0,8,80,80,230,1
Style: Brand,{FONT},44,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,2,0,1,3,0,2,60,60,170,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,{ass_time(0)},{ass_time(total)},Title,,0,0,0,,{ass_escape(title).upper()}
Dialogue: 0,{ass_time(0)},{ass_time(total)},Brand,,0,0,0,,{ass_escape(BRAND)}
"""
    Path(path).write_text(header + "\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- 5. vídeos de fundo (Pexels)
DEFAULT_QUERIES = ["miami night", "neon city night", "sports car night", "palm trees sunset", "miami beach aerial"]


def fetch_backgrounds(queries, n=4):
    headers = {"Authorization": PEXELS_API_KEY}
    queries = list(dict.fromkeys((queries or []) + DEFAULT_QUERIES))
    clips = []
    for q in queries:
        if len(clips) >= n:
            break
        try:
            r = requests.get("https://api.pexels.com/videos/search", headers=headers, timeout=30,
                             params={"query": q, "orientation": "portrait", "size": "medium", "per_page": 15})
            r.raise_for_status()
            videos = r.json().get("videos", [])
        except Exception as e:  # noqa
            log("Pexels falhou para", q, e)
            continue
        random.shuffle(videos)
        for v in videos[:2]:
            files = [f for f in v.get("video_files", [])
                     if f.get("height") and f.get("width") and f["height"] > f["width"] and f["height"] >= 1280]
            if not files:
                continue
            best = min(files, key=lambda f: abs(f["height"] - 1920))
            dest = WORK / f"bg{len(clips)}.mp4"
            with requests.get(best["link"], stream=True, timeout=120) as resp:
                resp.raise_for_status()
                with open(dest, "wb") as fh:
                    for part in resp.iter_content(1 << 20):
                        fh.write(part)
            clips.append(dest)
            if len(clips) >= n:
                break
    if not clips:
        raise RuntimeError("Sem vídeos de fundo do Pexels")
    return clips


# ---------------------------------------------------------------- 6. montagem (ffmpeg)
def render(clips, voice_mp3, ass_path, out_path, total):
    seg = total / len(clips)
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for c in clips:
        cmd += ["-stream_loop", "-1", "-t", f"{seg:.3f}", "-i", str(c)]
    cmd += ["-i", str(voice_mp3)]
    music = sorted(glob.glob(str(MUSIC_DIR / "*.mp3")))
    if music:
        cmd += ["-stream_loop", "-1", "-i", random.choice(music)]

    parts = []
    for i in range(len(clips)):
        parts.append(f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                     f"setsar=1,fps={FPS},trim=duration={seg:.3f},setpts=PTS-STARTPTS[v{i}]")
    concat = "".join(f"[v{i}]" for i in range(len(clips)))
    ass = str(ass_path).replace(":", r"\:")
    parts.append(f"{concat}concat=n={len(clips)}:v=1:a=0,eq=brightness=-0.10:saturation=1.15,"
                 f"ass='{ass}'[vout]")
    vi = len(clips)
    if music:
        parts.append(f"[{vi}:a]volume=1.0[a0];[{vi + 1}:a]volume=0.10[a1];"
                     f"[a0][a1]amix=inputs=2:duration=first:dropout_transition=0[aout]")
    else:
        parts.append(f"[{vi}:a]anull[aout]")

    cmd += ["-filter_complex", ";".join(parts), "-map", "[vout]", "-map", "[aout]",
            "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
            "-movflags", "+faststart", str(out_path)]
    subprocess.run(cmd, check=True)


# ---------------------------------------------------------------- 7. alojar vídeo (GitHub Release)
def host_video(path):
    tag = "v" + dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    subprocess.run(["gh", "release", "create", tag, str(path), "--repo", GITHUB_REPOSITORY,
                    "--title", tag, "--notes", "auto"], check=True)
    return f"https://github.com/{GITHUB_REPOSITORY}/releases/download/{tag}/{Path(path).name}"


def cleanup_old_releases(days=5):
    try:
        out = subprocess.check_output(["gh", "release", "list", "--repo", GITHUB_REPOSITORY, "--limit", "200",
                                       "--json", "tagName,createdAt"], text=True)
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
        for r in json.loads(out):
            created = dt.datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00"))
            if created < cutoff:
                subprocess.run(["gh", "release", "delete", r["tagName"], "--repo", GITHUB_REPOSITORY,
                                "--yes", "--cleanup-tag"], check=False)
    except Exception as e:  # noqa
        log("limpeza de releases falhou (não é grave):", e)


# ---------------------------------------------------------------- 8. publicar (Metricool)
def publish_metricool(video_url, data):
    hashtags = " ".join("#" + h.lstrip("#").replace(" ", "") for h in data.get("hashtags", [])[:8])
    text = f"{data['caption']}\n\n{hashtags}".strip()
    when = (dt.datetime.now(ZoneInfo(TIMEZONE)) + dt.timedelta(minutes=12)).replace(microsecond=0)

    info = {
        "autoPublish": True,
        "draft": False,
        "text": text,
        "media": [video_url],
        "providers": [{"network": n} for n in NETWORKS],
        "publicationDate": {"dateTime": when.strftime("%Y-%m-%dT%H:%M:%S"), "timezone": TIMEZONE},
        "shortener": False,
        "firstCommentText": "",
        "descendants": [],
        "smartLinkData": {"ids": []},
    }
    if "instagram" in NETWORKS:
        info["instagramData"] = {"type": "REEL", "showReelOnFeed": True, "isAiGenerated": True}
    if "tiktok" in NETWORKS:
        info["tiktokData"] = {"privacyOption": "PUBLIC_TO_EVERYONE", "title": data["title_overlay"].title()[:90],
                              "isAigc": True, "disableComment": False, "disableDuet": False,
                              "disableStitch": False, "autoAddMusic": False}
    if "youtube" in NETWORKS:
        info["youtubeData"] = {"title": data["youtube_title"][:95], "type": "short", "privacy": "public",
                               "madeForKids": False, "category": "GAMING",
                               "tags": [h.lstrip("#") for h in data.get("hashtags", [])][:10]}
    if "facebook" in NETWORKS:
        info["facebookData"] = {"type": "REEL"}

    r = requests.post("https://app.metricool.com/api/v2/scheduler/posts",
                      params={"userId": METRICOOL_USER_ID, "blogId": METRICOOL_BLOG_ID},
                      headers={"X-Mc-Auth": METRICOOL_TOKEN, "Content-Type": "application/json"},
                      json=info, timeout=60)
    if r.status_code >= 300:
        log("ERRO Metricool:", r.status_code, r.text[:1000])
        r.raise_for_status()
    log("agendado no Metricool para", when.isoformat())


# ---------------------------------------------------------------- 8b. fila (publicação via Claude + Metricool MCP)
def enqueue(video_url, data):
    queue = json.loads(QUEUE_FILE.read_text(encoding="utf-8")) if QUEUE_FILE.exists() else []
    hashtags = " ".join("#" + h.lstrip("#").replace(" ", "") for h in data.get("hashtags", [])[:8])
    queue.append({
        "id": data["news"]["id"],
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
        "status": "pending",
        "video_url": video_url,
        "text": f"{data['caption']}\n\n{hashtags}".strip(),
        "short_title": data["title_overlay"].title()[:90],
        "youtube_title": data["youtube_title"][:95],
        "tags": [h.lstrip("#") for h in data.get("hashtags", [])][:10],
        "news_title": data["news"]["title"],
    })
    QUEUE_FILE.write_text(json.dumps(queue[-60:], ensure_ascii=False, indent=1), encoding="utf-8")
    log("vídeo colocado na fila (queue.json)")


# ---------------------------------------------------------------- main
def check_env():
    need = ["GEMINI_API_KEY", "PEXELS_API_KEY"]
    if not DRY_RUN:
        need += ["GITHUB_REPOSITORY"]
    missing = [k for k in need if not os.getenv(k)]
    if missing:
        sys.exit(f"Faltam variáveis/secrets: {', '.join(missing)}")


def main():
    check_env()
    WORK.mkdir(exist_ok=True)
    posted = load_posted()
    candidates = fetch_news({p["id"] for p in posted})
    if not candidates:
        log("sem notícias novas — nada a publicar")
        return

    data = write_script(candidates, posted)
    if not data:
        log("nenhuma notícia válida — nada a publicar")
        return
    log("notícia:", data["news"]["title"])
    log("guião:", data["script"])

    voice = WORK / "voice.mp3"
    words = tts(data["script"], voice)
    total = media_duration(voice) + 0.6
    ass = WORK / "subs.ass"
    build_ass(words, data["title_overlay"], total, ass)
    clips = fetch_backgrounds(data.get("pexels_queries"))
    out = WORK / "gta6.mp4"
    render(clips, voice, ass, out, total)
    log(f"vídeo pronto: {out} ({total:.1f}s)")

    if DRY_RUN:
        log("DRY_RUN — não publicado")
        return

    url = host_video(out)
    log("vídeo alojado em", url)
    if METRICOOL_TOKEN:  # plano Advanced com API: publica direto
        time.sleep(5)
        publish_metricool(url, data)
    else:  # plano sem API: fica na fila para a tarefa agendada do Claude
        enqueue(url, data)

    posted.append({"id": data["news"]["id"], "title": data["news"]["title"],
                   "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")})
    save_posted(posted)
    cleanup_old_releases()


if __name__ == "__main__":
    main()
