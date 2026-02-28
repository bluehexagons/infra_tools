# Deployment Safety Features

This document describes the safety features built into the infra_tools deployment system to protect production data during Rails application deployments.

## Automatic Database Backups

### Overview

When deploying Rails applications with existing databases, the deployment system automatically creates timestamped backups before running database migrations. This provides a safety net in case migrations fail or cause data corruption.

### How It Works

1. **Detection**: Before running migrations, the system checks if:
   - A production database already exists (`db/production.sqlite3`)
   - There are pending migrations to run

2. **Backup Creation**: If both conditions are true, a timestamped backup is created:
   - Location: `/var/www/.infra_tools_shared/<app_name>/backups/`
   - Format: `<app_name>_production_YYYYMMDD_HHMMSS.sqlite3`
   - Verification: Backup size is checked to ensure it's not empty

3. **Migration**: Migrations proceed only after successful backup

4. **Cleanup**: Old backups are automatically removed, keeping the 10 most recent

### Example Output

```
Deploying to /var/www/clicker_bluehexagons_com...
  Building Rails project...
  Setting up database...
  Pending migrations detected, creating backup before migration...
  Creating database backup: clicker_production_20260217_143022.sqlite3
  ✓ Backup created successfully (2.34 MB)
  Running database migrations...
  ✓ Migrations completed successfully
  ℹ Removed 3 old backup(s), keeping 10 most recent
```

### Backup Location

Backups are stored in the persistent shared directory:

```
/var/www/.infra_tools_shared/<app_name>/backups/
  ├── app_production_20260217_143022.sqlite3
  ├── app_production_20260216_091533.sqlite3
  └── app_production_20260215_182401.sqlite3
```

### Manual Backup Access

To list available backups:

```bash
sudo ls -lh /var/www/.infra_tools_shared/*/backups/
```

To restore from a backup:

```bash
# Stop the Rails service
sudo systemctl stop rails-<app_name>.service

# Restore the backup
sudo cp /var/www/.infra_tools_shared/<app_name>/backups/<backup_file> \
       /var/www/.infra_tools_shared/<app_name>/db/production.sqlite3

# Restart the service
sudo systemctl start rails-<app_name>.service
```

## Intelligent Seed Safety

### Problem Solved

Previously, `db:seed` ran on **every deployment** if `db/seeds.rb` existed, which could:
- Overwrite user data
- Reset passwords
- Create duplicate records
- Corrupt production databases

### New Behavior: Smart Idempotency Detection

The deployment system now **analyzes seed files** to determine if they're safe to run:

#### ✅ Seeds Run When:
1. **New database** (no production.sqlite3 exists) - Always safe
2. **Idempotent seeds on existing database** - Safe patterns detected:
   - `find_or_create_by` / `find_or_create_by!`
   - `find_or_initialize_by`
   - `first_or_create` / `first_or_initialize`

#### ❌ Seeds Skipped When:
- **Non-idempotent seeds on existing database** - Dangerous patterns detected:
  - `create!` / `create(` without find_or_create
  - `.delete_all` / `.destroy_all`
  - `truncate`

### Example Output

**Idempotent Seeds (SAFE - runs on existing DB):**
```ruby
# db/seeds.rb
User.find_or_create_by!(username: 'admin') do |user|
  user.email = 'admin@example.com'
  user.password = SecureRandom.hex(12)
  user.admin = true
end
```

```
Setting up database...
Pending migrations detected, creating backup before migration...
✓ Backup created successfully (2.34 MB)
Running database migrations...
✓ Migrations completed successfully
✓ Running standard seeds (idempotent - safe for existing database)
  Reason: Uses idempotent patterns (find_or_create_by, etc.)
Admin user created
✓ Rails project built
```

**Non-Idempotent Seeds (SKIPPED on existing DB):**
```ruby
# db/seeds.rb
User.create!(username: 'admin', password: 'password')  # NOT SAFE
```

```
Setting up database...
Running database migrations...
✓ Migrations completed successfully
⚠ Skipping standard seeds (existing database - seeds may not be idempotent)
  Reason: Uses create! which may fail on duplicates
ℹ To run seeds manually if safe:
  cd /var/www/app && RAILS_ENV=production ... bundle exec rake db:seed
✓ Rails project built
```

