"""
Dango exchange adapter.

Docs: https://book.dango.zone/

Dango is a custom L1 chain (Grug/CometBFT) with a GraphQL API.
It is NOT CCXT-compatible — all communication is via GraphQL over HTTP.

Architecture:
  - Market data:  GraphQL queries (no auth)
  - Account ops:  GraphQL mutations — each tx is assembled, signed, and broadcast
  - Signing:      EIP-712 (Ethereum typed data) for ethereum-registered keys

Transaction flow:
  1. Build msgs list (wasm execute)
  2. Simulate to get gas estimate
  3. Assemble Tx with data (nonce, chain_id, user_index, expiry)
  4. Build EIP-712 typed data from SignDoc JSON
  5. Compute EIP-712 signing hash
  6. Sign with Ethereum private key → 65-byte recoverable signature
  7. Build credential {"standard": {"key_hash": ..., "signature": {"eip712": {"sig": <b64>, "typed_data": <b64>}}}}
  8. broadcastTxSync mutation

Auth fields required in .env:
  DANGO_WALLET_ADDRESS    — 0x... Ethereum-style wallet address
  DANGO_PRIVATE_KEY       — 0x... Ethereum private key (hex, with or without 0x)

Constants (mainnet):
  GRAPHQL_ENDPOINT        = https://api-mainnet.dango.zone/graphql
  CHAIN_ID                = dango-1
  PERPS_CONTRACT          = 0x90bc84df68d1aa59a857e04ed529e9a26edbea4f
  ACCOUNT_FACTORY_CONTRACT= 0x18d28bafcdf9d4574f920ea004dea2d13ec16f6b
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
from typing import TYPE_CHECKING, Any

import pandas as pd
import requests
from eth_hash.auto import keccak

from src.exchanges.base import ExchangeAdapter, OrderResult, Position

if TYPE_CHECKING:
    from src.config_loader import Config

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mainnet constants
# ---------------------------------------------------------------------------

GRAPHQL_ENDPOINT = "https://api-mainnet.dango.zone/graphql"
CHAIN_ID = "dango-1"
PERPS_CONTRACT = "0x90bc84df68d1aa59a857e04ed529e9a26edbea4f"
ACCOUNT_FACTORY_CONTRACT = "0x18d28bafcdf9d4574f920ea004dea2d13ec16f6b"

# Gas constants (§2.7): simulate returns gas_used, add 770_000 overhead for Secp256k1
_GAS_OVERHEAD = 770_000
_FALLBACK_GAS = 1_500_000

# Slippage for market orders (1%)
_DEFAULT_SLIPPAGE = "0.010000"
# TP/SL slippage (2%)
_CONDITIONAL_SLIPPAGE = "0.020000"

# Nonce: sliding window of 20, max jump 100
# We track the highest seen nonce and increment by 1 each call.
# A fresh instance starts at 0 and resolves the real nonce on first use.


# ---------------------------------------------------------------------------
# Signing helpers
# ---------------------------------------------------------------------------

def _canonical_json(obj: Any) -> bytes:
    """
    Produce canonical JSON: keys sorted alphabetically, recursively.
    No extra whitespace. UTF-8 encoded.
    This is what Dango calls the SignDoc encoding (§2.3).
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _key_hash_from_address(address: str) -> str:
    """
    Dango key hash for an Ethereum account (§2.4):
      SHA-256 of UTF-8 bytes of lowercase 0x-prefixed address → hex-encoded uppercase.
    """
    addr_lower = address.lower()
    if not addr_lower.startswith("0x"):
        addr_lower = "0x" + addr_lower
    digest = hashlib.sha256(addr_lower.encode("utf-8")).hexdigest().upper()
    return digest


def _remove_nones(obj: Any) -> Any:
    """Recursively remove None values from dicts (matches Rust skip_serializing_none)."""
    if isinstance(obj, dict):
        return {k: _remove_nones(v) for k, v in obj.items() if v is not None}
    elif isinstance(obj, list):
        return [_remove_nones(v) for v in obj]
    return obj


