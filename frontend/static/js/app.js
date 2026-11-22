// Placement Portal - Vue 3 SPA
const API = '';
const API_PREFIX = '/api/v1';   // versioned API; unversioned /api/* still works but is deprecated

const { createApp } = Vue;

const app = createApp({
    delimiters: ['${', '}'],
    data() {
        return {
            // UI state
            sidebarOpen: false,
            darkMode: localStorage.getItem('ppa_darkmode') === '1',

            // Auth
            currentPage: 'login',
            isLoggedIn: false,
            token: '',                       // access token: JS memory only (never localStorage); renewed via httpOnly refresh cookie
            liveStatus: 'off',               // off | live | polling   (server-sent events for notifications)
            user: JSON.parse(localStorage.getItem('ppa_user') || '{}'),
            loading: false,
            alert: { show: false, type: 'success', message: '' },

            // Notifications
            notifications: [],
            unreadNotifications: 0,

            // Login/Register forms
            loginTab: 'login',
            loginForm: { email: '', password: '' },
            sRegForm: { full_name: '', email: '', password: '', department: '', cgpa: '', graduation_year: '', phone: '' },
            cRegForm: { company_name: '', email: '', password: '', hr_name: '', hr_phone: '', website: '', industry: '', description: '' },

            // Demo accounts — verified from backend/SampleDataSeed.py:373 and sample_test_data.md:5
            demoAccounts: {
                admin: { email: 'jainparth7040@gmail.com', password: 'admin123', label: 'Admin' },
                company1: { email: 'hr@technova.com', password: 'Tech@123', label: 'TechNova (Company)' },
                company2: { email: 'careers@greenleaf.com', password: 'Green@123', label: 'GreenLeaf (Company)' },
                students: [
                    { email: 'rahul.verma@student.com', password: 'Rahul@123', name: 'Rahul Verma — CSE 8.5', badge: 'HIGH SDE' },
                    { email: 'kavya.nair@student.com', password: 'Kavya@123', name: 'Kavya Nair — CSE 9.1', badge: 'STAR' },
                    { email: 'rohan.joshi@student.com', password: 'Rohan@123', name: 'Rohan Joshi — IT 7.8', badge: 'Backend' },
                    { email: 'sneha.patel@student.com', password: 'Sneha@123', name: 'Sneha Patel — IT 7.2', badge: 'Analyst' },
                    { email: 'arjun.mehta@student.com', password: 'Arjun@123', name: 'Arjun Mehta — ECE 6.8', badge: 'IoT' },
                ]
            },

            // Admin
            adminStats: {},
            adminApplications: [],
            adminAppStatusFilter: '',
            pendingCompanies: [],
            pendingDrives: [],
            companies: [],
            adminDrives: [],
            students: [],
            reports: [],
            searchQuery: '',
            driveStatusFilter: '',
            selectedAdminDrive: null,
            adminDriveApplications: [],
            // Pagination meta — mirrors backend/pagination.py
            pg: {
                adminCompanies: { page: 1, per_page: 6, total: 0, pages: 1 },
                adminDrives: { page: 1, per_page: 6, total: 0, pages: 1 },
                adminStudents: { page: 1, per_page: 6, total: 0, pages: 1 },
                adminApplications: { page: 1, per_page: 6, total: 0, pages: 1 },
                adminReports: { page: 1, per_page: 6, total: 0, pages: 1 },
                adminDriveApps: { page: 1, per_page: 6, total: 0, pages: 1 },
                companyDrives: { page: 1, per_page: 6, total: 0, pages: 1 },
                companyApps: { page: 1, per_page: 6, total: 0, pages: 1 },
                companyInterviews: { page: 1, per_page: 6, total: 0, pages: 1 },
                studentDrives: { page: 1, per_page: 6, total: 0, pages: 1 },
                studentApps: { page: 1, per_page: 6, total: 0, pages: 1 },
                studentInterviews: { page: 1, per_page: 6, total: 0, pages: 1 },
                studentHistory: { page: 1, per_page: 6, total: 0, pages: 1 },
            },

            // Company
            companyProfile: null,
            companyDashboard: {},
            companyDrives: [],
            driveApplications: [],
            driveInterviews: [],
            showDriveForm: false,
            editingDriveId: null,
            driveForm: { drive_name: '', job_title: '', job_description: '', eligibility_branch: '', min_cgpa: '', eligible_year: '', application_deadline: '', location: '', salary: '', job_type: 'Full-time' },
            companyProfileForm: {},

            // Student
            studentProfile: null,
            approvedDrives: [],
            myApplications: [],
            placementHistory: [],
            myInterviews: [],
            atsResult: null,
            atsLoading: false,
            atsFallback: false,
            atsRetryMinutes: 10,
            reportGenerating: false,
            exportGenerating: false,
            studentProfileForm: {},
            skillsInput: '',
            driveSearch: '',
            branchFilter: '',
            selectedDrive: null,

            // Interview
            interviewForm: { interview_date: '', mode: 'Online', venue: '' },
            interviewAppId: null,

            // Lists
            departments: ['CSE', 'ECE', 'EEE', 'ME', 'CE', 'IT', 'BT', 'CHE'],
            adminStatCards: {
                total_students: { label: 'Total Students', icon: 'bi bi-people text-primary', class: '' },
                total_companies: { label: 'Total Companies', icon: 'bi bi-building text-success', class: '' },
                total_drives: { label: 'Total Drives', icon: 'bi bi-briefcase text-warning', class: '' },
                total_applications: { label: 'Applications', icon: 'bi bi-file-earmark-text text-info', class: '' },
                selected_students: { label: 'Selections', icon: 'bi bi-trophy text-danger', class: '' },
                pending_companies: { label: 'Pending Companies', icon: 'bi bi-hourglass text-secondary', class: '' },
                pending_drives: { label: 'Pending Drives', icon: 'bi bi-clock text-dark', class: '' },
                blacklisted_users: { label: 'Blacklisted', icon: 'bi bi-shield-x text-danger', class: '' },
            },


        };
    },
    computed: {
        pageTitle() {
            const titles = {
                'dashboard': 'Dashboard',
                'admin-companies': 'Companies',
                'admin-drives': 'Placement Drives',
                'admin-drive-detail': 'Drive Details',
                'admin-students': 'Students',
                'admin-applications': 'Applications',
                'admin-reports': 'Reports',
                'company-drives': 'My Drives',
                'company-profile': 'Company Profile',
                'company-drive-applications': 'Drive Applications',
                'student-drives': 'Browse Drives',
                'student-drive-detail': 'Drive Details',
                'student-applications': 'My Applications',
                'student-interviews': 'Interviews',
                'student-history': 'Placement History',
                'student-profile': 'My Profile',
            };
            return titles[this.currentPage] || 'Placement Portal';
        }
    },
    methods: {
        // toggle dark/light
        toggleTheme() {
            this.darkMode = !this.darkMode;
            document.documentElement.setAttribute('data-theme', this.darkMode ? 'dark' : 'light');
            localStorage.setItem('ppa_darkmode', this.darkMode ? '1' : '0');
        },

        // /api/x -> /api/v1/x
        v1(url) {
            return url.startsWith('/api/') && !url.startsWith(API_PREFIX + '/') ? API_PREFIX + url.slice(4) : url;
        },

        // ---- session handling -------------------------------------------------------------------------
        csrfToken() {
            const m = document.cookie.match(/(?:^|;\s*)ppa_csrf=([^;]+)/);
            return m ? decodeURIComponent(m[1]) : '';
        },
        // One refresh at a time per tab (the server also tolerates two tabs racing).
        refreshAccessToken() {
            if (this._refreshing) return this._refreshing;
            this._refreshing = (async () => {
                try {
                    const res = await fetch(API + API_PREFIX + '/auth/refresh', {
                        method: 'POST', headers: { 'X-CSRF-Token': this.csrfToken() }, credentials: 'same-origin',
                    });
                    if (!res.ok) return false;
                    const data = await res.json();
                    this.token = data.token;
                    this.user = data.user;
                    localStorage.setItem('ppa_user', JSON.stringify(data.user));   // non-sensitive profile hint only
                    if (data.profile) {
                        if (data.user.role === 'company') this.companyProfile = data.profile;
                        if (data.user.role === 'student') this.studentProfile = data.profile;
                    }
                    this.scheduleRefresh(data.expires_in);
                    return true;
                } catch (e) { return false; } finally { this._refreshing = null; }
            })();
            return this._refreshing;
        },
        scheduleRefresh(expiresIn) {            // renew at ~80% of the access-token lifetime
            clearTimeout(this._refreshTimer);
            this._refreshTimer = setTimeout(() => this.isLoggedIn && this.refreshAccessToken(), Math.max(30, (expiresIn || 900) * 0.8) * 1000);
        },
        sessionExpired() {
            this.stopLiveNotifications();
            this.token = ''; this.user = {}; this.isLoggedIn = false;
            localStorage.removeItem('ppa_user');
            this.currentPage = 'login';
            this.showAlert('Your session expired. Please log in again.', 'warning');
        },
        newIdempotencyKey() {
            return (window.crypto && crypto.randomUUID) ? crypto.randomUUID()
                : 'k-' + Date.now() + '-' + Math.random().toString(16).slice(2);
        },
        // fetch with Authorization + one transparent refresh-and-retry on 401 (used for downloads/uploads too)
        async authFetch(url, opts = {}, retried = false) {
            const headers = { ...(opts.headers || {}) };
            if (this.token) headers['Authorization'] = `Bearer ${this.token}`;
            const res = await fetch(API + this.v1(url), { ...opts, headers });
            if (res.status === 401 && !retried && this.isLoggedIn && !url.includes('/auth/')) {
                if (await this.refreshAccessToken()) return this.authFetch(url, opts, true);
                this.sessionExpired();
            }
            return res;
        },

        // api helper (JSON). POSTs carry an Idempotency-Key, reused on the post-refresh retry.
        async api(url, method = 'GET', body = null) {
            const headers = {};
            if (body) headers['Content-Type'] = 'application/json';
            if (method === 'POST' && !url.includes('/auth/')) headers['Idempotency-Key'] = this.newIdempotencyKey();
            if (url.endsWith('/auth/logout')) headers['X-CSRF-Token'] = this.csrfToken();
            try {
                const res = await this.authFetch(url, { method, headers, body: body ? JSON.stringify(body) : undefined });
                const data = await res.json();
                if (!res.ok) {
                    if (res.status === 401 && !this.isLoggedIn) { this.showAlert(data.error || 'Request failed', 'danger'); return null; }
                    if (res.status !== 401 || url.includes('/auth/login')) this.showAlert(data.error || 'Request failed', 'danger');
                    return null;
                }
                return data;
            } catch (e) {
                this.showAlert('Network error: ' + e.message, 'danger');
                return null;
            }
        },

        showAlert(message, type = 'success') {
            this.alert = { show: true, type, message };
            setTimeout(() => { this.alert.show = false; }, 4000);
        },

        formatDate(d) {
            if (!d) return '-';
            return new Date(d).toLocaleDateString() + ' ' + new Date(d).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        },

        statusBadge(status) {
            const m = { pending: 'badge bg-warning text-dark', approved: 'badge bg-success', rejected: 'badge bg-danger', closed: 'badge bg-secondary', applied: 'badge bg-primary', shortlisted: 'badge bg-info', selected: 'badge bg-success', withdrawn: 'badge bg-dark' };
            return m[status] || 'badge bg-secondary';
        },

        // pagination helper — unwraps {items, total, pages} or legacy array
        unwrapPaginated(res, pgKey) {
            if (!res) return [];
            if (Array.isArray(res)) return res;
            if (res.items && Array.isArray(res.items)) {
                if (pgKey && this.pg[pgKey]) {
                    this.pg[pgKey].total = res.total || 0;
                    this.pg[pgKey].pages = res.pages || 1;
                    this.pg[pgKey].page = res.page || 1;
                    this.pg[pgKey].per_page = res.per_page || 6;
                }
                return res.items;
            }
            return [];
        },
        goPage(pgKey, delta) {
            const pg = this.pg[pgKey];
            if (!pg) return;
            const np = pg.page + delta;
            if (np < 1 || np > pg.pages) return;
            pg.page = np;
            // route to correct loader
            const loaders = {
                adminCompanies: () => this.loadPageData('admin-companies'),
                adminDrives: () => this.loadAdminDrives(),
                adminStudents: () => this.loadPageData('admin-students'),
                adminApplications: () => this.loadAdminApplications(),
                adminReports: () => this.loadReports(),
                companyDrives: () => this.loadCompanyDrives(),
                companyApps: () => this.viewDriveApplications(this._lastCompanyDriveId),
                studentDrives: () => this.loadStudentDrives(),
                studentApps: () => this.loadMyApplications(),
                studentInterviews: () => this.loadMyInterviews(),
                studentHistory: () => this.loadPageData('student-history'),
            };
            if (loaders[pgKey]) loaders[pgKey]();
        },

        // navigation
        navigate(page) {
            this.currentPage = page;
            this.loadPageData(page);
        },

        // form validation
        validateForm(event) {
            const form = event.target;
            if (!form.checkValidity()) {
                event.stopPropagation();
                form.classList.add('was-validated');
                return false;
            }
            form.classList.add('was-validated');
            return true;
        },

        // chart rendering
        renderAdminCharts() {
            if (typeof Chart === 'undefined') return;
            // Application Status Doughnut
            const appCtx = document.getElementById('appStatusChart');
            if (appCtx && this.adminStats.chart_app_status) {
                if (this._appChart) this._appChart.destroy();
                const d = this.adminStats.chart_app_status;
                this._appChart = new Chart(appCtx, {
                    type: 'doughnut',
                    data: {
                        labels: ['Applied', 'Shortlisted', 'Selected', 'Rejected', 'Withdrawn'],
                        datasets: [{ data: [d.applied, d.shortlisted, d.selected, d.rejected, d.withdrawn], backgroundColor: ['#0d6efd', '#0dcaf0', '#198754', '#dc3545', '#6c757d'] }]
                    },
                    options: { responsive: true, plugins: { legend: { position: 'bottom' } } }
                });
            }
            // Drive Status Bar
            const driveCtx = document.getElementById('driveStatusChart');
            if (driveCtx && this.adminStats.chart_drive_status) {
                if (this._driveChart) this._driveChart.destroy();
                const d = this.adminStats.chart_drive_status;
                this._driveChart = new Chart(driveCtx, {
                    type: 'bar',
                    data: {
                        labels: ['Pending', 'Approved', 'Rejected', 'Closed'],
                        datasets: [{ label: 'Drives', data: [d.pending, d.approved, d.rejected, d.closed], backgroundColor: ['#ffc107', '#198754', '#dc3545', '#6c757d'] }]
                    },
                    options: { responsive: true, scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } }, plugins: { legend: { display: false } } }
                });
            }
        },

        async loadPageData(page) {
            this.loading = true;
            try {
                if (page === 'dashboard') {
                    if (this.user.role === 'admin') {
                        const stats = await this.api('/api/admin/dashboard');
                        if (stats) {
                            this.adminStats = stats;
                            this.$nextTick(() => this.renderAdminCharts());
                        }
                        const pc = await this.api('/api/admin/companies/pending');
                        if (pc) this.pendingCompanies = pc;
                        const pd = await this.api('/api/admin/drives/pending');
                        if (pd) this.pendingDrives = pd;
                    } else if (this.user.role === 'company') {
                        const d = await this.api('/api/company/dashboard');
                        if (d) { this.companyDashboard = d; this.companyProfile = d.company; }
                    } else if (this.user.role === 'student') {
                        await this.loadStudentDrives();
                        await this.loadMyApplications();
                    }
                } else if (page === 'admin-companies') {
                    const pg = this.pg.adminCompanies;
                    const c = await this.api(`/api/admin/companies?page=${pg.page}&per_page=${pg.per_page}`);
                    this.companies = this.unwrapPaginated(c, 'adminCompanies');
                } else if (page === 'admin-drives') {
                    await this.loadAdminDrives();
                } else if (page === 'admin-students') {
                    const pg = this.pg.adminStudents;
                    const s = await this.api(`/api/admin/students?page=${pg.page}&per_page=${pg.per_page}`);
                    this.students = this.unwrapPaginated(s, 'adminStudents');
                } else if (page === 'admin-drive-detail') {
                    // data loaded by viewAdminDriveDetail
                } else if (page === 'admin-applications') {
                    await this.loadAdminApplications();
                } else if (page === 'admin-reports') {
                    await this.loadReports();
                } else if (page === 'company-drives') {
                    this.pg.companyDrives.page = this.pg.companyDrives.page || 1;
                    await this.loadCompanyDrives();
                } else if (page === 'company-profile') {
                    const p = await this.api('/api/companies/profile');
                    if (p) { this.companyProfile = p; this.companyProfileForm = { ...p }; }
                } else if (page === 'student-drives') {
                    await this.loadStudentDrives();
                } else if (page === 'student-applications') {
                    await this.loadMyApplications();
                } else if (page === 'student-history') {
                    const pg = this.pg.studentHistory;
                    const h = await this.api(`/api/student/history?page=${pg.page}&per_page=${pg.per_page}`);
                    this.placementHistory = this.unwrapPaginated(h, 'studentHistory');
                } else if (page === 'student-interviews') {
                    await this.loadMyInterviews();
                } else if (page === 'student-profile') {
                    const p = await this.api('/api/students/profile');
                    if (p) { this.studentProfile = p; this.studentProfileForm = { ...p }; this.skillsInput = (p.skills || []).join(', '); }
                }
                await this.loadNotifications();
            } finally {
                this.loading = false;
            }
        },

        // auth
        async doLogin(event) {
            const form = event.target;
            if (!form.checkValidity()) { form.classList.add('was-validated'); return; }
            this.loading = true;
            const res = await this.api('/api/auth/login', 'POST', this.loginForm);
            this.loading = false;
            if (res) {
                this.token = res.token;
                this.user = res.user;
                this.isLoggedIn = true;
                localStorage.setItem('ppa_user', JSON.stringify(res.user));   // non-sensitive hint; the token stays in memory
                this.scheduleRefresh(res.expires_in);
                if (res.profile) {
                    if (res.user.role === 'company') this.companyProfile = res.profile;
                    if (res.user.role === 'student') this.studentProfile = res.profile;
                }
                this.showAlert('Welcome back!', 'success');
                this.startLiveNotifications();
                this.navigate('dashboard');
            }
        },

        async registerStudent(event) {
            const form = event.target;
            if (!form.checkValidity()) { form.classList.add('was-validated'); return; }
            this.loading = true;
            const res = await this.api('/api/students/register', 'POST', this.sRegForm);
            this.loading = false;
            if (res) {
                this.showAlert('Registration successful! Please login.', 'success');
                this.loginTab = 'login';
                this.currentPage = 'login';
            }
        },

        async registerCompany(event) {
            const form = event.target;
            if (!form.checkValidity()) { form.classList.add('was-validated'); return; }
            this.loading = true;
            const res = await this.api('/api/companies/register', 'POST', this.cRegForm);
            this.loading = false;
            if (res) {
                this.showAlert('Company registered! Awaiting admin approval. Please login.', 'success');
                this.loginTab = 'login';
                this.currentPage = 'login';
            }
        },

        fillDemo(account) {
            // one-click demo fill — verified against backend/SampleDataSeed.py:373
            this.loginTab = 'login';
            this.loginForm.email = account.email;
            this.loginForm.password = account.password;
            this.showAlert(`Filled ${account.label || account.name} — click Login`, 'info');
        },
        copyDemo(text) {
            navigator.clipboard.writeText(text).then(() => this.showAlert('Copied to clipboard', 'success'));
        },
        async logout() {
            this.stopLiveNotifications();
            clearTimeout(this._refreshTimer);
            try { await this.api('/api/auth/logout', 'POST'); } catch (e) { /* ignore */ }
            this.token = '';
            this.user = {};
            this.isLoggedIn = false;
            localStorage.removeItem('ppa_user');
            localStorage.removeItem('ppa_token');      // legacy key from older versions
            this.currentPage = 'login';
            this.showAlert('Logged out', 'info');
        },

        // notifications -------------------------------------------------------------------------------
        async loadNotifications() {
            const n = await this.api('/api/notifications');
            if (n) {
                const items = Array.isArray(n) ? n : (n.items || []);
                this.notifications = items;
                this.unreadNotifications = items.filter(x => !x.is_read).length;
            }
        },
        // Live notifications via Server-Sent Events. EventSource can't send an Authorization header, so we read
        // the SSE stream with fetch(). The server stamps each event with a stream id; on reconnect we send
        // Last-Event-ID so nothing is missed. If the stream is unavailable we fall back to polling.
        startLiveNotifications() {
            this.stopLiveNotifications();
            this._liveAbort = new AbortController();
            this._liveBackoff = 1000;
            this._liveLoop(this._liveAbort.signal);
        },
        stopLiveNotifications() {
            if (this._liveAbort) this._liveAbort.abort();
            this._liveAbort = null;
            clearInterval(this._pollTimer);
            this.liveStatus = 'off';
        },
        async _liveLoop(signal) {
            while (!signal.aborted && this.isLoggedIn) {
                try {
                    const headers = {};
                    if (this._lastEventId) headers['Last-Event-ID'] = this._lastEventId;
                    const res = await this.authFetch('/api/notifications/stream', { headers, signal });
                    if (!res.ok || !res.body) throw new Error('stream unavailable: ' + res.status);
                    this.liveStatus = 'live';
                    clearInterval(this._pollTimer);
                    this._liveBackoff = 1000;
                    await this._readSSE(res.body, signal);
                    if (!signal.aborted) continue;          // server ended the stream normally (max duration): reconnect right away
                } catch (e) {
                    if (signal.aborted) return;
                }
                if (signal.aborted) return;
                // degraded: poll while we retry the stream with exponential backoff (max 30s)
                this.liveStatus = 'polling';
                clearInterval(this._pollTimer);
                this._pollTimer = setInterval(() => this.isLoggedIn && this.loadNotifications(), 30000);
                await new Promise(r => setTimeout(r, this._liveBackoff));
                this._liveBackoff = Math.min(this._liveBackoff * 2, 30000);
            }
        },
        async _readSSE(body, signal) {
            const reader = body.getReader();
            const decoder = new TextDecoder();
            let buf = '';
            while (!signal.aborted) {
                const { done, value } = await reader.read();
                if (done) return;
                buf += decoder.decode(value, { stream: true });
                let idx;
                while ((idx = buf.indexOf('\n\n')) >= 0) {
                    const block = buf.slice(0, idx);
                    buf = buf.slice(idx + 2);
                    this._handleSSEBlock(block);
                }
            }
        },
        _handleSSEBlock(block) {
            let event = 'message', id = null, data = '';
            for (const line of block.split('\n')) {
                if (line.startsWith(':')) continue;                       // keep-alive comment
                if (line.startsWith('event:')) event = line.slice(6).trim();
                else if (line.startsWith('id:')) id = line.slice(3).trim();
                else if (line.startsWith('data:')) data += line.slice(5).trim();
            }
            if (id) this._lastEventId = id;
            if (event === 'notification' && data) {
                try { this._onLiveNotification(JSON.parse(data)); } catch (e) { /* ignore malformed */ }
            }
        },
        _onLiveNotification(n) {
            if (this.notifications.some(x => x.id === n.id)) return;      // at-least-once delivery => dedupe by id
            this.notifications = [n, ...this.notifications].slice(0, 50);
            if (!n.is_read) this.unreadNotifications += 1;
            this.showAlert(n.message, 'info');
        },
        async markRead(id) {
            await this.api(`/api/notifications/${id}/read`, 'PUT');
            await this.loadNotifications();
        },
        async markAllRead() {
            await this.api('/api/notifications/read-all', 'PUT');
            await this.loadNotifications();
        },

        // admin actions
        async approveCompany(id) {
            const res = await this.api(`/api/admin/companies/${id}/approve`, 'PUT');
            if (res) { this.showAlert('Company approved!', 'success'); this.loadPageData(this.currentPage); }
        },
        async rejectCompany(id) {
            const res = await this.api(`/api/admin/companies/${id}/reject`, 'PUT', { remarks: 'Rejected by admin' });
            if (res) { this.showAlert('Company rejected', 'warning'); this.loadPageData(this.currentPage); }
        },
        async toggleBlacklistCompany(c) {
            const action = c.is_blacklisted ? 'unblacklist' : 'blacklist';
            const res = await this.api(`/api/admin/companies/${c.id}/blacklist`, 'PUT', { action });
            if (res) { this.showAlert(res.message, 'success'); this.loadPageData(this.currentPage); }
        },
        async approveDrive(id) {
            const res = await this.api(`/api/admin/drives/${id}/approve`, 'PUT');
            if (res) { this.showAlert('Drive approved!', 'success'); this.loadPageData(this.currentPage); }
        },
        async rejectDrive(id) {
            const res = await this.api(`/api/admin/drives/${id}/reject`, 'PUT', { remarks: 'Rejected by admin' });
            if (res) { this.showAlert('Drive rejected', 'warning'); this.loadPageData(this.currentPage); }
        },
        async closeDrive(id) {
            const res = await this.api(`/api/admin/drives/${id}/close`, 'PUT');
            if (res) { this.showAlert('Drive closed', 'info'); this.loadPageData(this.currentPage); }
        },
        async loadAdminDrives() {
            const pg = this.pg.adminDrives;
            const base = this.driveStatusFilter ? `/api/admin/drives?status=${this.driveStatusFilter}&` : '/api/admin/drives?';
            const url = `${base}page=${pg.page}&per_page=${pg.per_page}`;
            const d = await this.api(url);
            this.adminDrives = this.unwrapPaginated(d, 'adminDrives');
        },
        async viewAdminDriveDetail(drive) {
            this.selectedAdminDrive = drive;
            const pg = this.pg.adminDriveApps;
            const apps = await this.api(`/api/admin/applications?drive_id=${drive.id}&page=${pg.page}&per_page=${pg.per_page}`);
            this.adminDriveApplications = this.unwrapPaginated(apps, 'adminDriveApps');
            this.currentPage = 'admin-drive-detail';
        },
        async toggleDeactivateStudent(s) {
            const action = s.is_active ? 'deactivate' : 'activate';
            const res = await this.api(`/api/admin/students/${s.id}/deactivate`, 'PUT', { action });
            if (res) { this.showAlert(res.message, 'success'); this.loadPageData(this.currentPage); }
        },
        async toggleBlacklistStudent(s) {
            const action = s.is_blacklisted ? 'unblacklist' : 'blacklist';
            const res = await this.api(`/api/admin/students/${s.id}/blacklist`, 'PUT', { action });
            if (res) { this.showAlert(res.message, 'success'); this.loadPageData(this.currentPage); }
        },
        async loadReports() {
            const pg = this.pg.adminReports;
            const r = await this.api(`/api/admin/reports/monthly?page=${pg.page}&per_page=${pg.per_page}`);
            this.reports = this.unwrapPaginated(r, 'adminReports');
        },
        async downloadReport(id) {
            try {
                const resp = await this.authFetch(`/api/admin/reports/download/${id}`);
                if (resp.ok) {
                    const blob = await resp.blob();
                    const url = window.URL.createObjectURL(blob);
                    const link = document.createElement('a');
                    link.href = url;
                    link.download = `report_${id}.pdf`;
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                    window.URL.revokeObjectURL(url);
                } else {
                    this.showAlert('Report file not found', 'danger');
                }
            } catch (e) { this.showAlert('Download failed', 'danger'); }
        },
        async loadAdminApplications() {
            const pg = this.pg.adminApplications;
            let url = `/api/admin/applications?page=${pg.page}&per_page=${pg.per_page}`;
            if (this.adminAppStatusFilter) url += '&status=' + this.adminAppStatusFilter;
            const a = await this.api(url);
            this.adminApplications = this.unwrapPaginated(a, 'adminApplications');
        },
        async searchAdmin(type) {
            if (!this.searchQuery.trim()) { this.loadPageData(this.currentPage); return; }
            const res = await this.api(`/api/admin/search?q=${encodeURIComponent(this.searchQuery)}&type=${type}`);
            if (res) {
                if (type === 'companies') this.companies = res.companies || [];
                if (type === 'students') this.students = res.students || [];
            }
        },
        async generateReport() {
            if (this.reportGenerating) return;
            // Optimistic feedback: tell the user immediately instead of blocking on a spinner.
            this.reportGenerating = true;
            this.showAlert("Report generation started! We'll notify you when it's ready.", 'info');
            const res = await this.api('/api/admin/reports/generate', 'POST');
            if (!res || !res.job_id) { this.reportGenerating = false; return; }
            const pollReport = async () => {
                const job = await this.api(`/api/jobs/${res.job_id}`);
                if (job && job.status === 'completed') {
                    this.reportGenerating = false;
                    this.showAlert('Report ready! Downloading...', 'success');
                    await this.loadReports();
                    await this.loadNotifications();
                    if (this.reports.length) await this.downloadReport(this.reports[0].id);
                } else if (job && job.status !== 'failed') {
                    setTimeout(pollReport, 3000);
                } else {
                    this.reportGenerating = false;
                    this.showAlert('Report generation failed. It was sent to the dead-letter queue for review.', 'danger');
                }
            };
            // ran inline (no worker)? it is already finished - poll right away
            setTimeout(pollReport, res.mode === 'sync' ? 0 : 2000);
        },

        // company actions
        async loadCompanyDrives() {
            const pg = this.pg.companyDrives;
            const d = await this.api(`/api/company/drives?page=${pg.page}&per_page=${pg.per_page}`);
            this.companyDrives = this.unwrapPaginated(d, 'companyDrives');
        },
        resetDriveForm() {
            this.editingDriveId = null;
            this.driveForm = { drive_name: '', job_title: '', job_description: '', eligibility_branch: '', min_cgpa: '', eligible_year: '', application_deadline: '', location: '', salary: '', job_type: 'Full-time' };
        },
        editDrive(drive) {
            this.editingDriveId = drive.id;
            this.driveForm = {
                drive_name: drive.drive_name || '',
                job_title: drive.job_title || '',
                job_description: drive.job_description || '',
                eligibility_branch: drive.eligibility_branch || '',
                min_cgpa: drive.min_cgpa || '',
                eligible_year: drive.eligible_year || '',
                application_deadline: drive.application_deadline ? drive.application_deadline.slice(0, 16) : '',
                location: drive.location || '',
                salary: drive.salary || '',
                job_type: drive.job_type || 'Full-time',
            };
            this.showDriveForm = true;
        },
        async saveDrive() {
            this.loading = true;
            let res;
            if (this.editingDriveId) {
                res = await this.api(`/api/company/drives/${this.editingDriveId}`, 'PUT', this.driveForm);
            } else {
                res = await this.api('/api/company/drives', 'POST', this.driveForm);
            }
            this.loading = false;
            if (res) {
                this.showAlert(this.editingDriveId ? 'Drive updated!' : 'Drive created! Awaiting admin approval.', 'success');
                this.showDriveForm = false;
                this.resetDriveForm();
                await this.loadCompanyDrives();
            }
        },
        async deleteDrive(id) {
            if (!confirm('Delete this drive?')) return;
            const res = await this.api(`/api/company/drives/${id}`, 'DELETE');
            if (res) { this.showAlert('Drive deleted', 'success'); await this.loadCompanyDrives(); }
        },
        async loadDriveInterviews(driveId) {
            const pg = this.pg.companyInterviews;
            const interviews = await this.api(`/api/company/drives/${driveId}/interviews?page=${pg.page}&per_page=${pg.per_page}`);
            this.driveInterviews = this.unwrapPaginated(interviews, 'companyInterviews');
            if (this.driveInterviews.length) this.$nextTick(() => window.scrollTo(0, document.body.scrollHeight));
        },
        async viewDriveApplications(id) {
            this._lastCompanyDriveId = id;
            const pg = this.pg.companyApps;
            const a = await this.api(`/api/company/drives/${id}/applications?page=${pg.page}&per_page=${pg.per_page}`);
            this.driveApplications = this.unwrapPaginated(a, 'companyApps');
            this.currentPage = 'company-drive-applications';
        },
        async updateAppStatus(id, status) {
            if (!status) return;
            const res = await this.api(`/api/company/applications/${id}/status`, 'PUT', { status });
            if (res) { this.showAlert('Status updated', 'success'); this.viewDriveApplications(this.driveApplications[0]?.drive_id); }
        },
        async updateCompanyProfile() {
            this.loading = true;
            const res = await this.api('/api/companies/profile', 'PUT', this.companyProfileForm);
            this.loading = false;
            if (res) { this.showAlert('Profile updated!', 'success'); this.companyProfile = res.company; }
        },
        scheduleInterview(appId) {
            this.interviewAppId = appId;
            this.interviewForm = { interview_date: '', mode: 'Online', venue: '' };
            const modal = new bootstrap.Modal(document.getElementById('interviewModal'));
            modal.show();
        },
        async submitInterview() {
            const res = await this.api(`/api/company/applications/${this.interviewAppId}/schedule-interview`, 'POST', this.interviewForm);
            if (res) {
                this.showAlert('Interview scheduled!', 'success');
                bootstrap.Modal.getInstance(document.getElementById('interviewModal')).hide();
            }
        },

        // student actions
        async loadStudentDrives() {
            const pg = this.pg.studentDrives;
            let url = `/api/student/drives?page=${pg.page}&per_page=${pg.per_page}`;
            if (this.driveSearch) url += `&search=${encodeURIComponent(this.driveSearch)}`;
            if (this.branchFilter) url += `&branch=${encodeURIComponent(this.branchFilter)}`;
            const d = await this.api(url);
            this.approvedDrives = this.unwrapPaginated(d, 'studentDrives');
        },
        async viewDriveDetail(id) {
            const drive = await this.api(`/api/student/drives/${id}`);
            if (drive) {
                this.selectedDrive = drive;
                this.currentPage = 'student-drive-detail';
            }
        },
        async loadMyApplications() {
            const pg = this.pg.studentApps;
            const a = await this.api(`/api/student/applications?page=${pg.page}&per_page=${pg.per_page}`);
            this.myApplications = this.unwrapPaginated(a, 'studentApps');
        },
        async applyForDrive(driveId) {
            const res = await this.api(`/api/student/apply/${driveId}`, 'POST', {});
            if (res) { this.showAlert('Application submitted!', 'success'); await this.loadMyApplications(); await this.loadStudentDrives(); }
        },
        async withdrawApplication(id) {
            if (!confirm('Withdraw this application?')) return;
            const res = await this.api(`/api/student/applications/${id}/withdraw`, 'PUT');
            if (res) { this.showAlert('Application withdrawn', 'info'); await this.loadMyApplications(); }
        },
        async checkATS(driveId) {
            this.atsResult = null;
            this.atsFallback = false;
            this.atsLoading = true;
            const modal = new bootstrap.Modal(document.getElementById('atsModal'));
            modal.show();
            const res = await this.api('/api/student/ats-check', 'POST', { drive_id: driveId });
            this.atsLoading = false;
            if (res) {
                this.atsResult = res.result;
                this.atsFallback = !!res.fallback;
                this.atsRetryMinutes = res.retry_after_minutes || 10;
            }
        },
        async loadMyInterviews() {
            const pg = this.pg.studentInterviews;
            const i = await this.api(`/api/student/interviews?page=${pg.page}&per_page=${pg.per_page}`);
            this.myInterviews = this.unwrapPaginated(i, 'studentInterviews');
        },
        async updateInterviewResult(id, result) {
            const res = await this.api(`/api/company/applications/${id}/interview-result`, 'PUT', { result });
            if (res) {
                this.showAlert(`Interview marked as ${result}`, 'success');
                if (this.driveApplications.length) {
                    this.viewDriveApplications(this.driveApplications[0]?.drive_id);
                }
            }
        },
        async updateStudentProfile() {
            this.loading = true;
            const data = { ...this.studentProfileForm };
            if (this.skillsInput) data.skills = this.skillsInput.split(',').map(s => s.trim()).filter(Boolean);
            const res = await this.api('/api/students/profile', 'PUT', data);
            this.loading = false;
            if (res) { this.showAlert('Profile updated!', 'success'); this.studentProfile = res.student; }
        },
        async uploadResume(event) {
            const file = event.target.files[0];
            if (!file) return;
            const fd = new FormData();
            fd.append('resume', file);
            try {
                const res = await this.authFetch('/api/students/upload-resume', { method: 'POST', body: fd });
                const data = await res.json();
                if (res.ok) this.showAlert('Resume uploaded!', 'success');
                else this.showAlert(data.error || 'Upload failed', 'danger');
            } catch (e) { this.showAlert('Upload error', 'danger'); }
        },
        async exportCSV() {
            if (this.exportGenerating) return;
            this.exportGenerating = true;
            this.showAlert("Export started! We'll notify you when it's ready.", 'info');
            const res = await this.api('/api/student/export-applications', 'POST');
            if (res && res.job_id) await this.pollJob(res.job_id, res.mode === 'sync' ? 0 : 2000);
            else this.exportGenerating = false;
        },
        async pollJob(jobId, firstDelay = 2000) {
            const poll = async () => {
                const job = await this.api(`/api/jobs/${jobId}`);
                if (job && job.status === 'completed') {
                    this.showAlert('Export ready! Downloading...', 'success');
                    await this.loadNotifications();
                    // trigger browser download with auth token
                    try {
                        const resp = await this.authFetch(`/api/student/download-export/${jobId}`);
                        if (resp.ok) {
                            const blob = await resp.blob();
                            const url = window.URL.createObjectURL(blob);
                            const link = document.createElement('a');
                            link.href = url;
                            link.download = 'my_applications.csv';
                            document.body.appendChild(link);
                            link.click();
                            document.body.removeChild(link);
                            window.URL.revokeObjectURL(url);
                        }
                    } catch (e) { console.error('Download failed:', e); }
                    this.exportGenerating = false;
                } else if (job && job.status !== 'failed') {
                    setTimeout(poll, 3000);
                } else {
                    this.exportGenerating = false;
                    this.showAlert('Export failed. Please try again.', 'danger');
                }
            };
            setTimeout(poll, firstDelay);
        },
    },
    async mounted() {
        // restore dark mode
        if (this.darkMode) {
            document.documentElement.setAttribute('data-theme', 'dark');
        }
        localStorage.removeItem('ppa_token');          // legacy: tokens are no longer persisted in JS-readable storage
        if (this.user && this.user.id) {
            // We remember *who* was logged in; the credential itself is the httpOnly refresh cookie.
            this.isLoggedIn = true;
            let ok = false;
            if (await this.refreshAccessToken()) {
                const res = await this.api('/api/auth/me');
                if (res && res.user) {
                    this.user = res.user;
                    this.startLiveNotifications();
                    this.navigate('dashboard');
                    ok = true;
                }
            }
            if (!ok) { this.isLoggedIn = false; this.user = {}; localStorage.removeItem('ppa_user'); }
        }
    }
});

app.mount('#app');
