# I did a bit to clean this script up to make it obvious what needs to be changed, just still go line by line and make sure all urls, ntfy topics, etc apply to your setup

# this script glues together Vikunja and ntfy. It will notify of upcoming and overdue tasks and tasks with past reminders. The notification will have handy "Mark Done", "Remind Me Tomorrow", and "View Tasks" buttons
# note of caution on multiple users: a recurring task with "default" repeat, if marked done multiple times, will have a due date too far out. Set to "from current date"

# cronjob example:
## notify every 15 minutes - just reminders
# */15  * * * * python3 /home/user/scripts/vikunja.py -r
## notify at 6pm every day of overdue tasks
# 0 18 * * * python3 /home/user/scripts/vikunja.py


import requests
import json
from datetime import datetime, timedelta
from base64 import standard_b64encode
from copy import copy
import argparse

# cronjob every just check reminders with -r
# cronjob every day for overdue tasks
parser = argparse.ArgumentParser()
parser.add_argument("-r", dest='just_reminders', action="store_true", default=False)
args = parser.parse_args()

vikunja_date_frmt = r'%Y-%m-%dT%H:%M:%SZ'

todo_url = "https://todo.your.url.here/api/v1/tasks/"
todo_jwt_key = "asuperlongstring"  # JWT token for Vikunja session. Easiest way to set this up is to set "long" session to several years, log in with a browser with "remember me", then use a JWT debugger to get that session token
todo_headers = {'Authorization': f'Bearer {todo_jwt_key}', 'Content-Type': 'application/json'}

ntfy_url = "https://notify.your.url.here/" # ntfy server url
ntft_error_url = "https://notify.your.url.here/server"  # topic for server errors
ntfy_auth = standard_b64encode(b"user:pw").decode("utf-8")  # username and password for ntfy

# get tasks from the server
try:
    tasks_request = requests.get(f"{todo_url}all", headers=todo_headers)
    tasks_request.raise_for_status()
    tasks = json.loads(tasks_request.content.decode('utf8'))
except requests.exceptions.HTTPError as err:
    requests.post(ntft_error_url, data=f"Unable to fetch tasks, {err}", headers={"Authorization": f"Basic {ntfy_auth}", "Title": "vikunja.py ntfy cronjob"})
    raise SystemExit(err)

overdue_tasks = []
reminder_tasks = []
upcoming_tasks = []
for t in tasks:
    # if the task is done, or there are no due date and no reminders
    if t["done"] or (t["due_date"][0] == "0" and t["reminder_dates"] is None):
        continue

    due_date = datetime.strptime(t["due_date"], vikunja_date_frmt)
    reminders = [datetime.strptime(d, vikunja_date_frmt) for d in t["reminder_dates"]] \
                    if t["reminder_dates"] is not None else []

    # tasks with past reminders
    if True in [datetime.now() > d for d in reminders]:
        reminder_tasks.append(t)
    # future reminder exists or just checking reminders right now
    elif True in [datetime.now() < d for d in reminders] or args.just_reminders:
        continue
    # overdue taks with no future reminders
    elif due_date < datetime.now():
        overdue_tasks.append(t)
    # tasks due soon
    elif due_date < (datetime.now() + timedelta(hours=6)):
        upcoming_tasks.append(t)

for t in reminder_tasks + overdue_tasks + upcoming_tasks:
    url = f"{todo_url}{t['id']}"

    if t in reminder_tasks:
        message = f"Here's a reminder for your task \'{t['title']}\'!"
    elif t in overdue_tasks:
        message = f"Your task \'{t['title']}\' is overdue!"
    else:
        message = f"Your task \'{t['title']}\' is due soon!"

    # clean up old reminders
    if t["reminder_dates"] is not None:
        t["reminder_dates"] = [d for d in t["reminder_dates"] 
                               if datetime.strptime(d, vikunja_date_frmt) > datetime.now()]
        requests.post(url, headers=todo_headers, data=json.dumps(t))

    # copy of task for marking as done
    t_done = copy(t)
    t_done["done"] = True

    # copy of task for setting a reminder
    t_remind = copy(t)
    t_remind["reminder_dates"] = [] if t_remind["reminder_dates"] is None else t_remind["reminder_dates"]
    reminder_date = (datetime.now() + timedelta(hours=22)).strftime(vikunja_date_frmt)  # 22 hours from now
    t_remind["reminder_dates"].append(reminder_date)

    # filter by project here if you have multiple users
    if t["bucket_id"] == 1:
        topic = "chores"
    elif t["bucket_id"] == 2:
        topic = "my-tasks"
    else:
        topic = "other-tasks"

    # ntfy notification with two actions back to vikunja
    requests.post(ntfy_url, 
                headers={"Authorization": f"Basic {ntfy_auth}"},
                data=json.dumps({
                    "topic": topic,
                    "message": message,
                    "title": t["title"],
                    "actions": [
                        {
                        "action": "http",
                        "label": "Mark Done",
                        "url": url,
                        "method": "POST",
                        "headers": todo_headers,
                        "body": json.dumps(t_done)
                        },
                        {
                        "action": "http",
                        "label": "Tomorrow",
                        "url": url,
                        "method": "POST",
                        "headers": todo_headers,
                        "body": json.dumps(t_remind)
                        },
                        {
                        "action": "view",
                        "label": "Open Tasks",
                        "url": "https://todo.your.url.here",
                        }]
                    })
                )
