# pip install cryptography datasets discord.py flask requests
import asyncio
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


# Init Discord Bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)


# Variables
bot_token = os.environ["DISCORD_BOT_TOKEN"] # Discord bot token, expected type: string
dataset_id = os.environ["DATASET_ID"] # ID of the HF dataset, expected type: string
hf_api_key = os.environ["HF_API_KEY"] # HF API key to access the dataset, expected type: string
f = Fernet(os.environ["FERNET_KEY"].encode()) # Fernet key for encryption/decryption, expected type: string
user_data_changed = False


# Load and reconstruct the user_data from the dataset
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
  print("WARNING: dataset is empty or does not exist(?):", e)
  user_data = []


# Function to escape markdown
def esc_md(text):
    escape_chars = ['*', '_', '~', '`', '|', '>', '[', ']', '(', ')', '#', '-', '+', '.']
    for char in escape_chars:
        text = text.replace(char, f'\\{char}')
    return text


# Function to update the HF dataset
def update_ds():
  # Filter user_data and then dump into a data.json file
  with open('data.json', 'w') as file:
    filtered_array = [{category: values for category, values in user.items() if (category != 'object' and category != 'newest_id' and category != 'channel')} for user in user_data]
    json.dump(filtered_array, file, indent=4)

  # Upload data.json to the HF dataset
  api = HfApi()
  api.upload_file(
      path_or_fileobj="data.json",
      path_in_repo="data.json",
      repo_id=dataset_id,
      repo_type="dataset",
      commit_message="Update data.json (program)",
      token=hf_api_key
  )
  print("database updated")


# Function to get the contents of the api
def read_api(token):
  headers = {'Authorization': 'Bearer ' + token}
  try:
    response = requests.get(
      "https://api.flat.io/v2/me/notifications?expand=actor,score&returnOptInScoresInvitations=true&limit=10", 
      headers=headers  
    )
    response.raise_for_status()
    return response.json()
  except requests.exceptions.RequestException as e:
    print("API request error:", e)
    return []
  except ValueError as e:
    print("JSON parsing error:", e)
    return []


# Discord - check notifications loop
@tasks.loop(seconds=60)
async def check_notifs():
  check_notifs.change_interval(seconds=(60+(len(user_data)*30)))
  # print("checking, interval in seconds:", (60+(len(user_data)*30)))
  global user_data_changed

  # If there've been any changes to user_data, update dataset
  if user_data_changed:
    update_ds()
    user_data_changed = False

  for user in user_data:
    if not user["paused"]:
      # Get the newest element and element list
      api_key = f.decrypt(user["api_key"].encode()).decode()
      elements = read_api(api_key)
      excluded = False

      if elements:
        for element in elements:
          # Break loop if you find the current element that matches the newest element
          if element['id'] == user['newest_id']:
            break

          # Iterate through important rules, append to is_important
          is_important = {"bool": False, "rules": []}
          for category, values in user["important"].items():
            # Iterate until you reach the bottom nested category
            nested_category = category.split('.')
            value = element
            for k in nested_category:
              value = value.get(k, None)
              if value is None:
                break
            
            # Check if excluded
            if ("-"+value) in values:
              is_important['bool'] = False
              excluded = True
              is_important['rules'].append(category + ": " + value)
              if not user["override"]:
                break

            # Check if included
            if (("+"+value) in values) or (value in values): # retain support for legacy system that doesn't have + or - prepended
              if not excluded:
                is_important['bool'] = True
              is_important['rules'].append(category + ": " + (("+"+value) if ("+"+value) in values else value))
              
          # Output
          print(f"{element['actor']['printableName']}: {element['type']}, ID-{element['id']}")
          if is_important['bool'] or user["override"]:
            if element['type'] == "scoreComment":
              url = element['attachments']['score']['htmlUrl'] + "#c-" + element['attachments']['scoreComment'] + "\n"
            elif element['type'] == "scorePublication":
              url = element['attachments']['score']['htmlUrl'] + "\n"
            else:
              url = ""
            n = f"{esc_md(element['actor']['printableName'])}: {esc_md(element['type'])} [(Open on Flat)]({url})\n-# Rule(s): {esc_md(str(is_important['rules']))}"
            if user["sendhere"]["bool"]:
              await user["channel"].send(n)
            else:
              await user["object"].send(n)
          print(f"This notification {'is' if is_important['bool'] else 'is not'} categorized as important{' by rule(s): ' + str(is_important['rules']) if is_important['bool'] else '.'}")

        # Update newest element
        user["newest_id"] = elements[0]["id"]

      else:
        await user["object"].send("[DEBUG]: Unable to check your notifications! Did you delete your API key?\nIf you have gotten this notification multiple times please use the command /pause and then contact the developer (get contact information by using the /help command)")
          
      await asyncio.sleep(30)


