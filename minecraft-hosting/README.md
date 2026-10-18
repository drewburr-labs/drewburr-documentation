# Minecraft Server Hosting

Last updated: 2026-10-18

I host private Minecraft servers for small groups. Prices start at $5 USD a month, based on how much memory your server needs. You pay monthly, with no contract.

## What you get

Each group gets its own server. It does not share memory or files with other groups.

| Feature | Details |
| --- | --- |
| Server address | Players join at `<name>.mc.drewburr.com`. |
| Control panel | A web panel (Crafty Controller) at `<name>.crafty.drewburr.com`. Start, stop, and restart the server, use the console, edit files, and manage players. |
| Mod loaders | Vanilla, Fabric, Forge, NeoForge, or Paper. Modpacks from Modrinth or CurseForge are fine. |
| Updates | The panel's Update Center makes a backup, then installs the newest server or mod loader version. |
| Backups | Run from the panel, on a schedule or by hand. You can restore an older copy of the world. |
| Storage | 100 GB for the server and world files, and 200 GB for backups. I can add more if you need it. |
| File access | SFTP access to the server files, over a private VPN. |
| Voice chat | Voice chat mods (for example, Simple Voice Chat) are supported. |
| Live map | Optional web map of the world (BlueMap) at `<name>.map.drewburr.com`. |
| Monitoring | I watch memory and CPU use, and I tune the server when it needs it. |

The servers run on my own hardware: a Kubernetes cluster with enterprise SSD storage on a 10 Gb network.

## Pricing

The price depends on memory. More mods and more players need more memory. Here's a general guideline I use to pick a memory size:

| Tier | Memory | Good for | Price per month (USD) |
| --- | --- | --- | --- |
| Feather | 4 GB | Vanilla, up to 5 players | $5 |
| Light | 6 GB | Vanilla with up to 15 players, or up to about 25 mods | $8 |
| Medium | 10 GB | Up to about 60 mods and 10 players | $12 |
| Heavy | 16 GB | Up to about 150 mods and 10 players | $15 |
| Larger | More than 16 GB | More than 150 mods, or more than 10 players with mods | Ask for a quote |

Memory is what the game gets: the maximum memory setting for the Minecraft server. I add 2 GB on top, at no cost, for Java and the control panel.

- **The price follows the size.** If you change modpacks or add players, we agree on a new size and price together. The new price starts on the next 1st of the month.
- **Fixes are free.** If the server crashes because I set the memory too low, I add memory at no extra cost.
- **Storage can change the price.** If the world or backups grow far beyond the storage limits, we may need to change the price.

## Billing and payment

Payment is due on the 1st of each month. There is no contract, and you can stop at any time.

| Term | Details |
| --- | --- |
| Billing period | Monthly. |
| Due date | The 1st day of each month. |
| First month | If your server starts mid-month, you pay only for the days that are left. |
| Payment methods | PayPal, Venmo, or Zelle. PayPal works from outside the US. Ask me if you need a different method. |
| How to pay | You send each payment yourself. There is no automatic charge. |
| Late payment | If a payment is 14 days late, I stop the server. Your files are kept for 30 days. The server starts again when the payment arrives. |
| Long outages | If my work causes a long outage, such as moving my hardware, I reduce or skip that month's payment. |

## Who does what

You run the game. I run the hardware and keep the server healthy.

| Area | You | Me |
| --- | --- | --- |
| Mods and modpacks | Choose, add, and update them. | Help when a mod will not load. |
| Game settings | World settings, rules, and plugins. | Advice when you ask. |
| Players | Whitelist, operators, and bans. | Nothing. |
| Server and loader versions | Start updates from the Update Center. | Help if an update fails. |
| Backups | Take one before big changes. | Keep backup storage running. |
| Storage | Keep the world and backups within the limits. | Watch disk use. If it makes sense, I may ask you to change the backup schedule or delete old backups. |
| Memory and performance | Tell me when you change modpacks or player count. | Size and tune the server. Fix crashes caused by settings. |
| Hardware, network, and storage | Nothing. | All of it. |
| VPN access (when required) | Install the VPN app. | Set up your access. |

Tip for large or modded worlds: pre-generate the map with the Chunky mod before players join. It keeps the game fast. Choose the spawn point first.

## Support and downtime

Message me on Discord. I usually answer the same day, but this is a one-person service, not a 24/7 help desk.

- **Problems:** Tell me what happened and when. Unexpected restarts, lost progress, or lag are good reasons to message me right away.
- **Changes:** I do updates and restarts when the server is empty, or at a time we agree on.
- **Planned maintenance:** I tell you at least one week before. For long work, I give the exact dates when I know them.
- **Uptime:** I keep the servers running all the time, but I cannot promise a set uptime. Power or internet outages at my location can stop the server.

## Getting started

Send me these details, and I will reply with a size and a monthly price.

- [ ] How many players, and how many are online at the same time
- [ ] Minecraft version and mod loader (if using mods)
- [ ] The modpack file or mod list, or "vanilla"
- [ ] Any server-side mods that need ports open, such as voice chat
- [ ] A short name for the server, used for its addresses
- [ ] When you want to start

After you accept the price:

1. I create the server, the control panel, and your panel login.
2. I set up VPN access for you, if it's required.
3. You upload your world or modpack, or start a new world.
4. You send the first (partial) payment.
5. After a few sessions, I check memory use and confirm the size.

## Ending service

To stop, tell me before the 1st of the month. You do not pay for the next month.

- The server keeps running until the end of the month you paid for.
- Before I delete anything, you can download your world and files from the panel. I can also send you a backup.
- After the server stops, I keep your files for 30 days, then delete them.
