import os
import logging
import re
from azure.communication.identity import CommunicationIdentityClient, CommunicationTokenScope
from azure.communication.callautomation import (
    CallAutomationClient,
    TextSource,
    CommunicationUserIdentifier,
    RecognizeInputType
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
        Answers an incoming call and directs it to the callback URL.
        """
        if not self.call_automation_client:
            raise RuntimeError("ACS Call Automation Client is not initialized.")
        
        callback_uri = f"{self.public_callback_url}/api/callback"
        cog_endpoint = os.getenv("COGNITIVE_SERVICES_ENDPOINT", "").strip()
        if not cog_endpoint:
            cog_endpoint = f"https://{self.speech_region}.api.cognitive.microsoft.com"
        else:
            cog_endpoint = cog_endpoint.rstrip("/")
            
        logger.info(f"Answering call. Callback: {callback_uri} | Speech Endpoint: {cog_endpoint}")
        
        answer_result = self.call_automation_client.answer_call(
            incoming_call_context=incoming_call_context,
            callback_url=callback_uri,
            cognitive_services_endpoint=cog_endpoint
        )
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
            
            logger.info(f"Received ACS Event: {event_type} for Call: {call_connection_id} (Server Call: {server_call_id})")
            
            if not call_connection_id or not self.call_automation_client:
                continue

            if server_call_id and server_call_id not in self.active_calls:
                self.active_calls[server_call_id] = {
                    "user_transcript": "Waiting for speech...",
                    "ai_response": "Connecting...",
                    "status": "CONNECTING",
                    "history": []
                }

            call_connection_client = self.call_automation_client.get_call_connection(call_connection_id)
            
            if event_type == "Microsoft.Communication.CallConnected":
                logger.info(f"Call Connected. Playing greeting and starting recognition...")
                greeting_text = "Hello, I am your Sainsbury's virtual assistant. How can I help you today?"
                
                if server_call_id:
                    self.active_calls[server_call_id]["ai_response"] = greeting_text
                    self.active_calls[server_call_id]["status"] = "SPEAKING"
                    self.active_calls[server_call_id]["history"] = [
                        {"role": "assistant", "content": greeting_text}
                    ]
                
                await self._speak_and_recognize(
                    call_connection_client,
                    text=greeting_text
                )

            elif event_type == "Microsoft.Communication.RecognizeCompleted":
                logger.info("Speech recognition completed successfully.")
                speech_text = (
                    event_data.get("speechResult", {}).get("speech")
                    or event_data.get("speechResult", {}).get("text")
                    or ""
                ).strip()
                logger.info(f"User Said: {speech_text}")
                
                if server_call_id:
                    self.active_calls[server_call_id]["user_transcript"] = speech_text
                    self.active_calls[server_call_id]["status"] = "PROCESSING"
                
                if not speech_text:
                    reprompt_text = "I didn't hear anything. Could you please repeat that?"
                    if server_call_id:
                        self.active_calls[server_call_id]["ai_response"] = reprompt_text
                        self.active_calls[server_call_id]["status"] = "SPEAKING"
                        if "history" not in self.active_calls[server_call_id]:
                            self.active_calls[server_call_id]["history"] = []
                        self.active_calls[server_call_id]["history"].append({"role": "assistant", "content": reprompt_text})
                    await self._speak_and_recognize(
                        call_connection_client,
                        text=reprompt_text
                    )
                    continue

                # Query agent router to get reply
                try:
                    # In a telephone session we can maintain context memory
                    history = self.active_calls[server_call_id].get("history", []) if server_call_id else []
                    result = await agent_router.handle(message=speech_text, history=history, is_voice=True)
                    reply_text = result.get("reply", "I am sorry, I did not catch that.")
                except Exception as e:
                    logger.error(f"Error in AgentRouter: {e}")
                    reply_text = "I am sorry, I am having trouble connecting to my service right now."

                if server_call_id:
                    if "history" not in self.active_calls[server_call_id]:
                        self.active_calls[server_call_id]["history"] = []
                    self.active_calls[server_call_id]["history"].append({"role": "user", "content": speech_text})
                    self.active_calls[server_call_id]["history"].append({"role": "assistant", "content": reply_text})
                    self.active_calls[server_call_id]["ai_response"] = reply_text
                    
                    # Store intent and suggestions to expose via status polling endpoint
                    self.active_calls[server_call_id]["intent"] = result.get("intent", "general") if isinstance(result, dict) else "general"
                    self.active_calls[server_call_id]["suggestions"] = result.get("suggestions", []) if isinstance(result, dict) else []
                    self.active_calls[server_call_id]["status"] = "SPEAKING"

                # Sanitize prompt for TTS
                tts_text = sanitize_text_for_tts(reply_text)
                logger.info(f"Playing sanitized TTS prompt: '{tts_text}'")

                # Play response and listen for next turn
                await self._speak_and_recognize(
                    call_connection_client,
                    text=tts_text
                )

            elif event_type == "Microsoft.Communication.RecognizeFailed":
                result_info = event_data.get("resultInformation", {})
                sub_code = result_info.get("subCode")
                msg = result_info.get("message")
                logger.warning(f"Speech recognition failed (subCode={sub_code}, message={msg}). Full data: {event_data}")
                # Reprompt the user and listen again
                reprompt_text = "I'm sorry, I didn't catch that. Could you repeat it?"
                if server_call_id:
                    self.active_calls[server_call_id]["ai_response"] = reprompt_text
                    self.active_calls[server_call_id]["status"] = "SPEAKING"
                    if "history" not in self.active_calls[server_call_id]:
                        self.active_calls[server_call_id]["history"] = []
                    self.active_calls[server_call_id]["history"].append({"role": "assistant", "content": reprompt_text})
                await self._speak_and_recognize(
                    call_connection_client,
                    text=reprompt_text
                )

            elif event_type == "Microsoft.Communication.PlayStarted":
                logger.info("Prompt playback started. Setting status to SPEAKING.")
                if server_call_id:
                    self.active_calls[server_call_id]["status"] = "SPEAKING"

            elif event_type in ["Microsoft.Communication.PlayCompleted", "Microsoft.Communication.PlayFailed"]:
                logger.info(f"Prompt playback finished/failed ({event_type}). Setting status to LISTENING.")
                if server_call_id:
                    self.active_calls[server_call_id]["status"] = "LISTENING"
                
            elif event_type == "Microsoft.Communication.CallDisconnected":
                logger.info("Call disconnected. Cleaning up.")
                if server_call_id:
                    self.active_calls[server_call_id]["status"] = "DISCONNECTED"

    async def _speak_and_recognize(self, call_connection_client, text: str):
        """
        Play text response to all participants and start speech recognition on the caller.
        """
        try:
            # Get the caller identifier
            props = call_connection_client.get_call_properties()
            caller = None
            
            # 1. Try checking targets (filtering out the bot user ID)
            if props.targets:
                for target in props.targets:
                    t_id = target.properties.get("id") if hasattr(target, "properties") and target.properties else getattr(target, "raw_id", None)
                    if t_id and t_id != self.bot_user_id:
                        caller = target
                        break

            # 2. Try checking call_source
            if not caller and hasattr(props, "call_source") and props.call_source:
                src_identifier = getattr(props.call_source, "identifier", None)
                if src_identifier:
                    src_id = src_identifier.properties.get("id") if hasattr(src_identifier, "properties") and src_identifier.properties else getattr(src_identifier, "raw_id", None)
                    if src_id and src_id != self.bot_user_id:
                        caller = src_identifier

            # 3. Fallback: list participants to locate the caller
            if not caller:
                participants = call_connection_client.list_participants()
                for p in participants:
                    p_id = p.identifier.properties.get("id") if hasattr(p.identifier, "properties") and p.identifier.properties else getattr(p.identifier, "raw_id", None)
                    if p_id and p_id != self.bot_user_id:
                        caller = p.identifier
                        break

            if caller:
                # Define prompt TextSource using high quality Azure Neural voice
                play_prompt = TextSource(text=text, voice_name="en-GB-SoniaNeural")
                
                # Start speech recognition which handles prompt playback & barge-in interruption
                call_connection_client.start_recognizing_media(
                    input_type=RecognizeInputType.SPEECH,
                    target_participant=caller,
                    play_prompt=play_prompt,
                    interrupt_prompt=True,
                    speech_language="en-GB",
                    initial_silence_timeout=10,
                    end_silence_timeout=2
                )
                logger.info(f"Started speak_and_recognize: '{text}' -> caller {getattr(caller, 'raw_id', 'unknown')}")
            else:
                logger.error("Could not find a valid caller identifier to play media and recognize speech.")
        except Exception as e:
            logger.error(f"Failed to play and recognize media: {e}")