**New Database (seeds always run):**
```
Setting up database...
Running database migrations...
✓ Migrations completed successfully
New database detected, running seeds...
✓ Rails project built
```

### Environment-Specific Seed Files

You can create environment-specific seed files that are automatically detected:

#### File Priority (checked in order):

1. `db/seeds/production_seeds.rb` (highest priority for production)
2. `db/production_seeds.rb`
3. `db/seeds.rb` (fallback/standard)

#### Example Structure:

```
your-rails-app/
├── db/
│   ├── seeds/
│   │   ├── production_seeds.rb    # Production-only seeds
│   │   ├── development_seeds.rb   # Dev-only (not used in prod)
│   │   └── test_seeds.rb         # Test-only (not used in prod)
│   └── seeds.rb                   # Fallback if no env-specific file
```

#### Creating Production-Specific Seeds:

```ruby
# db/seeds/production_seeds.rb
# Only essential data needed for production

# Create default admin (idempotent)
admin = User.find_or_create_by!(username: 'admin') do |user|
  password = SecureRandom.hex(16)
  user.email = 'admin@example.com'
  user.password = password
  user.password_confirmation = password
  user.admin = true
  
  puts "="*50
  puts "ADMIN USER CREATED"
  puts "Username: admin"
  puts "Password: #{password}"
  puts "Please save this password!"
  puts "="*50
end

# Essential categories (idempotent)
['Security', 'General', 'Support'].each do |name|
  Category.find_or_create_by!(name: name)
end
```

```ruby
# db/seeds/development_seeds.rb
# Lots of test data for local development

100.times do |i|
  User.create!(
    username: "user#{i}",
    email: "user#{i}@example.com",
    password: "password"
  )
end

# This file is NEVER used in production
```

### Writing Idempotent Seeds

#### ✅ Good Patterns (Idempotent):

```ruby
# Using find_or_create_by
User.find_or_create_by!(email: 'admin@example.com') do |user|
  user.username = 'admin'
  user.password = SecureRandom.hex(12)
end

# Using first_or_create
Category.where(name: 'General').first_or_create!(
  description: 'General category'
)

# Using find_or_initialize + conditional save
user = User.find_or_initialize_by(email: 'admin@example.com')
if user.new_record?
  user.username = 'admin'
  user.password = SecureRandom.hex(12)
  user.save!
end

# Array with find_or_create
['Action', 'Comedy', 'Drama'].each do |genre_name|
  MovieGenre.find_or_create_by!(name: genre_name)
end
```

#### ❌ Bad Patterns (NOT Idempotent):

```ruby
# Direct create - fails on second run
User.create!(email: 'admin@example.com', password: 'secret')

# Destructive operations
User.delete_all  # DELETES ALL USERS!
User.destroy_all
User.where(admin: false).delete_all

# These will cause issues on subsequent deployments
```

### Manual Seeding

If you need to run seeds manually on an existing production database:

```bash
cd /var/www/<app_directory>
sudo -u rails RAILS_ENV=production bundle exec rake db:seed
```

**WARNING**: Only run seeds manually if:
1. You have a current backup
2. You've verified seeds are idempotent
3. You understand what the seeds will do

## Migration Schema Conflicts

### The Problem: Squashed or Reset Migrations

When you squash migrations or reset your migration history in development, Rails on the server may still think the old individual migrations were run. This causes errors like:

```
ActiveRecord::StatementInvalid: table "users" already exists
```

This happens because:
1. **Old deployment**: Had migrations `20240101_create_users.rb`, `20240102_add_email.rb`
2. **Database remembers**: "I ran migrations 20240101, 20240102"
3. **New deployment**: You squashed into `20240105_initial_schema.rb` that creates users table
4. **Rails sees**: "20240105 hasn't been run yet, let me run it!"
5. **Migration fails**: "Table 'users' already exists"

### The Solution: --reset-migrations Flag

Use the `--reset-migrations` flag to reload the schema and mark all migrations as run:

```bash
./setup_server_web.py <host> \
  --deploy clicker.bluehexagons.com https://github.com/user/repo.git \
  --reset-migrations
```

### What --reset-migrations Does

