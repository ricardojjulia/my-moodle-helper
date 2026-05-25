#!/usr/bin/env python3
"""
Moodle Course Administrator
Generates a Moodle 5.x .mbz backup from a content prompt using a local LLM.

Usage:
    python3 create_course.py \
        --shortname "TH310-2026_1" \
        --fullname "TH 310 - HERMENEUTICA" \
        --professor "Ricardo Julia" \
        --prompt "Curso de hermenéutica bíblica para estudiantes de teología..." \
        --start-date "2026-04-20" \
        --end-date "2026-06-15"

    # Skip LLM, load content from a previously saved JSON:
    python3 create_course.py --shortname "TH310-2026_1" \
        --fullname "TH 310 - HERMENEUTICA" --load-json content.json
"""

import argparse
import ast
import html
import json
import os
import re
import sys
import time
import uuid
import zipfile
from datetime import datetime, timedelta
from io import BytesIO

import requests

# ─── Constants ────────────────────────────────────────────────────────────────

DEFAULT_LLM_URL = "http://192.168.86.41:1234/v1"
COLLEGE_NAME    = "YOUR INSTITUTION"
DEFAULT_PROF    = "Ricardo Julia"
DEFAULT_EMAIL   = "ricardojjulia@gmail.com"
DEFAULT_PHONE   = "813-466-8930"

# Model IDs whose names suggest they are NOT general-purpose chat/instruct models
_EXCLUDE_KEYWORDS = {
    'embed', 'bge', 'nomic', 'clip', 'whisper', 'tts', 'vision',
    'coder', 'codestral', 'starcoder', 'deepseek-coder',
}

# Known architecture quality tiers (higher = more accurate for academic text)
_ARCH_QUALITY = {
    'llama':      8,
    'qwen':       9,   # Excellent multilingual + Spanish
    'mistral':    7,
    'deepseek':   8,
    'gemma':      6,
    'phi':        6,
    'gpt':        8,
    'falcon':     5,
}

# Quantization quality scores (higher = better fidelity)
_QUANT_QUALITY = {
    'fp16': 10, 'bf16': 10,
    'mlx':  9,  # MLX = Apple-optimised near-full precision
    'q8':   9,  'q8_0': 9,
    'q6':   8,  'q6_k': 8,
    'q5':   7,  'q5_k': 7,
    'q4':   6,  'q4_k': 6, 'q4_0': 6,
    'q3':   4,  'q3_k': 4,
    'q2':   2,  'q2_k': 2,
}

# ─── Run cache (remembers last model choice) ──────────────────────────────────

_CACHE_FILE = os.path.expanduser('~/.moodle_creator_cache.json')

def _load_cache():
    try:
        with open(_CACHE_FILE, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def _save_cache(data: dict):
    try:
        cache = _load_cache()
        cache.update(data)
        with open(_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, indent=2)
    except OSError:
        pass  # non-fatal

# ─── Minimal XML stubs (reused across many files) ─────────────────────────────

_FILTERS = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<filters>\n  <filter_actives>\n  </filter_actives>\n'
            '  <filter_configs>\n  </filter_configs>\n</filters>')

_ROLES = ('<?xml version="1.0" encoding="UTF-8"?>\n'
          '<roles>\n  <role_overrides>\n  </role_overrides>\n'
          '  <role_assignments>\n  </role_assignments>\n</roles>')

_GRADES = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<activity_gradebook>\n  <grade_items>\n  </grade_items>\n'
           '  <grade_letters>\n  </grade_letters>\n</activity_gradebook>')

_COMMENTS   = '<?xml version="1.0" encoding="UTF-8"?>\n<comments>\n</comments>'
_LOGS       = '<?xml version="1.0" encoding="UTF-8"?>\n<logs>\n</logs>'
_INFOREF    = '<?xml version="1.0" encoding="UTF-8"?>\n<inforef>\n</inforef>'
_CALENDAR   = '<?xml version="1.0" encoding="UTF-8"?>\n<events>\n</events>'
_XAPISTATE  = '<?xml version="1.0" encoding="UTF-8"?>\n<xapistate>\n</xapistate>'
_COMPETENCIES = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                 '<course_competencies>\n  <competencies>\n  </competencies>\n'
                 '  <user_competencies>\n  </user_competencies>\n</course_competencies>')

# ─── LLM helpers ──────────────────────────────────────────────────────────────

def call_llm(messages, llm_url, model_id="local-model",
             temperature=0.7, max_tokens=4096, retries=3, api_key=""):
    """POST to the OpenAI-compatible /chat/completions endpoint."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(
                f"{llm_url}/chat/completions",
                headers=headers,
                json={"model": model_id, "messages": messages,
                      "temperature": temperature, "max_tokens": max_tokens},
                timeout=360,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            if attempt == retries:
                raise RuntimeError(f"LLM call failed after {retries} attempts: {exc}") from exc
            print(f"      [retry {attempt}/{retries}] {exc}")
            time.sleep(3)


# ─── LLM evaluation & selection ───────────────────────────────────────────────

def _fetch_models(llm_url):
    """Return list of model IDs from /v1/models, filtering non-chat models."""
    r = requests.get(f"{llm_url}/models", timeout=15)
    r.raise_for_status()
    all_ids = [m['id'] for m in r.json().get('data', [])]
    chat = []
    for mid in all_ids:
        low = mid.lower()
        if not any(kw in low for kw in _EXCLUDE_KEYWORDS):
            chat.append(mid)
    return chat


def _infer_specs(model_id):
    """
    Parse the model ID string to extract size, quantization, and architecture.
    Returns dict: {arch, size_b, quant, size_score, quant_score, context_k}
    """
    low = model_id.lower()

    # Architecture
    arch, arch_score = 'unknown', 5
    for name, score in _ARCH_QUALITY.items():
        if name in low:
            arch, arch_score = name, score
            break

    # Parameter count — try numeric first, then named tiers
    size_b = 0
    m = re.search(r'(\d+\.?\d*)b', low)
    if m:
        size_b = float(m.group(1))
    # MoE active-param hint: e.g. "30b-a3b" → real size 30B
    m2 = re.search(r'(\d+)b-a(\d+)b', low)
    if m2:
        size_b = float(m2.group(1))
    # Named size tiers (vendor conventions)
    if size_b == 0:
        _named = {'nano': 1, 'mini': 3, 'small': 22, 'medium': 22,
                  'large': 70, 'micro': 1, 'tiny': 1}
        for tag, approx in _named.items():
            if tag in low:
                size_b = approx
                break

    size_score = (
        10 if size_b >= 70 else
         9 if size_b >= 32 else
         8 if size_b >= 22 else
         7 if size_b >= 14 else
         6 if size_b >= 8  else
         5 if size_b >= 7  else
         4 if size_b >= 4  else
         3 if size_b >  0  else
         5  # unknown — assume mid-range
    )

    # Quantization
    quant, quant_score = 'unknown', 7
    for tag, score in _QUANT_QUALITY.items():
        if tag in low:
            quant, quant_score = tag, score
            break
    # MLX in name = near-full precision
    if 'mlx' in low and quant == 'unknown':
        quant, quant_score = 'mlx', 9

    # Context window (tokens) — rough heuristic
    ctx_k = 4
    for marker, k in [('128k', 128), ('64k', 64), ('32k', 32), ('16k', 16),
                       ('8k', 8), ('4k', 4)]:
        if marker in low:
            ctx_k = k
            break
    # Newer Qwen2.5 / LLaMA 3.x default to 32k+
    if ctx_k == 4 and any(x in low for x in ['qwen2', 'qwen3', 'llama-3', 'llama3']):
        ctx_k = 32

    return dict(arch=arch, size_b=size_b, quant=quant,
                size_score=size_score, quant_score=quant_score,
                arch_score=arch_score, ctx_k=ctx_k)


def _evaluate_model(llm_url, model_id, timeout=90):
    """
    Run a standardised academic-theology JSON test against one model.
    Returns a result dict with accuracy/speed metrics.
    """
    test_messages = [
        {"role": "system",
         "content": ("Eres un profesor de teología académica. "
                     "Responde SOLO en español. "
                     "Responde ÚNICAMENTE con JSON válido, sin texto adicional.")},
        {"role": "user",
         "content": (
             'Genera un JSON con EXACTAMENTE esta estructura:\n'
             '{\n'
             '  "term": "Hermenéutica",\n'
             '  "definition": "Definición académica en español de mínimo 20 palabras",\n'
             '  "question": "Pregunta de examen universitario sobre hermenéutica bíblica",\n'
             '  "options": ["opción correcta", "opción incorrecta 1", "opción incorrecta 2", "opción incorrecta 3"],\n'
             '  "correct_index": 0,\n'
             '  "explanation": "Explicación teológica breve en español de mínimo 15 palabras"\n'
             '}\n'
             'Responde SOLO con el JSON.'
         )},
    ]

    t0 = time.time()
    error = None
    raw = ''
    try:
        r = requests.post(
            f"{llm_url}/chat/completions",
            json={"model": model_id, "messages": test_messages,
                  "temperature": 0.3, "max_tokens": 500},
            timeout=timeout,
        )
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"]
    except requests.exceptions.Timeout:
        error = 'TIMEOUT'
    except Exception as exc:
        error = str(exc)[:60]

    elapsed = time.time() - t0

    if error:
        return dict(model_id=model_id, elapsed=elapsed, error=error,
                    json_valid=False, json_complete=False,
                    spanish_score=0.0, content_score=0.0,
                    accuracy=0.0, speed_score=0.0, final_score=0.0)

    # ── Score: JSON validity ──────────────────────────────────────────────────
    json_valid, json_complete, parsed = False, False, {}
    try:
        parsed = extract_json(raw)
        json_valid = True
        required = {'term', 'definition', 'question', 'options', 'correct_index', 'explanation'}
        json_complete = required.issubset(parsed.keys())
    except Exception:
        pass

    # ── Score: Spanish language quality ──────────────────────────────────────
    es_markers = ['la', 'el', 'de', 'en', 'que', 'es', 'se', 'un', 'una',
                  'los', 'del', 'para', 'por', 'con', 'como', 'su', 'al']
    words = raw.lower().split()
    word_set = set(words)
    spanish_score = min(sum(1 for w in es_markers if w in word_set) / len(es_markers), 1.0)

    # ── Score: Content quality (length + field completeness) ─────────────────
    if json_complete:
        defn_words = len(str(parsed.get('definition', '')).split())
        expl_words = len(str(parsed.get('explanation', '')).split())
        opts_ok    = isinstance(parsed.get('options'), list) and len(parsed['options']) == 4
        content_score = min(
            (min(defn_words, 20) / 20) * 0.4 +
            (min(expl_words, 15) / 15) * 0.3 +
            (1.0 if opts_ok else 0.0) * 0.3,
            1.0,
        )
    else:
        content_score = 0.0

    # ── Composite accuracy (0-10) ─────────────────────────────────────────────
    accuracy = (
        (1.0 if json_valid    else 0.0) * 3.0 +
        (1.0 if json_complete else 0.0) * 3.0 +
        spanish_score                   * 2.0 +
        content_score                   * 2.0
    )  # max = 10

    # ── Speed score (0-10): lower latency = higher score ────────────────────
    speed_score = max(0.0, 10.0 - elapsed / 6.0)  # 10→0 over 60 s

    return dict(model_id=model_id, elapsed=elapsed, error=None,
                json_valid=json_valid, json_complete=json_complete,
                spanish_score=spanish_score, content_score=content_score,
                accuracy=accuracy, speed_score=speed_score,
                final_score=0.0)   # filled in after specs merge


def _final_score(result, specs):
    """
    Combine live test scores with static model-spec scores.
    Weights: accuracy 50%, model quality 30%, speed 20%.
    """
    model_quality = (specs['size_score']  * 0.5 +
                     specs['quant_score'] * 0.3 +
                     specs['arch_score']  * 0.2)   # 0-10
    return (result['accuracy']    * 0.50 +
            model_quality          * 0.30 +
            result['speed_score'] * 0.20)


def _short_name(model_id, width=38):
    """Truncate model ID for display."""
    return model_id if len(model_id) <= width else '…' + model_id[-(width-1):]


def select_llm(llm_url):
    """
    Fetch available models, evaluate each one, rank them, and ask the user
    to accept the recommendation or choose a different model.
    Returns the selected model_id string.
    """
    W = 70  # display width
    print(f"\n{'─'*W}")
    print("  LLM EVALUATION FOR COURSE CREATION")
    print(f"  Server: {llm_url}")
    print(f"{'─'*W}")

    # 1. Fetch model list
    try:
        candidates = _fetch_models(llm_url)
    except Exception as exc:
        print(f"  ✗ Could not reach LLM server: {exc}")
        print("  Falling back to default model ID 'local-model'")
        return 'local-model'

    if not candidates:
        print("  No chat/instruct models found. Using 'local-model'.")
        return 'local-model'

    print(f"\n  Found {len(candidates)} chat model(s). Running evaluation…")
    print(f"  (Each model gets a 90-second theology JSON test)\n")

    # 2. Evaluate each model
    results = []
    for mid in candidates:
        label = _short_name(mid)
        print(f"  Testing {label:<40}", end='', flush=True)
        res  = _evaluate_model(llm_url, mid, timeout=90)
        spec = _infer_specs(mid)
        res['final_score'] = _final_score(res, spec)
        res['specs'] = spec

        if res['error']:
            status = f"✗ {res['error']}"
        else:
            j = '✓JSON' if res['json_complete'] else ('~json' if res['json_valid'] else '✗JSON')
            status = f"{j}  {res['elapsed']:.0f}s"
        print(status)
        results.append(res)

    # 3. Sort: best first
    results.sort(key=lambda r: r['final_score'], reverse=True)

    # 4. Display ranking table
    print(f"\n{'─'*W}")
    print(f"  {'#':>2}  {'Model':<38}  {'Accuracy':>8}  {'Speed':>5}  {'Score':>5}  {'Rec':>4}")
    print(f"{'─'*W}")

    def speed_bar(s):
        filled = round(s / 2)   # 0-5 bars
        return '●' * filled + '○' * (5 - filled)

    best_idx = 0  # first after sort is best
    for i, r in enumerate(results):
        rec   = '★ BEST' if i == best_idx else ''
        acc_pct = f"{r['accuracy']*10:.0f}%"
        spd_bar = speed_bar(r['speed_score'])
        score   = f"{r['final_score']:.1f}"
        label   = _short_name(r['model_id'], 38)
        err     = f"  [{r['error']}]" if r['error'] else ''
        print(f"  {i+1:>2}  {label:<38}  {acc_pct:>8}  {spd_bar:>5}  {score:>5}  {rec}{err}")

    print(f"{'─'*W}")

    best = results[0]
    print(f"\n  Recommendation: {best['model_id']}")
    specs = best['specs']
    reasons = []
    if specs['size_b'] >= 30:
        reasons.append(f"large model ({specs['size_b']:.0f}B params) → best accuracy")
    elif specs['size_b'] >= 14:
        reasons.append(f"mid-large model ({specs['size_b']:.0f}B params)")
    if specs['quant'] in ('mlx', 'fp16', 'bf16', 'q8', 'q8_0'):
        reasons.append("high-precision weights")
    if best['json_complete']:
        reasons.append("perfect JSON output in test")
    if best['spanish_score'] >= 0.8:
        reasons.append("excellent Spanish")
    if reasons:
        print(f"  Why: {' · '.join(reasons)}")
    else:
        print(f"  Score: {best['final_score']:.1f}/10")

    # 5. Prompt user
    print()
    print(f"  Press Enter to use the recommended model,")
    print(f"  or type a number (1-{len(results)}) to choose a different one:")
    print()

    while True:
        try:
            choice = input("  Your choice > ").strip()
        except (EOFError, KeyboardInterrupt):
            choice = ''
        if not choice:
            selected = best
            break
        if choice.isdigit() and 1 <= int(choice) <= len(results):
            selected = results[int(choice) - 1]
            break
        print(f"  Please enter a number between 1 and {len(results)}, or press Enter.")

    print(f"\n  ✓ Using model: {selected['model_id']}")
    print(f"{'─'*W}\n")
    return selected['model_id']


def _repair_json_fallback(candidate):
  return re.sub(r",(\s*[}\]])", r"\1", candidate)


def _load_json_candidate(candidate):
  try:
    return json.loads(candidate)
  except json.JSONDecodeError as first_error:
    pass

  try:
    from json_repair import repair_json
  except ImportError:
    repaired = _repair_json_fallback(candidate)
    for trial in (repaired, candidate):
      try:
        return json.loads(trial)
      except json.JSONDecodeError:
        continue

    for trial in (candidate, repaired):
      try:
        parsed = ast.literal_eval(trial)
      except (SyntaxError, ValueError):
        continue
      if isinstance(parsed, (dict, list)):
        return parsed

    raise first_error

  return json.loads(repair_json(candidate))


def extract_json(text):
  """Pull the first JSON object/array from an LLM response."""

  # Try fenced code block first
  m = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
  if m:
    candidate = m.group(1)
    return _load_json_candidate(candidate)

  # Find the first { or [ and extract to its matching close
  for start_char, end_char in [('{', '}'), ('[', ']')]:
    idx = text.find(start_char)
    if idx != -1:
      depth, in_str, escape = 0, False, False
      for i, c in enumerate(text[idx:], idx):
        if escape:
          escape = False
          continue
        if c == '\\' and in_str:
          escape = True
          continue
        if c == '"':
          in_str = not in_str
          continue
        if not in_str:
          if c == start_char:
            depth += 1
          elif c == end_char:
            depth -= 1
            if depth == 0:
              candidate = text[idx:i+1]
              return _load_json_candidate(candidate)
  raise ValueError(f"No JSON found in LLM response:\n{text[:300]}")


# ─── Content generation ────────────────────────────────────────────────────────

SYS_SPANISH_JSON = (
    "Eres un experto en diseño curricular teológico. "
    "Responde SIEMPRE en español. "
    "Responde ÚNICAMENTE con JSON válido, sin texto adicional."
)

_LANG_SUFFIX = {
    "es": ("Responde SIEMPRE en español. "
           "Responde ÚNICAMENTE con JSON válido, sin texto adicional."),
    "en": ("Always respond in English. "
           "Respond ONLY with valid JSON, no additional text."),
    "pt": ("Responda SEMPRE em português. "
           "Responda APENAS com JSON válido, sem texto adicional."),
    "fr": ("Répondez TOUJOURS en français. "
           "Répondez UNIQUEMENT avec du JSON valide, sans texte supplémentaire."),
    "de": ("Antworten Sie IMMER auf Deutsch. "
           "Antworten Sie NUR mit gültigem JSON, ohne zusätzlichen Text."),
}


def _sys(language: str) -> str:
    suffix = _LANG_SUFFIX.get(language,
        f"Always respond in this language code: {language}. Respond ONLY with valid JSON, no additional text.")
    return f"You are an expert in theological curriculum design. {suffix}"


def generate_course_structure(shortname, fullname, prompt, llm_url, model_id, api_key="",
                               num_modules=5, language="es"):
    print(f"  → Generating course structure ({num_modules} modules)…")
    messages = [
        {"role": "system", "content": _sys(language)},
        {"role": "user", "content": f"""
