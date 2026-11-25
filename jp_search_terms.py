"""English -> Japanese search terms by LOOKUP, not translation.

Runs in two ways with the same file:
  * in the browser (WebAssembly), e.g. on molab or GitHub Pages: no server needed
  * locally:  python -m pip install marimo requests
              python -m marimo run jp_search_terms.py

Sources (all open, no AI model):
  * JMdict Japanese-English dictionary (EDRDG, CC BY-SA 4.0): public/jmdict-en.json.gz,
    built with build_dictionary.py
  * Japanese Wikipedia titles + redirects (CC BY-SA), Wikidata labels and aliases (CC0)
  * NDL Subject Headings (Web NDL Authorities, reuse allowed with attribution)
  * CiNii Research record counts per form, with the user's own free CiNii app ID
  * rule-based Japanese spelling variants
"""

import marimo

__generated_with = "0.25.2"
app = marimo.App(width="full", app_title="EN → JA search terms")

with app.setup:
    import asyncio
    import gzip
    import itertools
    import json
    import os
    import re
    import sys
    import unicodedata
    import urllib.parse
    from functools import lru_cache
    from pathlib import Path

    import marimo as mo

    IN_BROWSER = sys.platform == "emscripten"  # running as WebAssembly (molab embed, GitHub Pages)
    DICTIONARY_FILE = "jmdict-en.json.gz"
    # Wikimedia asks server-side API clients to give contact details (set APP_CONTACT locally)
    USER_AGENT = {"User-Agent": "jp-search-term-helper/0.3 (marimo app; university library research use; "
                                + os.environ.get("APP_CONTACT", "contact not set") + ")"}
    EN_WIKI = "https://en.wikipedia.org/w/api.php"
    JA_WIKI = "https://ja.wikipedia.org/w/api.php"
    WIKIDATA = "https://www.wikidata.org/w/api.php"
    NDL_SPARQL = "https://id.ndl.go.jp/auth/ndla/sparql"
    CINII = "https://cir.nii.ac.jp/opensearch/all"

    RARE_MISC = {"archaism", "obsolete term", "obscure term", "rare term", "rare"}
    INFORMAL_MISC = {"slang", "colloquialism", "jocular, humorous term", "vulgar expression or word"}
    OFFENSIVE_MISC = {"sensitive", "derogatory"}
    FAMILIES = ("JMdict", "Wikipedia", "Wikidata", "NDLSH")  # independent sources (rules don't count)

    # New (shinjitai) -> old (kyujitai) kanji forms that still turn up in older indexed literature
    _NEW = "学医体薬図会国歯臓気経済発変応実戦栄険験声処権価児労帰写広数来楽万与区当対従単継総検圧囲衛円塩恵芸県献号歳雑辞縦焼条状乗浄真窃繊銭浅装属続台担胆団断昼鉄点伝灯闘徳独読脳廃売麦抜浜仏並弁宝豊訳予余揺様謡乱覧竜両猟礼励霊齢恋炉湾"
    _OLD = "學醫體藥圖會國齒臟氣經濟發變應實戰榮險驗聲處權價兒勞歸寫廣數來樂萬與區當對從單繼總檢壓圍衞圓鹽惠藝縣獻號歲雜辭縱燒條狀乘淨眞竊纖錢淺裝屬續臺擔膽團斷晝鐵點傳燈鬭德獨讀腦廢賣麥拔濱佛竝辯寶豐譯豫餘搖樣謠亂覽龍兩獵禮勵靈齡戀爐灣"
    assert len(_NEW) == len(_OLD)
    OLD_KANJI = dict(zip(_NEW, _OLD))

    KATAKANA_WORD = re.compile(r"[ァ-ヺー]+")  # katakana + ー, split at ・ and spaces
    FULL_WIDTH = str.maketrans({chr(c): chr(c + 0xFEE0) for c in range(0x21, 0x7F)})
    LONG_VOWEL_ENDINGS = "タダサザナバラリ"  # -ter, -der, -ser, -zer, -ner, -ver, -ler, -ry ...





@app.function
def http_get_json(url: str, params: dict) -> dict:
    """GET a JSON API. In the browser: a plain request (no custom headers, so CORS stays simple)."""
    full = url + "?" + urllib.parse.urlencode(params)
    if IN_BROWSER:
        from pyodide.http import open_url  # synchronous request from the browser

        text = open_url(full).read()
    else:
        import requests

        r = requests.get(full, headers=USER_AGENT, timeout=20)
        r.raise_for_status()
        text = r.text
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"unexpected answer from {url.split('/')[2]}: {text[:120]!r}") from e