# Discord - on startup
@bot.event
async def on_ready():
  print("Bot has connected to Discord! :3")

  # Set users and test that users can be reached
  for user in user_data:
    try: 
      user["object"] = await bot.fetch_user(user["id"])
      await user["object"].send("[DEBUG]: Flat Notifs is restarting... (just checking that the bot can still reach you)")
    except Exception as e:
      raise Exception(f"Error sending init message to user {user['id']} or user not found:", e)
    try:
      if user["sendhere"]["bool"]:
        user["channel"] = await bot.fetch_channel(user["sendhere"]["channel_id"])
    except Exception as e:
      user["sendhere"]["bool"] = False
      await user["object"].send("[DEBUG]: Unable to find your specified channel! Defaulting to DMs. Was the channel deleted, or did the bot lose access to it?\nYou can use /sendhere again to pick a channel to send notifications")

  # Get the newest element in the notifications
  for user in user_data:
    await asyncio.sleep(30)
    try:
      api_key = f.decrypt(user["api_key"].encode()).decode()
      elements = read_api(api_key)
      user["newest_id"] = elements[0]["id"]
      print(f"Newest element on startup is ID-{user['newest_id']}")
    except Exception as e:
      await user["object"].send("[DEBUG]: Unable to check your notifications! Did you delete your API key?\nIf you have gotten this notification multiple times please use the command /pause and then contact the developer (get contact information by using the /help command)")

  # Set bot status
  game = discord.Game(name="with the Flat.io API")
  await bot.change_presence(status=discord.Status.online, activity=game)
  print(f"{len(user_data)} users")

  # Start the check_notifs task
  print("Watching notifs...")
  check_notifs.start()


