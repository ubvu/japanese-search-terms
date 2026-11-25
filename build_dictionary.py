"""Build the compact dictionary file the app loads (public/jmdict-en.json.gz).

Source: JMdict (EDRDG, CC BY-SA 4.0) from the jamdict-data package:
    python -m pip install jamdict-data
    python build_dictionary.py
Only what the app needs is kept: written forms, readings, English glosses, and usage tags.
"""
import gzip
import json
import sqlite3
from pathlib import Path

import jamdict_data

COMMON_PRI = {"news1", "ichi1", "spec1", "spec2", "gai1"}
# form flags (bit field)
K_COMMON, K_OLD_KANJI, K_IRREG_OKURIGANA, K_IRREG_KANJI = 1, 2, 4, 8
R_COMMON, R_NOKANJI, R_OLD_KANA = 1, 2, 4

db = sqlite3.connect(Path(jamdict_data.__file__).parent / "jamdict.db")
meta = dict(db.execute("SELECT key, value FROM meta"))
misc_names, field_names = [], []


def code(names, text):
    if text not in names:
        names.append(text)
    return names.index(text)


def nf(pris):
    vals = [int(p[2:]) for p in pris if p.startswith("nf")]
    return min(vals) if vals else None


kj_pri, kj_inf, kn_pri, kn_inf = {}, {}, {}, {}
for table, target in [("KJP", kj_pri), ("KJI", kj_inf), ("KNP", kn_pri), ("KNI", kn_inf)]:
    for kid, text in db.execute(f"SELECT kid, text FROM {table}"):
        target.setdefault(kid, []).append(text)
misc, field = {}, {}
for sid, text in db.execute("SELECT sid, text FROM misc"):
    misc.setdefault(sid, []).append(code(misc_names, text))
for sid, text in db.execute("SELECT sid, text FROM field"):
    field.setdefault(sid, []).append(code(field_names, text))
glosses = {}
for sid, text in db.execute("SELECT sid, text FROM SenseGloss WHERE lang='eng' ORDER BY rowid"):
    glosses.setdefault(sid, []).append(text)

kanji, kana, senses = {}, {}, {}
for kid, idseq, text in db.execute("SELECT ID, idseq, text FROM Kanji ORDER BY ID"):
    inf = kj_inf.get(kid, [])
    flags = (K_COMMON * bool(set(kj_pri.get(kid, [])) & COMMON_PRI)
             | K_OLD_KANJI * ("word containing out-dated kanji" in inf)
             | K_IRREG_OKURIGANA * ("irregular okurigana usage" in inf)
             | K_IRREG_KANJI * ("word containing irregular kanji usage" in inf))
    kanji.setdefault(idseq, []).append([text, flags, nf(kj_pri.get(kid, []))])
for kid, idseq, text, nokanji in db.execute("SELECT ID, idseq, text, nokanji FROM Kana ORDER BY ID"):
    flags = (R_COMMON * bool(set(kn_pri.get(kid, [])) & COMMON_PRI) | R_NOKANJI * bool(nokanji)
             | R_OLD_KANA * ("out-dated or obsolete kana usage" in kn_inf.get(kid, [])))
    kana.setdefault(idseq, []).append([text, flags, nf(kn_pri.get(kid, []))])
for sid, idseq in db.execute("SELECT ID, idseq FROM Sense ORDER BY ID"):
    if sid in glosses:
        senses.setdefault(idseq, []).append([glosses[sid], misc.get(sid, []), field.get(sid, [])])

entries = []
for idseq in sorted(senses):
    ks, rs = kanji.get(idseq, []), kana.get(idseq, [])
    freqs = [x[2] for x in ks + rs if x[2] is not None]
    common = any(x[1] & 1 for x in ks + rs)
    freq = min(freqs) if freqs else (50 if common else 99)
    entries.append([[x[:2] for x in ks], [x[:2] for x in rs], senses[idseq], freq])

out = {
    "source": "JMdict, Electronic Dictionary Research and Development Group, CC BY-SA 4.0",
    "version": f"JMdict {meta.get('jmdict.version', '')}, data {meta.get('jmnedict.date', '')[:10]}",
    "misc": misc_names, "field": field_names, "entries": entries,
}
path = Path(__file__).parent / "public" / "jmdict-en.json.gz"
with gzip.open(path, "wt", encoding="utf-8", compresslevel=9) as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
print(f"{len(entries)} entries -> {path} ({path.stat().st_size / 1e6:.1f} MB)")