1. **Creates a backup** (if database exists and has data)
2. **Loads current schema** from `db/schema.rb` using `rake db:schema:load`
3. **Marks all migrations as run** in the `schema_migrations` table
4. **Runs any new migrations** that are newer than the schema
5. **Preserves all data** (no tables are dropped)

### When to Use --reset-migrations

Use this flag when:
- ✅ You've squashed or reset migrations in your repository
- ✅ You're getting "table already exists" or "column already exists" errors
- ✅ The database schema is correct but migration history is out of sync
- ✅ You're migrating from a different migration structure

**DO NOT use this flag when:**
- ❌ This is a fresh deployment (first time deploying the app)
- ❌ Migrations are running normally
- ❌ You want to run specific migrations (use manual migration commands instead)

### Automatic Error Detection

The deployment system automatically detects migration schema conflicts and provides instructions:

```
✗ Migration failed: Schema conflict detected

This typically happens when:
  • Migrations were squashed or reset in the repository
  • The database schema is out of sync with migration history

To fix this, redeploy with the --reset-migrations flag:
  ./setup_server_web.py <host> --deploy <deploy-spec> <git-url> --reset-migrations

⚠ WARNING: --reset-migrations will:
  • Load the current schema from db/schema.rb
  • Mark all migrations as already run
  • Preserve your data (tables won't be dropped)

ℹ Database backup is available in: /var/www/.infra_tools_shared/<app_name>/backups/
```

### Example: Fixing a Squashed Migration Error

**Before (error):**
```bash
$ ./setup_server_web.py myserver.com --deploy app.example.com https://github.com/user/app.git

Deploying to /var/www/app_example_com...
  Running database migrations...
  ✗ Migration failed: table "users" already exists
```

**After (fixed):**
```bash
$ ./setup_server_web.py myserver.com --deploy app.example.com https://github.com/user/app.git --reset-migrations

Deploying to /var/www/app_example_com...
  Resetting database schema (--reset-migrations flag used)...
  ⚠ This will load the current schema and mark all migrations as run
  Creating database backup: app_production_20260217_153045.sqlite3
  ✓ Backup created successfully (2.34 MB)
  ✓ Schema loaded successfully
  Running any new migrations...
  ✓ Migrations completed successfully
```

## Migration Failure Handling

### Automatic Rollback Information

If a migration fails, the deployment system provides clear information about the backup:

```
Running database migrations...
✗ Migration failed: StandardError: ...
ℹ Database backup is available in: /var/www/.infra_tools_shared/<app_name>/backups/
```

### Manual Rollback Steps

1. **Stop the Rails service**:
   ```bash
   sudo systemctl stop rails-<app_name>.service
   ```

2. **Restore from backup**:
   ```bash
   sudo cp /var/www/.infra_tools_shared/<app_name>/backups/<most_recent_backup> \
          /var/www/.infra_tools_shared/<app_name>/db/production.sqlite3
   ```

3. **Rollback the migration** (if needed):
   ```bash
   cd /var/www/<app_directory>
   sudo -u rails RAILS_ENV=production bundle exec rake db:rollback
   ```

4. **Restart the service**:
   ```bash
   sudo systemctl start rails-<app_name>.service
   ```

## Persistent State Management

### Database Location

Production databases are stored in a persistent location that survives redeployments:

```
/var/www/.infra_tools_shared/<app_name>/
  ├── db/
  │   └── production.sqlite3      # Persistent database
  ├── backups/                     # Automatic backups
  │   └── <app>_production_*.sqlite3
  ├── storage/                     # Active Storage files
  ├── log/                         # Rails logs
  └── public/
      ├── uploads/                 # User uploads
      └── system/                  # Attachment files
```

### Symlink Architecture

Each deployment creates symlinks from the release directory to the persistent storage:

```
/var/www/<app_name>/              # Release directory (changes on deploy)
  ├── db/
  │   └── production.sqlite3 -> /var/www/.infra_tools_shared/<app_name>/db/production.sqlite3
  ├── storage/ -> /var/www/.infra_tools_shared/<app_name>/storage/
  ├── log/ -> /var/www/.infra_tools_shared/<app_name>/log/
  └── public/
      ├── uploads/ -> /var/www/.infra_tools_shared/<app_name>/public/uploads/
      └── system/ -> /var/www/.infra_tools_shared/<app_name>/public/system/
```