def _make_type_name(key: str) -> str:
    """Capitalize a key for use as an EIP-712 type name."""
    if not key:
        return "Unknown"
    # Sanitize: remove array indices and special chars, then capitalize
    sanitized = "".join(c for c in key if c.isalnum() or c == "_")
    if not sanitized:
        return "Unknown"
    return sanitized[0].upper() + sanitized[1:]


def _infer_eip712_type(value: Any, types: dict[str, list[dict]], parent_key: str) -> str:
    """Infer the EIP-712 type for a JSON value."""
    if value is None:
        return "string"
    elif isinstance(value, bool):
        return "bool"
    elif isinstance(value, int):
        if 0 <= value <= 2**32 - 1:
            return "uint32"
        elif 0 <= value <= 2**64 - 1:
            return "uint64"
        else:
            return "uint256"
    elif isinstance(value, str):
        if len(value) == 42 and value.startswith("0x"):
            return "address"
        return "string"
    elif isinstance(value, dict):
        type_name = _make_type_name(parent_key)
        if type_name not in types:
            _generate_eip712_types(value, type_name, types)
        return type_name
    elif isinstance(value, list):
        if not value:
            return "string[]"
        elem_type = _infer_eip712_type(value[0], types, parent_key)
        return f"{elem_type}[]"
    else:
        return "string"


def _generate_eip712_types(value: dict, type_name: str = "Message", types: dict[str, list[dict]] | None = None) -> dict[str, list[dict]]:
    """Recursively generate EIP-712 types from a JSON object."""
    if types is None:
        types = {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ]
        }

    if isinstance(value, dict):
        fields = []
        for key, val in sorted(value.items()):
            field_type = _infer_eip712_type(val, types, key)
            fields.append({"name": key, "type": field_type})
        types[type_name] = fields
    elif isinstance(value, list) and value:
        _generate_eip712_types(value[0], type_name, types)

    return types


def _build_eip712_typed_data(sign_doc: dict, sender: str) -> dict:
    """Build the full EIP-712 typed data dict from a SignDoc."""
    types = _generate_eip712_types(sign_doc)
    return {
        "types": types,
        "primaryType": "Message",
        "domain": {
            "name": "dango",
            "chainId": 1,
            "verifyingContract": sender,
        },
        "message": sign_doc,
    }


