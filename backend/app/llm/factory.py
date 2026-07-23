import os
from functools import lru_cache

from app.llm.base import BaseLLM


@lru_cache
def get_llm() -> BaseLLM:
    """
    Factory that returns the correct LLM implementation based on env config.
    Phase 1: OpenAI GPT-4o-mini
    Phase 2: vLLM with Llama-3 (set LLM_PROVIDER=vllm)
    """
    provider = os.getenv("LLM_PROVIDER", "openai").lower()

    if provider == "openai":
        from app.llm.openai_llm import OpenAILLM

        return OpenAILLM()
    # elif provider == "vllm":
    #     from app.llm.vllm_llm import VLLMLLM
    #     base_url = os.getenv("VLLM_BASE_URL", "http://localhost:8001/v1")
    #     model = os.getenv("VLLM_MODEL", "meta-llama/Meta-Llama-3-8B-Instruct")
    #     return VLLMLLM(base_url=base_url, model=model)
    else:
        raise ValueError(f"Unknown LLM provider: {provider}. Valid: openai, vllm")


def get_llm_for_request(
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> BaseLLM:
    """
    BYOM passthrough: nếu request kèm api_key riêng (panel Cấu hình → Model tùy chỉnh),
    dựng một OpenAI-compatible client tạm thời (không cache, không lưu key ở server) thay
    vì dùng get_llm() mặc định. base_url cho phép trỏ tới các endpoint OpenAI-compatible
    khác (Gemini, Groq, OpenRouter, vLLM tự host...). Không có api_key → luôn get_llm().
    """
    if not api_key:
        return get_llm()

    from app.llm.openai_llm import OpenAILLM

    return OpenAILLM(api_key=api_key, base_url=base_url, model=model)