@app.function
def to_hiragana(s: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


@app.function
def kana_to_romaji(kana: str) -> str:
    """Hepburn romanisation of kana (long vowels written double, e.g. nyuugan)."""
    base = dict(zip(
        "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわゐゑをん"
        "がぎぐげござじずぜぞだぢづでどばびぶべぼぱぴぷぺぽぁぃぅぇぉゃゅょゎゔ",
        "a i u e o ka ki ku ke ko sa shi su se so ta chi tsu te to na ni nu ne no ha hi fu he ho "
        "ma mi mu me mo ya yu yo ra ri ru re ro wa i e o n ga gi gu ge go za ji zu ze zo da ji zu de do "
        "ba bi bu be bo pa pi pu pe po a i u e o ya yu yo wa vu".split(),
    ))
    special = {"てぃ": "ti", "でぃ": "di", "とぅ": "tu", "どぅ": "du", "うぃ": "wi", "うぇ": "we", "うぉ": "wo",
               "いぇ": "ye", "くぁ": "kwa", "つぁ": "tsa", "てゅ": "tyu", "でゅ": "dyu", "ふゅ": "fyu"}
    s = to_hiragana(unicodedata.normalize("NFKC", kana))
    out, i, double = [], 0, False
    while i < len(s):
        c, nxt = s[i], s[i + 1] if i + 1 < len(s) else ""
        if c == "っ":
            double, i = True, i + 1
            continue
        if c == "ー":
            if out and out[-1][-1:] in "aeiou":
                out.append(out[-1][-1])
            i += 1
            continue
        if c + nxt in special:
            syl, i = special[c + nxt], i + 2
        elif c in base and nxt in "ゃゅょ" and nxt and base[c].endswith("i") and len(base[c]) > 1:
            stem = base[c][:-1]
            syl = (stem if stem in ("sh", "ch", "j") else stem + "y") + base[nxt][-1]
            i += 2
        elif c in base and nxt in "ぁぃぅぇぉ" and nxt and len(base[c]) > 1:
            syl, i = base[c].rstrip("aeiou") + base[nxt], i + 2  # ふぁ fa, ゔぃ vi, ちぇ che
        elif c in base:
            syl, i = base[c], i + 1
        else:
            syl, i = c, i + 1
        if double and syl[:1].isalpha():
            syl = ("t" + syl) if syl.startswith("ch") else syl[0] + syl
        double = False
        out.append(syl)
    return "".join(out)


@app.class_definition
class JMDict:
    """The JMdict data in memory, with lookups by English gloss and by Japanese form."""

    def __init__(self, raw: bytes):
        data = json.loads(gzip.decompress(raw).decode("utf-8"))
        self.version = data["version"]
        self.misc_names, self.field_names = data["misc"], data["field"]
        self.entries = data["entries"]  # [kanji [[text, flags]], kana [[text, flags]], senses, freq]
        self.gloss_index, self.form_index = {}, {}
        for i, (kanji, kana, senses, _) in enumerate(self.entries):
            for s_no, (glosses, _, _) in enumerate(senses):
                for g_no, g in enumerate(glosses):
                    low = g.lower()
                    self.gloss_index.setdefault(low, []).append((i, s_no, g_no, g[:1].isupper() and not g.isupper()))
                    m = re.match(r"^(.*?) \([^()]*\)$", low) or re.match(r"^\([^()]*\) (.*)$", low)
                    if m:  # 'virus (computer)' is reachable as 'virus', marked as a qualified meaning
                        self.gloss_index.setdefault(m.group(1), []).append((i, s_no, g_no, True))
            for text, _ in kanji + kana:
                self.form_index.setdefault(text, []).append(i)
        self._cache = {}

    def lookup(self, query: str) -> list:
        """Entries with an English gloss equal to the query (qualified glosses count as secondary)."""
        key = ("lookup", query)
        if key in self._cache:
            return self._cache[key]
        q = query.lower()
        best = {}
        for i, s_no, g_no, special in self.gloss_index.get(q, []):
            kanji, kana, senses, freq = self.entries[i]
            glosses, misc, field = senses[s_no]
            primary = s_no == 0 and g_no < 3 and not special  # special: qualified or proper-noun gloss
            if i in best and (best[i]["primary"] or not primary):
                continue
            best[i] = {
                "id": i, "primary": primary, "sense_no": s_no + 1, "gloss_pos": g_no,
                "matched_gloss": glosses[g_no], "glosses": glosses[:4],
                "misc": sorted(self.misc_names[m] for m in misc), "field": [self.field_names[f] for f in field],
                "kanji": [(t, bool(f & 1), f) for t, f in kanji], "kana": [(t, bool(f & 1), f) for t, f in kana],
                "freq": freq,
            }
        out = sorted(best.values(), key=lambda e: (not e["primary"], e["gloss_pos"], e["freq"]))[:10]
        self._cache[key] = out
        return out

    def search(self, term: str) -> list:
        seen, out = set(), []
        for v in english_variants(term):
            for e in self.lookup(v):
                if e["id"] not in seen:
                    seen.add(e["id"])
                    out.append(e)
        return sorted(out, key=lambda e: (not e["primary"], e["gloss_pos"], e["freq"]))

    def forms(self, entry: dict) -> list:
        """Written forms of one entry as (japanese, type, usage, note)."""
        meaning = "; ".join(dict.fromkeys([entry["matched_gloss"]] + entry["glosses"][:3]))
        note = meaning + (f" [{', '.join(entry['field'])}]" if entry["field"] else "")
        if not entry["primary"]:
            note += f" (sense {entry['sense_no']} of this word)"
        misc = set(entry["misc"])
        base_usage = ("may be considered offensive" if misc & OFFENSIVE_MISC else
                      "rare or older" if misc & RARE_MISC else "informal" if misc & INFORMAL_MISC else None)
        abbreviation = "abbreviation" in misc
        kana_alone = "word usually written using kana alone" in misc
        out = []
        for text, common, flags in entry["kanji"]:
            typ, usage = ("abbreviation" if abbreviation else "dictionary form"), base_usage or ("common" if common else "")
            if flags & 2:
                typ, usage = "old kanji form", "rare or older"
            elif flags & 4:
                typ = "okurigana variant"
            elif flags & 8:
                typ = "irregular kanji spelling"
            out.append((text, typ, usage, note))
        for text, common, flags in entry["kana"]:
            if not entry["kanji"] or flags & 2 or kana_alone:
                typ = "abbreviation" if abbreviation else ("katakana form" if is_katakana(text) else "kana form")
                usage = "rare or older" if flags & 4 else base_usage or ("common" if (common or kana_alone) else "")
            else:
                typ, usage = "kana reading", "reading only"
            out.append((text, typ, usage, note))
        return out

    def reverse(self, form: str) -> dict:
        """Dictionary reading and usage warning for a Japanese form JMdict knows."""
        infos = []
        for i in self.form_index.get(form, []):
            kanji, kana, senses, _ = self.entries[i]
            misc = {self.misc_names[m] for m in senses[0][1]}
            infos.append((misc, kana[0][0] if kana else ""))
        if not infos:
            return {}
        neutral = [x for x in infos if not x[0] & (OFFENSIVE_MISC | RARE_MISC)]
        flag = ""
        if not neutral:
            if all(x[0] & OFFENSIVE_MISC for x in infos):
                flag = "may be considered offensive"
            elif all(x[0] & RARE_MISC for x in infos):
                flag = "rare or older"
        return {"reading": (neutral or infos)[0][1], "flag": flag}

    def romaji(self, form: str):
        """(romaji, sure). Uses dictionary readings; compounds are split into dictionary words."""
        if re.fullmatch(r"[\x00-\x7F]+", unicodedata.normalize("NFKC", form)):
            return "", True
        if re.fullmatch(r"[぀-ヿー・ 　]+", form):  # kana: spell it exactly as written
            return kana_to_romaji(form.replace("・", " ")), True
        for variant in (form, unicodedata.normalize("NFKC", form), to_hiragana(form),
                        form.replace("障がい", "障害").replace("障碍", "障害")):
            reading = self.reverse(variant).get("reading")
            if reading:
                return kana_to_romaji(reading), True
        parts, i = [], 0  # greedy longest-match split: 聴力損失 -> 聴力 + 損失
        while i < len(form):
            for j in range(min(len(form), i + 8), i, -1):
                piece = form[i:j]
                reading = self.reverse(piece).get("reading")
                if reading and (j - i > 1 or not re.fullmatch(r"[一-鿿]", piece) or j == len(form)):
                    parts.append(kana_to_romaji(reading))
                    i = j
                    break
            else:
                if re.fullmatch(r"[぀-ヿー]", form[i]):
                    parts.append(kana_to_romaji(form[i]))
                    i += 1
                else:
                    return "", False  # unknown kanji: better nothing than a wrong guess
        return " ".join(parts), False

@app.function
def rule_variants(jp: str, english: str) -> dict:
    """Deterministic orthographic variants of one Japanese form -> {variant: rule}."""
    out = {}

    def add(v, rule):
        if v and v != jp and v not in out:
            out[v] = rule

    add(unicodedata.normalize("NFKC", jp), "standard-width characters (e.g. ＱＯＬ → QOL, ｶﾞﾝ → ガン)")

    # word separators in katakana compounds
    if "・" in jp:
        add(jp.replace("・", ""), "written without the middle dot ・ that separates foreign words")
    kata_space = r"(?<=[゠-ヿ])[ 　](?=[゠-ヿ])"
    if re.search(kata_space, jp):
        add(re.sub(kata_space, "", jp), "loanword parts written together, without a space")
        add(re.sub(kata_space, "・", jp), "loanword parts joined with the middle dot ・")

    # final long vowel ー (コンピューター / コンピュータ, JIS-style spelling)
    def strip_lv(m):
        w = m.group(0)
        return w[:-1] if len(w) >= 4 and w.endswith("ー") and w[-2] in LONG_VOWEL_ENDINGS else w

    add(KATAKANA_WORD.sub(strip_lv, jp), "written without the long-vowel mark ー at the end (common in technical writing)")
    if re.search(r"[a-z]{2}(er|or|ar|ry)s?\b", english.lower()):
        def add_lv(m):
            w = m.group(0)
            return w + "ー" if len(w) >= 3 and w[-1] in LONG_VOWEL_ENDINGS else w

        add(KATAKANA_WORD.sub(add_lv, jp), "written with the long-vowel mark ー at the end")

    # ヴ spellings -> バ-row
    if "ヴ" in jp:
        v = jp
        for a, b in [("ヴァ", "バ"), ("ヴィ", "ビ"), ("ヴェ", "ベ"), ("ヴォ", "ボ"), ("ヴュ", "ビュ"), ("ヴ", "ブ")]:
            v = v.replace(a, b)
        add(v, "ヴ (v sound) written with バ, ビ, ブ… (b sound), the more common spelling")

    # small vs full-size vowel after ウ (ウィルス / ウイルス)
    for small, big in [("ウィ", "ウイ"), ("ウェ", "ウエ"), ("ウォ", "ウオ")]:
        if small in jp:
            add(jp.replace(small, big), f"{small} written as {big} (alternative loanword spelling)")
        if big in jp and KATAKANA_WORD.search(jp):
            add(jp.replace(big, small), f"{big} written as {small} (alternative loanword spelling)")

    # old kanji forms
    add("".join(OLD_KANJI.get(c, c) for c in jp), "pre-war kanji forms (旧字体), found in older literature")

    # disability terms: 障害 is also written 障がい (preferred by many authorities) and 障碍
    if "障害" in jp:
        add(jp.replace("障害", "障がい"), "障がい spelling, used by many authorities and organisations instead of 障害")
        add(jp.replace("障害", "障碍"), "障碍 spelling, an alternative kanji for 障害")

    # full-width Latin letters / digits used by some older databases (acronyms and mixed forms only)
    ascii_only = re.fullmatch(r"[\x00-\x7F]+", jp)
    if re.search(r"[A-Za-z0-9]", jp) and (not ascii_only or re.fullmatch(r"[A-Z0-9][A-Z0-9.&\-]{0,9}", jp)):
        add(jp.translate(FULL_WIDTH), "full-width letters, as used in some Japanese texts and older databases")

    return out


@app.function
def build_query(terms: list, style: str) -> str:
    if style == "OR, quoted":
        return " OR ".join(f'"{t}"' for t in terms)
    if style == "OR, unquoted":
        return " OR ".join(terms)
    return "\n".join(terms)



@app.function
def english_variants(term: str) -> list:
    """The term as typed plus US spellings, singular and hyphen forms, for exact-match lookups."""
    t = " ".join(term.strip().split())
    out = []

    def add(x):
        x = x.strip()
        if x and x not in out:
            out.append(x)

    add(t)
    low = t.lower()
    add(low)
    us = low
    for pat, rep in [
        (r"(\w)isation\b", r"\1ization"), (r"(\w)ising\b", r"\1izing"), (r"(\w)yse\b", r"\1yze"),
        (r"\b(\w{2,})our\b", r"\1or"), (r"(\w{2,})tre\b", r"\1ter"), (r"(\w{2,})bre\b", r"\1ber"),
        (r"aem", "em"), (r"oesoph", "esoph"), (r"oestr", "estr"), (r"rrhoea", "rrhea"), (r"foet", "fet"),
        (r"paed", "ped"), (r"aetiol", "etiol"), (r"programme", "program"), (r"ageing", "aging"),
        (r"(\w)lling\b", r"\1ling"), (r"(\w)lled\b", r"\1led"),
    ]:
        us = re.sub(pat, rep, us)
    add(us)
    for base in list(out):
        if "-" in base:
            add(base.replace("-", " "))
        words = base.split()
        last = words[-1]
        if len(last) > 4 and last.endswith("ies"):
            add(" ".join(words[:-1] + [last[:-3] + "y"]))
        elif len(last) > 3 and last.endswith("s") and not last.endswith(("ss", "us", "is", "sis")):
            add(" ".join(words[:-1] + [last[:-1]]))
    return out


@app.function
def clean_wiki_title(title: str):
    """Strip '(disambiguator)'; drop English-only titles except acronyms like AI or COVID-19."""
    base = re.sub(r"\s*[(（][^()（）]*[)）]$", "", title).strip()
    if len(base) > 40:
        return None
    if re.fullmatch(r"[\x00-\x7F]+", base) and not re.fullmatch(r"[A-Z0-9][A-Z0-9.&\-]{0,9}", base):
        return None
    return base


@app.function
def norm_key(form: str) -> str:
    """How CiNii appears to compare forms: width, hiragana/katakana, ー, ・, spaces and case ignored."""
    t = unicodedata.normalize("NFKC", form).lower()
    t = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in t)
    return re.sub(r"[ー・\s\-]", "", t)



