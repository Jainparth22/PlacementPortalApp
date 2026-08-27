// Placement Portal - Vue 3 SPA
const API = '';

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
            token: localStorage.getItem('ppa_token') || '',
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

        // api helper
        async api(url, method = 'GET', body = null) {
            const opts = {
                method,
                headers: {},
            };
            if (this.token) opts.headers['Authorization'] = `Bearer ${this.token}`;
            if (body) {
                opts.headers['Content-Type'] = 'application/json';
                opts.body = JSON.stringify(body);
            }

            try {
                const res = await fetch(API + url, opts);
                const data = await res.json();
                if (!res.ok) {
                    this.showAlert(data.error || 'Request failed', 'danger');
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
                localStorage.setItem('ppa_token', res.token);
                localStorage.setItem('ppa_user', JSON.stringify(res.user));
                if (res.profile) {
                    if (res.user.role === 'company') this.companyProfile = res.profile;
                    if (res.user.role === 'student') this.studentProfile = res.profile;
                }
                this.showAlert('Welcome back!', 'success');
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
            try { await this.api('/api/auth/logout', 'POST'); } catch (e) { /* ignore */ }
            this.token = '';
            this.user = {};
            this.isLoggedIn = false;
            localStorage.removeItem('ppa_token');
            localStorage.removeItem('ppa_user');
            this.currentPage = 'login';
            this.showAlert('Logged out', 'info');
        },

        // notifications
        async loadNotifications() {
            const n = await this.api('/api/notifications');
            if (n) {
                this.notifications = n;
                this.unreadNotifications = n.filter(x => !x.is_read).length;
            }
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
                const resp = await fetch(`/api/admin/reports/download/${id}`, {
                    headers: { 'Authorization': `Bearer ${this.token}` }
                });
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
            const res = await this.api('/api/admin/reports/generate', 'POST');
            if (res) {
                this.showAlert('Report generation started! Will download when ready...', 'info');
                if (res.job_id) {
                    // poll the job for completion
                    const pollReport = async () => {
                        const job = await this.api(`/api/jobs/${res.job_id}`);
                        if (job && job.status === 'completed') {
                            this.showAlert('Report ready! Downloading...', 'success');
                            await this.loadReports();
                            await this.loadNotifications();
                            // download the latest report
                            if (this.reports.length) {
                                await this.downloadReport(this.reports[0].id);
                            }
                        } else if (job && job.status !== 'failed') {
                            setTimeout(pollReport, 3000);
                        } else {
                            this.showAlert('Report generation failed.', 'danger');
                        }
                    };
                    setTimeout(pollReport, 2000);
                }
            }
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
            this.atsLoading = true;
            const modal = new bootstrap.Modal(document.getElementById('atsModal'));
            modal.show();
            const res = await this.api('/api/student/ats-check', 'POST', { drive_id: driveId });
            this.atsLoading = false;
            if (res) {
                this.atsResult = res.result;
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
                const res = await fetch(API + '/api/students/upload-resume', {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${this.token}` },
                    body: fd,
                });
                const data = await res.json();
                if (res.ok) this.showAlert('Resume uploaded!', 'success');
                else this.showAlert(data.error || 'Upload failed', 'danger');
            } catch (e) { this.showAlert('Upload error', 'danger'); }
        },
        async exportCSV() {
            const res = await this.api('/api/student/export-applications', 'POST');
            if (res) {
                this.showAlert('Export started! You will be notified when ready.', 'info');
                if (res.job_id) this.pollJob(res.job_id);
            }
        },
        async pollJob(jobId) {
            const poll = async () => {
                const job = await this.api(`/api/jobs/${jobId}`);
                if (job && job.status === 'completed') {
                    this.showAlert('Export ready! Downloading...', 'success');
                    await this.loadNotifications();
                    // trigger browser download with auth token
                    try {
                        const resp = await fetch(`/api/student/download-export/${jobId}`, {
                            headers: { 'Authorization': `Bearer ${this.token}` }
                        });
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
                } else if (job && job.status !== 'failed') {
                    setTimeout(poll, 3000);
                } else {
                    this.showAlert('Export failed. Please try again.', 'danger');
                }
            };
            setTimeout(poll, 2000);
        },
    },
    async mounted() {
        // restore dark mode
        if (this.darkMode) {
            document.documentElement.setAttribute('data-theme', 'dark');
        }
        if (this.token && this.user.id) {
            // verify token is still valid
            try {
                const res = await this.api('/api/auth/me');
                if (res && res.user) {
                    this.user = res.user;
                    localStorage.setItem('ppa_user', JSON.stringify(res.user));
                    this.isLoggedIn = true;
                    this.navigate('dashboard');
                } else {
                    // token expired or invalid
                    this.token = '';
                    localStorage.removeItem('ppa_token');
                    localStorage.removeItem('ppa_user');
                }
            } catch (e) {
                this.isLoggedIn = true;
                this.navigate('dashboard');
            }
        }
    }
});

app.mount('#app');