def _sign_eip712(private_key_hex: str, typed_data: dict) -> tuple[str, str]:
    """
    Sign EIP-712 typed data with an Ethereum private key.
    Returns (sig_base64, typed_data_base64).
    """
    try:
        from eth_account.messages import encode_typed_data  # type: ignore
    except ImportError as e:
        raise ImportError(
            "eth-account is required for EIP-712 signing. "
            "Install it with: pip install eth-account"
        ) from e

    try:
        import coincurve  # type: ignore
    except ImportError as e:
        raise ImportError(
            "coincurve is required for Dango signing. "
            "Install it with: pip install coincurve"
        ) from e

    encoded = encode_typed_data(full_message=typed_data)
    # EIP-712 final hash: keccak256("\x19\x01" || domainSeparator || hashStruct(message))
    digest = keccak(b"\x19\x01" + encoded.header + encoded.body)

    pk_hex = private_key_hex.lower()
    if pk_hex.startswith("0x"):
        pk_hex = pk_hex[2:]
    pk_bytes = bytes.fromhex(pk_hex)
    privkey = coincurve.PrivateKey(pk_bytes)
    sig = privkey.sign_recoverable(digest, hasher=None)

    sig_b64 = base64.b64encode(sig).decode("ascii")
    typed_data_b64 = base64.b64encode(
        json.dumps(typed_data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).decode("ascii")

    return sig_b64, typed_data_b64


# ---------------------------------------------------------------------------
# GraphQL transport
# ---------------------------------------------------------------------------

class _GQL:
    """Minimal synchronous GraphQL client over HTTP."""

    def __init__(self, endpoint: str, timeout: int = 10) -> None:
        self._endpoint = endpoint
        self._timeout = timeout
        self._session = requests.Session()

    def query(self, gql: str, variables: dict | None = None) -> dict:
        payload: dict[str, Any] = {"query": gql}
        if variables:
            payload["variables"] = variables
        resp = self._session.post(
            self._endpoint,
            json=payload,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        body = resp.json()
        if "errors" in body:
            raise RuntimeError(f"GraphQL error: {body['errors']}")
        return body.get("data", {})

    def mutate(self, gql: str, variables: dict | None = None) -> dict:
        return self.query(gql, variables)


# ---------------------------------------------------------------------------
# DangoAdapter
# ---------------------------------------------------------------------------

class DangoAdapter(ExchangeAdapter):
    """
    Exchange adapter for Dango perpetuals DEX.

    Uses a single Ethereum-style wallet (same keypair as Hyperliquid).
    Signing: secp256k1 (64-byte compact sig over SHA-256(canonical SignDoc JSON)).
    """

    def __init__(self, config: "Config") -> None:
        self._address: str = config.secrets.dango_wallet_address
        self._private_key: str = config.secrets.dango_private_key
        self._gql = _GQL(GRAPHQL_ENDPOINT)

        # Cached account state — resolved lazily on first tx
        self._user_info: dict | None = None
        self._user_index: int | None = None
        self._account_address: str | None = None  # smart account address (sender)
        self._next_nonce: int | None = None  # tracked locally; re-fetched on errors

        # Pre-compute key_hash (doesn't change)
        self._key_hash = _key_hash_from_address(self._address)

    # ------------------------------------------------------------------
    # Internal: account state
    # ------------------------------------------------------------------

    def _fetch_user_info(self) -> dict:
        """
        Resolve user info via the top-level GraphQL `users` query by key_hash,
        then fetch the full user record from the account factory.

        Returns the raw 'user' object (index, name, accounts, keys).
        """
        if self._user_info is not None:
            return self._user_info

        # Step 1: find user index via top-level users query (§3.8)
        gql_users = """
        query GetUserByKey($publicKeyHash: String!) {
          users(publicKeyHash: $publicKeyHash, first: 1) {
            nodes {
              userIndex
            }
          }
        }
        """
        data = self._gql.query(gql_users, {"publicKeyHash": self._key_hash})
        nodes = data.get("users", {}).get("nodes", [])
        if not nodes:
            raise RuntimeError(
                f"Dango wallet {self._address} is not registered on-chain. "
                "Register via the account factory first (§3.1)."
            )
        user_index = int(nodes[0]["userIndex"])

        # Step 2: fetch full user info from account factory (§3.7)
        gql_user = """
        query GetUser($index: Int!) {
          queryApp(request: {
            wasm_smart: {
              contract: "%s",
              msg: { user: { index: $index } }
            }
          })
        }
        """ % ACCOUNT_FACTORY_CONTRACT
        data2 = self._gql.query(gql_user, {"index": user_index})
        result = data2.get("queryApp")
        if result is None:
            raise RuntimeError("Could not fetch user info from account factory")
        if isinstance(result, str):
            result = json.loads(result)
        # The queryApp response for wasm_smart wraps the contract result.
        if isinstance(result, dict) and "wasm_smart" in result:
            result = result["wasm_smart"]
        self._user_info = result
        return result

    @staticmethod
    def _unwrap_wasm_smart(data: dict) -> Any:
        """Extract the contract result from a queryApp wasm_smart response."""
        result = data.get("queryApp")
        if isinstance(result, dict) and "wasm_smart" in result:
            return result["wasm_smart"]
        return result

    def _fetch_nonces(self) -> list[int]:
        """
        Fetch seen nonces from the smart account contract (§2.2).
        Returns list of active nonces. Next nonce = max + 1 (or 0 if empty).
        """
        account = self._resolve_account_address()
        gql = """
        query GetNonces($contract: String!) {
          queryApp(request: {
            wasm_smart: {
              contract: $contract,
              msg: { seen_nonces: {} }
            }
          })
        }
        """
        data = self._gql.query(gql, {"contract": account})
        result = self._unwrap_wasm_smart(data)
        if result is None:
            return []
        if isinstance(result, str):
            result = json.loads(result)
        if isinstance(result, list):
            return [int(n) for n in result]
        return []

    def _resolve_user_index(self) -> int:
        if self._user_index is not None:
            return self._user_index
        info = self._fetch_user_info()
        idx = info.get("index")
        if idx is None:
            raise RuntimeError(f"User index not found in account factory response: {info}")
        self._user_index = int(idx)
        _logger.debug("Resolved Dango user_index=%d for %s", self._user_index, self._address)
        return self._user_index

    def _resolve_account_address(self) -> str:
        """Return the smart account address to use as transaction sender."""
        if self._account_address is not None:
            return self._account_address
        info = self._fetch_user_info()
        accounts = info.get("accounts", {})
        if not accounts:
            raise RuntimeError(f"No accounts found for Dango user: {info}")
        # Use the first account (lowest index) as sender
        first_account = next(iter(sorted(accounts.values())))
        self._account_address = first_account
        _logger.debug("Resolved Dango sender=%s for %s", self._account_address, self._address)
        return self._account_address

    def _resolve_next_nonce(self) -> int:
        if self._next_nonce is not None:
            nonce = self._next_nonce
            self._next_nonce += 1
            return nonce
        nonces = self._fetch_nonces()
        base = (max(nonces) + 1) if nonces else 0
        self._next_nonce = base + 1  # reserve base for this tx
        _logger.debug("Resolved Dango nonce=%d (active nonces=%s)", base, nonces)
        return base

    def _reset_nonce(self) -> None:
        """Call after a nonce error to re-fetch from chain."""
        self._next_nonce = None

    # ------------------------------------------------------------------
    # Internal: signing and broadcast
    # ------------------------------------------------------------------

    def _build_sign_doc(
        self,
        sender: str,
        gas_limit: int,
        msgs: list[dict],
        nonce: int,
        user_index: int,
        expiry: str | None = None,
    ) -> dict:
        """
        Construct the SignDoc dict (§2.3).
        Fields must be sorted alphabetically in the canonical JSON, which
        _canonical_json() handles. We build it as a plain dict here.

        SignDoc mirrors the Tx but uses 'messages' (not 'msgs') and has no 'credential'.
        data fields are also sorted alphabetically.
        """
        return _remove_nones({
            "data": _remove_nones({
                "chain_id": CHAIN_ID,
                "expiry": expiry,
                "nonce": nonce,
                "user_index": user_index,
            }),
            "gas_limit": gas_limit,
            "messages": msgs,
            "sender": sender,
        })

    def _create_credential(self, sign_doc: dict) -> dict:
        """
        Sign the sign_doc and produce a secp256k1 standard credential.

        Flow (§2.5):
          1. Canonical JSON encode sign_doc (keys sorted alphabetically)
          2. SHA-256 hash the bytes
          3. Sign with secp256k1 private key → 64-byte compact hex
          4. Wrap in {"standard": {"key_hash": ..., "signature": {"secp256k1": <hex>}}}
        """
        sender = sign_doc["sender"]
        typed_data = _build_eip712_typed_data(sign_doc, sender)
        sig_b64, typed_data_b64 = _sign_eip712(self._private_key, typed_data)
        return {
            "standard": {
                "key_hash": self._key_hash,
                "signature": {
                    "eip712": {
                        "sig": sig_b64,
                        "typed_data": typed_data_b64,
                    },
                },
            }
        }

    def _simulate(self, msgs: list[dict], sender: str, nonce: int, user_index: int) -> int:
        """
        Estimate gas via the simulate query (§2.7).
        Simulate skips signature verification so we can use a dummy credential.
        Returns final gas_limit = gas_used + GAS_OVERHEAD.
        """
        unsigned_tx = {
            "sender": sender,
            "gas_limit": _FALLBACK_GAS,
            "msgs": msgs,
            "data": _remove_nones({
                "user_index": user_index,
                "chain_id": CHAIN_ID,
                "nonce": nonce,
                "expiry": None,
            }),
        }
        gql = """
        query Simulate($tx: UnsignedTx!) {
          simulate(tx: $tx)
        }
        """
        try:
            data = self._gql.query(gql, {"tx": unsigned_tx})
            sim_result = data.get("simulate", {})
            if isinstance(sim_result, dict):
                gas_used = int(sim_result.get("gas_used", _FALLBACK_GAS))
            else:
                gas_used = int(sim_result)
            gas_limit = gas_used + _GAS_OVERHEAD
            _logger.debug("Simulate: gas_used=%d → gas_limit=%d", gas_used, gas_limit)
            return gas_limit
        except Exception as exc:
            _logger.warning("Simulate failed, using fallback gas: %s", exc)
            return _FALLBACK_GAS

    def _broadcast(
        self,
        msgs: list[dict],
        sender: str,
        nonce: int,
        user_index: int,
        gas_limit: int,
    ) -> dict:
        """
        Assemble, sign, and broadcast a transaction. Returns the broadcastTxSync result.
        """
        sign_doc = self._build_sign_doc(
            sender=sender,
            gas_limit=gas_limit,
            msgs=msgs,
            nonce=nonce,
            user_index=user_index,
        )
        credential = self._create_credential(sign_doc)

        tx = {
            "sender": sender,
            "gas_limit": gas_limit,
            "msgs": msgs,
            "data": _remove_nones({
                "user_index": user_index,
                "chain_id": CHAIN_ID,
                "nonce": nonce,
                "expiry": None,
            }),
            "credential": credential,
        }

        gql = """
        mutation BroadcastTx($tx: Tx!) {
          broadcastTxSync(tx: $tx)
        }
        """
        data = self._gql.mutate(gql, {"tx": tx})
        result = data.get("broadcastTxSync")
        _logger.debug("broadcastTxSync result: %s", result)
        return result if isinstance(result, dict) else {"raw": result}

    def _execute_perps(self, msg: dict) -> dict:
        """
        Build a wasm execute message targeting PERPS_CONTRACT, simulate, and broadcast.
        Returns the broadcast result.
        """
        user_index = self._resolve_user_index()
        sender = self._resolve_account_address()
        nonce = self._resolve_next_nonce()

        msgs = [{
            "execute": {
                "contract": PERPS_CONTRACT,
                "msg": msg,
                "funds": {},
            }
        }]

        gas_limit = self._simulate(msgs, sender, nonce, user_index)

        try:
            return self._broadcast(msgs, sender, nonce, user_index, gas_limit)
        except Exception as exc:
            err_str = str(exc).lower()
            if "nonce" in err_str:
                _logger.warning("Nonce error, resetting and retrying: %s", exc)
                self._reset_nonce()
                nonce = self._resolve_next_nonce()
                return self._broadcast(msgs, sender, nonce, user_index, gas_limit)
            raise

    # ------------------------------------------------------------------
    # ExchangeAdapter interface
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        """
        Check connectivity and that our account exists on-chain.
        """
        try:
            info = self._fetch_user_info()
            return info is not None
        except Exception as exc:
            _logger.warning("Dango ping failed: %s", exc)
            return False

    def get_top_coins(self, n: int) -> list[str]:
        """
        Fetch all perp pairs sorted by 24h volume descending.
        Returns top N pair_ids in Dango format: 'perp/btcusd'.
        """
        gql = """
        query {
          allPerpsPairStats {
            pairId
            volume24H
          }
        }
        """
        data = self._gql.query(gql)
        pairs = data.get("allPerpsPairStats", [])

        # Filter to only perp pairs and sort by volume
        ranked = []
        for p in pairs:
            pair_id = p.get("pairId", "")
            if not pair_id.startswith("perp/"):
                continue
            volume = float(p.get("volume24H") or 0)
            ranked.append((pair_id, volume))

        ranked.sort(key=lambda x: x[1], reverse=True)
        result = [pair_id for pair_id, _ in ranked[:n]]
        _logger.debug("Top %d Dango pairs by 24h volume: %s", n, result)
        return result

    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV candles via the perpsCandles GraphQL query.

        symbol: Dango pair_id format, e.g. 'perp/btcusd'
        timeframe: standard string '1h', '4h', '1d', '15m', '5m', '1m', '1s', '1w'
        limit: number of candles to fetch
        """
        interval_map = {
            "1s": "ONE_SECOND",
            "1m": "ONE_MINUTE",
            "5m": "FIVE_MINUTES",
            "15m": "FIFTEEN_MINUTES",
            "1h": "ONE_HOUR",
            "4h": "FOUR_HOURS",
            "1d": "ONE_DAY",
            "1w": "ONE_WEEK",
        }
        interval = interval_map.get(timeframe)
        if interval is None:
            raise ValueError(
                f"Unsupported timeframe '{timeframe}' for Dango. "
                f"Supported: {list(interval_map.keys())}"
            )

        gql = """
        query GetCandles($pairId: String!, $interval: CandleInterval!, $first: Int!) {
          perpsCandles(pairId: $pairId, interval: $interval, first: $first) {
            nodes {
              open
              high
              low
              close
              volume
              timeStartUnix
            }
          }
        }
        """
        data = self._gql.query(gql, {
            "pairId": symbol,
            "interval": interval,
            "first": limit,
        })
        nodes = data.get("perpsCandles", {}).get("nodes", [])

        if not nodes:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        rows = []
        for node in nodes:
            rows.append({
                "timestamp": int(node["timeStartUnix"]),  # already in milliseconds
                "open": float(node["open"]),
                "high": float(node["high"]),
                "low": float(node["low"]),
                "close": float(node["close"]),
                "volume": float(node["volume"]),
            })

        df = pd.DataFrame(rows)
        df.index = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        return df[["open", "high", "low", "close", "volume"]].sort_index()

    def get_open_positions(self) -> list[Position]:
        """
        Fetch open positions via the user_state contract query.
        Positive size = long, negative size = short (§10.4 Position type).
        """
        try:
            account = self._resolve_account_address()
        except RuntimeError:
            return []

        gql = """
        query GetUserState($contract: String!, $user: String!) {
          queryApp(request: {
            wasm_smart: {
              contract: $contract,
              msg: { user_state: { user: $user } }
            }
          })
        }
        """
        data = self._gql.query(gql, {
            "contract": PERPS_CONTRACT,
            "user": account,
        })
        result = self._unwrap_wasm_smart(data)
        if not result:
            return []
        if isinstance(result, str):
            result = json.loads(result)

        positions_raw = result.get("positions", {})
        positions = []

        for pair_id, pos in positions_raw.items():
            size = float(pos.get("size", 0))
            if size == 0:
                continue
            side = "long" if size > 0 else "short"
            entry_price = float(pos.get("entry_price", 0))
            positions.append(Position(
                symbol=pair_id,
                side=side,
                size=abs(size),
                entry_price=entry_price,
            ))

        return positions

    def get_balance(self) -> float:
        """
        Return free margin (USD) from user_state.
        Uses margin - reserved_margin to get usable balance.
        """
        try:
            account = self._resolve_account_address()
        except RuntimeError:
            return 0.0

        gql = """
        query GetUserState($contract: String!, $user: String!) {
          queryApp(request: {
            wasm_smart: {
              contract: $contract,
              msg: { user_state: { user: $user } }
            }
          })
        }
        """
        data = self._gql.query(gql, {
            "contract": PERPS_CONTRACT,
            "user": account,
        })
        result = self._unwrap_wasm_smart(data)
        if not result:
            return 0.0
        if isinstance(result, str):
            result = json.loads(result)

        margin = float(result.get("margin", 0))
        reserved = float(result.get("reserved_margin", 0))
        free = max(0.0, margin - reserved)
        _logger.debug(
            "Dango balance: margin=%.2f, reserved=%.2f, free=%.2f",
            margin, reserved, free,
        )
        return free

    def place_order(
        self,
        symbol: str,
        side: str,
        size: float,
        tp_pct: float,
        sl_pct: float,
    ) -> OrderResult:
        """
        Place a market order with TP and SL as conditional child orders.

        symbol: Dango pair_id format, e.g. 'perp/btcusd'
        side: 'buy' (long) or 'sell' (short)
        size: position size in base asset units (positive number)
        tp_pct: take-profit distance as decimal (e.g. 0.04 = 4%)
        sl_pct: stop-loss distance as decimal (e.g. 0.02 = 2%)

        Signed size convention:
          long  (buy)  → positive size
          short (sell) → negative size
        """
        is_buy = side == "buy"
        signed_size = size if is_buy else -size

        # Format as 6 decimal place string (Dango Quantity type)
        size_str = f"{signed_size:.6f}"

        # We need the current price to compute TP/SL trigger prices.
        # Fetch from pair stats since we don't have entry price before fill.
        # The conditional orders will be attached to the market order itself.
        current_price = self._get_current_price(symbol)

        tp_trigger = current_price * (1 + tp_pct) if is_buy else current_price * (1 - tp_pct)
        sl_trigger = current_price * (1 - sl_pct) if is_buy else current_price * (1 + sl_pct)

        msg = {
            "trade": {
                "submit_order": {
                    "pair_id": symbol,
                    "size": size_str,
                    "kind": {
                        "market": {
                            "max_slippage": _DEFAULT_SLIPPAGE,
                        }
                    },
                    "reduce_only": False,
                    "tp": {
                        "trigger_price": f"{tp_trigger:.6f}",
                        "max_slippage": _CONDITIONAL_SLIPPAGE,
                    },
                    "sl": {
                        "trigger_price": f"{sl_trigger:.6f}",
                        "max_slippage": _CONDITIONAL_SLIPPAGE,
                    },
                }
            }
        }

        _logger.info(
            "Placing Dango order",
            extra={
                "symbol": symbol,
                "side": side,
                "size": size_str,
                "tp_trigger": f"{tp_trigger:.4f}",
                "sl_trigger": f"{sl_trigger:.4f}",
            },
        )

        result = self._execute_perps(msg)

        # Dango broadcastTxSync returns a tx hash string or result object.
        # Extract what we can for OrderResult.
        order_id = str(
            result.get("tx_hash")
            or result.get("txHash")
            or result.get("hash")
            or result.get("raw")
            or "unknown"
        )

        return OrderResult(
            order_id=order_id,
            symbol=symbol,
            side=side,
            size=size,
            entry_price=current_price,  # approximate — actual fill may differ
            tp_price=tp_trigger,
            sl_price=sl_trigger,
            status="open",
        )

    def close_position(self, symbol: str, size: float) -> OrderResult:
        """
        Close an open position with a reduce-only market order.

        symbol: Dango pair_id format, e.g. 'perp/btcusd'
        size: position size in base asset units (positive number)
        """
        current_price = self._get_current_price(symbol)
        size_str = f"-{size:.6f}"

        msg = {
            "trade": {
                "submit_order": {
                    "pair_id": symbol,
                    "size": size_str,
                    "kind": {
                        "market": {
                            "max_slippage": _DEFAULT_SLIPPAGE,
                        }
                    },
                    "reduce_only": True,
                }
            }
        }

        _logger.info(
            "Closing Dango position",
            extra={"symbol": symbol, "size": size_str},
        )

        result = self._execute_perps(msg)
        order_id = str(
            result.get("tx_hash")
            or result.get("txHash")
            or result.get("hash")
            or result.get("raw")
            or "unknown"
        )

        return OrderResult(
            order_id=order_id,
            symbol=symbol,
            side="sell",
            size=size,
            entry_price=current_price,
            tp_price=None,
            sl_price=None,
            status="closed",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_current_price(self, pair_id: str) -> float:
        """Fetch current oracle/mark price for a pair from allPerpsPairStats."""
        gql = """
        query GetPairPrice($pairId: String!) {
          perpsPairStats(pairId: $pairId) {
            currentPrice
          }
        }
        """
        try:
            data = self._gql.query(gql, {"pairId": pair_id})
            price_str = data.get("perpsPairStats", {}).get("currentPrice", "0")
            return float(price_str)
        except Exception:
            # Fallback: scan allPerpsPairStats
            gql2 = "query { allPerpsPairStats { pairId currentPrice } }"
            data2 = self._gql.query(gql2)
            for p in data2.get("allPerpsPairStats", []):
                if p.get("pairId") == pair_id:
                    return float(p.get("currentPrice", 0))
        raise RuntimeError(f"Could not fetch current price for {pair_id}")
