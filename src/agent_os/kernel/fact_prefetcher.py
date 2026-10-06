"""Deterministic entity matching and fact prefetching engine with token budget clamping."""

import re

from agent_os.domain.gateway import estimate_tokens
from agent_os.domain.memory import FactRecord, RecalledFactsPayload
from agent_os.infrastructure.storage.facts_repo import FactRepository


class FactPrefetcher:
    """Retrieves relevant facts for conversation turns and enforces prompt token budgets."""

    def __init__(
        self,
        facts_repo: FactRepository,
        token_ceiling: int = 300,
    ) -> None:
        self.facts_repo = facts_repo
        self.repo = facts_repo
        self.token_ceiling = token_ceiling
        self.char_ceiling = token_ceiling * 4

    def prefetch_for_turn(self, user_input: str) -> RecalledFactsPayload:
        """Tokenize input, retrieve matched entity facts, and render bounded XML block."""
        clean_text = re.sub(r"[^\w\s]", " ", user_input.lower())
        tokens = [t for t in clean_text.split() if t]

        user_aliases = {"user", "me", "i", "my"}
        candidate_keys: list[str] = []
        if any(t in user_aliases for t in tokens):
            candidate_keys.append("user")

        for token in tokens:
            if len(token) >= 3 and token not in candidate_keys:
                candidate_keys.append(token)

        matched_facts: list[FactRecord] = []
        seen_fact_ids: set[str] = set()

        for key in candidate_keys:
            for fact in self.repo.list_by_entity(key):
                if fact.fact_id not in seen_fact_ids:
                    seen_fact_ids.add(fact.fact_id)
                    matched_facts.append(fact)

        for search_result in self.repo.search_facts(user_input, limit=5):
            fact = search_result.fact
            if fact.fact_id not in seen_fact_ids:
                seen_fact_ids.add(fact.fact_id)
                matched_facts.append(fact)

        if not matched_facts:
            return RecalledFactsPayload(
                rendered_block="",
                recalled_count=0,
                token_estimate=0,
                matched_entity_keys=[],
            )

        included_facts: list[FactRecord] = []
        for fact in matched_facts:
            candidate_lines = [
                f"- [{f.entity_key}]: {f.fact_text}" for f in included_facts + [fact]
            ]
            candidate_block = "\n".join(["<recalled_facts>", *candidate_lines, "</recalled_facts>"])
            if estimate_tokens(candidate_block) <= self.token_ceiling:
                included_facts.append(fact)
            else:
                break

        if not included_facts:
            return RecalledFactsPayload(
                rendered_block="",
                recalled_count=0,
                token_estimate=0,
                matched_entity_keys=[],
            )

        fact_lines = [f"- [{f.entity_key}]: {f.fact_text}" for f in included_facts]
        rendered_block = "\n".join(["<recalled_facts>", *fact_lines, "</recalled_facts>"])
        token_estimate = estimate_tokens(rendered_block)
        matched_keys = list(dict.fromkeys(f.entity_key for f in included_facts))

        return RecalledFactsPayload(
            rendered_block=rendered_block,
            recalled_count=len(included_facts),
            token_estimate=token_estimate,
            matched_entity_keys=matched_keys,
        )
