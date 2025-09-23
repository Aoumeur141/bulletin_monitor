document.addEventListener('DOMContentLoaded', () => {
    const bulletinsContainer = document.getElementById('bulletins-container');
    const refreshButton = document.getElementById('refreshButton');
    const lastUpdatedSpan = document.getElementById('lastUpdated');
    const logModal = document.getElementById('logModal');
    const closeButton = document.querySelector('.close-button');
    const modalBulletinName = document.getElementById('modalBulletinName');
    const modalLogContent = document.getElementById('modalLogContent');

    const API_BASE_URL = '/api'; // Flask backend API base URL

    // Function to fetch and display bulletin statuses (summary)
    async function fetchBulletinsStatus() {
        bulletinsContainer.innerHTML = '<div class="loading-message">Loading bulletin statuses...</div>';
        try {
            const response = await fetch(`${API_BASE_URL}/bulletins`);
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.message || `HTTP error! status: ${response.status}`);
            }
            const bulletins = await response.json();
            renderBulletins(bulletins);
            updateLastUpdated();
        } catch (error) {
            console.error("Error fetching bulletin statuses:", error);
            bulletinsContainer.innerHTML = `<div class="loading-message status-ERROR">Error loading bulletins: ${error.message}. Please check backend logs.</div>`;
            updateLastUpdated(true);
        }
    }

    // Function to render bulletin cards
    function renderBulletins(bulletins) {
        bulletinsContainer.innerHTML = ''; // Clear previous content
        if (bulletins.length === 0) {
            bulletinsContainer.innerHTML = '<div class="loading-message">No bulletins configured or found.</div>';
            return;
        }

        bulletins.forEach(bulletin => {
            const card = document.createElement('div');
            card.className = 'bulletin-card';
            card.innerHTML = `
                <h2>${bulletin.name}</h2>
                <div class="bulletin-info">
                    <p>Status: <span class="status-indicator status-${bulletin.status}">${bulletin.status}</span></p>
                    <p>Last Run: <strong>${bulletin.last_run}</strong></p>
                    <p>Summary: <em>${bulletin.last_log_summary}</em></p>
                </div>
                <div class="bulletin-actions">
                    <button class="rerun-button" data-id="${bulletin.id}" ${bulletin.status === 'ERROR' ? 'disabled' : ''}>Rerun</button>
                    <button class="view-log-button" data-id="${bulletin.id}">View Log</button>
                    <a href="${bulletin.code_link}" target="_blank" class="code-link-button">Go to Code</a>
                </div>
            `;
            bulletinsContainer.appendChild(card);
        });

        // Attach event listeners to new buttons
        attachButtonListeners();
    }

    // Function to attach event listeners to buttons
    function attachButtonListeners() {
        document.querySelectorAll('.rerun-button').forEach(button => {
            button.onclick = () => rerunBulletin(button.dataset.id);
        });

        document.querySelectorAll('.view-log-button').forEach(button => {
            button.onclick = () => showLogModal(button.dataset.id, button); // Pass the button element
        });
    }

    // Function to handle bulletin re-run
    async function rerunBulletin(bulletinId) {
        if (!confirm(`Are you sure you want to re-run bulletin '${bulletinId}'?`)) {
            return;
        }

        const button = document.querySelector(`.rerun-button[data-id="${bulletinId}"]`);
        button.disabled = true;
        button.textContent = 'Rerunning...';

        try {
            const response = await fetch(`${API_BASE_URL}/bulletins/${bulletinId}/rerun`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            const result = await response.json();

            if (result.success) {
                alert(`Successfully sent re-run command for ${bulletinId}. Please refresh to see updated status.`);
            } else {
                alert(`Failed to re-run ${bulletinId}: ${result.message || result.error}`);
            }
        } catch (error) {
            console.error("Error re-running bulletin:", error);
            alert(`An error occurred while trying to re-run ${bulletinId}. Check console for details.`);
        } finally {
            button.disabled = false;
            button.textContent = 'Rerun';
            // Optionally, refresh status immediately after a rerun attempt
            fetchBulletinsStatus();
        }
    }

    // Function to show log modal - NOW FETCHES FULL LOG ON DEMAND
    async function showLogModal(bulletinId, button) {
        modalBulletinName.textContent = bulletinId; // Temporarily set to ID
        modalLogContent.textContent = 'Loading full log...';
        logModal.style.display = 'block';

        // Disable button while loading
        if (button) {
            button.disabled = true;
            button.textContent = 'Loading Log...';
        }

        try {
            const response = await fetch(`${API_BASE_URL}/bulletins/${bulletinId}/full_log`);
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.message || `HTTP error! status: ${response.status}`);
            }
            const data = await response.json();

            modalBulletinName.textContent = data.name; // Set actual name
            modalLogContent.textContent = data.full_log || 'No log content available.';

        } catch (error) {
            console.error("Error fetching full log:", error);
            modalLogContent.textContent = `Error fetching full log: ${error.message}. Please check backend logs.`;
        } finally {
            // Re-enable button
            if (button) {
                button.disabled = false;
                button.textContent = 'View Log';
            }
        }
    }

    // Function to update the last updated timestamp
    function updateLastUpdated(isError = false) {
        const now = new Date();
        lastUpdatedSpan.textContent = `Last updated: ${now.toLocaleTimeString()} ${isError ? '(Error during fetch)' : ''}`;
        if (isError) {
            lastUpdatedSpan.style.color = 'red';
        } else {
            lastUpdatedSpan.style.color = '#666';
        }
    }

    // Close modal when close button is clicked
    closeButton.onclick = () => {
        logModal.style.display = 'none';
    };

    // Close modal when clicking outside of it
    window.onclick = (event) => {
        if (event.target == logModal) {
            logModal.style.display = 'none';
        }
    };

    // Initial fetch on page load
    fetchBulletinsStatus();

    // Set up auto-refresh (e.g., every 30 seconds)
    setInterval(fetchBulletinsStatus, 30000); // 30 seconds

    // Manual refresh button
    refreshButton.addEventListener('click', fetchBulletinsStatus);
});
