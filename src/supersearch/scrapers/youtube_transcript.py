"""YouTube transcript scraper. Pulls auto-captions from video URLs/IDs."""

import json
import re
import sys

from youtube_transcript_api import YouTubeTranscriptApi


def extract_video_id(url_or_id):
    """Extract YouTube video ID from URL or return as-is if already an ID."""
    patterns = [
        r'(?:v=|\/v\/|youtu\.be\/)([a-zA-Z0-9_-]{11})',
        r'^([a-zA-Z0-9_-]{11})$',
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
    return url_or_id


def get_transcript(url_or_id, max_words=None):
    """Get transcript from a YouTube video.

    Args:
        url_or_id: YouTube URL or video ID
        max_words: If set, truncate to first N + middle N + last N words (for LLM context)
    """
    video_id = extract_video_id(url_or_id)

    output = {
        "video_id": video_id,
        "url": f"https://youtube.com/watch?v={video_id}",
        "transcript": "",
        "word_count": 0,
        "duration_seconds": 0,
        "language": "",
        "error": None,
    }

    try:
        api = YouTubeTranscriptApi()
        result = api.fetch(video_id)

        full_text = " ".join(snippet.text for snippet in result.snippets)
        output["language"] = result.language_code
        last = result.snippets[-1] if result.snippets else None
        output["duration_seconds"] = int(last.start + last.duration) if last else 0

        # Truncation strategy for LLM context: first + middle + last
        if max_words and len(full_text.split()) > max_words * 3:
            words = full_text.split()
            n = max_words
            truncated = words[:n] + words[len(words)//2 - n//2 : len(words)//2 + n//2] + words[-n:]
            full_text = " ".join(truncated)

        output["transcript"] = full_text
        output["word_count"] = len(full_text.split())

    except Exception as e:
        output["error"] = str(e)

    return output


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m supersearch.scrapers.youtube_transcript <video_url_or_id> [max_words]")
        sys.exit(1)
    max_w = int(sys.argv[2]) if len(sys.argv) > 2 else None
    result = get_transcript(sys.argv[1], max_words=max_w)
    print(json.dumps(result, indent=2))