Design the structure of a university-level theological course.

Code: {shortname}
Name: {fullname}
Description: {prompt}

Return EXACTLY this JSON (no extra text):
{{
  "course_summary": "Descriptive paragraph of the course (150-200 words)",
  "modules": [
    {{
      "number": 1,
      "title": "Module 1: [title]",
      "objective": "Module objective in one sentence",
      "key_topics": ["topic 1", "topic 2", "topic 3", "topic 4"]
    }}
  ]
}}

Include exactly {num_modules} modules.
"""},
    ]
    max_tok = min(500 + num_modules * 300, 4000)
    raw = call_llm(messages, llm_url, model_id, temperature=0.7, max_tokens=max_tok, api_key=api_key)
    data = extract_json(raw)
    if len(data["modules"]) != num_modules:
        data["modules"] = data["modules"][:num_modules]
    return data


def generate_module_content(mod_num, mod_title, objective, key_topics,
                             course_fullname, professor, llm_url, model_id,
                             extra_instructions="", custom_prompt="", api_key="", language="es"):
    print(f"  → Module {mod_num}: {mod_title[:55]}…")
    if custom_prompt.strip():
        user_content = custom_prompt
    else:
        topics = ", ".join(key_topics)
        extra = f"\n\nInstrucciones adicionales:\n{extra_instructions}" if extra_instructions.strip() else ""
        user_content = f"""Genera el contenido académico completo para este módulo de teología.

Curso: {course_fullname}
Módulo {mod_num}: {mod_title}
Objetivo: {objective}
Temas: {topics}{extra}

Devuelve EXACTAMENTE este JSON:
{{
  "glossary": [
    {{"term": "término", "definition": "definición de 20-30 palabras"}}
  ],
  "sections": [
    {{
      "heading": "Título de la sección",
      "text": "Desarrollo académico de mínimo 250 palabras. Usar párrafos separados por doble salto de línea."
    }}
  ],
  "discussion_question": "Pregunta de discusión reflexiva relacionada con el módulo"
}}

Incluye exactamente 10 términos en glossary y entre 5 y 7 secciones."""
    messages = [
        {"role": "system", "content": _sys(language)},
        {"role": "user", "content": user_content},
    ]
    raw = call_llm(messages, llm_url, model_id, temperature=0.7, max_tokens=6000, api_key=api_key)
    return extract_json(raw)


def generate_syllabus(course_fullname, shortname, professor, modules, llm_url, model_id, api_key="", language="es"):
    print("  → Generating PRONTUARIO (syllabus)…")
    module_lines = "\n".join(
        f"- {m['title']}: {m['objective']}" for m in modules
    )
    messages = [
        {"role": "system", "content": _sys(language)},
        {"role": "user", "content": f"""
Genera el prontuario académico completo para este curso.

Nombre: {course_fullname}
Código: {shortname}
Profesor: {professor}
Email: {DEFAULT_EMAIL}
Teléfono: {DEFAULT_PHONE}

Módulos:
{module_lines}

Devuelve EXACTAMENTE este JSON:
{{
  "intro_html": "HTML con información de contacto y descripción breve. Usa <p>, <b>. Sin estilos CSS.",
  "content_html": "Prontuario completo en HTML (mínimo 800 palabras) con: objetivos generales, resumen de cada módulo, metodología, sistema de evaluación, bibliografía. Usa <h2>, <h3>, <p>, <b>, <ul>, <li>."
}}
"""},
    ]
    raw = call_llm(messages, llm_url, model_id, temperature=0.6, max_tokens=4000, api_key=api_key)
    return extract_json(raw)


def generate_quiz_questions(course_fullname, modules, num_questions, llm_url, model_id, api_key="", language="es"):
    print(f"  → Generating {num_questions} quiz questions…")
    module_summary = "\n".join(
        f"Módulo {m['number']}: {m['title']} — Temas: {', '.join(m.get('key_topics', []))}"
        for m in modules
    )
    all_q = []
    batch_size = 25
    for start in range(0, num_questions, batch_size):
        count = min(batch_size, num_questions - start)
        print(f"    → Questions {start+1}–{start+count}…")
        messages = [
            {"role": "system", "content": _sys(language)},
            {"role": "user", "content": f"""
Crea {count} preguntas de selección múltiple para el examen final del curso "{course_fullname}".

Contenido:
{module_summary}

