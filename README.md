# OXYZC Income Bot v2

## Included
- OXYZC branded menu
- Balance and profile
- Referral system
- Daily bonus
- Admin-created tasks
- Manual task approval/rejection
- bKash / Nagad / Bank withdrawal request flow
- Manual withdrawal approval/rejection
- SQLite storage
- Admin statistics

## Install
Python 3.10+:
`pip install -r requirements.txt`

Set environment variables from `.env.example`, then:
`python bot.py`

## Admin commands
/addtask reward | title | description | url
/approvetask USER_ID TASK_ID
/rejecttask USER_ID TASK_ID
/approvewithdraw WITHDRAWAL_ID
/rejectwithdraw WITHDRAWAL_ID
/stats

Example:
`/addtask 25 | Join Community | Join the official community and complete the task. | https://t.me/example`

The bot uses points. It does not guarantee income. Withdrawal payment is manual and must be handled lawfully by the operator.
