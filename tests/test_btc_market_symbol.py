"""Batch 172 — BTC symbol map only. No network, no broker, no other markets retuned."""

import unittest

from app import MARKET_SYMBOLS


def lookup(market):
    """Same normalization as /live-candles (upper) plus fetch_live_market_data (strip spaces)."""
    key = str(market).strip().upper().replace(" ", "")
    return MARKET_SYMBOLS.get(key)


class BtcMarketSymbolTests(unittest.TestCase):
    def test_crypto_aliases_map_to_btcusd_spot(self):
        for raw in ("Crypto", "CRYPTO", "crypto", "BTC/USD", "btc/usd", "BTCUSD", "BTC / USD"):
            self.assertEqual(lookup(raw), "BTC/USD", raw)

    def test_existing_markets_unchanged(self):
        self.assertEqual(MARKET_SYMBOLS["FOREX"], "EUR/USD")
        self.assertEqual(MARKET_SYMBOLS["GOLD"], "XAU/USD")
        self.assertEqual(MARKET_SYMBOLS["NASDAQ"], "QQQ")
        self.assertEqual(MARKET_SYMBOLS["DOWJONES"], "DIA")
        self.assertEqual(MARKET_SYMBOLS["NATURALGAS"], "NG")
        self.assertEqual(MARKET_SYMBOLS["FUTURES"], "SPY")

    def test_unknown_market_still_unmapped(self):
        self.assertIsNone(lookup("ETH"))
        self.assertIsNone(lookup("ETHUSD"))


if __name__ == "__main__":
    unittest.main()
