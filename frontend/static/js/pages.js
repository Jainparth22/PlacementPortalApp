// page components

const LoginPage = {
    template: `
    <div class="login-page">
        <div class="container">
            <div class="row justify-content-center align-items-center min-vh-100">
                <div class="col-md-5">
                    <div class="card shadow-lg border-0 rounded-4">
                        <div class="card-body p-5">
                            <div class="text-center mb-4">
                                <i class="bi bi-mortarboard-fill text-primary" style="font-size:3rem;"></i>
                                <h2 class="fw-bold mt-2">Placement Portal</h2>
                                <p class="text-muted">Sign in to your account</p>
                            </div>
                            <ul class="nav nav-pills nav-fill mb-4">
                                <li class="nav-item"><a class="nav-link" :class="{active:tab==='login'}" href="#" @click.prevent="tab='login'">Login</a></li>
                                <li class="nav-item"><a class="nav-link" :class="{active:tab==='reg-student'}" href="#" @click.prevent="tab='reg-student'">Student</a></li>
                                <li class="nav-item"><a class="nav-link" :class="{active:tab==='reg-company'}" href="#" @click.prevent="tab='reg-company'">Company</a></li>
                            </ul>
                            <form v-if="tab==='login'" @submit.prevent="$emit('login',loginForm)">
                                <div class="mb-3"><label class="form-label">Email</label><input type="email" class="form-control" v-model="loginForm.email" required></div>
                                <div class="mb-3"><label class="form-label">Password</label><input type="password" class="form-control" v-model="loginForm.password" required></div>
                                <button type="submit" class="btn btn-primary w-100"><i class="bi bi-box-arrow-in-right me-1"></i>Login</button>
                            </form>
                            <form v-if="tab==='reg-student'" @submit.prevent="$emit('register-student',sForm)">
                                <div class="row"><div class="col-md-6 mb-3"><label class="form-label">Full Name *</label><input type="text" class="form-control" v-model="sForm.full_name" required></div><div class="col-md-6 mb-3"><label class="form-label">Email *</label><input type="email" class="form-control" v-model="sForm.email" required></div></div>
                                <div class="mb-3"><label class="form-label">Password *</label><input type="password" class="form-control" v-model="sForm.password" required minlength="6"></div>
                                <div class="row"><div class="col-md-4 mb-3"><label class="form-label">Department</label><select class="form-select" v-model="sForm.department"><option value="">Select</option><option v-for="d in depts" :value="d">{{d}}</option></select></div><div class="col-md-4 mb-3"><label class="form-label">CGPA</label><input type="number" class="form-control" v-model="sForm.cgpa" step="0.01" min="0" max="10"></div><div class="col-md-4 mb-3"><label class="form-label">Grad Year</label><input type="number" class="form-control" v-model="sForm.graduation_year" min="2020" max="2030"></div></div>
                                <div class="mb-3"><label class="form-label">Phone</label><input type="tel" class="form-control" v-model="sForm.phone"></div>
                                <button type="submit" class="btn btn-success w-100"><i class="bi bi-person-plus me-1"></i>Register</button>
                            </form>
                            <form v-if="tab==='reg-company'" @submit.prevent="$emit('register-company',cForm)">
                                <div class="mb-3"><label class="form-label">Company Name *</label><input type="text" class="form-control" v-model="cForm.company_name" required></div>
                                <div class="row"><div class="col-md-6 mb-3"><label class="form-label">Email *</label><input type="email" class="form-control" v-model="cForm.email" required></div><div class="col-md-6 mb-3"><label class="form-label">Password *</label><input type="password" class="form-control" v-model="cForm.password" required minlength="6"></div></div>
                                <div class="row"><div class="col-md-6 mb-3"><label class="form-label">HR Name</label><input type="text" class="form-control" v-model="cForm.hr_name"></div><div class="col-md-6 mb-3"><label class="form-label">Industry</label><input type="text" class="form-control" v-model="cForm.industry"></div></div>
                                <div class="row"><div class="col-md-6 mb-3"><label class="form-label">Website</label><input type="url" class="form-control" v-model="cForm.website"></div><div class="col-md-6 mb-3"><label class="form-label">HR Phone</label><input type="tel" class="form-control" v-model="cForm.hr_phone"></div></div>
                                <div class="mb-3"><label class="form-label">Description</label><textarea class="form-control" v-model="cForm.description" rows="2"></textarea></div>
                                <button type="submit" class="btn btn-primary w-100"><i class="bi bi-building-add me-1"></i>Register</button>
                            </form>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>`,
    data() {
        return {
            tab: 'login',
            loginForm: { email: '', password: '' },
            sForm: { full_name: '', email: '', password: '', department: '', cgpa: '', graduation_year: '', phone: '' },
            cForm: { company_name: '', email: '', password: '', hr_name: '', hr_phone: '', website: '', industry: '', description: '' },
            depts: ['CSE', 'ECE', 'EEE', 'ME', 'CE', 'IT', 'BT', 'CHE']
        };
    },
    emits: ['login', 'register-student', 'register-company']
};