@app.function
def is_katakana(s: str) -> bool:
    return bool(re.fullmatch(r"[゠-ヿ・ー]+", s))


@app.function
def wiki_api(url: str, **params) -> dict:
    return http_get_json(url, {**params, "format": "json", "formatversion": 2, "origin": "*"})


@app.function
@lru_cache(maxsize=512)
def wikipedia_lookup(term: str) -> dict:
    """English article -> Japanese article title, its redirects, and the Wikidata item."""
    props = dict(action="query", redirects=1, prop="langlinks|pageprops", lllang="ja",
                 ppprop="wikibase_item|disambiguation")
    page, exact = None, True
    for t in english_variants(term):
        pages = wiki_api(EN_WIKI, titles=t, **props).get("query", {}).get("pages", [])
        if pages and not pages[0].get("missing") and not pages[0].get("invalid"):
            page = pages[0]
            break
    if page is None:
        hits = wiki_api(EN_WIKI, action="query", list="search", srsearch=term, srlimit=1)
        hits = hits.get("query", {}).get("search", [])
        if not hits:
            return {}
        exact = False
        page = wiki_api(EN_WIKI, titles=hits[0]["title"], **props)["query"]["pages"][0]
    pp = page.get("pageprops", {})
    info = {"en_title": page.get("title", ""), "exact": exact, "disambiguation": "disambiguation" in pp,
            "qid": pp.get("wikibase_item"), "ja_title": None, "redirects": []}
    langlinks = page.get("langlinks", [])
    if not langlinks:
        return info
    ja_title = langlinks[0].get("title") or langlinks[0].get("*")
    ja = wiki_api(JA_WIKI, action="query", titles=ja_title, redirects=1, prop="redirects",
                  rdprop="title|fragment", rdnamespace=0, rdlimit="max")
    ja_page = ja.get("query", {}).get("pages", [{}])[0]
    info["ja_title"] = ja_page.get("title", ja_title)
    info["redirects"] = [(r["title"], r.get("fragment", "")) for r in ja_page.get("redirects", [])]
    return info


