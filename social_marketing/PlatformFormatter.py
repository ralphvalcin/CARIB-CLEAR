"""
PlatformFormatter — adapts raw content to platform-native formats.

Each platform has constraints:
- X: 280 chars per post, 4000 with threads, supports media
- Instagram: 2200 char captions, carousel support, visual-first
- LinkedIn: 3000 chars, professional tone, long-form OK
- Discord: 2000 chars per message, code blocks supported
"""

from typing import Optional


class PlatformFormatter:
    """Adapts content for each platform's format and audience."""

    MAX_CHARS = {
        "x_single": 280,
        "x_thread_post": 4000,
        "instagram_caption": 2200,
        "linkedin_post": 3000,
        "discord_message": 2000,
    }

    @staticmethod
    def for_x(content: str, as_thread: bool = False) -> str:
        """
        Format content for X/Twitter.
        Short sentences. Punchy. No fluff. Hashtags at end.
        """
        limit = PlatformFormatter.MAX_CHARS["x_thread_post"] if as_thread else PlatformFormatter.MAX_CHARS["x_single"]

        # Strip markdown formatting (X doesn't render it well)
        clean = content.replace("**", "").replace("__", "").replace("### ", "")

        if len(clean) <= limit:
            return clean

        # Truncate cleanly at word boundary
        truncated = clean[:limit].rsplit(" ", 1)[0] + "..."
        return truncated

    @staticmethod
    def for_instagram(caption: str, media_url: Optional[str] = None) -> dict:
        """
        Format content for Instagram.
        Returns caption + media reference.
        Instagram is visual-first — the caption supports the image.
        """
        limit = PlatformFormatter.MAX_CHARS["instagram_caption"]

        # Instagram captions: story first, then details, then hashtags
        if len(caption) > limit:
            caption = caption[: limit - 50].rsplit(" ", 1)[0] + "..."

        return {
            "caption": caption,
            "media_url": media_url,
            "alt_text": "CARIB-CLEAR project build in public update",
        }

    @staticmethod
    def for_linkedin(content: str) -> str:
        """
        Format content for LinkedIn.
        Professional tone. Longer paragraphs. Line breaks between sections.
        """
        limit = PlatformFormatter.MAX_CHARS["linkedin_post"]

        if len(content) > limit:
            content = content[: limit - 100].rsplit("\n", 1)[0] + "\n\n..."

        return content

    @staticmethod
    def thread_for_x(posts: list[str]) -> list[str]:
        """
        Convert a list of post segments into an X thread.
        Each post is numbered unless it's a single post.
        """
        if len(posts) == 1:
            return [PlatformFormatter.for_x(posts[0])]

        thread = []
        for i, post in enumerate(posts):
            formatted = PlatformFormatter.for_x(post, as_thread=True)
            thread.append(formatted)

        return thread

    @staticmethod
    def strip_ai_tells(text: str) -> str:
        """Quick cleanup of common AI writing tells before humanizer pass."""
        removals = [
            "In today's rapidly evolving",
            "In today's digital landscape",
            "It is important to note that",
            "It's worth noting that",
            "Let's dive into",
            "Let's explore",
            "Let me break this down",
            "Here's what you need to know",
            "stands as a testament",
            "serves as a",
            "pivotal moment",
            "evolving landscape",
            "underscores the importance",
            "at its core",
            "the heart of the matter",
            "the real question is",
            "In the event that",
            "Due to the fact that",
            "At this point in time",
        ]
        for phrase in removals:
            text = text.replace(phrase, "")
        return text.strip()