This ensures:
- Database survives code redeployments
- User-uploaded files persist
- Logs are preserved
- Rails state is maintained

## Best Practices

### Before Deploying Updates

1. **Test migrations locally** against a copy of production data:
   ```bash
   # Download production database
   scp user@server:/var/www/.infra_tools_shared/<app>/db/production.sqlite3 ./
   
   # Test migrations locally
   RAILS_ENV=development bundle exec rake db:migrate
   ```

2. **Ensure seeds are idempotent**:
   ```ruby
   # Good: idempotent seeding
   User.find_or_create_by(email: 'admin@example.com') do |user|
     user.password = SecureRandom.hex(32)
   end
   
   # Bad: creates duplicates
   User.create!(email: 'admin@example.com', password: '...')
   ```

3. **Consider environment-specific seeds**:
   - Create `db/seeds/production_seeds.rb` for production-only data
   - Keep `db/seeds.rb` for development/test data
   - The system automatically uses the right file

4. **Check for destructive migrations**:
   - Dropping columns
   - Removing tables
   - Changing data types (with data loss)

### During Deployment

1. **Monitor the deployment output** for warnings
2. **Check backup creation confirmation**
3. **Verify migrations succeed**
4. **Test the application** immediately after deployment

### After Deployment

1. **Verify application functionality**:
   ```bash
   curl https://yourdomain.com/
   sudo systemctl status rails-<app_name>.service
   ```

2. **Check logs** for errors:
   ```bash
   sudo journalctl -u rails-<app_name>.service -n 50
   tail -f /var/www/.infra_tools_shared/<app_name>/log/production.log
   ```

3. **Keep recent backups** for at least a few days

## Configuration

### Backup Retention

The system keeps the 10 most recent backups by default. To change this, you would need to modify the deployment code.

### Disabling Automatic Backups

Automatic backups cannot be disabled (this is by design for safety). If you need to skip backups for testing:

1. Deploy to a test environment first
2. Use `--dry-run` to preview changes
3. Test locally before deploying to production

## Troubleshooting

### Backup Failed Warning

If you see:
```
⚠ WARNING: Failed to create database backup before migration!
⚠ Migration will proceed, but consider stopping and backing up manually.
```

**Action**: Stop the deployment and create a manual backup:
```bash
sudo cp /var/www/.infra_tools_shared/<app>/db/production.sqlite3 \
       ~/manual_backup_$(date +%Y%m%d_%H%M%S).sqlite3
```

### No Backups Directory

If backups directory doesn't exist, it's created automatically on first backup. No action needed.

### Disk Space Issues

If backups fail due to disk space:

1. **Check available space**:
   ```bash
   df -h /var/www
   ```

2. **Clean old backups manually**:
   ```bash
   sudo find /var/www/.infra_tools_shared/*/backups/ -name "*.sqlite3" -mtime +30 -delete
   ```

3. **Monitor backup size**:
   ```bash
   du -sh /var/www/.infra_tools_shared/*/backups/
   ```

## Security Considerations

### Backup Permissions

Backups are created with the same permissions as the database:
- Owner: `rails:rails` (or configured web user)
- Permissions: `664` (owner and group can read/write)

### Sensitive Data

Backups contain the full production database, including:
- User passwords (hashed)
- Personal information
- API keys/secrets stored in database

**Best practices**:
- Restrict access to backup directory
- Include backups in encryption-at-rest strategy
- Exclude from public backups/syncs
- Consider backup retention policies for compliance

## Related Documentation

- [CI/CD System](CICD.md) - Continuous deployment integration
- [Storage Operations](../sync/README.md) - Data integrity and backup systems (see `sync/` module)
- [Logging](../lib/logging_utils.py) - Troubleshooting and monitoring (see `lib/logging_utils.py`)

## Summary

The deployment system provides multiple layers of protection:

✅ **Automatic backups** before migrations  
✅ **Backup verification** ensures data integrity  
✅ **Smart seeding** prevents data corruption  
✅ **Persistent storage** survives redeployments  
✅ **Clear error messages** with recovery instructions  
✅ **Automatic cleanup** manages disk space  

These features make Rails deployments safer and more reliable for production environments.
