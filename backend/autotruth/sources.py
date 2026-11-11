"""Fetch review text from a URL: YouTube transcript, Reddit thread, or an article page."""
from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, urlparse

import httpx

from .models import Source

UA = {"User-Agent": "Mozilla/5.0 (compatible; AutoTruthBot/0.1)"}


class FetchError(Exception):
    pass


def _youtube_id(url: str) -> str | None:
    u = urlparse(url)
    host = u.netloc.lower().removeprefix("www.").removeprefix("m.")
    if host == "youtu.be":
        return u.path.strip("/").split("/")[0] or None
    if host.endswith("youtube.com"):
        if u.path == "/watch":
            return (parse_qs(u.query).get("v") or [None])[0]
        m = re.match(r"^/(?:shorts|embed|live)/([\w-]+)", u.path)
        return m.group(1) if m else None
    return None


def _strip_html(page: str) -> tuple[str, str]:
    title = re.search(r"<title[^>]*>(.*?)</title>", page, re.IGNORECASE | re.DOTALL)
    body = re.sub(r"(?is)<(script|style|noscript|nav|header|footer|aside|form|svg)\b.*?</\1>", " ", page)
    paras = re.findall(r"(?is)<(?:p|li|h[1-4])\b[^>]*>(.*?)</(?:p|li|h[1-4])>", body)
    text = "\n".join(t for t in (re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", p))).strip() for p in paras)
                     if len(t) > 40)
    return (html.unescape(title.group(1)).strip() if title else "Web article"), text


def fetch(url: str) -> tuple[Source, str]:
    if not re.match(r"^https?://", url):
        raise FetchError("Only http(s) URLs are supported.")
    video = _youtube_id(url)
    if video:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi

            snippets = YouTubeTranscriptApi().fetch(video)
            text = " ".join(s.text.replace("\n", " ") for s in snippets)
        except Exception as exc:
            raise FetchError(f"Could not fetch a transcript for this video ({type(exc).__name__}).") from exc
        return Source(type="youtube", title=f"YouTube video {video}", url=url), text

    host = urlparse(url).netloc.lower()
    try:
        with httpx.Client(headers=UA, follow_redirects=True, timeout=20) as client:
            if "reddit.com" in host:
                data = client.get(url.split("?")[0].rstrip("/") + ".json", params={"limit": 50}).raise_for_status().json()
                post = data[0]["data"]["children"][0]["data"]
                comments = [c["data"].get("body", "") for c in data[1]["data"]["children"] if c.get("kind") == "t1"]
                text = "\n".join([post.get("title", ""), post.get("selftext", ""), *comments])
                return Source(type="reddit", title=post.get("title", "Reddit thread"), url=url, author=post.get("author")), text
            page = client.get(url).raise_for_status().text
    except FetchError:
        raise
    except Exception as exc:
        raise FetchError(f"Could not fetch {host} ({type(exc).__name__}).") from exc
    title, text = _strip_html(page)
    if len(text) < 200:
        raise FetchError("No article text found on that page (it may need JavaScript or block automated access).")
    return Source(type="web", title=title, url=url), text
