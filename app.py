# app.py

import os
from flask import Flask, jsonify, request, send_from_directory, abort, send_file  
import datetime
import logging
import atexit
import re
import shutil

from config import BULLETINS, SUCCESS_KEYWORDS, ERROR_KEYWORDS, WARNING_KEYWORDS, CRITICAL_KEYWORDS, LOG_LINES_TO_FETCH  
from ssh_utils import BQRMSshClient  

app = Flask(__name__, static_folder='static')
# --- IMPORTANT: Changed logging level to DEBUG for troubleshooting ---
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

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

# --- Helper Functions for Log Parsing and Dynamic Paths ---

def parse_log_status(log_content):
    """
    Analyzes the log content to determine the bulletin's status.
    Prioritizes CRITICAL > FAILED > SUCCESS.
    If SUCCESS is found, it remains SUCCESS even if WARNINGs are present,
    but a 'has_warnings' flag is set.
    """
    if not log_content or "Error fetching log file" in log_content:
        logging.debug("Log content is empty or contains fetch error, returning UNKNOWN status.")
        return "UNKNOWN", False

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
        if is_warning:
            has_warnings_notification = True
            logging.debug("SUCCESS status with WARNINGs detected.")
    elif is_warning:
        final_status = "WARNING"
        logging.debug("WARNING status detected (no SUCCESS/FAILED/CRITICAL).")
    
    logging.debug(f"Parsed log status: {final_status}, Has Warnings: {has_warnings_notification}")
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
        
        if any(kw in line_upper for kw in CRITICAL_KEYWORDS):
            styled_lines.append(f'<span class="log-critical">{line}</span>')
        elif any(kw in line_upper for kw in ERROR_KEYWORDS):
            styled_lines.append(f'<span class="log-error">{line}</span>')
        elif any(kw in line_upper for kw in WARNING_KEYWORDS):
            styled_lines.append(f'<span class="log-warning">{line}</span>')
        else:
            styled_lines.append(line)
    
    return "\n".join(styled_lines)

def _resolve_dynamic_path(template_string, date=None):
    """
    Resolves a dynamic path template using the provided date or current date.
    Example template: "/path/to/file_{year}{month}{day}.txt"
    Handles various date format variables including those for BMSLA.
    """
    if date is None:
        date = datetime.datetime.now()

    # Define common date format variables
    date_vars = {
        "year": date.strftime("%Y"),
        "year_short": date.strftime("%y"), # e.g., 24 for 2024
        "month": date.strftime("%m"),      # e.g., 09 for September
        "day": date.strftime("%d"),        # e.g., 05 for 5th
        "Hour": date.strftime("%H"),
        "hour": date.strftime("%H"),
        "Minute": date.strftime("%M"),
        "minute": date.strftime("%M"),
        "Second": date.strftime("%S"),
        "second": date.strftime("%S"),
        "DD": date.strftime("%d"),  
        "MM": date.strftime("%m"), 
        "YYYY": date.strftime("%Y"),  
        "Day": date.strftime("%d"),  
        "Month": date.strftime("%m"),  
        "Year": date.strftime("%Y"),  
    }
    
    try:
        resolved_path = template_string.format(**date_vars)
        logging.debug(f"Resolved dynamic path from template '{template_string}' with date {date.strftime('%Y-%m-%d')}: '{resolved_path}'")
        return resolved_path
    except KeyError as e:
        logging.error(f"Missing key in date_vars for template '{template_string}': {e}")
        return None
    except Exception as e:
        logging.error(f"Error resolving dynamic path template '{template_string}': {e}")
        return None

 
LINES_TO_FETCH_FOR_DAILY_CHECK = 1000 

