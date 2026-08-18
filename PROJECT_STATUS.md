# Project Status: Quant Energy Trading App

**Last Updated**: 2026-08-18 (Poniedziałek)  
**Current Phase**: Migration to GitHub + Supabase Auth System Setup

---

## ✅ Completed (Poniedziałek)

### 1. GitHub Repository
- [x] Repo created: `https://github.com/radonis/quan.energy`
- [x] `.gitignore` configured (secrets, data, cache)
- [x] Initial commit with 142 files
- [x] Security audit: removed credentials from CLAUDE.md
- [x] Created CLAUDE_LOCAL.md (credentials backup - local only)
- [x] Documentation: `github_rollout_manual.txt` with security policy

### 2. Supabase Setup
- [x] New project created: `quan-energy`
- [x] Tables created with RLS enabled:
  - `users` (id, email, password_hash, created_at)
  - `user_roles` (id, user_id, role, created_at)
  - `module_access` (id, user_id, module_name, created_at)
- [x] `.streamlit/secrets.toml` created (local, gitignored)
- [x] Project URL and Anon Key secured

### 3. Project Structure
- [x] `page_modules/auth.py` - scaffolding (TODO implementation)
- [x] `page_modules/permissions.py` - scaffolding (TODO implementation)
- [x] `page_modules/admin.py` - replaced with new version (backup: admin_old.py)

---

## 📋 In Progress (Wtorek)

### Task 2: Auth Integration
- [ ] **2.1: page_modules/auth.py** (3h)
  - `hash_password()` - SHA256 hashing
  - `register()` - new user registration
  - `login()` - user authentication
  - `get_user_role()` - fetch user role from Supabase
  - `render_login_page()` - Streamlit UI with login/register tabs

- [ ] **2.2: page_modules/permissions.py** (1h)
  - `has_access()` - check module access
  - `get_available_modules()` - list user modules
  - `check_permission()` - decorator for access control

- [ ] **2.3: app.py modifications** (1h)
  - Add auth check on startup
  - Sidebar: user info + logout button
  - Dynamic module selector based on permissions

- [ ] **2.4: .streamlit/secrets.toml** (done)
  - Supabase credentials stored locally

---

## 🎯 Next Steps (Środa+)

### Task 3: Admin Panel (Środa)
- [ ] **3.1: page_modules/admin.py** (3h)
  - TAB 1: User management (list, delete)
  - TAB 2: Module access assignment
  - TAB 3: Role management (viewer/trader/admin)

### Task 4: Testing & Deploy (Czwartek)
- [ ] Local testing (login/register/access/admin)
- [ ] Streamlit Cloud deployment
- [ ] Create test users (admin, trader, viewer)

### Task 5: Documentation (Piątek)
- [ ] SETUP.md for developers
- [ ] README.md update
- [ ] Final testing
- [ ] GitHub release (v1.0-auth)

---

## 🔐 Security Status

| Component | Status | Notes |
|-----------|--------|-------|
| GitHub repo | ✅ Safe | No credentials exposed, admin_old.py ignored |
| CLAUDE.md | ✅ Safe | Sanitized, credentials in CLAUDE_LOCAL.md only |
| .streamlit/secrets.toml | ✅ Safe | Local only, in .gitignore |
| Supabase | ✅ Secure | RLS enabled on all tables |
| .gitignore | ✅ Updated | Backs up data, caches, credentials excluded |

---

## 📊 Available Modules (for module_access table)

```
Coal, Forecast, Forward Market, OTF EE, OTF Gas,
ETS, CDS, CCS, Prices, FixTrade, TSOTrade
```

---

## 🔗 Key Resources

- **GitHub**: https://github.com/radonis/quan.energy
- **Supabase Project**: quan-energy (credentials in `.streamlit/secrets.toml`)
- **Local Secrets**: `C:\Users\rlucz\OneDrive\Pulpit\Data\Aplikacja\.streamlit\secrets.toml`
- **Private Docs**: `CLAUDE_LOCAL.md` (not on GitHub)
- **Security Guide**: `github_rollout_manual.txt`

---

## 📅 Timeline

| Day | Tasks | Status |
|-----|-------|--------|
| Pn (8/18) | GitHub + Supabase + Structure | ✅ DONE |
| Wt (8/19) | Auth Integration | ⏳ TODO |
| Śr (8/20) | Admin Panel | ⏳ TODO |
| Cz (8/21) | Testing & Deploy | ⏳ TODO |
| Pt (8/22) | Docs & Release | ⏳ TODO |

---

## 🚀 Start of Day Checklist (Wtorek)

- [ ] Review this PROJECT_STATUS.md
- [ ] Verify `.streamlit/secrets.toml` exists locally
- [ ] Verify Supabase project is accessible
- [ ] Start with Task 2.1: auth.py implementation
- [ ] End with `git push` of completed code