@app.function
@lru_cache(maxsize=512)
def wikidata_lookup(qid: str) -> dict:
    ent = http_get_json(WIKIDATA, {"action": "wbgetentities", "ids": qid, "props": "labels|aliases|descriptions",
                                   "languages": "ja|en", "format": "json", "origin": "*"})
    ent = ent.get("entities", {}).get(qid, {})
    return {
        "qid": qid,
        "ja_label": ent.get("labels", {}).get("ja", {}).get("value"),
        "ja_aliases": [a["value"] for a in ent.get("aliases", {}).get("ja", [])],
        "en_label": ent.get("labels", {}).get("en", {}).get("value", ""),
        "en_aliases": [a["value"] for a in ent.get("aliases", {}).get("en", [])],
        "en_desc": ent.get("descriptions", {}).get("en", {}).get("value", ""),
    }


@app.function
@lru_cache(maxsize=512)
def ja_wikipedia_pages(candidates: tuple) -> list:
    """Japanese Wikipedia articles reached directly from Japanese forms, with their redirects.

    Needed when the English article has no Japanese link (the two languages sometimes file the
    topic under different items, e.g. 'Hearing loss' vs 聴覚障害).
    """
    if not candidates:
        return []
    data = wiki_api(JA_WIKI, action="query", titles="|".join(candidates[:20]), redirects=1,
                    prop="redirects|pageprops", rdprop="title|fragment", rdnamespace=0, rdlimit="max",
                    ppprop="disambiguation")
    out = []
    for p in data.get("query", {}).get("pages", []):
        if p.get("missing") or p.get("invalid") or "disambiguation" in p.get("pageprops", {}):
            continue
        out.append({"title": p["title"], "redirects": [(r["title"], r.get("fragment", "")) for r in p.get("redirects", [])]})
    return out


@app.function
@lru_cache(maxsize=512)
def ndlsh_lookup(candidates: tuple) -> list:
    """NDL Subject Headings whose heading or variant equals one of the Japanese candidates."""
    if not candidates:
        return []
    values = " ".join(f"{json.dumps(c, ensure_ascii=False)} {json.dumps(c, ensure_ascii=False)}@ja" for c in candidates)
    prefixes = """PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX xl: <http://www.w3.org/2008/05/skos-xl#>
"""

    def sparql(q):
        return http_get_json(NDL_SPARQL, {"query": prefixes + q, "format": "json"})["results"]["bindings"]

    found = sparql(f"""SELECT DISTINCT ?s WHERE {{
  VALUES ?q {{ {values} }}
  {{ ?s rdfs:label ?q }} UNION {{ ?s skos:prefLabel ?q }} UNION {{ ?s skos:altLabel ?q }}
  UNION {{ ?s xl:prefLabel/xl:literalForm ?q }} UNION {{ ?s xl:altLabel/xl:literalForm ?q }}
  FILTER(STRSTARTS(STR(?s), "http://id.ndl.go.jp/auth/ndlsh/"))
}} LIMIT 10""")
    uris = sorted({b["s"]["value"] for b in found})
    if not uris:
        return []
    rows = sparql(f"""SELECT ?s ?p ?lit WHERE {{
  VALUES ?s {{ {' '.join(f'<{u}>' for u in uris)} }}
  {{ ?s ?p ?lit FILTER(isLiteral(?lit)) }} UNION {{ ?s ?p ?b . ?b xl:literalForm ?lit }}
}}""")
    headings = {}
    for b in rows:
        prop = re.split(r"[#/]", b["p"]["value"])[-1]
        lang = b["lit"].get("xml:lang", "")
        if prop not in {"label", "prefLabel", "altLabel"} or (lang and not lang.startswith("ja")) or "Kana" in lang:
            continue
        h = headings.setdefault(b["s"]["value"], {"uri": b["s"]["value"], "pref": None, "alt": []})
        text = b["lit"]["value"].strip()
        if not clean_wiki_title(text):  # English cross-references like 'Breast--Cancer'
            continue
        if prop == "altLabel":
            if text not in h["alt"]:
                h["alt"].append(text)
        elif h["pref"] is None:
            h["pref"] = text
    return list(headings.values())


@app.function
def count_key(form: str) -> str:
    """Forms CiNii is known to treat as one search (width, hiragana/katakana): count them once."""
    return to_hiragana(unicodedata.normalize("NFKC", form)).lower()


@app.function
@lru_cache(maxsize=8192)
def cinii_count(term: str, appid: str):
    """Number of CiNii Research records matching the form (all resource types)."""
    q = f'"{term}"' if " " in term else term
    data = http_get_json(CINII, {"q": q, "count": 1, "format": "json", "appid": appid})

    def find(d):
        if isinstance(d, dict):
            for k, v in d.items():
                if k.endswith("totalResults"):
                    return int(v)
                if (found := find(v)) is not None:
                    return found
        return None

    return find(data)


@app.function
def cinii_counts(terms: list, appid: str, progress=None) -> dict:
    """Counts for all forms; one request per distinct search."""
    unique = list(dict.fromkeys(count_key(t) for t in terms))
    first = {}
    for t in terms:
        first.setdefault(count_key(t), t)
    results = {}
    if IN_BROWSER:  # requests run one after another in the browser
        for n, k in enumerate(unique, 1):
            results[k] = cinii_count(first[k], appid)
            if progress:
                progress(n, len(unique))
    else:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = dict(zip(unique, pool.map(lambda k: cinii_count(first[k], appid), unique)))
    return {t: results[count_key(t)] for t in terms}


@app.function
def best_written_forms(jmd, phrase: str, k: int = 3) -> list:
    """Up to k written forms for an English word/phrase: the best form of each of the best entries."""
    forms = []
    for e in jmd.search(phrase):
        if not e["primary"]:
            continue
        usable = [jp for jp, typ, usage, _ in jmd.forms(e)
                  if typ not in ("kana reading", "old kanji form") and usage not in ("rare or older", "informal", "reading only", "may be considered offensive")]
        if usable:
            forms.append(usable[0])
        if len(forms) >= k:
            break
    return list(dict.fromkeys(forms))


