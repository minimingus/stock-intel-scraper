import json
import anthropic

_SYSTEM_PROMPT = """\
You are a professional prediction market analyst on Polymarket.

Analyze the provided markets and decide which ones to bet on.
Respond ONLY with valid JSON matching this exact schema — no markdown, no extra text:

{
  "decisions": [
    {
      "condition_id": "<market condition_id from input>",
      "action": "BUY_YES" | "BUY_NO",
      "token_id": "<token_id for the chosen outcome>",
      "confidence": <float 0.0-1.0>,
      "amount_usdc": <float, suggested dollar amount>,
      "reasoning": "<one concise sentence>"
    }
  ]
}

Only include markets you want to bet on. Return {"decisions": []} if none qualify.
Be conservative — only bet where you have a clear informational edge.
"""


class MarketAnalyzer:
    def __init__(self, api_key: str):
        self._client = anthropic.Anthropic(api_key=api_key)

    def analyze(
        self, markets: list[dict], max_bet_usdc: float, min_confidence: float
    ) -> list[dict]:
        if not markets:
            return []

        user_msg = (
            f"Analyze these Polymarket markets. Max bet per market: ${max_bet_usdc}.\n\n"
            + json.dumps(markets, indent=2)
        )
        try:
            resp = self._client.messages.create(
                model="claude-opus-4-6",
                max_tokens=2048,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            data = json.loads(resp.content[0].text)
        except Exception:
            return []

        decisions = []
        for d in data.get("decisions", []):
            if d.get("confidence", 0) < min_confidence:
                continue
            d["amount_usdc"] = min(float(d.get("amount_usdc", 0)), max_bet_usdc)
            decisions.append(d)
        return decisions
