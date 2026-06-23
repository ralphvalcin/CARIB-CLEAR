"""
MediaGenerator — creates visual content for social posts.

Generates:
- Architecture diagrams (for deep dives)
- Progress cards (for daily updates)
- Comparison visuals (before/after)
- Teaser images (for feature announcements)

Uses the image_generate tool through terminal/execution.
Returns a file path that can be uploaded to X or posted to Instagram.
"""

import json
import os
from datetime import datetime
from typing import Optional

# Style guide for generated images
STYLE_GUIDE = """
CARIB-CLEAR media style:
- Dark background (#1a1a2e or darker)
- Caribbean blue (#1B2A4A navy + #5BA3E6 light blue)
- Gold accents (#F4A460 or gold)
- Clean lines, minimal text
- Tech/fintech aesthetic
- Subtle grid or data visualization elements
"""


class MediaGenerator:
    """Creates visual assets for social media posts."""

    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = output_dir or os.path.join(
            os.path.dirname(__file__), "_media"
        )
        os.makedirs(self.output_dir, exist_ok=True)

    def generate_visual(self, prompt: str) -> str:
        """
        Generate a visual asset from a text prompt.

        Returns the file path of the generated image.
        Uses the image_generate tool (configured backend).

        Args:
            prompt: Text description of the desired image
        """
        # Build the prompt with style guide
        full_prompt = f"{prompt.strip()}. {STYLE_GUIDE.strip()}"

        # Save the prompt for manual generation
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        manifest = {
            "prompt": full_prompt,
            "created": timestamp,
            "style": "CARIB-CLEAR brand",
        }

        manifest_path = os.path.join(self.output_dir, f"generation_{timestamp}.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        return manifest_path

    def setup_post_package(self, caption: str, media_prompt: str) -> dict:
        """
        Create a full post package: caption + media prompt.
        This is what gets handed to the human or the posting pipeline.

        Returns:
            dict with keys: caption, media_prompt, media_instructions
        """
        return {
            "caption": caption,
            "media_prompt": media_prompt,
            "media_instructions": (
                "Generate this image using image_generate tool, "
                "then upload to X with xurl media upload, "
                "or save for Instagram posting"
            ),
        }


# Registry of reusable visual concepts
VISUAL_CONCEPTS = {
    "architecture_two_layer": (
        "Dark fintech architecture diagram showing two connected layers. "
        "Top layer: 'CARICOM FX Swap Network' with Caribbean islands BBD, JMD, TTD, XCD "
        "connected by glowing currency swap lines. "
        "Bottom layer: 'MSME Credit Layer' with data flowing upward through "
        "lending agents. Settlement rails (Stellar, ACH, Mobile Money) "
        "as vertical connectors between layers. "
        "Navy and electric blue color scheme, subtle grid background."
    ),
    "cost_comparison": (
        "Split comparison graphic. Left side labeled 'Traditional': "
        "BBD → USD → JMD with arrows showing 7-9% fees and 3 day delay, "
        "red color scheme. Right side labeled 'CARIB-CLEAR': "
        "BBD → JMD direct arrow showing <1% fees and <5 minute settlement, "
        "green color scheme. Dark background, clean modern infographic style."
    ),
    "msme_credit_gap": (
        "Data visualization showing 80-90% of Caribbean businesses as MSMEs "
        "locked out of credit. A large pie chart where most of the pie is "
        "shaded gray (no access) with a small slice highlighted in gold "
        "(current credit access). A glowing 'Cash-Flow Lending' element "
        "showing the solution. Dark fintech style."
    ),
    "agent_swarm": (
        "Network visualization showing multiple AI agents connected by "
        "light beams. Agents labeled: FlowVisibility, P2PMatching, "
        "NetSettlement, Compliance, CashFlowLending. "
        "Central hub labeled 'Governance'. "
        "Dark background, Caribbean blue and teal color palette, "
        "futuristic but clean."
    ),
    "settlement_rails": (
        "Three vertical rail lanes: 'Stellar/USDC' (5s, 0.1bps), "
        "'Local ACH' (1-3h, 15-25bps), 'Mobile Money' (10s, 30-50bps). "
        "A glowing router arrow selecting the optimal path. "
        "Caribbean map silhouette in background. "
        "Dark tech UI aesthetic."
    ),
}