def get_log_content_for_date_range(log_path, start_date, end_date):
    """
    Fetches log lines within a specific date range from the remote log file.
    This fetches a larger chunk and filters locally.
    """
    logging.debug(f"Attempting to fetch log content for {log_path} from {start_date.date()} to {end_date.date()}")
    if not bqrm_ssh_client or not bqrm_ssh_client.is_active():
        logging.error(f"SSH client inactive, cannot fetch log for {log_path}.")
        return "SSH_ERROR: Backend SSH client inactive."

    # Fetch a larger tail to ensure we capture activity across days
    command = f"tail -n {LINES_TO_FETCH_FOR_DAILY_CHECK} {log_path}"
    success, output, error = bqrm_ssh_client.execute_command(command)

    if not success:
        logging.warning(f"Could not fetch log for {log_path}. Error: {error}")
        return f"Error fetching log file '{log_path}': {error}"

    filtered_lines = []
    # Regex to match YYYY-MM-DD at the start of a line
    date_pattern = re.compile(r'^(\d{4}-\d{2}-\d{2})')

    for line in output.splitlines():
        match = date_pattern.match(line)
        if match:
            log_date_str = match.group(1)
            try:
                log_date = datetime.datetime.strptime(log_date_str, '%Y-%m-%d').date()
                if start_date.date() <= log_date <= end_date.date():
                    filtered_lines.append(line)
            except ValueError:
 
                 pass
 
        elif filtered_lines: # If we've already started collecting lines
            filtered_lines.append(line)
            
    logging.debug(f"Fetched {len(filtered_lines)} lines for date range from {log_path}.")
    return "\n".join(filtered_lines)


def _get_latest_timestamp_from_log_content(log_content, date_filter=None):
    """
    Finds the latest timestamp in the given log content, optionally filtered by date.
    Returns the timestamp string or None.
    """
    timestamp_pattern = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}')
    latest_timestamp = None
    latest_dt = None

    for line in reversed(log_content.splitlines()):
        match = timestamp_pattern.match(line)
        if match:
            try:
                current_dt = datetime.datetime.strptime(match.group(0), '%Y-%m-%d %H:%M:%S')
                if date_filter and current_dt.date() != date_filter.date():
                    continue # Skip if not for the filtered date
                
                if latest_dt is None or current_dt > latest_dt:
                    latest_dt = current_dt
                    latest_timestamp = match.group(0)
            except ValueError:
                continue
    logging.debug(f"Latest timestamp found (filtered by {date_filter.date() if date_filter else 'None'}): {latest_timestamp}")
    return latest_timestamp