@app.function
def compose_from_parts(jmd, term: str, use_web: bool = False, max_combos: int = 12) -> tuple:
    """For multi-word terms missing from the dictionary: translate the parts and join them.

    'tumour microenvironment' -> 腫瘍 + 微小環境; 'quality of life' -> 生活 + の + 質.
    """
    low = " ".join(term.lower().split())
    joiners = [""]
    if " of " in f" {low} ":
        head, mod = low.split(" of ", 1)
        low, joiners = f"{mod} {head}", ["の", ""]  # Japanese puts the modifier first
    words = [w for w in re.findall(r"[a-z0-9\-']+", low) if w not in {"the", "a", "an"}]
    if len(words) < 2:
        return ()
    parts, i = [], 0
    while i < len(words):
        for j in range(len(words), i, -1):
            phrase = " ".join(words[i:j])
            forms = best_written_forms(jmd, phrase)
            if forms:
                parts.append((phrase, forms))
                i = j
                break
        else:
            wiki = {}
            if use_web:  # e.g. 'microenvironment' is not in the dictionary but has a Wikipedia article
                try:
                    wiki = wikipedia_lookup(words[i])
                except Exception:
                    wiki = {}
            ja = clean_wiki_title(wiki.get("ja_title") or "") if wiki.get("exact") and not wiki.get("disambiguation") else None
            if not ja:
                return ()  # a word we cannot find; better nothing than a guess
            parts.append((words[i], [ja]))
            i += 1
    if len(parts) < 2:
        return ()
    out = []
    for joiner in joiners:
        for combo in itertools.product(*[f for _, f in parts]):
            jp = joiner.join(combo) if len(parts) == 2 else "".join(combo)
            note = " + ".join(f"{c} ({p})" for c, (p, _) in zip(combo, parts))
            out.append((jp, note))
            if len(out) >= max_combos:
                return tuple(out)
    return tuple(out)


@app.function
def english_synonyms(term: str, wiki: dict, wd: dict, limit: int = 6) -> list:
    """Other English names of the concept: the Wikipedia article title and Wikidata names."""
    own = {v.lower() for v in english_variants(term)}
    names = []
    if wiki.get("exact") and not wiki.get("disambiguation"):
        names.append(re.sub(r"\s*\([^)]*\)$", "", wiki.get("en_title", "")))
        names += ([wd.get("en_label", "")] + wd.get("en_aliases", [])) if wd else []
    out = []
    for n in names:
        n = " ".join((n or "").split())
        if n and n.lower() not in own and n.lower() not in {o.lower() for o in out} and len(n) <= 40:
            out.append(n)
    return out[:limit]


@app.function
def synonym_entries(jmd, synonyms: list) -> list:
    """(synonym, JMdict entry) pairs for the English synonyms, main senses only."""
    out = []
    for syn in synonyms:
        for e in jmd.search(syn)[:4]:
            if e["sense_no"] <= 2:
                out.append((syn, e))
    return out


@app.function
def family(source: str) -> str:
    return next((f for f in FAMILIES if source.startswith(f)), source)


@app.function
def assemble_rows(jmd, term, jm_entries, wiki, wd, ndl, composed, use_rules, syn_entries=(), ja_pages=(), extra=()) -> list:
    rows: dict = {}

    def put(jp, rank, typ, usage, source, note, variant_of=""):
        jp = (jp or "").strip()
        if not jp:
            return
        if jp in rows:
            r = rows[jp]
            r["_src"].add(source)
            r["_rank"] = min(r["_rank"], rank)
            if usage == "common" and r["Usage"] != "common":
                r["Usage"] = usage
            return
        rows[jp] = {"Japanese": jp, "Type": typ, "Usage": usage, "Note": note,
                    "_src": {source}, "_rank": rank, "_variant_of": variant_of}

    # 0. forms the user typed (e.g. from a Japanese colleague or a thesaurus)
    for jp in extra:
        put(jp, 0, "added by you", "", "you", "You added this form yourself")

    # 1. dictionary
    def acceptable(e):  # an older or offensive word (痴呆) must not hide the current one (認知症)
        return not set(e["misc"]) & (OFFENSIVE_MISC | RARE_MISC | INFORMAL_MISC)

    # technical terms often lack frequency tags: then all main forms count
    no_markers = not any(e["freq"] < 99 for e in jm_entries if e["primary"] and acceptable(e))
    for e in jm_entries:
        for jp, typ, usage, note in jmd.forms(e):
            if typ == "kana reading":
                rank = 8
            elif typ == "abbreviation":
                rank = 3
            else:
                rank = 0 if e["primary"] else 5
            put(jp, rank, typ, usage, "JMdict", f"Dictionary meaning: {note}")
            if rank == 0 and (usage == "common" or no_markers):
                rows[jp]["_core"] = True

    # 1b. dictionary forms of other English names of the concept ('hearing loss' for 'hearing impairment')
    for syn, e in syn_entries:
        for jp, typ, usage, note in jmd.forms(e):
            if typ == "kana reading":
                continue
            put(jp, 4, f"{typ} (via synonym)", usage, "JMdict", f"Found by also looking up '{syn}' in the dictionary. Meaning: {note}")

    # 2. Wikipedia + Wikidata
    def add_redirects(article, redirects):
        for title, fragment in redirects:
            base = clean_wiki_title(title)
            if not base or base == article:
                continue
            if fragment:
                put(base, 9, "related (redirects to a section)", "check", "Wikipedia redirect",
                    f"Wikipedia sends this title to the section '{fragment}' of the article {article}: usually a narrower topic")
            elif re.fullmatch(r"[A-Z0-9][A-Z0-9.&\-]{0,9}", base):
                put(base, 4, "abbreviation (check meaning)", "check", "Wikipedia redirect",
                    f"Wikipedia sends this abbreviation to the article {article}. Abbreviations can mean a subtype or something else entirely: check")
            else:
                put(base, 4, "Wikipedia redirect", "check", "Wikipedia redirect",
                    f"Wikipedia sends this title to the article {article}, so it is used as another name. Can also be a common typo or a narrower topic")

    if wiki and wiki.get("ja_title"):
        caveat = "" if wiki["exact"] and not wiki["disambiguation"] else " (closest match, check it is the right concept)"
        title = clean_wiki_title(wiki["ja_title"]) or wiki["ja_title"]
        put(title, 1, "Wikipedia article title", "common" if not caveat else "check", "Wikipedia",
            f"Japanese article for '{wiki['en_title']}'{caveat}")
        add_redirects(title, wiki.get("redirects", []))
    for page in ja_pages:
        title = clean_wiki_title(page["title"]) or page["title"]
        put(title, 1, "Wikipedia article title", "common", "Wikipedia", "Japanese Wikipedia article with this name")
        add_redirects(title, page["redirects"])
    if wd:
        if wd.get("ja_label") and clean_wiki_title(wd["ja_label"]):
            put(wd["ja_label"], 1, "Wikidata label", "common", "Wikidata", f"Main Japanese name on Wikidata for: {wd['en_desc']} ({wd['qid']})")
        for a in wd.get("ja_aliases", []):
            if clean_wiki_title(a):
                put(a, 4, "Wikidata alias", "check", "Wikidata", f"Other Japanese name on Wikidata for: {wd['en_desc']} ({wd['qid']})")

    # 3. NDL Subject Headings
    for h in ndl:
        if h["pref"]:
            put(h["pref"], 2, "NDL subject heading", "common", "NDLSH", f"Official subject heading of Japan's National Diet Library: library catalogues file books on this subject under this term ({h['uri']})")
        for a in h["alt"]:
            put(a, 4, "NDLSH variant", "check", "NDLSH", f"The national library lists this as another name for the subject '{h['pref'] or ''}' (a 'see from' reference: "
                f"someone looking up this term is sent to '{h['pref'] or ''}'). Useful in titles and abstracts")

    # 4. composed from parts
    for jp, note in composed:
        put(jp, 6, "composed from parts", "check", "composed", f"Built by translating the parts: {note}. A guess: keep it only if CiNii shows records")

    # 5. spelling rules on written forms
    if use_rules:
        for base, r in list(rows.items()):
            if r["Type"] in ("kana reading",) or r["_rank"] >= 9:
                continue
            for v, rule in rule_variants(base, term).items():
                if v not in rows:
                    put(v, 7, "spelling variant (rule)", "check", "spelling rule", f"Spelling rule: {rule} (made from {base})", variant_of=base)
                    if rule.startswith("standard-width characters"):  # ＡＩ -> AI: same form, same status
                        rows[v].update(_rank=r["_rank"], _core=r.get("_core", False), Usage=r["Usage"])
                else:
                    rows[v]["_src"].add("spelling rule")

    put(term, 10, "English form", "common", "input", "Your English term: many Japanese databases also index English titles and keywords")

    out = sorted(rows.values(), key=lambda r: r["_rank"])
    for r in out:
        fams = sorted({family(s) for s in r["_src"]} & set(FAMILIES))
        r["_n_sources"] = len(fams)
        r["Sources"] = " + ".join(sorted({family(s) for s in r["_src"]}))
        if r["Type"] == "English form":
            r["Romaji"] = ""
        else:
            romaji, sure = jmd.romaji(r["Japanese"])
            r["Romaji"] = romaji if sure or not romaji else f"{romaji} *"
            flag = jmd.reverse(r["Japanese"]).get("flag", "")
            if flag and r["Usage"] in ("", "common", "check"):
                r["Usage"] = flag
    return out


