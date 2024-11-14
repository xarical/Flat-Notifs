# pip install --quiet cryptography datasets discord.py flask requests

import asyncio
from datetime import datetime, timezone
import json
import os
from threading import Thread

from cryptography.fernet import Fernet
from datasets import load_dataset
import discord
from discord.ext import commands, tasks
from flask import Flask
from huggingface_hub import HfApi
import requests


# Instantiate Discord bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)


# Environment variables
bot_token = os.environ["DISCORD_BOT_TOKEN"] # Discord bot token, expected type: string
dataset_id = os.environ["DATASET_ID"] # ID of the HF dataset, expected type: string
hf_api_key = os.environ["HF_API_KEY"] # HF API key to access the dataset, expected type: string
f = Fernet(os.environ["FERNET_KEY"].encode()) # Fernet key for encryption/decryption, expected type: string


# Other variables
user_data_changed = False
ready = False


""" <-- Functions --> """

# Function to add datetime to print() (use this instead of print())
def dt_print(*args, **kwargs) -> None:
  print(f"[{datetime.now(timezone.utc).date().strftime('%Y-%m-%d')}], [{datetime.now(timezone.utc).strftime('%H:%M:%S')}] -", *args, **kwargs)


# Function to escape markdown
def esc_md(text: str) -> str:
    escape_chars = ['*', '_', '~', '`', '|', '>', '[', ']', '(', ')', '#', '-', '+', '.']
    for char in escape_chars:
        text = text.replace(char, f'\\{char}')
    return text


# Function to update the HF dataset
def update_ds() -> None:
  # Filter user_data and then dump into a data.json file
  with open('data.json', 'w') as file:
    filtered_array = [{key: value for key, value in user.items() if (key != 'object' and key != 'newest_id' and key != 'channel')} for user in user_data]
    json.dump(filtered_array, file, indent=4)

  # Upload data.json to the HF dataset
  api = HfApi()
  api.upload_file(
      path_or_fileobj="data.json",
      path_in_repo="data.json",
      repo_id=dataset_id,
      repo_type="dataset",
      commit_message="Update data.json 🤖",
      token=hf_api_key
  )
  dt_print("Database updated!")


# Function to get the contents of the api
def read_api(token: str) -> list[dict]:
  headers = {'Authorization': 'Bearer ' + token}
  try:
    response = requests.get(
      "https://api.flat.io/v2/me/notifications?expand=actor,score&returnOptInScoresInvitations=true&limit=10", 
      headers=headers  
    )
    response.raise_for_status()
    return response.json()
  
  except requests.exceptions.RequestException as e:
    dt_print("API request error:", e)
    return []
    
  except ValueError as e:
    dt_print("JSON parsing error:", e)
    return []


""" <-- Startup --> """

# Print datetime of startup
dt_print("Hello world!") # DEBUG

# Load and reconstruct the user_data from the HF dataset
try:
  dataset = load_dataset(dataset_id, token=hf_api_key)
  unprocessed_data = dataset['train'].to_dict()

  user_data = []
  for i in range(len(unprocessed_data["id"])):
    user_data.append({
          "id": unprocessed_data["id"][i],
          "api_key": unprocessed_data["api_key"][i],
          "important": unprocessed_data["important"][i],
          "override": unprocessed_data["override"][i],
          "paused": unprocessed_data["paused"][i],
          "sendhere": unprocessed_data["sendhere"][i]
      })
    
except Exception as e:
  dt_print("WARNING: dataset is empty or does not exist(?):", e)
  user_data = []


""" <-- Discord --> """

