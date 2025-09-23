import os
from flask import Flask, jsonify, request, send_from_directory, abort
import datetime
import logging
import atexit
import re

from config import BULLETINS, SUCCESS_KEYWORDS, ERROR_KEYWORDS, WARNING_KEYWORDS, CRITICAL_KEYWORDS, LOG_LINES_TO_FETCH
from ssh_utils import BQRMSshClient

app = Flask(__name__, static_folder='static')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Initialize the global SSH client ---
bqrm_ssh_client = None
try:
    bqrm_ssh_client = BQRMSshClient()
    if bqrm_ssh_client.is_active():
        logging.info("Global BQRMSshClient initialized and connected successfully.")
    else:
        logging.error("Global BQRMSshClient initialized but failed to connect. Check SSH configuration.")
except Exception as e:
    logging.critical(f"Failed to initialize global BQRMSshClient: {e}. All SSH-dependent operations will fail.")
    bqrm_ssh_client = None

if bqrm_ssh_client:
    atexit.register(bqrm_ssh_client.close)
    logging.info("Registered atexit handler for SSH client closure.")

# --- Helper Functions for Log Parsing ---

def parse_log_status(log_content):
    """
    Analyzes the log content to determine the bulletin's status.
    Prioritizes CRITICAL > FAILED > SUCCESS.
    If SUCCESS is found, it remains SUCCESS even if WARNINGs are present,
    but a 'has_warnings' flag is set.
    """
    if not log_content or "Error fetching log file" in log_content:
        return "UNKNOWN", False # Return status and has_warnings flag

    log_content_upper = log_content.upper()

    is_critical = any(kw in log_content_upper for kw in CRITICAL_KEYWORDS)
    is_failed = any(kw in log_content_upper for kw in ERROR_KEYWORDS)
    is_success = any(kw in log_content_upper for kw in SUCCESS_KEYWORDS)
    is_warning = any(kw in log_content_upper for kw in WARNING_KEYWORDS)

    final_status = "UNKNOWN"
    has_warnings_notification = False

    if is_critical:
        final_status = "CRITICAL"
    elif is_failed:
        final_status = "FAILED"
    elif is_success:
        final_status = "SUCCESS"
        if is_warning: # If success, but also warnings, note it for notification
            has_warnings_notification = True
    elif is_warning: # Only if no CRITICAL, FAILED, or SUCCESS
        final_status = "WARNING"

    return final_status, has_warnings_notification


def format_full_log_with_styles(raw_log_content):
    """
    Parses raw log content and wraps lines containing specific keywords
    with <span> tags and corresponding CSS classes for styling.
    """
    if not raw_log_content:
        return ""

    styled_lines = []
    for line in raw_log_content.splitlines():
        line_upper = line.upper()
        
        # Prioritize critical, then error, then warning for highlighting
        if any(kw in line_upper for kw in CRITICAL_KEYWORDS):
            styled_lines.append(f'<span class="log-critical">{line}</span>')
        elif any(kw in line_upper for kw in ERROR_KEYWORDS):
            styled_lines.append(f'<span class="log-error">{line}</span>')
        elif any(kw in line_upper for kw in WARNING_KEYWORDS):
            styled_lines.append(f'<span class="log-warning">{line}</span>')
        else:
            styled_lines.append(line)
    
    return "\n".join(styled_lines)


def get_bulletin_details_summary(bulletin_config):
    """
    Fetches the latest status and a summary of the log for a single bulletin.
    This uses LOG_LINES_TO_FETCH for performance on the dashboard.
    """
    if not bqrm_ssh_client or not bqrm_ssh_client.is_active():
        return {
            "id": bulletin_config["id"],
            "name": bulletin_config["name"],
            "status": "SSH_ERROR", # Specific status for SSH connection issues for this bulletin
            "last_run": "N/A",
            "has_warnings": False, # No warnings if SSH is down
            "access_command": bulletin_config["access_command"]
        }

    # Fetch only the last N lines for the summary view
    log_content_summary = bqrm_ssh_client.get_last_log_lines(bulletin_config["log_path"])
    status, has_warnings_notification = parse_log_status(log_content_summary)

    last_run_time = "N/A"
    # Regex to find YYYY-MM-DD HH:MM:SS at the start of a line
    timestamp_pattern = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}')
    
    # Iterate through lines from the end to find the latest valid timestamp
    for line in reversed(log_content_summary.splitlines()):
        match = timestamp_pattern.match(line)
        if match:
            try:
                # Validate the timestamp string
                datetime.datetime.strptime(match.group(0), '%Y-%m-%d %H:%M:%S')
                last_run_time = match.group(0)
                break # Found the latest timestamp, exit loop
            except ValueError:
                # Not a valid date/time despite matching pattern (e.g., 2024-99-99)
                continue

    return {
        "id": bulletin_config["id"],
        "name": bulletin_config["name"],
        "status": status,
        "last_run": last_run_time,
        "has_warnings": has_warnings_notification, # New field
        "access_command": bulletin_config["access_command"]
    }

