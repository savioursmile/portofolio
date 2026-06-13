# Portfolio site

A single-page portfolio with a dark, bento-grid, neon-glow design.

## Sections
- Home (hero with gradient text, glow background)
- Skills marquee (slow + fast scrolling rows)
- Projects (bento grid)
- Contact (form — currently a placeholder, see below)
- License (MIT)
- Donate

## Run locally
Just open `index.html` in a browser — no build step needed.

## Deploy on Render
1. Push this folder to a GitHub repo.
2. On Render, create a new **Static Site**, connect the repo.
3. Build command: (leave blank)
4. Publish directory: `.`
5. Deploy — Render gives you a free `*.onrender.com` URL.

## Wiring up the contact form
The form currently just shows an alert. To make it send real messages without a backend, use a free form service like:
- Formspree (formspree.io) — add `action="https://formspree.io/f/YOUR_ID"` and `method="POST"` to the `<form>` tag, remove the JS alert.
- Or build a small Express endpoint and deploy it alongside (Render Web Service instead of Static Site).

## Customizing
- Colors: edit the `--purple` / `--blue` variables in `<style>`.
- Content: edit text directly in `index.html`, replace placeholder project cards with your real work.
- Donate links: replace the placeholder cards with real links to Ko-fi / GitHub Sponsors / PayPal.
