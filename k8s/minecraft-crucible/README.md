# minecraft-crucible

Hosted Minecraft server for an outside group. The server runs in Crafty
Controller, the same way as the [JINKIES!](../minecraft-jinkies/) server.
General terms for all hosted servers are in [Minecraft Server Hosting](../../minecraft-hosting/README.md).

## Hosting agreement

> **Privacy note.** This document has no personal information. People are
> named by role (for example, "Client A"). The real names, chat handles, and
> payment addresses are kept outside this repository.
>
> **Translation note.** This section uses short sentences and plain words so
> that it is easy to translate. Dates use the `YYYY-MM-DD` format.

### Parties

| Role | Description |
|-|-|
| Host | The operator of the drewburr.com environment. |
| Client A | The person who asked for the server. Client A also runs the JINKIES! server on this platform. Client A lives in Canada. |

### Current terms

| Item | Current value | Since |
|-|-|-|
| Price | 12 per month | 2026-10-01 |
| Memory limit | 12Gi | 2026-09-22 |
| Use | Modded server, about 58 mods, 6 to 8 players | 2026-09 |
| Due date | The 1st day of each month | 2026-06-25 |
| Late payment | Server can be shut down after 14 days | 2026-06-25 |

> **Open item: currency.** The messages say "$" but do not say USD or CAD.
> Client A is in Canada. Confirm the currency with Client A.

### Agreement 1: new server (2026-06-25)

Made in direct messages on Discord. Client A asked the Host to host a second
server. The Host accepted.

#### What the server was for

- A recording project. The group played in hardcore mode for a fixed number of
  recording sessions.
- 6 to 8 players. All players are online at the same time.
- Sessions last a few hours.
- The only server-side mod that the group needed was voice chat.
- Goal: the server stays up, with little lag, for the whole session.

Client A said they might want a third server later, with far fewer mods. It
does not exist yet.

#### Server setup

| Item | Agreed |
|-|-|
| Name | Different from JINKIES!, so the two servers are separate. Client A suggested a name like "Hardcore Server". The Host picked **Crucible**. |
| Resources | Start with extra capacity. Reduce it later, after we know the real usage. |
| Player access | The same VPN process that Client A already uses for JINKIES!. |

#### Price

The Host quoted two prices. The price depends on how many resources the server
needs. Memory is the largest cost.

| Server type | Quoted price |
|-|-|
| Heavy mods (similar to JINKIES!) | 15 per month |
| Few mods | 8 per month |

Client A offered **10 per month** to start. The Host accepted.

- The price can change if the resource needs change.
- If Client A moves to a server with more mods, the price goes up.

#### Payment terms

| Term | Agreed |
|-|-|
| Billing period | Monthly. Client A chose monthly because future plans may change. |
| Due date | The 1st day of each month. |
| Method | PayPal, "Friends and Family" type. This type has no PayPal fee. |
| How it is sent | Client A sends each payment by hand. PayPal does not support automatic payments of the "Friends and Family" type. |
| First month | The Host proposed a partial (prorated) charge for the first month if the server starts mid-month. Client A accepted. |
| Late payment | If a payment is 14 days late, the Host can shut down the server. Client A accepted. |
| Payment address | The Host sent it to Client A in a direct message. It is not stored here. |

### Payment waiver: September 2026 (2026-08-14)

- The Host had to move the servers to a new location. This needed several days
  of full downtime.
- The Host told Client A on 2026-08-14, almost 4 weeks early.
- Because the downtime was long, the Host waived the September 2026 payment.
  Client A does not pay for September 2026.
- Planned downtime (shared on 2026-08-30): stop on 2026-09-09, restore by
  2026-09-14. The servers went down on 2026-09-09.

### Agreement 2: new modpack and price change (2026-09-21)

Made in direct messages on Discord, 2026-09-20 to 2026-09-21.

#### What changed

- The hardcore series ended. Client A started a new project on the same server.
- The new project uses a modpack with more mods: about 58 mods, including
  library mods. Client A may change the pack a little.
- The number of players stays about the same.
- Client A asked if the price should go up for October.

#### Price

- The Host expected the pack to run with the memory the server already had.
- To be safe, the Host offered more memory for **12 per month**.
- Client A accepted the safer option.
- The new price starts with the October 2026 payment.

#### Server setup

| Item | Agreed |
|-|-|
| Memory | Raised from 10Gi to 12Gi. Done on 2026-09-22. |
| Chunky | Client A will add the Chunky mod to the server. Chunky creates the world map before players join. The modpack includes Biomes O' Plenty, and the largest cost of those mods comes when new map areas load. Creating the map early keeps the game fast. |
| Chunky setup | Chunky is a server-only mod. It does not go in the player modpack. Choose the spawn point **before** running Chunky. The Host offered to help. |

### Change history

| Date | Change |
|-|-|
| 2026-06-25 | Agreement 1 made. Price: 10 per month. |
| 2026-06-28 | Server created with a 9Gi memory limit. |
| 2026-08-14 | Memory limit raised from 9Gi to 10Gi after out-of-memory restarts. See [the incident report](../../incidents/minecraft-crucible-oom-kills-inconsistent-rollback.md). The price did not change. |
| 2026-08-14 | September 2026 payment waived because of the planned move. |
| 2026-09-09 | Servers taken down for the move. |
| 2026-09-21 | Agreement 2 made. New modpack. Price: 12 per month from 2026-10-01. |
| 2026-09-22 | Memory limit raised from 10Gi to 12Gi. |

## Support log

Requests from Client A, in date order. Players are not named.

### 2026-08-14: server restarts and mixed rollbacks

| Item | Details |
|-|-|
| Report | About every 1 to 2 hours, the server removed all players and restarted. The number of players did not matter. After each restart, the world went back to different points in time. Broken blocks stayed broken, but players moved back to old positions. A dead player's items were in a chest and also back in the player's inventory. |
| Cause | The memory limit was too tight. The game had the right amount of memory, but only 1 GB was left for everything else in the container. When that space was full, the system stopped the game. There were 2 crashes that day. |
| Fix | Memory limit raised from 9Gi to 10Gi. Now there is 2 GB for everything else. |
| Time to fix | About 35 minutes after the Host started. |
| Follow-up | The Host asked Client A to report any new unexpected restart right away. |
| Details | [Incident report](../../incidents/minecraft-crucible-oom-kills-inconsistent-rollback.md) |

### 2026-08-30: mod loader update

| Item | Details |
|-|-|
| Request | Client A wanted to add a mod (Sweeper Maid) that needs Fabric Loader 0.18.6 or later. The server had 0.18.4. Client A tried to replace the files by hand. This did not work. |
| Fix | The Host updated the loader while the server was empty. The log after the update showed Minecraft 1.21.1 with Fabric Loader 0.19.3. |
| How to do it next time | In Crafty, open the server, then the **Update Center** tab. It makes a backup, then downloads the newest mod loader. Do not replace loader files by hand. |
