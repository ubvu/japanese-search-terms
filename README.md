# English → Japanese search terms

A web app that finds the Japanese ways of writing an English search term, for searching Japanese
databases such as CiNii Research, J-STAGE and NDL Search. It returns dictionary forms, spelling
variants, synonyms and library subject headings, shows where each form comes from, and builds a
ready-to-use search query from the forms you tick.

It uses no AI model: every form is looked up in open sources. With a free CiNii app ID, the app
also shows how often each form occurs in CiNii Research, and ticks the forms that are actually used.

**Use the app:** https://ACCOUNT.github.io/REPOSITORY/ *(replace with the real link once published)*

## For users

- Nothing to install: the app runs in your web browser. Opening it takes about 15 to 30 seconds,
  while the browser starts Python and prepares the dictionary.
- Optional: paste your own free CiNii app ID (https://support.nii.ac.jp/en/cinii/api/developer)
  in the box at the top to see record counts. It is used only during your visit and is not stored.
- The "How to read this table" panel at the bottom of the app explains every column.
- Have the ticked forms checked by someone who reads Japanese when the search matters.

**Privacy:** the terms you search are sent from your browser to Wikipedia, Wikidata, the National
Diet Library and CiNii to look them up. The app itself collects and stores nothing. GitHub, which
hosts the page, logs visitors' IP addresses for security purposes.

## How it works

| Source | What it adds |
|---|---|
| JMdict dictionary (in `public/`) | Standard forms, spellings and readings, with usage tags |
| Wikipedia and Wikidata | The Japanese article title, other titles that lead to it, alternative names |
| NDL Subject Headings | The national library's official subject heading and its variants |
| CiNii Research | How many records use each form (with the user's own app ID) |
| Spelling rules | Common spelling variants (long-vowel mark, middle dot, old kanji, …) |

The app is a [marimo](https://marimo.io) notebook, `jp_search_terms.py`. GitHub turns it into a
website that runs in the browser (WebAssembly) every time the main branch changes; see
`.github/workflows/deploy.yml` and [PUBLISHING.md](PUBLISHING.md).

## Files

| File | What it is |
|---|---|
| `jp_search_terms.py` | The app |
| `public/jmdict-en.json.gz` | Compact copy of the JMdict dictionary that the app loads |
| `build_dictionary.py` | Rebuilds the dictionary file (only needed to update it) |
| `.github/workflows/deploy.yml` | Instructions for GitHub to build and publish the website |
| `PUBLISHING.md` | How to publish and update the app |

## Run it on your own computer

```
python -m pip install marimo requests
python -m marimo run jp_search_terms.py
```

To try the browser version locally:

```
python -m marimo export html-wasm jp_search_terms.py -o site --mode run -f
python -m http.server 8001 --directory site
```

Then open http://localhost:8001. Use a port where no other marimo app has run before: a leftover
browser helper from such an app can block the dictionary download.

## Licences

- **Code:** MIT, see [LICENSE](LICENSE).
- **Dictionary data:** JMdict © Electronic Dictionary Research and Development Group, CC BY-SA 4.0,
  see [LICENSE-DATA.md](LICENSE-DATA.md).
