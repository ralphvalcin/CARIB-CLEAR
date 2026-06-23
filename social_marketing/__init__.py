"""
CARIB-CLEAR Social Media Marketing Department.

A suite of tools for building in public — generates platform-native content
from project state changes, creates visuals, and manages posting schedules.

Usage:
    from social_marketing import ContentEngine
    
    engine = ContentEngine()
    posts = engine.generate("Finished the P2P matching engine with multilateral netting")
    # Returns {x: post_text, instagram: {caption, media_prompt}, linkedin: post_text}
"""

from .ContentEngine import ContentEngine
from .PlatformFormatter import PlatformFormatter
from .MediaGenerator import MediaGenerator

__version__ = "0.1.0"
__all__ = ["ContentEngine", "PlatformFormatter", "MediaGenerator"]