# Check notifications loop
@tasks.loop(seconds=60)
async def check_notifs() -> None:
  # Set interval to the length of user_data times 15, unless user_data is 0 then default to 60
  check_notifs.change_interval(seconds=(len(user_data)*15 if len(user_data) > 0 else 60))

  # dt_print("checking") # DEBUG

  # If there've been any changes to user_data, update dataset
  global user_data_changed
  if user_data_changed:
    update_ds()
    user_data_changed = False

  for user in user_data:
    if not user["paused"]:
      # Get the newest element and element list
      api_key = f.decrypt(user["api_key"].encode()).decode()
      elements = read_api(api_key)
      excluded = False

      if not user["object"]:
        try: 
          user["object"] = await bot.fetch_user(user["id"])

        except Exception as e:
          user["paused"] = True
          dt_print(f"Error, user id {user['id']} (object?: {user['object']}) not found:", e)
          continue

      if not user["newest_id"]:
        user["paused"] = True
        user_data_changed = True
        await user["object"].send("[DEBUG]: Unable to check your notifications! Did you delete your personal token? (If not, this is probably just a result of a server error or restart)\n(Automatically pausing to avoid spamming you; you can use  `/flatnotifs pause`  to unpause)")
        continue

      if elements:
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
              # Split by dots
              nested_category = category.split('.')

              # Iterate until you reach the bottom nested category
              value = element
              for k in nested_category:
                value = value.get(k, None)
                if value is None:
                  dt_print(f"Couldn't iterate to {category} in {element} for user id {user['id']} (object?: {user['object']})")
                  break

              if value is None:
                continue
              
              # Check if excluded
              if ("-"+value) in values:
                excluded = True
                triggered_rules.append(category + ": -" + value)
                if not user["override"]: # break early since the user is never going to see the triggered_rules list anyway
                  break

              # Check if included
              if (("+"+value) in values) or (value in values): # retain support for legacy system that doesn't have + or - prepended
                if not excluded:
                  is_important = True
                triggered_rules.append(category + ": +" + value)
                
            dt_print(f"{element['actor']['printableName']}: {element['type']}, ID-{element['id']} {'is' if is_important else 'is not'} categorized as important{' by rule(s): ' + str(triggered_rules) if is_important else '.'}") # DEBUG
            # Output
            if is_important or user["override"]:
              if element['type'] == "scoreComment":
                url = element['attachments']['score']['htmlUrl'] + "#c-" + element['attachments']['scoreComment'] + "\n"

              elif element['type'] == "scorePublication" or element['type'] == "scoreStar":
                url = element['attachments']['score']['htmlUrl'] + "\n"
                
              elif element['type'] == "userFollow":
                url = element['actor']['htmlUrl'] + "\n"

              else:
                url = ""
                
              n = f"{esc_md(element['actor']['printableName'])}: {esc_md(element['type'])} [(Open on Flat)]({url})\n-# Rule(s): {esc_md(str(triggered_rules))}"

              if user["sendhere"]["bool"]:
                try:
                  await user["channel"].send(f"{user['object'].mention} {n}")
                  
                except Exception as e:
                  dt_print(f"WARNING: unable to find specified channel for user id {user['id']} (object?: {user['object']}):", e)
                  user["sendhere"]["bool"] = False
                  await user["object"].send("[DEBUG]: Unable to find your specified channel! Was the channel deleted, or did the bot lose access to it?\n(Defaulting to DMs to avoid spamming you; you can use  `/flatnotifs sendhere`  again to pick a channel to send notifications)")
                  await user["object"].send(n)

              else:
                await user["object"].send(n)

          # Update newest element after looping through all of the new elements
          user["newest_id"] = elements[0]["id"]
          dt_print(f"Newest id updated to {user['newest_id']} for user id {user['id']} (object?: {user['object']})")

      else:
        user["paused"] = True
        user_data_changed = True
        await user["object"].send("[DEBUG]: Unable to check your notifications! Did you delete your personal token? (If not, this is probably just a result of a server error or restart)\n(Automatically pausing to avoid spamming you; you can use  `/flatnotifs pause`  to unpause)")
          
      await asyncio.sleep(30) # wait between checks