@app.function
def decide_ticks(rows: list, counts, min_hits: int, min_share: float) -> None:
    """Set _tick, Share and Flags on every row (in place)."""
    def count(r):
        return None if counts is None else counts.get(r["Japanese"])

    japanese = [r for r in rows if r["Type"] != "English form" and r["Usage"] != "reading only"]
    top = max((count(r) or 0 for r in japanese), default=0)
    threshold = max(min_hits, top * min_share / 100)

    for r in rows:
        n = count(r)
        r["CiNii records"] = "" if n is None else n
        share = None if n is None or not top or r["Type"] == "English form" else 100 * n / top
        r["Share"] = "" if share is None else ("<0.1%" if 0 < share < 0.1 else f"{share:.1f}%")
        flags = [r["Usage"]] if r["Usage"] and r["Usage"] not in ("common",) else []
        if len(r["Japanese"]) == 1:
            flags.append("single character: also matches many longer words")
        if r["Type"] in ("added by you", "English form"):
            tick = True
        elif r["Usage"] in ("reading only", "may be considered offensive") or r["_rank"] >= 9:
            tick = False
        elif n is not None:
            tick = n >= threshold
            if not tick and n > 0:
                flags.append("few records")
        elif r["Usage"] in ("rare or older", "informal"):
            tick = False
        elif r.get("_core"):
            tick = True
        elif r["_rank"] in (1, 2):
            tick = r["Usage"] != "check" or r["_n_sources"] >= 2
        else:
            tick = r["_n_sources"] >= 2
        r["_tick"], r["_flags"] = tick, flags

    # spellings CiNii treats as the same search (hiragana/katakana, width, ー, ・)
    groups = {}
    for r in rows:
        if r["Type"] != "English form":
            groups.setdefault(norm_key(r["Japanese"]), []).append(r)
    for members in groups.values():
        if len(members) < 2:
            continue
        lead = max(members, key=lambda r: (r["_tick"], -r["_rank"], count(r) or 0))
        for r in members:
            if r is not lead and (counts is None or count(r) == count(lead)):
                r["_same_as"] = lead["Japanese"]
                r["_flags"].append(f"same search as {lead['Japanese']} in CiNii" if counts is not None
                                   else f"spelling variant of {lead['Japanese']}")

    # longer forms that contain a ticked form are already found by it in substring searches
    ticked = [r for r in rows if r["_tick"] and r["Type"] != "English form" and len(r["Japanese"]) >= 2]
    for r in rows:
        if r["Type"] in ("English form", "added by you"):
            continue
        parent = next((t for t in ticked if t is not r and t["Japanese"] in r["Japanese"]
                       and norm_key(t["Japanese"]) != norm_key(r["Japanese"])), None)
        if parent:
            r["_tick"] = False
            r["_flags"].append(f"narrower; already found by {parent['Japanese']}")

    for r in rows:
        r["Flags"] = "; ".join(dict.fromkeys(f for f in r["_flags"] if f))
    if counts is not None:  # most-used first; English form last
        rows.sort(key=lambda r: (r["Type"] == "English form", not r["_tick"], -(count(r) or 0)))


@app.cell(hide_code=True)
def _():
    mo.md("""
    # English → Japanese search terms

    Type an English term to see the Japanese forms found in **dictionaries, Wikipedia, Wikidata and the
    Japanese national library's subject headings**, plus spelling variants.
    With a CiNii app ID, each form also shows how many records in CiNii Research use it.
    """)
    return


@app.cell(hide_code=True)
async def _():
    # The dictionary file sits in public/ next to the notebook, locally and on the web
    _location = mo.notebook_location() / "public" / DICTIONARY_FILE
    with mo.status.spinner(title="Preparing the dictionary (about 10 seconds, once per visit)…"):
        if IN_BROWSER:
            from pyodide.http import pyfetch

            _problem = None
            try:
                _resp = await asyncio.wait_for(pyfetch(str(_location)), timeout=60)
                if not _resp.ok:
                    _problem = f"the server answered {_resp.status} for {_location}"
                else:
                    _raw = await asyncio.wait_for(_resp.bytes(), timeout=120)
            except asyncio.TimeoutError:
                _problem = "the download did not start within a minute"
            mo.stop(_problem is not None, mo.callout(mo.md(
                f"**The dictionary could not be loaded** ({_problem}).\n\n"
                "- Check your internet connection and reload the page.\n"
                "- When testing on your own computer: a leftover helper from another marimo app on the same "
                "address can block it. Use another port (`python -m http.server 8001 --directory site`), or press "
                "F12 → *Application* → *Service workers* → *Unregister*, then reload."
            ), kind="danger"))
        else:
            _raw = Path(_location).read_bytes()
        jmd = JMDict(_raw)
    return (jmd,)


