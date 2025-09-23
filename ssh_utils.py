#/bulletin_monitor/ssh_utils.py

import paramiko
import logging
import os
import time

# Import configuration from our config.py file
from config import BQRM_HOST, BQRM_USER, BQRM_PRIVATE_KEY_PATH, BQRM_PASSWORD, LOG_LINES_TO_FETCH

# Set up basic logging for this module
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class BQRMSshClient:
    """
    A utility class to manage SSH connections and operations on the BQRM server.
    """
    def __init__(self):
        self.client = paramiko.SSHClient()
        # Automatically add the server's host key.
        # In production, consider a more secure policy like WarningPolicy or manually adding keys.
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._is_connected = False # Internal state to track connection status
        try:
            self._connect() # Attempt to connect immediately upon creation
            self._is_connected = True
        except Exception as e:
            logging.error(f"Initial SSH connection failed: {e}")
            self._is_connected = False
            # Do not re-raise here, allow the client to be created but in a disconnected state.
            # The app.py's before_request will handle this state for API calls.

    def _connect(self):
        """
        Establishes an SSH connection to the BQRM server using either a private key or password.
        Raises exceptions on connection failure.
        """
        if not BQRM_HOST or not BQRM_USER:
            raise ValueError("BQRM_HOST or BQRM_USER is not configured in .env.")

        # Close existing connection if active before attempting a new one
        if self.client.get_transport() and self.client.get_transport().is_active():
            self.client.close()
            logging.info("Closed existing SSH connection before attempting re-connect.")

        try:
            logging.info(f"Attempting to connect to BQRM: {BQRM_USER}@{BQRM_HOST}")
            if BQRM_PRIVATE_KEY_PATH and os.path.exists(BQRM_PRIVATE_KEY_PATH):
                # Using SSH private key for authentication
                self.client.connect(
                    hostname=BQRM_HOST,
                    username=BQRM_USER,
                    key_filename=BQRM_PRIVATE_KEY_PATH,
                    timeout=10 # Connection timeout in seconds
                )
                logging.info(f"Connected using private key: {BQRM_PRIVATE_KEY_PATH}")
            elif BQRM_PASSWORD:
                # Using password for authentication (less secure, use key if possible)
                self.client.connect(
                    hostname=BQRM_HOST,
                    username=BQRM_USER,
                    password=BQRM_PASSWORD,
                    timeout=10
                )
                logging.info("Connected using password.")
            else:
                raise ValueError("No valid SSH credentials provided (BQRM_PRIVATE_KEY_PATH or BQRM_PASSWORD missing/invalid).")
            logging.info("Successfully established SSH connection to BQRM.")
            self._is_connected = True # Update internal state
        except paramiko.AuthenticationException:
            logging.error("SSH Authentication failed. Please verify BQRM_USER and your key/password.")
            self._is_connected = False
            raise
        except paramiko.SSHException as e:
            logging.error(f"Could not establish SSH connection to {BQRM_HOST}: {e}")
            self._is_connected = False
            raise
        except Exception as e:
            logging.error(f"An unexpected error occurred during SSH connection: {e}")
            self._is_connected = False
            raise

    def is_active(self):
        """Checks if the SSH connection is currently active."""
        # Check both internal state and Paramiko's transport status
        return self._is_connected and self.client.get_transport() and self.client.get_transport().is_active()

    def execute_command(self, command, timeout=30):
        """
        Executes a shell command on the BQRM server.
        Args:
            command (str): The shell command to execute.
            timeout (int): Maximum time in seconds to wait for the command to complete.
        Returns:
            tuple: (success (bool), stdout_output (str), stderr_output (str))
        """
        if not self.is_active():
            logging.warning("SSH client is not connected or connection is inactive. Attempting to re-connect.")
            try:
                self._connect() # Try to re-establish connection
            except Exception as e:
                logging.error(f"Failed to re-connect SSH: {e}")
                return False, "", f"SSH connection inactive and failed to re-connect: {e}"

        try:
            logging.info(f"Executing command on BQRM: '{command}'")
            stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
            exit_status = stdout.channel.recv_exit_status() # Wait for command to complete and get exit status
            output = stdout.read().decode().strip()
            error = stderr.read().decode().strip()

            if exit_status != 0:
                logging.error(f"Command '{command}' failed with exit status {exit_status}. Error: {error}")
                return False, output, error
            else:
                logging.info(f"Command '{command}' executed successfully. Output (first 100 chars): {output[:100]}...")
                return True, output, error
        except paramiko.SSHException as e:
            logging.error(f"SSH command execution error for '{command}': {e}")
            return False, "", str(e)
        except Exception as e:
            logging.error(f"An unexpected error occurred during command execution for '{command}': {e}")
            return False, "", str(e)

    def get_last_log_lines(self, log_path):
        """
        Fetches the last N lines of a log file from the BQRM server.
        Args:
            log_path (str): The full path to the log file on BQRM.
        Returns:
            str: The content of the last N log lines, or an error message.
        """
        command = f"tail -n {LOG_LINES_TO_FETCH} {log_path}"
        success, output, error = self.execute_command(command)
        if success:
            return output
        else:
            # If tail fails, it usually means the file doesn't exist or permissions are wrong
            logging.warning(f"Could not fetch log for {log_path}. Error: {error}")
            return f"Error fetching log file '{log_path}': {error}"

    def close(self):
        """Closes the SSH connection."""
        if self.client and self.client.get_transport() and self.client.get_transport().is_active():
            self.client.close()
            self._is_connected = False # Update internal state
            logging.info("SSH connection to BQRM closed.")
        else:
            logging.info("SSH client was not active or already closed.")