Reglas:
- Exactamente 4 opciones por pregunta
- Solo UNA respuesta correcta
- Nivel universitario, académico
- Esta es la tanda {start//batch_size + 1}

Devuelve un JSON array de {count} objetos:
[
  {{
    "question": "Texto de la pregunta",
    "options": ["opción a", "opción b", "opción c", "opción d"],
    "correct_index": 0
  }}
]
"""},
        ]
        raw = call_llm(messages, llm_url, model_id, temperature=0.5, max_tokens=5000, api_key=api_key)
        batch = extract_json(raw)
        if not isinstance(batch, list):
            batch = batch.get("questions", [])
        all_q.extend(batch)
    return all_q[:num_questions]


def generate_homework_prompts(course_fullname, modules, homework_spec,
                              llm_url, model_id, api_key="", language="es"):
    """Generate homework descriptions for specified weeks.

    homework_spec: dict {module_num (1-based int): 'assign'|'forum'}
    Returns: dict {module_num: {'type': ..., 'title': ..., 'description': ...}}
    """
    if not homework_spec:
        return {}

    print(f"  → Generating homework prompts for weeks {sorted(homework_spec)}…")
    results = {}
    for mod_num, hw_type in sorted(homework_spec.items()):
        idx = mod_num - 1
        if idx >= len(modules):
            continue
        mod = modules[idx]
        hw_label = "tarea escrita (ensayo/investigación)" if hw_type == 'assign' \
                   else "foro de discusión adicional"

        messages = [
            {"role": "system", "content": _sys(language)},
            {"role": "user", "content": f"""
Crea una {hw_label} para el Módulo {mod_num} del curso "{course_fullname}".

Módulo: {mod['title']}
Objetivo: {mod['objective']}
Temas: {', '.join(mod.get('key_topics', []))}

{"Para una tarea escrita:" if hw_type == 'assign' else "Para un foro de discusión:"}
{"- Título de la tarea" if hw_type == 'assign' else "- Pregunta principal del foro"}
{"- Instrucciones detalladas (800-1000 palabras) en HTML: contexto, pasos, requisitos de formato, criterios de evaluación" if hw_type == 'assign' else "- Descripción del foro con contexto y preguntas guía (300-400 palabras) en HTML"}

Devuelve EXACTAMENTE este JSON:
{{
  "title": "Título {"de la tarea" if hw_type == 'assign' else "del foro"}",
  "description": "HTML {"con instrucciones completas" if hw_type == 'assign' else "con la pregunta y contexto"}. Usa <p>, <b>, <ul>, <li>. Sin estilos CSS."
}}
"""},
        ]
        raw = call_llm(messages, llm_url, model_id, temperature=0.7, max_tokens=2000, api_key=api_key)
        data = extract_json(raw)
        results[mod_num] = {
            'type':        hw_type,
            'title':       data.get('title', f'Tarea #{mod_num}'),
            'description': data.get('description', ''),
        }
        print(f"      ✓ Module {mod_num} ({hw_type}): {results[mod_num]['title'][:60]}")
    return results


# ─── HTML helpers ──────────────────────────────────────────────────────────────

def xe(text):
    """Escape text for HTML embedding (will later be XML-escaped once)."""
    return html.escape(str(text), quote=False)


def glossary_to_html(glossary, course_fullname, professor):
    """Header + glossary as an HTML string ready for XML embedding."""
    parts = [
        f'<p align="center"><span lang="ES">{xe(COLLEGE_NAME)}</span></p>',
        f'<p align="center"><span lang="ES">CURSO: {xe(course_fullname)}</span></p>',
        f'<p align="center"><span lang="ES">PROFESOR: {xe(professor)}</span></p>',
        '<p>&nbsp;</p>',
        '<p><b>Glosario de Términos</b></p>',
        '<p>&nbsp;</p>',
    ]
    for i, item in enumerate(glossary, 1):
        term = xe(item.get('term', ''))
        defn = xe(item.get('definition', ''))
        parts.append(f'<p>{i}. <b>{term}</b>: {defn}</p>')
    return ''.join(parts)


def sections_to_html(sections):
    """Lecture sections as an HTML string ready for XML embedding."""
    parts = []
    for sec in sections:
        heading = xe(sec.get('heading', ''))
        parts.append(f'<p><b><span lang="ES">{heading}</span></b></p>')
        parts.append('<p><span lang="ES">&nbsp;</span></p>')
        raw_text = sec.get('text', '')
        for para in re.split(r'\n\n+', raw_text):
            para = para.strip().replace('\n', ' ')
            if para:
                parts.append(f'<p><span lang="ES">{xe(para)}</span></p>')
        parts.append('<p><span lang="ES">&nbsp;</span></p>')
    return ''.join(parts)


def to_xml(html_str):
    """Escape a complete HTML string for storage inside an XML element."""
    return html.escape(html_str, quote=False)


# ─── MBZ builder ──────────────────────────────────────────────────────────────

def now_ts():
    return int(time.time())


def rand_hex(n=12):
    return uuid.uuid4().hex[:n]


def build_mbz(config, content):
    """
    Assemble all XML files and return the complete .mbz as bytes.

    ID scheme (all small — Moodle remaps on restore):
      Sections  : 1 (general), 2–6 (modules 1–5)
      Module IDs: 101–118
      Context IDs: module_id + 1000
    """
    shortname  = config['shortname']
    fullname   = config['fullname']
    professor  = config['professor']
    category   = config['category']
    start_ts   = config['start_ts']
    end_ts     = config['end_ts']
    now        = now_ts()

    course_structure = content['course_structure']
    modules          = course_structure['modules']
    module_contents  = content['module_contents']
    syllabus         = content['syllabus']
    quiz_questions   = content['quiz_questions']

    # ── ID constants ───────────────────────────────────────────────────────────
    SEC_GENERAL  = 1
    n_mods       = len(modules)
    SEC_MODS     = list(range(2, n_mods + 2))

    MOD_ATTEND   = 101
    MOD_FEEDBACK = 102
    MOD_BBB1     = 103   # Aula Virtual
    MOD_BBB2     = 104   # Grabaciones
    MOD_LABEL    = 105
    MOD_PRONT    = 106   # PRONTUARIO
    MOD_QUIZ     = 107
    MOD_QBANK    = 108

    # Per-module page/forum pairs. For N modules: pages 109,111,...; forums 110,112,...
    MOD_PAIRS = [{'page': 109 + i*2, 'forum': 110 + i*2} for i in range(n_mods)]

    # Homework activities: IDs 119+ assigned to modules that have homework
    # homework_spec: {1: 'assign', 3: 'forum', ...}  (1-based module number)
    homework_spec    = config.get('homework_spec', {})   # {mod_num(int): 'assign'|'forum'}
    homework_prompts = content.get('homework_prompts', {})
    # Map module number → homework module ID (119, 120, …)
    hw_mids = {}
    hw_counter = 109 + 2 * n_mods
    for mod_num in sorted(homework_spec):
        hw_mids[mod_num] = hw_counter
        hw_counter += 1

    def ctx(mid): return mid + 1000

    # ── Helpers ────────────────────────────────────────────────────────────────
    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:

        def add(path, data):
            zf.writestr(path, data)

        def add_activity_aux(act_dir, grades_body=None):
            for fname, body in [
                ('grades.xml',       grades_body if grades_body is not None else _GRADES),
                ('roles.xml',        _ROLES),
                ('filters.xml',      _FILTERS),
                ('comments.xml',     _COMMENTS),
                ('logs.xml',         _LOGS),
                ('inforef.xml',      _INFOREF),
                ('competencies.xml', _COMPETENCIES),
                ('xapistate.xml',    _XAPISTATE),
                ('calendar.xml',     _CALENDAR),
            ]:
                add(f'activities/{act_dir}/{fname}', body)

        def add_module_xml(act_dir, mid, mtype, sec_id, sec_num):
            add(f'activities/{act_dir}/module.xml', f'''\
<?xml version="1.0" encoding="UTF-8"?>
<module id="{mid}" version="2025100600">
  <modulename>{mtype}</modulename>
  <sectionid>{sec_id}</sectionid>
  <sectionnumber>{sec_num}</sectionnumber>
  <idnumber></idnumber>
  <added>{now}</added>
  <score>0</score>
  <indent>0</indent>
  <visible>1</visible>
  <visibleoncoursepage>1</visibleoncoursepage>
  <visibleold>1</visibleold>
  <groupmode>0</groupmode>
  <groupingid>0</groupingid>
  <completion>0</completion>
  <completiongradeitemnumber>$@NULL@$</completiongradeitemnumber>
  <completionpassgrade>0</completionpassgrade>
  <completionview>0</completionview>
  <completionexpected>0</completionexpected>
  <availability>$@NULL@$</availability>
  <showdescription>1</showdescription>
  <downloadcontent>1</downloadcontent>
  <lang></lang>
  <enableaitools>$@NULL@$</enableaitools>
  <enabledaiactions>$@NULL@$</enabledaiactions>
  <tags>
  </tags>
</module>''')

        # ── moodle_backup.xml ──────────────────────────────────────────────────
        sec0_acts = [
            (MOD_ATTEND,   'attendance',     'Asistencia'),
            (MOD_FEEDBACK, 'feedback',       'Encuesta del Curso'),
            (MOD_BBB1,     'bigbluebuttonbn','Aula Virtual'),
            (MOD_BBB2,     'bigbluebuttonbn','Grabaciones'),
            (MOD_LABEL,    'label',          'Evaluacion del Curso'),
            (MOD_PRONT,    'page',           'PRONTUARIO'),
            (MOD_QUIZ,     'quiz',           'Examen Final'),
            (MOD_QBANK,    'qbank',          f'{shortname} question bank'),
        ]

        act_entries, sec_entries, act_settings = [], [], []

        for mid, mtype, title in sec0_acts:
            act_entries.append(f'''\
        <activity>
          <moduleid>{mid}</moduleid>
          <sectionid>{SEC_GENERAL}</sectionid>
          <modulename>{mtype}</modulename>
          <title>{xe(title)}</title>
          <directory>activities/{mtype}_{mid}</directory>
          <insubsection></insubsection>
        </activity>''')

        for i, mod in enumerate(modules):
            p, f_ = MOD_PAIRS[i]['page'], MOD_PAIRS[i]['forum']
            sid = SEC_MODS[i]
            disc_q = module_contents[i].get('discussion_question', mod['title'])
            forum_title = xe(f"Discusion #{i+1} - {disc_q[:60]}")
            act_entries.append(f'''\
        <activity>
          <moduleid>{p}</moduleid>
          <sectionid>{sid}</sectionid>
          <modulename>page</modulename>
          <title>Material y Contenido</title>
          <directory>activities/page_{p}</directory>
          <insubsection></insubsection>
        </activity>''')
            act_entries.append(f'''\
        <activity>
          <moduleid>{f_}</moduleid>
          <sectionid>{sid}</sectionid>
          <modulename>forum</modulename>
          <title>{forum_title}</title>
          <directory>activities/forum_{f_}</directory>
          <insubsection></insubsection>
        </activity>''')
            # Homework activity for this module (if any)
            mod_num = i + 1
            if mod_num in hw_mids:
                hw_mid  = hw_mids[mod_num]
                hw_type = homework_spec[mod_num]
                hw_info = homework_prompts.get(mod_num, {})
                hw_title= hw_info.get('title', f'{"Asignacion" if hw_type == "assign" else "Tarea Foro"} #{mod_num}')
                act_entries.append(f'''\
        <activity>
          <moduleid>{hw_mid}</moduleid>
          <sectionid>{sid}</sectionid>
          <modulename>{hw_type}</modulename>
          <title>{xe(hw_title)}</title>
          <directory>activities/{hw_type}_{hw_mid}</directory>
          <insubsection></insubsection>
        </activity>''')

        sec_entries.append(f'''\
        <section>
          <sectionid>{SEC_GENERAL}</sectionid>
          <title>0</title>
          <directory>sections/section_{SEC_GENERAL}</directory>
          <parentcmid></parentcmid>
          <modname></modname>
        </section>''')
        for i, mod in enumerate(modules):
            sec_entries.append(f'''\
        <section>
          <sectionid>{SEC_MODS[i]}</sectionid>
          <title>{xe(mod['title'])}</title>
          <directory>sections/section_{SEC_MODS[i]}</directory>
          <parentcmid></parentcmid>
          <modname></modname>
        </section>''')

        all_act_dirs = [f'{t}_{m}' for m, t, _ in sec0_acts]
        for i in range(n_mods):
            all_act_dirs += [f'page_{MOD_PAIRS[i]["page"]}',
                             f'forum_{MOD_PAIRS[i]["forum"]}']
        for mod_num, hw_mid in sorted(hw_mids.items()):
            all_act_dirs.append(f'{homework_spec[mod_num]}_{hw_mid}')

        for sid in [SEC_GENERAL] + SEC_MODS:
            act_settings.append(f'''\
      <setting>
        <level>section</level>
        <section>section_{sid}</section>
        <name>section_{sid}_included</name>
        <value>1</value>
      </setting>
      <setting>
        <level>section</level>
        <section>section_{sid}</section>
        <name>section_{sid}_userinfo</name>
        <value>0</value>
      </setting>''')

        for adir in all_act_dirs:
            act_settings.append(f'''\
      <setting>
        <level>activity</level>
        <activity>{adir}</activity>
        <name>{adir}_included</name>
        <value>1</value>
      </setting>
      <setting>
        <level>activity</level>
        <activity>{adir}</activity>
        <name>{adir}_userinfo</name>
        <value>0</value>
      </setting>''')

        backup_fn = f"backup-moodle2-course-{shortname}-{datetime.now().strftime('%Y%m%d-%H%M')}.mbz"

        add('moodle_backup.xml', f'''\
<?xml version="1.0" encoding="UTF-8"?>
<moodle_backup>
  <information>
    <name>{backup_fn}</name>
    <moodle_version>2025100602.01</moodle_version>
    <moodle_release>5.1.2+ (Build: 20260210)</moodle_release>
    <backup_version>2025100600</backup_version>
    <backup_release>5.1</backup_release>
    <backup_date>{now}</backup_date>
    <mnet_remoteusers>0</mnet_remoteusers>
    <include_files>1</include_files>
    <include_file_references_to_external_content>0</include_file_references_to_external_content>
    <original_wwwroot>https://your-moodle.example.com</original_wwwroot>
    <original_site_identifier_hash>{rand_hex(32)}</original_site_identifier_hash>
    <original_course_id>0</original_course_id>
    <original_course_format>weeks</original_course_format>
    <original_course_fullname>{xe(fullname)}</original_course_fullname>
    <original_course_shortname>{xe(shortname)}</original_course_shortname>
    <original_course_startdate>{start_ts}</original_course_startdate>
    <original_course_enddate>{end_ts}</original_course_enddate>
    <original_course_contextid>1</original_course_contextid>
    <original_system_contextid>1</original_system_contextid>
    <details>
      <detail backup_id="{rand_hex(32)}">
        <type>course</type>
        <format>moodle2</format>
        <interactive>1</interactive>
        <mode>10</mode>
        <execution>1</execution>
        <executiontime>0</executiontime>
      </detail>
    </details>
    <contents>
      <activities>
{chr(10).join(act_entries)}
      </activities>
      <sections>
{chr(10).join(sec_entries)}
      </sections>
      <course>
        <courseid>0</courseid>
        <title>{xe(shortname)}</title>
        <directory>course</directory>
      </course>
    </contents>
    <settings>
      <setting>
        <level>root</level>
        <name>filename</name>
        <value>{backup_fn}</value>
      </setting>
      <setting><level>root</level><name>imscc11</name><value>0</value></setting>
      <setting><level>root</level><name>users</name><value>0</value></setting>
      <setting><level>root</level><name>anonymize</name><value>0</value></setting>
      <setting><level>root</level><name>role_assignments</name><value>0</value></setting>
      <setting><level>root</level><name>activities</name><value>1</value></setting>
      <setting><level>root</level><name>blocks</name><value>1</value></setting>
      <setting><level>root</level><name>files</name><value>1</value></setting>
      <setting><level>root</level><name>filters</name><value>1</value></setting>
      <setting><level>root</level><name>comments</name><value>1</value></setting>
      <setting><level>root</level><name>badges</name><value>1</value></setting>
      <setting><level>root</level><name>calendarevents</name><value>1</value></setting>
      <setting><level>root</level><name>userscompletion</name><value>0</value></setting>
      <setting><level>root</level><name>logs</name><value>0</value></setting>
      <setting><level>root</level><name>grade_histories</name><value>0</value></setting>
      <setting><level>root</level><name>groups</name><value>1</value></setting>
      <setting><level>root</level><name>competencies</name><value>1</value></setting>
      <setting><level>root</level><name>customfield</name><value>1</value></setting>
      <setting><level>root</level><name>contentbankcontent</name><value>1</value></setting>
      <setting><level>root</level><name>xapistate</name><value>1</value></setting>
      <setting><level>root</level><name>legacyfiles</name><value>1</value></setting>
{chr(10).join(act_settings)}
    </settings>
  </information>
</moodle_backup>''')

        # ── course/course.xml ──────────────────────────────────────────────────
        summary_html = to_xml(
            f'<p dir="ltr" style="text-align: left;">'
            f'{xe(course_structure.get("course_summary", fullname))}</p>'
        )
        add('course/course.xml', f'''\
<?xml version="1.0" encoding="UTF-8"?>
<course id="0" contextid="1">
  <shortname>{xe(shortname)}</shortname>
  <fullname>{xe(fullname)}</fullname>
  <idnumber></idnumber>
  <summary>{summary_html}</summary>
  <summaryformat>1</summaryformat>
  <format>weeks</format>
  <showgrades>1</showgrades>
  <newsitems>0</newsitems>
  <startdate>{start_ts}</startdate>
  <enddate>{end_ts}</enddate>
  <marker>0</marker>
  <maxbytes>512000</maxbytes>
  <legacyfiles>0</legacyfiles>
  <showreports>1</showreports>
  <visible>1</visible>
  <groupmode>0</groupmode>
  <groupmodeforce>0</groupmodeforce>
  <defaultgroupingid>0</defaultgroupingid>
  <lang></lang>
  <theme></theme>
  <timecreated>{now}</timecreated>
  <timemodified>{now}</timemodified>
  <requested>0</requested>
  <showactivitydates>1</showactivitydates>
  <showcompletionconditions>1</showcompletionconditions>
  <pdfexportfont>$@NULL@$</pdfexportfont>
  <enablecompletion>1</enablecompletion>
  <completionnotify>0</completionnotify>
  <enableaitools>1</enableaitools>
  <category id="1">
    <name>{xe(category)}</name>
    <description></description>
  </category>
  <tags></tags>
  <customfields></customfields>
  <courseformatoptions>
    <courseformatoption>
      <format>weeks</format><sectionid>0</sectionid>
      <name>hiddensections</name><value>0</value>
    </courseformatoption>
    <courseformatoption>
      <format>weeks</format><sectionid>0</sectionid>
      <name>coursedisplay</name><value>0</value>
    </courseformatoption>
    <courseformatoption>
      <format>weeks</format><sectionid>0</sectionid>
      <name>automaticenddate</name><value>1</value>
    </courseformatoption>
  </courseformatoptions>
</course>''')

        for fname, body in [
            ('course/competencies.xml', _COMPETENCIES),
            ('course/filters.xml',      _FILTERS),
            ('course/roles.xml',        _ROLES),
            ('course/inforef.xml',      _INFOREF),
            ('course/enrolments.xml',
             '<?xml version="1.0" encoding="UTF-8"?>\n<enrolments>\n  <enrols>\n  </enrols>\n</enrolments>'),
            ('course/logs.xml',         _LOGS),
            ('course/comments.xml',     _COMMENTS),
            ('course/contentbank.xml',
             '<?xml version="1.0" encoding="UTF-8"?>\n<contentbank>\n</contentbank>'),
            ('course/completiondefaults.xml',
             '<?xml version="1.0" encoding="UTF-8"?>\n<course_completion_defaults>\n</course_completion_defaults>'),
            ('course/calendar.xml',
             '<?xml version="1.0" encoding="UTF-8"?>\n<events>\n</events>'),
            ('course/logstores.xml',
             '<?xml version="1.0" encoding="UTF-8"?>\n<logstores>\n</logstores>'),
            ('course/loglastaccess.xml',
             '<?xml version="1.0" encoding="UTF-8"?>\n<lastaccesses>\n</lastaccesses>'),
        ]:
            add(fname, body)

        # ── Sections ───────────────────────────────────────────────────────────
        sec0_seq = ','.join(str(m) for m in [
            MOD_ATTEND, MOD_FEEDBACK, MOD_BBB1, MOD_BBB2,
            MOD_LABEL, MOD_PRONT, MOD_QUIZ, MOD_QBANK
        ])
        add(f'sections/section_{SEC_GENERAL}/section.xml', f'''\
<?xml version="1.0" encoding="UTF-8"?>
<section id="{SEC_GENERAL}">
  <number>0</number>
  <name>$@NULL@$</name>
  <summary></summary>
  <summaryformat>1</summaryformat>
  <sequence>{sec0_seq}</sequence>
  <visible>1</visible>
  <availabilityjson>$@NULL@$</availabilityjson>
  <component>$@NULL@$</component>
  <itemid>$@NULL@$</itemid>
  <timemodified>{now}</timemodified>
</section>''')
        add(f'sections/section_{SEC_GENERAL}/inforef.xml', _INFOREF)

        for i, mod in enumerate(modules):
            sid      = SEC_MODS[i]
            mod_num  = i + 1
            page_id  = MOD_PAIRS[i]['page']
            forum_id = MOD_PAIRS[i]['forum']
            seq = (f"{page_id},{forum_id},{hw_mids[mod_num]}"
                   if mod_num in hw_mids else f"{page_id},{forum_id}")
            add(f'sections/section_{sid}/section.xml', f'''\
<?xml version="1.0" encoding="UTF-8"?>
<section id="{sid}">
  <number>{i+1}</number>
  <name>{xe(mod['title'])}</name>
  <summary></summary>
  <summaryformat>1</summaryformat>
  <sequence>{seq}</sequence>
  <visible>1</visible>
  <availabilityjson>$@NULL@$</availabilityjson>
  <component>$@NULL@$</component>
  <itemid>$@NULL@$</itemid>
  <timemodified>{now}</timemodified>
</section>''')
            add(f'sections/section_{sid}/inforef.xml', _INFOREF)

        # ── ATTENDANCE ─────────────────────────────────────────────────────────
        adir = f'attendance_{MOD_ATTEND}'
        add(f'activities/{adir}/attendance.xml', f'''\
<?xml version="1.0" encoding="UTF-8"?>
<activity id="{MOD_ATTEND}" moduleid="{MOD_ATTEND}" modulename="attendance" contextid="{ctx(MOD_ATTEND)}">
  <attendance id="{MOD_ATTEND}">
    <name>Asistencia</name>
    <intro></intro>
    <introformat>1</introformat>
    <grade>100</grade>
    <showextrauserdetails>1</showextrauserdetails>
    <showsessiondetails>1</showsessiondetails>
    <sessiondetailspos>left</sessiondetailspos>
    <subnet></subnet>
    <statuses>
      <status id="1"><acronym>P</acronym><description>Present</description><grade>2.00</grade>
        <studentavailability>$@NULL@$</studentavailability><availablebeforesession>$@NULL@$</availablebeforesession>
        <setunmarked>$@NULL@$</setunmarked><visible>1</visible><deleted>0</deleted><setnumber>0</setnumber>
      </status>
      <status id="2"><acronym>A</acronym><description>Absent</description><grade>0.00</grade>
        <studentavailability>$@NULL@$</studentavailability><availablebeforesession>$@NULL@$</availablebeforesession>
        <setunmarked>$@NULL@$</setunmarked><visible>1</visible><deleted>0</deleted><setnumber>0</setnumber>
      </status>
      <status id="3"><acronym>L</acronym><description>Late</description><grade>1.00</grade>
        <studentavailability>$@NULL@$</studentavailability><availablebeforesession>$@NULL@$</availablebeforesession>
        <setunmarked>$@NULL@$</setunmarked><visible>1</visible><deleted>0</deleted><setnumber>0</setnumber>
      </status>
      <status id="4"><acronym>E</acronym><description>Excused</description><grade>1.00</grade>
        <studentavailability>$@NULL@$</studentavailability><availablebeforesession>$@NULL@$</availablebeforesession>
        <setunmarked>$@NULL@$</setunmarked><visible>1</visible><deleted>0</deleted><setnumber>0</setnumber>
      </status>
    </statuses>
    <sessions></sessions>
    <user_grades></user_grades>
    <warnings></warnings>
  </attendance>
</activity>''')
        add_module_xml(adir, MOD_ATTEND, 'attendance', SEC_GENERAL, 0)
        add_activity_aux(adir)

        # ── FEEDBACK ───────────────────────────────────────────────────────────
        adir = f'feedback_{MOD_FEEDBACK}'
        add(f'activities/{adir}/feedback.xml', f'''\
<?xml version="1.0" encoding="UTF-8"?>
<activity id="{MOD_FEEDBACK}" moduleid="{MOD_FEEDBACK}" modulename="feedback" contextid="{ctx(MOD_FEEDBACK)}">
  <feedback id="{MOD_FEEDBACK}">
    <name>Encuesta del Curso</name>
    <intro></intro>
    <introformat>1</introformat>
    <anonymous>1</anonymous>
    <email_notification>0</email_notification>
    <multiple_submit>0</multiple_submit>
    <autonumbering>0</autonumbering>
    <site_after_submit></site_after_submit>
    <page_after_submit></page_after_submit>
    <page_after_submitformat>1</page_after_submitformat>
    <publish_stats>0</publish_stats>
    <timeopen>0</timeopen>
    <timeclose>0</timeclose>
    <timemodified>{now}</timemodified>
    <completionsubmit>0</completionsubmit>
    <items>
      <item id="1">
        <template>0</template><name></name><label></label>
        <presentation>&lt;p&gt;En una escala del 1 al 10, evalúe las siguientes aseveraciones:&lt;/p&gt;</presentation>
        <typ>label</typ><hasvalue>0</hasvalue><position>1</position>
        <required>0</required><dependitem>0</dependitem><dependvalue></dependvalue><options></options>
      </item>
      <item id="2">
        <template>0</template>
        <name>La información del curso fue presentada claramente.</name>
        <label></label>
        <presentation>r&gt;&gt;&gt;&gt;&gt;1|2|3|4|5|6|7|8|9|10&lt;&lt;&lt;&lt;&lt;1</presentation>
        <typ>multichoice</typ><hasvalue>1</hasvalue><position>2</position>
        <required>1</required><dependitem>0</dependitem><dependvalue></dependvalue><options></options>
      </item>
      <item id="3">
        <template>0</template>
        <name>El profesor estuvo disponible y fue accesible.</name>
        <label></label>
        <presentation>r&gt;&gt;&gt;&gt;&gt;1|2|3|4|5|6|7|8|9|10&lt;&lt;&lt;&lt;&lt;1</presentation>
        <typ>multichoice</typ><hasvalue>1</hasvalue><position>3</position>
        <required>1</required><dependitem>0</dependitem><dependvalue></dependvalue><options></options>
      </item>
      <item id="4">
        <template>0</template>
        <name>El curso cumplió con mis expectativas de aprendizaje.</name>
        <label></label>
        <presentation>r&gt;&gt;&gt;&gt;&gt;1|2|3|4|5|6|7|8|9|10&lt;&lt;&lt;&lt;&lt;1</presentation>
        <typ>multichoice</typ><hasvalue>1</hasvalue><position>4</position>
        <required>1</required><dependitem>0</dependitem><dependvalue></dependvalue><options></options>
      </item>
      <item id="5">
        <template>0</template>
        <name>Comentarios adicionales (opcional)</name>
        <label></label>
        <presentation>40|5</presentation>
        <typ>textarea</typ><hasvalue>1</hasvalue><position>5</position>
        <required>0</required><dependitem>0</dependitem><dependvalue></dependvalue><options></options>
      </item>
    </items>
    <completed></completed>
    <completedtmps></completedtmps>
  </feedback>
</activity>''')
        add_module_xml(adir, MOD_FEEDBACK, 'feedback', SEC_GENERAL, 0)
        add_activity_aux(adir)

        # ── BIGBLUEBUTTON — Aula Virtual ───────────────────────────────────────
        adir = f'bigbluebuttonbn_{MOD_BBB1}'
        add(f'activities/{adir}/bigbluebuttonbn.xml', f'''\
<?xml version="1.0" encoding="UTF-8"?>
<activity id="{MOD_BBB1}" moduleid="{MOD_BBB1}" modulename="bigbluebuttonbn" contextid="{ctx(MOD_BBB1)}">
  <bigbluebuttonbn id="{MOD_BBB1}">
    <type>1</type>
    <course>0</course>
    <name>Aula Virtual</name>
    <intro></intro>
    <introformat>1</introformat>
    <meetingid>{uuid.uuid4().hex}</meetingid>
    <moderatorpass>{rand_hex(12)}</moderatorpass>
    <viewerpass>{rand_hex(12)}</viewerpass>
    <wait>0</wait>
    <record>1</record>
    <recordallfromstart>1</recordallfromstart>
    <recordhidebutton>0</recordhidebutton>
    <welcome></welcome>
    <voicebridge>0</voicebridge>
    <openingtime>0</openingtime>
    <closingtime>0</closingtime>
    <timecreated>{now}</timecreated>
    <timemodified>0</timemodified>
    <presentation></presentation>
    <participants>[{{"selectiontype":"all","selectionid":"all","role":"viewer"}},{{"selectiontype":"role","selectionid":"3","role":"moderator"}}]</participants>
    <userlimit>100</userlimit>
    <recordings_html>0</recordings_html>
    <recordings_deleted>1</recordings_deleted>
    <recordings_imported>0</recordings_imported>
    <recordings_preview>1</recordings_preview>
    <clienttype>0</clienttype>
    <muteonstart>0</muteonstart>
    <completionattendance>0</completionattendance>
    <completionengagementchats>0</completionengagementchats>
    <completionengagementtalks>0</completionengagementtalks>
    <completionengagementraisehand>0</completionengagementraisehand>
    <completionengagementpollvotes>0</completionengagementpollvotes>
    <completionengagementemojis>0</completionengagementemojis>
    <guestallowed>0</guestallowed>
    <mustapproveuser>1</mustapproveuser>
    <showpresentation>1</showpresentation>
    <grade>0</grade>
    <logs></logs>
    <recordings></recordings>
  </bigbluebuttonbn>
</activity>''')
        add_module_xml(adir, MOD_BBB1, 'bigbluebuttonbn', SEC_GENERAL, 0)
        add_activity_aux(adir)

        # ── BIGBLUEBUTTON — Grabaciones ────────────────────────────────────────
        adir = f'bigbluebuttonbn_{MOD_BBB2}'
        add(f'activities/{adir}/bigbluebuttonbn.xml', f'''\
<?xml version="1.0" encoding="UTF-8"?>
<activity id="{MOD_BBB2}" moduleid="{MOD_BBB2}" modulename="bigbluebuttonbn" contextid="{ctx(MOD_BBB2)}">
  <bigbluebuttonbn id="{MOD_BBB2}">
    <type>2</type>
    <course>0</course>
    <name>Grabaciones</name>
    <intro></intro>
    <introformat>1</introformat>
    <meetingid>{uuid.uuid4().hex}</meetingid>
    <moderatorpass>{rand_hex(12)}</moderatorpass>
    <viewerpass>{rand_hex(12)}</viewerpass>
    <wait>0</wait>
    <record>0</record>
    <recordallfromstart>0</recordallfromstart>
    <recordhidebutton>0</recordhidebutton>
    <welcome></welcome>
    <voicebridge>0</voicebridge>
    <openingtime>0</openingtime>
    <closingtime>0</closingtime>
    <timecreated>{now}</timecreated>
    <timemodified>0</timemodified>
    <presentation></presentation>
    <participants>[{{"selectiontype":"all","selectionid":"all","role":"viewer"}},{{"selectiontype":"role","selectionid":"3","role":"moderator"}}]</participants>
    <userlimit>0</userlimit>
    <recordings_html>0</recordings_html>
    <recordings_deleted>1</recordings_deleted>
    <recordings_imported>0</recordings_imported>
    <recordings_preview>1</recordings_preview>
    <clienttype>0</clienttype>
    <muteonstart>0</muteonstart>
    <completionattendance>0</completionattendance>
    <completionengagementchats>0</completionengagementchats>
    <completionengagementtalks>0</completionengagementtalks>
    <completionengagementraisehand>0</completionengagementraisehand>
    <completionengagementpollvotes>0</completionengagementpollvotes>
    <completionengagementemojis>0</completionengagementemojis>
    <guestallowed>0</guestallowed>
    <mustapproveuser>0</mustapproveuser>
    <showpresentation>0</showpresentation>
    <grade>0</grade>
    <logs></logs>
    <recordings></recordings>
  </bigbluebuttonbn>
</activity>''')
        add_module_xml(adir, MOD_BBB2, 'bigbluebuttonbn', SEC_GENERAL, 0)
        add_activity_aux(adir)

        # ── LABEL — Evaluación ─────────────────────────────────────────────────
        adir = f'label_{MOD_LABEL}'
        label_html = to_xml(
            '<p>Estimados Estudiantes, estas son las formas de obtener su calificación final:</p>'
            '<p><b>Opción A — Discusiones:</b></p>'
            '<p>15 puntos por Entrada de Discusión × 4 = 60 puntos</p>'
            '<p>7.5 puntos por Respuesta × 4 = 30 puntos</p>'
            '<p>2 puntos por Asistencia × 5 = 10 puntos</p>'
            '<p><b>Total: 100 puntos</b></p>'
            '<p>&nbsp;</p>'
            '<p><b>Opción B — Examen Final (Opcional):</b></p>'
            '<p>90% = Nota del Examen Final × 90%</p>'
            '<p>10% = Asistencia</p>'
        )
        add(f'activities/{adir}/label.xml', f'''\
<?xml version="1.0" encoding="UTF-8"?>
<activity id="{MOD_LABEL}" moduleid="{MOD_LABEL}" modulename="label" contextid="{ctx(MOD_LABEL)}">
  <label id="{MOD_LABEL}">
    <name>Evaluacion del Curso</name>
    <intro>{label_html}</intro>
    <introformat>1</introformat>
    <timemodified>{now}</timemodified>
  </label>
</activity>''')
        add_module_xml(adir, MOD_LABEL, 'label', SEC_GENERAL, 0)
        add_activity_aux(adir)

        # ── PAGE — PRONTUARIO ──────────────────────────────────────────────────
        adir = f'page_{MOD_PRONT}'
        pront_intro = to_xml(syllabus.get('intro_html', ''))
        pront_content = to_xml(syllabus.get('content_html', ''))
        add(f'activities/{adir}/page.xml', f'''\
<?xml version="1.0" encoding="UTF-8"?>
<activity id="{MOD_PRONT}" moduleid="{MOD_PRONT}" modulename="page" contextid="{ctx(MOD_PRONT)}">
  <page id="{MOD_PRONT}">
    <name>PRONTUARIO</name>
    <intro>{pront_intro}</intro>
    <introformat>1</introformat>
    <content>{pront_content}</content>
    <contentformat>1</contentformat>
    <legacyfiles>0</legacyfiles>
    <legacyfileslast>$@NULL@$</legacyfileslast>
    <display>5</display>
    <displayoptions>a:2:{{s:10:"printintro";s:1:"0";s:17:"printlastmodified";s:1:"1";}}</displayoptions>
    <revision>1</revision>
    <timemodified>{now}</timemodified>
  </page>
</activity>''')
        add_module_xml(adir, MOD_PRONT, 'page', SEC_GENERAL, 0)
        add_activity_aux(adir)

        # ── QUIZ ───────────────────────────────────────────────────────────────
        adir  = f'quiz_{MOD_QUIZ}'
        nq    = len(quiz_questions)
        qi_lines = []
        for slot, q_idx in enumerate(range(nq), 1):
            qbe_id = q_idx + 1
            qi_lines.append(f'''\
      <question_instance id="{slot}">
        <quizid>{MOD_QUIZ}</quizid>
        <slot>{slot}</slot>
        <page>1</page>
        <displaynumber>$@NULL@$</displaynumber>
        <requireprevious>0</requireprevious>
        <maxmark>1.0000000</maxmark>
        <quizgradeitemid>$@NULL@$</quizgradeitemid>
        <question_reference id="{slot}">
          <usingcontextid>{ctx(MOD_QUIZ)}</usingcontextid>
          <component>mod_quiz</component>
          <questionarea>slot</questionarea>
          <questionbankentryid>{qbe_id}</questionbankentryid>
          <version>$@NULL@$</version>
        </question_reference>
      </question_instance>''')

        quiz_intro = (
            f'&lt;p style="text-align: center;"&gt;&lt;span lang="ES"&gt;{xe(COLLEGE_NAME)}&lt;/span&gt;&lt;/p&gt;\n'
            f'&lt;p style="text-align: center;"&gt;&lt;span lang="ES"&gt;CURSO: {xe(fullname)}&lt;/span&gt;&lt;/p&gt;\n'
            f'&lt;p style="text-align: center;"&gt;&lt;span lang="ES"&gt;PROFESOR: {xe(professor)}&lt;/span&gt;&lt;/p&gt;\n'
            '&lt;h3 style="text-align: center;"&gt;&lt;span lang="ES"&gt;EXAMEN FINAL&lt;/span&gt;&lt;/h3&gt;'
        )
        add(f'activities/{adir}/quiz.xml', f'''\
<?xml version="1.0" encoding="UTF-8"?>
<activity id="{MOD_QUIZ}" moduleid="{MOD_QUIZ}" modulename="quiz" contextid="{ctx(MOD_QUIZ)}">
  <quiz id="{MOD_QUIZ}">
    <name>Examen Final</name>
    <intro>{quiz_intro}</intro>
    <introformat>1</introformat>
    <timeopen>0</timeopen>
    <timeclose>0</timeclose>
    <timelimit>7200</timelimit>
    <overduehandling>autosubmit</overduehandling>
    <graceperiod>0</graceperiod>
    <preferredbehaviour>deferredfeedback</preferredbehaviour>
    <canredoquestions>0</canredoquestions>
    <attempts_number>1</attempts_number>
    <attemptonlast>0</attemptonlast>
    <grademethod>1</grademethod>
    <decimalpoints>2</decimalpoints>
    <questiondecimalpoints>-1</questiondecimalpoints>
    <reviewattempt>69632</reviewattempt>
    <reviewcorrectness>4096</reviewcorrectness>
    <reviewmaxmarks>69888</reviewmaxmarks>
    <reviewmarks>4096</reviewmarks>
    <reviewspecificfeedback>0</reviewspecificfeedback>
    <reviewgeneralfeedback>0</reviewgeneralfeedback>
    <reviewrightanswer>0</reviewrightanswer>
    <reviewoverallfeedback>0</reviewoverallfeedback>
    <questionsperpage>1</questionsperpage>
    <navmethod>free</navmethod>
    <shuffleanswers>1</shuffleanswers>
    <sumgrades>{float(nq):.5f}</sumgrades>
    <grade>{float(nq):.5f}</grade>
    <timecreated>{now}</timecreated>
    <timemodified>{now}</timemodified>
    <password></password>
    <subnet></subnet>
    <browsersecurity>-</browsersecurity>
    <delay1>0</delay1>
    <delay2>0</delay2>
    <showuserpicture>0</showuserpicture>
    <showblocks>0</showblocks>
    <completionattemptsexhausted>0</completionattemptsexhausted>
    <completionminattempts>0</completionminattempts>
    <allowofflineattempts>0</allowofflineattempts>
    <precreateattempts>$@NULL@$</precreateattempts>
    <subplugin_quizaccess_seb_quiz></subplugin_quizaccess_seb_quiz>
    <quiz_grade_items></quiz_grade_items>
    <question_instances>
{chr(10).join(qi_lines)}
    </question_instances>
    <feedbacks></feedbacks>
    <overrides></overrides>
    <grades></grades>
    <attempts></attempts>
  </quiz>
</activity>''')
        add_module_xml(adir, MOD_QUIZ, 'quiz', SEC_GENERAL, 0)
        add_activity_aux(adir, grades_body=f'''\
<?xml version="1.0" encoding="UTF-8"?>
<activity_gradebook>
  <grade_items>
    <grade_item id="2">
      <categoryid>1</categoryid>
      <itemname>Examen Final</itemname>
      <itemtype>mod</itemtype>
      <itemmodule>quiz</itemmodule>
      <iteminstance>{MOD_QUIZ}</iteminstance>
      <itemnumber>0</itemnumber>
      <iteminfo>$@NULL@$</iteminfo>
      <idnumber>$@NULL@$</idnumber>
      <calculation>$@NULL@$</calculation>
      <gradetype>1</gradetype>
      <grademax>{float(nq):.5f}</grademax>
      <grademin>0.00000</grademin>
      <scaleid>$@NULL@$</scaleid>
      <outcomeid>$@NULL@$</outcomeid>
      <gradepass>0.00000</gradepass>
      <multfactor>1.00000</multfactor>
      <plusfactor>0.00000</plusfactor>
      <aggregationcoef>0.00000</aggregationcoef>
      <aggregationcoef2>0.00000</aggregationcoef2>
      <weightoverride>0</weightoverride>
      <sortorder>2</sortorder>
      <display>0</display>
      <decimals>$@NULL@$</decimals>
      <hidden>0</hidden>
      <locked>0</locked>
      <locktime>0</locktime>
      <needsupdate>0</needsupdate>
      <timecreated>{now}</timecreated>
      <timemodified>{now}</timemodified>
      <grade_grades></grade_grades>
    </grade_item>
  </grade_items>
  <grade_letters></grade_letters>
</activity_gradebook>''')

        # ── QBANK ──────────────────────────────────────────────────────────────
        adir = f'qbank_{MOD_QBANK}'
        add(f'activities/{adir}/qbank.xml', f'''\
<?xml version="1.0" encoding="UTF-8"?>
<activity id="{MOD_QBANK}" moduleid="{MOD_QBANK}" modulename="qbank" contextid="{ctx(MOD_QBANK)}">
  <qbank id="{MOD_QBANK}">
    <name>{xe(shortname)} question bank</name>
    <intro></intro>
    <introformat>1</introformat>
    <timecreated>{now}</timecreated>
    <timemodified>{now}</timemodified>
  </qbank>
</activity>''')
        add_module_xml(adir, MOD_QBANK, 'qbank', SEC_GENERAL, 0)
        add_activity_aux(adir)

        # ── Module pages + forums ──────────────────────────────────────────────
        for i, mod in enumerate(modules):
            mc   = module_contents[i]
            pair = MOD_PAIRS[i]
            sid  = SEC_MODS[i]
            sec_num = i + 1

            # Page — Material y Contenido
            adir = f'page_{pair["page"]}'
            intro_html   = glossary_to_html(mc.get('glossary', []), fullname, professor)
            content_html = sections_to_html(mc.get('sections', []))
            add(f'activities/{adir}/page.xml', f'''\
<?xml version="1.0" encoding="UTF-8"?>
<activity id="{pair["page"]}" moduleid="{pair["page"]}" modulename="page" contextid="{ctx(pair["page"])}">
  <page id="{pair["page"]}">
    <name>Material y Contenido</name>
    <intro>{to_xml(intro_html)}</intro>
    <introformat>1</introformat>
    <content>{to_xml(content_html)}</content>
    <contentformat>1</contentformat>
    <legacyfiles>0</legacyfiles>
    <legacyfileslast>$@NULL@$</legacyfileslast>
    <display>5</display>
    <displayoptions>a:2:{{s:10:"printintro";s:1:"0";s:17:"printlastmodified";s:1:"1";}}</displayoptions>
    <revision>1</revision>
    <timemodified>{now}</timemodified>
  </page>
</activity>''')
            add_module_xml(adir, pair['page'], 'page', sid, sec_num)
            add_activity_aux(adir)

            # Forum — Discussion
            disc_q  = mc.get('discussion_question', f'Reflexione sobre {mod["title"]}')
            f_name  = f'Discusion #{sec_num} - {mod["title"]}'
            f_intro = to_xml(
                f'<p dir="ltr" style="text-align: left;">{xe(disc_q)}'
                '&nbsp;(Recuerde un m&iacute;nimo de 500 palabras y responder '
                'a un compa&ntilde;ero, con un m&iacute;nimo de 400 palabras)</p>'
            )
            adir = f'forum_{pair["forum"]}'
            add(f'activities/{adir}/forum.xml', f'''\
<?xml version="1.0" encoding="UTF-8"?>
<activity id="{pair["forum"]}" moduleid="{pair["forum"]}" modulename="forum" contextid="{ctx(pair["forum"])}">
  <forum id="{pair["forum"]}">
    <type>general</type>
    <name>{xe(f_name)}</name>
    <intro>{f_intro}</intro>
    <introformat>1</introformat>
    <duedate>0</duedate>
    <cutoffdate>0</cutoffdate>
    <assessed>0</assessed>
    <assesstimestart>0</assesstimestart>
    <assesstimefinish>0</assesstimefinish>
    <scale>100</scale>
    <maxbytes>512000</maxbytes>
    <maxattachments>9</maxattachments>
    <forcesubscribe>0</forcesubscribe>
    <trackingtype>1</trackingtype>
    <rsstype>0</rsstype>
    <rssarticles>0</rssarticles>
    <timemodified>{now}</timemodified>
    <warnafter>0</warnafter>
    <blockafter>0</blockafter>
    <blockperiod>0</blockperiod>
    <completiondiscussions>0</completiondiscussions>
    <completionreplies>0</completionreplies>
    <completionposts>0</completionposts>
    <displaywordcount>1</displaywordcount>
    <lockdiscussionafter>0</lockdiscussionafter>
    <grade_forum>0</grade_forum>
    <discussions></discussions>
  </forum>
</activity>''')
            add_module_xml(adir, pair['forum'], 'forum', sid, sec_num)
            add_activity_aux(adir)

        # ── Homework activities (assign or forum) ──────────────────────────────
        hw_grade_items = []   # (grade_item_id, module_type, title, mid)
        hw_gi_counter  = 3    # gradebook grade_item id; 1=course total, 2=quiz

        for mod_num, hw_mid in sorted(hw_mids.items()):
            hw_type  = homework_spec[mod_num]
            hw_info  = homework_prompts.get(mod_num, {})
            hw_title = hw_info.get('title',
                       f'{"Asignacion" if hw_type == "assign" else "Foro Tarea"} #{mod_num}')
            hw_desc  = hw_info.get('description', '')
            sid      = SEC_MODS[mod_num - 1]
            sec_num  = mod_num

            if hw_type == 'assign':
                adir = f'assign_{hw_mid}'
                assign_intro = to_xml(hw_desc) if hw_desc else xe(hw_title)
                assign_grades_body = f'''\
<?xml version="1.0" encoding="UTF-8"?>
<activity_gradebook>
  <grade_items>
    <grade_item id="{hw_gi_counter}">
      <categoryid>1</categoryid>
      <itemname>{xe(hw_title)}</itemname>
      <itemtype>mod</itemtype>
      <itemmodule>assign</itemmodule>
      <iteminstance>{hw_mid}</iteminstance>
      <itemnumber>0</itemnumber>
      <iteminfo>$@NULL@$</iteminfo>
      <idnumber>$@NULL@$</idnumber>
      <calculation>$@NULL@$</calculation>
      <gradetype>1</gradetype>
      <grademax>100.00000</grademax>
      <grademin>0.00000</grademin>
      <scaleid>$@NULL@$</scaleid>
      <outcomeid>$@NULL@$</outcomeid>
      <gradepass>0.00000</gradepass>
      <multfactor>1.00000</multfactor>
      <plusfactor>0.00000</plusfactor>
      <aggregationcoef>0.00000</aggregationcoef>
      <aggregationcoef2>0.00000</aggregationcoef2>
      <weightoverride>0</weightoverride>
      <sortorder>{hw_gi_counter}</sortorder>
      <display>0</display>
      <decimals>$@NULL@$</decimals>
      <hidden>0</hidden>
      <locked>0</locked>
      <locktime>0</locktime>
      <needsupdate>0</needsupdate>
      <timecreated>{now}</timecreated>
      <timemodified>{now}</timemodified>
      <grade_grades></grade_grades>
    </grade_item>
  </grade_items>
  <grade_letters></grade_letters>
</activity_gradebook>'''
                hw_grade_items.append((hw_gi_counter, 'assign', hw_title, hw_mid))
                hw_gi_counter += 1

                add(f'activities/{adir}/assign.xml', f'''\
<?xml version="1.0" encoding="UTF-8"?>
<activity id="{hw_mid}" moduleid="{hw_mid}" modulename="assign" contextid="{ctx(hw_mid)}">
  <assign id="{hw_mid}">
    <name>{xe(hw_title)}</name>
    <intro>{assign_intro}</intro>
    <introformat>1</introformat>
    <alwaysshowdescription>1</alwaysshowdescription>
    <nosubmissions>0</nosubmissions>
    <submissiondrafts>0</submissiondrafts>
    <sendnotifications>0</sendnotifications>
    <sendlatenotifications>0</sendlatenotifications>
    <sendstudentnotifications>1</sendstudentnotifications>
    <duedate>0</duedate>
    <allowsubmissionsfromdate>0</allowsubmissionsfromdate>
    <grade>100</grade>
    <timemodified>{now}</timemodified>
    <completionsubmit>0</completionsubmit>
    <cutoffdate>0</cutoffdate>
    <gradingduedate>0</gradingduedate>
    <teamsubmission>0</teamsubmission>
    <requireallteammemberssubmit>0</requireallteammemberssubmit>
    <teamsubmissiongroupingid>0</teamsubmissiongroupingid>
    <blindmarking>0</blindmarking>
    <hidegrader>0</hidegrader>
    <revealidentities>0</revealidentities>
    <attemptreopenmethod>none</attemptreopenmethod>
    <maxattempts>-1</maxattempts>
    <markingworkflow>0</markingworkflow>
    <markingallocation>0</markingallocation>
    <requiresubmissionstatement>0</requiresubmissionstatement>
    <preventsubmissionnotingroup>0</preventsubmissionnotingroup>
    <activityformat>0</activityformat>
    <timelimit>0</timelimit>
    <submissionattachments>0</submissionattachments>
    <maxfilessubmission>5</maxfilessubmission>
    <intro_attachments></intro_attachments>
    <plugin_configs>
      <plugin_config>
        <plugin>file</plugin><subtype>assignsubmission</subtype>
        <name>enabled</name><value>1</value>
      </plugin_config>
      <plugin_config>
        <plugin>file</plugin><subtype>assignsubmission</subtype>
        <name>maxfilesubmissions</name><value>5</value>
      </plugin_config>
      <plugin_config>
        <plugin>file</plugin><subtype>assignsubmission</subtype>
        <name>maxsubmissionsizebytes</name><value>0</value>
      </plugin_config>
      <plugin_config>
        <plugin>file</plugin><subtype>assignsubmission</subtype>
        <name>filetypeslist</name><value></value>
      </plugin_config>
      <plugin_config>
        <plugin>onlinetext</plugin><subtype>assignsubmission</subtype>
        <name>enabled</name><value>0</value>
      </plugin_config>
      <plugin_config>
        <plugin>comments</plugin><subtype>assignsubmission</subtype>
        <name>enabled</name><value>1</value>
      </plugin_config>
      <plugin_config>
        <plugin>comments</plugin><subtype>assignfeedback</subtype>
        <name>enabled</name><value>1</value>
      </plugin_config>
      <plugin_config>
        <plugin>file</plugin><subtype>assignfeedback</subtype>
        <name>enabled</name><value>0</value>
      </plugin_config>
    </plugin_configs>
    <submissions></submissions>
    <grades></grades>
    <overrides></overrides>
    <user_flags></user_flags>
    <user_overrides></user_overrides>
  </assign>
</activity>''')
                add_module_xml(adir, hw_mid, 'assign', sid, sec_num)
                add_activity_aux(adir, grades_body=assign_grades_body)

            else:  # hw_type == 'forum' — graded discussion board
                adir    = f'forum_{hw_mid}'
                f_intro = to_xml(
                    hw_desc if hw_desc else
                    f'<p>{xe(hw_title)}</p>'
                )
                forum_grades_body = f'''\
<?xml version="1.0" encoding="UTF-8"?>
<activity_gradebook>
  <grade_items>
    <grade_item id="{hw_gi_counter}">
      <categoryid>1</categoryid>
      <itemname>{xe(hw_title)}</itemname>
      <itemtype>mod</itemtype>
      <itemmodule>forum</itemmodule>
      <iteminstance>{hw_mid}</iteminstance>
      <itemnumber>0</itemnumber>
      <iteminfo>$@NULL@$</iteminfo>
      <idnumber>$@NULL@$</idnumber>
      <calculation>$@NULL@$</calculation>
      <gradetype>1</gradetype>
      <grademax>100.00000</grademax>
      <grademin>0.00000</grademin>
      <scaleid>$@NULL@$</scaleid>
      <outcomeid>$@NULL@$</outcomeid>
      <gradepass>0.00000</gradepass>
      <multfactor>1.00000</multfactor>
      <plusfactor>0.00000</plusfactor>
      <aggregationcoef>0.00000</aggregationcoef>
      <aggregationcoef2>0.00000</aggregationcoef2>
      <weightoverride>0</weightoverride>
      <sortorder>{hw_gi_counter}</sortorder>
      <display>0</display>
      <decimals>$@NULL@$</decimals>
      <hidden>0</hidden>
      <locked>0</locked>
      <locktime>0</locktime>
      <needsupdate>0</needsupdate>
      <timecreated>{now}</timecreated>
      <timemodified>{now}</timemodified>
      <grade_grades></grade_grades>
    </grade_item>
  </grade_items>
  <grade_letters></grade_letters>
</activity_gradebook>'''
                hw_grade_items.append((hw_gi_counter, 'forum', hw_title, hw_mid))
                hw_gi_counter += 1

                add(f'activities/{adir}/forum.xml', f'''\
<?xml version="1.0" encoding="UTF-8"?>
<activity id="{hw_mid}" moduleid="{hw_mid}" modulename="forum" contextid="{ctx(hw_mid)}">
  <forum id="{hw_mid}">
    <type>general</type>
    <name>{xe(hw_title)}</name>
    <intro>{f_intro}</intro>
    <introformat>1</introformat>
    <duedate>0</duedate>
    <cutoffdate>0</cutoffdate>
    <assessed>0</assessed>
    <assesstimestart>0</assesstimestart>
    <assesstimefinish>0</assesstimefinish>
    <scale>100</scale>
    <maxbytes>512000</maxbytes>
    <maxattachments>9</maxattachments>
    <forcesubscribe>0</forcesubscribe>
    <trackingtype>1</trackingtype>
    <rsstype>0</rsstype>
    <rssarticles>0</rssarticles>
    <timemodified>{now}</timemodified>
    <warnafter>0</warnafter>
    <blockafter>0</blockafter>
    <blockperiod>0</blockperiod>
    <completiondiscussions>0</completiondiscussions>
    <completionreplies>0</completionreplies>
    <completionposts>0</completionposts>
    <displaywordcount>1</displaywordcount>
    <lockdiscussionafter>0</lockdiscussionafter>
    <grade_forum>100</grade_forum>
    <discussions></discussions>
  </forum>
</activity>''')
                add_module_xml(adir, hw_mid, 'forum', sid, sec_num)
                add_activity_aux(adir, grades_body=forum_grades_body)

        # ── questions.xml ──────────────────────────────────────────────────────
        stamp_base = f"moodle-course-creator+{datetime.now().strftime('%y%m%d%H%M%S')}"
        qbe_lines  = []
        for q_idx, q in enumerate(quiz_questions):
            qbe_id  = q_idx + 1
            q_id    = q_idx + 1
            q_text  = xe(q.get('question', f'Pregunta {q_id}'))
            correct = int(q.get('correct_index', 0))
            options = q.get('options', ['a', 'b', 'c', 'd'])

            ans_lines = []
            for opt_i, opt in enumerate(options):
                a_id     = q_idx * 4 + opt_i + 1
                fraction = '1.0000000' if opt_i == correct else '0.0000000'
                opt_text = xe(opt)
                ans_lines.append(f'''\
                    <answer id="{a_id}">
                      <answertext>&lt;p dir="ltr" style="text-align: left;"&gt;&lt;span lang="ES"&gt;{opt_text}&lt;/span&gt;&lt;/p&gt;</answertext>
                      <answerformat>1</answerformat>
                      <fraction>{fraction}</fraction>
                      <feedback></feedback>
                      <feedbackformat>1</feedbackformat>
                    </answer>''')

            qbe_lines.append(f'''\
      <question_bank_entry id="{qbe_id}">
        <questioncategoryid>1</questioncategoryid>
        <idnumber>$@NULL@$</idnumber>
        <ownerid>2</ownerid>
        <nextversion>$@NULL@$</nextversion>
        <question_version>
          <question_versions id="{q_id}">
            <version>1</version>
            <status>ready</status>
            <questions>
              <question id="{q_id}">
                <parent>0</parent>
                <name>{xe(shortname)}-Q{q_id}</name>
                <questiontext>&lt;p dir="ltr" style="text-align: left;"&gt;&lt;span lang="ES"&gt;{q_text}&lt;/span&gt;&lt;br&gt;&lt;/p&gt;</questiontext>
                <questiontextformat>1</questiontextformat>
                <generalfeedback></generalfeedback>
                <generalfeedbackformat>1</generalfeedbackformat>
                <defaultmark>1.0000000</defaultmark>
                <penalty>0.3333333</penalty>
                <qtype>multichoice</qtype>
                <length>1</length>
                <stamp>{stamp_base}+{rand_hex(8)}</stamp>
                <timecreated>{now}</timecreated>
                <timemodified>{now}</timemodified>
                <createdby>2</createdby>
                <modifiedby>2</modifiedby>
                <plugin_qtype_multichoice_question>
                  <answers>
{chr(10).join(ans_lines)}
                  </answers>
                  <multichoice id="{q_id}">
                    <layout>0</layout>
                    <single>1</single>
                    <shuffleanswers>1</shuffleanswers>
                    <correctfeedback>Su respuesta es correcta.</correctfeedback>
                    <correctfeedbackformat>1</correctfeedbackformat>
                    <partiallycorrectfeedback>Su respuesta es parcialmente correcta.</partiallycorrectfeedback>
                    <partiallycorrectfeedbackformat>1</partiallycorrectfeedbackformat>
                    <incorrectfeedback>Su respuesta es incorrecta.</incorrectfeedback>
                    <incorrectfeedbackformat>1</incorrectfeedbackformat>
                    <answernumbering>abc</answernumbering>
                    <shownumcorrect>0</shownumcorrect>
                    <showstandardinstruction>0</showstandardinstruction>
                  </multichoice>
                </plugin_qtype_multichoice_question>
                <plugin_qbank_comment_question><comments></comments></plugin_qbank_comment_question>
                <plugin_qbank_customfields_question><customfields></customfields></plugin_qbank_customfields_question>
                <question_hints></question_hints>
                <tags></tags>
              </question>
            </questions>
          </question_versions>
        </question_version>
      </question_bank_entry>''')

        add('questions.xml', f'''\
<?xml version="1.0" encoding="UTF-8"?>
<question_categories>
  <question_category id="1">
    <name>Default for {xe(shortname)}</name>
    <contextid>{ctx(MOD_QBANK)}</contextid>
    <contextlevel>70</contextlevel>
    <contextinstanceid>{MOD_QBANK}</contextinstanceid>
    <info>Default category for {xe(shortname)}</info>
    <infoformat>0</infoformat>
    <stamp>{stamp_base}+default</stamp>
    <parent>2</parent>
    <sortorder>999</sortorder>
    <idnumber>$@NULL@$</idnumber>
    <question_bank_entries>
{chr(10).join(qbe_lines)}
    </question_bank_entries>
  </question_category>
  <question_category id="2">
    <name>top</name>
    <contextid>{ctx(MOD_QBANK)}</contextid>
    <contextlevel>70</contextlevel>
    <contextinstanceid>{MOD_QBANK}</contextinstanceid>
    <info></info>
    <infoformat>0</infoformat>
    <stamp>{stamp_base}+top</stamp>
    <parent>0</parent>
    <sortorder>0</sortorder>
    <idnumber>$@NULL@$</idnumber>
    <question_bank_entries></question_bank_entries>
  </question_category>
</question_categories>''')

        # ── gradebook.xml ──────────────────────────────────────────────────────
        # Only course/category/manual grade items go here; mod items are created
        # automatically when each activity module is restored.
        add('gradebook.xml', f'''\
<?xml version="1.0" encoding="UTF-8"?>
<gradebook>
  <attributes></attributes>
  <grade_categories>
    <grade_category id="1">
      <parent>$@NULL@$</parent>
      <depth>1</depth>
      <path>/1/</path>
      <fullname>?</fullname>
      <aggregation>13</aggregation>
      <keephigh>0</keephigh>
      <droplow>0</droplow>
      <aggregateonlygraded>1</aggregateonlygraded>
      <aggregateoutcomes>0</aggregateoutcomes>
      <timecreated>{now}</timecreated>
      <timemodified>{now}</timemodified>
      <hidden>0</hidden>
    </grade_category>
  </grade_categories>
  <grade_items>
    <grade_item id="1">
      <categoryid>1</categoryid>
      <itemname>$@NULL@$</itemname>
      <itemtype>course</itemtype>
      <itemmodule>$@NULL@$</itemmodule>
      <iteminstance>0</iteminstance>
      <itemnumber>$@NULL@$</itemnumber>
      <iteminfo>$@NULL@$</iteminfo>
      <idnumber>$@NULL@$</idnumber>
      <calculation>$@NULL@$</calculation>
      <gradetype>1</gradetype>
      <grademax>100.00000</grademax>
      <grademin>0.00000</grademin>
      <scaleid>$@NULL@$</scaleid>
      <outcomeid>$@NULL@$</outcomeid>
      <gradepass>0.00000</gradepass>
      <multfactor>1.00000</multfactor>
      <plusfactor>0.00000</plusfactor>
      <aggregationcoef>0.00000</aggregationcoef>
      <aggregationcoef2>0.00000</aggregationcoef2>
      <weightoverride>0</weightoverride>
      <sortorder>1</sortorder>
      <display>0</display>
      <decimals>$@NULL@$</decimals>
      <hidden>0</hidden>
      <locked>0</locked>
      <locktime>0</locktime>
      <needsupdate>0</needsupdate>
      <timecreated>{now}</timecreated>
      <timemodified>{now}</timemodified>
      <grade_grades></grade_grades>
    </grade_item>
  </grade_items>
  <grade_letters></grade_letters>
  <grade_settings></grade_settings>
</gradebook>''')

        # ── Top-level auxiliary files ───────────────────────────────────────────
        for fname, body in [
            ('files.xml',        '<?xml version="1.0" encoding="UTF-8"?>\n<files>\n</files>'),
            ('scales.xml',       '<?xml version="1.0" encoding="UTF-8"?>\n<scales_definition>\n</scales_definition>'),
            ('outcomes.xml',     '<?xml version="1.0" encoding="UTF-8"?>\n<outcomes_definition>\n</outcomes_definition>'),
            ('roles.xml',        _ROLES),
            ('users.xml',        '<?xml version="1.0" encoding="UTF-8"?>\n<users>\n</users>'),
            ('groups.xml',       '<?xml version="1.0" encoding="UTF-8"?>\n<groups>\n  <groupings>\n  </groupings>\n</groups>'),
            ('badges.xml',       '<?xml version="1.0" encoding="UTF-8"?>\n<badges>\n</badges>'),
            ('completion.xml',   '<?xml version="1.0" encoding="UTF-8"?>\n<course_completion>\n</course_completion>'),
            ('grade_history.xml','<?xml version="1.0" encoding="UTF-8"?>\n<grade_history>\n  <grade_grades>\n  </grade_grades>\n</grade_history>'),
            ('moodle_backup.log',''),
        ]:
            add(fname, body)

    return buf.getvalue()


# ─── CLI entry point ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Moodle Course Administrator — generates a .mbz from an AI prompt',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--shortname',    required=True,
                        help='Course shortname, e.g. TH310-2026_1')
    parser.add_argument('--fullname',     required=True,
                        help='Course full name, e.g. "TH 310 - HERMENEUTICA"')
    parser.add_argument('--professor',    default=DEFAULT_PROF,
                        help=f'Professor name (default: {DEFAULT_PROF})')
    parser.add_argument('--category',     default='2025 - 2026 Spring Term',
                        help='Moodle category name')
    parser.add_argument('--prompt',       default='',
                        help='Course content description prompt (required unless --load-json)')
    parser.add_argument('--start-date',   default='',
                        help='Course start date YYYY-MM-DD (default: today)')
    parser.add_argument('--end-date',     default='',
                        help='Course end date YYYY-MM-DD (default: start + 8 weeks)')
    parser.add_argument('--questions',    type=int, default=50,
                        help='Number of quiz questions (default: 50)')
    parser.add_argument('--output',       default='',
                        help='Output .mbz filename (default: <shortname>.mbz)')
    parser.add_argument('--llm-url',      default=DEFAULT_LLM_URL,
                        help=f'LLM API base URL (default: {DEFAULT_LLM_URL})')
    parser.add_argument('--llm-model',    default='',
                        help='Skip evaluation and use this model ID directly')
    parser.add_argument('--save-json',    default='',
                        help='Save generated content to JSON for inspection/reuse')
    parser.add_argument('--load-json',    default='',
                        help='Load content from a previously saved JSON (skips LLM)')
    parser.add_argument('--homework',     default='',
                        help='Homework per module, e.g. "1:assign,3:forum,5:assign"')
    args = parser.parse_args()

    if not args.load_json and not args.prompt:
        parser.error("--prompt is required unless --load-json is provided")

    # Parse --homework "1:assign,3:forum"
    homework_spec: dict[int, str] = {}
    if args.homework:
        for part in args.homework.split(','):
            part = part.strip()
            if ':' not in part:
                continue
            num_str, hw_type = part.split(':', 1)
            hw_type = hw_type.strip().lower()
            if hw_type not in ('assign', 'forum'):
                parser.error(f"--homework type must be 'assign' or 'forum', got '{hw_type}'")
            homework_spec[int(num_str.strip())] = hw_type

    # Dates
    start_dt = (datetime.strptime(args.start_date, '%Y-%m-%d')
                if args.start_date else datetime.now().replace(hour=0, minute=0, second=0))
    end_dt   = (datetime.strptime(args.end_date, '%Y-%m-%d')
                if args.end_date   else start_dt + timedelta(weeks=8))
    start_ts = int(start_dt.timestamp())
    end_ts   = int(end_dt.timestamp())

    output_file = args.output or f"{args.shortname}.mbz"

    print(f"\n{'='*55}")
    print(f"  Moodle Course Creator — {COLLEGE_NAME}")
    print(f"{'='*55}")
    print(f"  Course   : {args.fullname} ({args.shortname})")
    print(f"  Professor: {args.professor}")
    print(f"  Dates    : {start_dt.date()} → {end_dt.date()}")
    print(f"  Output   : {output_file}")
    if homework_spec:
        hw_desc = ', '.join(f'M{n}:{t}' for n, t in sorted(homework_spec.items()))
        print(f"  Homework : {hw_desc}")
    print(f"{'='*55}")

    # ── Model selection ────────────────────────────────────────────────────────
    llm = args.llm_url
    if args.load_json:
        model_id = args.llm_model or "none"
    elif args.llm_model:
        model_id = args.llm_model
    else:
        cache     = _load_cache()
        cached_id = cache.get('last_model')
        cached_url= cache.get('last_llm_url')
        if cached_id and cached_url == llm:
            print(f"\n  Last run used: {cached_id}")
            ans = input("  Use the same model again? [Y/n] > ").strip().lower()
            model_id = cached_id if ans in ('', 'y', 'yes') else select_llm(llm)
        else:
            model_id = select_llm(llm)

    # ── Generate or load content ───────────────────────────────────────────────
    if args.load_json:
        print(f"\n[0/4] Loading content from {args.load_json}…")
        with open(args.load_json, encoding='utf-8') as f:
            content = json.load(f)
        # If homework_spec was already in the JSON and not overridden on CLI, use stored
        if not homework_spec and 'homework_spec' in content:
            homework_spec = {int(k): v for k, v in content['homework_spec'].items()}
        hw_count = len(content.get('homework_prompts', {}))
        print(f"      Loaded {len(content['module_contents'])} modules, "
              f"{len(content['quiz_questions'])} questions"
              + (f", {hw_count} homework items" if hw_count else "") + "\n")
    else:
        print("[1/4] Generating course structure…")
        course_structure = generate_course_structure(
            args.shortname, args.fullname, args.prompt, llm, model_id)
        modules = course_structure['modules']
        for m in modules:
            print(f"      • {m['title']}")
        print()

        print("[2/4] Generating module content…")
        module_contents = []
        for m in modules:
            mc = generate_module_content(
                m['number'], m['title'], m['objective'],
                m.get('key_topics', []), args.fullname, args.professor,
                llm, model_id)
            module_contents.append(mc)
        print()

        print("[3/4] Generating PRONTUARIO (syllabus)…")
        syllabus = generate_syllabus(
            args.fullname, args.shortname, args.professor, modules, llm, model_id)
        print()

        print(f"[4/4] Generating {args.questions} quiz questions…")
        quiz_questions = generate_quiz_questions(
            args.fullname, modules, args.questions, llm, model_id)
        print(f"      ✓ {len(quiz_questions)} questions generated\n")

        homework_prompts: dict = {}
        if homework_spec:
            print("[5/5] Generating homework prompts…")
            homework_prompts = generate_homework_prompts(
                args.fullname, modules, homework_spec, llm, model_id)
            print()

        content = {
            'course_structure':  course_structure,
            'module_contents':   module_contents,
            'syllabus':          syllabus,
            'quiz_questions':    quiz_questions,
            'homework_prompts':  homework_prompts,
        }

        if homework_spec:
            content['homework_spec'] = homework_spec

        if args.save_json:
            with open(args.save_json, 'w', encoding='utf-8') as f:
                json.dump(content, f, ensure_ascii=False, indent=2)
            print(f"Content saved → {args.save_json}")

    # ── Build .mbz ────────────────────────────────────────────────────────────
    print("Building .mbz archive…")
    config = {
        'shortname':     args.shortname,
        'fullname':      args.fullname,
        'professor':     args.professor,
        'category':      args.category,
        'start_ts':      start_ts,
        'end_ts':        end_ts,
        'homework_spec': homework_spec,
    }
    mbz_bytes = build_mbz(config, content)

    with open(output_file, 'wb') as f:
        f.write(mbz_bytes)

    if model_id and model_id != "none":
        _save_cache({'last_model': model_id, 'last_llm_url': llm})

    size_kb = len(mbz_bytes) / 1024
    print(f"\n{'='*55}")
    print(f"  ✓ Created: {output_file}  ({size_kb:.1f} KB)")
    print(f"{'='*55}")
    print(f"\nImport steps:")
    print(f"  1. Log in to your Moodle instance as admin")
    print(f"  2. Site administration → Restore")
    print(f"  3. Upload {output_file} and follow the wizard")
    print()


if __name__ == '__main__':
    main()
