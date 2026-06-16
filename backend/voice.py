"""
Voice transcription using Azure Communication Services (Speech SDK).
The endpoint accepts a WAV audio blob and returns the transcript string.
"""

import os
import asyncio

import azure.cognitiveservices.speech as speechsdk


async def transcribe_audio(file_path: str) -> str:
    """
    Transcribe a WAV file using Azure Cognitive Services Speech SDK.
    Runs the synchronous SDK call in a thread pool to avoid blocking the event loop.
    """
    speech_key = os.getenv("AZURE_SPEECH_KEY", "")
    speech_region = os.getenv("AZURE_SPEECH_REGION", "eastus")

    if not speech_key:
        raise RuntimeError(
            "AZURE_SPEECH_KEY is not set. "
            "Add your Azure Communication Services speech key to .env"
        )

    loop = asyncio.get_event_loop()
    transcript = await loop.run_in_executor(
        None, _transcribe_sync, file_path, speech_key, speech_region
    )
    return transcript


def _transcribe_sync(file_path: str, speech_key: str, region: str) -> str:
    """Blocking transcription call – runs inside a thread pool."""
    speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=region)
    speech_config.speech_recognition_language = "en-GB"

    audio_config = speechsdk.AudioConfig(filename=file_path)
    recogniser = speechsdk.SpeechRecognizer(
        speech_config=speech_config,
        audio_config=audio_config,
    )

    result = recogniser.recognize_once_async().get()

    if result.reason == speechsdk.ResultReason.RecognizedSpeech:
        return result.text.strip()

    if result.reason == speechsdk.ResultReason.NoMatch:
        return ""

    if result.reason == speechsdk.ResultReason.Canceled:
        details = speechsdk.CancellationDetails.from_result(result)
        raise RuntimeError(
            f"Speech recognition cancelled: {details.reason} – {details.error_details}"
        )

    return ""
