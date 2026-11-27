# Division 2 Escalation → Discord

Posts the weekly Escalation missions, each mission's daily drop and the
Requisition vendor caches to a Discord channel once a day.

Data comes from [ProtoTrack.gg Target Loot](https://prototrack.gg/target-loot/target-loot.php),
which volunteers fill in a few minutes after the 08:00 UTC reset.

## How it works

- GitHub Actions runs `escalation.py` every 15 minutes (cron `7,22,37,52 8-15 * * *`, UTC; off the busy quarter-hours, because GitHub skips or delays many runs at :00/:15/:30/:45).
- The script does nothing before **10:00 Berlin time**, so the start time is right in summer and winter.
- It reads the page and compares missions, drops and caches with the last post
  (`state/last_posted.json`). If they changed, it posts and commits the new state.
  If not, the next run 15 minutes later checks again.
- After one post per day it stops. If nothing changed by **16:59 Berlin** it gives up
  for the day (change `GIVE_UP_HOUR` in `escalation.py`).
- If the page layout changes and the script can't find 5 missions, the run fails and
  GitHub emails you.

## Setup

1. **Discord webhook**: in Discord, open the channel's settings → *Integrations* →
   *Webhooks* → *New Webhook*, name it and click *Copy Webhook URL*.
2. **Repository secret**: on GitHub open the repo → *Settings* → *Secrets and variables*
   → *Actions* → *New repository secret*. Name: `DISCORD_WEBHOOK_URL`, value: the URL.
3. **Workflow permissions**: *Settings* → *Actions* → *General* → *Workflow permissions*
   → *Read and write permissions* → *Save* (needed to commit the state file).
4. **Test**: *Actions* tab → *Escalation daily post* → *Run workflow*. With *dry run*
   ticked it only prints what it would post. Untick *dry run* and tick *force* to post now.

## Notes

- GitHub starts scheduled runs late at busy times (often 5–20 minutes, especially on the hour).
- GitHub pauses scheduled workflows in public repos after 60 days without repository activity.
  The daily state commit counts as activity, so this should not happen while it posts.
