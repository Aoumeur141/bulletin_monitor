import os
from flask import Flask, jsonify, request, send_from_directory, abort # Import abort
import datetime
import logging
import atexit
import re 

from config import BULLETINS, SUCCESS_KEYWORDS, ERROR_KEYWORDS, LOG_LINES_TO_FETCH
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
    This is a basic keyword-based approach.
    """
    if not log_content or "Error fetching log file" in log_content:
        return "UNKNOWN", "Log not available or error fetching. Check log path/permissions."

    log_content_upper = log_content.upper()

    for keyword in ERROR_KEYWORDS:
        if keyword in log_content_upper:
            return "FAILED", "Error keyword found in recent logs"

    for keyword in SUCCESS_KEYWORDS:
        if keyword in log_content_upper:
            return "SUCCESS", "Success keyword found in recent logs."

    return "UNKNOWN", "No clear success/failure keywords found in recent logs."

def get_bulletin_details_summary(bulletin_config):
    """
    Fetches the latest status and a summary of the log for a single bulletin.
    This uses LOG_LINES_TO_FETCH for performance on the dashboard.
    """
    if not bqrm_ssh_client or not bqrm_ssh_client.is_active():
        return {
            "id": bulletin_config["id"],
            "name": bulletin_config["name"],
            "status": "ERROR",
            "last_run": "N/A",
            "last_log_summary": "Backend SSH client not initialized or connection inactive. Check server logs for connection issues.",
            "code_link": bulletin_config["code_link"]
        }

    # Fetch only the last N lines for the summary view
    log_content_summary = bqrm_ssh_client.get_last_log_lines(bulletin_config["log_path"])
    status, message = parse_log_status(log_content_summary)

    last_run_time = "N/A" ## variable with valuse N/A 
    lines = log_content_summary.splitlines() 
    if lines:
        for line in reversed(lines[-min(10, len(lines)):]):
            if len(line) >= 19 and line[4] == '-' and line[7] == '-' and line[10] == ' ' and line[13] == ':' and line[16] == ':':
                try:
                    timestamp_str = line[:19]
                    datetime.datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                    last_run_time = timestamp_str
                    break
                except ValueError:
                    pass

    return {
        "id": bulletin_config["id"],
        "name": bulletin_config["name"],
        "status": status,
        "last_run": last_run_time,
        "last_log_summary": message,
        "code_link": bulletin_config["code_link"]
    }

def get_full_log_content(log_path):
    """
    Fetches the entire content of a log file from the BQRM server.
    """
    if not bqrm_ssh_client or not bqrm_ssh_client.is_active():
        return "Backend SSH client not initialized or connection inactive. Cannot fetch full log."

    # Use 'cat' or 'tail -n +1' to get the entire file
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
        results.append(get_bulletin_details_summary(bulletin_config)) # Use summary function
    return jsonify(results)

@app.route('/api/bulletins/<string:bulletin_id>/full_log', methods=['GET'])
def get_bulletin_full_log(bulletin_id):
    """
    API endpoint to get the full log content for a specific bulletin.
    """
    logging.info(f"Received request for full log for bulletin ID: {bulletin_id}")

    if not bqrm_ssh_client or not bqrm_ssh_client.is_active():
        logging.error(f"Cannot fetch full log for {bulletin_id}: SSH client not initialized or connection inactive.")
        return jsonify({"message": "Backend SSH client not initialized or connection inactive. Cannot fetch log.", "success": False}), 503

    bulletin = next((b for b in BULLETINS if b["id"] == bulletin_id), None)
    if not bulletin:
        logging.warning(f"Full log request for unknown bulletin ID: {bulletin_id}")
        abort(404, description=f"Bulletin with ID '{bulletin_id}' not found.")

    full_log = get_full_log_content(bulletin["log_path"])
    return jsonify({"bulletin_id": bulletin_id, "name": bulletin["name"], "full_log": full_log})


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
            return jsonify({"message": "Backend SSH client failed to initialize at startup. Please check server logs.", "status": "error"}), 503
        elif not bqrm_ssh_client.is_active():
            logging.warning(f"API request to {request.path} received but SSH client is not active. Attempting re-connection before returning 503.")
            try:
                bqrm_ssh_client._connect()
                if bqrm_ssh_client.is_active():
                    logging.info("SSH client re-connected successfully for API request.")
                    return
            except Exception as e:
                logging.error(f"Failed to re-connect SSH client for API request: {e}")
            return jsonify({"message": "Backend SSH client connection is currently inactive. Please check server logs.", "status": "error"}), 503

if __name__ == '__main__':
    os.makedirs(app.static_folder, exist_ok=True)
    app.run(debug=True, host='0.0.0.0', port=5000)
