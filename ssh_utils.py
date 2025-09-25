# ssh_utils.py

import paramiko
import os
import logging
import datetime

from config import BQRM_HOST, BQRM_USER, BQRM_PRIVATE_KEY_PATH, BQRM_PASSWORD, LOG_LINES_TO_FETCH

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class BQRMSshClient:
    def __init__(self):
        self.client = None
        self.sftp = None
        self._connect()

    def _connect(self):
        try:
            if self.client and self.client.get_transport() and self.client.get_transport().is_active():
                logging.info(f"{datetime.datetime.now()} - SSH client already connected.")
                return

            self.client = paramiko.SSHClient()
            self.client.load_system_host_keys()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            if BQRM_PRIVATE_KEY_PATH and os.path.exists(BQRM_PRIVATE_KEY_PATH):
                private_key = paramiko.RSAKey.from_private_key_file(BQRM_PRIVATE_KEY_PATH)
                self.client.connect(hostname=BQRM_HOST, username=BQRM_USER, pkey=private_key)
                logging.info(f"{datetime.datetime.now()} - SSH connected to {BQRM_HOST} with private key.")
            elif BQRM_PASSWORD:
                self.client.connect(hostname=BQRM_HOST, username=BQRM_USER, password=BQRM_PASSWORD)
                logging.info(f"{datetime.datetime.now()} - SSH connected to {BQRM_HOST} with password.")
            else:
                raise ValueError("Neither BQRM_PRIVATE_KEY_PATH nor BQRM_PASSWORD is set for SSH connection.")
            
            self.sftp = self.client.open_sftp()
            logging.info(f"{datetime.datetime.now()} - SFTP client opened.")

        except Exception as e:
            logging.error(f"{datetime.datetime.now()} - Failed to establish SSH connection: {e}")
            self.client = None
            self.sftp = None

    def is_active(self):
        return self.client is not None and self.client.get_transport() and self.client.get_transport().is_active()

    def execute_command(self, command, timeout=30):
        if not self.is_active():
            logging.warning("SSH client is not connected or connection is inactive. Attempting to re-connect.")
            try:
                self._connect()
            except Exception as e:
                logging.error(f"Failed to re-connect SSH: {e}")
                return False, "", f"SSH connection inactive and failed to re-connect: {e}"

        try:
            logging.info(f"Executing command on BQRM: '{command}'")
            stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
            exit_status = stdout.channel.recv_exit_status()
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
        command = f"tail -n {LOG_LINES_TO_FETCH} {log_path}"
        success, output, error = self.execute_command(command)
        if success:
            return output
        else:
            logging.warning(f"Could not fetch log for {log_path}. Error: {error}")
            return f"Error fetching log file '{log_path}': {error}"

    def file_exists(self, remote_path):
        """
        Checks if a file exists on the remote server using SFTP.
        Returns True if exists, False otherwise (or on SSH error).
        """
        if not self.is_active():
            logging.warning(f"{datetime.datetime.now()} - SSH client inactive, cannot check file existence for {remote_path}.")
            return False

        try:
            self.sftp.stat(remote_path)
            return True
        except FileNotFoundError:
            return False
        except Exception as e:
            logging.error(f"{datetime.datetime.now()} - Error checking file existence for '{remote_path}': {e}")
            return False

    def download_file(self, remote_path, local_temp_dir="temp_downloads"):
        if not self.is_active():
            self._connect()
            if not self.is_active():
                logging.error(f"{datetime.datetime.now()} - Failed to download {remote_path}: SSH connection inactive.")
                return None, "SSH connection inactive."

        try:
            os.makedirs(local_temp_dir, exist_ok=True)
            filename = os.path.basename(remote_path)
            local_path = os.path.join(local_temp_dir, filename)
            
            logging.info(f"{datetime.datetime.now()} - Attempting to download remote file '{remote_path}' to local '{local_path}'")
            self.sftp.get(remote_path, local_path)
            logging.info(f"{datetime.datetime.now()} - Successfully downloaded '{remote_path}'")
            return local_path, None
        except FileNotFoundError:
            logging.error(f"{datetime.datetime.now()} - Remote file not found: {remote_path}")
            return None, f"Remote file not found: {remote_path}"
        except Exception as e:
            logging.error(f"{datetime.datetime.now()} - Error downloading file '{remote_path}': {e}")
            return None, str(e)

    def close(self):
        if self.client and self.client.get_transport() and self.client.get_transport().is_active():
            self.client.close()
            # Removed _is_connected as it's not a class member, rely on get_transport().is_active()
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
