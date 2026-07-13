import os
import logging
import re
import time
import json
from azure.communication.identity import CommunicationIdentityClient, CommunicationTokenScope
from azure.communication.callautomation import (
    CallAutomationClient,
    TextSource,
    CommunicationUserIdentifier,
    RecognizeInputType,
    MediaStreamingOptions,
    StreamingTransportType,
    MediaStreamingContentType,
    MediaStreamingAudioChannelType
)

logger = logging.getLogger(__name__)

def sanitize_text_for_tts(text: str) -> str:
    if not text:
        return ""
    # 1. Remove product-grid tags and content
    text = re.sub(r'<product-grid>.*?</product-grid>', '', text, flags=re.DOTALL)
    # 2. Remove other XML or HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # 3. Clean up customer IDs and store IDs
    text = re.sub(r'\bCUST-\d+\b', '', text)
    text = re.sub(r'\bSTR-\d+\b', '', text)
    # 4. Standardize quotes
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    # 5. Remove markdown formatting
    text = text.replace("**", "").replace("*", "").replace("_", "").replace("`", "")
    # 6. Remove bullet symbols and dash bullet points
    text = re.sub(r'^\s*[•\-*]\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n\s*[•\-*]\s*', ' ', text)
    text = text.replace("•", " ").replace("–", " ").replace("—", " ")
    # 7. Remove non-ASCII characters (e.g. emojis)
    text = re.sub(r'[^\x00-\x7F]+', ' ', text)
    # 8. Normalize space
    text = re.sub(r'\s+', ' ', text).strip()
    return text

class ACSBotManager:
    def __init__(self):
        self.active_calls = {}
        self.connection_string = os.getenv("ACS_CONNECTION_STRING", "")
        self.public_callback_url = os.getenv("PUBLIC_CALLBACK_URL", "")
        self.speech_region = os.getenv("AZURE_SPEECH_REGION", "eastus")
        
        if not self.connection_string:
            logger.warning("ACS_CONNECTION_STRING is not set in .env")
            self.call_automation_client = None
            self.identity_client = None
            self.bot_user_id = None
            return

        self.call_automation_client = CallAutomationClient.from_connection_string(self.connection_string)
        self.identity_client = CommunicationIdentityClient.from_connection_string(self.connection_string)
        
        # Load or generate bot identity
        self.bot_user_id = os.getenv("ACS_BOT_IDENTITY", "")
        if not self.bot_user_id:
            try:
                # Create a persistent user identity for the bot
                user = self.identity_client.create_user()
                self.bot_user_id = user.properties["id"]
                logger.info(f"Dynamically generated ACS Bot Identity: {self.bot_user_id}")
            except Exception as e:
                logger.error(f"Failed to generate ACS Bot Identity: {e}")

    def get_token_for_user(self) -> dict:
        """
        Creates a new user identity and issues an access token for VOIP calls.
        """
        if not self.identity_client:
            raise RuntimeError("ACS Identity Client is not initialized.")
        
        user_and_token = self.identity_client.create_user_and_token(
            scopes=[CommunicationTokenScope.VOIP]
        )
        user_id = user_and_token[0].properties["id"]
        token = user_and_token[1].token
        expires_on = user_and_token[1].expires_on
        
        return {
            "token": token,
            "user_id": user_id,
            "bot_user_id": self.bot_user_id,
            "expires_on": expires_on.isoformat() if hasattr(expires_on, "isoformat") else expires_on
        }

    async def answer_incoming_call(self, incoming_call_context: str):
        """
        Answers an incoming call and directs it to the callback URL, configuring bidirectional media streaming.
        """
        if not self.call_automation_client:
            raise RuntimeError("ACS Call Automation Client is not initialized.")
        
        callback_uri = f"{self.public_callback_url}/api/callback"
        
        # Configure Media Streaming Options pointing to the media stream WebSocket
        ws_url = self.public_callback_url.replace("https://", "wss://").replace("http://", "ws://") + "/api/media-stream"
        media_streaming_options = MediaStreamingOptions(
            transport_url=ws_url,
            transport_type=StreamingTransportType.WEBSOCKET,
            content_type=MediaStreamingContentType.AUDIO,
            audio_channel_type=MediaStreamingAudioChannelType.MIXED,
            start_media_streaming=True
        )
        
        logger.info(f"[ACSBot] Answering incoming call. Callback: {callback_uri} | Media Streaming WS: {ws_url}")
        
        answer_result = self.call_automation_client.answer_call(
            incoming_call_context=incoming_call_context,
            callback_url=callback_uri,
            media_streaming=media_streaming_options
        )
        logger.info(f"[ACSBot] Call answered successfully. Connection ID: {answer_result.call_connection_id}")
        return answer_result

    async def handle_callback_events(self, events: list, agent_router):
        """
        Processes events received from Call Automation.
        """
        for event in events:
            event_type = event.get("type")
            event_data = event.get("data", {})
            call_connection_id = event_data.get("callConnectionId")
            server_call_id = event_data.get("serverCallId")
            
            logger.info(f"[ACSBot] Received Event: {event_type} | Connection: {call_connection_id} | ServerCall: {server_call_id}")
            
            if not call_connection_id or not self.call_automation_client:
                continue

            if server_call_id and server_call_id not in self.active_calls:
                self.active_calls[server_call_id] = {
                    "user_transcript": "Waiting for speech...",
                    "ai_response": "Connecting...",
                    "status": "CONNECTING",
                    "history": []
                }
            
            if event_type == "Microsoft.Communication.CallConnected":
                logger.info(f"[ACSBot] Call Connected. Media streaming has been started.")
                if server_call_id:
                    self.active_calls[server_call_id]["status"] = "LISTENING"

            elif event_type == "Microsoft.Communication.CallDisconnected":
                logger.info("Call disconnected. Cleaning up.")
                if server_call_id:
                    self.active_calls[server_call_id]["status"] = "DISCONNECTED"