# On Discord bot startup
@bot.event
async def on_ready() -> None:
  dt_print("Bot has connected to Discord! :3")

  # Set users and test that users can be reached
  for user in user_data:
    try:
      user["object"] = await bot.fetch_user(user["id"])
      # await user["object"].send("[DEBUG]: Flat Notifs is restarting... (just checking that the bot can still reach you)")

      try:
        if user["sendhere"]["bool"]:
          user["channel"] = await bot.fetch_channel(user["sendhere"]["channel_id"])

      except Exception as e:
        dt_print(f"WARNING: unable to find specified channel for user id {user['id']} (object?: {user['object']}):", e)
        user["sendhere"]["bool"] = False
        await user["object"].send("[DEBUG]: Unable to find your specified channel! Was the channel deleted, or did the bot lose access to it?\n(Defaulting to DMs to avoid spamming you; you can use  `/flatnotifs sendhere`  again to pick a channel to send notifications)")

    except Exception as e:
      raise Exception(f"Error sending startup message to user id {user['id']} (object?: {user['object']}) or user not found:", e)


  # Get the newest element in the notifications
  for user in user_data:
    try:
      api_key = f.decrypt(user["api_key"].encode()).decode()
      elements = read_api(api_key)
      user["newest_id"] = elements[0]["id"]
      dt_print(f"Newest element on startup for user id {user['id']} (object?: {user['object']}) is ID-{user['newest_id']}") # DEBUG
      
    except Exception as e:
      try:
        dt_print(f"WARNING: unable to check notifications for user id {user['id']} (object?: {user['object']}):", e)
        user["paused"] = True
        await user["object"].send("[DEBUG]: Unable to check your notifications! Did you delete your personal token? (If not, this is probably just a result of a server error or restart)\n(Automatically pausing to avoid spamming you; you can use  `/flatnotifs pause`  to unpause)")
      except Exception as e2:
        raise Exception(f"Error sending 'unable to check notifications' message to user id {user['id']} (object?: {user['object']}):", e2)

    await asyncio.sleep(15) # wait between checks

  # Set bot status
  global ready
  ready = True
  game = discord.Game(name="with the Flat.io API")
  await bot.change_presence(status=discord.Status.online, activity=game)
  dt_print(f"{len(user_data)} user(s) on startup")

  # Start the check_notifs task
  dt_print("Watching notifs...")
  check_notifs.start()


