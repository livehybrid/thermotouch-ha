# ThermoTouch UFH for Home Assistant

Monitor and control **ETOP / Thermogroup ThermoTouch** underfloor-heating thermostats (the
ones whose app talks to `etop3.etopcontrols.com`) from Home Assistant.

It talks to the thermostat **through the ETOP cloud, as a client** — the same way the vendor app
does. Once it's set up there is **no bridge, no relay and no MQTT** to keep running, and the
vendor app keeps working alongside it.

> Reverse-engineered from our own devices; not affiliated with ETOP or Thermogroup. The cloud
> protocol is written up in the companion [`thermotouch-bridge`](https://github.com/livehybrid/thermotouch-bridge)
> project (`PROTOCOL.md`).

## Entities

One device per thermostat, with:

| Entity | Type | Notes |
|--------|------|-------|
| Thermostat | `climate` | target temperature, five preset modes (comfort / eco / manual / holiday / schedule), heating / idle action, room temperature |
| Towel rail | `select` | off / on / timer / 1 h / 2 h / 4 h |
| Room temperature | `sensor` | °C |
| Mode | `sensor` | current mode |
| Heating | `binary_sensor` | floor heating relay |
| Towel rail running | `binary_sensor` | rail element on |

## How it works (and what it does *not* need)

The thermostat keeps a permanent connection to the ETOP cloud. The vendor app reaches it by
connecting to the same cloud; this integration does the same. There is **no account/login** — the
app is paired by joining the thermostat's own Wi-Fi once, which stores a per-device **token** on
the device.

To act as a client, the integration needs, **per thermostat**:

| Item | Needed for | Nature |
|------|-----------|--------|
| **MAC** | everything | the thermostat's Wi-Fi MAC (`F0:FE:6B:…`) |
| **Token** | reading state | 12 hex characters, fixed per device |
| **Command template** | control (writing) | an 82-byte hex string, fixed per device |

The token and template are **not secret settings you can look up** — the only way to obtain them
is to observe the app talking to the thermostat **once**. That one capture is what the companion
bridge is for. **After the capture the bridge is not needed again** — the integration runs purely
as a cloud client.

```
                 one-time setup                            then, forever:
   vendor app ─▶ thermostat                      Home Assistant ─▶ ETOP cloud ─▶ thermostat
        │  (captured once via the bridge)             (integration, direct — no bridge, no MQTT)
        ▼
   token + command template ─▶ paste into HA
```

### The one-session rule

The thermostat serves **one app session at a time**. While you have the **vendor app open** it
holds that session, so the integration can neither read nor control the device; both resume
automatically a minute or two after you close the app (and vice-versa — close HA's influence is
not needed, it simply backs off). A command sent while the app is open is reported as failed
("busy") rather than silently dropped.

## Getting the token and command template (one time)

You need to see the app talk to the thermostat once. The companion
[`thermotouch-bridge`](https://github.com/livehybrid/thermotouch-bridge) does this:

1. Run the bridge on any always-on host on your LAN (Docker; see its README).
2. Point the thermostat's DNS for `etop3.etopcontrols.com` at that host — either a LAN DNS
   override (Pi-hole/AdGuard/router) **and a power-cycle of the thermostat**, or a gateway DNAT
   redirect (no power-cycle; see the bridge's `PROTOCOL.md`).
3. Open the vendor app and let it load the thermostat once (this is the capture).
4. Fetch the per-device material from the bridge:

   ```
   curl 'http://<bridge-host>:8026/api/material?mac=F0:FE:6B:6A:C8:10'
   # -> {"token": "ada6...", "command_template": "0002...", ...}
   ```

5. Undo the DNS redirect. **The bridge can now be stopped** — it is not used at runtime.

(If you only want monitoring, you need just the token; the command template is for control.)

## Install

**HACS** (recommended): HACS → Integrations → ⋮ → **Custom repositories**, add
`https://github.com/livehybrid/thermotouch-ha` as category **Integration**, install, and restart
Home Assistant. Then **Settings → Devices & Services → Add Integration → ThermoTouch UFH**.

**Manual**: copy `custom_components/thermotouch` into your HA `config/custom_components/` and
restart.

## Configuration

| Field | Required | Default | Notes |
|-------|----------|---------|-------|
| Name | yes | ThermoTouch UFH | the device name in HA |
| MAC | yes | — | `F0:FE:6B:…` |
| Token | yes | — | 12 hex characters |
| Command template | no | — | 82-byte hex; omit for monitor-only |
| Cloud host | no | `18.197.22.220` | ETOP endpoint; change only if it moves |
| Cloud port | no | `2026` | |
| Poll interval | no | `300` s | how often state is read |

The flow validates the token with a live read. If the vendor app happens to be open at that
moment the read is "busy" and the entry is still created (it will read once the app is closed).

## Troubleshooting

- **Everything is "unknown" / state never updates** — the vendor app may be open (one-session
  rule); close it for a couple of minutes. If it never reads with the app closed, the token is
  wrong — re-capture it.
- **A command errors with "busy"** — the vendor app is holding the session; close it and retry.
- **Control does nothing / no climate controls** — you need the command template; reading works
  with the token alone.
- **Reads/commands are a bit slow** — each one is a short cloud session; this is normal. Heating
  is slow, so the default 300 s poll is fine.

## Limitations & roadmap

- State is cloud-**polled**, not pushed: it refreshes on the poll interval and right after your
  own commands.
- One session at a time (above).
- Control needs the command template.
- **Roadmap:** an in-integration capture mode so the one-time token/template step needs no
  separate bridge at all.

## License

MIT. See [`LICENSE`](LICENSE).
