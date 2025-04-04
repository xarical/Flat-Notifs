host = "0.0.0.0"
port = 7860

datafile_name = "data.json"

#FIXME: As you scale, 30 or even 15 seconds per user might be too long
delay_amounts = {
    "per_loop_default": 60,
    "per_user": 30,
    "per_user_startup": 15
}

#FIXME: What if more than 20 notifications were sent within the loop interval?
api_url = f"https://api.flat.io/v2/me/notifications?expand=actor,score&returnOptInScoresInvitations=true&limit=20"
discord_url = "https://discord.gg/s5xXz8Nfun"

version_msg = f"""
**Current version:**
v2025.x.xx - Mention flag added to sendhere, refactor to use user IDs instead of usernames, bug fixes

**Previous version:**
v2025.3.13 - Handle API and server errors more gracefully, improve maintainability of codebase

*(Go to the bot's [Discord server](<{discord_url}>) for more details and older patch notes!)*
"""

check_err_msg = """
[DEBUG]: Unable to check your notifications! Did you delete your personal token? (If not, this is probably just a result of a server error)
(Automatically pausing to avoid spamming; you can use  `!flatnotifs pause`  to unpause)
"""

channel_err_msg = """
[DEBUG]: Unable to find your specified channel! Was the channel deleted, or did the bot lose access to it?
(Defaulting to DMs to avoid spamming; you can use  `!flatnotifs sendhere`  again to pick a channel to send notifications)
"""

welcome_msg = f"""
Welcome to Flat.io Notifs! Please provide a personal token in this format:  `!flatnotifs getstarted token`  (where token is your personal token).
To get a personal token: 1. Go to the [Flat.io Developers portal](https://flat.io/developers/apps), 2. Create a new app if you don't have one already, 3. Go to Personal Tokens, 4. Create a new token and add the notifications.readonly scope, 5. Copy the token that appears.
Note that getstarted can only be used in DMs. Remember to never send your personal token in a public channel! It can give other people access to your account's information. If you exposed your personal token, go delete it in the [Flat.io Developers portal](https://flat.io/developers/apps) and create a new one.
*(Need help? Join the bot's [Discord server](<{discord_url}>)!)*
"""

help_msg = [ f"""
**Help**

Welcome to Flat Notifs! This a bot that sends your Flat notifications directly to your Discord DMs or a channel in a server that you specify (that this bot has been added to)! In addition, it allows you to filter by user, notification type, and score id.

""",
f"""
**Available commands:**
`!flatnotifs addrule include/exclude category value`  (Add a rule. More than one value can be specified, seperated by spaces)
`!flatnotifs removerule value`  (Remove a rule. More than one value can be specified, seperated by spaces)
`!flatnotifs override`  (Override the rules you have set. The bot will notify you of all notifications. Use the same command to toggle on and off)
`!flatnotifs pause`  (Pause notifications. The bot will not notify you of any notifications. Use the same command to toggle on and off)
`!flatnotifs sendhere mention/nomention`  (Set your notifications to send in the channel where the command was sent. Use the same command to toggle on and off. When toggling on, specify whether you want to be @ mentioned)
`!flatnotifs unregister`  (Unregister and delete all of your information including your personal token, rules, and other preferences)
`!flatnotifs updatetoken token`  (Update your personal token)
`!flatnotifs rules`  (Show all rules you have set)
`!flatnotifs version`  (Show patch notes for the current and previous version)
`!flatnotifs help`  (You are here!)

**Available categories/values (for addrule and removerule):**
`actor.username`  (Flat.io username, without the @ sign. e.g. `actor.username flat`)
`type`  (Type of notification. Options: scorePublish, scoreComment, scoreStar, userFollow. e.g. `type userFollow`)
`attachments.score.id`  (id of a score, without the name. e.g. `attachments.score.id 623f2fab79ac0e0012b95dc8`)

*Answer not here, have feedback, or want to help with development? Join the bot's [Discord server](<{discord_url}>)!*
*(Go there to contact the developer, as well as to get access to the full patch notes, TODO, and known issues lists!)*

-# *Disclaimer: Flat Notifs is not made by Flat.io. It is a project that uses the Flat.io API, made by a member of the community. Additionally, it is not guaranteed to be free of bugs, be updated frequently, or even work. Updates may introduce breaking changes. Logs are collected for debug purposes.*
"""
] # split into two messages because of Discord message max length