# Handle messages from the user (allow user to run commands to configure their notif settings)
@bot.event
async def on_message(message: discord.Message) -> None:
  global user_data_changed
  message_content = message.content.split()

  # If no message_content (for example, an image or embed), isn't prefixed with /flatnotifs, or is bot user, return
  if not message_content or message_content[0] != "/flatnotifs" or message.author.id == bot.user.id:
    return

  # If bot isn't ready yet, return
  if not ready:
    dt_print(f"User id {message.author.id} (object?: {message.author}) (on_message) Not ready yet") # DEBUG
    return


  """ <-- User identification/registration --> """

  # If user is registered, set user
  registered = False
  for u in user_data: # using u instead of user so we can save the user var
    if message.author.id == int(u["id"]):
      registered = True
      user = u
      break


  # If not registered, prompt the user to register
  if not registered:
    # Make sure is in DMs
    if not isinstance(message.channel, discord.DMChannel):
      await message.channel.send("""
Welcome to Flat.io Notifs! Please provide a personal token in this format:  `/flatnotifs getstarted token`.
To get a personal token: 1. Go to the [Flat.io Developers portal](https://flat.io/developers/apps), 2. Create a new app if you don't have one already, 3. Go to Personal Tokens, 4. Create a new token and add the notifications.readonly scope, 5. Copy the token that appears.
Note that getstarted can only be used in DMs. Remember to never send your personal token in a public channel! It can give other people access to your account's information. If you exposed your personal token, go delete it in the [Flat.io Developers portal](https://flat.io/developers/apps) and create a new one.
(Need help? Join to the bot's [Discord server](<https://discord.gg/s5xXz8Nfun>)!)
""")
      return
      
    # Only valid command is getstarted, and message_content[1] and message_content[2] must exist
    if not (message_content[1] == "getstarted") or len(message_content) < 3:
      await message.channel.send("""
Welcome to Flat.io Notifs! Please provide a personal token in this format:  `/flatnotifs getstarted token`  (where token is your personal token).
To get a personal token: 1. Go to the [Flat.io Developers portal](https://flat.io/developers/apps), 2. Create a new app if you don't have one already, 3. Go to Personal Tokens, 4. Create a new token and add the notifications.readonly scope, 5. Copy the token that appears.
(Need help? Join the bot's [Discord server](<https://discord.gg/s5xXz8Nfun>)!)
""")
      return

    # If API key has been provided and is valid, register
    api_key = message_content[2]
    elements = read_api(api_key)

    if elements:
      user = message.author
      user_data.append({
        "id": message.author.id,
        "api_key": f.encrypt(api_key.encode()).decode(),
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
        "object": user,
        "newest_id": elements[0]["id"]
      })

      await message.channel.send("Successfully registered! (If you didn't mean to do this, use the command  `/flatnotifs unregister`. To learn how to start setting rules, use the command  `/flatnotifs help` )")
      user_data_changed = True
      dt_print(f"User id {user['id']} (object?: {user['object']}) registered, newest element on startup is ID-{elements[0]['id']}") # DEBUG
      return

    else:
      await message.channel.send("Please try again and provide a valid personal token (double check that the token is still valid and has the notifications.readonly scope!)")
      return


  """ <--- Commands ---> """

  # Make sure there is a command after /flatnotif (i.e. message_content[1] must exist)
  if len(message_content) < 2:
    await message.channel.send("Hello to you too! <3\n(/flatnotif is not a valid command by itself; use  `/flatnotifs help`  for a list of valid commands.)")
    return

  # Add a rule
  if message_content[1] == "addrule":
    try:
      include_exclude = message_content[2]
      category = message_content[3]
      input_values = message_content[4:]

      for input_value in input_values:
        if include_exclude == "include":
          temp = "+"+input_value

        elif include_exclude == "exclude":
          temp = "-"+input_value

        else:
          await message.channel.send("Please try again and provide include/exclude and a category and value in this format: `/flatnotifs addrule include/exclude category value`  (first parameter was not include or exclude)")
          return
        
        if category in user["important"]:
          user["important"][category].append(temp)
          await message.channel.send(f"Rule {esc_md(category)}: {esc_md(temp)} added")
          user_data_changed = True

        else:
          await message.channel.send(f"Category {esc_md(category)} not found")

    except IndexError:
      await message.channel.send("Please try again and provide include/exclude and a category and value in this format:  `/flatnotifs addrule include/exclude category value`  (category or value was missing)")


  # Remove a rule
  elif message_content[1] == "removerule":
    try:
      input_values = message_content[2:]

      for input_value in input_values:
        found = False
        for category, values in user["important"].items():
          for v in [input_value, ("+"+input_value), ("-"+input_value)]: # check value, +value, and -value
            if v in values:
              values.remove(v)
              found = True
              await message.channel.send(f"Rule {esc_md(v)} removed from {esc_md(category)}")
              user_data_changed = True
              break

        if not found:
          await message.channel.send(f"Rule {esc_md(input_value)} not found")

    except IndexError:
      await message.channel.send("Please try again and provide a value in this format:  `/flatnotifs removerule value`")
  

  # Override all rules
  elif message_content[1] == "override":
    if user["override"]:
      await message.channel.send("Override disabled (You will now only be notified of notifications that match your specified filters. Re-enable by using  `/flatnotifs override)`")
      
    else:
      await message.channel.send("Override enabled (You will now be notified of all notifications. Disable by using  `/flatnotifs override)`")

    user["override"] = not user["override"]
    user_data_changed = True


  # Pause notifications
  elif message_content[1] == "pause":
    if user["paused"]:
      try:
        api_key = f.decrypt(user["api_key"].encode()).decode()
        elements = read_api(api_key)
        user["newest_id"] = elements[0]["id"]
        dt_print(f"Newest element on unpause for user id {user['id']} (object?: {user['object']}) is ID-{user['newest_id']}") # DEBUG
        user["paused"] = False
        user_data_changed = True
        await message.channel.send("Notifications unpaused (You will now resume being notified of notifications. Pause by using  `/flatnotifs pause)`")
      
      except Exception as e:
        try:
          dt_print(f"WARNING: unable to check notifications for user id {user['id']} (object?: {user['object']}):", e)
          user["paused"] = True
          user_data_changed = True
          await message.channel.send("[DEBUG]: Unable to check your notifications (on unpause)! Did you delete your personal token? (If not, this is probably just a result of a server error or restart)\n(Automatically pausing to avoid spamming you; you can use  `/flatnotifs pause`  to unpause)")
        except Exception as e2:
          raise Exception(f"Error sending 'unable to check notifications on unpause' message to user id {user['id']} (object?: {user['object']}):", e2)

    else:
      await message.channel.send("Notifications paused (You will not be notified of any notifications. Unpause by using  `/flatnotifs pause)`")
      user["paused"] = True
      user_data_changed = True


  # Change notif send channel to here
  elif message_content[1] == "sendhere":
    if user["sendhere"]["bool"]:
      user["sendhere"]["bool"] = False
      await message.channel.send("Successfully changed your notification channel back to default (your DMs)")
      user_data_changed = True

    else:
      # Check that it's not DMs
      if not isinstance(message.channel, discord.DMChannel):
        # Ask for confirmation
        await message.channel.send("Are you sure you want to switch your notification send channel to here? (Y/N)\nIf this is a public channel, that means anyone can see the notifications that the bot sends you.")

        # Function to check that it's still the same user in the same channel
        def check(m: discord.Message) -> bool:
          dt_print(m.author, "sendhere check:", (m.author.id == message.author.id and m.channel.id == message.channel.id)) # DEBUG
          return m.author.id == message.author.id and m.channel.id == message.channel.id 
        
        # Wait 30 sec for a message that meets the check() requirement 
        try:
          msg = await bot.wait_for("message", check=check, timeout=30)

        except Exception as e:
          dt_print("WARNING: timeout(?):", e)
          await message.channel.send("Cancelling sendhere (no response for 30 sec)")
          return
        
        else:
          # Take action based on user response
          if msg.content.upper() == "Y":
            try:
              user["sendhere"]["channel_id"] = message.channel.id
              user["channel"] = message.channel
              await user["channel"].send("Successfully changed your notification channel to this channel. You can disable this at any time using /sendhere")
              user["sendhere"]["bool"] = True
              user_data_changed = True

            except Exception as e:
              dt_print(f"Error setting sendhere for user id {user['id']} (object?: {user['object']}):", e)
              await message.channel.send("[DEBUG]: Oops, there was an error while setting sendhere!")

          else:
            await message.channel.send("Cancelling sendhere (received a response other than 'Y')")
      else:
        await message.channel.send("sendhere can only be used in channels.")


  # Unregister
  elif message_content[1] == "unregister":
    # Ask for confirmation
    await message.channel.send("Are you sure you want to unregister? (Y/N)\nUnregistering means that you will lose any rules that you have set and will no longer receive notifications from this bot. Only unregister if you don't want to receive notifications from this bot anymore or if you need to change your personal token")

    # Function to check that it's still the same user in the same channel
    def check(m: discord.Message) -> bool:
      dt_print(m.author, "unregister check:", (m.author.id == message.author.id and m.channel.id == message.channel.id)) # DEBUG
      return m.author.id == message.author.id and m.channel.id == message.channel.id 
    
    # Wait 30 sec for a message that meets the check() requirement 
    try:
      msg = await bot.wait_for("message", check=check, timeout=30)

    except Exception as e:
      dt_print("WARNING: timeout(?):", e)
      await message.channel.send("Cancelling unregister (no response for 30 sec)")
      return
    
    else:
      # Take action based on user response
      if msg.content.upper() == "Y":
        try:
          user_data.remove(user)
          await message.channel.send("Successfully unregistered. You can re-register by using the command /getstarted")
          user_data_changed = True

        except Exception as e:
          dt_print(f"Error unregistering for user id {user['id']} (object?: {user['object']}):", e)
          await message.channel.send("[DEBUG]: Oops, there was an error during unregistering!")

      else:
        await message.channel.send("Cancelling unregister (received a response other than 'Y')")


  # Show all rules
  elif message_content[1] == "rules":
    # chr(10) is used in place of a newline escape character ("\n") to ensure compatibility with older versions of Python that don't allow escape characters in an f-string
    await user["object"].send(f"Rules: {esc_md(str(user['important']))}{chr(10)+'Override is currently enabled (disable by using /override)' if user['override'] else ''}{chr(10)+'Notifications are currently paused (unpause by using /pause)' if user['paused'] else ''}")


  # Get version
  elif message_content[1] == "version":
    await message.channel.send("""
**Version:** v2024.10.10
v2024.10.10 - Add link to support Discord server, finish support for usage in servers (/getstarted can only be used in DMs, add /flatnotifs as command prefix), update help page, clean some stuff up (THE CODE IS OVER 600 LINES LONG, HELP LMAO)
v2024.9.20 - Bug fixes. A lot of bug fixes. (the code for this bot is officially now over 500 lines long lul somebody pls save me-)
v2024.9.17 - Add support for specifying 'exclude' for rules, allow adding multiple rules at once (of the same include/exclude and category), add category attachments.score.id
v2024.9.14 - Minor update to notification and command handling, add /pause and /sendhere commands to allow setting to send in specific channels
v2024.9.12 - Add multi-user support, persistent storage, encryption of API keys
v2024.9.6 - Prototype complete
(Go to the bot's [Discord server](<https://discord.gg/s5xXz8Nfun>) for more details and older patch notes!)
        """)


  # Show all commands
  elif message_content[1] == "help":
    await message.channel.send("""
**Help**

Welcome to Flat Notifs! This a bot that sends your Flat notifications directly to your Discord DMs or a channel in a server that you specify (that this bot has been added to)! In addition, it allows you to filter by user, notification type, and score id.

**Available commands:**
`/flatnotifs addrule include/exclude category value`  (Add a rule. More than one value can be specified, seperated by spaces)
`/flatnotifs removerule value`  (Remove a rule. More than one value can be specified, seperated by spaces)
`/flatnotifs override`  (Override the rules you have set. The bot will notify you of all notifications. Use the same command to toggle on and off)
`/flatnotifs pause`  (Pause notifications. The bot will not notify you of any notifications. Use the same command to toggle on and off)
`/flatnotifs sendhere`  (Set your notifications to send in the channel where the command was sent. Use the same command to toggle on and off)
`/flatnotifs unregister`  (Unregister and delete all of your information including your personal token, rules, and other preferences)
`/flatnotifs rules`  (Show all rules you have set)
`/flatnotifs version`  (Show current version and patch notes for recent previous versions)
`/flatnotifs help`  (You are here!)

**Available categories/values (for addrule and removerule):**
`actor.username`  (Flat.io username, without the @ sign. e.g. `actor.username flat`)
`type`  (Type of notification. Options: scorePublish, scoreComment, scoreStar, userFollow. e.g. `type userFollow`)
`attachments.score.id`  (id of a score, without the name. e.g. `attachments.score.id 623f2fab79ac0e0012b95dc8`)
""")
    await message.channel.send("""
*Answer not here, have feedback, or want to help with development? Join the bot's [Discord server](<https://discord.gg/s5xXz8Nfun>)*
*(Go there to contact the developer, as well as to get access to the full patch notes, TODO, and known issues lists!)*

-# *Disclaimer: Flat Notifs is not made by Flat.io. It is a project that uses the Flat.io API, made by a member of the community (me). Additionally, it is in beta and worked on when I have time to, so it is not guaranteed to be free of bugs, be updated frequently, or even work. Updates may introduce breaking changes. Logs are collected for debug purposes.*
""")

  else:
    await message.channel.send("Whoops! That command was invalid.\n(Use  `/flatnotifs help`  for a list of valid commands. Make sure the command is spelled correctly!)")


""" <-- Run Flask app / Discord bot --> """

# Instantiate Flask app (for keep-alive)
flask_app = Flask(__name__)

@flask_app.route("/", methods=["GET"])
def home() -> str:
  return "I'm alive"

def flask_run() -> None:
  flask_app.run(host="0.0.0.0", port=7860)


# Run Flask app in a daemon thread
flask_thread = Thread(target=flask_run)
flask_thread.daemon = True
flask_thread.start()


# Run Discord bot
bot.run(bot_token)