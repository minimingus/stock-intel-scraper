import requests


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self._chat_id = chat_id

    def send(self, text: str) -> None:
        requests.post(
            self._url,
            json={"chat_id": self._chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )

    def send_trade_alert(
        self,
        question: str,
        action: str,
        amount_usdc: float,
        confidence: float,
        reasoning: str,
        dry_run: bool,
    ) -> None:
        prefix = "[DRY RUN] " if dry_run else ""
        side = "YES" if action == "BUY_YES" else "NO"
        self.send(
            f"{prefix}*Trade Alert*\n"
            f"Market: {question}\n"
            f"Action: BUY {side}\n"
            f"Amount: ${amount_usdc:.2f}\n"
            f"Confidence: {confidence:.0%}\n"
            f"Reason: {reasoning}"
        )

    def send_cycle_summary(
        self,
        markets_analyzed: int,
        bets_placed: int,
        total_usdc: float,
        dry_run: bool,
    ) -> None:
        prefix = "[DRY RUN] " if dry_run else ""
        self.send(
            f"{prefix}*Cycle Summary*\n"
            f"Markets analyzed: {markets_analyzed}\n"
            f"Bets placed: {bets_placed}\n"
            f"Total wagered: ${total_usdc:.2f}"
        )
