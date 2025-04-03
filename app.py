import asyncio
import json
import os
from typing import Callable

from cryptography.fernet import Fernet
import discord
from discord.ext import commands, tasks

from utils.AiohttpManager import AiohttpManager
import utils.config as config
import utils.datasets as datasets
import utils.helpers as helpers
import utils.keepalive as keepalive


# Instantiate Discord bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(
    command_prefix="!flatnotifs ", 
    case_insensitive=True, 
    strip_after_prefix=True, 
    help_command=None, 
    intents=intents,
)

# Environment variables
bot_token = os.environ["DISCORD_BOT_TOKEN"] # Discord bot token
dataset_id = os.environ["DATASET_ID"] # ID of the HF dataset
hf_api_key = os.environ["HF_API_KEY"] # HF API key to access the dataset
fernet = Fernet(os.environ["FERNET_KEY"].encode()) # Fernet key

# Other variables
aiohttp_manager = AiohttpManager()
user_data_changed = False
user_data = datasets.load_dataset(dataset_id, config.datafile_name, hf_api_key)


# Misc functions
def change_interval_calc():
    """Length of user_data times x, unless len(user_data) is 0 then default to y."""
    return (
        len(user_data) * config.delay_amounts["per_user"] 
        if len(user_data) > 0 else config.delay_amounts["per_loop_default"]
    )

def filter_user_data(exclude: set[str]):
    """Don't write any of the excluded properties."""
    return [
        {
            key: value for key, value in user.items() 
            if (key not in exclude)
        }
        for user in user_data
    ]

def get_user(ctx: commands.Context | discord.Message) -> dict | None:
    """Get the user from user_data."""
    for user in user_data:
        if ctx.author.id == int(user["id"]):
            return user
        
def is_registered() -> Callable[[commands.Context], bool]:
    """Registration check decorator."""
    async def func(ctx: commands.Context) -> bool:
        user = get_user(ctx)
        if not user:
            await ctx.channel.send(config.welcome_msg)
        return bool(user)
    
    return commands.check(func)

async def register_user(api_key, message) -> None:
    """Register the user."""
    global user_data_changed
    try: # Read API to see if API key was valid
        elements = await aiohttp_manager.read_api(config.api_url, api_key)
    except Exception as e: # handle edge case http codes
        helpers.log(e, f"during registration of user id {message.author.id} (object?: {message.author})")
        await message.channel.send(
            "Uh oh, there was an error during registration. Please try again later "
            "(if it doesn't resolve on its own soon, please join the bot's "
            f"[Discord server](<{config.discord_url}>) and report the bug!)"
        )
        return
    
    if elements: # If API key was valid
        user = {
            "id": message.author.id,
            "api_key": fernet.encrypt(api_key.encode()).decode(),
            "important": {
                "actor.username": [],
                "type": [],
                "attachments.score.id": []
            },
            "override": False,
            "paused": False,
            "sendhere": {
                "bool": False
            },
            "object": message.author,
            "newest_id": elements[0]["id"]
        }
        user_data.append(user)
        await message.channel.send(
            "Successfully registered! (If you didn't mean to do this, use the command  `!flatnotifs unregister`. "
            "To learn how to start setting rules, use the command  `!flatnotifs help` )"
        )
        user_data_changed = True
        helpers.log(f"User id {user['id']} (object?: {user['object']}) registered, newest element on startup is ID-{elements[0]['id']}") # DEBUG
    else:
        await message.channel.send(
            "Please try again and provide a valid personal token "
            "(double check that the token is still valid and has the notifications.readonly scope!)"
        )


# Loops
@tasks.loop(hours=24)
async def aiohttp_refresh_loop() -> None:
    """Refresh the aiohttp session every 24 hours."""
    await aiohttp_manager.refresh_session()

