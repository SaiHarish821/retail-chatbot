"""
Voice Filler Audio System

Pre-renders short filler phrases using Azure TTS at server startup,
so the caller isn't left in silence while the agent composes its answer.

Adapted from the reference implementation (53Karthik/vl). The fillers use
the SAME Azure voice as Voice Live, so they're indistinguishable from the
agent's own speech. Each "tree" is an ordered escalation spoken across a
long wait: the 1st line acknowledges, the middle lines show progress, the
last reassures. Short "thinking" sounds are sprinkled between steps for a
natural, human feel.

The filler clips are served to the browser via /api/fillers as base64 PCM16
24kHz audio. The browser handles the timing and playback.
"""

import os
import logging
import base64
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# ── Filler phrase definitions ──────────────────────────────────────────────

# Each "tree" is an ordered escalation sequence. One tree is chosen per wait
# so the structure never repeats turn-to-turn.
FILLER_TREES = [
    [
        "Alright, let me check that for you.",
        "Searching our system now.",
        "Almost there, give me a moment.",
        "Okay, just pulling it all together.",
    ],
    [
        "Sure, let me look into this for you.",
        "Going through the details now.",
        "Bear with me, nearly got it.",
        "Right, just finalising your answer.",
    ],
    [
        "Good question, let me dig into that.",
        "Checking my sources on this.",
        "Hold on, piecing it together.",
        "Nearly there, thanks for your patience.",
    ],
    [
        "Okay, give me a second on that.",
        "Looking through our records.",
        "Just making sure I get this right.",
        "Almost ready with your answer.",
    ],
    [
        "Let me find that for you.",
        "Pulling up the relevant info.",
        "A few more seconds, hang tight.",
        "Right, putting the answer together now.",
    ],
]

# Short interjections sprinkled between tree steps.
FILLER_THINKING = [
    "Hmm...",
    "Mmm, let me see...",
    "Uh, one moment...",
    "Hmm, okay...",
    "Let me think...",
    "Right...",
]


def _synthesize_pcm(text: str, token: str, endpoint: str, voice_name: str) -> str:
    """Render `text` to base64 PCM16 24 kHz using the same voice as Voice Live."""
    ssml = (
        f"<speak version='1.0' xml:lang='en-US'>"
        f"<voice name='{voice_name}'>{text}</voice></speak>"
    )
    url = endpoint.rstrip("/") + "/tts/cognitiveservices/v1"
    req = urllib.request.Request(url, data=ssml.encode("utf-8"), method="POST")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Content-Type", "application/ssml+xml")
    req.add_header("X-Microsoft-OutputFormat", "raw-24khz-16bit-mono-pcm")
    req.add_header("User-Agent", "retail-chatbot-filler")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return base64.b64encode(resp.read()).decode("utf-8")


def render_filler_clips(credential, endpoint: str, voice_name: str):
    """Pre-render all filler phrases to base64 PCM16 clips.
    
    Returns (tree_clips, thinking_clips) where:
    - tree_clips: list of lists of base64 audio strings (one list per tree)
    - thinking_clips: list of base64 audio strings
    
    Returns ([], []) if synthesis fails (fillers disabled gracefully).
    """
    try:
        tts_token = credential.get_token("https://cognitiveservices.azure.com/.default").token
        tree_phrases = [p for tree in FILLER_TREES for p in tree]
        all_phrases = tree_phrases + FILLER_THINKING
        
        # Render in parallel so startup stays fast despite the larger phrase set.
        with ThreadPoolExecutor(max_workers=10) as ex:
            clips = list(ex.map(
                lambda p: _synthesize_pcm(p, tts_token, endpoint, voice_name),
                all_phrases
            ))
        
        flat = iter(clips[:len(tree_phrases)])
        tree_clips = [[next(flat) for _ in tree] for tree in FILLER_TREES]
        thinking_clips = clips[len(tree_phrases):]
        
        logger.info(
            f"[VoiceFillers] Pre-rendered {len(FILLER_TREES)} filler trees "
            f"+ {len(thinking_clips)} thinking clips"
        )
        return tree_clips, thinking_clips
        
    except Exception as e:
        logger.warning(f"[VoiceFillers] Filler synthesis failed (fillers disabled): {repr(e)}")
        return [], []
