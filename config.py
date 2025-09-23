#/bulletin_monitor/config.py

import os
from dotenv import load_dotenv
##dotenv stand for dot-environment for 
load_dotenv() # This loads variables from your .env file into os.environ

# --- SSH Configuration ---
# Get these values from your .env file for security
BQRM_HOST = os.getenv("BQRM_HOST")
BQRM_USER = os.getenv("BQRM_USER")
BQRM_PRIVATE_KEY_PATH = os.getenv("BQRM_PRIVATE_KEY_PATH") # Path to your SSH private key
BQRM_PASSWORD = os.getenv("BQRM_PASSWORD") # Only if not using a private key

LOG_LINES_TO_FETCH = 50
# --- Bulletin Configurations ---
# REPLACE THESE WITH YOUR ACTUAL BULLETIN DETAILS!
BULLETINS = [
    {
        "id": "sonelgaz",
        "name": "sonalgaz",
        "log_path": "/home/bqrm/BQRM_V01/sonelgaz/scr/logs/sonelgaz.log",
        "rerun_command": "/bin/bash /home/bqrm/BQRM_V01/sonelgaz/scr/run.sh",
        "code_link": f"ssh://{BQRM_USER}@{BQRM_HOST}/home/bqrm/BQRM_V01/sonelgaz/scr/",
        # NEW: Command to copy for direct terminal access
        "access_command": f"ssh {BQRM_USER}@{BQRM_HOST} -t 'cd /home/bqrm/BQRM_V01/sonelgaz/scr; bash'"
    },
    {
        "id": "BMSLA",
        "name": "BMLSA",
        "log_path": "/home/bqrm/BQRM_V01/BMSLA/scr/logs/BMSLA.log",
        "rerun_command": "/bin/bash /home/bqrm/BQRM_V01/BMSLA/scr/run.sh",
        "code_link": f"ssh://{BQRM_USER}@{BQRM_HOST}/home/bqrm/BQRM_V01/BMSLA/scr/",
        "access_command": f"ssh {BQRM_USER}@{BQRM_HOST} -t 'cd /home/bqrm/BQRM_V01/BMSLA/scr; bash'"
    },
    {
        "id": "BQRM-main",
        "name": "BQRM-main",
        "log_path": "/home/bqrm/BQRM_V01/BQRM-main/scr/logs/bqrm_ref.log",
        "rerun_command": "/bin/bash /home/bqrm/BQRM_V01/BQRM-main/scr/run.sh",
        "code_link": f"ssh://{BQRM_USER}@{BQRM_HOST}/home/bqrm/BQRM_V01/BQRM-main/scr/",
        "access_command": f"ssh {BQRM_USER}@{BQRM_HOST} -t 'cd /home/bqrm/BQRM_V01/BQRM-main/scr; bash'"
    },
    {
        "id": "BQCP24h",
        "name": "BQCP24h",
        "log_path": "/home/bqrm/BQRM_V01/BQCP24h/logs/BQCP24h.log",
        "rerun_command": "/bin/bash /home/bqrm/BQRM_V01/BQCP24h/run.sh",
        "code_link": f"ssh://{BQRM_USER}@{BQRM_HOST}/home/bqrm/BQRM_V01/BQCP24h/scr/",
        "access_command": f"ssh {BQRM_USER}@{BQRM_HOST} -t 'cd /home/bqrm/BQRM_V01/BQCP24h/scr; bash'"
    },
   {
        "id": "synop2bufr",
        "name": "synop2bufr",
        "log_path": "/home/bqrm/BQRM_V01/synop2bufr/logs/synop2bufr_script.log",
        "rerun_command": "/bin/bash /home/bqrm/BQRM_V01/synop2bufr/synop2bufr.sh",
        "code_link": f"ssh://{BQRM_USER}@{BQRM_HOST}/home/bqrm/BQRM_V01/synop2bufr/",
        "access_command": f"ssh {BQRM_USER}@{BQRM_HOST} -t 'cd /home/bqrm/BQRM_V01/synop2bufr; bash'"
      },
]

# --- Log Parsing Configuration ---
# Keywords to look for in the log to determine status (case-insensitive)
SUCCESS_KEYWORDS = ["SUCCESS", "COMPLETED", "FINISHED"]
ERROR_KEYWORDS = ["ERROR", "FAILURE", "FAILED", "EXCEPTION"]
WARNING_KEYWORDS = ["WARNING", "WARN"] # New: Keywords for warnings
CRITICAL_KEYWORDS = ["CRITICAL", "FATAL", "SEVERE"] # New: Keywords for critical errors