@tasks.loop(seconds=60)
async def check_notifs_loop() -> None:
    """Check notifications every change_interval_calc seconds."""    
    check_notifs_loop.change_interval(seconds=change_interval_calc())
    global user_data_changed
    if user_data_changed:
        filtered_user_data = filter_user_data(exclude={"object", "newest_id", "channel"})
        datasets.update_dataset(filtered_user_data, dataset_id, config.datafile_name, hf_api_key)
        user_data_changed = False

    for user in user_data:
        if not user["paused"]:
            # Get the newest element and element list
            api_key = fernet.decrypt(user["api_key"].encode()).decode()
            excluded = False
            try:
                elements = await aiohttp_manager.read_api(config.api_url, api_key)
            except Exception as e: # handle edge case http codes
                helpers.log(e)
                continue

            if not user["object"]: # Try to fetch user object if it hasn't been set yet
                try: 
                    user["object"] = await bot.fetch_user(user["id"])
                except Exception as e:
                    user["paused"] = True
                    helpers.log(f"Error, user id {user['id']} (object?: {user['object']}) not found:", e)
                    continue

            if not user["newest_id"]: # Check if user newest id not set
                user["paused"] = True
                user_data_changed = True
                await user["object"].send(config.check_err_msg)
                continue

            if elements: # Check that there are elements
                # Don't loop if the current element matches the newest element
                if elements[0]['id'] != user["newest_id"]:
                    for element in elements:
                        # Break loop if you find the current element that matches the newest element
                        if element['id'] == user["newest_id"]:
                            break

                        # Iterate through important rules, append to triggered_rules
                        is_important = False 
                        triggered_rules = []
                        for category, values in user["important"].items():
                            nested_category = category.split('.') # Split by dots
                            
                            # Iterate until you reach the bottom nested category; if not found, continue to next rule
                            value = element
                            for k in nested_category:
                                value = value.get(k, None)
                                if value is None:
                                    break
                            if value is None:
                                continue
                        
                            # Check if excluded
                            if ("-"+value) in values:
                                excluded = True
                                triggered_rules.append(category + ": -" + value)
                                if not user["override"]:
                                    break

                            # Check if included
                            if ("+"+value) in values:
                                if not excluded:
                                    is_important = True
                                triggered_rules.append(category + ": +" + value)
                            
                        helpers.log(
                            f"{element['actor']['printableName']}: {element['type']}, ID-{element['id']} "
                            f"{'is' if is_important else 'is not'} categorized as important"
                            f"{' by rule(s): ' + str(triggered_rules) if is_important else '.'}"
                        ) # DEBUG

                        # Output once all rules have been iterated through
                        if is_important or user["override"]:
                            # Set url if applicable
                            if element['type'] == "scoreComment":
                                url = element['attachments']['score']['htmlUrl'] + "#c-" + element['attachments']['scoreComment'] + "\n"
                            elif element['type'] in ["scorePublication", "scoreStar", "scoreInvitation"]:
                                url = element['attachments']['score']['htmlUrl'] + "\n"               
                            elif element['type'] == "userFollow":
                                url = element['actor']['htmlUrl'] + "\n"
                            else:
                                url = ""
                        
                            # Compose message
                            m = (
                                f"{helpers.esc_md(element['actor']['printableName'])}: {helpers.esc_md(element['type'])} [(Open on Flat)]({url})\n"
                                f"-# Rule(s): {helpers.esc_md(str(triggered_rules))}"
                            )

                            # Send to user's specified channel if configured else send to user
                            if user["sendhere"]["bool"]:
                                try:
                                    await user["channel"].send(f"{user['object'].mention} {m}")
                                except Exception as e:
                                    helpers.log(f"WARNING: unable to find specified channel for user id {user['id']} (object?: {user['object']}):", e)
                                    user["sendhere"]["bool"] = False
                                    await user["object"].send(config.channel_err_msg)
                                    await user["object"].send(m)
                            else:
                                await user["object"].send(m)

                    # Update newest element after looping through all of the new elements
                    user["newest_id"] = elements[0]["id"]
                    helpers.log(f"Newest id updated to {user['newest_id']} for user id {user['id']} (object?: {user['object']})")

            else: # if no elements
                user["paused"] = True
                user_data_changed = True
                await user["object"].send(config.check_err_msg)
                
            await asyncio.sleep(config.delay_amounts["per_user"]) # wait between checks


