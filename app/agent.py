from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

from . import metrics
from .mock_llm import FakeLLM, FakeResponse
from .mock_rag import retrieve
from .pii import hash_user_id, scrub_text, summarize_text
from .tracing import langfuse_context, observe


@dataclass
class AgentResult:
    answer: str
    latency_ms: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    quality_score: float
    cache_hit: bool


class LabAgent:
    def __init__(self, model: str = "claude-sonnet-4-5") -> None:
        self.model = model
        self.llm = FakeLLM(model=model)
        # Cost-optimization: cache LLM responses by prompt so repeated
        # questions (common in chat support / FAQ-style traffic) skip the
        # billable LLM call entirely. See docs/blueprint-template.md bonus
        # section for measured before/after savings.
        self._response_cache: dict[str, FakeResponse] = {}

    @observe(capture_input=False, capture_output=False)
    def run(self, user_id: str, feature: str, session_id: str, message: str) -> AgentResult:
        started = time.perf_counter()
        docs = retrieve(message)
        prompt = f"Feature={feature}\nDocs={docs}\nQuestion={message}"
        cache_key = hashlib.sha256(prompt.encode("utf-8")).hexdigest()

        cache_hit = cache_key in self._response_cache
        if cache_hit:
            response = self._response_cache[cache_key]
        else:
            response = self.llm.generate(prompt)
            self._response_cache[cache_key] = response

        quality_score = self._heuristic_quality(message, response.text, docs)
        latency_ms = int((time.perf_counter() - started) * 1000)
        full_cost_usd = self._estimate_cost(response.usage.input_tokens, response.usage.output_tokens)
        cost_usd = 0.0 if cache_hit else full_cost_usd

        langfuse_context.update_current_trace(
            user_id=hash_user_id(user_id),
            session_id=session_id,
            tags=["lab", feature, self.model],
        )
        langfuse_context.update_current_observation(
            input={"message": scrub_text(message)},
            output={"answer": scrub_text(response.text)},
            metadata={"doc_count": len(docs), "query_preview": summarize_text(message), "cache_hit": cache_hit},
            usage_details={
                "input": 0 if cache_hit else response.usage.input_tokens,
                "output": 0 if cache_hit else response.usage.output_tokens,
            },
        )

        if cache_hit:
            metrics.record_cache_hit(full_cost_usd)

        metrics.record_request(
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            tokens_in=0 if cache_hit else response.usage.input_tokens,
            tokens_out=0 if cache_hit else response.usage.output_tokens,
            quality_score=quality_score,
        )

        return AgentResult(
            answer=response.text,
            latency_ms=latency_ms,
            tokens_in=0 if cache_hit else response.usage.input_tokens,
            tokens_out=0 if cache_hit else response.usage.output_tokens,
            cost_usd=cost_usd,
            quality_score=quality_score,
            cache_hit=cache_hit,
        )

    def _estimate_cost(self, tokens_in: int, tokens_out: int) -> float:
        input_cost = (tokens_in / 1_000_000) * 3
        output_cost = (tokens_out / 1_000_000) * 15
        return round(input_cost + output_cost, 6)

    def _heuristic_quality(self, question: str, answer: str, docs: list[str]) -> float:
        score = 0.5
        if docs:
            score += 0.2
        if len(answer) > 40:
            score += 0.1
        if question.lower().split()[0:1] and any(token in answer.lower() for token in question.lower().split()[:3]):
            score += 0.1
        if "[REDACTED" in answer:
            score -= 0.2
        return round(max(0.0, min(1.0, score)), 2)
