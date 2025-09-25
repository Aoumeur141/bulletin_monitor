// script.js
document.addEventListener('DOMContentLoaded', () => {
    const bulletinsContainer = document.getElementById('bulletins-container');
    const refreshButton = document.getElementById('refreshButton');
    const lastUpdatedSpan = document.getElementById('lastUpdated');
    const logModal = document.getElementById('logModal');
    const closeButton = document.querySelector('.close-button');
    const modalBulletinName = document.getElementById('modalBulletinName');
    const modalLogContent = document.getElementById('modalLogContent');

    // Export buttons
    const exportErrorsButton = document.getElementById('exportErrorsButton');
    const exportWarningsButton = document.getElementById('exportWarningsButton');
    const exportCriticalButton = document.getElementById('exportCriticalButton');

    const API_BASE_URL = '/api';

    // Function to fetch and display bulletin statuses (summary)
    async function fetchBulletinsStatus() {
        refreshButton.disabled = true;
        refreshButton.classList.add('loading');
        const originalRefreshText = refreshButton.textContent;
        refreshButton.textContent = 'Refreshing...';

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
            bulletinsContainer.innerHTML = `<div class="loading-message status-SYSTEM_ERROR">Error loading bulletins: ${error.message}. Please check backend logs.</div>`;
            updateLastUpdated(true);
        } finally {
            refreshButton.disabled = false;
            refreshButton.classList.remove('loading');
            refreshButton.textContent = originalRefreshText;
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

            const warningBadge = bulletin.has_warnings ?
                '<span class="warning-badge" title="Warnings found in log">&#9888;</span>' : '';
            
            card.innerHTML = `
                <h2>${bulletin.name}</h2>
                <div class="bulletin-info">
                    <p>Status: <span class="status-indicator status-${bulletin.status}">${bulletin.status}</span>${warningBadge}</p>
                    <p>Last Run: <strong>${bulletin.last_run}</strong></p>
                </div>
                <div class="bulletin-actions" id="actions-${bulletin.id}">
                    <button class="rerun-button" data-id="${bulletin.id}">Rerun</button>
                    <button class="view-log-button" data-id="${bulletin.id}">View Log</button>
                    <!-- Download Product Buttons will be added dynamically here -->
                </div>
            `;
            bulletinsContainer.appendChild(card);

            const actionsDiv = card.querySelector(`#actions-${bulletin.id}`);
            // NEW: bulletin.product_info now contains availability
            if (bulletin.product_info && bulletin.product_info.length > 0) {
                bulletin.product_info.forEach((product_details, index) => { // Iterate over product_info
                    const downloadButton = document.createElement('button');
                    downloadButton.className = 'download-product-button';
                    downloadButton.dataset.id = bulletin.id;
                    downloadButton.dataset.productIndex = index; // Store the index
                    downloadButton.textContent = product_details.name || `Download Product ${index + 1}`;
                    
                    // Disable button if product is not available
                    if (!product_details.available) {
                        downloadButton.disabled = true;
                        downloadButton.title = `Product "${product_details.name}" not available for today.`;
                    }
                    actionsDiv.appendChild(downloadButton);
                });
            }
        });
    }

    // Function to handle bulletin re-run
    async function rerunBulletin(bulletinId, button) {
        if (!confirm(`Are you sure you want to re-run bulletin '${bulletinId}'?`)) {
            return;
        }

        button.disabled = true;
        const originalText = button.textContent;
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
                button.textContent = 'Rerun Success!';
                button.style.backgroundColor = 'var(--status-success)';
            } else {
                button.textContent = 'Rerun Failed!';
                button.style.backgroundColor = 'var(--status-failed)';
                console.error(`Failed to re-run ${bulletinId}:`, result.message || result.error);
                alert(`Failed to re-run ${bulletinId}: ${result.message || result.error}`);
            }
        } catch (error) {
            console.error("Error re-running bulletin:", error);
            button.textContent = 'Rerun Error!';
            button.style.backgroundColor = 'var(--status-failed)';
            alert(`An error occurred while trying to re-run ${bulletinId}. Check console for details.`);
        } finally {
            setTimeout(() => {
                button.textContent = originalText;
                button.style.backgroundColor = '';
                button.disabled = false;
                fetchBulletinsStatus(); // Refresh status after a brief delay
            }, 2000);
        }
    }

    // Function to show log modal
    async function showLogModal(bulletinId, button) {
        modalBulletinName.textContent = bulletinId;
        modalLogContent.innerHTML = '<div style="text-align: center; padding: 20px; color: var(--text-dim);">Loading full log...</div>';
        logModal.style.display = 'flex';

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

            modalBulletinName.textContent = data.name;
            modalLogContent.innerHTML = data.full_log || 'No log content available.';
            
            modalLogContent.dataset.styledLogHtml = data.full_log; 

        } catch (error) {
            console.error("Error fetching full log:", error);
            modalLogContent.innerHTML = `<div class="log-error">Error fetching full log: ${error.message}. Please check backend logs.</div>`;
        } finally {
            if (button) {
                button.disabled = false;
                button.textContent = 'View Log';
            }
        }
    }

    // NEW: Function to download bulletin product
    async function downloadBulletinProduct(bulletinId, productIndex, button) {
        if (button.disabled) { // Prevent action if button is already disabled (e.g., product not available)
            return;
        }

        button.disabled = true;
        const originalText = button.textContent;
        button.textContent = 'Downloading...';

        try {
            const response = await fetch(`${API_BASE_URL}/bulletins/${bulletinId}/download_product?index=${productIndex}`);
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.message || `HTTP error! status: ${response.status}`);
            }

            const contentDisposition = response.headers.get('Content-Disposition');
            let filename = `product_${bulletinId}_${new Date().toISOString().slice(0,10)}`;
            if (contentDisposition && contentDisposition.indexOf('attachment') !== -1) {
                const filenameMatch = contentDisposition.match(/filename="([^"]+)"/);
                if (filenameMatch && filenameMatch[1]) {
                    filename = filenameMatch[1];
                }
            }

            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            a.remove();

            button.textContent = 'Download Success!';
            button.style.backgroundColor = 'var(--status-success)';
        } catch (error) {
            console.error("Error downloading product:", error);
            button.textContent = 'Download Failed!';
            button.style.backgroundColor = 'var(--status-failed)';
            alert(`Failed to download product for ${bulletinId}: ${error.message}. Check console for details.`);
        } finally {
                setTimeout(() => {
                button.textContent = originalText;
                button.style.backgroundColor = '';
                // IMPORTANT: Re-fetch status to update the button's disabled state
                fetchBulletinsStatus(); 
            }, 2000);
        }
    }

    // Function to filter and export log content
    function filterAndExportLog(filterType) {
        const logContentHtml = modalLogContent.dataset.styledLogHtml;
        if (!logContentHtml || logContentHtml.includes('Loading full log...')) {
            alert("No log content loaded yet or an error occurred. Please wait or try again.");
            return;
        }

        let filteredLogLines = [];
        const dummyDiv = document.createElement('div');
        dummyDiv.innerHTML = logContentHtml;

        let className;
        if (filterType === 'errors') className = 'log-error';
        else if (filterType === 'warnings') className = 'log-warning';
        else if (filterType === 'critical') className = 'log-critical';
        else {
            alert("Invalid filter type.");
            return;
        }

        dummyDiv.childNodes.forEach(node => {
            if (node.nodeType === Node.ELEMENT_NODE && node.tagName === 'SPAN' && node.classList.contains(className)) {
                filteredLogLines.push(node.textContent);
            }
        });
        
        if (filteredLogLines.length === 0) {
            alert(`No ${filterType} entries found in the log to export.`);
            return;
        }

        const bulletinName = modalBulletinName.textContent;
        const blob = new Blob([filteredLogLines.join('\n')], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${bulletinName}_${filterType}_log_${new Date().toISOString().slice(0,10)}.log`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    // Function to update the last updated timestamp
    function updateLastUpdated(isError = false) {
        const now = new Date();
        lastUpdatedSpan.textContent = `Last updated: ${now.toLocaleTimeString()} ${isError ? '(System Error)' : ''}`;
        if (isError) {
            lastUpdatedSpan.style.color = 'var(--status-system-error)';
        } else {
            lastUpdatedSpan.style.color = 'var(--text-secondary)';
        }
    }

    // --- Event Listeners ---

    // Event delegation for bulletin card buttons
    bulletinsContainer.addEventListener('click', (event) => {
        const target = event.target;
        if (target.classList.contains('rerun-button')) {
            rerunBulletin(target.dataset.id, target);
        } else if (target.classList.contains('view-log-button')) {
            showLogModal(target.dataset.id, target);
        } else if (target.classList.contains('download-product-button')) {
            downloadBulletinProduct(target.dataset.id, target.dataset.productIndex, target);
        }
    });

    closeButton.onclick = () => {
        logModal.style.display = 'none';
    };

    window.onclick = (event) => {
        if (event.target == logModal) {
            logModal.style.display = 'none';
        }
    };

    exportErrorsButton.addEventListener('click', () => filterAndExportLog('errors'));
    exportWarningsButton.addEventListener('click', () => filterAndExportLog('warnings'));
    exportCriticalButton.addEventListener('click', () => filterAndExportLog('critical'));

    refreshButton.addEventListener('click', fetchBulletinsStatus);

    fetchBulletinsStatus();

    setInterval(fetchBulletinsStatus, 30000); // 30 seconds
});