# Event handlers
@bot.event
async def on_ready() -> None:
    """Prepare on Discord bot startup."""

    helpers.log("Bot has connected to Discord! :3")

    # Start the aiohttp_refresh task
    helpers.log("Starting aiohttp_refresh_loop...")
    try:
        aiohttp_refresh_loop.start()
    except RuntimeError as e:
        helpers.log("Error starting aiohttp_refresh_loop: ", e)
    
    helpers.log("Processing users...")
    for user in user_data:
        try: # Set users and check the user channel can be reached if specified
            user["object"] = await bot.fetch_user(user["id"])
            try:
                if user["sendhere"]["bool"]:
                    user["channel"] = await bot.fetch_channel(user["sendhere"]["channel_id"])
            except Exception as e:
                helpers.log(f"WARNING: unable to find specified channel for user id {user['id']} (object?: {user['object']}):", e)
                user["sendhere"]["bool"] = False
                await user["object"].send(config.channel_err_msg)
        except Exception as e:
            raise Exception(f"Error getting user id {user['id']} (object?: {user['object']}) or user not found:", e)
        try: # Set newest element per user
            api_key = fernet.decrypt(user["api_key"].encode()).decode()
            elements = await aiohttp_manager.read_api(config.api_url, api_key)
            user["newest_id"] = elements[0]["id"]
            helpers.log(f"Newest element on startup for user id {user['id']} (object?: {user['object']}) is ID-{user['newest_id']}")
        except Exception as e:
            try:
                helpers.log(f"WARNING: unable to check notifications for user id {user['id']} (object?: {user['object']}):", e)
                user["paused"] = True
                await user["object"].send(config.check_err_msg)
            except Exception as e2:
                raise Exception(f"Error sending 'unable to check notifications' message to user id {user['id']} (object?: {user['object']}):", e2)
        await asyncio.sleep(config.delay_amounts["per_user_startup"]) # wait between checks

    # Set bot status
    helpers.log(f"{len(user_data)} user(s) on startup")
    await bot.change_presence(
       status=discord.Status.online, 
       activity=discord.Game(name="with the Flat.io API")
    )

    # Start the check_notifs_loop
    helpers.log("Starting check_notifs_loop...")
    try:
        check_notifs_loop.start()
    except RuntimeError as e:
        helpers.log("Error starting check_notifs_loop: ", e)

@bot.event
async def on_message(message: discord.Message) -> None:
    """Handle commands."""
    message_content = message.content.split()

    # If no message_content (for example, an image or embed), isn't prefixed with !flatnotifs, or is bot user, return
    if not message_content or message_content[0] != "!flatnotifs" or message.author.id == bot.user.id:
        return

    # Get user; if not registered, prompt the user to register
    user = get_user(message)
    if not user:
        if len(message_content) < 3 or not (message_content[1] == "getstarted"):
            # message_content[1] and message_content[2] must exist and only valid command is getstarted
            await message.channel.send(config.welcome_msg)
            return
        if not isinstance(message.channel, discord.DMChannel): # Make sure is in DMs
            await message.channel.send("`!flatnotifs getstarted`  must be used in DMs!")
            return
        api_key = message_content[2] # Register with provided API key
        await register_user(api_key, message)
        return

    # Make sure there is a command after !flatnotifs (i.e. message_content[1] must exist)
    if len(message_content) < 2:
        await message.channel.send(
            "Hello to you too! <3\n"
            "(!flatnotifs is not a valid command by itself; use  `!flatnotifs help`  for a list of valid commands.)"
        )
    else: # Process command
        await bot.process_commands(message)


