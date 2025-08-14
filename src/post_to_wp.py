#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Upload eines HTML-Artikels nach WordPress als Entwurf inkl. Beitragsbild.

Voraussetzungen:
  pip install requests beautifulsoup4

Beispielaufruf:
  python wp_upload_html.py \
    --wp-url https://example.com \
    --username dein-benutzer \
    --app-password "abcd abcd abcd abcd abcd abcd" \
    --html /pfad/zum/artikel.html \
    --image /pfad/zum/bild.jpg \
    --status draft
"""

import argparse
import base64
import mimetypes
import os
import sys
from urllib.parse import quote
from typing import Optional

import requests
from bs4 import BeautifulSoup


def extract_title_from_html(html_text: str) -> Optional[str]:
    soup = BeautifulSoup(html_text, "html.parser")
    if soup.title and soup.title.string:
        t = soup.title.string.strip()
        if t:
            return t
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)
    meta_og = soup.find("meta", attrs={"property": "og:title"})
    if meta_og and meta_og.get("content"):
        return meta_og["content"].strip()
    meta_headline = soup.find(attrs={"itemprop": "headline"})
    if meta_headline and meta_headline.get_text(strip=True):
        return meta_headline.get_text(strip=True)
    return None


def get_auth_header(username: str, app_password: str) -> dict:
    token = base64.b64encode(f"{username}:{app_password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def find_existing_media(base_url, auth_header, filename):
    """Prüft, ob bereits ein Medium mit diesem Dateinamen existiert."""
    media_endpoint = f"{base_url.rstrip('/')}/wp-json/wp/v2/media"
    search_url = f"{media_endpoint}?search={quote(filename)}&per_page=100"
    resp = requests.get(search_url, headers=auth_header, timeout=30)
    resp.raise_for_status()

    for item in resp.json():
        if item.get("media_type") == "image":
            source_url = os.path.basename(item.get("source_url", "")).lower()
            if source_url == filename.lower():
                return item.get("id")
    return None


def upload_media(base_url, auth_header, image_path, title=None, alt_text=None, caption=None):
    media_endpoint = f"{base_url.rstrip('/')}/wp-json/wp/v2/media"

    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Bilddatei nicht gefunden: {image_path}")

    filename = os.path.basename(image_path)

    # 1) Vorhandenes Medium suchen
    existing_id = find_existing_media(base_url, auth_header, filename)
    if existing_id:
        print(f"Bild '{filename}' bereits vorhanden (ID {existing_id}), Upload übersprungen.")
        return existing_id

    # 2) Falls nicht vorhanden → hochladen
    mime_type, _ = mimetypes.guess_type(filename)
    if not mime_type:
        mime_type = "application/octet-stream"

    with open(image_path, "rb") as img_file:
        files = {"file": (filename, img_file, mime_type)}
        data = {}
        if title:
            data["title"] = title
        if alt_text:
            data["alt_text"] = alt_text
        if caption:
            data["caption"] = caption

        headers = {
            **auth_header,
            "Content-Disposition": f'attachment; filename="{filename}"'
        }

        resp = requests.post(media_endpoint, headers=headers, files=files, data=data, timeout=60)
        resp.raise_for_status()

        media_id = resp.json().get("id")
        if not media_id:
            raise RuntimeError(f"Keine Medien-ID erhalten: {resp.text}")
        print(f"Bild '{filename}' hochgeladen. Medien-ID: {media_id}")
        return int(media_id)


def create_post(base_url, auth_header, title, content_html, status="draft", featured_media_id=None, categories=None, tags=None):
    post_endpoint = f"{base_url.rstrip('/')}/wp-json/wp/v2/posts"
    payload = {
        "title": title,
        "content": content_html,
        "status": status,
    }
    if featured_media_id:
        payload["featured_media"] = featured_media_id
    if categories:
        payload["categories"] = categories
    if tags:
        payload["tags"] = tags

    headers = {
        **auth_header,
        "Content-Type": "application/json; charset=utf-8",
    }

    resp = requests.post(post_endpoint, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()

    post_id = resp.json().get("id")
    if not post_id:
        raise RuntimeError(f"Keine Post-ID in Antwort: {resp.text}")
    print(f"Beitrag erstellt (ID {post_id})")
    return int(post_id)


def main():
    parser = argparse.ArgumentParser(description="Lädt eine HTML-Datei als WordPress-Beitrag (Entwurf) hoch und setzt ein Beitragsbild.")
    parser.add_argument("--wp-url", required=True, help="Basis-URL deiner WordPress-Site, z.B. https://example.com")
    parser.add_argument("--username", required=True, help="WordPress-Benutzername")
    parser.add_argument("--app-password", required=True, help="Application Password")
    parser.add_argument("--html", required=True, help="Pfad zur HTML-Datei mit dem Artikel")
    parser.add_argument("--image", required=True, help="Pfad zur Bilddatei für das Beitragsbild")
    parser.add_argument("--title", default=None, help="Optionaler Titel; überschreibt automatisch extrahierten Titel")
    parser.add_argument("--status", default="draft", choices=["draft", "pending", "private"], help='Beitragsstatus (Standard: "draft")')
    parser.add_argument("--category-ids", default=None, help="Kommagetrennte Kategorie-IDs (z.B. 2,7)")
    parser.add_argument("--tag-ids", default=None, help="Kommagetrennte Schlagwort-IDs (z.B. 15,23)")
    args = parser.parse_args()

    if not os.path.isfile(args.html):
        print(f"HTML-Datei nicht gefunden: {args.html}", file=sys.stderr)
        sys.exit(1)
    with open(args.html, "r", encoding="utf-8") as f:
        html_text = f.read()

    title = args.title or extract_title_from_html(html_text) or "Neuer Beitrag"

    auth_header = get_auth_header(args.username, args.app_password)

    print("Prüfe oder lade Bild hoch …")
    media_id = upload_media(
        args.wp_url,
        auth_header,
        args.image,
        title=f"Beitragsbild zu: {title}",
        alt_text=title
    )

    categories = [int(x) for x in args.category_ids.split(",")] if args.category_ids else None
    tags = [int(x) for x in args.tag_ids.split(",")] if args.tag_ids else None

    print("Lege Beitrag (Entwurf) an …")
    post_id = create_post(
        args.wp_url,
        auth_header,
        title=title,
        content_html=html_text,
        status=args.status,
        featured_media_id=media_id,
        categories=categories,
        tags=tags
    )
    print(f"Fertig: {args.wp_url.rstrip('/')}/wp-admin/post.php?post={post_id}&action=edit")


if __name__ == "__main__":
    main()
