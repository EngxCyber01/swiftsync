
            // ===================================
            // GLOBAL VARIABLES - DECLARE FIRST
            // ===================================
            
            // Safe localStorage wrapper to prevent access errors
            var safeStorage = {
                _setCookie: function(name, value, days) {
                    var expires = "";
                    if (days) {
                        var date = new Date();
                        date.setTime(date.getTime() + (days * 24 * 60 * 60 * 1000));
                        expires = "; expires=" + date.toUTCString();
                    }
                    var isSecure = window.location.protocol === 'https:';
                    var sameSite = isSecure ? 'SameSite=None; Secure' : 'SameSite=Lax';
                    document.cookie = name + "=" + (value || "") + expires + "; path=/; " + sameSite;
                },
                _getCookie: function(name) {
                    var nameEQ = name + "=";
                    var ca = document.cookie.split(';');
                    for (var i = 0; i < ca.length; i++) {
                        var c = ca[i];
                        while (c.charAt(0) == ' ') c = c.substring(1, c.length);
                        if (c.indexOf(nameEQ) == 0) return c.substring(nameEQ.length, c.length);
                    }
                    return null;
                },
                _deleteCookie: function(name) {
                    document.cookie = name + '=; Path=/; Expires=Thu, 01 Jan 1970 00:00:01 GMT;';
                },
                getItem: function(key) {
                    try {
                        var value = localStorage.getItem(key);
                        if (!value) {
                            value = this._getCookie(key);
                            if (value) {
                                try {
                                    localStorage.setItem(key, value);
                                } catch (e) {}
                            }
                        }
                        return value;
                    } catch (e) {
                        return this._getCookie(key);
                    }
                },
                setItem: function(key, value) {
                    try {
                        localStorage.setItem(key, value);
                        this._setCookie(key, value, 7);
                        return true;
                    } catch (e) {
                        this._setCookie(key, value, 7);
                        return false;
                    }
                },
                removeItem: function(key) {
                    try {
                        localStorage.removeItem(key);
                    } catch (e) {}
                    this._deleteCookie(key);
                }
            };
            
            // Attendance variables - Use safe storage
            var attendanceSessionToken = safeStorage.getItem('attendance_session_token') || null;
            var attendanceUsername = safeStorage.getItem('attendance_username') || null;
            var attendanceRefreshInterval = null;
            
            // Data cache for private sections (cleared on logout)
            var cachedResultAlerts = null;
            var cachedOfficialResults = null;
            var cachedAttendanceData = null;
            
            // Lectures data variables
            let allFilesData = {};
            let originalFilesData = {}; // Keep original data for search reset
            
            // ===================================
            // KURDISH TEXT ANIMATION
            // ===================================
            
            // Kurdish Text Typewriter Animation
            const kurdishTexts = [
                'ڕۆژئاوا ڕۆژهەڵاتە،کوردستان یەک وڵاتە ',
                'Rojava Rojhilat e,Kurdistan yek welat e '
            ];
            
            let currentTextIndex = 0;
            let currentCharIndex = 0;
            let isDeleting = false;
            let isPaused = false;
            let showEmoji = false;
            
            function typeWriter() {
                const element = document.getElementById('kurdishText');
                const currentText = kurdishTexts[currentTextIndex];
                
                if (isPaused) {
                    setTimeout(typeWriter, 1200); // Pause duration
                    isPaused = false;
                    return;
                }
                
                if (!isDeleting) {
                    // Typing
                    element.textContent = currentText.substring(0, currentCharIndex + 1);
                    currentCharIndex++;
                    
                    if (currentCharIndex === currentText.length) {
                        isPaused = true;
                        isDeleting = true;
                    }
                    
                    setTimeout(typeWriter, 60); // Faster, smoother typing
                } else {
                    // Deleting
                    element.textContent = currentText.substring(0, currentCharIndex - 1);
                    currentCharIndex--;
                    
                    if (currentCharIndex === 0) {
                        isDeleting = false;
                        currentTextIndex = (currentTextIndex + 1) % kurdishTexts.length;
                        setTimeout(typeWriter, 400); // Shorter pause
                    } else {
                        setTimeout(typeWriter, 30); // Faster deleting
                    }
                }
            }
            
            // Start animation immediately for smoother UX
            document.addEventListener('DOMContentLoaded', () => {
                setTimeout(typeWriter, 100); // Start almost immediately
            });
            
            // Disable right-click for professional web app feel
            document.addEventListener('contextmenu', (e) => {
                e.preventDefault();
                return false;
            });
            
            // Disable common dev tools shortcuts
            document.addEventListener('keydown', (e) => {
                if (e.key === 'F12' || 
                    (e.ctrlKey && e.shiftKey && (e.key === 'I' || e.key === 'J' || e.key === 'C')) ||
                    (e.ctrlKey && e.key === 'U')) {
                    e.preventDefault();
                    return false;
                }
            });
            
            // Session management - 7 days expiration
            var SESSION_DURATION = 7 * 24 * 60 * 60 * 1000; // 7 days in milliseconds
            
            // Session helper functions
            function formatBytes(bytes) {
                if (bytes === 0) return '0 B';
                const k = 1024;
                const sizes = ['B', 'KB', 'MB', 'GB'];
                const i = Math.floor(Math.log(bytes) / Math.log(k));
                return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
            }
            
            function getFileIcon(filename) {
                const ext = filename.split('.').pop().toLowerCase();
                const icons = {
                    pdf: '<i class="fas fa-file-pdf"></i>',
                    doc: '<i class="fas fa-file-word"></i>',
                    docx: '<i class="fas fa-file-word"></i>',
                    ppt: '<i class="fas fa-file-powerpoint"></i>',
                    pptx: '<i class="fas fa-file-powerpoint"></i>',
                    zip: '<i class="fas fa-file-archive"></i>',
                    rar: '<i class="fas fa-file-archive"></i>',
                    mp4: '<i class="fas fa-file-video"></i>',
                    avi: '<i class="fas fa-file-video"></i>'
                };
                return icons[ext] || '<i class="fas fa-file"></i>';
            }
            
            function getFileClass(filename) {
                const ext = filename.split('.').pop().toLowerCase();
                if (['pdf'].includes(ext)) return 'pdf';
                if (['doc', 'docx'].includes(ext)) return 'doc';
                if (['ppt', 'pptx'].includes(ext)) return 'ppt';
                return 'default';
            }
            
            function renderFiles(data, isFiltering = false) {
                console.log('🎨 Rendering files...', data);
                // Only update original data on initial load, not during filtering
                if (!isFiltering) {
                    allFilesData = data;
                    originalFilesData = JSON.parse(JSON.stringify(data)); // Deep copy
                }
                const fileGrid = document.getElementById('fileGrid');
                const semesters = Object.keys(data);
                console.log('📚 Semesters found:', semesters);
                
                if (semesters.length === 0) {
                    fileGrid.innerHTML = `
                        <div class="empty-state" style="padding: 3rem;">
                            <i class="fas fa-cloud-download-alt" style="font-size: 4rem; color: var(--primary); margin-bottom: 1rem;"></i>
                            <h3 style="color: var(--text-primary); margin-bottom: 0.5rem;">No Lectures Yet</h3>
                            <p style="color: var(--text-secondary); margin-bottom: 1.5rem;">Click "Sync Now" to fetch your latest lectures</p>
                            <button onclick="syncNow()" style="padding: 0.75rem 1.5rem; background: var(--primary); color: white; border: none; border-radius: 12px; cursor: pointer; font-size: 1rem; font-weight: 600; display: inline-flex; align-items: center; gap: 0.5rem; transition: all 0.2s;">
                                <i class="fas fa-sync-alt"></i> Sync Now
                            </button>
                        </div>
                    `;
                    // Update stats to show 0 when no results
                    document.getElementById('totalFiles').textContent = 0;
                    document.getElementById('totalSize').textContent = formatBytes(0);
                    document.getElementById('totalSubjects').textContent = 0;
                    return;
                }
                
                let html = '';
                let totalFiles = 0;
                let totalSize = 0;
                let totalSubjects = 0;
                
                // Sort semesters (Fall first, then Spring)
                const semesterOrder = ['Fall Semester', 'Spring Semester'];
                const sortedSemesters = semesters.sort((a, b) => {
                    const aIndex = semesterOrder.indexOf(a);
                    const bIndex = semesterOrder.indexOf(b);
                    if (aIndex === -1) return 1;
                    if (bIndex === -1) return -1;
                    return aIndex - bIndex;
                });
                
                sortedSemesters.forEach(semester => {
                    const subjects = data[semester];
                    const subjectNames = Object.keys(subjects);
                    totalSubjects += subjectNames.length;
                    
                    // Calculate semester stats
                    let semesterFiles = 0;
                    subjectNames.forEach(subject => {
                        semesterFiles += subjects[subject].length;
                        subjects[subject].forEach(f => totalSize += f.size_bytes);
                    });
                    totalFiles += semesterFiles;
                    
                    // Semester section (using same styling as subject-section)
                    html += `
                        <div class="subject-section" style="margin-bottom: 1.5rem;">
                            <div class="subject-header" onclick="toggleSemester(this)" style="background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 100%); cursor: pointer;">
                                <div class="subject-title" style="color: white; font-size: 1.1rem; font-weight: 700;">
                                    <i class="fas fa-calendar-alt" style="color: white;"></i>
                                    ${semester}
                                    <span class="file-count" style="background: rgba(255,255,255,0.2); color: white;">${semesterFiles} file${semesterFiles > 1 ? 's' : ''}</span>
                                </div>
                                <div class="collapse-btn">
                                    <i class="fas fa-chevron-down" style="color: white; transform: rotate(-90deg);"></i>
                                </div>
                            </div>
                            <div class="semester-content" style="display: none; padding-left: 0;">
                    `;
                    
                    // Subjects within semester
                    subjectNames.sort().forEach(subject => {
                        const files = subjects[subject];
                        
                        html += `
                            <div class="subject-section" style="margin-left: 1rem; margin-bottom: 1rem;">
                                <div class="subject-header" onclick="toggleSubject(this)">
                                    <div class="subject-title">
                                        <i class="fas fa-book"></i>
                                        ${subject}
                                        <span class="file-count">${files.length} file${files.length > 1 ? 's' : ''}</span>
                                    </div>
                                    <div class="collapse-btn">
                                        <i class="fas fa-chevron-down"></i>
                                    </div>
                                </div>
                                <div class="subject-files">
                                    ${files.map(file => `
                                        <div class="file-item">
                                            <div class="file-icon ${getFileClass(file.name)}">
                                                ${getFileIcon(file.name)}
                                            </div>
                                            <div class="file-info">
                                                <div class="file-name">${file.name}</div>
                                                <div class="file-meta">
                                                    <span><i class="fas fa-clock"></i> ${new Date(file.modified).toLocaleDateString()}</span>
                                                </div>
                                            </div>
                                            <div class="file-size">${formatBytes(file.size_bytes)}</div>
                                            <a href="${file.url}" class="open-btn" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation();">
                                                <i class="fas fa-external-link-alt"></i>
                                                <span>Open</span>
                                            </a>
                                            <button class="download-btn" onclick="downloadFile(this.dataset.url, this.dataset.name, event); return false;" data-url="${file.url}" data-name="${file.name}">
                                                <i class="fas fa-download"></i>
                                                <span>Download</span>
                                            </button>
                                        </div>
                                    `).join('')}
                                </div>
                            </div>
                        `;
                    });
                    
                    html += `
                            </div>
                        </div>
                    `;
                });
                
                fileGrid.innerHTML = html;
                document.getElementById('totalFiles').textContent = totalFiles;
                document.getElementById('totalSize').textContent = formatBytes(totalSize);
                document.getElementById('totalSubjects').textContent = totalSubjects;
                console.log('✅ Stats updated:', {totalFiles, totalSize, totalSubjects});
            }
            
            function toggleSubject(header) {
                const section = header.closest('.subject-section');
                const files = section.querySelector('.subject-files');
                const icon = header.querySelector('.collapse-btn i');
                
                if (files.style.display === 'none' || files.style.display === '') {
                    files.style.display = 'block';
                    icon.style.transform = 'rotate(0deg)';
                } else {
                    files.style.display = 'none';
                    icon.style.transform = 'rotate(-90deg)';
                }
            }
            
            function toggleSemester(header) {
                const section = header.closest('.subject-section');
                const content = section.querySelector('.semester-content');
                const icon = header.querySelector('.collapse-btn i');
                
                if (content.style.display === 'none') {
                    content.style.display = 'block';
                    icon.style.transform = 'rotate(0deg)';
                } else {
                    content.style.display = 'none';
                    icon.style.transform = 'rotate(-90deg)';
                }
            }
            
            // Search functionality
            document.getElementById('searchInput').addEventListener('input', (e) => {
                const query = e.target.value.toLowerCase().trim();
                if (!query) {
                    // Restore original full data when search is cleared
                    renderFiles(originalFilesData, false);
                    return;
                }
                
                const filtered = {};
                // Search through semester → subject → files structure
                Object.keys(originalFilesData).forEach(semester => {
                    const subjects = originalFilesData[semester];
                    Object.keys(subjects).forEach(subject => {
                        const matchingFiles = subjects[subject].filter(file => 
                            file.name.toLowerCase().includes(query) ||
                            subject.toLowerCase().includes(query) ||
                            semester.toLowerCase().includes(query)
                        );
                        if (matchingFiles.length > 0) {
                            if (!filtered[semester]) filtered[semester] = {};
                            filtered[semester][subject] = matchingFiles;
                        }
                    });
                });
                
                renderFiles(filtered, true);
            });
            
            // Sync Now functionality
            async function syncNow() {
                const btn = document.getElementById('syncBtn');
                const icon = btn.querySelector('i');
                
                btn.disabled = true;
                icon.classList.add('fa-spin');
                
                try {
                    const response = await fetch('/api/sync-now', { method: 'POST' });
                    const result = await response.json();
                    
                    if (result.success) {
                        showNotification('✅ Sync completed!', 'success');
                        loadFiles(); // Reload files
                    } else {
                        showNotification(`❌ Sync failed: ${result.error}`, 'error');
                    }
                } catch (error) {
                    showNotification(`❌ Error: ${error.message}`, 'error');
                } finally {
                    btn.disabled = false;
                    icon.classList.remove('fa-spin');
                }
            }
            
            // Show Notification Function
            function showNotification(message, type = 'success') {
                const notification = document.createElement('div');
                notification.className = `notification notification-${type}`;
                notification.innerHTML = `
                    <i class="fas fa-${type === 'success' ? 'check-circle' : 'exclamation-circle'}"></i>
                    <span>${message}</span>
                `;
                document.body.appendChild(notification);
                
                // Trigger animation
                setTimeout(() => notification.classList.add('show'), 100);
                
                // Remove after 3 seconds
                setTimeout(() => {
                    notification.classList.remove('show');
                    setTimeout(() => notification.remove(), 400);
                }, 3000);
            }
            
            // Download File Function
            async function downloadFile(url, filename, event) {
                if (event) {
                    event.preventDefault();
                    event.stopPropagation();
                }
                
                try {
                    // OFFLINE CHECK: Don't attempt download if offline
                    if (!navigator.onLine) {
                        showNotification('❌ No internet connection', 'error');
                        return;
                    }
                    
                    // Generate unique download URL with timestamp to prevent 'download again' dialog
                    const timestamp = new Date().getTime();
                    const downloadUrl = `/api/download/${encodeURIComponent(filename)}?_=${timestamp}`;
                    
                    // Fetch with strict no-cache policy
                    const response = await fetch(downloadUrl, {
                        cache: 'no-store',
                        headers: {
                            'Cache-Control': 'no-cache, no-store, must-revalidate',
                            'Pragma': 'no-cache'
                        }
                    });
                    
                    if (!response.ok) throw new Error('Download failed');
                    
                    const blob = await response.blob();
                    const blobUrl = URL.createObjectURL(blob);
                    
                    // Create hidden link and trigger download
                    const a = document.createElement('a');
                    a.style.display = 'none';
                    a.href = blobUrl;
                    a.download = filename;
                    document.body.appendChild(a);
                    
                    // MOBILE FIX: Only show notification after download actually starts
                    // No premature notification - let the browser handle the download
                    a.click();
                    
                    // Cleanup after reasonable time (no notification)
                    setTimeout(() => {
                        document.body.removeChild(a);
                        URL.revokeObjectURL(blobUrl);
                    }, 2000);
                } catch (error) {
                    // Only show notification on actual errors
                    showNotification('❌ Download failed!', 'error');
                    console.error('Download error:', error);
                }
            }
            
            // Restore last active zone on page load (default to lectures)
            window.addEventListener('load', () => {
                const lastZone = localStorage.getItem('lastActiveZone');
                const lastPrivateSection = localStorage.getItem('lastPrivateSection');
                
                // Always default to lectures unless explicitly on private
                if (lastZone && lastZone === 'private') {
                    // Don't auto-switch to private, keep lectures as default
                }
                
                // Restore last private section if applicable
                if (lastPrivateSection && (lastPrivateSection === 'result-alerts' || lastPrivateSection === 'official-results')) {
                    // Will be restored when private mode is activated by checkAttendanceSession
                }
                
                // Lectures is already active by default in HTML
            });
            
            // Load files on page load
            async function loadFiles() {
                try {
                    console.log('📡 Fetching lectures from API...');
                    
                    // OFFLINE CHECK: Show cached data or friendly message
                    if (!navigator.onLine) {
                        console.log('📴 Offline - attempting to load cached data');
                    }
                    
                    const response = await fetch('/api/files');
                    console.log('✅ API response received:', response.status);
                    
                    // Handle offline or network errors gracefully
                    if (!response.ok) {
                        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                    }
                    
                    const data = await response.json();
                    console.log('📊 Data loaded:', Object.keys(data).length, 'semesters');
                    renderFiles(data);
                } catch (error) {
                    console.error('❌ Error loading files:', error);
                    
                    // Friendly offline message without panic
                    const errorMsg = !navigator.onLine 
                        ? 'You are offline. Connect to internet to load lectures.'
                        : error.message;
                    
                    document.getElementById('fileGrid').innerHTML = `
                        <div class="empty-state">
                            <i class="fas fa-${!navigator.onLine ? 'wifi-slash' : 'exclamation-triangle'}"></i>
                            <h3>${!navigator.onLine ? 'No Internet Connection' : 'Error Loading Files'}</h3>
                            <p>${errorMsg}</p>
                            <button onclick="loadFiles()" style="margin-top: 1rem; padding: 0.5rem 1rem; background: var(--accent); color: white; border: none; border-radius: 8px; cursor: pointer;">
                                <i class="fas fa-sync"></i> Retry
                            </button>
                        </div>
                    `;
                }
            }
            
            // Initialize - Load files immediately  
            console.log('🚀 Initializing dashboard...');
            
            // Make sure DOM is fully loaded
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', () => {
                    console.log('📄 DOM loaded, calling loadFiles()...');
                    loadFiles();
                });
            } else {
                // DOM already loaded
                console.log('📄 DOM already ready, calling loadFiles()...');
                loadFiles();
            }
            
            // ===== AI SUMMARIZATION FUNCTIONS =====
            
            function openSummaryModal() {
                document.getElementById('summaryModal').classList.add('active');
                document.body.style.overflow = 'hidden';
            }
            
            function closeSummaryModal() {
                document.getElementById('summaryModal').classList.remove('active');
                document.body.style.overflow = 'auto';
            }
            
            // Close modal when clicking outside
            document.getElementById('summaryModal').addEventListener('click', (e) => {
                if (e.target.id === 'summaryModal') {
                    closeSummaryModal();
                }
            });
            
            // Close modal with Escape key
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') {
                    closeSummaryModal();
                }
            });
            
            function showLoadingInModal(title) {
                document.getElementById('modalTitle').innerHTML = `<i class="fas fa-brain"></i> ${title}`;
                document.getElementById('modalBody').innerHTML = `
                    <div class="summary-loading">
                        <div class="spinner"></div>
                        <p style="color: var(--text-secondary); font-weight: 600;">
                            <i class="fas fa-magic"></i> AI is analyzing the content...
                        </p>
                        <p style="color: var(--text-tertiary); font-size: 0.85rem; margin-top: 0.5rem;">
                            This may take a few moments
                        </p>
                    </div>
                `;
                openSummaryModal();
            }
            
            function showErrorInModal(title, error) {
                document.getElementById('modalTitle').innerHTML = `<i class="fas fa-exclamation-triangle"></i> ${title}`;
                document.getElementById('modalBody').innerHTML = `
                    <div class="summary-error">
                        <i class="fas fa-exclamation-circle"></i>
                        <h3>Summarization Failed</h3>
                        <p>${error}</p>
                    </div>
                `;
            }
            
            function displaySummary(data, isMultiple = false) {
                const modalBody = document.getElementById('modalBody');
                
                let metaHtml = '<div class="summary-meta">';
                
                if (!isMultiple) {
                    metaHtml += `
                        <div class="summary-meta-item">
                            <i class="fas fa-file-pdf"></i>
                            <span>${data.filename}</span>
                        </div>
                    `;
                } else {
                    metaHtml += `
                        <div class="summary-meta-item">
                            <i class="fas fa-layer-group"></i>
                            <span>${data.files_included ? data.files_included.length : 0} file(s) analyzed</span>
                        </div>
                    `;
                }
                
                if (data.token_usage) {
                    metaHtml += `
                        <div class="summary-meta-item">
                            <i class="fas fa-brain"></i>
                            <span>AI Tokens: ${data.token_usage.total}</span>
                        </div>
                    `;
                }
                
                metaHtml += '</div>';
                
                // Convert markdown-style content to HTML
                let summaryHtml = data.summary
                    .replace(/## (.*?)\n/g, '<h2>$1</h2>')
                    .replace(/\n\n/g, '</p><p>')
                    .replace(/- (.*?)\n/g, '<li>$1</li>');
                
                // Wrap list items in ul tags
                summaryHtml = summaryHtml.replace(/(<li>.*?<\/li>)+/gs, '<ul>$&</ul>');
                
                // Wrap content in paragraphs if not already wrapped
                if (!summaryHtml.startsWith('<h2>') && !summaryHtml.startsWith('<p>')) {
                    summaryHtml = '<p>' + summaryHtml + '</p>';
                }
                
                modalBody.innerHTML = metaHtml + '<div class="summary-content">' + summaryHtml + '</div>';
            }
            
            async function summarizeLecture(filename, event) {
                // Prevent any default actions
                if (event) {
                    event.preventDefault();
                    event.stopPropagation();
                }
                
                const btn = event.target.closest('.summary-btn');
                if (btn) {
                    btn.disabled = true;
                    btn.querySelector('i').classList.add('fa-spin');
                }
                
                try {
                    showLoadingInModal('Generating Summary');
                    
                    const response = await fetch(`/api/summarize?filename=${encodeURIComponent(filename)}`, {
                        method: 'POST'
                    });
                    
                    const result = await response.json();
                    
                    if (result.success) {
                        document.getElementById('modalTitle').innerHTML = `
                            <i class="fas fa-brain"></i> Summary: ${filename}
                        `;
                        displaySummary(result.data, false);
                    } else {
                        showErrorInModal('Error', result.error);
                    }
                } catch (error) {
                    showErrorInModal('Error', `Failed to generate summary: ${error.message}`);
                } finally {
                    if (btn) {
                        btn.disabled = false;
                        btn.querySelector('i').classList.remove('fa-spin');
                    }
                }
            }
            
            async function summarizeAllLectures(subject, event) {
                // Prevent any default actions
                if (event) {
                    event.preventDefault();
                    event.stopPropagation();
                }
                
                const btn = event.target.closest('.summarize-all-btn');
                if (btn) {
                    btn.disabled = true;
                    btn.querySelector('i').classList.add('fa-spin');
                }
                
                try {
                    showLoadingInModal(`Analyzing All Lectures in ${subject}`);
                    
                    const response = await fetch(`/api/summarize-all?subject=${encodeURIComponent(subject)}`, {
                        method: 'POST'
                    });
                    
                    const result = await response.json();
                    
                    if (result.success) {
                        document.getElementById('modalTitle').innerHTML = `
                            <i class="fas fa-magic"></i> Combined Summary: ${subject}
                        `;
                        displaySummary(result.data, true);
                    } else {
                        showErrorInModal('Error', result.error);
                    }
                } catch (error) {
                    showErrorInModal('Error', `Failed to generate summary: ${error.message}`);
                } finally {
                    if (btn) {
                        btn.disabled = false;
                        btn.querySelector('i').classList.remove('fa-spin');
                    }
                }
            }
            
            // ===================================
            // GLOBAL VARIABLES - MUST BE DECLARED FIRST
            // ===================================
            
            // ===================================
            // ATTENDANCE SESSION MANAGEMENT
            // ===================================
            
            // Session management - already declared at top
            // SESSION_DURATION already defined
            
            // Session helper functions
            function updateSessionTimestamp() {
                var timestamp = Date.now();
                safeStorage.setItem('attendance_session_timestamp', timestamp.toString());
                console.log('Session timestamp updated:', new Date(timestamp).toLocaleString());
            }
            
            function isSessionExpired() {
                var timestampStr = safeStorage.getItem('attendance_session_timestamp');
                if (!timestampStr) return true;
                
                var timestamp = parseInt(timestampStr);
                var now = Date.now();
                var elapsed = now - timestamp;
                
                if (elapsed > SESSION_DURATION) {
                    console.log('Session expired:', elapsed / (1000 * 60 * 60 * 24), 'days old');
                    return true;
                }
                return false;
            }
            
            // PWA install prompt
            var deferredPrompt = null;
            
            // ===================================
            // ZONE SWITCHING
            // ===================================
            
            function switchZone(zone) {
                // Update tabs
                document.querySelectorAll('.zone-tab').forEach(tab => tab.classList.remove('active'));
                document.querySelectorAll('.zone-content').forEach(content => content.classList.remove('active'));
                
                if (zone === 'lectures') {
                    document.getElementById('lecturesTab').classList.add('active');
                    document.getElementById('lecturesZone').classList.add('active');
                    localStorage.setItem('lastActiveZone', 'lectures');
                } else if (zone === 'private') {
                    document.getElementById('privateTab').classList.add('active');
                    document.getElementById('privateZone').classList.add('active');
                    localStorage.setItem('lastActiveZone', 'private');
                    
                    // Check if user has a saved session
                    checkAttendanceSession();
                }
            }
            
            // Switch between Attendance, Result Alerts, and Official Results within Private Mode
            function switchPrivateSection(section) {
                // Update subtabs
                document.querySelectorAll('.private-subtab').forEach(tab => tab.classList.remove('active'));
                document.querySelectorAll('.private-section').forEach(content => content.classList.remove('active'));
                
                if (section === 'attendance') {
                    document.getElementById('attendanceSubtab').classList.add('active');
                    document.getElementById('attendanceSection').classList.add('active');
                    localStorage.setItem('lastPrivateSection', 'attendance');
                } else if (section === 'result-alerts') {
                    document.getElementById('resultAlertsSubtab').classList.add('active');
                    document.getElementById('resultAlertsSection').classList.add('active');
                    localStorage.setItem('lastPrivateSection', 'result-alerts');
                    
                    // Load result alerts - use cache if available
                    if (attendanceSessionToken) {
                        if (cachedResultAlerts) {
                            // Instantly show cached data
                            renderResultsCards(cachedResultAlerts.results, cachedResultAlerts.totalCount);
                            // Optional: background refresh without showing spinner
                            fetchResultAlerts(true);
                        } else {
                            // First load - fetch with loading spinner
                            fetchResultAlerts(false);
                        }
                    }
                } else if (section === 'official-results') {
                    document.getElementById('officialResultsSubtab').classList.add('active');
                    document.getElementById('officialResultsSection').classList.add('active');
                    localStorage.setItem('lastPrivateSection', 'official-results');
                    
                    // Load official results - use cache if available
                    if (attendanceSessionToken) {
                        if (cachedOfficialResults) {
                            // Instantly show cached data
                            renderOfficialResults(cachedOfficialResults);
                            // Optional: background refresh without showing spinner
                            fetchOfficialResults(true);
                        } else {
                            // First load - fetch with loading spinner
                            fetchOfficialResults(false);
                        }
                    }
                }
            }
            
            // ===================================
            // ATTENDANCE FUNCTIONS
            // ===================================
            
            function checkAttendanceSession() {
                // Check if session is expired
                if (attendanceSessionToken && isSessionExpired()) {
                    console.log('Session expired, clearing...');
                    // Clear expired session
                    attendanceSessionToken = null;
                    safeStorage.removeItem('attendance_session_token');
                    safeStorage.removeItem('attendance_session_timestamp');
                }
                
                // Check for saved credentials (encrypted in base64)
                const savedCreds = safeStorage.getItem('attendance_credentials');
                
                if (savedCreds && !attendanceSessionToken) {
                    // Auto-fill and auto-login
                    try {
                        const creds = JSON.parse(atob(savedCreds));
                        document.getElementById('attendanceUsername').value = creds.u;
                        document.getElementById('attendancePassword').value = creds.p;
                        document.getElementById('rememberMe').checked = true;
                        
                        // Auto-login silently
                        setTimeout(() => {
                            document.getElementById('attendanceLoginForm').dispatchEvent(new Event('submit'));
                        }, 100);
                    } catch (e) {
                        console.error('Failed to load saved credentials');
                        // Show login form
                        document.getElementById('privateLoginArea').style.display = 'block';
                        document.getElementById('privateDataArea').style.display = 'none';
                    }
                } else if (attendanceSessionToken) {
                    // User has a valid session, try to load attendance data
                    updateSessionTimestamp(); // Refresh session
                    loadAttendanceData();
                } else {
                    // Show login form
                    document.getElementById('privateLoginArea').style.display = 'block';
                    document.getElementById('privateDataArea').style.display = 'none';
                }
            }
            
            function startAttendanceAutoRefresh() {
                // Clear any existing interval
                if (attendanceRefreshInterval) {
                    clearInterval(attendanceRefreshInterval);
                }
                
                // Refresh every 60 seconds
                attendanceRefreshInterval = setInterval(() => {
                    if (attendanceSessionToken) {
                        console.log('Auto-refreshing attendance data...');
                        loadAttendanceData(true); // true = silent refresh
                    }
                }, 60000); // 60 seconds
            }
            
            function stopAttendanceAutoRefresh() {
                if (attendanceRefreshInterval) {
                    clearInterval(attendanceRefreshInterval);
                    attendanceRefreshInterval = null;
                }
            }
            
            async function loginAttendance(event) {
                event.preventDefault();
                
                var username = document.getElementById('attendanceUsername').value.trim();
                var password = document.getElementById('attendancePassword').value;
                var rememberMe = document.getElementById('rememberMe').checked;
                var submitBtn = document.getElementById('loginSubmitBtn');
                
                if (!username || !password) {
                    alert('Please enter both username and password');
                    return;
                }
                
                // Show loading state
                submitBtn.disabled = true;
                submitBtn.classList.add('loading');
                submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i><span>Authenticating...</span>';
                
                try {
                    var response = await fetch(`/api/attendance/login?username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        }
                    });
                    
                    if (!response.ok) {
                        throw new Error(`HTTP error! status: ${response.status}`);
                    }
                    
                    var result = await response.json();
                    
                    if (result.success) {
                        // Save session token
                        attendanceSessionToken = result.session_token;
                        attendanceUsername = result.username;
                        safeStorage.setItem('attendance_session_token', attendanceSessionToken);
                        safeStorage.setItem('attendance_username', attendanceUsername);
                        
                        // Set session timestamp (7 days expiration)
                        updateSessionTimestamp();
                        
                        // Save credentials if remember me is checked (encrypted)
                        if (rememberMe) {
                            const creds = btoa(JSON.stringify({ u: username, p: password }));
                            safeStorage.setItem('attendance_credentials', creds);
                        } else {
                            safeStorage.removeItem('attendance_credentials');
                        }
                        
                        // Load attendance data
                        await loadAttendanceData();
                        
                        // Start auto-refresh
                        startAttendanceAutoRefresh();
                        
                        console.log('✅ Login successful - session valid for 7 days');
                    } else {
                        alert(`Login failed: ${result.error}`);
                        // Reset button
                        submitBtn.disabled = false;
                        submitBtn.classList.remove('loading');
                        submitBtn.innerHTML = '<i class="fas fa-sign-in-alt"></i><span>Login Securely</span>';
                    }
                } catch (error) {
                    alert(`Login error: ${error.message}`);
                    submitBtn.disabled = false;
                    submitBtn.classList.remove('loading');
                    submitBtn.innerHTML = '<i class="fas fa-sign-in-alt"></i><span>Login Securely</span>';
                }
            }
            
            // Function to parse HTML and render beautiful cards
            async function renderAttendanceCards(html, fullName = null) {
                // Update student name in header with welcome message
                if (fullName) {
                    // Check if fullName is actually a student ID (starts with B and has numbers)
                    const isStudentId = /^B\d+$/.test(fullName);
                    
                    if (isStudentId) {
                        // Show student ID with a friendly message
                        document.getElementById('studentNameDisplay').innerHTML = `
                            <span style="color: var(--accent);">Welcome</span> <span style="font-weight: 600;">${fullName}</span>
                            <small style="display: block; font-size: 0.8em; color: var(--text-secondary); margin-top: 4px;">
                                📝 To show your name instead of ID, contact the administrator
                            </small>
                        `;
                    } else {
                        // Show actual name without title
                        document.getElementById('studentNameDisplay').textContent = `Welcome ${fullName}`;
                    }
                }
                
                // Create a temporary element to parse HTML
                const tempDiv = document.createElement('div');
                tempDiv.innerHTML = html;
                
                // Find the table
                const table = tempDiv.querySelector('table');
                if (!table) {
                    document.getElementById('attendanceContent').innerHTML = `
                        <div class="no-absences">
                            <i class="fas fa-clipboard-check"></i>
                            <h3>No Attendance Data</h3>
                            <p>No attendance records found for this user.</p>
                        </div>
                    `;
                    return;
                }
                
                // Parse table rows (skip header)
                const rows = Array.from(table.querySelectorAll('tr')).slice(1);
                const modules = [];
                
                // Parse all rows first
                for (const row of rows) {
                    const cells = row.querySelectorAll('td');
                    if (cells.length >= 4) {
                        // Extract module info
                        const moduleCell = cells[0];
                        const classCell = cells[1];
                        const semesterCell = cells[2];
                        const absencesCell = cells[3];
                        
                        // Extract GUIDs from row HTML
                        const rowHtml = row.innerHTML;
                        const guidRegex = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi;
                        const guids = rowHtml.match(guidRegex) || [];
                        
                        const studentClassId = guids[0] || '';
                        const classId = guids[1] || '';
                        
                        modules.push({
                            module: moduleCell.textContent.trim(),
                            className: classCell.textContent.trim(),
                            semester: semesterCell.textContent.trim(),
                            absences: parseInt(absencesCell.textContent.trim()) || 0,
                            absenceDetails: [],
                            studentClassId: studentClassId,
                            classId: classId
                        });
                    }
                }
                
                // Absence details fetching removed - not working properly
                
                if (modules.length === 0) {
                    document.getElementById('attendanceContent').innerHTML = `
                        <div class="no-absences">
                            <i class="fas fa-clipboard-check"></i>
                            <h3>No Attendance Data</h3>
                            <p>No attendance records found for this user.</p>
                        </div>
                    `;
                    return;
                }
                
                // Calculate statistics - FIXED CALCULATION
                const totalModules = modules.length;
                const totalAbsences = modules.reduce((sum, m) => sum + m.absences, 0);
                const perfectModules = modules.filter(m => m.absences === 0).length;
                
                // Better attendance rate: assume average 15 sessions per module (30 weeks / 2)
                // Attendance Rate = (Total Possible Sessions - Total Absences) / Total Possible Sessions * 100
                const estimatedTotalSessions = totalModules * 15; // Rough estimate
                const attendanceRate = estimatedTotalSessions > 0 
                    ? ((estimatedTotalSessions - totalAbsences) / estimatedTotalSessions * 100).toFixed(1)
                    : '100.0';
                
                // Build stats dashboard
                let htmlContent = `
                    <div class="attendance-stats">
                        <div class="stat-item">
                            <div class="stat-item-value">${totalModules}</div>
                            <div class="stat-item-label">Total Modules</div>
                        </div>
                        <div class="stat-item">
                            <div class="stat-item-value">${totalAbsences}</div>
                            <div class="stat-item-label">Total Absences</div>
                        </div>
                        <div class="stat-item">
                            <div class="stat-item-value">${perfectModules}</div>
                            <div class="stat-item-label">Perfect Modules</div>
                        </div>
                        <div class="stat-item">
                            <div class="stat-item-value">${attendanceRate}%</div>
                            <div class="stat-item-label">Attendance Rate</div>
                        </div>
                    </div>
                `;
                
                // Build cards for each module
                modules.forEach(module => {
                    // Determine badge class
                    let badgeClass = 'perfect';
                    if (module.absences >= 3) {
                        badgeClass = 'danger';
                    } else if (module.absences >= 1) {
                        badgeClass = 'warning';
                    }
                    
                    // Absence details display removed
                    
                    htmlContent += `
                        <div class="attendance-card">
                            <div class="attendance-card-header">
                                <div class="module-info">
                                    <div class="module-name">
                                        <i class="fas fa-book"></i>
                                        <span>${module.module}</span>
                                    </div>
                                    <div class="class-name">
                                        <i class="fas fa-users"></i>
                                        <span>${module.className}</span>
                                    </div>
                                </div>
                                <div class="absence-badge ${badgeClass}">
                                    <div class="absence-count">${module.absences}</div>
                                    <div class="absence-label">Absences</div>
                                </div>
                            </div>
                            <div class="attendance-card-body">
                                <div class="attendance-detail">
                                    <div class="detail-icon">
                                        <i class="fas fa-calendar-alt"></i>
                                    </div>
                                    <div class="detail-content">
                                        <div class="detail-label">Semester</div>
                                        <div class="detail-value">${module.semester}</div>
                                    </div>
                                </div>
                                <div class="attendance-detail">
                                    <div class="detail-icon">
                                        <i class="fas fa-chart-line"></i>
                                    </div>
                                    <div class="detail-content">
                                        <div class="detail-label">Status</div>
                                        <div class="detail-value">${module.absences === 0 ? 'Perfect' : module.absences >= 3 ? 'At Risk' : 'Good'}</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    `;
                });
                
                document.getElementById('attendanceContent').innerHTML = htmlContent;
            }
            
            async function loadAttendanceData(silentRefresh = false) {
                if (!attendanceSessionToken) {
                    return;
                }
                
                // Show private data area with loading (unless silent refresh)
                document.getElementById('privateLoginArea').style.display = 'none';
                document.getElementById('privateDataArea').style.display = 'block';
                
                // Restore last private section (attendance, result-alerts, or official-results)
                const lastPrivateSection = localStorage.getItem('lastPrivateSection');
                if (lastPrivateSection && !silentRefresh) {
                    // Delay slightly to ensure DOM is ready
                    setTimeout(() => {
                        if (lastPrivateSection === 'result-alerts') {
                            switchPrivateSection('result-alerts');
                        } else if (lastPrivateSection === 'official-results') {
                            switchPrivateSection('official-results');
                        }
                        // If 'attendance' or invalid, default to attendance (already active)
                    }, 100);
                }
                
                if (!silentRefresh) {
                    document.getElementById('attendanceContent').innerHTML = `
                        <div class="loading">
                            <div class="spinner"></div>
                            <p style="color: var(--text-secondary)">Loading attendance data...</p>
                        </div>
                    `;
                }
                
                try {
                    // Fetch attendance data first
                    const attendanceResponse = await fetch(`/api/attendance/data?session_token=${encodeURIComponent(attendanceSessionToken)}`);
                    const attendanceResult = await attendanceResponse.json();
                    
                    if (attendanceResult.success) {
                        // Refresh session timestamp on successful data load
                        updateSessionTimestamp();
                        
                        // Try to fetch profile (but don't fail if it doesn't work)
                        let fullName = attendanceUsername;
                        
                        // First, check if we extracted name from attendance HTML
                        if (attendanceResult.extracted_name) {
                            fullName = attendanceResult.extracted_name;
                        } else {
                            // Try to fetch from profile API
                            try {
                                const profileResponse = await fetch(`/api/attendance/profile?session_token=${encodeURIComponent(attendanceSessionToken)}`);
                                const profileResult = await profileResponse.json();
                                
                                if (profileResult.success) {
                                    const firstName = profileResult.first_name || '';
                                    const middleName = profileResult.middle_name || '';
                                    const lastName = profileResult.last_name || '';
                                    
                                    // If we have a proper name (not just student ID), use it
                                    if (firstName && lastName) {
                                        fullName = [firstName, middleName, lastName].filter(n => n).join(' ');
                                    } else if (firstName) {
                                        // Use just first name (which might be student ID)
                                        fullName = firstName;
                                    }
                                }
                            } catch (profileError) {
                                console.log('Profile fetch failed, using student ID:', profileError);
                            }
                        }
                        
                        // Parse HTML and create beautiful cards
                        await renderAttendanceCards(attendanceResult.html, fullName);
                    } else {
                        // Session expired or error
                        if (attendanceResult.error && attendanceResult.error.toLowerCase().includes('expired')) {
                            logoutAttendance();
                            alert('Session expired. Please login again.');
                        } else {
                            document.getElementById('attendanceContent').innerHTML = `
                                <div class="empty-state">
                                    <i class="fas fa-exclamation-triangle"></i>
                                    <h3>Error Loading Attendance</h3>
                                    <p>${attendanceResult.error}</p>
                                </div>
                            `;
                        }
                    }
                } catch (error) {
                    document.getElementById('attendanceContent').innerHTML = `
                        <div class="empty-state">
                            <i class="fas fa-exclamation-triangle"></i>
                            <h3>Error Loading Attendance</h3>
                            <p>${error.message}</p>
                        </div>
                    `;
                }
            }
            
            async function logoutAttendance() {
                // Stop auto-refresh
                stopAttendanceAutoRefresh();
                
                if (attendanceSessionToken) {
                    try {
                        await fetch(`/api/attendance/logout?session_token=${encodeURIComponent(attendanceSessionToken)}`, {
                            method: 'POST'
                        });
                    } catch (error) {
                        console.error('Logout error:', error);
                    }
                }
                
                // Clear session and saved credentials
                attendanceSessionToken = null;
                attendanceUsername = null;
                safeStorage.removeItem('attendance_session_token');
                safeStorage.removeItem('attendance_username');
                safeStorage.removeItem('attendance_credentials');
                safeStorage.removeItem('attendance_session_timestamp');
                
                // Clear all cached private data
                cachedResultAlerts = null;
                cachedOfficialResults = null;
                cachedAttendanceData = null;
                
                // Reset form
                document.getElementById('attendanceLoginForm').reset();
                document.getElementById('loginSubmitBtn').disabled = false;
                document.getElementById('loginSubmitBtn').classList.remove('loading');
                document.getElementById('loginSubmitBtn').innerHTML = '<i class="fas fa-sign-in-alt"></i><span>Login Securely</span>';
                document.getElementById('loginSubmitBtn').innerHTML = '<i class="fas fa-sign-in-alt"></i><span>Login Securely</span>';
                
                // Show login area
                document.getElementById('privateLoginArea').style.display = 'block';
                document.getElementById('privateDataArea').style.display = 'none';
                
                // Switch back to lectures zone
                switchZone('lectures');
            }
            
            // ===================================
            // RESULT ALERTS FUNCTIONS (Notification-based)
            // ===================================
            
            async function fetchResultAlerts(silentRefresh = false) {
                if (!attendanceSessionToken) {
                    return;
                }
                
                if (!silentRefresh) {
                    document.getElementById('resultsContent').innerHTML = `
                        <div class="loading">
                            <div class="spinner"></div>
                            <p style="color: var(--text-secondary)">Loading result alerts from notifications...</p>
                        </div>
                    `;
                }
                
                try {
                    const response = await fetch(`/api/results/data?session_token=${encodeURIComponent(attendanceSessionToken)}`);
                    const result = await response.json();
                    
                    if (result.success) {
                        // Refresh session timestamp on successful data load
                        updateSessionTimestamp();
                        
                        // Cache the data for instant future loads
                        cachedResultAlerts = {
                            results: result.results || [],
                            totalCount: result.total_count || 0
                        };
                        
                        // Render results cards
                        renderResultsCards(cachedResultAlerts.results, cachedResultAlerts.totalCount);
                    } else {
                        // Session expired or error
                        if (result.error && result.error.toLowerCase().includes('expired')) {
                            logoutAttendance();
                            alert('Session expired. Please login again.');
                        } else {
                            document.getElementById('resultsContent').innerHTML = `
                                <div class="empty-state">
                                    <i class="fas fa-exclamation-triangle"></i>
                                    <h3>Error Loading Result Alerts</h3>
                                    <p>${result.error}</p>
                                </div>
                            `;
                        }
                    }
                } catch (error) {
                    document.getElementById('resultsContent').innerHTML = `
                        <div class="empty-state">
                            <i class="fas fa-exclamation-triangle"></i>
                            <h3>Error Loading Results</h3>
                            <p>${error.message}</p>
                        </div>
                    `;
                }
            }
            
            function renderResultsCards(results, totalCount) {
                const container = document.getElementById('resultsContent');
                
                if (results.length === 0) {
                    container.innerHTML = `
                        <div class="no-absences">
                            <i class="fas fa-bell-slash"></i>
                            <h3>No Results Found</h3>
                            <p>No result-related notifications found in your feed yet.</p>
                            <div class="login-note" style="margin-top: 1rem;">
                                <i class="fas fa-info-circle"></i>
                                <span>Results appear here when published by the college as notifications</span>
                            </div>
                        </div>
                    `;
                    return;
                }
                
                // Build stats dashboard
                const passedCount = results.filter(r => r.status === 'passed').length;
                const failedCount = results.filter(r => r.status === 'failed').length;
                const unknownCount = results.length - passedCount - failedCount;
                
                let htmlContent = `
                    <div class="attendance-stats">
                        <div class="stat-item">
                            <div class="stat-item-value">${totalCount}</div>
                            <div class="stat-item-label">Total Results</div>
                        </div>
                        <div class="stat-item">
                            <div class="stat-item-value" style="color: var(--success);">${passedCount}</div>
                            <div class="stat-item-label">Passed</div>
                        </div>
                        <div class="stat-item">
                            <div class="stat-item-value" style="color: #ef4444;">${failedCount}</div>
                            <div class="stat-item-label">Failed</div>
                        </div>
                        <div class="stat-item">
                            <div class="stat-item-value" style="color: var(--text-secondary);">${unknownCount}</div>
                            <div class="stat-item-label">Pending</div>
                        </div>
                    </div>
                `;
                
                // Function to map semester codes to readable semester numbers (1-4)
                function getSemesterName(semesterCode) {
                    if (!semesterCode || semesterCode.trim() === '') {
                        return null;
                    }
                    
                    // Parse patterns like "Software_F25-26", "Software_S25-26", "Software_S_25-26", etc.
                    const match = semesterCode.match(/([A-Za-z]+)_?([FS])_?(\d{2})-(\d{2})/);
                    if (match) {
                        const [, group, season, startYear, endYear] = match;
                        const fullStartYear = 2000 + parseInt(startYear);
                        
                        // Map academic years to semester numbers
                        // 24-25: Fall=Semester 1, Spring=Semester 2
                        // 25-26: Fall=Semester 3, Spring=Semester 4
                        let semesterNum;
                        if (fullStartYear === 2024) {
                            semesterNum = season === 'F' ? 1 : 2;
                        } else if (fullStartYear === 2025) {
                            semesterNum = season === 'F' ? 3 : 4;
                        } else {
                            // For other years, calculate based on offset from 2024
                            const yearOffset = fullStartYear - 2024;
                            semesterNum = (yearOffset * 2) + (season === 'F' ? 1 : 2);
                            // Cap at semester 4
                            semesterNum = Math.min(4, Math.max(1, semesterNum));
                        }
                        
                        return `Semester ${semesterNum}`;
                    }
                    
                    // Try to extract semester number from patterns like "24_sf_1st_b", "Group A"
                    const semesterNumMatch = semesterCode.match(/(\d+)/);
                    if (semesterNumMatch) {
                        const num = Math.min(4, Math.max(1, parseInt(semesterNumMatch[1])));
                        return `Semester ${num}`;
                    }
                    
                    // For unrecognized patterns, return null to filter out
                    return null;
                }
                
                // Group results by DISPLAY semester name (Semester 1, 2, 3, 4)
                // This ensures all results with same semester number are grouped together
                const resultsBySemester = {};
                results.forEach(result => {
                    const rawSemester = result.semester;
                    const displaySemester = getSemesterName(rawSemester);
                    
                    // Skip results without valid semester
                    if (!displaySemester) {
                        return;
                    }
                    
                    // Filter out "skill" subjects from Semester 4 (they belong to Semester 1)
                    const subjectLower = (result.subject || '').toLowerCase();
                    if (displaySemester === 'Semester 4' && subjectLower.includes('skill')) {
                        return; // Skip this result
                    }
                    
                    // Only show Semester 3 and 4 (current academic year)
                    if (displaySemester !== 'Semester 3' && displaySemester !== 'Semester 4') {
                        return; // Skip semesters 1 and 2
                    }
                    
                    if (!resultsBySemester[displaySemester]) {
                        resultsBySemester[displaySemester] = [];
                    }
                    resultsBySemester[displaySemester].push(result);
                });
                
                // Check if no valid results after filtering
                if (Object.keys(resultsBySemester).length === 0) {
                    container.innerHTML += `
                        <div class="no-absences" style="margin-top: 2rem;">
                            <i class="fas fa-info-circle"></i>
                            <h3>No Results Available</h3>
                            <p>Results will appear here once semester information is available.</p>
                        </div>
                    `;
                    return;
                }
                
                // Sort semesters by semester number (1, 2, 3, 4)
                const sortedSemesters = Object.keys(resultsBySemester).sort((a, b) => {
                    // Extract semester numbers from "Semester 1", "Semester 2", etc.
                    const numA = parseInt(a.match(/\d+/)[0]);
                    const numB = parseInt(b.match(/\d+/)[0]);
                    return numA - numB; // Sort ascending (Semester 1, 2, 3, 4)
                });
                
                // Render each semester section
                sortedSemesters.forEach((semesterDisplayName, semesterIdx) => {
                    const semesterResults = resultsBySemester[semesterDisplayName];
                    
                    htmlContent += `
                        <div class="subject-section" style="margin-bottom: 1.5rem;">
                            <div class="subject-header" onclick="toggleResultsSemester(this)" style="background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 100%); cursor: pointer;">
                                <div class="subject-title" style="color: white; font-size: 1.1rem; font-weight: 700;">
                                    <i class="fas fa-graduation-cap" style="color: white;"></i>
                                    ${semesterDisplayName}
                                    <span class="file-count" style="background: rgba(255,255,255,0.2); color: white;">${semesterResults.length} result${semesterResults.length > 1 ? 's' : ''}</span>
                                </div>
                                <div class="collapse-btn">
                                    <i class="fas fa-chevron-down" style="color: white; transform: rotate(-90deg); transition: transform 0.3s ease;"></i>
                                </div>
                            </div>
                            <div class="semester-results-content" style="display: none; padding: 0; transition: all 0.3s ease;">
                                <div class="results-table-container">
                                    <table class="results-table">
                                        <thead>
                                            <tr>
                                                <th>No.</th>
                                                <th><i class="fas fa-book"></i> Subject</th>
                                                <th><i class="fas fa-clipboard-list"></i> Exam Type</th>
                                                <th><i class="fas fa-star"></i> Score</th>
                                                <th><i class="fas fa-calendar-alt"></i> Date</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                    `;
                    
                    // Build table rows for this semester (newest first - already sorted from backend)
                    // Reset numbering for each semester
                    let rowIndex = 1;
                    semesterResults.forEach((result) => {
                        // Format date
                        let formattedDate = 'N/A';
                        if (result.date) {
                            try {
                                const dateObj = new Date(result.date);
                                if (!isNaN(dateObj.getTime())) {
                                    formattedDate = dateObj.toLocaleDateString('en-US', {
                                        year: 'numeric',
                                        month: 'short',
                                        day: 'numeric'
                                    });
                                }
                            } catch (e) {
                                formattedDate = result.date;
                            }
                        }
                        
                        htmlContent += `
                            <tr class="result-row">
                                <td class="row-number">${rowIndex}</td>
                                <td class="subject-cell">
                                    <strong>${result.subject || '-'}</strong>
                                </td>
                                <td>${result.exam_type || '-'}</td>
                                <td class="score-cell">
                                    <span class="score-badge">${result.score || '-'}</span>
                                </td>
                                <td style="color: var(--text-tertiary); font-size: 0.9rem;">${formattedDate}</td>
                            </tr>
                        `;
                        rowIndex++;
                    });
                    
                    htmlContent += `
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </div>
                    `;
                });
                
                container.innerHTML = htmlContent;
            }
            
            // Unified toggle function for all collapsible sections (Result Alerts)
            function toggleResultsSemester(header) {
                const section = header.closest('.subject-section');
                const icon = header.querySelector('.collapse-btn i');
                
                // Smart detection: try multiple content selectors
                let content = section.querySelector('.semester-results-content');
                if (!content) {
                    content = section.querySelector('.semester-results-table');
                }
                if (!content) {
                    content = section.querySelector('.subject-files');
                }
                
                if (!content) return; // Safety check
                
                // Toggle with smooth animation
                if (content.style.display === 'none' || content.style.display === '') {
                    content.style.display = 'block';
                    setTimeout(() => {
                        icon.style.transform = 'rotate(0deg)';
                    }, 10);
                } else {
                    icon.style.transform = 'rotate(-90deg)';
                    setTimeout(() => {
                        content.style.display = 'none';
                    }, 150); // Wait for rotation animation
                }
            }
            
            // ===================================
            // OFFICIAL RESULTS FUNCTIONS (StudentResult API)
            // ===================================
            
            async function fetchOfficialResults(silentRefresh = false) {
                if (!attendanceSessionToken) {
                    return;
                }
                
                if (!silentRefresh) {
                    document.getElementById('officialResultsContent').innerHTML = `
                        <div class="loading">
                            <div class="spinner"></div>
                            <p style="color: var(--text-secondary)">Loading official results...</p>
                        </div>
                    `;
                }
                
                try {
                    const response = await fetch(`/api/official-results/data?session_token=${encodeURIComponent(attendanceSessionToken)}`);
                    const result = await response.json();
                    
                    if (result.success) {
                        // Refresh session timestamp on successful data load
                        updateSessionTimestamp();
                        
                        // Cache the data for instant future loads
                        cachedOfficialResults = result.results || [];
                        
                        // Render official results
                        renderOfficialResults(cachedOfficialResults);
                    } else {
                        // Session expired or error
                        if (result.error && result.error.toLowerCase().includes('expired')) {
                            logoutAttendance();
                            alert('Session expired. Please login again.');
                        } else {
                            document.getElementById('officialResultsContent').innerHTML = `
                                <div class="empty-state">
                                    <i class="fas fa-exclamation-triangle"></i>
                                    <h3>Error Loading Results</h3>
                                    <p>${result.error}</p>
                                </div>
                            `;
                        }
                    }
                } catch (error) {
                    document.getElementById('officialResultsContent').innerHTML = `
                        <div class="empty-state">
                            <i class="fas fa-exclamation-triangle"></i>
                            <h3>Error Loading Results</h3>
                            <p>${error.message}</p>
                        </div>
                    `;
                }
            }
            
            function renderOfficialResults(results) {
                const container = document.getElementById('officialResultsContent');
                
                if (!results || results.length === 0) {
                    container.innerHTML = `
                        <div class="no-absences">
                            <i class="fas fa-clipboard-list"></i>
                            <h3>No Official Results Found</h3>
                            <p>Your official exam results will appear here once published by the college.</p>
                            <div class="login-note" style="margin-top: 1rem;">
                                <i class="fas fa-info-circle"></i>
                                <span>This section shows official results from the student portal system</span>
                            </div>
                        </div>
                    `;
                    return;
                }
                
                // Group results by Academic Year → Semester (like university portal)
                let htmlContent = '';
                const resultsByYearAndSemester = {};
                
                results.forEach(result => {
                    const academicYear = result.AcademicYear || result.academicYear || result.Year || result.year || 'Unknown Year';
                    const semesterName = result.SemesterName || result.Semester || result.semester || 'Unknown Semester';
                    
                    if (!resultsByYearAndSemester[academicYear]) {
                        resultsByYearAndSemester[academicYear] = {};
                    }
                    
                    if (!resultsByYearAndSemester[academicYear][semesterName]) {
                        resultsByYearAndSemester[academicYear][semesterName] = [];
                    }
                    
                    resultsByYearAndSemester[academicYear][semesterName].push(result);
                });
                
                // Sort academic years descending (newest first)
                const sortedYears = Object.keys(resultsByYearAndSemester).sort((a, b) => {
                    const yearA = parseInt(a.split('-')[0]) || 0;
                    const yearB = parseInt(b.split('-')[0]) || 0;
                    return yearB - yearA;
                });
                
                // Render each Academic Year with nested Semesters
                sortedYears.forEach((academicYear) => {
                    const semestersInYear = resultsByYearAndSemester[academicYear];
                    
                    // Academic Year header (main container)
                    htmlContent += `
                        <div class="year-section" style="margin-bottom: 1.5rem; border: 1px solid var(--border); border-radius: 12px; overflow: hidden; background: var(--bg-secondary);">
                            <div class="year-header" onclick="toggleResultsYear(this)" style="background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%); padding: 1.25rem 1.5rem; cursor: pointer; display: flex; justify-content: space-between; align-items: center;">
                                <div style="color: white; font-size: 1.1rem; font-weight: 700; display: flex; align-items: center; gap: 0.75rem;">
                                    <i class="fas fa-calendar-alt" style="font-size: 1.2rem;"></i>
                                    <span>${academicYear}</span>
                                </div>
                                <div class="collapse-btn">
                                    <i class="fas fa-chevron-down" style="color: white; font-size: 1.1rem; transition: transform 0.3s ease;"></i>
                                </div>
                            </div>
                            <div class="year-content" style="display: block;">
                    `;
                    
                    // Sort semesters
                    const semesterOrder = { 'Spring Semester': 1, 'Fall Semester': 2, 'Summer Semester': 3 };
                    const sortedSemesters = Object.keys(semestersInYear).sort((a, b) => {
                        const orderA = semesterOrder[a] || 999;
                        const orderB = semesterOrder[b] || 999;
                        return orderA - orderB;
                    });
                    
                    // Render each Semester inside the Academic Year
                    sortedSemesters.forEach((semesterName) => {
                        const semesterResults = semestersInYear[semesterName];
                        
                        htmlContent += `
                            <div class="semester-section" style="border-top: 1px solid var(--border);">
                                <div class="semester-header" onclick="toggleResultsSemester(this)" style="background: var(--surface); padding: 1rem 1.5rem; cursor: pointer; display: flex; justify-content: space-between; align-items: center; transition: background 0.2s;" onmouseover="this.style.background='var(--bg-tertiary)'" onmouseout="this.style.background='var(--surface)'">
                                    <div style="color: var(--text-primary); font-weight: 600; display: flex; align-items: center; gap: 0.75rem;">
                                        <i class="fas fa-book-open" style="color: var(--primary);"></i>
                                        <span>${semesterName}</span>
                                    </div>
                                    <div class="collapse-btn" style="display: flex; align-items: center; gap: 0.5rem;">
                                        <i class="fas fa-chevron-down" style="color: var(--text-tertiary); font-size: 0.9rem; transition: transform 0.3s ease;"></i>
                                    </div>
                                </div>
                                <div class="semester-results-table" style="display: block; padding: 1.5rem; transition: all 0.3s ease;">
                                    <div class="results-card-container" style="display: flex; flex-direction: column; gap: 1.25rem;">
                        `;
                        
                        // Render each result row
                        semesterResults.forEach((result, index) => {
                            // New API structure: SubjectName=Course, Assessments=Array, Points=Total, Status=Pass/Fail
                            const courseName = result.SubjectName || result.Subject || result.subject || 'Unknown Course';
                            const credit = result.Credit || result.credit || '-';
                            const assessments = result.Assessments || [];
                            const continuousTotal = result.ContinuousTotal || result.continuousTotal || '-';
                            const points = result.Points || result.points || '-';
                            const status = result.Status || result.status || '-';
                            
                            // Determine final status (Pass/Fail) based on status text or points
                            let statusColor = '#94a3b8';
                            let statusIcon = 'fa-clock';
                            let statusBg = 'rgba(148, 163, 184, 0.15)';
                            let statusDisplay = 'Pending';
                            const statusLower = status.toLowerCase();
                            
                            // Check for Pass/Fail/Accept indicators
                            if (statusLower.includes('pass') || statusLower.includes('accept') || statusLower === 'ناجح' || statusLower.includes('excellent') || statusLower.includes('امتياز') || statusLower.includes('medium') || statusLower.includes('متوسط')) {
                                statusColor = '#10b981';
                                statusIcon = 'fa-check-circle';
                                statusBg = 'rgba(16, 185, 129, 0.15)';
                                statusDisplay = 'Pass';
                            } else if (statusLower.includes('fail') || statusLower === 'راسب') {
                                statusColor = '#ef4444';
                                statusIcon = 'fa-times-circle';
                                statusBg = 'rgba(239, 68, 68, 0.15)';
                                statusDisplay = 'Fail';
                            } else if (parseFloat(points) >= 5) {
                                // If points suggest passing
                                statusColor = '#10b981';
                                statusIcon = 'fa-check-circle';
                                statusBg = 'rgba(16, 185, 129, 0.15)';
                                statusDisplay = 'Pass';
                            }
                            
                            // Build assessment grid HTML
                            let assessmentGridHTML = '';
                            if (assessments && assessments.length > 0) {
                                assessments.forEach(assessment => {
                                    const assessmentName = assessment.name || assessment.Name || 'Assessment';
                                    const assessmentScore = assessment.score || assessment.Score || '-';
                                    
                                    assessmentGridHTML += `
                                        <div class="assessment-item" style="background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 10px; padding: 0.85rem; transition: all 0.2s;" onmouseover="this.style.borderColor='var(--primary)'; this.style.background='var(--bg-tertiary)';" onmouseout="this.style.borderColor='var(--border)'; this.style.background='var(--bg-secondary)';">
                                            <div style="font-size: 0.75rem; color: var(--text-tertiary); font-weight: 600; margin-bottom: 0.4rem; text-transform: capitalize; letter-spacing: 0.3px;">${assessmentName}</div>
                                            <div style="font-size: 1.3rem; font-weight: 800; color: var(--text-primary); font-family: 'Courier New', monospace;">${assessmentScore}</div>
                                        </div>
                                    `;
                                });
                            } else {
                                // Fallback: show continuous total and final as placeholders
                                if (continuousTotal && continuousTotal !== '-') {
                                    assessmentGridHTML += `
                                        <div class="assessment-item" style="background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 10px; padding: 0.85rem;">
                                            <div style="font-size: 0.75rem; color: var(--text-tertiary); font-weight: 600; margin-bottom: 0.4rem; text-transform: uppercase; letter-spacing: 0.3px;">Continuous Exam</div>
                                            <div style="font-size: 1.3rem; font-weight: 800; color: var(--text-primary); font-family: 'Courier New', monospace;">${continuousTotal}</div>
                                        </div>
                                    `;
                                }
                                assessmentGridHTML += `
                                    <div class="assessment-item" style="background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 10px; padding: 0.85rem;">
                                        <div style="font-size: 0.75rem; color: var(--text-tertiary); font-weight: 600; margin-bottom: 0.4rem; text-transform: uppercase; letter-spacing: 0.3px;">Total Points</div>
                                        <div style="font-size: 1.3rem; font-weight: 800; color: var(--text-primary); font-family: 'Courier New', monospace;">${points}</div>
                                    </div>
                                `;
                            }
                            
                            htmlContent += `
                                <!-- Modern Subject Result Card -->
                                <div class="subject-result-card" style="background: var(--surface); border: 1px solid var(--border); border-radius: 16px; overflow: hidden; transition: all 0.3s ease; box-shadow: 0 2px 8px rgba(0,0,0,0.1);" onmouseover="this.style.transform='translateY(-2px)'; this.style.boxShadow='0 8px 20px rgba(0,0,0,0.15)';" onmouseout="this.style.transform='translateY(0)'; this.style.boxShadow='0 2px 8px rgba(0,0,0,0.1)';">
                                    
                                    <!-- Card Header: Subject Info -->
                                    <div class="card-header" style="background: linear-gradient(135deg, rgba(30, 64, 175, 0.08), rgba(59, 130, 246, 0.08)); padding: 1.5rem; border-bottom: 1px solid var(--border);">
                                        <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 1rem;">
                                            <div style="display: flex; align-items: center; gap: 1rem; flex: 1; min-width: 0;">
                                                <div class="subject-number" style="background: var(--primary); color: white; width: 42px; height: 42px; border-radius: 12px; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 1.1rem; flex-shrink: 0; box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);">${index + 1}</div>
                                                <div style="flex: 1; min-width: 0;">
                                                    <h3 class="course-name" style="font-size: 1.05rem; font-weight: 700; color: var(--text-primary); margin: 0 0 0.25rem 0; line-height: 1.4; word-wrap: break-word;">${courseName}</h3>
                                                    ${credit && credit !== '-' ? `<div class="credit-badge" style="display: inline-block; background: var(--bg-tertiary); padding: 0.25rem 0.6rem; border-radius: 6px; font-size: 0.75rem; color: var(--text-secondary);"><i class="fas fa-certificate" style="margin-right: 0.3rem;"></i>${credit} Credits</div>` : ''}
                                                </div>
                                            </div>
                                            <div class="status-badge-container" style="display: flex; gap: 0.75rem; align-items: center; flex-shrink: 0;">
                                                <span class="status-badge" style="display: inline-flex; align-items: center; gap: 0.5rem; padding: 0.65rem 1.25rem; background: ${statusBg}; color: ${statusColor}; border-radius: 12px; font-weight: 700; font-size: 0.9rem; border: 2px solid ${statusColor}; box-shadow: 0 2px 8px ${statusBg};">
                                                    <i class="fas ${statusIcon}" style="font-size: 1rem;"></i>
                                                    <span>${statusDisplay}</span>
                                                </span>
                                            </div>
                                        </div>
                                    </div>
                                    
                                    <!-- Card Body: Assessment Breakdown & Summary -->
                                    <div class="card-body" style="padding: 1.5rem;">
                                        <div style="display: grid; grid-template-columns: 1fr auto; gap: 2rem; align-items: start;">
                                            
                                            <!-- Assessment Breakdown Section -->
                                            <div class="assessment-section" style="min-width: 0;">
                                                <div class="section-label" style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 1rem; color: var(--text-secondary); font-size: 0.85rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">
                                                    <i class="fas fa-clipboard-list" style="color: var(--primary);"></i>
                                                    <span>Assessment Breakdown</span>
                                                </div>
                                                <div class="assessment-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 0.75rem;">
                                                    ${assessmentGridHTML}
                                                </div>
                                                ${assessments.length === 0 ? `
                                                    <div style="margin-top: 0.75rem; padding: 0.75rem; background: rgba(59, 130, 246, 0.05); border-left: 3px solid var(--primary); border-radius: 6px;">
                                                        <div style="font-size: 0.8rem; color: var(--text-secondary); display: flex; align-items: center; gap: 0.5rem;">
                                                            <i class="fas fa-info-circle" style="color: var(--primary);"></i>
                                                            <span>Detailed assessment breakdown not available for this subject</span>
                                                        </div>
                                                    </div>
                                                ` : ''}
                                            </div>
                                            
                                            <!-- Summary Panel -->
                                            <div class="summary-panel" style="background: linear-gradient(135deg, rgba(59, 130, 246, 0.1), rgba(147, 51, 234, 0.1)); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; min-width: 180px; max-width: 220px;">
                                                <div style="text-align: center;">
                                                    <div style="font-size: 0.75rem; color: var(--text-tertiary); font-weight: 600; margin-bottom: 0.75rem; text-transform: uppercase; letter-spacing: 0.5px;">Performance</div>
                                                    ${continuousTotal && continuousTotal !== '-' ? `
                                                        <div class="continuous-display" style="background: var(--bg-tertiary); border: 1px solid var(--border); border-radius: 12px; padding: 1rem; margin-bottom: 1rem;">
                                                            <div style="font-size: 1.5rem; font-weight: 800; color: var(--text-primary); font-family: 'Courier New', monospace;">${continuousTotal}</div>
                                                            <div style="font-size: 0.7rem; color: var(--text-tertiary); margin-top: 0.25rem; font-weight: 600;">Continuous</div>
                                                        </div>
                                                    ` : ''}
                                                    <div class="grade-display" style="background: linear-gradient(135deg, var(--primary), var(--secondary)); color: white; border-radius: 16px; padding: 1.25rem 1rem; margin-bottom: 1rem; box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);">
                                                        <div style="font-size: 2.5rem; font-weight: 900; line-height: 1; font-family: 'Courier New', monospace;">${points}</div>
                                                        <div style="font-size: 0.75rem; margin-top: 0.5rem; opacity: 0.9; font-weight: 600;">Total Points</div>
                                                    </div>
                                                    <div style="font-size: 0.75rem; color: var(--text-secondary); font-weight: 600;">${status}</div>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            `;
                        });

                        htmlContent += `
                                    </div>
                                </div>
                            </div>
                        `;
                    });
                    
                    htmlContent += `
                            </div>
                        </div>
                    `;
                });
                
                container.innerHTML = htmlContent;
            }
            
            // Unified toggle function for Academic Year sections (Official Results)
            function toggleResultsYear(header) {
                const section = header.closest('.year-section');
                const content = section.querySelector('.year-content');
                const icon = header.querySelector('.collapse-btn i');
                
                if (!content) return; // Safety check
                
                // Toggle with smooth animation
                if (content.style.display === 'none' || content.style.display === '') {
                    content.style.display = 'block';
                    setTimeout(() => {
                        icon.style.transform = 'rotate(0deg)';
                    }, 10);
                } else {
                    icon.style.transform = 'rotate(-90deg)';
                    setTimeout(() => {
                        content.style.display = 'none';
                    }, 150);
                }
            }
            
            // Legacy support for old function names
            function toggleSemesterSection(header) {
                toggleResultsSemester(header);
            }
            
            function toggleOfficialSemesterSection(header) {
                toggleResultsSemester(header);
            }
        