@app.cell(hide_code=True)
def _():
    # The ID from the environment is used on the server only and never sent to the browser
    cinii_appid = mo.ui.text(value="", kind="password", full_width=True,
                             label="CiNii app ID"
                             + (" · using the ID set on this machine" if os.environ.get("CINII_APPID") else ""))
    min_hits = mo.ui.number(start=0, stop=10000, value=5, label="Tick forms with at least this many CiNii records")
    min_share = mo.ui.number(start=0, stop=100, step=0.5, value=1,
                             label="… and at least this % of the records of the most-used Japanese form")
    use_web = mo.ui.checkbox(value=True, label="Wikipedia and Wikidata")
    use_ndl = mo.ui.checkbox(value=True, label="NDL Subject Headings")
    use_syn = mo.ui.checkbox(value=True, label="Also look up other English names of the concept")
    use_rules = mo.ui.checkbox(value=True, label="Rule-based spelling variants")
    use_compose = mo.ui.checkbox(value=True, label="Build multi-word terms from their parts")
    return cinii_appid, min_hits, min_share, use_compose, use_ndl, use_rules, use_syn, use_web


@app.cell(hide_code=True)
def _(cinii_appid, jmd, min_hits, min_share, use_compose, use_ndl, use_rules, use_syn, use_web):
    _dict_status = mo.callout(mo.md(f"Dictionary ready: {jmd.version} ({len(jmd.entries):,} entries)"), kind="success")
    _cinii_box = mo.callout(mo.vstack([
        mo.md("**Optional: your own CiNii app ID.** With it, each Japanese form shows how many records in "
              "CiNii Research use it, and the most-used forms are ticked for you. "
              "Get a free ID at <https://support.nii.ac.jp/en/cinii/api/developer>. "
              "It is only used for this session: it is not saved and other users cannot see it."),
        cinii_appid,
    ]), kind="info")
    _settings = mo.accordion({
        "Settings": mo.vstack([
            _dict_status,
            min_hits,
            min_share,
            mo.hstack([use_web, use_ndl, use_syn], justify="start"),
            mo.hstack([use_rules, use_compose], justify="start"),
        ])
    })
    mo.vstack([_cinii_box, _settings])
    return


@app.cell(hide_code=True)
def _():
    search_form = (
        mo.md("**English search term**  \n{term}\n\n"
              "**Japanese forms to add yourself** (optional, one per line, e.g. from a Japanese colleague or a thesaurus)  \n{extra}")
        .batch(
            term=mo.ui.text(placeholder="e.g. machine learning, tumour microenvironment, quality of life", full_width=True),
            extra=mo.ui.text_area(placeholder="乳腺癌\n乳房腫瘍", rows=2, full_width=True),
        )
        .form(submit_button_label="Look up", clear_on_submit=False)
    )
    search_form
    return (search_form,)


@app.cell(hide_code=True)
def _(cinii_appid, jmd, min_hits, min_share, search_form, use_compose, use_ndl, use_rules, use_syn, use_web):
    mo.stop(search_form.value is None, mo.md("_Enter a term and press **Look up**._"))
    term = " ".join(search_form.value["term"].split())
    mo.stop(not term, mo.callout("Please type a search term.", kind="warn"))
    _extra = tuple(dict.fromkeys(x.strip() for x in (search_form.value["extra"] or "").splitlines() if x.strip()))

    _errors, _jm, _wiki, _wd, _ndl, _composed, _syn_e, _ja_pages, counts = [], [], {}, {}, [], (), [], [], None
    _synonyms = []

    def _candidates(limit=20):
        return [r["Japanese"] for r in assemble_rows(jmd, term, _jm, _wiki, _wd, _ndl, (), False, _syn_e, _ja_pages, _extra)
                if r["_rank"] <= 4 and r["Type"] != "English form" and clean_wiki_title(r["Japanese"])][:limit]

    with mo.status.spinner(title="Looking up the dictionary…") as _spin:
        try:
            _jm = jmd.search(term)
        except Exception as e:
            _errors.append(f"Dictionary: {e}")
        if use_web.value:
            _spin.update("Looking up Wikipedia and Wikidata…")
            try:
                _wiki = wikipedia_lookup(term)
                if _wiki.get("qid"):
                    _wd = wikidata_lookup(_wiki["qid"])
            except Exception as e:
                _errors.append(f"Wikipedia/Wikidata: {e}")
        if use_syn.value and (_wiki or _wd):
            _synonyms = english_synonyms(term, _wiki, _wd)
            try:
                _syn_e = synonym_entries(jmd, _synonyms)
            except Exception as e:
                _errors.append(f"Dictionary (synonyms): {e}")
        if use_compose.value and not any(e["primary"] for e in _jm):
            _spin.update("Building the term from its parts…")
            try:
                _composed = compose_from_parts(jmd, term, use_web.value)
            except Exception as e:
                _errors.append(f"Composition: {e}")
        if use_ndl.value:
            _spin.update("Looking up NDL Subject Headings…")
            try:
                _ndl = ndlsh_lookup(tuple(_candidates()))
            except Exception as e:
                _errors.append(f"NDL Subject Headings could not be reached ({e}); the other sources still work.")
        if use_web.value:
            _spin.update("Looking up Japanese Wikipedia directly…")
            try:
                _ja_pages = ja_wikipedia_pages(tuple(c for c in _candidates(8) if c != (_wiki or {}).get("ja_title")))
            except Exception as e:
                _errors.append(f"Japanese Wikipedia: {e}")
        rows = assemble_rows(jmd, term, _jm, _wiki, _wd, _ndl, _composed, use_rules.value, _syn_e, _ja_pages, _extra)
        _appid = cinii_appid.value.strip() or os.environ.get("CINII_APPID", "").strip()
        if _appid:
            _spin.update(f"Counting CiNii Research records for {len(rows)} forms…")
            try:
                counts = cinii_counts([r["Japanese"] for r in rows], _appid,
                                      lambda n, total: _spin.update(f"Counting CiNii Research records… {n}/{total}"))
            except Exception as e:
                _errors.append(f"CiNii: {e}")
                counts = None
    decide_ticks(rows, counts, int(min_hits.value), float(min_share.value))

    _found = {f: any(f in r["Sources"] for r in rows) for f in FAMILIES}
    _summary = mo.md(
        f"**{len(rows)}** forms for *{term}* · found in: "
        + ", ".join(f"{'✓' if ok else '✗'} {f}" for f, ok in _found.items())
        + (f" · also looked up: {', '.join(_synonyms)}" if _synonyms else "")
        + ("" if counts is not None else " · _add a CiNii app ID to see how often each form is used_")
    )
    mo.vstack([_summary] + [mo.callout(e, kind="danger") for e in _errors])
    return counts, rows, term