# No global bqrm_ssh_client instance here. It will be managed in app.py.

# --- Self-Test for ssh_utils.py (Run this file directly to test SSH) ---
if __name__ == "__main__":
    print("\n--- Testing BQRMSshClient directly ---")
    temp_bqrm_ssh_client = None
    try:
        temp_bqrm_ssh_client = BQRMSshClient() # Create an instance for testing
        if temp_bqrm_ssh_client.is_active():
            print(f"Successfully connected to BQRM for self-test.")

            # Test 1: Fetching a log file
            print("\n--- Testing log fetching ---")
            from config import BULLETINS # Import here for self-test
            if BULLETINS:
                test_bulletin = BULLETINS[0] # Use the first bulletin from config
                print(f"Attempting to fetch log for: {test_bulletin['name']} ({test_bulletin['log_path']})")
                log_content = temp_bqrm_ssh_client.get_last_log_lines(test_bulletin['log_path'])
                print(f"Fetched log (last {LOG_LINES_TO_FETCH} lines):\n{log_content}\n")
            else:
                print("No bulletins configured in config.py for log fetching test.")

            # Test 2: Executing a dummy command (e.g., 'ls -l')
            print("\n--- Testing command execution (ls -l) ---")
            success, output, error = temp_bqrm_ssh_client.execute_command("ls -l /tmp")
            if success:
                print(f"Command 'ls -l /tmp' successful. Output:\n{output}\n")
            else:
                print(f"Command 'ls -l /tmp' failed. Error:\n{error}\n")

            # Test 3: Executing a command that should fail
            print("\n--- Testing command execution (non-existent command) ---")
            success, output, error = temp_bqrm_ssh_client.execute_command("this_command_does_not_exist")
            if not success:
                print(f"Command 'this_command_does_not_exist' correctly failed. Error:\n{error}\n")
            else:
                print(f"Command 'this_command_does_not_exist' unexpectedly succeeded. Output:\n{output}\n")


        else:
            print("SSH client failed to connect during self-test. Check logs above.")

    except Exception as e:
        logging.critical(f"Failed to initialize BQRM SSH client for self-test or during test: {e}")
    finally:
        if temp_bqrm_ssh_client:
            temp_bqrm_ssh_client.close()
            print("Temporary SSH client closed.")
        print("\n--- BQRMSshClient testing complete ---")
