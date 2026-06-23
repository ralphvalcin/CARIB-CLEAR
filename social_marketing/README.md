# CARIB-CLEAR Social Media Marketing Department

> Build in public for the Future Caribbean Global AI Buildathon

## What This Is

An agent-powered social media department that turns CARIB-CLEAR's build progress into platform-native content. Every time we build something, fix something, or hit a milestone, the ContentEngine generates posts for X, Instagram, and LinkedIn — in your voice, for each platform's format.

## Department Structure

```
social_marketing/
├── README.md              ← This file
├── __init__.py            ← Package
├── ContentEngine.py       ← Core agent: turns "what changed" into posts
├── PlatformFormatter.py   ← Adapts content per platform (X, Instagram, LinkedIn)
├── MediaGenerator.py      ← Creates visual assets (diagrams, cards)
├── content_calendar.md    ← Strategy, schedule, templates
└── _history.json          ← Track what's been posted (auto)
```

## How to Use

### Quick: after every build session

```python
from social_marketing import ContentEngine

engine = ContentEngine()
posts = engine.generate(
    "Built the P2P matching engine with multilateral netting",
    detail="80% volume reduction, <5min settlement, direct BBD↔JMD no USD bridge"
)
# posts = {
#   "x": "Day whatever...",
#   "instagram": {"caption": "...", "media_prompt": "..."},
#   "linkedin": "..."
# }
```

### Session closeout (multiple builds)

```python
engine.session_closeout([
    {"description": "StellarAdapter with mock mode", "type": "feature"},
    {"description": "NetSettlement multilateral netting", "type": "feature"},
    {"description": "Fixed compliance agent KYC threshold bug", "type": "fix"},
])
```

## Platforms

| Platform | Status | Method |
|----------|--------|--------|
| **X/Twitter** | Ready after xurl setup | `xurl post` |
| **Instagram** | Manual (you post) | I generate caption + image, you post through app |
| **LinkedIn** | Manual or via X-post | Longer-form narrative posts |

## Setting Up X/Twitter

See `ContentEngine.install_xurl_guide()` or the X_URL_SETUP_GUIDE constant in ContentEngine.py.

One-time setup (~10 minutes):
1. Install xurl CLI
2. Create X Developer App
3. Authenticate with OAuth
4. Verify with `xurl whoami`

After that, I can post to X directly for you.

## Voice Guide

- **Who:** Haitian native building for the Caribbean
- **Tone:** Narrative-first, specific, personal
- **No:** Hype, corporate speak, generic AI writing
- **Yes:** Short sentences, real specifics, the hard parts, the mission
- **Key themes:** 3 codebases merged, 80-90% MSMEs, no USD bridge, cash-flow lending, building alone with AI

## Content Calendar

See `content_calendar.md` for the full pre-buildathon + buildathon schedule with daily post angles.