@app.cell(hide_code=True)
def _(counts, rows):
    _cols = ["Japanese", "CiNii records", "Flags", "Type", "Sources", "Romaji", "Note"]
    if counts is None:
        _cols.remove("CiNii records")
    _view = [{c: r[c] for c in _cols} for r in rows]
    results_table = mo.ui.table(
        _view,
        selection="multi",
        initial_selection=[i for i, r in enumerate(rows) if r["_tick"]],
        page_size=60,
        wrapped_columns=["Note", "Flags"],
        freeze_columns_left=["Japanese"],
        label=("Ticked: forms with enough CiNii records (see Settings)" if counts is not None
               else "Ticked: main dictionary forms and forms found in two or more sources")
        + ". See 'How to read this table' at the bottom of the page.",
    )
    query_style = mo.ui.dropdown(["OR, quoted", "OR, unquoted", "One per line"], value="OR, unquoted", label="Query format")
    compact = mo.ui.checkbox(value=False, label="Compact query: leave out forms that CiNii treats as the same search")
    mo.vstack([results_table, mo.hstack([query_style, compact], justify="start")])
    return compact, query_style, results_table


@app.cell(hide_code=True)
def _(compact, query_style, results_table, rows, term):
    _same = {r["Japanese"] for r in rows if r.get("_same_as")}
    _picked = [r["Japanese"] for r in results_table.value if not (compact.value and r["Japanese"] in _same)]
    _query = build_query(_picked, query_style.value)
    mo.vstack([
        mo.md(f"### Search query for *{term}* · {len(_picked)} forms"),
        mo.ui.text_area(value=_query, rows=4, full_width=True),
        mo.download(data=_query.encode("utf-8"), filename=f"{term.replace(' ', '_')}_ja_query.txt",
                    mimetype="text/plain", label="Download query"),
        mo.md("<small>Each database has its own query syntax and length limits; check the search help pages.</small>"),
    ])
    return


@app.cell(hide_code=True)
def _():
    mo.accordion({"How to read this table": mo.md("""
    The app collects every Japanese way of writing your term that it can find, shows where each one comes from,
    and ticks the ones it suggests for your search query. **You decide**: tick or untick any row, and the query
    above updates.

    #### How the ticks are chosen
    - **With a CiNii app ID:** a form is ticked when enough records in CiNii Research use it: at least 5, and at
      least 1% as many as the most-used Japanese form (both adjustable in Settings). Forms that are only readings,
      possibly offensive, or narrower topics are never ticked automatically.
    - **Without an ID:** the dictionary's main forms are ticked, plus forms that two or more sources agree on.

    #### The columns
    | Column | What it tells you |
    |---|---|
    | **Japanese** | The form to search for, exactly as you would type it |
    | **CiNii records** | How many records in CiNii Research contain this form (only with an app ID) |
    | **Flags** | Warnings and remarks, explained below |
    | **Type** | What kind of form it is, explained below |
    | **Sources** | Where the form was found. The more sources agree, the more reliable the form |
    | **Romaji** | Pronunciation in Latin letters, for non-Japanese readers. Not used for searching. Empty when the form is already in Latin letters or the reading is uncertain; * means pieced together from dictionary words |
    | **Note** | The meaning or the reason the form is listed. **Check it**: English words with several meanings (e.g. *depression*) bring in all of them |

    #### Sources
    - **JMdict**: an open Japanese-English dictionary
    - **Wikipedia**: the Japanese article on the topic, and other titles that lead to it
    - **Wikidata**: the main and alternative Japanese names of the concept
    - **NDLSH**: the subject headings of Japan's National Diet Library (the national library)
    - **spelling rule**: made by the app from another form, using common patterns in Japanese spelling. A guess
      until CiNii shows records. "JMdict + spelling rule" means the dictionary lists it and the rule also produced it
    - **composed**: built by translating the words of a phrase one by one. Also a guess
    - **you** / **input**: forms you added, and your English term

    #### Types
    - **dictionary form**: a standard written form of the word, usually with kanji
    - **kana form / katakana form**: a form written in Japanese syllables only, common for loanwords (クオリティオブライフ)
    - **kana reading**: how a kanji word is pronounced. Not normally written this way, so never ticked
    - **abbreviation**: a short form such as QOL or AI
    - **old kanji form / okurigana variant / irregular kanji spelling**: older or less standard ways of writing the
      same word, which can still appear in older literature
    - **Wikipedia article title / Wikipedia redirect**: the article's name, or another title that leads to it
    - **Wikidata label / alias**: the main or an alternative Japanese name on Wikidata
    - **NDL subject heading**: the national library's official term for the subject; catalogues file books under it
    - **NDLSH variant**: another name the library records for the same subject (a *"see from"* reference: someone
      looking up the variant is sent to the official heading). Searching the official heading in a library
      catalogue finds the books; the variant can still appear in titles and abstracts
    - **spelling variant (rule)** / **composed from parts**: made by the app, see Sources
    - **added by you** / **English form**: your own additions and your original term

    #### Flags
    - **same search as … in CiNii**: CiNii treats this form and the one named as the same search (for example
      hiragana and katakana, or full-width and normal letters). Tick "Compact query" to leave such duplicates out
    - **narrower; already found by …**: a longer form that contains a ticked form, so searching the shorter form
      already finds it
    - **few records**: used in CiNii, but rarely compared with the main form
    - **rare or older / informal**: labelled so in the dictionary
    - **may be considered offensive**: an older term now often avoided (e.g. 痴呆 for dementia). Useful for finding
      older literature, but think before using it in teaching material
    - **reading only**: a pronunciation, not a written form
    - **single character**: also matches many longer words, so it gives broad results
    - **spelling variant of …**: the same form written slightly differently (shown when there is no CiNii ID)

    **Tip:** when in doubt, ask someone who reads Japanese to check the ticked forms.
    """)})
    return


@app.cell(hide_code=True)
def _():
    mo.md("""
    <small>Data: JMdict © Electronic Dictionary Research and Development Group, CC BY-SA 4.0 ·
    Wikipedia (CC BY-SA) · Wikidata (CC0) · subject headings obtained from Web NDL Authorities ·
    record counts from CiNii Research (NII). Romaji comes from dictionary readings; * marks readings
    pieced together from dictionary words, which can be wrong for compounds.</small>
    """)
    return


if __name__ == "__main__":
    app.run()
