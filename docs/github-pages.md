---
layout: default
title: GitHub Pages Deploy
description: How to publish the AgenticLocal project website from the docs folder with GitHub Pages and preview the static pages locally.
---

# GitHub Pages Deploy

The project page lives in:

```text
docs/index.html
```

It is designed for GitHub Pages with the `docs/` folder as the publishing
source.

## Deploy From Repository Settings

1. Push `main` to GitHub.
2. Open the repository on GitHub.
3. Go to **Settings** -> **Pages**.
4. Under **Build and deployment**, choose **Deploy from a branch**.
5. Select branch `main`.
6. Select folder `/docs`.
7. Save.

GitHub will publish the project page at a URL like:

```text
https://<owner>.github.io/<repo>/
```

For this repository, that will usually be:

```text
https://bowen-ai.github.io/AgenticLocal/
```

## What Gets Published

The static entry page:

```text
docs/index.html
```

Supporting styles:

```text
docs/site.css
```

Screenshot assets:

```text
docs/assets/screenshots/
```

Markdown docs in `docs/` are also rendered by GitHub Pages through Jekyll.

## Search Indexing

The site publishes crawler discovery files at:

```text
https://bowen-ai.github.io/AgenticLocal/robots.txt
https://bowen-ai.github.io/AgenticLocal/sitemap.xml
```

After GitHub Pages finishes deploying, add the property in Google Search
Console and submit:

```text
https://bowen-ai.github.io/AgenticLocal/sitemap.xml
```

If Google Search Console gives you an HTML meta verification token, paste the
token into `google_site_verification` in `docs/_config.yml`.

## Local Preview

From the repository root:

```bash
python3 -m http.server 8080 --directory docs
```

Then open:

```text
http://127.0.0.1:8080/
```

This simple preview serves the project page, CSS, and image assets. GitHub
Pages will additionally render Markdown files into HTML through Jekyll, so links
such as `install.html` and `use-cases.html` resolve after the Pages build.