# Command handlers
@bot.command(description="Add a rule.")
@is_registered()
async def addrule(ctx: commands.Context, include_exclude: str | None = None, category: str | None = None, *input_values: str) -> None:
    if not include_exclude:
        await ctx.send(
            "Please try again and provide include/exclude and a category and value in this format: "
            "`!flatnotifs addrule include/exclude category value`  (include/exclude was missing)"
        )
        return
    if not category or not input_values:
        await ctx.send(
            "Please try again and provide include/exclude and a category and value in this format: "
            "`!flatnotifs addrule include/exclude category value`  (category or value was missing)"
        )
        return
    
    global user_data_changed
    user = get_user(ctx)

    for value in input_values:
        if include_exclude == "include":
            temp = "+"+value
        elif include_exclude == "exclude":
            temp = "-"+value
        else:
            await ctx.send(
                "Please try again and provide include/exclude and a category and value in this format: "
                "`!flatnotifs addrule include/exclude category value`  (first argument was not include or exclude)"
            )
            return
        
        if category in user["important"]:
            user["important"][category].append(temp)
            await ctx.send(f"Rule {helpers.esc_md(category)}: {helpers.esc_md(temp)} added")
            user_data_changed = True
        else:
            await ctx.send(f"Category {helpers.esc_md(category)} not found")

@bot.command(description="Remove a rule.")
@is_registered()
async def removerule(ctx: commands.Context, *input_values: str) -> None:
    if not input_values:
        await ctx.send("Please try again and provide a value in this format:  `!flatnotifs removerule value`")
        return
    
    global user_data_changed
    user = get_user(ctx)
    
    for input_value in input_values:
        found = False
        for category, values in user["important"].items():
            for v in [input_value, ("+"+input_value), ("-"+input_value)]: # check value, +value, and -value
                if v in values:
                    values.remove(v)
                    found = True
                    await ctx.send(f"Rule {helpers.esc_md(v)} removed from {helpers.esc_md(category)}")
                    user_data_changed = True
                    break
        if not found:
            await ctx.send(f"Rule {helpers.esc_md(input_value)} not found")

@bot.command(description="Activate/deactivate overriding of all rules.")
@is_registered()
async def override(ctx: commands.Context) -> None:
    global user_data_changed
    user = get_user(ctx)
    if user["override"]:
        await ctx.send(
            "Override disabled (You will now only be notified of notifications that "
            "match your specified filters. Re-enable by using  `!flatnotifs override`)"
        )
    else:
        await ctx.send(
            "Override enabled (You will now be notified of all notifications. "
            "Disable by using  `!flatnotifs override`)"
        )
    user["override"] = not user["override"]
    user_data_changed = True

@bot.command(description="Pause/unpause notifications.")
@is_registered()
async def pause(ctx: commands.Context) -> None:
    global user_data_changed
    user = get_user(ctx)
    if not user["paused"]:
        await ctx.send("Notifications paused (You will not be notified of any notifications. Unpause by using  `!flatnotifs pause`)")
        user["paused"] = True
        user_data_changed = True
    else:
        try:
            api_key = fernet.decrypt(user["api_key"].encode()).decode()
            elements = await aiohttp_manager.read_api(config.api_url, api_key)
            user["newest_id"] = elements[0]["id"]
            helpers.log(f"Newest element on unpause for user id {user['id']} (object?: {user['object']}) is ID-{user['newest_id']}") # DEBUG
            user["paused"] = False
            user_data_changed = True
            await ctx.send("Notifications unpaused (You will now resume being notified of notifications. Pause by using  `!flatnotifs pause`)")
        except Exception as e:
            try:
                helpers.log(f"WARNING: unable to check notifications for user id {user['id']} (object?: {user['object']}):", e)
                user["paused"] = True
                user_data_changed = True
                await ctx.send(config.check_err_msg)
            except Exception as e2:
                raise Exception(
                    "Error sending 'unable to check notifications on unpause' "
                    f"message to user id {user['id']} (object?: {user['object']}):", e2
                )