def get_bulletin_details_summary(bulletin_config):
    """
    Fetches the latest status and a summary of the log for a single bulletin,
    specifically focusing on today's run and product availability.
    """
    logging.debug(f"Getting summary for bulletin: {bulletin_config['id']}")
    current_date = datetime.datetime.now()
    yesterday_date = current_date - datetime.timedelta(days=1)

    # Default values if SSH fails or no run today
    status = "UNKNOWN"
    last_run_time = "N/A"
    has_warnings_notification = False
    product_info_list = []

    if not bqrm_ssh_client or not bqrm_ssh_client.is_active():
        status = "SSH_ERROR"
        # For products, we can't check availability if SSH is down
        for product_template_details in bulletin_config.get("product_paths", []):
            product_info_list.append({
                "name": product_template_details.get("name", "Product"),
                "available": False,
                # Still resolve path for display/info, even if not available
                "remote_path": _resolve_dynamic_path(product_template_details["template"], current_date) 
            })
        logging.debug(f"Bulletin {bulletin_config['id']} returning SSH_ERROR due to inactive client.")
        return {
            "id": bulletin_config["id"],
            "name": bulletin_config["name"],
            "status": status,
            "last_run": last_run_time,
            "has_warnings": has_warnings_notification,
            "product_info": product_info_list
        }

    # 1. Get log content for today and yesterday
    log_content_for_check = get_log_content_for_date_range(bulletin_config["log_path"], yesterday_date, current_date)
    
    if "SSH_ERROR" in log_content_for_check:
        status = "SSH_ERROR"
        last_run_time = "N/A (Log fetch error)"
        logging.debug(f"Bulletin {bulletin_config['id']} returning SSH_ERROR due to log fetch error.")
    else:
        # Filter log content to only include today's entries for status parsing
        today_log_lines = []
        current_date_str = current_date.strftime('%Y-%m-%d')
        for line in log_content_for_check.splitlines():
            if line.startswith(current_date_str):
                today_log_lines.append(line)


            elif today_log_lines and not re.match(r'^\d{4}-\d{2}-\d{2}', line):
                today_log_lines.append(line)
        today_log_content = "\n".join(today_log_lines)
        logging.debug(f"Today's log content for {bulletin_config['id']} (first 200 chars): {today_log_content[:200]}...")


        # 2. Determine last run time and status for today
        latest_run_today = _get_latest_timestamp_from_log_content(today_log_content, current_date)
        
        if latest_run_today:
            last_run_time = latest_run_today
            # Parse status based *only* on today's relevant log entries
            status, has_warnings_notification = parse_log_status(today_log_content)
            logging.debug(f"Bulletin {bulletin_config['id']} status: {status}, last_run: {last_run_time} (today)")
        else:
            # No run found today. Check if there was a run yesterday for "PENDING" status.
            yesterday_log_lines = []
            yesterday_date_str = yesterday_date.strftime('%Y-%m-%d')
            for line in log_content_for_check.splitlines():
                if line.startswith(yesterday_date_str):
                    yesterday_log_lines.append(line)
                elif yesterday_log_lines and not re.match(r'^\d{4}-\d{2}-\d{2}', line):
                    yesterday_log_lines.append(line)
            yesterday_log_content = "\n".join(yesterday_log_lines)
            logging.debug(f"Yesterday's log content for {bulletin_config['id']} (first 200 chars): {yesterday_log_content[:200]}...")


            latest_run_yesterday = _get_latest_timestamp_from_log_content(yesterday_log_content, yesterday_date)
            
            if latest_run_yesterday:
                # It ran yesterday, but not today. Status is PENDING.
                status = "PENDING"
                last_run_time = f"N/A (Last run: {latest_run_yesterday} - Yesterday)"
                logging.debug(f"Bulletin {bulletin_config['id']} status: PENDING, last_run: {last_run_time} (yesterday)")
            else:
                # No run found today or yesterday. Status is NO_RECENT_RUN.
                status = "NO_RECENT_RUN"
                last_run_time = "N/A (No recent runs today or yesterday)"
                logging.debug(f"Bulletin {bulletin_config['id']} status: NO_RECENT_RUN")

    # 3. Check product availability for today
    for product_template_details in bulletin_config.get("product_paths", []):
        remote_product_path = _resolve_dynamic_path(product_template_details["template"], current_date)
        is_available = False
        if remote_product_path:
            is_available = bqrm_ssh_client.file_exists(remote_product_path)
            logging.debug(f"Product '{product_template_details.get('name', 'Product')}' for {bulletin_config['id']}: Checking path='{remote_product_path}', Exists={is_available}")
            if not is_available:
                logging.debug(f"Product not found for {bulletin_config['name']}: {remote_product_path}")
        else:
            logging.error(f"Could not resolve product path for {bulletin_config['name']} with template {product_template_details['template']}")

        product_info_list.append({
            "name": product_template_details.get("name", "Product"),
            "available": is_available,
            "remote_path": remote_product_path
        })

    return {
        "id": bulletin_config["id"],
        "name": bulletin_config["name"],
        "status": status,
        "last_run": last_run_time,
        "has_warnings": has_warnings_notification,
        "product_info": product_info_list
    }

def get_full_log_content(log_path):
    """
    Fetches the entire content of a log file from the BQRM server.
    """
    logging.debug(f"Fetching full log content for {log_path}")
    if not bqrm_ssh_client or not bqrm_ssh_client.is_active():
        return "Backend SSH client not initialized or connection inactive. Cannot fetch full log."

    command = f"cat {log_path}"
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