# Discord - handle messages (allow user to run commands to configure their notif settings)
@bot.event
async def on_message(message):
  global user_data_changed
  message_content = message.content.split()

  # If bot user, return
  if message.author.id == bot.user.id:
    return
  
  # If user is registered, set user
  registered = False
  for u in user_data: # using u instead of user so we can save the user var
    if message.author.id == int(u["id"]):
      registered = True
      user = u
      break

  # If not registered, prompt the user to register
  if not registered:
    if message_content[0] == "/getstarted":
      # If API key has been provided and is valid, register
      try:
        api_key = message_content[1]
        elements = read_api(api_key)
        if elements:
          user = message.author
          user_data.append({
            "id": message.author.id,
            "api_key": f.encrypt(api_key.encode()).decode(),
            "important": {
              "actor.username": ['flat'],
              "type": ["userFollow", "scoreStar"]
            },
            "override": False,
            "paused": False,
            "sendhere": {
              "bool": False
            },
            "object": user,
            "newest_id": elements[0]["id"]
          })
          await message.channel.send("Successfully registered! (If you didn't mean to do this, use the command /unregister)")
          user_data_changed = True
          print(f"user {user} registered, newest element on startup is ID-{elements[0]['id']}")
        else:
          await message.channel.send("Please provide a valid API key")
      except IndexError:
        await message.channel.send("Please try again and provide an API key in this format: /getstarted key (where key is your API key)")
    elif message_content[0].startswith("/"):
      await message.channel.send("Welcome to Flat.io Notifs! To get started, use the command /getstarted key (where key is your API key)")
    return

  # Add a rule
  if message_content[0] == "/addrule":
    try:
      include_exclude = message_content[1]
      category = message_content[2]
      input_values = message_content[3:]
      for input_value in input_values:
        if include_exclude == "include":
          temp = "+"+input_value
        elif include_exclude == "exclude":
          temp = "-"+input_value
        else:
          await message.channel.send("Please try again and provide include/exclude and a category and value in this format: /addrule include/exclude category value (first parameter was not include or exclude)")
          return
        if category in user["important"]:
          user["important"][category].append(temp)
          await message.channel.send(f"Rule {esc_md(category)}: {esc_md(temp)} added")
          user_data_changed = True
        else:
          await message.channel.send(f"Category {esc_md(category)} not found")
    except IndexError:
      await message.channel.send("Please try again and provide include/exclude and a category and value in this format: /addrule include/exclude category value (category or value was missing)")

  # Remove a rule
  elif message_content[0] == "/removerule":
    try:
      input_values = message_content[1:]
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
      await message.channel.send("Please try again and provide a value in this format: /removerule value")
  
  # Override all rules
  elif message_content[0] == "/override":
    if user["override"]:
      await message.channel.send("Override disabled (You will now only be notified of notifications that match your specified filters. Re-enable by using /override)")
    else:
      await message.channel.send("Override enabled (You will now be notified of all notifications. Disable by using /override)")
    user["override"] = not user["override"]
    user_data_changed = True

  # Pause notifications
  elif message_content[0] == "/pause":
    if user["paused"]:
      await message.channel.send("Notifications unpaused (You will now resume receiving notifications. Pause by using /pause)")
    else:
      await message.channel.send("Notifications paused (You will not receive notifications. Unpause by using /pause)")
    user["paused"] = not user["paused"]
    user_data_changed = True

  # Change notif send channel to here
  elif message_content[0] == "/sendhere":
    if user["sendhere"]["bool"]:
      user["sendhere"]["bool"] == False
      await message.channel.send("Successfully changed your notification channel back to default (your DMs)")
      user_data_changed = True
    else:
      # Ask for confirmation
      await message.channel.send("Are you sure you want to switch your notification send channel to here? (Y/N)\nIf this is a public channel, that means anyone can see your notifications.")

      # Function to check that it's still the same user in the same channel
      def check(m: discord.Message):
        print("unregister check:", (m.author.id == message.author.id and m.channel.id == message.channel.id))
        return m.author.id == message.author.id and m.channel.id == message.channel.id 
      
      # Wait 30 sec for a message that meets the check() requirement 
      try:
        msg = await bot.wait_for("message", check=check, timeout=30)
      except Exception as e:
        print("WARNING: timeout(?):", e)
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
            print("Setting sendhere error:", e)
            await message.channel.send("Oops, there was an error while setting sendhere")
        else:
          await message.channel.send("Cancelling sendhere (received a response other than 'Y')")

  # Unregister
  elif message_content[0] == "/unregister":
    # Ask for confirmation
    await message.channel.send("Are you sure you want to unregister? (Y/N)\nUnregistering means that you will lose any rules that you have set and will no longer receive notifications from this bot. Only unregister if you don't want to receive notifications from this bot anymore or if you need to change your API key")

    # Function to check that it's still the same user in the same channel
    def check(m: discord.Message):
      print("unregister check:", (m.author.id == message.author.id and m.channel.id == message.channel.id))
      return m.author.id == message.author.id and m.channel.id == message.channel.id 
    
    # Wait 30 sec for a message that meets the check() requirement 
    try:
      msg = await bot.wait_for("message", check=check, timeout=30)
    except Exception as e:
      print("WARNING: timeout(?):", e)
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
          print("Unregistration error:", e)
          await message.channel.send("Oops, there was an error during unregistering")
      else:
        await message.channel.send("Cancelling unregister (received a response other than 'Y')")

  # Show all rules
  elif message_content[0] == "/rules":
    await user["object"].send(f"Rules: {esc_md(str(user['important']))}{chr(10)+'Override is currently enabled (disable by using /override)' if user['override'] else ''}{chr(10)+'Notifications are currently paused (unpause by using /pause)' if user['paused'] else ''}")

  # Show all commands
  elif message_content[0] == "/help":
    await message.channel.send(f"**Help**\n\n**Available commands:**\n/addrule include/exclude category value\n/removerule value\n/override\n/pause\n/sendhere\n/unregister\n/rules\n/help\n/version\n\n**Available categories/values (for /addrule and /removerule):**\nactor.username (Flat username, without the @ sign. e.g. actor.username flat)\ntype (Type of notification. Options: scorePublish, scoreComment, scoreStar, userFollow. e.g. type userFollow)\n\n*Answer not here, found bugs, or want to help with development? Contact the developer:*\n*Discord: xarical*\n*Flat.io: @rzyr_*\n*Github: xarical/fomobot (Go here for the TODO and known issues lists!)*\n\n-# *Disclaimer: Flat Notifs is not made by Flat.io. It is a project that uses the Flat.io API, made by a member of the community (me). Additionally, it is in beta and worked on when I have time to, so it is not guaranteed to be free of bugs, updated frequently, or even work. Updates may introduce breaking changes. Logs are collected for debug purposes. Use at your own discretion.*")

  # Get version
  elif message_content[0] == "/version":
    await message.channel.send("**Version:** v2024.9.16\nv2024.9.16 - Bug fixes, add limited support for specifying 'exclude' for rules, allow adding multiple rules at once (of the same include/exclude and category), add streaming status\nv2024.9.14 - Minor update to notification and command handling, add /pause and /sendhere commands\nv2024.9.12 - Add persistent storage, key encryption, and multi-user support\nv2024.9.6 - Prototype complete")


# Init Flask app (for keep-alive)
flask_app = Flask(__name__)

@flask_app.route("/", methods=["GET"])
def home():
  return "I'm alive"

def flask_run():
  flask_app.run(host="0.0.0.0", port=7860)


# Run Flask app in a daemon thread
flask_thread = Thread(target=flask_run)
flask_thread.daemon = True
flask_thread.start()


# Run Discord bot
bot.run(bot_token)