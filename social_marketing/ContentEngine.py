"""
ContentEngine — the core agent that turns build progress into platform-native posts.

Given a "what changed" description, it:
1. Tracks what's already been posted (prevents repeats)
2. Generates drafts for X, Instagram, and LinkedIn
3. Applies the brand voice (narrative-driven, technical depth, personal mission)
4. Requests appropriate visuals from the MediaGenerator

Voice Guide (Ralph Valcin / @ralphvalcin):
- Haitian native building for the Caribbean — this is personal
- Lead with the story/mission, then the tech
- Short sentences. Real specifics. No hype.
- "I'm Haitian. Remittances feed my family. This is why."
- Systems that move capital, not apps
- Buildathon. H200. 21 days. Real code.
"""

import json
import os
from datetime import datetime
from typing import Optional


class ContentEngine:
    """Generates platform-specific social content from project state changes."""

    def __init__(self, history_path: Optional[str] = None):
        self.history_path = history_path or os.path.join(
            os.path.dirname(__file__), "_history.json"
        )
        self.history = self._load_history()

        # Brand voice constants
        self.brand = {
            "handle": "@ralphvalcin",
            "project": "CARIB-CLEAR",
            "buildathon": "Future Caribbean Global AI Buildathon",
            "track": "Track 3: Finance, Payments & MSME Capital",
            "hashtags": [
                "#CARIB_CLEAR", "#FutureCaribbean", "#Buildathon",
                "#FinTech", "#AI", "#Caribbean", "#Haiti",
            ],
            "key_points": [
                "Haitian native building for the Caribbean",
                "3 proven systems merged into 1",
                "MSMEs locked out of collateral-based lending",
                "80-90% of Caribbean businesses are MSMEs",
                "Direct BBD↔JMD settlement, no USD bridge",
                "Cash-flow lending, not collateral",
                "H200 compute, 21-day buildathon",
                "NYSE pitch for winners",
            ],
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, description: str, detail: Optional[str] = None) -> dict:
        """
        Generate posts from a "what changed" description.

        Args:
            description: Short summary of what was built/fixed/iterated
            detail: Optional deeper technical context

        Returns:
            dict with keys: 'x', 'instagram', 'linkedin'
        """
        session_id = self._session_id(description)

        # Check for duplicate
        if session_id in self.history.get("posted", []):
            return {"error": "Already posted this update", "session_id": session_id}

        posts = {
            "x": self._format_x(description, detail),
            "instagram": self._format_instagram(description, detail),
            "linkedin": self._format_linkedin(description, detail),
        }

        # Mark posted
        self._mark_posted(session_id)
        return posts

    def session_closeout(self, builds: list[dict]) -> dict:
        """
        Generate a session closeout / dev log post from a list of builds.

        Each build dict: { description, detail?, type? }
        type: 'feature' | 'fix' | 'refactor' | 'docs' | 'infra'
        """
        count = len(builds)
        types = [b.get("type", "feature") for b in builds]

        # Build a narrative summary
        features = [b for b in builds if b.get("type", "feature") == "feature"]
        fixes = [b for b in builds if b.get("type") == "fix"]

        lines = []
        if features:
            lines.append(f"Built: {' • '.join(b['description'] for b in features)}")
        if fixes:
            lines.append(f"Fixed: {' • '.join(b['description'] for b in fixes)}")

        return self.generate(
            f"Session closeout: {count} changes ({', '.join(types)})",
            "\n".join(lines),
        )

    def install_xurl_guide(self) -> str:
        """Returns instructions for setting up xurl for X/Twitter posting."""
        return XURL_SETUP_GUIDE

    # ------------------------------------------------------------------
    # Internal formatters
    # ------------------------------------------------------------------

    def _format_x(self, description: str, detail: Optional[str]) -> str:
        """Short, punchy, narrative-first. Max 280 chars per post (thread OK)."""
        short_post = self._build_short_post(description)
        if len(short_post) <= 280:
            return short_post
        # Fall back to a thread
        return f"{short_post[:250]}...\n\nThread below 👇"

    def _format_instagram(self, description: str, detail: Optional[str]) -> dict:
        """Visual-first. Returns caption + media generation prompt."""
        caption = self._build_caption(description)
        if detail:
            caption += f"\n\n{detail[:200]}"
        caption += (
            f"\n\n#CARIB_CLEAR #FutureCaribbean #Buildathon "
            f"#CaribbeanTech #FinTech #Haiti #AI #MSME"
        )
        return {
            "caption": caption,
            "media_prompt": self._media_prompt_for(description),
        }

    def _format_linkedin(self, description: str, detail: Optional[str]) -> str:
        """Professional, narrative-driven, longer form."""
        return self._build_linkedin_post(description, detail)

    # ------------------------------------------------------------------
    # Post builders
    # ------------------------------------------------------------------

    def _build_short_post(self, description: str) -> str:
        """Core narrative post — short sentences, real specifics."""
        # Narrative templates
        templates = [
            f"Today on CARIB-CLEAR: {description}",
            f"{description}. Caribbean financial infrastructure, one commit at a time.",
            f"Buildathon update. Just finished: {description}.",
        ]
        base = templates[1]  # default

        # Add narrative hook
        hooks = [
            "Haitian kid building fintech for the Caribbean. This is the stuff.",
            "80% of Caribbean businesses are MSMEs with no access to credit. This changes that.",
            "No USD bridge. Direct settlement. That's the whole point.",
        ]
        post = f"{base}\n\n{hooks[0]}"

        # Add buildathon tag
        post += f"\n\n#CARIB_CLEAR #FutureCaribbean"
        return post

    def _build_caption(self, description: str) -> str:
        """Instagram caption — narrative hook, then what, then why."""
        return (
            f"Building CARIB-CLEAR — agentic financial infrastructure "
            f"for the Caribbean.\n\n"
            f"{description}.\n\n"
            f"I'm Haitian. Remittances feed my family. "
            f"Three weeks on H200, three proven codebases merged into one. "
            f"This is why."
        )

    def _build_linkedin_post(self, description: str, detail: Optional[str]) -> str:
        """LinkedIn — professional narrative with technical depth."""
        lines = [
            f"CARIB-CLEAR update: {description}",
            "",
            "I'm building this for the Future Caribbean Global AI Buildathon "
            "(Track 3: Finance, Payments & MSME Capital).",
            "",
        ]
        if detail:
            lines.append(detail)
            lines.append("")
        lines.append(
            "The Caribbean has $5.5B+ in banking revenue, $20B+ in annual remittances, "
            "and 80-90% of businesses are MSMEs locked out of collateral-based lending. "
            "This isn't a technology problem. It's a coordination problem."
        )
        lines.append("")
        lines.append(
            "Three codebases merged: algorithmic trading governance → "
            "JARVIS voice pipeline → Kreyol-AI LLM. One agentic swarm on H200."
        )
        lines.append("")
        lines.append("#CARIB_CLEAR #FutureCaribbean #Buildathon #FinTech #Caribbean #AI")
        return "\n".join(lines)

    def _media_prompt_for(self, description: str) -> str:
        """Generate an image prompt from the description."""
        # Map common keywords to visual concepts
        if any(w in description.lower() for w in ["matching", "swap", "fx", "exchange"]):
            return (
                "A clean architectural diagram showing two Caribbean islands "
                "connected by a glowing currency swap line, dark background, "
                "neon blue and green, data flow visualization, modern fintech style"
            )
        if any(w in description.lower() for w in ["credit", "lending", "loan", "score"]):
            return (
                "A futuristic credit score visualization with Caribbean flags, "
                "data flowing upward, dark theme, blue and gold gradients, "
                "modern dashboard aesthetic"
            )
        if any(w in description.lower() for w in ["agent", "pipeline", "orchestrat"]):
            return (
                "Abstract representation of AI agents communicating, "
                "network nodes connected by light beams, Caribbean colors, "
                "dark background, tech-art style"
            )
        # Default
        return (
            "CARIB-CLEAR project architecture overview, two-layer design, "
            "FX swap network on top and MSME credit layer below, "
            "connected by glowing settlement rails, Caribbean blue and green palette, "
            "dark futuristic background, clean tech diagram style"
        )

    # ------------------------------------------------------------------
    # History tracking
    # ------------------------------------------------------------------

    def _session_id(self, description: str) -> str:
        return description.strip().lower().replace(" ", "-")[:60]

    def _load_history(self) -> dict:
        if os.path.exists(self.history_path):
            try:
                with open(self.history_path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {"posted": [], "updated_at": None}

    def _mark_posted(self, session_id: str) -> None:
        self.history.setdefault("posted", []).append(session_id)
        self.history["updated_at"] = datetime.utcnow().isoformat()
        os.makedirs(os.path.dirname(self.history_path) or ".", exist_ok=True)
        with open(self.history_path, "w") as f:
            json.dump(self.history, f, indent=2)


# ---------------------------------------------------------------------------
# xurl setup guide (printable for the user)
# ---------------------------------------------------------------------------

XURL_SETUP_GUIDE = """
═══ X/Twitter Setup for @ralphvalcin ═══

You need to do this ONCE on your machine. It takes ~10 minutes.

Step 1: Install xurl
─────────────────────
    curl -fsSL https://raw.githubusercontent.com/xdevplatform/xurl/main/install.sh | bash
    # Verify:
    xurl --help

Step 2: Create an X Developer App
──────────────────────────────────
    1. Go to https://developer.x.com/en/portal/dashboard
    2. Sign in as @ralphvalcin
    3. Click "Create App" → name it "carib-clear-bot" or similar
    4. App type: "Web app, automated app or bot" (NOT Native App)
    5. Redirect URI: http://localhost:8080/callback
    6. Copy your Client ID and Client Secret

Step 3: Register the app locally
─────────────────────────────────
    xurl auth apps add carib-clear \\
        --client-id YOUR_CLIENT_ID \\
        --client-secret YOUR_CLIENT_SECRET

Step 4: Authenticate
─────────────────────
    xurl auth oauth2 --app carib-clear
    # Your browser opens → authorize → token saved locally
    # If it fails: xurl auth oauth2 --app carib-clear ralphvalcin

Step 5: Set as default
───────────────────────
    xurl auth default carib-clear

Step 6: Verify
───────────────
    xurl auth status
    xurl whoami
    # Should show @ralphvalcin

Done! Once set up, I can post to X for you using xurl.

⚠️ NEVER share or show ~/.xurl file contents — it contains auth tokens.
"""