@bot.command(description="Change your notification send channel to current channel.")
@is_registered()
async def sendhere(ctx: commands.Context) -> None:
    global user_data_changed
    user = get_user(ctx)
    if user["sendhere"]["bool"]:
        user["sendhere"]["bool"] = False
        await ctx.send("Successfully changed your notification channel back to default (your DMs)")
        user_data_changed = True
    else:
        if isinstance(ctx.channel, discord.DMChannel): # Check that it's not DMs
            await ctx.send("sendhere can only be set in non-DM channels.")
            return
        await ctx.send( # Ask for confirmation
            "Are you sure you want to switch your notification send channel to here? (Y/N)\n"
            "If this is a public channel, that means anyone can see the notifications that the bot sends you."
        )

        def check(m: discord.Message) -> bool:
            """Function to check that it's still the same user in the same channel"""
            helpers.log(m.author, "sendhere check:", (m.author.id == ctx.author.id and m.channel.id == ctx.channel.id)) # DEBUG
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id 
            
        try: # Wait 30 sec for a message that meets the check() requirement 
            msg = await bot.wait_for("message", check=check, timeout=30)
        except Exception as e:
            helpers.log("WARNING: sendhere timeout:", e)
            await ctx.send("Cancelling sendhere (no response for 30 sec)")
            return
        else:
            if msg.content.upper() == "Y": # Change user's notification channel
                try:
                    user["sendhere"]["channel_id"] = ctx.channel.id
                    user["channel"] = ctx.channel
                    await user["channel"].send(
                        "Successfully changed your notification channel to this channel. "
                        "You can disable this at any time using /sendhere"
                    )
                    user["sendhere"]["bool"] = True
                    user_data_changed = True
                except Exception as e:
                    helpers.log(f"Error setting sendhere for user id {user['id']} (object?: {user['object']}):", e)
                    await ctx.send("[DEBUG]: Oops, there was an error while setting sendhere!")
            else:
                await ctx.send("Cancelling sendhere (received a response other than 'Y')")

@bot.command(description="Unregister, permanently deleting your rules and API key from the bot.")
@is_registered()
async def unregister(ctx: commands.Context) -> None:
    global user_data_changed
    user = get_user(ctx)
    await ctx.send( # Ask for confirmation
        "Are you sure you want to unregister? (Y/N)\n"
        "Unregistering means that you will lose any rules that you have set and will no longer receive notifications from this bot. "
        "Only unregister if you don't want to receive notifications from this bot anymore or if you need to change your personal token."
    )

    def check(m: discord.Message) -> bool:
        """Function to check that it's still the same user in the same channel"""
        helpers.log(m.author, "unregister check:", (m.author.id == ctx.author.id and m.channel.id == ctx.channel.id)) # DEBUG
        return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id 
    
    try: # Wait 30 sec for a message that meets the check() requirement 
        msg = await bot.wait_for("message", check=check, timeout=30)
    except Exception as e:
        helpers.log("WARNING: unregister timeout:", e)
        await ctx.send("Cancelling unregister (no response for 30 sec)")
        return
    else:
        if msg.content.upper() == "Y": # Unregister the user
            try:
                user_data.remove(user)
                await ctx.send("Successfully unregistered. You can re-register by using the command /getstarted")
                user_data_changed = True
            except Exception as e:
                helpers.log(f"Error unregistering for user id {user['id']} (object?: {user['object']}):", e)
                await ctx.send("[DEBUG]: Oops, there was an error during unregistering!")
        else:
            await ctx.send("Cancelling unregister (received a response other than 'Y')")