const AdminDashboard = {
    props: ['stats', 'pendingCompanies', 'pendingDrives'],
    emits: ['approve-company', 'reject-company', 'approve-drive', 'reject-drive'],
    template: `
    <div class="container-fluid py-4">
        <h3 class="fw-bold mb-4"><i class="bi bi-speedometer2 me-2"></i>Admin Dashboard</h3>
        <div class="row g-3 mb-4">
            <div class="col-md-3" v-for="s in statCards" :key="s.key"><div class="card stat-card border-0 shadow-sm h-100"><div class="card-body text-center"><i :class="s.icon" class="stat-icon"></i><h2 class="fw-bold mb-0">{{stats[s.key]||0}}</h2><small class="text-muted">{{s.label}}</small></div></div></div>
        </div>
        <div class="row g-3">
            <div class="col-md-6"><div class="card border-0 shadow-sm"><div class="card-header bg-warning-subtle"><i class="bi bi-building me-2"></i>Pending Companies</div><div class="card-body"><p v-if="!pendingCompanies.length" class="text-muted mb-0">None</p><div v-for="c in pendingCompanies" :key="c.id" class="d-flex justify-content-between align-items-center mb-2 p-2 bg-light rounded"><div><strong>{{c.company_name}}</strong><br><small class="text-muted">{{c.email}}</small></div><div><button class="btn btn-sm btn-success me-1" @click="$emit('approve-company',c.id)"><i class="bi bi-check"></i></button><button class="btn btn-sm btn-danger" @click="$emit('reject-company',c.id)"><i class="bi bi-x"></i></button></div></div></div></div></div>
            <div class="col-md-6"><div class="card border-0 shadow-sm"><div class="card-header bg-info-subtle"><i class="bi bi-briefcase me-2"></i>Pending Drives</div><div class="card-body"><p v-if="!pendingDrives.length" class="text-muted mb-0">None</p><div v-for="d in pendingDrives" :key="d.id" class="d-flex justify-content-between align-items-center mb-2 p-2 bg-light rounded"><div><strong>{{d.drive_name}}</strong><br><small class="text-muted">{{d.company_name}}</small></div><div><button class="btn btn-sm btn-success me-1" @click="$emit('approve-drive',d.id)"><i class="bi bi-check"></i></button><button class="btn btn-sm btn-danger" @click="$emit('reject-drive',d.id)"><i class="bi bi-x"></i></button></div></div></div></div></div>
        </div>
    </div>`,
    data() {
        return {
            statCards: [
                { key: 'total_students', icon: 'bi bi-people text-primary stat-icon', label: 'Students' },
                { key: 'total_companies', icon: 'bi bi-building text-success stat-icon', label: 'Companies' },
                { key: 'total_drives', icon: 'bi bi-briefcase text-warning stat-icon', label: 'Drives' },
                { key: 'total_applications', icon: 'bi bi-file-earmark-text text-info stat-icon', label: 'Applications' }
            ]
        };
    }
};

const AdminTable = {
    props: ['title', 'icon', 'columns', 'items', 'searchable'],
    emits: ['search', 'action'],
    template: `
    <div class="container-fluid py-4">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h3 class="fw-bold"><i :class="icon" class="me-2"></i>{{title}}</h3>
            <div v-if="searchable" class="input-group" style="max-width:300px;"><input type="text" class="form-control" placeholder="Search..." v-model="q" @input="$emit('search',q)"><button class="btn btn-outline-primary" @click="$emit('search',q)"><i class="bi bi-search"></i></button></div>
            <slot name="filter"></slot>
        </div>
        <div class="table-responsive"><table class="table table-hover align-middle"><thead class="table-dark"><tr><th v-for="c in columns" :key="c.key">{{c.label}}</th></tr></thead><tbody><slot name="rows"></slot><tr v-if="!items||!items.length"><td :colspan="columns.length" class="text-center text-muted">No data</td></tr></tbody></table></div>
    </div>`,
    data() { return { q: '' }; }
};

const DriveCard = {
    props: ['drive'],
    emits: ['apply'],
    template: `
    <div class="card border-0 shadow-sm drive-card h-100">
        <div class="card-body">
            <div class="d-flex justify-content-between"><h6 class="fw-bold">{{drive.drive_name}}</h6><span class="badge bg-success">{{drive.job_type||'Full-time'}}</span></div>
            <p class="text-muted small mb-1"><i class="bi bi-building me-1"></i>{{drive.company_name}}</p>
            <p class="text-muted small mb-1"><i class="bi bi-geo-alt me-1"></i>{{drive.location||'Remote'}} Â· <i class="bi bi-cash me-1"></i>{{drive.salary||'Not disclosed'}}</p>
            <p class="text-muted small mb-2"><i class="bi bi-clock me-1"></i>Deadline: {{drive.application_deadline?new Date(drive.application_deadline).toLocaleDateString():'Open'}}</p>
            <p class="small mb-2">Min CGPA: {{drive.min_cgpa||'None'}} Â· Branch: {{drive.eligibility_branch||'All'}}</p>
            <button class="btn btn-sm btn-primary w-100" @click="$emit('apply',drive.id)"><i class="bi bi-send me-1"></i>Apply</button>
        </div>
    </div>`
};

