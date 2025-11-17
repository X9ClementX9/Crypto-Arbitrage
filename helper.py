import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from dotenv import load_dotenv
import os
from datetime import datetime, timezone

# Configuration des URLs de l'API Binance
BINANCE_BASE_URL = "https://api.binance.com"
BASE_URL_FAPI = "https://fapi.binance.com"


# ================== API CALLS ==================
def get_spot_price(symbol):
    url = f"{BINANCE_BASE_URL}/api/v3/ticker/price"
    params = {"symbol": symbol}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    return float(data["price"])


def get_future_price(symbol):
    url = f"{BASE_URL_FAPI}/fapi/v2/ticker/price"
    params = {"symbol": symbol}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    return float(data["price"])


def get_exchange_info():
    url = f"{BASE_URL_FAPI}/fapi/v1/exchangeInfo"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.json()



# ================== Taux d'interêt pour un actif ==================
def get_binance_borrow_rate(api_key, api_secret, asset, is_isolated = True):

    BINANCE_BASE_URL = "https://api.binance.com"
    endpoint = "/sapi/v1/margin/next-hourly-interest-rate"
    url = BINANCE_BASE_URL + endpoint

    timestamp = int(time.time() * 1000)

    params = {
        "assets": asset,
        "isIsolated": is_isolated,
        "timestamp": timestamp,
    }

    query_string = urlencode(params)

    signature = hmac.new(
        api_secret.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    params["signature"] = signature

    headers = {"X-MBX-APIKEY": api_key}

    r = requests.get(url, headers=headers, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    return data[0]["nextHourlyInterestRate"]



# ================== Donne les Futures et l'expiration pour un Ticker ==================
def get_futures_prices(UNDERLYING_BASE, MAX_DAYS_TO_EXPIRY = 60, UNDERLYING_QUOTE = "USDT"):

    BASE_URL_FAPI = "https://fapi.binance.com"

    data_info = get_exchange_info()
    server_time_ms = data_info["serverTime"]
    server_time = datetime.fromtimestamp(server_time_ms / 1000, tz=timezone.utc)

    url_price = f"{BASE_URL_FAPI}/fapi/v2/ticker/price"
    r_price = requests.get(url_price, timeout=10)
    r_price.raise_for_status()
    data_price = r_price.json()

    prices = {}
    for item in data_price:
        symbol = item["symbol"]
        price = float(item["price"])
        prices[symbol] = price

    results = []

    for symbol in data_info["symbols"]:
        # On ne garde que BTC/USDT
        if symbol.get("baseAsset") != UNDERLYING_BASE:
            continue
        if symbol.get("quoteAsset") != UNDERLYING_QUOTE:
            continue

        contract_type = symbol.get("contractType")
        status = symbol.get("status")

        # On exclut les perpétuels et on garde que ceux qui sont en trading
        if contract_type == "PERPETUAL":
            continue
        if status != "TRADING":
            continue

        delivery_ts_ms = symbol.get("deliveryDate", 0)
        if not delivery_ts_ms:
            continue

        # calcul du nombre de jours jusqu'à l'échéance
        days_to_expiry = (delivery_ts_ms - server_time_ms) / (1000 * 60 * 60 * 24)

        if days_to_expiry < 0:
            # contrat déjà expiré ou en cours de livraison
            continue

        if days_to_expiry <= MAX_DAYS_TO_EXPIRY:
            results.append({
                "symbol": symbol["symbol"],
                "days_to_expiry": days_to_expiry,
            })

    # Tri par maturité croissante
    results.sort(key=lambda x: x["days_to_expiry"])

    return results, server_time



# ================== Donne la Delivery Time ==================
def get_future_delivery_info(future_symbol):
    info = get_exchange_info()
    server_time_ms = info["serverTime"]

    for symbol in info["symbols"]:
        if symbol.get("symbol") == future_symbol:
            delivery_ts_ms = symbol.get("deliveryDate", 0)
            break

    return delivery_ts_ms, server_time_ms



# ================== Frais de trading spot ==================
def CashCarry_arbitrage(API_KEY, API_SECRET, SPOT_SYMBOL = "BTCUSDT", FUTURE_SYMBOL = "BTCUSDT_251226", CASH_SYMBOL = "USDT", SPOT_FEE_RATE = 0.001, FUT_FEE_RATE  = 0.0004, risk_rate_asked = 0.02):
    
    repo_USDT = float(get_binance_borrow_rate(API_KEY, API_SECRET, CASH_SYMBOL))
    spot = get_spot_price(SPOT_SYMBOL)
    fut = get_future_price(FUTURE_SYMBOL)
    delivery_ts_ms, now_ts_ms = get_future_delivery_info(FUTURE_SYMBOL)

    # Convertir en datetime pour affichage
    delivery_dt = datetime.fromtimestamp(delivery_ts_ms / 1000, tz=timezone.utc)
    now_dt = datetime.fromtimestamp(now_ts_ms / 1000, tz=timezone.utc)

    # Temps jusqu'à maturité en années
    ms_in_hour = 1000 * 60 * 60
    T_hour = (delivery_ts_ms - now_ts_ms) / ms_in_hour

    # Fees, Base, Theorical Future Price
    fees_spot  = spot * SPOT_FEE_RATE
    fees_fut   = fut * FUT_FEE_RATE
    theorical_fut = spot * (1 + repo_USDT) ** T_hour
    
    arbitrage_opportunity = "No Opportunity"
    arbitrage_rate = 0.0

    if fut - fees_fut > (theorical_fut + fees_spot) * (1 + risk_rate_asked):
        arbitrage_opportunity = "Cash & Carry Opportunity"
        arbitrage_rate = (fut - fees_fut) / (theorical_fut + fees_spot) - 1

    elif fut + fees_fut < (theorical_fut - fees_spot) * (1 - risk_rate_asked):
        arbitrage_opportunity = "Reverse Cash & Carry Opportunity"
        arbitrage_rate = 1 - (fut + fees_fut) / (theorical_fut - fees_spot)

    # Retourner toutes les infos
    return {
        "spot": spot,
        "future": fut,
        "arbitrage_opportunity": arbitrage_opportunity,
        "now_dt": now_dt,
        "delivery_dt": delivery_dt,
        "arbitrage_rate": arbitrage_rate,
    }



# ================== EXAMPLES D'UTILISATION ==================
load_dotenv()
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

#print(get_binance_borrow_rate(API_KEY, API_SECRET, "USDT"))
#print(get_futures_prices("BTC"))
#print(get_spot_price("BTC"))
#print(CashCarry_arbitrage(API_KEY, API_SECRET))