@bot.command(description="Update your personal token.")
@is_registered()
async def updatetoken(ctx: commands.Context, api_key: str | None = None) -> None:
    global user_data_changed
    user = get_user(ctx)
    if not isinstance(ctx.channel, discord.DMChannel): # Make sure is in DMs
        await ctx.send("`!flatnotifs updatetoken` must be used in DMs!")
        return
    if api_key is None:
        await ctx.send("Please provide your new personal token.")
        return
    await ctx.send( # Ask for confirmation
        "Are you sure you want to update your personal token? (Y/N)\n"
        "Updating your personal token will invalidate your old token. "
        "Make sure your new personal token is valid!"
    )

    def check(m: discord.Message) -> bool:
        """Function to check that it's still the same user in the same channel"""
        helpers.log(m.author, "updatetoken check:", (m.author.id == ctx.author.id and m.channel.id == ctx.channel.id)) # DEBUG
        return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id 
    
    try: # Wait 30 sec for a message that meets the check() requirement 
        msg = await bot.wait_for("message", check=check, timeout=30)
    except Exception as e:
        helpers.log("WARNING: updatetoken timeout:", e)
        await ctx.send("Cancelling updatetoken (no response for 30 sec)")
        return
    else:
        if msg.content.upper() == "Y": # Update the user's token
            try: # Read API to see if API key was valid
                elements = await aiohttp_manager.read_api(config.api_url, api_key)
            except Exception as e: # handle edge case http codes
                helpers.log(e, f"during updatetoken of user id {ctx.author.id} (object?: {ctx.author})")
                await ctx.channel.send(
                    "Uh oh, there was an error during updatetoken. Please try again later "
                    "(if it doesn't resolve on its own soon, please join the bot's "
                    f"[Discord server](<{config.discord_url}>) and report the bug!)"
                )
                return
            
            if elements: # If API key was valid
                user["api_key"] = fernet.encrypt(api_key.encode()).decode()
                user["newest_id"] = elements[0]["id"]
                await ctx.send("Successfully updated your personal token!")
                user_data_changed = True
                helpers.log(f"User id {user['id']} (object?: {user['object']}) updated token, newest element on startup is ID-{elements[0]['id']}") # DEBUG
            else:
                await ctx.send(
                    "Please try again and provide a valid personal token "
                    "(double check that the token is still valid and has the notifications.readonly scope!)"
                )
        else:
            await ctx.send("Cancelling updatetoken (received a response other than 'Y')")

@bot.command(description="Show all rules that you have set.")
@is_registered()
async def rules(ctx: commands.Context) -> None:
    user = get_user(ctx)
    # chr(10) is used in place \n to ensure compatibility with older versions of Python that don't allow escape chars in an f-string
    await ctx.author.send(
        f"Rules: {helpers.esc_md(json.dumps(user['important'], indent=4))}"
        f"{chr(10)+'Override is currently enabled (disable by using /override)' if user['override'] else ''}"
        f"{chr(10)+'Notifications are currently paused (unpause by using /pause)' if user['paused'] else ''}"
    )

@bot.command(description="Show the version of the bot.")
@is_registered()
async def version(ctx: commands.Context) -> None:
    await ctx.send(config.version_msg)

@bot.command(description="Show all valid commands.")
@is_registered()
async def help(ctx: commands.Context) -> None:
    # split into two messages because of Discord message max length
    await ctx.channel.send(config.help_msg[0])
    await ctx.channel.send(config.help_msg[1])

@bot.command(description="Sync the command tree.")
@commands.is_owner()
async def sync(ctx: commands.Context) -> None:
    synced = await bot.tree.sync()
    await ctx.send(f"Synced {len(synced)} commands")

@bot.hybrid_command(description="Hello world!")
async def hello(ctx: commands.Context) -> None:
    await ctx.send("Hello world!")

@bot.event
async def on_command_error(ctx: commands.Context, error: discord.ext.commands.errors.CommandError):
    if isinstance(error, discord.ext.commands.errors.CommandNotFound):
        await ctx.send(
            "Whoops! That command was invalid.\n"
            "(Use  `!flatnotifs help`  for a list of valid commands. Make sure the command is spelled correctly!)"
        )


if __name__ == "__main__":
    # Start keepalive and run Discord bot
    keepalive.run()
    bot.run(bot_token)

    # If CTRL-C, clean up
    asyncio.run(aiohttp_manager.close_session())