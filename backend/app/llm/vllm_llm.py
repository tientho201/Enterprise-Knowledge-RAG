"""vLLM LLM implementation — Phase 2 (local Llama-3 inference)."""
from collections.abc import AsyncIterator

import httpx

from app.llm.base import BaseLLM


class VLLMLLM(BaseLLM):
    """Connects to a running vLLM OpenAI-compatible server."""

    def __init__(self, base_url: str = "http://localhost:8001/v1", model: str = "meta-llama/Meta-Llama-3-8B-Instruct"):
        self.base_url = base_url
        self.model = model
        self.client = httpx.AsyncClient(base_url=base_url, timeout=120.0)

    async def chat(
        self,
        messages: list[dict],
        temperature: float | None = 0.1,
        max_tokens: int | None = 2048,
    ) -> str:
        response = await self.client.post(
            "/chat/completions",
            json={
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    async def stream_chat(
        self,
        messages: list[dict],
        temperature: float | None = 0.1,
        max_tokens: int | None = 2048,
    ) -> AsyncIterator[str]:
        async with self.client.stream(
            "POST",
            "/chat/completions",
            json={
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
            },
        ) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    import json
                    data = json.loads(line[6:])
                    delta = data["choices"][0]["delta"].get("content", "")
                    if delta:
                        yield delta

    async def embed(self, texts: list[str]) -> list[list[float]]:
        response = await self.client.post("/embeddings", json={"model": self.model, "input": texts})
        response.raise_for_status()
        return [item["embedding"] for item in response.json()["data"]]
