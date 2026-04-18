import ccxt

def check_my_exchanges():
    search_list = ['hyperliquid', 'hibachi', 'tradexyz', 'dreamcash']
    supported = ccxt.exchanges

    print(f"--- CCXT Support Check ---")
    for name in search_list:
        status = "[OK] Supported" if name in supported else "[X] Not Direct (Check Ecosystem)"
        print(f"{name.capitalize()}: {status}")

check_my_exchanges()