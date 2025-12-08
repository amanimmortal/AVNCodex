# How to Update AVN Codex on Unraid

## Prerequisites: Merge `dev` to `main`
Since I have been working on the `dev` branch and your Unraid box pulls from `main`, you first need to merge the changes.

### On your Development Machine (VS Code)
Run these commands in your VS Code terminal (or standard terminal) to push the latest changes to the main GitHub repository:

```bash
# 1. Ensure all local changes on dev are added and committed (I have done this)
# 2. Switch to the main branch
git checkout main

# 3. Pull latest main (just in case)
git pull origin main

# 4. Merge the dev branch into main
git merge dev

# 5. Push the updated main branch to GitHub
git push origin main

# 6. Switch back to dev to continue working later
git checkout dev
```

---

## Update Procedure on Unraid

Once you have pushed the `main` branch to GitHub, follow these steps on your Unraid server.

### 1. Open Unraid Terminal
Click the `>_` (Terminal) icon in the top right of your Unraid web interface.

### 2. Navigate to Project Folder
Change directory to where your project is stored. 
*(Adjust the path if you stored it somewhere else)*

```bash
cd /mnt/user/appdata/avncodex
# OR
cd /boot/config/plugins/compose.manager/projects/avncodex
```

### 3. Pull Latest Code
Download the changes you just pushed to `main`.

```bash
git pull origin main
```

### 4. Rebuild and Restart
**Critical Step:** Because the code is copied *inside* the Docker image during build, you must **rebuild** it.

```bash
docker-compose up -d --build
```

### 5. Verify
Check the logs to ensure everything started correctly:

```bash
docker-compose logs -f
```
*(Press `Ctrl + C` to exit logs)*