def get_full_log_content(log_path):
    """
    Fetches the entire content of a log file from the BQRM server.
    """
    if not bqrm_ssh_client or not bqrm_ssh_client.is_active():
        return "Backend SSH client not initialized or connection inactive. Cannot fetch full log."

    command = f"cat {log_path}" # 'tail -n +1 {log_path}' is an alternative
    success, output, error = bqrm_ssh_client.execute_command(command)
    if success:
        return output
    else:
        logging.warning(f"Could not fetch full log for {log_path}. Error: {error}")
        return f"Error fetching full log file '{log_path}': {error}"

# --- API Endpoints ---

@app.route('/')
def serve_index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/api/bulletins', methods=['GET'])
def get_all_bulletins_status():
    logging.info("Received request for all bulletin statuses (summary).")
    results = []
    for bulletin_config in BULLETINS:
        results.append(get_bulletin_details_summary(bulletin_config))
    return jsonify(results)

@app.route('/api/bulletins/<string:bulletin_id>/full_log', methods=['GET'])
def get_bulletin_full_log(bulletin_id):
    """
    API endpoint to get the full log content for a specific bulletin,
    formatted with styling spans.
    """
    logging.info(f"Received request for full log for bulletin ID: {bulletin_id}")

    if not bqrm_ssh_client or not bqrm_ssh_client.is_active():
        logging.error(f"Cannot fetch full log for {bulletin_id}: SSH client not initialized or connection inactive.")
        return jsonify({"message": "Backend SSH client not initialized or connection inactive. Cannot fetch log.", "success": False}), 503

    bulletin = next((b for b in BULLETINS if b["id"] == bulletin_id), None)
    if not bulletin:
        logging.warning(f"Full log request for unknown bulletin ID: {bulletin_id}")
        abort(404, description=f"Bulletin with ID '{bulletin_id}' not found.")

    raw_full_log = get_full_log_content(bulletin["log_path"])
    
    # Apply styling to the log content
    styled_full_log = format_full_log_with_styles(raw_full_log)
    
    return jsonify({"bulletin_id": bulletin_id, "name": bulletin["name"], "full_log": styled_full_log})


@app.route('/api/bulletins/<string:bulletin_id>/rerun', methods=['POST'])
def rerun_single_bulletin(bulletin_id):
    logging.info(f"Received re-run request for bulletin ID: {bulletin_id}")

    if not bqrm_ssh_client or not bqrm_ssh_client.is_active():
        logging.error(f"Cannot re-run {bulletin_id}: SSH client not initialized or connection inactive.")
        return jsonify({"message": "Backend SSH client not initialized or connection inactive. Cannot re-run.", "success": False}), 503

    bulletin = next((b for b in BULLETINS if b["id"] == bulletin_id), None)
    if not bulletin:
        logging.warning(f"Re-run request for unknown bulletin ID: {bulletin_id}")
        return jsonify({"message": f"Bulletin with ID '{bulletin_id}' not found.", "success": False}), 404

    logging.info(f"Attempting to execute re-run command for bulletin '{bulletin['name']}': {bulletin['rerun_command']}")
    success, output, error = bqrm_ssh_client.execute_command(bulletin["rerun_command"])

    if success:
        logging.info(f"Re-run command for '{bulletin['name']}' sent successfully.")
        return jsonify({"message": f"Bulletin '{bulletin['name']}' re-run command sent successfully.", "output": output, "success": True})
    else:
        logging.error(f"Failed to execute re-run command for '{bulletin['name']}'. Error: {error}")
        return jsonify({"message": f"Failed to send re-run command for '{bulletin['name']}'.", "error": error, "output": output, "success": False}), 500

# --- Error Handling for SSH Client Status ---

@app.before_request
def check_global_ssh_client_status():
    if request.path.startswith('/api'):
        if bqrm_ssh_client is None:
            logging.warning(f"API request to {request.path} received but SSH client was never initialized. Returning 503.")
            return jsonify({"message": "Backend SSH client failed to initialize at startup. Please check server logs.", "status": "SYSTEM_ERROR"}), 503
        elif not bqrm_ssh_client.is_active():
            logging.warning(f"API request to {request.path} received but SSH client is not active. Attempting re-connection before returning 503.")
            try:
                bqrm_ssh_client._connect()
                if bqrm_ssh_client.is_active():
                    logging.info("SSH client re-connected successfully for API request.")
                    return
            except Exception as e:
                logging.error(f"Failed to re-connect SSH client for API request: {e}")
            return jsonify({"message": "Backend SSH client connection is currently inactive. Please check server logs.", "status": "SYSTEM_ERROR"}), 503

if __name__ == '__main__':
    os.makedirs(app.static_folder, exist_ok=True)
    app.run(debug=True, host='0.0.0.0', port=5000)
