# ThermoTouch UFH for Home Assistant

A Home Assistant integration for **ETOP / Thermogroup ThermoTouch** underfloor-heating
thermostats (the ones whose app talks to `etop3.etopcontrols.com`). It reads and controls the
thermostat over the ETOP cloud as a client, so **no local redirect is required** once set up,
and the vendor app keeps working.

> Reverse-engineered from our own devices. Not affiliated with ETOP or Thermogroup. The cloud
> protocol is documented in the companion [`thermotouch-bridge`](https://github.com/livehybrid/thermotouch-bridge)
> project (`PROTOCOL.md`).

## Entities

Per thermostat:

- **Climate** — target temperature, the five modes as presets (comfort / eco / manual / holiday
  / schedule), and heating / idle action.
- **Towel rail** select — off / on / timer / 1 h / 2 h / 4 h.
- **Sensors** — room temperature, mode.
- **Binary sensors** — heating, towel rail running.

## How it works, and what you need

The thermostat serves **one app session at a time** and validates a per-device **token** on
reads. There is no account login. To talk to it you need two things, both obtained **once** with
the companion bridge:

| Item | Needed for | How to get it |
|------|-----------|---------------|
| **MAC** | everything | the thermostat's Wi-Fi MAC (`F0:FE:6B:...`), shown in the app or your router |
| **Token** | reading state | 12 hex characters |
| **Command template** | control (writing) | an 82-byte hex string |

Run the [`thermotouch-bridge`](https://github.com/livehybrid/thermotouch-bridge) in relay mode,
open the vendor app once so it talks to the thermostat, then fetch the material:

```
curl 'http://<bridge>:8026/api/material?mac=F0:FE:6B:6A:C8:10'
# -> { "token": "...", "command_template": "..." }
```

Paste those into the integration's config. The token alone enables monitoring; add the command
template to enable control.

> **One session at a time:** while you have the **vendor app open** it holds the thermostat's single
> session, so the integration can neither read nor control it; both resume automatically once the
> app is closed.

## Install

**HACS** (custom repository): add `https://github.com/livehybrid/thermotouch-ha` as an
Integration, install, restart Home Assistant, then **Settings → Devices & Services → Add
Integration → ThermoTouch UFH**.

Manual: copy `custom_components/thermotouch` into your HA `config/custom_components/` and restart.

## Options

- **Poll interval** (default 300 s) — how often state is read. Heating is slow; reads use a cloud
  session, so keep this modest.
- **Cloud host / port** — defaults to the current ETOP endpoint; change only if it moves.

## Limitations

- State updates on the poll interval and on your own commands; it is cloud-polled, not pushed.
- Control needs the command template (reading does not).
- One app session at a time (see above).

## License

MIT.
