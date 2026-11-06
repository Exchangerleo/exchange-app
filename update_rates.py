#!/usr/bin/env python3
"""Обновляет rates.json свежими курсами. Только стандартная библиотека Python.

Фиат:   open.er-api.com (основной), Frankfurter / ЕЦБ (запасной).
Крипта: CoinGecko (основной), Binance data-api (запасной).

Запуск: python3 update_rates.py
Если какой-то курс получить не удалось, остаётся прежнее значение из rates.json.
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "rates.json")

# Валюты, которые нужны приложению (коды как в CONFIG.assets в index.html)
FIAT = ["UAH", "PLN", "CZK", "TRY", "MDL", "GEL", "AMD", "KZT", "AED", "RUB", "EUR", "GBP"]
CRYPTO = {  # код -> id в CoinGecko
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "TON": "the-open-network",
    "USDT": "tether",
    "USDC": "usd-coin",
}
BINANCE = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "TON": "TONUSDT"}

# Защита от мусора: новый курс не должен отличаться от прежнего сильнее этого
MAX_JUMP_FIAT = 0.25
MAX_JUMP_CRYPTO = 0.40


def fetch_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "rates-updater/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def log(msg):
    print(msg, file=sys.stderr)


def get_fiat():
    """Возвращает ({код: сколько единиц за 1 USD}, [использованные источники])."""
    got, used = {}, []
    try:
        d = fetch_json("https://open.er-api.com/v6/latest/USD")
        if d.get("result") == "success":
            for c in FIAT:
                v = d.get("rates", {}).get(c)
                if isinstance(v, (int, float)) and v > 0:
                    got[c] = float(v)
            used.append("open.er-api.com")
    except Exception as e:
        log("open.er-api.com: ошибка: %s" % e)

    missing = [c for c in FIAT if c not in got]
    if missing:
        try:
            d = fetch_json("https://api.frankfurter.dev/v1/latest?base=USD&symbols=" + ",".join(missing))
            for c, v in d.get("rates", {}).items():
                if isinstance(v, (int, float)) and v > 0:
                    got[c] = float(v)
            used.append("frankfurter.dev (ECB)")
        except Exception as e:
            log("frankfurter.dev: ошибка: %s" % e)
    return got, used


def get_crypto():
    """Возвращает ({код: цена в USD}, [использованные источники])."""
    got, used = {}, []
    try:
        ids = ",".join(CRYPTO.values())
        d = fetch_json("https://api.coingecko.com/api/v3/simple/price?vs_currencies=usd&ids=" + ids)
        for code, cid in CRYPTO.items():
            v = d.get(cid, {}).get("usd")
            if isinstance(v, (int, float)) and v > 0:
                got[code] = float(v)
        used.append("coingecko.com")
    except Exception as e:
        log("coingecko.com: ошибка: %s" % e)

    for code, sym in BINANCE.items():
        if code in got:
            continue
        try:
            d = fetch_json("https://data-api.binance.vision/api/v3/ticker/price?symbol=" + sym)
            v = float(d["price"])
            if v > 0:
                got[code] = v
                if "binance.vision" not in used:
                    used.append("data-api.binance.vision")
        except Exception as e:
            log("binance %s: ошибка: %s" % (sym, e))
    return got, used


def accept(code, new, old, limit):
    """Принять новое значение, если оно не нарушает защиту от скачков."""
    if not old:
        return True
    if abs(new / old - 1) > limit:
        log("%s: скачок %.1f%% (было %s, стало %s), значение не принято" % (code, (new / old - 1) * 100, old, new))
        return False
    return True


def main():
    try:
        with open(OUT, encoding="utf-8") as f:
            prev = json.load(f)
    except Exception:
        prev = {}
    per_usd = dict(prev.get("perUsd", {}))
    usd_value = dict(prev.get("usdValue", {}))

    fiat, src_f = get_fiat()
    crypto, src_c = get_crypto()

    updated = 0
    for c in FIAT:
        if c in fiat and accept(c, fiat[c], per_usd.get(c), MAX_JUMP_FIAT):
            per_usd[c] = round(fiat[c], 6)
            updated += 1
        elif c not in fiat:
            log("%s: курс не получен, оставлен прежний" % c)
    for c in CRYPTO:
        if c in crypto and accept(c, crypto[c], usd_value.get(c), MAX_JUMP_CRYPTO):
            usd_value[c] = round(crypto[c], 8)
            updated += 1
        elif c not in crypto:
            log("%s: курс не получен, оставлен прежний" % c)

    if updated == 0:
        log("Ни один курс не обновлён, файл не изменён.")
        return 1

    data = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": src_f + src_c,
        "perUsd": per_usd,
        "usdValue": usd_value,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("Обновлено курсов: %d. Источники: %s" % (updated, ", ".join(data["sources"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