@app.route('/api/bulletins/<string:bulletin_id>/download_product', methods=['GET'])
def download_bulletin_product(bulletin_id):
    logging.info(f"Received download product request for bulletin ID: {bulletin_id}")

    if not bqrm_ssh_client or not bqrm_ssh_client.is_active():
        logging.error(f"Cannot download product for {bulletin_id}: SSH client not initialized or connection inactive.")
        return jsonify({"message": "Backend SSH client not initialized or connection inactive. Cannot download product.", "success": False}), 503

    bulletin = next((b for b in BULLETINS if b["id"] == bulletin_id), None)
    if not bulletin:
        logging.warning(f"Download product request for unknown bulletin ID: {bulletin_id}")
        abort(404, description=f"Bulletin with ID '{bulletin_id}' not found.")

    # Get the product index from query parameters
    product_index_str = request.args.get('index')
    if product_index_str is None:
        logging.warning(f"Download product request for '{bulletin_id}' missing 'index' parameter.")
        return jsonify({"message": "Missing product index for download.", "success": False}), 400

    try:
        product_index = int(product_index_str)
    except ValueError:
        logging.warning(f"Invalid product index '{product_index_str}' for bulletin '{bulletin_id}'.")
        return jsonify({"message": "Invalid product index format.", "success": False}), 400

    product_paths = bulletin.get("product_paths", [])
    if not product_paths or product_index < 0 or product_index >= len(product_paths):
        logging.warning(f"Bulletin '{bulletin_id}' has no product path at index {product_index}.")
        return jsonify({"message": f"Bulletin '{bulletin_id}' has no product path configured at index {product_index}.", "success": False}), 400

    product_template_info = product_paths[product_index]
    product_template = product_template_info["template"]
    
    # Resolve the dynamic path using the current date
    current_date = datetime.datetime.now()
    remote_path = _resolve_dynamic_path(product_template, current_date)
    if not remote_path:
        logging.error(f"Failed to resolve dynamic product path for '{bulletin_id}' (template: {product_template}).")
        return jsonify({"message": f"Failed to resolve dynamic product path for '{bulletin_id}' (template: {product_template}).", "success": False}), 500

    logging.debug(f"Download request for bulletin {bulletin_id}, product index {product_index}. Resolved remote path: '{remote_path}'")

    # --- NEW: Check if the file exists before attempting download ---
    if not bqrm_ssh_client.file_exists(remote_path):
        logging.warning(f"Attempted to download non-existent product: {remote_path} for bulletin {bulletin_id}. File reported as not existing by SFTP.")
        return jsonify({"message": f"Product file '{os.path.basename(remote_path)}' not found on remote server for today's date. It might not have run yet or failed.", "success": False}), 404

    # Create a temporary directory for downloads
    temp_dir = "temp_downloads"
    os.makedirs(temp_dir, exist_ok=True)

    local_file_path, error_message = bqrm_ssh_client.download_file(remote_path, temp_dir)

    if local_file_path:
        filename = os.path.basename(local_file_path)
        logging.info(f"Sending file '{local_file_path}' to client with filename '{filename}'.")
        try:
            response = send_file(local_file_path, as_attachment=True, download_name=filename)
            @response.call_on_close
            def cleanup_file():
                try:
                    os.remove(local_file_path)
                    logging.info(f"Cleaned up temporary file: {local_file_path}")
                except OSError as e:
                    logging.error(f"Error cleaning up temporary file {local_file_path}: {e}")
            return response
        except Exception as e:
            logging.error(f"Error sending file '{local_file_path}' to client: {e}")
            if os.path.exists(local_file_path):
                try:
                    os.remove(local_file_path)
                except OSError as e:
                    logging.error(f"Error cleaning up failed-to-send file {local_file_path}: {e}")
            return jsonify({"message": f"Failed to send product file: {e}", "success": False}), 500
    else:
        logging.error(f"Failed to download product file '{remote_path}' for '{bulletin_id}'. Error: {error_message}")
        return jsonify({"message": f"Failed to download product file from remote server: {error_message}", "success": False}), 500

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
    os.makedirs("temp_downloads", exist_ok=True)
    app.run(debug=True, host='0.0.0.0', port=5000)
