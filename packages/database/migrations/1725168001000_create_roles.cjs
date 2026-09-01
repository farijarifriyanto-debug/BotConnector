/**
 * Migration: Create database roles
 * - migration_owner: owns schema objects, runs migrations
 * - application_role: runtime role, NOSUPERUSER, NOBYPASSRLS
 */
exports.up = (pgm) => {
  pgm.createRole('migration_owner', {
    login: false,
    superuser: false,
    bypassrls: false,
    createDb: false,
    inherit: true,
  });

  pgm.createRole('application_role', {
    login: false,
    superuser: false,
    bypassrls: false,
    createDb: false,
    inherit: true,
  });

  // Grant schema usage to application_role
  const schemas = [
    'iam', 'core', 'design', 'memory', 'work',
    'ai', 'change', 'validation', 'build', 'resource',
    'deploy', 'event', 'security', 'ops'
  ];
  for (const schema of schemas) {
    pgm.sql(`GRANT USAGE ON SCHEMA ${schema} TO application_role`);
    pgm.sql(`GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ${schema} TO application_role`);
    pgm.sql(`ALTER DEFAULT PRIVILEGES IN SCHEMA ${schema} GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO application_role`);
    pgm.sql(`GRANT USAGE ON ALL SEQUENCES IN SCHEMA ${schema} TO application_role`);
    pgm.sql(`ALTER DEFAULT PRIVILEGES IN SCHEMA ${schema} GRANT USAGE ON SEQUENCES TO application_role`);
  }
};

exports.down = (pgm) => {
  pgm.dropRole('application_role', { ifExists: true });
  pgm.dropRole('migration_owner', { ifExists: true });
};
