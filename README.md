# TODO:
* pause on api key error in check_notif
* pause on api key error in startup
* add more comments
* unregister user if no successful notification sent in x days (unless paused)
* make it so that /getstarted can only be used in DMs
* handle errors if user id ceases to exist during run
* add filter by score id
* test all command flows again
* 

# Known issues:
* after unpausing, on the next check you will be sent any of the last 10 notifs that match your filters. this is a "feature" not a bug.
* startup and check_notifs have delays that scale based on the number of users registered. this is intended behavior to avoid hitting the Flat.io API too often.
* /removerule only removes the first rule that it finds. i dont feel like fixing it.
* some rules might not have the + or - signs. it's due to maintaining support for the older version of rule management, which didn't have exclude so there was no need for + or - signs. basically if it doesn't have a sign, it's include by default.
* exclude doesn't work as intended. support for exclude is limited at this point.
* 