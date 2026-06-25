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


async def synthesize_speech(text: str) -> bytes:
    """
    Synthesize text to audio bytes (WAV) using Azure Neural Voices (en-GB-SoniaNeural).
    """
    speech_key = os.getenv("AZURE_SPEECH_KEY", "")
    speech_region = os.getenv("AZURE_SPEECH_REGION", "eastus")

    if not speech_key:
        raise RuntimeError(
            "AZURE_SPEECH_KEY is not set. "
            "Add your Azure Communication Services speech key to .env"
        )

    loop = asyncio.get_event_loop()
    audio_data = await loop.run_in_executor(
        None, _synthesize_sync, text, speech_key, speech_region
    )
    return audio_data


def _synthesize_sync(text: str, speech_key: str, region: str) -> bytes:
    """Blocking speech synthesis call – runs inside a thread pool."""
    speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=region)
    speech_config.speech_synthesis_voice_name = "en-GB-SoniaNeural"

    # Pass audio_config=None to synthesize to memory stream (result.audio_data)
    # without trying to play to a speaker (which causes errors on servers)
    synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=speech_config,
        audio_config=None,
    )
    result = synthesizer.speak_text_async(text).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return result.audio_data

    if result.reason == speechsdk.ResultReason.Canceled:
        details = speechsdk.SpeechSynthesisCancellationDetails.from_result(result)
        raise RuntimeError(
            f"Speech synthesis cancelled: {details.reason} – {details.error_details}"
        )

    raise RuntimeError("Speech synthesis failed.")

