# Discovery V2 Analysis

## Purpose of the current module

The existing discovery stack in `common/discovery.py` handles three separate responsibilities:

1. Network/interface inspection to choose an advertised IPv4 address and discovery targets.
2. UDP beacon announce/listen for server lookup on LAN or overlay networks.
3. HTTP localhost fallback used when UDP discovery does not find a matching server.

That combination works, but it also means transport assumptions, reachability heuristics, and app-level fallback behavior are tightly coupled in one module.

For the v2 rewrite, VPN / overlay-specific fallbacks are out of scope in the first pass.

## Current feature inventory

### 1. Server beacon announcement

- `ServerAnnouncer` periodically sends a JSON beacon on UDP port `5354`.
- Beacon payload fields:
  - `magic`
  - `server_id`
  - `host`
  - `host_is_explicit`
  - `port`
- The announcer supports:
  - global broadcast to `255.255.255.255`
  - per-interface directed broadcast targets
  - multicast to `239.255.42.99`
  - caller-supplied extra targets

### 2. IPv4 interface inspection

- The module enumerates active IPv4 interfaces with `psutil`.
- It filters out loopback, unspecified, link-local, and multicast addresses.
- It prefers broadcast-capable private interfaces when choosing the "best" local IP.

### 3. Directed broadcast derivation

- If an interface exposes a broadcast address, that address is used.
- Otherwise the code falls back to a synthetic `/24` directed broadcast by replacing the last octet with `255`.
- If no interface-specific targets exist, it repeats the same `/24` derivation using the default route IP.

This synthetic `/24` fallback is exactly the kind of behavior we should avoid in v2.

### 4. Beacon listening

- Clients bind a UDP socket on the shared discovery port.
- Optional multicast join is attempted on the listen socket.
- Incoming packets are parsed as ASCII JSON and filtered by `magic` and `server_id`.
- If the server host was auto-detected, the listener prefers the packet source IP over the advertised `host`.
- If the server host was explicitly configured, the listener honors the advertised `host`.

### 5. Client fallback behavior

- `discover_server_with_local_fallback()` first waits for UDP discovery.
- If that times out, it performs `GET /health` on `127.0.0.1:<port>`.
- A localhost match is accepted only if `/health` returns the same `server_id`.

### 6. Duplicate-server check

- Server startup uses the same UDP listen path to detect an already-running server with the same `server_id`.
- If UDP cannot confirm a duplicate, startup can optionally probe localhost on the target HTTP port.

## Assumptions baked into the current design

These are the main reasons the implementation still feels tied to classic `192.168.x.x` style networks:

- Discovery is IPv4-only.
- Directed broadcast fallback assumes `/24` subnet boundaries.
- Address selection prefers broadcast-capable private interfaces.
- Multicast membership is joined with `0.0.0.0`, which is simple but not interface-aware.
- The "best" advertised address is inferred globally instead of selected per transport/interface.
- Beacon transport and advertised reachability are treated as the same problem.

## What is worth preserving in v2

- `server_id` filtering so multiple environments can coexist.
- Small beacon payload with a stable `magic` marker.
- Source-IP preference when the server auto-detects its own address.
- Pluggable extra targets for explicit environments.
- Localhost health fallback for same-machine development and duplicate detection.
- Minimal startup surface area for callers:
  - server: start announcer / duplicate check
  - client: resolve host / port

## Main redesign opportunities

### Separate concerns

V2 should likely split into distinct layers:

- address inventory
- advertise strategy
- listen/parse strategy
- reachability validation
- app-specific fallback policy

### Stop inferring network shape from host octets

Instead of generating `x.y.z.255`, v2 should prefer:

- actual interface netmasks/broadcasts when available
- explicit configured peers or rendezvous targets
- multicast or unicast probe flows that do not assume LAN broadcast semantics

### Model discovery transports explicitly

A cleaner v2 could support multiple discovery modes with clear behavior:

- broadcast
- multicast
- unicast target list
- localhost probe
- future relay or registry mode

That makes it easier to disable brittle transports in overlay or segmented environments.

### Separate "who am I?" from "how do I announce?"

The current module picks a single advertised host early. V2 should likely allow:

- multiple candidate advertised addresses
- interface-specific advertisements
- transport-specific advertised addresses
- optional active reachability validation before returning a target

### Keep app integration thin

The app really needs only two public capabilities:

- server-side: announce presence and detect conflicts
- client-side: resolve a reachable server endpoint

Everything else can become internal strategy objects or helper functions.

## Suggested ground-up v2 scope

Reasonable first milestone:

1. Define a transport-agnostic discovery result model.
2. Build interface/address inventory from real interface metadata, not `/24` guesses.
3. Implement one clean announce/listen path with structured beacon parsing.
4. Re-add localhost fallback as a separate optional resolver stage.
5. Add tests around standard subnet layouts and non-broadcast interfaces before wiring v2 into the app.

## Practical note for this repo

`common/discovery_v2.py` remains the isolated rewrite baseline, and the active `common/discovery.py` now uses the same simplified behavior. Both drop VPN-specific interface heuristics and synthetic `/24` directed-broadcast guesses.
