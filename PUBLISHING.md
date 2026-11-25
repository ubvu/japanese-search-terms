# Publishing and updating the app

Everything below happens in the browser on github.com. No Git or Python installation is needed.

## First publication

### 1. Create the repository
1. In the library's GitHub account, click **New repository**.
2. **Repository name:** this becomes part of the link, `https://ACCOUNT.github.io/REPOSITORY-NAME/`.
   Choose something short and clear, e.g. `japanese-search-terms`.
3. Set it to **Public** (needed for GitHub Pages on a free account).
4. Leave "Add a README" and the other options **unticked**, then click **Create repository**.

### 2. Upload the files
1. On the new repository page, click **uploading an existing file**.
2. Drag in: `jp_search_terms.py`, `build_dictionary.py`, `README.md`, `PUBLISHING.md`, `LICENSE`,
   `LICENSE-DATA.md`, `.gitignore`, and the **`public` folder** (with `jmdict-en.json.gz` inside).
3. Write a short message (e.g. "First version") and click **Commit changes**.
4. Check that the repository shows the `public` folder with the dictionary file in it.

### 3. Add the build file
Your computer may hide the `.github` folder, and GitHub may skip it when you drag folders in, so
create this file by hand:

1. Click **Add file → Create new file**.
2. As the name, type exactly: `.github/workflows/deploy.yml`
   (typing the `/` creates the folders).
3. Open `deploy.yml` from the folder you received, copy all its text, and paste it into the editor.
4. Click **Commit changes**.

### 4. Switch on GitHub Pages
1. Go to **Settings → Pages** (left menu).
2. Under **Build and deployment → Source**, choose **GitHub Actions**.

### 5. Start the first build
1. Go to the **Actions** tab. A run called "Publish app to GitHub Pages" may already be running,
   started by step 3. If not, click it in the left menu and then **Run workflow**.
2. Wait 2 to 3 minutes until it shows a **green tick**. A red cross means something failed: click
   the run to see the step and its message.
3. The link appears under **Settings → Pages** ("Your site is live at …") and on the run's summary.

### 6. Test
Open the link, wait for the dictionary to load, and try a few terms, with and without a CiNii app ID.
Check that the summary line under the search shows ✓ for JMdict, Wikipedia, Wikidata and NDLSH.
Then replace the placeholder link at the top of `README.md` with the real one.

## Updating the app

- **Change the app:** open `jp_search_terms.py` on GitHub, click the pencil icon (Edit), make the
  change, and **Commit changes**. Or upload a new version via **Add file → Upload files**.
- GitHub rebuilds and republishes the website automatically within a few minutes (see the
  **Actions** tab). Users get the new version the next time they open the link.
- **Update marimo:** change the version number in `.github/workflows/deploy.yml`
  (`marimo==0.25.2`), then check the app after the rebuild.
- **Update the dictionary:** run `build_dictionary.py` locally (see the notes at the top of that
  file) and upload the new `public/jmdict-en.json.gz`.

## If the build fails

| Message in the Actions run | What to do |
|---|---|
| "The dictionary file is missing from the website" | Check that `public/jmdict-en.json.gz` is in the repository |
| A Python error in "Build the website" | The last change to `jp_search_terms.py` has a mistake: undo it (History → revert) |
| "Get Pages site failed" / permission errors | Check that Settings → Pages → Source is set to **GitHub Actions** |
