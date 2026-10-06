"""Model providers (neutrality by construction).

Every provider is an adapter. `echo` is the offline default; hosted providers are
gated on `AGENTFOX_ALLOW_EGRESS` so nothing leaves a regulated boundary by accident.
"""

from agentfox.providers.base import (
    CompletionRequest,
    CompletionResponse,
    ModelProvider,
    all_providers,
    available_providers,
    get_provider,
    register_provider,
)
from agentfox.providers.echo import EchoProvider, clear_scripts, script
from agentfox.providers.enterprise import (
    AzureOpenAIProvider,
    BedrockProvider,
    LiteLLMProvider,
    VertexProvider,
)
from agentfox.providers.remote import AnthropicProvider, OpenAIProvider, estimate_cost

__all__ = [
    "AnthropicProvider",
    "AzureOpenAIProvider",
    "BedrockProvider",
    "LiteLLMProvider",
    "VertexProvider",
    "CompletionRequest",
    "CompletionResponse",
    "EchoProvider",
    "ModelProvider",
    "OpenAIProvider",
    "all_providers",
    "available_providers",
    "clear_scripts",
    "estimate_cost",
    "get_provider",
    "register_provider",
    "script",
]
