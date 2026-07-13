"""
Retail AI Assistant – Centralized Azure AI Foundry Configuration
"""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class AgentNames:
    """
    Maps each logical agent role to the exact name configured in AI Foundry Portal.
    Names are read from environment variables so they can be changed without code edits.
    """
    order:      str = field(default_factory=lambda: os.getenv("AZURE_AGENT_ORDER_NAME",      "Order-Agent"))
    delivery:   str = field(default_factory=lambda: os.getenv("AZURE_AGENT_DELIVERY_NAME",   "Delivery-Agent"))
    refund:     str = field(default_factory=lambda: os.getenv("AZURE_AGENT_REFUND_NAME",     "Refund-Agent"))
    store:      str = field(default_factory=lambda: os.getenv("AZURE_AGENT_STORE_NAME",      "Store-Agent"))
    general:    str = field(default_factory=lambda: os.getenv("AZURE_AGENT_GENERAL_NAME",    "General-Assistant-Agent"))
    intent_classifier: str = field(default_factory=lambda: os.getenv("AZURE_AGENT_INTENT_NAME", "Intent-Classifier-Agent"))
    context_resolver:  str = field(default_factory=lambda: os.getenv("AZURE_AGENT_CONTEXT_NAME",  "Context-Resolver-Agent"))
    suggestions:        str = field(default_factory=lambda: os.getenv("AZURE_AGENT_SUGGESTIONS_NAME", "Suggestions-Agent"))
    voice_assistant:   str = field(default_factory=lambda: os.getenv("AZURE_AGENT_VOICE_NAME",   "Voice-Assistant-Agent"))

    def as_dict(self) -> dict[str, str]:
        """Returns a mapping of role -> agent_name for resolution lookups."""
        return {
            "order":      self.order,
            "delivery":   self.delivery,
            "refund":     self.refund,
            "store":      self.store,
            "general":    self.general,
            "intent_classifier": self.intent_classifier,
            "context_resolver":  self.context_resolver,
            "suggestions":        self.suggestions,
            "voice_assistant":   self.voice_assistant,
        }


@dataclass(frozen=True)
class FoundryConfig:
    """
    Single source of truth for all Azure AI Foundry configuration.

    Usage:
        from .foundry_config import config
        endpoint = config.project_endpoint
        deployment = config.deployment_name
    """

    # ── Azure AI Foundry Project ───────────────────────────────────────────────
    # Format: https://<hub-name>.services.ai.azure.com/api/projects/<project-name>
    # Copied from: AI Foundry Portal -> Project -> Overview -> "Project endpoint"
    project_endpoint: str = field(
        default_factory=lambda: os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "").strip()
    )

    # API key for authenticating without Azure CLI / Managed Identity
    # Copied from: AI Foundry Portal -> Project -> Overview -> "API key"
    api_key: str = field(
        default_factory=lambda: os.getenv("AZURE_AI_FOUNDRY_API_KEY", "").strip()
    )

    # ── Azure OpenAI ──────────────────────────────────────────────────────────
    # Used for fast classification calls (domain, intent, guardrail, suggestions)
    # Format: https://<resource>.cognitiveservices.azure.com/openai/v1
    openai_endpoint: str = field(
        default_factory=lambda: os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    )

    # Must exactly match the deployment name in Models + Endpoints
    # Model: gpt-5.1 | Version: 2025-11-13 | GA | 400k context | 128k output
    deployment_name: str = field(
        default_factory=lambda: os.getenv("AZURE_AI_FOUNDRY_DEPLOYMENT_NAME", "gpt-5.1").strip()
    )

    # Voice fast-path deployment — used by _call_voice_openai() only.
    # Falls back to deployment_name if not set, so no code change is needed
    # when a mini variant is not yet available.
    voice_deployment_name: str = field(
        default_factory=lambda: (
            os.getenv("AZURE_OPENAI_VOICE_DEPLOYMENT_NAME", "").strip()
            or os.getenv("AZURE_AI_FOUNDRY_DEPLOYMENT_NAME", "gpt-5.1").strip()
        )
    )

    # ── Azure Tenant ──────────────────────────────────────────────────────────
    tenant_id: str = field(
        default_factory=lambda: (os.getenv("AZURE_TENANT_ID", "").strip() or "")
    )

    # ── Agent Names ───────────────────────────────────────────────────────────
    agent_names: AgentNames = field(default_factory=AgentNames)

    # ── Derived properties ────────────────────────────────────────────────────

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    @property
    def has_project_endpoint(self) -> bool:
        return bool(self.project_endpoint)

    @property
    def has_openai_endpoint(self) -> bool:
        return bool(self.openai_endpoint)

    @property
    def is_new_foundry_format(self) -> bool:
        """
        Returns True if the project endpoint uses the new AI Foundry format
        (services.ai.azure.com) rather than the old Azure ML format (api.azureml.ms).
        """
        return "services.ai.azure.com" in self.project_endpoint

    def validate(self) -> list[str]:
        """
        Returns a list of configuration warnings. Empty list = all good.
        Call this at startup to surface configuration issues in logs.
        """
        warnings = []

        if not self.project_endpoint:
            warnings.append(
                "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT is not set. "
                "Foundry agents will be unavailable -- all calls will fall back to direct OpenAI."
            )
        elif not self.is_new_foundry_format:
            warnings.append(
                f"AZURE_AI_FOUNDRY_PROJECT_ENDPOINT appears to use the old Azure ML format "
                f"({self.project_endpoint[:60]}). "
                "Expected format: https://<hub>.services.ai.azure.com/api/projects/<project>. "
                "Update this value after creating your AI Foundry Hub + Project in Azure Portal."
            )

        if not self.api_key:
            warnings.append(
                "AZURE_AI_FOUNDRY_API_KEY is not set. "
                "Authentication will fall back to AzureCliCredential (local only) "
                "or DefaultAzureCredential (serverless). "
                "Set this for reliable authentication in all environments."
            )

        if not self.openai_endpoint:
            warnings.append(
                "AZURE_OPENAI_ENDPOINT is not set. "
                "Domain/intent classification and suggestion generation will be skipped. "
                "All queries will use keyword-based routing only."
            )

        return warnings


# ── Singleton instance ─────────────────────────────────────────────────────────
# Import this instead of calling FoundryConfig() repeatedly.
config = FoundryConfig()
